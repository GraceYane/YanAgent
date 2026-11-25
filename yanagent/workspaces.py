"""工作区项目持久化及桌面文件服务；不注册或执行模型文件工具。"""

import hashlib
import hmac
import json
import logging
import math
import os
import stat
import threading
import time
import uuid
import sqlite3
from functools import wraps
from pathlib import Path
from urllib.parse import urlencode

from yanagent.workspace_paths import WorkspaceError, WorkspacePreviewAccessError, clean_absolute, within, locked_path, safe_stat, make_directories
from yanagent.sessions.store import _identifier


LOGGER = logging.getLogger('yanagent.workspaces')
FILE_LOCK = threading.RLock()
MAX_TEXT_BYTES = 512 * 1024
IGNORED = {'.git', '.venv', 'node_modules', '__pycache__'}
TEXT_SUFFIXES = {'.txt', '.log', '.md', '.markdown', '.py', '.js', '.jsx', '.ts', '.tsx', '.json',
                 '.toml', '.yaml', '.yml', '.ini', '.cfg', '.conf', '.css', '.scss', '.html', '.xml',
                 '.csv', '.tsv', '.sql', '.sh', '.ps1', '.bat', '.rs', '.go', '.java', '.c', '.cpp', '.h'}


def workspace_errors(function):
    """将系统/仓储异常收敛成受控错误，不把原路径和异常正文发给客户端。"""
    @wraps(function)
    def wrapped(*args, **kwargs):
        """执行有限工作区操作，记录异常类型而不记录文件正文。"""
        try:
            with args[0]._lock:
                return function(*args, **kwargs)
        except (OSError, sqlite3.Error, ValueError, TypeError):
            LOGGER.warning('[workspaces.py][%s] 工作区操作未完成，底层访问或参数无效', function.__qualname__)
            raise WorkspaceError() from None
    return wrapped


class WorkspaceBusyError(WorkspaceError):
    """运行或排队期间不允许改变会话的项目归属。"""

    code = 'workspace_busy'
    message = '当前会话仍有运行或排队任务，请结束任务后切换工作区。'


def _name(value):
    """校验项目名称为单个普通目录名，禁止路径、控制字符和保留设备名。"""
    if type(value) is not str or not value.strip() or value != value.strip() or len(value) > 100 or '/' in value or '\\' in value:
        raise WorkspaceError()
    clean_absolute(str(Path.cwd() / value))
    if value in {'.', '..'}:
        raise WorkspaceError()
    return value


class WorkspaceService:
    """按完整用户/Agent/Session 作用域管理项目授权和有限文本访问。"""

    def __init__(self, sessions):
        """绑定同一 SQLite 仓储；默认目录独立于 CowAgent 且不在初始化时创建。"""
        self.sessions, self.database = sessions, sessions.database
        self.owner = (sessions.user_id, sessions.agent_id)
        scope = hashlib.sha256(json.dumps(self.owner).encode()).hexdigest()[:24]
        self.base = self.database.data_dir / 'workspaces' / scope
        self.default_root, self.projects_root = self.base / 'default', self.base / 'projects'
        self._lock = threading.RLock()
        self.access_token = os.urandom(32).hex()

    def preview_token(self, session, path, expires):
        """为单个会话根内文件生成短期只读凭证，换项目后旧链接自动失效。"""
        message = json.dumps([self.owner, session or '', str(self.root(session)), path, expires], ensure_ascii=False)
        return hmac.new(self.access_token.encode(), message.encode(), hashlib.sha256).hexdigest()

    @workspace_errors
    def preview(self, session, path, expires, token):
        """在同一关联锁内核验只读凭证并读取，避免换项目时读到另一根的同名文件。"""
        if expires is None or not time.time() < expires <= time.time() + 3605 or not hmac.compare_digest(token, self.preview_token(session, path, expires)):
            raise WorkspacePreviewAccessError()
        return self.read(session, path)

    def _rows(self, conn):
        """只读取当前用户和 Agent 的项目授权及排序。"""
        return conn.execute('SELECT * FROM workspace_projects WHERE user_id=? AND agent_id=? ORDER BY sort_order,used_at DESC', self.owner).fetchall()

    @workspace_errors
    def root(self, session):
        """读取会话项目根；空或尚未创建的会话仅能访问当前身份的默认目录。"""
        if session:
            session = _identifier(session)
            with self.database.connection() as conn:
                row = conn.execute('SELECT metadata_json FROM sessions WHERE user_id=? AND agent_id=? AND session_id=?', (*self.owner, session)).fetchone()
                project = json.loads(row['metadata_json']).get('workspace_project') if row else None
                if project:
                    grant = conn.execute('SELECT path FROM workspace_projects WHERE user_id=? AND agent_id=? AND path=?', (*self.owner, project['path'])).fetchone()
                    if grant is None:
                        raise WorkspaceError()
                    return clean_absolute(grant['path'])
        return self.default_root

    @workspace_errors
    def state(self, session):
        """返回选择器状态，不自动探测或枚举未授权的电脑目录。"""
        selected = self.root(session)
        with self.database.connection() as conn:
            rows = self._rows(conn)
        recents = [{'path': row['path'], 'name': row['name'], 'ts': row['used_at'] / 1000} for row in rows]
        current = next((item for item in recents if item['path'] == str(selected)), None)
        return {'status': 'success', 'current': current, 'recents': recents,
                'default_workspace': str(self.default_root), 'projects_root': str(self.projects_root)}

    def _ensure_idle(self, conn, session):
        """在项目变更事务内检查任务状态，避免执行中换到另一目录。"""
        if conn.execute("SELECT 1 FROM runs WHERE user_id=? AND agent_id=? AND session_id=? AND status IN ('queued','running') LIMIT 1",
                        (*self.owner, session)).fetchone():
            raise WorkspaceBusyError()

    @workspace_errors
    def select(self, session, project_dir):
        """显式选择目录即授予当前身份的项目访问权；清空只解除此会话关联。"""
        session = _identifier(session)
        selected = None if project_dir is None else clean_absolute(project_dir)
        if selected is not None:
            if selected == Path(selected.anchor):
                raise WorkspaceError()
            with locked_path(selected, directory=True):
                selected = clean_absolute(os.path.realpath(selected))
        now = int(time.time() * 1000)
        with self._lock, self.database.transaction(immediate=True) as conn:
            self._ensure_idle(conn, session)
            conn.execute('INSERT OR IGNORE INTO sessions(user_id,agent_id,session_id,title,created_at,updated_at) VALUES(?,?,?,?,?,?)',
                         (*self.owner, session, '', now, now))
            row = conn.execute('SELECT metadata_json FROM sessions WHERE user_id=? AND agent_id=? AND session_id=?', (*self.owner, session)).fetchone()
            metadata = json.loads(row['metadata_json'])
            if selected is None:
                metadata.pop('workspace_project', None)
            else:
                if len(self._rows(conn)) >= 200 and not conn.execute('SELECT 1 FROM workspace_projects WHERE user_id=? AND agent_id=? AND path=?', (*self.owner, str(selected))).fetchone():
                    raise WorkspaceError()
                conn.execute('''INSERT INTO workspace_projects(user_id,agent_id,path,name,used_at) VALUES(?,?,?,?,?)
                    ON CONFLICT(user_id,agent_id,path) DO UPDATE SET used_at=excluded.used_at''', (*self.owner, str(selected), selected.name, now))
                name = conn.execute('SELECT name FROM workspace_projects WHERE user_id=? AND agent_id=? AND path=?', (*self.owner, str(selected))).fetchone()['name']
                metadata['workspace_project'] = {'path': str(selected), 'name': name}
            conn.execute('UPDATE sessions SET metadata_json=?,updated_at=? WHERE user_id=? AND agent_id=? AND session_id=?',
                         (json.dumps(metadata, ensure_ascii=False), now, *self.owner, session))
        LOGGER.info('[workspaces.py][WorkspaceService.select] 会话工作区已选择，user=%s，agent=%s，session=%s，使用默认=%s', *self.owner, session, selected is None)
        return self.state(session)

    @workspace_errors
    def create(self, session, name):
        """仅在当前身份托管 projects 目录创建新项目，不覆盖已有目录。"""
        name = _name(name)
        _identifier(session)
        with self.database.connection() as conn:
            self._ensure_idle(conn, session)
        with self._lock:
            make_directories(self.projects_root)
            target = self.projects_root / name
            with locked_path(self.projects_root, directory=True) as fd:
                try:
                    os.mkdir(target if os.name == 'nt' else name, **({} if os.name == 'nt' else {'dir_fd': fd}))
                except OSError:
                    raise WorkspaceError() from None
            try:
                result = self.select(session, str(target))
            except BaseException:
                # 只回收本次新建的空目录；不递归删除，外部已写入内容时保留并记录。
                with locked_path(self.projects_root, directory=True) as fd:
                    try:
                        if os.name == 'nt':
                            target.rmdir()
                        else:
                            os.rmdir(name, dir_fd=fd)
                    except OSError:
                        LOGGER.warning('[workspaces.py][WorkspaceService.create] 新建关联失败，空目录未能回收')
                raise
            return {**result, 'path': str(target)}

    @workspace_errors
    def manage(self, action, path=None, name=None, order=None):
        """维护项目显示名/排序/记录；移除仅解除关联，从不删除磁盘内容。"""
        with self._lock, self.database.transaction(immediate=True) as conn:
            rows = self._rows(conn)
            known = {row['path'] for row in rows}
            if action == 'order':
                if type(order) is not list or any(type(item) is not str for item in order) or len(set(order)) != len(order):
                    raise WorkspaceError()
                # 默认分组是 UI 排序占位，不是可访问目录。
                if set(order) - known - {'__default__'}:
                    raise WorkspaceError()
                for index, item in enumerate(order):
                    conn.execute('UPDATE workspace_projects SET sort_order=? WHERE user_id=? AND agent_id=? AND path=?', (index, *self.owner, item))
            else:
                if type(path) is not str or path not in known:
                    raise WorkspaceError()
                selected_name = _name(name) if action == 'rename' else None
                sessions = conn.execute('SELECT session_id,metadata_json FROM sessions WHERE user_id=? AND agent_id=?', self.owner).fetchall()
                for row in sessions:
                    metadata = json.loads(row['metadata_json'])
                    if metadata.get('workspace_project', {}).get('path') != path:
                        continue
                    self._ensure_idle(conn, row['session_id'])
                    if action == 'rename':
                        metadata['workspace_project']['name'] = selected_name
                    else:
                        metadata.pop('workspace_project', None)
                    conn.execute('UPDATE sessions SET metadata_json=? WHERE user_id=? AND agent_id=? AND session_id=?', (json.dumps(metadata), *self.owner, row['session_id']))
                if action == 'rename':
                    conn.execute('UPDATE workspace_projects SET name=? WHERE user_id=? AND agent_id=? AND path=?', (selected_name, *self.owner, path))
                elif action == 'delete':
                    conn.execute('DELETE FROM workspace_projects WHERE user_id=? AND agent_id=? AND path=?', (*self.owner, path))
                else:
                    raise WorkspaceError()
        return {'status': 'success'}

    def _target(self, session, value):
        """统一解析相对和绝对文件名，所有入口共享当前会话边界。"""
        root = self.root(session)
        if root == self.default_root:
            make_directories(root)
        return root, within(root, value)

    def _entry(self, root, path, session):
        """生成有限元数据和受会话约束的预览地址，不暴露任意文件读取入口。"""
        clean_absolute(str(path))
        info = safe_stat(path)
        relative = path.relative_to(root).as_posix()
        if relative == '.':
            relative = ''
        directory = stat.S_ISDIR(info.st_mode)
        kind = ('directory' if directory else 'markdown' if path.suffix.lower() in {'.md', '.markdown'} else
                'csv' if path.suffix.lower() in {'.csv', '.tsv'} else 'text' if path.suffix.lower() in {'.txt', '.log'} else
                'code' if path.suffix.lower() in TEXT_SUFFIXES or not path.suffix else 'file')
        expires = int(time.time()) + 3600
        url = '/api/workspace/preview?' + urlencode({'session': session or '', 'path': relative, 'expires': expires,
                                                   'token': self.preview_token(session, relative, expires)})
        return {'name': path.name, 'path': relative, 'abs_path': str(path), 'is_dir': directory, 'kind': kind,
                'previewable': not directory and kind != 'file', 'size': info.st_size, 'mtime': info.st_mtime_ns // 1_000_000,
                'preview_url': url if not directory and kind != 'file' else '', 'raw_url': ''}

    @workspace_errors
    def tree(self, session, path=''):
        """只列当前一级，隐藏链接和大型依赖目录，限制最多五百项。"""
        root, target = self._target(session, path)
        entries, truncated = [], False
        with locked_path(target, directory=True) as fd:
            with os.scandir(target if os.name == 'nt' else fd) as listing:
                for item in listing:
                    if item.name in IGNORED:
                        continue
                    try:
                        entries.append(self._entry(root, target / item.name, session))
                    except (WorkspaceError, OSError):
                        continue
                    if len(entries) >= 500:
                        truncated = True
                        break
        entries.sort(key=lambda item: (not item['is_dir'], item['name'].casefold()))
        relative = target.relative_to(root).as_posix()
        return {'status': 'success', 'path': '' if relative == '.' else relative, 'root': str(root), 'entries': entries, 'truncated': truncated}

    @workspace_errors
    def search(self, session, query, limit=30):
        """按文件名查找，不读取内容；限制遍历条数、深度、耗时与返回数量。"""
        if type(query) is not str or not query.strip() or len(query) > 256 or type(limit) is not int or not 1 <= limit <= 100:
            raise WorkspaceError()
        pending, results, visited, deadline = [('', 0)], [], 0, time.monotonic() + 2
        while pending and visited < 3000 and time.monotonic() < deadline:
            directory, depth = pending.pop()
            for item in self.tree(session, directory)['entries']:
                visited += 1
                if query.casefold() in item['name'].casefold():
                    results.append(item)
                    if len(results) >= limit:
                        return {'status': 'success', 'results': results, 'truncated': True}
                if item['is_dir'] and depth < 8:
                    pending.append((item['path'], depth + 1))
        return {'status': 'success', 'results': results, 'truncated': bool(pending)}

    @workspace_errors
    def resolve(self, session, path):
        """只解析当前会话根内的已存在对象，所有组件均拒绝链接。"""
        root, target = self._target(session, path)
        info = safe_stat(target)
        with locked_path(target, directory=stat.S_ISDIR(info.st_mode)):
            return {'status': 'success', 'file': self._entry(root, target, session)}

    @workspace_errors
    def read(self, session, path):
        """读取最多 512 KiB UTF-8 文本，二进制/截断/有损文本禁止编辑。"""
        _, target = self._target(session, path)
        with locked_path(target) as fd:
            info = os.fstat(fd)
            data = os.read(fd, MAX_TEXT_BYTES + 1)
        truncated = len(data) > MAX_TEXT_BYTES
        data = data[:MAX_TEXT_BYTES]
        try:
            content, lossy = data.decode('utf-8'), False
        except UnicodeDecodeError:
            content, lossy = data.decode('utf-8', errors='replace'), True
        editable = not truncated and not lossy and '\x00' not in content
        LOGGER.info('[workspaces.py][WorkspaceService.read] 工作区文本已读取，session=%s，字节=%d，截断=%s，可编辑=%s', session, len(data), truncated, editable)
        return {'status': 'success', 'path': str(target), 'content': content, 'truncated': truncated, 'lossy': lossy,
                'size': info.st_size, 'mtime': info.st_mtime_ns // 1_000_000, 'editable': editable,
                'etag': hashlib.sha256(data).hexdigest()}

    @workspace_errors
    def write(self, session, path, content, expected_mtime, expected_etag=None):
        """用户手动保存已有文本；冲突检测后同目录临时文件原子替换，不执行模型写工具。"""
        if type(content) is not str or '\x00' in content:
            raise WorkspaceError()
        try:
            data = content.encode('utf-8')
        except UnicodeError:
            raise WorkspaceError() from None
        if len(data) > MAX_TEXT_BYTES or (expected_mtime is not None and (type(expected_mtime) not in (int, float) or not math.isfinite(expected_mtime))):
            raise WorkspaceError()
        _, target = self._target(session, path)
        temporary = '.yanagent-edit-' + uuid.uuid4().hex
        with FILE_LOCK, self._lock, locked_path(target.parent, directory=True) as parent_fd:
            previous = self.read(session, path)
            if not previous['editable']:
                raise WorkspaceError()
            if expected_mtime is not None and (previous['mtime'] != expected_mtime or (expected_etag is not None and previous['etag'] != expected_etag)):
                return {'status': 'error', 'code': 'conflict', 'message': '文件已被其他操作修改，请重新加载或确认覆盖。'}
            temporary_path = target.parent / temporary
            kwargs = {} if os.name == 'nt' else {'dir_fd': parent_fd}
            try:
                fd = os.open(temporary_path if os.name == 'nt' else temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, **kwargs)
                with os.fdopen(fd, 'wb') as handle:
                    if os.name != 'nt':
                        os.fchmod(handle.fileno(), safe_stat(target).st_mode & 0o777)
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
                latest = self.read(session, path)
                if (latest['mtime'], latest['etag']) != (previous['mtime'], previous['etag']):
                    return {'status': 'error', 'code': 'conflict', 'message': '保存过程中检测到外部修改，请重新加载。'}
                if os.name == 'nt':
                    os.replace(temporary_path, target)
                else:
                    os.replace(temporary, target.name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
            finally:
                try:
                    os.unlink(temporary_path if os.name == 'nt' else temporary, **kwargs)
                except FileNotFoundError:
                    pass
            result = self.read(session, path)
        LOGGER.info('[workspaces.py][WorkspaceService.write] 用户手动保存完成，session=%s，字节=%d', session, len(data))
        return {key: result[key] for key in ('status', 'path', 'size', 'mtime', 'etag')}
