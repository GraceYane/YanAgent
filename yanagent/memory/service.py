"""长期记忆处理链路——当前有意保留为空实现。"""

from dataclasses import dataclass


@dataclass(slots=True)
class MemoryHit:
    text: str
    score: float
    source: str


class MemoryService:
    async def remember(self, *, user_id: str, agent_id: str, text: str) -> None:
        raise NotImplementedError("请实现记忆提取、去重和持久化")

    async def search(self, *, user_id: str, agent_id: str, query: str, limit: int = 5) -> list[MemoryHit]:
        raise NotImplementedError("请实现混合检索与重排序")
