"""基于 SQLite 的会话与完整消息仓储。"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import time
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from yanagent.contracts import ContractValidationError, Message
from yanagent.errors import (
    AgentError,
    SessionAlreadyExistsError,
    SessionNotFoundError,
    SessionStorageError,
    SessionValidationError,
)
from yanagent.storage import Database


LOGGER = logging.getLogger("yanagent.sessions")
MAX_TITLE_LENGTH = 200
MAX_PAGE_SIZE = 100
MAX_HISTORY_LIMIT = 500


@dataclass(frozen=True, slots=True)
class SessionRecord:
    """一条会话摘要，包含归属、排序字段、消息数量和扩展元数据。"""

    user_id: str
    agent_id: str
    session_id: str
    title: str
    pinned: bool
    created_at: int
    updated_at: int
    message_count: int
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class SessionPage:
    """会话分页结果；total 是当前用户与 Agent 范围内的总数。"""

    sessions: list[SessionRecord]
    total: int
    page: int
    page_size: int
    has_more: bool


@dataclass(frozen=True, slots=True)
class StoredMessage:
    """持久化消息及其稳定序号，序号只在所属会话内递增。"""

    message_id: str
    user_id: str
    agent_id: str
    session_id: str
    sequence: int
    created_at: int
    message: Message


def _identifier(value: str) -> str:
    """校验会话作用域标识，拒绝空白和异常超长值。"""
    if (
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or len(value) > 256
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise SessionValidationError()
    return value


def _title(value: str, *, allow_empty: bool) -> str:
    """校验会话标题；创建时允许空标题，重命名时不允许。"""
    if not isinstance(value, str) or len(value) > MAX_TITLE_LENGTH:
        raise SessionValidationError()
    normalized = value.strip()
    if not allow_empty and not normalized:
        raise SessionValidationError()
    return normalized


def _json_object(value: dict[str, Any]) -> str:
    """将扩展元数据编码为严格 JSON 对象。"""
    if type(value) is not dict:
        raise SessionValidationError()
    try:
        return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    except (TypeError, ValueError, RecursionError):
        raise SessionValidationError() from None


def _decode_json_object(value: str) -> dict[str, Any]:
    """读取数据库中的 JSON 对象；损坏数据统一视为仓储错误。"""
    try:
        result = json.loads(value)
    except (TypeError, ValueError, RecursionError):
        raise SessionStorageError() from None
    if type(result) is not dict:
        raise SessionStorageError()
    return result


class SessionStore:
    """在固定用户与 Agent 作用域内管理会话和消息，阻塞 I/O 在线程执行。"""

    def __init__(
        self,
        database: Database,
        *,
        user_id: str,
        agent_id: str,
        clock: Callable[[], int] | None = None,
        message_id_factory: Callable[[], str] | None = None,
    ) -> None:
        """绑定数据库和可信作用域；后续方法不再接收可伪造的用户归属。"""
        self.database = database
        self.user_id = _identifier(user_id)
        self.agent_id = _identifier(agent_id)
        self._clock = clock or (lambda: int(time.time() * 1000))
        self._message_id_factory = message_id_factory or (lambda: uuid.uuid4().hex)

    async def create(
        self,
        session_id: str,
        *,
        title: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> SessionRecord:
        """创建一条空会话；同一作用域内重复标识会明确失败。"""
        selected_id = _identifier(session_id)
        selected_title = _title(title, allow_empty=True)
        metadata_json = _json_object({} if metadata is None else metadata)
        return await asyncio.to_thread(
            self._create_sync, selected_id, selected_title, metadata_json
        )

    async def get(self, session_id: str) -> SessionRecord:
        """读取当前作用域内的一条会话，不泄露其他用户是否存在同名会话。"""
        return await asyncio.to_thread(self._get_sync, _identifier(session_id))

    async def list_sessions(self, *, page: int = 1, page_size: int = 20) -> SessionPage:
        """按置顶、更新时间和会话标识稳定分页列出会话。"""
        if type(page) is not int or page < 1:
            raise SessionValidationError()
        if type(page_size) is not int or not 1 <= page_size <= MAX_PAGE_SIZE:
            raise SessionValidationError()
        return await asyncio.to_thread(self._list_sync, page, page_size)

    async def rename(self, session_id: str, title: str) -> SessionRecord:
        """修改标题并刷新更新时间，保留原有元数据和消息。"""
        return await asyncio.to_thread(
            self._update_session_sync,
            _identifier(session_id),
            "title",
            _title(title, allow_empty=False),
        )

    async def set_pinned(self, session_id: str, pinned: bool) -> SessionRecord:
        """设置置顶状态并刷新更新时间，确保列表排序立即生效。"""
        if type(pinned) is not bool:
            raise SessionValidationError()
        return await asyncio.to_thread(
            self._update_session_sync,
            _identifier(session_id),
            "pinned",
            int(pinned),
        )

    async def append(
        self, session_id: str, messages: Sequence[Message]
    ) -> list[StoredMessage]:
        """在一个立即事务内追加整批消息，任意一条失败则全部回滚。"""
        selected_id = _identifier(session_id)
        if not isinstance(messages, (list, tuple)) or not messages:
            raise SessionValidationError()
        try:
            copied = [Message.from_dict(message.to_dict()) for message in messages]
        except (AttributeError, ContractValidationError, TypeError):
            raise SessionValidationError() from None
        return await asyncio.to_thread(self._append_sync, selected_id, copied)

    async def history(
        self,
        session_id: str,
        *,
        limit: int = 100,
        before_sequence: int | None = None,
    ) -> list[StoredMessage]:
        """按升序返回最近消息；游标为排他的会话内序号。"""
        selected_id = _identifier(session_id)
        if type(limit) is not int or not 1 <= limit <= MAX_HISTORY_LIMIT:
            raise SessionValidationError()
        if before_sequence is not None and (
            type(before_sequence) is not int or before_sequence < 0
        ):
            raise SessionValidationError()
        return await asyncio.to_thread(
            self._history_sync, selected_id, limit, before_sequence
        )

    async def context(self, session_id: str, *, token_budget: int) -> list[Message]:
        """P02-03 才实现历史到模型上下文的选择，本阶段不提前伪装完成。"""
        raise NotImplementedError("P02-03 将实现历史到模型上下文的转换")

    async def delete(self, session_id: str) -> None:
        """删除当前作用域内的会话，关联消息由数据库外键级联删除。"""
        await asyncio.to_thread(self._delete_sync, _identifier(session_id))

    def _create_sync(
        self, session_id: str, title: str, metadata_json: str
    ) -> SessionRecord:
        """同步创建会话并读取规范化结果。"""
        timestamp = self._timestamp()
        try:
            with self.database.transaction(immediate=True) as connection:
                connection.execute(
                    "INSERT INTO sessions("
                    "user_id, agent_id, session_id, title, pinned, created_at, updated_at, "
                    "metadata_json, message_count) VALUES (?, ?, ?, ?, 0, ?, ?, ?, 0)",
                    (
                        self.user_id,
                        self.agent_id,
                        session_id,
                        title,
                        timestamp,
                        timestamp,
                        metadata_json,
                    ),
                )
                row = self._select_session(connection, session_id)
        except sqlite3.IntegrityError:
            raise SessionAlreadyExistsError() from None
        except sqlite3.Error as error:
            self._log_storage_error("_create_sync", error)
            raise SessionStorageError() from None
        LOGGER.info(
            "[store.py][SessionStore._create_sync] 会话创建成功，user_id=%s，agent_id=%s，session_id=%s",
            self.user_id,
            self.agent_id,
            session_id,
        )
        return self._session_from_row(row)

    def _get_sync(self, session_id: str) -> SessionRecord:
        """同步读取会话。"""
        try:
            with self.database.connection() as connection:
                row = self._select_session(connection, session_id)
        except sqlite3.Error as error:
            self._log_storage_error("_get_sync", error)
            raise SessionStorageError() from None
        if row is None:
            raise SessionNotFoundError()
        return self._session_from_row(row)

    def _list_sync(self, page: int, page_size: int) -> SessionPage:
        """同步执行作用域内的稳定分页查询。"""
        offset = (page - 1) * page_size
        try:
            with self.database.connection() as connection:
                total = int(
                    connection.execute(
                        "SELECT COUNT(*) FROM sessions WHERE user_id = ? AND agent_id = ?",
                        (self.user_id, self.agent_id),
                    ).fetchone()[0]
                )
                rows = connection.execute(
                    "SELECT * FROM sessions WHERE user_id = ? AND agent_id = ? "
                    "ORDER BY pinned DESC, updated_at DESC, session_id ASC LIMIT ? OFFSET ?",
                    (self.user_id, self.agent_id, page_size, offset),
                ).fetchall()
        except sqlite3.Error as error:
            self._log_storage_error("_list_sync", error)
            raise SessionStorageError() from None
        return SessionPage(
            sessions=[self._session_from_row(row) for row in rows],
            total=total,
            page=page,
            page_size=page_size,
            has_more=offset + len(rows) < total,
        )

    def _update_session_sync(
        self, session_id: str, field: str, value: str | int
    ) -> SessionRecord:
        """同步更新允许的会话字段；字段名只由内部白名单传入。"""
        if field not in {"title", "pinned"}:
            raise SessionValidationError()
        try:
            with self.database.transaction(immediate=True) as connection:
                cursor = connection.execute(
                    f"UPDATE sessions SET {field} = ?, updated_at = ? "
                    "WHERE user_id = ? AND agent_id = ? AND session_id = ?",
                    (value, self._timestamp(), self.user_id, self.agent_id, session_id),
                )
                if cursor.rowcount != 1:
                    raise SessionNotFoundError()
                row = self._select_session(connection, session_id)
        except AgentError:
            raise
        except sqlite3.Error as error:
            self._log_storage_error("_update_session_sync", error)
            raise SessionStorageError() from None
        LOGGER.info(
            "[store.py][SessionStore._update_session_sync] 会话属性已更新，session_id=%s，field=%s",
            session_id,
            field,
        )
        return self._session_from_row(row)

    def _append_sync(
        self, session_id: str, messages: list[Message]
    ) -> list[StoredMessage]:
        """同步追加一批消息并分配连续序号。"""
        records: list[StoredMessage] = []
        try:
            with self.database.transaction(immediate=True) as connection:
                if self._select_session(connection, session_id) is None:
                    raise SessionNotFoundError()
                row = connection.execute(
                    "SELECT MAX(sequence) FROM messages "
                    "WHERE user_id = ? AND agent_id = ? AND session_id = ?",
                    (self.user_id, self.agent_id, session_id),
                ).fetchone()
                first_sequence = 0 if row[0] is None else int(row[0]) + 1
                for index, message in enumerate(messages):
                    sequence = first_sequence + index
                    message_id = _identifier(self._message_id_factory())
                    created_at = self._timestamp()
                    connection.execute(
                        "INSERT INTO messages("
                        "message_id, user_id, agent_id, session_id, sequence, role, content, "
                        "tool_calls_json, tool_call_id, name, created_at, metadata_json, is_error"
                        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            message_id,
                            self.user_id,
                            self.agent_id,
                            session_id,
                            sequence,
                            message.role,
                            message.content,
                            json.dumps(
                                [call.to_dict() for call in message.tool_calls],
                                ensure_ascii=False,
                                allow_nan=False,
                                separators=(",", ":"),
                            ),
                            message.tool_call_id,
                            message.name,
                            created_at,
                            _json_object(message.metadata),
                            int(message.is_error),
                        ),
                    )
                    records.append(
                        StoredMessage(
                            message_id=message_id,
                            user_id=self.user_id,
                            agent_id=self.agent_id,
                            session_id=session_id,
                            sequence=sequence,
                            created_at=created_at,
                            message=Message.from_dict(message.to_dict()),
                        )
                    )
                connection.execute(
                    "UPDATE sessions SET message_count = message_count + ?, updated_at = ? "
                    "WHERE user_id = ? AND agent_id = ? AND session_id = ?",
                    (
                        len(messages),
                        self._timestamp(),
                        self.user_id,
                        self.agent_id,
                        session_id,
                    ),
                )
        except AgentError:
            raise
        except (sqlite3.Error, TypeError, ValueError, RecursionError) as error:
            self._log_storage_error("_append_sync", error)
            raise SessionStorageError() from None
        LOGGER.info(
            "[store.py][SessionStore._append_sync] 消息批次提交成功，session_id=%s，数量=%d，起始序号=%d",
            session_id,
            len(records),
            records[0].sequence,
        )
        return records

    def _history_sync(
        self, session_id: str, limit: int, before_sequence: int | None
    ) -> list[StoredMessage]:
        """同步读取最近一页历史，查询倒序取最近项后恢复为升序。"""
        try:
            with self.database.connection() as connection:
                if self._select_session(connection, session_id) is None:
                    raise SessionNotFoundError()
                parameters: list[Any] = [self.user_id, self.agent_id, session_id]
                cursor_clause = ""
                if before_sequence is not None:
                    cursor_clause = " AND sequence < ?"
                    parameters.append(before_sequence)
                parameters.append(limit)
                rows = connection.execute(
                    "SELECT * FROM messages WHERE user_id = ? AND agent_id = ? "
                    f"AND session_id = ?{cursor_clause} "
                    "ORDER BY sequence DESC LIMIT ?",
                    parameters,
                ).fetchall()
        except AgentError:
            raise
        except sqlite3.Error as error:
            self._log_storage_error("_history_sync", error)
            raise SessionStorageError() from None
        records = [self._message_from_row(row) for row in reversed(rows)]
        LOGGER.info(
            "[store.py][SessionStore._history_sync] 历史读取完成，session_id=%s，返回数量=%d",
            session_id,
            len(records),
        )
        return records

    def _delete_sync(self, session_id: str) -> None:
        """同步删除会话并依赖外键级联清理消息。"""
        try:
            with self.database.transaction(immediate=True) as connection:
                cursor = connection.execute(
                    "DELETE FROM sessions WHERE user_id = ? AND agent_id = ? AND session_id = ?",
                    (self.user_id, self.agent_id, session_id),
                )
                if cursor.rowcount != 1:
                    raise SessionNotFoundError()
        except AgentError:
            raise
        except sqlite3.Error as error:
            self._log_storage_error("_delete_sync", error)
            raise SessionStorageError() from None
        LOGGER.info(
            "[store.py][SessionStore._delete_sync] 会话及关联记录已删除，session_id=%s",
            session_id,
        )

    def _select_session(
        self, connection: sqlite3.Connection, session_id: str
    ) -> sqlite3.Row | None:
        """按完整作用域查询会话，避免仅凭 session_id 越权读取。"""
        return connection.execute(
            "SELECT * FROM sessions WHERE user_id = ? AND agent_id = ? AND session_id = ?",
            (self.user_id, self.agent_id, session_id),
        ).fetchone()

    def _session_from_row(self, row: sqlite3.Row | None) -> SessionRecord:
        """将 SQLite 行转换为不可变会话摘要。"""
        if row is None:
            raise SessionNotFoundError()
        return SessionRecord(
            user_id=str(row["user_id"]),
            agent_id=str(row["agent_id"]),
            session_id=str(row["session_id"]),
            title=str(row["title"]),
            pinned=bool(row["pinned"]),
            created_at=int(row["created_at"]),
            updated_at=int(row["updated_at"]),
            message_count=int(row["message_count"]),
            metadata=_decode_json_object(str(row["metadata_json"])),
        )

    def _message_from_row(self, row: sqlite3.Row) -> StoredMessage:
        """将 SQLite 行还原为完整内部 Message，保留工具和失败语义。"""
        try:
            tool_calls = json.loads(str(row["tool_calls_json"] or "[]"))
            message = Message.from_dict(
                {
                    "role": str(row["role"]),
                    "content": str(row["content"]),
                    "name": row["name"],
                    "tool_call_id": row["tool_call_id"],
                    "metadata": _decode_json_object(str(row["metadata_json"])),
                    "tool_calls": tool_calls,
                    "is_error": bool(row["is_error"]),
                }
            )
        except (TypeError, ValueError, RecursionError, ContractValidationError):
            raise SessionStorageError() from None
        return StoredMessage(
            message_id=str(row["message_id"]),
            user_id=str(row["user_id"]),
            agent_id=str(row["agent_id"]),
            session_id=str(row["session_id"]),
            sequence=int(row["sequence"]),
            created_at=int(row["created_at"]),
            message=message,
        )

    def _timestamp(self) -> int:
        """读取可测试时钟并拒绝负数或非整数时间戳。"""
        value = self._clock()
        if type(value) is not int or value < 0:
            raise SessionStorageError()
        return value

    @staticmethod
    def _log_storage_error(function_name: str, error: BaseException) -> None:
        """记录可定位但不含 SQL 参数、消息正文和凭据的安全日志。"""
        LOGGER.error(
            "[store.py][SessionStore.%s] 会话数据库操作失败，异常类型=%s",
            function_name,
            type(error).__name__,
        )
