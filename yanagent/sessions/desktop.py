"""桌面会话接口适配：把内部仓储记录转换为复制界面的 JSON 契约。"""

from __future__ import annotations

import logging
import re
from typing import Any

from yanagent.errors import SessionValidationError
from yanagent.sessions.runs import RunStore, StoredRun
from yanagent.sessions.store import (
    MAX_PAGE_SIZE,
    SessionRecord,
    SessionStore,
    StoredMessage,
)


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

    def __init__(
        self,
        store: SessionStore,
        *,
        run_store: RunStore | None = None,
    ) -> None:
        """绑定同一可信作用域的消息与 Run 仓储，后者用于解释未完成工具轮次。"""
        if not isinstance(store, SessionStore):
            raise TypeError("store 必须是 SessionStore")
        if run_store is not None and not isinstance(run_store, RunStore):
            raise TypeError("run_store 必须是 RunStore 或 None")
        if run_store is not None and (
            run_store.user_id != store.user_id or run_store.agent_id != store.agent_id
        ):
            raise ValueError("消息仓储与 Run 仓储必须属于同一用户和 Agent")
        self.store = store
        self.run_store = run_store

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
        """把原始消息聚合为桌面轮次，并按聚合结果从最新页向前稳定分页。"""
        if type(page) is not int or page < 1:
            raise SessionValidationError()
        if type(page_size) is not int or not 1 <= page_size <= MAX_PAGE_SIZE:
            raise SessionValidationError()
        if until_sequence is not None and (
            type(until_sequence) is not int or until_sequence < 0
        ):
            raise SessionValidationError()

        records = await self.store.complete_history(session_id)
        runs = (
            await self.run_store.list_for_session(session_id)
            if self.run_store is not None
            else []
        )
        runs_by_request = {run.request_id: run for run in runs}
        messages = [
            payload
            for group in self._turn_groups(records)
            for payload in self._turn_payloads(group, runs_by_request)
        ]
        represented = {record.message.metadata.get("request_id") for record in records}
        for run in runs:
            queued_text = run.metadata.get("queued_message")
            if run.request_id in represented or not isinstance(queued_text, str) or run.status == "completed":
                continue
            # 排队任务尚未写 User Message 时，也能在重启后的历史中定位与恢复。
            messages.append({"role": "user", "content": queued_text, "created_at": _seconds(run.created_at)})
            messages.extend(self._attach_run_diagnostics([{
                "role": "assistant", "content": "", "created_at": _seconds(run.created_at),
                "steps": [], "run_state": self._unfinished_run_state(run),
            }], run))
        selected_page = page
        if until_sequence is not None:
            target_index = next(
                (
                    index
                    for index, payload in enumerate(messages)
                    if payload.get("_seq") == until_sequence
                ),
                None,
            )
            if target_index is not None:
                distance_from_latest = len(messages) - target_index
                selected_page = max(
                    selected_page,
                    (distance_from_latest + page_size - 1) // page_size,
                )

        if until_sequence is None:
            end = max(0, len(messages) - (selected_page - 1) * page_size)
            start = max(0, end - page_size)
        else:
            end = len(messages)
            start = max(0, end - selected_page * page_size)
        selected = messages[start:end]
        LOGGER.info(
            "[desktop.py][DesktopSessionService.history] 桌面历史已聚合，"
            "session_id=%s，原始消息数=%d，桌面消息数=%d，返回数=%d，page=%d",
            session_id,
            len(records),
            len(messages),
            len(selected),
            selected_page,
        )
        return {
            "status": "success",
            "messages": selected,
            "total": len(messages),
            "page": selected_page,
            "page_size": page_size,
            "has_more": start > 0,
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
        if message.role == 'assistant':
            payload['finish_reason'] = message.metadata.get('finish_reason')
            reasoning = message.metadata.get('reasoning')
            if type(reasoning) is str and reasoning:
                payload['steps'] = [{'type': 'thinking', 'content': reasoning}]
        return payload

    def _turn_groups(self, records: list[StoredMessage]) -> list[list[StoredMessage]]:
        """按用户消息切分完整历史，使一个模型工具循环在分页和展示时不可拆开。"""
        groups: list[list[StoredMessage]] = []
        for record in records:
            if record.message.role == "user" or not groups:
                groups.append([record])
            else:
                groups[-1].append(record)
        return groups

    def _turn_payloads(
        self,
        records: list[StoredMessage],
        runs_by_request: dict[str, StoredRun],
    ) -> list[dict[str, Any]]:
        """把一轮原始 User/Assistant/Tool 消息还原为用户气泡和一个过程气泡。"""
        if not records:
            return []
        request_id = self._request_id(records)
        run = runs_by_request.get(request_id) if request_id is not None else None
        user = records[0] if records[0].message.role == "user" else None
        process = records[1:] if user is not None else records
        has_tool_process = any(
            record.message.role == "tool" or bool(record.message.tool_calls)
            for record in process
        )
        payloads = [] if user is None else [self._message_payload(user)]
        if has_tool_process:
            payloads.append(self._tool_process_payload(process, run))
            return self._attach_run_diagnostics(payloads, run)
        if process:
            payloads.extend(self._message_payload(record) for record in process)
            return self._attach_run_diagnostics(payloads, run)
        run_state = self._unfinished_run_state(run)
        if run_state is not None:
            payloads.append(self._empty_run_payload(records[0], run, run_state))
        return self._attach_run_diagnostics(payloads, run)

    def _attach_run_diagnostics(self, payloads: list[dict[str, Any]], run: StoredRun | None) -> list[dict[str, Any]]:
        """给过程气泡附加 Run 定位、已知用量和耗时，让重启后的失败可诊断。"""
        if run is None:
            return payloads
        for payload in payloads:
            if payload.get("role") != "assistant":
                continue
            payload["run_id"] = run.request_id
            payload["recovery_available"] = run.status in {"failed", "cancelled", "interrupted"} and not run.metadata.get("recovered_by")
            payload["run_error_code"] = run.error_code
            payload.setdefault("usage", run.usage)
            payload["duration_ms"] = (None if run.started_at is None or run.finished_at is None else
                                      max(0, run.finished_at - run.started_at))
        return payloads

    def _request_id(self, records: list[StoredMessage]) -> str | None:
        """读取一轮受信元数据中的请求标识，忽略旧数据里的空值或非字符串。"""
        for record in records:
            value = record.message.metadata.get("request_id")
            if type(value) is str and value:
                return value
        return None

    def _unfinished_run_state(self, run: StoredRun | None) -> str | None:
        """把内部 Run 状态收敛为桌面可解释的 running 或 interrupted。"""
        if run is None or run.status == "completed":
            return None
        if run.status in {"queued", "running"}:
            return "running"
        return "interrupted"

    def _empty_run_payload(
        self,
        anchor: StoredMessage,
        run: StoredRun | None,
        run_state: str,
    ) -> dict[str, Any]:
        """为尚无 Assistant 消息的活动或失败 Run 生成稳定的状态气泡。"""
        cancelled = run is not None and run.status == "cancelled"
        return {
            "role": "assistant",
            "content": "_(Cancelled by user)_" if cancelled else "",
            "created_at": _seconds(anchor.created_at),
            "_seq": anchor.sequence,
            "steps": [],
            **({} if cancelled else {"run_state": run_state}),
        }

    def _tool_process_payload(
        self,
        records: list[StoredMessage],
        run: StoredRun | None,
    ) -> dict[str, Any]:
        """聚合多轮 Assistant ToolCall、Tool Result 和最终文本为桌面步骤。"""
        if not records:
            raise ValueError("工具过程至少需要一条消息")
        steps: list[dict[str, Any]] = []
        calls: dict[str, int] = {}
        final_content = ""
        usage: dict[str, Any] | None = None
        has_final_answer = False

        for record in records:
            message = record.message
            if message.role == "assistant":
                reasoning = message.metadata.get('reasoning')
                if type(reasoning) is str and reasoning:
                    steps.append({'type': 'thinking', 'content': reasoning})
                if message.tool_calls:
                    if message.content.strip():
                        steps.append({"type": "content", "content": message.content})
                    for call in message.tool_calls:
                        calls[call.id] = len(steps)
                        steps.append({
                            "type": "tool",
                            "id": call.id,
                            "name": call.name,
                            "arguments": call.arguments,
                            "status": "running",
                        })
                else:
                    final_content = message.content
                    has_final_answer = True
                    if message.content:
                        steps.append({"type": "content", "content": message.content})
                    current_usage = message.metadata.get("usage")
                    if type(current_usage) is dict:
                        usage = current_usage
            elif message.role == "tool":
                call_id = message.tool_call_id or ""
                index = calls.get(call_id)
                if index is None:
                    index = len(steps)
                    calls[call_id] = index
                    steps.append({
                        "type": "tool",
                        "id": call_id,
                        "name": message.name or "unknown_tool",
                        "arguments": {},
                    })
                step = steps[index]
                step["result"] = message.content
                step["is_error"] = message.is_error
                step["status"] = "error" if message.is_error else "success"
                execution_time = message.metadata.get("execution_time")
                if type(execution_time) in (int, float) and execution_time >= 0:
                    step["execution_time"] = execution_time

        run_state = None if has_final_answer else self._unfinished_run_state(run)
        if not has_final_answer and run_state is None:
            run_state = "interrupted"
        cancelled = (
            not has_final_answer
            and run is not None
            and run.status == "cancelled"
        )
        for step in steps:
            if step.get("type") != "tool" or step.get("status") != "running":
                continue
            if run_state == "running":
                continue
            step["status"] = "error"
            step["is_error"] = True
            step["result"] = (
                "运行已取消，工具没有留下完成结果。"
                if cancelled
                else "运行已中断，工具没有留下可验证的完成结果。"
            )

        payload: dict[str, Any] = {
            "role": "assistant",
            "content": "_(Cancelled by user)_" if cancelled else final_content,
            "created_at": _seconds(records[0].created_at),
            "_seq": records[-1].sequence,
            "steps": steps,
            "finish_reason": next((record.message.metadata.get('finish_reason') for record in reversed(records)
                                   if record.message.role == 'assistant'), None),
        }
        if usage is not None:
            payload["usage"] = usage
        if run_state is not None and not cancelled:
            payload["run_state"] = run_state
        return payload
