"""无需密钥或网络的确定性 Provider，用于后续循环与失败路径验收。"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import AsyncIterator, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from yanagent.contracts import Message, ModelReply
from yanagent.errors import AgentError
from yanagent.events import ModelStreamEvent
from .openai_compatible import prepare_request
from .provider import NonStreamingProvider


@dataclass
class ProviderCall:
    """一次 Fake 调用的输入快照；不包含配置或密钥。"""

    messages: list[Message]
    tools: list[dict[str, Any]]


class FakeProviderExhaustedError(AgentError):
    """标识测试预设已耗尽，避免重复最后一个回答而掩盖多调用缺陷。"""

    code = "fake_provider_exhausted"
    message = "Fake Provider 的预设响应已耗尽，请检查调用次数或补充测试预设。"


class FakeProvider(NonStreamingProvider):
    """依序返回完整或流式预设，并保留每轮独立输入记录。"""

    name = "fake"

    def __init__(
        self,
        outcomes: Sequence[ModelReply | AgentError],
        *,
        stream_outcomes: Sequence[Sequence[ModelStreamEvent | AgentError]] = (),
    ) -> None:
        """复制两类预设；仅接受内部契约或统一错误，不接收真实凭据。"""
        self._outcomes: deque[ModelReply | AgentError] = deque()
        for outcome in outcomes:
            if isinstance(outcome, ModelReply):
                self._outcomes.append(ModelReply.from_dict(outcome.to_dict()))
            elif isinstance(outcome, AgentError):
                self._outcomes.append(outcome)
            else:
                raise TypeError("Fake 预设必须是 ModelReply 或 AgentError")
        self._calls: list[ProviderCall] = []
        self._stream_outcomes: deque[list[ModelStreamEvent | AgentError]] = deque()
        for stream in stream_outcomes:
            copied: list[ModelStreamEvent | AgentError] = []
            for outcome in stream:
                if isinstance(outcome, ModelStreamEvent):
                    copied.append(deepcopy(outcome))
                elif isinstance(outcome, AgentError):
                    copied.append(outcome)
                else:
                    raise TypeError("Fake 流预设必须是 ModelStreamEvent 或 AgentError")
            self._stream_outcomes.append(copied)

    @property
    def calls(self) -> list[ProviderCall]:
        """返回调用记录副本，外部断言或修改不会污染内部快照。"""
        return deepcopy(self._calls)

    @property
    def remaining(self) -> int:
        """返回尚未消费的预设数量，用于验证调用轮数。"""
        return len(self._outcomes)

    @property
    def remaining_streams(self) -> int:
        """返回尚未消费的流式预设数量，用于验证调用轮数。"""
        return len(self._stream_outcomes)

    async def complete(
        self, messages: Sequence[Message], *, tools: Sequence[dict[str, Any]] = (),
    ) -> ModelReply:
        """有效输入消费一个预设；错误预设也占一轮，非法输入不消耗。"""
        prepare_request(messages, tools)
        self._calls.append(ProviderCall(deepcopy(list(messages)), deepcopy(list(tools))))
        if not self._outcomes:
            raise FakeProviderExhaustedError()
        outcome = self._outcomes.popleft()
        if isinstance(outcome, AgentError):
            raise outcome from None
        return ModelReply.from_dict(outcome.to_dict())

    async def stream(
        self, messages: Sequence[Message], *, tools: Sequence[dict[str, Any]] = (),
    ) -> AsyncIterator[ModelStreamEvent]:
        """依序产出一条流预设；取消会在下一个异步检查点立即生效。"""
        prepare_request(messages, tools)
        self._calls.append(ProviderCall(deepcopy(list(messages)), deepcopy(list(tools))))
        if not self._stream_outcomes:
            raise FakeProviderExhaustedError()
        outcomes = self._stream_outcomes.popleft()
        for outcome in outcomes:
            # 即使预设立即可得也让出执行权，使并发和取消测试接近真实流。
            await asyncio.sleep(0)
            if isinstance(outcome, AgentError):
                raise outcome from None
            yield deepcopy(outcome)
