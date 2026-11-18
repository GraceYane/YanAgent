# P04-05 桌面与持久化联调

状态：已完成  
完成日期：2026-11-04  
下一项：P05-01 Bridge 收口

## 1. 本阶段解决的问题

P04-04 已能通过 SSE 发送文本、工具开始、工具结束和最终回答，但桌面曾被临时切到非流式模式，而且历史接口仍逐条返回内部 `Assistant / Tool / Assistant` 消息。这样会导致三个问题：

1. 实时聊天收不到工具卡片事件；
2. 重启后前端无法把原始 ToolCall 和 Tool Result 还原为一次可读的执行过程；
3. 运行在工具开始后异常退出时，历史可能显示空 Assistant 或永远 running 的半条工具卡片。

P04-05 恢复桌面流式请求，并在历史适配层建立“内部消息轨迹 → 桌面步骤气泡”的投影。模型上下文仍读取原始消息，桌面只读取聚合后的展示结果，两者不互相改写。

## 2. 实时桌面工具卡片

桌面发送消息重新使用 `stream: true`。既有 `message_end / tool_start / tool_progress / tool_end / done` 分支现在真正参与主聊天链路：

```text
模型文本增量 → Assistant 正文
message_end(has_tool_calls) → 已有文本冻结为 content step
tool_start → running 工具卡片
tool_end → success/error、结果和耗时
done → 最终回答与累计 Usage
```

新增统一的工具卡收口逻辑。若收到 `cancelled`、`error`、`done` 时仍有 running 卡片，或 SSE 在终态前断开，桌面会把这些卡片改为带明确原因的 error，而不是继续转圈。断流后仍会重新读取后端历史，以持久化结果覆盖临时界面状态。

## 3. 历史过程还原

`DesktopSessionService` 现在同时使用同一用户和 Agent 作用域的 `SessionStore` 与 `RunStore`。历史读取后先按用户轮次分组，再把一轮中的消息聚合为：

```text
User 气泡
Assistant 过程气泡
  ├─ 可选的中间 content step
  ├─ tool step：调用 ID、名称、参数、结果、错误状态、耗时
  ├─ 后续 tool step
  └─ 最终 content step，同时作为 Assistant 最终正文
```

桌面分页发生在聚合后的消息上，因此同一工具循环不会被拆到两个历史页。`until_seq` 仍能定位用户消息；普通无工具历史继续保持原来的用户/助手消息和序号。

AgentLoop 会把每个本地工具的 `execution_time` 写入 Tool Message 元数据。实时事件和重启后的历史卡片因此使用同一个耗时来源。

## 4. 中断和退出语义

历史适配层会结合 Run 终态解释未完成记录：

- Run 仍是 `queued/running`：工具步骤保留 running，Assistant 标记 `run_state=running`；
- 启动恢复或失败使 Run 变为 `interrupted/failed`：没有结果的工具步骤收口为 error，并显示“没有留下可验证完成结果”；
- Run 为 `cancelled`：使用既有取消标记，未完成工具显示取消原因；
- 已有最终 Assistant：以最终回答为准，不因终态竞态覆盖有效文本。

这里没有承诺崩溃后自动重做工具，也没有声称外部副作用恰好执行一次。P04-05 只保证历史可解释；工具执行状态表、显式继续/重试和不确定副作用处理仍属于 P05-06。

## 5. 自动化与构建验证

新增两项桌面历史 HTTP 测试：

1. 两轮工具调用聚合为一个有序 Assistant 过程，保留两个调用 ID、参数、结果、成功状态、执行耗时、累计 Usage 和最终回答；
2. 重启中断后的半条工具请求变成带明确说明的 error，既不永久 running，也不成为孤立空消息。

同时扩展 RunStore 作用域测试和流式持久化测试，验证批量 Run 查询不能跨用户读取，并确认真实 AgentLoop 保存的 Tool Message 带非负执行耗时。

验证结果：

- 定向 19 项测试通过；
- 全量 `python -u -X utf8 -m unittest discover -s tests -v`：**211 项通过**；
- `desktop/npm run build` 通过 renderer Vite 构建和 main TypeScript 编译；
- Python 编译检查与 `git diff --check` 通过。

桌面构建仍有既有字体运行时解析、Browserslist 数据较旧、主 bundle 大于 500 kB 和静态/动态混合导入警告；这些不是本次引入的编译错误。

## 6. 真实 DeepSeek 工具闭环

新增 `scripts.verify_p04_real_tool`，读取本机忽略配置但不输出 API Key，也不修改保存的权限设置。2026-11-04 使用 OpenAI-compatible `deepseek-flash` 完成：

```text
第 1 轮：模型返回 current_time ToolCall
本地：YanAgent 执行 current_time，得到日期、时间、星期和 UTC+08:00
第 2 轮：模型读取 Tool Result，生成中文最终回答
```

实际结果为 2 个模型轮次、1 次成功工具调用、累计 1886 tokens，真实闭环通过。脚本为低风险时间工具显式使用 `allow`，用于隔离验证 AgentLoop；用户保存的 `ask` 配置没有被改写。确认 UI 和交互批准仍按 P05-03 实现。

## 7. 阶段边界

P04 至此完成了统一上下文、普通/流式多工具循环、有限结束、实时工具事件、桌面工具卡片、历史还原和真实模型工具闭环。以下仍未完成：

- P05-01～P05-02：正式 AgentBridge、同 Session 排队和完整身份路由；
- P05-03：确认 UI、批准/拒绝回传和工具执行中的完整取消传播；
- P05-04～P05-06：Token 预算、重试/去重、持久化工具执行状态和崩溃后的继续/重试入口；
- P06 以后：文件、命令、网页、MCP、Skills、记忆和 Multi-Agent。
