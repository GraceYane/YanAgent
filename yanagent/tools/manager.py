"""Tool registry, validation and execution -- deliberately not implemented."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from yanagent.contracts import ToolCall, ToolResult


ToolHandler = Callable[[dict[str, Any]], Awaitable[str]]


@dataclass(slots=True)
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler
    requires_confirmation: bool = False


class ToolManager:
    def register(self, definition: ToolDefinition) -> None:
        raise NotImplementedError("Implement duplicate-safe tool registration")

    def schemas(self) -> list[dict[str, Any]]:
        raise NotImplementedError("Export provider-neutral JSON schemas")

    async def execute(self, call: ToolCall, *, permission_mode: str) -> ToolResult:
        raise NotImplementedError("Validate arguments, permissions, timeout and result size")
