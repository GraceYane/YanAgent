"""运行时控制与调度层——当前有意保留为空实现。"""

from yanagent.contracts import RunRequest, RunResult


class AgentBridge:
    """将用户、会话和 Agent 路由到相互隔离的运行时实例。"""

    async def dispatch(self, request: RunRequest) -> RunResult:
        raise NotImplementedError("请实现会话与 Agent 路由，以及运行时生命周期管理")

    async def cancel(self, request_id: str) -> bool:
        raise NotImplementedError("请实现协作式任务取消机制")
