"""显式恢复任务：重建完整消息、继承写操作保护并创建有父 Run 的新任务。"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import uuid
from typing import Any

from yanagent.contracts import Message, ToolCall, ToolResult, validate_conversation
from yanagent.errors import (
    RecoveryAcknowledgementRequiredError, RunRecoveryError, SessionStorageError,
)
from yanagent.sessions.executions import ExecutionStore, tool_fingerprint
from yanagent.sessions.runs import RunStore, _decode_json_object, _json_object
from yanagent.sessions.store import SessionStore


LOGGER = logging.getLogger("yanagent.recovery")


class RecoveryService:
    """在单 Session 调度锁内核对恢复资格，保守处理不确定副作用。"""

    def __init__(self, runs: RunStore, sessions: SessionStore, executions: ExecutionStore) -> None:
        """绑定同身份的 Run、消息和执行步骤仓储。"""
        self.runs = runs
        self.sessions = sessions
        self.executions = executions

    async def reconcile_messages(self, session_id: str) -> None:
        """只补齐尾部缺失的工具结果；使用日志中的已知结果，不调用任何 handler。"""
        records = await self.sessions.complete_history(session_id)
        pending: dict[str, tuple[ToolCall, str]] = {}
        for record in records:
            message = record.message
            if message.role == "tool":
                pending.pop(message.tool_call_id, None)
            else:
                if pending:
                    raise SessionStorageError()
                for call in message.tool_calls:
                    pending[call.id] = (call, str(message.metadata.get("request_id", "")))
        if not pending:
            return
        steps = await self.executions.list_steps(session_id)
        by_call = {step["data"]["call"]["id"]: step for step in steps if step["kind"] == "tool"}
        repaired = []
        for call, original_request in pending.values():
            step = by_call.get(call.id)
            state = "uncertain" if step is None else step["status"]
            if step is not None and state == "completed" and "result" in step["data"]:
                result = ToolResult.from_dict(step["data"]["result"])
            else:
                text = (
                    "该调用未进入工具执行函数，原任务已结束，本次没有执行。"
                    if state in {"pending", "skipped"} else
                    "该调用没有可验证的完成结果，可能已经产生副作用。禁止自动重做，请用户核对外部结果。"
                )
                result = ToolResult(tool_call_id=call.id, content=text, is_error=True)
            message = result.to_message()
            message.name = call.name
            message.metadata.update({
                "request_id": original_request, "recovered_tool_result": True,
                "execution_state": state, "fingerprint": tool_fingerprint(call),
                "read_only": False if step is None else step["data"].get("read_only", False),
            })
            repaired.append(message)
        validate_conversation([*(r.message for r in records), *repaired])
        await self.sessions.append(session_id, repaired)
        LOGGER.warning("[recovery.py][RecoveryService.reconcile_messages] 已补齐尾部工具结果且未执行工具，session_id=%s，数量=%d",
                       session_id, len(repaired))

    async def guard_seed(self, session_id: str, source_id: str | None = None) -> tuple[dict, dict]:
        """恢复任务继承祖先写操作保护；所有新任务都保护未解决的不确定写操作。"""
        chain: set[str] = set()
        current = source_id
        while current:
            if current in chain or len(chain) >= 100:
                raise RunRecoveryError()
            chain.add(current)
            run = await self.runs.get(current, session_id)
            if run is None:
                raise RunRecoveryError()
            current = run.parent_request_id
        attempts, results = {}, {}
        for step in await self.executions.list_steps(session_id):
            data = step["data"]
            if step["kind"] != "tool" or data.get("read_only"):
                continue
            if step["status"] in {"running", "uncertain"} or (
                step["request_id"] in chain and step["status"] == "completed"
            ):
                fingerprint = data["fingerprint"]
                attempts[fingerprint] = 1
                if step["status"] == "completed" and "result" in data:
                    results[fingerprint] = ToolResult.from_dict(data["result"])
                else:
                    results[fingerprint] = ToolResult(
                        tool_call_id=data["call"]["id"], is_error=True,
                        content="此前写操作结果不确定，须人工核对；不得自动重做。",
                    )
        # 旧版本没有执行日志时，也保护恢复消息明确标注的不确定写调用。
        for record in await self.sessions.complete_history(session_id):
            meta = record.message.metadata
            if meta.get("execution_state") == "uncertain" and not meta.get("read_only"):
                fingerprint = meta.get("fingerprint")
                if isinstance(fingerprint, str):
                    attempts[fingerprint] = 1
                    results[fingerprint] = ToolResult(
                        tool_call_id=record.message.tool_call_id or "unknown", is_error=True,
                        content="历史调用结果不确定，须人工核对。",
                    )
        return attempts, results

    async def describe(self, session_id: str, request_id: str) -> dict[str, Any]:
        """返回有作用域限制的任务诊断、用量、步骤与可用恢复动作。"""
        run = await self.runs.get(request_id, session_id)
        if run is None:
            raise RunRecoveryError()
        steps = await self.executions.list_steps(session_id, request_id)
        latest = await asyncio.to_thread(self._latest_sync, session_id)
        eligible = (latest == request_id and run.status in {"failed", "cancelled", "interrupted"}
                    and not run.metadata.get("recovered_by"))
        unknown = [s for s in steps if s["kind"] == "tool" and s["status"] in {"running", "uncertain"}
                   and not s["data"].get("read_only")]
        history = await self.sessions.complete_history(session_id)
        pending = {}
        for record in history:
            if record.message.role == "tool":
                pending.pop(record.message.tool_call_id, None)
            else:
                pending.update({c.id: record.message.metadata.get("request_id") for c in record.message.tool_calls})
        known = {s["data"]["call"]["id"] for s in steps if s["kind"] == "tool"}
        legacy_unknown = any(owner == request_id and call_id not in known for call_id, owner in pending.items())
        requires_ack = bool(unknown) or legacy_unknown
        # 已补齐的旧版不确定调用也需要核对确认。
        requires_ack = requires_ack or any(
            r.message.metadata.get("request_id") == request_id
            and r.message.metadata.get("execution_state") == "uncertain"
            and not r.message.metadata.get("read_only") for r in history
        )
        return {
            "status": "success", "request_id": request_id, "session_id": session_id,
            "run_status": run.status, "parent_request_id": run.parent_request_id,
            "error_code": run.error_code, "finish_reason": run.finish_reason, "usage": run.usage,
            "duration_ms": None if run.started_at is None or run.finished_at is None
                else max(0, run.finished_at - run.started_at),
            "steps": [{key: value for key, value in step.items() if key not in {"data_json", "usage_json"}}
                      for step in steps],
            "can_continue": eligible, "can_retry": eligible and not requires_ack,
            "requires_acknowledgement": requires_ack,
            "recovered_by": run.metadata.get("recovered_by"),
        }

    def _latest_sync(self, session_id: str) -> str | None:
        """按实际插入顺序确定最新 Run，避免同毫秒时间戳产生歧义。"""
        try:
            with self.runs.database.connection() as conn:
                row = conn.execute(
                    "SELECT request_id FROM runs WHERE user_id=? AND agent_id=? AND session_id=? "
                    "ORDER BY rowid DESC LIMIT 1", (self.runs.user_id, self.runs.agent_id, session_id),
                ).fetchone()
                return None if row is None else row[0]
        except sqlite3.Error:
            raise SessionStorageError() from None

    async def claim(self, session_id: str, source_id: str, child_id: str, mode: str,
                    acknowledged: bool, metadata: dict) -> None:
        """恢复前核对不确定操作，并在一个事务内登记子 Run 及来源占用。"""
        plan = await self.describe(session_id, source_id)
        if not plan["can_continue"] or mode not in {"continue", "retry"}:
            raise RunRecoveryError()
        if plan["requires_acknowledgement"] and (not acknowledged or mode == "retry"):
            raise RecoveryAcknowledgementRequiredError()
        await self.reconcile_messages(session_id)
        await asyncio.to_thread(self._claim_sync, session_id, source_id, child_id, mode, acknowledged, metadata)

    def _claim_sync(self, session_id, source_id, child_id, mode, acknowledged, metadata) -> None:
        """原子检查最新 Run 与一次性恢复资格，防止双击重复创建任务。"""
        now = self.runs._timestamp()
        try:
            with self.runs.database.transaction(immediate=True) as conn:
                source = self.runs._select_run(conn, source_id, session_id)
                latest = conn.execute(
                    "SELECT request_id FROM runs WHERE user_id=? AND agent_id=? AND session_id=? "
                    "ORDER BY rowid DESC LIMIT 1", (self.runs.user_id, self.runs.agent_id, session_id),
                ).fetchone()
                if source is None or latest is None or latest[0] != source_id:
                    raise RunRecoveryError()
                previous = _decode_json_object(source["metadata_json"])
                if source["status"] not in {"failed", "interrupted", "cancelled"} or previous.get("recovered_by"):
                    raise RunRecoveryError()
                previous["recovered_by"] = child_id
                conn.execute("UPDATE runs SET metadata_json=? WHERE request_id=?",
                             (_json_object(previous), source_id))
                child_metadata = {**metadata, "recovery_mode": mode, "acknowledged_uncertain": acknowledged}
                conn.execute(
                    "INSERT INTO runs(request_id,user_id,agent_id,session_id,parent_request_id,status,"
                    "created_at,started_at,metadata_json) VALUES(?,?,?,?,?,'running',?,?,?)",
                    (child_id, self.runs.user_id, self.runs.agent_id, session_id, source_id,
                     now, now, _json_object(child_metadata)),
                )
                last = conn.execute(
                    "SELECT COALESCE(MAX(sequence),-1) FROM messages WHERE user_id=? AND agent_id=? AND session_id=?",
                    (self.runs.user_id, self.runs.agent_id, session_id),
                ).fetchone()[0]
                added = 1
                has_input = any(
                    _decode_json_object(row[0]).get("request_id") == source_id
                    for row in conn.execute("SELECT metadata_json FROM messages WHERE user_id=? AND agent_id=? AND session_id=?",
                        (self.runs.user_id, self.runs.agent_id, session_id)).fetchall()
                )
                if not has_input and isinstance(previous.get("queued_message"), str):
                    conn.execute(
                        "INSERT INTO messages(message_id,user_id,agent_id,session_id,sequence,role,content,"
                        "created_at,metadata_json) VALUES(?,?,?,?,?,'user',?,?,?)",
                        (uuid.uuid4().hex, self.runs.user_id, self.runs.agent_id, session_id, last + 1,
                         previous["queued_message"], now, _json_object({"request_id": source_id,
                             "recovered_queued_input": True})),
                    )
                    last += 1
                    added += 1
                conn.execute(
                    "INSERT INTO messages(message_id,user_id,agent_id,session_id,sequence,role,content,"
                    "created_at,metadata_json) VALUES(?,?,?,?,?,'user',?,?,?)",
                    (uuid.uuid4().hex, self.runs.user_id, self.runs.agent_id, session_id, last + 1,
                     metadata["recovery_message"], now, _json_object({"request_id": child_id,
                         "recovery_source": source_id, "recovery_mode": mode})),
                )
                conn.execute(
                    "UPDATE sessions SET message_count=message_count+?,updated_at=? "
                    "WHERE user_id=? AND agent_id=? AND session_id=?",
                    (added, now, self.runs.user_id, self.runs.agent_id, session_id),
                )
        except sqlite3.Error:
            raise SessionStorageError() from None
        LOGGER.info("[recovery.py][RecoveryService._claim_sync] 显式恢复已创建子任务，source=%s，child=%s，模式=%s",
                    source_id, child_id, mode)
