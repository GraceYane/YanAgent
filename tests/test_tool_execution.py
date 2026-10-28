"""P03-03 工具参数校验、统一结果、超时、异常和截断测试。"""

from __future__ import annotations

import asyncio
import unittest
from typing import Any

from yanagent.contracts import ToolCall
from yanagent.tools import (
    ToolDefinition,
    ToolHandlerError,
    ToolManager,
    calculator_definition,
    current_time_definition,
)


def _call(
    name: str = "calculator",
    arguments: Any = None,
    *,
    call_id: str = "call-1",
) -> ToolCall:
    """构造执行测试调用，允许故意传入损坏参数验证失败收口。"""
    return ToolCall(
        id=call_id,
        name=name,
        arguments={"expression": "1 + 2"} if arguments is None else arguments,
    )


def _definition(name: str, handler, parameters: dict[str, Any] | None = None):
    """构造低风险测试工具定义，默认不接收参数。"""
    return ToolDefinition(
        name=name,
        description=f"测试工具 {name}",
        parameters=parameters
        or {"type": "object", "properties": {}, "required": []},
        handler=handler,
        risk_level="low",
        parallel_safe=True,
        scope="global",
    )


def _corrupted_call(arguments: Any) -> ToolCall:
    """绕过 ToolCall 构造校验，模拟边界外传入的损坏模型参数。"""
    call = object.__new__(ToolCall)
    object.__setattr__(call, "id", "call-1")
    object.__setattr__(call, "name", "strict")
    object.__setattr__(call, "arguments", arguments)
    return call


class ToolExecutionTests(unittest.IsolatedAsyncioTestCase):
    """验证统一执行入口始终关联调用 ID，并在 handler 前后安全收口。"""

    async def test_calculator_success_preserves_tool_call_id(self) -> None:
        """合法计算通过注册表执行并返回关联原调用的成功结果。"""
        manager = ToolManager()
        manager.register(calculator_definition())
        result = await manager.execute(
            _call(arguments={"expression": "(2 + 3) * 4"}, call_id="calc-7"),
            permission_mode="allow",
        )
        self.assertEqual(result.tool_call_id, "calc-7")
        self.assertEqual(result.content, "20")
        self.assertFalse(result.is_error)

    async def test_current_time_success_returns_json_text(self) -> None:
        """无参数时间工具也通过相同执行入口返回成功结果。"""
        manager = ToolManager()
        manager.register(current_time_definition())
        result = await manager.execute(
            _call("current_time", {}, call_id="time-1"),
            permission_mode="allow",
        )
        self.assertEqual(result.tool_call_id, "time-1")
        self.assertIn('"timezone":', result.content)
        self.assertFalse(result.is_error)

    async def test_invalid_arguments_never_reach_handler(self) -> None:
        """缺失、未知、错误类型和损坏 JSON 参数均在 handler 前失败。"""
        executions = 0

        async def handler(_arguments: dict[str, Any]) -> str:
            """记录执行次数，用于证明参数失败没有产生副作用。"""
            nonlocal executions
            executions += 1
            return "unexpected"

        manager = ToolManager()
        manager.register(
            _definition(
                "strict",
                handler,
                {
                    "type": "object",
                    "properties": {"count": {"type": "integer"}},
                    "required": ["count"],
                },
            )
        )
        cases = (
            ({}, "missing"),
            ({"count": 1, "extra": True}, "unknown"),
            ({"count": "1"}, "type"),
        )
        for arguments, label in cases:
            with self.subTest(label=label):
                result = await manager.execute(
                    _call("strict", arguments), permission_mode="allow"
                )
                self.assertTrue(result.is_error)
                self.assertEqual(result.tool_call_id, "call-1")
        damaged = await manager.execute(
            _corrupted_call("{broken-json"), permission_mode="allow"
        )
        self.assertTrue(damaged.is_error)
        self.assertEqual(damaged.tool_call_id, "call-1")
        self.assertEqual(executions, 0)

    async def test_nested_types_and_constraints_are_validated(self) -> None:
        """数组、对象、布尔、长度与数值范围使用同一 Schema 子集校验。"""
        executions = 0

        async def handler(_arguments: dict[str, Any]) -> str:
            """记录合法嵌套参数是否真正进入 handler。"""
            nonlocal executions
            executions += 1
            return "ok"

        schema = {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "minimum": 1, "maximum": 5},
                "tags": {
                    "type": "array",
                    "items": {"type": "string", "maxLength": 4},
                    "maxItems": 2,
                },
                "options": {
                    "type": "object",
                    "properties": {"enabled": {"type": "boolean"}},
                    "required": ["enabled"],
                    "additionalProperties": False,
                },
            },
            "required": ["limit", "tags", "options"],
        }
        manager = ToolManager()
        manager.register(_definition("nested", handler, schema))
        valid = {"limit": 2, "tags": ["a", "b"], "options": {"enabled": True}}
        success = await manager.execute(_call("nested", valid), permission_mode="allow")
        self.assertFalse(success.is_error)
        invalid = {"limit": 9, "tags": ["long-tag"], "options": {"enabled": 1}}
        failure = await manager.execute(
            _call("nested", invalid), permission_mode="allow"
        )
        self.assertTrue(failure.is_error)
        self.assertEqual(executions, 1)

    async def test_handler_receives_independent_arguments_copy(self) -> None:
        """handler 修改参数不会污染后续需要持久化的原始 ToolCall。"""
        async def handler(arguments: dict[str, Any]) -> str:
            """故意修改参数副本，验证执行边界隔离。"""
            arguments["value"]["nested"] = "changed"
            return "ok"

        manager = ToolManager()
        manager.register(
            _definition(
                "mutate",
                handler,
                {
                    "type": "object",
                    "properties": {
                        "value": {
                            "type": "object",
                            "properties": {"nested": {"type": "string"}},
                            "required": ["nested"],
                            "additionalProperties": False,
                        }
                    },
                    "required": ["value"],
                },
            )
        )
        call = _call("mutate", {"value": {"nested": "original"}})
        result = await manager.execute(call, permission_mode="allow")
        self.assertFalse(result.is_error)
        self.assertEqual(call.arguments["value"]["nested"], "original")

    async def test_unknown_tool_returns_structured_failure(self) -> None:
        """未知工具不抛出到调用方，并保留原 tool_call_id。"""
        result = await ToolManager().execute(
            _call("missing", {}), permission_mode="allow"
        )
        self.assertTrue(result.is_error)
        self.assertEqual(result.tool_call_id, "call-1")
        self.assertIn("不存在", result.content)

    async def test_permission_modes_fail_closed_before_handler(self) -> None:
        """P03-04 前 deny、ask 和非法模式均不会运行 handler。"""
        executions = 0

        async def handler(_arguments: dict[str, Any]) -> str:
            """记录是否错误越过了最小权限闸门。"""
            nonlocal executions
            executions += 1
            return "unsafe"

        manager = ToolManager()
        manager.register(_definition("guarded", handler))
        for mode in ("deny", "ask", "invalid"):
            result = await manager.execute(_call("guarded", {}), permission_mode=mode)
            self.assertTrue(result.is_error)
        self.assertEqual(executions, 0)

    async def test_timeout_cancels_handler_and_returns_failure(self) -> None:
        """超过单工具期限时取消协作式 handler，并返回超时结果。"""
        cancelled = asyncio.Event()

        async def handler(_arguments: dict[str, Any]) -> str:
            """等待较长时间并在收到取消后留下可断言信号。"""
            try:
                await asyncio.sleep(10)
                return "late"
            finally:
                cancelled.set()

        manager = ToolManager(timeout_seconds=0.01)
        manager.register(_definition("slow", handler))
        result = await manager.execute(_call("slow", {}), permission_mode="allow")
        self.assertTrue(result.is_error)
        self.assertIn("超时", result.content)
        self.assertTrue(cancelled.is_set())

    async def test_handler_errors_are_safe_and_service_continues(self) -> None:
        """受控与未知异常都成为失败结果，下一次调用仍能成功。"""
        outcomes = ["controlled", "unexpected", "success"]

        async def handler(_arguments: dict[str, Any]) -> str:
            """依序制造受控失败、未知失败和成功，验证执行器不崩溃。"""
            outcome = outcomes.pop(0)
            if outcome == "controlled":
                raise ToolHandlerError("可恢复的测试失败")
            if outcome == "unexpected":
                raise RuntimeError("不应回显的内部细节")
            return "recovered"

        manager = ToolManager()
        manager.register(_definition("unstable", handler))
        controlled = await manager.execute(
            _call("unstable", {}), permission_mode="allow"
        )
        unexpected = await manager.execute(
            _call("unstable", {}), permission_mode="allow"
        )
        recovered = await manager.execute(
            _call("unstable", {}), permission_mode="allow"
        )
        self.assertTrue(controlled.is_error)
        self.assertIn("可恢复", controlled.content)
        self.assertTrue(unexpected.is_error)
        self.assertNotIn("内部细节", unexpected.content)
        self.assertFalse(recovered.is_error)
        self.assertEqual(recovered.content, "recovered")

    async def test_non_string_result_becomes_failure(self) -> None:
        """handler 违反字符串输出契约时不会把对象隐式序列化成成功。"""
        async def handler(_arguments: dict[str, Any]):
            """故意返回字典，验证运行时类型保护。"""
            return {"not": "text"}

        manager = ToolManager()
        manager.register(_definition("wrong_result", handler))
        result = await manager.execute(
            _call("wrong_result", {}), permission_mode="allow"
        )
        self.assertTrue(result.is_error)
        self.assertIn("结果类型", result.content)

    async def test_large_output_is_truncated_with_marker(self) -> None:
        """大输出保留头部和原始长度标记，最终内容不超过配置上限。"""
        async def handler(_arguments: dict[str, Any]) -> str:
            """返回固定大文本供截断测试。"""
            return "甲" * 200

        manager = ToolManager(max_output_chars=80)
        manager.register(_definition("large", handler))
        result = await manager.execute(_call("large", {}), permission_mode="allow")
        self.assertFalse(result.is_error)
        self.assertLessEqual(len(result.content), 80)
        self.assertIn("工具输出已截断", result.content)
        self.assertIn("200", result.content)

    async def test_outer_cancellation_is_not_converted_to_tool_failure(self) -> None:
        """调用方取消必须继续向上传播，不能伪装成普通工具错误。"""
        started = asyncio.Event()

        async def handler(_arguments: dict[str, Any]) -> str:
            """持续等待，直到测试取消外层执行任务。"""
            started.set()
            await asyncio.sleep(10)
            return "late"

        manager = ToolManager(timeout_seconds=5)
        manager.register(_definition("cancel_me", handler))
        pending = asyncio.create_task(
            manager.execute(_call("cancel_me", {}), permission_mode="allow")
        )
        await started.wait()
        pending.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await pending


class ToolManagerConfigurationTests(unittest.TestCase):
    """验证统一超时和输出上限不能使用危险或含糊配置。"""

    def test_invalid_execution_limits_are_rejected(self) -> None:
        """布尔、非有限、非正超时和过小或过大输出上限均失败。"""
        invalid_timeouts = (True, 0, -1, float("inf"), 601)
        for timeout in invalid_timeouts:
            with self.subTest(timeout=timeout):
                with self.assertRaises(ValueError):
                    ToolManager(timeout_seconds=timeout)
        invalid_outputs = (True, 0, 63, 1_000_001)
        for limit in invalid_outputs:
            with self.subTest(limit=limit):
                with self.assertRaises(ValueError):
                    ToolManager(max_output_chars=limit)


if __name__ == "__main__":
    unittest.main()
