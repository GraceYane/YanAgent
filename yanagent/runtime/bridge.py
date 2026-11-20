"""AgentBridge：统一管理身份路由、Session 队列和运行资源生命周期。"""

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
from yanagent.sessions import RunStore, SessionStore


LOGGER = logging.getLogger("yanagent.runtime.bridge")
ResultType = TypeVar("ResultType")


class AgentBridge:
    """作为 HTTP 与运行引擎间的统一门面，按身份管理实例并路由任务。"""

    def __init__(
        self, application: YanAgentApplication, *, retention_seconds: float = 60.0,
    ) -> None:
        """初始化单用户默认实例，并记录后续按身份扩展所需的基础配置。"""
        self.application = application
        self.retention_seconds = retention_seconds
        self._lock = threading.RLock()
        self._closed = False
        self._applications: dict[tuple[str, str], YanAgentApplication] = {
            ("local", "default"): application,
        }
        self._instances: dict[tuple[str, str], AgentRuntime] = {
            ("local", "default"): AgentRuntime(
                application, retention_seconds=retention_seconds,
            ),
        }
        LOGGER.info(
            "[bridge.py][AgentBridge.__init__] Bridge 已启动，身份实例数=%d，默认身份=local/default",
            len(self._instances),
        )

    @property
    def runtime(self) -> AgentRuntime:
        """返回默认运行实例，供旧 HTTP 适配器兼容使用。"""
        return self._instance_for("local", "default")

    def _application_for(self, user_id: str, agent_id: str) -> YanAgentApplication:
        """为身份作用域创建独立仓储，复用共享配置、工具和上下文组件。"""
        key = (user_id, agent_id)
        application = self._applications.get(key)
        if application is not None:
            return application
        base_store = self.application.session_store
        if base_store is None:
            raise RequestValidationError(reason="unsupported", field="user_id")
        database = base_store.database
        session_store = SessionStore(database, user_id=user_id, agent_id=agent_id)
        run_store = (
            RunStore(database, user_id=user_id, agent_id=agent_id)
            if self.application.run_store is not None else None
        )
        application = YanAgentApplication(
            self.application.config_store,
            provider_factory=self.application.provider_factory,
            session_store=session_store,
            run_store=run_store,
            tool_manager=self.application.tool_manager,
            context_builder=self.application.context_builder,
        )
        self._applications[key] = application
        return application

    def _instance_for(self, user_id: str, agent_id: str) -> AgentRuntime:
        """使用完整用户和 Agent 标识从缓存取得或创建隔离运行实例。"""
        with self._lock:
            if self._closed:
                raise RuntimeError("AgentBridge 已关闭")
            key = (user_id, agent_id)
            runtime = self._instances.get(key)
            if runtime is not None:
                return runtime
            application = self._application_for(user_id, agent_id)
            runtime = AgentRuntime(
                application, retention_seconds=self.retention_seconds,
            )
            self._instances[key] = runtime
            LOGGER.info(
                "[bridge.py][AgentBridge._instance_for] 创建身份隔离实例，user_id=%s，agent_id=%s，实例数=%d",
                user_id, agent_id, len(self._instances),
            )
            return runtime

    def _existing_instance(self, user_id: str, agent_id: str) -> AgentRuntime | None:
        """只查已有身份实例，避免事件查询或取消请求创建空 Runtime。"""
        with self._lock:
            if self._closed:
                raise RuntimeError("AgentBridge 已关闭")
            return self._instances.get((user_id, agent_id))

    async def dispatch(self, request: RunRequest) -> RunResult:
        """校验标准任务契约，按身份与 Session 排队执行并返回 RunResult。"""
        request.validate()
        runtime = self._instance_for(request.user_id, request.agent_id)
        request_id = request.request_id or f"run-{uuid.uuid4().hex}"
        payload = {"session_id": request.session_id, "message": request.user_message}
        queue_key = (request.user_id, request.agent_id, request.session_id)
        LOGGER.info(
            "[bridge.py][AgentBridge.dispatch] 接收并路由任务，request_id=%s，user_id=%s，agent_id=%s，session_id=%s",
            request_id, request.user_id, request.agent_id, request.session_id,
        )
        response = await asyncio.to_thread(
            runtime.complete, payload, request_id=request_id, queue_key=queue_key,
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

    def complete(
        self,
        payload: dict[str, Any],
        *,
        request_id: str,
        user_id: str = "local",
        agent_id: str = "default",
    ) -> dict[str, Any]:
        """按身份实例和完整 Session 键串行执行非流式聊天。"""
        session_id = payload.get("session_id")
        if type(session_id) is not str or not session_id:
            raise RequestValidationError(reason="invalid", field="session_id")
        runtime = self._instance_for(user_id, agent_id)
        return runtime.complete(
            payload,
            request_id=request_id,
            queue_key=(user_id, agent_id, session_id),
        )

    def start_stream(
        self,
        payload: dict[str, Any],
        *,
        request_id: str,
        user_id: str = "local",
        agent_id: str = "default",
    ) -> dict[str, Any]:
        """按身份作用域登记流任务，并在同一 Session 队列中串行执行。"""
        session_id = payload.get("session_id")
        if type(session_id) is not str or not session_id:
            raise RequestValidationError(reason="invalid", field="session_id")
        runtime = self._instance_for(user_id, agent_id)
        return runtime.start_stream(
            payload,
            request_id=request_id,
            queue_key=(user_id, agent_id, session_id),
        )

    def execute(
        self, operation: Coroutine[Any, Any, ResultType], *, timeout: float = 10.0,
    ) -> ResultType:
        """把 HTTP 会话控制等协程交给默认实例的常驻事件循环执行。"""
        return self.runtime.execute(operation, timeout=timeout)

    def wait_events(
        self,
        request_id: str,
        cursor: int,
        timeout: float = 15.0,
        *,
        user_id: str = "local",
        agent_id: str = "default",
    ) -> tuple[list[RunEvent], bool] | None:
        """只从指定身份实例订阅 Run 事件，避免跨作用域读取。"""
        runtime = self._existing_instance(user_id, agent_id)
        if runtime is None:
            return None
        return runtime.wait_events(request_id, cursor, timeout=timeout)

    def resolve_tool_confirmation(
        self,
        *,
        confirmation_id: str,
        run_id: str,
        approved: bool,
        user_id: str = "local",
        agent_id: str = "default",
    ) -> bool:
        """只向指定身份实例提交与 Run 匹配的一次批准或拒绝。"""
        runtime = self._existing_instance(user_id, agent_id)
        if runtime is None:
            return False
        return runtime.resolve_tool_confirmation(
            confirmation_id=confirmation_id,
            run_id=run_id,
            approved=approved,
        )

    def queue_instruction(
        self,
        *,
        request_id: str,
        session_id: str,
        content: str,
        user_id: str = "local",
        agent_id: str = "default",
    ) -> dict[str, str] | None:
        """把追加指令路由到目标身份的活动 Run，由其安全检查点注入。"""
        runtime = self._existing_instance(user_id, agent_id)
        if runtime is None:
            return None
        return runtime.queue_instruction(
            request_id=request_id,
            session_id=session_id,
            content=content,
        )

    def cancel_with_details(
        self,
        *,
        request_id: str | None = None,
        session_id: str | None = None,
        user_id: str = "local",
        agent_id: str = "default",
    ) -> dict[str, int]:
        """在指定身份实例中取消任务，并区分排队与运行中任务。"""
        runtime = self._existing_instance(user_id, agent_id)
        if runtime is None:
            return {"cancelled": 0, "queued_cancelled": 0, "running_cancelled": 0}
        return runtime.cancel_with_details(request_id=request_id, session_id=session_id)

    def cancel(
        self,
        *,
        request_id: str | None = None,
        session_id: str | None = None,
        user_id: str = "local",
        agent_id: str = "default",
    ) -> int:
        """兼容旧调用方，返回所选身份范围内接受取消的任务总数。"""
        return self.cancel_with_details(
            request_id=request_id,
            session_id=session_id,
            user_id=user_id,
            agent_id=agent_id,
        )["cancelled"]

    def close(self) -> None:
        """幂等关闭全部身份实例，释放排队任务、事件循环和线程资源。"""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            instances = list(self._instances.values())
            self._instances.clear()
            self._applications.clear()
        for runtime in instances:
            runtime.close()
        LOGGER.info(
            "[bridge.py][AgentBridge.close] Bridge 已关闭，释放运行实例数=%d",
            len(instances),
        )
