from __future__ import annotations

import unittest

from app import empty_sessions_payload, health_payload


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
if __name__ == "__main__":
    unittest.main()
