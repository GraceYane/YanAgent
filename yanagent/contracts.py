"""统一的消息、模型响应和任务数据契约。

内部始终使用结构化工具参数和独立的 tool 角色。不同供应商的 JSON 字符串参数、
tool_use / tool_result 等格式，后续由 Provider 适配器转换。
构造、反序列化和序列化时均执行校验；此处不负责认证、工具执行或数据库访问。
"""

from __future__ import annotations

import json
import math
from abc import ABC, abstractmethod
from collections.abc import Sequence
from copy import deepcopy
from dataclasses import MISSING, asdict, dataclass, field, fields
from typing import Any, Literal, TypeVar


Role = Literal["system", "user", "assistant", "tool"]
RunStatus = Literal["completed", "failed", "cancelled", "interrupted"]
Usage = dict[str, int | None]
ContractT = TypeVar("ContractT", bound="JsonContract")


class ContractValidationError(ValueError):
    """数据不满足内部契约；错误描述不回显消息正文、参数或元数据。"""


def _text(value: Any, label: str, *, nonempty: bool = False) -> None:
    """检查字符串；身份字段和工具标识必须包含非空白字符。"""
    if not isinstance(value, str) or (nonempty and not value.strip()):
        requirement = "非空字符串" if nonempty else "字符串"
        raise ContractValidationError(f"{label} 必须是{requirement}")


def _optional_text(value: Any, label: str) -> None:
    if value is not None:
        _text(value, label, nonempty=True)


def _json_value(value: Any, label: str, active: set[int] | None = None) -> None:
    """只接受无环、字符串键、有限数值的 JSON 数据，避免隐式转换造成信息丢失。"""
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float:
        if math.isfinite(value):
            return
        raise ContractValidationError(f"{label} 不允许包含 NaN 或 Infinity")
    if type(value) not in (dict, list):
        raise ContractValidationError(f"{label} 只能包含标准 JSON 类型")
    active = set() if active is None else active
    identity = id(value)
    if identity in active:
        raise ContractValidationError(f"{label} 不允许包含循环引用")
    active.add(identity)
    try:
        if isinstance(value, dict):
            if any(type(key) is not str for key in value):
                raise ContractValidationError(f"{label} 的对象键必须是字符串")
            children = value.values()
        else:
            children = value
        for child in children:
            _json_value(child, label, active)
    finally:
        active.remove(identity)


def _json_object(value: Any, label: str) -> None:
    if type(value) is not dict:
        raise ContractValidationError(f"{label} 必须是 JSON 对象")
    _json_value(value, label)


def _usage(value: Any) -> None:
    """用量缺失可用空字典或 None 表示；零仅表示明确报告的零用量。"""
    _json_object(value, "usage")
    for count in value.values():
        if count is not None and (type(count) is not int or count < 0):
            raise ContractValidationError("usage 的值必须是非负整数或 None")


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """拒绝重复 JSON 键，防止同一字段在解析时被悄悄覆盖。"""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ContractValidationError("JSON 对象不允许包含重复键")
        result[key] = value
    return result


def _invalid_json_constant(_value: str) -> None:
    raise ContractValidationError("JSON 不允许包含 NaN 或 Infinity")


class JsonContract(ABC):
    """为所有数据契约提供统一的严格 JSON 转换入口。"""

    __slots__ = ()

    def __post_init__(self) -> None:
        self.validate()

    @abstractmethod
    def validate(self) -> None:
        """验证当前对象；字段修改后可以显式重新检查。"""

    def to_dict(self) -> dict[str, Any]:
        """返回独立的 JSON 字典，后续修改不会影响原对象。"""
        self.validate()
        return asdict(self)

    def to_json(self) -> str:
        """输出保留中文的严格 JSON，不允许非有限浮点数。"""
        return json.dumps(self.to_dict(), ensure_ascii=False, allow_nan=False)

    @classmethod
    def _decode_fields(cls, data: dict[str, Any]) -> dict[str, Any]:
        """子类在此还原嵌套契约，普通字段已完成深拷贝。"""
        return data

    @classmethod
    def from_dict(cls: type[ContractT], data: dict[str, Any]) -> ContractT:
        """从字典恢复对象；拒绝未知字段及缺失的必填字段。"""
        _json_object(data, cls.__name__)
        definitions = fields(cls)
        names = {definition.name for definition in definitions}
        if set(data) - names:
            raise ContractValidationError(f"{cls.__name__} 包含未知字段")
        required = [
            definition.name
            for definition in definitions
            if definition.default is MISSING
            and definition.default_factory is MISSING
            and definition.name not in data
        ]
        if required:
            raise ContractValidationError(
                f"{cls.__name__} 缺少必填字段：{', '.join(required)}"
            )
        return cls(**cls._decode_fields(deepcopy(data)))

    @classmethod
    def from_json(cls: type[ContractT], data: str) -> ContractT:
        """从 JSON 文本恢复；不自动接受列表、重复键或非法数值。"""
        _text(data, "JSON 文本")
        try:
            decoded = json.loads(
                data,
                object_pairs_hook=_unique_json_object,
                parse_constant=_invalid_json_constant,
            )
        except json.JSONDecodeError:
            raise ContractValidationError("JSON 文本格式不合法") from None
        return cls.from_dict(decoded)


@dataclass(slots=True)
class ToolCall(JsonContract):
    """模型发起的一次工具调用；参数保持对象形式，尚未执行。"""

    id: str  # 本次调用的唯一标识，供后续工具结果引用。
    name: str  # 注册的工具名称，由 ToolManager 在执行时检查是否存在。
    arguments: dict[str, Any]  # 已解析的 JSON 参数；Schema 校验由工具层负责。

    def validate(self) -> None:
        _text(self.id, "ToolCall.id", nonempty=True)
        _text(self.name, "ToolCall.name", nonempty=True)
        _json_object(self.arguments, "ToolCall.arguments")


def _tool_calls(value: Any) -> None:
    """验证调用列表内的对象和唯一标识；列表顺序保留模型的原始意图。"""
    if type(value) is not list:
        raise ContractValidationError("tool_calls 必须是 ToolCall 列表")
    seen: set[str] = set()
    for call in value:
        if not isinstance(call, ToolCall):
            raise ContractValidationError("tool_calls 中的元素必须是 ToolCall")
        call.validate()
        if call.id in seen:
            raise ContractValidationError("同一调用列表不允许出现重复的工具调用 ID")
        seen.add(call.id)


def _decode_tool_calls(data: dict[str, Any]) -> dict[str, Any]:
    if "tool_calls" in data:
        if type(data["tool_calls"]) is not list:
            raise ContractValidationError("tool_calls 必须是列表")
        data["tool_calls"] = [ToolCall.from_dict(item) for item in data["tool_calls"]]
    return data


@dataclass(slots=True)
class Message(JsonContract):
    """一条完整对话消息；流式增量后续使用独立事件表示。"""

    role: Role  # system=系统指令；user=用户输入；assistant=模型输出；tool=工具结果。
    content: str  # 当前阶段保存文本；纯工具调用的 Assistant 可使用空字符串。
    name: str | None = None  # 可选的发言者或工具名称，不参与身份认证。
    tool_call_id: str | None = None  # 仅 tool 消息使用，对应 Assistant 发起的调用 ID。
    metadata: dict[str, Any] = field(default_factory=dict)  # 来源等 JSON 扩展信息。
    tool_calls: list[ToolCall] = field(default_factory=list)  # 仅 Assistant 可携带。
    is_error: bool = False  # 仅 tool 消息标记工具失败，防止保存历史时丢失错误语义。

    def validate(self) -> None:
        if not isinstance(self.role, str) or self.role not in (
            "system", "user", "assistant", "tool"
        ):
            raise ContractValidationError("Message.role 必须是有效的消息角色")
        _text(self.content, "Message.content")
        _optional_text(self.name, "Message.name")
        _optional_text(self.tool_call_id, "Message.tool_call_id")
        _json_object(self.metadata, "Message.metadata")
        _tool_calls(self.tool_calls)
        if type(self.is_error) is not bool:
            raise ContractValidationError("Message.is_error 必须是布尔值")
        if self.role != "assistant" and self.tool_calls:
            raise ContractValidationError("只有 Assistant 消息可以携带 tool_calls")
        if self.role == "tool":
            if self.tool_call_id is None:
                raise ContractValidationError("Tool 消息必须提供 tool_call_id")
        elif self.tool_call_id is not None or self.is_error:
            raise ContractValidationError("只有 Tool 消息可以携带结果引用和错误标记")

    @classmethod
    def _decode_fields(cls, data: dict[str, Any]) -> dict[str, Any]:
        return _decode_tool_calls(data)


@dataclass(slots=True)
class ToolResult(JsonContract):
    """一次工具执行的结构化结果，可转换为历史消息。"""

    tool_call_id: str  # 对应 ToolCall.id，成功和失败都必须关联原调用。
    content: str  # 模型可以阅读的执行结果或错误说明。
    is_error: bool = False  # 工具失败时为 True，不用异常文本冒充成功结果。

    def validate(self) -> None:
        _text(self.tool_call_id, "ToolResult.tool_call_id", nonempty=True)
        _text(self.content, "ToolResult.content")
        if type(self.is_error) is not bool:
            raise ContractValidationError("ToolResult.is_error 必须是布尔值")

    def to_message(self) -> Message:
        """转换为 Tool 消息，保留错误标记及工具调用引用。"""
        self.validate()
        return Message(
            role="tool",
            content=self.content,
            tool_call_id=self.tool_call_id,
            is_error=self.is_error,
        )


@dataclass(slots=True)
class ModelReply(JsonContract):
    """一次模型调用的完整响应；供应商原始字段由适配器统一。"""

    content: str = ""  # 本次模型回复的文本；可能只有工具请求而没有文本。
    tool_calls: list[ToolCall] = field(default_factory=list)  # 模型要求执行的工具。
    finish_reason: str | None = None  # 结束原因；未知时为 None，供应商适配层负责转换。
    usage: Usage = field(default_factory=dict)  # 非负 Token 计数；缺失为 {} 或 None 值。

    def validate(self) -> None:
        _text(self.content, "ModelReply.content")
        _tool_calls(self.tool_calls)
        _optional_text(self.finish_reason, "ModelReply.finish_reason")
        _usage(self.usage)

    @classmethod
    def _decode_fields(cls, data: dict[str, Any]) -> dict[str, Any]:
        return _decode_tool_calls(data)

    def to_message(self) -> Message:
        """转换为 Assistant 消息，完整保留后续 Tool Result 所引用的调用。"""
        self.validate()
        return Message(
            role="assistant", content=self.content, tool_calls=deepcopy(self.tool_calls)
        )


def _run_identity(value: RunRequest | RunResult) -> None:
    _text(value.user_id, "user_id", nonempty=True)
    _text(value.agent_id, "agent_id", nonempty=True)
    _text(value.session_id, "session_id", nonempty=True)
    _optional_text(value.request_id, "request_id")


@dataclass(slots=True)
class RunRequest(JsonContract):
    """发起一次任务的输入；身份字段是路由信息，不代表已获得授权。"""

    session_id: str  # 一段持续对话的标识；同一会话可包含多个 Run。
    user_message: str  # 本次用户输入，纯空白输入无效。
    agent_id: str = "default"  # 执行任务的 Agent，预留多 Agent 路由。
    metadata: dict[str, Any] = field(default_factory=dict)  # 渠道来源等 JSON 信息。
    user_id: str = "local"  # 本地单用户默认身份；后续由可信入口解析真实用户。
    request_id: str | None = None  # 一次 Run 的标识；None 表示尚未由 Bridge 分配。

    def validate(self) -> None:
        _run_identity(self)
        _text(self.user_message, "RunRequest.user_message", nonempty=True)
        _json_object(self.metadata, "RunRequest.metadata")


@dataclass(slots=True)
class RunResult(JsonContract):
    """一次任务的最终结果；与单次模型响应区分，轮数和用量可跨调用累计。"""

    content: str  # 最终回答或已产生的部分文本；失败或取消时可能为空。
    session_id: str  # 结果所属会话。
    turns: int  # 已进行的模型调用轮数；不包含队列等待次数。
    usage: Usage = field(default_factory=dict)  # 本次任务的累计用量，未知不能当作零。
    user_id: str = "local"  # 与发起请求的可信用户身份对应。
    agent_id: str = "default"  # 实际执行 Agent 的标识。
    request_id: str | None = None  # 与 RunRequest 关联，尚未接入调度时允许为空。
    status: RunStatus = "completed"  # 最终状态，不在此处保存 running 等中间态。

    def validate(self) -> None:
        _run_identity(self)
        _text(self.content, "RunResult.content")
        if type(self.turns) is not int or self.turns < 0:
            raise ContractValidationError("RunResult.turns 必须是非负整数")
        if not isinstance(self.status, str) or self.status not in (
            "completed", "failed", "cancelled", "interrupted"
        ):
            raise ContractValidationError("RunResult.status 必须是有效的最终状态")
        _usage(self.usage)


def validate_conversation(
    messages: Sequence[Message], *, allow_pending_tool_calls: bool = False
) -> None:
    """验证对话中的工具配对，不自动补造结果或删除原消息。

    Assistant 发出的一组调用必须先全部收到 Tool 结果，才能进入下一条普通消息。
    同组结果允许不同顺序；跨整段对话的调用 ID 不可重复。运行中允许尾部待执行调用
    时显式传入 allow_pending_tool_calls=True，完整历史默认不允许遗留调用。
    """
    if not isinstance(messages, (list, tuple)):
        raise ContractValidationError("对话必须是 Message 列表或元组")
    if type(allow_pending_tool_calls) is not bool:
        raise ContractValidationError("allow_pending_tool_calls 必须是布尔值")
    seen: set[str] = set()
    pending: set[str] = set()
    for message in messages:
        if not isinstance(message, Message):
            raise ContractValidationError("对话中的元素必须是 Message")
        message.validate()
        if message.role == "tool":
            if message.tool_call_id not in pending:
                raise ContractValidationError("工具结果没有对应的待完成调用或已重复返回")
            pending.remove(message.tool_call_id)
            continue
        if pending:
            raise ContractValidationError("工具调用尚未全部返回结果，不能追加普通消息")
        for call in message.tool_calls:
            if call.id in seen:
                raise ContractValidationError("对话中不允许出现重复的工具调用 ID")
            seen.add(call.id)
            pending.add(call.id)
    if pending and not allow_pending_tool_calls:
        raise ContractValidationError("对话末尾存在尚未返回结果的工具调用")
