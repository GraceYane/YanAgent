"""P02-05 Run 归属、终态转换与启动恢复测试。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app import create_server
from yanagent.chat import YanAgentApplication
from yanagent.config import ConfigStore
from yanagent.errors import (
    AuthenticationError,
    RunAlreadyExistsError,
    SessionNotFoundError,
)
from yanagent.models import FakeProvider
from yanagent.sessions import RunStore, SessionStore
from yanagent.storage import Database


class FakeClock:
    """提供递增的确定性毫秒时间，便于验证 Run 生命周期字段。"""

    def __init__(self, start: int = 10_000) -> None:
        """保存下一次返回的毫秒值。"""
        self.value = start

    def __call__(self) -> int:
        """返回当前值并递增一毫秒。"""
        current = self.value
        self.value += 1
        return current


class RunStoreTests(unittest.IsolatedAsyncioTestCase):
    """验证 Run 只在可信作用域内可见，并且终态只写入一次。"""

    def setUp(self) -> None:
        """建立隔离数据库、默认 Session 和确定性 RunStore。"""
        project_root = Path(__file__).resolve().parents[1]
        self.temporary = tempfile.TemporaryDirectory(
            prefix=".yan-db-test-", dir=project_root
        )
        self.database = Database(data_dir=Path(self.temporary.name) / "data", environ={})
        self.clock = FakeClock()
        self.sessions = SessionStore(
            self.database, user_id="user-a", agent_id="agent-a", clock=self.clock
        )
        self.runs = RunStore(
            self.database, user_id="user-a", agent_id="agent-a", clock=self.clock
        )

    def tearDown(self) -> None:
        """删除测试创建的 SQLite 文件。"""
        self.temporary.cleanup()

    async def test_create_finish_and_duplicate_are_deterministic(self) -> None:
        """活动 Run 可完成一次，重复完成无效，重复标识得到明确冲突。"""
        await self.sessions.create("session-a")
        created = await self.runs.create(
            "run-a", "session-a", metadata={"provider": "fake"}
        )
        self.assertEqual(created.status, "running")
        self.assertEqual(created.metadata, {"provider": "fake"})

        changed = await self.runs.finish(
            "run-a",
            "session-a",
            status="completed",
            finish_reason="stop",
            usage={"input_tokens": 2, "output_tokens": 3},
        )
        self.assertTrue(changed)
        self.assertFalse(await self.runs.finish("run-a", "session-a", status="failed"))
        stored = await self.runs.get("run-a", "session-a")
        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(stored.status, "completed")
        self.assertEqual(stored.finish_reason, "stop")
        self.assertEqual(stored.usage, {"input_tokens": 2, "output_tokens": 3})
        self.assertIsNotNone(stored.finished_at)

        with self.assertRaises(RunAlreadyExistsError):
            await self.runs.create("run-a", "session-a")

    async def test_complete_ownership_prevents_cross_scope_access(self) -> None:
        """不同用户或 Agent 无法读取、结束或挂靠另一个作用域的 Run。"""
        await self.sessions.create("shared")
        await self.runs.create("owned-run", "shared")
        other_user = RunStore(
            self.database, user_id="user-b", agent_id="agent-a", clock=self.clock
        )
        other_agent = RunStore(
            self.database, user_id="user-a", agent_id="agent-b", clock=self.clock
        )

        self.assertIsNone(await other_user.get("owned-run", "shared"))
        self.assertIsNone(await other_agent.get("owned-run", "shared"))
        self.assertIsNone(await self.runs.get("owned-run", "wrong-session"))
        self.assertFalse(await other_user.finish("owned-run", "shared", status="failed"))
        self.assertFalse(await self.runs.finish("owned-run", "wrong-session", status="failed"))
        with self.assertRaises(SessionNotFoundError):
            await other_user.create("foreign-run", "shared")
        self.assertEqual((await self.runs.get("owned-run", "shared")).status, "running")

    async def test_startup_recovery_only_interrupts_owned_active_runs(self) -> None:
        """恢复仅中断当前作用域的 queued/running，保留终态和其他归属。"""
        await self.sessions.create("session-a")
        await self.runs.create("queued", "session-a", status="queued")
        await self.runs.create("running", "session-a")
        await self.runs.create("completed", "session-a")
        await self.runs.finish(
            "completed", "session-a", status="completed", finish_reason="stop"
        )

        foreign_sessions = SessionStore(
            self.database, user_id="user-b", agent_id="agent-a", clock=self.clock
        )
        foreign_runs = RunStore(
            self.database, user_id="user-b", agent_id="agent-a", clock=self.clock
        )
        await foreign_sessions.create("session-b")
        await foreign_runs.create("foreign-running", "session-b")

        self.assertEqual(self.runs.recover_unfinished_on_startup(), 2)
        for request_id in ("queued", "running"):
            recovered = await self.runs.get(request_id, "session-a")
            assert recovered is not None
            self.assertEqual(recovered.status, "interrupted")
            self.assertEqual(recovered.finish_reason, "process_restarted")
            self.assertEqual(recovered.error_code, "run_interrupted")
            self.assertIsNotNone(recovered.finished_at)
        self.assertEqual(
            (await self.runs.get("completed", "session-a")).status, "completed"
        )
        self.assertEqual(
            (await foreign_runs.get("foreign-running", "session-b")).status, "running"
        )
        self.assertEqual(self.runs.recover_unfinished_on_startup(), 0)

    async def test_provider_failure_persists_failed_run(self) -> None:
        """模型失败时保留用户消息，并把对应 Run 结束为带错误码的 failed。"""
        config = ConfigStore(Path(self.temporary.name) / "config.json", environ={})
        config.save({
            "api_base": "https://example.invalid/v1",
            "model": "fake-model",
            "api_key": "fake-key",
        })
        application = YanAgentApplication(
            config,
            provider_factory=lambda _config: FakeProvider([AuthenticationError()]),
            session_store=self.sessions,
            run_store=self.runs,
        )

        with self.assertRaises(AuthenticationError):
            await application.chat(
                {"session_id": "failed-session", "message": "你好"},
                request_id="failed-run",
            )
        failed = await self.runs.get("failed-run", "failed-session")
        assert failed is not None
        self.assertEqual(failed.status, "failed")
        self.assertEqual(failed.finish_reason, "error")
        self.assertEqual(failed.error_code, "authentication_error")

    async def test_server_recovers_unfinished_runs_before_accepting_traffic(self) -> None:
        """HTTP Server 构造完成前会恢复默认作用域遗留 Run，并报告恢复数量。"""
        local_sessions = SessionStore(
            self.database, user_id="local", agent_id="default", clock=self.clock
        )
        local_runs = RunStore(
            self.database, user_id="local", agent_id="default", clock=self.clock
        )
        await local_sessions.create("restart-session")
        await local_runs.create("restart-run", "restart-session")
        config = ConfigStore(Path(self.temporary.name) / "startup-config.json", environ={})

        server = create_server(
            "127.0.0.1",
            0,
            config_store=config,
            provider_factory=lambda _config: FakeProvider([]),
            database=self.database,
        )
        try:
            self.assertEqual(server.recovered_runs, 1)
        finally:
            server.server_close()
        recovered = await local_runs.get("restart-run", "restart-session")
        assert recovered is not None
        self.assertEqual(recovered.status, "interrupted")
        self.assertEqual(recovered.error_code, "run_interrupted")


if __name__ == "__main__":
    unittest.main()
