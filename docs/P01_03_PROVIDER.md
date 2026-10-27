# P01-03：非流式 Provider 与 Fake Provider

日期：2026-10-21。状态：实现完成，离线行为测试及真实本地 HTTP 联调通过；外部模型供应商尚未实测。

本阶段让 Python 核心能够发送一次 Chat Completions 兼容请求，并将结果转换为 `ModelReply`。`app.py` 和桌面聊天仍是骨架，P01-04 才把 Provider 接到 `/message` 与模型配置接口。

## 1. 文件与职责

| 文件 | 核心作用 |
|---|---|
| `yanagent/models/provider.py` | 统一 `complete/stream` 协议，本阶段明确拒绝流式调用 |
| `yanagent/models/openai_compatible.py` | `prepare_request` 转换请求、`parse_reply` 转换响应、`OpenAICompatibleProvider` 组装一次调用 |
| `yanagent/models/transport.py` | 可注入 `JsonTransport`；默认 `UrllibJsonTransport` 完成 HTTP、超时、错误映射和受限 JSON 读取 |
| `yanagent/models/fake.py` | `FakeProvider` 依序返回预设结果/错误，保存每次输入快照 |
| `yanagent/errors.py` | 增加格式错误、空响应和拒绝回答三种错误 |
| `tests/test_provider.py` | 请求/响应转换、Fake、超时和传输错误测试 |
| `tests/test_provider_http.py` | 本地随机端口上的真实 HTTP 请求联调 |
| `examples/provider_demo.py` | 默认离线演示；显式 `--live` 时读取用户配置并真实调用 |

```text
AppConfig + Message 列表 + 工具描述
                 ↓
OpenAICompatibleProvider.complete()
                 ↓
配置就绪检查 → 对话配对校验 → 消息/Schema 转换
                 ↓
JsonTransport.post_json() → POST {api_base}/chat/completions
                 ↓
HTTP 错误分类 / 有大小限制的 JSON 读取
                 ↓
文本 + 工具参数 + finish_reason + usage → ModelReply
```

Provider 不执行工具、不自动重试、不保存会话、不生成 SSE，不代替 AgentLoop。

## 2. 请求转换约定

`complete(messages, tools=())` 接受内部 `Message` 列表或元组，以及供应商无关的工具字典列表或元组。消息不能为空，工具调用必须已经有对应结果；不允许把等待工具执行的半轮历史直接发给模型。

工具描述沿用现有 `ToolDefinition` 的字段：

```python
tools = [{
    "name": "calculator",
    "description": "计算表达式",
    "parameters": {
        "type": "object",
        "properties": {"expression": {"type": "string"}},
        "required": ["expression"],
    },
}]
```

转换为供应商的 `{"type":"function","function":{...}}` 包装。工具名称要求 1～64 个 ASCII 字母、数字、下划线或连字符，禁止重名；顶层参数类型要求 object，内部值要求标准 JSON。P03-01 已实现工具定义、封闭对象 Schema 和唯一注册；真实调用参数校验仍在 P03-03 实现。

- system/user/assistant 的正文按原文发送；内部 `metadata` 不发送。
- Assistant 的 `ToolCall.arguments` 从对象转为 JSON 字符串，保留 ID 与名称；纯工具调用时 content 为 null。
- Tool 结果保留 `tool_call_id`；成功结果正文直接发送；失败结果用 `{"is_error":true,"content":"..."}` 正文包装，因为兼容接口没有通用的 `is_error` 消息字段。
- 未提供工具时省略 `tools`，不发送空数组；请求明确使用 `stream=false`。
- URL 使用 `api_base.rstrip('/') + '/chat/completions'`。配置应填 API 根路径，如本地服务的 `http://127.0.0.1:端口/v1`，不要填完整 `/chat/completions` 地址；是否需要 `/v1` 由供应商定义，本实现不猜测。
- 认证使用请求头 `Authorization: Bearer ...`，不把密钥写进 URL 或 JSON 正文。默认不自动重定向，避免转发凭据。

## 3. 响应转换约定

| 供应商字段 | 内部字段与处理 |
|---|---|
| `choices[0].message.content` | `ModelReply.content`；null 可转空串，非文本内容块本阶段不支持 |
| `message.tool_calls[].id` | `ToolCall.id`；缺失或同轮重复时拒绝，不自动生成 |
| `message.tool_calls[].function.name` | `ToolCall.name`；这里只保留名称，是否注册由后续工具系统检查 |
| `function.arguments` | 必须是严格 JSON 字符串且解析成对象；错误不补成 `{}` |
| `choices[0].finish_reason` | 原样保留非空字符串，缺失/null 为 None，不猜测未知厂商值 |
| `usage.prompt_tokens` | `usage.input_tokens` |
| `usage.completion_tokens` | `usage.output_tokens` |
| `usage.total_tokens` | `usage.total_tokens` |

只接受单候选完整响应，不静默丢弃多个候选；不支持旧版 `function_call`。工具调用可以有多个，且允许没有文本。文本因 `length` 截断时保留部分内容和结束原因，由调用方决定后续策略。

Usage 缺失为 `{}`；某个字段缺失就省略该字段，明确的 null 和零分别保留。不推算总 Token，不把未知值写为零。嵌套缓存/推理 Token 明细和厂商 Thinking 字段本阶段不映射。

新增的公开错误：

- `model_response_error`：响应形状错误、JSON 损坏、重复 JSON 键、非法工具参数、超出大小限制等。
- `empty_model_response`：没有文本，也没有工具请求；或 choices 为空。
- `model_refusal`：模型明确 refusal 或 `content_filter`；不把拒绝正文当成普通答案。

HTTP 401/403/404/408/429/5xx 使用 P01-02 的分类。HTTP 200 中带 error 包络只标识响应错误，不从正文猜测认证或限流。底层异常正文、错误响应体及密钥不进入统一错误说明。

## 4. HTTP 与异步边界

默认实现仅使用 Python 标准库，无新增依赖。真实阻塞 HTTP 请求放到 `asyncio.to_thread` 中执行，外层 `wait_for` 使用配置的 `request_timeout` 限制等待时间，底层 socket 操作也传入该超时。超时不会自动重发请求；调用方取消仍向上传播 `CancelledError`。

响应读取默认上限 **8 MiB**，可在构造 `UrllibJsonTransport(max_response_bytes=...)` 时调整。超过上限拒绝解析；成功和失败均关闭响应。不为 HTTP 错误读取并记录原始正文。

需要注意：取消 Future 或等待超时不等于杀死后台线程。DNS 阶段、慢速持续回包等情况可能让工作线程继续运行；`asyncio.run` 退出时也可能等待线程池回收。本阶段不承诺底层连接立即取消或全过程硬时限，P01-05 必须继续处理流式传输与取消生命周期，不能把当前实现当成已完成桌面停止生成。

默认 urllib 会遵循系统代理配置；本地联调必须能直连回环地址。本阶段不实现代理配置页面、连接池、备用模型、自动重试或多厂商协议。

## 5. Fake Provider

```python
from yanagent.contracts import Message, ModelReply
from yanagent.errors import RateLimitError
from yanagent.models import FakeProvider

fake = FakeProvider([
    ModelReply(content="第一次回答"),
    RateLimitError(),
    ModelReply(content="第三次回答"),
])

reply = await fake.complete([Message(role="user", content="你好")])
```

- 每次有效输入消费一个预设。预设错误也消费一轮；非法输入不消费、不记录。
- 响应耗尽时抛 `FakeProviderExhaustedError`，不重复最后一个答案掩盖多调用问题；耗尽后的有效调用也记入记录。
- `fake.calls` 返回包含每轮 messages/tools 的独立副本；`fake.remaining` 返回剩余预设数。
- 预设响应、实际返回和输入记录均独立复制。修改外部消息或返回内容不会污染以前记录。
- Fake 允许预设契约合法的空 `ModelReply`，供未来上层失败策略测试；真实 Provider 的空响应检测仍在原始 JSON 解析边界执行。
- Fake 目前复用兼容请求的输入检查，范围是本阶段文本和函数工具格式。没有执行工具、延迟模拟或完整 Agent 循环，使用者显式追加模拟工具结果。

## 6. 验收

从项目根目录运行：

```powershell
cd C:\Users\1\Documents\ChatGPT\langgraph\code\YanAgent
.\.venv\Scripts\python.exe -X utf8 -W error -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -X utf8 -W error -m examples.provider_demo
.\.venv\Scripts\python.exe -X utf8 -W error -m compileall -q -f app.py yanagent tests examples
```

本次结果：**75 项测试全部通过**，含本次新增 26 项（22 项转换/异步/传输测试，4 项本地 HTTP 集成测试），原有 49 项通过。演示和语法检查通过。

本地 HTTP 测试监听 `127.0.0.1` 的随机端口，使用虚构密钥，验证真实请求路径、UTF-8 正文、认证头、文本/工具响应、HTTP 401/429、重定向不跟随。它验证的是本机 HTTP 链路，不是外部供应商可用性。

默认演示应输出：第一轮工具请求、手工插入固定结果后的第二轮答案、第二轮角色顺序 `user → assistant → tool`，最后显示“验收通过”。演示没有执行计算器，输出的 Token 数字也是预设值。

当前 Codex Windows 沙箱无法正常创建默认 asyncio 事件循环，本次在经工具审批的普通执行环境中运行异步测试与回环联调。普通 PowerShell 可使用上面的命令，不需要修改项目的事件循环策略来规避沙箱。

如果你已按 P01-02 配置好 API Base、模型和密钥，可以**主动**运行一次真实模型验收：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m examples.provider_demo --live --prompt "你好"
```

只有 `--live` 会请求配置中的服务，可能产生供应商调用费用；输出真实 `ModelReply`，失败输出统一错误并以非零状态退出。本次未执行该模式，未读取或使用你的真实密钥。

## 7. 难度与后续

本次整体工程难度评为 **6/10**。难点集中在工具请求/结果转换、严格解析与未知用量表达、异步等待和底层资源生命周期、可复现 Fake 输入快照。详细实现取舍、难点评分及岗位关联记录在根目录 `workProcess.md`。

下一项为 **P01-04 普通聊天联调**：接通配置/模型接口和 `/message`，先显示 `inline_reply`。本任务没有完成 P01 整阶段，也没有实现流式、工具执行、会话持久化或多 Agent。
