# P02-05 隔离、并发写入与 Run 恢复

状态：已完成  
完成日期：2026-10-22  
后续状态：P03-01～P03-03 已完成；下一项为 P03-04 权限基础

## 1. 本阶段解决的问题

P02-05 为 P02 的 Session 持久化阶段收尾，解决三个问题：

1. Session、Message 和 Run 的查询与更新必须同时匹配 `user_id + agent_id + session_id`，不能只凭一个可猜测的 `session_id` 访问数据。
2. 多个线程或仓储实例并发向同一 Session 写消息时，序号不能重复，消息计数不能丢失。
3. 进程退出时来不及完成的 `queued/running` Run，下一次启动不能继续伪装成正在执行，必须转为可解释的 `interrupted`。

## 2. 完整归属边界

`SessionStore` 和 `RunStore` 都在构造时绑定可信的 `user_id` 与 `agent_id`，每次操作只接收 `session_id`，调用方不能在单次查询中覆盖可信作用域。

```text
可信服务作用域：user_id=local, agent_id=default
                         + 请求中的 session_id
                         + Run 操作中的 request_id
                                      ↓
                 只有完整匹配的 Session / Message / Run 可见
```

- Session 与 Message 的所有读取、修改和删除继续使用三元归属。
- Run 创建时在同一事务内验证目标 Session 的三元归属。
- Run 读取与终态更新同时匹配 `request_id + user_id + agent_id + session_id`。
- 桌面 HTTP 当前只接受 `default` Agent；即使直接绕过界面请求另一个用户的 `session_id`，历史接口也只返回 `session_not_found`，不会回显隐藏内容。

当前产品仍是本机单用户模式，`local/default` 是后端可信固定身份，不等于已经完成远程登录、租户认证或角色授权；这些属于 P11 的 Web 与认证范围。

## 3. 并发写入如何保持顺序

消息追加使用 SQLite `BEGIN IMMEDIATE`。读取当前最大序号、插入整批消息、更新 `message_count` 在一个事务中完成：

```text
写入 A ─┐
        ├─ 等待 SQLite 写事务 ─ 读取最新 sequence ─ 分配新序号 ─ 提交
写入 B ─┘
```

测试使用两个独立 `SessionStore` 并发写入 20 条消息，最终验证：

- 每次返回的序号排序后严格等于 `0..19`；
- 数据库历史序号严格等于 `0..19`；
- 20 条正文均存在，没有覆盖或丢失；
- `message_count` 等于 20。

这证明的是数据库写事务正确，不代表同一 Session 的两个模型请求已经排队。请求 A、B 仍可能在相近时间读取不同的历史快照；P05-02 才实现同 Session 默认串行、不同 Session 并行的 Bridge 调度。

## 4. Run 生命周期

新增 `RunStore`，把普通响应和 SSE 流式响应接到已有 `runs` 表：

```text
用户消息落库
    ↓
创建 running Run
    ├─ 模型与 Assistant 保存成功 → completed + finish_reason + usage
    ├─ AgentError              → failed + error_code
    ├─ 显式停止/任务取消       → cancelled
    └─ 进程在终态前退出        → 下次启动改为 interrupted
```

终态更新带活动状态条件，只允许 `queued/running` 转换一次。重复结束、错误 Session 或错误用户/Agent 作用域均不会改写已完成记录。Run 元数据只保存 Provider 和模型标识，不保存 API Key、消息正文或原始异常。

## 5. 启动恢复

`YanAgentHTTPServer` 在绑定并开始处理请求前调用 `recover_unfinished_on_startup()`。当前可信作用域中遗留的 `queued/running` 会原子更新为：

```text
status        = interrupted
finish_reason = process_restarted
error_code    = run_interrupted
finished_at   = 当前毫秒时间
```

已是 `completed/failed/cancelled/interrupted` 的记录不变，其他用户或 Agent 的活动 Run 也不会被当前作用域误改。恢复操作可重复执行，第二次没有新遗留记录时返回 0。

## 6. 验证证据

- `tests/test_run_store.py`：创建与单次终态、跨用户/Agent/Session 隔离、失败终态、作用域恢复和 Server 启动恢复。
- `tests/test_session_store.py`：两个仓储并发追加 20 条消息，验证连续唯一序号和计数。
- `tests/test_desktop_sessions.py`：绕过 UI 直接请求另一个用户的 Session，得到 404 且响应不含隐藏正文。
- `tests/test_chat_history.py`：普通与 SSE 成功请求均保存真实 `completed` Run。
- `tests/test_chat_integration.py`：显式取消 SSE 后保存 `cancelled` Run。
- 全量 137 项自动化测试通过；Python `compileall` 和 `git diff --check` 通过。

## 7. 已知边界

- 没有实现同 Session 请求队列、追加指令、跨 Session 调度、公平性和背压；这些属于 P05。
- 没有实现远程用户登录、Token、RBAC 或多租户管理；当前只使用后端固定的 `local/default` 作用域。
- 启动恢复记录“上次任务被进程中断”，不会自动续跑模型请求，也不会尝试重放可能产生副作用的任务。
- 用户消息先于 Run 创建落库；若进程恰好在两步之间崩溃，可能留下没有 Run 的 User Message。后续 Bridge/恢复设计应以幂等性和人工可见性处理，不能盲目自动重试。
- SQLite 的事务测试验证正确性，不代表已完成生产压测或得出吞吐量结论。
