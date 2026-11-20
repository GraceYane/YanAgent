# P05-02 身份与并发

状态：已实现，自动化验证待补
当前桌面 HTTP 身份：`local/default`

## 本项交付

- `AgentBridge` 以 `(user_id, agent_id)` 作为运行实例缓存键；每个身份组合有独立的 `AgentRuntime`、`SessionStore` 和 `RunStore`。身份组合共享模型配置、Provider 工厂、工具目录及上下文构建器。
- 每次聊天以 `(user_id, agent_id, session_id)` 作为队列键。流式和非流式路径共用常驻 Runtime 中的异步锁；同一键的任务按锁等待顺序串行，不同会话或身份组合不共享锁，可以并发执行。
- 非流式任务在进入等待队列前建立 `PreparedChat`，配置与 Provider 快照随任务保留；排队期间配置变化不会改变该任务快照。
- 流式 RunRecord 显示 `queued / running / terminal` 生命周期。取消仍在排队中的流任务会结束为 `cancelled_before_start`，不会进入 Agent Loop；取消运行中任务会走现有协作取消处理。HTTP `/cancel` 在原有 `cancelled` 数量之外返回 `queued_cancelled` 与 `running_cancelled`。
- 事件读取和取消均通过指定身份实例操作，不能从一个身份实例读取另一个实例的 Run 记录。

## 身份边界

桌面 HTTP 入口没有多用户认证机制，仍由本地服务固定路由到 `local/default`。`RunRequest.user_id/agent_id` 是 Bridge 的路由字段，不是认证凭证；后续接入远程或多用户入口时，必须由可信入口解析身份，再构造 RunRequest，不能直接相信客户端自报身份。现有聊天协议仍只接受 `default` Agent；Bridge API 的身份隔离为仓储归属和并发边界，不代表系统已具备独立 Agent 配置或完整多 Agent 能力。

## 验证情况

本次没有新增或运行自动化测试。仍需通过行为测试确认：同 Session 两任务不交错、不同 Session 两任务可并发、身份仓储互相隔离、排队取消不启动 Agent Loop、运行中取消只影响目标 Run，以及旧 HTTP/SSE 行为兼容。

## 岗位要求关联与实践证据

对应 `docs/TARGET_ROLES.md` 的“Session、上下文和数据隔离”“路由、任务调度与多入口”条目：代码按完整身份创建实例和数据仓储，并按完整 Session 作用域串行化任务；不同队列键不争用同一锁。当前是实现结构，缺少自动化运行证据；桌面 HTTP 仍是单用户默认身份，不声称已支持身份认证、线上多租户或多 Agent 配置。

实现难度：**8/10**。核心难点是让流式和非流式都遵循同一 Session 顺序，同时避免一个 Session 的锁把其他会话堵住，并处理“取消发生在拿锁前后”的竞态。实现上在每个身份 Runtime 的事件循环里维护按完整三元组索引的异步锁；排队 Run 先记录状态，获锁后再原子转成 running。取消会先查看状态，再取消对应 Future；等待锁时被取消的任务写出 `cancelled_before_start` 终态，运行后的任务仍由原执行协程完成清理。

## 后续范围

- P05-03：完善非流式任务的显式取消跟踪、工具取消传播和追加指令安全检查点，并接入批准/拒绝 UI。
- P05-04：上下文预算和压缩。
- 本项身份路由不提供认证；多用户入口需要先由入口层建立可信身份。
