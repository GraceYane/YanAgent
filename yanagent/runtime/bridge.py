"""Runtime control plane -- deliberately not implemented."""

from yanagent.contracts import RunRequest, RunResult


class AgentBridge:
    """Route users, sessions and Agents to isolated runtime instances."""

    async def dispatch(self, request: RunRequest) -> RunResult:
        raise NotImplementedError("Implement session/Agent routing and runtime lifecycle")

    async def cancel(self, request_id: str) -> bool:
        raise NotImplementedError("Implement cooperative cancellation")
