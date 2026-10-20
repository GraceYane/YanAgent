"""Session and context storage -- deliberately not implemented."""

from collections.abc import Sequence

from yanagent.contracts import Message


class SessionStore:
    async def create(self, session_id: str, *, agent_id: str) -> None:
        raise NotImplementedError("Create sessions in a durable database")

    async def append(self, session_id: str, messages: Sequence[Message]) -> None:
        raise NotImplementedError("Append messages transactionally")

    async def history(self, session_id: str, *, limit: int = 100) -> list[Message]:
        raise NotImplementedError("Load ordered, isolated session history")

    async def context(self, session_id: str, *, token_budget: int) -> list[Message]:
        raise NotImplementedError("Trim/summarize context without splitting tool pairs")

    async def delete(self, session_id: str) -> None:
        raise NotImplementedError("Delete the session and dependent records")
