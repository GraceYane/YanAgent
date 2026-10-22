"""使用本地忽略配置验证 P01 普通与流式真实模型调用，不输出 API Key。"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

from yanagent.config import AppConfig, ConfigStore
from yanagent.contracts import Message, ModelReply
from yanagent.errors import AgentError, ModelResponseError, UnexpectedToolCallError
from yanagent.models import OpenAICompatibleProvider


LOGGER = logging.getLogger("yanagent.verification")
NON_STREAM_PROMPT = "这是 YanAgent P01 验收。请只回复：普通调用通过"
STREAM_PROMPT = "这是 YanAgent P01 验收。请只回复：流式调用通过"


@dataclass(frozen=True)
class CallEvidence:
    """保存一次真实调用的非敏感验收证据。"""

    mode: str
    content: str
    elapsed_seconds: float
    chunk_count: int
    usage: dict[str, object]


def _safe_content(content: str, *, maximum: int = 300) -> str:
    """压平并限制模型正文，只用于终端人工确认，不处理或展示凭据。"""
    flattened = " ".join(content.split())
    return flattened if len(flattened) <= maximum else flattened[:maximum] + "…"


async def _verify_non_stream(
    provider: OpenAICompatibleProvider,
) -> CallEvidence:
    """执行一次真实非流式调用并检查文本、工具和完成结果。"""
    started = time.perf_counter()
    reply = await provider.complete([Message(role="user", content=NON_STREAM_PROMPT)])
    if reply.tool_calls:
        raise UnexpectedToolCallError()
    if not reply.content.strip():
        raise ModelResponseError()
    return CallEvidence(
        mode="非流式",
        content=reply.content,
        elapsed_seconds=time.perf_counter() - started,
        chunk_count=1,
        usage=dict(reply.usage),
    )


async def _verify_stream(
    provider: OpenAICompatibleProvider,
) -> CallEvidence:
    """执行一次真实 SSE 调用，确认增量能重组为唯一完整响应。"""
    started = time.perf_counter()
    chunks: list[str] = []
    completed: ModelReply | None = None
    async for event in provider.stream([Message(role="user", content=STREAM_PROMPT)]):
        if event.kind == "text_delta":
            chunks.append(event.content)
        elif event.kind == "completed":
            if completed is not None or event.reply is None:
                raise ModelResponseError()
            completed = event.reply
    if completed is None or completed.content != "".join(chunks):
        raise ModelResponseError()
    if completed.tool_calls:
        raise UnexpectedToolCallError()
    return CallEvidence(
        mode="流式",
        content=completed.content,
        elapsed_seconds=time.perf_counter() - started,
        chunk_count=len(chunks),
        usage=dict(completed.usage),
    )


def _print_header(config: AppConfig) -> None:
    """打印可提交的配置摘要，只包含供应商、主机、模型和超时。"""
    host = urlsplit(config.api_base).hostname or "<无效主机>"
    print("P01 真实 API 验证")
    print(f"- Provider：{config.model_provider}")
    print(f"- API 主机：{host}")
    print(f"- 模型：{config.model}")
    print(f"- 超时：{config.request_timeout:g} 秒")
    print("- API Key：已配置（始终不输出内容）")


def _print_evidence(evidence: CallEvidence) -> None:
    """输出一条调用的人工可读证据，不输出请求头或配置原文。"""
    print(f"\n[{evidence.mode}] 通过")
    print(f"- 耗时：{evidence.elapsed_seconds:.3f} 秒")
    print(f"- 文本增量数：{evidence.chunk_count}")
    print(f"- 回答：{_safe_content(evidence.content)}")
    print(f"- Usage：{evidence.usage}")


async def verify() -> tuple[CallEvidence, CallEvidence]:
    """加载本地配置，依次完成普通与流式真实模型验收。"""
    config = ConfigStore().load()
    config.require_model_ready()
    _print_header(config)
    provider = OpenAICompatibleProvider(config)
    LOGGER.info(
        "[verify_p01_real_api.py][verify] 开始真实模型验收，provider=%s，model=%s",
        config.model_provider,
        config.model,
    )
    non_stream = await _verify_non_stream(provider)
    _print_evidence(non_stream)
    stream = await _verify_stream(provider)
    _print_evidence(stream)
    LOGGER.info(
        "[verify_p01_real_api.py][verify] 真实模型验收完成，普通字符数=%d，流式字符数=%d",
        len(non_stream.content),
        len(stream.content),
    )
    return non_stream, stream


def main() -> int:
    """运行验收并把安全统一错误转换成非零退出码。"""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        asyncio.run(verify())
    except AgentError as error:
        print(f"\nP01 真实 API 验证失败：{error.code} - {error.message}")
        return 1
    except Exception:
        # 未分类异常可能携带第三方对象；不打印 repr 或 traceback，避免意外暴露凭据。
        print("\nP01 真实 API 验证失败：unexpected_error - 请查看不含凭据的本地调试日志。")
        return 2
    print("\nP01 真实 API 普通与流式调用均通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
