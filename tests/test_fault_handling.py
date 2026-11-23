"""P05-05 故障注入：模型重试、写工具去重、取消及流式断线续传。"""

from __future__ import annotations

import asyncio
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request, urlopen

from app import create_server
from yanagent.chat import YanAgentApplication
from yanagent.config import ConfigStore
from yanagent.contracts import Message, ModelReply, ToolCall
from yanagent.errors import (
    AuthenticationError, EmptyModelResponseError, ModelConnectionError,
    ModelServerError, RateLimitError,
)
from yanagent.events import ModelStreamEvent
from yanagent.models import FakeProvider
from yanagent.retries import parse_retry_after, retry_delay
from yanagent.runtime import AgentLoop, AgentRuntime
from yanagent.tools import ToolDefinition, ToolManager, ToolPermissionContext


class FaultHandlingTests(unittest.IsolatedAsyncioTestCase):
    """在离线可控模型下验证重试不跨越工具执行边界。"""

    async def run_loop(self, fake, manager=None, **options):
        """创建单次独立 Run 并执行真实 AgentLoop。"""
        manager = manager if manager is not None else ToolManager()
        return await AgentLoop(model=fake, tools=manager, sessions=None, **options).run(
            messages=[Message('user', '测试故障处理')], tool_schemas=manager.schemas(),
            session_id='fault-session', request_id='fault-run', permission_mode='allow',
            permission_context=ToolPermissionContext(),
        )

    async def test_empty_reply_retries_once_and_counts_known_usage(self):
        """完全空响应补一次且累计已知用量，连续空两次则失败。"""
        fake = FakeProvider([
            ModelReply(content=' ', usage={'total_tokens': 4}),
            ModelReply(content='完成', usage={'total_tokens': 5}),
        ])
        result = await self.run_loop(fake)
        self.assertEqual(result.usage['total_tokens'], 9)
        self.assertEqual(len(fake.calls), 2)
        self.assertEqual(result.turns, 1)
        with self.assertRaises(EmptyModelResponseError):
            await self.run_loop(FakeProvider([ModelReply(), ModelReply()]))

    async def test_transient_errors_have_bounded_attempts(self):
        """429 和 5xx 最多三个请求，认证与网络不确定错误不自动重试。"""
        with patch('yanagent.retries.random.uniform', return_value=0), patch(
            'yanagent.runtime.agent_loop.retry_delay', side_effect=lambda e, i: 0 if i < 2 else None,
        ):
            fake = FakeProvider([RateLimitError(), ModelServerError(), ModelReply(content='恢复')])
            self.assertEqual((await self.run_loop(fake)).reply.content, '恢复')
            limited = FakeProvider([RateLimitError(), RateLimitError(), RateLimitError()])
            with self.assertRaises(RateLimitError):
                await self.run_loop(limited)
            self.assertEqual(len(limited.calls), 3)
        for error in (AuthenticationError(), ModelConnectionError()):
            fake = FakeProvider([error, ModelReply(content='不应调用')])
            with self.assertRaises(type(error)):
                await self.run_loop(fake)
            self.assertEqual(len(fake.calls), 1)

    async def test_retry_after_and_backoff_respect_deadline_and_cancel(self):
        """遵守 Retry-After；期限不足不抢跑请求，退避期间可取消。"""
        self.assertEqual(parse_retry_after('120'), 120)
        self.assertIsNone(parse_retry_after('nan'))
        self.assertIsNone(parse_retry_after('invalid'))
        error = RateLimitError(retry_after_seconds=120)
        self.assertGreaterEqual(retry_delay(error, 0), 120)
        self.assertIsNone(retry_delay(error, 2))
        fake = FakeProvider([error, ModelReply(content='不应调用')])
        with self.assertRaises(RateLimitError):
            await self.run_loop(fake, total_timeout_seconds=0.5)
        self.assertEqual(len(fake.calls), 1)
        fake = FakeProvider([RateLimitError(retry_after_seconds=20)])
        task = asyncio.create_task(self.run_loop(fake))
        while not fake.calls:
            await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(len(fake.calls), 1)

    async def test_model_retry_does_not_reexecute_write_tool(self):
        """写工具执行后模型限流只重发带结果的模型上下文。"""
        executed = []

        async def write_tool(arguments):
            """记录一次写入以检验副作用次数。"""
            executed.append(arguments)
            return '已写入'

        manager = ToolManager()
        manager.register(ToolDefinition(
            name='write', description='测试写入', parameters={'type': 'object'},
            handler=write_tool, scope='global',
        ))
        fake = FakeProvider([
            ModelReply(tool_calls=[ToolCall('w1', 'write', {})]),
            RateLimitError(), ModelReply(content='完成'),
        ])
        with patch('yanagent.runtime.agent_loop.retry_delay', return_value=0):
            await self.run_loop(fake, manager)
        self.assertEqual(len(executed), 1)
        self.assertEqual(fake.calls[1].messages[-1].role, 'tool')
        self.assertEqual(fake.calls[1].messages, fake.calls[2].messages)

    async def test_same_write_with_new_ids_is_blocked_even_after_failure(self):
        """同参数换 ID 的同轮及后续调用被拦截，异常也不盲目重做。"""
        for fails in (False, True):
            executed = []

            async def write_tool(arguments):
                """模拟提交后成功或连接丢失。"""
                executed.append(arguments)
                if fails:
                    raise OSError('副作用可能已发生')
                return '完成一次'

            manager = ToolManager()
            manager.register(ToolDefinition(
                name='write', description='写入', parameters={'type': 'object'},
                handler=write_tool, scope='global',
            ))
            fake = FakeProvider([
                ModelReply(tool_calls=[ToolCall('w1', 'write', {}), ToolCall('w2', 'write', {})]),
                ModelReply(tool_calls=[ToolCall('w3', 'write', {})]),
                ModelReply(content='已核对结果'),
            ])
            await self.run_loop(fake, manager, max_consecutive_tool_failures=4)
            self.assertEqual(len(executed), 1)
            self.assertTrue(fake.calls[-1].messages[-1].is_error)
            self.assertIn('本次未执行', fake.calls[-1].messages[-1].content)

    async def test_read_only_tool_can_refresh_but_repetition_is_bounded(self):
        """显式只读工具可重复获取，第四次同参请求反馈失败而不执行。"""
        executed = []

        async def read_tool(arguments):
            """用递增结果模拟外部状态变化。"""
            executed.append(arguments)
            return str(len(executed))

        manager = ToolManager()
        manager.register(ToolDefinition(
            name='read', description='只读', parameters={'type': 'object'},
            handler=read_tool, scope='global', read_only=True,
        ))
        self.assertTrue(manager.get('read').read_only)
        fake = FakeProvider([
            ModelReply(tool_calls=[ToolCall(f'r{i}', 'read', {})]) for i in range(4)
        ] + [ModelReply(content='停止重复查询')])
        await self.run_loop(fake, manager)
        self.assertEqual(len(executed), 3)
        self.assertTrue(fake.calls[-1].messages[-1].is_error)

    async def test_tool_fingerprint_ignores_argument_key_order(self):
        """对象键顺序和调用 ID 变化不能绕过同参数检查。"""
        self.assertEqual(
            AgentLoop._tool_fingerprint(ToolCall('a', 'write', {'x': 1, 'y': 2})),
            AgentLoop._tool_fingerprint(ToolCall('b', 'write', {'y': 2, 'x': 1})),
        )


class StreamFaultTests(unittest.TestCase):
    """用真实运行时及本机 HTTP 验证流式重试和订阅续传。"""

    def setUp(self):
        """为每个用例提供隔离配置和运行时清理列表。"""
        self.temp = tempfile.TemporaryDirectory()
        self.store = ConfigStore(Path(self.temp.name) / 'config.json', environ={})
        self.store.save({'api_base': 'https://example.invalid/v1', 'model': 'fake', 'api_key': 'fake'})
        self.runtime = None

    def tearDown(self):
        """关闭工作线程并释放临时配置。"""
        if self.runtime is not None:
            self.runtime.close()
        self.temp.cleanup()

    def collect(self, runtime, run_id):
        """有界读取到运行终态。"""
        cursor = 0
        events = []
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            batch, terminal = runtime.wait_events(run_id, cursor, timeout=0.1)
            events.extend(batch)
            cursor += len(batch)
            if terminal:
                return events
        self.fail('等待终态超时')

    def test_empty_stream_retry_and_partial_stream_never_replayed(self):
        """首帧前空流可补一次；文字或工具增量后失败不得重放。"""
        for first, success in (([], True), ([RateLimitError()], True), ([ModelStreamEvent('text_delta', content='半')], False), (
            [ModelStreamEvent('tool_call_delta', tool_index=0, tool_name='write')], False,
        )):
            fake = FakeProvider([], stream_outcomes=[
                [*first, *([] if success else [RateLimitError()])],
                [ModelStreamEvent('text_delta', content='好'), ModelStreamEvent(
                    'completed', reply=ModelReply(content='好'),
                )],
            ])
            app = YanAgentApplication(self.store, provider_factory=lambda _: fake)
            runtime = AgentRuntime(app)
            try:
                runtime.start_stream({'session_id': 's', 'message': 'hi', 'stream': True}, request_id='r')
                events = self.collect(runtime, 'r')
            finally:
                runtime.close()
            self.assertEqual(len(fake.calls), 2 if success else 1)
            self.assertEqual(events[-1].type, 'done' if success else 'error')
            if not success:
                self.assertEqual(events[-1].data['code'], 'model_stream_interrupted')

    def test_http_resume_uses_same_run_and_skips_delivered_events(self):
        """HTTP 断开后携带 Last-Event-ID 续读，模型只调用一次。"""
        fake = FakeProvider([], stream_outcomes=[[
            ModelStreamEvent('text_delta', content='第一'),
            ModelStreamEvent('text_delta', content='第二'),
            ModelStreamEvent('completed', reply=ModelReply(content='第一第二')),
        ]])
        app = YanAgentApplication(self.store, provider_factory=lambda _: fake)
        server = create_server(application=app, host='127.0.0.1', port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            server.runtime.start_stream({'session_id': 's', 'message': 'hi', 'stream': True}, request_id='r')
            self.collect(server.runtime, 'r')
            url = f'http://127.0.0.1:{server.server_port}/stream?request_id=r'
            with urlopen(url, timeout=3) as response:
                first_id = response.readline().decode().strip()
                self.assertEqual(first_id, 'id: 1')
            with urlopen(Request(url, headers={'Last-Event-ID': '1'}), timeout=3) as response:
                resumed = response.read().decode()
            self.assertIn('id: 2', resumed)
            self.assertNotIn('"content":"第一"', resumed)
            self.assertIn('"type":"done"', resumed)
            self.assertEqual(len(fake.calls), 1)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
