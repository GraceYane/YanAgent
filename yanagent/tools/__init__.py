"""工具系统的定义、注册表、安全示例工具与后续执行入口。"""

from .manager import (
    ToolAlreadyRegisteredError,
    ToolDefinition,
    ToolDefinitionError,
    ToolHandlerError,
    ToolHandler,
    ToolManager,
    ToolRisk,
    ToolScope,
)
from .validation import ToolArgumentError, ToolSchemaError, validate_tool_arguments
from .examples import (
    SafeToolError,
    calculate_expression,
    calculator_definition,
    calculator_handler,
    current_time_definition,
    current_time_handler,
    current_time_info,
    register_safe_example_tools,
    safe_example_definitions,
)

__all__ = [
    "SafeToolError",
    "ToolAlreadyRegisteredError",
    "ToolDefinition",
    "ToolDefinitionError",
    "ToolHandlerError",
    "ToolHandler",
    "ToolManager",
    "ToolRisk",
    "ToolScope",
    "ToolArgumentError",
    "ToolSchemaError",
    "calculate_expression",
    "calculator_definition",
    "calculator_handler",
    "current_time_definition",
    "current_time_handler",
    "current_time_info",
    "register_safe_example_tools",
    "safe_example_definitions",
    "validate_tool_arguments",
]
