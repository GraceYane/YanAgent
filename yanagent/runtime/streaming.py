"""P01-05 最小运行时：常驻事件循环、运行隔离、SSE 队列、取消与清理。"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from yanagent.chat import PreparedChat, YanAgentApplication
from yanagent.errors import (
    AgentError, EmptyModelResponseError, ModelResponseError, ModelTimeoutError,
    UnexpectedToolCallError,
)
from yanagent.events import ClientEventType, RunEvent


LOGGER = logging.getLogger("yanagent.runtime")
MAX_RUN_EVENTS = 20_000


@dataclass
class RunRecord:
    """保存单次运行的事件和终态；所有可变字段均由条件锁保护。"""

    request_id: str
    session_id: str
    created_at: float = field(default_factory=time.monotonic)
    _events: list[RunEvent] = field(default_factory=list, repr=False)
    _terminal: bool = field(default=False, repr=False)
    _finished_at: float | None = field(default=None, repr=False)
    _cancel_requested: bool = field(default=False, repr=False)
    _future: concurrent.futures.Future[None] | None = field(default=None, repr=False)
    _condition: threading.Condition = field(default_factory=threading.Condition, repr=False)

    def attach_future(self, future: concurrent.futures.Future[None]) -> None:
        """关联事件循环任务；若取消先到达，则立即把取消传给任务。"""
        with self._condition:
            self._future = future
            should_cancel = self._cancel_requested and not self._terminal
        if should_cancel:
            future.cancel()

    def append(self, event_type: ClientEventType, data: dict[str, Any]) -> RunEvent:
        """原子追加同一 ``request_id`` 的事件，并唤醒全部 SSE 订阅者。"""
        with self._condition:
            if self._terminal:
                raise RuntimeError("终态运行不能继续写入事件")
            if len(self._events) >= MAX_RUN_EVENTS and event_type not in {
                "cancelled", "done", "error",
            }:
                raise ModelResponseError()
            event = RunEvent(
                sequence=len(self._events), request_id=self.request_id,
                type=event_type, data=data,
            )
            self._events.append(event)
            if event.terminal:
                self._terminal = True
                self._finished_at = time.monotonic()
            self._condition.notify_all()
            return event

    def wait(self, cursor: int, timeout: float) -> tuple[list[RunEvent], bool]:
        """阻塞等待 cursor 之后的新事件；用于 HTTP 线程桥接异步生产者。"""
        with self._condition:
            if cursor < 0 or cursor > len(self._events):
                raise ValueError("SSE cursor 超出事件范围")
            if cursor == len(self._events) and not self._terminal:
                self._condition.wait(timeout)
            return list(self._events[cursor:]), self._terminal

    def cancel(self) -> bool:
        """请求取消活动任务；重复取消或已结束返回 False。"""
        with self._condition:
            if self._terminal or self._cancel_requested:
                return False
            self._cancel_requested = True
            future = self._future
        if future is not None:
            future.cancel()
        timer = threading.Timer(0.1, self._ensure_cancel_terminal)
        timer.daemon = True
        timer.start()
        return True

    def _ensure_cancel_terminal(self) -> None:
        """兜底处理协程尚未进入函数体便取消的竞态，避免订阅者永久等待。"""
        if not self.terminal:
            try:
                self.append("cancelled", {"content": ""})
                self.append("done", {
                    "content": "", "finish_reason": "cancelled", "usage": {},
                })
            except RuntimeError:
                # 正常取消分支可能刚好先写入终态。
                pass

    @property
    def terminal(self) -> bool:
        """返回运行是否已经写入 done/error 终态事件。"""
        with self._condition:
            return self._terminal

    def expired(self, now: float, ttl: float) -> bool:
        """判断终态事件是否已超过保留期限。"""
        with self._condition:
            return self._finished_at is not None and now - self._finished_at >= ttl


class AgentRuntime:
    """在独立线程维护唯一 asyncio 循环，为所有 HTTP 请求共享异步任务。"""

    def __init__(
        self, application: YanAgentApplication, *, retention_seconds: float = 60.0,
    ) -> None:
        """启动常驻循环；终态运行暂存一段时间，以支持 SSE 晚订阅和重连。"""
        if type(retention_seconds) not in (int, float) or retention_seconds <= 0:
            raise ValueError("运行保留时间必须为正数")
        self.application = application
        self.retention_seconds = float(retention_seconds)
        self._loop = asyncio.new_event_loop()
        self._started = threading.Event()
        self._closed = False
        self._close_lock = threading.Lock()
        self._runs_lock = threading.RLock()
        self._runs: dict[str, RunRecord] = {}
        self._thread = threading.Thread(
            target=self._run_loop, name="yanagent-async-runtime", daemon=True,
        )
        self._thread.start()
        if not self._started.wait(5):
            raise RuntimeError("异步运行环境启动超时")

    def _run_loop(self) -> None:
        """在固定线程中运行事件循环，关闭时回收剩余异步生成器。"""
        asyncio.set_event_loop(self._loop)
        self._started.set()
        self._loop.run_forever()
        pending = asyncio.all_tasks(self._loop)
        for task in pending:
            task.cancel()
        if pending:
            self._loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        self._loop.run_until_complete(self._loop.shutdown_asyncgens())
        self._loop.close()

    def complete(self, payload: dict[str, Any], *, request_id: str) -> dict[str, Any]:
        """在常驻循环中执行非流式调用，替代每个请求临时 ``asyncio.run``。"""
        self._ensure_open()
        timeout = self.application.load_config().request_timeout
        future = asyncio.run_coroutine_threadsafe(
            self.application.chat(payload, request_id=request_id), self._loop,
        )
        try:
            return future.result(timeout=timeout + 1.0)
        except concurrent.futures.TimeoutError:
            future.cancel()
            raise ModelTimeoutError() from None

    def start_stream(self, payload: dict[str, Any], *, request_id: str) -> dict[str, Any]:
        """校验后登记运行并调度流任务，立即返回供桌面端订阅的 request_id。"""
        self._ensure_open()
        prepared = self.application.prepare_chat(payload)
        self._sweep()
        record = RunRecord(request_id=request_id, session_id=prepared.session_id)
        with self._runs_lock:
            if request_id in self._runs:
                raise ValueError("request_id 不能重复")
            self._runs[request_id] = record
        future = asyncio.run_coroutine_threadsafe(self._run_stream(record, prepared), self._loop)
        record.attach_future(future)
        LOGGER.info(
            "[streaming.py][AgentRuntime.start_stream] 流任务已登记，request_id=%s，session_id=%s",
            request_id, prepared.session_id,
        )
        return {
            "status": "success", "request_id": request_id, "stream": True,
            "speaker": "default", "received_session_id": prepared.session_id,
        }

    async def _run_stream(self, record: RunRecord, prepared: PreparedChat) -> None:
        """消费 Provider 增量，组装桌面事件，并把异常或取消转换为稳定终态。"""
        content: list[str] = []
        completed = False
        try:
            messages = await self.application.begin_chat(
                prepared, request_id=record.request_id,
            )
            async for event in prepared.provider.stream(messages, tools=[]):
                if event.kind == "text_delta":
                    content.append(event.content)
                    record.append("delta", {"content": event.content})
                elif event.kind == "completed":
                    if completed or event.reply is None:
                        raise ModelResponseError()
                    completed = True
                    if event.reply.tool_calls:
                        raise UnexpectedToolCallError()
                    if event.reply.content != "".join(content):
                        raise ModelResponseError()
                    await self.application.finish_chat(
                        prepared, event.reply, request_id=record.request_id,
                    )
                    record.append("done", {
                        "content": event.reply.content,
                        "finish_reason": event.reply.finish_reason,
                        "usage": event.reply.usage,
                    })
            if not completed:
                raise EmptyModelResponseError()
            LOGGER.info(
                "[streaming.py][AgentRuntime._run_stream] 流任务完成且回答已持久化，request_id=%s，上下文消息数=%d，输出字符数=%d",
                record.request_id, len(messages), len("".join(content)),
            )
        except asyncio.CancelledError:
            if not record.terminal:
                record.append("cancelled", {"content": "".join(content)})
                record.append("done", {
                    "content": "".join(content), "finish_reason": "cancelled", "usage": {},
                })
            LOGGER.info(
                "[streaming.py][AgentRuntime._run_stream] 流任务已取消，request_id=%s",
                record.request_id,
            )
        except AgentError as error:
            if not record.terminal:
                record.append("error", {
                    "message": error.message, "code": error.code, "reason": error.code,
                })
            LOGGER.warning(
                "[streaming.py][AgentRuntime._run_stream] 流任务失败，request_id=%s，error_code=%s",
                record.request_id, error.code,
            )
        except Exception:
            if not record.terminal:
                error = ModelResponseError()
                record.append("error", {
                    "message": error.message, "code": error.code, "reason": error.code,
                })
            LOGGER.exception(
                "[streaming.py][AgentRuntime._run_stream] 流任务出现未分类异常，request_id=%s",
                record.request_id,
            )

    def wait_events(
        self, request_id: str, cursor: int, timeout: float = 15.0,
    ) -> tuple[list[RunEvent], bool] | None:
        """获取或等待某个运行的新事件；未知 request_id 返回 None。"""
        self._sweep()
        with self._runs_lock:
            record = self._runs.get(request_id)
        return None if record is None else record.wait(cursor, timeout)

    def cancel(self, *, request_id: str | None = None, session_id: str | None = None) -> int:
        """按 request_id 精确取消，缺少它时可取消同一会话的全部活动运行。"""
        self._sweep()
        with self._runs_lock:
            if request_id:
                candidates = [self._runs[request_id]] if request_id in self._runs else []
            elif session_id:
                candidates = [run for run in self._runs.values() if run.session_id == session_id]
            else:
                candidates = []
        cancelled = sum(1 for run in candidates if run.cancel())
        LOGGER.info(
            "[streaming.py][AgentRuntime.cancel] 取消请求完成，request_id=%s，session_id=%s，数量=%d",
            request_id or "<未提供>", session_id or "<未提供>", cancelled,
        )
        return cancelled

    def _sweep(self) -> None:
        """惰性移除过期终态运行，活动任务永不因清理策略被误删。"""
        now = time.monotonic()
        with self._runs_lock:
            expired = [key for key, run in self._runs.items()
                       if run.expired(now, self.retention_seconds)]
            for key in expired:
                del self._runs[key]

    def _ensure_open(self) -> None:
        """在调度前拒绝已关闭运行时，避免 future 永远无法执行。"""
        if self._closed:
            raise RuntimeError("异步运行环境已关闭")

    def close(self) -> None:
        """幂等取消活动任务、停止事件循环并等待运行线程退出。"""
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
            with self._runs_lock:
                runs = list(self._runs.values())
            for run in runs:
                run.cancel()
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=3)
            LOGGER.info("[streaming.py][AgentRuntime.close] 异步运行环境已关闭")
