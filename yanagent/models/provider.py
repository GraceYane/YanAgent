"""与供应商无关的统一大模型接口——当前有意保留为空实现。"""

from collections.abc import AsyncIterator, Sequence
from typing import Any, Protocol

from yanagent.contracts import Message, ModelReply


class ModelProvider(Protocol):
    name: str

    async def complete(
        self, messages: Sequence[Message], *, tools: Sequence[dict[str, Any]]
    ) -> ModelReply: ...

    def stream(
        self, messages: Sequence[Message], *, tools: Sequence[dict[str, Any]]
    ) -> AsyncIterator[dict[str, Any]]: ...


class UnimplementedModelProvider:
    name = "unimplemented"

    async def complete(self, messages: Sequence[Message], *, tools: Sequence[dict[str, Any]]) -> ModelReply:
        raise NotImplementedError("请至少实现一个可用的大模型供应商")

    async def stream(self, messages: Sequence[Message], *, tools: Sequence[dict[str, Any]]):
        raise NotImplementedError("请实现统一格式的流式响应")
        yield  # pragma: no cover - 仅用于保持异步生成器接口
