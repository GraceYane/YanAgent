"""非流式 Agent Loop：模型请求工具、执行并回写结果后继续调用模型。"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from yanagent.contracts import (
    ContractValidationError,
    Message,
    ModelReply,
    Usage,
    validate_conversation,
)
from yanagent.debug_log import yan_debug
from yanagent.errors import ModelResponseError, MultipleToolCallsUnsupportedError
from yanagent.models.provider import ModelProvider
from yanagent.sessions.store import SessionStore
from yanagent.tools.manager import ToolManager
from yanagent.tools.permissions import ToolPermissionContext


LOGGER = logging.getLogger("yanagent.agent_loop")

@dataclass(frozen=True, slots=True)
class AgentLoopResult:
    """保存一次非流式循环的最终模型回答、轮数、累计用量和消息序号。"""

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
    """执行供应商无关的非流式模型与单工具多轮闭环。"""

    def __init__(
        self,
        *,
        model: ModelProvider,
        tools: ToolManager,
        sessions: SessionStore | None,
    ) -> None:
        """注入当前 Run 的 Provider、应用级工具管理器和可选会话仓储。"""
        if not callable(getattr(model, "complete", None)):
            raise TypeError("model 必须实现 complete")
        if not isinstance(tools, ToolManager):
            raise TypeError("tools 必须是 ToolManager")
        if sessions is not None and not isinstance(sessions, SessionStore):
            raise TypeError("sessions 必须是 SessionStore 或 None")
        self.model = model
        self.tools = tools
        self.sessions = sessions

    async def run(
        self,
        *,
        messages: Sequence[Message],
        tool_schemas: Sequence[dict[str, Any]],
        session_id: str,
        request_id: str,
        permission_mode: str,
        permission_context: ToolPermissionContext,
    ) -> AgentLoopResult:
        """循环调用模型和工具，直到模型返回不含 ToolCall 的最终回答。"""
        selected_session = _identifier(session_id, "session_id")
        selected_request = _identifier(request_id, "request_id")
        if not isinstance(permission_context, ToolPermissionContext):
            raise TypeError("permission_context 必须是 ToolPermissionContext")
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
        turns = 0
        usage: Usage = {}

        LOGGER.info(
            "[agent_loop.py][AgentLoop.run] 非流式循环开始，"
            "request_id=%s，session_id=%s，初始消息数=%d，工具数=%d，权限模式=%s",
            selected_request,
            selected_session,
            len(working),
            len(schemas),
            permission_mode,
        )
        while True:
            yan_debug(
                "agent_loop.py",
                "AgentLoop.run",
                "准备发送非流式模型轮次",
                messages=working,
                tools=schemas,
            )
            reply = await self.model.complete(working, tools=schemas)
            yan_debug(
                "agent_loop.py",
                "AgentLoop.run",
                "收到非流式模型轮次回复",
                reply=reply,
            )
            turns += 1
            usage = _merge_usage(usage, reply.usage)
            LOGGER.info(
                "[agent_loop.py][AgentLoop.run] 模型轮次完成，"
                "request_id=%s，turn=%d，工具调用数=%d，文本字符数=%d",
                selected_request,
                turns,
                len(reply.tool_calls),
                len(reply.content),
            )

            if len(reply.tool_calls) > 1:
                LOGGER.warning(
                    "[agent_loop.py][AgentLoop.run] 当前阶段拒绝同轮多工具调用，"
                    "request_id=%s，turn=%d，工具调用数=%d",
                    selected_request,
                    turns,
                    len(reply.tool_calls),
                )
                raise MultipleToolCallsUnsupportedError()

            assistant = reply.to_message()
            assistant.metadata.update({
                "request_id": selected_request,
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
                    selected_session,
                    [assistant],
                    request_id=selected_request,
                    stage="final_assistant",
                )
                LOGGER.info(
                    "[agent_loop.py][AgentLoop.run] 非流式循环完成，"
                    "request_id=%s，turns=%d，累计用量字段=%s，assistant_sequence=%s",
                    selected_request,
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

            call = reply.tool_calls[0]
            await self._append(
                selected_session,
                [assistant],
                request_id=selected_request,
                stage="assistant_tool_call",
            )
            working.append(Message.from_dict(assistant.to_dict()))
            LOGGER.info(
                "[agent_loop.py][AgentLoop.run] Assistant 工具请求已保存，"
                "request_id=%s，turn=%d，call_id=%s，tool=%s",
                selected_request,
                turns,
                call.id,
                call.name,
            )

            result = await self.tools.execute(
                call,
                permission_mode=permission_mode,
                permission_context=permission_context,
            )
            tool_message = result.to_message()
            tool_message.name = call.name
            tool_message.metadata.update({
                "request_id": selected_request,
                "model_turn": turns,
                "tool_name": call.name,
            })
            self._validate_next(working, tool_message, allow_pending=False)
            await self._append(
                selected_session,
                [tool_message],
                request_id=selected_request,
                stage="tool_result",
            )
            working.append(Message.from_dict(tool_message.to_dict()))
            LOGGER.info(
                "[agent_loop.py][AgentLoop.run] Tool Result 已保存并回写模型上下文，"
                "request_id=%s，turn=%d，call_id=%s，tool=%s，is_error=%s，结果字符数=%d",
                selected_request,
                turns,
                call.id,
                call.name,
                result.is_error,
                len(result.content),
            )

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
