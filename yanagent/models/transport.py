"""有响应大小限制的 HTTP JSON 传输；阻塞 I/O 在线程中执行，不阻塞事件循环。"""

from __future__ import annotations

import asyncio
import json
import threading
from http.client import HTTPException
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any, BinaryIO, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from yanagent.errors import (
    AgentError, InvalidRequestError, ModelConnectionError, ModelResponseError, ModelTimeoutError,
    map_http_error,
)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """拒绝重复 JSON 键，避免模型工具参数出现含糊的覆盖行为。"""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ModelResponseError()
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    """拒绝 NaN 和 Infinity 这类非标准 JSON 值。"""
    raise ModelResponseError()


def strict_json_loads(raw: str) -> Any:
    """解码响应或工具参数；错误不回显原文，顶层形状由使用者检查。"""
    try:
        return json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (ValueError, TypeError, RecursionError):
        raise ModelResponseError() from None


class JsonTransport(Protocol):
    """可替换的异步 JSON 传输接口，用于真实网络和确定性的离线测试。"""

    async def post_json(
        self, *, url: str, headers: dict[str, str], payload: dict[str, Any], timeout: float,
    ) -> dict[str, Any]:
        """发送 JSON 并返回解析后的对象，失败抛出统一错误。"""
        ...


class SseTransport(Protocol):
    """可替换的异步 SSE 传输接口，只负责 HTTP 和事件帧，不解释模型 JSON。"""

    def stream_data(
        self, *, url: str, headers: dict[str, str], payload: dict[str, Any], timeout: float,
    ) -> AsyncIterator[str]:
        """逐条返回 SSE ``data`` 正文；取消迭代时必须关闭底层响应。"""
        ...


class _NoRedirect(HTTPRedirectHandler):
    """禁止自动重定向，防止携带 Authorization 的请求被转发到别处。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        """让 urllib 将 3xx 作为错误返回，而不是携带凭据继续访问。"""
        return None


class UrllibJsonTransport:
    """标准库传输实现；无自动重试，每次请求结束均关闭响应。"""

    def __init__(self, *, max_response_bytes: int = 8 * 1024 * 1024) -> None:
        """设置最多读取的响应字节数，超出时拒绝而不是截断后误解析。"""
        if type(max_response_bytes) is not int or max_response_bytes <= 0:
            raise ValueError("响应大小限制必须是正整数")
        self.max_response_bytes = max_response_bytes

    async def post_json(
        self, *, url: str, headers: dict[str, str], payload: dict[str, Any], timeout: float,
    ) -> dict[str, Any]:
        """等待一次有期限的后台请求；取消等待不能强制结束标准库线程。"""
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self._post_sync, url, headers, payload, timeout), timeout=timeout,
            )
        except (TimeoutError, asyncio.TimeoutError):
            raise ModelTimeoutError() from None

    def _post_sync(
        self, url: str, headers: dict[str, str], payload: dict[str, Any], timeout: float,
    ) -> dict[str, Any]:
        """构造请求并读取受限响应；底层错误只转换为安全的统一错误。"""
        try:
            body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
            # HTTP 头采用 ASCII；不让非法凭据触发包含原值的编码异常。
            for key, value in headers.items():
                key.encode("ascii")
                value.encode("ascii")
                if "\r" in value or "\n" in value:
                    raise ValueError()
            request = Request(url, data=body, headers=headers, method="POST")
            with build_opener(_NoRedirect()).open(request, timeout=timeout) as response:
                if not 200 <= response.status < 300:
                    raise ModelResponseError()
                raw = response.read(self.max_response_bytes + 1)
        except HTTPError as error:
            status = error.code
            error.close()
            if type(status) is int and 400 <= status <= 599:
                raise map_http_error(status) from None
            raise ModelResponseError() from None
        except URLError as error:
            if isinstance(error.reason, TimeoutError):
                raise ModelTimeoutError() from None
            raise ModelConnectionError() from None
        except TimeoutError:
            raise ModelTimeoutError() from None
        except (OSError, HTTPException):
            raise ModelConnectionError() from None
        except (ValueError, TypeError, RecursionError):
            raise InvalidRequestError() from None
        if len(raw) > self.max_response_bytes:
            raise ModelResponseError()
        try:
            data = strict_json_loads(raw.decode("utf-8"))
        except UnicodeError:
            raise ModelResponseError() from None
        if type(data) is not dict:
            raise ModelResponseError()
        return data


@dataclass(frozen=True)
class _WorkerItem:
    """阻塞读取线程交给事件循环的单条结果。"""

    kind: str
    value: str | AgentError | None = None


class UrllibSseTransport:
    """标准库 SSE 传输；阻塞读取在线程中进行，取消时主动关闭响应。"""

    def __init__(
        self, *, max_response_bytes: int = 8 * 1024 * 1024, max_event_bytes: int = 1 * 1024 * 1024,
    ) -> None:
        """设置整条响应与单个 SSE 事件上限，防止无限流耗尽内存。"""
        if (
            type(max_response_bytes) is not int
            or type(max_event_bytes) is not int
            or max_response_bytes <= 0
            or max_event_bytes <= 0
            or max_event_bytes > max_response_bytes
        ):
            raise ValueError("SSE 响应与事件大小限制必须是有效正整数")
        self.max_response_bytes = max_response_bytes
        self.max_event_bytes = max_event_bytes

    async def stream_data(
        self, *, url: str, headers: dict[str, str], payload: dict[str, Any], timeout: float,
    ) -> AsyncIterator[str]:
        """把读取线程的帧送入当前事件循环，并在总期限或取消时释放连接。"""
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[_WorkerItem] = asyncio.Queue()
        stopped = threading.Event()
        response_lock = threading.Lock()
        response_holder: list[BinaryIO] = []

        def publish(item: _WorkerItem) -> None:
            """从工作线程安全地投递一项；事件循环关闭后静默丢弃。"""
            try:
                if not loop.is_closed():
                    loop.call_soon_threadsafe(queue.put_nowait, item)
            except RuntimeError:
                pass

        worker = threading.Thread(
            target=self._stream_sync,
            args=(url, headers, payload, timeout, stopped, response_lock, response_holder, publish),
            name="yanagent-sse-reader",
            daemon=True,
        )
        worker.start()
        deadline = loop.time() + timeout
        try:
            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise ModelTimeoutError()
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=remaining)
                except (TimeoutError, asyncio.TimeoutError):
                    raise ModelTimeoutError() from None
                if item.kind == "data":
                    yield str(item.value)
                elif item.kind == "error":
                    if isinstance(item.value, AgentError):
                        raise item.value from None
                    raise ModelResponseError()
                else:
                    return
        finally:
            stopped.set()
            response_to_close: BinaryIO | None = None
            with response_lock:
                if response_holder:
                    response_to_close = response_holder[0]
            # Windows 的 HTTPResponse.close 可能等待正在执行的 readline；不能在事件
            # 循环线程同步关闭，否则“停止生成”会反而等服务端。后台关闭和 socket
            # timeout 共同给资源回收设上界，协程本身立即响应取消。
            if response_to_close is not None:
                threading.Thread(
                    target=self._close_response,
                    args=(response_to_close,),
                    name="yanagent-sse-closer",
                    daemon=True,
                ).start()

    @staticmethod
    def _close_response(response: BinaryIO) -> None:
        """在独立守护线程关闭可能正被阻塞读取的标准库 HTTP 响应。"""
        try:
            response.close()
        except OSError:
            pass

    def _stream_sync(
        self,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        timeout: float,
        stopped: threading.Event,
        response_lock: threading.Lock,
        response_holder: list[BinaryIO],
        publish: Callable[[_WorkerItem], None],
    ) -> None:
        """在线程内建立连接并按 SSE 空行边界组装多行 ``data``。"""
        response: Any = None
        try:
            body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
            for key, value in headers.items():
                key.encode("ascii")
                value.encode("ascii")
                if "\r" in value or "\n" in value:
                    raise ValueError()
            request = Request(url, data=body, headers=headers, method="POST")
            response = build_opener(_NoRedirect()).open(request, timeout=timeout)
            with response_lock:
                response_holder.append(response)
            if not 200 <= response.status < 300:
                raise ModelResponseError()
            consumed = 0
            data_lines: list[str] = []
            event_bytes = 0
            while not stopped.is_set():
                raw = response.readline(self.max_event_bytes + 2)
                if not raw:
                    if data_lines:
                        publish(_WorkerItem("data", "\n".join(data_lines)))
                    break
                consumed += len(raw)
                if consumed > self.max_response_bytes or len(raw) > self.max_event_bytes + 1:
                    raise ModelResponseError()
                line = raw.rstrip(b"\r\n")
                if not line:
                    if data_lines:
                        publish(_WorkerItem("data", "\n".join(data_lines)))
                        data_lines = []
                        event_bytes = 0
                    continue
                if line.startswith(b":"):
                    continue
                if line == b"data" or line.startswith(b"data:"):
                    value = line[5:] if line.startswith(b"data:") else b""
                    if value.startswith(b" "):
                        value = value[1:]
                    event_bytes += len(value)
                    if event_bytes > self.max_event_bytes:
                        raise ModelResponseError()
                    data_lines.append(value.decode("utf-8"))
            publish(_WorkerItem("end"))
        except HTTPError as error:
            status = error.code
            error.close()
            publish(_WorkerItem(
                "error",
                map_http_error(status) if type(status) is int and 400 <= status <= 599
                else ModelResponseError(),
            ))
        except URLError as error:
            mapped = (
                ModelTimeoutError()
                if isinstance(error.reason, TimeoutError)
                else ModelConnectionError()
            )
            publish(_WorkerItem("error", mapped))
        except TimeoutError:
            publish(_WorkerItem("error", ModelTimeoutError()))
        except UnicodeError:
            publish(_WorkerItem("error", ModelResponseError()))
        except (OSError, HTTPException):
            if stopped.is_set():
                publish(_WorkerItem("end"))
            else:
                publish(_WorkerItem("error", ModelConnectionError()))
        except (ValueError, TypeError, RecursionError):
            if stopped.is_set():
                publish(_WorkerItem("end"))
            else:
                publish(_WorkerItem("error", InvalidRequestError()))
        except AgentError as error:
            publish(_WorkerItem("error", error))
        finally:
            with response_lock:
                if response_holder:
                    response_holder.clear()
            if response is not None:
                try:
                    response.close()
                except OSError:
                    pass
