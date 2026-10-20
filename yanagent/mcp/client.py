"""模型上下文协议客户端——当前有意保留为空实现。"""

from dataclasses import dataclass
from typing import Any, Literal


Transport = Literal["stdio", "sse", "streamable_http"]


@dataclass(slots=True)
class MCPServerConfig:
    name: str
    transport: Transport
    command: list[str] | None = None
    url: str | None = None


class MCPClient:
    async def connect(self, config: MCPServerConfig) -> None:
        raise NotImplementedError("请实现安全的传输层启动和 MCP 初始化握手")

    async def list_tools(self, server_name: str) -> list[dict[str, Any]]:
        raise NotImplementedError("请实现支持分页的 tools/list")

    async def call_tool(self, server_name: str, tool_name: str, arguments: dict[str, Any]) -> Any:
        raise NotImplementedError("请实现支持超时和重连的 tools/call")

    async def close(self) -> None:
        raise NotImplementedError("请实现 HTTP 会话和子进程的关闭与清理")
