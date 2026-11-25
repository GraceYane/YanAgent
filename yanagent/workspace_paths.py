"""工作区路径边界与描述符访问：拒绝链接、设备路径及跨目录读取。"""

import os
import re
import stat
from contextlib import contextmanager, ExitStack
from pathlib import Path

from yanagent.errors import AgentError, PermissionDeniedError


class WorkspaceError(AgentError):
    """工作区受控错误，不向客户端转发底层异常或文件内容。"""

    code = 'workspace_error'
    message = '工作区路径无效、文件不受支持或当前无法访问。'


class WorkspaceAccessError(PermissionDeniedError):
    """桌面文件凭证问题与模型供应商的 403 分开，避免引导用户修改 API Key。"""

    code = 'workspace_access_denied'
    message = '工作区访问凭证缺失或已失效，请完全退出桌面端后重新启动；仅刷新页面无效。'


class WorkspacePreviewAccessError(PermissionDeniedError):
    """只读预览凭证失效时重新打开文件，不要求修改模型配置。"""

    code = 'workspace_preview_expired'
    message = '文件预览链接无效或已失效，请在工作区中重新打开该文件。'


def clean_absolute(value):
    """只接受本机规范绝对路径，拒绝 UNC、设备、ADS、保留名称及父级跳转。"""
    if type(value) is not str or not value or len(value) > 4096 or any(ord(c) < 32 for c in value):
        raise WorkspaceError()
    raw = value.replace('\\', '/')
    if raw.startswith('//') or any(part == '..' for part in raw.split('/')):
        raise WorkspaceError()
    path = Path(value)
    if not path.is_absolute():
        raise WorkspaceError()
    for part in path.parts[1:]:
        if part in {'.', ''} or (os.name == 'nt' and (
            any(c in part for c in ':*?"<>|') or part.endswith((' ', '.')) or
            re.fullmatch(r'(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?', part, re.I))):
            raise WorkspaceError()
    return Path(os.path.abspath(path))


def within(root, value):
    """按路径组件判断归属，不以字符串前缀代替根目录边界。"""
    if type(value) is not str or '\x00' in value:
        raise WorkspaceError()
    raw = value.replace('\\', '/')
    if raw.startswith('//') or any(part == '..' for part in raw.split('/')):
        raise WorkspaceError()
    candidate = Path(value)
    if not candidate.is_absolute():
        if candidate.drive or (os.name == 'nt' and raw.startswith('/')):
            raise WorkspaceError()
        candidate = root / candidate
    candidate = clean_absolute(str(candidate))
    if not candidate.is_relative_to(root):
        raise WorkspaceError()
    return candidate


def safe_stat(path):
    """读取链接自身属性，拒绝符号链接、Windows 重解析点及特殊文件。"""
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
        raise WorkspaceError()
    if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
        raise WorkspaceError()
    if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
        raise WorkspaceError()
    return info


if os.name == 'nt':
    import ctypes
    from ctypes import wintypes
    import msvcrt

    _kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    _kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                   wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    _kernel.CreateFileW.restype = wintypes.HANDLE
    _kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel.GetFileInformationByHandleEx.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    _kernel.GetFinalPathNameByHandleW.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]


def _win_open(path, directory):
    """不跟随重解析点打开 Windows 句柄，并核验句柄最终路径与预期一致。"""
    access = 0x80 if directory else 0x80000000
    handle = _kernel.CreateFileW(str(path), access, 3 if directory else 1, None, 3,
                                 0x00200000 | (0x02000000 if directory else 0), None)
    if handle == ctypes.c_void_p(-1).value:
        raise OSError(ctypes.get_last_error(), '无法打开工作区对象')
    try:
        attributes = (wintypes.DWORD * 2)()
        if not _kernel.GetFileInformationByHandleEx(handle, 9, ctypes.byref(attributes), ctypes.sizeof(attributes)):
            raise WorkspaceError()
        if attributes[0] & 0x400 or bool(attributes[0] & 0x10) != directory:
            raise WorkspaceError()
        buffer = ctypes.create_unicode_buffer(32768)
        length = _kernel.GetFinalPathNameByHandleW(handle, buffer, len(buffer), 0)
        if not length or length >= len(buffer):
            raise WorkspaceError()
        final = buffer.value.removeprefix('\\\\?\\')
        if os.path.normcase(final) != os.path.normcase(str(path)):
            raise WorkspaceError()
        return handle
    except BaseException:
        _kernel.CloseHandle(handle)
        raise


@contextmanager
def locked_path(path, *, directory=False):
    """逐级固定目录；Windows 禁止目录改名，POSIX 使用 dir_fd 和 O_NOFOLLOW。"""
    path = clean_absolute(str(path))
    try:
        with ExitStack() as stack:
            if os.name == 'nt':
                prefix = Path(path.anchor)
                components = [prefix, *[Path(*path.parts[:i]) for i in range(2, len(path.parts) + 1)]]
                for current in components if directory else components[:-1]:
                    handle = _win_open(current, True)
                    stack.callback(_kernel.CloseHandle, handle)
                if directory:
                    yield None
                else:
                    handle = _win_open(path, False)
                    try:
                        fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
                    except BaseException:
                        _kernel.CloseHandle(handle)
                        raise
                    stack.callback(os.close, fd)
                    if os.fstat(fd).st_nlink != 1:
                        raise WorkspaceError()
                    yield fd
            else:
                fd = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
                stack.callback(os.close, fd)
                for index, part in enumerate(path.parts[1:]):
                    is_directory = index < len(path.parts) - 2 or directory
                    fd = os.open(part, os.O_RDONLY | os.O_NOFOLLOW | (os.O_DIRECTORY if is_directory else os.O_NONBLOCK), dir_fd=fd)
                    stack.callback(os.close, fd)
                info = os.fstat(fd)
                if not directory and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1):
                    raise WorkspaceError()
                yield fd
    except (OSError, ValueError):
        raise WorkspaceError() from None


def make_directories(path):
    """从存在的父目录逐级创建托管目录，每次创建都在固定父目录内执行。"""
    path = clean_absolute(str(path))
    missing, parent = [], path
    while not parent.exists():
        missing.append(parent)
        parent = parent.parent
    for target in reversed(missing):
        with locked_path(target.parent, directory=True) as fd:
            if os.name == 'nt':
                target.mkdir(exist_ok=True)
            else:
                try:
                    os.mkdir(target.name, dir_fd=fd)
                except FileExistsError:
                    pass
    with locked_path(path, directory=True):
        return path
