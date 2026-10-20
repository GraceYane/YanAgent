"""Agent 的核心执行循环——当前有意保留为空实现。

目标流程：加载上下文 -> 调用模型 -> 执行模型请求的工具 ->
追加工具结果 -> 再次调用模型 -> 重复执行，直到得到最终回答或触发限制。
"""

from __future__ import annotations

from dataclasses import dataclass

from yanagent.contracts import RunRequest, RunResult


@dataclass(slots=True)
class LoopLimits:
    max_turns: int = 12
    max_consecutive_tool_errors: int = 3
    timeout_seconds: float = 300.0


class AgentLoop:
    def __init__(self, *, model: object, tools: object, sessions: object, limits: LoopLimits | None = None):
        self.model = model
        self.tools = tools
        self.sessions = sessions
        self.limits = limits or LoopLimits()

    async def run(self, request: RunRequest) -> RunResult:
        """运行一次 Agent 任务，直到生成最终回答。

        待实现：加载并裁剪上下文；追加用户消息；调用模型；校验并执行
        工具调用；追加工具结果；在支持取消、超时和轮数限制的前提下
        重复执行；最后持久化最终回答。
        """
        raise NotImplementedError("请实现 YanAgent 的模型与工具执行循环")
