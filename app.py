"""YanAgent 本地 HTTP 服务：连接桌面端、常驻运行时与 SSE 流。"""

from __future__ import annotations

import json
import logging
import signal
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, cast
from urllib.parse import parse_qs, unquote, urlparse

from yanagent.chat import ProviderFactory, YanAgentApplication, ensure_application_ready
from yanagent.config import ConfigStore
from yanagent.errors import (
    AgentError, AuthenticationError, ConfigurationError, InvalidRequestError,
    MessageNotFoundError,
    ModelConnectionError, ModelNotFoundError, ModelRefusalError, ModelResponseError,
    ModelServerError, ModelTimeoutError, PermissionDeniedError, RateLimitError,
    RequestValidationError, RunAlreadyExistsError, SessionAlreadyExistsError,
    SessionNotFoundError,
    SessionStorageError, SessionValidationError, UnexpectedToolCallError,
)
from yanagent.runtime import AgentRuntime
from yanagent.sessions import DesktopSessionService, RunStore, SessionStore
from yanagent.storage import Database


LOGGER = logging.getLogger("yanagent.http")
MAX_REQUEST_BYTES = 1 * 1024 * 1024


def health_payload() -> dict[str, str]:
    """返回进程和当前运行能力状态，不探测外部模型网络。"""
    return {
        "status": "ok", "name": "YanAgent", "edition": "core-runtime-learning",
        "agent_runtime": "streaming_chat",
    }


def empty_sessions_payload() -> dict[str, Any]:
    """为未注入数据库的离线测试模式返回空会话分页结构。"""
    return {
        "status": "success", "sessions": [], "total": 0, "page": 1,
        "page_size": 50, "has_more": False, "group_mode": "time", "project_order": [],
    }


def _http_status(error: AgentError) -> HTTPStatus:
    """将内部稳定错误类型映射为 HTTP 状态，正文仍使用统一错误对象。"""
    if isinstance(error, (
        RequestValidationError, ConfigurationError, InvalidRequestError, SessionValidationError,
    )):
        return HTTPStatus.BAD_REQUEST
    if isinstance(error, AuthenticationError):
        return HTTPStatus.UNAUTHORIZED
    if isinstance(error, PermissionDeniedError):
        return HTTPStatus.FORBIDDEN
    if isinstance(error, (ModelNotFoundError, MessageNotFoundError, SessionNotFoundError)):
        return HTTPStatus.NOT_FOUND
    if isinstance(error, (RunAlreadyExistsError, SessionAlreadyExistsError)):
        return HTTPStatus.CONFLICT
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
    if isinstance(error, SessionStorageError):
        return HTTPStatus.INTERNAL_SERVER_ERROR
    return HTTPStatus.INTERNAL_SERVER_ERROR


class YanAgentHTTPServer(ThreadingHTTPServer):
    """携带共享应用服务的线程 HTTP Server；每个请求仍由独立线程处理。"""

    daemon_threads = True

    def __init__(
        self, server_address: tuple[str, int], application: YanAgentApplication,
        database: Database | None = None,
    ) -> None:
        """保存应用和数据库服务，并启动唯一常驻异步运行环境。"""
        self.application = application
        self.database = database
        self.session_service = (
            DesktopSessionService(application.session_store)
            if application.session_store is not None
            else None
        )
        self.recovered_runs = application.recover_runs_on_startup()
        LOGGER.info(
            "[app.py][YanAgentHTTPServer.__init__] 启动 Run 恢复完成，中断数量=%d",
            self.recovered_runs,
        )
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

    @property
    def session_service(self) -> DesktopSessionService | None:
        """获取桌面会话适配服务；无数据库测试模式下返回空。"""
        return cast(YanAgentHTTPServer, self.server).session_service

    def _query_text(
        self,
        query: dict[str, list[str]],
        field: str,
        *,
        required: bool = False,
        maximum: int = 256,
    ) -> str | None:
        """读取单值查询参数，拒绝重复、空必填值和异常长度。"""
        values = query.get(field, [])
        if not values:
            if required:
                raise RequestValidationError(reason="missing", field=field)
            return None
        if len(values) != 1 or not values[0] or len(values[0]) > maximum:
            raise RequestValidationError(reason="invalid", field=field)
        return values[0]

    def _query_int(
        self,
        query: dict[str, list[str]],
        field: str,
        *,
        default: int | None = None,
        minimum: int = 0,
    ) -> int | None:
        """读取十进制整数查询参数，拒绝重复值和越界值。"""
        value = self._query_text(query, field)
        if value is None:
            return default
        try:
            parsed = int(value)
        except ValueError:
            raise RequestValidationError(reason="invalid", field=field) from None
        if str(parsed) != value or parsed < minimum:
            raise RequestValidationError(reason="invalid", field=field)
        return parsed

    def _validate_agent(self, value: Any, *, field: str = "agent_id") -> None:
        """限制桌面请求只能访问当前阶段唯一的 default Agent。"""
        if value not in (None, "", "default"):
            raise RequestValidationError(reason="unsupported", field=field)

    def _session_id_from_path(self, path: str, *, suffix: str = "") -> str:
        """从会话资源路径解码标识，并拒绝空标识或多余子路径。"""
        prefix = "/api/sessions/"
        if not path.startswith(prefix) or (suffix and not path.endswith(suffix)):
            raise RequestValidationError(reason="invalid", field="session_id")
        raw = path[len(prefix):]
        if suffix:
            raw = raw[:-len(suffix)]
        value = unquote(raw)
        if not value or "/" in value:
            raise RequestValidationError(reason="invalid", field="session_id")
        return value

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
        """处理 SSE、健康、模型配置以及桌面会话和历史只读接口。"""
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
                if self.session_service is None:
                    self._json(empty_sessions_payload())
                    return
                query = parse_qs(parsed.query, keep_blank_values=True)
                self._validate_agent(self._query_text(query, "agent_id"))
                scope = self._query_text(query, "scope")
                if scope not in (None, "all"):
                    raise RequestValidationError(reason="unsupported", field="scope")
                page = self._query_int(query, "page", default=1, minimum=1)
                page_size = self._query_int(query, "page_size", default=50, minimum=1)
                self._json(self.runtime.execute(self.session_service.list_sessions(
                    page=cast(int, page), page_size=cast(int, page_size),
                )))
                return
            if path == "/api/history/user_messages":
                query = parse_qs(parsed.query, keep_blank_values=True)
                session_id = self._query_text(query, "session_id", required=True)
                self._validate_agent(self._query_text(query, "agent_id"))
                if self.session_service is None:
                    self._json({"status": "success", "messages": [], "total": 0})
                    return
                self._json(self.runtime.execute(
                    self.session_service.user_messages(cast(str, session_id))
                ))
                return
            if path == "/api/history":
                query = parse_qs(parsed.query, keep_blank_values=True)
                session_id = self._query_text(query, "session_id", required=True)
                self._validate_agent(self._query_text(query, "agent_id"))
                page = self._query_int(query, "page", default=1, minimum=1)
                page_size = self._query_int(query, "page_size", default=20, minimum=1)
                until_sequence = self._query_int(query, "until_seq", minimum=0)
                if self.session_service is None:
                    self._json({
                        "status": "success", "messages": [], "total": 0,
                        "page": cast(int, page), "page_size": cast(int, page_size),
                        "has_more": False,
                    })
                    return
                self._json(self.runtime.execute(self.session_service.history(
                    cast(str, session_id),
                    page=cast(int, page),
                    page_size=cast(int, page_size),
                    until_sequence=until_sequence,
                )))
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
                self._json(self.application.tools_payload())
                return
            if path == "/api/skills":
                self._json({"status": "success", "skills": []})
                return
            if path == "/api/mcp/servers":
                self._json({"status": "success", "servers": []})
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
        """处理配置、模型、聊天、取消以及桌面标题和消息删除请求。"""
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
            if path.startswith("/api/sessions/") and path.endswith("/generate_title"):
                if self.session_service is None:
                    raise SessionStorageError()
                allowed = {"user_message", "assistant_reply", "agent_id"}
                if any(type(key) is not str or key not in allowed for key in payload):
                    raise RequestValidationError(reason="unknown_field", field="body")
                self._validate_agent(payload.get("agent_id"))
                user_message = payload.get("user_message")
                if (
                    type(user_message) is not str
                    or not user_message.strip()
                    or len(user_message) > 200_000
                ):
                    raise RequestValidationError(reason="invalid", field="user_message")
                assistant_reply = payload.get("assistant_reply")
                if assistant_reply is not None and type(assistant_reply) is not str:
                    raise RequestValidationError(reason="invalid", field="assistant_reply")
                session_id = self._session_id_from_path(path, suffix="/generate_title")
                self._json(self.runtime.execute(self.session_service.generate_title(
                    session_id, user_message,
                )))
                return
            if path == "/api/messages/delete":
                if self.session_service is None:
                    raise SessionStorageError()
                allowed = {"session_id", "user_seq", "delete_user", "cascade", "agent_id"}
                if any(type(key) is not str or key not in allowed for key in payload):
                    raise RequestValidationError(reason="unknown_field", field="body")
                self._validate_agent(payload.get("agent_id"))
                session_id = payload.get("session_id")
                user_sequence = payload.get("user_seq")
                delete_user = payload.get("delete_user", True)
                cascade = payload.get("cascade", False)
                if type(session_id) is not str or not session_id or len(session_id) > 256:
                    raise RequestValidationError(reason="invalid", field="session_id")
                if type(user_sequence) is not int or user_sequence < 0:
                    raise RequestValidationError(reason="invalid", field="user_seq")
                if type(delete_user) is not bool:
                    raise RequestValidationError(reason="invalid", field="delete_user")
                if type(cascade) is not bool:
                    raise RequestValidationError(reason="invalid", field="cascade")
                self._json(self.runtime.execute(self.session_service.delete_messages(
                    session_id,
                    user_sequence,
                    delete_user=delete_user,
                    cascade=cascade,
                )))
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

    def do_PUT(self) -> None:  # noqa: N802 - 标准库处理器约定的方法名
        """处理桌面会话重命名和置顶状态修改。"""
        path = urlparse(self.path).path
        try:
            if not path.startswith("/api/sessions/") or path.endswith("/generate_title"):
                self._json({
                    "status": "not_implemented",
                    "message": f"Scaffold endpoint not implemented: PUT {path}",
                }, HTTPStatus.NOT_IMPLEMENTED)
                return
            if self.session_service is None:
                raise SessionStorageError()
            payload = self._body()
            allowed = {"title", "pinned", "agent_id"}
            if any(type(key) is not str or key not in allowed for key in payload):
                raise RequestValidationError(reason="unknown_field", field="body")
            self._validate_agent(payload.get("agent_id"))
            has_title = "title" in payload
            has_pinned = "pinned" in payload
            if not has_title and not has_pinned:
                raise RequestValidationError(reason="missing", field="body")
            session_id = self._session_id_from_path(path)
            result: dict[str, Any] = {"status": "success"}
            if has_title:
                title = payload["title"]
                if type(title) is not str:
                    raise RequestValidationError(reason="invalid", field="title")
                result.update(self.runtime.execute(
                    self.session_service.rename(session_id, title)
                ))
            if has_pinned:
                pinned = payload["pinned"]
                if type(pinned) is not bool:
                    raise RequestValidationError(reason="invalid", field="pinned")
                result.update(self.runtime.execute(
                    self.session_service.set_pinned(session_id, pinned)
                ))
            self._json(result)
        except AgentError as error:
            self._error(error)

    def do_DELETE(self) -> None:  # noqa: N802 - 标准库处理器约定的方法名
        """取消会话活动运行后删除桌面会话及其全部持久化消息。"""
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if not path.startswith("/api/sessions/"):
                self._json({
                    "status": "not_implemented",
                    "message": f"Scaffold endpoint not implemented: DELETE {path}",
                }, HTTPStatus.NOT_IMPLEMENTED)
                return
            if self.session_service is None:
                raise SessionStorageError()
            query = parse_qs(parsed.query, keep_blank_values=True)
            self._validate_agent(self._query_text(query, "agent_id"))
            session_id = self._session_id_from_path(path)
            self.runtime.cancel(session_id=session_id)
            self._json(self.runtime.execute(self.session_service.delete(session_id)))
        except AgentError as error:
            self._error(error)


def create_server(
    host: str | None = None,
    port: int | None = None,
    *,
    application: YanAgentApplication | None = None,
    config_store: ConfigStore | None = None,
    provider_factory: ProviderFactory | None = None,
    database: Database | None = None,
) -> YanAgentHTTPServer:
    """根据配置创建服务；生产入口注入数据库时同时启用完整会话历史。"""
    if application is not None and (config_store is not None or provider_factory is not None):
        raise ValueError("application 与 config_store/provider_factory 不能同时传入")
    session_store = (
        SessionStore(database, user_id="local", agent_id="default")
        if application is None and database is not None
        else None
    )
    run_store = (
        RunStore(database, user_id="local", agent_id="default")
        if application is None and database is not None
        else None
    )
    app = application or YanAgentApplication(
        config_store,
        provider_factory=provider_factory,
        session_store=session_store,
        run_store=run_store,
    )
    ensure_application_ready(app)
    config = app.load_config()
    bind_host = config.host if host is None else host
    bind_port = config.port if port is None else port
    return YanAgentHTTPServer((bind_host, bind_port), app, database)


def main() -> None:
    """启动本地服务并在 SIGTERM 或 Ctrl+C 时关闭监听。"""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    database = Database()
    database_info = database.initialize()
    server = create_server(database=database)

    def stop_server(_signum: int, _frame: object) -> None:
        """处理桌面父进程终止信号，关闭监听并退出主循环。"""
        LOGGER.info("[app.py][main.stop_server] 收到终止信号，正在关闭服务")
        server.server_close()
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop_server)
    host, port = server.server_address[:2]
    LOGGER.info("[app.py][main] YanAgent 后端已启动：http://%s:%s", host, port)
    LOGGER.info(
        "[app.py][main] P02 数据库基础已就绪：schema_version=%d，文件=%s",
        database_info.schema_version,
        database_info.path,
    )
    LOGGER.info(
        "[app.py][main] 启动恢复已将遗留 Run 标记为中断：数量=%d",
        server.recovered_runs,
    )
    LOGGER.info(
        "[app.py][main] 当前能力：P01 单模型聊天；P02 会话持久化；P03 工具与权限基础"
    )
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        LOGGER.info("[app.py][main] YanAgent 后端已关闭")


if __name__ == "__main__":
    main()
