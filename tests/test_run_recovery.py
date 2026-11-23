"""P05-06 崩溃时点、状态恢复、副作用保护及持久化观测测试。"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
import json
import threading
from pathlib import Path
from urllib.request import Request, urlopen

from app import create_server

from yanagent.chat import YanAgentApplication
from yanagent.config import ConfigStore
from yanagent.contracts import Message, ModelReply, ToolCall, ToolResult, validate_conversation
from yanagent.errors import AuthenticationError, RecoveryAcknowledgementRequiredError, RunRecoveryError
from yanagent.models import FakeProvider
from yanagent.events import ModelStreamEvent
from yanagent.sessions import RunStore, SessionStore, DesktopSessionService
from yanagent.sessions.executions import ExecutionStore
from yanagent.sessions.recovery import RecoveryService
from yanagent.storage import Database
from yanagent.runtime import AgentRuntime
from yanagent.tools import ToolDefinition, ToolManager


class RunRecoveryTests(unittest.IsolatedAsyncioTestCase):
    """通过重建仓储模拟进程重新启动，检查数据库而不是只检查内存对象。"""

    def setUp(self):
        """创建真实 SQLite、可控模型配置及可计数的测试工具。"""
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = Database(data_dir=self.root / 'data', environ={})
        self.sessions = SessionStore(self.db, user_id='local', agent_id='default')
        self.runs = RunStore(self.db, user_id='local', agent_id='default')
        self.steps = ExecutionStore(self.runs)
        self.recovery = RecoveryService(self.runs, self.sessions, self.steps)
        self.config = ConfigStore(self.root / 'config.json', environ={})
        self.config.save({'api_base': 'https://example.invalid/v1', 'model': 'fake',
                          'api_key': 'fake', 'permission_mode': 'allow'})
        self.tools = ToolManager()
        self.executed = []

        async def handler(arguments):
            """记录真实 handler 调用次数。"""
            self.executed.append(arguments)
            return '工具实际执行完成'

        self.tools.register(ToolDefinition(name='write', description='写操作',
            parameters={'type': 'object'}, handler=handler, scope='global'))
        self.tools.register(ToolDefinition(name='read', description='只读操作',
            parameters={'type': 'object'}, handler=handler, scope='global', read_only=True))

    def tearDown(self):
        """释放当前测试目录。"""
        self.temp.cleanup()

    def app(self, outcomes):
        """使用共享真实仓储创建确定性应用。"""
        return YanAgentApplication(self.config, provider_factory=lambda _: FakeProvider(outcomes),
            session_store=self.sessions, run_store=self.runs, tool_manager=self.tools)

    async def source(self, state='pending', *, name='write', journal=True):
        """把进程冻结在指定工具执行时点，尚不写 Tool Message。"""
        await self.sessions.create('s')
        await self.runs.create('source', 's')
        call = ToolCall('original-call', name, {})
        await self.sessions.append('s', [
            Message('user', '完成测试任务', metadata={'request_id': 'source'}),
            Message('assistant', '', tool_calls=[call], metadata={'request_id': 'source'}),
        ])
        if journal:
            await self.steps.plan_tools('source', 's', [call], self.tools)
            if state != 'pending':
                await self.steps.start_tool('source', call.id)
            if state == 'completed':
                await self.steps.finish(self.steps.tool_step_id('source', call.id),
                    result=ToolResult(tool_call_id=call.id, content='已经写入，结果已保存'), duration_ms=7)
        # 使用新 Database 实例模拟重启后只依赖持久化信息。
        reopened = RunStore(Database(data_dir=self.root / 'data', environ={}),
                            user_id='local', agent_id='default')
        reopened.recover_unfinished_on_startup()
        return call

    async def recover_chat(self, outcomes, *, mode='continue', acknowledged=False):
        """通过生产应用路径创建子 Run 并执行恢复循环。"""
        app = self.app(outcomes)
        payload = {'session_id': 's', 'source_request_id': 'source', 'mode': mode,
                   'acknowledge_uncertain': acknowledged}
        prepared = app.prepare_recovery(payload)
        return await app.chat({}, request_id='child', prepared=prepared)

    async def test_completed_result_survives_crash_before_message_append(self):
        """工具已完成但未写回消息时复用日志结果，子 Run 不重复写入。"""
        await self.source('completed')
        await self.recover_chat([
            ModelReply(tool_calls=[ToolCall('new-call', 'write', {})]),
            ModelReply(content='根据已保存结果完成'),
        ])
        self.assertEqual(self.executed, [])
        history = await self.sessions.complete_history('s')
        validate_conversation([r.message for r in history])
        self.assertEqual(history[2].message.content, '已经写入，结果已保存')
        self.assertEqual((await self.runs.get('child', 's')).parent_request_id, 'source')
        self.assertEqual((await self.runs.get('source', 's')).metadata['recovered_by'], 'child')
        self.assertEqual((await self.steps.list_steps('s', 'child'))[1]['status'], 'skipped')

    async def test_uncertain_write_requires_ack_and_never_automatically_repeats(self):
        """执行中崩溃不能解释成未执行；核对后也只继续模型而不重做写操作。"""
        await self.source('running')
        plan = await self.recovery.describe('s', 'source')
        self.assertTrue(plan['requires_acknowledgement'])
        self.assertFalse(plan['can_retry'])
        with self.assertRaises(RecoveryAcknowledgementRequiredError):
            await self.recover_chat([ModelReply(content='不应请求')])
        with self.assertRaises(RecoveryAcknowledgementRequiredError):
            await self.recover_chat([], mode='retry', acknowledged=True)
        await self.recover_chat([
            ModelReply(tool_calls=[ToolCall('new-write', 'write', {})]), ModelReply(content='需要人工核对'),
        ], acknowledged=True)
        self.assertEqual(self.executed, [])
        self.assertEqual((await self.steps.list_steps('s', 'source'))[0]['status'], 'uncertain')

    async def test_planned_tool_is_known_not_started_and_may_be_requested_again(self):
        """进入 handler 前崩溃，恢复后可让模型重新决定并执行一次。"""
        await self.source('pending')
        self.assertFalse((await self.recovery.describe('s', 'source'))['requires_acknowledgement'])
        await self.recover_chat([
            ModelReply(tool_calls=[ToolCall('new-write', 'write', {})]), ModelReply(content='完成'),
        ])
        self.assertEqual(len(self.executed), 1)

    async def test_uncertain_read_only_tool_can_be_explicitly_retried(self):
        """只读工具执行中中断不要求副作用确认，可显式刷新结果。"""
        await self.source('running', name='read')
        await self.recover_chat([
            ModelReply(tool_calls=[ToolCall('new-read', 'read', {})]), ModelReply(content='得到新结果'),
        ], mode='retry')
        self.assertEqual(len(self.executed), 1)

    async def test_legacy_call_without_execution_journal_is_uncertain(self):
        """旧版本无执行日志不能推断未执行，恢复与后续普通任务均保护同参数写调用。"""
        await self.source(journal=False)
        self.assertTrue((await self.recovery.describe('s', 'source'))['requires_acknowledgement'])
        await self.recover_chat([ModelReply(content='先核对外部结果')], acknowledged=True)
        app = self.app([ModelReply(tool_calls=[ToolCall('third', 'write', {})]), ModelReply(content='已阻止重复')])
        await app.chat({'session_id': 's', 'message': '继续'}, request_id='third-run')
        self.assertEqual(self.executed, [])

    async def test_model_usage_and_errors_remain_after_failed_run(self):
        """工具轮次后的模型失败仍保存之前 Token、模型错误和步骤耗时。"""
        app = self.app([
            ModelReply(tool_calls=[ToolCall('w', 'write', {})], usage={'total_tokens': 17}),
            AuthenticationError(),
        ])
        with self.assertRaises(AuthenticationError):
            await app.chat({'session_id': 's', 'message': '测试'}, request_id='run')
        run = await self.runs.get('run', 's')
        self.assertEqual(run.status, 'failed')
        self.assertEqual(run.usage['total_tokens'], 17)
        steps = await self.steps.list_steps('s', 'run')
        self.assertEqual([s['status'] for s in steps], ['completed', 'completed', 'failed'])
        self.assertEqual(steps[-1]['error_code'], 'authentication_error')
        self.assertTrue(all(s['duration_ms'] >= 0 for s in steps))

    async def test_recovery_claim_is_atomic_and_rejects_wrong_owner(self):
        """同一来源并发恢复只有一个子 Run；不同用户或 Session 不可读取。"""
        await self.source('completed')
        results = await asyncio.gather(*[
            self.recovery.claim('s', 'source', child, 'continue', False,
                                {'recovery_message': '继续任务'}) for child in ('c1', 'c2')
        ], return_exceptions=True)
        self.assertEqual(sum(r is None for r in results), 1)
        other = RunStore(self.db, user_id='other', agent_id='default')
        service = RecoveryService(other, SessionStore(self.db, user_id='other', agent_id='default'), ExecutionStore(other))
        with self.assertRaises(RunRecoveryError):
            await service.describe('s', 'source')
        with self.assertRaises(RunRecoveryError):
            await self.recovery.describe('wrong-session', 'source')
        with self.assertRaises(RunRecoveryError):
            await self.recovery.claim('s', 'source', 'another', 'continue', False,
                                      {'recovery_message': '继续'})

    async def test_saved_final_answer_is_recognized_as_completed_on_restart(self):
        """最终 Assistant 已落库但 Run 尚未终结，重启识别完成而不重发模型。"""
        await self.sessions.create('s')
        await self.runs.create('source', 's')
        await self.sessions.append('s', [Message('assistant', '已完成', metadata={'request_id': 'source'})])
        self.runs.recover_unfinished_on_startup()
        self.assertEqual((await self.runs.get('source', 's')).status, 'completed')
        self.assertFalse((await self.recovery.describe('s', 'source'))['can_continue'])

    async def test_instruction_crash_gap_is_reconciled_without_duplicate_injection(self):
        """指令已写消息但尚未更新 Run 时，重启按 instruction ID 识别已注入。"""
        await self.sessions.create('s')
        await self.runs.create('source', 's')
        await self.runs.queue_instruction('source', 's', 'one', '新要求一')
        await self.runs.queue_instruction('source', 's', 'two', '新要求二')
        await self.sessions.append('s', [Message('user', '新要求一',
            metadata={'request_id': 'source', 'run_instruction_id': 'one'})])
        self.runs.recover_unfinished_on_startup()
        items = (await self.runs.get('source', 's')).metadata['run_instructions']
        self.assertEqual([i['status'] for i in items], ['injected', 'rejected'])
        self.assertEqual(items[0]['sequence'], 0)

    async def test_execution_log_failure_prevents_handler(self):
        """执行前日志无法写入时，不进入 handler 产生副作用。"""
        async def fail_checkpoint():
            """模拟权限批准后、handler 前的数据库故障。"""
            raise RuntimeError('持久化不可用')
        with self.assertRaises(RuntimeError):
            await self.tools.execute(ToolCall('x', 'write', {}), permission_mode='allow',
                                     on_execute=fail_checkpoint)
        self.assertEqual(self.executed, [])

    async def test_queued_input_can_be_recovered_after_restart(self):
        """尚未拿到 Session 锁的任务保留原始需求，恢复时不变成空任务。"""
        app = self.app([ModelReply(content='继续原需求')])
        prepared = app.prepare_chat({'session_id': 's', 'message': '尚未执行的原始需求'})
        await app.queue_run(prepared, request_id='source')
        self.assertEqual((await self.runs.get('source', 's')).status, 'queued')
        self.runs.recover_unfinished_on_startup()
        preview = await DesktopSessionService(self.sessions, run_store=self.runs).history(
            's', page=1, page_size=20, until_sequence=None)
        self.assertTrue(any(m.get('run_id') == 'source' for m in preview['messages']))
        recovery = app.prepare_recovery({'session_id': 's', 'source_request_id': 'source'})
        await app.chat({}, request_id='child', prepared=recovery)
        history = await self.sessions.complete_history('s')
        self.assertEqual(history[0].message.content, '尚未执行的原始需求')
        self.assertEqual(history[0].message.metadata['request_id'], 'source')
        self.assertEqual((await self.runs.get('child', 's')).status, 'completed')

    async def test_cancelled_handler_keeps_uncertain_state_and_known_usage(self):
        """工具执行期间取消后保存不确定状态，不能把取消当成副作用回滚。"""
        started = asyncio.Event()

        async def blocking(arguments):
            """模拟已开始执行且尚未返回的写工具。"""
            started.set()
            await asyncio.Event().wait()

        self.tools.register(ToolDefinition(name='blocking', description='阻塞写操作',
            parameters={'type': 'object'}, handler=blocking, scope='global'))
        app = self.app([ModelReply(tool_calls=[ToolCall('b', 'blocking', {})], usage={'total_tokens': 3})])
        task = asyncio.create_task(app.chat({'session_id': 's', 'message': '测试取消'}, request_id='source'))
        await asyncio.wait_for(started.wait(), timeout=2)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        run = await self.runs.get('source', 's')
        self.assertEqual(run.status, 'cancelled')
        self.assertEqual(run.usage['total_tokens'], 3)
        steps = await self.steps.list_steps('s', 'source')
        self.assertEqual(steps[-1]['status'], 'uncertain')
        self.assertTrue((await self.recovery.describe('s', 'source'))['requires_acknowledgement'])

    async def test_http_diagnostics_recovery_stream_and_history(self):
        """真实本机 HTTP 从诊断创建恢复 Run，SSE 完成后历史可定位父子任务。"""
        await self.source('completed')
        fake = FakeProvider([], stream_outcomes=[[
            ModelStreamEvent('text_delta', content='已根据结果完成'),
            ModelStreamEvent('completed', reply=ModelReply(content='已根据结果完成', usage={'total_tokens': 9})),
        ]])
        app = YanAgentApplication(self.config, provider_factory=lambda _: fake,
            session_store=self.sessions, run_store=self.runs, tool_manager=self.tools)
        server = create_server(application=app, host='127.0.0.1', port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}'

        def request_flow():
            """在线程中像桌面一样调用诊断、恢复和 SSE，避免阻塞测试事件循环。"""
            with urlopen(base + '/api/sessions/s/run_diagnostics?request_id=source', timeout=3) as response:
                self.assertTrue(json.load(response)['can_continue'])
            request = Request(base + '/runs/recover', method='POST',
                headers={'Content-Type': 'application/json'},
                data=json.dumps({'session_id': 's', 'source_request_id': 'source', 'mode': 'continue'}).encode())
            with urlopen(request, timeout=3) as response:
                created = json.load(response)
            with urlopen(base + '/stream?request_id=' + created['request_id'], timeout=3) as response:
                events = [json.loads(line[6:]) for line in response.read().decode().splitlines() if line.startswith('data: ')]
            self.assertEqual(events[-1]['type'], 'done')
            return created['request_id']

        try:
            child_id = await asyncio.to_thread(request_flow)
            self.assertEqual((await self.runs.get(child_id, 's')).parent_request_id, 'source')
            self.assertEqual(self.executed, [])
            self.assertEqual(len(fake.calls), 1)
            self.assertFalse((await self.recovery.describe('s', 'source'))['can_continue'])
            detail = await self.recovery.describe('s', child_id)
            self.assertEqual(detail['usage']['total_tokens'], 9)
            self.assertIsNotNone(detail['duration_ms'])
        finally:
            await asyncio.to_thread(server.shutdown)
            server.server_close()
            thread.join(timeout=2)

    async def test_accepted_queued_stream_is_durable_and_cancel_is_recorded(self):
        """流任务返回已接受前已有 queued Run，同会话等待任务取消后有终态。"""
        entered = threading.Event()

        class BlockingProvider:
            """占住第一个 Session 任务以制造真实排队。"""

            async def complete(self, messages, *, tools=()):
                """满足 Provider 的普通调用接口。"""
                return ModelReply(content='完成')

            async def stream(self, messages, *, tools=()):
                """第一条任务只等待取消，第二条不能进入此处。"""
                entered.set()
                yield ModelStreamEvent('text_delta', content='开始')
                await asyncio.Event().wait()

        app = YanAgentApplication(self.config, provider_factory=lambda _: BlockingProvider(),
            session_store=self.sessions, run_store=self.runs, tool_manager=self.tools)
        runtime = AgentRuntime(app)
        try:
            runtime.start_stream({'session_id': 's', 'message': '第一条'}, request_id='first')
            self.assertTrue(await asyncio.to_thread(entered.wait, 2))
            runtime.start_stream({'session_id': 's', 'message': '第二条'}, request_id='second')
            self.assertEqual((await self.runs.get('second', 's')).status, 'queued')
            runtime.cancel(request_id='second')
            for _ in range(100):
                if (await self.runs.get('second', 's')).status == 'cancelled':
                    break
                await asyncio.sleep(0.01)
            self.assertEqual((await self.runs.get('second', 's')).status, 'cancelled')
        finally:
            runtime.cancel(request_id='first')
            for _ in range(100):
                if (await self.runs.get('first', 's')).status == 'cancelled':
                    break
                await asyncio.sleep(0.01)
            runtime.close()
