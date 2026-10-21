"""与供应商无关的模型接口；非流式调用与流式增量分开实现。"""

from collections.abc import AsyncIterator, Sequence
from typing import Any, Protocol

from yanagent.contracts import Message, ModelReply
from yanagent.events import ModelStreamEvent


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
    ) -> AsyncIterator[ModelStreamEvent]:
        """返回类型化模型增量，最后必须产生且只产生一个完成事件。"""
        ...


class NonStreamingProvider:
    """供只支持完整响应的实现复用，明确拒绝流式入口。"""

    async def stream(
        self, messages: Sequence[Message], *, tools: Sequence[dict[str, Any]] = ()
    ) -> AsyncIterator[ModelStreamEvent]:
        """不把完整回答伪装成增量，调用方可据此拒绝错误配置。"""
        raise NotImplementedError("当前 Provider 不支持流式模型调用")
        yield  # pragma: no cover - 保持异步生成器接口。


class UnimplementedModelProvider(NonStreamingProvider):
    """保留旧骨架占位入口，真实调用应使用 OpenAICompatibleProvider。"""

    name = "unimplemented"

    async def complete(self, messages: Sequence[Message], *, tools: Sequence[dict[str, Any]]) -> ModelReply:
        """显式拒绝使用未选定供应商的占位实例。"""
        raise NotImplementedError("请至少实现一个可用的大模型供应商")
