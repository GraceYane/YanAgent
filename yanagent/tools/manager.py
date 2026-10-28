"""工具定义、注册表与执行入口：统一 Schema、权限、校验和结果。"""

from __future__ import annotations

import asyncio
import inspect
import logging
import math
import re
import threading
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from yanagent.contracts import ContractValidationError, ToolCall, ToolResult

from .validation import ToolArgumentError, ToolSchemaError, validate_tool_arguments
from .permissions import (
    TOOL_PERMISSION_MODES,
    ToolConfirmationResult,
    ToolPermissionContext,
    ToolPermissionDecision,
    evaluate_tool_permission,
)


LOGGER = logging.getLogger("yanagent.tools")
ToolHandler = Callable[[dict[str, Any]], Awaitable[str]]
ToolRisk = Literal["low", "medium", "high"]
ToolScope = Literal["global", "user", "agent", "session", "workspace"]
TOOL_NAME_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,64}")
TOOL_RISKS = frozenset({"low", "medium", "high"})
TOOL_SCOPES = frozenset({"global", "user", "agent", "session", "workspace"})
PERMISSION_MODES = TOOL_PERMISSION_MODES
DEFAULT_TOOL_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_TOOL_OUTPUT_CHARS = 20_000
MIN_TOOL_OUTPUT_CHARS = 64
MAX_TOOL_OUTPUT_CHARS = 1_000_000
MAX_CONSUMED_CONFIRMATIONS = 10_000


class ToolDefinitionError(ValueError):
    """表示工具名称、说明、Schema 或执行元数据不符合注册约定。"""


class ToolAlreadyRegisteredError(ToolDefinitionError):
    """表示注册表中已存在同名工具，避免后注册实现静默覆盖原工具。"""


class ToolHandlerError(ValueError):
    """表示 handler 主动返回可安全展示给模型的受控失败说明。"""

    def __init__(self, message: str) -> None:
        """限制公开错误长度和控制字符，避免 handler 将任意内容写入历史。"""
        if type(message) is not str or not message.strip() or len(message) > 500:
            raise ValueError("工具公开错误必须是 1～500 个字符")
        if any(ord(character) < 32 or ord(character) == 127 for character in message):
            raise ValueError("工具公开错误不允许包含非法控制字符")
        self.public_message = message.strip()
        super().__init__(self.public_message)


def _is_async_callable(value: Any) -> bool:
    """判断函数或可调用对象是否声明异步入口，避免执行阶段才发现不可等待。"""
    return inspect.iscoroutinefunction(value) or inspect.iscoroutinefunction(
        getattr(value, "__call__", None)
    )


def _copy_json(value: Any, *, active: set[int] | None = None) -> Any:
    """复制严格 JSON 值，拒绝循环引用、非字符串键和非有限数字。"""
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float:
        if math.isfinite(value):
            return value
        raise ToolDefinitionError("工具参数 Schema 不允许 NaN 或 Infinity")
    if type(value) not in (dict, list):
        raise ToolDefinitionError("工具参数 Schema 只能包含标准 JSON 类型")
    active = set() if active is None else active
    identity = id(value)
    if identity in active:
        raise ToolDefinitionError("工具参数 Schema 不允许循环引用")
    active.add(identity)
    try:
        if type(value) is list:
            return [_copy_json(item, active=active) for item in value]
        if any(type(key) is not str for key in value):
            raise ToolDefinitionError("工具参数 Schema 的对象键必须是字符串")
        return {key: _copy_json(item, active=active) for key, item in value.items()}
    finally:
        active.remove(identity)


def _normalize_parameters(parameters: Any) -> dict[str, Any]:
    """校验并复制对象参数 Schema，默认禁止模型提交未声明的顶层字段。"""
    copied = _copy_json(parameters)
    if type(copied) is not dict or copied.get("type") != "object":
        raise ToolDefinitionError("工具参数 Schema 顶层 type 必须是 object")
    properties = copied.get("properties", {})
    if type(properties) is not dict:
        raise ToolDefinitionError("工具参数 Schema 的 properties 必须是对象")
    required = copied.get("required", [])
    if (
        type(required) is not list
        or any(type(name) is not str or not name for name in required)
        or len(set(required)) != len(required)
    ):
        raise ToolDefinitionError("工具参数 Schema 的 required 必须是唯一非空字符串列表")
    if any(name not in properties for name in required):
        raise ToolDefinitionError("工具参数 Schema 的 required 必须引用已声明属性")
    additional = copied.get("additionalProperties", False)
    if additional is not False:
        raise ToolDefinitionError("工具参数 Schema 当前必须禁止未知顶层字段")
    copied["properties"] = properties
    copied["required"] = required
    copied["additionalProperties"] = False
    return copied


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """描述一个可注册工具的模型接口、安全属性和异步处理函数。"""

    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler
    risk_level: ToolRisk = "low"
    parallel_safe: bool = False
    scope: ToolScope = "session"
    requires_confirmation: bool = False

    def __post_init__(self) -> None:
        """构造时验证元数据并保存独立 Schema，防止外部字典后改污染定义。"""
        if type(self.name) is not str or TOOL_NAME_PATTERN.fullmatch(self.name) is None:
            raise ToolDefinitionError("工具名称必须是 1～64 位 ASCII 字母、数字、下划线或连字符")
        if type(self.description) is not str or not self.description.strip():
            raise ToolDefinitionError("工具说明必须是非空字符串")
        if len(self.description) > 2_000:
            raise ToolDefinitionError("工具说明不能超过 2000 个字符")
        if any(
            (ord(character) < 32 and character not in "\r\n\t")
            or ord(character) == 127
            for character in self.description
        ):
            raise ToolDefinitionError("工具说明不允许包含非法控制字符")
        if not callable(self.handler) or not _is_async_callable(self.handler):
            raise ToolDefinitionError("工具 handler 必须是异步可调用对象")
        if type(self.risk_level) is not str or self.risk_level not in TOOL_RISKS:
            raise ToolDefinitionError("工具风险必须是 low、medium 或 high")
        if type(self.parallel_safe) is not bool:
            raise ToolDefinitionError("工具 parallel_safe 必须是布尔值")
        if type(self.scope) is not str or self.scope not in TOOL_SCOPES:
            raise ToolDefinitionError("工具 scope 不受支持")
        if type(self.requires_confirmation) is not bool:
            raise ToolDefinitionError("工具 requires_confirmation 必须是布尔值")
        object.__setattr__(self, "description", self.description.strip())
        object.__setattr__(self, "parameters", _normalize_parameters(self.parameters))

    def model_schema(self) -> dict[str, Any]:
        """导出 Provider 可接收的统一函数 Schema，不暴露 handler 和权限元数据。"""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": _copy_json(self.parameters),
        }

    def catalog_entry(self) -> dict[str, Any]:
        """导出内部工具目录条目，包含调度和权限阶段需要的安全元数据。"""
        return {
            **self.model_schema(),
            "risk_level": self.risk_level,
            "parallel_safe": self.parallel_safe,
            "scope": self.scope,
            "requires_confirmation": self.requires_confirmation,
        }


class ToolManager:
    """线程安全地注册、发现并在权限边界内执行工具。"""

    def __init__(
        self,
        *,
        timeout_seconds: float = DEFAULT_TOOL_TIMEOUT_SECONDS,
        max_output_chars: int = DEFAULT_MAX_TOOL_OUTPUT_CHARS,
    ) -> None:
        """创建带统一超时和输出上限的空注册表，所有定义读写受锁保护。"""
        if (
            type(timeout_seconds) not in (int, float)
            or not math.isfinite(timeout_seconds)
            or not 0 < timeout_seconds <= 600
        ):
            raise ValueError("工具超时必须是 0～600 秒之间的有限数字")
        if (
            type(max_output_chars) is not int
            or not MIN_TOOL_OUTPUT_CHARS <= max_output_chars <= MAX_TOOL_OUTPUT_CHARS
        ):
            raise ValueError("工具输出上限必须是 64～1000000 之间的整数")
        self.timeout_seconds = float(timeout_seconds)
        self.max_output_chars = max_output_chars
        self._definitions: dict[str, ToolDefinition] = {}
        self._consumed_confirmation_ids: set[str] = set()
        self._lock = threading.RLock()

    def register(self, definition: ToolDefinition) -> None:
        """注册定义快照；同名工具无论实现是否相同都明确拒绝。"""
        if not isinstance(definition, ToolDefinition):
            raise ToolDefinitionError("只能注册 ToolDefinition")
        snapshot = ToolDefinition(
            name=definition.name,
            description=definition.description,
            parameters=definition.parameters,
            handler=definition.handler,
            risk_level=definition.risk_level,
            parallel_safe=definition.parallel_safe,
            scope=definition.scope,
            requires_confirmation=definition.requires_confirmation,
        )
        with self._lock:
            if snapshot.name in self._definitions:
                LOGGER.warning(
                    "[manager.py][ToolManager.register] 拒绝重复工具，name=%s",
                    snapshot.name,
                )
                raise ToolAlreadyRegisteredError(f"工具已注册：{snapshot.name}")
            self._definitions[snapshot.name] = snapshot
        LOGGER.info(
            "[manager.py][ToolManager.register] 工具已注册，"
            "name=%s，risk=%s，scope=%s，parallel_safe=%s",
            snapshot.name,
            snapshot.risk_level,
            snapshot.scope,
            snapshot.parallel_safe,
        )

    def get(self, name: str) -> ToolDefinition | None:
        """按精确名称读取独立定义副本；未知或非法名称返回 None。"""
        if type(name) is not str:
            return None
        with self._lock:
            definition = self._definitions.get(name)
            if definition is None:
                return None
            return ToolDefinition(
                name=definition.name,
                description=definition.description,
                parameters=definition.parameters,
                handler=definition.handler,
                risk_level=definition.risk_level,
                parallel_safe=definition.parallel_safe,
                scope=definition.scope,
                requires_confirmation=definition.requires_confirmation,
            )

    def names(self) -> tuple[str, ...]:
        """返回按名称排序的不可变快照，供日志、测试和后续工具列表接口使用。"""
        with self._lock:
            return tuple(sorted(self._definitions))

    def schemas(self) -> list[dict[str, Any]]:
        """按名称稳定导出模型 Schema；返回值可修改但不会污染注册表。"""
        with self._lock:
            schemas = [
                self._definitions[name].model_schema()
                for name in sorted(self._definitions)
            ]
        LOGGER.info(
            "[manager.py][ToolManager.schemas] 已导出模型工具 Schema，数量=%d",
            len(schemas),
        )
        return schemas

    def catalog(self) -> list[dict[str, Any]]:
        """按名称稳定导出含风险、并行和作用范围的内部工具目录。"""
        with self._lock:
            return [
                self._definitions[name].catalog_entry()
                for name in sorted(self._definitions)
            ]

    def _failure(self, call_id: str, content: str) -> ToolResult:
        """构造关联原调用 ID 的统一失败结果。"""
        result = ToolResult(tool_call_id=call_id, content=content, is_error=True)
        result.validate()
        return result

    def _truncate_output(self, content: str) -> tuple[str, bool]:
        """按字符数截断工具输出，并把原始长度写入保留在上限内的标记。"""
        if len(content) <= self.max_output_chars:
            return content, False
        marker = f"\n...[工具输出已截断，原始字符数={len(content)}]"
        prefix_length = self.max_output_chars - len(marker)
        return content[:prefix_length] + marker, True

    def _consume_confirmation(
        self,
        decision: ToolPermissionDecision,
        confirmation: ToolConfirmationResult | None,
    ) -> ToolPermissionDecision:
        """原子消费批准结果，阻止并发或重试重复执行同一受确认调用。"""
        if decision.reason != "confirmation_approved":
            return decision
        assert confirmation is not None
        with self._lock:
            if confirmation.request_id in self._consumed_confirmation_ids:
                return ToolPermissionDecision("denied", "confirmation_replayed")
            if len(self._consumed_confirmation_ids) >= MAX_CONSUMED_CONFIRMATIONS:
                return ToolPermissionDecision("denied", "confirmation_capacity")
            self._consumed_confirmation_ids.add(confirmation.request_id)
        return decision

    async def execute(
        self,
        call: ToolCall,
        *,
        permission_mode: str,
        permission_context: ToolPermissionContext | None = None,
        confirmation: ToolConfirmationResult | None = None,
    ) -> ToolResult:
        """校验并执行一次工具调用，把所有可预期失败转换为结构化 ToolResult。"""
        if not isinstance(call, ToolCall):
            raise TypeError("call 必须是 ToolCall")
        if type(call.id) is not str or not call.id.strip():
            raise ValueError("ToolCall.id 必须是非空字符串")
        call_id = call.id
        try:
            call.validate()
        except ContractValidationError:
            LOGGER.warning(
                "[manager.py][ToolManager.execute] 工具调用契约无效，call_id=%r",
                call_id,
            )
            return self._failure(call_id, "工具调用格式不合法。")

        if type(permission_mode) is not str or permission_mode not in PERMISSION_MODES:
            LOGGER.warning(
                "[manager.py][ToolManager.execute] 权限模式无效，call_id=%r",
                call_id,
            )
            return self._failure(call_id, "工具权限模式不合法。")
        if permission_mode == "deny":
            LOGGER.info(
                "[manager.py][ToolManager.execute] 当前模式禁止执行工具，"
                "call_id=%r，tool=%r，mode=%s",
                call_id,
                call.name,
                permission_mode,
            )
            return self._failure(call_id, "当前权限模式禁止执行工具。")
        if permission_context is not None and not isinstance(
            permission_context, ToolPermissionContext
        ):
            LOGGER.warning(
                "[manager.py][ToolManager.execute] 权限上下文无效，call_id=%r",
                call_id,
            )
            return self._failure(call_id, "工具权限上下文不合法。")
        if confirmation is not None and not isinstance(confirmation, ToolConfirmationResult):
            LOGGER.warning(
                "[manager.py][ToolManager.execute] 确认结果类型无效，call_id=%r",
                call_id,
            )
            return self._failure(call_id, "工具确认结果不合法。")

        definition = self.get(call.name)
        if definition is None:
            LOGGER.warning(
                "[manager.py][ToolManager.execute] 未找到工具，call_id=%r，tool=%r",
                call_id,
                call.name,
            )
            return self._failure(call_id, "工具不存在或当前不可用。")
        try:
            arguments = validate_tool_arguments(call.arguments, definition.parameters)
        except ToolArgumentError as error:
            LOGGER.info(
                "[manager.py][ToolManager.execute] 工具参数校验失败，"
                "call_id=%r，tool=%r，reason=%s",
                call_id,
                call.name,
                error.reason,
            )
            return self._failure(call_id, str(error))
        except ToolSchemaError:
            LOGGER.error(
                "[manager.py][ToolManager.execute] 工具 Schema 无法执行，"
                "call_id=%r，tool=%r",
                call_id,
                call.name,
            )
            return self._failure(call_id, "工具定义不合法，无法执行。")

        context = permission_context or ToolPermissionContext()
        decision = evaluate_tool_permission(
            call,
            definition,
            permission_mode=permission_mode,
            context=context,
            confirmation=confirmation,
        )
        decision = self._consume_confirmation(decision, confirmation)
        if decision.status != "allowed":
            request_id = (
                decision.confirmation_request.request_id
                if decision.confirmation_request is not None
                else None
            )
            LOGGER.info(
                "[manager.py][ToolManager.execute] 工具权限未放行，"
                "call_id=%r，tool=%r，mode=%s，reason=%s，confirmation_id=%r",
                call_id,
                call.name,
                permission_mode,
                decision.reason,
                request_id,
            )
            return self._failure(call_id, decision.message)

        LOGGER.info(
            "[manager.py][ToolManager.execute] 开始执行工具，call_id=%r，"
            "tool=%r，timeout=%.3f",
            call_id,
            call.name,
            self.timeout_seconds,
        )
        try:
            content = await asyncio.wait_for(
                definition.handler(arguments),
                timeout=self.timeout_seconds,
            )
        except (TimeoutError, asyncio.TimeoutError):
            LOGGER.warning(
                "[manager.py][ToolManager.execute] 工具执行超时，call_id=%r，tool=%r",
                call_id,
                call.name,
            )
            return self._failure(call_id, "工具执行超时。")
        except ToolHandlerError as error:
            LOGGER.warning(
                "[manager.py][ToolManager.execute] 工具受控失败，"
                "call_id=%r，tool=%r，reason=%s",
                call_id,
                call.name,
                error.public_message,
            )
            return self._failure(call_id, f"工具执行失败：{error.public_message}")
        except Exception as error:
            LOGGER.error(
                "[manager.py][ToolManager.execute] 工具执行异常，"
                "call_id=%r，tool=%r，exception=%s",
                call_id,
                call.name,
                type(error).__name__,
            )
            return self._failure(call_id, "工具执行失败。")

        if type(content) is not str:
            LOGGER.error(
                "[manager.py][ToolManager.execute] 工具返回类型错误，"
                "call_id=%r，tool=%r，result_type=%s",
                call_id,
                call.name,
                type(content).__name__,
            )
            return self._failure(call_id, "工具返回了不支持的结果类型。")
        output, truncated = self._truncate_output(content)
        result = ToolResult(tool_call_id=call_id, content=output, is_error=False)
        result.validate()
        LOGGER.info(
            "[manager.py][ToolManager.execute] 工具执行完成，call_id=%r，"
            "tool=%r，output_chars=%d，truncated=%s",
            call_id,
            call.name,
            len(content),
            truncated,
        )
        return result
