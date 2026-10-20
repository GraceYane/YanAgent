"""会话与上下文存储——当前有意保留为空实现。"""

from collections.abc import Sequence

from yanagent.contracts import Message


class SessionStore:
    async def create(self, session_id: str, *, agent_id: str) -> None:
        raise NotImplementedError("请在持久化数据库中实现会话创建")

    async def append(self, session_id: str, messages: Sequence[Message]) -> None:
        raise NotImplementedError("请实现以事务方式追加消息")

    async def history(self, session_id: str, *, limit: int = 100) -> list[Message]:
        raise NotImplementedError("请实现按顺序加载相互隔离的会话历史")

    async def context(self, session_id: str, *, token_budget: int) -> list[Message]:
        raise NotImplementedError("请实现上下文裁剪与摘要，并保证工具调用和结果不被拆散")

    async def delete(self, session_id: str) -> None:
        raise NotImplementedError("请实现删除会话及其关联记录")
