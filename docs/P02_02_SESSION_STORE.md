# P02-02 会话与消息存储

## 1. 本阶段完成了什么

P02-02 将 P02-01 的 SQLite 表变成可调用的会话仓储。`SessionStore` 绑定一个可信的 `user_id + agent_id` 作用域，提供：

- 创建、读取、稳定分页、重命名、置顶和删除会话；
- 在一个事务内追加一批完整 `Message`；
- 为每个会话分配从 0 开始且稳定递增的消息序号；
- 按最近一页读取历史，并使用排他的 `before_sequence` 游标继续向前翻页；
- 保存标题、置顶、创建/更新时间、消息数和 JSON 元数据；
- 完整还原 Assistant 工具调用、Tool 调用 ID、工具名称及 `is_error` 失败语义；
- 关闭并重新创建 `Database` / `SessionStore` 后继续读取原数据。

## 2. 主要入口

```python
from yanagent.sessions import SessionStore
from yanagent.storage import Database

store = SessionStore(
    Database(),
    user_id="local",
    agent_id="default",
)

session = await store.create("session-001", title="新对话")
await store.append("session-001", [Message(role="user", content="你好")])
history = await store.history("session-001", limit=100)
```

身份在构造仓储时绑定，所有 SQL 都同时带上 `user_id`、`agent_id` 和 `session_id`。调用者不能在单次查询里换一个用户 ID 去读取同名会话。

## 3. 事务追加流程

```text
校验并复制整批 Message
        ↓
在线程中开启 BEGIN IMMEDIATE
        ↓
按完整身份确认 Session 存在
        ↓
读取该 Session 当前最大 sequence
        ↓
逐条写入完整消息和连续 sequence
        ↓
原子增加 message_count 并刷新 updated_at
        ↓
统一 COMMIT；任意异常统一 ROLLBACK
```

这里保证的是单个 SQLite 数据库内一次追加批次的原子性。测试故意让第二条消息的 `message_id` 冲突，验证第一条消息和 `message_count` 都没有残留。

## 4. Schema v2

P02-02 新增向前迁移 `session_message_storage`：

- `sessions.message_count`：缓存会话消息数量；
- `messages.is_error`：保存 Tool 消息的失败含义。

自动化测试先建立真实 Schema v1、写入旧会话，再由当前程序升级到 v2，确认旧标题和会话仍存在，新字段得到安全默认值。

## 5. 分页与顺序约定

- 会话列表排序：`pinned DESC, updated_at DESC, session_id ASC`；最后的 `session_id` 使相同时间下结果稳定。
- 消息序号：只在所属 `user + agent + session` 内连续递增。
- 历史接口默认取最近 `limit` 条，但返回给调用者时仍按序号升序排列。
- `before_sequence=N` 只返回序号小于 N 的消息，因此翻页不会重复边界消息。

## 6. 错误与日志

会话层增加四类安全错误：参数非法、会话不存在、会话重复和存储失败。数据库原始 SQL、消息正文、工具参数和凭据不会进入对外错误。

创建、属性更新、批次提交、历史读取和删除都有中文关键日志，日志注明文件与函数；消息正文和元数据不打印。

## 7. 验证

```powershell
.\.venv\Scripts\python.exe -X utf8 -W error -m unittest tests.test_database tests.test_session_store -v
.\.venv\Scripts\python.exe -X utf8 -W error -m unittest discover -s tests -q
.\.venv\Scripts\python.exe -X utf8 -W error -m compileall -q -f app.py yanagent tests examples scripts
```

定向测试覆盖 Schema v1→v2、CRUD、分页排序、工具消息完整往返、历史游标、批次回滚、用户隔离、级联删除、重启持久化和非法输入。

## 8. 当前边界

- P02-02 只完成后端仓储，当前聊天链路还没有读取历史并交给模型；这是 P02-03。
- 桌面会话列表和历史接口还没有改为读取 `SessionStore`；这是 P02-04。
- `context()` 明确抛出未实现，不用完整历史冒充经过 Token 预算选择的模型上下文。
- 本阶段通过事务串行化 SQLite 写入，但同一 Session 的 Run 排队、取消、进程中断恢复仍属于 P02-05 / P05。
- 数据隔离测试证明仓储查询按作用域过滤，不等于已经实现登录认证或远程多租户授权。
