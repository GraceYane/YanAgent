"""P01-01 数据契约的离线行为测试。"""

from __future__ import annotations

import json
import unittest
from datetime import datetime

from yanagent.contracts import (
    ContractValidationError,
    Message,
    ModelReply,
    RunRequest,
    RunResult,
    ToolCall,
    ToolResult,
    validate_conversation,
)


def calculator_call(call_id: str = "call_001") -> ToolCall:
    """固定工具请求，测试不执行计算器或调用真实模型。"""
    return ToolCall(id=call_id, name="calculator", arguments={"expression": "1 + 2"})


class ContractRoundTripTests(unittest.TestCase):
    """验证六种契约和完整四条消息不会在保存、还原时丢失信息。"""

    def test_all_contracts_round_trip(self) -> None:
        objects = [
            calculator_call(),
            Message(
                role="assistant", content="我来计算", name="YanAgent",
                tool_calls=[calculator_call()], metadata={"source": "桌面"},
            ),
            ToolResult(tool_call_id="call_001", content="失败原因", is_error=True),
            ModelReply(
                tool_calls=[calculator_call()], finish_reason="tool_calls",
                usage={"input_tokens": 20, "output_tokens": None},
            ),
            RunRequest(
                session_id="s1", user_message="计算 1 + 2", user_id="u1",
                agent_id="a1", request_id="r1", metadata={"channel": "桌面"},
            ),
            RunResult(
                content="计算结果是 3", session_id="s1", turns=2,
                user_id="u1", agent_id="a1", request_id="r1",
                usage={"input_tokens": 30, "output_tokens": 10},
            ),
        ]
        for obj in objects:
            with self.subTest(contract=type(obj).__name__):
                self.assertEqual(type(obj).from_dict(obj.to_dict()), obj)
                self.assertEqual(type(obj).from_json(obj.to_json()), obj)

    def test_four_messages_keep_tool_request_and_result(self) -> None:
        messages = [
            Message(role="user", content="计算 1 + 2"),
            ModelReply(tool_calls=[calculator_call()]).to_message(),
            ToolResult(tool_call_id="call_001", content="3").to_message(),
            ModelReply(content="计算结果是 3").to_message(),
        ]
        validate_conversation(messages)
        serialized = json.dumps([msg.to_dict() for msg in messages], ensure_ascii=False)
        restored = [Message.from_dict(item) for item in json.loads(serialized)]
        validate_conversation(restored)
        self.assertEqual(restored, messages)
        self.assertEqual(restored[1].tool_calls[0].arguments, {"expression": "1 + 2"})
        self.assertEqual(restored[1].tool_calls[0].id, restored[2].tool_call_id)
        self.assertIn("计算结果是 3", serialized)
        self.assertIsInstance(restored[1].tool_calls[0], ToolCall)

    def test_failed_tool_result_keeps_error_flag_in_history(self) -> None:
        message = ToolResult("call_001", "权限被拒绝", is_error=True).to_message()
        self.assertTrue(Message.from_json(message.to_json()).is_error)

    def test_old_minimal_constructors_remain_usable(self) -> None:
        request = RunRequest(session_id="s1", user_message="你好")
        self.assertEqual(request.user_id, "local")
        self.assertEqual(request.agent_id, "default")
        self.assertIsNone(request.request_id)
        self.assertEqual(RunResult("你好", "s1", 1).status, "completed")
        self.assertEqual(Message.from_dict({"role": "user", "content": "你好"}),
                         Message("user", "你好"))

    def test_unknown_usage_is_distinct_from_zero(self) -> None:
        reply = ModelReply(usage={"input_tokens": None, "output_tokens": 0})
        restored = ModelReply.from_json(reply.to_json())
        self.assertIsNone(restored.usage["input_tokens"])
        self.assertEqual(restored.usage["output_tokens"], 0)
        self.assertEqual(ModelReply().usage, {})

    def test_defaults_and_serialized_data_are_independent(self) -> None:
        first, second = Message("user", "甲"), Message("user", "乙")
        first.metadata["nested"] = {"values": ["原始"]}
        self.assertEqual(second.metadata, {})
        output = first.to_dict()
        output["metadata"]["nested"]["values"].append("输出修改")
        self.assertEqual(first.metadata["nested"]["values"], ["原始"])
        restored = Message.from_dict(output)
        output["metadata"]["nested"]["values"].append("再次修改")
        self.assertEqual(restored.metadata["nested"]["values"], ["原始", "输出修改"])
        reply = ModelReply(tool_calls=[calculator_call()])
        message = reply.to_message()
        message.tool_calls[0].arguments["expression"] = "2 + 3"
        self.assertEqual(reply.tool_calls[0].arguments["expression"], "1 + 2")
        self.assertEqual(ModelReply().tool_calls, [])
        self.assertEqual(RunRequest("s", "你好").metadata, {})


class ContractValidationTests(unittest.TestCase):
    """覆盖构造和反序列化边界，避免仅靠类型标注接受错误数据。"""

    def test_invalid_roles_and_role_specific_fields(self) -> None:
        invalid = [
            {"role": "developer", "content": "文本"},
            {"role": [], "content": "文本"},
            {"role": "user", "content": 42},
            {"role": "tool", "content": "3"},
            {"role": "tool", "content": "3", "tool_call_id": " "},
            {"role": "user", "content": "文本", "tool_call_id": "call_001"},
            {"role": "assistant", "content": "文本", "is_error": True},
            {"role": "tool", "content": "3", "tool_call_id": "call_001", "is_error": 1},
        ]
        for data in invalid:
            with self.subTest(data=data), self.assertRaises(ContractValidationError):
                Message.from_dict(data)
        with self.assertRaises(ContractValidationError):
            Message("user", "文本", tool_calls=[calculator_call()])

    def test_required_and_unknown_fields(self) -> None:
        invalid = [
            (ToolCall, {"id": "call_001", "name": "calculator"}),
            (RunRequest, {"user_message": "你好"}),
            (RunResult, {"content": "你好", "session_id": "s1"}),
            (Message, {"role": "user", "content": "你好", "typo": True}),
            (ModelReply, {"tool_calls": [{"id": "c", "name": "t", "arguments": {}, "x": 1}]}),
        ]
        for cls, data in invalid:
            with self.subTest(contract=cls.__name__, data=data):
                with self.assertRaises(ContractValidationError):
                    cls.from_dict(data)

    def test_nested_tool_calls_are_validated(self) -> None:
        for cls in (Message, ModelReply):
            base = {"role": "assistant", "content": ""} if cls is Message else {}
            for calls in (None, {}, [42], [{"id": "c", "name": "t", "arguments": "{}"}]):
                with self.subTest(contract=cls.__name__, calls=calls):
                    with self.assertRaises(ContractValidationError):
                        cls.from_dict({**base, "tool_calls": calls})
        with self.assertRaises(ContractValidationError):
            ModelReply(tool_calls=[{"id": "c", "name": "t", "arguments": {}}])
        with self.assertRaises(ContractValidationError):
            ModelReply(tool_calls=[calculator_call(), calculator_call()])
        for kwargs in (
            {"id": "", "name": "t", "arguments": {}},
            {"id": "c", "name": " ", "arguments": {}},
            {"id": "c", "name": "t", "arguments": []},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ContractValidationError):
                ToolCall(**kwargs)

    def test_non_json_data_is_rejected_without_silent_conversion(self) -> None:
        cyclic: list = []
        cyclic.append(cyclic)
        invalid = [
            {"value": {1, 2}}, {1: "非字符串键"}, {"value": (1, 2)},
            {"value": datetime(2026, 10, 20)}, {"value": float("nan")},
            {"value": float("inf")}, {"value": cyclic},
        ]
        for data in invalid:
            with self.subTest(kind=type(next(iter(data.values()))).__name__):
                with self.assertRaises(ContractValidationError):
                    ToolCall("c", "t", data)
                with self.assertRaises(ContractValidationError):
                    Message("user", "你好", metadata=data)
        shared = {"value": 3}
        self.assertEqual(ToolCall("c", "t", {"a": shared, "b": shared}).arguments["a"], shared)

    def test_json_syntax_root_and_duplicate_keys(self) -> None:
        for payload in ("{", "[]", "null", "42", '"文本"',
                        '{"role":"user","role":"tool","content":"x"}',
                        '{"role":"user","content":"x","metadata":{"x":NaN}}',
                        '{"role":"user","content":"x","metadata":{"x":Infinity}}',
                        '{"role":"user","content":"x","metadata":{"x":1e999}}'):
            with self.subTest(payload=payload), self.assertRaises(ContractValidationError):
                Message.from_json(payload)
        with self.assertRaises(ContractValidationError):
            Message.from_json(b'{}')

    def test_identity_and_request_validation(self) -> None:
        for name in ("user_id", "agent_id", "session_id", "request_id"):
            for value in ("", " ", 42):
                with self.subTest(name=name, value=value):
                    args = {"session_id": "s1", "user_message": "你好", name: value}
                    with self.assertRaises(ContractValidationError):
                        RunRequest(**args)
                    result = {"session_id": "s1", "content": "你好", "turns": 1, name: value}
                    with self.assertRaises(ContractValidationError):
                        RunResult(**result)
        for value in (None, "", " ", 42):
            with self.subTest(user_message=value), self.assertRaises(ContractValidationError):
                RunRequest("s1", value)

    def test_usage_turns_status_and_error_boolean(self) -> None:
        for value in (-1, True, 1.5, "1"):
            with self.subTest(value=value):
                with self.assertRaises(ContractValidationError):
                    ModelReply(usage={"input_tokens": value})
                with self.assertRaises(ContractValidationError):
                    RunResult("回答", "s1", 1, usage={"output_tokens": value})
                with self.assertRaises(ContractValidationError):
                    RunResult("回答", "s1", value)
        for status in ("running", "unknown", None, []):
            with self.subTest(status=status), self.assertRaises(ContractValidationError):
                RunResult("", "s1", 0, status=status)
        for status in ("completed", "failed", "cancelled", "interrupted"):
            self.assertEqual(RunResult("", "s1", 0, status=status).status, status)
        with self.assertRaises(ContractValidationError):
            ToolResult("c", "错误", is_error="false")

    def test_serialization_revalidates_mutated_objects(self) -> None:
        call = calculator_call()
        call.arguments["bad"] = object()
        with self.assertRaises(ContractValidationError):
            call.to_dict()
        message = Message("assistant", "", tool_calls=[calculator_call()])
        message.tool_calls[0].id = ""
        with self.assertRaises(ContractValidationError):
            message.to_json()

    def test_validation_errors_do_not_echo_payload(self) -> None:
        secret = "sensitive-test-value"
        with self.assertRaises(ContractValidationError) as raised:
            Message.from_json('{"role":"user","content":"' + secret + '",')
        self.assertNotIn(secret, str(raised.exception))


class ConversationValidationTests(unittest.TestCase):
    """校验跨消息的配对、顺序与未完成调用，而非只验证单条字段。"""

    def test_parallel_results_may_arrive_in_different_order(self) -> None:
        validate_conversation([
            Message("assistant", "", tool_calls=[calculator_call("c1"), calculator_call("c2")]),
            ToolResult("c2", "3").to_message(),
            ToolResult("c1", "失败", is_error=True).to_message(),
            Message("assistant", "汇总结果"),
        ])

    def test_orphan_duplicate_missing_and_interleaved_results_are_rejected(self) -> None:
        request = Message("assistant", "", tool_calls=[calculator_call()])
        result = ToolResult("call_001", "3").to_message()
        invalid = [
            [result],
            [request, ToolResult("other", "3").to_message()],
            [request, result, result],
            [request],
            [request, Message("assistant", "提前结束")],
            [request, Message("user", "下一题")],
            [request, result, request, result],
        ]
        for messages in invalid:
            with self.subTest(roles=[m.role for m in messages]):
                with self.assertRaises(ContractValidationError):
                    validate_conversation(messages)

    def test_pending_tail_must_be_explicit(self) -> None:
        messages = [Message("assistant", "", tool_calls=[calculator_call()])]
        validate_conversation(messages, allow_pending_tool_calls=True)
        with self.assertRaises(ContractValidationError):
            validate_conversation(messages)
        with self.assertRaises(ContractValidationError):
            validate_conversation(messages + [Message("user", "打断")], allow_pending_tool_calls=True)

    def test_empty_plain_and_multiple_tool_rounds(self) -> None:
        validate_conversation([])
        validate_conversation((Message("system", "助手规则"), Message("user", "你好")))
        validate_conversation([
            Message("user", "做两次计算"),
            Message("assistant", "", tool_calls=[calculator_call("c1")]),
            ToolResult("c1", "3").to_message(),
            Message("assistant", "", tool_calls=[calculator_call("c2")]),
            ToolResult("c2", "3").to_message(),
            Message("assistant", "两次结果都是 3"),
        ])

    def test_invalid_conversation_container_or_item(self) -> None:
        for messages in ("not a list", {}, [object()]):
            with self.subTest(messages=messages), self.assertRaises(ContractValidationError):
                validate_conversation(messages)
        with self.assertRaises(ContractValidationError):
            validate_conversation([], allow_pending_tool_calls="true")


if __name__ == "__main__":
    unittest.main()
