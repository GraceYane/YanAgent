"""AgentBridge：统一管理当前单 Agent 的运行实例、任务入口和资源生命周期。"""

from __future__ import annotations

import asyncio
import logging
import threading
import uuid
from collections.abc import Coroutine
from typing import Any, TypeVar

from yanagent.chat import YanAgentApplication
from yanagent.contracts import RunRequest, RunResult
from yanagent.errors import RequestValidationError
from yanagent.events import RunEvent
from yanagent.runtime.streaming import AgentRuntime


LOGGER = logging.getLogger("yanagent.runtime.bridge")
ResultType = TypeVar("ResultType")


class AgentBridge:
    """作为 HTTP 与运行引擎之间的统一门面，负责单 Agent 实例和资源收口。"""

    def __init__(
        self, application: YanAgentApplication, *, retention_seconds: float = 60.0,
    ) -> None:
        """创建当前 local/default 实例缓存，并启动其常驻异步运行环境。"""
        self.application = application
        self._lock = threading.RLock()
        self._closed = False
        self._instances: dict[tuple[str, str], AgentRuntime] = {}
        self._instances[("local", "default")] = AgentRuntime(
            application, retention_seconds=retention_seconds,
        )
        LOGGER.info(
            "[bridge.py][AgentBridge.__init__] Bridge 已启动，实例数=%d，当前身份=local/default",
            len(self._instances),
        )

    @property
    def runtime(self) -> AgentRuntime:
        """返回当前默认运行实例，供现有 HTTP 适配器逐步迁移时兼容使用。"""
        return self._instance_for("local", "default")

    def _instance_for(self, user_id: str, agent_id: str) -> AgentRuntime:
        """从缓存取得运行实例；P05-02 再扩展为按完整身份范围路由。"""
        with self._lock:
            if self._closed:
                raise RuntimeError("AgentBridge 已关闭")
            runtime = self._instances.get((user_id, agent_id))
            if runtime is None:
                field = "user_id" if user_id != "local" else "agent_id"
                raise RequestValidationError(reason="unsupported", field=field)
            return runtime

    async def dispatch(self, request: RunRequest) -> RunResult:
        """校验标准 RunRequest，经唯一实例完成非流式任务并返回标准 RunResult。"""
        request.validate()
        runtime = self._instance_for(request.user_id, request.agent_id)
        request_id = request.request_id or f"run-{uuid.uuid4().hex}"
        payload = {"session_id": request.session_id, "message": request.user_message}
        LOGGER.info(
            "[bridge.py][AgentBridge.dispatch] 接收任务并路由，request_id=%s，user_id=%s，agent_id=%s，session_id=%s",
            request_id, request.user_id, request.agent_id, request.session_id,
        )
        response = await asyncio.to_thread(
            runtime.complete, payload, request_id=request_id,
        )
        result = RunResult(
            content=response["inline_reply"],
            session_id=request.session_id,
            turns=response["turns"],
            usage=response["usage"],
            user_id=request.user_id,
            agent_id=request.agent_id,
            request_id=request_id,
            status="completed",
        )
        result.validate()
        LOGGER.info(
            "[bridge.py][AgentBridge.dispatch] 任务完成，request_id=%s，模型轮数=%d，输出字符数=%d",
            request_id, result.turns, len(result.content),
        )
        return result

    def complete(self, payload: dict[str, Any], *, request_id: str) -> dict[str, Any]:
        """通过 Bridge 默认实例执行非流式聊天，维持桌面 HTTP 响应格式。"""
        return self.runtime.complete(payload, request_id=request_id)

    def start_stream(self, payload: dict[str, Any], *, request_id: str) -> dict[str, Any]:
        """登记流式任务并固定本轮配置快照，返回可订阅的 request_id。"""
        return self.runtime.start_stream(payload, request_id=request_id)

    def execute(
        self, operation: Coroutine[Any, Any, ResultType], *, timeout: float = 10.0,
    ) -> ResultType:
        """把 HTTP 会话控制等协程交给当前实例的常驻事件循环执行。"""
        return self.runtime.execute(operation, timeout=timeout)

    def wait_events(
        self, request_id: str, cursor: int, timeout: float = 15.0,
    ) -> tuple[list[RunEvent], bool] | None:
        """订阅指定 Run 从 cursor 之后的事件，支持晚订阅和断线续读。"""
        return self.runtime.wait_events(request_id, cursor, timeout=timeout)

    def cancel(
        self, *, request_id: str | None = None, session_id: str | None = None,
    ) -> int:
        """将取消请求转发到运行实例，并返回实际接受取消的任务数。"""
        return self.runtime.cancel(request_id=request_id, session_id=session_id)

    def close(self) -> None:
        """幂等关闭 Bridge 中缓存的全部实例，释放任务、事件循环和线程资源。"""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            instances = list(self._instances.values())
            self._instances.clear()
        for runtime in instances:
            runtime.close()
        LOGGER.info(
            "[bridge.py][AgentBridge.close] Bridge 已关闭，释放运行实例数=%d",
            len(instances),
        )
