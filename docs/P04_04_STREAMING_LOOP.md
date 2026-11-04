# P04-04 流式循环

状态：已完成  
完成日期：2026-11-04  
下一项：P04-05 桌面与持久化联调

## 1. 本阶段解决的问题

P04-03 已完成普通非流式多工具循环，但流式 Runtime 过去只接受纯文本；模型一旦在流中返回 ToolCall，就会以 `unexpected_tool_call` 失败。P04-04 将既有流式 Provider 接到与非流式相同的 `AgentLoop`：

```text
Provider 文本增量 ───────────────→ delta
Provider 工具参数增量 ─→ 只在 Provider 内组装，不执行
Provider completed（完整 ToolCall）
        ↓
message_end → 保存 Assistant ToolCall → tool_start
        ↓
YanAgent 本地 ToolManager 执行工具
        ↓
保存并回写 Tool Result → tool_end
        ↓
再次发起一轮 Provider.stream(...)
        ↓
最终文本 delta → done（最终答案、累计 Usage、总轮数）
```

模型仍然只负责选择工具和生成参数，工具 handler 始终在 YanAgent 本地执行。流式与非流式不再各维护一套轮数、超时、连续失败和消息配对逻辑。

## 2. 统一循环与流式轮次边界

`AgentLoop` 新增可注入的 `model_turn`。默认实现仍调用 `ModelProvider.complete()`，所以普通聊天行为不变；流式 Runtime 注入一个消费 `ModelProvider.stream()` 的轮次函数。该函数实时把 `text_delta` 转成桌面 `delta`，但只有读到唯一 `completed` 后才向 `AgentLoop` 返回完整 `ModelReply`。

工具生命周期通过两个观察器接出：

- `on_tool_start`：Assistant ToolCall 已通过统一对话校验并保存后触发；SSE 携带完整参数对象、工具名和调用 ID。
- `on_tool_end`：Tool Result 已保存并追加到下一轮模型上下文后触发；SSE 携带成功/失败状态、结果和本地执行耗时。

因此 P04-03 的 20 轮模型上限、600 秒循环总超时、30 秒单工具超时、连续 3 次失败熔断、同轮多调用顺序和剩余调用补齐规则会自动作用于流式路径。

## 3. 工具参数完整性

OpenAI-compatible Provider 的 `StreamReplyBuilder` 继续负责按 `tool_index` 拼接调用 ID、工具名称和 JSON 参数片段，并在 `[DONE]` 后校验索引、必需字段和严格 JSON。Runtime 收到 `tool_call_delta` 时只记录不含正文的调试信息，不产生 `tool_start`，也不调用 `ToolManager`。

只有 Provider 生成包含 `ToolCall(arguments: dict)` 的 `completed` 事件后，`AgentLoop` 才保存 Assistant 调用并开始工具执行。若流在参数尚未完成时结束，则以 `empty_model_response` 终止，不会执行部分参数，也不会向桌面制造一个永远处于 running 的工具卡片。

## 4. SSE 事件与持久化顺序

本阶段在后端 `ClientEventType` 中加入：

| 事件 | 产生时机 | 关键字段 |
|---|---|---|
| `message_end` | 当前模型轮次包含工具调用，文本阶段需要与工具阶段分隔 | `has_tool_calls=true`、本轮 Usage |
| `tool_start` | 完整 Assistant ToolCall 已保存，即将本地执行 | `tool`、`tool_call_id`、`arguments`、`status=running` |
| `tool_end` | Tool Result 已保存并回写上下文 | `tool`、`tool_call_id`、`status`、`result`、`execution_time` |
| `done` | 模型返回无工具的最终答案 | `content`、`finish_reason`、累计 `usage`、`turns`、消息序号 |

普通无工具的流式回答仍保持 `delta → done`，不额外插入无意义的 `message_end`，兼容既有桌面和 HTTP 测试。`AgentLoop` 负责保存中间 Assistant/Tool 及最终 Assistant，因此流式 Runtime 不再额外调用 `finish_chat()`，避免最终回答重复落库。

## 5. 验证

`tests/test_streaming_runtime.py` 从 5 项扩展为 8 项，新增验证：

1. Fake Provider 连续两轮请求计算器，第三轮分片返回最终答案；
2. 每轮参数可以先以多个 `tool_call_delta` 到达，但 `tool_start.arguments` 必须是完整对象；
3. 事件顺序为 `message_end → tool_start → tool_end`，两轮工具后才出现最终 `delta → done`；
4. 三次 Provider 输入分别包含原始问题、第一组 Assistant/Tool、第二组 Assistant/Tool；
5. SQLite 历史严格为 `User → Assistant → Tool → Assistant → Tool → Assistant`；
6. `done.usage` 是三轮 Usage 的字段级累计值，Run 只进入一次 completed 终态；
7. 只有工具参数增量而没有完整完成事件时不执行工具，也不发送工具卡片；
8. 未知工具产生失败 `tool_end` 和 `Tool Result(is_error=True)`，下一轮模型仍可生成最终回答。

最终执行 `python -X utf8 -m unittest discover -s tests -v`，共 **209 项测试通过**；Python 编译检查和 `git diff --check` 通过。异步测试因 Windows 沙箱不允许事件循环内部 socketpair，按批准在沙箱外执行；测试使用 Fake Provider 和本地安全工具，没有请求网络或读取真实 API Key。

## 6. 尚未完成

- P04-05：恢复桌面流式开关后实际展示工具卡片，验证退出重启后的工具过程还原，并处理崩溃/取消造成的半轮展示。
- P05-03：确认 UI 和批准/拒绝回传；当前需要确认的工具在无确认界面时仍安全拒绝。
- P05：同 Session 排队、工具执行中的完整取消闭环、重试、上下文预算和崩溃恢复。
- P04 阶段最终验收前仍需真实 DeepSeek 完成一次“调用当前时间工具并根据结果回答”的人工验证；本次 209 项仅证明确定性自动化行为。
