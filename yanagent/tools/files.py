"""模型文件工具：工作区内有限文本读取、原子写入、精确编辑和字面量搜索。"""

import hashlib
import json
import logging
import os
import stat
import time
import uuid
from pathlib import Path

from yanagent.workspace_paths import within, clean_absolute, locked_path, safe_stat, make_directories, WorkspaceError
from yanagent.workspaces import FILE_LOCK, MAX_TEXT_BYTES, IGNORED
from .execution_context import current_context
from .manager import ToolDefinition, ToolHandlerError


LOGGER = logging.getLogger('yanagent.tools.files')
BINARY_SUFFIXES = {'.docx', '.doc', '.xlsx', '.xls', '.pptx', '.pdf', '.zip', '.png', '.jpg', '.exe', '.dll'}


def json_result(value):
    """在序列化后控制体积，保留合法 JSON 和明确截断标记。"""
    encoded = json.dumps(value, ensure_ascii=False)
    while len(encoded) > 16000:
        value['truncated'] = True
        for key in ('content', 'output', 'entries', 'matches'):
            if value.get(key):
                value[key] = value[key][:len(value[key]) // 2]
        encoded = json.dumps(value, ensure_ascii=False)
    return encoded


def target_path(value=''):
    """从可信快照取根目录，禁止通过模型参数改变授权根。"""
    root = clean_absolute(current_context().workspace)
    make_directories(root)
    return root, within(root, value)


def read_text(target):
    """完整读取有限 UTF-8 文本；拒绝二进制、有损解码和超大文件。"""
    with locked_path(target) as fd:
        data = os.read(fd, MAX_TEXT_BYTES + 1)
    if len(data) > MAX_TEXT_BYTES or b'\x00' in data or target.suffix.lower() in BINARY_SUFFIXES:
        raise ToolHandlerError('只支持不超过 512 KiB 的 UTF-8 文本；该文件不是可编辑文本。')
    try:
        content = data.decode('utf-8')
    except UnicodeDecodeError:
        raise ToolHandlerError('文件不是 UTF-8 文本，请先转换编码。') from None
    return content, hashlib.sha256(data).hexdigest()


def atomic_write(target, content, expected_etag=None, create_parents=False):
    """新建禁止覆盖；修改必须核验旧哈希，固定父目录后原子发布。"""
    data = content.encode('utf-8')
    if len(data) > MAX_TEXT_BYTES or b'\x00' in data or target.suffix.lower() in BINARY_SUFFIXES:
        raise ToolHandlerError('写入仅支持不超过 512 KiB 的 UTF-8 文本，不能把文本伪装为 Word 等二进制格式。')
    with FILE_LOCK:
        if create_parents:
            make_directories(target.parent)
        with locked_path(target.parent, directory=True) as parent_fd:
            exists = os.path.lexists(target)
            mode = 0o600
            if exists:
                _, previous = read_text(target)
                mode = safe_stat(target).st_mode & 0o777
                if not expected_etag or previous != expected_etag:
                    raise ToolHandlerError('文件已存在或已变更；请先 read_file 读取最新 etag，再确认修改。')
            elif expected_etag:
                raise ToolHandlerError('预期修改的文件已不存在，请重新检查。')
            temporary = '.yanagent-tool-' + uuid.uuid4().hex
            temporary_path = target.parent / temporary
            kwargs = {} if os.name == 'nt' else {'dir_fd': parent_fd}
            try:
                fd = os.open(temporary_path if os.name == 'nt' else temporary,
                             os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode, **kwargs)
                with os.fdopen(fd, 'wb') as handle:
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
                if exists:
                    if read_text(target)[1] != previous:
                        raise ToolHandlerError('保存时发现外部修改，本次写入已放弃。')
                    if os.name == 'nt':
                        os.replace(temporary_path, target)
                    else:
                        os.replace(temporary, target.name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
                elif os.name == 'nt':
                    os.rename(temporary_path, target)
                else:
                    os.link(temporary, target.name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd, follow_symlinks=False)
            finally:
                try:
                    os.unlink(temporary_path if os.name == 'nt' else temporary, **kwargs)
                except FileNotFoundError:
                    pass
    LOGGER.info('[files.py][atomic_write] 文件原子写入完成，run=%s，字节=%d，新建=%s', current_context().run_id, len(data), not exists)
    return {'path': str(target), 'bytes': len(data), 'etag': hashlib.sha256(data).hexdigest(), 'created': not exists}


async def read_file(arguments):
    """返回指定行范围和完整文件哈希，截断时明确说明。"""
    _, target = target_path(arguments['path'])
    content, etag = read_text(target)
    lines = content.splitlines(keepends=True)
    start = arguments.get('start_line', 1)
    selected = ''.join(lines[start - 1:start - 1 + arguments.get('max_lines', 200)])
    truncated = len(selected) > 12000 or start - 1 + arguments.get('max_lines', 200) < len(lines)
    return json_result({'path': str(target), 'content': selected[:12000], 'start_line': start,
                        'total_lines': len(lines), 'truncated': truncated, 'etag': etag})


async def write_file(arguments):
    """在确认通过后新建文本或带版本校验地替换文本。"""
    _, target = target_path(arguments['path'])
    return json_result(atomic_write(target, arguments['content'], arguments.get('expected_etag'), arguments.get('create_parents', False)))


async def edit_file(arguments):
    """按旧文本精确替换，默认只允许一个匹配，防止含糊修改。"""
    _, target = target_path(arguments['path'])
    with FILE_LOCK:
        content, etag = read_text(target)
        if etag != arguments['expected_etag']:
            raise ToolHandlerError('文件版本已变化，请重新读取后编辑。')
        count = content.count(arguments['old_text'])
        if not count or (count != 1 and not arguments.get('replace_all', False)):
            raise ToolHandlerError('旧文本没有匹配或存在多个匹配，请提供唯一片段或明确 replace_all。')
        updated = content.replace(arguments['old_text'], arguments['new_text'])
        return json_result({**atomic_write(target, updated, etag), 'replacements': count})


def entries(target):
    """在固定目录句柄内读取有限条目，跳过链接和依赖目录。"""
    with locked_path(target, directory=True) as fd:
        with os.scandir(target if os.name == 'nt' else fd) as iterator:
            for index, entry in enumerate(iterator):
                if index >= 1000:
                    yield None, None
                    break
                if entry.name in IGNORED:
                    continue
                child = target / entry.name
                try:
                    info = safe_stat(child)
                except (OSError, WorkspaceError):
                    continue
                yield child, info


async def list_directory(arguments):
    """列出根内目录，输出限制条目数，不跟随链接。"""
    root, target = target_path(arguments.get('path', ''))
    limit = arguments.get('limit', 200)
    found = []
    limited = False
    for child, info in entries(target):
        if child is None:
            limited = True
            break
        found.append({'path': str(child.relative_to(root)), 'is_dir': stat.S_ISDIR(info.st_mode), 'size': info.st_size})
        if len(found) > limit:
            break
    return json_result({'entries': found[:limit], 'truncated': limited or len(found) > limit})


async def search_files(arguments):
    """在有限目录和字节预算内进行文件名或内容字面量搜索，避免正则失控。"""
    root, target = target_path(arguments.get('path', ''))
    query = arguments['query'].casefold()
    mode = arguments.get('target', 'content')
    pending, found, visited, read_bytes = [(target, 0)], [], 0, 0
    deadline = time.monotonic() + 2
    limited = False
    while pending and not limited:
        directory, depth = pending.pop()
        for child, info in entries(directory):
            if child is None:
                limited = True
                break
            visited += 1
            if visited > 1000 or time.monotonic() > deadline or read_bytes > 4 * 1024 * 1024:
                limited = True
                break
            if stat.S_ISDIR(info.st_mode):
                if depth < 8:
                    pending.append((child, depth + 1))
                else:
                    limited = True
                continue
            if mode == 'files':
                if query in child.name.casefold():
                    found.append({'path': str(child.relative_to(root))})
            elif info.st_size <= MAX_TEXT_BYTES:
                if read_bytes + info.st_size > 4 * 1024 * 1024:
                    limited = True
                    break
                read_bytes += info.st_size
                try:
                    content, _ = read_text(child)
                except (OSError, WorkspaceError, ToolHandlerError):
                    continue
                for number, line in enumerate(content.splitlines(), 1):
                    if query in line.casefold():
                        found.append({'path': str(child.relative_to(root)), 'line': number, 'text': line[:250]})
                        if len(found) >= arguments.get('limit', 30):
                            break
            if len(found) >= arguments.get('limit', 30):
                limited = True
                break
    return json_result({'matches': found, 'truncated': limited, 'visited': min(visited, 1000)})


def file_definitions():
    """导出读写分级的工作区工具，修改操作始终要求确认。"""
    path = {'type': 'string', 'maxLength': 4096, 'description': '当前工作区内相对路径；禁止根外路径。'}
    etag = {'type': 'string', 'minLength': 64, 'maxLength': 64, 'description': '先 read_file 获取的完整文件 etag。'}
    specifications = [
        ('read_file', '读取工作区 UTF-8 文本及 etag；支持行范围，不能读取 Word 等二进制。', read_file, False,
         {'path': path, 'start_line': {'type': 'integer', 'minimum': 1}, 'max_lines': {'type': 'integer', 'minimum': 1, 'maximum': 500}}, ['path']),
        ('write_file', '需确认：新建 UTF-8 文本；已有文件必须先读取并提供 expected_etag。不能生成 Word 等二进制。', write_file, True,
         {'path': path, 'content': {'type': 'string', 'maxLength': 200000}, 'expected_etag': etag, 'create_parents': {'type': 'boolean'}}, ['path', 'content']),
        ('edit_file', '需确认：凭 etag 精确替换文本；默认只允许唯一旧片段。', edit_file, True,
         {'path': path, 'old_text': {'type': 'string', 'minLength': 1, 'maxLength': 200000}, 'new_text': {'type': 'string', 'maxLength': 200000}, 'expected_etag': etag, 'replace_all': {'type': 'boolean'}}, ['path', 'old_text', 'new_text', 'expected_etag']),
        ('list_directory', '列出工作区目录，跳过链接、版本库和依赖目录。', list_directory, False,
         {'path': path, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 300}}, []),
        ('search_files', '工作区内文件名或文本内容字面量搜索；有深度、条目、时间和字节上限。', search_files, False,
         {'path': path, 'query': {'type': 'string', 'minLength': 1, 'maxLength': 200}, 'target': {'type': 'string', 'enum': ['files', 'content']}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 50}}, ['query']),
    ]
    return [ToolDefinition(name, description, {'type': 'object', 'properties': properties, 'required': required}, handler,
                           risk_level='medium' if modifies else 'low', scope='workspace', requires_confirmation=modifies,
                           read_only=not modifies) for name, description, handler, modifies, properties, required in specifications]
