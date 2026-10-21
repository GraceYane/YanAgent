# P01-05 流式链路

## 本次交付结果

P01-05 把 P01-04 的“一次请求、一次完整回答”升级为可持续运行、可订阅、可取消的最小流式 Runtime：

```text
桌面 POST /message (stream=true)
  ↓
分配 request_id，登记 RunRecord
  ↓
常驻 asyncio 事件循环执行 Provider.stream()
  ↓
模型 SSE → ModelStreamEvent → RunEvent 队列
  ↓
桌面 GET /stream?request_id=... 回放并跟随 delta/done/error
  ↓
POST /cancel 跨线程取消任务，输出 cancelled + done 终态
```

非流式请求仍受支持，但也改为提交到同一个常驻事件循环，不再在每个 HTTP 请求线程中调用 `asyncio.run()`。

## 关键模块

| 文件 | 职责 |
|---|---|
| `yanagent/events.py` | 定义 Provider 层 `ModelStreamEvent` 和 Runtime 层 `RunEvent`，防止供应商 JSON 直接污染桌面协议 |
| `yanagent/models/openai_compatible.py` | 发送 `stream=true` 请求；解析增量文本；按 tool index 组装 ID、名称和参数 JSON；在 `[DONE]` 后生成唯一 `ModelReply` |
| `yanagent/models/transport.py` | 使用标准库在线程中读取真实 HTTP SSE；限制总响应和单事件大小；禁止重定向；把数据帧安全交给 asyncio；取消时异步关闭响应 |
| `yanagent/models/fake.py` | 支持可控的完整响应序列和流式事件序列，供离线并发、错误和取消测试使用 |
| `yanagent/runtime/streaming.py` | 维护唯一后台事件循环、Run 注册表、线程安全事件列表、晚订阅回放、取消竞态兜底和终态 TTL 清理 |
| `app.py` | 实现 `/message` 流式分支、`/stream` SSE、`/cancel`，并在 Server 关闭时回收 Runtime |

## 三层事件边界

1. 供应商层：HTTP SSE 的 `data: {...}` 或 `data: [DONE]`。
2. 模型层：`text_delta`、`tool_call_delta`、`completed`。完成事件必须携带完整统一 `ModelReply`。
3. 桌面层：匿名 SSE 的 JSON 正文，当前最小集合为 `delta`、`cancelled`、`done`、`error`。

桌面端现有代码使用 `EventSource.onmessage`，所以后端发送：

```text
data: {"type":"delta","content":"你"}

data: {"type":"delta","content":"好"}

data: {"type":"done","content":"你好","finish_reason":"stop","usage":{}}
```

这里没有使用 `event: delta` 这类命名事件，否则现有桌面端不会进入 `onmessage`。

## 工具参数增量组装

模型可能把一次工具调用拆成多块：

```text
块 1：index=0, id=call-1, name=calculator, arguments={"x":
块 2：index=0, arguments=3}
```

`StreamReplyBuilder` 按 `index` 关联片段，拒绝索引空洞、ID/名称冲突、非函数类型、坏 JSON 和非对象参数，最后还原为：

```json
{"id":"call-1","name":"calculator","arguments":{"x":3}}
```

P01-05 只完成“正确识别和组装”这一步。当前普通聊天没有开放工具，模型若意外返回工具调用，Runtime 会发送明确错误，不会擅自执行。工具注册、权限和执行属于 P03～P04。

## Run、订阅和并发隔离

- 每次流式消息由后端生成不可复用的 `request_id`。
- 每个 `RunRecord` 独立保存 `session_id`、事件序号、任务 Future 和终态。
- 事件在锁内追加并唤醒 SSE 线程；订阅从 cursor 0 开始，所以模型先返回、浏览器后连接也不会丢掉开头。
- 两个请求可以在同一个 asyncio 循环交错执行，但事件只写入各自的 Run。
- `done` 或 `error` 是终态；终态 Run 默认保留 60 秒，之后在下一次访问时惰性清理。
- SSE 客户端意外断开不会取消后台任务；重新连接同一 request_id 可以重新回放。这为后续 P02/P05 的恢复机制保留了边界。

## 取消语义

`POST /cancel` 优先按 `request_id` 精确取消；没有 request_id 时可以按 `session_id` 取消该会话活动 Run。成功取消后：

1. `concurrent.futures.Future.cancel()` 把取消传到常驻 asyncio 循环；
2. 模型异步生成器收到 `CancelledError`；
3. Runtime 发送 `cancelled`，再发送 `done(finish_reason=cancelled)`，保证桌面和 SSE 都能结束等待；
4. 若任务在进入协程函数体前就被取消，100 ms 兜底计时器仍会补齐终态，避免竞态造成永久悬挂；
5. 已终态或重复取消返回 `cancelled: 0`。

标准库 `HTTPResponse.close()` 在 Windows 上可能等待另一个线程中的阻塞 `readline()`。因此取消协程时不在事件循环线程同步关闭它，而是交给守护关闭线程；读取线程还受配置的 socket timeout 约束。这样 UI 和 Runtime 任务可以立即结束，底层阻塞线程在有限超时内回收。测试验证取消等待约 0.1 秒内返回，但这不是“操作系统级强杀 socket”的承诺。

## HTTP 契约

流式创建成功：

```json
{
  "status": "success",
  "request_id": "run-...",
  "stream": true,
  "speaker": "default",
  "received_session_id": "session-..."
}
```

SSE 地址：

```text
GET /stream?request_id=run-...
```

取消请求：

```json
{"request_id":"run-...","session_id":"session-..."}
```

未知 request_id 的 SSE 会返回 `type=error, reason=unknown_request`。错误事件只包含统一错误码和安全中文说明，不回显上游正文、密钥或请求内容。

## 自动验收证据

```powershell
cd C:\Users\1\Documents\ChatGPT\langgraph\code\YanAgent
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
cd desktop
npm run build
```

结果：

- 96 项 Python 测试通过；
- 真实回环 HTTP 验证普通请求、真实 SSE 分块、`[DONE]`、取消、HTTP 错误与禁止重定向；
- Runtime 测试验证双请求隔离、晚订阅回放、运行中取消、立即取消竞态和终态清理；
- 桌面生产构建通过，TypeScript 与现有 `StreamEvent` 契约兼容。

## 当前边界与下一步

- 没有把消息或 Run 写入数据库；P02 才实现会话与持久化。
- 没有执行工具或形成模型—工具循环；P03～P04 才实现。
- 没有追加指令、上下文压缩、崩溃恢复或完整 AgentBridge；P05 才实现。
- 没有使用用户的真实外部 API Key 发请求，也没有完成桌面人工截图验收；这些属于 P01-06。
- 当前下一项是 **P01-06 验证与文档**：补齐外部模型、桌面停止生成、错误路径和阶段级验收记录。
