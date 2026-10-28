"""工具调用参数校验：实现 P03-03 所需的受控 JSON Schema 子集。"""

from __future__ import annotations

import math
from copy import deepcopy
from typing import Any


SUPPORTED_SCHEMA_TYPES = frozenset(
    {"object", "array", "string", "integer", "number", "boolean", "null"}
)
MAX_SCHEMA_VALIDATION_DEPTH = 32


class ToolArgumentError(ValueError):
    """表示模型提供的工具参数缺失、未知、类型错误或违反约束。"""

    _MESSAGES = {
        "invalid_object": "工具参数必须是 JSON 对象。",
        "missing": "工具参数缺少必填字段。",
        "unknown": "工具参数包含未知字段。",
        "type": "工具参数字段类型不符合 Schema。",
        "constraint": "工具参数字段不符合 Schema 约束。",
    }

    def __init__(self, *, reason: str) -> None:
        """把失败收敛到固定原因，避免在结果中回显模型原始参数。"""
        self.reason = reason if reason in self._MESSAGES else "constraint"
        super().__init__(self._MESSAGES[self.reason])


class ToolSchemaError(ValueError):
    """表示内部工具 Schema 超出当前支持范围或自身结构不合法。"""


def _schema_integer(schema: dict[str, Any], key: str) -> int | None:
    """读取非负整数 Schema 约束；定义错误与用户参数错误分开。"""
    value = schema.get(key)
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise ToolSchemaError(f"Schema 的 {key} 必须是非负整数")
    return value


def _schema_number(schema: dict[str, Any], key: str) -> int | float | None:
    """读取有限数值 Schema 约束，拒绝布尔值和 NaN/Infinity。"""
    value = schema.get(key)
    if value is None:
        return None
    if type(value) not in (int, float) or (
        type(value) is float and not math.isfinite(value)
    ):
        raise ToolSchemaError(f"Schema 的 {key} 必须是有限数字")
    return value


def _matches_type(value: Any, schema_type: str) -> bool:
    """按 JSON 类型严格匹配 Python 值，不把 bool 当作 integer 或 number。"""
    if schema_type == "object":
        return type(value) is dict
    if schema_type == "array":
        return type(value) is list
    if schema_type == "string":
        return type(value) is str
    if schema_type == "integer":
        return type(value) is int
    if schema_type == "number":
        return type(value) is int or (
            type(value) is float and math.isfinite(value)
        )
    if schema_type == "boolean":
        return type(value) is bool
    if schema_type == "null":
        return value is None
    return False


def _validate_enum(value: Any, schema: dict[str, Any]) -> None:
    """校验可选 enum，并避免 Python 把 True 与 1 当成相同枚举值。"""
    if "enum" not in schema:
        return
    choices = schema["enum"]
    if type(choices) is not list or not choices:
        raise ToolSchemaError("Schema 的 enum 必须是非空列表")
    if not any(type(value) is type(choice) and value == choice for choice in choices):
        raise ToolArgumentError(reason="constraint")


def _validate_object(value: dict[str, Any], schema: dict[str, Any], depth: int) -> None:
    """校验对象必填、未知字段和已声明属性的递归类型。"""
    if any(type(name) is not str for name in value):
        raise ToolArgumentError(reason="invalid_object")
    properties = schema.get("properties", {})
    required = schema.get("required", [])
    additional = schema.get("additionalProperties", True)
    if type(properties) is not dict:
        raise ToolSchemaError("Schema 的 properties 必须是对象")
    if type(required) is not list or any(type(name) is not str for name in required):
        raise ToolSchemaError("Schema 的 required 必须是字符串列表")
    if len(set(required)) != len(required) or any(
        name not in properties for name in required
    ):
        raise ToolSchemaError("Schema 的 required 必须唯一且引用已声明属性")
    if type(additional) is not bool:
        raise ToolSchemaError("当前仅支持布尔值 additionalProperties")
    if any(name not in value for name in required):
        raise ToolArgumentError(reason="missing")
    if additional is False and any(name not in properties for name in value):
        raise ToolArgumentError(reason="unknown")
    for name, item in value.items():
        property_schema = properties.get(name)
        if property_schema is None:
            continue
        if type(property_schema) is not dict:
            raise ToolSchemaError("Schema 的属性定义必须是对象")
        _validate_value(item, property_schema, depth=depth + 1)


def _validate_array(value: list[Any], schema: dict[str, Any], depth: int) -> None:
    """校验数组长度和可选 items Schema。"""
    minimum = _schema_integer(schema, "minItems")
    maximum = _schema_integer(schema, "maxItems")
    if minimum is not None and maximum is not None and minimum > maximum:
        raise ToolSchemaError("Schema 的 minItems 不能大于 maxItems")
    if minimum is not None and len(value) < minimum:
        raise ToolArgumentError(reason="constraint")
    if maximum is not None and len(value) > maximum:
        raise ToolArgumentError(reason="constraint")
    items = schema.get("items")
    if items is None:
        return
    if type(items) is not dict:
        raise ToolSchemaError("Schema 的 items 必须是对象")
    for item in value:
        _validate_value(item, items, depth=depth + 1)


def _validate_string(value: str, schema: dict[str, Any]) -> None:
    """校验字符串最小和最大字符数。"""
    minimum = _schema_integer(schema, "minLength")
    maximum = _schema_integer(schema, "maxLength")
    if minimum is not None and maximum is not None and minimum > maximum:
        raise ToolSchemaError("Schema 的 minLength 不能大于 maxLength")
    if minimum is not None and len(value) < minimum:
        raise ToolArgumentError(reason="constraint")
    if maximum is not None and len(value) > maximum:
        raise ToolArgumentError(reason="constraint")


def _validate_number(value: int | float, schema: dict[str, Any]) -> None:
    """校验数字最小值和最大值。"""
    minimum = _schema_number(schema, "minimum")
    maximum = _schema_number(schema, "maximum")
    if minimum is not None and maximum is not None and minimum > maximum:
        raise ToolSchemaError("Schema 的 minimum 不能大于 maximum")
    if minimum is not None and value < minimum:
        raise ToolArgumentError(reason="constraint")
    if maximum is not None and value > maximum:
        raise ToolArgumentError(reason="constraint")


def _validate_value(value: Any, schema: dict[str, Any], *, depth: int) -> None:
    """递归校验一个值；超过深度时视为内部 Schema 不适合当前执行器。"""
    if depth > MAX_SCHEMA_VALIDATION_DEPTH:
        raise ToolSchemaError("工具参数 Schema 嵌套过深")
    schema_type = schema.get("type")
    if type(schema_type) is not str or schema_type not in SUPPORTED_SCHEMA_TYPES:
        raise ToolSchemaError("Schema 必须声明受支持的单一 type")
    if not _matches_type(value, schema_type):
        raise ToolArgumentError(reason="type")
    _validate_enum(value, schema)
    if schema_type == "object":
        _validate_object(value, schema, depth)
    elif schema_type == "array":
        _validate_array(value, schema, depth)
    elif schema_type == "string":
        _validate_string(value, schema)
    elif schema_type in ("integer", "number"):
        _validate_number(value, schema)


def validate_tool_arguments(
    arguments: Any,
    schema: dict[str, Any],
) -> dict[str, Any]:
    """校验并复制工具参数，保证 handler 不能修改原始 ToolCall 参数。"""
    if type(arguments) is not dict:
        raise ToolArgumentError(reason="invalid_object")
    if type(schema) is not dict:
        raise ToolSchemaError("工具参数 Schema 必须是对象")
    _validate_value(arguments, schema, depth=0)
    return deepcopy(arguments)
