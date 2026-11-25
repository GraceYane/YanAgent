"""模型尝试与工具执行日志：先登记后执行，保留可恢复结果与不确定副作用。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import sqlite3
import uuid
from typing import Any

from yanagent.contracts import ToolCall, ToolResult
from yanagent.errors import SessionStorageError
from yanagent.sessions.runs import RunStore, _identifier, _json_object, _decode_json_object


LOGGER = logging.getLogger("yanagent.executions")


def tool_fingerprint(call: ToolCall) -> str:
    """按工具名和规范 JSON 参数生成跨重启稳定的操作指纹。"""
    raw = json.dumps([call.name, call.arguments], sort_keys=True, ensure_ascii=False,
                     separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class ExecutionStore:
    """使用 RunStore 的可信身份范围事务性记录模型请求及工具步骤。"""

    def __init__(self, runs: RunStore) -> None:
        """复用 Run 仓储的数据库、时钟和作用域。"""
        self.runs = runs
        self.database = runs.database
        self.user_id = runs.user_id
        self.agent_id = runs.agent_id

    async def list_steps(self, session_id: str, request_id: str | None = None) -> list[dict[str, Any]]:
        """按完整身份读取步骤；支持单 Run 查询及当前 Session 的恢复保护。"""
        return await asyncio.to_thread(self._list_sync, str(_identifier(session_id)), request_id)

    def _list_sync(self, session_id: str, request_id: str | None) -> list[dict[str, Any]]:
        """同步读取并解析步骤，失败不暴露 SQL 或工具正文。"""
        try:
            with self.database.connection() as conn:
                rows = conn.execute(
                    "SELECT * FROM run_steps WHERE user_id=? AND agent_id=? AND session_id=? "
                    + ("AND request_id=? " if request_id is not None else "")
                    + "ORDER BY created_at, rowid",
                    (self.user_id, self.agent_id, session_id)
                    + ((str(_identifier(request_id)),) if request_id is not None else ()),
                ).fetchall()
            return [{**dict(row), "data": _decode_json_object(row["data_json"]),
                     "usage": _decode_json_object(row["usage_json"])} for row in rows]
        except sqlite3.Error:
            raise SessionStorageError() from None

    async def plan_tools(self, request_id: str, session_id: str, calls: list[ToolCall], tools) -> None:
        """在调用任何 handler 前持久化同轮所有工具意图。"""
        entries = []
        for call in calls:
            definition = tools.get(call.name)
            entries.append((self.tool_step_id(request_id, call.id), "tool", {
                "call": call.to_dict(), "fingerprint": tool_fingerprint(call),
                "read_only": definition is not None and definition.read_only,
            }, "pending"))
        await asyncio.to_thread(self._insert_sync, request_id, session_id, entries)

    @staticmethod
    def tool_step_id(request_id: str, call_id: str) -> str:
        """根据 Run 和调用 ID 定位工具步骤，避免恢复时重复登记。"""
        return hashlib.sha256(f"{request_id}\0{call_id}".encode()).hexdigest()

    async def start_model(self, request_id: str, session_id: str, attempt: int) -> str:
        """每次真实模型请求前登记一个独立尝试，包括自动重试。"""
        step_id = uuid.uuid4().hex
        await asyncio.to_thread(self._insert_sync, request_id, session_id,
                                [(step_id, "model", {"attempt": attempt}, "running")])
        return step_id

    def _insert_sync(self, request_id: str, session_id: str, entries: list) -> None:
        """验证活动 Run 归属后批量写入步骤；失败时禁止继续执行。"""
        now = self.runs._timestamp()
        try:
            with self.database.transaction(immediate=True) as conn:
                row = self.runs._select_run(conn, request_id, session_id)
                if row is None or row["status"] != "running":
                    raise SessionStorageError()
                for step_id, kind, data, status in entries:
                    conn.execute(
                        "INSERT INTO run_steps(step_id,request_id,user_id,agent_id,session_id,kind,"
                        "status,created_at,started_at,data_json) VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (step_id, request_id, self.user_id, self.agent_id, session_id, kind,
                         status, now, now if status == "running" else None, _json_object(data)),
                    )
        except sqlite3.Error:
            raise SessionStorageError() from None
        LOGGER.info("[executions.py][ExecutionStore._insert_sync] 步骤已持久化，request_id=%s，数量=%d",
                    request_id, len(entries))

    async def start_tool(self, request_id: str, call_id: str) -> None:
        """权限与预算通过后，在真正进入 handler 前标记执行中。"""
        await asyncio.to_thread(self._start_tool_sync, self.tool_step_id(request_id, call_id))

    def _start_tool_sync(self, step_id: str) -> None:
        """只允许 pending 工具进入 running，阻止重复使用同一步骤。"""
        try:
            with self.database.transaction(immediate=True) as conn:
                changed = conn.execute(
                    "UPDATE run_steps SET status='running',started_at=? WHERE step_id=? "
                    "AND user_id=? AND agent_id=? AND status='pending'",
                    (self.runs._timestamp(), step_id, self.user_id, self.agent_id),
                ).rowcount
                if changed != 1:
                    raise SessionStorageError()
        except sqlite3.Error:
            raise SessionStorageError() from None

    async def finish(self, step_id: str, *, result: ToolResult | None = None,
                     usage: dict | None = None, error_code: str | None = None,
                     duration_ms: int = 0, details: dict | None = None) -> None:
        """保存模型用量或工具结果；已进入 handler 的失败保守视为不确定。"""
        await asyncio.to_thread(self._finish_sync, step_id, result, usage, error_code, duration_ms, details)

    def _finish_sync(self, step_id: str, result, usage, error_code, duration_ms: int, details=None) -> None:
        """事务性结束步骤并累计已知模型用量，重复结束不重复计费。"""
        try:
            with self.database.transaction(immediate=True) as conn:
                row = conn.execute("SELECT * FROM run_steps WHERE step_id=? AND user_id=? AND agent_id=?",
                                   (step_id, self.user_id, self.agent_id)).fetchone()
                if row is None:
                    raise SessionStorageError()
                if row["status"] not in {"pending", "running"}:
                    return
                data = _decode_json_object(row["data_json"])
                if details:
                    data.update({k: v for k, v in details.items() if k in {'provider', 'model', 'fallback_transitions'}})
                if row["kind"] == "tool":
                    if result is not None:
                        data["result"] = result.to_dict()
                    status = ("completed" if result is not None and not result.is_error else
                              "uncertain" if row["status"] == "running" else "skipped")
                    error_code = error_code or ("tool_execution_uncertain" if status == "uncertain"
                                                else "tool_not_executed" if status == "skipped" else None)
                else:
                    status = "failed" if error_code else "completed"
                conn.execute(
                    "UPDATE run_steps SET status=?,finished_at=?,duration_ms=?,error_code=?,"
                    "data_json=?,usage_json=? WHERE step_id=?",
                    (status, self.runs._timestamp(), max(0, duration_ms), error_code,
                     _json_object(data), _json_object(usage or {}), step_id),
                )
                if row["kind"] == "model" and usage:
                    run = self.runs._select_run(conn, row["request_id"], row["session_id"])
                    total = _decode_json_object(run["usage_json"])
                    for name, value in usage.items():
                        total[name] = (None if value is None or (name in total and total[name] is None)
                                       else total.get(name, 0) + value)
                    conn.execute("UPDATE runs SET usage_json=? WHERE request_id=?",
                                 (_json_object(total), row["request_id"]))
        except sqlite3.Error:
            raise SessionStorageError() from None
        LOGGER.info("[executions.py][ExecutionStore._finish_sync] 步骤结束，step_id=%s，状态=%s，耗时毫秒=%d，错误码=%s",
                    step_id, status, duration_ms, error_code or "无")

    async def set_initial_usage(self, request_id: str, session_id: str, usage: dict) -> None:
        """在模型循环启动前保存摘要等准备阶段已知用量。"""
        await asyncio.to_thread(self._initial_sync, request_id, session_id, usage)

    def _initial_sync(self, request_id: str, session_id: str, usage: dict) -> None:
        """只在无步骤用量时初始化，防止重复执行覆盖已有记录。"""
        try:
            with self.database.transaction(immediate=True) as conn:
                conn.execute("UPDATE runs SET usage_json=? WHERE request_id=? AND user_id=? "
                             "AND agent_id=? AND session_id=? AND usage_json IS NULL",
                             (_json_object(usage), request_id, self.user_id, self.agent_id, session_id))
        except sqlite3.Error:
            raise SessionStorageError() from None

    async def close_active(self, request_id: str, session_id: str) -> None:
        """Run 退出时补齐遗留步骤状态；不执行或回滚任何外部副作用。"""
        await asyncio.to_thread(self._close_sync, request_id, session_id)

    def _close_sync(self, request_id: str, session_id: str) -> None:
        """把未启动意图标为 skipped，执行中工具标为 uncertain。"""
        try:
            with self.database.transaction(immediate=True) as conn:
                conn.execute(
                    "UPDATE run_steps SET status=CASE WHEN status='pending' THEN 'skipped' "
                    "WHEN kind='tool' THEN 'uncertain' ELSE 'failed' END,finished_at=?,"
                    "duration_ms=CASE WHEN started_at IS NULL THEN 0 ELSE MAX(0,?-started_at) END,"
                    "error_code='run_ended_before_step_finished' WHERE request_id=? "
                    "AND user_id=? AND agent_id=? AND session_id=? AND status IN ('pending','running')",
                    (self.runs._timestamp(), self.runs._timestamp(), request_id, self.user_id, self.agent_id, session_id),
                )
        except sqlite3.Error:
            raise SessionStorageError() from None
