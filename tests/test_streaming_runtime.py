"""P01-05 常驻运行时、事件隔离、取消和终态清理测试。"""

from __future__ import annotations

import asyncio
import tempfile
import threading
import time
import unittest
from collections.abc import AsyncIterator, Sequence
from pathlib import Path
from typing import Any

from yanagent.chat import YanAgentApplication
from yanagent.config import ConfigStore
from yanagent.contracts import Message, ModelReply, ToolCall
from yanagent.events import ModelStreamEvent
from yanagent.models import FakeProvider
from yanagent.runtime import AgentRuntime
from yanagent.sessions import RunStore, SessionStore
from yanagent.storage import Database


class EchoStreamingProvider:
    """按用户输入生成可交错的确定性字符流，用于验证运行隔离。"""

    name = "echo-stream"

    async def complete(
        self, messages: Sequence[Message], *, tools: Sequence[dict[str, Any]] = (),
    ) -> ModelReply:
        """返回完整回声，满足统一 Provider 协议。"""
        return ModelReply(content=messages[-1].content)

    async def stream(
        self, messages: Sequence[Message], *, tools: Sequence[dict[str, Any]] = (),
    ) -> AsyncIterator[ModelStreamEvent]:
        """逐字符让出执行权并以完成事件收尾。"""
        content = messages[-1].content
        for char in content:
            await asyncio.sleep(0.001)
            yield ModelStreamEvent(kind="text_delta", content=char)
        yield ModelStreamEvent(kind="completed", reply=ModelReply(
            content=content, finish_reason="stop",
        ))


class BlockingStreamingProvider(EchoStreamingProvider):
    """发出首个字符后阻塞，供取消和清理路径测试。"""

    def __init__(self) -> None:
        """建立跨线程可观察的取消标记。"""
        self.cancelled = threading.Event()

    async def stream(
        self, messages: Sequence[Message], *, tools: Sequence[dict[str, Any]] = (),
    ) -> AsyncIterator[ModelStreamEvent]:
        """在无限等待的 finally 中记录任务确已收到取消。"""
        yield ModelStreamEvent(kind="text_delta", content="已")
        try:
            await asyncio.Event().wait()
        finally:
            self.cancelled.set()


class StreamingRuntimeTests(unittest.TestCase):
    """在真实后台事件循环中验证运行注册表的并发语义。"""

    def setUp(self) -> None:
        """为每个用例建立独立的可调用配置。"""
        self.temporary = tempfile.TemporaryDirectory()
        self.store = ConfigStore(Path(self.temporary.name) / "config.json", environ={})
        self.store.save({
            "api_base": "https://example.invalid/v1", "model": "fake", "api_key": "fake-key",
            "request_timeout": 2, "permission_mode": "allow",
        })
        self.runtime: AgentRuntime | None = None

    def tearDown(self) -> None:
        """停止后台循环并清理临时文件。"""
        if self.runtime is not None:
            self.runtime.close()
        self.temporary.cleanup()

    def _runtime(self, provider: Any, *, retention: float = 60.0) -> AgentRuntime:
        """创建使用同一受控 Provider 的运行环境。"""
        application = YanAgentApplication(self.store, provider_factory=lambda _config: provider)
        self.runtime = AgentRuntime(application, retention_seconds=retention)
        return self.runtime

    def _collect(self, runtime: AgentRuntime, request_id: str) -> list[dict[str, Any]]:
        """像 SSE 处理器一样从零开始等待到终态并返回事件对象。"""
        cursor = 0
        collected: list[dict[str, Any]] = []
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            batch = runtime.wait_events(request_id, cursor, timeout=0.1)
            self.assertIsNotNone(batch)
            events, terminal = batch  # type: ignore[misc]
            collected.extend(event.to_dict() for event in events)
            cursor += len(events)
            if terminal:
                return collected
        self.fail("等待运行终态超时")

    def test_two_runs_keep_events_and_content_isolated(self) -> None:
        """同一循环内并发的两条请求不会混用 request_id 或文本。"""
        runtime = self._runtime(EchoStreamingProvider())
        runtime.start_stream(
            {"session_id": "s-a", "message": "甲乙", "stream": True}, request_id="run-a",
        )
        runtime.start_stream(
            {"session_id": "s-b", "message": "12", "stream": True}, request_id="run-b",
        )
        first = self._collect(runtime, "run-a")
        second = self._collect(runtime, "run-b")
        self.assertEqual("".join(e.get("content", "") for e in first if e["type"] == "delta"), "甲乙")
        second_content = "".join(
            event.get("content", "") for event in second if event["type"] == "delta"
        )
        self.assertEqual(second_content, "12")
        self.assertEqual(first[-1]["type"], "done")
        self.assertEqual(second[-1]["type"], "done")

    def test_late_subscription_replays_early_events(self) -> None:
        """Provider 先完成也不丢事件，SSE 晚订阅仍从 cursor=0 完整回放。"""
        runtime = self._runtime(EchoStreamingProvider())
        runtime.start_stream(
            {"session_id": "s", "message": "晚订阅", "stream": True}, request_id="late",
        )
        time.sleep(0.05)
        events = self._collect(runtime, "late")
        self.assertEqual([event["type"] for event in events][-1], "done")
        self.assertEqual(events[-1]["content"], "晚订阅")

    def test_cancel_reaches_provider_and_produces_finite_terminal(self) -> None:
        """取消从 HTTP 侧跨线程传到模型协程，并以 cancelled+done 释放订阅者。"""
        provider = BlockingStreamingProvider()
        runtime = self._runtime(provider)
        runtime.start_stream(
            {"session_id": "s", "message": "阻塞", "stream": True}, request_id="cancel-me",
        )
        first = runtime.wait_events("cancel-me", 0, timeout=1)
        self.assertIsNotNone(first)
        self.assertEqual(first[0][0].type, "delta")  # type: ignore[index]
        self.assertEqual(runtime.cancel(request_id="cancel-me"), 1)
        events = self._collect(runtime, "cancel-me")
        self.assertEqual([event["type"] for event in events][-2:], ["cancelled", "done"])
        self.assertTrue(provider.cancelled.wait(1))
        self.assertEqual(runtime.cancel(request_id="cancel-me"), 0)

    def test_immediate_cancel_still_produces_terminal_events(self) -> None:
        """任务尚未进入协程函数体时取消，也不会留下永远等待的 SSE。"""
        runtime = self._runtime(BlockingStreamingProvider())
        runtime.start_stream(
            {"session_id": "s", "message": "立即停止", "stream": True}, request_id="early",
        )
        self.assertEqual(runtime.cancel(request_id="early"), 1)
        events = self._collect(runtime, "early")
        self.assertEqual([event["type"] for event in events][-2:], ["cancelled", "done"])

    def test_terminal_run_expires_after_retention_window(self) -> None:
        """终态超过 TTL 后移除，避免已结束运行永久占用内存。"""
        runtime = self._runtime(EchoStreamingProvider(), retention=0.02)
        runtime.start_stream(
            {"session_id": "s", "message": "完", "stream": True}, request_id="old",
        )
        self._collect(runtime, "old")
        time.sleep(0.03)
        self.assertIsNone(runtime.wait_events("old", 0, timeout=0))

    def test_two_streaming_tool_rounds_emit_ordered_events_and_persist_history(self) -> None:
        """连续两轮流式工具调用后第三轮回答，并保存完整 A/T 配对与累计用量。"""
        first_reply = ModelReply(
            tool_calls=[ToolCall(
                id="stream-call-1",
                name="calculator",
                arguments={"expression": "1+2"},
            )],
            finish_reason="tool_calls",
            usage={"input_tokens": 10, "output_tokens": 2, "total_tokens": 12},
        )
        second_reply = ModelReply(
            tool_calls=[ToolCall(
                id="stream-call-2",
                name="calculator",
                arguments={"expression": "3*4"},
            )],
            finish_reason="tool_calls",
            usage={"input_tokens": 20, "output_tokens": 3, "total_tokens": 23},
        )
        final_reply = ModelReply(
            content="两个结果分别是 3 和 12。",
            finish_reason="stop",
            usage={"input_tokens": 30, "output_tokens": 8, "total_tokens": 38},
        )
        provider = FakeProvider([], stream_outcomes=[
            [
                ModelStreamEvent(
                    kind="tool_call_delta",
                    tool_index=0,
                    tool_call_id="stream-call-1",
                    tool_name="calculator",
                    arguments_delta='{"expression":"1',
                ),
                ModelStreamEvent(
                    kind="tool_call_delta",
                    tool_index=0,
                    arguments_delta='+2"}',
                ),
                ModelStreamEvent(kind="completed", reply=first_reply),
            ],
            [
                ModelStreamEvent(
                    kind="tool_call_delta",
                    tool_index=0,
                    tool_call_id="stream-call-2",
                    tool_name="calculator",
                    arguments_delta='{"expression":"3*4"}',
                ),
                ModelStreamEvent(kind="completed", reply=second_reply),
            ],
            [
                ModelStreamEvent(kind="text_delta", content="两个结果分别是 "),
                ModelStreamEvent(kind="text_delta", content="3 和 12。"),
                ModelStreamEvent(kind="completed", reply=final_reply),
            ],
        ])
        root = Path(self.temporary.name)
        database = Database(data_dir=root / "data", environ={})
        sessions = SessionStore(database, user_id="local", agent_id="default")
        runs = RunStore(database, user_id="local", agent_id="default")
        application = YanAgentApplication(
            self.store,
            provider_factory=lambda _config: provider,
            session_store=sessions,
            run_store=runs,
        )
        self.runtime = AgentRuntime(application)

        self.runtime.start_stream(
            {"session_id": "stream-loop", "message": "依次计算", "stream": True},
            request_id="run-stream-loop",
        )
        events = self._collect(self.runtime, "run-stream-loop")

        self.assertEqual(
            [event["type"] for event in events],
            [
                "message_end", "tool_start", "tool_end",
                "message_end", "tool_start", "tool_end",
                "delta", "delta", "done",
            ],
        )
        starts = [event for event in events if event["type"] == "tool_start"]
        ends = [event for event in events if event["type"] == "tool_end"]
        self.assertEqual(
            [event["arguments"] for event in starts],
            [{"expression": "1+2"}, {"expression": "3*4"}],
        )
        self.assertEqual([event["result"] for event in ends], ["3", "12"])
        self.assertEqual([event["status"] for event in ends], ["success", "success"])
        self.assertEqual(events[-1]["content"], final_reply.content)
        self.assertEqual(events[-1]["turns"], 3)
        self.assertEqual(
            events[-1]["usage"],
            {"input_tokens": 60, "output_tokens": 13, "total_tokens": 73},
        )

        calls = provider.calls
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[1].messages[-2].tool_calls[0].id, "stream-call-1")
        self.assertEqual(calls[1].messages[-1].tool_call_id, "stream-call-1")
        self.assertEqual(calls[1].messages[-1].content, "3")
        self.assertEqual(calls[2].messages[-2].tool_calls[0].id, "stream-call-2")
        self.assertEqual(calls[2].messages[-1].tool_call_id, "stream-call-2")
        self.assertEqual(calls[2].messages[-1].content, "12")

        history = self.runtime.execute(sessions.complete_history("stream-loop"))
        self.assertEqual(
            [record.message.role for record in history],
            ["user", "assistant", "tool", "assistant", "tool", "assistant"],
        )
        stored_run = self.runtime.execute(runs.get("run-stream-loop", "stream-loop"))
        self.assertEqual(stored_run.status, "completed")
        self.assertEqual(stored_run.usage["total_tokens"], 73)

    def test_incomplete_tool_delta_never_executes_or_emits_tool_card(self) -> None:
        """只有参数增量而没有 completed 完整 ToolCall 时，拒绝执行并以流错误结束。"""
        provider = FakeProvider([], stream_outcomes=[[
            ModelStreamEvent(
                kind="tool_call_delta",
                tool_index=0,
                tool_call_id="partial-call",
                tool_name="calculator",
                arguments_delta='{"expression":"1+',
            ),
        ]])
        runtime = self._runtime(provider)
        runtime.start_stream(
            {"session_id": "partial", "message": "计算 1+2", "stream": True},
            request_id="run-partial",
        )

        events = self._collect(runtime, "run-partial")

        self.assertEqual([event["type"] for event in events], ["error"])
        self.assertNotIn("tool_start", [event["type"] for event in events])
        self.assertEqual(provider.remaining_streams, 0)

    def test_streaming_unknown_tool_emits_failed_result_then_model_can_finish(self) -> None:
        """未知工具以 tool_end 失败事件和 Tool Result 回写，模型下一轮仍可正常收尾。"""
        tool_reply = ModelReply(
            tool_calls=[ToolCall(id="missing-call", name="missing_tool", arguments={})],
            finish_reason="tool_calls",
        )
        final_reply = ModelReply(content="该工具不可用，我已停止调用。", finish_reason="stop")
        provider = FakeProvider([], stream_outcomes=[
            [ModelStreamEvent(kind="completed", reply=tool_reply)],
            [
                ModelStreamEvent(kind="text_delta", content=final_reply.content),
                ModelStreamEvent(kind="completed", reply=final_reply),
            ],
        ])
        runtime = self._runtime(provider)
        runtime.start_stream(
            {"session_id": "missing", "message": "调用不存在工具", "stream": True},
            request_id="run-missing",
        )

        events = self._collect(runtime, "run-missing")

        tool_end = next(event for event in events if event["type"] == "tool_end")
        self.assertEqual(tool_end["status"], "error")
        self.assertIn("工具不存在", tool_end["result"])
        self.assertEqual(events[-1]["type"], "done")
        self.assertEqual(events[-1]["content"], final_reply.content)
        self.assertTrue(provider.calls[1].messages[-1].is_error)


if __name__ == "__main__":
    unittest.main()
