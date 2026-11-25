"""P06-02 公开思考字段、协议续接、Token 口径、预算和桌面事件验收。"""

import asyncio
import json
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path

from yanagent.chat import YanAgentApplication
from yanagent.config import AppConfig, ConfigStore
from yanagent.contracts import Message, ModelReply, ToolCall
from yanagent.context import estimate_message_tokens
from yanagent.debug_log import yan_debug
from yanagent.errors import ModelResponseError, ModelOutputLimitError, ModelStreamInterruptedError, ModelServerError, ConfigurationError, InvalidRequestError
from yanagent.events import ModelStreamEvent
from yanagent.models import FakeProvider
from yanagent.models.factory import FallbackProvider
from yanagent.models.native import NativeProvider
from yanagent.models.normalization import normalize_usage, finish_reason, context_limits
from yanagent.models.openai_compatible import OpenAICompatibleProvider, StreamReplyBuilder, parse_reply
from yanagent.runtime import AgentRuntime
from yanagent.sessions import SessionStore, DesktopSessionService
from yanagent.storage import Database


class FixtureTransport:
    """记录发送参数并提供离线 JSON/SSE；从不访问真实供应商。"""

    def __init__(self, data=None, frames=()):
        """保存预设及关闭标志。"""
        self.data, self.frames, self.calls, self.closed = data, frames, [], False

    async def post_json(self, **kwargs):
        """记录完整请求，返回离线对象。"""
        self.calls.append(kwargs)
        return self.data

    async def stream_data(self, **kwargs):
        """发出帧并在流结束或取消时标记关闭。"""
        self.calls.append(kwargs)
        try:
            for frame in self.frames:
                yield frame if type(frame) is str else json.dumps(frame)
        finally:
            self.closed = True


def config(vendor='deepseek', **updates):
    """生成虚构供应商配置，不加载真实密钥或模型。"""
    return AppConfig(**{'model_provider': vendor, 'model': 'fixture', 'api_base': 'https://example.invalid/v1',
                        'api_key': 'fixture-key', 'enable_thinking': True, **updates})


def completion(*, thought='公开字段', reason='stop', content='答案', calls=None, usage=None):
    """构造兼容协议响应，不把思考放在普通正文中。"""
    message = {'role': 'assistant', 'content': content, 'reasoning_content': thought, 'reasoning': '未知字段不得展示'}
    if calls:
        message['tool_calls'] = calls
    return {'choices': [{'message': message, 'finish_reason': reason}], 'usage': usage or {}}


class ResponseNormalizationTests(unittest.IsolatedAsyncioTestCase):
    """覆盖不同协议的完整/流式响应与工具续接。"""

    async def test_usage_subcounts_are_not_double_counted(self):
        """OpenAI 子计数不加总，Claude 缓存加入输入，Gemini 推理加入输出。"""
        usage = normalize_usage({'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15,
            'prompt_tokens_details': {'cached_tokens': 8}, 'completion_tokens_details': {'reasoning_tokens': 3}})
        self.assertEqual(usage, {'input_tokens': 10, 'output_tokens': 5, 'total_tokens': 15,
            'cached_input_tokens': 8, 'reasoning_tokens': 3})
        usage = normalize_usage({'input_tokens': 10, 'output_tokens': 3,
            'cache_read_input_tokens': 5, 'cache_creation_input_tokens': 2}, 'claude')
        self.assertEqual((usage['input_tokens'], usage['total_tokens']), (17, 20))
        usage = normalize_usage({'promptTokenCount': 10, 'candidatesTokenCount': 2,
            'thoughtsTokenCount': 4, 'cachedContentTokenCount': 8, 'totalTokenCount': 16}, 'gemini')
        self.assertEqual((usage['input_tokens'], usage['output_tokens'], usage['total_tokens']), (10, 6, 16))

    async def test_usage_missing_null_zero_and_invalid_values(self):
        """未知保持未知，显式零保留，非法计数不能进入执行记录。"""
        self.assertEqual(normalize_usage({}), {})
        self.assertEqual(normalize_usage({'prompt_tokens': None, 'completion_tokens': 0}), {'input_tokens': None, 'output_tokens': 0})
        for bad in (-1, True, '2', 1.5):
            with self.assertRaises(ModelResponseError):
                normalize_usage({'completion_tokens_details': {'reasoning_tokens': bad}})

    async def test_finish_reasons_reject_unknown_and_truncated_tools(self):
        """统一截断与工具结束；有 JSON 也不能执行被截断的工具参数。"""
        self.assertEqual(finish_reason('model_context_window_exceeded', 'claude', False), 'context_length')
        self.assertEqual(finish_reason('STOP', 'gemini', True), 'tool_calls')
        for vendor, reason in (('claude', 'pause_turn'), ('gemini', 'MALFORMED_FUNCTION_CALL'), ('openai', 'untrusted-reason')):
            with self.assertRaises(ModelResponseError):
                finish_reason(reason, vendor, False)
        with self.assertRaises(ModelResponseError):
            parse_reply(completion(reason='length', calls=[{'id': 'c', 'type': 'function',
                'function': {'name': 'calc', 'arguments': '{}'}}]))

    async def test_compatible_reasoning_gate_and_replay(self):
        """只认明确供应商的 reasoning_content，关闭展示仍保留必要续接状态。"""
        for vendor, enabled, expected in (('deepseek', True, '公开字段'), ('qwen', True, '公开字段'),
                ('openai', True, ''), ('openai-compatible', True, ''), ('deepseek', False, '')):
            transport = FixtureTransport(completion())
            provider = OpenAICompatibleProvider(config(vendor, enable_thinking=enabled), transport=transport)
            reply = await provider.complete([Message('user', 'hi')])
            self.assertEqual(reply.reasoning, expected)
            self.assertEqual(reply.content, '答案')
            if vendor == 'deepseek':
                await provider.complete([Message('user', 'hi'), reply.to_message(), Message('user', '继续')])
                self.assertEqual(transport.calls[-1]['payload']['messages'][1]['reasoning_content'], '公开字段')
                self.assertEqual(transport.calls[-1]['payload']['thinking']['type'], 'enabled' if enabled else 'disabled')

    async def test_qwen_encrypted_state_is_replayed_without_display(self):
        """Qwen 密文仅用于协议回传，不解释或展示。"""
        data = completion()
        data['choices'][0]['message']['encrypted_content'] = 'opaque-ciphertext'
        provider = OpenAICompatibleProvider(config('qwen'), transport=FixtureTransport(data))
        reply = await provider.complete([Message('user', 'hi')])
        payload = provider._payload([Message('user', 'hi'), reply.to_message(), Message('user', '继续')], [], False)
        self.assertEqual(payload['messages'][1]['encrypted_content'], 'opaque-ciphertext')
        self.assertTrue(payload['preserve_thinking'])
        self.assertNotIn('opaque-ciphertext', reply.reasoning)

    async def test_compatible_stream_separates_reasoning_and_usage_tail(self):
        """思考独立增量，末尾累计用量不重复求和，连接正常关闭。"""
        transport = FixtureTransport(frames=[
            {'choices': [{'index': 0, 'delta': {'reasoning_content': '公开摘要'}}]},
            {'choices': [{'index': 0, 'delta': {'content': '好'}, 'finish_reason': 'stop'}]},
            {'choices': [], 'usage': {'prompt_tokens': 3, 'completion_tokens': 5, 'total_tokens': 8,
                                     'completion_tokens_details': {'reasoning_tokens': 4}}}, '[DONE]'])
        provider = OpenAICompatibleProvider(config(), stream_transport=transport)
        events = [e async for e in provider.stream([Message('user', 'hi')])]
        self.assertEqual([e.kind for e in events], ['reasoning_delta', 'text_delta', 'completed'])
        self.assertEqual(events[-1].reply.reasoning, '公开摘要')
        self.assertEqual(events[-1].reply.usage['total_tokens'], 8)
        self.assertTrue(transport.closed)

    async def test_empty_length_is_terminal_and_keeps_known_usage(self):
        """思考耗尽输出上限没有正文时明确报错，不能当作空响应补请求。"""
        with self.assertRaises(ModelOutputLimitError) as failure:
            parse_reply(completion(reason='length', content='', usage={'total_tokens': 8}))
        self.assertEqual(failure.exception.usage['total_tokens'], 8)
        builder = StreamReplyBuilder(reasoning_protocol='deepseek', show_reasoning=True)
        builder.add({'choices': [{'delta': {'reasoning_content': '公开字段'}, 'finish_reason': 'length'}], 'usage': {'total_tokens': 9}})
        with self.assertRaises(ModelOutputLimitError) as failure:
            builder.finish()
        self.assertEqual(failure.exception.usage['total_tokens'], 9)

    async def test_claude_thinking_signature_and_redacted_roundtrip(self):
        """Claude 公开 thinking 可展示，完整签名和 redacted 数据仅原样回传。"""
        blocks = [{'type': 'thinking', 'thinking': '公开摘要', 'signature': 'opaque-signature'},
                  {'type': 'redacted_thinking', 'data': 'opaque-redacted'}]
        data = {'content': [*blocks, {'type': 'tool_use', 'id': 'c', 'name': 'calc', 'input': {}}], 'stop_reason': 'tool_use'}
        provider = NativeProvider(config('claude'), transport=FixtureTransport(data))
        reply = await provider.complete([Message('user', 'hi')])
        self.assertEqual(reply.reasoning, '公开摘要')
        _, _, payload = provider.request([Message('user', 'hi'), reply.to_message(), Message('tool', '2', tool_call_id='c')], [], False)
        self.assertEqual(payload['messages'][1]['content'][:2], blocks)
        self.assertEqual(payload['thinking'], {'type': 'enabled', 'budget_tokens': 1024})
        self.assertNotIn('opaque', reply.reasoning)

    async def test_claude_stream_signature_delta_and_cumulative_usage(self):
        """签名增量不得变成文字；message_delta 的累计 output 只采用最新值。"""
        transport = FixtureTransport(frames=[
            {'type': 'message_start', 'message': {'usage': {'input_tokens': 2, 'cache_read_input_tokens': 5, 'output_tokens': 1}}},
            {'type': 'content_block_start', 'index': 0, 'content_block': {'type': 'thinking', 'thinking': '', 'signature': ''}},
            {'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'thinking_delta', 'thinking': '摘要'}},
            {'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'signature_delta', 'signature': 'opaque'}},
            {'type': 'content_block_delta', 'index': 1, 'delta': {'type': 'text_delta', 'text': '好'}},
            {'type': 'message_delta', 'delta': {'stop_reason': 'end_turn'}, 'usage': {'output_tokens': 3}},
            {'type': 'message_stop'}])
        provider = NativeProvider(config('claude'), stream_transport=transport)
        events = [e async for e in provider.stream([Message('user', 'hi')])]
        self.assertEqual([e.kind for e in events], ['reasoning_delta', 'text_delta', 'completed'])
        self.assertEqual(events[-1].reply.usage['total_tokens'], 10)
        self.assertEqual(events[-1].reply.provider_metadata['claude_thinking'][0]['signature'], 'opaque')

    async def test_claude_interleaved_signed_blocks_keep_original_order(self):
        """正文、思考和工具交错时仍保持签名块原序，不能统一搬到最前面。"""
        parts = [{'type': 'text', 'text': '准备'}, {'type': 'thinking', 'thinking': '摘要', 'signature': 'opaque'},
                 {'type': 'tool_use', 'id': 'c', 'name': 'calc', 'input': {}}]
        provider = NativeProvider(config('claude'), transport=FixtureTransport({'content': parts, 'stop_reason': 'tool_use'}))
        reply = await provider.complete([Message('user', 'hi')])
        _, _, payload = provider.request([Message('user', 'hi'), reply.to_message(), Message('tool', '2', tool_call_id='c')], [], False)
        self.assertEqual(payload['messages'][1]['content'], parts)

    async def test_gemini_signed_parts_and_generated_ids_remain_unchanged(self):
        """缺失原生调用 ID 时仅生成本地 ID，不修改被签名的原始内容。"""
        parts = [{'thought': True, 'text': '公开摘要'}, {'text': '准备计算', 'thoughtSignature': 'text-signature'},
                 {'functionCall': {'name': 'calc', 'args': {}}, 'thoughtSignature': 'call-signature'}]
        provider = NativeProvider(config('gemini'), transport=FixtureTransport({'candidates': [{'content': {'parts': parts}, 'finishReason': 'STOP'}]}))
        reply = await provider.complete([Message('user', 'hi')])
        call = reply.tool_calls[0]
        _, _, payload = provider.request([Message('user', 'hi'), reply.to_message(), Message('tool', '2', tool_call_id=call.id)], [], False)
        self.assertEqual(payload['contents'][1]['parts'], parts)
        self.assertNotIn('id', payload['contents'][2]['parts'][0]['functionResponse'])
        self.assertEqual(reply.reasoning, '公开摘要')
        other = NativeProvider(replace(provider.config, model='another-model'))
        _, _, changed = other.request([Message('user', 'hi'), reply.to_message(), Message('tool', '2', tool_call_id=call.id)], [], False)
        self.assertNotIn('thoughtSignature', json.dumps(changed))

    async def test_gemini_stream_reasoning_usage_and_signature(self):
        """流式公开摘要与正常正文分离，所有原始签名可在后续请求恢复。"""
        transport = FixtureTransport(frames=[
            {'candidates': [{'content': {'parts': [{'thought': True, 'text': '摘要'}]}}]},
            {'candidates': [{'content': {'parts': [{'text': '好', 'thoughtSignature': 'opaque'}]}, 'finishReason': 'STOP'}],
             'usageMetadata': {'promptTokenCount': 4, 'candidatesTokenCount': 2, 'thoughtsTokenCount': 3, 'totalTokenCount': 9}}])
        events = [e async for e in NativeProvider(config('gemini'), stream_transport=transport).stream([Message('user', 'hi')])]
        self.assertEqual([e.kind for e in events], ['reasoning_delta', 'text_delta', 'completed'])
        self.assertEqual(events[-1].reply.usage['output_tokens'], 5)
        self.assertEqual(events[-1].reply.provider_metadata['gemini_parts'][-1]['thoughtSignature'], 'opaque')

    async def test_thinking_protocol_overrides_and_budget_validation(self):
        """新模型可明确声明 adaptive/level；手动预算不满足接口约束时不发送请求。"""
        options = {'claude': {'model_options': {'fixture': {'thinking_protocol': 'claude-adaptive'}}}}
        _, _, payload = NativeProvider(config('claude', provider_configs=options)).request([Message('user', 'hi')], [], False)
        self.assertEqual(payload['thinking']['type'], 'adaptive')
        _, _, payload = NativeProvider(config('gemini')).request([Message('user', 'hi')], [], False)
        self.assertTrue(payload['generationConfig']['thinkingConfig']['includeThoughts'])
        with self.assertRaises(InvalidRequestError):
            NativeProvider(config('claude', max_output_tokens=512)).request([Message('user', 'hi')], [], False)

    async def test_model_limits_catalog_and_fallback_are_consistent(self):
        """目录里的模型窗口和输出上限实际影响会话及备用链预算。"""
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(Path(directory) / 'config.json', environ={})
            app = YanAgentApplication(store, provider_factory=lambda _: FakeProvider([]))
            app.save_model_action({'action': 'save_catalog', 'provider_id': 'deepseek', 'models': [
                {'name': 'small', 'capabilities': ['text'], 'context_window': 8192, 'max_output_tokens': 1024}], 'hidden': []})
            selected = replace(store.load(), model_provider='deepseek', model='small')
            self.assertEqual(context_limits(selected), (8192, 1024))
            primary = replace(store.load(), chat_fallback={'enabled': True, 'chain': [{'provider': 'deepseek', 'model': 'small'}]})
            self.assertEqual(context_limits(primary, include_fallback=True)[0], 8192)
            item = next(p for p in app.models_payload()['providers'] if p['id'] == 'deepseek')
            self.assertEqual(item['catalog'][0]['context_window'], 8192)
            with self.assertRaises(ConfigurationError):
                store.save({'provider_configs': {'deepseek': {'model_options': {'bad': {'context_window': True}}}}})
            app.save_model_action({'action': 'save_catalog', 'provider_id': 'deepseek', 'models': [], 'hidden': []})
            self.assertEqual(context_limits(replace(store.load(), model_provider='deepseek', model='small'))[0], 64_000)

    async def test_auto_window_and_disabled_native_reasoning(self):
        """自动窗口采用明确目录值；关闭公开思考时签名仍保留但不展示。"""
        selected = config('claude', max_context_tokens=0, provider_configs={'claude': {
            'model_options': {'fixture': {'context_window': 128_000}}}})
        self.assertEqual(context_limits(selected)[0], 128_000)
        data = {'content': [{'type': 'thinking', 'thinking': '不可展示', 'signature': 'opaque'},
                            {'type': 'text', 'text': '答案'}], 'stop_reason': 'end_turn'}
        for enabled, protocol in ((False, 'claude-enabled'), (True, 'none')):
            provider = NativeProvider(config('claude', enable_thinking=enabled,
                provider_configs={'claude': {'model_options': {'fixture': {'thinking_protocol': protocol}}}}), transport=FixtureTransport(data))
            reply = await provider.complete([Message('user', 'hi')])
            self.assertEqual(reply.reasoning, '')
            self.assertEqual(reply.provider_metadata['claude_thinking'][0]['signature'], 'opaque')

    async def test_completed_frames_cannot_receive_more_answer_deltas(self):
        """完成原因后只接受用量尾帧，不能追加另一段答案或工具参数。"""
        builder = StreamReplyBuilder()
        builder.add({'choices': [{'delta': {'content': '好'}, 'finish_reason': 'stop'}]})
        with self.assertRaises(ModelResponseError):
            builder.add({'choices': [{'delta': {'content': '多余'}}]})

    async def test_replayed_protocol_state_is_budgeted_and_redacted(self):
        """必要回传内容占用预算，但日志不输出公开思考正文或 opaque 状态。"""
        message = ModelReply(content='答案', reasoning='display-secret', provider_metadata={
            'provider': 'claude', 'model': 'fixture', 'claude_thinking': [{'type': 'thinking', 'thinking': 'protocol-secret', 'signature': 'opaque-secret'}]}).to_message()
        self.assertGreater(estimate_message_tokens(message), estimate_message_tokens(Message('assistant', '答案')))
        with self.assertLogs('yanagent.debug_trace', level='INFO') as logs:
            yan_debug('test_response_normalization.py', 'test_redaction', '检查状态', working=[message])
        for value in ('display-secret', 'protocol-secret', 'opaque-secret'):
            self.assertNotIn(value, '\n'.join(logs.output))

    async def test_reasoning_delta_also_prevents_fallback_replay(self):
        """已经向用户输出公开摘要后，同样不能自动切换模型重复生成。"""
        primary = FakeProvider([], stream_outcomes=[[ModelStreamEvent('reasoning_delta', content='摘要'), ModelServerError()]])
        backup = FakeProvider([], stream_outcomes=[[ModelStreamEvent('completed', reply=ModelReply(content='不应调用'))]])
        chain = FallbackProvider([('a', 'x', primary), ('b', 'y', backup)])
        with self.assertRaises(ModelStreamInterruptedError):
            async for _ in chain.stream([Message('user', 'hi')]):
                pass
        self.assertEqual(backup.calls, [])


class PublicReasoningRuntimeTests(unittest.TestCase):
    """通过真实后台循环和 SQLite 检查桌面事件及重载后的显示。"""

    def test_reasoning_sse_and_history_do_not_expose_protocol_state(self):
        """公开思考独立于答案，截断原因可恢复，签名只留在内部消息。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = ConfigStore(root / 'config.json', environ={})
            store.save({'model_provider': 'gemini', 'model': 'fixture', 'api_base': 'https://example.invalid', 'api_key': 'fixture', 'enable_thinking': True})
            transport = FixtureTransport(frames=[
                {'candidates': [{'content': {'parts': [{'thought': True, 'text': '摘要'}]}}]},
                {'candidates': [{'content': {'parts': [{'text': '部分答案', 'thoughtSignature': 'opaque-secret'}]}, 'finishReason': 'MAX_TOKENS'}]}])
            sessions = SessionStore(Database(data_dir=root / 'data', environ={}), user_id='local', agent_id='default')
            app = YanAgentApplication(store, session_store=sessions,
                provider_factory=lambda snapshot: NativeProvider(snapshot, stream_transport=transport))
            runtime = AgentRuntime(app)
            try:
                runtime.start_stream({'session_id': 's', 'message': 'hi', 'stream': True}, request_id='r')
                events, cursor, deadline = [], 0, time.monotonic() + 5
                while time.monotonic() < deadline:
                    batch, terminal = runtime.wait_events('r', cursor, timeout=0.1)
                    events.extend(event.to_dict() for event in batch)
                    cursor += len(batch)
                    if terminal:
                        break
                self.assertEqual(events[-1]['type'], 'done')
                self.assertEqual(events[-1]['content'], '部分答案')
                self.assertEqual(events[-1]['finish_reason'], 'length')
                self.assertEqual([event['content'] for event in events if event['type'] == 'reasoning'], ['摘要'])
                history = runtime.execute(DesktopSessionService(sessions).history('s', page=1, page_size=20, until_sequence=None))
                self.assertIn('摘要', json.dumps(history, ensure_ascii=False))
                self.assertNotIn('opaque-secret', json.dumps([history, events]))
            finally:
                runtime.close()
