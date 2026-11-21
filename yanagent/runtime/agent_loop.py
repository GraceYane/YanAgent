"""统一 Agent Loop：模型请求工具、执行并回写结果后继续调用模型。"""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Awaitable, Callable, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from yanagent.contracts import (
    ContractValidationError,
    Message,
    ModelReply,
    ToolCall,
    ToolResult,
    Usage,
    validate_conversation,
)
from yanagent.context import estimate_context_usage, trim_complete_turns
from yanagent.debug_log import yan_debug
from yanagent.errors import (
    AgentLoopConsecutiveFailuresError,
    AgentLoopMaxTurnsError,
    AgentLoopTimeoutError,
    EmptyModelResponseError,
    ModelResponseError,
    RequestValidationError,
)
from yanagent.models.provider import ModelProvider
from yanagent.sessions.store import SessionStore
from yanagent.tools.manager import ToolManager
from yanagent.tools.permissions import (
    ToolConfirmationRequest,
    ToolConfirmationResult,
    ToolPermissionContext,
)


LOGGER = logging.getLogger("yanagent.agent_loop")
DEFAULT_MAX_MODEL_TURNS = 20
DEFAULT_TOTAL_TIMEOUT_SECONDS = 600.0
DEFAULT_MAX_CONSECUTIVE_TOOL_FAILURES = 3
MAX_CONFIGURED_MODEL_TURNS = 1_000
MAX_CONFIGURED_TIMEOUT_SECONDS = 86_400.0
MAX_CONFIGURED_CONSECUTIVE_FAILURES = 1_000
ModelTurn = Callable[[Sequence[Message], Sequence[dict[str, Any]]], Awaitable[ModelReply]]
ToolStartObserver = Callable[[ToolCall, int, int, int], None]
ToolEndObserver = Callable[[ToolCall, ToolResult, int, int, int, float], None]
ConfirmationHandler = Callable[[ToolConfirmationRequest], Awaitable[ToolConfirmationResult]]
CheckpointObserver = Callable[[], Awaitable[Sequence[Message]]]


@dataclass(frozen=True, slots=True)
class AgentLoopResult:
    """保存一次循环的最终模型回答、轮数、累计用量和消息序号。"""

    reply: ModelReply
    turns: int
    usage: Usage
    assistant_sequence: int | None


def _identifier(value: Any, label: str) -> str:
    """校验循环使用的可信标识，防止空值或控制字符进入日志和元数据。"""
    if (
        type(value) is not str
        or not value.strip()
        or value != value.strip()
        or len(value) > 256
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ValueError(f"{label} 必须是 1～256 位无控制字符的非空字符串")
    return value


def _merge_usage(total: Usage, current: Usage) -> Usage:
    """累计多轮模型用量；任一轮明确未知的字段保持未知而不是猜成零。"""
    merged: Usage = deepcopy(total)
    for name, value in current.items():
        previous = merged.get(name)
        if name not in merged:
            merged[name] = value
        elif previous is None or value is None:
            merged[name] = None
        else:
            merged[name] = previous + value
    return merged


class AgentLoop:
    """执行供应商无关的模型与多工具循环，并统一限制运行边界。"""

    def __init__(
        self,
        *,
        model: ModelProvider,
        tools: ToolManager,
        sessions: SessionStore | None,
        max_model_turns: int = DEFAULT_MAX_MODEL_TURNS,
        total_timeout_seconds: float = DEFAULT_TOTAL_TIMEOUT_SECONDS,
        max_consecutive_tool_failures: int = DEFAULT_MAX_CONSECUTIVE_TOOL_FAILURES,
        model_turn: ModelTurn | None = None,
        on_tool_start: ToolStartObserver | None = None,
        on_tool_end: ToolEndObserver | None = None,
        confirmation_handler: ConfirmationHandler | None = None,
        on_checkpoint: CheckpointObserver | None = None,
    ) -> None:
        """注入循环依赖、可选流式轮次及观察器，并校验所有运行限制。"""
        if not callable(getattr(model, "complete", None)):
            raise TypeError("model 必须实现 complete")
        if not isinstance(tools, ToolManager):
            raise TypeError("tools 必须是 ToolManager")
        if sessions is not None and not isinstance(sessions, SessionStore):
            raise TypeError("sessions 必须是 SessionStore 或 None")
        if model_turn is not None and not callable(model_turn):
            raise TypeError("model_turn 必须是可调用对象或 None")
        if on_tool_start is not None and not callable(on_tool_start):
            raise TypeError("on_tool_start 必须是可调用对象或 None")
        if on_tool_end is not None and not callable(on_tool_end):
            raise TypeError("on_tool_end 必须是可调用对象或 None")
        if confirmation_handler is not None and not callable(confirmation_handler):
            raise TypeError("confirmation_handler 必须是可调用对象或 None")
        if on_checkpoint is not None and not callable(on_checkpoint):
            raise TypeError("on_checkpoint 必须是可调用对象或 None")
        if (
            type(max_model_turns) is not int
            or not 1 <= max_model_turns <= MAX_CONFIGURED_MODEL_TURNS
        ):
            raise ValueError("最大模型轮数必须是 1～1000 之间的整数")
        if (
            type(total_timeout_seconds) not in (int, float)
            or not math.isfinite(total_timeout_seconds)
            or not 0 < total_timeout_seconds <= MAX_CONFIGURED_TIMEOUT_SECONDS
        ):
            raise ValueError("循环总超时必须是 0～86400 秒之间的有限数字")
        if (
            type(max_consecutive_tool_failures) is not int
            or not 1
            <= max_consecutive_tool_failures
            <= MAX_CONFIGURED_CONSECUTIVE_FAILURES
        ):
            raise ValueError("连续工具失败上限必须是 1～1000 之间的整数")
        self.model = model
        self.tools = tools
        self.sessions = sessions
        self.max_model_turns = max_model_turns
        self.total_timeout_seconds = float(total_timeout_seconds)
        self.max_consecutive_tool_failures = max_consecutive_tool_failures
        self.model_turn = model_turn or self._complete_model_turn
        self.on_tool_start = on_tool_start
        self.on_tool_end = on_tool_end
        self.confirmation_handler = confirmation_handler
        self.on_checkpoint = on_checkpoint

    async def _complete_model_turn(
        self,
        messages: Sequence[Message],
        tools: Sequence[dict[str, Any]],
    ) -> ModelReply:
        """执行默认非流式模型轮次；流式运行时可注入等价的完整轮次实现。"""
        return await self.model.complete(messages, tools=tools)

    async def run(
        self,
        *,
        messages: Sequence[Message],
        tool_schemas: Sequence[dict[str, Any]],
        session_id: str,
        request_id: str,
        permission_mode: str,
        permission_context: ToolPermissionContext,
        initial_usage: Usage | None = None,
        context_window_tokens: int = 64_000,
        reserved_output_tokens: int = 4_000,
        max_context_turns: int = 20,
    ) -> AgentLoopResult:
        """在总超时内循环模型和工具，直到最终回答或稳定限制错误。"""
        selected_session = _identifier(session_id, "session_id")
        selected_request = _identifier(request_id, "request_id")
        if not isinstance(permission_context, ToolPermissionContext):
            raise TypeError("permission_context 必须是 ToolPermissionContext")
        if initial_usage is not None:
            try:
                ModelReply(content="", usage=deepcopy(initial_usage))
            except (ContractValidationError, TypeError):
                raise ValueError("initial_usage 必须是合法 Token 用量对象") from None
        if type(context_window_tokens) is not int or context_window_tokens < 1_024:
            raise ValueError("context_window_tokens 必须至少为 1024")
        if (
            type(reserved_output_tokens) is not int
            or not 0 <= reserved_output_tokens < context_window_tokens
        ):
            raise ValueError("reserved_output_tokens 必须小于上下文窗口")
        if type(max_context_turns) is not int or max_context_turns < 1:
            raise ValueError("max_context_turns 必须是正整数")
        if not isinstance(messages, (list, tuple)) or not messages:
            raise ValueError("messages 必须是非空列表或元组")
        if not isinstance(tool_schemas, (list, tuple)):
            raise ValueError("tool_schemas 必须是列表或元组")
        try:
            working = [Message.from_dict(message.to_dict()) for message in messages]
            validate_conversation(working)
        except (AttributeError, ContractValidationError, TypeError):
            raise ModelResponseError() from None
        schemas = deepcopy(list(tool_schemas))

        LOGGER.info(
            "[agent_loop.py][AgentLoop.run] 模型工具循环开始，"
            "request_id=%s，session_id=%s，初始消息数=%d，工具数=%d，权限模式=%s，"
            "最大模型轮数=%d，总超时=%.3f，连续失败上限=%d，单工具超时=%.3f",
            selected_request,
            selected_session,
            len(working),
            len(schemas),
            permission_mode,
            self.max_model_turns,
            self.total_timeout_seconds,
            self.max_consecutive_tool_failures,
            self.tools.timeout_seconds,
        )
        deadline = asyncio.get_running_loop().time() + self.total_timeout_seconds
        return await self._run_loop(
            working=working,
            schemas=schemas,
            session_id=selected_session,
            request_id=selected_request,
            permission_mode=permission_mode,
            permission_context=permission_context,
            deadline=deadline,
            initial_usage={} if initial_usage is None else deepcopy(initial_usage),
            context_window_tokens=context_window_tokens,
            reserved_output_tokens=reserved_output_tokens,
            max_context_turns=max_context_turns,
        )

    async def _run_loop(
        self,
        *,
        working: list[Message],
        schemas: list[dict[str, Any]],
        session_id: str,
        request_id: str,
        permission_mode: str,
        permission_context: ToolPermissionContext,
        deadline: float,
        initial_usage: Usage,
        context_window_tokens: int,
        reserved_output_tokens: int,
        max_context_turns: int,
    ) -> AgentLoopResult:
        """执行已校验的内部循环；同轮调用顺序执行并保持完整消息配对。"""
        turns = 0
        usage: Usage = deepcopy(initial_usage)
        consecutive_failures = 0

        while True:
            if self.on_checkpoint is not None:
                injected = list(await self.on_checkpoint())
                if injected:
                    working.extend(
                        Message.from_dict(message.to_dict()) for message in injected
                    )
                    validate_conversation(working)
                    LOGGER.info(
                        "[agent_loop.py][AgentLoop._run_loop] 安全检查点注入追加指令，"
                        "request_id=%s，消息数=%d",
                        request_id, len(injected),
                    )
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                self._raise_total_timeout(request_id)
            request_messages = self._fit_model_context(
                working,
                schemas,
                request_id=request_id,
                context_window_tokens=context_window_tokens,
                reserved_output_tokens=reserved_output_tokens,
                max_context_turns=max_context_turns,
            )
            yan_debug(
                "agent_loop.py",
                "AgentLoop.run",
                "准备发送模型轮次",
                messages=request_messages,
                tools=schemas,
            )
            try:
                reply = await asyncio.wait_for(
                    self.model_turn(request_messages, schemas),
                    timeout=remaining,
                )
            except (TimeoutError, asyncio.TimeoutError):
                self._raise_total_timeout(request_id)
            yan_debug(
                "agent_loop.py",
                "AgentLoop.run",
                "收到模型轮次回复",
                reply=reply,
            )
            turns += 1
            usage = _merge_usage(usage, reply.usage)
            LOGGER.info(
                "[agent_loop.py][AgentLoop.run] 模型轮次完成，"
                "request_id=%s，turn=%d，工具调用数=%d，文本字符数=%d",
                request_id,
                turns,
                len(reply.tool_calls),
                len(reply.content),
            )

            if not reply.tool_calls and not reply.content.strip():
                LOGGER.warning(
                    "[agent_loop.py][AgentLoop._run_loop] 模型返回空内容且没有工具调用，"
                    "request_id=%s，turn=%d",
                    request_id,
                    turns,
                )
                raise EmptyModelResponseError()

            if reply.tool_calls and turns >= self.max_model_turns:
                LOGGER.warning(
                    "[agent_loop.py][AgentLoop._run_loop] 模型在最后允许轮次仍请求工具，"
                    "request_id=%s，turn=%d，工具调用数=%d",
                    request_id,
                    turns,
                    len(reply.tool_calls),
                )
                raise AgentLoopMaxTurnsError()

            assistant = reply.to_message()
            assistant.metadata.update({
                "request_id": request_id,
                "model_turn": turns,
                "usage": deepcopy(reply.usage),
            })
            self._validate_next(working, assistant, allow_pending=bool(reply.tool_calls))

            if not reply.tool_calls:
                final_reply = ModelReply(
                    content=reply.content,
                    finish_reason=reply.finish_reason,
                    usage=usage,
                )
                assistant.metadata["usage"] = deepcopy(usage)
                sequence = await self._append(
                    session_id,
                    [assistant],
                    request_id=request_id,
                    stage="final_assistant",
                )
                working.append(Message.from_dict(assistant.to_dict()))
                if self.on_checkpoint is not None:
                    injected = list(await self.on_checkpoint())
                    if injected:
                        working.extend(
                            Message.from_dict(message.to_dict()) for message in injected
                        )
                        validate_conversation(working)
                        LOGGER.info(
                            "[agent_loop.py][AgentLoop._run_loop] 最终回答保存后收到追加指令，"
                            "同一 Run 继续处理，request_id=%s，消息数=%d",
                            request_id, len(injected),
                        )
                        continue
                LOGGER.info(
                    "[agent_loop.py][AgentLoop.run] 模型工具循环完成，"
                    "request_id=%s，turns=%d，累计用量字段=%s，assistant_sequence=%s",
                    request_id,
                    turns,
                    sorted(usage),
                    sequence,
                )
                return AgentLoopResult(
                    reply=final_reply,
                    turns=turns,
                    usage=deepcopy(usage),
                    assistant_sequence=sequence,
                )

            await self._append(
                session_id,
                [assistant],
                request_id=request_id,
                stage="assistant_tool_call",
            )
            working.append(Message.from_dict(assistant.to_dict()))
            LOGGER.info(
                "[agent_loop.py][AgentLoop._run_loop] Assistant 工具请求组已保存，"
                "request_id=%s，turn=%d，工具调用数=%d",
                request_id,
                turns,
                len(reply.tool_calls),
            )

            failure_limit_reached = False
            total_limit_reached = False
            for index, call in enumerate(reply.tool_calls):
                tool_started_at = asyncio.get_running_loop().time()
                if self.on_tool_start is not None:
                    self.on_tool_start(
                        call,
                        turns,
                        index,
                        len(reply.tool_calls),
                    )
                remaining = deadline - asyncio.get_running_loop().time()
                if total_limit_reached or remaining <= 0:
                    total_limit_reached = True
                    result = ToolResult(
                        tool_call_id=call.id,
                        content="Agent 循环总超时，本次工具调用未执行完成。",
                        is_error=True,
                    )
                    LOGGER.warning(
                        "[agent_loop.py][AgentLoop._run_loop] 总超时后补齐工具失败结果，"
                        "request_id=%s，turn=%d，call_index=%d/%d，call_id=%s，tool=%s",
                        request_id,
                        turns,
                        index + 1,
                        len(reply.tool_calls),
                        call.id,
                        call.name,
                    )
                elif failure_limit_reached:
                    result = ToolResult(
                        tool_call_id=call.id,
                        content="此前工具连续失败已达到限制，本次调用未执行。",
                        is_error=True,
                    )
                    LOGGER.warning(
                        "[agent_loop.py][AgentLoop._run_loop] 连续失败熔断后跳过同轮剩余工具，"
                        "request_id=%s，turn=%d，call_index=%d/%d，call_id=%s，tool=%s",
                        request_id,
                        turns,
                        index + 1,
                        len(reply.tool_calls),
                        call.id,
                        call.name,
                    )
                else:
                    LOGGER.info(
                        "[agent_loop.py][AgentLoop._run_loop] 按模型顺序执行工具，"
                        "request_id=%s，turn=%d，call_index=%d/%d，call_id=%s，tool=%s",
                        request_id,
                        turns,
                        index + 1,
                        len(reply.tool_calls),
                        call.id,
                        call.name,
                    )
                    try:
                        current_usage = estimate_context_usage(
                            messages=working,
                            tools=schemas,
                            reserved_output=reserved_output_tokens,
                        )
                        available_result_tokens = max(
                            0,
                            context_window_tokens - current_usage.total_tokens - 16,
                        )
                        max_result_chars = int(available_result_tokens / 1.08)
                        result = await asyncio.wait_for(
                            self.tools.execute(
                                call,
                                permission_mode=permission_mode,
                                permission_context=permission_context,
                                confirmation_handler=self.confirmation_handler,
                                max_result_chars=max_result_chars,
                            ),
                            timeout=remaining,
                        )
                    except (TimeoutError, asyncio.TimeoutError):
                        total_limit_reached = True
                        result = ToolResult(
                            tool_call_id=call.id,
                            content="Agent 循环总超时，本次工具调用未执行完成。",
                            is_error=True,
                        )

                if not total_limit_reached:
                    consecutive_failures = (
                        consecutive_failures + 1 if result.is_error else 0
                    )
                    if consecutive_failures >= self.max_consecutive_tool_failures:
                        failure_limit_reached = True

                execution_time = max(
                    0.0,
                    asyncio.get_running_loop().time() - tool_started_at,
                )
                tool_message = result.to_message()
                tool_message.name = call.name
                tool_message.metadata.update({
                    "request_id": request_id,
                    "model_turn": turns,
                    "tool_name": call.name,
                    "tool_call_index": index,
                    "execution_time": execution_time,
                })
                has_pending_calls = index + 1 < len(reply.tool_calls)
                self._validate_next(
                    working,
                    tool_message,
                    allow_pending=has_pending_calls,
                )
                await self._append(
                    session_id,
                    [tool_message],
                    request_id=request_id,
                    stage="tool_result",
                )
                working.append(Message.from_dict(tool_message.to_dict()))
                if self.on_tool_end is not None:
                    self.on_tool_end(
                        call,
                        result,
                        turns,
                        index,
                        len(reply.tool_calls),
                        execution_time,
                    )
                LOGGER.info(
                    "[agent_loop.py][AgentLoop._run_loop] Tool Result 已保存并回写模型上下文，"
                    "request_id=%s，turn=%d，call_index=%d/%d，call_id=%s，tool=%s，"
                    "is_error=%s，连续失败数=%d，结果字符数=%d",
                    request_id,
                    turns,
                    index + 1,
                    len(reply.tool_calls),
                    call.id,
                    call.name,
                    result.is_error,
                    consecutive_failures,
                    len(result.content),
                )

            if total_limit_reached:
                self._raise_total_timeout(request_id)
            if failure_limit_reached:
                LOGGER.warning(
                    "[agent_loop.py][AgentLoop._run_loop] 工具连续失败达到限制，"
                    "request_id=%s，turn=%d，连续失败数=%d，上限=%d",
                    request_id,
                    turns,
                    consecutive_failures,
                    self.max_consecutive_tool_failures,
                )
                raise AgentLoopConsecutiveFailuresError()

    def _fit_model_context(
        self,
        messages: list[Message],
        schemas: list[dict[str, Any]],
        *,
        request_id: str,
        context_window_tokens: int,
        reserved_output_tokens: int,
        max_context_turns: int,
    ) -> list[Message]:
        """每轮请求前按预算裁剪完整旧轮次，不改写 AgentLoop 的持久化历史。"""
        current = estimate_context_usage(
            messages=messages,
            tools=schemas,
            reserved_output=reserved_output_tokens,
        )
        turns = [message for message in messages if message.role != "system"]
        turn_count = sum(message.role == "user" for message in turns)
        if current.total_tokens <= context_window_tokens and turn_count <= max_context_turns:
            return messages

        system_messages = [message for message in messages if message.role == "system"]
        history_messages = [message for message in messages if message.role != "system"]
        fixed = estimate_context_usage(
            messages=system_messages,
            tools=schemas,
            reserved_output=reserved_output_tokens,
        ).total_tokens
        history_budget = max(0, context_window_tokens - fixed)
        selected = trim_complete_turns(
            history_messages,
            token_budget=history_budget,
            max_turns=max_context_turns,
        )
        bounded = [*system_messages, *selected]
        try:
            validate_conversation(bounded)
        except ContractValidationError:
            raise ModelResponseError() from None
        final_usage = estimate_context_usage(
            messages=bounded,
            tools=schemas,
            reserved_output=reserved_output_tokens,
        )
        if final_usage.total_tokens > context_window_tokens:
            LOGGER.warning(
                "[agent_loop.py][AgentLoop._fit_model_context] 当前完整轮次仍超过上下文预算，"
                "request_id=%s，估算=%d，窗口=%d",
                request_id, final_usage.total_tokens, context_window_tokens,
            )
            raise RequestValidationError(reason="too_large", field="message")
        LOGGER.info(
            "[agent_loop.py][AgentLoop._fit_model_context] 本轮模型输入已按完整轮次裁剪，"
            "request_id=%s，估算 Token=%d，窗口=%d，消息数=%d→%d",
            request_id, final_usage.total_tokens, context_window_tokens,
            len(messages), len(bounded),
        )
        return bounded

    def _raise_total_timeout(self, request_id: str) -> None:
        """记录统一总超时日志并抛出稳定错误，不暴露正在处理的消息内容。"""
        LOGGER.warning(
            "[agent_loop.py][AgentLoop._raise_total_timeout] 模型工具循环达到总超时，"
            "request_id=%s，总超时=%.3f",
            request_id,
            self.total_timeout_seconds,
        )
        raise AgentLoopTimeoutError()

    def _validate_next(
        self,
        messages: Sequence[Message],
        message: Message,
        *,
        allow_pending: bool,
    ) -> None:
        """在落库和执行副作用前检查新消息能否接到当前统一对话末尾。"""
        try:
            validate_conversation(
                [*messages, message],
                allow_pending_tool_calls=allow_pending,
            )
        except ContractValidationError:
            LOGGER.warning(
                "[agent_loop.py][AgentLoop._validate_next] 模型消息破坏工具调用关联，role=%s",
                message.role,
            )
            raise ModelResponseError() from None

    async def _append(
        self,
        session_id: str,
        messages: Sequence[Message],
        *,
        request_id: str,
        stage: str,
    ) -> int | None:
        """按原始顺序保存循环消息；无仓储的离线测试模式只维护内存上下文。"""
        if self.sessions is None:
            LOGGER.info(
                "[agent_loop.py][AgentLoop._append] 无会话仓储，跳过循环消息落库，"
                "request_id=%s，stage=%s，消息数=%d",
                request_id,
                stage,
                len(messages),
            )
            return None
        records = await self.sessions.append(session_id, messages)
        LOGGER.info(
            "[agent_loop.py][AgentLoop._append] 循环消息已落库，"
            "request_id=%s，stage=%s，消息数=%d，起始序号=%d",
            request_id,
            stage,
            len(records),
            records[0].sequence,
        )
        return records[-1].sequence
