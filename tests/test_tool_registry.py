"""P03-01 工具定义、唯一注册、元数据与模型 Schema 导出测试。"""

from __future__ import annotations

import concurrent.futures
import math
import unittest

from yanagent.contracts import Message
from yanagent.models.openai_compatible import prepare_request
from yanagent.tools import (
    ToolAlreadyRegisteredError,
    ToolDefinition,
    ToolDefinitionError,
    ToolManager,
)


async def _handler(arguments: dict[str, object]) -> str:
    """返回固定文本的测试处理函数；P03-01 不实际调用它。"""
    return str(arguments)


def _definition(
    name: str = "calculator",
    *,
    parameters: object | None = None,
    **overrides: object,
) -> ToolDefinition:
    """构造一份合法定义，允许单个测试覆盖目标字段。"""
    values: dict[str, object] = {
        "name": name,
        "description": "安全计算一个表达式",
        "parameters": (
            parameters
            if parameters is not None
            else {
                "type": "object",
                "properties": {"expression": {"type": "string"}},
                "required": ["expression"],
            }
        ),
        "handler": _handler,
        "risk_level": "low",
        "parallel_safe": True,
        "scope": "global",
        "requires_confirmation": False,
    }
    values.update(overrides)
    return ToolDefinition(**values)


class ToolDefinitionTests(unittest.TestCase):
    """验证工具定义在进入注册表前已具有安全且稳定的元数据。"""

    def test_definition_normalizes_safe_object_schema(self) -> None:
        """合法定义会修剪说明，并明确禁止未知顶层参数。"""
        definition = _definition(description="  安全计算一个表达式  ")
        self.assertEqual(definition.description, "安全计算一个表达式")
        self.assertEqual(definition.parameters["additionalProperties"], False)
        self.assertEqual(definition.parameters["required"], ["expression"])

    def test_invalid_names_are_rejected(self) -> None:
        """空白、路径式、中文和过长名称不能进入模型工具命名空间。"""
        for name in ("", "bad name", "../read", "计算器", "a" * 65):
            with self.subTest(name=name):
                with self.assertRaises(ToolDefinitionError):
                    _definition(name)

    def test_invalid_metadata_is_rejected(self) -> None:
        """说明、handler、风险、并行标记、范围和确认标记均严格校验。"""
        cases = [
            {"description": "   "},
            {"description": "坏说明\x00"},
            {"handler": "not-callable"},
            {"handler": lambda _arguments: "sync"},
            {"risk_level": "critical"},
            {"parallel_safe": 1},
            {"scope": "filesystem"},
            {"requires_confirmation": 1},
        ]
        for overrides in cases:
            with self.subTest(overrides=overrides):
                with self.assertRaises(ToolDefinitionError):
                    _definition(**overrides)

    def test_invalid_parameter_schemas_are_rejected(self) -> None:
        """参数必须是封闭对象 Schema，必填字段必须存在且 JSON 值安全。"""
        cyclic: dict[str, object] = {"type": "object"}
        cyclic["properties"] = cyclic
        cases = [
            [],
            {"type": "array"},
            {"type": "object", "properties": []},
            {
                "type": "object",
                "properties": {"x": {"type": "number"}},
                "required": ["missing"],
            },
            {
                "type": "object",
                "properties": {"x": {"type": "number"}},
                "required": ["x", "x"],
            },
            {"type": "object", "additionalProperties": True},
            {"type": "object", "maximum": math.inf},
            cyclic,
        ]
        for parameters in cases:
            with self.subTest(parameters=type(parameters).__name__):
                with self.assertRaises(ToolDefinitionError):
                    _definition(parameters=parameters)

    def test_definition_does_not_share_callers_schema(self) -> None:
        """构造后修改原字典不会改变工具定义，避免热加载时发生隐式漂移。"""
        parameters = {
            "type": "object",
            "properties": {"value": {"type": "integer"}},
        }
        definition = _definition(parameters=parameters)
        parameters["properties"]["other"] = {"type": "string"}
        self.assertNotIn("other", definition.parameters["properties"])


class ToolManagerTests(unittest.TestCase):
    """验证注册唯一性、并发边界、发现和 Schema 快照。"""

    def setUp(self) -> None:
        """为每个用例创建独立空注册表。"""
        self.manager = ToolManager()

    def test_register_get_names_and_catalog(self) -> None:
        """注册后可按稳定名称发现，并保留完整风险、并行和范围元数据。"""
        self.manager.register(_definition())
        stored = self.manager.get("calculator")
        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(self.manager.names(), ("calculator",))
        self.assertEqual(stored.risk_level, "low")
        self.assertTrue(stored.parallel_safe)
        self.assertEqual(stored.scope, "global")
        self.assertEqual(self.manager.catalog()[0]["requires_confirmation"], False)
        stored.parameters["properties"]["polluted"] = {"type": "string"}
        fresh = self.manager.get("calculator")
        assert fresh is not None
        self.assertNotIn("polluted", fresh.parameters["properties"])
        self.assertIsNone(self.manager.get("missing"))

    def test_duplicate_registration_does_not_replace_original(self) -> None:
        """同名定义明确失败，原 handler 和说明保持不变。"""
        original = _definition(description="原始定义")
        self.manager.register(original)
        with self.assertRaises(ToolAlreadyRegisteredError):
            self.manager.register(_definition(description="试图覆盖"))
        stored = self.manager.get("calculator")
        assert stored is not None
        self.assertEqual(stored.description, "原始定义")
        self.assertIs(stored.handler, original.handler)

    def test_concurrent_duplicate_registration_has_one_winner(self) -> None:
        """两个线程同时注册同名工具时只允许一个成功。"""
        def register_once(index: int) -> str:
            """尝试注册带不同说明的同名定义，并返回可断言结果。"""
            try:
                self.manager.register(_definition(description=f"定义-{index}"))
                return "registered"
            except ToolAlreadyRegisteredError:
                return "duplicate"

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(register_once, range(2)))
        self.assertEqual(sorted(outcomes), ["duplicate", "registered"])
        self.assertEqual(self.manager.names(), ("calculator",))

    def test_schemas_are_sorted_independent_and_provider_compatible(self) -> None:
        """模型 Schema 顺序稳定、无内部安全字段，并可直接交给 Provider 适配器。"""
        self.manager.register(_definition("z_tool"))
        self.manager.register(_definition("a_tool"))
        schemas = self.manager.schemas()
        self.assertEqual([item["name"] for item in schemas], ["a_tool", "z_tool"])
        self.assertEqual(set(schemas[0]), {"name", "description", "parameters"})
        self.assertNotIn("risk_level", schemas[0])
        messages, converted = prepare_request(
            [Message(role="user", content="计算 1+1")], schemas
        )
        self.assertEqual(messages[0]["content"], "计算 1+1")
        self.assertEqual(converted[0]["type"], "function")
        self.assertEqual(converted[0]["function"]["name"], "a_tool")

        schemas[0]["parameters"]["properties"]["polluted"] = {"type": "string"}
        self.assertNotIn(
            "polluted", self.manager.schemas()[0]["parameters"]["properties"]
        )

    def test_register_rejects_non_definition(self) -> None:
        """普通字典不能绕过 ToolDefinition 的校验直接进入注册表。"""
        with self.assertRaises(ToolDefinitionError):
            self.manager.register({"name": "unsafe"})

if __name__ == "__main__":
    unittest.main()
