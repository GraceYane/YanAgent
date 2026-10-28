"""P03-02 本机时间与受限计算器的安全行为测试。"""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from typing import Any, Coroutine
from unittest.mock import patch

from yanagent.tools import (
    SafeToolError,
    ToolManager,
    calculate_expression,
    calculator_handler,
    current_time_handler,
    current_time_info,
    register_safe_example_tools,
    safe_example_definitions,
)


def _complete(coroutine: Coroutine[Any, Any, str]) -> str:
    """推进不含等待点的示例 handler，避免单测依赖 Windows 事件循环资源。"""
    with unittest.TestCase().assertRaises(StopIteration) as stopped:
        coroutine.send(None)
    return stopped.exception.value


class CurrentTimeToolTests(unittest.TestCase):
    """验证时间工具的字段、时区表达和无参数边界。"""

    def test_current_time_info_uses_supplied_aware_time(self) -> None:
        """固定时间会生成稳定的中文星期、UTC 偏移和 ISO 8601 字段。"""
        moment = datetime(
            2026,
            10,
            23,
            15,
            4,
            5,
            tzinfo=timezone(timedelta(hours=8)),
        )
        self.assertEqual(
            current_time_info(moment),
            {
                "date": "2026-10-23",
                "time": "15:04:05",
                "weekday": "星期五",
                "timezone": "UTC+08:00",
                "iso8601": "2026-10-23T15:04:05+08:00",
            },
        )

    def test_current_time_handler_returns_strict_json(self) -> None:
        """时间 handler 返回包含完整字段的 JSON 文本。"""
        payload = json.loads(_complete(current_time_handler({})))
        self.assertEqual(
            set(payload), {"date", "time", "weekday", "timezone", "iso8601"}
        )
        datetime.fromisoformat(payload["iso8601"])

    def test_current_time_handler_rejects_arguments(self) -> None:
        """无参数工具不会静默忽略模型提交的未知字段。"""
        with self.assertRaises(SafeToolError):
            _complete(current_time_handler({"timezone": "UTC"}))


class CalculatorToolTests(unittest.TestCase):
    """验证计算器正确性、语法白名单和资源限制。"""

    def test_supported_arithmetic(self) -> None:
        """基础优先级、括号、单目、整除、取余和幂运算结果正确。"""
        cases = {
            "1 + 2 * 3": 7,
            "(10 - 4) / 3": 2.0,
            "-5 + +2": -3,
            "17 // 5": 3,
            "17 % 5": 2,
            "2 ** 8": 256,
        }
        for expression, expected in cases.items():
            with self.subTest(expression=expression):
                self.assertEqual(calculate_expression(expression), expected)

    def test_handler_formats_results(self) -> None:
        """handler 从严格参数对象取表达式并返回稳定文本。"""
        self.assertEqual(_complete(calculator_handler({"expression": "4 / 2"})), "2")
        self.assertEqual(
            _complete(calculator_handler({"expression": "0.1 + 0.2"})), "0.3"
        )

    def test_calculator_does_not_use_python_eval(self) -> None:
        """即使 Python eval 被禁止，受限 AST 计算仍能正常完成。"""
        with patch("builtins.eval", side_effect=AssertionError("不允许调用 eval")):
            self.assertEqual(calculate_expression("(2 + 3) * 4"), 20)

    def test_code_execution_syntax_is_rejected(self) -> None:
        """调用、名称、属性、下标、容器和位运算不会进入求值路径。"""
        expressions = (
            "__import__('os').system('echo unsafe')",
            "open('secret.txt')",
            "variable + 1",
            "(1).__class__",
            "[1][0]",
            "1 << 2",
            "True + 1",
        )
        for expression in expressions:
            with self.subTest(expression=expression):
                with self.assertRaises(SafeToolError):
                    calculate_expression(expression)

    def test_invalid_or_dangerous_math_is_rejected(self) -> None:
        """空表达式、除零、复数、超长、超复杂和巨大结果均受控失败。"""
        expressions = (
            "",
            "1 / 0",
            "(-1) ** 0.5",
            "1" * 257,
            "1+" * 40 + "1",
            "10 ** 101",
            "1e309",
        )
        for expression in expressions:
            with self.subTest(expression=expression[:30]):
                with self.assertRaises(SafeToolError):
                    calculate_expression(expression)

    def test_handler_requires_exact_typed_arguments(self) -> None:
        """缺失、未知字段和非字符串表达式都不能被 handler 接受。"""
        cases = (
            {},
            {"expression": "1", "extra": 2},
            {"expression": 1},
            {1: "非法参数名"},
        )
        for arguments in cases:
            with self.subTest(arguments=arguments):
                with self.assertRaises(SafeToolError):
                    _complete(calculator_handler(arguments))


class SafeExampleRegistrationTests(unittest.TestCase):
    """验证两个示例工具通过 P03-01 注册表暴露一致安全元数据。"""

    def test_definitions_have_expected_metadata_and_closed_schemas(self) -> None:
        """示例工具均为低风险、全局、并行安全且无需确认。"""
        definitions = safe_example_definitions()
        self.assertEqual(
            {definition.name for definition in definitions},
            {"current_time", "calculator"},
        )
        for definition in definitions:
            with self.subTest(name=definition.name):
                self.assertEqual(definition.risk_level, "low")
                self.assertEqual(definition.scope, "global")
                self.assertTrue(definition.parallel_safe)
                self.assertFalse(definition.requires_confirmation)
                self.assertIs(definition.parameters["additionalProperties"], False)

    def test_register_safe_examples_exports_provider_schemas(self) -> None:
        """统一注册入口产生稳定名称和可发给模型的 Schema。"""
        manager = ToolManager()
        register_safe_example_tools(manager)
        self.assertEqual(manager.names(), ("calculator", "current_time"))
        schemas = manager.schemas()
        self.assertEqual(
            [schema["name"] for schema in schemas], ["calculator", "current_time"]
        )
        calculator = schemas[0]
        self.assertEqual(calculator["parameters"]["required"], ["expression"])


if __name__ == "__main__":
    unittest.main()
