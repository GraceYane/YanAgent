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
from yanagent.config import AppConfig, ConfigStore
from yanagent.contracts import Message, ModelReply
from yanagent.events import ModelStreamEvent
from yanagent.runtime import AgentRuntime


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
            "request_timeout": 2,
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


if __name__ == "__main__":
    unittest.main()
