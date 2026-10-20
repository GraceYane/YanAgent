"""多 Agent 与子 Agent 编排——当前有意保留为空实现。"""

from dataclasses import dataclass


@dataclass(slots=True)
class Delegation:
    parent_agent_id: str
    child_agent_id: str
    task: str
    depth: int


class MultiAgentCoordinator:
    async def delegate(self, delegation: Delegation) -> str:
        raise NotImplementedError("请实现有深度限制且上下文隔离的子 Agent 执行机制")

    async def route_mention(self, text: str, roster: list[str]) -> str | None:
        raise NotImplementedError("请准确解析显式 @Agent 指令，避免 Agent 身份混乱")
