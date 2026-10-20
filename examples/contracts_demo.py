r"""四条消息的数据保存与还原演示，不调用模型或执行计算器。

在项目根目录执行：
    .\.venv\Scripts\python.exe -X utf8 -m examples.contracts_demo
"""

from __future__ import annotations

import json

from yanagent.contracts import (
    Message,
    ModelReply,
    RunRequest,
    RunResult,
    ToolCall,
    ToolResult,
    validate_conversation,
)


def main() -> None:
    """使用固定结果检验契约，而非提前模拟业务功能已经完成。"""
    request = RunRequest(
        session_id="session_demo", user_message="计算 1 + 2", request_id="run_demo"
    )
    call = ToolCall(
        id="call_001", name="calculator", arguments={"expression": "1 + 2"}
    )
    # 这里的结果由示例直接给定；计算器和执行循环在 P03、P04 实现。
    tool_result = ToolResult(tool_call_id=call.id, content="3")
    messages = [
        Message(role="user", content=request.user_message),
        ModelReply(tool_calls=[call], finish_reason="tool_calls").to_message(),
        tool_result.to_message(),
        ModelReply(content="计算结果是 3", finish_reason="stop").to_message(),
    ]
    validate_conversation(messages)
    payload = json.dumps([message.to_dict() for message in messages], ensure_ascii=False)
    restored = [Message.from_dict(item) for item in json.loads(payload)]
    validate_conversation(restored)
    if restored != messages:
        raise RuntimeError("消息还原后与原始内容不一致")
    result = RunResult(
        content=restored[-1].content,
        session_id=request.session_id,
        turns=2,
        user_id=request.user_id,
        agent_id=request.agent_id,
        request_id=request.request_id,
    )
    print("固定数据演示：未调用模型、未执行工具。")
    print(json.dumps([message.to_dict() for message in restored], ensure_ascii=False, indent=2))
    print("四条消息往返一致，工具调用与结果正确配对。")
    print("示例任务结果：", result.to_json())


if __name__ == "__main__":
    main()
