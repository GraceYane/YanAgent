"""Run 生命周期持久化：记录终态，并在进程重启时恢复遗留运行。"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from yanagent.errors import (
    AgentError,
    RunAlreadyExistsError,
    SessionNotFoundError,
    SessionStorageError,
    SessionValidationError,
)
from yanagent.storage import Database


LOGGER = logging.getLogger("yanagent.sessions.runs")
ActiveRunStatus = Literal["queued", "running"]
TerminalRunStatus = Literal["completed", "failed", "cancelled", "interrupted"]


@dataclass(frozen=True, slots=True)
class StoredRun:
    """一条持久化 Run，用于检查生命周期、用量和崩溃恢复结果。"""

    request_id: str
    user_id: str
    agent_id: str
    session_id: str
    parent_request_id: str | None
    status: str
    created_at: int
    started_at: int | None
    finished_at: int | None
    finish_reason: str | None
    error_code: str | None
    usage: dict[str, Any]
    metadata: dict[str, Any]


def _identifier(value: str, *, allow_none: bool = False) -> str | None:
    """校验 Run 和作用域标识，拒绝控制字符、首尾空白和异常长度。"""
    if allow_none and value is None:
        return None
    if (
        type(value) is not str
        or not value.strip()
        or value != value.strip()
        or len(value) > 256
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise SessionValidationError()
    return value


def _json_object(value: dict[str, Any]) -> str:
    """把 Run 扩展字段编码为严格 JSON 对象。"""
    if type(value) is not dict:
        raise SessionValidationError()
    try:
        return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    except (TypeError, ValueError, RecursionError):
        raise SessionValidationError() from None


def _decode_json_object(value: str | None) -> dict[str, Any]:
    """读取 Run JSON 对象，损坏记录统一转换为安全仓储错误。"""
    try:
        result = json.loads(value or "{}")
    except (TypeError, ValueError, RecursionError):
        raise SessionStorageError() from None
    if type(result) is not dict:
        raise SessionStorageError()
    return result


class RunStore:
    """在固定用户和 Agent 作用域内保存 Run，并恢复异常退出遗留状态。"""

    def __init__(
        self,
        database: Database,
        *,
        user_id: str,
        agent_id: str,
        clock: Callable[[], int] | None = None,
    ) -> None:
        """绑定可信归属和可测试时钟，调用方不能逐次伪造作用域。"""
        self.database = database
        self.user_id = str(_identifier(user_id))
        self.agent_id = str(_identifier(agent_id))
        self._clock = clock or (lambda: int(time.time() * 1000))

    async def create(
        self,
        request_id: str,
        session_id: str,
        *,
        status: ActiveRunStatus = "running",
        parent_request_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> StoredRun:
        """为已归属的 Session 创建 queued/running Run，重复 request_id 明确失败。"""
        if status not in {"queued", "running"}:
            raise SessionValidationError()
        selected_parent = (
            None
            if parent_request_id is None
            else str(_identifier(parent_request_id))
        )
        return await asyncio.to_thread(
            self._create_sync,
            str(_identifier(request_id)),
            str(_identifier(session_id)),
            status,
            selected_parent,
            _json_object({} if metadata is None else metadata),
        )

    async def finish(
        self,
        request_id: str,
        session_id: str,
        *,
        status: TerminalRunStatus,
        finish_reason: str | None = None,
        error_code: str | None = None,
        usage: dict[str, Any] | None = None,
    ) -> bool:
        """把当前作用域内的活动 Run 原子转为终态；不存在或已终态返回 False。"""
        if status not in {"completed", "failed", "cancelled", "interrupted"}:
            raise SessionValidationError()
        for value in (finish_reason, error_code):
            if value is not None and (
                type(value) is not str
                or len(value) > 256
                or any(ord(char) < 32 for char in value)
            ):
                raise SessionValidationError()
        return await asyncio.to_thread(
            self._finish_sync,
            str(_identifier(request_id)),
            str(_identifier(session_id)),
            status,
            finish_reason,
            error_code,
            None if usage is None else _json_object(usage),
        )

    async def get(self, request_id: str, session_id: str) -> StoredRun | None:
        """按用户、Agent、Session 和请求标识读取 Run，错误归属不可见。"""
        return await asyncio.to_thread(
            self._get_sync,
            str(_identifier(request_id)),
            str(_identifier(session_id)),
        )

    async def mark_running(self, request_id: str, session_id: str) -> bool:
        """在拿到 Session 锁后将持久化排队任务转成 running。"""
        return await asyncio.to_thread(self._mark_running_sync, request_id, session_id)

    def _mark_running_sync(self, request_id: str, session_id: str) -> bool:
        """按完整归属执行一次性 queued 到 running 转换。"""
        try:
            with self.database.transaction(immediate=True) as conn:
                return conn.execute(
                    "UPDATE runs SET status='running',started_at=? WHERE request_id=? AND user_id=? "
                    "AND agent_id=? AND session_id=? AND status='queued'",
                    (self._timestamp(), request_id, self.user_id, self.agent_id, session_id),
                ).rowcount == 1
        except sqlite3.Error:
            raise SessionStorageError() from None

    async def list_for_session(self, session_id: str) -> list[StoredRun]:
        """按创建顺序读取当前作用域会话的全部 Run，供历史过程恢复批量关联。"""
        return await asyncio.to_thread(
            self._list_for_session_sync,
            str(_identifier(session_id)),
        )

    async def queue_instruction(
        self, request_id: str, session_id: str, instruction_id: str, content: str,
    ) -> bool:
        """把运行中追加指令先写入 Run 元数据，供安全检查点注入。"""
        if type(content) is not str or not content.strip() or len(content) > 200_000:
            raise SessionValidationError()
        return await asyncio.to_thread(
            self._queue_instruction_sync,
            str(_identifier(request_id)), str(_identifier(session_id)),
            str(_identifier(instruction_id)), content,
        )

    async def finish_instruction(
        self,
        request_id: str,
        session_id: str,
        instruction_id: str,
        *,
        status: str,
        sequence: int | None = None,
    ) -> bool:
        """持久化追加指令已注入或因 Run 结束而未注入的状态。"""
        if status not in {"injected", "rejected"}:
            raise SessionValidationError()
        if sequence is not None and (type(sequence) is not int or sequence < 0):
            raise SessionValidationError()
        return await asyncio.to_thread(
            self._finish_instruction_sync,
            str(_identifier(request_id)), str(_identifier(session_id)),
            str(_identifier(instruction_id)), status, sequence,
        )

    def recover_unfinished_on_startup(self) -> int:
        """启动接流量前把当前作用域遗留的 queued/running Run 标记为 interrupted。"""
        timestamp = self._timestamp()
        try:
            with self.database.transaction(immediate=True) as connection:
                connection.execute(
                    "UPDATE run_steps SET status=CASE WHEN status='pending' THEN 'skipped' "
                    "WHEN kind='tool' THEN 'uncertain' ELSE 'failed' END,finished_at=?,"
                    "duration_ms=CASE WHEN started_at IS NULL THEN 0 ELSE MAX(0,?-started_at) END,"
                    "error_code='process_restarted' WHERE user_id=? AND agent_id=? "
                    "AND status IN ('pending','running') AND request_id IN "
                    "(SELECT request_id FROM runs WHERE user_id=? AND agent_id=? "
                    "AND status IN ('queued','running'))",
                    (timestamp, timestamp, self.user_id, self.agent_id, self.user_id, self.agent_id),
                )
                active = connection.execute(
                    "SELECT request_id,session_id,metadata_json FROM runs WHERE user_id=? "
                    "AND agent_id=? AND status IN ('queued','running')",
                    (self.user_id, self.agent_id),
                ).fetchall()
                for run in active:
                    metadata = _decode_json_object(run["metadata_json"])
                    instructions = metadata.get("run_instructions", [])
                    messages = connection.execute(
                        "SELECT sequence,metadata_json,role,tool_calls_json FROM messages WHERE user_id=? AND agent_id=? "
                        "AND session_id=? ORDER BY sequence", (self.user_id, self.agent_id, run["session_id"]),
                    ).fetchall()
                    injected = {
                        _decode_json_object(message["metadata_json"]).get("run_instruction_id"): message["sequence"]
                        for message in messages
                    }
                    for item in instructions:
                        if item.get("status") == "queued":
                            sequence = injected.get(item.get("instruction_id"))
                            item.update(status="injected" if sequence is not None else "rejected",
                                        sequence=sequence, recovery_reason="process_restarted")
                    connection.execute("UPDATE runs SET metadata_json=? WHERE request_id=?",
                                       (_json_object(metadata), run["request_id"]))
                    own = [m for m in messages if _decode_json_object(m["metadata_json"]).get("request_id") == run["request_id"]]
                    if own and own[-1]["role"] == "assistant" and not json.loads(own[-1]["tool_calls_json"] or "[]"):
                        connection.execute(
                            "UPDATE runs SET status='completed',finished_at=?,finish_reason='recovered_saved_answer',"
                            "error_code=NULL WHERE request_id=?", (timestamp, run["request_id"]),
                        )
                cursor = connection.execute(
                    "UPDATE runs SET status = 'interrupted', finished_at = ?, "
                    "finish_reason = 'process_restarted', error_code = 'run_interrupted' "
                    "WHERE user_id = ? AND agent_id = ? AND status IN ('queued', 'running')",
                    (timestamp, self.user_id, self.agent_id),
                )
                recovered = max(0, cursor.rowcount)
        except sqlite3.Error as error:
            self._log_storage_error("recover_unfinished_on_startup", error)
            raise SessionStorageError() from None
        LOGGER.info(
            "[runs.py][RunStore.recover_unfinished_on_startup] 启动恢复完成，"
            "user_id=%s，agent_id=%s，中断数量=%d",
            self.user_id,
            self.agent_id,
            recovered,
        )
        return recovered

    def _create_sync(
        self,
        request_id: str,
        session_id: str,
        status: ActiveRunStatus,
        parent_request_id: str | None,
        metadata_json: str,
    ) -> StoredRun:
        """同步创建 Run，并在同一事务内验证 Session 完整归属。"""
        timestamp = self._timestamp()
        try:
            with self.database.transaction(immediate=True) as connection:
                session = connection.execute(
                    "SELECT 1 FROM sessions WHERE user_id = ? AND agent_id = ? AND session_id = ?",
                    (self.user_id, self.agent_id, session_id),
                ).fetchone()
                if session is None:
                    raise SessionNotFoundError()
                connection.execute(
                    "INSERT INTO runs("
                    "request_id, user_id, agent_id, session_id, parent_request_id, status, "
                    "created_at, started_at, metadata_json"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        request_id,
                        self.user_id,
                        self.agent_id,
                        session_id,
                        parent_request_id,
                        status,
                        timestamp,
                        timestamp if status == "running" else None,
                        metadata_json,
                    ),
                )
                row = self._select_run(connection, request_id, session_id)
        except AgentError:
            raise
        except sqlite3.IntegrityError:
            raise RunAlreadyExistsError() from None
        except sqlite3.Error as error:
            self._log_storage_error("_create_sync", error)
            raise SessionStorageError() from None
        LOGGER.info(
            "[runs.py][RunStore._create_sync] Run 已创建，"
            "request_id=%s，session_id=%s，status=%s",
            request_id,
            session_id,
            status,
        )
        return self._run_from_row(row)

    def _finish_sync(
        self,
        request_id: str,
        session_id: str,
        status: TerminalRunStatus,
        finish_reason: str | None,
        error_code: str | None,
        usage_json: str | None,
    ) -> bool:
        """同步完成 Run，只允许当前作用域的活动状态发生一次终态转换。"""
        try:
            with self.database.transaction(immediate=True) as connection:
                cursor = connection.execute(
                    "UPDATE runs SET status = ?, finished_at = ?, finish_reason = ?, "
                    "error_code = ?, usage_json = COALESCE(?, usage_json) "
                    "WHERE request_id = ? AND user_id = ? AND agent_id = ? "
                    "AND session_id = ? AND status IN ('queued', 'running')",
                    (
                        status,
                        self._timestamp(),
                        finish_reason,
                        error_code,
                        usage_json,
                        request_id,
                        self.user_id,
                        self.agent_id,
                        session_id,
                    ),
                )
                changed = cursor.rowcount == 1
        except sqlite3.Error as error:
            self._log_storage_error("_finish_sync", error)
            raise SessionStorageError() from None
        if changed:
            LOGGER.info(
                "[runs.py][RunStore._finish_sync] Run 已进入终态，"
                "request_id=%s，status=%s，error_code=%s",
                request_id,
                status,
                error_code or "<无>",
            )
        return changed

    def _get_sync(self, request_id: str, session_id: str) -> StoredRun | None:
        """同步读取当前用户、Agent 和 Session 作用域内的一条 Run。"""
        try:
            with self.database.connection() as connection:
                row = self._select_run(connection, request_id, session_id)
        except sqlite3.Error as error:
            self._log_storage_error("_get_sync", error)
            raise SessionStorageError() from None
        return None if row is None else self._run_from_row(row)

    def _list_for_session_sync(self, session_id: str) -> list[StoredRun]:
        """同步批量读取一个会话的 Run，并继续使用完整用户与 Agent 归属过滤。"""
        try:
            with self.database.connection() as connection:
                session = connection.execute(
                    "SELECT 1 FROM sessions WHERE user_id = ? AND agent_id = ? "
                    "AND session_id = ?",
                    (self.user_id, self.agent_id, session_id),
                ).fetchone()
                if session is None:
                    raise SessionNotFoundError()
                rows = connection.execute(
                    "SELECT * FROM runs WHERE user_id = ? AND agent_id = ? "
                    "AND session_id = ? ORDER BY created_at ASC, request_id ASC",
                    (self.user_id, self.agent_id, session_id),
                ).fetchall()
        except AgentError:
            raise
        except sqlite3.Error as error:
            self._log_storage_error("_list_for_session_sync", error)
            raise SessionStorageError() from None
        runs = [self._run_from_row(row) for row in rows]
        LOGGER.info(
            "[runs.py][RunStore._list_for_session_sync] 会话 Run 批量读取完成，"
            "session_id=%s，数量=%d",
            session_id,
            len(runs),
        )
        return runs

    def _queue_instruction_sync(
        self, request_id: str, session_id: str, instruction_id: str, content: str,
    ) -> bool:
        """在单个事务内验证 Run 活动状态并保存追加指令。"""
        try:
            with self.database.transaction(immediate=True) as connection:
                row = connection.execute(
                    "SELECT metadata_json FROM runs WHERE request_id = ? AND user_id = ? "
                    "AND agent_id = ? AND session_id = ? AND status = 'running'",
                    (request_id, self.user_id, self.agent_id, session_id),
                ).fetchone()
                if row is None:
                    return False
                metadata = _decode_json_object(row["metadata_json"])
                instructions = metadata.setdefault("run_instructions", [])
                if type(instructions) is not list:
                    raise SessionStorageError()
                if any(
                    type(item) is dict and item.get("instruction_id") == instruction_id
                    for item in instructions
                ):
                    return False
                instructions.append({
                    "instruction_id": instruction_id,
                    "content": content,
                    "status": "queued",
                    "sequence": None,
                    "created_at": self._timestamp(),
                })
                connection.execute(
                    "UPDATE runs SET metadata_json = ? WHERE request_id = ? AND user_id = ? "
                    "AND agent_id = ? AND session_id = ? AND status = 'running'",
                    (
                        _json_object(metadata), request_id, self.user_id,
                        self.agent_id, session_id,
                    ),
                )
        except AgentError:
            raise
        except (sqlite3.Error, TypeError, ValueError, RecursionError) as error:
            self._log_storage_error("_queue_instruction_sync", error)
            raise SessionStorageError() from None
        LOGGER.info(
            "[runs.py][RunStore._queue_instruction_sync] 追加指令已持久化，request_id=%s，instruction_id=%s",
            request_id, instruction_id,
        )
        return True

    def _finish_instruction_sync(
        self,
        request_id: str,
        session_id: str,
        instruction_id: str,
        status: str,
        sequence: int | None,
    ) -> bool:
        """按完整 Run 归属更新追加指令状态和注入后的消息序号。"""
        try:
            with self.database.transaction(immediate=True) as connection:
                row = connection.execute(
                    "SELECT metadata_json FROM runs WHERE request_id = ? AND user_id = ? "
                    "AND agent_id = ? AND session_id = ?",
                    (request_id, self.user_id, self.agent_id, session_id),
                ).fetchone()
                if row is None:
                    return False
                metadata = _decode_json_object(row["metadata_json"])
                instructions = metadata.get("run_instructions", [])
                if type(instructions) is not list:
                    raise SessionStorageError()
                for item in instructions:
                    if type(item) is dict and item.get("instruction_id") == instruction_id:
                        item["status"] = status
                        item["sequence"] = sequence
                        connection.execute(
                            "UPDATE runs SET metadata_json = ? WHERE request_id = ? "
                            "AND user_id = ? AND agent_id = ? AND session_id = ?",
                            (
                                _json_object(metadata), request_id, self.user_id,
                                self.agent_id, session_id,
                            ),
                        )
                        return True
        except AgentError:
            raise
        except (sqlite3.Error, TypeError, ValueError, RecursionError) as error:
            self._log_storage_error("_finish_instruction_sync", error)
            raise SessionStorageError() from None
        return False

    def _select_run(
        self,
        connection: sqlite3.Connection,
        request_id: str,
        session_id: str,
    ) -> sqlite3.Row | None:
        """使用请求、用户、Agent 和 Session 四项条件查询，防止跨归属读取。"""
        return connection.execute(
            "SELECT * FROM runs WHERE request_id = ? AND user_id = ? AND agent_id = ? "
            "AND session_id = ?",
            (request_id, self.user_id, self.agent_id, session_id),
        ).fetchone()

    def _run_from_row(self, row: sqlite3.Row | None) -> StoredRun:
        """把 SQLite 行还原为不可变 Run 记录。"""
        if row is None:
            raise SessionStorageError()
        return StoredRun(
            request_id=str(row["request_id"]),
            user_id=str(row["user_id"]),
            agent_id=str(row["agent_id"]),
            session_id=str(row["session_id"]),
            parent_request_id=row["parent_request_id"],
            status=str(row["status"]),
            created_at=int(row["created_at"]),
            started_at=None if row["started_at"] is None else int(row["started_at"]),
            finished_at=None if row["finished_at"] is None else int(row["finished_at"]),
            finish_reason=row["finish_reason"],
            error_code=row["error_code"],
            usage=_decode_json_object(row["usage_json"]),
            metadata=_decode_json_object(row["metadata_json"]),
        )

    def _timestamp(self) -> int:
        """读取非负毫秒时间，拒绝测试时钟返回非法值。"""
        value = self._clock()
        if type(value) is not int or value < 0:
            raise SessionStorageError()
        return value

    @staticmethod
    def _log_storage_error(function_name: str, error: BaseException) -> None:
        """记录安全的 Run 仓储诊断，不写入消息、Usage 或数据库原文。"""
        LOGGER.error(
            "[runs.py][RunStore.%s] Run 数据库操作失败，异常类型=%s",
            function_name,
            type(error).__name__,
        )
