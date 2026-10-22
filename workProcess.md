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

## 2026-10-21：P01-02 配置与统一错误

### 需求

按开发计划继续 P01-02，完成模型配置读取和保存、环境变量优先覆盖、字段校验、密钥脱敏，以及配置、认证、限流、超时、服务端错误的统一表达。遵循本次读取到的最新 AGENTS.md：新增每个类和函数均写中文说明；保留用户对约定文件的未提交修改。

### 完成内容

- 新增不可变 `AppConfig`，承载 `model_provider / api_base / model / api_key / request_timeout`，保留骨架的 `host / port / permission_mode` 字段；统一校验类型、枚举、数值范围及文本。配置允许初始未填写，通过 `require_model_ready()` 在未来调用模型前检查完整性。
- 新增 `ConfigStore`，默认只使用 YanAgent 根目录的 `config.json`，支持显式路径和 `YAN_CONFIG_PATH`；文件不存在时返回默认值，坏 JSON、重复键、未知字段明确失败，兼容 UTF-8 BOM。
- 以“默认值 → 文件 → 非空 YAN_* 环境变量”合并配置；环境中的空串占位保留文件值，非法非空覆盖报错。创建实例时捕获环境，每次读取重新加载文件。
- 保存采用局部更新并基于文件层合并，不将环境密钥或环境模型自动写回文件。省略密钥保留、非空替换、空串清除；拒绝把脱敏星号回写成真实密钥。
- 保存前完成校验和序列化，使用同目录临时文件、flush/fsync、os.replace；失败不回退到截断原文件。用故障注入验证落盘与替换失败时原文件保持完整。
- `AppConfig.to_dict()` 完全隐藏非空密钥，对象 repr 不含密钥；统一错误使用固定原因和已知字段，不回显原始值、路径、底层异常正文或供应商响应。
- 新增统一错误层和 `map_http_error()`，区分配置、认证、权限、模型/路径不存在、请求参数、限流、超时、连接和服务端错误。错误码、说明、重试提示和上游状态均可序列化；没有自动重试。
- 新增 26 项离线测试、配置演示、详细验收文档；更新无凭据模板、临时文件忽略规则及阶段状态。P01 仍为进行中，下一项 P01-03。

### 参考实现与设计取舍

- 开发前检查 CowAgentByYan 工作区，对应本次读取的源码没有已跟踪改动；存在用户的未跟踪文档和桌面脚本，均未修改。
- 参考 `config.py` 的环境覆盖、空串占位和敏感字段处理：采用相同的“非空环境优先”规则，但本项目仅接受专属变量、显式解析数字，非法值报错；不输出短密钥或密钥首尾片段。
- 参考 `channel/web/api/config.py` 的“全部校验后应用”和按文件层局部更新：文件配置与生效配置分离，避免环境值污染持久配置；桌面 API 适配继续留在 P01-04。
- 参考 `common/atomic_write.py` 及 `tests/test_root_config_atomic_write.py` 的临时文件替换机制：本次采取替换失败即失败，不提供原地写回退，以保持原文件不被截断的承诺。
- 参考 `models/openai/openai_compat.py` 的 HTTP 状态分类：内部错误不继承某个 SDK，也不保存上游原始 message/body；实际传输异常捕获在 P01-03 完成。
- 仍使用标准库，不为单模型配置引入额外依赖。`permission_mode` 只存储枚举，不提前宣称已实现工具权限；完整运行时和目录隔离继续按原阶段推进。

### 涉及文件

- `yanagent/config/__init__.py`、`yanagent/config/settings.py`
- `yanagent/errors.py`
- `tests/test_config.py`、`tests/test_errors.py`
- `examples/config_demo.py`
- `config.example.json`、`.gitignore`
- `docs/P01_02_CONFIG_ERRORS.md`
- `docs/DEVELOPMENT_REQUIREMENTS.md`、`docs/IMPLEMENTATION_ROADMAP.md`、`docs/TARGET_ROLES.md`
- `README.md`、`workProcess.md`

### 验证结果

- `.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -v`：49 项测试通过，含本次配置测试 22 项、错误测试 4 项及原有 23 项。
- `.\.venv\Scripts\python.exe -X utf8 -W error -m examples.config_demo`：通过；展示环境覆盖、密钥脱敏、局部保存未写回环境密钥、非法超时不覆盖旧值和模拟 HTTP 429 分类。
- `.\.venv\Scripts\python.exe -X utf8 -W error -m compileall -q -f app.py yanagent tests examples`：通过，警告按错误处理。
- `test_failed_fsync_or_replace_preserves_old_file_and_cleans_temp`：分别模拟刷盘和替换失败，原文件字节不变，临时文件清理，公开异常栈不回显模拟底层敏感信息。
- `test_patch_preserves_key_and_never_persists_environment`：读取使用环境值；保存其他设置后重新读取文件，仍保留文件中的密钥和模型。
- `test_masked_display_cannot_overwrite_secret`、`test_secret_redaction_in_display_and_logs`：展示脱敏、日志输出与脱敏占位符回写保护均通过。
- 以上均为离线行为验证，模拟密钥无效；没有真实模型请求、桌面页面联调或 HTTP 接口接入，本次未改前端。
- 对本次新增 Python 文件进行 AST 检查：所有类和函数均有中文 Docstring；本次修改的已跟踪文件通过 `git diff --check`。开发期间发现 `contracts.py` 出现用户补充的身份字段注释，已保留，未纳入本次实现。

### 实际问题与处理

- 首轮测试在当前 Windows 沙箱分配的系统临时目录中遇到 WinError 5，影响临时文件访问及清理。停止该轮测试后，用项目内独立临时目录验证可正常读写，随后测试和演示统一使用此位置并正常清理；未改变系统权限，首轮失败不计为通过。
- `UnicodeDecodeError` 属于 `ValueError` 子类，若通用捕获写在前面会误报读取失败。在自查时调整异常分支顺序，加入非法 UTF-8 测试，确保返回配置格式错误。
- 环境覆盖后的对象不能直接当作文件配置回写：通过文件层局部更新和返回独立生效快照解决，并验证同时存在不同文件/环境密钥的场景。
- 保存展示字典会把星号误当作凭据：密钥全星号校验阻止这一操作，文档要求只提交变更字段。

### 岗位要求关联与实践证据

- 开发任务：P01-02 配置与统一错误。
- 对应条款：XM-职责6 的稳定性与安全基础、XM-职责7 的稳定性与可维护性；DYQ-职责3 的可复用框架工程化；TX-要求1 的 Python 基础与代码质量。现有岗位映射中的模型接入条款，本次只覆盖其配置和错误边界，不覆盖 Prompt 优化、模型原理或真实调用。
- 重合范围：统一配置入口、错误协议、凭据显示边界和失败保护，可供后续 Provider/Runtime 复用。没有企业内部系统接入、团队协作部署或生产合规验收。
- 具体实现：`AppConfig` 的不可变快照和就绪检查；`ConfigStore._read_file/_effective/save/_write_atomic` 分离读、覆盖、保存；`AgentError.to_dict` 与状态分类提供稳定程序接口。
- 设计原因：区分持久值和临时环境值使配置行为可解释；整体校验与原子替换减少失败后配置被破坏的风险；明确错误类型让调用方无需解析自然语言异常来决定反馈方式。
- 验证证据：26 项新增测试和离线演示可复现覆盖优先级、密钥不落盘、坏输入拒绝及失败保留旧文件；共 49 项回归测试通过。
- 难点与取舍：空环境变量不等于主动删除；脱敏展示不可直接回写；配置未填写与远端认证失败分开；错误只给重试提示，是否重试仍需运行时结合副作用决定。为保持原文件完整，替换失败时宁可返回错误。
- 指标与结论：测试证明当前代码在这些本地受控场景下的行为，没有测量可用率、Token 成本、性能提升或真实用户规模，不填写优化百分比。
- 面试可讲事实：为 Agent Runtime 实现可校验的配置管理和统一错误接口，将文件配置与环境覆盖分离，使用原子替换和故障注入测试验证保存失败时保留旧配置，并实现密钥脱敏和回写保护。
- 后续差距：未连接模型 API、未实现请求超时执行和退避重试、未接桌面设置、未提供加密存储/跨进程写锁/完整可观测性；这些基础工作不能写成已完成生产级 Agent 平台。

### 后续事项

- 下一项 P01-03：实现 OpenAI-compatible 非流式 Provider、消息及响应适配和 Fake Provider，将本次配置与错误接入实际调用边界。
- P01-04 接通桌面配置查询/保存与普通聊天；P01-05 再实现流式事件和取消，当前不自动推进。
- 数据目录、并发配置更新、凭据持久化增强和运行时策略按后续相应阶段处理；当前可保存明文密钥，脱敏不等于加密或权限隔离。

## 2026-10-21：P01-03 非流式 Provider 与 Fake Provider

### 需求

根据最新 AGENTS.md 继续 P01-03：实现 OpenAI-compatible 非流式调用，统一消息转换、工具调用解析、结束原因和用量；提供可预设响应序列的 Fake Provider。所有新增/修改的类和函数写中文说明，并在本记录中详细说明开发难点、十分制评分和实现方式。

### 完成内容

- 完善 `ModelProvider` 协议说明，新增 `NonStreamingProvider`，本阶段真实/Fake 实现的流式入口均明确报未实现，不以完整回答伪装流式。
- 实现 `OpenAICompatibleProvider.complete()`，使用 P01-02 配置快照和就绪检查，向 `{api_base}/chat/completions` 发送一次非流式请求，传入认证头及请求超时；不管理会话、不执行工具、不自动重试。
- `prepare_request()` 校验完整对话及工具配对，保留角色/调用 ID，工具参数对象编码成 JSON 字符串，不发送内部 metadata；失败 ToolResult 通过正文包装保留错误语义。供应商无关的工具描述转换为 function Schema。
- `parse_reply()` 将单候选响应还原成 `ModelReply`；严格解析多个 Tool Call，拒绝缺失/重复 ID、损坏 JSON、重复键、非对象参数、错误包络及不支持的旧式调用；不自动生成 ID 或把坏参数补成空对象。
- 结束原因保留原值，空文本但有工具请求视为有效；新增响应格式错误、空响应、明确拒绝三类统一错误。Usage 仅映射明确报告的 input/output/total，未知值不变成零，不伪造总数。
- 新增可注入 `JsonTransport` 及标准库 `UrllibJsonTransport`：后台线程执行阻塞网络操作、等待截止时间、socket 超时、默认 8 MiB 响应限制、禁止自动重定向、关闭响应、HTTP/连接/超时安全错误映射。
- 新增 `FakeProvider`、调用记录及耗尽错误，按预设依序返回结果或抛出统一异常；每轮记录独立输入快照；非法输入不消费预设，耗尽后不重复最后响应。
- 新增默认离线演示及显式 `--live` 入口。离线示例手工填入固定工具结果，不执行工具；真实模式只在用户显式选择时读取配置发出请求，本次未运行。
- 新增 26 项测试，其中 4 项通过回环随机端口执行真实 HTTP；同步更新需求、路线、README、岗位状态和详细验收指南。P01 仍进行中，下一项为 P01-04。

### 参考实现与设计取舍

- 开发前读取最新 AGENTS.md、P01-03 需求、岗位映射和现有契约/配置/错误；YanAgent 当时工作区干净。CowAgentByYan 存在原有未跟踪文档和桌面脚本，与本次参考源码无关，未作修改。
- 参考 CowAgentByYan `models/openai_compatible_bot.py` 的 `_handle_sync_response()`、`_convert_tools_to_openai_format()`、`_convert_messages_to_openai_format()`：吸收供应商格式适配边界，YanAgent 使用 P01-01 内部契约，不在 Runtime 传播厂商 JSON 结构。
- 参考 `models/openai/openai_http_client.py` 的 `_build_headers()`、`_request()`、`_parse_response()`：沿用 Base 拼路径、认证头、超时及 HTTP 分类思路；本次不引入 requests/模型 SDK，不搬入流式、Responses API 或多厂商特性。
- 与参考实现的区别：YanAgent 用统一异常代替返回原始错误正文；请求前拒绝不完整工具历史；响应参数严格解析；不将缺失 Token 用量默认为零；禁止自动重定向，不把凭据带到后续地址。
- 标准库 HTTP + 线程使本阶段无需新增依赖并可复用异步接口，但保留“取消等待不等于强制中断线程”的限制。传输是可替换接口，P01-05 可在此边界完善可取消的流式 I/O，不提前宣称取消闭环完成。

### 涉及文件

- `yanagent/models/provider.py`、`yanagent/models/__init__.py`
- `yanagent/models/openai_compatible.py`、`yanagent/models/transport.py`、`yanagent/models/fake.py`
- `yanagent/errors.py`
- `tests/test_provider.py`、`tests/test_provider_http.py`
- `examples/provider_demo.py`
- `docs/P01_03_PROVIDER.md`
- `docs/DEVELOPMENT_REQUIREMENTS.md`、`docs/IMPLEMENTATION_ROADMAP.md`、`docs/TARGET_ROLES.md`
- `README.md`、`workProcess.md`

### 验证结果

- `.\.venv\Scripts\python.exe -X utf8 -W error -m unittest discover -s tests -v`：75 项测试通过；新增 26 项，原有 49 项通过；没有将未实现业务的骨架测试算为真实模型或 AgentLoop 完成。
- `.\.venv\Scripts\python.exe -X utf8 -W error -m examples.provider_demo`：通过，两轮预设、工具引用和第二轮输入角色顺序正确，明确标注工具结果与 Usage 是固定模拟值。
- `.\.venv\Scripts\python.exe -X utf8 -W error -m compileall -q -f app.py yanagent tests examples`：通过。
- `CodecTests`：消息及失败工具结果转换、Schema 隔离、坏上下文、文本/多工具响应、结束原因、未知/零用量、坏参数/重复 ID、空响应/拒绝和错误包络均通过。
- `ProviderAsyncTests`：配置检查先于网络；真实适配器传入 URL/认证/超时/Schema；Fake 顺序、快照、耗尽、非法输入不消费；阻塞操作在线程中执行；等待超时与取消不自动重试，流式入口明确拒绝。
- `TransportTests`：状态精确分类、HTTPError 关闭、错误栈不含原始敏感片段、DNS/超时分类、受限读取及坏 JSON/编码拒绝。
- `LocalHttpTests`：4 项真实本地 HTTP 测试通过，验证 UTF-8 POST、认证头、文本和工具响应、401/429 无重试、307 不跟随；服务器只监听 127.0.0.1 随机端口，使用虚构密钥，正常关闭。
- 未请求真实外部供应商，未读取或使用用户真实密钥，未运行 `--live`，未改前端或接通 `/message`；本地 HTTP 验证不能替代真实模型联调。

### 难点、评分与实现方式

整体开发难度：**6/10**，属于中等工程难度。分项评分描述各问题自身复杂度，不是累加分数。

| 难点 | 评分 | 容易出现的问题 | 实现方式与证据 |
|---|---|---|---|
| 内部消息与模型协议转换 | 6/10 | 丢失调用 ID、将工具参数对象直接发给接口、遗漏失败语义 | 请求前做完整配对验证；参数编码为字符串，响应反向还原对象；失败工具正文包装；四消息和真实 HTTP 工具响应测试验证 |
| 响应不完整或字段缺失 | 6/10 | 把坏工具 JSON 修成空参数继续执行，把工具型回复误判为空，把未知 Token 当成零 | 严格 JSON 与契约校验；允许无文本的有效工具请求；空、拒绝、格式错误分开；仅映射明确报告的 Usage，保留 finish_reason |
| 异步与资源生命周期 | 7/10 | async 函数内部直接阻塞网络；取消等待后误认为 socket 已停止；超时后盲目重试 | 通过 to_thread 隔离阻塞 I/O，wait_for 限制等待，socket 也设超时，所有响应关闭且不自动重试；测试确认执行线程和异常路径，文档明确后台线程的剩余限制 |
| 可复现的 Fake 模型 | 5/10 | 原消息或预设被修改后污染之前记录；预设耗尽却重复响应掩盖多调用 | 队列每轮消费、响应/输入深拷贝、记录返回副本、耗尽专用错误；用两轮工具历史及变更外部对象测试验证 |
| 统一错误与信息边界 | 5/10 | 原始 HTTP 异常带出 URL/正文/凭据；重定向将认证转发 | 只按 HTTP 状态分类，固定安全文案，不保留错误体，抑制底层异常链打印，禁止自动重定向；真实 307 和错误栈测试验证 |

这里已完成的是非流式适配基础，不包含真正的工具执行、流式拼装、多会话并发或完整停止生成，因此不按完整 Agent Runtime 的难度评分。

### 实际问题与处理

- 本机 Windows 沙箱内创建默认 asyncio 事件循环出现阻塞，终止探测后在经工具审批的普通执行环境中验证 `ProactorEventLoop` 正常，再运行异步测试与本地回环联调；没有修改系统设置或为测试替换产品事件循环策略。
- P01-01 允许合法空 `ModelReply`，但真实模型无文本无工具的响应应可识别：把检测放在真实响应解析边界，Fake 仍可主动预设空结果供后续上层策略验证，避免混淆数据表达能力与调用成功条件。
- 兼容 API 没有统一的 Tool 消息 `is_error` 字段，不能直接把内部字段全量转发：只发送标准字段，错误结果用 JSON 正文表达，并测试原始内部消息不被修改。
- 标准库阻塞 HTTP 无法随异步取消立即强杀线程，这一限制未被隐藏为“取消已实现”；文档指出 DNS/慢速回包及事件循环退出时可能等待线程回收，P01-05 需要继续处理。

### 岗位要求关联与实践证据

- 开发任务：P01-03 非流式 Provider 与 Fake Provider。
- 对应条款：XM-职责1 的模型接入链路基础、XM-职责7 的稳定性与可维护性；DYQ-职责2 的上下文及多工具调用编排基础、DYQ-职责3 的通用协议和调试能力；TX-要求1 的 Python 工程质量、TX-职责1 的工具调用接口基础。模型/Prompt 映射条目中，本次只覆盖模型适配和错误处理，不宣称完成 Prompt 优化或模型原理研究。
- 重合范围：后续 Agent 可复用统一输入/输出及错误接口，Fake 可以稳定复现多轮调用与失败；尚未实现工具实际执行、任务规划、质量工作流或生产部署。
- 具体实现：`OpenAICompatibleProvider` 将配置和协议转换连接到传输；`prepare_request/parse_reply` 作为边界；`JsonTransport` 允许替换网络实现；`FakeProvider.calls/remaining` 支持验证每轮上下文和调用次数。
- 设计原因：模型厂商细节留在适配器，Runtime 面向 `ModelReply`；Tool Call 必须保留请求/结果关联；错误分类让调用方决定策略；可控 Fake 避免联网模型的随机响应导致基础回归不可复现。
- 验证证据：新增 26 项测试及默认示例；真实回环 HTTP 验证传输而非只 Mock 方法；超时/取消通过受控异步替身验证，未当成远端网络可立即取消的证据。
- 难点与取舍：见上表，重点为严格工具参数与未知用量处理、非流式线程 I/O 的取消限制、Fake 状态隔离；暂不自动修复模型输出或在 Provider 层重试，避免隐式改变语义。
- 指标与结论：75 项测试通过是当前受控正确性证据；未测量真实任务成功率、吞吐、Token 成本或生产可用率，没有性能提升数字。
- 面试可讲事实：为 Agent Runtime 实现统一非流式模型适配层，将工具参数与消息格式转换、Usage、错误类型收口，提供确定性 Fake Provider 并用本地 HTTP 服务验证真实请求链路，为后续 AgentLoop 建立可重复测试基础。
- 后续差距：未验证真实模型能力，未接桌面用户链路，未实现 ToolManager/AgentLoop、流式与完整取消、自动退避、多模型切换或完整评测；不能把本阶段写成已完成 Multi-Agent 平台或企业业务落地。

### 后续事项

- 下一项 P01-04：模型与配置接口、`/message` 非流式调用、`inline_reply` 桌面展示和统一错误反馈。
- P01-05 接入流式协议、内部事件及取消生命周期；需优先解决本次记录的后台线程限制。
- 真实外部供应商验收另行记录所用模型与结果；当前仅提供显式 `--live` 入口，未自动使用真实凭据。

## 2026-10-21：P01-04 普通聊天联调

### 需求

按照开发计划完成 P01-04：接通桌面端配置与模型查询/保存接口，让 `/message` 调用 P01-03 的非流式 Provider，并使用现有前端支持的 `inline_reply` 展示完整回答；非法输入和模型调用失败返回明确错误。继续遵循最新 `AGENTS.md`：新增类和函数使用中文说明，关键流程输出带文件名与函数名的中文日志，并记录难点评分、实现方式及岗位重合证据。

### 完成内容

- 新增 `YanAgentApplication` 应用层，将 `ConfigStore`、Provider 工厂和桌面 HTTP 契约隔离开。生产默认创建 `OpenAICompatibleProvider`，测试注入 `FakeProvider`；应用层不依赖 `BaseHTTPRequestHandler`，可以离线验证。
- 接通 `GET/POST /config`：将精简配置映射到复制桌面端的 `ConfigData`，兼容 `bot_type → model_provider`、`agent_permission_mode → permission_mode`；`cow_lang` 和 `use_linkai` 作为尚未进入精简配置的复制 UI 字段不落盘。未知字段失败，不静默吞掉拼写错误。
- 接通 `GET/POST /api/models`：返回单一 `openai-compatible` Provider、密钥/API Base 脱敏状态、模型目录和 Chat 能力；支持 `set_provider`、Chat 的 `set_capability` 及 `delete_provider`。语音、视觉、Embedding、搜索、模型发现和多 Provider 管理未实现时明确拒绝或显示不可编辑，不返回虚假成功。
- 将 `/message` 从固定占位回复改为真实 Provider 调用：校验 `session_id`、消息、stream 类型、Agent 和 P01-04 能力范围；构造一条内部 `Message(role="user")`，调用 `complete(..., tools=[])`，把 `ModelReply` 转成 `stream=false + inline_reply`，并返回 finish reason 与 Usage。
- 对齐了桌面 `chatStore` 的已有兼容分支：前端当前仍发送 `stream=true`，收到 `stream=false` 和 `inline_reply` 后会结束 loading 并一次性写入 Assistant 气泡。本任务没有伪造 SSE，流式按 P01-05 实现。
- 每个消息请求在调用模型前分配 `run-...` 请求 ID；成功和失败日志均可关联该 ID。日志写明 `[chat.py][类.函数]` 或 `[app.py][类.函数]`，记录动作、错误码、Provider 和输出长度，不记录用户消息正文、API Key 或上游响应正文。
- HTTP 层增加 1 MiB 请求上限、严格 JSON 对象解析和错误状态映射；单条消息限制 200,000 字符。空字段、附件、语音、其他 Agent 及意外工具请求均明确失败，避免被当成普通聊天成功。
- 新增 `RequestValidationError` 与 `UnexpectedToolCallError`。配置/请求返回 400，认证 401，权限 403，模型不存在 404，限流 429，超时 504，拒绝 422，连接/响应/上游服务异常 502；正文保留统一安全错误对象。
- 修改 TypeScript API Client：非 2xx 时读取后端安全的 JSON `message`，聊天气泡可以显示“缺少 API Key”“认证失败”“超时”等中文原因，而不只有浏览器状态文本。
- 健康状态从 `not_implemented` 更新为 `non_streaming_chat`；AgentLoop 的占位测试仍保留，防止将本次普通单轮调用误写成完整工具循环已实现。
- 新增 10 项 P01-04 行为测试、接口说明和手工验收步骤；同步更新需求勾选、路线、README 和岗位状态。P01 仍是进行中，下一项为 P01-05。

### 调用流程与设计取舍

```text
Electron/React chatStore
  → POST /message（stream=true）
  → YanAgentHandler：正文边界、JSON、HTTP 错误
  → YanAgentApplication：业务字段和阶段能力校验
  → ConfigStore.load()：当前生效配置快照
  → ProviderFactory(config)
  → OpenAICompatibleProvider.complete([User Message], tools=[])
  → ModelReply
  → {stream:false, inline_reply, request_id, finish_reason, usage}
  → chatStore 完成当前 Assistant 气泡
```

- 没有把模型调用直接写进路由分支：HTTP 只做传输，应用层做请求语义和配置适配，Provider 继续只负责模型协议。这使测试不必启动 Electron，也不必把 Fake 逻辑写入生产代码。
- 配置模型在 P01-04 每次消息读取一次不可变快照；网络等待期间不持有配置锁。配置读写用进程内 `RLock` 避免当前线程 HTTP 服务内的交叉写入，但尚未解决多进程写同一文件的问题。
- 当前 `BaseHTTPRequestHandler` 每条请求运行在线程中，内部暂用 `asyncio.run()` 执行一次非流式协程。这对 P01-04 的单次调用足够清晰，但不适合作为长期异步 Runtime；P01-05 必须设计常驻事件循环、Run 任务、事件队列和跨线程通信。
- Provider 没有收到工具描述，若模型仍返回 Tool Call，不自动执行、不丢弃，也不把空文本当回答，而是返回 `unexpected_tool_call`。真正工具链属于 P03～P04。
- 当前模型目录给出常见名称作为首次设置入口；它们不是能力声明或真实可用性保证。用户选择的模型必须与 API Base 一致，外部真实验证留到 P01-06。
- 只有当前用户消息进入 Provider，多轮上下文、完整历史和持久化明确留在 P02；`session_id` 当前用于接口关联，不代表数据库归属校验已完成。

### 涉及文件

- `yanagent/chat.py`
- `app.py`
- `yanagent/errors.py`
- `desktop/src/renderer/src/api/client.ts`
- `tests/test_chat_integration.py`、`tests/test_scaffold.py`
- `docs/P01_04_CHAT_INTEGRATION.md`
- `docs/DEVELOPMENT_REQUIREMENTS.md`、`docs/IMPLEMENTATION_ROADMAP.md`、`docs/TARGET_ROLES.md`
- `README.md`、`workProcess.md`

### 验证结果

- `.\.venv\Scripts\python.exe -X utf8 -W error -m unittest discover -s tests -v`：85 项测试通过；其中 P01-04 新增 10 项，原有 75 项回归通过。
- P01-04 应用测试：配置/模型两种适配返回同一状态且不泄密；旧配置字段和模型动作正确落入精简配置；`inline_reply`、结束原因、Usage 和当前单条输入符合契约；坏请求不消费 Fake 预设；配置缺失在发网前失败；意外 Tool Call 不执行。
- P01-04 真实回环 HTTP：桌面完整请求即使携带 `stream=true` 也收到 `stream=false + inline_reply`；`/config` 和 `/api/models` 路径可查询/保存；400 请求错误与 401 认证错误均返回稳定代码、安全中文说明和请求 ID。
- `.\.venv\Scripts\python.exe -X utf8 -W error -m compileall -q -f app.py yanagent tests examples`：通过。
- `desktop\npm run build`：Vite renderer 与 TypeScript main 构建通过。构建输出保留既有的字体路径、Browserslist 数据、动态/静态导入及大 chunk 警告；这些不是本次引入的失败，未在 P01-04 扩大范围处理。
- 本次没有读取、打印或调用用户真实 API Key，没有访问外部模型供应商。真实回环 HTTP 和 Fake 证明接口/控制流可复现，但不等于真实模型桌面联调已通过。
- 开发时在受限 Windows 沙箱内运行 asyncio 测试仍会阻塞；中止该轮后，在用户授权的普通 Windows 执行环境运行完整测试并通过。未修改系统事件循环或安全设置。
- 对本次新增/修改 Python 代码执行中文 Docstring 检查并进行差异检查；所有新增类和函数均有中文说明，日志关键路径包含文件名和函数名。

### 难点、评分与实现方式

整体开发难度：**7/10**。难点不在“再调用一次 API”，而在同时对齐复制前端、同步 HTTP 服务、异步 Provider、配置安全和真实错误语义。

| 难点 | 评分 | 容易出现的问题 | 实现方式与证据 |
|---|---:|---|---|
| 复制桌面端与精简后端契约对齐 | 7/10 | 前端请求 `/config` 而后端只有 `/api/config`；聊天固定发 `stream=true` 后只等待 SSE；模型控制台字段远多于当前配置 | 阅读 `client.ts`、`chatStore.ts`、`types.ts` 和模型页面；同时提供两套查询兼容映射；利用已有 `inline_reply` 分支；模型动作按白名单支持，其余明确拒绝；前端生产构建和真实 HTTP 验证 |
| 同步 HTTP 与异步 Provider 生命周期 | 7/10 | 在路由里阻塞事件循环、随意共享循环、把临时方案扩展成错误的 SSE 架构 | 应用层保持 async `chat()`，线程 Handler 仅在 P01-04 用 `asyncio.run()`；配置锁不跨网络等待；文档将常驻异步 Runtime 列为 P01-05 必须替换点，不提前实现半套流式 |
| 错误语义与桌面可见反馈 | 7/10 | 后端错误被前端压成 `HTTP 400`；上游正文或密钥进入响应/日志；失败没有 request ID | 内部错误类型→HTTP 状态→安全 JSON message；客户端读取 message；模型前分配 request ID 并贯穿错误日志/响应；测试覆盖 400/401、缺配置和不泄密 |
| 阶段边界和“不伪装成功” | 6/10 | 接受附件却忽略、模型请求工具却显示空白、把非流式完整文本标成 stream、把 session_id 当成已持久化 | 不支持能力显式报错；Tool Call 返回专用错误；成功明确 `stream=false`；文档写明当前只使用单条输入，Session/Persistence/Tool Loop/Cancel 均未完成 |
| 配置兼容与密钥保护 | 6/10 | 把整个复制 UI 配置写进精简文件、回写 `********` 覆盖密钥、环境值或密钥被接口泄露 | 白名单映射到底层 8 字段；脱敏值保存时跳过；查询只返回掩码；日志只记录字段名；测试检查序列化响应中不存在原始密钥 |

### 岗位要求关联与实践证据

- 开发任务：P01-04 普通聊天联调。
- 对应条款：XM-职责1“任务接入、上下文管理、执行编排、结果回写”的任务接入和结果回写基础，XM-职责6～7 的稳定性/可观测性/可维护性基础；DYQ-职责2 的核心链路及结果汇总基础、DYQ-职责3 的可复用协议和调试能力；TX-要求1 的 Python/TypeScript 工程能力。当前只覆盖单模型单轮非流式接入，不覆盖规划、多工具编排、Multi-Agent 或规模化业务。
- 重合范围：已经实现从桌面输入到 Provider 再回写聊天气泡的完整普通请求路径，统一配置与错误能被 TypeScript 客户端消费；没有实现长期上下文、任务拆解、工具执行、Reflection、评测体系或企业系统接入。
- 具体实现：`YanAgentApplication` 分离 HTTP/应用/模型边界；`/config` 与 `/api/models` 兼容适配；`/message` 的输入边界、请求 ID、Provider 调用和 `inline_reply`；客户端安全错误详情；Fake 与回环 HTTP 行为测试。
- 设计原因：让模型协议、业务语义和前端传输各自有单一边界，后续流式和 AgentLoop 可替换对应层而不是重写所有接口；对未实现能力失败比静默忽略更利于稳定性和调试。
- 验证证据：85 项 Python 测试、10 项本任务行为测试、真实回环 HTTP 和桌面生产构建；没有把未运行的真实外部调用写成验证通过。
- 难点与取舍：见上表。最大取舍是保留线程 HTTP 外壳并暂时每请求创建事件循环，以最小范围完成普通联调，同时明确 P01-05 的架构替换点。
- 指标与结论：当前只测得本地受控正确性和构建结果，没有真实模型延迟、吞吐、Token 成本、任务成功率或生产可用率数据，不声称任何百分比提升。
- 面试可讲事实：为自研 Agent Runtime 完成桌面到 OpenAI-compatible Provider 的普通聊天链路，设计应用层隔离配置/HTTP/模型协议，实现请求 ID、统一错误与密钥脱敏，并用 Fake 和真实回环 HTTP 覆盖成功及失败路径，同时维护 Python/TypeScript 接口兼容。
- 后续差距：需在 P01-05 实现常驻异步 Runtime、SSE、真正取消、并发隔离；P01-06 记录真实模型与桌面人工验收；P02 后才有多轮 Session；P03～P04 后才有工具调用闭环。不能据此声称完成 Agent Harness、Multi-Agent 或生产级系统。

### 后续事项

- 下一项 P01-05：设计长期异步执行环境、内部事件、Provider 增量解析、Run 事件队列、SSE 订阅、基本取消和任务清理。
- P01-06：补两请求隔离、流式错误与停止生成验证，并在用户自愿配置真实服务后记录模型名称和桌面人工结果；真实密钥不进入仓库或开发记录。
- P01-04 已完成，不自动进入 P01-05；等待用户明确开始下一项。

## 2026-10-21：配置本地 DeepSeek 默认模型

### 需求

为 YanAgent 准备一份可由用户稍后自行粘贴真实凭据的 DeepSeek 本地默认配置。

### 完成内容

- 更新项目根目录、已被 Git 忽略的 `config.json`，使用 OpenAI-compatible Provider。
- API Base 使用 DeepSeek 官方地址，默认模型使用当前可用的 `deepseek-flash`；旧 `deepseek-chat` 已由官方停止使用，因此没有继续写入过期模型名。
- 将配置文件中原有的非占位凭据替换为无效占位内容；开发记录不保存任何凭据值。
- 未把凭据硬编码到 Python/TypeScript 源码，也未修改 `config.example.json` 或全局默认配置，避免模板和 Git 历史携带秘密。

### 涉及文件

- 本地忽略文件：`config.json`
- 开发记录：`workProcess.md`

### 验证结果

- 使用 `ConfigStore` 成功读取配置，并通过 `require_model_ready()` 完整性校验。
- 安全展示只返回脱敏密钥；`git check-ignore` 确认 `config.json` 不会被正常 Git 提交。

### 后续事项

- 用户需要在本地 `config.json` 中将占位内容替换为自己的真实 DeepSeek API Key，然后重启 YanAgent。
- 真实模型请求尚未在本次配置操作中发送；填写有效凭据后再从桌面聊天页验收。

## 2026-10-21：P01-05 流式链路

### 需求

按照 `docs/DEVELOPMENT_REQUIREMENTS.md` 和最新 `AGENTS.md` 完成 P01-05：确定长期异步执行环境；定义内部流式事件；实现 OpenAI-compatible Provider 的真实 SSE 响应、文本和工具参数增量组装；创建 request_id、运行事件队列和桌面 SSE 订阅；实现基本取消、并发隔离与任务清理。技术行为继续对齐 CowAgentByYan 的桌面 SSE 契约，但不提前实现 Session、工具执行或完整 AgentBridge。

### 完成内容

- 新增 `yanagent/events.py`，把供应商 SSE、Provider 增量和桌面事件分成三个边界。`ModelStreamEvent` 明确区分 `text_delta`、`tool_call_delta`、`completed`；`RunEvent` 带独立序号和 request_id，并只向桌面暴露 `delta/done/cancelled/error`。
- 扩展 `OpenAICompatibleProvider.stream()`：发送 `stream=true` 的 Chat Completions 请求，逐块解析文本，按 tool index 累积调用 ID、函数名和 arguments 字符串，在 `[DONE]` 后严格解析参数对象并生成唯一 `ModelReply`。断流、坏 JSON、索引空洞、字段冲突、空回答和拒绝均不会冒充成功。
- 新增标准库 `UrllibSseTransport`：在守护读取线程中处理真实 HTTP SSE，多行 `data` 按空行组帧；禁止携带认证头自动重定向；限制总响应 8 MiB、单事件 1 MiB；沿用统一 HTTP 错误映射，不读取或回显上游错误正文。
- 扩展 `FakeProvider`，允许分别预设完整响应序列和流式事件序列，并继续复制输入/输出快照，给并发、错误、取消和后续 AgentLoop 提供确定性离线入口。
- 新增 `yanagent/runtime/streaming.py`：进程只维护一个后台线程和一个常驻 asyncio 事件循环。非流式请求也提交到该循环，不再由 HTTP Handler 为每条消息创建 `asyncio.run()`。
- 每条流式消息建立独立 `RunRecord`，保存 session_id、Future、带序号事件和终态。线程安全 Condition 连接异步生产者与 ThreadingHTTPServer；从 cursor 0 回放，因此模型先返回、EventSource 后建立也不丢开头；两条并发请求只读取各自事件。
- `/message` 根据 `stream` 选择完整回答或创建 Run；`/stream?request_id=...` 输出与现有 TypeScript `EventSource.onmessage` 一致的匿名 `data: JSON`；`/cancel` 可按 request_id 精确取消，也支持 session_id 兜底；未知 Run 返回 `unknown_request` 错误事件。
- 取消正常路径产生 `cancelled` 后再产生 `done(finish_reason=cancelled)`，保证前端立即恢复输入且 SSE 有明确终态。对“任务还没进入协程函数体就被取消”的竞态，RunRecord 使用 100 ms 兜底补齐终态；重复取消返回 0。
- Windows 标准库 `HTTPResponse.close()` 可能等待另一个线程的 `readline()`，因此响应关闭被移到独立守护线程，不能阻塞 asyncio 取消。读取线程仍受 `request_timeout` 限制，避免把“UI 已停止”等同于“操作系统已强杀 socket”。
- 终态 Run 默认保留 60 秒支持晚订阅/短期重连，之后惰性清理；活动 Run 不按 TTL 删除。服务关闭时幂等取消活动任务、停止事件循环并回收异步生成器。
- 新增 `docs/P01_05_STREAMING.md`；同步更新 README、需求、路线和岗位映射。P01 仍为进行中，下一项是 P01-06；真实外部模型与桌面人工验收没有被虚构为完成。

### 涉及文件

- 运行与协议：`yanagent/events.py`、`yanagent/runtime/streaming.py`、`yanagent/runtime/__init__.py`
- Provider 与传输：`yanagent/models/provider.py`、`yanagent/models/openai_compatible.py`、`yanagent/models/transport.py`、`yanagent/models/fake.py`
- 应用与 HTTP：`yanagent/chat.py`、`app.py`
- 测试：`tests/test_provider.py`、`tests/test_provider_http.py`、`tests/test_chat_integration.py`、`tests/test_streaming_runtime.py`、`tests/test_scaffold.py`
- 文档：`docs/P01_05_STREAMING.md`、`docs/DEVELOPMENT_REQUIREMENTS.md`、`docs/IMPLEMENTATION_ROADMAP.md`、`docs/TARGET_ROLES.md`、`README.md`、`workProcess.md`

### 关键流程日志

- `[streaming.py][AgentRuntime.start_stream]`：记录 Run 登记、request_id 与 session_id，不记录消息正文和密钥。
- `[streaming.py][AgentRuntime._run_stream]`：记录完成字符数、取消或统一错误码。
- `[streaming.py][AgentRuntime.cancel]`：记录取消目标和实际取消数量。
- `[streaming.py][AgentRuntime.close]`：记录常驻异步运行环境关闭。
- `[app.py][YanAgentHandler.do_GET]`：记录 SSE 客户端断开，但不自动取消后台任务。

### 验证结果

- `.\.venv\Scripts\python.exe -m unittest discover -s tests -v`：96 项测试通过；原有 85 项全部回归通过，本任务新增 11 项核心行为覆盖。
- Provider 流测试：文本分块、Usage、工具 ID/名称/参数跨块还原、可控 Fake、缺失 `[DONE]`、坏 JSON 和空响应均验证。
- 真实回环 HTTP/SSE：默认标准库传输收到逐块文本和 `[DONE]`；取消阻塞中的下一块约 0.1 秒内返回；同一请求不重试；普通 401/429、禁止重定向和非流式路径继续通过。
- Runtime 测试：两条并发 Run 内容互不混淆；晚订阅完整回放；运行中取消到达 Provider；立即取消竞态仍得到终态；终态 TTL 到期后清理。
- 桌面 HTTP 测试：`POST /message(stream=true)` 返回 request_id；真实 `GET /stream` 得到两条 delta 和一条 done；`POST /cancel` 能终止活动 Provider 并产生 cancelled + done；非流式 `inline_reply` 兼容路径继续通过。
- `desktop\npm run build`：Vite renderer 与 TypeScript main 构建通过。保留的字体路径、Browserslist、动态/静态 import 和大 chunk 提示均是已有构建警告，不是本次流式改动失败。
- `python -m compileall` 和 `git diff --check` 通过；Git 仅提示 Windows 后续可能转换 LF/CRLF。

### 开发难点与评分

整体难度：**8/10**。这次不只是“把文字一块块返回”，而是同时处理线程 HTTP、单一异步循环、真实网络增量、事件回放、取消竞态和资源生命周期；任一层含糊都会表现为串流、卡死、假取消或工具参数损坏。

| 难点 | 难度 | 主要风险 | 实现方式与验证 |
|---|---:|---|---|
| 线程 HTTP 与异步 Runtime 桥接 | 8/10 | 每请求新建事件循环导致任务无法被另一接口取消；跨线程直接操作 asyncio 对象 | 独立后台线程维护唯一事件循环；`run_coroutine_threadsafe` 调度；RunRecord 用 Condition 连接异步生产者和 SSE 请求线程；双 Run 和关闭测试验证 |
| 流式协议和工具参数组装 | 8/10 | 文本重复/丢块；工具 ID 与参数串错；半段 JSON 被当完整对象；断流被误报成功 | 三层事件；按 tool index 累积并校验 ID/名称；只在 `[DONE]` 后完成；坏 JSON、索引和真实 HTTP SSE 测试验证 |
| 取消竞态与阻塞 I/O | 9/10 | Future 取消早于协程启动时没有终态；同步 close 卡住事件循环；UI 停止但后台永久占用 | 正常 CancelledError 分支 + 100 ms 终态兜底；close 移到守护线程；socket timeout 保证底层有限回收；立即取消与慢 SSE 测试验证 |
| SSE 晚订阅、断线和清理 | 7/10 | Run 返回速度快于 EventSource 建连而丢首块；断线误取消；终态永久占内存 | 事件列表按序保留并从 0 回放；客户端断开不取消 Run；终态保留 60 秒后惰性清理；晚订阅与 TTL 测试验证 |
| 桌面兼容与错误边界 | 6/10 | 发送 `event: delta` 导致现有 onmessage 收不到；错误正文/密钥进入 SSE；非流式回归破坏 | 严格对齐 `data: {type:...}`；统一安全错误；保留 inline_reply；真实桌面接口测试和 TypeScript 构建验证 |

### 与目标岗位的重合点

- **XM-职责1**：完成了任务接入后的运行登记、流式执行与结果回写基础；request_id 将创建请求、SSE 和取消串成一条链。尚无上下文恢复和工具编排。
- **XM-职责6～7**：响应大小限制、统一错误、禁止认证重定向、超时、取消竞态、终态清理和关键日志属于稳定性、可观测性、性能与可维护性基础；没有生产流量、成本或 SLA 数据。
- **XM-要求2、XM-要求5～6**：体现 Python 异步/线程实现、TypeScript 协议联调、可运行 Side Project 和中文设计/复盘。不能替代学历、出勤或团队经历。
- **DYQ-职责2～3**：实现 Agent 核心链路中的模型增量、执行管控、结果汇总和可复用事件/Provider/Runtime 协议，并用自动化测试形成调试与质量证据；尚无任务规划、多工具调用和业务价值评测。
- **DYQ-要求2～4、DYQ-加分1**：体现 Python 工程、Agent 项目实践、结构化文档和可展示个人项目基础；没有开源贡献事实时不能写成开源贡献。
- **TX-职责1、TX-职责3**：实现最小任务调度、运行隔离、取消传播和质量保障测试；尚未实现 Multi-Agent、规划、成本评测体系。
- **TX-要求1～2、TX-要求6、TX-加分1～2**：体现 Python/TypeScript、Tool Use 协议前置能力、系统边界思考和 Agent Runtime 实践；当前工具只组装不执行，也没有 Memory、Reflection 或系统性效果评测。
- **DYG-职责4、DYG-要求2～5**：属于基于 LLM 的 Agent 工程链路落地和可靠性基础；当前没有用户增长业务、自动规划、任务拆解、Multi-Agent 或亿级场景证据。

### 能力边界与面试口径

- 可以表述：为自研 Agent Runtime 设计常驻异步执行环境和线程安全 Run 注册表，实现 OpenAI-compatible SSE 增量解析、工具参数跨块组装、晚订阅回放、请求隔离、基本取消和资源清理，并以 96 项测试、真实回环 SSE 和桌面构建验证。
- 不可以表述：已完成完整 Agent Harness、工具执行闭环、多轮上下文、生产级 Gateway、云端 Runtime、Multi-Agent、MCP 或企业级部署。
- 本阶段没有发送真实 DeepSeek/外部模型请求，也没有记录桌面人工演示；真实密钥从未进入源码、测试或开发记录。

### 后续事项

- 下一项 P01-06：使用用户本地有效配置做真实模型和桌面人工联调，覆盖流式错误、停止生成、两请求隔离及阶段验收记录；凭据不得进入 Git 或文档。
- P02 实现 Session 与持久化后，done/cancelled/error 才能形成可恢复历史；当前 Run 只保存在进程内 60 秒。
- P03～P04 才消费已经正确组装的 ToolCall，加入 Schema、权限、执行、结果回写和循环；本次不能把“解析工具调用”描述成“会调用工具”。

## 2026-10-22：P01-06 验证与文档

### 需求

按照 `docs/DEVELOPMENT_REQUIREMENTS.md` 和最新 `AGENTS.md` 完成 P01-06：覆盖配置、普通/流式调用、流式错误、停止生成和两次请求隔离；使用真实外部模型及 Electron 桌面端完成阶段验收；同步更新需求状态、验收文档和开发记录。技术链路继续以 CowAgentByYan 的桌面消息/SSE 使用效果为参考，不提前实现 P02 的持久化或 P03～P04 的工具循环。

### 实际完成内容

- 扩展真实回环 Provider 测试。测试服务现在能在流式握手阶段返回 401、404、429，验证 `authentication_error`、`model_not_found`、`rate_limit` 的分类；错误正文故意包含测试秘密，断言异常与 SSE 不回显。另增加正常结束但没有文本或工具的真实 SSE，确认产生 `empty_model_response`。
- 新增桌面 HTTP/SSE 错误矩阵：缺少密钥、错误密钥、无效模型、超时、限流和空响应均通过真实 `/message` 创建 Run，再经 `/stream` 得到唯一、稳定、安全的 `error` 事件；事件中不存在本地配置凭据。
- 新增两请求端到端隔离验收。`EchoStreamProvider` 让两个请求逐字符交错，两个线程同时订阅各自 SSE；断言 request_id 不同，各自 delta 拼接与 done 完整文本只含本请求内容。
- 保留并复用 P01-05 的停止生成真实 HTTP 测试：阻塞 Provider 发出首块后等待，桌面同契约 `/cancel` 返回取消数量 1，取消进入 Provider 的 `finally`，SSE 有限结束为 `cancelled + done(finish_reason=cancelled)`。
- 新增 `scripts.verify_p01_real_api`。脚本只从 Git 忽略配置或环境读取凭据，输出 Provider、API 主机、模型、超时、耗时、回答、增量数与 Usage，不输出 API Key、Authorization 或配置原文；统一错误只显示安全 code/message。
- 2026-10-21 使用本地 DeepSeek 配置完成真实验证：模型 `deepseek-flash`，API 主机 `api.deepseek.com`。非流式回答“普通调用通过”，1.999 秒，Usage 45/53/98；流式回答“流式调用通过”，1.144 秒、4 个文本增量，Usage 46/51/97。密钥未进入终端输出、代码、测试或文档。
- 2026-10-22 从源码启动 Electron 桌面端，输入固定验收提示词，观察到消息进入时间线、等待气泡、停止按钮、流式完成后的 Assistant 气泡“桌面流式通过”，以及输入框/发送按钮恢复。
- 桌面长输出验收中，停止按钮可见并执行点击；DeepSeek 输出在人工确认取消反馈前快速完成，因此没有把该次外部 socket 写成“确定已被中断”。后台取消结论来自可控阻塞 Provider 的真实 HTTP 测试，明确区分人工观察与确定性自动化证据。
- 新增 `docs/P01_06_VERIFICATION.md`，沉淀验收矩阵、真实 API 命令、真实模型结果、桌面步骤、取消证据边界和阶段能力边界。
- 更新后端能力版本、README、需求文档、路线和岗位映射。P01-01～P01-06 均标记完成，P01 阶段改为“已完成”，下一项严格按需求文档进入 P02-01 数据库基础。

### 涉及文件

- 验收脚本：`scripts/__init__.py`、`scripts/verify_p01_real_api.py`
- 行为测试：`tests/test_provider_http.py`、`tests/test_chat_integration.py`
- 后端能力标识与日志：`app.py`
- 验收文档：`docs/P01_06_VERIFICATION.md`
- 状态与导航：`docs/DEVELOPMENT_REQUIREMENTS.md`、`docs/IMPLEMENTATION_ROADMAP.md`、`docs/TARGET_ROLES.md`、`README.md`
- 开发记录：`workProcess.md`
- 本地忽略配置：`config.json` 仅被读取用于实测，没有写入 Git，也没有在记录中保存凭据

### 验证结果

- `.\.venv\Scripts\python.exe -X utf8 -W error -m unittest discover -s tests -q`：100 项测试通过；P01-05 的 96 项全部回归通过，本次新增 4 项聚合验收测试。
- 新增 Provider 证据：真实回环流式 401/404/429 各只请求一次并安全分类；空 SSE 正常结束得到专用空响应错误；错误正文中的测试秘密不出现在异常。
- 新增应用证据：六类要求错误均成为桌面可识别的 SSE 错误码；两条同时运行的 HTTP/SSE 请求逐字符交错但内容、request_id 和 done 不混淆。
- 停止生成证据：真实回环 `/message → /cancel → /stream` 确认取消传到阻塞 Provider，最终事件为 `cancelled + done`，不会在终态后继续写入 Run。
- `.\.venv\Scripts\python.exe -X utf8 -W error -m compileall -q -f app.py yanagent tests examples scripts`：通过。
- `desktop\npm run build`：Vite renderer 和 TypeScript main 构建通过；字体路径、Browserslist、动态/静态 import 与大 chunk 为已有警告。
- `scripts.verify_p01_real_api`：真实 DeepSeek 普通和流式调用均通过，实际结果已在上文及 `docs/P01_06_VERIFICATION.md` 记录。
- Electron 桌面人工验收：真实流式回答正确进入聊天气泡，生成/结束控制状态可见；取消的确定性后台结论由自动化测试补足。
- `git diff --check` 和敏感值扫描在最终文档更新后执行；本记录不包含任何 API Key、Token 或 Authorization 值。

### 开发难点与评分

整体难度：**7/10**。本次主要难点不是新增聊天功能，而是建立“每项结论对应哪一层证据”的验收体系，尤其要避免用 Fake、真实回环、外部 API 或桌面截图中的任意一种去冒充另外三种。

| 难点 | 难度 | 容易出现的问题 | 实现方式与证据 |
|---|---:|---|---|
| 错误矩阵跨层验证 | 7/10 | 只测试错误类构造却声称桌面可识别；流式握手错误被 200 SSE 分支吞掉；上游正文进入日志 | 回环服务在 SSE 前返回真实 HTTP 状态；六类错误从 `/message` 经 Runtime 到 `/stream`；测试正文放入秘密并做负向断言 |
| 并发隔离的端到端证明 | 7/10 | Runtime 单测通过但 HTTP request_id 或 SSE URL 仍可能串流；两个请求顺序执行无法暴露竞态 | Echo Provider 逐字符让出事件循环；两个请求先启动再用两个线程并发订阅；分别断言 delta、done 和排他文本 |
| 真实凭据与可复现证据兼顾 | 7/10 | 为了复现把 Key 写脚本/日志；只说“调通”却没有模型、模式、Usage；异常 traceback 泄密 | 验收脚本仅从忽略配置读取；输出白名单摘要；AgentError 安全化；记录模型、主机、耗时、增量、Usage，不保存凭据 |
| 桌面取消竞态的诚实结论 | 8/10 | 模型快速完成后仍把点击停止写成后台取消成功；只验证按钮却没验证 Provider 收到取消 | 桌面记录只声明观察到的 UI；后台取消使用阻塞 Provider 的真实 HTTP 测试确认；文档明确外部 socket 本次未独立证明 |
| 阶段状态收口 | 5/10 | 测试数与文档状态不一致；P01 完成后下一任务名称写错；把后续能力提前算入成果 | 同步 README/需求/路线/岗位映射/能力日志；按原需求准确指向 P02-01 数据库基础；列出未实现边界 |

### 岗位要求关联与实践证据

- **XM-职责1（任务接入、上下文管理、执行编排、结果回写完整链路）**：本阶段可证明单轮任务从 Electron 输入、HTTP 接入、Run 登记、Provider 调用、SSE 回写到气泡显示；上下文管理仅有本轮 `Message` 和配置快照，不具备多轮恢复，因此不能声称完整满足该条款。
- **XM-职责6～7（可用性、稳定性、可观测性、性能、Token 成本与维护性）**：统一错误、超时、响应上限、无自动重试、取消、并发隔离、关键中文日志和 Usage 记录属于基础实践；只记录单次真实耗时和 Token，不推导生产性能或成本提升比例。
- **XM-要求2、要求5～6**：代码体现 Python 异步/线程/HTTP/SSE 与 TypeScript 桌面契约，项目可运行且文档/复盘完整。没有据此扩大学历、出勤或团队推广经历。
- **DYQ-职责2～3（核心链路、执行管控、结果验证、调试评测）**：P01 建立了 request_id、流式结果汇总校验、停止控制和可重复错误/并发验证；仍没有任务规划、多工具调用、缺陷发现或系统性 Agent Benchmark。
- **DYQ-加分1（个人项目/开源/博客）**：形成可演示个人项目和完整阶段验收文档；除非后续真实公开仓库或文章，不能写成开源贡献或技术博客事实。
- **TX-职责1、职责3与要求1～2、要求6**：体现 Python/TypeScript、模型调用、运行隔离、取消和质量保障思维；Planning、Memory、Tool Use 执行、Reflection 和评测/成本体系仍是后续差距。
- **DYG-职责1、职责4及要求2～5**：已完成一个基于 LLM 的单模型端到端工程链路并能结构化解释；没有复杂产品需求理解、自规划、任务拆解、Multi-Agent、人类经验学习或亿级业务证据。

### 面试可讲事实与边界

- 可以表述：为自研 Agent Runtime 完成第一阶段单模型链路，以统一契约连接 Electron、线程 HTTP、常驻 asyncio Runtime 和 OpenAI-compatible Provider；实现普通/流式调用、SSE、统一错误、基本取消和并发 Run 隔离；用 100 项测试、真实回环 HTTP/SSE、真实 DeepSeek 普通/流式请求与桌面人工验收收口。
- 可以表述：专门设计了安全真实 API 验收脚本，记录模式、耗时、增量和 Usage，同时保证凭据不进入源码、Git、日志或文档；对桌面取消的快速完成竞态采用受控阻塞 Provider 给出确定性证据，而没有夸大外部 socket 结果。
- 不可以表述：已经实现多轮 Session、持久化、Agent Loop、工具执行、MCP、Skills、Memory、Multi-Agent、Sandbox、本地/云双 Runtime、企业系统集成或生产级 SLA。
- 本次没有性能优化前后对照、线上用户量、并发吞吐、成功率或成本下降数据，不写百分比成果。

### 后续事项

- 下一项按需求文档执行 P02-01 数据库基础：确定 YanAgent 独立数据目录，使用 SQLite，建立 `sessions`、`messages`、`runs`、`schema_migrations` 并记录 Schema 版本。
- P02 完成前，桌面看到的旧界面内容不能当作后端 Session 持久化证据；当前后端 `/api/history` 仍返回空结构，Run 只在进程内短期保留。
- P03～P04 才实现工具注册、Schema/权限/执行和 Agent Loop；P01 只解析模型 ToolCall 并拒绝执行。

## 2026-10-22：并发交错与 request_id 隔离说明文档

### 需求

将本轮关于流式请求交错执行、两个回答如何隔离、桌面端如何人工观察并发、固定 `request_id` 的后果、重复 ID 判断与锁的运行方式，以及对应源码位置的问答整理为一份中文 Markdown 文档。

### 实际完成内容

- 新增 `docs/REQUEST_ID_CONCURRENCY_GUIDE.md`，按现象、运行原理、桌面人工验证、固定 ID 风险、字典重复判断、锁的原子保护、自动化并发测试和源码索引进行整理。
- 明确区分“后端执行时间交错”和“同一回答内容混合”：前者是正常异步并发，后者是错误串流。
- 说明当前实现遇到重复 ID 会拒绝第二个请求；同时分析删除重复检查后可能产生的覆盖、错误订阅和错误取消风险，避免把所有问题笼统描述成逐字混合。
- 记录从 `POST /message` 生成 UUID，到 `RunRecord` 登记、Provider 增量写入、SSE 按 ID 查询，以及并发测试排他断言的完整链路。

### 涉及文件

- 说明文档：`docs/REQUEST_ID_CONCURRENCY_GUIDE.md`
- 开发记录：`workProcess.md`

### 验证结果

- 对照 `app.py`、`yanagent/runtime/streaming.py`、`desktop/src/renderer/src/components/ChatInput.tsx`、`desktop/src/renderer/src/api/client.ts` 和 `tests/test_chat_integration.py` 核对函数名称、关键语句和源码位置。
- 文档没有写入 API Key、Token、密码或配置原文，也没有将人工观察描述成确定性的并发测试证据。

### 开发难点与评分

整体难度：**2/10**。本次为已有实现的说明整理，主要难点是准确区分重复 ID 被拒绝、字典映射被覆盖和真正共享同一 `RunRecord` 三种不同后果，并明确人工界面观察与自动化并发测试的证据边界。

### 岗位要求关联与实践证据

- **小米职责1、职责6～7及要求3**：文档可以作为解释任务接入、流式执行、request_id 隔离、并发稳定性和验证回路的学习材料；它记录的是个人项目机制与测试证据，不代表生产规模经验。
- **字节质量 Agent 职责2～3**：体现执行管控、结果回写、调试验证和通用运行协议的结构化表达；本次没有新增任务规划或多工具编排。
- **腾讯职责1、要求2及要求6**：能够结合源码说明异步执行、请求路由和隔离机制；本次仅新增说明文档，没有新增 Multi-Agent、Memory、Planning 或 Reflection 能力。

### 后续事项

- 本次没有修改运行逻辑或测试逻辑，P01 状态不变。
- 下一项业务开发仍按照需求文档进入 P02-01 数据库基础。

## 2026-10-22：P02-01 数据库基础

### 需求

按照 `docs/DEVELOPMENT_REQUIREMENTS.md` 和最新 `AGENTS.md` 完成 P02-01：确定 YanAgent 独立数据目录，使用 SQLite，建立 `sessions`、`messages`、`runs` 和 `schema_migrations`，从第一版记录 Schema 版本；技术实现参考 CowAgentByYan 的 ConversationStore 数据归属、稳定序号和 WAL 取舍，但不复制其历次兼容迁移或提前实现 P02-02 业务。

### 实际完成内容

- 新增 `yanagent.storage` 模块。默认数据目录为用户主目录下 `.yanagent`，数据库文件为 `yanagent.db`；支持 `YANAGENT_DATA_DIR` 显式覆盖，只读取 YanAgent 专属变量，测试确认即使存在 `COW_DATA_DIR` 也不会进入 `.cow`。
- 建立 Schema v1：`sessions` 保存 `user_id + agent_id + session_id` 复合归属、标题、置顶、时间和元数据；`messages` 保存稳定序号、角色、正文、工具消息预留字段和元数据；`runs` 保存请求身份、父 Run、受限状态、时间、结束原因、错误与 Usage；`schema_migrations` 保存版本、名称、迁移校验和与应用时间。
- 数据库层启用外键、WAL、`synchronous=NORMAL` 和 `busy_timeout`。消息与 Run 使用复合外键指向所属 Session；同一归属会话内的消息序号唯一；角色、置顶值和 Run 状态使用 CHECK 约束。
- 实现只向前的版本迁移器。`schema_migrations` 建表、业务 DDL、迁移登记和结构校验在同一个 `BEGIN IMMEDIATE` 事务中执行；SQL 或校验失败整体回滚。重复初始化核对迁移名称与 SHA-256 校验和并保留数据；数据库版本高于当前程序时拒绝旧程序写入。
- 将数据库初始化接入 `app.py/main()`：后端监听端口前先完成 Schema 初始化，数据库对象注入 HTTP Server 供 P02-02 继续接入；新增包含文件、函数、版本的中文关键日志。
- 新增 `docs/P02_01_DATABASE.md`，记录目录规则、四表字段用途、迁移流程、验证命令和能力边界；同步更新 README、需求状态、路线和岗位映射。P02 状态改为“进行中”，下一项为 P02-02。

### 涉及文件

- 数据库模块：`yanagent/storage/__init__.py`、`yanagent/storage/database.py`
- 启动接入：`app.py`
- 自动化测试：`tests/test_database.py`
- 测试临时目录忽略：`.gitignore`
- 实现说明：`docs/P02_01_DATABASE.md`
- 状态与导航：`docs/DEVELOPMENT_REQUIREMENTS.md`、`docs/IMPLEMENTATION_ROADMAP.md`、`docs/TARGET_ROLES.md`、`README.md`
- 开发记录：`workProcess.md`

### 验证结果

- `.\.venv\Scripts\python.exe -X utf8 -W error -m unittest tests.test_database -v`：新增 8 项测试全部通过。
- 首次初始化验证四张目标表、Schema v1、64 位迁移校验和、外键启用和 WAL；再次使用新 Database 实例打开同一文件，已有 Session 和唯一迁移记录均保留。
- 数据库约束验证：孤立消息、同一归属会话重复序号和非法 Run 状态均触发 `sqlite3.IntegrityError`。
- 版本与事务验证：高于当前程序的版本触发 `UnsupportedSchemaVersionError`；故意在第二条迁移 SQL 制造错误后，SQLite 中没有残留 `sessions` 或 `schema_migrations` 表。
- `.\.venv\Scripts\python.exe -X utf8 -W error -m unittest discover -s tests -q`：最终全量 108 项测试通过，本次运行 5.184 秒；原有 P01 的 100 项全部回归通过。该耗时仅是本机单次测试记录，不作为性能结论。由于 Windows `asyncio` 创建事件循环和回环 HTTP 需要本机 socket，该命令在允许本机 socket 的受控环境运行，不访问公网、不使用真实密钥。
- `.\.venv\Scripts\python.exe -X utf8 -W error -m compileall -q -f app.py yanagent tests examples scripts`：通过。
- `git diff --check`：代码阶段检查通过；最终文档更新后再次检查。
- 本次没有修改 Electron/TypeScript，因此未重复执行桌面生产构建；P01-06 的桌面构建证据保持不变。

### 开发难点与评分

整体难度：**6/10**。本次表面上是“建四张表”，真正难点是让第一版 Schema 能支撑后续归属隔离、消息顺序、工具消息和 Run 生命周期，同时保证迁移失败不会产生难以恢复的半成品数据库。

| 难点 | 难度 | 容易出现的问题 | 实现方式与证据 |
|---|---:|---|---|
| 首版 Schema 的未来兼容性 | 6/10 | 只用 `session_id` 主键，后续加入用户和 Agent 时重建大表；消息无法保存工具配对；Run 状态可写入任意值 | 从 v1 使用 `user_id + agent_id + session_id` 复合归属；预留工具/Usage/元数据字段；角色、序号和状态使用约束；结构测试验证 |
| 原子迁移与版本真实性 | 7/10 | `executescript` 或分段提交导致表建一半、版本却已记录；改写旧迁移后静默通过 | 手动 `BEGIN IMMEDIATE`，逐条执行并在同一事务登记；保存 SHA-256；失败回滚测试确认数据库无残留表 |
| 独立数据目录 | 5/10 | 复制桌面壳后继续读取 `COW_DATA_DIR`，污染 CowAgent 的 `.cow` 数据 | 仅支持 `YANAGENT_DATA_DIR`，默认 `.yanagent`；专门用同时包含 `COW_DATA_DIR` 的测试做负向验证 |
| SQLite 连接生命周期 | 5/10 | 误以为 `with sqlite3.connect()` 会关闭连接，Windows 临时库因句柄未释放无法删除 | 生产连接在 `finally` 关闭；测试使用 `contextlib.closing`；`-W error` 下无 ResourceWarning，全量测试通过 |
| 沙箱内 asyncio 验收 | 4/10 | 把 Windows socketpair 被沙箱拦截误判为业务死锁 | 用 `faulthandler` 定位到 `socket.accept()`；在允许本机 socket、禁用公网依赖的环境重跑同一测试，108 项通过；没有修改业务逻辑绕过测试 |

### 岗位要求关联与实践证据

- **小米职责1～2、职责6～7及要求3、要求6**：本次属于 Session/Gateway 后端的持久化基础，体现独立数据目录、身份维度、Schema 迁移、失败回滚、日志和稳定性取舍。当前尚未实现上下文读取、云端 Runtime 或完整 Sessions API，不能宣称已满足完整链路。
- **字节质量 Agent 职责2～3**：Schema 为运行轨迹、结果验证和可复用会话基础预留结构；8 项确定性数据库测试和 108 项回归属于工程质量证据，但不是 Agent 效果评测体系。
- **腾讯职责2～3、要求1、要求6**：体现 Python/SQLite、状态建模、Memory/Session 基础和质量保障思维；这不是长期记忆检索、Reflection、Benchmark 或成本管控的完成证据。
- **岗位通用结构化表达**：`docs/P02_01_DATABASE.md` 可用于面试说明“为什么从 v1 建迁移表、为什么使用复合归属键、为什么旧程序拒绝新数据库、如何验证事务回滚”。可以讲已实现和已测试的 SQLite 基础，不能把预留字段描述为已上线业务能力。

### 面试可讲事实与边界

- 可以表述：为自研 Agent Runtime 设计 SQLite Schema v1，覆盖 Session、Message、Run 和迁移记录；使用复合归属键、稳定消息序号、外键与状态约束，从数据库层为多会话隔离和运行恢复打基础。
- 可以表述：实现带迁移名称与 SHA-256 的只向前迁移器，所有 DDL、版本登记和结构校验处于同一立即事务；通过故障注入证明中途失败整体回滚，通过未来版本测试防止旧程序错误写入。
- 不可以表述：已经完成会话创建/分页/删除、消息持久化、多轮上下文恢复、并发业务写入、启动中断恢复、桌面历史联调或生产数据库性能优化；这些仍属于 P02-02～P02-05。

### 后续事项

- 下一项严格执行 P02-02：实现会话创建、分页、重命名、置顶、删除；事务追加消息；按稳定序号读取；保存时间、归属和元数据。
- P02-02 需要决定 SessionStore 的同步/异步边界和写事务策略，并复用本次 `Database.connection()`；不能绕过复合归属字段直接按裸 `session_id` 查询。
- P02-03 前聊天 Provider 仍只收到本次用户消息；数据库文件存在不代表当前聊天已经具有多轮记忆。
