"""Chat Completions 兼容适配：内部消息 ↔ HTTP JSON ↔ ModelReply。"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Sequence
from typing import Any

from yanagent.config import AppConfig
from yanagent.contracts import (
    ContractValidationError, Message, ModelReply, ToolCall, validate_conversation,
)
from yanagent.errors import (
    EmptyModelResponseError, InvalidRequestError, ModelRefusalError, ModelResponseError,
)
from .provider import NonStreamingProvider
from .transport import JsonTransport, UrllibJsonTransport, strict_json_loads


def _copy_json(value: Any) -> Any:
    """复制标准 JSON 值，拒绝隐式字符串化的对象键和非有限数字。"""
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    if type(value) is list:
        return [_copy_json(item) for item in value]
    if type(value) is dict and all(type(key) is str for key in value):
        return {key: _copy_json(item) for key, item in value.items()}
    raise InvalidRequestError()


def prepare_request(
    messages: Sequence[Message], tools: Sequence[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """校验完整上下文并转换工具描述；不修改原消息，不发送内部元数据。"""
    try:
        validate_conversation(messages)
        if not messages or not isinstance(tools, (list, tuple)):
            raise InvalidRequestError()
        converted = []
        for message in messages:
            item: dict[str, Any] = {"role": message.role, "content": message.content}
            if message.name is not None and message.role != "tool":
                item["name"] = message.name
            if message.tool_calls:
                item["content"] = message.content or None
                item["tool_calls"] = [{
                    "id": call.id, "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(call.arguments, ensure_ascii=False, allow_nan=False),
                    },
                } for call in message.tool_calls]
            if message.role == "tool":
                item["tool_call_id"] = message.tool_call_id
                if message.is_error:
                    # 兼容协议没有 is_error 字段，通过结果正文保留失败语义。
                    item["content"] = json.dumps(
                        {"is_error": True, "content": message.content}, ensure_ascii=False,
                    )
            converted.append(item)
        schemas = []
        names: set[str] = set()
        for tool in tools:
            if type(tool) is not dict or set(tool) - {"name", "description", "parameters"}:
                raise InvalidRequestError()
            name = tool.get("name")
            description = tool.get("description", "")
            parameters = tool.get("parameters")
            if (
                type(name) is not str or re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name) is None
                or name in names or type(description) is not str
                or type(parameters) is not dict or parameters.get("type") != "object"
            ):
                raise InvalidRequestError()
            names.add(name)
            schemas.append({"type": "function", "function": {
                "name": name, "description": description, "parameters": _copy_json(parameters),
            }})
        # 提前检查可编码性，避免发送时才暴露 Unicode 错误或内部对象。
        json.dumps([converted, schemas], ensure_ascii=False, allow_nan=False).encode("utf-8")
        return converted, schemas
    except (ContractValidationError, ValueError, TypeError, RecursionError):
        raise InvalidRequestError() from None


def parse_reply(data: dict[str, Any]) -> ModelReply:
    """解析单候选响应，严格还原工具参数；缺失用量保持未知，不按零计算。"""
    try:
        if type(data) is not dict or data.get("error") is not None:
            raise ModelResponseError()
        choices = data.get("choices")
        if choices == []:
            raise EmptyModelResponseError()
        if type(choices) is not list or len(choices) != 1 or type(choices[0]) is not dict:
            raise ModelResponseError()
        choice = choices[0]
        message = choice.get("message")
        if type(message) is not dict or message.get("role") != "assistant":
            raise ModelResponseError()
        if message.get("function_call") is not None:
            raise ModelResponseError()  # 本阶段仅支持 tool_calls，不静默丢弃旧版调用。
        content = message.get("content")
        if content is None:
            content = ""
        if type(content) is not str:
            raise ModelResponseError()
        finish_reason = choice.get("finish_reason")
        if message.get("refusal") or finish_reason == "content_filter":
            raise ModelRefusalError()
        calls = message.get("tool_calls")
        calls = [] if calls is None else calls
        if type(calls) is not list:
            raise ModelResponseError()
        parsed_calls = []
        for call in calls:
            if type(call) is not dict or call.get("type") != "function":
                raise ModelResponseError()
            function = call.get("function")
            if type(function) is not dict or type(function.get("arguments")) is not str:
                raise ModelResponseError()
            arguments = strict_json_loads(function["arguments"])
            parsed_calls.append(ToolCall(id=call.get("id"), name=function.get("name"), arguments=arguments))
        if finish_reason == "tool_calls" and not parsed_calls:
            raise ModelResponseError()
        usage = data.get("usage")
        usage = {} if usage is None else usage
        if type(usage) is not dict:
            raise ModelResponseError()
        normalized_usage = {
            target: usage[source]
            for source, target in (
                ("prompt_tokens", "input_tokens"), ("completion_tokens", "output_tokens"),
                ("total_tokens", "total_tokens"),
            ) if source in usage
        }
        reply = ModelReply(
            content=content, tool_calls=parsed_calls,
            finish_reason=finish_reason, usage=normalized_usage,
        )
        reply.to_json().encode("utf-8")
        if not content.strip() and not parsed_calls:
            raise EmptyModelResponseError()
        return reply
    except (ContractValidationError, ValueError, TypeError, RecursionError):
        raise ModelResponseError() from None


class OpenAICompatibleProvider(NonStreamingProvider):
    """使用 P01-02 配置完成一轮非流式请求；不执行工具、不重试、不管理历史。"""

    name = "openai-compatible"

    def __init__(self, config: AppConfig, *, transport: JsonTransport | None = None) -> None:
        """保留配置快照；可注入离线传输，默认使用标准库 HTTP 实现。"""
        self._config = config
        self._transport = transport if transport is not None else UrllibJsonTransport()

    async def complete(
        self, messages: Sequence[Message], *, tools: Sequence[dict[str, Any]] = (),
    ) -> ModelReply:
        """检查配置和输入，发送一次 POST，并将结果转换为 ModelReply。"""
        self._config.require_model_ready()
        converted, schemas = prepare_request(messages, tools)
        payload: dict[str, Any] = {
            "model": self._config.model, "messages": converted, "stream": False,
        }
        if schemas:
            payload["tools"] = schemas
        data = await self._transport.post_json(
            url=self._config.api_base.rstrip("/") + "/chat/completions",
            headers={"Authorization": f"Bearer {self._config.api_key}",
                     "Content-Type": "application/json", "Accept": "application/json"},
            payload=payload, timeout=self._config.request_timeout,
        )
        return parse_reply(data)
