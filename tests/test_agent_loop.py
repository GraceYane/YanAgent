"""P04-02 非流式模型、工具、模型闭环及持久化测试。"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from yanagent.chat import YanAgentApplication
from yanagent.config import ConfigStore
from yanagent.contracts import ModelReply, ToolCall
from yanagent.errors import AuthenticationError, MultipleToolCallsUnsupportedError
from yanagent.models import FakeProvider
from yanagent.sessions import RunStore, SessionStore
from yanagent.storage import Database


def _run(coroutine):
    """在同步 unittest 中执行一个短异步 Agent Loop 操作。"""
    return asyncio.run(coroutine)


def _tool_reply(call_id: str, name: str, arguments: dict[str, object]) -> ModelReply:
    """构造只包含一个原生 ToolCall 的确定性模型响应。"""
    return ModelReply(
        tool_calls=[ToolCall(id=call_id, name=name, arguments=arguments)],
        finish_reason="tool_calls",
    )


class NonStreamingAgentLoopTests(unittest.TestCase):
    """验证 P04-02 单工具多轮循环、消息顺序、失败回写和 Run 终态。"""

    def setUp(self) -> None:
        """创建独立配置、SQLite SessionStore 和 RunStore。"""
        project_root = Path(__file__).resolve().parents[1]
        self.temporary = tempfile.TemporaryDirectory(
            prefix=".yan-loop-test-",
            dir=project_root,
        )
        root = Path(self.temporary.name)
        self.config = ConfigStore(root / "config.json", environ={})
        self.config.save({
            "api_base": "https://example.invalid/v1",
            "model": "fake-model",
            "api_key": "fake-key",
            "permission_mode": "allow",
        })
        self.database = Database(data_dir=root / "data", environ={})
        self.sessions = SessionStore(
            self.database,
            user_id="local",
            agent_id="default",
        )
        self.runs = RunStore(
            self.database,
            user_id="local",
            agent_id="default",
        )

    def tearDown(self) -> None:
        """删除当前测试创建的配置和 SQLite 文件。"""
        self.temporary.cleanup()

    def _application(self, fake: FakeProvider) -> YanAgentApplication:
        """创建使用真实仓储、真实安全工具和可控模型响应的应用。"""
        return YanAgentApplication(
            self.config,
            provider_factory=lambda _config: fake,
            session_store=self.sessions,
            run_store=self.runs,
        )

    def test_two_tool_rounds_then_final_answer_are_ordered_and_persisted(self) -> None:
        """连续两轮工具请求后完成回答，并保存 User/A/T/A/T/A 的完整顺序。"""
        fake = FakeProvider([
            ModelReply(
                tool_calls=[ToolCall(
                    id="call-1",
                    name="calculator",
                    arguments={"expression": "1+2"},
                )],
                finish_reason="tool_calls",
                usage={"input_tokens": 10, "output_tokens": 2, "total_tokens": 12},
            ),
            ModelReply(
                tool_calls=[ToolCall(
                    id="call-2",
                    name="calculator",
                    arguments={"expression": "3*4"},
                )],
                finish_reason="tool_calls",
                usage={"input_tokens": 20, "output_tokens": 3, "total_tokens": 23},
            ),
            ModelReply(
                content="第一次是 3，第二次是 12。",
                finish_reason="stop",
                usage={"input_tokens": 30, "output_tokens": 4, "total_tokens": 34},
            ),
        ])

        result = _run(self._application(fake).chat(
            {"session_id": "loop", "message": "连续计算两次"},
            request_id="run-loop",
        ))

        self.assertEqual(result["inline_reply"], "第一次是 3，第二次是 12。")
        self.assertEqual(result["turns"], 3)
        self.assertEqual(result["usage"], {
            "input_tokens": 60,
            "output_tokens": 9,
            "total_tokens": 69,
        })
        self.assertEqual((result["user_seq"], result["bot_seq"]), (0, 5))
        self.assertEqual(fake.remaining, 0)

        calls = fake.calls
        self.assertEqual(len(calls), 3)
        self.assertEqual(
            [message.role for message in calls[0].messages],
            ["system", "user"],
        )
        self.assertEqual(
            [message.role for message in calls[1].messages],
            ["system", "user", "assistant", "tool"],
        )
        self.assertEqual(
            [message.role for message in calls[2].messages],
            ["system", "user", "assistant", "tool", "assistant", "tool"],
        )
        self.assertEqual(calls[1].messages[-2].tool_calls[0].id, "call-1")
        self.assertEqual(calls[1].messages[-1].tool_call_id, "call-1")
        self.assertEqual(calls[1].messages[-1].content, "3")
        self.assertEqual(calls[2].messages[-2].tool_calls[0].id, "call-2")
        self.assertEqual(calls[2].messages[-1].tool_call_id, "call-2")
        self.assertEqual(calls[2].messages[-1].content, "12")
        self.assertEqual(
            [schema["name"] for schema in calls[2].tools],
            ["calculator", "current_time"],
        )

        history = _run(self.sessions.complete_history("loop"))
        self.assertEqual(
            [record.message.role for record in history],
            ["user", "assistant", "tool", "assistant", "tool", "assistant"],
        )
        self.assertEqual(history[1].message.tool_calls[0].arguments, {"expression": "1+2"})
        self.assertEqual(history[2].message.tool_call_id, "call-1")
        self.assertFalse(history[2].message.is_error)
        self.assertEqual(history[3].message.tool_calls[0].arguments, {"expression": "3*4"})
        self.assertEqual(history[4].message.tool_call_id, "call-2")
        self.assertEqual(history[5].message.metadata["usage"], result["usage"])
        run = _run(self.runs.get("run-loop", "loop"))
        self.assertIsNotNone(run)
        self.assertEqual(run.status, "completed")
        self.assertEqual(run.usage, result["usage"])

    def test_unknown_tool_and_bad_arguments_are_returned_to_model(self) -> None:
        """未知工具和参数错误都成为同 ID 的失败 Tool Message，模型仍能继续回答。"""
        scenarios = [
            (
                "unknown",
                _tool_reply("unknown-1", "missing_tool", {}),
                "工具不存在或当前不可用。",
            ),
            (
                "bad-arguments",
                _tool_reply("bad-1", "calculator", {}),
                "工具参数缺少必填字段",
            ),
        ]
        for session_id, tool_reply, expected_error in scenarios:
            with self.subTest(session_id=session_id):
                fake = FakeProvider([
                    tool_reply,
                    ModelReply(content="我已根据工具错误继续处理。", finish_reason="stop"),
                ])
                result = _run(self._application(fake).chat(
                    {"session_id": session_id, "message": "请使用工具"},
                    request_id=f"run-{session_id}",
                ))

                self.assertEqual(result["turns"], 2)
                second_input = fake.calls[1].messages
                self.assertEqual(second_input[-2].role, "assistant")
                self.assertEqual(second_input[-1].role, "tool")
                self.assertEqual(
                    second_input[-1].tool_call_id,
                    second_input[-2].tool_calls[0].id,
                )
                self.assertTrue(second_input[-1].is_error)
                self.assertIn(expected_error, second_input[-1].content)
                history = _run(self.sessions.complete_history(session_id))
                self.assertEqual(
                    [record.message.role for record in history],
                    ["user", "assistant", "tool", "assistant"],
                )

    def test_permission_denial_is_a_tool_result_and_run_can_complete(self) -> None:
        """deny 模式不抛散权限异常，而是把失败 Tool Result 交回模型收尾。"""
        self.config.save({"permission_mode": "deny"})
        fake = FakeProvider([
            _tool_reply("denied-1", "calculator", {"expression": "40+2"}),
            ModelReply(content="当前权限不允许执行计算器。", finish_reason="stop"),
        ])

        result = _run(self._application(fake).chat(
            {"session_id": "denied", "message": "计算 40+2"},
            request_id="run-denied",
        ))

        self.assertEqual(result["inline_reply"], "当前权限不允许执行计算器。")
        self.assertEqual(result["turns"], 2)
        tool_message = fake.calls[1].messages[-1]
        self.assertTrue(tool_message.is_error)
        self.assertEqual(tool_message.tool_call_id, "denied-1")
        self.assertIn("权限模式禁止", tool_message.content)
        run = _run(self.runs.get("run-denied", "denied"))
        self.assertEqual(run.status, "completed")

    def test_multiple_tool_calls_fail_before_partial_assistant_persistence(self) -> None:
        """P04-03 前拒绝同轮多工具调用，避免只执行或保存其中一部分。"""
        fake = FakeProvider([
            ModelReply(
                tool_calls=[
                    ToolCall(id="multi-1", name="calculator", arguments={"expression": "1+1"}),
                    ToolCall(id="multi-2", name="calculator", arguments={"expression": "2+2"}),
                ],
                finish_reason="tool_calls",
            )
        ])

        with self.assertRaises(MultipleToolCallsUnsupportedError):
            _run(self._application(fake).chat(
                {"session_id": "multiple", "message": "同时计算两次"},
                request_id="run-multiple",
            ))

        history = _run(self.sessions.complete_history("multiple"))
        self.assertEqual([record.message.role for record in history], ["user"])
        run = _run(self.runs.get("run-multiple", "multiple"))
        self.assertEqual(run.status, "failed")
        self.assertEqual(run.error_code, "multiple_tool_calls_unsupported")

    def test_model_failure_after_tool_keeps_complete_pair_and_failed_run(self) -> None:
        """第二轮模型失败时保留完整 A/T 工具轮次，不伪造最终 Assistant。"""
        fake = FakeProvider([
            _tool_reply("before-failure", "calculator", {"expression": "6*7"}),
            AuthenticationError(),
        ])

        with self.assertRaises(AuthenticationError):
            _run(self._application(fake).chat(
                {"session_id": "model-failure", "message": "计算后继续回答"},
                request_id="run-model-failure",
            ))

        history = _run(self.sessions.complete_history("model-failure"))
        self.assertEqual(
            [record.message.role for record in history],
            ["user", "assistant", "tool"],
        )
        self.assertEqual(history[1].message.tool_calls[0].id, "before-failure")
        self.assertEqual(history[2].message.tool_call_id, "before-failure")
        self.assertEqual(history[2].message.content, "42")
        run = _run(self.runs.get("run-model-failure", "model-failure"))
        self.assertEqual(run.status, "failed")
        self.assertEqual(run.error_code, "authentication_error")


if __name__ == "__main__":
    unittest.main()
