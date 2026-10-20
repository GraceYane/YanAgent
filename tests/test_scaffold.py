from __future__ import annotations

import unittest

from app import empty_sessions_payload, health_payload
from yanagent.contracts import RunRequest
from yanagent.runtime.agent_loop import AgentLoop


class ScaffoldPayloadTests(unittest.TestCase):
    def test_health_marks_runtime_as_unimplemented(self) -> None:
        payload = health_payload()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["agent_runtime"], "not_implemented")

    def test_sessions_start_empty(self) -> None:
        payload = empty_sessions_payload()
        self.assertEqual(payload["sessions"], [])
        self.assertEqual(payload["total"], 0)


class MissingCoreTests(unittest.TestCase):
    def test_agent_loop_is_deliberately_missing(self) -> None:
        loop = AgentLoop(model=object(), tools=object(), sessions=object())
        pending = loop.run(RunRequest(session_id="s1", user_message="hello"))
        with self.assertRaises(NotImplementedError):
            pending.send(None)


if __name__ == "__main__":
    unittest.main()
