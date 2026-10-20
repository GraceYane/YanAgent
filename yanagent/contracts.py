"""Provider- and transport-neutral data contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


Role = Literal["system", "user", "assistant", "tool"]


@dataclass(slots=True)
class Message:
    role: Role
    content: str
    name: str | None = None
    tool_call_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(slots=True)
class ModelReply:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str | None = None
    usage: dict[str, int] = field(default_factory=dict)


@dataclass(slots=True)
class RunRequest:
    session_id: str
    user_message: str
    agent_id: str = "default"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class RunResult:
    content: str
    session_id: str
    turns: int
    usage: dict[str, int] = field(default_factory=dict)


@dataclass(slots=True)
class ToolResult:
    tool_call_id: str
    content: str
    is_error: bool = False
