"""P02-01 数据目录、SQLite Schema、迁移与约束测试。"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import yanagent.storage.database as database_module
from yanagent.storage import (
    CURRENT_SCHEMA_VERSION,
    Database,
    DatabaseInitializationError,
    UnsupportedSchemaVersionError,
    resolve_data_dir,
)
from yanagent.storage.database import Migration


class DataDirectoryTests(unittest.TestCase):
    """验证 YanAgent 数据目录与 CowAgent 环境完全隔离。"""

    def test_default_directory_uses_yanagent_home(self) -> None:
        """没有专属覆盖时固定使用用户目录下的 .yanagent。"""
        home = Path("C:/example-home")
        result = resolve_data_dir(environ={}, home=home)
        self.assertEqual(result, (home / ".yanagent").resolve())

    def test_yanagent_environment_override_wins(self) -> None:
        """专属环境变量允许桌面和测试显式选择可写目录。"""
        root = Path.cwd() / ".directory-resolution-test"
        selected = root / "custom-data"
        result = resolve_data_dir(
            environ={"YANAGENT_DATA_DIR": str(selected)},
            home=root / "home",
        )
        self.assertEqual(result, selected.resolve())

    def test_cowagent_environment_is_ignored(self) -> None:
        """即使存在 COW_DATA_DIR，也不能读取 CowAgent 的目录。"""
        root = Path.cwd() / ".directory-resolution-test"
        home = root / "home"
        cow = root / ".cow"
        result = resolve_data_dir(environ={"COW_DATA_DIR": str(cow)}, home=home)
        self.assertEqual(result, (home / ".yanagent").resolve())
        self.assertNotEqual(result, cow.resolve())


class DatabaseSchemaTests(unittest.TestCase):
    """验证首版数据库创建、幂等、约束和迁移失败语义。"""

    def setUp(self) -> None:
        """为每个测试建立独立临时数据库。"""
        project_root = Path(__file__).resolve().parents[1]
        self.temporary = tempfile.TemporaryDirectory(prefix=".yan-db-test-", dir=project_root)
        self.data_dir = Path(self.temporary.name) / "yanagent-data"
        self.database = Database(data_dir=self.data_dir, environ={})

    def tearDown(self) -> None:
        """关闭测试作用域并删除临时数据库。"""
        self.temporary.cleanup()

    def test_initialize_creates_four_tables_and_version(self) -> None:
        """首次初始化必须建立四张目标表并登记全部 Schema 迁移。"""
        info = self.database.initialize()
        self.assertEqual(info.schema_version, CURRENT_SCHEMA_VERSION)
        self.assertEqual(info.path, self.data_dir.resolve() / "yanagent.db")
        self.assertTrue(info.path.is_file())
        with self.database.connection() as connection:
            tables = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            self.assertTrue({"sessions", "messages", "runs", "schema_migrations"} <= tables)
            migrations = connection.execute(
                "SELECT version, name, checksum FROM schema_migrations ORDER BY version"
            ).fetchall()
            self.assertEqual(
                [row["version"] for row in migrations],
                list(range(1, CURRENT_SCHEMA_VERSION + 1)),
            )
            self.assertEqual(migrations[0]["name"], "initial_session_schema")
            self.assertEqual(migrations[1]["name"], "session_message_storage")
            self.assertTrue(all(len(row["checksum"]) == 64 for row in migrations))
            session_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(sessions)")
            }
            message_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(messages)")
            }
            self.assertIn("message_count", session_columns)
            self.assertIn("is_error", message_columns)
            self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone()[0], "wal")

    def test_initialize_is_idempotent_and_preserves_rows(self) -> None:
        """重复初始化不得重复登记迁移或删除已经存在的会话。"""
        self.database.initialize()
        with self.database.connection() as connection:
            connection.execute(
                "INSERT INTO sessions(user_id, agent_id, session_id, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                ("user-a", "agent-a", "session-a", 1, 1),
            )
        reopened = Database(data_dir=self.data_dir, environ={})
        reopened.initialize()
        with reopened.connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0], 1)
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0],
                CURRENT_SCHEMA_VERSION,
            )

    def test_v1_database_upgrades_to_v2_without_losing_sessions(self) -> None:
        """已有 Schema v1 必须原地升级，并保留升级前的会话数据。"""
        first_migration = database_module.MIGRATIONS[0]
        legacy_columns = {
            table: set(columns) for table, columns in database_module.REQUIRED_COLUMNS.items()
        }
        legacy_columns["sessions"].remove("message_count")
        legacy_columns["messages"].remove("is_error")
        with (
            patch.object(database_module, "CURRENT_SCHEMA_VERSION", 1),
            patch.object(database_module, "MIGRATIONS", (first_migration,)),
            patch.object(database_module, "REQUIRED_COLUMNS", legacy_columns),
        ):
            legacy = Database(data_dir=self.data_dir, environ={})
            legacy.initialize()
            with legacy.connection() as connection:
                connection.execute(
                    "INSERT INTO sessions("
                    "user_id, agent_id, session_id, title, created_at, updated_at"
                    ") VALUES (?, ?, ?, ?, ?, ?)",
                    ("u", "a", "legacy", "旧会话", 1, 1),
                )

        upgraded = Database(data_dir=self.data_dir, environ={})
        info = upgraded.initialize()
        self.assertEqual(info.schema_version, CURRENT_SCHEMA_VERSION)
        with upgraded.connection() as connection:
            row = connection.execute(
                "SELECT title, message_count FROM sessions WHERE session_id = 'legacy'"
            ).fetchone()
            self.assertEqual(row["title"], "旧会话")
            self.assertEqual(row["message_count"], 0)
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0],
                CURRENT_SCHEMA_VERSION,
            )

    def test_foreign_key_sequence_and_status_constraints(self) -> None:
        """孤立消息、重复序号和非法 Run 状态必须由数据库拒绝。"""
        self.database.initialize()
        with self.database.connection() as connection:
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO messages("
                    "message_id, user_id, agent_id, session_id, sequence, role, content, created_at"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    ("orphan", "u", "a", "missing", 0, "user", "hello", 1),
                )
            connection.execute(
                "INSERT INTO sessions(user_id, agent_id, session_id, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                ("u", "a", "s", 1, 1),
            )
            connection.execute(
                "INSERT INTO messages("
                "message_id, user_id, agent_id, session_id, sequence, role, content, created_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("m1", "u", "a", "s", 0, "user", "hello", 1),
            )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO messages("
                    "message_id, user_id, agent_id, session_id, sequence, role, content, created_at"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    ("m2", "u", "a", "s", 0, "assistant", "duplicate", 2),
                )
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO runs("
                    "request_id, user_id, agent_id, session_id, status, created_at"
                    ") VALUES (?, ?, ?, ?, ?, ?)",
                    ("r1", "u", "a", "s", "unknown", 1),
                )

    def test_future_schema_version_is_rejected(self) -> None:
        """旧程序遇到更高版本数据库时必须停止，不能尝试降级写入。"""
        self.data_dir.mkdir(parents=True)
        path = self.data_dir / "yanagent.db"
        with closing(sqlite3.connect(path)) as connection:
            with connection:
                connection.execute(database_module.SCHEMA_MIGRATIONS_DDL)
                connection.execute(
                    "INSERT INTO schema_migrations(version, name, checksum, applied_at) "
                    "VALUES (?, ?, ?, ?)",
                    (CURRENT_SCHEMA_VERSION + 1, "future", "future-checksum", 1),
                )
        with self.assertRaises(UnsupportedSchemaVersionError):
            self.database.initialize()

    def test_failed_migration_rolls_back_all_schema_changes(self) -> None:
        """迁移中途失败时不能留下表或成功版本记录。"""
        broken = Migration(
            version=1,
            name="broken_initial",
            statements=(
                "CREATE TABLE sessions (session_id TEXT PRIMARY KEY)",
                "这不是合法的 SQL",
            ),
        )
        with patch.object(database_module, "MIGRATIONS", (broken,)):
            with self.assertRaises(DatabaseInitializationError):
                self.database.initialize()
        with closing(sqlite3.connect(self.data_dir / "yanagent.db")) as connection:
            tables = connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        self.assertEqual(tables, [])


if __name__ == "__main__":
    unittest.main()
