# P05-06 恢复与观测

日期：2026-11-23。状态：实现完成，恢复专项及回归结果见验证部分；真实外部副作用与桌面点击验收仍需补充。

## 本项实现

- 数据库升级到 Schema v3，增加独立 `run_steps` 表。v1/v2 迁移内容保持原样；新表通过 Run 外键随会话删除，步骤按 user、agent、session、request 完整归属查询。
- 普通和流式任务均登记排队 Run；普通流式请求在返回已接受之前保存 queued 记录及原始用户需求，拿到 Session 锁后转为 running。恢复动作先等待同一 Session 锁，再原子创建子 Run。
- AgentLoop 的每次模型尝试（含有限重试）分别记录状态、错误码、已知 Usage 与耗时。工具先批量记录意图，权限及预算通过后、真正进入 handler 前再标记 running；结果先写执行日志，再写 Tool Message。
- Run 即使失败或取消，也保留此前模型步骤已知用量。成功摘要的准备阶段 Usage 在进入循环时初始化；摘要请求本身暂不作为独立模型步骤记录。供应商没有返回的失败请求用量不推测。
- 桌面历史和实时气泡可展开“执行记录与恢复”，显示任务耗时、已知 Token、模型/工具状态及错误码。尚无消息锚点的排队任务也能从持久化 Run 显示原始需求和恢复入口。

## 步骤状态与崩溃时点

| 状态/时点 | 程序知道的事实 | 重启或继续时的处理 |
|---|---|---|
| pending | 工具意图已登记，尚未进入 handler | 遗留时标为 skipped；可以由模型重新决定调用 |
| running（工具） | 即将或已经进入 handler，尚无可靠返回结果 | 遗留时标为 uncertain；不推断外部副作用没有发生 |
| completed | 工具返回的成功结果已经写入日志 | 缺 Tool Message 时复用该结果补齐，不执行 handler |
| skipped | 权限/参数/预算拒绝、重复保护拦截，或意图未启动 | 对应调用未执行 |
| uncertain | 进入 handler 后失败、取消、超时或崩溃 | 写工具要求人工核对；不能用换 call ID 的方式自动重做 |
| running（模型） | 模型尝试未留下完整完成记录 | 重启标为 failed；保留 Run 已知用量，不伪造回答 |
| 最终 Assistant 已保存、Run 尚未终结 | 有持久化的最终答案且后面没有同 Run 追加输入 | 启动识别为 completed，原因标为 recovered_saved_answer |

正常步骤耗时使用单调时钟；取消收尾或重启识别遗留步骤时只能以保存的墙钟时间估算，重启时的值可能包含停机时间。Run 耗时由开始与结束时间计算，排队等待未包含在该值中；工具步骤耗时包含确认等待与执行过程。

对于旧版本只有 Assistant 工具调用而没有执行日志的情况，无法证明 handler 没有执行，按不确定写操作处理。补齐的失败 Tool Message 明确说明结果未知，不伪造成功。修复会保留原始调用，只增加相应结果消息。

## 显式继续与重试

1. 查看当前会话的最新失败、中断或取消任务的诊断。
2. “继续未完成任务”保留已有历史和结果，让模型处理剩余工作；“重试失败部分”允许重新决策及刷新只读结果，不重新执行已完成写操作。
3. 如果有结果不确定的写操作，只提供继续路径，并要求用户先核对外部结果、明确确认。确认表示用户愿意基于当前记录继续，不会解除不确定写操作的重复保护。
4. 恢复使用当前配置快照，创建新的 request_id，并将原 request_id 保存为 parent_request_id。原 Run 保留原终态，metadata 中记下 recovered_by。
5. 来源占用、子 Run 与恢复 User 消息锚点在同一 SQLite 事务中写入，避免双击产生两个成功恢复。只接受当前 Session 最新 Run；有更新任务时须先处理最新记录。
6. 新 Run 继承恢复祖先的已完成写操作保护；所有普通新任务也会保护本会话尚未解决的不确定写指纹。已知未执行的调用可以重新决策，只读工具仍受每 Run 重复上限约束。

这不是从任意 Python 指令位置恢复，也不自动回滚外部操作。当前保护以工具名和规范 JSON 参数的指纹识别操作；不同参数表达可能对应相同业务副作用，仍需要工具自身的幂等键、结果核对或业务侧事务。未知写操作的保护不会仅凭一次“继续”确认解除；当前没有独立的外部结果人工裁决接口。

## 追加指令与排队恢复

- 启动时检查持久化 queued/running Run，将遗留状态收口；不自动重新执行工具。
- 对 Run 元数据里仍标为 queued 的追加指令，按 Session 消息中的 run_instruction_id 查找：消息已经写入则识别 injected 并补序号，否则标为 rejected，避免重启后重复注入。
- 排队任务尚未写入 User Message 时，原始需求来自 queued_message；用户显式恢复后，把原需求与恢复动作一起原子写入 Session。
- 确认等待不代表 handler 已启动。ToolManager 只有在确认、权限和预算都通过后才调用执行状态持久化回调；该回调失败则不执行 handler。

## 接口与文件

- `GET /api/sessions/{session_id}/run_diagnostics?request_id={request_id}`：返回 Run 状态、父任务、已知用量、耗时、步骤和当前可用恢复动作。
- `POST /runs/recover`：接收 session_id、source_request_id、mode（continue/retry）、acknowledge_uncertain，返回新流式 request_id，继续使用 `/stream` 和 `/cancel`。
- 桌面 HTTP 仍限定 local/default；Bridge 根据可信身份创建隔离仓储。接口不是远程多用户认证机制。
- 核心代码：`yanagent/sessions/executions.py`、`yanagent/sessions/recovery.py`、`yanagent/sessions/runs.py`、`yanagent/runtime/agent_loop.py` 和 `yanagent/runtime/streaming.py`。
- 桌面展示：`RunDiagnostics.tsx`、`MessageBubble.tsx`、`ChatPage.tsx`、`chatStore.ts` 与 `types.ts`。

## 验证与剩余边界

- 新增 14 项恢复测试，使用真实 SQLite、重建仓储、Fake Provider、本机 HTTP 和实际 Session 队列。覆盖工具完成后消息未写回、进入 handler 前后崩溃、无执行日志的旧调用、写保护继承、取消、用量与错误保留、原子恢复占用、身份隔离、最终答案识别、追加指令写入间隙、日志失败不执行 handler、排队需求恢复和 HTTP/SSE 恢复。
- 增加 v2→v3 保留 Run 的迁移测试；v1 升级测试保留。长历史测试更新为检查原始记录完整保留、较早内容进入摘要，符合 P05-04 的当前行为。
- Renderer 生产构建通过；TypeScript 全量静态检查仍被基线问题阻挡：ChannelsPage.tsx 的 IconComponent size 类型与 Lucide 不兼容，以及 types.ts 已有的重复 user_seq。已用 HEAD 核对两者为本次修改前已有问题；新恢复代码没有被该检查报告类型错误。
- Python 静态编译、diff 检查通过；最终全量 **236 项离线回归通过**，其中恢复专项 14 项、v2→v3 迁移新增 1 项。运行命令与剩余边界记录在 workProcess.md。
- 没有执行真实写工具副作用、强杀真实服务或 Electron 点击确认验收。测试按数据库日志时点模拟崩溃；SQLite 日志提交与外部副作用之间无法组成跨系统原子事务。
- P05-01～P05-04 的专项待验收项目仍保留；P05-06 本项的恢复日志与入口完成，不代表 P01～P05 已全部通过产品验收。

## 参考来源

参考 CowAgentByYan `agent/protocol/agent_stream.py` 中取消/中断时补齐工具结果的流程，以及 `agent/memory/conversation_store.py` 中 unfinished_runs 与历史状态聚合。检查时 HEAD 为 1fa66340，参考仓库没有受跟踪文件改动。本项目新增独立步骤日志以区分未启动、已完成和不确定；没有直接移植参考项目全部恢复机制。

下一开发项为 P06-01：多模型与备用链；P05 尚需专项桌面和真实副作用验收。
