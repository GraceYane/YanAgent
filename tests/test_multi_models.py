"""P06-01 各供应商契约、凭据隔离、会话覆盖与备用链的离线验收。"""

import asyncio
import json
import tempfile
import unittest
import threading
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from app import create_server

from yanagent.chat import YanAgentApplication
from yanagent.config import AppConfig, ConfigStore
from yanagent.contracts import Message, ModelReply, ToolCall
from yanagent.errors import AuthenticationError, ConfigurationError, EmptyModelResponseError, ModelServerError, ModelResponseError, ModelRefusalError, ModelStreamInterruptedError
from yanagent.events import ModelStreamEvent
from yanagent.models import FakeProvider
from yanagent.models.catalog import PROVIDERS
from yanagent.models.factory import create_single_provider, create_provider_chain, select_model, FallbackProvider
from yanagent.models.native import NativeProvider
from yanagent.sessions import SessionStore
from yanagent.storage import Database
from yanagent.runtime import AgentLoop
from yanagent.tools import ToolDefinition, ToolManager, ToolPermissionContext
from yanagent.debug_log import yan_debug


class Transport:
    """记录请求并返回预设 JSON/SSE，不访问供应商或读取真实配置。"""

    def __init__(self, response=None, frames=()):
        """保存响应和连接关闭标志。"""
        self.response, self.frames, self.calls, self.closed = response, frames, [], False

    async def post_json(self, **kwargs):
        """保存完整请求供检查凭据、URL 与协议正文。"""
        self.calls.append(kwargs)
        return self.response

    async def stream_data(self, **kwargs):
        """逐帧输出并在关闭时标记资源回收。"""
        self.calls.append(kwargs)
        try:
            for frame in self.frames:
                yield json.dumps(frame)
        finally:
            self.closed = True


class ProviderContracts(unittest.IsolatedAsyncioTestCase):
    """独立检查兼容协议和两种原生协议的输入、文本、工具及流结束语义。"""

    def config(self, provider):
        """构造不会访问公网的供应商快照。"""
        return AppConfig(model_provider=provider, model='fixture-model', api_base='https://example.invalid/v1', api_key='fixture-key')

    async def test_each_openai_family_uses_its_own_config(self):
        """GPT、DeepSeek、Qwen 和通用兼容接口各自通过完整响应契约。"""
        for provider in ('openai-compatible', 'openai', 'deepseek', 'qwen'):
            with self.subTest(provider=provider):
                model = create_single_provider(self.config(provider))
                transport = Transport({'choices': [{'message': {'role': 'assistant', 'content': '完成'}, 'finish_reason': 'stop'}]})
                model._transport = transport
                reply = await model.complete([Message('user', '你好')])
                self.assertEqual(reply.content, '完成')
                self.assertEqual(transport.calls[0]['url'], 'https://example.invalid/v1/chat/completions')
                self.assertEqual(transport.calls[0]['headers']['Authorization'], 'Bearer fixture-key')

    async def test_claude_text_tools_and_result_roundtrip(self):
        """Claude 用顶层 system 和原生 tool_use/tool_result 传递工具轮次。"""
        transport = Transport({'content': [{'type': 'text', 'text': '正在计算'},
            {'type': 'tool_use', 'id': 'c', 'name': 'calc', 'input': {'x': 2}}],
            'stop_reason': 'tool_use', 'usage': {'input_tokens': 5, 'output_tokens': 7}})
        provider = NativeProvider(self.config('claude'), transport=transport)
        reply = await provider.complete([Message('system', '规则'), Message('user', '计算')])
        self.assertEqual(reply.tool_calls[0].arguments, {'x': 2})
        self.assertEqual(reply.usage['total_tokens'], 12)
        url, headers, payload = provider.request([Message('system', '规则'), Message('user', '计算'),
            reply.to_message(), Message('tool', '2', tool_call_id='c', name='calc')], [], False)
        self.assertEqual(url, 'https://example.invalid/v1/messages')
        self.assertEqual(headers['x-api-key'], 'fixture-key')
        self.assertNotIn('Authorization', headers)
        self.assertEqual(payload['system'], '规则')
        self.assertEqual(payload['messages'][-1]['content'][0]['tool_use_id'], 'c')

    async def test_native_tool_declarations_preserve_schema_and_optional_description(self):
        """两种原生接口都传递工具参数约束，并接受内部协议允许省略的描述。"""
        schema = {'type': 'object', 'properties': {'expression': {'type': 'string'}},
                  'required': ['expression'], 'additionalProperties': False}
        for vendor in ('claude', 'gemini'):
            provider = NativeProvider(self.config(vendor))
            _, _, payload = provider.request([Message('user', '计算')], [{'name': 'calc', 'parameters': schema}], False)
            tool = payload['tools'][0] if vendor == 'claude' else payload['tools'][0]['functionDeclarations'][0]
            self.assertEqual(tool['input_schema' if vendor == 'claude' else 'parametersJsonSchema'], schema)
            self.assertEqual(tool['description'], '')

    async def test_claude_sse_text_tool_arguments_usage_and_close(self):
        """Claude 文本/参数增量与累积用量正确转换，message_stop 后关闭连接。"""
        transport = Transport(frames=[
            {'type': 'message_start', 'message': {'usage': {'input_tokens': 4, 'output_tokens': 0}}},
            {'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'text_delta', 'text': '好'}},
            {'type': 'content_block_start', 'index': 1, 'content_block': {'type': 'tool_use', 'id': 'c', 'name': 'calc', 'input': {}}},
            {'type': 'content_block_delta', 'index': 1, 'delta': {'type': 'input_json_delta', 'partial_json': '{"x":2}'}},
            {'type': 'message_delta', 'delta': {'stop_reason': 'tool_use'}, 'usage': {'output_tokens': 8}},
            {'type': 'message_stop'},
        ])
        provider = NativeProvider(self.config('claude'), stream_transport=transport)
        events = [event async for event in provider.stream([Message('user', '计算')])]
        self.assertEqual(events[-1].reply.content, '好')
        self.assertEqual(events[-1].reply.tool_calls[0].arguments, {'x': 2})
        self.assertEqual(events[-1].reply.usage['total_tokens'], 12)
        self.assertTrue(transport.closed)

    async def test_gemini_function_signature_and_function_response(self):
        """Gemini 只回传工具调用签名，不把 thought 文本当成答案。"""
        data = {'candidates': [{'content': {'parts': [{'thought': True, 'text': '不进入答案'},
            {'functionCall': {'name': 'calc', 'args': {'x': 2}}, 'thoughtSignature': 'opaque'}]}, 'finishReason': 'STOP'}],
            'usageMetadata': {'promptTokenCount': 2, 'candidatesTokenCount': 3, 'totalTokenCount': 5}}
        transport = Transport(data)
        provider = NativeProvider(self.config('gemini'), transport=transport)
        reply = await provider.complete([Message('user', '计算')])
        self.assertEqual(reply.content, '')
        call = reply.tool_calls[0]
        url, headers, payload = provider.request([Message('user', '计算'), reply.to_message(),
            Message('tool', '2', tool_call_id=call.id)], [], False)
        self.assertTrue(url.endswith('/models/fixture-model:generateContent'))
        self.assertNotIn('fixture-key', url)
        self.assertEqual(headers['x-goog-api-key'], 'fixture-key')
        self.assertEqual(payload['contents'][1]['parts'][0]['thoughtSignature'], 'opaque')
        self.assertEqual(payload['contents'][2]['parts'][0]['functionResponse']['name'], 'calc')

    async def test_gemini_stream_stop_usage_and_connection(self):
        """Gemini SSE 需要终止原因，累计片段后形成一份统一完整回复。"""
        transport = Transport(frames=[
            {'candidates': [{'content': {'parts': [{'text': '甲'}]}}]},
            {'candidates': [{'content': {'parts': [{'text': '乙'}]}, 'finishReason': 'STOP'}],
             'usageMetadata': {'totalTokenCount': 9}},
        ])
        provider = NativeProvider(self.config('gemini'), stream_transport=transport)
        events = [event async for event in provider.stream([Message('user', '你好')])]
        self.assertEqual(events[-1].reply.content, '甲乙')
        self.assertEqual(events[-1].reply.usage['total_tokens'], 9)
        self.assertTrue(transport.closed)

    async def test_native_refusal_malformed_and_truncated_stream_are_errors(self):
        """原生拒答、坏结构与缺失完成事件保持明确错误，不伪造成功。"""
        for provider in ('claude', 'gemini'):
            model = NativeProvider(self.config(provider), transport=Transport({'unexpected': True}))
            with self.assertRaises(ModelResponseError):
                await model.complete([Message('user', 'hi')])
            model = NativeProvider(self.config(provider), stream_transport=Transport(frames=[]))
            with self.assertRaises(ModelResponseError):
                async for _ in model.stream([Message('user', 'hi')]):
                    pass
        model = NativeProvider(self.config('gemini'), transport=Transport({'promptFeedback': {'blockReason': 'SAFETY'}}))
        with self.assertRaises(ModelRefusalError):
            await model.complete([Message('user', 'hi')])

    async def test_fallback_keeps_tool_context_and_does_not_restart_run(self):
        """主模型失败后备用模型收到同一工具结果，前置工具不在工厂中执行。"""
        first = FakeProvider([ModelServerError()])
        backup = FakeProvider([ModelReply(content='恢复')])
        chain = FallbackProvider([('first', 'a', first), ('backup', 'b', backup)])
        messages = [Message('user', '计算'), Message('assistant', '', tool_calls=[ToolCall('c', 'calc', {})]),
                    Message('tool', '2', tool_call_id='c')]
        reply = await chain.complete(messages)
        self.assertEqual(reply.content, '恢复')
        self.assertEqual(backup.calls[0].messages, messages)
        self.assertEqual(reply.provider_metadata['provider'], 'backup')

    async def test_fallback_for_stream_before_first_delta_only(self):
        """首帧前可切换，已输出文字后错误不得拼接备用回答。"""
        for partial in (False, True):
            first = FakeProvider([], stream_outcomes=[[
                *([ModelStreamEvent('text_delta', content='半')] if partial else []), ModelServerError()]])
            backup = FakeProvider([], stream_outcomes=[[
                ModelStreamEvent('text_delta', content='完整'), ModelStreamEvent('completed', reply=ModelReply(content='完整'))]])
            chain = FallbackProvider([('first', 'a', first), ('backup', 'b', backup)])
            if partial:
                with self.assertRaises(ModelStreamInterruptedError):
                    async for _ in chain.stream([Message('user', 'hi')]):
                        pass
                self.assertEqual(len(backup.calls), 0)
            else:
                events = [e async for e in chain.stream([Message('user', 'hi')])]
                self.assertEqual(events[-1].reply.content, '完整')

    async def test_fallback_counts_empty_usage_once_across_loop_retry(self):
        """空响应切换和最终候选补请求均保留用量，不重复累计先前消耗。"""
        for stream in (False, True):
            first = FakeProvider([ModelReply(usage={'total_tokens': 2})])
            backup = FakeProvider([ModelReply(usage={'total_tokens': 3}), ModelReply(content='完成', usage={'total_tokens': 5})])
            if stream:
                first = FakeProvider([], stream_outcomes=[[ModelStreamEvent('completed', reply=ModelReply(usage={'total_tokens': 2}))]])
                backup = FakeProvider([], stream_outcomes=[
                    [ModelStreamEvent('completed', reply=ModelReply(usage={'total_tokens': 3}))],
                    [ModelStreamEvent('completed', reply=ModelReply(content='完成', usage={'total_tokens': 5}))]])
            chain = FallbackProvider([('primary', 'a', first), ('backup', 'b', backup)])
            if stream:
                with self.assertRaises(EmptyModelResponseError) as failure:
                    async for _ in chain.stream([Message('user', 'hi')]):
                        pass
                self.assertEqual(failure.exception.usage['total_tokens'], 5)
                events = [e async for e in chain.stream([Message('user', 'hi')])]
                self.assertEqual(events[-1].reply.usage['total_tokens'], 5)
            else:
                manager = ToolManager()
                result = await AgentLoop(model=chain, tools=manager, sessions=None).run(
                    messages=[Message('user', 'hi')], tool_schemas=[], session_id='s', request_id='r',
                    permission_mode='allow', permission_context=ToolPermissionContext())
                self.assertEqual(result.usage['total_tokens'], 10)

    async def test_fallback_after_real_loop_tool_execution_does_not_repeat_handler(self):
        """真实 AgentLoop 执行一次本地工具，第二轮故障后备用收到同一结果。"""
        executed = []

        async def write(arguments):
            """记录本地副作用次数以检查切换边界。"""
            executed.append(arguments)
            return '已写入'

        manager = ToolManager()
        manager.register(ToolDefinition(name='write', description='测试写入', parameters={'type': 'object'}, handler=write, scope='global'))
        primary = FakeProvider([ModelReply(tool_calls=[ToolCall('c', 'write', {})]), ModelServerError()])
        backup = FakeProvider([ModelReply(content='完成')])
        chain = FallbackProvider([('primary', 'a', primary), ('backup', 'b', backup)])
        result = await AgentLoop(model=chain, tools=manager, sessions=None).run(
            messages=[Message('user', '写入')], tool_schemas=manager.schemas(), session_id='s', request_id='r',
            permission_mode='allow', permission_context=ToolPermissionContext())
        self.assertEqual(result.reply.content, '完成')
        self.assertEqual(len(executed), 1)
        self.assertEqual(backup.calls[0].messages[-1].content, '已写入')
        self.assertEqual(backup.calls[0].messages, primary.calls[-1].messages)

    async def test_authentication_and_refusal_never_fall_back(self):
        """认证错误与拒答保持原错误，不能借备用链绕过。"""
        for error in (AuthenticationError(), ModelRefusalError()):
            backup = FakeProvider([ModelReply(content='不应运行')])
            chain = FallbackProvider([('primary', 'a', FakeProvider([error])), ('backup', 'b', backup)])
            with self.assertRaises(type(error)):
                await chain.complete([Message('user', 'hi')])
            self.assertEqual(backup.calls, [])
        native = NativeProvider(self.config('claude'), stream_transport=Transport(frames=[
            {'type': 'error', 'error': {'type': 'authentication_error', 'message': '不得外泄'}}]))
        with self.assertRaises(AuthenticationError):
            async for _ in native.stream([Message('user', 'hi')]):
                pass

    async def test_protocol_state_is_not_printed_in_debug_trace(self):
        """调试日志屏蔽 opaque 签名，但原对象仍能完整回传供应商。"""
        message = Message('assistant', '', metadata={'provider_state': {'gemini_calls': {'c': {'thoughtSignature': 'opaque-secret'}}}})
        with self.assertLogs('yanagent.debug_trace', level='INFO') as captured:
            yan_debug('test_multi_models.py', 'test_protocol_state', '检查协议状态', messages=[message])
        self.assertNotIn('opaque-secret', '\n'.join(captured.output))
        self.assertEqual(message.metadata['provider_state']['gemini_calls']['c']['thoughtSignature'], 'opaque-secret')


class ModelSettingsTests(unittest.IsolatedAsyncioTestCase):
    """验证配置文件、供应商凭据和 Session 覆盖均不串用。"""

    def setUp(self):
        """建立隔离文件配置、真实 SessionStore 与无网络工厂。"""
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = ConfigStore(self.root / 'config.json', environ={})
        self.store.save({'api_base': 'https://primary.invalid/v1', 'api_key': 'primary-secret', 'model': 'a'})
        self.sessions = SessionStore(Database(data_dir=self.root / 'data', environ={}), user_id='u', agent_id='a')
        self.app = YanAgentApplication(self.store, session_store=self.sessions, provider_factory=lambda _: FakeProvider([]))

    def tearDown(self):
        """释放当前测试的配置和数据库。"""
        self.temp.cleanup()

    async def test_catalog_credentials_and_fallback_can_be_saved_through_existing_ui_actions(self):
        """原有模型控制台可维护目录、凭据、主模型和有界备用链。"""
        self.app.save_model_action({'action': 'set_provider', 'provider_id': 'deepseek', 'api_key': 'backup-secret'})
        self.app.save_model_action({'action': 'save_catalog', 'provider_id': 'deepseek',
            'models': [{'name': 'custom-model', 'capabilities': ['text']}], 'hidden': []})
        self.app.save_model_action({'action': 'set_capability', 'capability': 'chat_fallback', 'enabled': True,
            'chain': [{'provider': 'deepseek', 'model': 'custom-model'}]})
        payload = self.app.models_payload()
        self.assertEqual({p['id'] for p in payload['providers']}, set(PROVIDERS))
        self.assertNotIn('backup-secret', json.dumps(payload))
        self.assertNotIn('primary-secret', json.dumps(self.store.load().to_dict()))
        self.app.save_model_action({'action': 'set_capability', 'capability': 'chat', 'provider_id': 'deepseek', 'model': 'custom-model'})
        self.assertEqual(self.store.load().api_key, 'backup-secret')
        old = select_model(self.store.load(), 'openai-compatible', 'a')
        self.assertEqual(old.api_key, 'primary-secret')

    async def test_session_override_persists_and_prepared_snapshot_stays_fixed(self):
        """会话独立选择模型，修改设置只影响后续准备的任务。"""
        self.app.save_model_action({'action': 'set_provider', 'provider_id': 'gemini', 'api_key': 'gemini-secret'})
        await self.app.session_settings('s1', {'provider': 'gemini', 'model': 'gemini-example'})
        prepared = self.app.prepare_chat({'session_id': 's1', 'message': 'hi'})
        self.assertEqual(prepared.config.api_key, 'gemini-secret')
        self.assertEqual(prepared.config.model_provider, 'gemini')
        reopened = YanAgentApplication(self.store,
            session_store=SessionStore(Database(data_dir=self.root / 'data', environ={}), user_id='u', agent_id='a'),
            provider_factory=lambda _: FakeProvider([]))
        self.assertEqual((await reopened.session_settings('s1'))['model']['provider'], 'gemini')
        other = self.app.prepare_chat({'session_id': 's2', 'message': 'hi'})
        self.assertEqual(other.config.api_key, 'primary-secret')
        await self.app.session_settings('s1', {'model': None, 'provider': None})
        self.assertEqual(prepared.config.model_provider, 'gemini')
        self.assertEqual(self.app.prepare_chat({'session_id': 's1', 'message': 'hi'}).config.model_provider, 'openai-compatible')

    async def test_masked_update_does_not_replace_secret_or_copy_environment_secret(self):
        """脱敏占位保留原密钥；模型动作不会把环境变量密钥复制回文件。"""
        self.app.save_model_action({'action': 'set_provider', 'provider_id': 'claude', 'api_key': 'saved'})
        self.app.save_model_action({'action': 'set_provider', 'provider_id': 'claude', 'api_key': '********'})
        self.assertEqual(self.store.load().provider_configs['claude']['api_key'], 'saved')
        env = ConfigStore(self.store.path, environ={'YAN_API_KEY': 'environment-secret'})
        app = YanAgentApplication(env)
        app.save_model_action({'action': 'set_capability', 'capability': 'chat', 'provider_id': 'claude', 'model': 'example'})
        self.assertNotIn('environment-secret', self.store.path.read_text())

    async def test_invalid_chain_and_profiles_fail_before_requests(self):
        """拒绝未知供应商、重复链路、超长链和伪造嵌套密钥。"""
        for updates in (
            {'provider_configs': {'unknown': {}}},
            {'provider_configs': {'claude': {'api_key': '********'}}},
            {'provider_configs': {'openai-compatible': []}},
            {'chat_fallback': {'enabled': True, 'chain': []}},
            {'chat_fallback': {'enabled': True, 'chain': [{'provider': 'claude', 'model': 'a'}] * 2}},
        ):
            with self.assertRaises(ConfigurationError):
                self.store.save(updates)

    async def test_flat_config_provider_switch_and_clear_do_not_reuse_keys(self):
        """旧配置入口切供应商隔离密钥，显式清空后不会由档案恢复。"""
        switched = self.store.save({'model_provider': 'claude', 'model': 'example'})
        self.assertEqual(switched.api_key, '')
        self.assertEqual(switched.api_base, '')
        self.assertEqual(select_model(switched, 'openai-compatible', 'a').api_key, 'primary-secret')
        self.store.save({'model_provider': 'openai-compatible'})
        cleared = self.store.save({'api_key': ''})
        self.assertEqual(select_model(cleared, 'openai-compatible', 'a').api_key, '')

    async def test_environment_provider_switch_isolates_file_credentials(self):
        """仅通过环境切换供应商，不得把旧主供应商密钥或模型发送过去。"""
        selected = ConfigStore(self.store.path, environ={'YAN_MODEL_PROVIDER': 'claude'}).load()
        self.assertEqual((selected.api_key, selected.api_base, selected.model), ('', '', ''))
        self.app.save_model_action({'action': 'set_provider', 'provider_id': 'claude', 'api_key': 'claude-secret'})
        selected = ConfigStore(self.store.path, environ={'YAN_MODEL_PROVIDER': 'claude', 'YAN_MODEL': 'example'}).load()
        self.assertEqual(selected.api_key, 'claude-secret')
        self.assertEqual(selected.model, 'example')


class ModelSettingsHttpTests(unittest.TestCase):
    """通过桌面实际 URL 验证模型配置与会话覆盖，不调用公网模型。"""

    def test_models_and_session_settings_http_contract_and_identity(self):
        """配置供应商、设置会话、聊天和恢复全局使用一致的后端快照。"""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = ConfigStore(root / 'config.json', environ={})
            store.save({'model': 'primary', 'api_base': 'https://primary.invalid', 'api_key': 'primary-secret'})
            snapshots = []

            def factory(config):
                """捕获请求快照供 HTTP 验收，不创建外部连接。"""
                snapshots.append(config)
                return FakeProvider([ModelReply(content='完成')])

            server = create_server('127.0.0.1', 0, config_store=store,
                provider_factory=factory, database=Database(data_dir=root / 'data', environ={}))
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()

            def request(path, payload=None):
                """统一解析本机成功及拒绝响应，保留 HTTP 状态码。"""
                body = json.dumps(payload).encode() if payload is not None else None
                req = Request(f'http://127.0.0.1:{server.server_address[1]}' + path, data=body,
                    headers={'Content-Type': 'application/json'})
                try:
                    response = urlopen(req, timeout=5)
                except HTTPError as error:
                    response = error
                with response:
                    return response.status, json.loads(response.read())

            try:
                self.assertEqual(request('/api/models', {'action': 'set_provider', 'provider_id': 'claude', 'api_key': 'claude-secret'})[0], 200)
                status, data = request('/api/sessions/session-http/settings', {'provider': 'claude', 'model': 'example'})
                self.assertEqual(status, 200)
                self.assertEqual(data['model']['source'], 'session')
                self.assertNotIn('claude-secret', json.dumps(data))
                self.assertEqual(request('/api/sessions/session-http/settings')[1]['model']['provider'], 'claude')
                self.assertEqual(request('/message', {'session_id': 'session-http', 'message': 'hi', 'stream': False})[0], 200)
                self.assertEqual(snapshots[-1].model_provider, 'claude')
                self.assertEqual(snapshots[-1].api_key, 'claude-secret')
                self.assertEqual(request('/api/sessions/session-http/settings?agent_id=other')[0], 400)
                self.assertEqual(request('/api/sessions/session-http/settings', {'api_key': 'forbidden'})[0], 400)
                status, data = request('/api/sessions/session-http/settings', {'provider': None, 'model': None})
                self.assertEqual((status, data['model']['source']), (200, 'global'))
            finally:
                server.shutdown()
                server.server_close()
                worker.join(timeout=5)
