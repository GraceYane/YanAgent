"""P02-04 桌面会话列表、历史、索引、重命名与删除 HTTP 联调测试。"""

from __future__ import annotations

import asyncio
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app import create_server
from yanagent.config import ConfigStore
from yanagent.contracts import Message
from yanagent.models import FakeProvider
from yanagent.sessions import SessionStore
from yanagent.storage import Database


def _run(coroutine):
    """在同步 HTTP 测试准备阶段执行短仓储协程。"""
    return asyncio.run(coroutine)


class DesktopSessionHttpTests(unittest.TestCase):
    """通过真实回环 HTTP 验证复制桌面与 SQLite 的会话管理闭环。"""

    def setUp(self) -> None:
        """建立独立数据库，写入三轮历史并启动本地服务。"""
        project_root = Path(__file__).resolve().parents[1]
        self.temporary = tempfile.TemporaryDirectory(prefix=".yan-db-test-", dir=project_root)
        root = Path(self.temporary.name)
        self.config = ConfigStore(root / "config.json", environ={})
        self.database = Database(data_dir=root / "data", environ={})
        self.store = SessionStore(self.database, user_id="local", agent_id="default")
        _run(self.store.create("desktop", title="旧标题"))
        _run(self.store.append("desktop", [
            Message(role="user", content="第一问"),
            Message(role="assistant", content="第一答"),
            Message(role="user", content="第二问"),
            Message(role="assistant", content="第二答"),
            Message(role="user", content="第三问"),
            Message(role="assistant", content="第三答"),
        ]))
        hidden = SessionStore(self.database, user_id="other", agent_id="default")
        _run(hidden.create("hidden-only", title="其他用户会话"))
        _run(hidden.append(
            "hidden-only", [Message(role="user", content="不可泄露的内容")]
        ))
        self.server = create_server(
            "127.0.0.1",
            0,
            config_store=self.config,
            provider_factory=lambda _config: FakeProvider([]),
            database=self.database,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self) -> None:
        """关闭服务和运行时，并删除隔离数据库。"""
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.temporary.cleanup()

    def _request(
        self,
        path: str,
        *,
        method: str = "GET",
        payload: dict[str, object] | None = None,
    ) -> tuple[int, dict[str, object]]:
        """发送一次 JSON 请求，并把成功或错误响应统一解码。"""
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(
            self.base_url + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=3) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            with error:
                return error.code, json.loads(error.read().decode("utf-8"))

    def test_list_history_and_user_index_match_desktop_contract(self) -> None:
        """列表时间单位、历史页方向、跳转扩页和用户索引均符合桌面类型。"""
        status, sessions = self._request("/api/sessions?page=1&page_size=50&scope=all")
        self.assertEqual(status, 200)
        self.assertEqual(sessions["sessions"][0]["session_id"], "desktop")
        self.assertEqual(sessions["sessions"][0]["msg_count"], 6)
        self.assertIsInstance(sessions["sessions"][0]["created_at"], float)

        query = urlencode({"session_id": "desktop", "page": 1, "page_size": 2})
        _, recent = self._request(f"/api/history?{query}")
        self.assertEqual([item["_seq"] for item in recent["messages"]], [4, 5])
        expanded_query = query + "&until_seq=0"
        _, expanded = self._request(f"/api/history?{expanded_query}")
        self.assertEqual([item["_seq"] for item in expanded["messages"]], list(range(6)))
        self.assertEqual(expanded["page"], 3)

        _, index = self._request("/api/history/user_messages?session_id=desktop")
        self.assertEqual([item["seq"] for item in index["messages"]], [0, 2, 4])
        self.assertEqual([item["preview"] for item in index["messages"]], [
            "第一问", "第二问", "第三问",
        ])

    def test_rename_pin_generate_title_and_delete_session(self) -> None:
        """桌面会话管理动作会真实修改数据库，标题可早于首轮消息创建。"""
        _, renamed = self._request(
            "/api/sessions/desktop", method="PUT", payload={"title": "新标题"},
        )
        self.assertEqual(renamed["title"], "新标题")
        _, pinned = self._request(
            "/api/sessions/desktop", method="PUT", payload={"pinned": True},
        )
        self.assertTrue(pinned["pinned"])

        _, generated = self._request(
            "/api/sessions/early/generate_title",
            method="POST",
            payload={"user_message": "  请   帮我制定一个学习计划  "},
        )
        self.assertEqual(generated["title"], "请 帮我制定一个学习计划")
        self.assertEqual(_run(self.store.get("early")).message_count, 0)

        status, deleted = self._request("/api/sessions/desktop", method="DELETE")
        self.assertEqual(status, 200)
        self.assertTrue(deleted["deleted"])
        missing_status, _ = self._request("/api/history?session_id=desktop")
        self.assertEqual(missing_status, 404)

    def test_message_delete_cascades_and_rejects_non_user_sequence(self) -> None:
        """重新生成式删除会截断后续上下文，非用户序号返回可识别的 404。"""
        status, result = self._request(
            "/api/messages/delete",
            method="POST",
            payload={
                "session_id": "desktop",
                "user_seq": 2,
                "delete_user": True,
                "cascade": True,
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(result["deleted"], 4)
        self.assertEqual(
            [item.sequence for item in _run(self.store.history("desktop"))], [0, 1]
        )
        missing_status, missing = self._request(
            "/api/messages/delete",
            method="POST",
            payload={"session_id": "desktop", "user_seq": 1},
        )
        self.assertEqual(missing_status, 404)
        self.assertEqual(missing["error"]["code"], "message_not_found")

    def test_http_cannot_read_another_users_session(self) -> None:
        """即使猜中 session_id，桌面接口也不能列出或读取其他用户的数据。"""
        _, sessions = self._request("/api/sessions?page=1&page_size=50&scope=all")
        self.assertNotIn(
            "hidden-only", [item["session_id"] for item in sessions["sessions"]]
        )
        status, result = self._request("/api/history?session_id=hidden-only")
        self.assertEqual(status, 404)
        self.assertEqual(result["error"]["code"], "session_not_found")
        self.assertNotIn("不可泄露的内容", json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
