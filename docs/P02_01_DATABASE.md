# P02-01 数据库基础

## 1. 本次完成范围

P02-01 为 YanAgent 建立可版本化的 SQLite 持久化底座：

- 确定 YanAgent 独立数据目录；
- 创建 `yanagent.db`；
- 建立 `sessions`、`messages`、`runs`、`schema_migrations`；
- 从首版开始记录 Schema 版本、迁移名称和校验和；
- 将数据库初始化接入真实后端启动入口；
- 验证目录隔离、幂等初始化、数据库约束、未来版本拒绝和失败回滚。

本次没有实现 Session CRUD、消息写入服务、历史接口和多轮上下文。这些分别属于 P02-02～P02-04。

## 2. 数据目录

默认目录：

```text
~/.yanagent/
└── yanagent.db
```

可以通过专属环境变量覆盖：

```powershell
$env:YANAGENT_DATA_DIR = "D:\YanAgentData"
.\.venv\Scripts\python.exe app.py
```

路径解析只读取 `YANAGENT_DATA_DIR`，不会读取 `COW_DATA_DIR`，因此不会误用 CowAgent 的 `.cow` 数据库、配置或密钥。

测试和嵌入式调用也可以显式传入：

```python
database = Database(data_dir=temporary_directory, environ={})
database.initialize()
```

## 3. Schema v1

### 3.1 schema_migrations

| 字段 | 作用 |
|---|---|
| `version` | 单调递增的 Schema 版本，首版为 1 |
| `name` | 迁移名称 |
| `checksum` | 迁移 SQL 的 SHA-256，用于发现已登记迁移被改写 |
| `applied_at` | 应用迁移时的 Unix 毫秒时间 |

程序遇到高于自身支持范围的版本时会拒绝启动，避免旧程序对新结构进行降级写入。

### 3.2 sessions

保存会话归属和会话级元数据。主键是：

```text
(user_id, agent_id, session_id)
```

首版字段已经预留标题、置顶、创建/更新时间和 JSON 元数据，为 P02-02 的会话管理提供结构基础。

### 3.3 messages

保存消息身份、归属、稳定序号、角色、正文、工具调用相关字段、时间和元数据。

数据库约束包括：

- `role` 只允许 `system / user / assistant / tool`；
- 同一归属会话内的 `sequence` 唯一；
- 消息必须通过复合外键关联真实 Session；
- 删除 Session 时关联消息级联删除。

`tool_calls_json`、`tool_call_id` 和 `name` 为 P02-03 保存完整工具消息预留，本阶段尚未接入业务写入。

### 3.4 runs

保存可寻址运行的归属、父运行、状态、时间、结束原因、错误码、Usage 和元数据。

状态只允许：

```text
queued → running → completed / failed / cancelled / interrupted
```

本次只建立数据结构。P02-05 才会在启动时把上次未结束的 Run 标记为 `interrupted`，P04～P05 才会完整接入运行状态机。

## 4. 初始化与迁移流程

```text
解析 ~/.yanagent 或 YANAGENT_DATA_DIR
        ↓
创建数据目录
        ↓
打开 SQLite，启用 foreign_keys / WAL / busy_timeout
        ↓
BEGIN IMMEDIATE
        ↓
建立 schema_migrations
        ↓
读取并校验已登记版本
        ↓
按版本执行缺失迁移
        ↓
校验版本连续性和四张表的关键列
        ↓
COMMIT
```

任意 SQL 或结构校验失败都会执行 `ROLLBACK`。迁移表和业务表处于同一个事务中，不会留下“表只创建一半，但版本已经成功登记”的状态。

重复调用 `Database.initialize()` 是幂等的：已应用迁移会核对名称和校验和，不会重复建表，也不会删除业务数据。

## 5. 启动接入

`app.py` 的 `main()` 在启动 HTTP 服务前执行：

```python
database = Database()
database_info = database.initialize()
server = create_server(database=database)
```

关键日志会显示初始化函数、Schema 版本和数据库位置：

```text
[database.py][Database.initialize] 正在初始化数据库
[database.py][Database._apply_migrations] 已应用数据库迁移
[database.py][Database.initialize] 数据库已就绪
[app.py][main] P02 数据库基础已就绪
```

初始化失败时 HTTP 服务不会带着半成品数据库继续启动。

## 6. 验证

定向测试：

```powershell
.\.venv\Scripts\python.exe -X utf8 -W error -m unittest tests.test_database -v
```

覆盖 8 项：

1. 默认使用 `.yanagent`；
2. `YANAGENT_DATA_DIR` 覆盖；
3. 忽略 `COW_DATA_DIR`；
4. 建立四张表、v1 记录、外键和 WAL；
5. 重复初始化保留已有数据；
6. 拒绝孤立消息、重复序号和非法 Run 状态；
7. 拒绝未来 Schema 版本；
8. 迁移中途失败后没有残留表或版本记录。

全量回归：

```powershell
.\.venv\Scripts\python.exe -X utf8 -W error -m unittest discover -s tests -q
```

结果：108 项通过，其中原有 P01 测试 100 项、本次新增 8 项。

编译检查：

```powershell
.\.venv\Scripts\python.exe -X utf8 -W error -m compileall -q -f app.py yanagent tests examples scripts
```

结果：通过。

## 7. 当前能力边界

- 数据库及 Schema 已创建，但桌面端的会话列表和历史接口还没有读取这些表；
- `yanagent/sessions/store.py` 仍是空接口，P02-02 才实现会话和消息存储；
- 当前聊天仍只把本次用户消息发送给模型，P02-03 才接入多轮历史；
- 所有权字段和复合外键已经建立，但所有查询都强制校验归属属于 P02-05；
- WAL 和 `busy_timeout` 是并发基础，不代表当前已经完成 P02-05 的并发写入策略或生产级吞吐验证。
