# P01-04 普通聊天联调

## 1. 本次完成的链路

```text
桌面聊天框
  ↓ POST /message（现有客户端仍发送 stream=true）
YanAgentHandler：限制正文大小、解析 JSON、统一 HTTP 错误
  ↓
YanAgentApplication：校验 Session、消息和当前阶段能力
  ↓
ConfigStore：读取不可变生效配置快照
  ↓
OpenAICompatibleProvider.complete()
  ↓
ModelReply → stream=false + inline_reply
  ↓
现有 chatStore 将完整回答写入 Assistant 气泡
```

P01-04 只发送当前这一条用户消息。聊天历史和多轮上下文属于 P02；工具执行属于 P03～P04；逐字增量、SSE、真正取消和请求队列属于 P01-05。

## 2. 桌面配置接口

底层只保存 P01-02 的 8 个字段：`host`、`port`、`model_provider`、`api_base`、`model`、`api_key`、`request_timeout`、`permission_mode`。

- `GET /config`：为复制的旧设置页面提供兼容字段，密钥只显示为 `********`。
- `POST /config`：接受 `{ "updates": {...} }`；`bot_type` 映射为 `model_provider`，`agent_permission_mode` 映射为 `permission_mode`。
- `GET /api/models`：返回一个 `openai-compatible` Provider 和当前聊天模型状态。
- `POST /api/models`：本阶段支持 `set_provider`、聊天能力的 `set_capability`、`delete_provider`；其他能力明确返回不支持，不伪造成功。

模型控制台展示的 `gpt-4o-mini`、`deepseek-chat`、`qwen-plus` 只是首次设置时可替换的常见模型名称，不代表对应服务已经配置或验证。API Base 留空时首次凭据保存使用 `https://api.openai.com/v1`；使用其他兼容服务时必须明确填写对应地址，并让模型名称与其匹配。

## 3. 消息接口

请求示例：

```json
{
  "session_id": "session-1",
  "message": "你好",
  "stream": true,
  "attachments": [],
  "is_voice": false,
  "agent_id": "default"
}
```

P01-04 成功响应：

```json
{
  "status": "success",
  "request_id": "run-...",
  "stream": false,
  "inline_reply": "模型的完整回答",
  "speaker": "default",
  "received_session_id": "session-1",
  "finish_reason": "stop",
  "usage": {}
}
```

虽然现有桌面端发送 `stream=true`，后端会明确返回 `stream=false`，`chatStore` 随即使用 `inline_reply` 完成气泡。P01-05 才会返回流式 Run 并连接 SSE。

## 4. 校验和错误

- HTTP 正文上限为 1 MiB，单条消息上限为 200,000 个字符。
- 空 `session_id`、空消息、坏 JSON、错误字段类型和未知字段返回 `request_validation_error`。
- 本阶段不接收非空附件、语音输入、其他 Agent 或意外工具调用。
- 配置、认证、权限、模型不存在、限流、超时、连接和响应错误映射为明确 HTTP 状态及统一 JSON 错误。
- 每次消息请求在进入模型前分配 `request_id`；日志包含文件、函数、请求 ID 和错误码，但不记录消息正文、API Key 或上游错误正文。
- 桌面 API Client 会读取安全的 JSON `message`，聊天气泡能显示具体中文原因，而不是只有 `HTTP 400`。

## 5. 手工验收

在项目根目录创建自己的 `config.json`，或打开桌面端“设置 → 模型”填写兼容 API Base、API Key 和模型名称。不要提交真实密钥。

```powershell
cd C:\Users\1\Documents\ChatGPT\langgraph\code\YanAgent\desktop
npm run dev
```

桌面进程会自动启动上一级 `app.py`。发送“你好”后，当前阶段应一次性显示完整模型回答。若未配置，应显示安全的配置错误；错误密钥、限流和超时由统一错误映射反馈。

也可先查询接口：

```powershell
Invoke-RestMethod http://127.0.0.1:9876/api/health
Invoke-RestMethod http://127.0.0.1:9876/api/models
Invoke-RestMethod http://127.0.0.1:9876/config
```

## 6. 自动验证证据与限制

- 9 项 P01-04 测试（补充配置缺失用例后为 10 项）覆盖应用层和真实回环 HTTP；全量测试最终数量以 `workProcess.md` 为准。
- 回环测试验证桌面消息字段、`inline_reply`、模型/配置路径、密钥脱敏、400 与 401 错误。
- `npm run build` 通过；已有字体、Browserslist、动态/静态导入和大包警告不影响构建成功，本次未处理这些既有警告。
- 本次没有读取或使用用户真实密钥，没有请求外部模型，因此“外部真实模型桌面联调”仍留在 P01-06 记录。
- `BaseHTTPRequestHandler` 请求线程中暂用 `asyncio.run()` 完成一次非流式调用。P01-05 必须改为长期运行的异步任务环境，不能沿用每请求一个事件循环来实现 SSE、取消和并发运行管理。
