"""P04-02～P04-03 非流式 Agent Loop、多调用、限制及持久化测试。"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from yanagent.chat import YanAgentApplication
from yanagent.config import ConfigStore
from yanagent.contracts import Message, ModelReply, ToolCall
from yanagent.errors import (
    AgentLoopConsecutiveFailuresError,
    AgentLoopMaxTurnsError,
    AgentLoopTimeoutError,
    AuthenticationError,
    EmptyModelResponseError,
)
from yanagent.models import FakeProvider
from yanagent.runtime import AgentLoop
from yanagent.sessions import RunStore, SessionStore
from yanagent.storage import Database
from yanagent.tools import ToolDefinition, ToolManager, ToolPermissionContext


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
    """验证非流式多工具循环、消息顺序、运行限制和 Run 终态。"""

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

    async def _run_direct_loop(
        self,
        fake: object,
        *,
        tools: ToolManager | None = None,
        max_model_turns: int = 20,
        total_timeout_seconds: float = 600,
        max_consecutive_tool_failures: int = 3,
    ):
        """无数据库运行可调限制的 AgentLoop，供边界测试精确缩短阈值。"""
        selected_tools = tools if tools is not None else self._application(fake).tool_manager
        return await AgentLoop(
            model=fake,
            tools=selected_tools,
            sessions=None,
            max_model_turns=max_model_turns,
            total_timeout_seconds=total_timeout_seconds,
            max_consecutive_tool_failures=max_consecutive_tool_failures,
        ).run(
            messages=[Message("user", "测试循环限制")],
            tool_schemas=selected_tools.schemas(),
            session_id="direct-loop",
            request_id="run-direct-loop",
            permission_mode="allow",
            permission_context=ToolPermissionContext(
                allowed_scopes=frozenset({"global", "user", "agent", "session"}),
                run_id="run-direct-loop",
                user_id="local",
                agent_id="default",
                session_id="direct-loop",
            ),
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

    def test_multiple_tool_calls_execute_in_model_order_and_persist_complete_group(self) -> None:
        """同轮多个调用按模型顺序执行，下一轮收到一个 Assistant 和全部 Tool 结果。"""
        fake = FakeProvider([
            ModelReply(
                tool_calls=[
                    ToolCall(id="multi-1", name="calculator", arguments={"expression": "1+1"}),
                    ToolCall(id="multi-2", name="calculator", arguments={"expression": "2+2"}),
                ],
                finish_reason="tool_calls",
            ),
            ModelReply(content="两个结果分别是 2 和 4。", finish_reason="stop"),
        ])

        result = _run(self._application(fake).chat(
            {"session_id": "multiple", "message": "同时计算两次"},
            request_id="run-multiple",
        ))

        self.assertEqual(result["inline_reply"], "两个结果分别是 2 和 4。")
        self.assertEqual(result["turns"], 2)
        second_input = fake.calls[1].messages
        self.assertEqual(
            [message.role for message in second_input[-3:]],
            ["assistant", "tool", "tool"],
        )
        self.assertEqual(
            [message.tool_call_id for message in second_input[-2:]],
            ["multi-1", "multi-2"],
        )
        self.assertEqual(
            [message.content for message in second_input[-2:]],
            ["2", "4"],
        )
        history = _run(self.sessions.complete_history("multiple"))
        self.assertEqual(
            [record.message.role for record in history],
            ["user", "assistant", "tool", "tool", "assistant"],
        )
        self.assertEqual(
            [call.id for call in history[1].message.tool_calls],
            ["multi-1", "multi-2"],
        )
        run = _run(self.runs.get("run-multiple", "multiple"))
        self.assertEqual(run.status, "completed")

    def test_max_model_turns_stops_before_unconsumable_tool_side_effect(self) -> None:
        """最后允许轮次仍请求工具时直接失败，不执行无法再交给模型消费的调用。"""
        fake = FakeProvider([
            _tool_reply("turn-1", "calculator", {"expression": "1+1"}),
            _tool_reply("turn-2", "calculator", {"expression": "2+2"}),
        ])

        with self.assertRaises(AgentLoopMaxTurnsError):
            _run(self._run_direct_loop(fake, max_model_turns=2))

        self.assertEqual(len(fake.calls), 2)
        self.assertEqual(fake.calls[1].messages[-1].content, "2")

    def test_consecutive_tool_failures_stop_loop_and_mark_run_failed(self) -> None:
        """连续三个失败 Tool Result 后熔断，不再发起下一轮模型请求。"""
        fake = FakeProvider([
            _tool_reply(f"failed-{index}", "missing_tool", {})
            for index in range(1, 5)
        ])

        with self.assertRaises(AgentLoopConsecutiveFailuresError):
            _run(self._application(fake).chat(
                {"session_id": "failure-limit", "message": "重复调用未知工具"},
                request_id="run-failure-limit",
            ))

        self.assertEqual(len(fake.calls), 3)
        self.assertEqual(fake.remaining, 1)
        history = _run(self.sessions.complete_history("failure-limit"))
        self.assertEqual(
            [record.message.role for record in history],
            ["user", "assistant", "tool", "assistant", "tool", "assistant", "tool"],
        )
        self.assertTrue(all(history[index].message.is_error for index in (2, 4, 6)))
        run = _run(self.runs.get("run-failure-limit", "failure-limit"))
        self.assertEqual(run.status, "failed")
        self.assertEqual(run.error_code, "agent_loop_consecutive_tool_failures")

    def test_failure_limit_closes_remaining_calls_in_same_model_group(self) -> None:
        """同轮达到失败上限后跳过剩余副作用，但仍补齐结果以保持历史合法。"""
        fake = FakeProvider([ModelReply(
            tool_calls=[
                ToolCall(id=f"group-failed-{index}", name="missing_tool", arguments={})
                for index in range(1, 4)
            ] + [
                ToolCall(
                    id="group-skipped-4",
                    name="calculator",
                    arguments={"expression": "100+1"},
                )
            ],
            finish_reason="tool_calls",
        )])

        with self.assertRaises(AgentLoopConsecutiveFailuresError):
            _run(self._application(fake).chat(
                {"session_id": "group-failure", "message": "一轮调用多个工具"},
                request_id="run-group-failure",
            ))

        history = _run(self.sessions.complete_history("group-failure"))
        self.assertEqual(
            [record.message.role for record in history],
            ["user", "assistant", "tool", "tool", "tool", "tool"],
        )
        self.assertEqual(history[-1].message.tool_call_id, "group-skipped-4")
        self.assertTrue(history[-1].message.is_error)
        self.assertIn("未执行", history[-1].message.content)

    def test_total_timeout_cancels_slow_model_with_stable_error(self) -> None:
        """模型长时间不返回时由 Agent Loop 总预算取消，并转换为稳定超时错误。"""

        class SlowProvider:
            """模拟超过循环总预算才返回的模型 Provider。"""

            async def complete(self, _messages, *, tools=()):
                """等待足够长时间，使测试中的循环总超时先触发。"""
                del tools
                await asyncio.sleep(0.2)
                return ModelReply(content="不应返回")

        with self.assertRaises(AgentLoopTimeoutError):
            _run(self._run_direct_loop(
                SlowProvider(),
                total_timeout_seconds=0.01,
            ))

    def test_total_timeout_closes_current_multi_tool_group_without_more_side_effects(self) -> None:
        """工具阶段耗尽总预算时补齐整组结果，并阻止后续工具产生副作用。"""

        async def scenario() -> None:
            later_executed = False

            async def slow_handler(_arguments):
                """模拟运行时间超过 Agent 总剩余预算的第一个工具。"""
                await asyncio.sleep(1)
                return "慢工具不应完成"

            async def later_handler(_arguments):
                """记录熔断后本不应该执行的同轮后续工具。"""
                nonlocal later_executed
                later_executed = True
                return "不应执行"

            tools = ToolManager(timeout_seconds=1)
            for name, handler in (("slow_tool", slow_handler), ("later_tool", later_handler)):
                tools.register(ToolDefinition(
                    name=name,
                    description=f"测试 {name}。",
                    parameters={"type": "object", "properties": {}, "required": []},
                    handler=handler,
                    requires_confirmation=False,
                ))
            fake = FakeProvider([ModelReply(
                tool_calls=[
                    ToolCall(id="timeout-1", name="slow_tool", arguments={}),
                    ToolCall(id="timeout-2", name="later_tool", arguments={}),
                ],
                finish_reason="tool_calls",
            )])
            await self.sessions.create("timeout-tools")
            await self.sessions.append("timeout-tools", [Message("user", "测试总超时")])
            loop = AgentLoop(
                model=fake,
                tools=tools,
                sessions=self.sessions,
                total_timeout_seconds=0.05,
            )
            with self.assertRaises(AgentLoopTimeoutError):
                await loop.run(
                    messages=[Message("user", "测试总超时")],
                    tool_schemas=tools.schemas(),
                    session_id="timeout-tools",
                    request_id="run-timeout-tools",
                    permission_mode="allow",
                    permission_context=ToolPermissionContext(
                        allowed_scopes=frozenset({"session"}),
                        run_id="run-timeout-tools",
                        user_id="local",
                        agent_id="default",
                        session_id="timeout-tools",
                    ),
                )
            self.assertFalse(later_executed)
            history = await self.sessions.complete_history("timeout-tools")
            self.assertEqual(
                [record.message.role for record in history],
                ["user", "assistant", "tool", "tool"],
            )
            self.assertEqual(
                [record.message.tool_call_id for record in history[-2:]],
                ["timeout-1", "timeout-2"],
            )
            self.assertTrue(all(record.message.is_error for record in history[-2:]))

        _run(scenario())

    def test_single_tool_timeout_counts_as_failure_and_cancels_handler(self) -> None:
        """单工具超时仍由 ToolManager 取消 handler，并纳入连续失败熔断。"""

        async def scenario() -> None:
            cancelled = asyncio.Event()

            async def slow_handler(_arguments):
                """模拟可响应取消的慢工具处理函数。"""
                try:
                    await asyncio.sleep(1)
                finally:
                    cancelled.set()

            tools = ToolManager(timeout_seconds=0.01)
            tools.register(ToolDefinition(
                name="slow_tool",
                description="测试单工具超时。",
                parameters={"type": "object", "properties": {}, "required": []},
                handler=slow_handler,
                requires_confirmation=False,
            ))
            fake = FakeProvider([_tool_reply("slow-1", "slow_tool", {})])
            with self.assertRaises(AgentLoopConsecutiveFailuresError):
                await self._run_direct_loop(
                    fake,
                    tools=tools,
                    max_consecutive_tool_failures=1,
                )
            self.assertTrue(cancelled.is_set())

        _run(scenario())

    def test_empty_model_reply_fails_once_instead_of_completing_empty_run(self) -> None:
        """空文本且无工具调用不能冒充最终答案，Run 进入稳定失败终态。"""
        fake = FakeProvider([ModelReply(content="   ", finish_reason="stop")])

        with self.assertRaises(EmptyModelResponseError):
            _run(self._application(fake).chat(
                {"session_id": "empty", "message": "不要返回空消息"},
                request_id="run-empty",
            ))

        history = _run(self.sessions.complete_history("empty"))
        self.assertEqual([record.message.role for record in history], ["user"])
        run = _run(self.runs.get("run-empty", "empty"))
        self.assertEqual(run.status, "failed")
        self.assertEqual(run.error_code, "empty_model_response")

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
