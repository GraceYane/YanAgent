"""工具系统的定义、注册表、安全示例、权限与统一执行入口。"""

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
from .permissions import (
    PermissionMode,
    ToolConfirmationRequest,
    ToolConfirmationResult,
    ToolPermissionContext,
    ToolPermissionDecision,
    build_confirmation_request,
    evaluate_tool_permission,
)
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
    "PermissionMode",
    "ToolConfirmationRequest",
    "ToolConfirmationResult",
    "ToolPermissionContext",
    "ToolPermissionDecision",
    "ToolArgumentError",
    "ToolSchemaError",
    "calculate_expression",
    "build_confirmation_request",
    "calculator_definition",
    "calculator_handler",
    "current_time_definition",
    "current_time_handler",
    "current_time_info",
    "evaluate_tool_permission",
    "register_safe_example_tools",
    "safe_example_definitions",
    "validate_tool_arguments",
]
