"""P02-03 完整历史、模型上下文与聊天持久化测试。"""

from __future__ import annotations

import asyncio
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import Request, urlopen

from app import create_server
from yanagent.chat import YanAgentApplication
from yanagent.config import ConfigStore
from yanagent.contracts import Message, ModelReply, ToolCall
from yanagent.errors import AuthenticationError
from yanagent.events import ModelStreamEvent
from yanagent.models import FakeProvider
from yanagent.sessions import RunStore, SessionStore
from yanagent.storage import Database


def _run(coroutine):
    """在同步 unittest 中运行一个短异步仓储或应用操作。"""
    return asyncio.run(coroutine)


class ChatHistoryTests(unittest.TestCase):
    """直接验证应用层装载历史、持久化回答和错误后的记录语义。"""

    def setUp(self) -> None:
        """创建隔离配置、数据库和默认会话仓储。"""
        project_root = Path(__file__).resolve().parents[1]
        self.temporary = tempfile.TemporaryDirectory(prefix=".yan-db-test-", dir=project_root)
        root = Path(self.temporary.name)
        self.config = ConfigStore(root / "config.json", environ={})
        self.config.save({
            "api_base": "https://example.invalid/v1",
            "model": "fake-model",
            "api_key": "fake-key",
        })
        self.database = Database(data_dir=root / "data", environ={})
        self.sessions = SessionStore(
            self.database, user_id="local", agent_id="default"
        )

    def tearDown(self) -> None:
        """删除当前测试产生的配置和 SQLite 文件。"""
        self.temporary.cleanup()

    def _application(self, fake: FakeProvider) -> YanAgentApplication:
        """创建注入真实 SessionStore 和可控模型的应用层。"""
        return YanAgentApplication(
            self.config,
            provider_factory=lambda _config: fake,
            session_store=self.sessions,
        )

    def test_two_turns_send_previous_history_and_persist_four_messages(self) -> None:
        """第二轮模型输入必须包含第一轮问答，并把两轮完整保存。"""
        fake = FakeProvider([
            ModelReply(content="好的，我记住了。", finish_reason="stop"),
            ModelReply(content="你叫张三。", finish_reason="stop"),
        ])
        application = self._application(fake)

        _run(application.chat({"session_id": "s1", "message": "我叫张三"}, request_id="r1"))
        result = _run(
            application.chat({"session_id": "s1", "message": "我叫什么？"}, request_id="r2")
        )

        self.assertEqual(result["inline_reply"], "你叫张三。")
        self.assertEqual((result["user_seq"], result["bot_seq"]), (2, 3))
        second_context = fake.calls[1].messages
        self.assertEqual(
            [(message.role, message.content) for message in second_context],
            [
                ("user", "我叫张三"),
                ("assistant", "好的，我记住了。"),
                ("user", "我叫什么？"),
            ],
        )
        history = _run(self.sessions.complete_history("s1"))
        self.assertEqual(
            [(item.sequence, item.message.role, item.message.content) for item in history],
            [
                (0, "user", "我叫张三"),
                (1, "assistant", "好的，我记住了。"),
                (2, "user", "我叫什么？"),
                (3, "assistant", "你叫张三。"),
            ],
        )
        self.assertEqual(history[0].message.metadata["request_id"], "r1")
        self.assertEqual(history[3].message.metadata["request_id"], "r2")

    def test_restart_and_other_session_keep_correct_context_boundaries(self) -> None:
        """重新打开数据库后仍加载旧历史，另一个 Session 不继承它。"""
        first = FakeProvider([ModelReply(content="已记录", finish_reason="stop")])
        _run(
            self._application(first).chat(
                {"session_id": "remember", "message": "我的代号是青山"}, request_id="r1"
            )
        )

        reopened_store = SessionStore(
            Database(data_dir=self.database.data_dir, environ={}),
            user_id="local",
            agent_id="default",
        )
        second = FakeProvider([
            ModelReply(content="你的代号是青山", finish_reason="stop"),
            ModelReply(content="我还不知道", finish_reason="stop"),
        ])
        reopened = YanAgentApplication(
            self.config,
            provider_factory=lambda _config: second,
            session_store=reopened_store,
        )
        _run(
            reopened.chat(
                {"session_id": "remember", "message": "我的代号是什么？"}, request_id="r2"
            )
        )
        _run(
            reopened.chat(
                {"session_id": "isolated", "message": "我的代号是什么？"}, request_id="r3"
            )
        )

        self.assertEqual(len(second.calls[0].messages), 3)
        self.assertEqual(
            [(item.role, item.content) for item in second.calls[1].messages],
            [("user", "我的代号是什么？")],
        )

    def test_model_failure_keeps_user_message_but_no_fake_assistant(self) -> None:
        """模型失败时保留用户事实，不伪造或保存不存在的 Assistant 回答。"""
        fake = FakeProvider([AuthenticationError()])
        application = self._application(fake)

        with self.assertRaises(AuthenticationError):
            _run(
                application.chat(
                    {"session_id": "failed", "message": "这次会失败"}, request_id="r-fail"
                )
            )

        history = _run(self.sessions.complete_history("failed"))
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].message.role, "user")
        self.assertEqual(history[0].message.content, "这次会失败")

    def test_complete_tool_round_is_restored_into_provider_context(self) -> None:
        """重启后的工具请求、结果引用和失败含义必须原样进入模型上下文。"""
        _run(self.sessions.create("tools"))
        _run(self.sessions.append("tools", [
            Message(role="user", content="读取天气"),
            Message(
                role="assistant",
                content="",
                tool_calls=[ToolCall(id="call-1", name="weather", arguments={"city": "北京"})],
            ),
            Message(
                role="tool",
                content="服务暂不可用",
                name="weather",
                tool_call_id="call-1",
                is_error=True,
            ),
            Message(role="assistant", content="天气服务暂不可用。"),
        ]))
        fake = FakeProvider([ModelReply(content="我可以稍后重试。", finish_reason="stop")])

        _run(
            self._application(fake).chat(
                {"session_id": "tools", "message": "那稍后再试"}, request_id="r-tool"
            )
        )

        context = fake.calls[0].messages
        self.assertEqual([item.role for item in context], [
            "user", "assistant", "tool", "assistant", "user",
        ])
        self.assertEqual(context[1].tool_calls[0].id, "call-1")
        self.assertEqual(context[2].tool_call_id, "call-1")
        self.assertTrue(context[2].is_error)

    def test_complete_history_is_not_silently_limited_to_one_page(self) -> None:
        """P02-03 必须读取完整历史，不能只取 SessionStore 的最近 500 条。"""
        _run(self.sessions.create("long"))
        _run(self.sessions.append(
            "long", [Message(role="user", content=f"历史-{index}") for index in range(501)]
        ))
        fake = FakeProvider([ModelReply(content="已收到", finish_reason="stop")])

        _run(
            self._application(fake).chat(
                {"session_id": "long", "message": "当前消息"}, request_id="r-long"
            )
        )

        self.assertEqual(len(fake.calls[0].messages), 502)
        self.assertEqual(fake.calls[0].messages[0].content, "历史-0")
        self.assertEqual(fake.calls[0].messages[-1].content, "当前消息")


class ChatHistoryHttpTests(unittest.TestCase):
    """验证生产创建路径下桌面 HTTP/SSE 会真实写库并复用历史。"""

    def setUp(self) -> None:
        """启动注入数据库与 Fake Provider 的真实回环 HTTP 服务。"""
        project_root = Path(__file__).resolve().parents[1]
        self.temporary = tempfile.TemporaryDirectory(prefix=".yan-db-test-", dir=project_root)
        root = Path(self.temporary.name)
        self.config = ConfigStore(root / "config.json", environ={})
        self.config.save({
            "api_base": "https://example.invalid/v1",
            "model": "fake-model",
            "api_key": "fake-key",
        })
        self.database = Database(data_dir=root / "data", environ={})
        self.fake = FakeProvider(
            [ModelReply(content="你是张三。", finish_reason="stop")],
            stream_outcomes=[[
                ModelStreamEvent(kind="text_delta", content="记住了"),
                ModelStreamEvent(
                    kind="completed",
                    reply=ModelReply(content="记住了", finish_reason="stop"),
                ),
            ]],
        )
        self.server = create_server(
            "127.0.0.1",
            0,
            config_store=self.config,
            provider_factory=lambda _config: self.fake,
            database=self.database,
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self) -> None:
        """关闭运行时、HTTP 线程并清理数据库。"""
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.temporary.cleanup()

    def _post(self, payload: dict[str, object]) -> dict[str, object]:
        """向桌面消息接口发送 UTF-8 JSON 并读取响应。"""
        request = Request(
            self.base_url + "/message",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urlopen(request, timeout=3) as response:
            return json.loads(response.read().decode("utf-8"))

    def test_stream_then_inline_share_persisted_session_history(self) -> None:
        """流式完成先落库，下一次普通请求能通过同一 Session 读取该历史。"""
        first = self._post({
            "session_id": "desktop-history",
            "message": "你好，我是张三",
            "stream": True,
            "attachments": [],
            "is_voice": False,
            "agent_id": "default",
        })
        with urlopen(
            self.base_url + f"/stream?request_id={first['request_id']}", timeout=3
        ) as response:
            events = [
                json.loads(line[6:])
                for line in response.read().decode("utf-8").splitlines()
                if line.startswith("data: ")
            ]
        self.assertEqual(events[-1]["type"], "done")
        self.assertEqual((events[-1]["user_seq"], events[-1]["bot_seq"]), (0, 1))

        second = self._post({
            "session_id": "desktop-history",
            "message": "我是谁？",
            "stream": False,
            "attachments": [],
            "is_voice": False,
            "agent_id": "default",
        })
        self.assertEqual(second["inline_reply"], "你是张三。")
        self.assertEqual(
            [(item.role, item.content) for item in self.fake.calls[1].messages],
            [
                ("user", "你好，我是张三"),
                ("assistant", "记住了"),
                ("user", "我是谁？"),
            ],
        )
        store = SessionStore(self.database, user_id="local", agent_id="default")
        history = _run(store.complete_history("desktop-history"))
        self.assertEqual([item.message.role for item in history], [
            "user", "assistant", "user", "assistant",
        ])
        runs = RunStore(self.database, user_id="local", agent_id="default")
        first_run = _run(runs.get(str(first["request_id"]), "desktop-history"))
        second_run = _run(runs.get(str(second["request_id"]), "desktop-history"))
        self.assertEqual(first_run.status, "completed")
        self.assertEqual(second_run.status, "completed")
        self.assertEqual(first_run.session_id, "desktop-history")
        self.assertEqual(second_run.session_id, "desktop-history")
        self.assertIsNotNone(first_run.finished_at)
        self.assertIsNotNone(second_run.finished_at)


if __name__ == "__main__":
    unittest.main()
