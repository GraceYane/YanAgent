# P01-01：统一数据契约实现说明

任务依据：[开发需求与实施计划](DEVELOPMENT_REQUIREMENTS.md) 的 P01-01。实现位置：`yanagent/contracts.py`。

## 1. 为什么先做数据契约

模型、工具、Session、运行时要共同理解一段任务数据。参考 CowAgent 的 `agent/protocol/message_utils.py` 可以看到，丢失工具请求或工具结果会破坏历史，必须修复或丢弃孤立结果。

YanAgent 在写入和调用模型之前提供显式校验：保留完整请求与结果，错误数据报错；运行中尚未完成的调用通过显式选项处理。厂商适配和历史恢复后续分别实现。

## 2. 六种结构

| 结构 | 用途 | 关键字段与约束 |
|---|---|---|
| `ToolCall` | 模型要求执行的动作 | `id`、`name` 非空，`arguments` 为 JSON 对象；尚不检查工具是否存在或参数 Schema |
| `Message` | 历史中的一条完整消息 | 四种角色；`tool_calls` 仅用于 Assistant；`tool_call_id`、`is_error` 仅用于 Tool |
| `ToolResult` | 工具执行返回值 | 引用原调用 ID，保存文本及错误状态；`to_message()` 转成 Tool 历史消息 |
| `ModelReply` | 一次模型调用的完整响应 | 文本、工具调用、结束原因和用量；`to_message()` 完整保留工具请求 |
| `RunRequest` | 一次用户任务的输入 | 会话、用户输入、Agent、用户和请求标识，以及 JSON 元数据 |
| `RunResult` | 整个任务的最终结果 | 内容、身份、模型调用轮数、累计用量和终态 |

`ModelReply` 可以只有工具调用而无文本，也可以为空响应。空响应如何重试或失败，是后续 Provider/Loop 的业务策略。`Message` 当前保存文本，图片等内容块在 P06 扩展。

### 身份字段的区别

| 字段 | 含义 | 当前默认值 |
|---|---|---|
| `user_id` | 用户归属 | `local`，仅供本地单用户起步 |
| `agent_id` | 本次任务对应的 Agent | `default` |
| `session_id` | 持续对话，可包含多个 Run | 必填非空字符串 |
| `request_id` | 单次 Run 的请求标识 | `None`，等待后续 Bridge 分配 |

请求和结果都保存上述字段，便于之后关联。字段存在不代表已实施认证、访问控制或多 Agent 隔离；这些由后续入口、Store 和 Bridge 实现。

### 用量与状态

`usage` 使用非负整数或 `None`：空字典表示没有用量信息，`None` 表示该项未知，`0` 表示明确的零。建议后续统一使用 `input_tokens`、`output_tokens` 等内部键，供应商字段由 Provider 转换；当前保留扩展键。

`turns` 表示模型调用轮数，必须为非负整数，不接受 Python 的布尔值冒充整数。

`RunResult.status` 支持 `completed / failed / cancelled / interrupted`。排队、运行等中间状态由后续运行时管理。

## 3. 构造、保存与还原

所有结构都提供：

```python
obj.validate()           # 检查当前字段
data = obj.to_dict()    # 生成独立字典
text = obj.to_json()    # 生成保留中文的 JSON 文本
restored = type(obj).from_dict(data)
restored = type(obj).from_json(text)
```

构造时自动校验；序列化时重新校验，因此对象后续被改成非法状态也不能保存。反序列化拒绝未知字段和缺少必填字段，不将错误数字、布尔或对象强制转成字符串。

嵌套 `tool_calls` 在还原后仍是 `ToolCall` 实例。参数、元数据必须由标准 JSON 类型组成，禁止非字符串键、元组、集合、日期对象、NaN、Infinity 和循环引用，避免 JSON 隐式转换造成丢失或歧义。JSON 文本中的重复键会被拒绝。

错误类型为 `ContractValidationError`（继承 `ValueError`）。错误信息指出字段和规则，不回显原始消息正文、工具参数和元数据。

数据类允许修改字段；可变嵌套对象也不是深度不可变。外部边界应调用 `validate()` 或使用经过校验的序列化入口，不能把类型标注当作运行时权限保障。

## 4. 工具请求与结果怎样配对

```text
User：计算 1 + 2
Assistant：tool_calls = [ToolCall(id="call_001", ...)]
Tool：tool_call_id = "call_001"，content = "3"
Assistant：计算结果是 3
```

单条 Tool 消息可以独立构造，因为它之后还要被存入或读取数据库。完整序列通过 `validate_conversation(messages)` 检查：

- 结果必须引用前面待完成的调用，不能孤立、重复返回或引用其他 ID。
- 同一组工具结果可以乱序返回，但全部返回前不能追加新的普通消息。
- 调用 ID 在被校验的整段对话内保持唯一；每条工具请求先于结果。
- 完整历史默认不允许尾部存在未完成调用。
- 运行中暂存 Assistant 请求时可使用 `allow_pending_tool_calls=True`，只允许尾部未完成，不放宽中间错误配对。

```python
validate_conversation(messages)
validate_conversation(pending_messages, allow_pending_tool_calls=True)
```

该函数只验证，不执行工具、不生成结果、不修复历史。暂停、取消、摘要裁剪和跨厂商 ID 转换策略在后续阶段接入此约束。

## 5. 可复现示例与测试

在项目根目录执行：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m examples.contracts_demo
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

示例打印四条完整消息，验证 JSON 保存前后相等及调用配对，并输出关联同一 Run 的结果。计算结果是固定测试数据，没有调用真实模型或计算器。

测试覆盖六种结构往返、旧构造方式兼容、可变数据独立性、未知用量、字段和角色、嵌套 JSON、重复键、重复工具 ID、孤立结果、结果乱序、未完成尾部和错误标记保留。

## 6. 当前范围和下一步

P01-01 完成数据契约；真实 Provider、配置、HTTP/SSE、Session 持久化和 Agent Loop 尚待后续开发。

下一项为 **P01-02：配置与统一错误**。岗位关联详见本次 `workProcess.md`：本任务覆盖统一消息/工具协议基础，尚不能代表已实现完整 Agent 编排或多用户权限隔离。
