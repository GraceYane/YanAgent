"""有确认的本机命令与后台进程：身份隔离、有限输出和进程树生命周期。"""

import asyncio
import base64
import locale
import logging
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field

from yanagent.workspace_paths import locked_path
from .execution_context import current_context
from .files import target_path, json_result
from .manager import ToolDefinition, ToolHandlerError


LOGGER = logging.getLogger('yanagent.tools.processes')
MAX_OUTPUT_BYTES = 48 * 1024
# 子进程先等待父端放行；Windows 在放行前加入 Job，避免后代逃过取消收尾。
GATE = "import sys,subprocess; token=sys.stdin.buffer.read(1); sys.exit(subprocess.call(sys.argv[1:],stdin=subprocess.DEVNULL) if token==b'1' else 125)"


class WindowsJob:
    """用无继承的 Job 句柄统一终止当前命令及其普通后代。"""

    def __init__(self, process):
        """建立 kill-on-close Job，并在命令门闩打开前绑定进程。"""
        import ctypes
        from ctypes import wintypes
        class BasicLimits(ctypes.Structure):
            """对应 Windows 基本 Job 限制的原生布局。"""
            _fields_ = [('process_time', ctypes.c_longlong), ('job_time', ctypes.c_longlong),
                        ('flags', wintypes.DWORD), ('minimum', ctypes.c_size_t), ('maximum', ctypes.c_size_t),
                        ('active', wintypes.DWORD), ('affinity', ctypes.c_size_t),
                        ('priority', wintypes.DWORD), ('scheduling', wintypes.DWORD)]
        class ExtendedLimits(ctypes.Structure):
            """对应含 IO 计数的扩展 Job 限制布局。"""
            _fields_ = [('basic', BasicLimits), ('io', ctypes.c_ulonglong * 6),
                        ('process_memory', ctypes.c_size_t), ('job_memory', ctypes.c_size_t),
                        ('peak_process', ctypes.c_size_t), ('peak_job', ctypes.c_size_t)]
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.kernel.CreateJobObjectW.restype = wintypes.HANDLE
        self.kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        self.kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.kernel.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        self.kernel.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p]
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.handle = self.kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise OSError('无法创建进程 Job')
        limits = ExtendedLimits()
        limits.basic.flags = 0x2000
        if not self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)) or not self.kernel.AssignProcessToJobObject(self.handle, int(process._handle)):
            self.close()
            raise OSError('无法绑定进程 Job')

    def close(self):
        """终止 Job 全部成员后关闭句柄，调用多次无副作用。"""
        if self.handle:
            import ctypes
            class Accounting(ctypes.Structure):
                """读取 Job 活动进程计数，避免关闭后代仍持有工作目录的竞态。"""
                _fields_ = [('times', ctypes.c_longlong * 4), ('faults', ctypes.c_uint32),
                            ('total', ctypes.c_uint32), ('active', ctypes.c_uint32), ('terminated', ctypes.c_uint32)]
            self.kernel.TerminateJobObject(self.handle, 1)
            accounting = Accounting()
            deadline = time.monotonic() + 3
            while self.kernel.QueryInformationJobObject(self.handle, 1, ctypes.byref(accounting), ctypes.sizeof(accounting), None) and accounting.active and time.monotonic() < deadline:
                time.sleep(0.005)
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def owner_key(context):
    """完整会话和根路径组成进程可见边界，调用 ID 不能替代身份。"""
    return (context.user_id, context.agent_id, context.session_id, context.workspace)


def decode_output(data, encoding, *, dropped=False, final=True):
    """优先指定编码，兼容本地编码；UTF-8 分块/尾部截断不误判成 GBK。"""
    encodings = [encoding] if encoding != 'auto' else ['utf-8', locale.getpreferredencoding(False), 'gb18030' if os.name == 'nt' else 'utf-8']
    for candidate in encodings:
        chunk = data
        if candidate == 'utf-8' and dropped:
            skipped = 0
            while chunk and 0x80 <= chunk[0] < 0xc0 and skipped < 3:
                chunk = chunk[1:]
                skipped += 1
        try:
            return chunk.decode(candidate), candidate, False
        except UnicodeDecodeError as error:
            if candidate == 'utf-8' and not final and error.reason == 'unexpected end of data':
                return chunk[:error.start].decode(candidate), candidate, False
            continue
    candidate = encodings[-1]
    return data.decode(candidate, errors='replace'), candidate, True


@dataclass
class CommandJob:
    """保存有限进程输出与运行状态，不保存命令正文或环境密钥。"""
    id: str
    owner: tuple
    run_id: str
    process: subprocess.Popen
    encoding: str
    timeout: float
    windows_job: WindowsJob | None = None
    buffer: bytearray = field(default_factory=bytearray)
    dropped: int = 0
    state: str = 'running'
    task: asyncio.Task | None = None
    reader: threading.Thread | None = None
    lock: threading.RLock = field(default_factory=threading.RLock)
    terminated: bool = False

    def drain(self):
        """独立线程持续排空合并管道，只保留尾部有限字节以防堵塞和内存膨胀。"""
        try:
            with self.process.stdout as stream:
                while True:
                    chunk = os.read(stream.fileno(), 4096)
                    if not chunk:
                        break
                    with self.lock:
                        self.buffer.extend(chunk)
                        overflow = max(0, len(self.buffer) - MAX_OUTPUT_BYTES)
                        if overflow:
                            del self.buffer[:overflow]
                            self.dropped += overflow
        except (OSError, ValueError):
            pass

    def terminate(self):
        """取消整棵普通进程树；POSIX 组外脱离进程不属于此机制的隔离保证。"""
        if self.terminated:
            return
        self.terminated = True
        if os.name == 'nt':
            if self.windows_job:
                self.windows_job.close()
        else:
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if self.process.poll() is None:
            self.process.kill()
        self.process.wait(timeout=5)
        if self.reader and self.reader is not threading.current_thread():
            self.reader.join(timeout=2)

    def snapshot(self):
        """原子读取有界尾部输出，保留退出码、状态、编码和截断信息。"""
        with self.lock:
            text, encoding, lossy = decode_output(bytes(self.buffer), self.encoding,
                                                 dropped=self.dropped > 0, final=self.state != 'running')
            return {'process_id': self.id, 'status': self.state, 'exit_code': self.process.poll(),
                    'output': text[-12000:], 'encoding': encoding, 'lossy': lossy,
                    'truncated': self.dropped > 0 or len(text) > 12000, 'dropped_bytes': self.dropped}


class ProcessService:
    """管理本应用注册的命令；允许同会话后续轮询，不接收任意系统 PID。"""

    def __init__(self):
        """初始化跨身份线程共用注册表，实际监控留在所属 Runtime 事件循环。"""
        self.jobs = {}
        self.lock = threading.RLock()

    async def monitor(self, job):
        """后台期限、取消和正常退出均回收进程树与管道。"""
        started = time.monotonic()
        try:
            while job.process.poll() is None:
                if time.monotonic() - started >= job.timeout:
                    job.state = 'timed_out'
                    break
                await asyncio.sleep(0.05)
            if job.state == 'running':
                job.state = 'completed'
        except asyncio.CancelledError:
            job.state = 'cancelled'
            raise
        finally:
            job.terminate()
            if job.reader:
                await asyncio.to_thread(job.reader.join, 2)
            LOGGER.info('[processes.py][ProcessService.monitor] 进程已回收，run=%s，process=%s，状态=%s，退出码=%s', job.run_id, job.id, job.state, job.process.returncode)

    def argv(self, arguments):
        """Windows 默认 PowerShell，POSIX 默认 Bash；明确 shell，不拼接文件路径。"""
        shell = arguments.get('shell', 'auto')
        if shell == 'auto':
            shell = 'powershell' if os.name == 'nt' else 'bash'
        if shell == 'powershell':
            program = shutil.which('pwsh') or shutil.which('powershell')
            prefix = "$ErrorActionPreference='Stop'; [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); $OutputEncoding = [Console]::OutputEncoding; "
            suffix = "\n$yanAgentCommandOk=$?; if ($null -ne $LASTEXITCODE) { exit $LASTEXITCODE }; if (-not $yanAgentCommandOk) { exit 1 }"
            encoded = base64.b64encode((prefix + arguments['command'] + suffix).encode('utf-16-le')).decode('ascii')
            argv = [program, '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded]
        else:
            program = shutil.which('bash')
            argv = [program, '--noprofile', '--norc', '-c', arguments['command']]
        if not program:
            raise ToolHandlerError('系统没有所选 Shell，请选择已安装的 PowerShell 或 Bash。')
        return argv

    async def execute(self, arguments):
        """确认后启动有限时命令；后台立即返回句柄，前台等待期限或外层取消。"""
        context = current_context()
        _, cwd = target_path(arguments.get('cwd', ''))
        argv = self.argv(arguments)
        python = shutil.which('python') if getattr(sys, 'frozen', False) else sys.executable
        if not python:
            raise ToolHandlerError('当前打包环境未找到 Python，命令启动门闩需要本机 Python；请安装后重试。')
        background = arguments.get('background', False)
        timeout = arguments.get('timeout_seconds', 120 if background else 20)
        if not background and timeout > 25:
            raise ToolHandlerError('前台命令最长 25 秒；更长任务请设置 background=true 后轮询。')
        with self.lock:
            for key, old in list(self.jobs.items()):
                if old.task and old.task.done() and len(self.jobs) >= 32:
                    del self.jobs[key]
            if len(self.jobs) >= 32 or sum(job.owner == owner_key(context) and job.state == 'running' for job in self.jobs.values()) >= 4:
                raise ToolHandlerError('后台进程数量已达上限，请先停止已有进程。')
            environment = {key: value for key, value in os.environ.items() if key.upper() in {
                'PATH', 'PATHEXT', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'TEMP', 'TMP', 'HOME', 'USERPROFILE',
                'APPDATA', 'LOCALAPPDATA', 'PROGRAMFILES', 'PROGRAMFILES(X86)', 'LANG', 'LC_ALL',
            }}
            environment.update({'PYTHONIOENCODING': 'utf-8', 'PYTHONUTF8': '1'})
            with locked_path(cwd, directory=True):
                process = subprocess.Popen([python, '-u', '-c', GATE, *argv], cwd=str(cwd), env=environment,
                                           stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                           creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
                                           start_new_session=os.name != 'nt')
            job = CommandJob('proc_' + uuid.uuid4().hex, owner_key(context), context.run_id, process,
                             arguments.get('encoding', 'auto'), timeout)
            try:
                if os.name == 'nt':
                    job.windows_job = WindowsJob(process)
                job.reader = threading.Thread(target=job.drain, daemon=True)
                job.reader.start()
                self.jobs[job.id] = job
                job.task = asyncio.create_task(self.monitor(job))
                process.stdin.write(b'1')
                process.stdin.close()
            except BaseException:
                if process.stdin and not process.stdin.closed:
                    process.stdin.close()
                job.terminate()
                self.jobs.pop(job.id, None)
                raise
        LOGGER.info('[processes.py][ProcessService.execute] 已启动命令，run=%s，process=%s，后台=%s，期限=%s', context.run_id, job.id, background, timeout)
        if not background:
            await job.task
        result = job.snapshot()
        if not background and (result['status'] != 'completed' or result['exit_code'] != 0):
            raise ToolHandlerError('命令未成功完成；使用 process_status 查询输出。process_id=' + job.id)
        return json_result(result)

    def get(self, process_id):
        """只允许当前完整会话与同一工作区访问自己注册的进程。"""
        context = current_context()
        with self.lock:
            job = self.jobs.get(process_id)
        if job is None or job.owner != owner_key(context):
            raise ToolHandlerError('进程不存在或不属于当前会话工作区。')
        return job

    async def status(self, arguments):
        """有限等待已有进程状态，不启动进程，避免模型忙循环消耗轮次。"""
        job = self.get(arguments['process_id'])
        if job.task and not job.task.done():
            await asyncio.wait({job.task}, timeout=arguments.get('wait_seconds', 1))
        return json_result(job.snapshot())

    async def stop(self, arguments):
        """确认后取消已注册进程的监控任务，由最终收尾终止进程树。"""
        job = self.get(arguments['process_id'])
        if job.task and not job.task.done():
            job.task.cancel()
            await asyncio.gather(job.task, return_exceptions=True)
            if job.state == 'running':
                job.state = 'cancelled'
            job.terminate()
        return json_result(job.snapshot())

    async def cancel_run(self, run_id):
        """Run 失败或取消时回收它启动的后台进程，成功轮次可以继续保留至期限。"""
        with self.lock:
            jobs = [job for job in self.jobs.values() if job.run_id == run_id and job.task and not job.task.done() and job.task.get_loop() is asyncio.get_running_loop()]
        for job in jobs:
            job.task.cancel()
        if jobs:
            await asyncio.gather(*(job.task for job in jobs), return_exceptions=True)
        for job in jobs:
            if job.state == 'running':
                job.state = 'cancelled'
            job.terminate()

    def close_loop(self):
        """所属 Runtime 关闭时同步兜底回收尚未来得及进入监控协程的进程。"""
        with self.lock:
            jobs = [job for job in self.jobs.values() if job.task and job.task.get_loop() is asyncio.get_event_loop()]
        for job in jobs:
            if job.state == 'running':
                job.state = 'cancelled'
            job.terminate()

    def definitions(self):
        """声明命令执行、查询及停止；任意 Shell 具有本机权限，执行前必须确认。"""
        process_id = {'type': 'string', 'minLength': 1, 'maxLength': 64}
        return [
            ToolDefinition('execute_command', '需确认：在工作区启动本机命令。Windows 默认 PowerShell，其他系统 Bash。命令具有当前用户权限，cwd 不构成沙箱，可访问根外文件与网络。前台最长25秒；长任务用 background=true，最长600秒，再 process_status 查询。',
                           {'type': 'object', 'properties': {
                               'command': {'type': 'string', 'minLength': 1, 'maxLength': 4096, 'description': 'Shell 命令；较长脚本请先写入工作区文件再运行。'},
                               'cwd': {'type': 'string', 'maxLength': 4096},
                               'shell': {'type': 'string', 'enum': ['auto', 'powershell', 'bash']},
                               'background': {'type': 'boolean'},
                               'timeout_seconds': {'type': 'number', 'minimum': 0.1, 'maximum': 600},
                               'encoding': {'type': 'string', 'enum': ['auto', 'utf-8', 'gb18030', 'cp1252']},
                           }, 'required': ['command']}, self.execute, risk_level='high', scope='workspace', requires_confirmation=True),
            ToolDefinition('process_status', '查询本会话同工作区进程状态、退出码及有限输出。',
                           {'type': 'object', 'properties': {'process_id': process_id, 'wait_seconds': {'type': 'number', 'minimum': 0, 'maximum': 20}}, 'required': ['process_id']}, self.status, scope='workspace', read_only=True),
            ToolDefinition('stop_process', '需确认：停止本会话同工作区已注册的进程及普通子进程。',
                           {'type': 'object', 'properties': {'process_id': process_id}, 'required': ['process_id']}, self.stop, risk_level='medium', scope='workspace', requires_confirmation=True),
        ]
