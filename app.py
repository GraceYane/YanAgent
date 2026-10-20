"""YanAgent 学习脚手架的最小 HTTP 服务外壳。

本文件有意不包含 Agent 执行循环，只负责让复制过来的桌面客户端能够启动。
真正的 Agent Runtime 需要在 ``yanagent/`` 目录下逐步实现。
"""

from __future__ import annotations

import json
import os
import signal
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse


NOT_IMPLEMENTED_REPLY = (
    "YanAgent 的界面与后端骨架已经运行成功，但 Agent Runtime 被有意移除了。\n\n"
    "请从 `yanagent/runtime/agent_loop.py` 开始实现模型调用、工具循环和最终回复。"
)


def _empty_capability() -> dict[str, Any]:
    return {"current_provider": "", "current_model": "", "providers": []}


def health_payload() -> dict[str, str]:
    return {
        "status": "ok",
        "name": "YanAgent",
        "edition": "core-runtime-scaffold",
        "agent_runtime": "not_implemented",
    }


def empty_sessions_payload() -> dict[str, Any]:
    return {
        "status": "success",
        "sessions": [],
        "total": 0,
        "page": 1,
        "page_size": 50,
        "has_more": False,
        "group_mode": "time",
        "project_order": [],
    }


class YanAgentHandler(BaseHTTPRequestHandler):
    server_version = "YanAgentScaffold/0.1"

    def log_message(self, fmt: str, *args: object) -> None:
        print("[yanagent] " + (fmt % args), flush=True)

    def _json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length else b"{}"
            value = json.loads(raw.decode("utf-8"))
            return value if isinstance(value, dict) else {}
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            return {}

    def do_OPTIONS(self) -> None:  # noqa: N802 - 标准库处理器约定的方法名
        self._json({"status": "ok"})

    def do_GET(self) -> None:  # noqa: N802 - 标准库处理器约定的方法名
        path = urlparse(self.path).path

        if path in {"/", "/api/health"}:
            self._json(health_payload())
            return

        if path == "/auth/check":
            self._json({"status": "success", "auth_required": False, "authenticated": True})
            return

        if path == "/api/agents":
            self._json(
                {
                    "status": "success",
                    "default_agent_id": "default",
                    "agents": [{"id": "default", "name": "YanAgent", "enabled": True}],
                    "channel_instances": [],
                    "revision": "scaffold",
                }
            )
            return

        if path == "/api/sessions":
            self._json(empty_sessions_payload())
            return

        if path == "/api/history":
            self._json(
                {
                    "status": "success",
                    "messages": [],
                    "total": 0,
                    "page": 1,
                    "page_size": 20,
                    "has_more": False,
                }
            )
            return

        if path == "/api/menu":
            self._json({"status": "success", "menu": None})
            return

        if path == "/api/models":
            capabilities = {
                key: _empty_capability()
                for key in ("chat", "vision", "asr", "tts", "embedding", "image")
            }
            capabilities["search"] = {"current_provider": "", "providers": []}
            self._json({"status": "success", "providers": [], "capabilities": capabilities})
            return

        if path == "/api/config":
            self._json({"status": "success", "config": {"app_name": "YanAgent"}})
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

        self._json(
            {
                "status": "not_implemented",
                "message": f"Scaffold endpoint not implemented: GET {path}",
            },
            HTTPStatus.NOT_IMPLEMENTED,
        )

    def do_POST(self) -> None:  # noqa: N802 - 标准库处理器约定的方法名
        path = urlparse(self.path).path
        payload = self._body()

        if path == "/message":
            self._json(
                {
                    "status": "not_implemented",
                    "request_id": f"stub-{uuid.uuid4().hex}",
                    "stream": False,
                    "inline_reply": NOT_IMPLEMENTED_REPLY,
                    "received_session_id": payload.get("session_id", ""),
                }
            )
            return

        if path == "/poll":
            self._json({"status": "success", "has_content": False})
            return

        if path == "/cancel":
            self._json({"status": "success", "cancelled": 0})
            return

        self._json(
            {
                "status": "not_implemented",
                "message": f"Scaffold endpoint not implemented: POST {path}",
            },
            HTTPStatus.NOT_IMPLEMENTED,
        )


def create_server(host: str | None = None, port: int | None = None) -> ThreadingHTTPServer:
    bind_host = host or os.getenv("YAN_WEB_HOST", "127.0.0.1")
    bind_port = port if port is not None else int(
        os.getenv("YAN_WEB_PORT") or os.getenv("COW_WEB_PORT") or "9876"
    )
    return ThreadingHTTPServer((bind_host, bind_port), YanAgentHandler)


def main() -> None:
    server = create_server()

    def stop_server(_signum: int, _frame: object) -> None:
        server.server_close()
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop_server)
    host, port = server.server_address[:2]
    print(f"YanAgent scaffold backend: http://{host}:{port}", flush=True)
    print("Core Agent runtime is intentionally not implemented.", flush=True)
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
