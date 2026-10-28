# P02-04 桌面会话联调

完成日期：2026-10-22  
状态：已完成  
后续状态：P02-05 隔离与恢复、P03-01～P03-02 已完成，当前下一项为 P03-03 参数与结果

## 1. 本阶段交付

P02-04 将复制桌面已有的会话界面接到 YanAgent 自己的 SQLite 数据库。现在关闭再打开桌面后，可以从会话列表重新进入旧会话、加载历史，并继续使用同一 Session 的上下文。

本阶段接通：

- 会话分页列表、标题、置顶、消息数和最后活动时间；
- 历史分页与“跳到某条用户消息”所需的向前扩页；
- 全量用户消息轻量索引；
- 会话重命名、置顶、删除；
- 首轮对话的确定性自动标题；
- 按用户消息序号删除一轮或截断后续上下文；
- 普通和流式回答返回落库后的 `user_seq` / `bot_seq`，新产生的气泡无需刷新即可参与删除与重新生成。

## 2. 接口

| 方法与路径 | 作用 | 关键返回或规则 |
|---|---|---|
| `GET /api/sessions` | 会话列表 | 最新更新时间排序，置顶优先；毫秒存储转换为桌面需要的秒 |
| `GET /api/history` | 消息历史 | 第 1 页代表最新消息，页内仍按先后顺序；支持 `until_seq` 一次取回到目标页 |
| `GET /api/history/user_messages` | 用户消息索引 | 只返回 `seq / preview / created_at`，供时间线定位 |
| `PUT /api/sessions/{id}` | 重命名或置顶 | 接收 `title` 和/或 `pinned` |
| `DELETE /api/sessions/{id}` | 删除会话 | 先取消该 Session 活动 Run，再由外键级联删除消息 |
| `POST /api/sessions/{id}/generate_title` | 首轮标题 | 从用户首条消息折叠空白并截断，不额外调用模型 |
| `POST /api/messages/delete` | 删除消息轮次 | 目标必须是 User Message 的稳定序号 |

当前是单 Agent 阶段，接口只接受缺省值或 `agent_id=default`。请求其他 Agent 不会被悄悄映射到默认数据。

## 3. 历史分页方向

历史从最新一页开始编号，但每次返回的消息仍按对话发生顺序排列。例如数据库有序号 `0～5`，`page_size=2`：

```text
page=1 -> [4, 5]
page=2 -> [2, 3]
page=3 -> [0, 1]
```

如果界面当前请求 `page=1&until_seq=0`，后端一次返回 `[0, 1, 2, 3, 4, 5]`，并将响应页码设为 `3`。这样时间线可以直接定位旧消息，同时下一次继续加载时不会重复页。

## 4. 删除与重新生成规则

稳定消息序号 `_seq` 是删除接口的定位依据。数据库不会按界面数组下标删除，也不会允许 Assistant 序号冒充 User 序号。

| 场景 | 请求 | 数据库行为 |
|---|---|---|
| 删除单轮 | `delete_user=true, cascade=false` | 删除目标 User 以及它之后、下一个 User 之前的本轮消息；保留后续轮次 |
| 保留问题只删回答 | `delete_user=false, cascade=false` | 保留目标 User，删除本轮后续消息；当前桌面没有暴露此操作 |
| 从某轮截断 | `delete_user=true, cascade=true` | 删除目标 User 及其后所有消息 |
| 桌面删除 | 当前桌面传 `cascade=true` | 界面删除后不会继续保留受该输入影响的后续回答 |
| 重新生成 | 先以 `cascade=true` 删除，再重新发送原问题 | 新模型调用不会看到旧回答及旧回答之后的上下文 |

级联删除是重新生成的安全默认值。若仅删除中间一轮却保留后续 Assistant，后续回答可能已经使用了被删除内容，数据库显示出来的因果关系会失真。

## 5. 自动标题竞态

复制桌面在首条消息发出后会立即请求标题，此请求可能早于聊天协程创建 Session。`upsert_title()` 在一个 `BEGIN IMMEDIATE` 事务里执行：

- Session 已存在：只更新标题与更新时间；
- Session 尚不存在：创建一条空 Session，并标记 `created_by=desktop-title`；
- 聊天随后创建时读到该 Session，直接追加 User/Assistant，不覆盖标题。

标题由首条用户消息确定性生成，最多 30 个字符。P02 阶段不为标题额外消耗一次模型调用。

## 6. 实时序号

`begin_chat()` 在保存 User Message 后记录真实序号；`finish_chat()` 在保存 Assistant 后返回真实序号。只有 Assistant 成功落库后，普通响应或 SSE `done` 才携带：

```json
{
  "user_seq": 0,
  "bot_seq": 1
}
```

因此界面刚显示的新消息就可以准确删除或重新生成，不必依赖一次历史刷新来补序号。

## 7. 验证

- P02-04 新增 6 项自动化测试：3 项仓储行为、3 项真实 HTTP 桌面联调；同时扩充普通/流式落库序号断言。
- 全量 `130` 项测试通过。
- Python 强制编译检查通过。
- `git diff --check` 通过（仅有 Windows 工作区换行提示）。
- `desktop/npm run build` 通过；Vite 的既有字体运行时解析、Browserslist 数据和大 chunk 提示不影响构建成功。

## 8. 未完成边界

- P02-05 已完成完整归属、并发数据库写入验证和启动时把未结束 Run 标记为 interrupted，见 [隔离与恢复](P02_05_ISOLATION_RECOVERY.md)；同一 Session 的模型请求排队仍属于 P05。
- P05：同一 Session 默认排队、可靠取消传播、Token 预算、摘要与上下文压缩。
- P03～P04：工具注册、权限和模型工具循环。历史接口虽然能还原已存 ToolCall，但当前聊天不会执行新工具。
- P09：长期记忆与跨 Session 知识。P02 的历史只属于当前 Session。
