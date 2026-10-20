"""Multi-Agent and sub-agent orchestration -- deliberately not implemented."""

from dataclasses import dataclass


@dataclass(slots=True)
class Delegation:
    parent_agent_id: str
    child_agent_id: str
    task: str
    depth: int


class MultiAgentCoordinator:
    async def delegate(self, delegation: Delegation) -> str:
        raise NotImplementedError("Implement bounded, isolated sub-agent execution")

    async def route_mention(self, text: str, roster: list[str]) -> str | None:
        raise NotImplementedError("Resolve an explicit @Agent without identity confusion")
