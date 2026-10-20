# 需求文档在 docs/DEVELOPMENT_REQUIREMENTS.md

# 并且开发的时候会遵守AGENTS.md 里边的约定
# YanAgent 开发记录

后续每次完成一个需求，都在本文件末尾追加记录。历史记录按时间顺序保留。

## 2026-10-20：建立需求开发记录约定

### 需求

每次处理 YanAgent 的需求后，将实际完成的工作记录到 `workProcess.md`。

### 完成内容

- 初始化本开发记录文件，明确后续采用追加记录的方式。
- 新增项目级 `AGENTS.md`，将开发记录要求写入项目约定，供后续开发时遵守。
- 约定记录包含日期、需求、完成内容、涉及文件、验证结果及未完成事项。

### 涉及文件

- `AGENTS.md`
- `workProcess.md`

### 验证结果

- 已确认原 `workProcess.md` 为空，本次初始化没有覆盖已有内容。
- 本次仅新增开发约定和记录文档，无运行逻辑变更。

## 2026-10-20：制定开发需求与实施计划

### 需求

以用户提供的 CowAgentByYan 核心功能整理为最终目标，制定 YanAgent 后续开发依据，让阶段顺序、具体任务和验收流程清晰可查。

### 完成内容

- 读取用户提供的目标文本，核对 YanAgent 现有骨架、客户端调用方式和参考仓库 Git 基线。
- 新增 `docs/DEVELOPMENT_REQUIREMENTS.md`，定义 P01～P12 的依赖、子任务、验收标准和当前进度。
- 详细拆分第一个大阶段“单模型聊天链路”，明确下一项为 P01-01“完善统一消息数据结构”。
- 纳入核心运行时、Skills、MCP、记忆知识库、Multi-Agent、Web、多渠道、定时与桌面交付，明确最终使用功能对照清单验收。
- 统一 README、路线摘要和项目约定的文档入口，后续按同一份需求推进。

### 涉及文件

- `docs/DEVELOPMENT_REQUIREMENTS.md`
- `docs/IMPLEMENTATION_ROADMAP.md`
- `README.md`
- `AGENTS.md`
- `workProcess.md`

### 验证结果

- 已核对阶段依赖、任务编号、功能覆盖和本地文档链接；所有业务阶段保持“未开始”。
- 本次只修改文档，无运行逻辑变更，无需运行业务测试。

### 后续事项

- 按 P01-01 开始实现数据契约，当前尚未开展业务代码开发。

## 2026-10-20：追加目标岗位参考与开发成果记录规则

### 需求

保存用户提供的小米、字节用户增长、抖音 Agent 研发、腾讯 Agent 研发和微信小程序 Agent 青云课题要求。技术实现继续参考 CowAgentByYan，后续开发与岗位要求重合时详细记录。

### 完成内容

- 新增 `docs/TARGET_ROLES.md`，归档五组岗位原文并建立稳定的岗位和条款编号。
- 将现有 P01～P12 任务映射到协议、上下文、工具、执行循环、MCP、Skills、记忆、Multi-Agent、质量和成本等岗位关注点。
- 明确 daemon/云端、Sandbox、MCP Server、Hook、Verification Loop、Planning、Reflection、质量场景及 Text-to-Skill 等能力差距，保持原有复现范围与顺序。
- 补充后续记录模板：对应条款、重合范围、具体实现、设计取舍、验证证据、实际难点、指标、面试事实和剩余差距。
- 更新 `AGENTS.md` 的长期约定与文档导航，需求文档升为 v1.1。

### 涉及文件

- `docs/TARGET_ROLES.md`
- `docs/DEVELOPMENT_REQUIREMENTS.md`
- `docs/IMPLEMENTATION_ROADMAP.md`
- `README.md`
- `AGENTS.md`
- `workProcess.md`

### 验证结果

- 核对五组岗位归档、任务关联和能力边界；业务阶段仍为未开始，下一项仍为 P01-01。
- 本次只更新参考文档与开发约定，无运行逻辑变更，不运行业务测试。

### 岗位要求关联与实践证据

- 对应条款：XM-要求6、DYG-要求4、DYQ-要求4中的方案记录与结构化表达部分。
- 实际完成：建立岗位条款与开发任务的追溯关系，以及后续技术证据记录模板。
- 实践边界：本次仅形成文档和规范，尚不构成 Agent 编排、MCP、Multi-Agent、企业落地或性能优化的实现证据。

### 后续事项

- 按 P01-01 开发数据契约，并记录其与统一协议相关岗位要求的实际重合范围。

## 2026-10-20：P01-01 统一数据契约

### 需求

开始 P01，完成 P01-01：统一消息、工具请求、工具结果、模型响应、任务输入及任务结果；支持 Assistant 工具调用、身份字段、JSON 保存/还原和必要校验，并用四条工具对话消息验收。

### 完成内容

- 完善六种标准库数据类：`Message`、`ToolCall`、`ToolResult`、`ModelReply`、`RunRequest`、`RunResult`，为字段和接口补充中文说明，保持原有最小构造方式兼容。
- `Message` 增加 `tool_calls` 和 `is_error`；`ModelReply.to_message()` 保留 Assistant 发起的调用；`ToolResult.to_message()` 保留结果引用与错误标记。
- 请求和结果统一提供 `user_id / agent_id / session_id / request_id`：用户归属、执行 Agent、持续会话、单次 Run 分开表示；请求 ID 默认待 Bridge 分配。
- 增加 `JsonContract` 的 `to_dict / from_dict / to_json / from_json` 和 `ContractValidationError`；构造、还原、保存时校验；未知字段、缺失字段、非法嵌套参数等不会被静默忽略。
- 校验标准 JSON 类型、有限数字、字符串键和循环引用；拒绝重复 JSON 键，避免信息隐式丢失。序列化结果和反序列化输入做独立拷贝，减少消息内容互相污染。
- 用量支持未知值，与零明确区分；用量和轮数拒绝负数及布尔值；Run 结果区分完成、失败、取消和中断终态。
- 新增 `validate_conversation()` 检查跨消息工具配对：孤立/重复结果、遗漏结果、重复调用 ID 和结果未齐即插入普通消息会报错；允许同组结果乱序返回；运行中可显式允许尾部未完成调用。
- 新增离线四消息示例及实现说明，更新 P01 阶段和 P01-01 子任务进度。P01 仍为进行中。

### 参考实现与设计取舍

- 阅读 CowAgentByYan 的 `agent/protocol/message_utils.py`：`_repair_tool_use_adjacency()` 和 `drop_orphaned_tool_results_openai()` 处理调用/结果不完整的历史；本任务吸收完整配对约束，采用显式验证，不在数据层补造结果或删除消息。
- 阅读 `agent/protocol/agent_stream.py` 的流式取消和用量读取片段：取消可能产生部分输出，且供应商用量并不总在同一位置返回。因此保留空内容、未知用量和中断终态的表达能力，具体策略留给运行时。
- 延续骨架的标准库 dataclass，当前不引入外部验证库；在共同转换入口中验证，避免各 Provider 和存储层各写一套字段规则。
- 内部工具参数保持 JSON 对象，当前使用独立 tool 角色；供应商 JSON 字符串参数、Claude tool_use/tool_result 等差异由后续适配器转换。
- 单条消息字段校验与整段历史配对校验分开：数据库可以独立读取 Tool 消息，完整上下文在交给模型前再检查整体一致性。

### 涉及文件

- `yanagent/contracts.py`
- `tests/test_contracts.py`
- `examples/__init__.py`
- `examples/contracts_demo.py`
- `docs/P01_01_CONTRACTS.md`
- `docs/DEVELOPMENT_REQUIREMENTS.md`
- `docs/IMPLEMENTATION_ROADMAP.md`
- `docs/TARGET_ROLES.md`
- `README.md`
- `workProcess.md`

### 验证结果

- `.\.venv\Scripts\python.exe -m unittest discover -s tests -v`：23 项通过，包括 20 项新增契约测试和 3 项原有骨架测试。
- `ContractRoundTripTests.test_four_messages_keep_tool_request_and_result`：四消息 JSON 往返相等，工具参数及调用 ID 关联保持一致。
- `ConversationValidationTests`：多轮调用、同组结果乱序、孤立/重复/缺失结果和显式未完成尾部规则通过验证。
- `ContractValidationTests`：角色与字段限制、非法身份、用量/轮数、非 JSON 数据、重复键、后续修改对象的再校验、错误信息不回显正文均通过验证。
- `.\.venv\Scripts\python.exe -X utf8 -W error -m examples.contracts_demo`：离线示例成功，输出中文及完整四消息，明确未调用模型、未执行工具。
- `.\.venv\Scripts\python.exe -W error -m compileall -q -f app.py yanagent tests examples`：通过语法检查，警告按错误处理。
- 本次没有修改前端或请求真实模型，不将上述离线测试记为桌面或 API 联调通过。

### 实际问题与处理

- 可变字典即使在构造时合法，后续也可能加入不可序列化值：保存前再次验证，并测试嵌套字段修改后的失败行为。
- Python 的 bool 属于 int 子类：用量和轮数通过精确类型判断避免将 True 当作 1。
- 示例初次运行发现 Windows 路径的 Docstring 触发转义警告，已改为原始字符串；本机默认输出编码造成中文显示错误，示例命令使用 `-X utf8` 后输出正确，未修改系统级编码。

### 岗位要求关联与实践证据

- 对应条款：XM-职责1 的任务接入、上下文和回写基础；DYQ-职责3 的工具协议规范；TX-职责1 的工具调用与执行引擎接口基础。
- 重合范围：实现了后续链路共享的数据表达、工具请求/结果关联及输入边界；尚未实现实际任务调度、工具执行或完整 Agent 架构。
- 具体实现：`Message.tool_calls / tool_call_id / is_error`；`RunRequest / RunResult` 身份；`JsonContract` 的统一转换；`validate_conversation()` 的待完成调用集合和唯一 ID 检查。
- 设计原因：工具调用结果必须能反向关联模型发起的请求，才能恢复可供模型继续使用的上下文；统一格式可把供应商差异留在 Provider，而不是传播到每个模块。
- 验证证据：`tests/test_contracts.py` 的四消息往返、角色限制、嵌套校验和跨消息配对测试；`examples/contracts_demo.py` 的可复现离线输出。
- 难点与取舍：单条 Tool 允许独立存在、完整对话再检查顺序；等待工具结果的运行中尾部与完整历史使用不同验证选项；未知用量不伪装成零；保留 dataclass 的可变性并在保存边界重新检查。
- 指标与结论：23 项测试通过是当前正确性证据；未进行性能、Token 成本、真实模型或用户规模测量，不声称优化收益。
- 面试可讲事实：为自研 Agent Runtime 实现供应商无关的消息与工具数据契约，通过序列化和完整工具调用配对校验保证数据可还原，建立了离线行为测试与演示。
- 剩余差距：字段归属不等于身份认证；结构校验不等于工具 Schema 校验；本任务没有实现 MCP 协议、数据库隔离、Planning 或真实模型调用。

### 后续事项

- P01-01 已完成；下一项为 P01-02 配置与统一错误。
- 后续 Provider/Session/Loop 接入时使用这些契约，按需要补充多模态、流式事件与迁移策略。
