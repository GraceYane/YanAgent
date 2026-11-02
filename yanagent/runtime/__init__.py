"""Agent 运行时接口；流式 Runtime 延迟导入以避免与应用层形成循环依赖。"""

from __future__ import annotations

from typing import Any

from .agent_loop import AgentLoop, AgentLoopResult


__all__ = ["AgentLoop", "AgentLoopResult", "AgentRuntime", "RunRecord"]


def __getattr__(name: str) -> Any:
    """按需导出流式 Runtime，同时让聊天应用可直接复用非流式 AgentLoop。"""
    if name in {"AgentRuntime", "RunRecord"}:
        from .streaming import AgentRuntime, RunRecord

        return {"AgentRuntime": AgentRuntime, "RunRecord": RunRecord}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
