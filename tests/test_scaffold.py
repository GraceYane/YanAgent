from __future__ import annotations

import unittest

from app import empty_sessions_payload, health_payload
from yanagent.contracts import RunRequest
from yanagent.runtime.agent_loop import AgentLoop


class ScaffoldPayloadTests(unittest.TestCase):
    """验证仍由骨架提供的健康和空会话响应。"""

    def test_health_marks_streaming_chat_available(self) -> None:
        """P01-05 完成后健康状态应声明流式聊天已可用。"""
        payload = health_payload()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["agent_runtime"], "streaming_chat")

    def test_sessions_start_empty(self) -> None:
        """P02 前会话接口仍返回合法的空分页。"""
        payload = empty_sessions_payload()
        self.assertEqual(payload["sessions"], [])
        self.assertEqual(payload["total"], 0)


class MissingCoreTests(unittest.TestCase):
    """防止普通聊天联调被误写成完整 AgentLoop 已完成。"""

    def test_agent_loop_is_deliberately_missing(self) -> None:
        """真正的模型工具循环仍应保持未实现。"""
        loop = AgentLoop(model=object(), tools=object(), sessions=object())
        pending = loop.run(RunRequest(session_id="s1", user_message="hello"))
        with self.assertRaises(NotImplementedError):
            pending.send(None)


if __name__ == "__main__":
    unittest.main()
