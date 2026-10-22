"""桌面会话接口适配：把内部仓储记录转换为复制界面的 JSON 契约。"""

from __future__ import annotations

import logging
import re
from typing import Any

from yanagent.sessions.store import SessionRecord, SessionStore, StoredMessage


LOGGER = logging.getLogger("yanagent.sessions.desktop")
TITLE_LENGTH = 30
PREVIEW_LENGTH = 60


def _seconds(milliseconds: int) -> float:
    """把 SQLite 使用的毫秒时间戳转换为桌面端使用的秒。"""
    return milliseconds / 1000


def _compact_text(value: str, maximum: int) -> str:
    """折叠空白并截断展示文本，避免标题和索引预览无限增长。"""
    normalized = re.sub(r"\s+", " ", value).strip()
    if len(normalized) <= maximum:
        return normalized
    return normalized[: maximum - 1] + "…"


class DesktopSessionService:
    """提供桌面所需的会话列表、历史、标题和删除操作。"""

    def __init__(self, store: SessionStore) -> None:
        """绑定一个已固定用户和 Agent 作用域的会话仓储。"""
        self.store = store

    async def list_sessions(self, *, page: int, page_size: int) -> dict[str, Any]:
        """返回桌面会话分页，并附上单 Agent 所有者标识。"""
        result = await self.store.list_sessions(page=page, page_size=page_size)
        return {
            "status": "success",
            "sessions": [self._session_payload(record) for record in result.sessions],
            "total": result.total,
            "page": result.page,
            "page_size": result.page_size,
            "has_more": result.has_more,
            "group_mode": "time",
            "project_order": [],
        }

    async def history(
        self,
        session_id: str,
        *,
        page: int,
        page_size: int,
        until_sequence: int | None,
    ) -> dict[str, Any]:
        """返回从最新页向前编号、页内按发生顺序排列的消息历史。"""
        result = await self.store.history_page(
            session_id,
            page=page,
            page_size=page_size,
            until_sequence=until_sequence,
        )
        return {
            "status": "success",
            "messages": [self._message_payload(record) for record in result.messages],
            "total": result.total,
            "page": result.page,
            "page_size": result.page_size,
            "has_more": result.has_more,
        }

    async def user_messages(self, session_id: str) -> dict[str, Any]:
        """返回会话中全部用户消息的轻量导航索引。"""
        records = await self.store.user_message_index(session_id)
        messages = [
            {
                "seq": record.sequence,
                "preview": _compact_text(record.message.content, PREVIEW_LENGTH),
                "created_at": _seconds(record.created_at),
            }
            for record in records
        ]
        return {"status": "success", "messages": messages, "total": len(messages)}

    async def rename(self, session_id: str, title: str) -> dict[str, Any]:
        """重命名指定会话并返回最终标题。"""
        record = await self.store.rename(session_id, title)
        return {"status": "success", "title": record.title}

    async def set_pinned(self, session_id: str, pinned: bool) -> dict[str, Any]:
        """修改指定会话的置顶状态。"""
        record = await self.store.set_pinned(session_id, pinned)
        return {"status": "success", "pinned": record.pinned}

    async def delete(self, session_id: str) -> dict[str, Any]:
        """删除指定会话及数据库外键关联的全部消息。"""
        await self.store.delete(session_id)
        return {"status": "success", "deleted": True}

    async def generate_title(self, session_id: str, user_message: str) -> dict[str, Any]:
        """从首条用户消息生成确定性标题，不额外消耗一次模型调用。"""
        title = _compact_text(user_message, TITLE_LENGTH) or "新对话"
        record = await self.store.upsert_title(session_id, title)
        LOGGER.info(
            "[desktop.py][DesktopSessionService.generate_title] 自动标题已保存，session_id=%s",
            session_id,
        )
        return {"status": "success", "title": record.title}

    async def delete_messages(
        self,
        session_id: str,
        user_sequence: int,
        *,
        delete_user: bool,
        cascade: bool,
    ) -> dict[str, Any]:
        """删除一轮消息；重新生成使用级联删除以丢弃受旧输入影响的后续上下文。"""
        deleted = await self.store.delete_turn(
            session_id,
            user_sequence,
            delete_user=delete_user,
            cascade=cascade,
        )
        return {"status": "success", "deleted": deleted}

    def _session_payload(self, record: SessionRecord) -> dict[str, Any]:
        """把内部会话摘要转换为桌面列表项。"""
        return {
            "session_id": record.session_id,
            "title": record.title,
            "created_at": _seconds(record.created_at),
            "last_active": _seconds(record.updated_at),
            "msg_count": record.message_count,
            "pinned": record.pinned,
            "agent": {"id": record.agent_id, "name": "YanAgent"},
        }

    def _message_payload(self, record: StoredMessage) -> dict[str, Any]:
        """把完整内部消息转换为桌面历史项并保留稳定序号。"""
        message = record.message
        payload: dict[str, Any] = {
            "role": message.role,
            "content": message.content,
            "created_at": _seconds(record.created_at),
            "_seq": record.sequence,
        }
        if message.tool_calls:
            payload["tool_calls"] = [call.to_dict() for call in message.tool_calls]
        usage = message.metadata.get("usage")
        if type(usage) is dict:
            payload["usage"] = usage
        return payload
