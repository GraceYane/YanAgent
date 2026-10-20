"""Model Context Protocol client -- deliberately not implemented."""

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
        raise NotImplementedError("Implement safe transport startup and MCP handshake")

    async def list_tools(self, server_name: str) -> list[dict[str, Any]]:
        raise NotImplementedError("Implement paginated tools/list")

    async def call_tool(self, server_name: str, tool_name: str, arguments: dict[str, Any]) -> Any:
        raise NotImplementedError("Implement tools/call with timeout and reconnect")

    async def close(self) -> None:
        raise NotImplementedError("Close HTTP sessions and child processes")
