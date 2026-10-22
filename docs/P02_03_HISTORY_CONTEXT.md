# P02-03 历史与上下文接通

## 1. 本阶段完成了什么

P02-03 将 P02-02 的 `SessionStore` 接入普通聊天和流式聊天主链路。通过源码启动 YanAgent 后，每条成功对话都会写入 `~/.yanagent/yanagent.db`，下一轮模型调用会加载同一 Session 的既有完整历史。

现在同一 Session 的两轮流程是：

```text
第一轮：用户“我叫张三”
  创建/确认 Session
  读取历史：[]
  保存 User
  Provider 输入：[User]
  保存 Assistant

第二轮：用户“我叫什么？”
  读取历史：[User“我叫张三”, Assistant“记住了”]
  保存本轮 User
  Provider 输入：[旧 User, 旧 Assistant, 新 User]
  保存本轮 Assistant
```

数据库中的完整历史与本轮 Provider 输入是两个概念：数据库记录长期保留；本阶段 Provider 输入由“调用前的完整历史 + 当前用户消息”临时组装，不把临时上下文反向覆盖数据库。

## 2. 普通聊天流程

```text
校验请求和模型配置
        ↓
创建或确认 Session
        ↓
分页读取完整历史
        ↓
先保存当前 User Message
        ↓
历史 + 当前 User 发送给 Provider
        ↓
校验 ModelReply
        ↓
保存完整 Assistant Message
        ↓
返回 inline_reply
```

回答必须成功落库后才返回成功结果。若保存 Assistant 失败，接口不会把未持久化的回答标成成功。

## 3. 流式聊天流程

流式路径复用相同的 `begin_chat()` 和 `finish_chat()`：

- 模型增量仍立即作为 `delta` 推送；
- 收到完整 `ModelReply` 后先验证增量拼接结果；
- 然后保存 Assistant 完整消息；
- 保存成功后才发出 `done`。

因此客户端收到 `done` 时，完整回答已经存在数据库。若最终持久化失败，客户端会得到错误终态，而不是成功 `done`。

## 4. 重启、隔离与完整历史

- 正式 `create_server(database=...)` 路径自动创建 `SessionStore`，当前本地身份为 `user_id=local`、`agent_id=default`。
- 关闭应用再启动后，新的 Database/SessionStore 会从同一 SQLite 文件读取旧消息。
- 新 Session 第一次发送时自动创建；另一个 `session_id` 不会获得原 Session 的历史。
- `complete_history()` 使用稳定序号游标逐页读取，不会因为单页上限 500 而静默丢掉更早消息。
- Assistant ToolCall、Tool Result、`tool_call_id` 和 `is_error` 会按内部契约还原后再交给 Provider。

## 5. 失败与取消语义

- 模型调用失败：当前 User Message 保留，数据库不伪造 Assistant 回答。
- 模型异常返回未启用的工具请求：当前 User Message 保留，未执行的 Assistant 工具请求不作为成功历史保存。
- 流式取消：User Message 已保存；当前阶段不把部分 Assistant 文本冒充完整回答写入历史。
- 下次请求可能看到上一条没有 Assistant 回答的 User Message。P02-04 的重新生成规则和 P05 的 Run 状态/恢复机制会继续完善这一行为。

## 6. 主要代码

- `yanagent/chat.py`
  - `begin_chat()`：模型调用前创建 Session、读取历史、保存当前用户消息并组装输入。
  - `finish_chat()`：成功完成前保存 Assistant 完整回答。
  - `_ensure_session()`：处理首次创建以及并发创建竞态。
- `yanagent/runtime/streaming.py`
  - `_run_stream()`：流式 Provider 使用历史，并在发出 `done` 前调用 `finish_chat()`。
- `yanagent/sessions/store.py`
  - `complete_history()`：跨分页读取完整历史。
- `app.py`
  - `create_server()`：正式数据库启动路径注入 `SessionStore(local/default)`。

## 7. 验证

```powershell
.\.venv\Scripts\python.exe -X utf8 -W error -m unittest tests.test_chat_history -v
.\.venv\Scripts\python.exe -X utf8 -W error -m unittest discover -s tests -q
.\.venv\Scripts\python.exe -X utf8 -W error -m compileall -q -f app.py yanagent tests examples scripts
```

新增测试验证：

1. “我叫张三 → 我叫什么”第二轮 Provider 收到第一轮问答；数据库有四条稳定消息。
2. 重建 Database/SessionStore 后历史仍可使用；另一个 Session 只有自己的当前消息。
3. 模型认证失败后只保留 User，不产生虚假 Assistant。
4. 工具调用、工具结果引用和失败含义重启后完整进入上下文。
5. 501 条旧消息加当前消息共 502 条进入 Provider，证明没有只取最近一页。
6. 真实 `POST /message → SSE done → POST /message` 路径共享持久化历史，并确认数据库最终为 User/Assistant/User/Assistant。

## 8. 当前边界

- P02-04 才实现 `/api/sessions`、`/api/history` 以及桌面列表、打开、重命名、置顶和删除联调；当前聊天会写库，但左侧会话列表仍不会展示真实数据。
- 本阶段发送完整历史，不做 Token 预算、裁剪或摘要；超长历史可能被模型供应商拒绝。`SessionStore.context(token_budget=...)` 仍明确留到 P05-04。
- P02-05 才完善同一 Session 并发写入/任务排序和上次未结束 Run 的恢复标记。当前两个同 Session 请求同时开始时，可能各自在对方写入前取得历史快照。
- 当前本地入口固定为 `local/default`，数据作用域不等于登录认证或远程多租户授权。
- 本阶段没有修改桌面 TypeScript；通过现有 `/message` 和 `/stream` 契约接入。
