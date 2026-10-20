# YanAgent 核心能力实现路线

这份路线不是让功能“能演示”就算完成，而是给每一阶段一个可以测试的工程验收条件。

## Phase 1：模型适配

实现位置：`yanagent/models/provider.py`

- 至少接入一个 OpenAI-compatible Provider。
- 输入统一的 `Message`，输出统一的 `ModelReply`。
- 支持文本、Tool Call、流式增量和 Usage。
- API Key 不写入日志或 Git。
- 为超时、401、429、5xx 定义统一异常。

验收：使用 Fake Provider 的单元测试不联网也能覆盖文本、流式、Tool Call 和错误映射。

## Phase 2：Session 与上下文

实现位置：`yanagent/sessions/store.py`

- SQLite schema 与迁移机制。
- 创建、追加、分页、删除和恢复会话。
- `user_id + agent_id + session_id` 三层隔离。
- Token 估算、旧消息裁剪和摘要。
- 不允许截断 `assistant.tool_call` 与对应 `tool` 消息。

验收：重启进程后历史仍存在；并发写入不乱序；不同 Agent 读不到彼此数据。

## Phase 3：工具系统

实现位置：`yanagent/tools/manager.py`

- 注册工具并生成 JSON Schema。
- 校验未知工具、缺失字段、字段类型和额外字段。
- 权限模式：`deny / ask / allow`。
- 超时、异常封装、输出截断和敏感信息过滤。
- 只并行执行互不依赖且允许并行的工具。

验收：危险工具未经授权不会执行；工具异常会成为模型可理解的 ToolResult，而不是击穿 Agent 进程。

## Phase 4：Agent Loop

实现位置：`yanagent/runtime/agent_loop.py`

- 组装 System Prompt、历史消息、用户输入和工具 Schema。
- 执行 `模型 -> 工具 -> 模型` 多轮循环。
- 最大轮数、连续失败数和总超时限制。
- 用户取消与运行中追加指令。
- 事件流：文本、思考、工具开始/结束、完成、错误。
- 最终回复和中间记录持久化。

验收：Fake Model 连续请求两个工具后生成最终答案；循环不会无限执行；取消后数据库仍保持一致。

## Phase 5：Bridge 与 HTTP/SSE

实现位置：`yanagent/runtime/bridge.py` 和 `app.py`

- `/message` 创建后台任务并返回 `request_id`。
- `/stream` 以 SSE 推送规范化事件。
- `/cancel` 精确取消一个请求。
- Session 恢复、Agent 路由、运行实例缓存。
- 同一 Session 串行，不同 Session 可并发。

验收：桌面端能看到流式文字和工具卡片；刷新 UI 后历史可恢复；两个会话并发不会串流。

## Phase 6：高级能力

按这个顺序实现：

1. Skills：先做本地只读加载，再做安装与热刷新。
2. MCP：先做 stdio，再做 Streamable HTTP，最后做 OAuth。
3. Memory：先关键词检索，再做 Embedding、混合召回、Rerank。
4. Multi-Agent：先单层委派，再做 Team 会话和跨 Agent 消息。

## 必须长期保持的非功能指标

- 可取消：任何长任务都要有取消检查点。
- 可观测：每次 Run、模型调用和工具调用都有结构化日志与耗时。
- 可恢复：进程异常退出后不产生半条不可解析消息。
- 可隔离：用户、Agent、Session、Workspace 数据边界明确。
- 可测试：模型、工具、时间和存储都能替换为 Fake。
- 安全：路径限制、命令白名单、SSRF 防护、密钥脱敏和最小权限。
