# P05-01 Bridge 收口

状态：已实现
当前桌面 HTTP 入口：单用户 `local`、单 Agent `default`

## 本项交付

`AgentBridge` 成为 HTTP 层和运行引擎之间的统一入口。P05-01 首次交付时 Bridge 持有默认身份的 `AgentRuntime` 实例；P05-02 已将实例缓存扩展为按身份组合分开，并为非流式任务、流式任务、SSE 事件订阅、取消、异步控制操作和关闭提供统一方法。

标准 `RunRequest` 可以经 `AgentBridge.dispatch()` 执行非流式 Agent Loop，并返回带 request/session/user/agent、模型轮数、累计 Usage 和最终正文的 `RunResult`。未提供 request_id 时由 Bridge 分配。

流式请求仍在 `AgentRuntime.start_stream()` 中完成请求校验和 `PreparedChat` 配置/Provider 快照创建；快照随任务传给异步执行，不受后续配置变更影响。Bridge 统一委托已有的运行登记、事件回放订阅、取消和终态保留逻辑，并在服务关闭时释放运行线程和事件循环。

HTTP 路由继续沿用原有请求/响应格式。服务现在持有 `AgentBridge`，Handler 的兼容 `runtime` 属性实际返回 Bridge，避免本次内部架构收口改变桌面协议。

## 范围边界

- P05-02 已把实例缓存扩展到 `(user_id, agent_id)`，并把 Session 队列键扩展到 `(user_id, agent_id, session_id)`。
- 当前 HTTP 桌面入口仍使用可信的 `local/default` 身份；本地桌面未接入多用户认证。`RunRequest` 身份用于 Bridge 内路由，不等于认证或授权凭证。
- P05-02 实现细节见 [P05-02 身份与并发](P05_02_IDENTITY_CONCURRENCY.md)。
- P05-03 实现运行中追加指令和更完整的协作式取消。
- P05-04 实现上下文预算、压缩和截断。
- 本项未新增或运行自动化测试；后续验证应覆盖 dispatch 契约、Bridge 生命周期以及已有 HTTP/SSE 行为。

## 岗位要求关联与实践证据

对应 `docs/TARGET_ROLES.md` 中“Agent 核心闭环”和“路由、任务调度与多入口”条目：本项将应用入口收口到统一 Bridge，并把标准 Run 契约、运行实例、运行任务、事件订阅和资源生命周期连成一条边界；身份路由和 Session 队列由 P05-02 补齐。桌面入口仍是单用户默认身份，也没有完整的多 Agent 配置。

实现难度：**6/10**。主要难点是保持现有 HTTP/SSE 行为和旧 Runtime 调用面不变，同时增加标准 Bridge 调度入口及资源所有权；通过组合既有 AgentRuntime、由 Bridge 统一委托和关闭来降低迁移面。自动化行为证据尚未补充，不能据此声称验证了运行稳定性或并发隔离。
