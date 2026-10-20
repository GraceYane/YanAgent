"""Provider-neutral LLM interface -- deliberately not implemented."""

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
        raise NotImplementedError("Implement at least one concrete LLM provider")

    async def stream(self, messages: Sequence[Message], *, tools: Sequence[dict[str, Any]]):
        raise NotImplementedError("Implement normalized streaming")
        yield  # pragma: no cover
