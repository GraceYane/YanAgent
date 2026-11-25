"""P06-04 真实临时文件、命令、确认、取消及桌面流式执行链验证。"""

import asyncio
import dataclasses
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from yanagent.chat import YanAgentApplication
from yanagent.config import ConfigStore
from yanagent.contracts import ModelReply, ToolCall
from yanagent.contracts import Message
from yanagent.context import PromptContextBuilder, RuntimeIdentity
from yanagent.models.openai_compatible import prepare_request
from yanagent.events import ModelStreamEvent
from yanagent.models import FakeProvider
from yanagent.runtime import AgentRuntime
from yanagent.sessions import SessionStore, RunStore
from yanagent.storage import Database
from yanagent.tools import ToolManager, ToolPermissionContext, ToolConfirmationResult
from yanagent.tools.files import file_definitions
from yanagent.tools.processes import ProcessService, decode_output, MAX_OUTPUT_BYTES
from yanagent.tools.execution_context import execution_context


class FileCommandToolTests(unittest.IsolatedAsyncioTestCase):
    """使用默认工具执行器验证真实副作用，绝不操作用户项目。"""

    def setUp(self):
        """建立独立中文工作区、工具目录和可信身份。"""
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = self.base / '中文 项目'
        self.root.mkdir()
        self.manager = ToolManager()
        self.processes = ProcessService()
        for definition in (*file_definitions(), *self.processes.definitions()):
            self.manager.register(definition)
        self.context = ToolPermissionContext(allowed_scopes={'workspace'}, workspace=str(self.root),
            user_id='u', agent_id='a', session_id='s', run_id='r', confirmation_ui_available=True)
        self.counter = 0
        self.requests = []

    async def asyncTearDown(self):
        """回收当前用例创建的进程后再删除其临时文件。"""
        self.processes.close_loop()
        tasks = [job.task for job in self.processes.jobs.values() if job.task and not job.task.done()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.temp.cleanup()

    async def call(self, name, arguments, *, approve=True, context=None, mode='allow'):
        """走真实参数、权限和确认入口，可明确模拟用户批准或拒绝。"""
        self.counter += 1
        async def confirm(request):
            """保存待确认内容，并返回与本次请求绑定的一次性决定。"""
            self.requests.append(request)
            return ToolConfirmationResult(request.request_id, 'approved' if approve else 'rejected')
        return await self.manager.execute(ToolCall(str(self.counter), name, arguments), permission_mode=mode,
            permission_context=context or self.context, confirmation_handler=confirm)

    async def success(self, name, arguments, **kwargs):
        """检查工具成功，并解析合法 JSON 结果。"""
        result = await self.call(name, arguments, **kwargs)
        self.assertFalse(result.is_error, result.content)
        return json.loads(result.content)

    async def test_create_read_edit_with_hash_and_confirmation_details(self):
        """确认新建、读取哈希、精确编辑形成真实文件闭环。"""
        created = await self.success('write_file', {'path': '子目录/你好.txt', 'content': '你好word\n端口=3000', 'create_parents': True})
        self.assertTrue(created['created'])
        request = self.requests[0]
        self.assertEqual(request.arguments['content'], '你好word\n端口=3000')
        self.assertEqual(request.workspace, str(self.root))
        read = await self.success('read_file', {'path': '子目录/你好.txt'})
        await self.success('edit_file', {'path': '子目录/你好.txt', 'expected_etag': read['etag'], 'old_text': '3000', 'new_text': '8080'})
        self.assertEqual((self.root / '子目录/你好.txt').read_text(encoding='utf-8'), '你好word\n端口=8080')
        self.assertIsNone(execution_context.get())

    async def test_denied_write_and_command_produce_no_side_effect(self):
        """拒绝后既不创建目录，也不启动本机命令。"""
        result = await self.call('write_file', {'path': 'nested/no.txt', 'content': 'no', 'create_parents': True}, approve=False)
        self.assertTrue(result.is_error)
        self.assertFalse((self.root / 'nested').exists())
        result = await self.call('execute_command', {'command': "'no'"}, approve=False)
        self.assertTrue(result.is_error)
        self.assertEqual(self.processes.jobs, {})

    async def test_no_confirmation_ui_never_writes_even_in_allow_mode(self):
        """高风险操作不会因 allow 绕过必须确认的工具元数据。"""
        context = dataclasses.replace(self.context, confirmation_ui_available=False)
        result = await self.call('write_file', {'path': 'no.txt', 'content': 'no'}, context=context)
        self.assertTrue(result.is_error)
        self.assertFalse((self.root / 'no.txt').exists())

    async def test_hash_conflict_preserves_external_modification(self):
        """旧 etag 和无 etag 的覆盖都不能破坏外部最新版本。"""
        file = self.root / 'a.txt'
        file.write_text('old', encoding='utf-8')
        read = await self.success('read_file', {'path': 'a.txt'})
        file.write_text('external', encoding='utf-8')
        for arguments in ({'expected_etag': read['etag']}, {}):
            result = await self.call('write_file', {'path': 'a.txt', 'content': 'overwrite', **arguments})
            self.assertTrue(result.is_error)
            self.assertEqual(file.read_text(encoding='utf-8'), 'external')

    async def test_ambiguous_edit_and_empty_old_text_are_rejected(self):
        """精确编辑默认拒绝多匹配，显式全替换才会修改全部。"""
        file = self.root / 'a.txt'
        file.write_text('x x', encoding='utf-8')
        read = await self.success('read_file', {'path': 'a.txt'})
        args = {'path': 'a.txt', 'old_text': 'x', 'new_text': 'y', 'expected_etag': read['etag']}
        self.assertTrue((await self.call('edit_file', args)).is_error)
        self.assertTrue((await self.call('edit_file', {**args, 'old_text': ''})).is_error)
        result = await self.success('edit_file', {**args, 'replace_all': True})
        self.assertEqual(result['replacements'], 2)
        self.assertEqual(file.read_text(encoding='utf-8'), 'y y')

    async def test_failed_atomic_replace_leaves_original_and_no_temp(self):
        """发布失败时原文件保持完整，临时文件被回收。"""
        file = self.root / 'a.txt'
        file.write_text('old', encoding='utf-8')
        read = await self.success('read_file', {'path': 'a.txt'})
        with patch('yanagent.tools.files.os.replace', side_effect=OSError()):
            result = await self.call('write_file', {'path': 'a.txt', 'content': 'new', 'expected_etag': read['etag']})
        self.assertTrue(result.is_error)
        self.assertEqual(file.read_text(encoding='utf-8'), 'old')
        self.assertEqual(list(self.root.glob('.yanagent-tool-*')), [])

    async def test_traversal_absolute_outside_and_missing_context(self):
        """读写边界与命令 cwd 一样拒绝根外路径，模型不能提供身份字段。"""
        for name, args in [('read_file', {'path': '../outside.txt'}),
                           ('write_file', {'path': str(self.base / 'outside.txt'), 'content': 'no'}),
                           ('execute_command', {'command': 'echo no', 'cwd': '..'}),
                           ('read_file', {'path': 'a.txt', 'workspace': str(self.base)})]:
            self.assertTrue((await self.call(name, args)).is_error)
        context = dataclasses.replace(self.context, workspace=None, allowed_scopes={'global'})
        self.assertTrue((await self.call('list_directory', {}, context=context)).is_error)
        self.assertFalse((self.base / 'outside.txt').exists())

    async def test_hardlink_and_junction_are_not_followed(self):
        """模型文件工具复用文件句柄边界，拒绝链接到根外内容。"""
        outside = self.base / 'outside.txt'
        outside.write_text('secret', encoding='utf-8')
        os.link(outside, self.root / 'alias.txt')
        self.assertTrue((await self.call('read_file', {'path': 'alias.txt'})).is_error)
        self.assertTrue((await self.call('write_file', {'path': 'alias.txt', 'content': 'overwrite'})).is_error)
        directory = self.base / 'outside'
        directory.mkdir()
        link = self.root / 'link'
        if os.name == 'nt':
            result = subprocess.run(['powershell', '-NoProfile', '-NonInteractive', '-Command',
                'New-Item -ItemType Junction -Path $env:YAN_LINK_PATH -Target $env:YAN_LINK_TARGET | Out-Null'],
                env={**os.environ, 'YAN_LINK_PATH': str(link), 'YAN_LINK_TARGET': str(directory)}, capture_output=True)
            self.assertEqual(result.returncode, 0)
        else:
            link.symlink_to(directory, target_is_directory=True)
        try:
            self.assertTrue((await self.call('write_file', {'path': 'link/no.txt', 'content': 'no'})).is_error)
            self.assertTrue((await self.call('execute_command', {'cwd': 'link', 'command': 'echo no'})).is_error)
            self.assertFalse((directory / 'no.txt').exists())
        finally:
            link.rmdir() if os.name == 'nt' else link.unlink()

    async def test_binary_non_utf8_and_large_text_are_explicit_failures(self):
        """不把二进制当文本，也不生成仅扩展名像 Word 的坏文件。"""
        for name, data in [('binary.txt', b'a\x00b'), ('gbk.txt', '中文'.encode('gbk')), ('large.txt', b'a' * (512 * 1024 + 1))]:
            (self.root / name).write_bytes(data)
            self.assertTrue((await self.call('read_file', {'path': name})).is_error)
        self.assertTrue((await self.call('write_file', {'path': '你好.docx', 'content': '你好word'})).is_error)
        self.assertFalse((self.root / '你好.docx').exists())

    async def test_line_ranges_search_and_pruned_directories(self):
        """行范围与字面量查询返回真实路径，依赖目录不参与搜索。"""
        (self.root / 'settings.txt').write_text('one\nport=8080\nthree', encoding='utf-8')
        (self.root / 'node_modules').mkdir()
        (self.root / 'node_modules/hidden.txt').write_text('port=8080', encoding='utf-8')
        read = await self.success('read_file', {'path': 'settings.txt', 'start_line': 2, 'max_lines': 1})
        self.assertEqual(read['content'].replace('\r\n', '\n'), 'port=8080\n')
        self.assertTrue(read['truncated'])
        found = await self.success('search_files', {'query': 'port=8080'})
        self.assertEqual(len(found['matches']), 1)
        self.assertEqual(found['matches'][0]['line'], 2)
        found = await self.success('search_files', {'query': 'settings', 'target': 'files'})
        self.assertEqual(found['matches'][0]['path'], 'settings.txt')
        listed = await self.success('list_directory', {})
        self.assertEqual(len(listed['entries']), 1)

    async def test_large_serialized_result_remains_valid_json(self):
        """包含转义字符的大内容不因执行器截断变成损坏 JSON。"""
        (self.root / 'a.txt').write_text('"\\\t' * 10000, encoding='utf-8')
        read = await self.success('read_file', {'path': 'a.txt'})
        self.assertTrue(read['truncated'])
        self.assertEqual(read['etag'], hashlib.sha256((self.root / 'a.txt').read_bytes()).hexdigest())

    async def test_concurrent_contexts_do_not_share_workspace(self):
        """同一个工具目录交错执行两个会话仍读到各自目录。"""
        other = self.base / 'other'
        other.mkdir()
        (self.root / 'a.txt').write_text('first', encoding='utf-8')
        (other / 'a.txt').write_text('second', encoding='utf-8')
        context = dataclasses.replace(self.context, session_id='other', workspace=str(other))
        one, two = await asyncio.gather(self.success('read_file', {'path': 'a.txt'}), self.success('read_file', {'path': 'a.txt'}, context=context))
        self.assertEqual((one['content'], two['content']), ('first', 'second'))

    async def test_command_unicode_exit_and_cwd(self):
        """真实本机命令使用固定工作目录并返回中文输出与退出码。"""
        command = "Write-Output '你好 命令'; (Get-Location).Path" if os.name == 'nt' else "printf '你好 命令\\n'; pwd"
        result = await self.success('execute_command', {'command': command})
        self.assertIn('你好 命令', result['output'])
        self.assertIn(str(self.root), result['output'])
        self.assertEqual(result['exit_code'], 0)
        failure = await self.call('execute_command', {'command': 'exit 7'})
        self.assertTrue(failure.is_error)
        job = list(self.processes.jobs.values())[-1]
        status = await self.success('process_status', {'process_id': job.id})
        self.assertEqual(status['exit_code'], 7)

    async def test_command_timeout_and_outer_cancellation_reap_processes(self):
        """内部期限与外层任务取消都确实回收系统进程。"""
        command = 'Start-Sleep -Seconds 30' if os.name == 'nt' else 'sleep 30'
        result = await self.call('execute_command', {'command': command, 'timeout_seconds': 0.2})
        self.assertTrue(result.is_error)
        timed = list(self.processes.jobs.values())[-1]
        self.assertEqual(timed.state, 'timed_out')
        self.assertIsNotNone(timed.process.poll())
        task = asyncio.create_task(self.call('execute_command', {'command': command}))
        while len(self.processes.jobs) < 2:
            await asyncio.sleep(0.01)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        cancelled = list(self.processes.jobs.values())[-1]
        self.assertEqual(cancelled.state, 'cancelled')
        self.assertIsNotNone(cancelled.process.poll())

    async def test_background_poll_stop_scope_and_run_cleanup(self):
        """后台任务立即返回句柄、跨会话拒绝、停止及 Run 取消均有效。"""
        command = "Write-Output 'started'; Start-Sleep -Seconds 30" if os.name == 'nt' else "echo started; sleep 30"
        result = await self.success('execute_command', {'command': command, 'background': True})
        pid = result['process_id']
        self.assertEqual(result['status'], 'running')
        other = dataclasses.replace(self.context, session_id='other')
        self.assertTrue((await self.call('process_status', {'process_id': pid}, context=other)).is_error)
        self.assertTrue((await self.call('stop_process', {'process_id': pid}, approve=False)).is_error)
        stopped = await self.success('stop_process', {'process_id': pid})
        self.assertEqual(stopped['status'], 'cancelled')
        result = await self.success('execute_command', {'command': command, 'background': True})
        await self.processes.cancel_run('r')
        self.assertIsNotNone(self.processes.jobs[result['process_id']].process.poll())

    async def test_command_output_is_drained_and_bounded(self):
        """大输出不会堵塞管道，缓存和对模型输出都有明确上限。"""
        command = "Write-Output ('x' * 100000)" if os.name == 'nt' else "printf '%100000s' x"
        result = await self.success('execute_command', {'command': command})
        self.assertTrue(result['truncated'])
        job = self.processes.jobs[result['process_id']]
        self.assertLessEqual(len(job.buffer), MAX_OUTPUT_BYTES)
        self.assertLessEqual(len(result['output']), 12000)

    async def test_background_cap_and_encoding(self):
        """并发进程有限，编码可明确选择，环境不会直接继承 API Key。"""
        self.assertEqual(decode_output('中文'.encode('gbk'), 'gb18030')[0], '中文')
        self.assertEqual(decode_output('中文'.encode('utf-8')[:-1], 'auto', final=False), ('中', 'utf-8', False))
        self.assertEqual(decode_output('中文'.encode('utf-8')[1:], 'auto', dropped=True), ('文', 'utf-8', False))
        command = 'Start-Sleep -Seconds 30' if os.name == 'nt' else 'sleep 30'
        for _ in range(4):
            await self.success('execute_command', {'command': command, 'background': True})
        self.assertTrue((await self.call('execute_command', {'command': command, 'background': True})).is_error)
        await self.processes.cancel_run('r')
        with patch.dict(os.environ, {'TEST_PRIVATE_API_KEY': 'must-not-leak'}):
            command = 'Write-Output $env:TEST_PRIVATE_API_KEY' if os.name == 'nt' else "printf '%s' \"$TEST_PRIVATE_API_KEY\""
            result = await self.success('execute_command', {'command': command})
        self.assertNotIn('must-not-leak', result['output'])

    async def test_timeout_kills_real_descendant_before_late_file_write(self):
        """命令实际创建子进程；超时后后代不能继续写迟到文件。"""
        child_script = self.root / 'late_child.py'
        child_script.write_text("import time\nfrom pathlib import Path\nPath('started.txt').write_text('yes')\ntime.sleep(1)\nPath('late.txt').write_text('unexpected')\n", encoding='utf-8')
        parent_script = self.root / 'parent.py'
        parent_script.write_text('import subprocess,sys\np=subprocess.Popen([sys.executable,"late_child.py"])\np.wait()\n', encoding='utf-8')
        if os.name == 'nt':
            command = "& '" + sys.executable.replace("'", "''") + "' parent.py"
        else:
            import shlex
            command = shlex.quote(sys.executable) + ' parent.py'
        result = await self.call('execute_command', {'command': command, 'background': True, 'timeout_seconds': 0.6})
        self.assertFalse(result.is_error, result.content)
        job = self.processes.jobs[json.loads(result.content)['process_id']]
        await job.task
        self.assertTrue((self.root / 'started.txt').exists(), '测试必须证明后代已启动')
        self.assertEqual(job.state, 'timed_out')
        await asyncio.sleep(0.8)
        self.assertFalse((self.root / 'late.txt').exists())

    async def test_completed_background_can_be_queried_in_later_run(self):
        """同会话下一 Run 能读完成结果，其他身份或切换根后看不到。"""
        command = "Write-Output 'background done'" if os.name == 'nt' else 'echo background done'
        result = await self.success('execute_command', {'command': command, 'background': True})
        await self.processes.jobs[result['process_id']].task
        later = dataclasses.replace(self.context, run_id='next-run')
        status = await self.success('process_status', {'process_id': result['process_id']}, context=later)
        self.assertEqual(status['status'], 'completed')
        self.assertIn('background done', status['output'])
        for context in (dataclasses.replace(later, user_id='other'), dataclasses.replace(later, agent_id='other'),
                        dataclasses.replace(later, workspace=str(self.base))):
            self.assertTrue((await self.call('process_status', {'process_id': result['process_id']}, context=context)).is_error)

    async def test_packaged_backend_never_recursively_launches_itself(self):
        """打包环境缺少外部 Python 时明确失败，不把服务 exe 当解释器启动。"""
        with patch.object(sys, 'frozen', True, create=True), patch.object(self.processes, 'argv', return_value=['unused']), patch('yanagent.tools.processes.shutil.which', return_value=None):
            result = await self.call('execute_command', {'command': 'echo test'})
        self.assertTrue(result.is_error)
        self.assertIn('Python', result.content)
        self.assertEqual(self.processes.jobs, {})


class FileToolRuntimeTests(unittest.TestCase):
    """通过真实常驻 Runtime 和 SQLite 验证工具确认及操作记录。"""

    def setUp(self):
        """创建无网络的应用，注册生产默认文件工具。"""
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.database = Database(data_dir=self.root / 'data', environ={})
        self.sessions = SessionStore(self.database, user_id='local', agent_id='default')
        self.runs = RunStore(self.database, user_id='local', agent_id='default')
        config = ConfigStore(self.root / 'config.json', environ={})
        config.save({'api_base': 'https://example.invalid/v1', 'api_key': 'fake', 'model': 'fake', 'permission_mode': 'allow'})
        call = ToolCall('write-1', 'write_file', {'path': '你好.txt', 'content': '你好word'})
        replies = [ModelReply(content='', tool_calls=[call], finish_reason='tool_calls'), ModelReply(content='文件已创建', finish_reason='stop')]
        self.provider = FakeProvider(replies, stream_outcomes=[
            ([ModelStreamEvent(kind='text_delta', content=reply.content)] if reply.content else [])
            + [ModelStreamEvent(kind='completed', reply=reply)] for reply in replies
        ])
        self.app = YanAgentApplication(config, provider_factory=lambda _: self.provider, session_store=self.sessions, run_store=self.runs)
        self.runtime = AgentRuntime(self.app)

    def tearDown(self):
        """关闭 Runtime 后清除临时数据库和文件。"""
        self.runtime.close()
        self.temp.cleanup()

    def collect(self, run_id, *, approve):
        """消费真实流事件，在确认事件处明确提交模拟用户决定。"""
        cursor, events = 0, []
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            batch, terminal = self.runtime.wait_events(run_id, cursor, timeout=0.1)
            cursor += len(batch)
            for event in batch:
                item = event.to_dict()
                events.append(item)
                if item['type'] == 'confirmation_required':
                    self.assertEqual(item['arguments']['content'], '你好word')
                    self.assertEqual(item['workspace'], str(self.app.workspaces.root('s')))
                    self.assertFalse((self.app.workspaces.root('s') / '你好.txt').exists())
                    self.assertTrue(self.runtime.resolve_tool_confirmation(confirmation_id=item['confirmation_id'], run_id=run_id, approved=approve))
            if terminal:
                return events
        self.fail('等待文件工具流式终态超时')

    def test_stream_approval_creates_file_and_persists_operation(self):
        """模型请求→参数确认→真实文件→Tool Result→最终正文全部走生产链路。"""
        self.runtime.start_stream({'session_id': 's', 'message': '创建你好文本'}, request_id='write-run')
        events = self.collect('write-run', approve=True)
        self.assertEqual((self.app.workspaces.root('s') / '你好.txt').read_text(encoding='utf-8'), '你好word')
        self.assertEqual(events[-1]['type'], 'done')
        history = self.runtime.execute(self.sessions.complete_history('s'))
        self.assertEqual([item.message.role for item in history], ['user', 'assistant', 'tool', 'assistant'])
        steps = self.runtime.execute(self.app.executions.list_steps('s', 'write-run'))
        tool = next(step for step in steps if step['kind'] == 'tool')
        self.assertEqual(tool['status'], 'completed')
        self.assertEqual(tool['data']['call']['name'], 'write_file')
        self.assertEqual(json.loads(history[2].message.content)['created'], True)

    def test_rejection_is_saved_without_creating_file(self):
        """用户拒绝后保存失败结果，模型能据此继续，但文件没有创建。"""
        self.runtime.start_stream({'session_id': 's', 'message': '创建你好文本'}, request_id='reject-run')
        events = self.collect('reject-run', approve=False)
        self.assertFalse((self.app.workspaces.root('s') / '你好.txt').exists())
        self.assertTrue(any(event['type'] == 'tool_end' and event['status'] == 'error' for event in events))

    def test_old_capability_claim_does_not_replace_current_schema(self):
        """旧回复与摘要保留为历史，当前系统能力及 HTTP 工具字段仍含实际文件工具。"""
        prepared = self.app.prepare_chat({'session_id': 's', 'message': '读取 test.txt 的内容'})
        old_claim = '本轮只有 calculator 和 current_time，不能读取文件。'
        context = PromptContextBuilder().build(
            identity=RuntimeIdentity('local', 'default', 's', 'current-run', workspace_root=prepared.workspace_root),
            history=[Message('user', '读一下 test.txt'), Message('assistant', old_claim)],
            current=prepared.message, tools=self.app.tool_manager.schemas(), memory_summary=old_claim,
        )
        system = context.messages[0].content
        self.assertIn('历史回答、较早摘要', system)
        self.assertIn('本轮已提供 read_file', system)
        self.assertIn('应先提交 read_file 请求', system)
        self.assertEqual(context.messages[2].content, old_claim)
        converted, schemas = prepare_request(context.messages, context.tools)
        self.assertEqual(converted[0]['role'], 'system')
        self.assertEqual(converted[-1]['content'], '读取 test.txt 的内容')
        self.assertEqual(len(schemas), 10)
        self.assertIn('read_file', [schema['function']['name'] for schema in schemas])
        self.assertIn('write_file', [schema['function']['name'] for schema in schemas])
        empty = PromptContextBuilder().build(identity=RuntimeIdentity('local', 'default', 's', 'empty-run'),
            history=[], current=Message('user', '读取 test.txt'))
        self.assertNotIn('本轮已提供 read_file', empty.messages[0].content)
        self.assertEqual(empty.tools, ())

    def test_runtime_close_reaps_background_after_successful_run(self):
        """成功回答后后台仍可运行；关闭 Runtime 必须终止，不能留下服务。"""
        async def launch():
            """在所属事件循环通过真实权限入口启动测试命令。"""
            prepared = self.app.prepare_chat({'session_id': 's', 'message': '运行后台'})
            context = self.app.tool_permission_context(prepared, request_id='background-run', confirmation_ui_available=True)
            async def confirm(request):
                """明确批准本用例有限后台命令。"""
                return ToolConfirmationResult(request.request_id, 'approved')
            return await self.app.tool_manager.execute(ToolCall('bg', 'execute_command', {
                'command': 'Start-Sleep -Seconds 30' if os.name == 'nt' else 'sleep 30', 'background': True,
            }), permission_mode='allow', permission_context=context, confirmation_handler=confirm)
        result = self.runtime.execute(launch())
        self.assertFalse(result.is_error, result.content)
        job = self.app.process_service.jobs[json.loads(result.content)['process_id']]
        self.assertIsNone(job.process.poll())
        self.runtime.close()
        self.assertIsNotNone(job.process.poll())
        self.assertFalse(self.runtime._thread.is_alive())


if __name__ == '__main__':
    unittest.main()
