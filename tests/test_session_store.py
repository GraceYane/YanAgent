"""P02-02 会话 CRUD、消息事务、分页、隔离与重启持久化测试。"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from yanagent.contracts import Message, ToolCall
from yanagent.errors import (
    MessageNotFoundError,
    SessionAlreadyExistsError,
    SessionNotFoundError,
    SessionStorageError,
    SessionValidationError,
)
from yanagent.sessions import SessionStore
from yanagent.storage import Database


class FakeClock:
    """提供可预测且递增的毫秒时间，便于断言列表排序和更新时间。"""

    def __init__(self, start: int = 1_000) -> None:
        """保存首个将要返回的时间戳。"""
        self.value = start

    def __call__(self) -> int:
        """返回当前时间戳并为下一次调用递增一毫秒。"""
        current = self.value
        self.value += 1
        return current


class SessionStoreTests(unittest.IsolatedAsyncioTestCase):
    """验证 P02-02 已实现的仓储行为，不依赖桌面、密钥或公网。"""

    def setUp(self) -> None:
        """为每个测试建立独立数据库和固定身份仓储。"""
        project_root = Path(__file__).resolve().parents[1]
        self.temporary = tempfile.TemporaryDirectory(prefix=".yan-db-test-", dir=project_root)
        self.data_dir = Path(self.temporary.name) / "data"
        self.database = Database(data_dir=self.data_dir, environ={})
        self.clock = FakeClock()
        self.store = SessionStore(
            self.database,
            user_id="user-a",
            agent_id="agent-a",
            clock=self.clock,
        )

    def tearDown(self) -> None:
        """删除当前测试创建的 SQLite 文件。"""
        self.temporary.cleanup()

    async def test_create_get_and_duplicate_detection(self) -> None:
        """会话创建后可读取，重复标识会返回明确错误。"""
        created = await self.store.create(
            "session-a", title=" 第一段对话 ", metadata={"channel": "desktop"}
        )
        self.assertEqual(created.title, "第一段对话")
        self.assertEqual(created.metadata, {"channel": "desktop"})
        self.assertEqual(created.message_count, 0)
        self.assertEqual(await self.store.get("session-a"), created)
        with self.assertRaises(SessionAlreadyExistsError):
            await self.store.create("session-a")

    async def test_list_is_scoped_paginated_and_stably_sorted(self) -> None:
        """列表只显示当前作用域，并按置顶、更新时间稳定分页。"""
        await self.store.create("a", title="A")
        await self.store.create("b", title="B")
        await self.store.create("c", title="C")
        await self.store.set_pinned("a", True)
        other = SessionStore(
            self.database, user_id="user-b", agent_id="agent-a", clock=self.clock
        )
        await other.create("hidden", title="不可见")
        other_agent = SessionStore(
            self.database, user_id="user-a", agent_id="agent-b", clock=self.clock
        )
        await other_agent.create("hidden-agent", title="也不可见")

        first = await self.store.list_sessions(page=1, page_size=2)
        second = await self.store.list_sessions(page=2, page_size=2)
        self.assertEqual([item.session_id for item in first.sessions], ["a", "c"])
        self.assertEqual([item.session_id for item in second.sessions], ["b"])
        self.assertEqual(first.total, 3)
        self.assertTrue(first.has_more)
        self.assertFalse(second.has_more)

    async def test_rename_and_pin_preserve_metadata(self) -> None:
        """重命名和置顶只修改目标属性，不覆盖会话扩展元数据。"""
        await self.store.create("s", title="旧标题", metadata={"source": "test"})
        renamed = await self.store.rename("s", "新标题")
        pinned = await self.store.set_pinned("s", True)
        self.assertEqual(renamed.title, "新标题")
        self.assertEqual(pinned.title, "新标题")
        self.assertTrue(pinned.pinned)
        self.assertEqual(pinned.metadata, {"source": "test"})

    async def test_upsert_title_creates_missing_session_and_preserves_messages(self) -> None:
        """自动标题可先于首条消息创建会话，后续更新不会覆盖已有消息。"""
        created = await self.store.upsert_title("early", "首轮标题")
        self.assertEqual(created.title, "首轮标题")
        self.assertEqual(created.metadata, {"created_by": "desktop-title"})
        await self.store.append("early", [Message(role="user", content="你好")])
        updated = await self.store.upsert_title("early", "修改后的标题")
        self.assertEqual(updated.title, "修改后的标题")
        self.assertEqual(updated.message_count, 1)
        self.assertEqual((await self.store.history("early"))[0].message.content, "你好")

    async def test_append_round_trips_complete_tool_messages(self) -> None:
        """消息往返必须保留工具调用对象、调用关联、元数据和失败语义。"""
        await self.store.create("s")
        messages = [
            Message(role="user", content="计算 1+2", metadata={"source": "desktop"}),
            Message(
                role="assistant",
                content="",
                tool_calls=[ToolCall(id="call-1", name="calculator", arguments={"x": 1})],
            ),
            Message(
                role="tool",
                content="计算器暂时不可用",
                name="calculator",
                tool_call_id="call-1",
                is_error=True,
            ),
            Message(role="assistant", content="工具调用失败，请稍后再试。"),
        ]
        stored = await self.store.append("s", messages)
        loaded = await self.store.history("s")
        self.assertEqual([item.sequence for item in stored], [0, 1, 2, 3])
        self.assertEqual([item.sequence for item in loaded], [0, 1, 2, 3])
        self.assertEqual(
            [item.message.to_dict() for item in loaded],
            [message.to_dict() for message in messages],
        )
        self.assertEqual((await self.store.get("s")).message_count, 4)

    async def test_history_uses_exclusive_sequence_cursor(self) -> None:
        """历史页返回最近消息但保持升序，游标消息不会在下一页重复。"""
        await self.store.create("s")
        await self.store.append(
            "s", [Message(role="user", content=f"消息-{index}") for index in range(5)]
        )
        recent = await self.store.history("s", limit=2)
        older = await self.store.history("s", limit=2, before_sequence=recent[0].sequence)
        self.assertEqual([item.sequence for item in recent], [3, 4])
        self.assertEqual([item.sequence for item in older], [1, 2])

    async def test_desktop_history_can_expand_to_target_user_message(self) -> None:
        """桌面历史可从当前页一次扩展到包含指定序号的更早页面。"""
        await self.store.create("s")
        await self.store.append(
            "s", [Message(role="user", content=f"消息-{index}") for index in range(7)]
        )
        recent = await self.store.history_page("s", page=1, page_size=2)
        expanded = await self.store.history_page(
            "s", page=1, page_size=2, until_sequence=1,
        )
        self.assertEqual([item.sequence for item in recent.messages], [5, 6])
        self.assertEqual([item.sequence for item in expanded.messages], [1, 2, 3, 4, 5, 6])
        self.assertEqual(expanded.page, 3)
        self.assertTrue(expanded.has_more)

    async def test_user_index_and_turn_deletion_rules(self) -> None:
        """用户索引只含用户消息，单轮删除与级联截断遵守明确边界。"""
        await self.store.create("s")
        await self.store.append("s", [
            Message(role="user", content="第一问"),
            Message(role="assistant", content="第一答"),
            Message(role="user", content="第二问"),
            Message(role="assistant", content="第二答"),
            Message(role="user", content="第三问"),
            Message(role="assistant", content="第三答"),
        ])
        index = await self.store.user_message_index("s")
        self.assertEqual([item.sequence for item in index], [0, 2, 4])

        deleted = await self.store.delete_turn("s", 2, cascade=False)
        self.assertEqual(deleted, 2)
        self.assertEqual(
            [item.sequence for item in await self.store.history("s")], [0, 1, 4, 5]
        )
        deleted = await self.store.delete_turn("s", 4, cascade=True)
        self.assertEqual(deleted, 2)
        self.assertEqual(
            [item.sequence for item in await self.store.history("s")], [0, 1]
        )
        self.assertEqual((await self.store.get("s")).message_count, 2)
        with self.assertRaises(MessageNotFoundError):
            await self.store.delete_turn("s", 1)

    async def test_append_failure_rolls_back_entire_batch(self) -> None:
        """批次第二条消息写入失败时，第一条和消息计数也必须回滚。"""
        duplicate_ids = SessionStore(
            self.database,
            user_id="user-a",
            agent_id="agent-a",
            clock=self.clock,
            message_id_factory=lambda: "same-message-id",
        )
        await duplicate_ids.create("s")
        with self.assertRaises(SessionStorageError):
            await duplicate_ids.append(
                "s",
                [Message(role="user", content="一"), Message(role="assistant", content="二")],
            )
        self.assertEqual(await duplicate_ids.history("s"), [])
        self.assertEqual((await duplicate_ids.get("s")).message_count, 0)

    async def test_concurrent_writers_allocate_unique_sequences(self) -> None:
        """多个仓储并发追加时，事务仍分配唯一连续序号并保持准确计数。"""
        await self.store.create("concurrent")
        second = SessionStore(
            self.database,
            user_id="user-a",
            agent_id="agent-a",
            clock=self.clock,
        )

        async def append_one(index: int):
            """交替使用两个仓储连接写入一条可识别消息。"""
            selected = self.store if index % 2 == 0 else second
            return await selected.append(
                "concurrent", [Message(role="user", content=f"并发消息-{index}")]
            )

        batches = await asyncio.gather(*(append_one(index) for index in range(20)))
        records = await self.store.complete_history("concurrent")

        self.assertEqual(
            sorted(batch[0].sequence for batch in batches), list(range(20))
        )
        self.assertEqual([record.sequence for record in records], list(range(20)))
        self.assertEqual(
            {record.message.content for record in records},
            {f"并发消息-{index}" for index in range(20)},
        )
        self.assertEqual((await self.store.get("concurrent")).message_count, 20)

    async def test_delete_cascades_without_crossing_user_scope(self) -> None:
        """删除只影响当前用户会话，并级联删除其消息。"""
        await self.store.create("shared")
        await self.store.append("shared", [Message(role="user", content="用户 A")])
        other = SessionStore(
            self.database, user_id="user-b", agent_id="agent-a", clock=self.clock
        )
        await other.create("shared")
        await other.append("shared", [Message(role="user", content="用户 B")])

        await self.store.delete("shared")
        with self.assertRaises(SessionNotFoundError):
            await self.store.get("shared")
        self.assertEqual((await other.history("shared"))[0].message.content, "用户 B")
        with self.database.connection() as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM messages WHERE user_id = 'user-a'"
            ).fetchone()[0]
        self.assertEqual(count, 0)

    async def test_reopen_preserves_sessions_and_messages(self) -> None:
        """关闭并重新建立数据库对象后，会话和消息仍能完整读取。"""
        await self.store.create("s", title="可恢复")
        await self.store.append("s", [Message(role="user", content="重启后仍存在")])
        reopened = SessionStore(
            Database(data_dir=self.data_dir, environ={}),
            user_id="user-a",
            agent_id="agent-a",
        )
        self.assertEqual((await reopened.get("s")).title, "可恢复")
        self.assertEqual((await reopened.history("s"))[0].message.content, "重启后仍存在")

    async def test_invalid_and_missing_inputs_return_safe_errors(self) -> None:
        """非法分页、空批次和不存在会话均返回统一错误，不泄露原始 SQL。"""
        with self.assertRaises(SessionValidationError):
            await self.store.list_sessions(page=0)
        with self.assertRaises(SessionValidationError):
            await self.store.append("s", [])
        with self.assertRaises(SessionValidationError):
            await self.store.rename("s", "   ")
        with self.assertRaises(SessionValidationError):
            await self.store.create("伪造\n日志")
        with self.assertRaises(SessionNotFoundError):
            await self.store.get("missing")


if __name__ == "__main__":
    unittest.main()
