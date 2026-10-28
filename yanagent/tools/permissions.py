"""工具权限基础：作用域限制、确认请求和失败关闭决策。"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from yanagent.contracts import ToolCall


PermissionMode = Literal["deny", "ask", "allow"]
PermissionStatus = Literal["allowed", "denied", "confirmation_required"]
ConfirmationDecision = Literal["approved", "rejected"]
PermissionReason = Literal[
    "invalid_mode",
    "mode_denied",
    "scope_denied",
    "mode_allowed",
    "confirmation_unavailable",
    "confirmation_context_missing",
    "confirmation_required",
    "confirmation_mismatch",
    "confirmation_rejected",
    "confirmation_approved",
    "confirmation_replayed",
    "confirmation_capacity",
]
ToolScopeName = Literal["global", "user", "agent", "session", "workspace"]
TOOL_PERMISSION_MODES = frozenset({"deny", "ask", "allow"})
TOOL_PERMISSION_SCOPES = frozenset(
    {"global", "user", "agent", "session", "workspace"}
)
CONFIRMATION_REQUEST_PREFIX = "confirm_"
PERMISSION_STATUSES = frozenset({"allowed", "denied", "confirmation_required"})
PERMISSION_REASONS = frozenset(
    {
        "invalid_mode",
        "mode_denied",
        "scope_denied",
        "mode_allowed",
        "confirmation_unavailable",
        "confirmation_context_missing",
        "confirmation_required",
        "confirmation_mismatch",
        "confirmation_rejected",
        "confirmation_approved",
        "confirmation_replayed",
        "confirmation_capacity",
    }
)


class ToolSecurityMetadata(Protocol):
    """描述权限判断所需的最小工具安全元数据，避免权限模块依赖注册表实现。"""

    name: str
    risk_level: str
    scope: str
    requires_confirmation: bool


def _normalize_optional_identifier(value: Any, *, label: str, limit: int) -> str | None:
    """校验可信运行时传入的可选身份字段，拒绝空值和控制字符。"""
    if value is None:
        return None
    if type(value) is not str or not value.strip() or len(value) > limit:
        raise ValueError(f"{label} 必须是 1～{limit} 个字符的字符串或 None")
    normalized = value.strip()
    if any(ord(character) < 32 or ord(character) == 127 for character in normalized):
        raise ValueError(f"{label} 不允许包含控制字符")
    return normalized


@dataclass(frozen=True, slots=True)
class ToolPermissionContext:
    """保存由可信运行时提供的身份、可用作用域和确认界面状态。"""

    allowed_scopes: frozenset[ToolScopeName] = frozenset({"global"})
    run_id: str | None = None
    user_id: str | None = None
    agent_id: str | None = None
    session_id: str | None = None
    workspace: str | None = None
    confirmation_ui_available: bool = False

    def __post_init__(self) -> None:
        """规范化上下文并保证每个已授权作用域都有对应身份边界。"""
        try:
            scopes = frozenset(self.allowed_scopes)
        except TypeError:
            raise ValueError("allowed_scopes 必须是可迭代的工具作用域集合") from None
        if any(type(scope) is not str or scope not in TOOL_PERMISSION_SCOPES for scope in scopes):
            raise ValueError("allowed_scopes 包含不支持的工具作用域")
        if type(self.confirmation_ui_available) is not bool:
            raise ValueError("confirmation_ui_available 必须是布尔值")

        run_id = _normalize_optional_identifier(self.run_id, label="run_id", limit=256)
        user_id = _normalize_optional_identifier(self.user_id, label="user_id", limit=256)
        agent_id = _normalize_optional_identifier(self.agent_id, label="agent_id", limit=256)
        session_id = _normalize_optional_identifier(
            self.session_id, label="session_id", limit=256
        )
        workspace = _normalize_optional_identifier(
            self.workspace, label="workspace", limit=4096
        )
        if "user" in scopes and user_id is None:
            raise ValueError("user 作用域必须绑定 user_id")
        if "agent" in scopes and (user_id is None or agent_id is None):
            raise ValueError("agent 作用域必须绑定 user_id 和 agent_id")
        if "session" in scopes and (
            user_id is None or agent_id is None or session_id is None
        ):
            raise ValueError("session 作用域必须绑定 user_id、agent_id 和 session_id")
        if "workspace" in scopes and workspace is None:
            raise ValueError("workspace 作用域必须绑定 workspace")

        object.__setattr__(self, "allowed_scopes", scopes)
        object.__setattr__(self, "run_id", run_id)
        object.__setattr__(self, "user_id", user_id)
        object.__setattr__(self, "agent_id", agent_id)
        object.__setattr__(self, "session_id", session_id)
        object.__setattr__(self, "workspace", workspace)


@dataclass(frozen=True, slots=True)
class ToolConfirmationRequest:
    """描述一次与运行、工具调用和参数绑定的用户确认请求。"""

    request_id: str
    run_id: str
    tool_call_id: str
    tool_name: str
    risk_level: str
    scope: str

    def __post_init__(self) -> None:
        """拒绝外部伪造的空确认字段，并校验请求 ID 的固定形状。"""
        if (
            type(self.request_id) is not str
            or not self.request_id.startswith(CONFIRMATION_REQUEST_PREFIX)
            or len(self.request_id) != len(CONFIRMATION_REQUEST_PREFIX) + 32
            or any(character not in "0123456789abcdef" for character in self.request_id[8:])
        ):
            raise ValueError("确认请求 ID 格式不合法")
        for label, value in (
            ("run_id", self.run_id),
            ("tool_call_id", self.tool_call_id),
            ("tool_name", self.tool_name),
            ("risk_level", self.risk_level),
            ("scope", self.scope),
        ):
            if type(value) is not str or not value:
                raise ValueError(f"确认请求的 {label} 必须是非空字符串")


@dataclass(frozen=True, slots=True)
class ToolConfirmationResult:
    """表示可信确认界面对某个确认请求作出的批准或拒绝结果。"""

    request_id: str
    decision: ConfirmationDecision

    def __post_init__(self) -> None:
        """校验确认结果，避免布尔值或任意字符串造成含糊授权。"""
        if (
            type(self.request_id) is not str
            or not self.request_id.startswith(CONFIRMATION_REQUEST_PREFIX)
            or len(self.request_id) != len(CONFIRMATION_REQUEST_PREFIX) + 32
            or any(character not in "0123456789abcdef" for character in self.request_id[8:])
        ):
            raise ValueError("确认结果的请求 ID 格式不合法")
        if type(self.decision) is not str or self.decision not in {"approved", "rejected"}:
            raise ValueError("确认结果必须是 approved 或 rejected")


@dataclass(frozen=True, slots=True)
class ToolPermissionDecision:
    """返回可执行、已拒绝或待确认三种互斥权限结论。"""

    status: PermissionStatus
    reason: PermissionReason
    confirmation_request: ToolConfirmationRequest | None = None

    def __post_init__(self) -> None:
        """保证只有待确认结论携带确认请求，避免调用方误读状态。"""
        if type(self.status) is not str or self.status not in PERMISSION_STATUSES:
            raise ValueError("工具权限结论状态不合法")
        if type(self.reason) is not str or self.reason not in PERMISSION_REASONS:
            raise ValueError("工具权限结论原因不合法")
        if self.status == "confirmation_required":
            if self.confirmation_request is None or self.reason != "confirmation_required":
                raise ValueError("待确认结论必须携带确认请求")
        elif self.confirmation_request is not None:
            raise ValueError("非待确认结论不能携带确认请求")

    @property
    def message(self) -> str:
        """返回可安全写入 ToolResult 的固定中文说明。"""
        messages = {
            "invalid_mode": "工具权限模式不合法。",
            "mode_denied": "当前权限模式禁止执行工具。",
            "scope_denied": "工具作用范围未获授权。",
            "mode_allowed": "工具已按当前权限模式放行。",
            "confirmation_unavailable": "工具需要确认，但当前未接入确认界面，已默认拒绝。",
            "confirmation_context_missing": "工具需要确认，但运行上下文不完整，已默认拒绝。",
            "confirmation_mismatch": "确认结果与本次工具调用不匹配，已拒绝执行。",
            "confirmation_rejected": "工具执行已被用户拒绝。",
            "confirmation_approved": "工具执行已获用户批准。",
            "confirmation_replayed": "确认结果已使用，不能重复执行工具。",
            "confirmation_capacity": "确认记录容量已满，已默认拒绝执行。",
        }
        if self.reason == "confirmation_required":
            assert self.confirmation_request is not None
            return f"工具执行需要用户确认，确认请求 ID：{self.confirmation_request.request_id}。"
        return messages[self.reason]


def _confirmation_fingerprint(
    call: ToolCall,
    definition: ToolSecurityMetadata,
    context: ToolPermissionContext,
) -> str:
    """生成包含身份和参数的规范指纹，防止确认结果被挪用到其他调用。"""
    canonical = json.dumps(
        {
            "run_id": context.run_id,
            "user_id": context.user_id,
            "agent_id": context.agent_id,
            "session_id": context.session_id,
            "workspace": context.workspace,
            "tool_call_id": call.id,
            "tool_name": call.name,
            "arguments": call.arguments,
            "risk_level": definition.risk_level,
            "scope": definition.scope,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


def build_confirmation_request(
    call: ToolCall,
    definition: ToolSecurityMetadata,
    context: ToolPermissionContext,
) -> ToolConfirmationRequest:
    """为已校验调用构造稳定确认请求，相同上下文和参数得到相同 ID。"""
    if context.run_id is None:
        raise ValueError("缺少 run_id，无法构造确认请求")
    if call.name != definition.name:
        raise ValueError("工具调用名称与确认目标不一致")
    request_id = CONFIRMATION_REQUEST_PREFIX + _confirmation_fingerprint(
        call, definition, context
    )
    return ToolConfirmationRequest(
        request_id=request_id,
        run_id=context.run_id,
        tool_call_id=call.id,
        tool_name=call.name,
        risk_level=definition.risk_level,
        scope=definition.scope,
    )


def evaluate_tool_permission(
    call: ToolCall,
    definition: ToolSecurityMetadata,
    *,
    permission_mode: str,
    context: ToolPermissionContext,
    confirmation: ToolConfirmationResult | None = None,
) -> ToolPermissionDecision:
    """按模式、作用域、风险和确认结果计算一次无副作用权限结论。"""
    if type(permission_mode) is not str or permission_mode not in TOOL_PERMISSION_MODES:
        return ToolPermissionDecision("denied", "invalid_mode")
    if permission_mode == "deny":
        return ToolPermissionDecision("denied", "mode_denied")
    if definition.scope not in context.allowed_scopes:
        return ToolPermissionDecision("denied", "scope_denied")

    requires_confirmation = (
        permission_mode == "ask"
        or definition.requires_confirmation
        or definition.risk_level in {"medium", "high"}
    )
    if not requires_confirmation:
        return ToolPermissionDecision("allowed", "mode_allowed")
    if not context.confirmation_ui_available:
        return ToolPermissionDecision("denied", "confirmation_unavailable")
    if context.run_id is None:
        return ToolPermissionDecision("denied", "confirmation_context_missing")

    request = build_confirmation_request(call, definition, context)
    if confirmation is None:
        return ToolPermissionDecision(
            "confirmation_required",
            "confirmation_required",
            confirmation_request=request,
        )
    if confirmation.request_id != request.request_id:
        return ToolPermissionDecision("denied", "confirmation_mismatch")
    if confirmation.decision == "rejected":
        return ToolPermissionDecision("denied", "confirmation_rejected")
    return ToolPermissionDecision("allowed", "confirmation_approved")
