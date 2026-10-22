"""YanAgent 本地 HTTP 服务：连接桌面端、常驻运行时与 SSE 流。"""

from __future__ import annotations

import json
import logging
import signal
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, cast
from urllib.parse import parse_qs, urlparse

from yanagent.chat import ProviderFactory, YanAgentApplication, ensure_application_ready
from yanagent.config import ConfigStore
from yanagent.errors import (
    AgentError, AuthenticationError, ConfigurationError, InvalidRequestError,
    ModelConnectionError, ModelNotFoundError, ModelRefusalError, ModelResponseError,
    ModelServerError, ModelTimeoutError, PermissionDeniedError, RateLimitError,
    RequestValidationError, UnexpectedToolCallError,
)
from yanagent.runtime import AgentRuntime


LOGGER = logging.getLogger("yanagent.http")
MAX_REQUEST_BYTES = 1 * 1024 * 1024


def health_payload() -> dict[str, str]:
    """返回进程和当前运行能力状态，不探测外部模型网络。"""
    return {
        "status": "ok", "name": "YanAgent", "edition": "core-runtime-learning",
        "agent_runtime": "streaming_chat",
    }


def empty_sessions_payload() -> dict[str, Any]:
    """返回 P02 前使用的空会话分页结构。"""
    return {
        "status": "success", "sessions": [], "total": 0, "page": 1,
        "page_size": 50, "has_more": False, "group_mode": "time", "project_order": [],
    }


def _http_status(error: AgentError) -> HTTPStatus:
    """将内部稳定错误类型映射为 HTTP 状态，正文仍使用统一错误对象。"""
    if isinstance(error, (RequestValidationError, ConfigurationError, InvalidRequestError)):
        return HTTPStatus.BAD_REQUEST
    if isinstance(error, AuthenticationError):
        return HTTPStatus.UNAUTHORIZED
    if isinstance(error, PermissionDeniedError):
        return HTTPStatus.FORBIDDEN
    if isinstance(error, ModelNotFoundError):
        return HTTPStatus.NOT_FOUND
    if isinstance(error, RateLimitError):
        return HTTPStatus.TOO_MANY_REQUESTS
    if isinstance(error, ModelTimeoutError):
        return HTTPStatus.GATEWAY_TIMEOUT
    if isinstance(error, ModelRefusalError):
        return HTTPStatus.UNPROCESSABLE_ENTITY
    if isinstance(error, (
        ModelConnectionError, ModelResponseError, ModelServerError, UnexpectedToolCallError,
    )):
        return HTTPStatus.BAD_GATEWAY
    return HTTPStatus.INTERNAL_SERVER_ERROR


class YanAgentHTTPServer(ThreadingHTTPServer):
    """携带共享应用服务的线程 HTTP Server；每个请求仍由独立线程处理。"""

    daemon_threads = True

    def __init__(
        self, server_address: tuple[str, int], application: YanAgentApplication,
    ) -> None:
        """保存应用服务并启动唯一常驻异步运行环境。"""
        self.application = application
        super().__init__(server_address, YanAgentHandler)
        self.runtime = AgentRuntime(application)

    def server_close(self) -> None:
        """关闭监听套接字前幂等停止异步运行环境及其中的活动任务。"""
        if hasattr(self, "runtime"):
            self.runtime.close()
        super().server_close()


class YanAgentHandler(BaseHTTPRequestHandler):
    """实现桌面端当前所需的 JSON 接口及普通聊天错误边界。"""

    server_version = "YanAgent/0.1"

    @property
    def application(self) -> YanAgentApplication:
        """从类型化 Server 获取共享应用层。"""
        return cast(YanAgentHTTPServer, self.server).application

    @property
    def runtime(self) -> AgentRuntime:
        """获取该进程唯一的常驻异步运行环境。"""
        return cast(YanAgentHTTPServer, self.server).runtime

    def log_message(self, fmt: str, *args: object) -> None:
        """将标准库访问日志统一为包含文件和函数的中文可检索格式。"""
        LOGGER.info("[app.py][YanAgentHandler.log_message] HTTP 访问：%s", fmt % args)

    def _json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        """发送 UTF-8 JSON 响应和本地桌面端需要的 CORS 头。"""
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict[str, Any]:
        """读取有大小上限的严格 JSON 对象，坏正文不再悄悄变成空对象。"""
        raw_length = self.headers.get("Content-Length", "0")
        try:
            length = int(raw_length)
        except (TypeError, ValueError):
            raise RequestValidationError(reason="invalid", field="body") from None
        if length < 0 or length > MAX_REQUEST_BYTES:
            raise RequestValidationError(reason="too_large", field="body")
        try:
            raw = self.rfile.read(length) if length else b"{}"
            value = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError, RecursionError):
            raise RequestValidationError(reason="invalid_json", field="body") from None
        if type(value) is not dict:
            raise RequestValidationError(reason="invalid_json", field="body")
        return value

    def _error(self, error: AgentError, *, request_id: str | None = None) -> None:
        """返回统一失败包络；日志只记录错误码，不记录密钥、正文或上游响应。"""
        status = _http_status(error)
        LOGGER.warning(
            "[app.py][YanAgentHandler._error] 请求失败，http_status=%d，error_code=%s，request_id=%s",
            status.value, error.code, request_id or "<未分配>",
        )
        payload = {
            "status": "error", "message": error.message, "error": error.to_dict(),
            "stream": False,
        }
        if request_id is not None:
            payload["request_id"] = request_id
        self._json(payload, status)

    def _sse_headers(self) -> None:
        """发送 EventSource 需要的响应头；不缓存、不缓冲且由服务端主动关闭。"""
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("Connection", "close")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.close_connection = True

    def _sse_data(self, payload: dict[str, Any]) -> None:
        """写出一条桌面端按 onmessage 消费的匿名 SSE JSON 事件。"""
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        self.wfile.write(f"data: {body}\n\n".encode("utf-8"))
        self.wfile.flush()

    def _stream(self, request_id: str) -> None:
        """从 cursor=0 回放并跟随一个运行，直至 done/error 终态。"""
        self._sse_headers()
        cursor = 0
        while True:
            batch = self.runtime.wait_events(request_id, cursor, timeout=15.0)
            if batch is None:
                self._sse_data({
                    "type": "error", "reason": "unknown_request",
                    "message": "未找到对应的运行，请重新发送消息。",
                })
                return
            events, terminal = batch
            if not events:
                self.wfile.write(b": keepalive\n\n")
                self.wfile.flush()
            for event in events:
                self._sse_data(event.to_dict())
                cursor += 1
            if terminal:
                return

    def do_OPTIONS(self) -> None:  # noqa: N802 - 标准库处理器约定的方法名
        """响应浏览器跨域预检。"""
        self._json({"status": "ok"})

    def do_GET(self) -> None:  # noqa: N802 - 标准库处理器约定的方法名
        """处理 SSE、健康、模型配置及仍为骨架状态的只读接口。"""
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path == "/stream":
                values = parse_qs(parsed.query, keep_blank_values=True).get("request_id", [])
                if len(values) != 1 or not values[0] or len(values[0]) > 128:
                    raise RequestValidationError(reason="invalid", field="request_id")
                self._stream(values[0])
                return
            if path in {"/", "/api/health"}:
                self._json(health_payload())
                return
            if path == "/auth/check":
                self._json({"status": "success", "auth_required": False, "authenticated": True})
                return
            if path == "/api/agents":
                self._json({
                    "status": "success", "default_agent_id": "default",
                    "agents": [{"id": "default", "name": "YanAgent", "enabled": True}],
                    "channel_instances": [], "revision": "p01-complete",
                })
                return
            if path == "/api/sessions":
                self._json(empty_sessions_payload())
                return
            if path == "/api/history":
                self._json({
                    "status": "success", "messages": [], "total": 0, "page": 1,
                    "page_size": 20, "has_more": False,
                })
                return
            if path == "/api/menu":
                self._json({"status": "success", "menu": None})
                return
            if path == "/api/models":
                self._json(self.application.models_payload())
                return
            if path in {"/config", "/api/config"}:
                self._json(self.application.config_payload())
                return
            if path == "/api/tools":
                self._json({"status": "success", "tools": []})
                return
            if path == "/api/skills":
                self._json({"status": "success", "skills": []})
                return
            if path == "/api/mcp/servers":
                self._json({"status": "success", "servers": {}})
                return
            if path.startswith("/api/scheduler/runs"):
                self._json({"status": "success", "runs": []})
                return
            self._json({
                "status": "not_implemented",
                "message": f"Scaffold endpoint not implemented: GET {path}",
            }, HTTPStatus.NOT_IMPLEMENTED)
        except (BrokenPipeError, ConnectionResetError):
            LOGGER.info("[app.py][YanAgentHandler.do_GET] SSE 客户端已断开，运行继续在后台执行")
        except AgentError as error:
            self._error(error)

    def do_POST(self) -> None:  # noqa: N802 - 标准库处理器约定的方法名
        """处理配置保存、模型动作、普通/流式消息及取消请求。"""
        path = urlparse(self.path).path
        request_id: str | None = None
        try:
            payload = self._body()
            if path == "/message":
                request_id = f"run-{uuid.uuid4().hex}"
                if payload.get("stream") is True:
                    self._json(self.runtime.start_stream(payload, request_id=request_id))
                else:
                    self._json(self.runtime.complete(payload, request_id=request_id))
                return
            if path == "/config":
                self._json(self.application.save_config(payload))
                return
            if path == "/api/models":
                self._json(self.application.save_model_action(payload))
                return
            if path == "/poll":
                self._json({"status": "success", "has_content": False})
                return
            if path == "/cancel":
                allowed = {"request_id", "session_id", "lang"}
                if any(type(key) is not str or key not in allowed for key in payload):
                    raise RequestValidationError(reason="unknown_field", field="body")
                request_value = payload.get("request_id")
                session_value = payload.get("session_id")
                if request_value is not None and (
                    type(request_value) is not str or not request_value or len(request_value) > 128
                ):
                    raise RequestValidationError(reason="invalid", field="request_id")
                if session_value is not None and (
                    type(session_value) is not str or not session_value or len(session_value) > 256
                ):
                    raise RequestValidationError(reason="invalid", field="session_id")
                if request_value is None and session_value is None:
                    raise RequestValidationError(reason="missing", field="request_id")
                cancelled = self.runtime.cancel(
                    request_id=request_value, session_id=session_value,
                )
                self._json({"status": "success", "cancelled": cancelled})
                return
            self._json({
                "status": "not_implemented",
                "message": f"Scaffold endpoint not implemented: POST {path}",
            }, HTTPStatus.NOT_IMPLEMENTED)
        except AgentError as error:
            self._error(error, request_id=request_id)


def create_server(
    host: str | None = None,
    port: int | None = None,
    *,
    application: YanAgentApplication | None = None,
    config_store: ConfigStore | None = None,
    provider_factory: ProviderFactory | None = None,
) -> YanAgentHTTPServer:
    """根据生效配置创建服务；测试可注入临时配置和 Fake Provider。"""
    if application is not None and (config_store is not None or provider_factory is not None):
        raise ValueError("application 与 config_store/provider_factory 不能同时传入")
    app = application or YanAgentApplication(config_store, provider_factory=provider_factory)
    ensure_application_ready(app)
    config = app.load_config()
    bind_host = config.host if host is None else host
    bind_port = config.port if port is None else port
    return YanAgentHTTPServer((bind_host, bind_port), app)


def main() -> None:
    """启动本地服务并在 SIGTERM 或 Ctrl+C 时关闭监听。"""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    server = create_server()

    def stop_server(_signum: int, _frame: object) -> None:
        """处理桌面父进程终止信号，关闭监听并退出主循环。"""
        LOGGER.info("[app.py][main.stop_server] 收到终止信号，正在关闭服务")
        server.server_close()
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop_server)
    host, port = server.server_address[:2]
    LOGGER.info("[app.py][main] YanAgent 后端已启动：http://%s:%s", host, port)
    LOGGER.info("[app.py][main] 当前能力：P01 单模型普通/流式聊天、错误反馈与基本取消")
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        LOGGER.info("[app.py][main] YanAgent 后端已关闭")


if __name__ == "__main__":
    main()
