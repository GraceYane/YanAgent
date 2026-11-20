"""Agent 运行时接口；流式 Runtime 延迟导入以避免与应用层形成循环依赖。"""

from __future__ import annotations

from typing import Any

from .agent_loop import AgentLoop, AgentLoopResult


__all__ = ["AgentBridge", "AgentLoop", "AgentLoopResult", "AgentRuntime", "RunRecord"]


def __getattr__(name: str) -> Any:
    """按需导出 Bridge 和运行引擎，避免聊天应用导入时形成循环依赖。"""
    if name == "AgentBridge":
        from .bridge import AgentBridge

        return AgentBridge
    if name in {"AgentRuntime", "RunRecord"}:
        from .streaming import AgentRuntime, RunRecord

        return {"AgentRuntime": AgentRuntime, "RunRecord": RunRecord}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
