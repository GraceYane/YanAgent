# P04-02 非流式 Agent Loop

状态：已完成
完成日期：2026-10-29
后续状态：P04-03 多调用与限制已完成；下一项为 P04-04 流式循环

## 1. 本阶段解决的问题

P04-01 已把工具 Schema 发送给模型，但模型返回 ToolCall 后仍会失败。本阶段把普通非流式聊天接成最小可运行闭环：

```text
完整模型上下文 + 工具 Schema
            ↓
      Provider.complete()
            ↓
   无 ToolCall ──────────────→ 保存最终 Assistant → 完成 Run
            │
            └─ 有一个 ToolCall
                    ↓
         保存原始 Assistant ToolCall
                    ↓
     ToolManager 参数校验、权限判断和执行
                    ↓
      保存同 tool_call_id 的 Tool Result
                    ↓
      把 Assistant + Tool 追加到模型上下文
                    ↓
             再次调用模型
```

本阶段用 `FakeProvider` 确定性验证两轮工具请求、第三轮最终回答，没有使用网络或真实 API Key。

## 2. 核心实现

### 2.1 独立 AgentLoop

`yanagent/runtime/agent_loop.py` 不再是 `NotImplementedError` 占位。`AgentLoop` 接收当前 Provider、应用级 `ToolManager` 和可选 `SessionStore`，普通聊天通过同一入口运行；无仓储的离线测试模式仍在内存中完成循环。

每轮模型响应先转换为统一 `Message`，并在落库或执行工具前调用 `validate_conversation()` 验证调用 ID 和对话顺序。Provider、ToolManager 和数据库继续使用 P01～P03 的既有契约，没有创建第二套消息格式或旁路执行接口。

### 2.2 Assistant 与 Tool Result 的保存顺序

模型返回一个 ToolCall 时：

1. 先保存原始 Assistant Message，包括模型提供的调用 ID、工具名、参数对象、正文和本轮 Usage；
2. 再调用 `ToolManager.execute()`；
3. 把成功或失败统一转换为 Tool Message，保留相同 `tool_call_id`；
4. 保存 Tool Message 后才发起下一轮模型请求。

因此数据库不会出现“只有工具结果、没有模型请求”的孤立记录。模型第二轮失败时，已经完成的 Assistant/Tool 对仍会保留，但不会伪造最终 Assistant 回答。

### 2.3 权限和失败语义

AgentLoop 使用当前配置的 `permission_mode`，并由运行时提供 `run_id / user_id / agent_id / session_id`。当前可信普通聊天开放 `global / user / agent / session` 目录范围，不开放 workspace；确认界面仍未接通，所以 `ask` 或需要确认的工具会失败关闭。

未知工具、非法参数、权限拒绝、工具超时或 handler 失败都由 `ToolManager` 返回 `ToolResult(is_error=True)`，写入历史后交回模型。它们不是 Provider 异常，模型可以根据错误说明继续回答。

### 2.4 Run 与累计用量

一次用户请求只创建一个 Run。循环完成时保存一个 `completed` 终态；模型或循环协议失败时保存一个 `failed` 终态。多轮 Provider Usage 按字段累计，任一轮明确为未知的字段保持 `None`，不会猜成零。普通 HTTP 结果增加 `turns` 字段，并继续返回最终回答、累计 Usage 和真实 `user_seq / bot_seq`。

### 2.5 当前阶段的多工具边界

P04-02 每个模型响应只允许一个 ToolCall。同一响应出现多个调用时，在保存 Assistant 或执行任何工具前抛出稳定的 `multiple_tool_calls_unsupported`，避免只处理一部分造成歧义。P04-03 将按模型原顺序执行同一响应中的多个调用，并增加最大轮数、总超时和连续失败限制。

以上是 P04-02 完成时的历史边界；P04-03 已解除该限制，当前行为见 [多调用与限制](P04_03_MULTI_CALL_LIMITS.md)。

## 3. 失败与恢复边界

- ToolCall 必须先通过统一消息契约，跨轮重复调用 ID 会在副作用前失败。
- Assistant ToolCall 一定先于对应 Tool Result 落库。
- Tool Result 无论成功或失败都引用原 `tool_call_id`，并在下一轮模型输入中保持原顺序。
- 第二轮模型失败不会删除已经真实执行并保存的工具轮次，也不会生成假的最终回答。
- 流式 Provider 仍在 `yanagent/runtime/streaming.py` 使用原有路径，遇到 ToolCall 明确失败；流式工具事件属于 P04-04。

## 4. 本阶段未完成

- 同一响应多个 ToolCall 的顺序执行、最大模型轮数、总超时和连续失败限制属于 P04-03。
- 当前最小循环本身没有轮数上限；正式长期运行前必须完成 P04-03，不能把 P04-02 描述成完整稳定性保护。
- 同一 Session 的并发模型请求尚未由 Bridge 串行化；SQLite 能保证序号唯一，但两条 Run 的业务消息仍可能交错。P04-02 验收使用单 Run，P05-02 再完成同 Session 排队。
- SSE 流式工具增量、工具开始/结束事件和取消中工具闭环属于 P04-04。
- 桌面工具卡片、确认 UI、崩溃后半轮恢复和真实模型工具联调尚未完成，分别属于 P04-04～P04-05及后续稳定性阶段。
- 本阶段只使用 `calculator / current_time` 安全示例工具，没有文件、命令、浏览器、MCP 或 Workspace 工具。

## 5. 验证

新增 `tests/test_agent_loop.py` 的 5 项行为测试，覆盖：

1. Fake Provider 连续两轮请求计算器、第三轮返回答案；
2. 三次模型输入依次为 `System+User`、追加 `Assistant+Tool`、再追加第二组 `Assistant+Tool`；
3. SQLite 保存 `User → Assistant ToolCall → Tool → Assistant ToolCall → Tool → Assistant` 六消息顺序；
4. 未知工具、非法参数和权限拒绝作为失败 Tool Result 回写模型；
5. 同轮多工具在部分保存/执行前失败，工具后模型失败保留完整工具对并将 Run 标为失败。

旧的“AgentLoop 必须抛出未实现”占位测试被移除，普通无工具聊天、历史恢复、Run 生命周期和流式回归继续通过。全量测试共 198 项。

验收命令：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest tests.test_agent_loop -v
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall app.py yanagent tests
git diff --check
```
