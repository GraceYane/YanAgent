"""工具注册、参数校验与执行——当前有意保留为空实现。"""

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
        raise NotImplementedError("请实现能够防止工具重名的注册机制")

    def schemas(self) -> list[dict[str, Any]]:
        raise NotImplementedError("请导出与模型供应商无关的 JSON Schema")

    async def execute(self, call: ToolCall, *, permission_mode: str) -> ToolResult:
        raise NotImplementedError("请实现参数、权限、超时和结果大小校验")
