"""The central Agent loop -- deliberately not implemented.

Target algorithm: load context -> call model -> execute requested tools ->
append results -> call model again -> repeat until a final answer or limit.
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
        """Run one Agent task until it produces a final answer.

        TODO: load and trim context; append the user message; call the model;
        validate and execute tool calls; append tool results; repeat with
        cancellation, timeout and turn limits; persist the final answer.
        """
        raise NotImplementedError("Implement YanAgent's model/tool execution loop")
