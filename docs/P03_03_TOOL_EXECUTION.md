# P03-03 统一工具执行

状态：已完成  
完成日期：2026-10-28  
后续状态：P03-04～P03-05、P04-01 已完成；下一项为 P04-02 非流式 Agent Loop

## 1. 本阶段交付

P03-03 把 P03-01 注册表和 P03-02 handler 接成统一执行链：

```text
ToolCall
   ↓ 契约检查
权限模式最小闸门
   ↓ 工具查找
参数 Schema 校验并复制
   ↓ 单工具超时
异步 handler
   ↓ 类型检查与输出截断
ToolResult(tool_call_id, content, is_error)
```

成功和失败都保留原 `tool_call_id`。参数错误、未知工具、超时、受控 handler 失败、未知异常、错误返回类型和过大输出均不会作为未处理异常冲垮服务。

## 2. 参数校验子集

`yanagent/tools/validation.py` 实现当前工具系统使用的 JSON Schema 子集，不宣称是完整 JSON Schema 标准实现：

- 类型：`object / array / string / integer / number / boolean / null`。
- 对象：`properties / required / additionalProperties`。
- 字符串：`minLength / maxLength`。
- 数组：`items / minItems / maxItems`。
- 数字：`minimum / maximum`。
- 通用：`enum`。

整数和布尔严格区分，`True` 不会被当成 `1`。所有参数通过后再深复制给 handler，handler 对嵌套字典或列表的修改不会污染原 `ToolCall`，便于 P04 保存模型原始调用消息。

缺失、未知、类型和约束错误使用固定安全说明，不回显模型提交的原始参数。Provider 已在字符串参数解析阶段拒绝损坏 JSON；执行器仍会再次调用 `ToolCall.validate()`，即使边界外绕过构造检查传入损坏对象，也会得到关联调用 ID 的失败结果。

## 3. 统一结果与异常边界

| 情况 | `is_error` | 对模型返回 |
|---|---:|---|
| handler 成功 | `false` | handler 的字符串结果，必要时截断 |
| 调用或参数不合法 | `true` | 固定参数错误说明 |
| 未知工具 | `true` | 工具不存在或不可用 |
| `ToolHandlerError` | `true` | 最多 500 字的受控公开说明 |
| 未知异常 | `true` | 固定“工具执行失败”，不回显异常正文 |
| 返回值不是字符串 | `true` | 固定结果类型错误 |
| 超时 | `true` | 固定超时说明 |

未知异常日志只记录异常类型、工具名和调用 ID，不记录原始参数或异常正文。调用方取消使用 `asyncio.CancelledError` 向上传播，不会伪装为普通工具失败，便于后续 Run 正确进入 cancelled 状态。

## 4. 超时与输出限制

`ToolManager` 默认单工具超时为 30 秒，可配置范围为 `0 < timeout <= 600`。当前使用 `asyncio.wait_for()`，能够取消正常协作的异步 handler；如果 handler 在事件循环中直接执行长时间阻塞代码或故意吞掉取消，Python 无法强制终止它。后续阻塞型工具必须像 Provider 网络层一样使用线程/进程隔离，并在底层设置自己的期限。

默认输出上限为 20000 个字符，可配置范围为 64～1000000。超过上限时保留头部，并在总上限内追加：

```text
...[工具输出已截断，原始字符数=...]
```

本阶段不把完整输出写入临时文件，因此不存在未受控文件路径；未来若需要保留完整产物，必须先通过工作区路径和权限校验。

## 5. 后续权限状态

P03-03 完成时，为避免权限绕过，只有 `permission_mode="allow"` 会进入 handler；`deny`、`ask` 和非法模式都在 handler 前失败关闭。P03-04 现已将该最小闸门替换为完整基础决策：

- `deny` 全拒绝，`ask` 全确认，`allow` 自动放行低风险且无需确认的工具。
- `risk_level / scope / requires_confirmation` 已参与执行判断。
- 已定义与运行、身份、调用和参数绑定的确认请求 ID，以及批准/拒绝结果。

详见 [工具权限基础](P03_04_PERMISSION_FOUNDATION.md)。桌面确认 UI 仍未接入，需确认的操作默认拒绝。

## 6. 验证证据

`tests/test_tool_execution.py` 新增 13 项测试，覆盖：

- 计算器与时间工具统一执行，成功结果关联原调用 ID。
- 缺失、未知、错误类型和损坏参数在 handler 前失败。
- 嵌套对象、数组、布尔、长度和数值范围。
- handler 参数深复制隔离。
- 未知工具。
- `deny / ask / invalid` 失败关闭且 handler 不执行。
- 超时取消和结构化失败。
- 受控失败、未知异常和后续继续服务。
- 非字符串返回值。
- 大输出截断标记及总长度。
- 外层取消继续向上传播。
- 超时和输出配置边界。

P03-03 完成时 P03 共 34 项工具测试、全量共 171 项测试通过；P03-04 完成后分别增至 45 项和 182 项。

## 7. 当前边界

- `deny / ask / allow`、作用范围和确认协议已由 P03-04 完成；桌面确认 UI 尚未接入。
- HTTP 工具列表及阶段综合失败测试已由 P03-05 完成，详见 [工具列表与阶段验收](P03_05_TOOL_INTERFACE.md)。
- 模型工具 Schema 注入、Assistant 工具调用消息保存、工具执行和结果回写后的下一轮模型请求由 P04 完成。
- 当前可以从 Python 调用统一执行器，但桌面聊天仍不会自动使用时间或计算器。
