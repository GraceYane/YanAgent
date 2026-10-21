"""与供应商无关的模型接口；非流式调用与流式增量分开实现。"""

from collections.abc import AsyncIterator, Sequence
from typing import Any, Protocol

from yanagent.contracts import Message, ModelReply


class ModelProvider(Protocol):
    """供 AgentLoop 使用的模型协议，调用方只接触内部消息和响应契约。"""

    name: str

    async def complete(
        self, messages: Sequence[Message], *, tools: Sequence[dict[str, Any]]
    ) -> ModelReply:
        """发送完整上下文和工具描述，返回一轮模型响应，不负责执行工具。"""
        ...

    def stream(
        self, messages: Sequence[Message], *, tools: Sequence[dict[str, Any]]
    ) -> AsyncIterator[dict[str, Any]]:
        """返回内部流式增量；事件格式和实现由 P01-05 补齐。"""
        ...


class NonStreamingProvider:
    """明确拒绝尚未实现的流式调用，供本阶段的真实和 Fake Provider 复用。"""

    async def stream(
        self, messages: Sequence[Message], *, tools: Sequence[dict[str, Any]] = ()
    ) -> AsyncIterator[dict[str, Any]]:
        """流式实现留到 P01-05，不用完整回答伪装成流式增量。"""
        raise NotImplementedError("流式模型调用将在 P01-05 实现")
        yield  # pragma: no cover - 保持异步生成器接口。


class UnimplementedModelProvider(NonStreamingProvider):
    """保留旧骨架占位入口，真实调用应使用 OpenAICompatibleProvider。"""

    name = "unimplemented"

    async def complete(self, messages: Sequence[Message], *, tools: Sequence[dict[str, Any]]) -> ModelReply:
        """显式拒绝使用未选定供应商的占位实例。"""
        raise NotImplementedError("请至少实现一个可用的大模型供应商")
