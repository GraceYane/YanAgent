"""P01-05 内部流式事件：隔离供应商增量、运行队列与桌面 SSE。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from yanagent.contracts import ModelReply


ModelStreamKind = Literal["text_delta", "tool_call_delta", "completed"]
ClientEventType = Literal["delta", "done", "cancelled", "error"]


@dataclass(frozen=True)
class ModelStreamEvent:
    """Provider 产生的模型增量；完成事件携带统一 ``ModelReply``。"""

    kind: ModelStreamKind
    content: str = ""
    tool_index: int | None = None
    tool_call_id: str = ""
    tool_name: str = ""
    arguments_delta: str = ""
    reply: ModelReply | None = None

    def __post_init__(self) -> None:
        """拒绝含糊事件，避免上层靠猜测区分文本、工具和最终结果。"""
        if self.kind == "text_delta":
            valid = bool(self.content) and self.tool_index is None and self.reply is None
        elif self.kind == "tool_call_delta":
            valid = (
                type(self.tool_index) is int
                and self.tool_index >= 0
                and self.reply is None
                and bool(self.tool_call_id or self.tool_name or self.arguments_delta)
            )
        else:
            valid = self.reply is not None and self.tool_index is None
        if not valid:
            raise ValueError("模型流事件字段与事件类型不匹配")


@dataclass(frozen=True)
class RunEvent:
    """一次运行写入线程安全队列的事件，可直接转换为桌面 SSE 数据。"""

    sequence: int
    request_id: str
    type: ClientEventType
    data: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """验证序号、运行标识和正文类型，防止不同运行事件互相污染。"""
        if type(self.sequence) is not int or self.sequence < 0:
            raise ValueError("运行事件序号必须是非负整数")
        if type(self.request_id) is not str or not self.request_id:
            raise ValueError("运行事件必须包含 request_id")
        if self.type not in {"delta", "done", "cancelled", "error"}:
            raise ValueError("运行事件类型不受支持")
        if type(self.data) is not dict or "type" in self.data:
            raise ValueError("运行事件 data 必须是且只能是附加字段对象")

    def to_dict(self) -> dict[str, Any]:
        """生成桌面端现有 ``StreamEvent`` 能直接消费的 JSON 对象。"""
        return {"type": self.type, **self.data}

    @property
    def terminal(self) -> bool:
        """说明该事件之后不会再产生同一运行的新事件。"""
        return self.type in {"done", "error"}
