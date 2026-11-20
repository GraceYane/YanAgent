"""P01-05 最小运行时：常驻事件循环、运行隔离、SSE 队列、取消与清理。"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading
import time
import uuid
from collections.abc import Coroutine, Sequence
from dataclasses import dataclass, field
from typing import Any, TypeVar

from yanagent.chat import PreparedChat, YanAgentApplication
from yanagent.contracts import Message, ModelReply, ToolCall, ToolResult
from yanagent.errors import (
    AgentError, EmptyModelResponseError, ModelResponseError, ModelTimeoutError,
    RequestValidationError, SessionStorageError,
)
from yanagent.events import ClientEventType, RunEvent
from yanagent.runtime.agent_loop import AgentLoop
from yanagent.sessions.runs import TerminalRunStatus
from yanagent.tools.permissions import ToolConfirmationRequest, ToolConfirmationResult


LOGGER = logging.getLogger("yanagent.runtime")
MAX_RUN_EVENTS = 20_000
ResultType = TypeVar("ResultType")


@dataclass(frozen=True, slots=True)
class RunInstruction:
    """记录一条等待当前 Run 安全检查点注入的用户追加指令。"""

    instruction_id: str
    content: str


@dataclass
class PendingConfirmation:
    """保存唯一确认请求及其等待结果的协程 Future。"""

    request: ToolConfirmationRequest
    future: asyncio.Future[ToolConfirmationResult]
    decided: bool = False


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
    _state: str = field(default="queued", repr=False)
    _accepting_instructions: bool = field(default=False, repr=False)
    _pending_instructions: list[RunInstruction] = field(default_factory=list, repr=False)
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
                self._state = "terminal"
                self._accepting_instructions = False
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
        return self.request_cancel() is not None

    def request_cancel(self) -> str | None:
        """原子记录取消并返回取消生效前的状态，终态或重复取消返回 None。"""
        with self._condition:
            if self._terminal or self._cancel_requested:
                return None
            previous_state = self._state
            self._cancel_requested = True
            future = self._future
        if future is not None:
            future.cancel()
        if previous_state == "queued":
            timer = threading.Timer(0.1, self._ensure_cancel_terminal)
            timer.daemon = True
            timer.start()
        return previous_state

    def mark_running(self) -> bool:
        """在获得会话队列后原子切换为运行态；已取消任务不能启动。"""
        with self._condition:
            if self._terminal or self._cancel_requested:
                return False
            self._state = "running"
            return True

    @property
    def state(self) -> str:
        """读取排队、运行或终态，供取消逻辑区分任务所处阶段。"""
        with self._condition:
            return self._state

    def queue_instruction(self, instruction: RunInstruction) -> bool:
        """仅在运行态接受新指令；排队、取消或终态 Run 均拒绝追加。"""
        with self._condition:
            if (
                self._state != "running" or not self._accepting_instructions
                or self._terminal or self._cancel_requested
            ):
                return False
            self._pending_instructions.append(instruction)
            self._condition.notify_all()
            return True

    def set_accepting_instructions(self, accepting: bool) -> None:
        """在 Run 持久化就绪后开放追加，并在结束/取消时关闭入口。"""
        with self._condition:
            self._accepting_instructions = (
                accepting and not self._terminal and not self._cancel_requested
            )

    def take_instructions(self) -> list[RunInstruction]:
        """在安全检查点原子取出当前已持久化等待注入的指令。"""
        with self._condition:
            instructions = list(self._pending_instructions)
            self._pending_instructions.clear()
            return instructions

    def restore_instructions(self, instructions: list[RunInstruction]) -> None:
        """持久化注入失败时按原顺序放回待处理队列。"""
        with self._condition:
            known = {item.instruction_id for item in self._pending_instructions}
            self._pending_instructions = [
                item for item in instructions if item.instruction_id not in known
            ] + self._pending_instructions

    def _ensure_cancel_terminal(self) -> None:
        """兜底处理协程尚未进入函数体便取消的竞态，避免订阅者永久等待。"""
        if not self.terminal:
            queued = self.state == "queued"
            try:
                self.append("cancelled", {
                    "content": "",
                    **({"reason": "cancelled_while_queued"} if queued else {}),
                })
                self.append("done", {
                    "content": "",
                    "finish_reason": "cancelled_before_start" if queued else "cancelled",
                    "usage": {},
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
        self._session_queues: dict[tuple[str, str, str], tuple[asyncio.Lock, int]] = {}
        self._confirmations_lock = threading.RLock()
        self._confirmations: dict[str, PendingConfirmation] = {}
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

    def complete(
        self,
        payload: dict[str, Any],
        *,
        request_id: str,
        queue_key: tuple[str, str, str] | None = None,
    ) -> dict[str, Any]:
        """在常驻循环中执行非流式调用，替代每个请求临时 ``asyncio.run``。"""
        self._ensure_open()
        prepared = self.application.prepare_chat(payload)
        selected_queue_key = queue_key or (
            "local", "default", prepared.session_id,
        )
        timeout = prepared.config.request_timeout
        future = asyncio.run_coroutine_threadsafe(
            self._run_in_session_queue(
                self.application.chat(
                    payload, request_id=request_id, prepared=prepared,
                ),
                selected_queue_key,
            ),
            self._loop,
        )
        try:
            return future.result(timeout=timeout + 1.0)
        except concurrent.futures.TimeoutError:
            future.cancel()
            raise ModelTimeoutError() from None

    def execute(
        self,
        operation: Coroutine[Any, Any, ResultType],
        *,
        timeout: float = 10.0,
    ) -> ResultType:
        """在常驻循环执行短异步控制操作，供线程化 HTTP 会话接口复用。"""
        try:
            self._ensure_open()
        except Exception:
            operation.close()
            raise
        future = asyncio.run_coroutine_threadsafe(operation, self._loop)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            future.cancel()
            raise SessionStorageError() from None

    def start_stream(
        self,
        payload: dict[str, Any],
        *,
        request_id: str,
        queue_key: tuple[str, str, str] | None = None,
    ) -> dict[str, Any]:
        """校验后登记运行并调度流任务，立即返回供桌面端订阅的 request_id。"""
        self._ensure_open()
        prepared = self.application.prepare_chat(payload)
        self._sweep()
        record = RunRecord(request_id=request_id, session_id=prepared.session_id)
        with self._runs_lock:
            if request_id in self._runs:
                raise ValueError("request_id 不能重复")
            self._runs[request_id] = record
        selected_queue_key = queue_key or ("local", "default", prepared.session_id)
        future = asyncio.run_coroutine_threadsafe(
            self._run_stream_queued(record, prepared, selected_queue_key), self._loop,
        )
        record.attach_future(future)
        LOGGER.info(
            "[yanDebug][02-流任务登记][streaming.py][AgentRuntime.start_stream] "
            "流任务已登记，request_id=%s，session_id=%s",
            request_id, prepared.session_id,
        )
        return {
            "status": "success", "request_id": request_id, "stream": True,
            "speaker": "default", "received_session_id": prepared.session_id,
        }

    async def _request_tool_confirmation(
        self,
        record: RunRecord,
        request: ToolConfirmationRequest,
    ) -> ToolConfirmationResult:
        """发出需确认事件并等待同一 Run 的一次性批准或拒绝结果。"""
        future: asyncio.Future[ToolConfirmationResult] = self._loop.create_future()
        pending = PendingConfirmation(request=request, future=future)
        with self._confirmations_lock:
            if request.request_id in self._confirmations:
                raise ModelResponseError()
            self._confirmations[request.request_id] = pending
        try:
            record.append("confirmation_required", {
                "confirmation_id": request.request_id,
                "run_id": request.run_id,
                "tool_call_id": request.tool_call_id,
                "tool": request.tool_name,
                "risk_level": request.risk_level,
                "scope": request.scope,
            })
            LOGGER.info(
                "[streaming.py][AgentRuntime._request_tool_confirmation] 已等待工具确认，"
                "request_id=%s，tool_call_id=%s，tool=%s",
                request.run_id, request.tool_call_id, request.tool_name,
            )
            return await future
        finally:
            with self._confirmations_lock:
                if self._confirmations.get(request.request_id) is pending:
                    del self._confirmations[request.request_id]

    def resolve_tool_confirmation(
        self, *, confirmation_id: str, run_id: str, approved: bool,
    ) -> bool:
        """校验 Run 归属并原子消费一次确认决定，再唤醒等待中的工具执行。"""
        if type(approved) is not bool:
            return False
        with self._confirmations_lock:
            pending = self._confirmations.get(confirmation_id)
            if (
                pending is None or pending.request.run_id != run_id or pending.decided
            ):
                return False
            pending.decided = True
        result = ToolConfirmationResult(
            request_id=confirmation_id,
            decision="approved" if approved else "rejected",
        )

        def finish_confirmation() -> None:
            """在 Runtime 事件循环中安全完成确认 Future。"""
            if not pending.future.done():
                pending.future.set_result(result)

        try:
            self._loop.call_soon_threadsafe(finish_confirmation)
        except RuntimeError:
            return False
        LOGGER.info(
            "[streaming.py][AgentRuntime.resolve_tool_confirmation] 用户已提交确认结果，"
            "request_id=%s，confirmation_id=%s，approved=%s",
            run_id, confirmation_id, approved,
        )
        return True

    def queue_instruction(
        self, *, request_id: str, session_id: str, content: str,
    ) -> dict[str, str] | None:
        """把追加指令持久化到 Run 元数据，等待 AgentLoop 安全检查点注入。"""
        if type(content) is not str or not content.strip() or len(content) > 200_000:
            raise RequestValidationError(reason="invalid", field="message")
        with self._runs_lock:
            record = self._runs.get(request_id)
        if record is None or record.session_id != session_id:
            return None
        instruction = RunInstruction(uuid.uuid4().hex, content)
        future = asyncio.run_coroutine_threadsafe(
            self._queue_instruction(record, instruction), self._loop,
        )
        try:
            return future.result(timeout=10.0)
        except concurrent.futures.TimeoutError:
            future.cancel()
            raise ModelTimeoutError() from None

    async def _queue_instruction(
        self, record: RunRecord, instruction: RunInstruction,
    ) -> dict[str, str] | None:
        """先持久化追加文本，再开放给检查点读取，避免先注入后落库。"""
        if record.state != "running":
            return None
        run_store = self.application.run_store
        if run_store is not None:
            persisted = await run_store.queue_instruction(
                record.request_id,
                record.session_id,
                instruction.instruction_id,
                instruction.content,
            )
            if not persisted:
                return None
        if not record.queue_instruction(instruction):
            if run_store is not None:
                await run_store.finish_instruction(
                    record.request_id, record.session_id,
                    instruction.instruction_id, status="rejected",
                )
            return None
        record.append("instruction_queued", {
            "instruction_id": instruction.instruction_id,
        })
        LOGGER.info(
            "[streaming.py][AgentRuntime._queue_instruction] 追加指令已排队等待检查点，"
            "request_id=%s，instruction_id=%s",
            record.request_id, instruction.instruction_id,
        )
        return {"request_id": record.request_id, "instruction_id": instruction.instruction_id}

    async def _run_in_session_queue(
        self,
        operation: Coroutine[Any, Any, ResultType],
        queue_key: tuple[str, str, str],
    ) -> ResultType:
        """按完整身份和 Session 键串行执行操作，不同键可并行推进。"""
        lock, users = self._session_queues.get(queue_key, (asyncio.Lock(), 0))
        self._session_queues[queue_key] = (lock, users + 1)
        started = False
        try:
            async with lock:
                started = True
                return await operation
        finally:
            if not started:
                operation.close()
            current_lock, current_users = self._session_queues[queue_key]
            if current_users <= 1:
                del self._session_queues[queue_key]
            else:
                self._session_queues[queue_key] = (current_lock, current_users - 1)

    async def _run_stream_queued(
        self,
        record: RunRecord,
        prepared: PreparedChat,
        queue_key: tuple[str, str, str],
    ) -> None:
        """排队等待会话锁，取消等待任务时写入明确的未启动终态。"""
        lock, users = self._session_queues.get(queue_key, (asyncio.Lock(), 0))
        self._session_queues[queue_key] = (lock, users + 1)
        try:
            async with lock:
                if not record.mark_running():
                    self._finish_queued_cancel(record)
                    return
                LOGGER.info(
                    "[streaming.py][AgentRuntime._run_stream_queued] 排队任务开始运行，"
                    "request_id=%s，session_id=%s",
                    record.request_id, prepared.session_id,
                )
                await self._run_stream(record, prepared)
        except asyncio.CancelledError:
            self._finish_queued_cancel(record)
        finally:
            current_lock, current_users = self._session_queues[queue_key]
            if current_users <= 1:
                del self._session_queues[queue_key]
            else:
                self._session_queues[queue_key] = (current_lock, current_users - 1)

    @staticmethod
    def _finish_queued_cancel(record: RunRecord) -> None:
        """为尚未启动就被取消的任务写出独立可识别的终态事件。"""
        if record.terminal:
            return
        try:
            record.append("cancelled", {
                "content": "", "reason": "cancelled_while_queued",
            })
            record.append("done", {
                "content": "", "finish_reason": "cancelled_before_start", "usage": {},
            })
            LOGGER.info(
                "[streaming.py][AgentRuntime._finish_queued_cancel] 排队任务在执行前已取消，request_id=%s",
                record.request_id,
            )
        except RuntimeError:
            pass

    async def _run_stream(self, record: RunRecord, prepared: PreparedChat) -> None:
        """循环消费模型增量、执行完整工具调用，并转换为桌面流事件和稳定终态。"""
        content: list[str] = []
        run_started = False

        async def stream_model_turn(
            messages: Sequence[Message],
            tools: Sequence[dict[str, Any]],
        ) -> ModelReply:
            """消费一轮 Provider 流，实时转发文本，并仅返回已完整解析的轮次结果。"""
            turn_content: list[str] = []
            completed_reply: ModelReply | None = None
            LOGGER.info(
                "[streaming.py][AgentRuntime._run_stream] 开始流式模型轮次，"
                "request_id=%s，消息数=%d，工具数=%d",
                record.request_id,
                len(messages),
                len(tools),
            )
            async for event in prepared.provider.stream(messages, tools=tools):
                if event.kind == "text_delta":
                    turn_content.append(event.content)
                    content.append(event.content)
                    record.append("delta", {"content": event.content})
                elif event.kind == "tool_call_delta":
                    # Provider 在 completed 前负责拼接并校验全部参数；此处绝不提前执行。
                    LOGGER.debug(
                        "[streaming.py][AgentRuntime._run_stream] 收到工具调用增量，等待完整参数，"
                        "request_id=%s，tool_index=%s，参数增量字符数=%d",
                        record.request_id,
                        event.tool_index,
                        len(event.arguments_delta),
                    )
                elif event.kind == "completed":
                    if completed_reply is not None or event.reply is None:
                        raise ModelResponseError()
                    completed_reply = event.reply
            if completed_reply is None:
                raise EmptyModelResponseError()
            if completed_reply.content != "".join(turn_content):
                raise ModelResponseError()
            if completed_reply.tool_calls:
                record.append("message_end", {
                    "has_tool_calls": True,
                    "finish_reason": completed_reply.finish_reason,
                    "usage": completed_reply.usage,
                })
            LOGGER.info(
                "[streaming.py][AgentRuntime._run_stream] 流式模型轮次完成，"
                "request_id=%s，输出字符数=%d，工具调用数=%d，finish_reason=%s",
                record.request_id,
                len(completed_reply.content),
                len(completed_reply.tool_calls),
                completed_reply.finish_reason,
            )
            return completed_reply

        def emit_tool_start(call: ToolCall, turn: int, index: int, total: int) -> None:
            """在完整 ToolCall 已保存且即将执行时发送桌面工具开始事件。"""
            record.append("tool_start", {
                "tool": call.name,
                "tool_call_id": call.id,
                "arguments": dict(call.arguments),
                "status": "running",
                "model_turn": turn,
                "tool_call_index": index,
                "tool_call_total": total,
            })

        def emit_tool_end(
            call: ToolCall,
            result: ToolResult,
            turn: int,
            index: int,
            total: int,
            execution_time: float,
        ) -> None:
            """在 Tool Result 已保存并回写上下文后发送成功或失败的工具结束事件。"""
            record.append("tool_end", {
                "tool": call.name,
                "tool_call_id": call.id,
                "status": "error" if result.is_error else "success",
                "result": result.content,
                "execution_time": execution_time,
                "model_turn": turn,
                "tool_call_index": index,
                "tool_call_total": total,
            })

        async def inject_pending_instructions() -> Sequence[Message]:
            """在无悬空 ToolCall 的检查点落库并注入追加用户指令。"""
            pending = record.take_instructions()
            if not pending:
                return ()
            messages = [
                Message(
                    role="user",
                    content=item.content,
                    metadata={
                        "request_id": record.request_id,
                        "run_instruction_id": item.instruction_id,
                        "injected_at_checkpoint": True,
                    },
                )
                for item in pending
            ]
            checkpoint_id = uuid.uuid4().hex
            try:
                stored = (
                    await self.application.session_store.append(
                        prepared.session_id, messages,
                    )
                    if self.application.session_store is not None
                    else []
                )
                for index, item in enumerate(pending):
                    sequence = stored[index].sequence if stored else None
                    if self.application.run_store is not None:
                        await self.application.run_store.finish_instruction(
                            record.request_id,
                            prepared.session_id,
                            item.instruction_id,
                            status="injected",
                            sequence=sequence,
                        )
                    record.append("instruction_injected", {
                        "instruction_id": item.instruction_id,
                        "user_seq": sequence,
                        "checkpoint_id": checkpoint_id,
                    })
                LOGGER.info(
                    "[streaming.py][AgentRuntime._run_stream] 安全检查点追加指令已持久化并注入，"
                    "request_id=%s，数量=%d，首序号=%s",
                    record.request_id, len(pending),
                    stored[0].sequence if stored else "<无仓储>",
                )
                return messages
            except Exception:
                record.restore_instructions(pending)
                LOGGER.exception(
                    "[streaming.py][AgentRuntime._run_stream] 追加指令注入失败并保留待处理状态，"
                    "request_id=%s，数量=%d",
                    record.request_id, len(pending),
                )
                raise

        async def request_confirmation(
            request: ToolConfirmationRequest,
        ) -> ToolConfirmationResult:
            """把当前 Run 的工具确认请求交给 SSE 桌面界面并等待决定。"""
            return await self._request_tool_confirmation(record, request)

        async def reject_uninjected_instructions() -> None:
            """Run 结束或失败时明确标记尚未到安全检查点的追加指令。"""
            pending = record.take_instructions()
            for item in pending:
                if self.application.run_store is not None:
                    await self.application.run_store.finish_instruction(
                        record.request_id,
                        prepared.session_id,
                        item.instruction_id,
                        status="rejected",
                    )
                record.append("instruction_rejected", {
                    "instruction_id": item.instruction_id,
                    "reason": "run_finished_before_checkpoint",
                })

        try:
            LOGGER.info(
                "[yanDebug][02-流任务执行][streaming.py][AgentRuntime._run_stream] "
                "开始加载会话上下文，request_id=%s，session_id=%s",
                record.request_id,
                prepared.session_id,
            )
            context = await self.application.begin_chat(
                prepared, request_id=record.request_id,
            )
            run_started = await self.application.start_run(
                prepared, request_id=record.request_id,
            )
            record.set_accepting_instructions(True)
            loop_result = await AgentLoop(
                model=prepared.provider,
                tools=self.application.tool_manager,
                sessions=self.application.session_store,
                model_turn=stream_model_turn,
                on_tool_start=emit_tool_start,
                on_tool_end=emit_tool_end,
                confirmation_handler=request_confirmation,
                on_checkpoint=inject_pending_instructions,
            ).run(
                messages=context.messages,
                tool_schemas=context.tools,
                session_id=prepared.session_id,
                request_id=record.request_id,
                permission_mode=prepared.config.permission_mode,
                permission_context=self.application.tool_permission_context(
                    prepared,
                    request_id=record.request_id,
                    confirmation_ui_available=True,
                ),
            )
            record.set_accepting_instructions(False)
            await reject_uninjected_instructions()
            if run_started:
                await self.application.finish_run(
                    record.request_id,
                    prepared.session_id,
                    status="completed",
                    finish_reason=loop_result.reply.finish_reason,
                    usage=loop_result.usage,
                )
            record.append("done", {
                "content": loop_result.reply.content,
                "finish_reason": loop_result.reply.finish_reason,
                "usage": loop_result.usage,
                "turns": loop_result.turns,
                "user_seq": context.user_sequence,
                "bot_seq": loop_result.assistant_sequence,
            })
            LOGGER.info(
                "[yanDebug][08-SSE交付完成][streaming.py][AgentRuntime._run_stream] "
                "流式工具循环完成且回答已持久化，request_id=%s，模型轮数=%d，"
                "上下文消息数=%d，最终输出字符数=%d",
                record.request_id,
                loop_result.turns,
                len(context.messages),
                len(loop_result.reply.content),
            )
        except asyncio.CancelledError:
            record.set_accepting_instructions(False)
            await reject_uninjected_instructions()
            if run_started:
                await self._finish_run_after_error(
                    record.request_id,
                    prepared.session_id,
                    status="cancelled",
                    finish_reason="cancelled",
                )
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
            record.set_accepting_instructions(False)
            await reject_uninjected_instructions()
            if run_started:
                await self._finish_run_after_error(
                    record.request_id,
                    prepared.session_id,
                    status="failed",
                    finish_reason="error",
                    error_code=error.code,
                )
            if not record.terminal:
                record.append("error", {
                    "message": error.message, "code": error.code, "reason": error.code,
                })
            LOGGER.warning(
                "[streaming.py][AgentRuntime._run_stream] 流任务失败，request_id=%s，error_code=%s",
                record.request_id, error.code,
            )
        except Exception:
            record.set_accepting_instructions(False)
            await reject_uninjected_instructions()
            if run_started:
                await self._finish_run_after_error(
                    record.request_id,
                    prepared.session_id,
                    status="failed",
                    finish_reason="error",
                    error_code="unexpected_error",
                )
            if not record.terminal:
                error = ModelResponseError()
                record.append("error", {
                    "message": error.message, "code": error.code, "reason": error.code,
                })
            LOGGER.exception(
                "[streaming.py][AgentRuntime._run_stream] 流任务出现未分类异常，request_id=%s",
                record.request_id,
            )

    async def _finish_run_after_error(
        self,
        request_id: str,
        session_id: str,
        *,
        status: TerminalRunStatus,
        finish_reason: str,
        error_code: str | None = None,
    ) -> None:
        """错误或取消路径尽力保存 Run 终态，失败时不覆盖原始流错误。"""
        try:
            await self.application.finish_run(
                request_id,
                session_id,
                status=status,
                finish_reason=finish_reason,
                error_code=error_code,
            )
        except AgentError as error:
            LOGGER.error(
                "[streaming.py][AgentRuntime._finish_run_after_error] Run 终态保存失败，request_id=%s，error_code=%s",
                request_id,
                error.code,
            )

    def wait_events(
        self, request_id: str, cursor: int, timeout: float = 15.0,
    ) -> tuple[list[RunEvent], bool] | None:
        """获取或等待某个运行的新事件；未知 request_id 返回 None。"""
        self._sweep()
        with self._runs_lock:
            record = self._runs.get(request_id)
        return None if record is None else record.wait(cursor, timeout)

    def cancel_with_details(
        self, *, request_id: str | None = None, session_id: str | None = None,
    ) -> dict[str, int]:
        """按运行阶段分别统计取消的排队任务和运行中任务。"""
        self._sweep()
        with self._runs_lock:
            if request_id:
                candidates = [self._runs[request_id]] if request_id in self._runs else []
            elif session_id:
                candidates = [run for run in self._runs.values() if run.session_id == session_id]
            else:
                candidates = []
        queued = running = 0
        for run in candidates:
            previous_state = run.request_cancel()
            if previous_state is None:
                continue
            if previous_state == "queued":
                queued += 1
            else:
                running += 1
        LOGGER.info(
            "[streaming.py][AgentRuntime.cancel_with_details] 取消请求完成，request_id=%s，"
            "session_id=%s，排队取消=%d，运行中取消=%d",
            request_id or "<未提供>", session_id or "<未提供>", queued, running,
        )
        return {"cancelled": queued + running, "queued_cancelled": queued,
                "running_cancelled": running}

    def cancel(self, *, request_id: str | None = None, session_id: str | None = None) -> int:
        """兼容旧接口，返回成功接受取消的任务总数。"""
        return self.cancel_with_details(
            request_id=request_id, session_id=session_id,
        )["cancelled"]

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
