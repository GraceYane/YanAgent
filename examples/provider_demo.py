"""P01-03 演示：默认离线 Fake；显式 --live 才调用用户配置的模型。"""

from __future__ import annotations

import argparse
import asyncio
import json

from yanagent.config import ConfigStore
from yanagent.contracts import Message, ModelReply, ToolCall, ToolResult
from yanagent.errors import AgentError
from yanagent.models import FakeProvider, OpenAICompatibleProvider


async def run_demo(*, live: bool, prompt: str) -> None:
    """执行一次真实非流式调用，或演示两轮可控 Fake 响应与输入记录。"""
    if live:
        provider = OpenAICompatibleProvider(ConfigStore().load())
        reply = await provider.complete([Message(role="user", content=prompt)])
        print("模型真实响应：")
        print(reply.to_json())
        return

    fake = FakeProvider([
        ModelReply(tool_calls=[ToolCall("call_demo", "calculator", {"expression": "1 + 2"})],
                   finish_reason="tool_calls"),
        ModelReply(content="计算结果是 3", finish_reason="stop",
                   usage={"input_tokens": 20, "output_tokens": 5, "total_tokens": 25}),
    ])
    messages = [Message(role="user", content="计算 1 + 2")]
    tools = [{"name": "calculator", "description": "计算数学表达式", "parameters": {
        "type": "object", "properties": {"expression": {"type": "string"}},
        "required": ["expression"],
    }}]
    first = await fake.complete(messages, tools=tools)
    print("第一轮预设响应（工具请求，尚未执行）：")
    print(first.to_json())
    # 本阶段没有 ToolManager/AgentLoop；此处手工插入固定结果，不冒充工具执行。
    messages.extend([first.to_message(), ToolResult("call_demo", "3").to_message()])
    final = await fake.complete(messages, tools=tools)
    print("手工追加固定工具结果后，第二轮预设响应：")
    print(final.to_json())
    print("第二轮收到的角色顺序：", [item.role for item in fake.calls[1].messages])
    assert len(fake.calls) == 2 and fake.remaining == 0
    assert fake.calls[1].messages[2].tool_call_id == "call_demo"
    print("验收通过：预设顺序、工具引用和每轮输入记录正确。")
    print("默认演示没有访问网络、执行工具或运行 AgentLoop；用量也是预设值。")


def main() -> None:
    """解析演示模式并输出安全错误；真实调用失败时使用非零退出码。"""
    parser = argparse.ArgumentParser(description="YanAgent 非流式 Provider 验收")
    parser.add_argument("--live", action="store_true", help="调用已配置的真实模型，可能产生费用")
    parser.add_argument("--prompt", default="你好，请用一句话介绍你自己。", help="真实调用的输入文本")
    args = parser.parse_args()
    try:
        asyncio.run(run_demo(live=args.live, prompt=args.prompt))
    except AgentError as error:
        print(json.dumps(error.to_dict(), ensure_ascii=False))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
