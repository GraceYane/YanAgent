"""P01-03 请求、响应、传输和 Fake Provider 的离线行为测试。"""

from __future__ import annotations

import asyncio
import io
import json
import threading
import traceback
import unittest
from copy import deepcopy
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

from yanagent.config import AppConfig
from yanagent.contracts import Message, ModelReply, ToolCall, ToolResult
from yanagent.errors import (
    AuthenticationError, ConfigurationError, EmptyModelResponseError, InvalidRequestError,
    ModelConnectionError, ModelRefusalError, ModelResponseError, ModelServerError,
    ModelTimeoutError, RateLimitError,
)
from yanagent.models import FakeProvider, FakeProviderExhaustedError, OpenAICompatibleProvider
from yanagent.models.openai_compatible import parse_reply, prepare_request
from yanagent.models.transport import UrllibJsonTransport


def response(content="你好", *, calls=None, reason="stop", usage=None) -> dict:
    """生成最小兼容响应，允许测试覆盖空内容、工具调用及用量差异。"""
    return {"choices": [{"message": {"role": "assistant", "content": content,
                                     "tool_calls": calls}, "finish_reason": reason}], "usage": usage}


def wire_call(call_id="c1", arguments='{"x": 1}') -> dict:
    """生成供应商格式的函数调用，参数保持 JSON 字符串。"""
    return {"id": call_id, "type": "function", "function": {"name": "calculator", "arguments": arguments}}


def schema() -> dict:
    """提供本阶段统一的工具描述，不涉及真实工具执行。"""
    return {"name": "calculator", "description": "计算", "parameters": {
        "type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"],
    }}


def config(**updates) -> AppConfig:
    """返回只含虚构密钥的测试配置，不读取本机环境或配置文件。"""
    values = {"api_base": "https://example.com/v1/", "model": "demo", "api_key": "fake-secret"}
    values.update(updates)
    return AppConfig(**values)


class RecordingTransport:
    """记录实际请求并返回预设 JSON 的离线传输替身。"""

    def __init__(self, data: dict) -> None:
        """保存预设原始响应和空请求记录。"""
        self.data = data
        self.requests: list[dict] = []

    async def post_json(self, **kwargs) -> dict:
        """拷贝请求参数供断言，并返回独立响应。"""
        self.requests.append(deepcopy(kwargs))
        return deepcopy(self.data)


class CodecTests(unittest.TestCase):
    """验证供应商格式与内部契约转换，包括不完整或损坏的响应。"""

    def test_four_message_conversion_and_error_result(self) -> None:
        """四消息顺序和工具引用保持一致，失败标记进入结果正文而非非法字段。"""
        messages = [Message(role="system", content="规则"), Message(role="user", content="计算"),
                    Message(role="assistant", content="", metadata={"private": "hidden"},
                            tool_calls=[ToolCall("c1", "calculator", {"x": 1})]),
                    ToolResult("c1", "失败原因", True).to_message()]
        original = deepcopy(messages)
        converted, schemas = prepare_request(messages, [schema()])
        self.assertEqual(messages, original)
        self.assertEqual(converted[2]["tool_calls"][0], wire_call())
        self.assertIsNone(converted[2]["content"])
        self.assertEqual(converted[3]["tool_call_id"], "c1")
        self.assertEqual(json.loads(converted[3]["content"]), {"is_error": True, "content": "失败原因"})
        self.assertNotIn("is_error", converted[3])
        self.assertNotIn("metadata", converted[2])
        self.assertEqual(schemas[0]["function"], schema())

    def test_bad_conversation_rejected_before_sending(self) -> None:
        """缺少调用、缺少结果、无消息或非法对象都不能进入模型请求。"""
        for messages in ([], [ToolResult("orphan", "3").to_message()],
                         [Message(role="assistant", content="", tool_calls=[ToolCall("c", "calc", {})])],
                         ["not-message"]):
            with self.subTest(messages=messages), self.assertRaises(InvalidRequestError):
                prepare_request(messages, [])

    def test_invalid_schemas_rejected_and_copies_isolated(self) -> None:
        """工具重名、非法类型和非 JSON 参数被拒绝；转换结果不共享输入字典。"""
        valid = schema()
        _, converted = prepare_request([Message(role="user", content="a")], [valid])
        converted[0]["function"]["parameters"]["required"].append("extra")
        self.assertEqual(valid["parameters"]["required"], ["x"])
        bad = [None, [valid, valid], [{"name": "bad name", "parameters": {"type": "object"}}],
               [{"name": "x", "parameters": {"type": "array"}}],
               [{"name": "x", "parameters": {"type": "object", "bad": (1, 2)}}],
               [{"name": "x", "parameters": {"type": "object", 3: "bad"}}],
               [{"name": "x", "parameters": {"type": "object", "bad": float("nan")}}]]
        for tools in bad:
            with self.subTest(tools=tools), self.assertRaises(InvalidRequestError):
                prepare_request([Message(role="user", content="a")], tools)

    def test_text_finish_reason_and_usage_mapping(self) -> None:
        """文本和结束原因原样保留，仅映射已报告的用量，不推算总数。"""
        reply = parse_reply(response("部分内容", reason="length", usage={
            "prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15,
            "prompt_tokens_details": {"cached_tokens": 2},
        }))
        self.assertEqual((reply.content, reply.finish_reason), ("部分内容", "length"))
        self.assertEqual(reply.usage, {"input_tokens": 12, "output_tokens": 3, "total_tokens": 15})
        self.assertEqual(parse_reply(response(usage={"prompt_tokens": 2})).usage, {"input_tokens": 2})

    def test_missing_null_and_zero_usage_are_distinct(self) -> None:
        """缺失用量不伪装成零，供应商明确报告的 None 或零保留。"""
        self.assertEqual(parse_reply(response()).usage, {})
        self.assertEqual(parse_reply(response(usage={"prompt_tokens": None, "completion_tokens": 0})).usage,
                         {"input_tokens": None, "output_tokens": 0})
        for count in (-1, True, 1.5, "2"):
            with self.subTest(count=count), self.assertRaises(ModelResponseError):
                parse_reply(response(usage={"prompt_tokens": count}))

    def test_multiple_tool_calls_and_unknown_reason(self) -> None:
        """无文本的多工具响应有效，调用顺序和参数对象保持一致。"""
        reply = parse_reply(response(None, calls=[wire_call(), wire_call("c2", '{"x": 2}')], reason="tool_calls"))
        self.assertEqual(reply.content, "")
        self.assertEqual([call.id for call in reply.tool_calls], ["c1", "c2"])
        self.assertEqual(reply.tool_calls[1].arguments, {"x": 2})
        self.assertEqual(parse_reply(response(reason="vendor_reason")).finish_reason, "vendor_reason")
        self.assertIsNone(parse_reply(response(reason=None)).finish_reason)

    def test_invalid_tool_arguments_never_become_empty_object(self) -> None:
        """损坏 JSON、重复键、非对象和非标准数值不能被修补为空参数。"""
        for raw in ("{", "", "[]", "null", '"text"', '{"x":1,"x":2}', '{"x":NaN}', '{"x":1e999}'):
            with self.subTest(raw=raw), self.assertRaises(ModelResponseError):
                parse_reply(response(None, calls=[wire_call(arguments=raw)], reason="tool_calls"))

    def test_bad_tool_identifiers_and_shapes_are_rejected(self) -> None:
        """缺失 ID、工具重号及非函数调用都会拒绝，不自动生成新 ID。"""
        bad_calls = [[wire_call(None)], [wire_call(), wire_call()], [{"type": "custom"}],
                     [{"id": "c1", "type": "function", "function": {"name": "x", "arguments": {}}}]]
        for calls in bad_calls:
            with self.subTest(calls=calls), self.assertRaises(ModelResponseError):
                parse_reply(response(None, calls=calls, reason="tool_calls"))

    def test_empty_and_refusal_have_distinct_errors(self) -> None:
        """空回复与显式拒绝分开报告，工具调用不被误判为空。"""
        for data in ({"choices": []}, response(None), response("  ")):
            with self.assertRaises(EmptyModelResponseError):
                parse_reply(data)
        data = response(None)
        data["choices"][0]["message"]["refusal"] = "隐藏的拒绝正文"
        for item in (data, response(None, reason="content_filter")):
            with self.assertRaises(ModelRefusalError):
                parse_reply(item)

    def test_bad_response_shape_and_error_envelope_are_safe(self) -> None:
        """错误包络、多候选、旧工具格式及非文本内容都不会冒充正常回复。"""
        old = response("a")
        old["choices"][0]["message"]["function_call"] = {"name": "old"}
        for data in ({}, [], {"error": {"message": "secret-body"}},
                     {"choices": [response()["choices"][0]] * 2}, response([{"text": "a"}]),
                     response(None, calls=[], reason="tool_calls"), old):
            with self.subTest(data=data), self.assertRaises(ModelResponseError) as caught:
                parse_reply(data)
            self.assertNotIn("secret-body", str(caught.exception))


class ProviderAsyncTests(unittest.IsolatedAsyncioTestCase):
    """在真实异步事件循环中验证 Provider 请求和可控 Fake 序列。"""

    async def test_request_url_auth_payload_and_timeout(self) -> None:
        """Base 只追加一次路径，认证放请求头，超时来自配置且工具为空时省略。"""
        transport = RecordingTransport(response())
        provider = OpenAICompatibleProvider(config(request_timeout=12), transport=transport)
        reply = await provider.complete([Message(role="user", content="你好")])
        request = transport.requests[0]
        self.assertEqual(reply.content, "你好")
        self.assertEqual(request["url"], "https://example.com/v1/chat/completions")
        self.assertEqual(request["headers"]["Authorization"], "Bearer fake-secret")
        self.assertEqual(request["timeout"], 12)
        self.assertEqual(request["payload"], {"model": "demo", "stream": False,
                                             "messages": [{"role": "user", "content": "你好"}]})
        self.assertNotIn("fake-secret", repr(provider))

    async def test_configuration_and_input_fail_before_transport(self) -> None:
        """缺少密钥或输入不合法时不发出任何请求。"""
        transport = RecordingTransport(response())
        with self.assertRaises(ConfigurationError):
            await OpenAICompatibleProvider(config(api_key=""), transport=transport).complete([Message("user", "hi")])
        with self.assertRaises(InvalidRequestError):
            await OpenAICompatibleProvider(config(), transport=transport).complete([])
        self.assertEqual(transport.requests, [])

    async def test_tools_are_sent_and_reply_does_not_execute_them(self) -> None:
        """真实适配器传递工具 Schema 并只返回调用意图，不代替工具执行器。"""
        transport = RecordingTransport(response(None, calls=[wire_call()], reason="tool_calls"))
        provider = OpenAICompatibleProvider(config(), transport=transport)
        reply = await provider.complete([Message("user", "计算")], tools=[schema()])
        self.assertEqual(transport.requests[0]["payload"]["tools"][0]["function"], schema())
        self.assertEqual(reply.tool_calls, [ToolCall("c1", "calculator", {"x": 1})])
        self.assertEqual(len(transport.requests), 1)

    async def test_fake_sequence_error_and_exhaustion(self) -> None:
        """预设错误占一轮，之后继续到下一条响应，耗尽明确失败。"""
        fake = FakeProvider([ModelReply(content="one"), RateLimitError(), ModelReply(content="three")])
        messages = [Message("user", "hi")]
        self.assertEqual((await fake.complete(messages)).content, "one")
        with self.assertRaises(RateLimitError):
            await fake.complete(messages)
        self.assertEqual((await fake.complete(messages)).content, "three")
        self.assertEqual(fake.remaining, 0)
        with self.assertRaises(FakeProviderExhaustedError):
            await fake.complete(messages)
        self.assertEqual(len(fake.calls), 4)

    async def test_fake_input_and_reply_snapshots_are_independent(self) -> None:
        """预设、返回值和每轮输入分别复制，不随调用方后续修改而改变。"""
        preset = ModelReply(content="original")
        fake = FakeProvider([preset, preset])
        preset.content = "mutated"
        messages, tools = [Message("user", "before")], [schema()]
        first = await fake.complete(messages, tools=tools)
        first.content = "changed"
        messages[0].content = "after"
        tools[0]["description"] = "changed"
        calls = fake.calls
        self.assertEqual(calls[0].messages[0].content, "before")
        self.assertEqual(calls[0].tools[0]["description"], "计算")
        calls[0].messages[0].content = "external"
        self.assertEqual(fake.calls[0].messages[0].content, "before")
        self.assertEqual((await fake.complete(messages)).content, "original")

    async def test_fake_tool_round_trip_and_invalid_input_not_consumed(self) -> None:
        """两次模型调用之间显式追加工具结果，Fake 不代替 AgentLoop 执行工具。"""
        fake = FakeProvider([ModelReply(tool_calls=[ToolCall("c1", "calculator", {"x": 1})]),
                             ModelReply(content="结果为 1")])
        with self.assertRaises(InvalidRequestError):
            await fake.complete([])
        self.assertEqual(fake.remaining, 2)
        messages = [Message("user", "计算")]
        first = await fake.complete(messages, tools=[schema()])
        messages.extend([first.to_message(), ToolResult("c1", "1").to_message()])
        self.assertEqual((await fake.complete(messages)).content, "结果为 1")
        self.assertEqual([m.role for m in fake.calls[1].messages], ["user", "assistant", "tool"])

    async def test_stream_is_explicitly_not_implemented(self) -> None:
        """两个实现都明确拒绝流式入口，不能消耗 Fake 的普通响应。"""
        fake = FakeProvider([ModelReply(content="a")])
        for provider in (fake, OpenAICompatibleProvider(config())):
            with self.assertRaises(NotImplementedError):
                await anext(provider.stream([Message("user", "hi")]))
        self.assertEqual(fake.remaining, 1)

    async def test_transport_runs_off_event_loop_thread(self) -> None:
        """实际 to_thread 让阻塞实现在线程池运行，事件循环线程保持独立。"""
        main_thread = threading.get_ident()
        seen = []

        def worker(*args):
            """记录执行线程并返回固定结果，不访问网络。"""
            seen.append(threading.get_ident())
            return response()

        transport = UrllibJsonTransport()
        with patch.object(transport, "_post_sync", side_effect=worker):
            data = await transport.post_json(url="unused", headers={}, payload={}, timeout=1)
        self.assertEqual(data, response())
        self.assertNotEqual(seen, [main_thread])

    async def test_deadline_and_cancellation_are_not_retried(self) -> None:
        """等待超时转换统一错误，外部取消仍是取消且不自动重新调用。"""
        started = asyncio.Event()

        async def stalled(*args):
            """模拟尚未完成的传输等待，避免真实后台线程遗留。"""
            started.set()
            await asyncio.Event().wait()

        transport = UrllibJsonTransport()
        with patch("yanagent.models.transport.asyncio.to_thread", side_effect=stalled) as call:
            with self.assertRaises(ModelTimeoutError):
                await transport.post_json(url="unused", headers={}, payload={}, timeout=0.01)
            self.assertEqual(call.call_count, 1)
            started.clear()
            task = asyncio.create_task(transport.post_json(url="unused", headers={}, payload={}, timeout=5))
            await started.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertEqual(call.call_count, 2)


class TransportTests(unittest.TestCase):
    """使用 HTTP 响应替身验证底层错误映射、读取限制与资源关闭。"""

    def invoke(self, opener, *, max_bytes=1024):
        """注入受控 opener，直接验证同步 I/O 边界而不发出网络请求。"""
        with patch("yanagent.models.transport.build_opener", return_value=opener):
            return UrllibJsonTransport(max_response_bytes=max_bytes)._post_sync(
                "https://example.com/v1/chat/completions", {}, {"model": "demo"}, 4,
            )

    def test_http_errors_close_response_and_hide_raw_body(self) -> None:
        """HTTP 错误体不读取也不泄露，认证等异常通过状态精确映射。"""
        for status, expected in ((401, AuthenticationError), (429, RateLimitError),
                                 (500, ModelServerError), (307, ModelResponseError)):
            body = io.BytesIO(b"secret-body")
            error = HTTPError("https://secret-path", status, "secret-message", {}, body)
            opener = Mock()
            opener.open.side_effect = error
            try:
                self.invoke(opener)
            except expected:
                rendered = traceback.format_exc()
                self.assertNotIn("secret-body", rendered)
                self.assertNotIn("secret-message", rendered)
                self.assertNotIn("secret-path", rendered)
            else:
                self.fail("应返回对应的统一错误")
            self.assertTrue(body.closed)
            self.assertEqual(opener.open.call_count, 1)

    def test_connection_and_timeout_errors(self) -> None:
        """DNS/连接失败与超时区分，底层异常字符串不会透出。"""
        for error, expected in ((URLError("secret"), ModelConnectionError),
                                 (URLError(TimeoutError("secret")), ModelTimeoutError),
                                 (TimeoutError("secret"), ModelTimeoutError),
                                 (OSError("secret"), ModelConnectionError)):
            opener = Mock()
            opener.open.side_effect = error
            with self.assertRaises(expected) as caught:
                self.invoke(opener)
            self.assertNotIn("secret", str(caught.exception))

    def test_response_read_limit_and_strict_json(self) -> None:
        """大响应、坏编码、重复键及非对象 JSON 均拒绝，响应总会关闭。"""
        for raw in (b"x" * 33, b"\xff", b"{", b"[]", b'{"a":1,"a":2}', b'{"a":NaN}'):
            handle = Mock(status=200)
            handle.read.return_value = raw
            context = Mock()
            context.__enter__ = Mock(return_value=handle)
            context.__exit__ = Mock(return_value=False)
            opener = Mock()
            opener.open.return_value = context
            with self.assertRaises(ModelResponseError):
                self.invoke(opener, max_bytes=32)
            handle.read.assert_called_once_with(33)
            context.__exit__.assert_called_once()


if __name__ == "__main__":
    unittest.main()
