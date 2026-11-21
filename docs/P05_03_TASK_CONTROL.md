# P05-03 任务控制

状态：桌面流式链路已实现，行为验证待补

## 本项交付

- **协作式取消**：Runtime 取消目标 Run 的异步任务。模型流、等待工具确认和异步工具执行均接收任务取消；工具 handler 的 `CancelledError` 向 AgentLoop 和 Runtime 继续传播，由 Runtime 关闭追加入口、拒绝尚未到检查点的指令、更新 Run 终态并结束 SSE。
- **工具确认闭环**：当权限策略要求确认时，后端发出带 Run、工具调用、风险和作用域标识的 `confirmation_required` 事件。桌面弹出批准/拒绝对话框，并把一次性决定提交到原 Run；后端再次核验确认 ID，只有批准后才会进入 handler。Run 取消或事件循环关闭后，过期决定不能匹配新调用。
- **运行中追加指令**：流式任务运行期间可以发送纯文本。后端先将文本及 `queued` 状态写入 Run 元数据，再放入 RunRecord 的内存队列，并发送 `instruction_queued`。
- **安全检查点注入**：AgentLoop 在每次模型轮次前检查待处理消息；完成并保存最终 Assistant 后也检查一次，以接住完成边缘到达的新消息。只有没有悬空 ToolCall 的合法对话边界才会继续组装并校验输入。
- **持久化顺序**：安全检查点按顺序将追加 User Message 写入 Session；随后将 Run 元数据状态更新为 `injected` 并写入 Session 序号，再发出 `instruction_injected`。若 Run 在检查点前结束或取消，则将其标为 `rejected` 并发出 `instruction_rejected`。SSE 事件只在持久化动作之后通知桌面。
- 桌面显示追加中的用户消息；注入后补齐稳定消息序号并开启后续回答气泡；Run 结束前未注入的消息会显示为未接收。

## 关键边界

- 追加指令入口只接受非空纯文本，最多 200,000 字符；流式期间禁用附件提交。
- 追加消息不会中断当前模型请求或工具调用，只会在下一安全检查点进入上下文。
- 拒绝确认会生成工具失败结果供 AgentLoop 继续处理；这不代表工具已经执行。
- 取消是协作式的。异步 handler 收到取消后应尽快退出；如果 handler 屏蔽取消或其副作用已提交，Runtime 无法回滚外部操作。
- 本次交互控制接入桌面默认的流式路径。非流式桌面请求仍没有运行中取消入口，也不支持运行中追加指令。
- 多个待追加消息以单批次的顺序写入 Session；Session 与 Run 元数据的写入不是跨表原子事务。进程在两个持久化动作之间崩溃时，记录状态可能需要后续恢复逻辑处理；自动恢复属于 P05-06。
- 桌面 HTTP 仍由本地默认身份路由；本项没有新增远程身份认证。

## 涉及的代码

- `yanagent/runtime/streaming.py`：确认 Future 与 Run 绑定、追加队列、检查点注入、终态拒绝和取消收尾。
- `yanagent/runtime/agent_loop.py`：模型轮次边界和最终 Assistant 持久化后的追加指令检查点；将确认处理器传递给工具执行。
- `yanagent/tools/manager.py`：等待批准、拒绝时阻止 handler，并在确认等待或工具执行时传播取消。
- `yanagent/sessions/runs.py`：将排队、注入/拒绝状态与 Session 序号保存到 Run 元数据。
- `yanagent/runtime/bridge.py`、`app.py`：提供身份作用域内的确认回传、追加消息和既有取消入口。
- `desktop/src/renderer/src/api/client.ts`、`types.ts`、`store/chatStore.ts`、`components/ChatInput.tsx`、`i18n.ts`：确认交互、流式追加文本及消息状态反馈。

## 验证情况

- `python -X utf8 -m compileall -q app.py yanagent` 通过。
- `git diff --check` 通过；Git 给出工作区换行符 LF/CRLF 提示，不是空白错误。
- 未新增或运行自动化测试；未启动桌面、HTTP/SSE 实测或执行真实工具确认，因此批准、拒绝、取消竞争和持久化排序仍需行为测试确认。

## 岗位要求关联

对应 `docs/TARGET_ROLES.md` 的“工具调用与执行管控”“路由、任务调度与多入口”和“可用性、稳定性与可观测性”。实现证据是 Run 作用域校验、权限确认一次性回传、工具取消传播、检查点消息注入和状态事件。当前只有代码与静态编译证据，不声称外部副作用可回滚、非流式任务可取消或已通过竞态测试。

实现难度：**8/10**。最难的是让 Run 元数据、Session 消息序号、线程安全的 SSE 队列和桌面乐观消息保持同一追加指令的顺序。实现采用“先记录排队、后在检查点批量落 Session、再更新 Run 状态、最后发 SSE”的顺序；桌面另用 `instruction_id` 关联请求响应与可能先到达的 SSE 事件，避免网络时序导致消息失联。确认则用 Run ID 与一次性确认 ID 绑定等待 Future，取消时由工具执行栈传播 `CancelledError` 并清理未注入任务。

## 后续事项

- 为批准/拒绝、等待确认时取消、工具执行中取消、最终回答边缘追加和 Run 结束拒绝补行为测试并运行。
- 如开放非流式桌面交互，增加请求开始前可用的 Run ID 与对应的用户取消流程。
- P05-04 已实现上下文 Token 预算、裁剪和压缩；下一项 P05-05：故障处理。
