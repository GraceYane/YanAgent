"""SQLite 数据库、首版 Schema 与版本迁移。"""

from __future__ import annotations

import hashlib
import logging
import os
import sqlite3
import threading
import time
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path


LOGGER = logging.getLogger("yanagent.storage")
DATA_DIR_ENV = "YANAGENT_DATA_DIR"
DATABASE_FILENAME = "yanagent.db"
CURRENT_SCHEMA_VERSION = 2


class DatabaseInitializationError(RuntimeError):
    """表示数据目录、SQLite 连接或迁移初始化失败。"""


class UnsupportedSchemaVersionError(DatabaseInitializationError):
    """表示数据库版本高于当前程序，禁止旧程序继续写入。"""


class SchemaValidationError(DatabaseInitializationError):
    """表示迁移记录、表或关键列与当前 Schema 定义不一致。"""


@dataclass(frozen=True, slots=True)
class Migration:
    """描述一个只能向前执行的数据库版本迁移。"""

    version: int
    name: str
    statements: tuple[str, ...]

    @property
    def checksum(self) -> str:
        """计算迁移内容校验和，用于发现已登记版本被意外改写。"""
        source = "\n-- statement --\n".join(statement.strip() for statement in self.statements)
        return hashlib.sha256(source.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class DatabaseInfo:
    """返回已经初始化的数据库位置与当前 Schema 版本。"""

    data_dir: Path
    path: Path
    schema_version: int


SCHEMA_MIGRATIONS_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version     INTEGER PRIMARY KEY CHECK (version > 0),
    name        TEXT    NOT NULL UNIQUE,
    checksum    TEXT    NOT NULL,
    applied_at  INTEGER NOT NULL
)
"""


MIGRATIONS = (
    Migration(
        version=1,
        name="initial_session_schema",
        statements=(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                user_id       TEXT    NOT NULL,
                agent_id      TEXT    NOT NULL,
                session_id    TEXT    NOT NULL,
                title         TEXT    NOT NULL DEFAULT '',
                pinned        INTEGER NOT NULL DEFAULT 0 CHECK (pinned IN (0, 1)),
                created_at    INTEGER NOT NULL,
                updated_at    INTEGER NOT NULL,
                metadata_json TEXT    NOT NULL DEFAULT '{}',
                PRIMARY KEY (user_id, agent_id, session_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS messages (
                message_id     TEXT    NOT NULL PRIMARY KEY,
                user_id        TEXT    NOT NULL,
                agent_id       TEXT    NOT NULL,
                session_id     TEXT    NOT NULL,
                sequence       INTEGER NOT NULL CHECK (sequence >= 0),
                role           TEXT    NOT NULL
                                       CHECK (role IN ('system', 'user', 'assistant', 'tool')),
                content        TEXT    NOT NULL,
                tool_calls_json TEXT,
                tool_call_id   TEXT,
                name           TEXT,
                created_at     INTEGER NOT NULL,
                metadata_json  TEXT    NOT NULL DEFAULT '{}',
                UNIQUE (user_id, agent_id, session_id, sequence),
                FOREIGN KEY (user_id, agent_id, session_id)
                    REFERENCES sessions (user_id, agent_id, session_id)
                    ON DELETE CASCADE
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS runs (
                request_id       TEXT    NOT NULL PRIMARY KEY,
                user_id          TEXT    NOT NULL,
                agent_id         TEXT    NOT NULL,
                session_id       TEXT    NOT NULL,
                parent_request_id TEXT,
                status           TEXT    NOT NULL
                                         CHECK (status IN (
                                             'queued', 'running', 'completed', 'failed',
                                             'cancelled', 'interrupted'
                                         )),
                created_at       INTEGER NOT NULL,
                started_at       INTEGER,
                finished_at      INTEGER,
                finish_reason    TEXT,
                error_code       TEXT,
                usage_json       TEXT,
                metadata_json    TEXT    NOT NULL DEFAULT '{}',
                FOREIGN KEY (user_id, agent_id, session_id)
                    REFERENCES sessions (user_id, agent_id, session_id)
                    ON DELETE CASCADE
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_sessions_updated
                ON sessions (user_id, agent_id, pinned DESC, updated_at DESC)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_messages_session_sequence
                ON messages (user_id, agent_id, session_id, sequence)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_runs_session_created
                ON runs (user_id, agent_id, session_id, created_at DESC)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_runs_status
                ON runs (status, created_at)
            """,
        ),
    ),
    Migration(
        version=2,
        name="session_message_storage",
        statements=(
            """
            ALTER TABLE sessions
                ADD COLUMN message_count INTEGER NOT NULL DEFAULT 0
                CHECK (message_count >= 0)
            """,
            """
            ALTER TABLE messages
                ADD COLUMN is_error INTEGER NOT NULL DEFAULT 0
                CHECK (is_error IN (0, 1))
            """,
        ),
    ),
)


REQUIRED_COLUMNS = {
    "schema_migrations": {"version", "name", "checksum", "applied_at"},
    "sessions": {
        "user_id", "agent_id", "session_id", "title", "pinned", "created_at",
        "updated_at", "message_count", "metadata_json",
    },
    "messages": {
        "message_id", "user_id", "agent_id", "session_id", "sequence", "role",
        "content", "tool_calls_json", "tool_call_id", "name", "created_at", "is_error",
        "metadata_json",
    },
    "runs": {
        "request_id", "user_id", "agent_id", "session_id", "parent_request_id", "status",
        "created_at", "started_at", "finished_at", "finish_reason", "error_code", "usage_json",
        "metadata_json",
    },
}


def resolve_data_dir(
    *, environ: Mapping[str, str] | None = None, home: Path | None = None,
) -> Path:
    """解析 YanAgent 独立数据目录；只接受专属环境变量，不读取 CowAgent 配置。"""
    source = os.environ if environ is None else environ
    configured = source.get(DATA_DIR_ENV, "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    home_dir = Path.home() if home is None else Path(home)
    return (home_dir.expanduser().resolve() / ".yanagent").resolve()


class Database:
    """负责创建 YanAgent 数据目录、连接 SQLite 并原子执行版本迁移。"""

    def __init__(
        self,
        db_path: Path | str | None = None,
        *,
        data_dir: Path | str | None = None,
        environ: Mapping[str, str] | None = None,
        home: Path | None = None,
        timeout: float = 10.0,
    ) -> None:
        """确定数据库位置；显式文件路径与数据目录不能同时提供。"""
        if db_path is not None and data_dir is not None:
            raise ValueError("db_path 与 data_dir 不能同时提供")
        if type(timeout) not in {int, float} or timeout <= 0:
            raise ValueError("SQLite 超时必须是正数")
        if db_path is not None:
            selected_path = Path(db_path).expanduser().resolve()
            selected_dir = selected_path.parent
        else:
            selected_dir = (
                Path(data_dir).expanduser().resolve()
                if data_dir is not None
                else resolve_data_dir(environ=environ, home=home)
            )
            selected_path = selected_dir / DATABASE_FILENAME
        self.data_dir = selected_dir
        self.path = selected_path
        self.timeout = float(timeout)
        self._initialize_lock = threading.RLock()
        self._initialized = False

    def initialize(self) -> DatabaseInfo:
        """创建目录并迁移到当前版本；重复调用保持幂等且不改写业务数据。"""
        with self._initialize_lock:
            if self._initialized:
                return self._info()
            LOGGER.info(
                "[database.py][Database.initialize] 正在初始化数据库，目录=%s",
                self.data_dir,
            )
            try:
                self.data_dir.mkdir(parents=True, exist_ok=True)
                if not self.data_dir.is_dir():
                    raise OSError("数据目录不是文件夹")
                connection = self._open_connection()
                try:
                    self._apply_migrations(connection)
                finally:
                    connection.close()
            except (OSError, sqlite3.Error) as error:
                LOGGER.error(
                    "[database.py][Database.initialize] 数据库初始化失败，异常类型=%s",
                    type(error).__name__,
                )
                raise DatabaseInitializationError("YanAgent 数据库初始化失败。") from None
            self._initialized = True
            info = self._info()
            LOGGER.info(
                "[database.py][Database.initialize] 数据库已就绪，schema_version=%d，文件=%s",
                info.schema_version,
                info.path,
            )
            return info

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        """返回启用外键和忙等待的短连接，并保证使用后关闭。"""
        self.initialize()
        connection = self._open_connection()
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def transaction(self, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        """开启显式事务；异常时完整回滚，正常结束时一次提交。"""
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            try:
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def _info(self) -> DatabaseInfo:
        """构造当前数据库只读信息。"""
        return DatabaseInfo(
            data_dir=self.data_dir,
            path=self.path,
            schema_version=CURRENT_SCHEMA_VERSION,
        )

    def _open_connection(self) -> sqlite3.Connection:
        """建立配置一致的 SQLite 连接；事务边界由调用者显式控制。"""
        connection = sqlite3.connect(
            str(self.path), timeout=self.timeout, isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute(f"PRAGMA busy_timeout = {int(self.timeout * 1000)}")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        return connection

    def _apply_migrations(self, connection: sqlite3.Connection) -> None:
        """在一个立即事务内校验并执行缺失迁移，任何失败都整体回滚。"""
        connection.execute("BEGIN IMMEDIATE")
        try:
            migration_versions = [migration.version for migration in MIGRATIONS]
            expected_versions = list(range(1, CURRENT_SCHEMA_VERSION + 1))
            if migration_versions != expected_versions:
                raise SchemaValidationError("程序内数据库迁移定义不连续。")
            connection.execute(SCHEMA_MIGRATIONS_DDL)
            rows = connection.execute(
                "SELECT version, name, checksum FROM schema_migrations ORDER BY version"
            ).fetchall()
            applied = {int(row["version"]): row for row in rows}
            if applied and max(applied) > CURRENT_SCHEMA_VERSION:
                raise UnsupportedSchemaVersionError(
                    "数据库版本高于当前 YanAgent，禁止使用旧程序写入。"
                )
            for migration in MIGRATIONS:
                existing = applied.get(migration.version)
                if existing is not None:
                    if (
                        existing["name"] != migration.name
                        or existing["checksum"] != migration.checksum
                    ):
                        raise SchemaValidationError("数据库迁移记录与程序定义不一致。")
                    continue
                for statement in migration.statements:
                    connection.execute(statement)
                connection.execute(
                    "INSERT INTO schema_migrations(version, name, checksum, applied_at) "
                    "VALUES (?, ?, ?, ?)",
                    (migration.version, migration.name, migration.checksum, int(time.time() * 1000)),
                )
                LOGGER.info(
                    "[database.py][Database._apply_migrations] 已应用数据库迁移，version=%d，name=%s",
                    migration.version,
                    migration.name,
                )
            self._validate_schema(connection)
            connection.commit()
        except BaseException:
            connection.rollback()
            raise

    def _validate_schema(self, connection: sqlite3.Connection) -> None:
        """验证版本连续性以及四张核心表的关键列，拒绝半迁移数据库。"""
        versions = [
            int(row[0])
            for row in connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            ).fetchall()
        ]
        expected_versions = list(range(1, CURRENT_SCHEMA_VERSION + 1))
        if versions != expected_versions:
            raise SchemaValidationError("数据库迁移版本不连续。")
        for table, required in REQUIRED_COLUMNS.items():
            columns = {
                str(row["name"])
                for row in connection.execute(f'PRAGMA table_info("{table}")').fetchall()
            }
            if not required.issubset(columns):
                raise SchemaValidationError("数据库核心表结构不完整。")
