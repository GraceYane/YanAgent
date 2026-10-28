# P03-04 工具权限基础

状态：已完成  
完成日期：2026-10-28  
后续状态：P03-05 测试与接口、P04-01 已完成；下一项为 P04-02 非流式 Agent Loop

## 1. 本阶段交付

P03-04 在统一工具执行器前增加了显式权限决策：

```text
ToolCall + ToolDefinition
          ↓
deny / ask / allow
          ↓
ToolPermissionContext（身份与可用 scope）
          ↓
risk_level / requires_confirmation
          ↓
无需确认 ───────────────→ handler
需要确认 → 请求 ID → 批准 / 拒绝 → handler 或 ToolResult 失败
```

权限判断仍发生在 handler 之前。权限拒绝、作用域不匹配、确认界面不可用、确认 ID 不匹配、用户拒绝和确认结果重放均返回关联原 `tool_call_id` 的失败 `ToolResult`，不会产生工具副作用。

## 2. 三种模式的确切语义

| 模式 | 语义 |
|---|---|
| `deny` | 所有工具均拒绝，不查找或执行 handler，也不能被确认结果覆盖。 |
| `ask` | 每次工具调用都必须获得匹配的显式批准；没有确认界面时默认拒绝。 |
| `allow` | 低风险且未标记 `requires_confirmation` 的工具可自动执行；`medium / high` 或显式要求确认的工具仍进入确认流程。 |

非法模式始终失败关闭。批准只能满足“需要确认”这一条件，不能绕过 `deny`、作用域限制、参数校验或未知工具检查。

## 3. 作用域限制

`ToolPermissionContext.allowed_scopes` 由可信运行时提供，不能来自模型工具参数。工具定义的 `scope` 必须在该集合内：

| scope | 上下文必须绑定的边界 |
|---|---|
| `global` | 无私有身份；默认上下文只允许此范围。 |
| `user` | `user_id`。 |
| `agent` | `user_id + agent_id`。 |
| `session` | `user_id + agent_id + session_id`。 |
| `workspace` | `workspace`。 |

缺少对应身份时，权限上下文本身无法构造。当前 scope 是工具目录级能力边界：它决定某类工具能否进入执行器，但不替代文件路径规范化、工作区根目录检查或操作系统 Sandbox。后续文件和命令工具仍需在各自 handler 内实施资源级检查。

## 4. 确认请求与结果

`ToolConfirmationRequest` 包含：

- `request_id`：`confirm_` 加 32 位十六进制摘要。
- `run_id`、`tool_call_id`、`tool_name`。
- 工具 `risk_level` 与 `scope`。

请求 ID 的摘要同时绑定用户、Agent、Session、工作区、工具参数和安全元数据。相同调用可稳定得到相同 ID；参数、运行或身份变化后 ID 随之变化，避免“批准一个调用却执行另一个调用”。该 ID 是本地关联标识，不是数字签名，可信边界仍依赖运行时不能让模型伪造 `ToolPermissionContext` 或确认结果。

`ToolConfirmationResult` 只接受精确的：

- `approved`：匹配请求可放行一次。
- `rejected`：明确拒绝，不执行 handler。

批准结果由 `ToolManager` 原子消费；同一结果在并发或重试中再次使用会被拒绝。管理器最多保留 10000 个已消费确认 ID，容量满后继续失败关闭，不通过淘汰旧记录重新开放重放窗口。

## 5. 当前 UI 边界

桌面确认 UI 尚未接入。默认 `ToolPermissionContext.confirmation_ui_available=False`，因此：

- `ask` 模式当前不会弹窗，而是返回“确认界面未接入，已默认拒绝”。
- `allow` 下的中高风险或显式确认工具也默认拒绝。
- 只有可信调用方明确声明 UI 可用、提供 `run_id`，并回传完全匹配的批准结果，工具才会执行。

测试中使用构造的可信上下文模拟未来 UI 往返，这只验证协议和执行边界，不代表桌面已经有确认按钮。真实聊天模型仍未接入工具循环。

## 6. 验证

P03-04 新增 11 项权限测试：

- 四类 scope 身份缺失拒绝与完整上下文规范化。
- `deny / ask / allow` 的差异语义。
- 中高风险和显式确认标记不能被 `allow` 绕过。
- 未授权 Session scope 拒绝，完整归属后允许。
- 确认请求 ID 稳定并绑定参数。
- 精确批准、明确拒绝、跨 Run ID 挪用拒绝。
- `deny`、无 UI 确认和重放均在 handler 前失败。

P03 工具专项测试由 34 项增至 45 项，全量测试由 171 项增至 182 项。Python 编译、全量回归和 `git diff --check` 均通过。

## 7. 尚未完成

- P03-05 已接通工具列表接口并完成 P03 综合 HTTP/执行验收，详见 [工具列表与阶段验收](P03_05_TOOL_INTERFACE.md)。
- P04 才将模型的 `tool_calls`、权限决策、handler 结果和下一轮模型请求组成 Agent Loop。
- 桌面确认卡片、按钮和可信确认回传尚未实现。
- scope 不等于资源级 ACL 或 OS Sandbox；文件、命令和网页能力在 P06 继续建设。
