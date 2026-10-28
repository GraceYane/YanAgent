# P04-01 Prompt 与上下文组装

状态：已完成  
完成日期：2026-10-28  
下一项：P04-02 非流式 Agent Loop

## 1. 本阶段解决的问题

P02 已能读取完整 Session 历史，P03 已能导出工具 Schema，但此前模型请求仍只有历史和当前 User 消息，工具参数始终传空列表。本阶段建立统一上下文边界：

```text
可信运行身份（user / agent / session / run）
                  ↓
系统规则 + 工具使用说明 + 工具摘要
                  ↓
完整持久化历史 + 当前 User 输入
                  ↓
统一 Message 序列 + 独立工具 Schema 快照
                  ↓
         ModelProvider 普通或流式入口
```

系统提示词只存在于本次模型输入，不写入 `messages` 表。数据库继续保存用户、Assistant 和 Tool 的真实完整历史，避免每轮重复落库系统提示词。

## 2. 核心实现

### 2.1 可信身份

`RuntimeIdentity` 保存 `user_id`、`agent_id`、`session_id` 和 `request_id`。四个字段必须是 1～256 位非空且无控制字符的字符串，防止换行破坏系统提示词结构。

当前桌面阶段使用 SessionStore 的可信作用域身份：`local / default`。用户正文不能覆盖这些字段；多用户和多 Agent 路由仍由后续 Bridge 与入口认证完成。

### 2.2 固定系统规则

`PromptContextBuilder` 生成唯一的首条 System Message，内容包括：

- YanAgent 和当前运行身份；
- 系统规则优先级、事实约束、凭据脱敏和回复语言；
- 不得在缺少真实 Tool Result 时声称工具已执行；
- 只能使用本轮真实提供的工具 Schema；
- 使用原生 Tool Call，不在普通正文中伪造调用 JSON；
- 工具权限、确认、超时和执行由 Runtime 处理。

### 2.3 历史与当前输入

组装顺序固定为：

```text
System → 完整历史 → 当前 User
```

历史和当前输入都使用 `yanagent.contracts.Message`。已有 Assistant ToolCall 与 Tool Result 必须通过原调用 ID 完整配对；持久化历史中的额外 System Message、未完成工具轮次或非 Message 数据会在模型请求前失败。

组装器复制消息和工具 Schema。Provider 或测试代码修改收到的对象，不会反向污染数据库消息或 `ToolManager` 注册表。

### 2.4 普通与流式共用

`YanAgentApplication.begin_chat()` 是两条链路共同入口：

- 普通调用使用 `provider.complete(context.messages, tools=context.tools)`；
- 流式调用使用 `provider.stream(context.messages, tools=context.tools)`。

因此普通和 SSE 请求看到相同身份、规则、历史、当前输入和工具集合，不会出现一条链路有 Prompt、另一条链路仍发送旧格式的问题。

## 3. 失败关闭边界

- 身份含换行或控制字符：拒绝组装。
- 工具 Schema 重名、字段不完整、参数顶层不是对象或含非标准 JSON：拒绝组装。
- 历史出现额外 System Message：拒绝组装，避免持久化内容覆盖运行时规则。
- 历史工具请求没有完整结果：拒绝追加下一条 User 消息。
- 没有工具：发送空工具列表，并在 System Message 明确禁止伪造工具执行。

## 4. 本阶段未完成

- 模型虽然已经能看到 `calculator` 和 `current_time` 的 Schema，但 P04-02 前不会执行模型返回的 ToolCall；当前仍以 `UnexpectedToolCallError` 明确失败。
- 没有实现 `模型 → 工具 → 模型` 多轮循环、轮数/总超时/连续失败限制或累计 Token。
- 没有实现上下文 Token 预算、裁剪和摘要；这些属于 P05-04。
- 没有接入 Skills、Memory、Knowledge、MCP 或 Workspace Prompt；分别属于 P07～P09 和 P06。
- 没有新增桌面页面，本阶段复用现有普通与 SSE 聊天入口。

## 5. 验证

新增 `tests/test_prompt_context.py`，覆盖：

1. System、历史和当前输入的稳定顺序；
2. 四类可信身份及固定系统规则；
3. 真实注册工具摘要和 Provider Schema；
4. 完整工具历史的调用 ID 配对；
5. 消息和 Schema 快照隔离；
6. 空工具、System 注入、未完成工具轮次、非法身份和工具重名失败路径。

同时更新普通聊天、流式聊天、完整历史、重启恢复和并发 Echo Provider 测试，使它们验证新上下文契约而不是绕过 System Message。

验收命令：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall app.py yanagent tests
git diff --check
```

最终验证结果以 `workProcess.md` 本次记录为准。
