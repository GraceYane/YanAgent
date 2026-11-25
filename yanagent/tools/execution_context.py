"""把可信调用身份传到异步工具，不允许模型参数决定工作区或用户身份。"""

from contextvars import ContextVar

from .permissions import ToolPermissionContext
from .manager import ToolHandlerError


execution_context: ContextVar[ToolPermissionContext | None] = ContextVar(
    'yanagent_tool_context', default=None,
)


def current_context() -> ToolPermissionContext:
    """取得本次已授权的身份快照；无工作区绑定时失败关闭。"""
    context = execution_context.get()
    if context is None or not context.workspace or not all((
        context.user_id, context.agent_id, context.session_id, context.run_id,
    )):
        raise ToolHandlerError('缺少可信工作区运行上下文，本次工具未执行。')
    return context
