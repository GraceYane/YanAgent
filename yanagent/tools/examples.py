"""P03-02 安全示例工具：本地时间与受限算术计算器。"""

from __future__ import annotations

import ast
import json
import logging
import operator
from datetime import datetime
from typing import Any

from .manager import ToolDefinition, ToolManager


LOGGER = logging.getLogger("yanagent.tools")
MAX_EXPRESSION_CHARS = 256
MAX_AST_NODES = 64
MAX_AST_DEPTH = 16
MAX_EXPONENT = 100
MAX_ABSOLUTE_VALUE = 10**100
_WEEKDAYS_ZH = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")
_BINARY_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
}
_UNARY_OPERATORS = {ast.UAdd: operator.pos, ast.USub: operator.neg}


class SafeToolError(ValueError):
    """表示安全示例工具收到非法输入或无法安全完成计算。"""


def _utc_offset_label(moment: datetime) -> str:
    """把有时区时间的 UTC 偏移格式化为固定的 UTC±HH:MM。"""
    offset = moment.utcoffset()
    if offset is None:
        raise SafeToolError("当前时间缺少时区偏移")
    total_minutes = int(offset.total_seconds() // 60)
    sign = "+" if total_minutes >= 0 else "-"
    hours, minutes = divmod(abs(total_minutes), 60)
    return f"UTC{sign}{hours:02d}:{minutes:02d}"


def current_time_info(moment: datetime | None = None) -> dict[str, str]:
    """返回本机当前日期、时间、星期、UTC 偏移和 ISO 8601 时间。"""
    if moment is None:
        current = datetime.now().astimezone()
    elif moment.tzinfo is None or moment.utcoffset() is None:
        current = moment.astimezone()
    else:
        current = moment
    return {
        "date": current.strftime("%Y-%m-%d"),
        "time": current.strftime("%H:%M:%S"),
        "weekday": _WEEKDAYS_ZH[current.weekday()],
        "timezone": _utc_offset_label(current),
        "iso8601": current.isoformat(timespec="seconds"),
    }


def _require_arguments(arguments: Any, expected: set[str]) -> dict[str, Any]:
    """在 handler 边界再次检查参数对象和精确字段，作为 Schema 校验前的防线。"""
    if type(arguments) is not dict:
        raise SafeToolError("工具参数必须是对象")
    if any(type(name) is not str for name in arguments):
        raise SafeToolError("工具参数名必须是字符串")
    received = set(arguments)
    if received != expected:
        missing = sorted(expected - received)
        unknown = sorted(received - expected)
        if missing:
            raise SafeToolError(f"缺少工具参数：{', '.join(missing)}")
        raise SafeToolError(f"包含未知工具参数：{', '.join(unknown)}")
    return arguments


async def current_time_handler(arguments: dict[str, Any]) -> str:
    """读取一次本机时间并返回严格 JSON；不访问网络或用户私有数据。"""
    _require_arguments(arguments, set())
    info = current_time_info()
    LOGGER.info(
        "[examples.py][current_time_handler] 已读取本机时间，date=%s，timezone=%s",
        info["date"],
        info["timezone"],
    )
    return json.dumps(info, ensure_ascii=False, separators=(",", ":"))


def _checked_number(value: Any) -> int | float:
    """只接受有限实数并限制绝对值，阻止巨大整数和非有限浮点结果。"""
    if type(value) is int:
        if abs(value) > MAX_ABSOLUTE_VALUE:
            raise SafeToolError("数值超过计算器允许范围")
        return value
    if type(value) is float:
        if value != value or value in (float("inf"), float("-inf")):
            raise SafeToolError("计算结果不是有限实数")
        if abs(value) > MAX_ABSOLUTE_VALUE:
            raise SafeToolError("数值超过计算器允许范围")
        return value
    raise SafeToolError("计算器只支持整数和小数")


def _evaluate_node(node: ast.AST, *, depth: int = 0) -> int | float:
    """递归计算白名单 AST 节点，拒绝名称、调用、属性和容器等语法。"""
    if depth > MAX_AST_DEPTH:
        raise SafeToolError("表达式嵌套过深")
    if isinstance(node, ast.Expression):
        return _evaluate_node(node.body, depth=depth + 1)
    if isinstance(node, ast.Constant):
        return _checked_number(node.value)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPERATORS:
        operand = _evaluate_node(node.operand, depth=depth + 1)
        return _checked_number(_UNARY_OPERATORS[type(node.op)](operand))
    if isinstance(node, ast.BinOp):
        left = _evaluate_node(node.left, depth=depth + 1)
        right = _evaluate_node(node.right, depth=depth + 1)
        if isinstance(node.op, ast.Pow):
            if abs(right) > MAX_EXPONENT:
                raise SafeToolError("指数超过计算器允许范围")
            try:
                return _checked_number(left**right)
            except (OverflowError, ZeroDivisionError):
                raise SafeToolError("幂运算超出允许范围或除数为零") from None
        operation = _BINARY_OPERATORS.get(type(node.op))
        if operation is None:
            raise SafeToolError("表达式包含不支持的运算符")
        try:
            return _checked_number(operation(left, right))
        except ZeroDivisionError:
            raise SafeToolError("除数不能为零") from None
        except OverflowError:
            raise SafeToolError("计算结果超过允许范围") from None
    raise SafeToolError("表达式只允许数字、括号和基础算术运算符")


def calculate_expression(expression: str) -> int | float:
    """使用 Python AST 白名单解析算术表达式，绝不执行任意代码。"""
    if type(expression) is not str:
        raise SafeToolError("expression 必须是字符串")
    source = expression.strip()
    if not source:
        raise SafeToolError("expression 不能为空")
    if len(source) > MAX_EXPRESSION_CHARS:
        raise SafeToolError("表达式过长")
    try:
        tree = ast.parse(source, mode="eval")
    except (SyntaxError, ValueError, MemoryError, RecursionError):
        raise SafeToolError("表达式语法不合法") from None
    if sum(1 for _node in ast.walk(tree)) > MAX_AST_NODES:
        raise SafeToolError("表达式结构过于复杂")
    try:
        return _evaluate_node(tree)
    except RecursionError:
        raise SafeToolError("表达式嵌套过深") from None


def _format_number(value: int | float) -> str:
    """把安全计算结果转换为稳定文本，整数值浮点数不保留无意义小数点。"""
    if type(value) is int:
        return str(value)
    if value == 0:
        return "0"
    if value.is_integer():
        return str(int(value))
    return format(value, ".15g")


async def calculator_handler(arguments: dict[str, Any]) -> str:
    """校验参数并调用受限解析器，返回可直接写入 ToolResult 的数值文本。"""
    checked = _require_arguments(arguments, {"expression"})
    expression = checked["expression"]
    LOGGER.info(
        "[examples.py][calculator_handler] 开始安全计算，表达式长度=%s",
        len(expression) if isinstance(expression, str) else "<非字符串>",
    )
    try:
        result = calculate_expression(expression)
    except SafeToolError as error:
        LOGGER.warning(
            "[examples.py][calculator_handler] 安全计算被拒绝，原因=%s",
            str(error),
        )
        raise
    LOGGER.info(
        "[examples.py][calculator_handler] 安全计算完成，结果类型=%s",
        type(result).__name__,
    )
    return _format_number(result)


def current_time_definition() -> ToolDefinition:
    """创建只读、可并行且不需要确认的本机时间工具定义。"""
    return ToolDefinition(
        name="current_time",
        description=(
            "读取运行 YanAgent 的本机当前日期、时间、星期和 UTC 偏移。"
            "当回答依赖当前时刻时调用，不要猜测时间。"
        ),
        parameters={"type": "object", "properties": {}, "required": []},
        handler=current_time_handler,
        risk_level="low",
        parallel_safe=True,
        scope="global",
        requires_confirmation=False,
    )


def calculator_definition() -> ToolDefinition:
    """创建只支持基础算术表达式的低风险计算器工具定义。"""
    return ToolDefinition(
        name="calculator",
        description=(
            "计算只包含数字、括号、加减乘除、整除、取余和有限次幂的算术表达式。"
            "不支持变量、函数、属性、容器、导入或任何代码执行。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": MAX_EXPRESSION_CHARS,
                    "description": "需要计算的基础算术表达式，例如 (1 + 2) * 3。",
                }
            },
            "required": ["expression"],
        },
        handler=calculator_handler,
        risk_level="low",
        parallel_safe=True,
        scope="global",
        requires_confirmation=False,
    )


def safe_example_definitions() -> tuple[ToolDefinition, ...]:
    """按固定顺序创建 P03-02 的全部安全示例工具定义。"""
    return (current_time_definition(), calculator_definition())


def register_safe_example_tools(manager: ToolManager) -> None:
    """把 P03-02 示例工具注册到指定管理器，重复名称继续由注册表拒绝。"""
    if not isinstance(manager, ToolManager):
        raise TypeError("manager 必须是 ToolManager")
    definitions = safe_example_definitions()
    for definition in definitions:
        manager.register(definition)
    LOGGER.info(
        "[examples.py][register_safe_example_tools] 安全示例工具注册完成，数量=%d",
        len(definitions),
    )
