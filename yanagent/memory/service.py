"""Long-term memory pipeline -- deliberately not implemented."""

from dataclasses import dataclass


@dataclass(slots=True)
class MemoryHit:
    text: str
    score: float
    source: str


class MemoryService:
    async def remember(self, *, user_id: str, agent_id: str, text: str) -> None:
        raise NotImplementedError("Implement extraction, deduplication and persistence")

    async def search(self, *, user_id: str, agent_id: str, query: str, limit: int = 5) -> list[MemoryHit]:
        raise NotImplementedError("Implement hybrid retrieval and reranking")
