"""P03-04 工具权限模式、作用域和确认流程测试。"""

from __future__ import annotations

import unittest
from typing import Any

from yanagent.contracts import ToolCall
from yanagent.tools import (
    ToolConfirmationResult,
    ToolDefinition,
    ToolManager,
    ToolPermissionContext,
    build_confirmation_request,
    evaluate_tool_permission,
)


def _call(
    *,
    call_id: str = "call-permission-1",
    name: str = "guarded",
    arguments: dict[str, Any] | None = None,
) -> ToolCall:
    """构造权限测试使用的合法工具调用。"""
    return ToolCall(id=call_id, name=name, arguments=arguments or {})


def _definition(
    handler,
    *,
    name: str = "guarded",
    risk_level: str = "low",
    scope: str = "global",
    requires_confirmation: bool = False,
) -> ToolDefinition:
    """构造可调整风险、范围和确认标记的无参数测试工具。"""
    return ToolDefinition(
        name=name,
        description="验证权限边界的测试工具",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=handler,
        risk_level=risk_level,
        parallel_safe=True,
        scope=scope,
        requires_confirmation=requires_confirmation,
    )


class ToolPermissionContextTests(unittest.TestCase):
    """验证作用域必须绑定明确身份，不能仅靠字符串扩大工具权限。"""

    def test_scope_identity_requirements_are_enforced(self) -> None:
        """user、agent、session 和 workspace 缺少身份字段时均拒绝构造。"""
        invalid_contexts = (
            {"allowed_scopes": {"user"}},
            {"allowed_scopes": {"agent"}, "user_id": "user-1"},
            {
                "allowed_scopes": {"session"},
                "user_id": "user-1",
                "agent_id": "agent-1",
            },
            {"allowed_scopes": {"workspace"}},
        )
        for values in invalid_contexts:
            with self.subTest(values=values), self.assertRaises(ValueError):
                ToolPermissionContext(**values)

    def test_complete_context_normalizes_scopes_and_identifiers(self) -> None:
        """完整可信上下文可同时授权全局、会话和工作区工具。"""
        context = ToolPermissionContext(
            allowed_scopes={"global", "session", "workspace"},
            run_id=" run-1 ",
            user_id=" user-1 ",
            agent_id=" agent-1 ",
            session_id=" session-1 ",
            workspace=" C:/workspace ",
            confirmation_ui_available=True,
        )
        self.assertEqual(
            context.allowed_scopes, frozenset({"global", "session", "workspace"})
        )
        self.assertEqual(context.run_id, "run-1")
        self.assertEqual(context.workspace, "C:/workspace")


class ToolPermissionDecisionTests(unittest.TestCase):
    """验证三种模式、风险标记和确认请求的精确决策。"""

    def setUp(self) -> None:
        """为纯权限决策准备不会真正执行的异步 handler。"""
        async def handler(_arguments: dict[str, Any]) -> str:
            """纯决策测试不会调用该 handler。"""
            return "ok"

        self.handler = handler

    def test_modes_have_distinct_fail_closed_semantics(self) -> None:
        """deny 全拒绝、ask 无 UI 默认拒绝、allow 自动放行低风险工具。"""
        call = _call()
        definition = _definition(self.handler)
        context = ToolPermissionContext()
        statuses = {
            mode: evaluate_tool_permission(
                call,
                definition,
                permission_mode=mode,
                context=context,
            )
            for mode in ("deny", "ask", "allow")
        }
        self.assertEqual(statuses["deny"].reason, "mode_denied")
        self.assertEqual(statuses["ask"].reason, "confirmation_unavailable")
        self.assertEqual(statuses["allow"].status, "allowed")

    def test_allow_still_requires_confirmation_for_risky_or_marked_tools(self) -> None:
        """allow 不绕过中高风险和 requires_confirmation 安全标记。"""
        call = _call()
        context = ToolPermissionContext()
        definitions = (
            _definition(self.handler, risk_level="medium"),
            _definition(self.handler, risk_level="high"),
            _definition(self.handler, requires_confirmation=True),
        )
        for definition in definitions:
            with self.subTest(definition=definition):
                decision = evaluate_tool_permission(
                    call,
                    definition,
                    permission_mode="allow",
                    context=context,
                )
                self.assertEqual(decision.reason, "confirmation_unavailable")

    def test_scope_must_be_explicitly_available(self) -> None:
        """低风险 allow 也不能越过上下文未授权的 session 范围。"""
        decision = evaluate_tool_permission(
            _call(),
            _definition(self.handler, scope="session"),
            permission_mode="allow",
            context=ToolPermissionContext(),
        )
        self.assertEqual(decision.reason, "scope_denied")

    def test_confirmation_request_is_stable_and_binds_arguments(self) -> None:
        """同一调用得到稳定 ID，参数变化后确认 ID 必须随之变化。"""
        definition = _definition(self.handler)
        context = ToolPermissionContext(
            run_id="run-1", confirmation_ui_available=True
        )
        first = build_confirmation_request(
            _call(arguments={"value": 1}), definition, context
        )
        repeated = build_confirmation_request(
            _call(arguments={"value": 1}), definition, context
        )
        changed = build_confirmation_request(
            _call(arguments={"value": 2}), definition, context
        )
        self.assertEqual(first.request_id, repeated.request_id)
        self.assertNotEqual(first.request_id, changed.request_id)
        self.assertEqual(first.tool_call_id, "call-permission-1")

    def test_ask_returns_structured_request_then_accepts_exact_result(self) -> None:
        """ask 在 UI 可用时先返回请求，仅匹配 ID 的批准结果可放行。"""
        call = _call()
        definition = _definition(self.handler)
        context = ToolPermissionContext(
            run_id="run-1", confirmation_ui_available=True
        )
        pending = evaluate_tool_permission(
            call,
            definition,
            permission_mode="ask",
            context=context,
        )
        assert pending.confirmation_request is not None
        approved = evaluate_tool_permission(
            call,
            definition,
            permission_mode="ask",
            context=context,
            confirmation=ToolConfirmationResult(
                pending.confirmation_request.request_id, "approved"
            ),
        )
        rejected = evaluate_tool_permission(
            call,
            definition,
            permission_mode="ask",
            context=context,
            confirmation=ToolConfirmationResult(
                pending.confirmation_request.request_id, "rejected"
            ),
        )
        self.assertEqual(pending.status, "confirmation_required")
        self.assertEqual(approved.reason, "confirmation_approved")
        self.assertEqual(rejected.reason, "confirmation_rejected")

    def test_mismatched_confirmation_cannot_authorize_another_call(self) -> None:
        """其他 run 或调用生成的批准 ID 不能挪用到当前工具调用。"""
        call = _call()
        definition = _definition(self.handler)
        context = ToolPermissionContext(
            run_id="run-current", confirmation_ui_available=True
        )
        other_request = build_confirmation_request(
            call,
            definition,
            ToolPermissionContext(run_id="run-other", confirmation_ui_available=True),
        )
        decision = evaluate_tool_permission(
            call,
            definition,
            permission_mode="ask",
            context=context,
            confirmation=ToolConfirmationResult(other_request.request_id, "approved"),
        )
        self.assertEqual(decision.reason, "confirmation_mismatch")


class ToolPermissionExecutionTests(unittest.IsolatedAsyncioTestCase):
    """验证权限拒绝发生在 handler 前，批准结果只能消费一次。"""

    async def test_denied_and_unavailable_confirmation_never_reach_handler(self) -> None:
        """deny、无 UI 的 ask 和需确认的 allow 都在副作用前失败。"""
        executions = 0

        async def handler(_arguments: dict[str, Any]) -> str:
            """记录是否错误越过权限闸门。"""
            nonlocal executions
            executions += 1
            return "unsafe"

        manager = ToolManager()
        manager.register(_definition(handler, requires_confirmation=True))
        for mode in ("deny", "ask", "allow"):
            result = await manager.execute(_call(), permission_mode=mode)
            self.assertTrue(result.is_error)
        self.assertEqual(executions, 0)

    async def test_matching_approval_executes_once_and_replay_is_denied(self) -> None:
        """匹配批准只执行一次，同一确认结果重放不会产生第二次副作用。"""
        executions = 0

        async def handler(_arguments: dict[str, Any]) -> str:
            """累计真实执行次数以验证确认结果一次性消费。"""
            nonlocal executions
            executions += 1
            return "executed"

        manager = ToolManager()
        definition = _definition(handler)
        manager.register(definition)
        call = _call()
        context = ToolPermissionContext(
            run_id="run-approval", confirmation_ui_available=True
        )
        request = build_confirmation_request(call, definition, context)
        confirmation = ToolConfirmationResult(request.request_id, "approved")
        first = await manager.execute(
            call,
            permission_mode="ask",
            permission_context=context,
            confirmation=confirmation,
        )
        replay = await manager.execute(
            call,
            permission_mode="ask",
            permission_context=context,
            confirmation=confirmation,
        )
        self.assertFalse(first.is_error)
        self.assertTrue(replay.is_error)
        self.assertIn("不能重复", replay.content)
        self.assertEqual(executions, 1)

    async def test_authorized_session_scope_executes_with_complete_identity(self) -> None:
        """完整归属上下文显式允许 session 范围后，低风险工具才能执行。"""
        async def handler(_arguments: dict[str, Any]) -> str:
            """返回成功标记证明作用域检查已通过。"""
            return "session-ok"

        manager = ToolManager()
        manager.register(_definition(handler, scope="session"))
        context = ToolPermissionContext(
            allowed_scopes={"session"},
            user_id="user-1",
            agent_id="agent-1",
            session_id="session-1",
        )
        result = await manager.execute(
            _call(), permission_mode="allow", permission_context=context
        )
        self.assertFalse(result.is_error)
        self.assertEqual(result.content, "session-ok")
