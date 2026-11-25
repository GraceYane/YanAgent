"""P06-03 工作区真实文件、作用域、链接边界、冲突及本机 HTTP 验收。"""

import asyncio
import concurrent.futures
import json
import os
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from app import create_server
from yanagent.chat import YanAgentApplication
from yanagent.config import ConfigStore
from yanagent.contracts import Message, ModelReply
from yanagent.models import FakeProvider
from yanagent.sessions import SessionStore, RunStore, DesktopSessionService
from yanagent.storage import Database, CURRENT_SCHEMA_VERSION
import yanagent.storage.database as database_module
from yanagent.workspaces import WorkspaceService, WorkspaceBusyError, MAX_TEXT_BYTES
from yanagent.workspace_paths import WorkspaceError, locked_path, clean_absolute


class WorkspaceTests(unittest.TestCase):
    """用真实临时文件验证边界，不读写用户的项目。"""

    def setUp(self):
        """创建两个项目、一个根外文件和独立仓储。"""
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.project = self.root / '中文项目 空格'
        self.other = self.root / '其他项目'
        self.project.mkdir()
        self.other.mkdir()
        self.file = self.project / 'hello.txt'
        self.file.write_text('中文第一版', encoding='utf-8')
        (self.other / 'secret.txt').write_text('根外内容', encoding='utf-8')
        self.database = Database(data_dir=self.root / 'data', environ={})
        self.sessions = SessionStore(self.database, user_id='u', agent_id='a')
        self.service = WorkspaceService(self.sessions)
        self.service.select('s', str(self.project))

    def tearDown(self):
        """清理临时目录；链接测试提前移除链接本身。"""
        self.temporary.cleanup()

    def test_select_create_default_and_restart_persistence(self):
        """项目关联持久化，默认目录与托管项目独立于原参考工程。"""
        reopened = WorkspaceService(SessionStore(Database(data_dir=self.root / 'data', environ={}), user_id='u', agent_id='a'))
        self.assertEqual(reopened.root('s'), self.project)
        created = reopened.create('new', '新项目')
        self.assertTrue(Path(created['current']['path']).is_dir())
        self.assertEqual(Path(created['current']['path']).parent, reopened.projects_root)
        self.assertIsNone(reopened.select('s', None)['current'])
        self.assertEqual(reopened.tree('s')['root'], str(reopened.default_root))

    def test_complete_owner_and_session_boundaries(self):
        """同名会话在不同身份中没有项目授权，另一会话也不能读取未选择根。"""
        for user, agent in (('another', 'a'), ('u', 'another')):
            other = WorkspaceService(SessionStore(self.database, user_id=user, agent_id=agent))
            self.assertEqual(other.state('s')['recents'], [])
            self.assertNotEqual(other.default_root, self.service.default_root)
            with self.assertRaises(WorkspaceError):
                other.read('s', str(self.file))
        with self.assertRaises(WorkspaceError):
            self.service.read('unselected', str(self.file))

    def test_unicode_tree_search_resolve_and_manual_edit(self):
        """已有目录界面契约支持中文路径、文件树、文件名搜索和手动原子编辑。"""
        entry = self.service.tree('s')['entries'][0]
        self.assertEqual(entry['path'], 'hello.txt')
        self.assertIn('token=', entry['preview_url'])
        self.assertEqual(len(self.service.search('s', 'HELLO')['results']), 1)
        self.assertEqual(self.service.resolve('s', str(self.file))['file']['abs_path'], str(self.file))
        original = self.service.read('s', 'hello.txt')
        self.assertLess(original['mtime'], 2 ** 53)
        result = self.service.write('s', 'hello.txt', '保存后的中文\n第二行', original['mtime'], original['etag'])
        self.assertEqual(result['status'], 'success')
        self.assertEqual(self.file.read_text(encoding='utf-8'), '保存后的中文\n第二行')

    def test_traversal_sibling_absolute_drive_and_device_paths_are_rejected(self):
        """相对父级、同前缀目录、其他绝对根和 Windows 特殊路径不放行。"""
        bad = ['../其他项目/secret.txt', '..\\其他项目\\secret.txt', str(self.other / 'secret.txt')]
        if os.name == 'nt':
            bad += ['C:hello.txt', '\\Windows\\win.ini', '\\\\?\\C:\\Windows\\win.ini',
                    '\\\\server\\share\\file', 'hello.txt:secret', 'CON', 'foo.']
        for value in bad:
            with self.subTest(path=value), self.assertRaises(WorkspaceError):
                self.service.read('s', value)

    def test_create_rejects_invalid_names_and_existing_directory(self):
        """托管新建不接受路径输入、不覆盖已有项目。"""
        for name in ('', '../escape', '..', 'x/y', 'x\\y', 'bad\nname'):
            with self.assertRaises(WorkspaceError):
                self.service.create('s', name)
        self.service.create('s', '新建')
        with self.assertRaises(WorkspaceError):
            self.service.create('s', '新建')

    def test_failed_project_binding_removes_only_its_empty_new_directory(self):
        """新建后关联失败仅回收本次空目录，不留下误导性的成功项目。"""
        with patch.object(self.service, 'select', side_effect=WorkspaceBusyError()):
            with self.assertRaises(WorkspaceBusyError):
                self.service.create('s', '失败项目')
        self.assertFalse((self.service.projects_root / '失败项目').exists())

    def test_text_limits_binary_and_lossy_files_cannot_be_edited(self):
        """截断、有损和包含 NUL 的文本不能保存，避免覆盖原始二进制。"""
        for name, content in (('binary.txt', b'hello\x00world'), ('legacy.txt', b'\xff\xfeabc'),
                              ('large.txt', b'x' * (MAX_TEXT_BYTES + 1))):
            (self.project / name).write_bytes(content)
            read = self.service.read('s', name)
            self.assertFalse(read['editable'])
            with self.assertRaises(WorkspaceError):
                self.service.write('s', name, '新内容', read['mtime'])
            self.assertEqual((self.project / name).read_bytes(), content)
        self.assertFalse(self.service.resolve('s', 'binary.txt')['file']['raw_url'])

    def test_conflict_uses_hash_even_when_mtime_is_unchanged(self):
        """纳秒时间戳不能安全传给 JS，毫秒版本另配内容哈希防止同时间改写。"""
        old = self.service.read('s', 'hello.txt')
        timestamp = self.file.stat().st_mtime_ns
        self.file.write_text('外部编辑', encoding='utf-8')
        os.utime(self.file, ns=(timestamp, timestamp))
        result = self.service.write('s', 'hello.txt', '不应覆盖', old['mtime'], old['etag'])
        self.assertEqual(result['code'], 'conflict')
        self.assertEqual(self.file.read_text(encoding='utf-8'), '外部编辑')
        self.assertEqual(self.service.write('s', 'hello.txt', '用户明确覆盖', None)['status'], 'success')

    def test_failed_replace_keeps_original_and_cleans_temporary_file(self):
        """原子替换失败保留原文并回收本次临时文件。"""
        old = self.service.read('s', 'hello.txt')
        with patch('yanagent.workspaces.os.replace', side_effect=OSError('模拟失败')):
            with self.assertRaises(WorkspaceError):
                self.service.write('s', 'hello.txt', '不应写入', old['mtime'], old['etag'])
        self.assertEqual(self.file.read_text(encoding='utf-8'), '中文第一版')
        self.assertEqual(list(self.project.glob('.yanagent-edit-*')), [])

    def test_concurrent_services_only_one_edit_wins(self):
        """同进程不同服务写同一文件共用锁，第二份旧版本不能覆盖第一份。"""
        second = WorkspaceService(self.sessions)
        old = self.service.read('s', 'hello.txt')
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(svc.write, 's', 'hello.txt', text, old['mtime'], old['etag'])
                       for svc, text in ((self.service, '甲'), (second, '乙'))]
            results = [f.result() for f in futures]
        self.assertEqual(sorted(item['status'] for item in results), ['error', 'success'])

    def test_hardlinks_are_rejected_for_read_and_forced_write(self):
        """根内文件硬链接到根外时，读和强制写都拒绝。"""
        alias = self.project / 'alias.txt'
        os.link(self.other / 'secret.txt', alias)
        for operation in (lambda: self.service.read('s', 'alias.txt'), lambda: self.service.write('s', 'alias.txt', '不可写', None)):
            with self.assertRaises(WorkspaceError):
                operation()
        self.assertEqual((self.other / 'secret.txt').read_text(encoding='utf-8'), '根外内容')

    def test_symlink_or_windows_junction_never_crosses_root(self):
        """真实 Windows Junction 或 POSIX 目录链接不能成为项目根或子目录。"""
        link = self.project / 'escape'
        if os.name == 'nt':
            env = dict(os.environ, YAN_TEST_LINK=str(link), YAN_TEST_TARGET=str(self.other))
            result = subprocess.run(['powershell', '-NoProfile', '-Command',
                'New-Item -ItemType Junction -Path $env:YAN_TEST_LINK -Target $env:YAN_TEST_TARGET | Out-Null'], env=env, capture_output=True)
            self.assertEqual(result.returncode, 0)
        else:
            link.symlink_to(self.other, target_is_directory=True)
        try:
            for operation in (lambda: self.service.read('s', 'escape/secret.txt'), lambda: self.service.select('other', str(link)),
                              lambda: self.service.write('s', 'escape/secret.txt', '不可写', None)):
                with self.assertRaises(WorkspaceError):
                    operation()
            self.assertNotIn('escape', [item['name'] for item in self.service.tree('s')['entries']])
        finally:
            os.rmdir(link) if os.name == 'nt' else link.unlink()

    def test_pinned_windows_parent_cannot_be_replaced(self):
        """Windows 读取期间父目录句柄不共享删除，改名替换应失败。"""
        if os.name != 'nt':
            self.skipTest('Windows 句柄共享语义专项')
        with locked_path(self.file):
            with self.assertRaises(OSError):
                self.project.rename(self.root / 'moved')

    def test_busy_session_cannot_switch_or_remove_project(self):
        """排队和执行状态阻止换项目及移除关联。"""
        runs = RunStore(self.database, user_id='u', agent_id='a')
        asyncio.run(runs.create('busy', 's', status='queued'))
        with self.assertRaises(WorkspaceBusyError):
            self.service.select('s', str(self.other))
        with self.assertRaises(WorkspaceBusyError):
            self.service.manage('delete', str(self.project))
        self.assertEqual(self.service.root('s'), self.project)

    def test_manage_changes_records_only_and_preserves_other_metadata(self):
        """项目改名/移除不会动磁盘文件，也不会抹掉模型或摘要元数据。"""
        asyncio.run(self.sessions.update_model_settings('s', {'model': 'example', 'provider': 'deepseek'}))
        self.service.manage('rename', str(self.project), '显示名称')
        self.assertEqual(self.service.state('s')['current']['name'], '显示名称')
        self.service.manage('order', order=['__default__', str(self.project)])
        self.service.manage('delete', str(self.project))
        self.assertTrue(self.file.exists())
        self.assertIsNone(self.service.state('s')['current'])
        self.assertEqual(asyncio.run(self.sessions.get('s')).metadata['model_settings']['model'], 'example')

    def test_project_snapshot_prompt_and_session_grouping(self):
        """模型得到受信项目路径而非文件内容；列表按项目分组且任务快照固定。"""
        store = ConfigStore(self.root / 'config.json', environ={})
        store.save({'api_key': 'fixture', 'api_base': 'https://example.invalid', 'model': 'fixture'})
        fake = FakeProvider([ModelReply(content='未读取文件')])
        app = YanAgentApplication(store, session_store=self.sessions, provider_factory=lambda _: fake)
        prepared = app.prepare_chat({'session_id': 's', 'message': '当前工作区'})
        app.workspaces.select('s', str(self.other))
        self.assertEqual(prepared.workspace_root, str(self.project))
        asyncio.run(app.chat({'session_id': 's', 'message': '当前工作区'}, prepared=prepared))
        self.assertIn(str(self.project).replace('\\', '\\\\'), fake.calls[0].messages[0].content)
        self.assertNotIn('中文第一版', fake.calls[0].messages[0].content)
        self.service.select('default', None)
        page = asyncio.run(DesktopSessionService(self.sessions).list_sessions(page=1, page_size=50))
        self.assertEqual(page['group_mode'], 'project')
        self.assertTrue(any(item['project'] for item in page['sessions']))

    def test_v3_migration_preserves_messages_and_steps(self):
        """真实 v3 数据库升级至 v4，已有会话/消息和执行日志不被重建。"""
        legacy_dir = self.root / 'legacy'
        with patch.object(database_module, 'CURRENT_SCHEMA_VERSION', 3), patch.object(database_module, 'MIGRATIONS', database_module.MIGRATIONS[:3]), patch.object(
            database_module, 'REQUIRED_COLUMNS', {key: value for key, value in database_module.REQUIRED_COLUMNS.items() if key != 'workspace_projects'}):
            old = Database(data_dir=legacy_dir, environ={})
            sessions = SessionStore(old, user_id='u', agent_id='a')
            asyncio.run(sessions.create('old'))
            asyncio.run(sessions.append('old', [Message('user', '历史消息')]))
        upgraded = Database(data_dir=legacy_dir, environ={})
        self.assertEqual(upgraded.initialize().schema_version, CURRENT_SCHEMA_VERSION)
        restored = SessionStore(upgraded, user_id='u', agent_id='a')
        self.assertEqual(asyncio.run(restored.complete_history('old'))[0].message.content, '历史消息')
        with upgraded.connection() as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM workspace_projects').fetchone()[0], 0)
            self.assertEqual(conn.execute('SELECT count(*) FROM run_steps').fetchone()[0], 0)

    def test_tree_cap_and_dependency_pruning(self):
        """文件树不因大型目录无限扫描，并剪掉依赖和 Git 目录。"""
        (self.project / '.git').mkdir()
        for index in range(505):
            (self.project / f'file-{index}.txt').write_text('x')
        listing = self.service.tree('s')
        self.assertEqual(len(listing['entries']), 500)
        self.assertTrue(listing['truncated'])
        self.assertNotIn('.git', [item['name'] for item in listing['entries']])


class WorkspaceHttpTests(unittest.TestCase):
    """验证桌面真实 URL、进程凭证和短期预览链接。"""

    def setUp(self):
        """启动随机本机端口与隔离数据库，捕获所有实际文件操作。"""
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.project = self.root / 'project'
        self.project.mkdir()
        (self.project / 'file.txt').write_text('文件内容', encoding='utf-8')
        self.server = create_server('127.0.0.1', 0, config_store=ConfigStore(self.root / 'config.json', environ={}),
            provider_factory=lambda _: FakeProvider([]), database=Database(data_dir=self.root / 'data', environ={}))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_address[1]}'
        status, response = self.request('/api/workspace/access', authenticated=False)
        self.assertEqual(status, 200)
        self.token = response['token']

    def tearDown(self):
        """关闭线程与数据库临时文件。"""
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.temporary.cleanup()

    def request(self, path, payload=None, *, method=None, headers=None, authenticated=True, text=False):
        """模拟主进程及 Renderer 请求，统一读取成功与受控 HTTP 错误。"""
        selected = {'Content-Type': 'application/json', **(headers or {})}
        if authenticated and hasattr(self, 'token'):
            selected['X-YanAgent-Workspace'] = self.token
        req = Request(self.base + path, data=json.dumps(payload).encode() if payload is not None else None,
                      method=method or ('POST' if payload is not None else 'GET'), headers=selected)
        try:
            response = urlopen(req, timeout=5)
        except HTTPError as error:
            response = error
        with response:
            raw = response.read().decode('utf-8')
            return response.status, raw if text else json.loads(raw)

    def test_browser_cannot_bootstrap_or_access_files_without_capability(self):
        """普通网站和 opaque Origin 不得取得桌面进程的文件权限。"""
        for origin in ('https://example.invalid', 'null'):
            self.assertEqual(self.request('/api/workspace/access', headers={'Origin': origin}, authenticated=False)[0], 403)
        self.assertEqual(self.request('/api/workspace/access', headers={'Sec-Fetch-Site': 'none'}, authenticated=False)[0], 403)
        self.assertEqual(self.request('/api/workspace/tree?session=s', authenticated=False)[0], 403)

    def test_renderer_empty_root_path_and_default_session_are_valid(self):
        """使用桌面实际发送的 path= 根目录 URL，不能用省略参数的测试掩盖问题。"""
        status, tree = self.request('/api/workspace/tree?path=&session=s')
        self.assertEqual(status, 200)
        self.assertEqual(tree['path'], '')
        self.assertEqual(self.request('/api/projects?session=')[0], 200)
        status, created = self.request('/api/projects/create', {'session': 'created-via-renderer', 'name': 'x'})
        self.assertEqual(status, 200)
        self.assertEqual(created['current']['name'], 'x')
        self.request('/api/projects/select', {'session': 's', 'project_dir': str(self.project)})
        status, tree = self.request('/api/workspace/tree?path=&session=s')
        self.assertEqual(status, 200)
        self.assertEqual(tree['entries'][0]['name'], 'file.txt')
        self.assertEqual(self.request('/api/workspace/tree?path=&path=&session=s')[0], 400)

    def test_workspace_denial_and_preview_errors_do_not_claim_model_permissions(self):
        """文件凭证缺失/预览过期的说明不能误报为模型账号权限。"""
        status, body = self.request('/api/projects/create', {'session': 's', 'name': 'x'}, authenticated=False)
        self.assertEqual(status, 403)
        self.assertEqual(body['error']['code'], 'workspace_access_denied')
        self.assertNotIn('模型', body['message'])
        self.assertIn('重新启动', body['message'])
        self.request('/api/projects/select', {'session': 's', 'project_dir': str(self.project)})
        _, tree = self.request('/api/workspace/tree?path=&session=s')
        status, body = self.request(tree['entries'][0]['preview_url'] + 'bad', authenticated=False)
        self.assertEqual(status, 403)
        self.assertEqual(body['error']['code'], 'workspace_preview_expired')
        self.assertNotIn('模型', body['message'])

    def test_project_tree_read_edit_and_signed_preview_contract(self):
        """桌面选择项目后可以读写，签名预览只能读取指定会话和文件。"""
        self.assertEqual(self.request('/api/projects/select', {'session': 's', 'project_dir': str(self.project)})[0], 200)
        status, tree = self.request('/api/workspace/tree?session=s')
        self.assertEqual(status, 200)
        preview = tree['entries'][0]['preview_url']
        self.assertEqual(self.request(preview, authenticated=False, text=True), (200, '文件内容'))
        self.assertEqual(self.request(preview.replace('file.txt', 'else.txt'), authenticated=False)[0], 403)
        _, original = self.request('/api/workspace/read?session=s&path=file.txt')
        status, written = self.request('/api/workspace/write', {'session': 's', 'path': 'file.txt', 'content': '更新',
            'expected_mtime': original['mtime'], 'expected_etag': original['etag']})
        self.assertEqual((status, written['status']), (200, 'success'))
        self.request('/api/projects/select', {'session': 's', 'project_dir': None})
        self.assertEqual(self.request(preview, authenticated=False)[0], 403)

    def test_outside_and_foreign_identity_requests_fail_safely(self):
        """当前进程凭证也不能绕过根路径与 Agent 范围。"""
        self.request('/api/projects/select', {'session': 's', 'project_dir': str(self.project)})
        status, result = self.request('/api/workspace/read?session=s&path=../config.json')
        self.assertEqual(status, 400)
        self.assertEqual(result['error']['code'], 'workspace_error')
        self.assertEqual(self.request('/api/projects?session=s&agent_id=other')[0], 400)
        self.assertEqual(self.request('/api/projects/manage', {'path': str(self.project), 'name': '新名字'}, method='PUT')[0], 200)
        self.assertEqual(self.request('/api/projects/manage', {'path': str(self.project)}, method='DELETE')[0], 200)
        self.assertTrue((self.project / 'file.txt').exists())

    def test_node_fetch_bootstrap_matches_desktop_main_process(self):
        """Node 主进程 fetch 可取得凭证，再经请求头调用工作区接口。"""
        script = """(async () => {
          const base = process.argv[1];
          const access = await fetch(base + '/api/workspace/access', {redirect: 'error'});
          const {token} = await access.json();
          const state = await fetch(base + '/api/projects?session=s', {headers: {'X-YanAgent-Workspace': token}});
          console.log(JSON.stringify([access.status, state.status]));
        })().catch(() => process.exit(1));"""
        result = subprocess.run(['node', '-e', script, self.base], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout), [200, 200])
