"""使用本地忽略配置验证 P04 真实模型工具闭环，始终不输出 API Key。"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

from yanagent.config import ConfigStore
from yanagent.context import PromptContextBuilder, RuntimeIdentity
from yanagent.contracts import Message, ToolCall, ToolResult
from yanagent.errors import AgentError, ModelResponseError
from yanagent.models import OpenAICompatibleProvider
from yanagent.runtime.agent_loop import AgentLoop
from yanagent.tools import ToolManager, ToolPermissionContext, register_safe_example_tools


LOGGER = logging.getLogger("yanagent.verification")
PROMPT = (
    "请调用 current_time 工具读取运行 YanAgent 的本机当前时间，"
    "然后用中文说明日期、时间、星期和 UTC 偏移。不要猜测时间。"
)


@dataclass(frozen=True, slots=True)
class ToolCallEvidence:
    """保存真实工具闭环的非敏感证据，供终端和阶段文档人工核对。"""

    content: str
    elapsed_seconds: float
    turns: int
    tool_names: tuple[str, ...]
    usage: dict[str, int | None]


def _safe_content(content: str, *, maximum: int = 300) -> str:
    """压平并截断模型最终正文，避免验收终端输出无界增长。"""
    flattened = " ".join(content.split())
    return flattened if len(flattened) <= maximum else flattened[:maximum] + "…"


async def verify() -> ToolCallEvidence:
    """执行真实模型选择工具、本地执行、结果回写和最终回答的完整闭环。"""
    config = ConfigStore().load()
    config.require_model_ready()
    manager = ToolManager()
    register_safe_example_tools(manager)
    identity = RuntimeIdentity(
        user_id="local",
        agent_id="default",
        session_id="p04-real-tool-verification",
        request_id="p04-real-tool-verification",
    )
    context = PromptContextBuilder().build(
        identity=identity,
        history=[],
        current=Message(role="user", content=PROMPT),
        tools=manager.schemas(),
    )
    started_calls: list[ToolCall] = []
    ended_calls: list[tuple[ToolCall, ToolResult]] = []

    def on_tool_start(call: ToolCall, _turn: int, _index: int, _total: int) -> None:
        """记录真实模型选择的完整工具调用，不打印参数或凭据。"""
        started_calls.append(call)

    def on_tool_end(
        call: ToolCall,
        result: ToolResult,
        _turn: int,
        _index: int,
        _total: int,
        _execution_time: float,
    ) -> None:
        """记录本地工具终态，供闭环完成后检查调用配对和成功状态。"""
        ended_calls.append((call, result))

    started_at = time.perf_counter()
    result = await AgentLoop(
        model=OpenAICompatibleProvider(config),
        tools=manager,
        sessions=None,
        on_tool_start=on_tool_start,
        on_tool_end=on_tool_end,
    ).run(
        messages=context.messages,
        tool_schemas=context.tools,
        session_id=identity.session_id,
        request_id=identity.request_id,
        permission_mode="allow",
        permission_context=ToolPermissionContext(
            allowed_scopes=frozenset({"global"}),
            run_id=identity.request_id,
            user_id=identity.user_id,
            agent_id=identity.agent_id,
            session_id=identity.session_id,
            confirmation_ui_available=False,
        ),
    )
    if not result.reply.content.strip():
        raise ModelResponseError()
    if not started_calls or not any(call.name == "current_time" for call in started_calls):
        raise ModelResponseError()
    if len(started_calls) != len(ended_calls):
        raise ModelResponseError()
    if any(call.id != ended.id or tool_result.is_error for call, (ended, tool_result) in zip(
        started_calls, ended_calls, strict=True,
    )):
        raise ModelResponseError()
    evidence = ToolCallEvidence(
        content=result.reply.content,
        elapsed_seconds=time.perf_counter() - started_at,
        turns=result.turns,
        tool_names=tuple(call.name for call in started_calls),
        usage=dict(result.usage),
    )
    host = urlsplit(config.api_base).hostname or "<无效主机>"
    print("P04 真实模型工具闭环验证")
    print(f"- Provider：{config.model_provider}")
    print(f"- API 主机：{host}")
    print(f"- 模型：{config.model}")
    print("- API Key：已配置（始终不输出内容）")
    print(f"- 模型轮数：{evidence.turns}")
    print(f"- 本地执行工具：{', '.join(evidence.tool_names)}")
    print(f"- 耗时：{evidence.elapsed_seconds:.3f} 秒")
    print(f"- 最终回答：{_safe_content(evidence.content)}")
    print(f"- Usage：{evidence.usage}")
    LOGGER.info(
        "[verify_p04_real_tool.py][verify] 真实工具闭环完成，模型轮数=%d，工具数=%d",
        evidence.turns,
        len(evidence.tool_names),
    )
    return evidence


def main() -> int:
    """运行验收并把安全统一错误转换为不含敏感详情的非零退出码。"""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        asyncio.run(verify())
    except AgentError as error:
        print(f"P04 真实模型工具闭环失败：{error.code} - {error.message}")
        return 1
    except Exception:
        print("P04 真实模型工具闭环失败：unexpected_error，请检查本地安全日志。")
        return 2
    print("P04 真实模型工具闭环通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
