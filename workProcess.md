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

## 2026-10-22：P02-02 会话与消息存储

### 需求

按照 `docs/DEVELOPMENT_REQUIREMENTS.md` 和最新 `AGENTS.md` 完成 P02-02：在 P02-01 SQLite 基础上实现会话创建、读取、分页、重命名、置顶和删除；事务追加完整消息；按稳定序号读取；保存时间、用户/Agent 归属和元数据，并为后续多轮上下文及桌面会话接口提供真实仓储。

### 实际完成内容

- 将 `yanagent/sessions/store.py` 从空接口替换为真实 `SessionStore`。仓储在构造时绑定 `user_id + agent_id`，所有会话与消息 SQL 均使用完整作用域，避免只凭裸 `session_id` 跨用户或跨 Agent 读取。
- 新增 `SessionRecord`、`SessionPage` 和 `StoredMessage`：分别表达会话摘要、分页状态和带稳定序号/消息 ID/时间的持久化消息。会话列表按 `pinned DESC, updated_at DESC, session_id ASC` 排序，相同时间下也能稳定分页。
- 实现 `create/get/list_sessions/rename/set_pinned/delete`。标题、分页、标识、布尔值和 JSON 元数据在进入 SQL 前校验；删除依靠已启用的复合外键级联清理关联消息。
- 实现异步 `append()` 与 `history()`，SQLite 阻塞操作通过 `asyncio.to_thread` 移出事件循环。追加使用 `BEGIN IMMEDIATE`：确认会话归属、读取最大序号、逐条写入、增加 `message_count` 和刷新时间处于同一事务，任意异常整体回滚。
- 消息存储覆盖角色、正文、名称、元数据、Assistant `tool_calls`、Tool `tool_call_id` 和 `is_error`。读取时恢复成统一 `Message` / `ToolCall` 契约，工具调用关联和失败含义不会因落库丢失。
- 数据库升级至 Schema v2，新增 `sessions.message_count` 和 `messages.is_error`。新增真实 v1→v2 升级测试：先用 v1 Schema 写入旧会话，再由当前版本迁移，确认旧数据保留且新字段得到默认值。
- 新增会话统一错误：参数非法、不存在、重复和存储失败。对外错误不回显 SQL、消息正文、工具参数或数据库异常原文；关键操作日志为中文，并带 `store.py` 与具体函数名。
- `context()` 继续明确为 P02-03 未实现，没有把“读取完整历史”冒充成“按 Token 预算构建模型上下文”。本阶段也没有提前修改桌面接口。
- 新增 `docs/P02_02_SESSION_STORE.md`，同步更新 README、需求文档、路线和岗位映射；P02-02 标记完成，下一项为 P02-03。

### 涉及文件

- 会话仓储：`yanagent/sessions/store.py`、`yanagent/sessions/__init__.py`
- 统一错误：`yanagent/errors.py`
- Schema v2 与事务入口：`yanagent/storage/database.py`
- 自动化测试：`tests/test_database.py`、`tests/test_session_store.py`
- 实现说明：`docs/P02_02_SESSION_STORE.md`
- 状态与导航：`README.md`、`docs/DEVELOPMENT_REQUIREMENTS.md`、`docs/IMPLEMENTATION_ROADMAP.md`、`docs/TARGET_ROLES.md`
- 开发记录：`workProcess.md`

### 验证结果

- `tests.test_database + tests.test_session_store`：18 项定向测试通过，其中 P02-02 新增 10 项（1 项迁移升级、9 项会话仓储）。
- CRUD 与分页：验证重复会话错误、标题规范化、置顶排序、分页总数/续页标记，以及其他用户会话不进入当前列表。
- 完整消息往返：固定四消息序列保存后还原，Assistant 工具调用对象、Tool 调用 ID、名称、元数据和 `is_error=True` 均一致，序号为 0～3。
- 事务故障注入：让批次第二条消息的全局 `message_id` 冲突，确认第一条也回滚、历史为空且 `message_count` 仍为 0。
- 持久化与隔离：重新创建 Database/SessionStore 后仍能读取会话和消息；删除用户 A 的同名会话不会影响用户 B，会话消息通过外键完成级联清理。
- Schema 升级：真实建立 v1 并写入旧会话后升级到 v2，旧标题保留、`message_count=0`、迁移记录连续。
- `.\.venv\Scripts\python.exe -X utf8 -W error -m unittest discover -s tests -q`：最终全量 118 项测试通过，本次运行 5.606 秒；该耗时仅是本机单次记录，不作为性能结论。Windows asyncio 测试在允许本机线程/回环资源且不访问公网的受控环境执行。
- `.\.venv\Scripts\python.exe -X utf8 -W error -m compileall -q -f app.py yanagent tests examples scripts`：通过；`git diff --check`：通过；敏感值模式扫描没有发现实际密钥，文档只包含 `Authorization: Bearer ...` 说明占位符。
- 本次没有修改 Electron/TypeScript，因此未重复桌面生产构建；P01-06 的构建证据保持不变。

### 开发难点与评分

整体难度：**7/10**。这次不难在 SQL CRUD 本身，而在于同时保证“归属不越界、批次不半写、顺序可恢复、内部消息语义不丢失、旧数据库可升级”。

| 难点 | 难度 | 容易出现的问题 | 实现方式与证据 |
|---|---:|---|---|
| 批次原子性与序号分配 | 7/10 | 先提交用户消息、Assistant 写入失败后留下半轮；两个写入读取同一最大序号；计数和真实消息不一致 | `BEGIN IMMEDIATE` 内读取最大序号、写整批、更新计数并一次提交；重复消息 ID 故障测试证明整批和计数同时回滚 |
| 完整内部消息持久化 | 7/10 | 只保存正文导致 ToolCall 参数、调用 ID 或失败含义丢失，重启后无法继续 Agent 循环 | ToolCall 使用 JSON 保存，Tool 结果独立保存引用和 `is_error`；四消息往返逐字段比较 `Message.to_dict()` |
| 多维归属隔离 | 7/10 | 全局按 `session_id` 查询，同名会话跨用户/Agent 可见或被误删 | Store 在构造时绑定可信作用域，每条查询都带三元身份；分页和删除隔离测试验证，接口认证仍明确属于后续范围 |
| 向前兼容迁移 | 6/10 | 直接修改 v1 建表语句使已有数据库缺字段；升级时丢失会话；旧消息无法表达工具失败 | 保持 v1 不变并新增 v2 `ALTER TABLE`；测试建立真实 v1、写旧数据后升级并检查默认值和迁移连续性 |
| 异步与 SQLite 边界 | 6/10 | 在 `async` 方法中同步访问磁盘阻塞事件循环；取消等待被误认为能强制终止底层线程 | 公共接口用 `asyncio.to_thread`；SQLite 自身事务控制一致性；文档明确线程取消和 Run 排队/取消仍属 P05 |

### 岗位要求关联与实践证据

- **小米职责1～2（上下文管理完整链路、Sessions 设计）**：本阶段真实实现 Session 后端的数据归属、CRUD、分页、稳定消息顺序和重启恢复，是后续上下文构建的持久化基础。当前 Provider 仍未加载历史，也没有 Gateway、本地 daemon/云端双 Runtime，因此只能描述为 Sessions 存储层证据。
- **小米职责6～7（稳定性、可观测性、维护性）**：事务回滚、向前迁移、统一安全错误、响应上限式分页和中文关键日志属于工程稳定性实践；没有生产压测、Token 成本或性能提升数据。
- **小米要求3（上下文管理实践）**：可以解释完整历史与模型上下文为什么分开，P02-02 保存不可丢失的完整记录，P02-03/P05 才负责选择和裁剪输入；本阶段尚无 Token 预算或摘要实践。
- **字节质量 Agent 职责2～3（上下文构建、执行管控、复用框架与调试评测）**：统一会话/消息模型、事务边界、稳定游标和确定性测试可作为框架基础证据；没有测试生成、代码评审、缺陷发现或 Agent 效果评测。
- **腾讯职责2～3及要求1、要求6（Memory、质量保障、系统思维）**：实现了短期会话记忆的数据层和 10 项新增行为测试，体现 Python/SQLite、迁移和故障注入；这不等于长期 Memory、向量检索、Reflection 或系统性 Benchmark。
- **岗位通用结构化表达**：`docs/P02_02_SESSION_STORE.md` 和本记录可用于讲清楚事务流程、游标分页、复合身份、Schema 升级和已知边界；只能陈述个人项目中已实现与已验证的内容。

### 面试可讲事实与边界

- 可以表述：为自研 Agent Runtime 实现 SQLite SessionStore，支持会话 CRUD/分页和完整消息持久化；以 `user + agent + session` 作为查询作用域，以立即事务分配稳定序号并原子提交整批消息。
- 可以表述：设计并验证 Schema v1→v2 无损迁移，保存 Assistant ToolCall、Tool Result 引用和失败语义；通过故障注入证明批次第二条失败不会留下第一条或错误计数。
- 不可以表述：模型已经能记住上一轮、桌面会话列表已接通、具备生产多租户认证、同 Session Run 队列、崩溃自动恢复、长期记忆或上下文 Token 压缩。这些仍属于 P02-03～P02-05、P05 和 P09。

### 后续事项

- 下一项严格执行 P02-03：区分完整历史与本次模型输入，将同 Session 的先前完整轮次传入 Provider，并为以后工具消息成对选择保留正确语义。
- P02-04 才把会话 CRUD 与历史接入 HTTP/桌面；本阶段通过后端单测验收，不把现有桌面静态会话 UI 当作功能证据。
- P02-05/P05 继续处理同 Session 并发排队、未结束 Run 恢复、取消传播和更完整的身份/授权入口。

## 2026-10-22：P02-03 历史与上下文接通

### 需求

按照 `docs/DEVELOPMENT_REQUIREMENTS.md` 和最新 `AGENTS.md` 完成 P02-03：区分数据库完整历史和本轮模型输入，将同一 Session 的先前完整轮次传入 Provider，并让普通/流式聊天真实写入 P02-02 的 SessionStore；工具调用及结果从数据库还原后保持内部消息语义。

### 实际完成内容

- 在 `YanAgentApplication` 中新增 `begin_chat()`：生产持久化模式先检查模型配置，创建或确认 Session，使用稳定游标读取完整历史，保存当前 User Message，再组装“旧历史 + 当前 User”交给 Provider。
- 新增 `finish_chat()`：将成功 `ModelReply` 转为完整 Assistant Message，附加当前 `request_id` 后落库。普通聊天只有在 Assistant 保存成功后才返回 `inline_reply`。
- `_ensure_session()` 支持桌面第一次直接发消息时自动建立会话，并容忍两个请求在 `get → create` 间发生的重复创建竞态；真正的同 Session 请求排队仍留到 P02-05/P05。
- 流式 Runtime 改为使用 `begin_chat()` 生成上下文。收到 Provider 完成事件后，先核对增量拼接结果，再保存 Assistant，最后发送 `done`；因此客户端看到成功终态时数据库已经有完整回答。
- 明确失败语义：模型失败、配置失败或未启用的工具请求不会产生虚假 Assistant；Provider 已开始前保存的 User Message继续保留。流式取消不把部分 Assistant 文本冒充完整回答写入历史。
- 在 `SessionStore` 新增 `complete_history()`，通过 `before_sequence` 多页读取并恢复升序。501 条旧消息测试确认不会被单页 500 条上限静默截断。
- 正式 `create_server(database=...)` 路径现在自动注入 `SessionStore(user_id=local, agent_id=default)`；源码/桌面启动会使用 `~/.yanagent/yanagent.db`。显式不注入仓储的旧离线测试模式继续保持单轮行为，避免测试污染真实用户数据。
- 工具消息历史进入 Provider 前恢复成统一 Message：Assistant ToolCall、Tool Result、调用 ID 和 `is_error` 均保留。P03/P04 未实现前仍不会真正执行新工具请求。
- 新增 `docs/P02_03_HISTORY_CONTEXT.md`，同步 README、需求状态、路线和岗位映射；P02-03 标记完成，下一项为 P02-04。

### 涉及文件

- 聊天上下文与持久化：`yanagent/chat.py`
- 流式完成顺序：`yanagent/runtime/streaming.py`
- 完整历史读取：`yanagent/sessions/store.py`
- 正式启动注入：`app.py`
- 自动化测试：`tests/test_chat_history.py`、`tests/test_chat_integration.py`
- 实现说明：`docs/P02_03_HISTORY_CONTEXT.md`
- 状态与导航：`README.md`、`docs/DEVELOPMENT_REQUIREMENTS.md`、`docs/IMPLEMENTATION_ROADMAP.md`、`docs/TARGET_ROLES.md`
- 开发记录：`workProcess.md`

### 验证结果

- `tests.test_session_store + tests.test_chat_history`：15 项定向测试通过，其中 P02-03 新增 6 项。
- 两轮上下文：第一轮“我叫张三”，第二轮“我叫什么”；第二次 Fake Provider 实际收到 User/Assistant/User，SQLite 最终为连续的 User/Assistant/User/Assistant 四条消息，并保存每轮 request_id。
- 重启与隔离：用新的 Database/SessionStore 打开同一目录后仍能恢复旧历史；不同 Session 的首次输入只包含自己的当前消息。
- 失败路径：Provider 抛认证错误后数据库仅保存 User，不伪造 Assistant；真实 HTTP/SSE 成功链路确认 `done` 后数据库已有回答。
- 工具历史：预置 Assistant ToolCall + 失败 Tool Result + Assistant 总结，下一轮 Provider 收到完整五消息上下文，调用 ID 与失败标记一致。
- 完整历史：501 条旧消息跨两页读取，加当前输入共 502 条传给 Provider，首条与末条顺序正确。
- 第一次全量回归暴露 6 个旧 Fake 测试被提前配置检查拦截；将提前配置检查限定在“已注入持久化仓储”的生产路径后，旧无状态 Fake 模式和新持久化模式均按各自契约工作。
- `.\.venv\Scripts\python.exe -X utf8 -W error -m unittest discover -s tests -q`：最终全量 124 项测试通过，本次运行 6.732 秒；耗时仅为本机单次记录，不作为性能结论。
- `.\.venv\Scripts\python.exe -X utf8 -W error -m compileall -q -f app.py yanagent tests examples scripts`：通过；`git diff --check`：通过，仅提示 Windows 工作区既有 LF→CRLF 转换信息。
- 敏感值模式扫描没有发现实际 API Key；测试只使用 `fake-key` 和无效示例地址。本次没有修改 Electron/TypeScript，因此未重复桌面生产构建。

### 开发难点与评分

整体难度：**7/10**。核心难点是决定历史读取、User 落库、Provider 调用、Assistant 落库和流式 `done` 的严格顺序，并对失败、取消、重启和长历史给出不夸大的确定语义。

| 难点 | 难度 | 容易出现的问题 | 实现方式与证据 |
|---|---:|---|---|
| 数据库历史与模型输入区分 | 7/10 | 把当前 User 重复写入或重复发送；用裁剪后的上下文覆盖完整历史；不同 Session 串历史 | 调用前先读取旧记录，再独立追加当前 User，临时组装 Provider 输入；两轮、重启和 Session 隔离测试逐条断言 |
| 流式完成与持久化顺序 | 8/10 | 先发 `done` 再写库，写库失败后 UI 显示成功但重启丢回答；每个 delta 都写库造成半条消息 | delta 只用于实时显示；完成事件先校验并保存完整 Assistant，成功后才 `done`；真实 HTTP/SSE→数据库测试验证 |
| 失败与取消历史语义 | 7/10 | 模型失败却伪造 Assistant；部分流式文本被当作完整答案；失败时删除用户事实 | User 在调用前保存；只有完整成功 Reply 保存 Assistant；失败测试确认仅一条 User；部分回答恢复留到后续阶段 |
| 跨页完整历史 | 6/10 | `history(limit=500)` 被误当完整上下文，长对话静默遗忘最早事实 | `complete_history()` 沿排他序号游标翻页并逆页恢复升序；501+1 条 Provider 输入测试验证 |
| 兼容旧 Fake 测试与正式持久化 | 6/10 | 为避免坏配置落库而全局提前检查，导致不依赖真实配置的 Fake Provider 失效 | 仅持久化生产路径提前检查；无仓储模式继续由 Provider 决定；首次回归失败被保留为修复证据，最终 124 项通过 |

### 岗位要求关联与实践证据

- **小米职责1（任务接入、上下文管理、执行编排、结果回写）**：已实现桌面请求进入 Runtime、按 Session 加载历史、调用 Provider、先持久化再成功回写的单模型多轮链路；还没有工具执行、桌面 Session 管理、Token 预算或生产认证，不能宣称完整 Agent 链路全部完成。
- **小米职责2及要求3（Sessions、上下文管理、Verification Loop）**：可以结合源码解释完整历史与模型上下文的边界、流式 `done` 前落库、重启恢复和失败语义，并有 Fake/SQLite/HTTP/SSE 分层测试；尚未实现 Gateway、双 Runtime、Sub-agent 或上下文压缩。
- **小米职责6～7（稳定性、可观测性、成本与维护性）**：关键步骤包含中文文件/函数日志，request_id 写入消息元数据，错误不伪造成功回答；本阶段发送全部历史，尚未优化 Token 成本，也没有生产性能数据。
- **字节用户增长职责1～2及质量 Agent 职责2～3**：具备可验证的多轮上下文构建、数据隔离、结果落库顺序和复用接口；没有自规划、任务拆解、多工具调用、多 Agent 协作或亿级 C 端证据。
- **腾讯职责2～3及要求2、要求6**：实现短期会话 Memory 的读取和决策输入链路，并用重启、长历史、工具语义和失败测试做质量保障；长期记忆、Planning、Reflection、评测和成本体系仍未完成。

### 面试可讲事实与边界

- 可以表述：把 SQLite SessionStore 接入普通与流式 Agent 聊天链路，明确“完整历史”和“本轮 Provider 输入”边界；第二轮调用真实携带第一轮 User/Assistant，关闭后重启仍可继续。
- 可以表述：设计流式一致性顺序——实时 delta 不逐块落库，完整响应校验后先事务保存 Assistant，再发成功 `done`；模型失败只保留真实 User，不制造 Assistant。
- 可以表述：通过 501 条跨页历史、工具调用配对、重启、Session 隔离和真实 HTTP/SSE 测试验证；同时明确当前全量历史会带来 Token 上限风险。
- 不可以表述：已经有 Token 裁剪/摘要、桌面会话管理、同 Session 串行队列、未完成 Run 恢复、长期记忆、工具执行、Multi-Agent 或生产级多租户。

### 后续事项

- 下一项严格执行 P02-04：将 `/api/sessions`、`/api/history` 和新建/打开/重命名/置顶/删除接到桌面真实界面，并明确单条删除和重新生成规则。
- P02-05/P05 处理同 Session 并发串行、未结束 Run 的中断恢复和取消记录；当前并发请求可能读取彼此写入前的历史快照。
- P05-04 才实现 Token 预算、完整轮次裁剪和摘要；当前 `SessionStore.context(token_budget=...)` 继续明确未实现，防止把“全部历史”伪装成安全预算上下文。

## 2026-10-22：P02-04 桌面会话联调

### 需求

按照 `docs/DEVELOPMENT_REQUIREMENTS.md` 和最新 `AGENTS.md` 完成 P02-04：把复制桌面的会话列表、历史、用户消息索引、重命名、置顶、删除和自动标题接口接到 YanAgent 自己的 SQLite；明确单轮删除、重新生成和后续上下文之间的规则，并让刚完成的实时消息立即具有数据库序号。

### 实际完成内容

- 新增 `DesktopSessionService`，作为桌面 JSON 契约与内部 `SessionStore` 之间的适配层。会话列表返回标题、置顶、消息数、创建/最后活动时间和 default Agent 标识；SQLite 毫秒时间戳在接口边界转换为桌面使用的秒。
- 将 `GET /api/sessions` 从固定空数组接到真实分页仓储，保留复制桌面发送的 `scope=all`；当前只允许 `agent_id=default`，不会把其他 Agent 标识静默映射到默认会话。
- 接通 `GET /api/history`。页码从最新一页开始，页内仍按消息发生顺序排列；`until_seq` 会把响应一次扩展到包含目标序号的更早页面，并返回实际到达的页码，支持桌面时间线直接跳转旧消息。
- 接通 `GET /api/history/user_messages`，只返回 User Message 的稳定序号、折叠空白后的预览和时间，避免为导航时间线传输全部 Assistant 正文。
- 接通 `PUT /api/sessions/{id}` 的重命名/置顶和 `DELETE /api/sessions/{id}` 的会话删除。删除前请求取消该 Session 的活动 Run，数据库依赖复合外键级联删除消息。
- 接通 `POST /api/sessions/{id}/generate_title`。标题从首条用户消息确定性生成，不额外消耗模型调用；`upsert_title()` 使用立即事务处理“标题请求先到、聊天建会话后到”的真实竞态，后续聊天不会覆盖标题。
- 接通 `POST /api/messages/delete`。目标必须是 User Message 的 `_seq`：`cascade=false` 删除这一轮，保留下一条 User 开始的后续轮次；`cascade=true` 从目标 User 截断到末尾。复制桌面的删除与重新生成都使用级联规则，避免保留已经受被删输入影响的后续回答。
- 普通和流式聊天现在保存 User 后记录 `user_seq`，保存 Assistant 后记录 `bot_seq`；成功普通响应和 SSE `done` 均在消息落库后返回两个真实序号。刚生成的气泡无需先刷新历史即可准确执行删除/重新生成。
- Assistant 的 Usage 同步放入消息元数据，历史适配层可恢复 `usage`；已有 ToolCall 继续按完整内部对象还原。P03/P04 未实现前没有声称能执行新工具调用。
- 新增会话/消息不存在的稳定错误映射：错误用户序号或用 Assistant 序号删除返回 `message_not_found` 与 HTTP 404；非法分页/字段返回 400；仓储故障不回显 SQL 或正文。
- 新增 `docs/P02_04_DESKTOP_SESSIONS.md`，记录接口、分页示例、自动标题竞态、删除/重新生成规则和未完成边界；同步 README、需求、路线和岗位映射，P02-04 标记完成，下一项为 P02-05。

### 涉及文件

- 桌面会话接口：`app.py`
- 桌面契约适配：`yanagent/sessions/desktop.py`、`yanagent/sessions/__init__.py`
- 会话分页、索引、自动标题与删除事务：`yanagent/sessions/store.py`
- 实时消息序号与 Usage：`yanagent/chat.py`、`yanagent/runtime/streaming.py`、`desktop/src/renderer/src/api/client.ts`、`desktop/src/renderer/src/store/chatStore.ts`
- 统一错误：`yanagent/errors.py`
- 自动化测试：`tests/test_session_store.py`、`tests/test_desktop_sessions.py`、`tests/test_chat_history.py`
- 实现说明：`docs/P02_04_DESKTOP_SESSIONS.md`
- 状态与导航：`README.md`、`docs/DEVELOPMENT_REQUIREMENTS.md`、`docs/IMPLEMENTATION_ROADMAP.md`、`docs/TARGET_ROLES.md`
- 开发记录：`workProcess.md`

### 验证结果

- 定向执行仓储、桌面 HTTP、聊天历史、聊天接口和流式 Runtime 共 40 项测试，全部通过。
- 新增 6 项独立测试：3 项仓储行为、3 项真实回环 HTTP 桌面联调；另在已有历史测试增加普通响应和 SSE `done` 的落库序号断言。
- 会话列表测试验证真实消息数、秒时间戳和桌面字段；历史测试验证 6 条消息的最新页 `[4,5]`、`until_seq=0` 扩展为 `[0..5]`、响应页码为 3；用户索引只返回序号 `[0,2,4]`。
- 管理动作测试验证重命名、置顶、标题先创建空 Session、整会话删除及删除后的 404；消息删除测试验证从序号 2 级联删除 4 条，只留下 `[0,1]`，并验证 Assistant 序号拒绝为 `message_not_found`。
- `.\.venv\Scripts\python.exe -X utf8 -W error -m unittest discover -s tests -q`：最终全量 130 项测试通过，本次最终运行 8.142 秒；耗时仅为本机单次记录，不作为性能结论。测试只使用本机线程和 `127.0.0.1` 回环，不访问公网。
- `.\.venv\Scripts\python.exe -X utf8 -W error -m compileall -q -f app.py yanagent tests examples scripts`：通过；`git diff --check`：通过，仅提示 Windows 工作区既有 LF→CRLF 转换信息。
- `desktop/npm run build`：通过，Renderer 共转换 2152 个模块且 Main TypeScript 编译成功。Vite 提示既有字体在运行时解析、Browserslist 数据较旧、主 chunk 较大；这些是非阻断警告，本次没有据此声称前端性能已优化。
- 最初在受限沙箱内执行 Windows asyncio 测试时卡在创建本机 socketpair；在允许本机回环资源的受控环境复跑后定向和全量测试均通过。该现象是测试执行环境限制，不作为产品功能缺陷或通过证据跳过。

### 开发难点与评分

整体难度：**8/10**。本阶段表面是补几个 HTTP 接口，真实难点是同时对齐桌面的分页方向、实时消息序号、自动标题竞态和删除后的上下文因果关系，并保持所有操作仍走同一份 SessionStore。

| 难点 | 难度 | 容易出现的问题 | 实现方式与证据 |
|---|---:|---|---|
| 历史分页与时间线跳转 | 7/10 | 数据库按升序存储，界面却把第 1 页定义为最新；翻页时重复消息；跳到旧消息只加载目标页导致中间断层 | Store 先确定最新页边界，再恢复页内升序；`until_seq` 计算目标所在的最新向前页并返回连续区间；`[4,5]` 与 `[0..5]` HTTP 测试验证 |
| 删除/重新生成的上下文一致性 | 8/10 | 只删屏幕气泡不删数据库；删掉中间问题却保留受它影响的后续回答；用数组下标误删 | 使用稳定 User `_seq` 定位；明确单轮与级联两种事务规则；桌面删除/重新生成统一级联；消息数量同事务扣减并用数据库历史断言 |
| 实时响应与数据库序号关联 | 7/10 | 新消息只有临时 UI ID，刷新前无法删除；在 Assistant 落库前就发 `done`，返回虚假序号 | `begin_chat` 返回 User 序号，`finish_chat` 返回 Assistant 序号；落库成功后普通/SSE 才回写；两条历史测试分别验证 `(0,1)` 和 `(2,3)` |
| 首轮自动标题竞态 | 7/10 | 桌面标题请求先于聊天建会话而 404；两条创建路径互相覆盖标题或消息 | `INSERT ... ON CONFLICT DO UPDATE` 放在立即事务；缺失时建空会话，存在时只更新标题；测试证明随后追加消息和再次改标题不丢数据 |
| 线程 HTTP 与异步仓储桥接 | 6/10 | 每个请求使用 `asyncio.run` 建不同循环；关闭时产生悬空任务；控制接口卡死无期限等待 | `AgentRuntime.execute()` 把短控制协程提交到进程唯一常驻循环，设置有限等待并统一映射仓储错误；全量 HTTP/Runtime 回归通过 |

### 岗位要求关联与实践证据

- **小米职责1～2（任务接入、上下文管理、结果回写、Sessions/Gateway 思路）**：本阶段形成桌面请求→HTTP 校验→常驻 Runtime→SessionStore→桌面 JSON 的真实会话管理链路，并解决标题竞态、历史分页和实时序号；仍是单机 default Agent，没有云端 Runtime、多 Agent Gateway 或生产认证。
- **小米职责6～7（稳定性、可观测性、成本与维护性）**：确定性标题避免额外模型 Token；删除与计数同事务；错误码和中文文件/函数日志支持定位；未做生产压测、成本仪表盘或性能提升测量。
- **小米要求3（上下文管理、Verification Loop 实践）**：可讲述为什么重新生成必须截断受旧输入影响的后续上下文，以及如何用真实 HTTP→SQLite 断言验证；Token 预算、摘要、同 Session 排队仍未实现。
- **字节用户增长职责1～2、质量 Agent 职责2～3（任务链路、上下文准确、执行管控和可复用框架）**：稳定序号、历史扩页、删除语义、统一适配服务和 130 项回归是工程化证据；没有自规划、任务拆解、多工具编排、需求到代码生成或亿级用户规模证据。
- **腾讯职责2～3及要求1～2/6（Memory、质量保障、系统思维）**：实现的是同 Session 短期 Memory 的产品读取/修改闭环，并用竞态、分页、错误和删除测试保障；不等于长期 Memory、Reflection、RAG、系统 Benchmark 或性能成本体系。
- **岗位通用 Coding Agent 实践**：本阶段在保持既有桌面 TypeScript 契约不变的情况下补 Python 后端，使用专项文档、确定性 Fake/SQLite/HTTP 测试和全量回归构成 Verification Loop；没有修改或声称贡献 Claude Code/Codex/Cursor 本身。

### 面试可讲事实与边界

- 可以表述：为自研 Agent Runtime 接通桌面 Session 管理，支持真实 SQLite 会话列表、最新页历史分页、用户消息索引、重命名、置顶、删除和自动标题；设计 `until_seq` 连续扩页支持时间线跳转。
- 可以表述：用稳定消息序号实现单轮删除和级联截断；桌面重新生成先删除目标问题及后续上下文再重发，避免保留已受旧输入影响的回答；普通/SSE 完成事件携带真实落库序号。
- 可以表述：处理首轮标题与聊天建会话的并发先后问题，使用原子 upsert；通过真实回环 HTTP 和全量 130 项测试验证接口到数据库闭环。
- 不可以表述：已经完成多租户认证、同 Session 串行调度、未结束 Run 崩溃恢复、Token 压缩、长期记忆、工具循环、Multi-Agent 或生产性能优化；这些属于 P02-05、P03～P05、P09～P10。

### 后续事项

- 下一项严格执行 P02-05：加强 `user_id + agent_id + session_id` 的接口级归属验证，验证并发写入边界，并在启动时将上次未结束的 Run 标记为 interrupted。
- P05-02 再实现同一 Session 默认排队、不同 Session 并行的完整 Bridge 策略；P02-04 的存储事务不等于 Run 调度已经串行。
- P05-04 实现 Token 预算、完整轮次裁剪和摘要；P02-04 历史接口始终展示完整记录，不用物理删除冒充上下文压缩。

## 2026-10-22：P02-05 隔离、并发写入与 Run 恢复

### 需求

按照 `docs/DEVELOPMENT_REQUIREMENTS.md` 和最新 `AGENTS.md` 完成 P02-05：所有 Session/Message/Run 查询与更新强制校验 `user_id + agent_id + session_id` 完整归属；验证同一 Session 并发写入不会产生重复序号或错误计数；后端启动接流量前将上次进程遗留的 `queued/running` Run 标记为 `interrupted`。同时接通普通聊天、SSE、取消和模型错误的真实 Run 终态，避免 `runs` 表继续只是空 Schema。

### 实际完成内容

- 新增 `yanagent/sessions/runs.py`，实现绑定可信用户/Agent 作用域的 `RunStore` 和不可变 `StoredRun`。Run 创建时在 `BEGIN IMMEDIATE` 事务内验证目标 Session 完整归属，读取和终态更新同时匹配 `request_id + user_id + agent_id + session_id`。
- Run 只允许 `queued/running` 原子转换到 `completed/failed/cancelled/interrupted` 一次；重复完成、错误 Session、错误用户或错误 Agent 均返回未修改，不会覆盖既有终态。
- 普通聊天和 SSE 在用户消息落库后创建 `running` Run；模型回答和 Assistant 消息保存成功后写 `completed + finish_reason + usage`；统一模型错误写 `failed + error_code`；显式停止写 `cancelled`。
- `YanAgentHTTPServer` 在开始接受请求前执行启动恢复：当前可信作用域内遗留的 `queued/running` 被写为 `interrupted`，同时记录 `process_restarted`、`run_interrupted` 和完成时间；其他作用域与已有终态不变。
- 新增 `RunAlreadyExistsError` 并映射为 HTTP 409，防止重复 `request_id` 覆盖或复用原 Run。日志只记录 ID、状态和稳定错误码，不保存消息正文、API Key、Usage 明细或原始数据库异常。
- 保留 SessionStore 已有 `BEGIN IMMEDIATE` 写事务，并增加两个独立仓储并发追加 20 条消息的测试：返回序号、数据库序号均严格为 `0..19`，正文无覆盖，`message_count=20`。
- 增加绕过 UI 的真实 HTTP 越权测试：数据库存在另一个用户的 `hidden-only` 会话和隐藏正文，但默认桌面列表不展示，直接请求历史得到 404，错误响应不包含隐藏内容。
- 普通与流式成功请求、流式取消和模型认证失败现在均检查 `runs` 表真实终态；新增 Server 构造测试确认恢复发生在服务接流量前，而不是只存在一个未调用的辅助函数。
- 新增 `docs/P02_05_ISOLATION_RECOVERY.md`，同步 README、需求文档 v1.7、路线图、岗位映射和启动能力日志；P02-05 与整个 P02 标记完成，下一项为 P03-01。

### 涉及文件

- Run 仓储与导出：`yanagent/sessions/runs.py`、`yanagent/sessions/__init__.py`
- 聊天与流式生命周期：`yanagent/chat.py`、`yanagent/runtime/streaming.py`
- 服务启动恢复与错误映射：`app.py`、`yanagent/errors.py`
- 自动化测试：`tests/test_run_store.py`、`tests/test_session_store.py`、`tests/test_desktop_sessions.py`、`tests/test_chat_history.py`、`tests/test_chat_integration.py`
- 实现说明：`docs/P02_05_ISOLATION_RECOVERY.md`
- 状态与导航：`README.md`、`docs/DEVELOPMENT_REQUIREMENTS.md`、`docs/IMPLEMENTATION_ROADMAP.md`、`docs/TARGET_ROLES.md`
- 开发记录：`workProcess.md`

### 验证结果

- P02-05 定向测试：Run 生命周期、失败、取消、启动恢复、普通/SSE 成功持久化和三元归属测试通过。
- 并发写入：两个 `SessionStore` 同时追加 20 条消息，所有序号唯一连续，正文集合完整，会话计数准确。
- 归属隔离：错误 user、agent 或 session 均不能读取或结束目标 Run；绕过桌面直接访问其他用户 Session 得到 404 且不泄露正文。
- 恢复幂等：默认作用域活动 Run 在 Server 构造时转为 `interrupted`；已完成和其他作用域的 Run 保持原状态；第二次恢复数量为 0。
- `.\.venv\Scripts\python.exe -X utf8 -W error -m unittest discover -s tests -p "test_*.py"`：全量 137 项测试通过；测试只使用本机 SQLite、线程和 `127.0.0.1` 回环，不访问公网。
- `.\.venv\Scripts\python.exe -X utf8 -W error -m compileall -q -f app.py yanagent tests examples scripts`：通过。
- `desktop/npm run build`：通过，Renderer 转换 2152 个模块且 Main TypeScript 编译成功；字体运行时解析、Browserslist 数据和大 chunk 为既有非阻断警告，本阶段没有据此声称前端性能已优化。
- `git diff --check`：通过，仅提示 Windows 工作区既有 LF→CRLF 转换信息。
- Windows 受限沙箱内的回环 HTTP 测试仍会阻塞；在允许本机回环资源的受控环境复跑定向与全量测试通过。该限制没有被当作功能失败，也没有跳过测试。

### 开发难点与评分

整体难度：**8/10**。难点不是把一行状态写入数据库，而是让完整归属、消息事务、普通/流式/取消/错误四条终态路径和进程恢复使用同一套可验证语义，同时不把数据库串行写误写成已经实现 Bridge 调度。

| 难点 | 难度 | 容易出现的问题 | 实现方式与证据 |
|---|---:|---|---|
| 完整归属与非泄露错误 | 8/10 | 只凭 `session_id` 或 `request_id` 查询；猜中 ID 后读到别人历史；错误响应回显隐藏正文 | Store 构造时绑定 user/agent，Session/Run 操作再强制匹配 session；跨用户/Agent/Session 单测与真实 HTTP 404 非泄露测试验证 |
| 并发序号和计数事务 | 8/10 | 两个写入都读取同一最大序号；一条覆盖或冲突；消息插入成功但计数丢失 | `BEGIN IMMEDIATE` 中完成读取最大序号、整批插入和计数更新；两个仓储并发 20 写验证 `0..19`、正文集合和计数 |
| 多入口 Run 终态一致性 | 8/10 | SSE 已发 done 但终态未保存；取消被记录为失败；错误终态保存异常覆盖原模型错误；重复完成覆盖结果 | 普通和 SSE 均在成功对外返回前完成 Assistant 与 Run；取消、AgentError、未知异常分别映射；活动状态条件保证一次转换；对应数据库断言通过 |
| 启动恢复与作用域 | 7/10 | 所有历史 running 永久悬挂；恢复误伤别的用户；已完成记录被再次改写；服务先接流量再恢复 | Server 初始化阶段按可信 user/agent 原子更新活动 Run；终态/异作用域/幂等测试验证，恢复数量写中文日志 |
| P02 与 P05 边界 | 6/10 | 把 SQLite 写锁当成同 Session 模型任务已经排队；崩溃后盲目重放可能有副作用的请求 | 文档明确本阶段只保证数据事务与状态收口；同 Session 默认排队、不同 Session 并行、续跑/幂等策略留给 P05 Bridge |

### 岗位要求关联与实践证据

- **小米职责1～2（上下文管理、执行编排、本地 Runtime、Sessions）**：实现从桌面消息到 Session、Run 创建、模型调用、结果回写和启动恢复的可追踪链路，完整归属和遗留状态收口可作为 Sessions/Runtime 工程证据；当前没有云端 Runtime、Gateway 多 Agent 路由或生产认证。
- **小米职责6～7（稳定性、合规、可观测性、维护性）**：越权不泄露、事务写入、确定性终态、启动恢复和中文安全日志属于稳定性与数据边界实践；没有生产压测、SLA、成本仪表盘或合规审计结论。
- **小米要求3（上下文、子 Agent 委派、Verification Loop）**：本阶段可讲述如何用 Fake Provider、真实 HTTP/SSE、SQLite 状态和 137 项回归构成 Verification Loop，以及为何数据库事务不等于调度；没有实现子 Agent 委派。
- **字节职责1～2、质量 Agent 职责2～3（任务执行、多 Agent 流转、执行管控和调试评测）**：Run 状态机基础、错误/取消/重启路径和确定性回归属于任务执行管控基础；尚无自规划、任务拆解、多 Agent 流转、需求到代码生成或亿级规模证据。
- **腾讯职责1～3及要求1～2/6（调度基础、Memory、质量保障、系统思维）**：用 Python/SQLite 实现短期会话 Memory 的归属、并发一致性和 Run 账本，并建立隔离/恢复测试；不等于完成 Planning、Reflection、完整调度引擎、长期 Memory、RAG 或系统 Benchmark。
- **岗位通用工程表达**：`docs/P02_05_ISOLATION_RECOVERY.md` 明确状态转换、事务边界、失败语义和未实现范围，可以复现并验证，不把计划项包装成完成项。

### 面试可讲事实与边界

- 可以表述：为自研 Agent Runtime 实现完整 Session/Run 数据归属，所有操作以用户、Agent、Session 作为作用域；通过直接 HTTP 越权测试确认猜中 Session ID 也不能读取数据。
- 可以表述：使用 SQLite 立即事务保证并发消息序号与计数一致，用两个独立仓储 20 路并发写验证没有重复、覆盖或丢失。
- 可以表述：接通普通、SSE、取消和错误的 Run 生命周期，并在服务接流量前将上次遗留活动 Run 原子标记为 interrupted；通过真实回环 HTTP 和数据库断言验证。
- 不可以表述：已经完成远程多租户认证、同 Session 请求队列、跨 Session 调度、崩溃自动续跑、生产并发压测、工具循环、长期记忆或 Multi-Agent。这些分别属于 P05、P03～P04、P09～P11。

### 后续事项

- 下一项严格执行 P03-01：完善工具定义、唯一名称、描述、参数 JSON Schema、风险、并行标记和作用范围，并导出统一模型工具 Schema。
- P05-02 再实现同 Session 默认排队、不同 Session 并行、追加指令和背压；本阶段仅证明 SQLite 数据写入正确。
- P05 设计恢复策略时必须处理“User Message 已落库但 Run 尚未创建”的崩溃窗口，并区分可安全重试与可能产生副作用的任务。

## 2026-10-23：P03-01 工具注册与统一 Schema

### 需求

按照 `docs/DEVELOPMENT_REQUIREMENTS.md` 和最新 `AGENTS.md` 完成 P03-01：完善 `ToolDefinition`，支持唯一名称、说明、参数 JSON Schema、风险等级、是否允许并行和作用范围；实现可发现的线程安全注册表，并导出 ModelProvider 可直接使用的供应商无关 Schema。严格保持阶段边界，不提前把注册功能写成工具已经可执行。

### 实际完成内容

- 将 `yanagent/tools/manager.py` 从空骨架实现为工具定义和注册基础。新增严格 `ToolDefinition`，包含 `name / description / parameters / handler / risk_level / parallel_safe / scope / requires_confirmation`。
- 工具名与现有 Provider 协议保持一致，只接受 1～64 位 ASCII 字母、数字、下划线或连字符；说明必须非空且限制长度；handler 必须可调用。
- 风险等级固定为 `low / medium / high`，作用范围固定为 `global / user / agent / session / workspace`，并行与确认标记必须为真正布尔值，避免 `1` 等隐式值进入权限和调度逻辑。
- 参数 Schema 只接受严格 JSON：拒绝循环引用、非字符串键、非有限数字和 Python 私有对象；顶层必须是 object，`properties` 必须是对象，`required` 只能引用已声明属性且不能重复。
- 顶层 `additionalProperties` 默认补为 `false`，显式允许未知字段会被拒绝。这样模型看到的 Schema 与后续 P03-03“未知参数拒绝”目标一致，不会出现模型被允许发送、执行层又拒绝的契约冲突。
- `ToolManager.register()` 在锁内执行名称唯一检查，同名工具明确抛 `ToolAlreadyRegisteredError`，不允许后注册实现静默覆盖 handler。注册前再次复制定义，避免调用方后改原 Schema 污染注册表。
- 新增 `get()`、`names()`、`schemas()` 和 `catalog()`：读取与导出均返回独立快照；工具按名称排序，确保注册先后不改变模型请求和测试结果。
- `schemas()` 只向模型输出 `name + description + parameters`；`catalog()` 才包含风险、并行、范围和确认元数据。安全策略字段不会作为未知 Provider 字段发送给模型。
- 导出的统一 Schema 已通过现有 `openai_compatible.prepare_request()` 验证，可继续由 Provider 适配层包装为 Chat Completions 的 function tool 格式。
- `execute()` 继续明确抛出未实现错误；P03-01 没有执行 handler，没有接入聊天，也没有把风险元数据冒充权限控制。时间/计算器、参数执行和权限分别留给 P03-02～P03-04。
- 参考 CowAgentByYan `BaseTool` 的 `name / description / params / parallel_safe` 和 ToolManager 注册概念，但没有复制其插件装载、MCP 生命周期或完整执行器；YanAgent 使用自己的显式定义、快照和阶段化边界。
- 新增 `docs/P03_01_TOOL_REGISTRY.md`，同步 README、需求文档 v1.8、路线图、P01 Provider 说明和岗位映射；P03-01 标记完成，下一项为 P03-02。

### 涉及文件

- 工具定义与注册：`yanagent/tools/manager.py`
- 工具公开接口：`yanagent/tools/__init__.py`
- 自动化测试：`tests/test_tool_registry.py`
- 实现说明：`docs/P03_01_TOOL_REGISTRY.md`
- 状态与导航：`README.md`、`docs/DEVELOPMENT_REQUIREMENTS.md`、`docs/IMPLEMENTATION_ROADMAP.md`、`docs/P01_03_PROVIDER.md`、`docs/TARGET_ROLES.md`
- 开发记录：`workProcess.md`

### 验证结果

- P03-01 新增 11 项定向测试：合法定义规范化、非法名称/元数据/Schema、输入与输出快照隔离、重名不覆盖、并发唯一注册、稳定排序、内部元数据隔离和 Provider 兼容均通过。
- 并发注册测试用两个线程同时注册 `calculator`，结果严格为一个 `registered`、一个 `duplicate`，注册表最终只有一项。
- Schema 适配测试将 `ToolManager.schemas()` 直接交给 `prepare_request()`，成功生成 Chat Completions function tool 包装；模型 Schema 不含风险、范围或 handler。
- 修改调用方原始 Schema、`get()` 返回定义或 `schemas()` 返回字典不会污染注册表中的保存快照。
- `.\.venv\Scripts\python.exe -X utf8 -W error -m unittest tests.test_tool_registry -v`：11 项定向测试通过。
- `.\.venv\Scripts\python.exe -X utf8 -W error -m unittest discover -s tests -p "test_*.py"`：全量 148 项测试通过，本次最终运行 12.403 秒；耗时仅为本机单次记录，不作为性能结论。
- `.\.venv\Scripts\python.exe -X utf8 -W error -m compileall -q -f app.py yanagent tests examples scripts`：通过。
- `git diff --check`：通过，仅提示 Windows 工作区既有 LF→CRLF 转换信息。
- 定向测试最初用 `asyncio.run()` 验证未实现入口时，在 Windows 受限沙箱卡在事件循环初始化；改为直接推进协程到首个异常后，测试不再依赖 socketpair。全量含 HTTP/asyncio 测试仍在允许本机回环的受控环境通过。

### 开发难点与评分

整体难度：**7/10**。核心难点是同时定义模型可理解的 Schema、内部安全元数据和后续执行边界，既不能让坏定义进入系统，也不能在 P03-01 过度实现完整 JSON Schema 或权限执行。

| 难点 | 难度 | 容易出现的问题 | 实现方式与证据 |
|---|---:|---|---|
| 内部元数据与模型 Schema 分层 | 7/10 | 把 risk、scope、handler 发送给 Provider 导致协议拒绝；或模型 Schema 与执行定义分成两份后漂移 | 单一 ToolDefinition 保存全部信息；`model_schema()` 只投影三字段，`catalog_entry()` 导出内部字段；Provider 适配测试验证 |
| Schema 安全子集 | 7/10 | 循环对象导致递归崩溃；NaN 无法严格编码；required 引用不存在字段；允许未知字段与后续执行策略冲突 | 递归严格 JSON 复制、活动对象检测、封闭 object Schema、required 一致性检查；8 类坏 Schema 测试验证 |
| 注册唯一性和快照隔离 | 7/10 | 两线程同时检查后都注册成功；后注册工具替换原 handler；外部字典修改导致运行中的工具定义漂移 | 唯一检查和写入放在同一 RLock；重复明确失败；构造、注册、读取和导出多次复制；并发和污染测试验证 |
| 风险、并行与范围语义 | 6/10 | 用任意字符串导致后续策略分支失控；把“parallel_safe=True”误解为当前已经并行执行 | 使用固定 Literal/运行时白名单和严格 bool；文档明确当前只保存元数据，P03-04/P04 才消费 |
| 阶段边界 | 5/10 | 注册表完成后顺手执行 handler，从而跳过参数校验、权限和超时；或保留全部空实现导致 P03-01 没有真实业务价值 | 完成定义/注册/发现/适配，`execute()` 保持显式未实现并有测试；后续编号和边界写入专项文档 |

### 岗位要求关联与实践证据

- **小米职责1、职责3（Agent 完整链路、Tooling/MCP 信息打通）**：本阶段实现统一工具描述、唯一注册和 Provider Schema 边界，是内置工具与未来 MCP 工具共享入口的协议基础；没有实现 MCP Client/Server、企业数据/监控/CI 接入或真实工具执行。
- **小米职责6～7（安全、稳定性、可维护性）**：封闭参数 Schema、风险/范围元数据、重名拒绝、线程安全注册和中文定位日志属于安全与维护基础；没有权限 UI、生产压测、成本或性能指标。
- **字节质量 Agent 职责2～3（多工具编排、可复用框架、工具协议规范）**：统一 ToolDefinition、稳定 Schema 和确定性注册测试可作为工具协议规范证据；没有多工具调用编排、测试生成、代码评审或结果汇总验证。
- **腾讯职责1～2及要求2/4（工具调用执行引擎、Tool Use、工具描述）**：实现了 Tool Use 的定义和发现层，可解释模型 Schema 与内部安全字段为何分离；尚未实现执行引擎、Planning、Reflection 或真实 Prompt 工具选择效果。
- **小米要求4、腾讯要求3/5（开源机制拆解和技术选型）**：实际对照 CowAgentByYan `BaseTool`/ToolManager 的字段与并行标记，选择显式数据定义而不是类扫描；这只是一个开源项目的局部机制拆解，不等于熟悉 OpenClaw、LangGraph、AutoGen、CrewAI 或 MetaGPT。
- **Verification Loop 实践**：用坏 Schema、重复/并发注册、快照污染和 Provider 转换构成确定性验证；这是工程回归，不等于 Agent 自主验证和修复闭环。

### 面试可讲事实与边界

- 可以表述：为自研 Agent Runtime 设计供应商无关 ToolDefinition，统一名称、说明、封闭 JSON Schema、风险、并行安全和数据作用范围，并由 Provider 适配层转换厂商格式。
- 可以表述：实现线程安全的唯一注册和多层快照隔离，用并发测试证明同名工具只有一个注册成功，用适配测试证明 Schema 能直接进入现有模型请求链路。
- 可以表述：参考 CowAgent 工具基类和管理器后，刻意分离模型可见 Schema 与内部权限/调度元数据，避免协议耦合并为 MCP 复用入口预留边界。
- 不可以表述：Agent 已经能调用计算器/时间工具、已完成参数校验、权限确认、超时截断、多工具循环、MCP、Sandbox 或工具并行执行。这些属于 P03-02～P04、P06 和 P08。

### 后续事项

- 下一项严格执行 P03-02：实现 `current_time` 和安全计算器；计算器使用受限解析，禁止 `eval/exec` 和任意函数、属性或导入。
- P03-03 再实现真实 ToolCall 参数类型校验、未知工具、统一 ToolResult、超时、异常和输出截断；当前参数 Schema 只定义接口。
- P03-04 将风险、范围和 `requires_confirmation` 与 `deny / ask / allow` 结合；在确认 UI 接通前，需要确认的工具默认拒绝。

## 2026-10-27：P03-02 安全示例工具

### 需求

按照 `docs/DEVELOPMENT_REQUIREMENTS.md` 和最新 `AGENTS.md` 完成 P03-02：实现 `current_time` 与计算器；计算器必须使用受限解析，不能执行任意 Python 代码。保持阶段边界，不提前把独立 handler 描述成统一工具执行器或模型工具循环。

### 实际完成内容

- 新增 `yanagent/tools/examples.py`，实现 `current_time_info()` 与异步 `current_time_handler()`。工具按需读取本机时间，返回日期、时间、中文星期、UTC 偏移和 ISO 8601 的严格 JSON 文本，不访问网络或用户私有数据。
- 时间辅助函数支持注入带时区的固定 `datetime`，让星期和偏移测试与真实时钟、测试机器地区解耦；无参数 handler 对未知字段明确失败，不静默忽略模型输入。
- 实现 `calculate_expression()` 与异步 `calculator_handler()`。表达式先由 `ast.parse(mode="eval")` 解析，再由自有递归函数对白名单节点求值；没有使用 `eval / exec / compile / shell`。
- 计算器仅允许整数、有限小数、括号、加减乘除、整除、取余、有限次幂和单目正负号；拒绝名称、调用、导入、属性、下标、容器、布尔值、复数、位运算、比较及条件表达式。
- 增加表达式 256 字符、64 个 AST 节点、16 层求值深度、指数绝对值 100、结果绝对值 `10^100` 五类上限，避免把“没有任意代码执行”误当成“不会被资源滥用”。
- handler 防御性校验精确参数集合：时间工具必须为空对象，计算器必须且只能包含字符串 `expression`；统一 JSON Schema 验证仍按计划留给 P03-03。
- 新增 `current_time_definition()`、`calculator_definition()`、`safe_example_definitions()` 和 `register_safe_example_tools()`。两个工具均标记为低风险、全局范围、并行安全且无需确认，统一经过 P03-01 `ToolManager` 注册和 Schema 导出。
- 关键路径增加包含文件名和函数名的中文日志；计算器日志只记录表达式长度、拒绝原因和结果类型，不回显完整表达式。
- 参考 CowAgentByYan 把准确时间放在按需工具而非长期 Prompt 的产品边界；计算器采用 YanAgent 自己的 AST 白名单设计，没有引入参考项目的插件、执行器或文件/进程能力。
- 新增 `docs/P03_02_SAFE_TOOLS.md`，同步 README、需求文档 v1.9、路线图、P03-01 后续状态和岗位映射；P03-02 标记完成，下一项为 P03-03。

### 涉及文件

- 安全示例工具：`yanagent/tools/examples.py`
- 工具公开接口：`yanagent/tools/__init__.py`
- 自动化测试：`tests/test_safe_tools.py`
- 实现说明：`docs/P03_02_SAFE_TOOLS.md`
- 状态与导航：`README.md`、`docs/DEVELOPMENT_REQUIREMENTS.md`、`docs/IMPLEMENTATION_ROADMAP.md`、`docs/P03_01_TOOL_REGISTRY.md`、`docs/P02_04_DESKTOP_SESSIONS.md`、`docs/P02_05_ISOLATION_RECOVERY.md`、`docs/TARGET_ROLES.md`
- 开发记录：`workProcess.md`

### 验证结果

- P03-02 新增 11 项测试：固定时间、时间 JSON、无参数边界、运算正确性、结果格式、不使用 `eval`、危险语法拒绝、资源限制、参数精确性、安全元数据和统一注册均通过。
- 通过实际替换 `builtins.eval` 为抛错函数后计算 `(2 + 3) * 4`，结果仍为 20，证明正常计算路径不依赖 Python `eval`。
- `__import__('os').system(...)`、`open(...)`、变量、属性、下标、列表、位移、布尔值、除零、复数、巨大指数和非有限浮点等输入均得到受控 `SafeToolError`，没有执行副作用。
- `register_safe_example_tools()` 注册后名称稳定为 `calculator / current_time`，模型 Schema 继续封闭未知字段，内部风险元数据不混入 Provider Schema。
- `tests.test_safe_tools + tests.test_tool_registry` 共 22 项定向测试通过。
- `python -m compileall`、全量 159 项回归和 `git diff --check` 在最终代码与文档更新后通过。

### 开发难点与评分

整体难度：**7/10**。难点不是四则运算本身，而是确保解析器没有代码执行入口，同时限制合法但可能消耗大量 CPU/内存的数学表达式，并保持 P03-02 与后续统一执行、权限阶段的边界。

| 难点 | 难度 | 容易出现的问题 | 实现方式与证据 |
|---|---:|---|---|
| 受限解析而非代码执行 | 8/10 | 直接 `eval` 可访问导入、文件、对象属性；简单字符串替换容易绕过 | `ast.parse(mode="eval")` 只解析，递归求值仅接收 Constant、指定 BinOp/UnaryOp；危险语法矩阵和禁用 `eval` 测试验证 |
| 资源滥用边界 | 7/10 | `2**超大指数`、超长或超深表达式虽不是任意代码，也可能耗尽资源 | 在求值前后限制字符、节点、深度、指数和数值绝对值；巨大指数、复杂表达式和非有限结果测试验证 |
| 工具本体与统一执行器分层 | 6/10 | handler 可调用后误称工具循环已完成；或把 P03-03 的所有校验提前写进单个工具 | handler 只做必要防御和业务计算，注册定义可供 Provider 使用；`ToolManager.execute()` 仍显式未实现，文档列出 ToolResult/超时/截断边界 |
| 时间与测试确定性 | 5/10 | 测试依赖当前秒数和机器时区，跨机器不稳定；Prompt 中固定时钟会过期 | 时间按需读取；辅助函数允许注入 aware datetime；固定 +08:00 用例验证中文星期、偏移和 ISO 8601 |

### 岗位要求关联与实践证据

- **小米职责1、职责3和职责6（Agent 链路、Tooling、安全稳定性）**：两个真实工具通过统一定义和注册表暴露，计算器具备代码执行隔离与资源上限；当前没有接入 MCP、企业系统、权限 UI 或操作系统 Sandbox。
- **字节质量 Agent 职责2～3（多工具调用、执行管控、可复用框架）**：工具本体与定义分离、统一注册、稳定 Schema 和恶意输入测试属于可复用 Tooling 基础；没有完成模型多工具编排、结果汇总或质量业务工作流。
- **腾讯职责1～2及要求1～2/4（执行引擎、Tool Use、Python 与工具描述）**：用 Python AST 实现白名单解释器，并为模型提供清晰的能力/限制描述；尚未完成统一执行引擎、Planning、Reflection 或 ToolResult 生命周期。
- **Verification Loop 实践**：先列出允许/拒绝语法和资源上限，再用 11 项行为测试验证，且全量回归保持通过；这是确定性工程验证，不等于 Agent 自主验证、修复和重试闭环。

### 面试可讲事实与边界

- 可以表述：为 Agent 实现低风险时间和计算工具；计算器不使用 `eval`，而是 AST 白名单解释，并对表达式规模、递归深度、指数和结果范围施加限制。
- 可以表述：将工具业务 handler、模型 Schema 和内部安全元数据分层，通过注册表统一暴露；用恶意表达式矩阵和禁用 `eval` 测试证明代码执行路径被封闭。
- 可以表述：参考开源 Agent 将实时信息做成按需工具，避免在长期 Prompt 中写入会过期的时钟，并用可注入时间保证测试确定性。
- 不可以表述：模型已经能自动调用工具、所有 JSON Schema 已统一校验、错误已转换为 ToolResult、权限/确认/超时/截断已完成，或计算器等同操作系统 Sandbox。这些属于 P03-03～P04 或更强隔离层。

### 后续事项

- 下一项严格执行 P03-03：把 `ToolCall` 接到注册表 handler，统一校验必填、类型和未知字段，处理未知工具、损坏参数、超时、异常和输出截断，并始终返回关联原 `tool_call_id` 的 `ToolResult`。
- P03-04 再实现 `deny / ask / allow` 和作用范围；尚未接入确认 UI 时，需要确认的操作默认拒绝。
- P04 才把模型工具请求、Assistant 原始调用消息、Tool Result 和下一轮模型请求组成真正 Agent Loop。

## 2026-10-28：P03-03 参数校验与统一工具结果

### 需求

按照 `docs/DEVELOPMENT_REQUIREMENTS.md` 和最新 `AGENTS.md` 完成 P03-03：校验工具必填参数、类型与未知字段，处理损坏参数和未知工具；通过 `ToolManager` 统一生成 `ToolResult`，处理单工具超时、handler 异常、返回类型和大输出截断。保持阶段边界，不把最小失败关闭闸门描述为完整权限系统，也不提前实现模型工具循环。

### 实际完成内容

- 新增 `yanagent/tools/validation.py`，实现显式 JSON Schema 子集：object、array、string、integer、number、boolean、null，以及 required、additionalProperties、enum、长度、数组数量和数值范围约束。
- 参数类型严格匹配 JSON 语义，不把 bool 当作 integer/number；对象必填和未知字段在 handler 前检查；嵌套 Schema 最多校验 32 层，内部矛盾约束被识别为工具定义错误，而不是用户参数错误。
- 参数校验成功后深复制再传给 handler，阻止工具修改后续需要持久化的原始 `ToolCall.arguments`。
- 将 `ToolManager.execute()` 从占位实现替换为完整单调用执行链：验证 ToolCall、最小权限闸门、查找工具、校验参数、限时等待 handler、检查字符串结果、截断输出并生成结构化 `ToolResult`。
- 成功、参数失败、未知工具、超时、受控失败、未知异常、错误返回类型和截断结果均保留原 `tool_call_id`；未知异常正文和模型原始参数不会写入结果或日志。
- 新增 `ToolHandlerError`，内部 handler 只有显式使用该类型时才能向模型提供最多 500 字且无控制字符的公开错误；其他异常只返回固定“工具执行失败”。P03-02 `SafeToolError` 改为其子类。
- `ToolManager` 默认单工具超时 30 秒、输出上限 20000 字符；超时允许 0～600 秒，输出允许 64～1000000 字符。大结果保留头部，并在总上限内追加原始字符数截断标记。
- `asyncio.CancelledError` 不被普通异常分支吞掉，外层取消继续传播；协作式超时会取消 handler。文档明确事件循环阻塞或吞取消的 handler 无法被 Python 强制终止，阻塞工具必须另做线程/进程和底层期限。
- 在 P03-04 完成前实施最小失败关闭：只有 `allow` 进入 handler，`deny / ask / 非法模式` 都不执行。尚未消费 risk、scope、requires_confirmation，也没有确认请求 ID，因此没有标记 P03-04 完成。
- 删除 P03-01 中“execute 必须保持未实现”的过期测试，新增 13 项执行测试；同步 README、需求文档 v1.10、路线图、P03 前序说明和岗位映射，下一项更新为 P03-04。

### 涉及文件

- 工具执行与定义：`yanagent/tools/manager.py`
- 参数校验：`yanagent/tools/validation.py`
- 安全示例错误基类接入：`yanagent/tools/examples.py`
- 工具公开接口：`yanagent/tools/__init__.py`
- 自动化测试：`tests/test_tool_execution.py`、`tests/test_tool_registry.py`
- 实现说明：`docs/P03_03_TOOL_EXECUTION.md`
- 状态与导航：`README.md`、`docs/DEVELOPMENT_REQUIREMENTS.md`、`docs/IMPLEMENTATION_ROADMAP.md`、`docs/P03_01_TOOL_REGISTRY.md`、`docs/P03_02_SAFE_TOOLS.md`、`docs/P02_04_DESKTOP_SESSIONS.md`、`docs/P02_05_ISOLATION_RECOVERY.md`、`docs/TARGET_ROLES.md`
- 开发记录：`workProcess.md`

### 验证结果

- P03-03 新增 13 项执行测试：成功关联调用 ID、参数前置拒绝、嵌套 Schema、参数副本、未知工具、最小权限闸门、超时、受控/未知异常、错误返回类型、截断、取消传播和配置边界全部通过。
- 损坏 JSON 正常路径继续由 Provider 严格解析器拒绝；测试还绕过 `ToolCall` 构造校验模拟损坏对象进入执行边界，执行器再次校验并返回关联 `call-1` 的结构化失败，handler 执行次数保持 0。
- 超时测试让 handler 等待 10 秒、管理器期限设为 0.01 秒，结果为超时失败且 handler 的 finally 收到取消；外层任务取消测试确认 `CancelledError` 继续传播。
- 异常测试依次触发受控错误、含敏感占位正文的 RuntimeError 和成功；未知异常正文未进入 ToolResult，第三次调用仍返回 `recovered`，证明单次工具失败不使管理器失效。
- 200 字符输出在 80 字符配置下被截断，结果包含“工具输出已截断”和原始字符数 200，最终内容长度不超过 80。
- P03-01～P03-03 当前 34 项工具专项测试通过；全量 171 项测试通过。本机最终完整回归运行 9.711 秒，该单次耗时不作为性能结论。
- `python -m compileall` 与 `git diff --check` 在最终代码和文档更新后通过；敏感值扫描未发现实际密钥或凭据。

### 开发难点与评分

整体难度：**8/10**。难点在于把模型提供的不可信参数、内部 Schema、异步生命周期和可持久化结果分层：失败必须发生在副作用前，异常不能泄露内部正文，超时不能吞掉外层取消，大输出又必须留下可解释的截断证据。

| 难点 | 难度 | 容易出现的问题 | 实现方式与证据 |
|---|---:|---|---|
| 参数与副作用顺序 | 8/10 | 缺失/未知/错误类型仍进入 handler，产生文件或网络副作用；handler 修改原 ToolCall 破坏历史 | 统一 Schema 前置校验，成功后深复制；四类坏参数和嵌套修改测试证明 handler 未执行/原参数不变 |
| 异步超时与取消语义 | 8/10 | 把外层取消转成普通失败；超时后误称所有代码都已强制停止；阻塞事件循环使期限失效 | `wait_for` 管理协作式 handler，Timeout 转结构化失败，CancelledError 向上传播；两类测试及限制文档验证 |
| 安全错误与可诊断性 | 7/10 | 将异常正文、模型参数或凭据回显给模型/日志；全部固定错误又难以定位 | ToolHandlerError 只允许受控短文本；未知异常只记类型，日志保留文件/函数、call_id、tool 和 reason 分类；连续失败后成功测试验证服务继续 |
| 输出截断一致性 | 7/10 | 直接切片没有标记，模型误以为内容完整；追加标记后超过配置上限 | 先计算含原始字符数的标记，再按剩余空间取头部；80 字符上限测试验证标记与总长度 |
| Schema 支持边界 | 7/10 | 声称完整 JSON Schema 却漏掉组合、引用和 pattern；bool 被 Python 当作 int | 明确实现受控子集并递归校验常用类型/约束，严格 type 比较；文档列出能力，不宣称完整标准实现 |

### 岗位要求关联与实践证据

- **小米职责1、职责3、职责6～7（Agent 链路、Tooling、安全稳定性和可维护性）**：形成从不可信 ToolCall 到结构化结果的统一执行边界，包含副作用前校验、超时、取消、异常脱敏和截断；没有企业系统/MCP 接入、生产压测或 OS Sandbox。
- **字节质量 Agent 职责2～3（多工具编排、执行管控、调试与评测）**：统一 Schema、结果和失败分类为后续多工具编排提供执行管控基础，34 项工具回归提供可复现证据；没有模型多轮编排、测试生成/评审业务流或效果评测。
- **腾讯职责1～3及要求1～2/6（工具执行引擎、Tool Use、质量保障、系统思维）**：用 Python 实现递归参数验证、异步超时和安全错误边界，并验证取消传播与连续服务；尚未完成 Planning、Reflection、完整权限、Agent Loop 或系统 Benchmark。
- **Verification Loop 实践**：从缺失/未知/类型/损坏参数到超时、异常、截断、取消建立失败矩阵，修复测试中发现的 ToolCall 构造期校验差异后复跑专项与全量；这是工程验证回路，不等于 Agent 自主修复闭环。

### 面试可讲事实与边界

- 可以表述：为自研 Agent Runtime 实现统一工具执行器，在 handler 副作用前做递归 Schema 校验，并用深复制保护模型原始调用；成功和失败都关联 tool_call_id。
- 可以表述：将受控业务失败与未知异常分开，未知异常不回显正文；实现单工具超时、外层取消传播、返回类型校验和带原始长度的有界截断。
- 可以表述：通过损坏参数、未知工具、嵌套类型、超时取消、连续异常恢复和大输出测试验证执行器边界，并明确异步协作取消不等于强制杀死阻塞代码。
- 不可以表述：已完成完整 JSON Schema、ask 确认 UI、细粒度 scope/risk 权限、模型自动选工具、多工具并发、聊天工具卡片或 OS 级 Sandbox。这些属于 P03-04～P04 或更强隔离层。

### 后续事项

- 下一项严格执行 P03-04：定义 `deny / ask / allow` 的完整语义，结合 risk、scope 与 requires_confirmation，增加确认请求 ID 和批准/拒绝结果；确认 UI 未接通前 ask 默认拒绝。
- P03-05 接通工具列表接口，并对 P03 阶段重复注册、非法参数、权限拒绝、超时和执行失败做综合接口验收。
- P04 才将工具 Schema 注入模型请求，保存 Assistant 原始工具调用和 Tool Result，并驱动下一轮模型直到最终文本。

## 2026-10-28：P03-04 工具权限基础

### 需求

按照 `docs/DEVELOPMENT_REQUIREMENTS.md` 和最新 `AGENTS.md` 完成 P03-04：定义 `deny / ask / allow` 的确切语义，限制工具可用作用域，为确认流程定义请求 ID 和批准/拒绝结果；桌面确认 UI 尚未接入时，所有需确认操作必须默认拒绝。权限拒绝必须发生在 handler 副作用之前，并保持 P03-04 与 P03-05 工具列表、P04 模型工具循环的阶段边界。

### 实际完成内容

- 新增 `yanagent/tools/permissions.py`，将权限决策从 `ToolManager` 的临时字符串判断拆成无副作用策略函数和显式数据契约：`ToolPermissionContext`、`ToolPermissionDecision`、`ToolConfirmationRequest`、`ToolConfirmationResult`。
- 明确三种模式：`deny` 无条件拒绝且不能被确认覆盖；`ask` 每次调用都要求显式确认；`allow` 只自动放行低风险且未标记 `requires_confirmation` 的工具，中高风险或显式确认工具仍进入确认流程。非法模式失败关闭。
- `ToolPermissionContext.allowed_scopes` 默认只包含 `global`。授权 `user` 必须绑定 `user_id`，授权 `agent` 必须绑定 `user_id + agent_id`，授权 `session` 必须绑定 `user_id + agent_id + session_id`，授权 `workspace` 必须绑定工作区标识；缺少边界时上下文构造直接失败。
- 作用域判断消费 P03-01 的 `scope` 元数据。批准结果只能满足确认条件，不能越过 `deny`、未授权 scope、参数校验或未知工具；默认上下文不会意外开放用户、Agent、Session 或工作区工具。
- 确认请求 ID 使用 `confirm_` 加 32 位 SHA-256 摘要，规范输入绑定 `run_id`、用户/Agent/Session/工作区、`tool_call_id`、工具名、完整参数以及风险/范围元数据。相同调用 ID 稳定，任一关键输入变化都会得到不同 ID。
- 确认结果使用精确枚举 `approved / rejected`，不接受含糊布尔或任意字符串。ID 不匹配、用户拒绝、确认界面不可用、缺少 run 上下文都返回固定安全失败说明。
- `ToolManager.execute()` 新增可选权限上下文与确认结果；参数通过后再决策，handler 只在 `allowed` 结论下运行。所有拒绝仍生成关联原 `tool_call_id` 的 `ToolResult(is_error=True)`。
- 批准结果在 `ToolManager` 内通过线程锁原子消费，阻止并发或重试对同一确认结果重复产生副作用。已消费集合上限为 10000；容量满后默认拒绝，不通过淘汰旧记录重新允许重放。
- 默认 `confirmation_ui_available=False`。因此当前桌面不会弹出确认框，`ask` 以及 `allow` 下的中高风险/显式确认工具都会默认拒绝；测试只用可信构造上下文模拟未来 UI 往返，不把协议测试描述为桌面功能已完成。
- 参考 CowAgentByYan 权限策略中“未知能力失败关闭”“作用域检查不是 OS Sandbox”的边界，但没有复制其 `read-only / workspace-write / full-access` 命令解析器。YanAgent 当前先实现工具目录级的 `deny / ask / allow` 和身份 scope，文件/命令参数级路径策略按 P06 建设。
- 新增 `docs/P03_04_PERMISSION_FOUNDATION.md`，同步 README、需求文档 v1.11、路线图、P03 前序状态、P02 后续状态和岗位映射；P03-04 标记完成，下一项更新为 P03-05。

### 涉及文件

- 权限契约与策略：`yanagent/tools/permissions.py`
- 统一执行入口：`yanagent/tools/manager.py`
- 工具公开接口：`yanagent/tools/__init__.py`
- 自动化测试：`tests/test_tool_permissions.py`、`tests/test_tool_execution.py`
- 实现说明：`docs/P03_04_PERMISSION_FOUNDATION.md`
- 状态与导航：`README.md`、`docs/DEVELOPMENT_REQUIREMENTS.md`、`docs/IMPLEMENTATION_ROADMAP.md`、`docs/P03_01_TOOL_REGISTRY.md`、`docs/P03_02_SAFE_TOOLS.md`、`docs/P03_03_TOOL_EXECUTION.md`、`docs/P02_04_DESKTOP_SESSIONS.md`、`docs/P02_05_ISOLATION_RECOVERY.md`、`docs/TARGET_ROLES.md`
- 开发记录：`workProcess.md`

### 验证结果

- 新增 11 项 P03-04 测试：作用域身份约束、完整上下文规范化、三模式语义、中高风险/显式确认、scope 拒绝、确认 ID 稳定与参数绑定、批准/拒绝、跨 Run 挪用拒绝、handler 前失败、一次性批准消费和 Session 归属放行均通过。
- 权限与统一执行定向共 24 项测试通过；其中 `deny / ask / allow` 拒绝用例的 handler 执行次数为 0，批准重放用例第一次成功、第二次失败，最终执行次数为 1。
- P03 工具专项测试由 34 项增至 45 项；全量 `unittest discover` 共 182 项通过，最终单次回归耗时 9.957 秒。该耗时只记录本机本次运行，不作为性能或吞吐结论。
- `python -m compileall -q yanagent tests` 通过。Windows 异步测试在受限沙箱内创建事件循环本机 socket 时发生等待，改在获准的本机环境运行后立即通过；这是测试执行环境限制，不是权限代码死锁。
- `git diff --check`、敏感值扫描和最终工作区检查通过；没有引入真实 API Key、凭据或外部网络调用。

### 开发难点与评分

整体难度：**8/10**。难点不是写三个 `if`，而是避免“批准”成为万能绕过：需要同时绑定运行、身份、工具、参数和安全元数据，明确 scope 与资源 ACL 的边界，并保证并发重放时最多一个执行进入 handler。

| 难点 | 难度 | 容易出现的问题 | 实现方式与证据 |
|---|---:|---|---|
| 三模式与风险组合 | 7/10 | 把 `allow` 解释为中高风险全自动；把 `ask` 当普通失败而没有可关联请求 | 明确模式表；medium/high 与显式确认在 allow 下仍确认；纯决策测试覆盖三模式和三类确认触发 |
| 确认结果防挪用 | 9/10 | 只绑定工具名，批准后参数或 Session 被替换；跨 Run 复用批准 | 规范 JSON 指纹同时绑定运行、身份、调用 ID、参数和安全元数据；参数变化与跨 Run 测试验证 ID 不同/拒绝 |
| 并发与重放 | 8/10 | 两个协程同时消费同一批准，产生两次外部副作用；无限记录造成内存增长 | 锁内检查并消费 ID；重放测试执行次数为 1；固定容量满后失败关闭 |
| scope 语义与 Sandbox 边界 | 8/10 | 仅有 `scope="session"` 就误认为已校验归属；把工作区分类冒充路径或 OS 隔离 | 每类 scope 要求可信身份字段；默认只开放 global；文档明确目录级能力边界不替代路径检查/容器 |
| 未接 UI 的安全退化 | 6/10 | 为方便联调把 ask 静默当 allow，导致生产环境无按钮却执行敏感操作 | 默认 UI 不可用；所有确认型调用返回固定拒绝，只有显式可信上下文和匹配批准才能执行 |

### 岗位要求关联与实践证据

- **小米职责3、职责6～7（Tooling、Sandbox 边界、安全稳定性与可维护性）**：实现风险、作用域、确认协议和 handler 前失败关闭，明确目录级策略不是 OS Sandbox；没有容器隔离、命令/文件完整 ACL、企业系统或 MCP 授权。
- **字节质量 Agent 职责2～3（多工具执行管控、调试与评测框架）**：权限结论、确认 ID 和结构化失败为后续工具编排提供可测试管控点，45 项工具回归形成确定性证据；没有模型多工具规划、质量业务流或效果评测。
- **腾讯职责1～3及要求2/6（工具执行引擎、Tool Use、质量保障和系统思维）**：将工具元数据、运行身份和执行入口组合成失败关闭权限层，并验证重放/越权/异常路径；尚未完成 Agent Loop、Planning、Reflection 或 Benchmark。
- **开源机制拆解实践**：对照 CowAgent 权限策略的模式、工具分类和“参数级检查不是硬沙箱”说明，选择适合 YanAgent 阶段的显式上下文与确认协议；这不等于完成 CowAgent 全部命令策略或使用 LangGraph/AutoGen 等框架。
- **Verification Loop 实践**：先列出越权、无 UI、跨 Run、参数替换和确认重放失败矩阵，再用纯决策与真实 handler 计数测试验证；这是权限工程验证回路，不等于 Agent 自主修复闭环。

### 面试可讲事实与边界

- 可以表述：为自研 Agent Runtime 设计三模式工具权限层，低风险工具和需确认工具采用不同路径，并以可信身份上下文限制 global/user/agent/session/workspace 范围。
- 可以表述：确认请求 ID 绑定运行、身份、工具调用和参数，批准结果原子一次性消费；通过跨 Run 挪用和重放测试证明拒绝发生在 handler 副作用前。
- 可以表述：参考开源 Agent 的权限策略后，明确区分工具目录级授权、参数级资源 ACL 与 OS Sandbox，避免把字符串 scope 夸大为硬隔离。
- 不可以表述：桌面已经有确认弹窗、模型已经会自动调用工具、工作区文件路径已被完整隔离、已有容器 Sandbox、HTTP 工具列表或 P03 全阶段接口联调。这些属于 P03-05、P04 和 P06。

### 后续事项

- 下一项严格执行 P03-05：接通工具列表接口，并综合覆盖重复注册、非法参数、权限拒绝、超时和执行失败。
- P04 将模型工具调用、权限决策、handler 结果和下一轮模型请求组成真实 Agent Loop；届时需决定确认事件如何进入流式事件协议。
- P06 文件与命令工具必须在 scope 之外继续实现规范路径、工作区根检查、危险参数拒绝和更强隔离，不能把当前 `workspace` 标签直接视为安全沙箱。

## 2026-10-28：P03-05 工具列表接口与阶段综合验收

### 需求

按照 `docs/DEVELOPMENT_REQUIREMENTS.md` 和最新 `AGENTS.md` 完成 P03-05：接通桌面工具列表，并综合覆盖重复注册、非法参数、权限拒绝、超时和执行失败。完成后对 P03 阶段做整体验收，但不提前实现 P04 的模型工具循环或旁路 HTTP 工具执行接口。

### 实际完成内容

- 在 `YanAgentApplication` 中注入应用级 `ToolManager`。生产缺省路径创建独立注册表并注册 P03-02 的 `calculator` 与 `current_time`；测试和未来独立 Agent 可以显式注入自己的注册表。
- 显式注入注册表时严格保留调用方实例，包括空注册表，不会因为“没有工具”而自动补入默认定义，避免测试、不同 Agent 或未来受限运行环境被静默扩大能力。
- 新增 `YanAgentApplication.tools_payload()`，从线程安全目录快照生成桌面接口负载。仅导出 `name + description`，不暴露 handler、参数 Schema、风险、scope、确认对象或任何配置凭据。
- 将 `GET /api/tools` 从固定 `{"tools": []}` 占位响应改为真实应用目录。返回顺序继承 `ToolManager.catalog()` 的名称排序，结果每次独立生成，调用方修改响应不会污染注册表。
- 保持目录与授权分层：工具出现在能力页只表示已经注册，不表示当前请求得到执行授权。实际调用仍必须通过 P03-03 参数校验和 P03-04 模式、作用域、风险及确认检查。
- 刻意没有增加 `POST /api/tools/execute`。P04 的身份、历史、Assistant 工具调用消息和模型后续轮次尚未接好时开放任意执行端点会形成绕过 Agent Loop 的旁路。
- 新增 P03 综合验收：同名注册拒绝且不覆盖；坏参数与 `deny` 的 handler 执行次数为 0；计算器返回 `20` 并关联原调用 ID；慢工具得到结构化超时；未知异常不泄露正文，下一次调用仍成功。
- 对照 CowAgentByYan `/api/tools` 的桌面契约，只复用 `name + description` 的产品接口形状；YanAgent 目录来自显式注册表快照，没有复制参考项目的动态类扫描、插件加载或 MCP 工具发现。
- 新增 `docs/P03_05_TOOL_INTERFACE.md`，同步 README、需求文档 v1.12、路线图、P02/P03 后续状态和岗位映射；P03 全阶段标记完成，下一项更新为 P04-01。

### 涉及文件

- 应用级注册表和目录负载：`yanagent/chat.py`
- 桌面 HTTP 接口与启动日志：`app.py`
- 自动化测试：`tests/test_tool_interface.py`
- 实现与验收说明：`docs/P03_05_TOOL_INTERFACE.md`
- 状态与导航：`README.md`、`docs/DEVELOPMENT_REQUIREMENTS.md`、`docs/IMPLEMENTATION_ROADMAP.md`、`docs/P02_04_DESKTOP_SESSIONS.md`、`docs/P02_05_ISOLATION_RECOVERY.md`、`docs/P03_01_TOOL_REGISTRY.md`、`docs/P03_02_SAFE_TOOLS.md`、`docs/P03_03_TOOL_EXECUTION.md`、`docs/P03_04_PERMISSION_FOUNDATION.md`、`docs/TARGET_ROLES.md`
- 开发记录：`workProcess.md`

### 验证结果

- 新增 5 项 P03-05 测试：默认真实目录、显式空目录隔离、真实回环 `/api/tools`、重复注册/执行前拒绝、计算成功/超时/异常恢复全部通过。
- 回环 HTTP 响应稳定返回 `calculator / current_time`，每项仅包含 `name / description`；旧的空数组占位已被真实注册结果替换。
- 综合拒绝测试中，缺少必填参数与 `deny` 均返回失败 `ToolResult`，handler 执行次数保持 0；重复注册抛出 `ToolAlreadyRegisteredError`。
- 综合执行测试中，`calculator-1` 返回 `20`；慢 handler 返回超时；未知 `RuntimeError` 正文没有进入结果；同一管理器下一次调用返回 `recovered`。
- P03 工具专项测试由 45 项增至 50 项；全量 187 项自动化测试通过，最终单次回归耗时 12.920 秒。该耗时只记录本机本次运行，不作为性能结论。
- 桌面 `npm run build` 通过：Vite 完成 2152 个模块转换，主进程 TypeScript 编译通过。构建保留既有字体运行时解析、Browserslist 数据过期、混合动态/静态导入和大 chunk 警告，本次没有把既有警告误报为新增错误。
- Python 编译、`git diff --check`、敏感值扫描和最终工作区核对通过；本阶段没有外部网络请求或真实凭据。

### 开发难点与评分

整体难度：**6/10**。接口代码本身很短，主要难点是选择正确生命周期和公开边界：注册表必须与应用共享而不是每次 GET 临时创建，目录又不能成为绕过权限或 Agent Loop 的执行入口。

| 难点 | 难度 | 容易出现的问题 | 实现方式与证据 |
|---|---:|---|---|
| 注册表生命周期 | 7/10 | 每次请求新建管理器导致动态注册丢失；使用全局可变单例导致测试/Agent 相互污染 | 由 `YanAgentApplication` 持有并支持构造注入；默认与注入空目录测试验证两条路径 |
| 目录与执行授权分层 | 7/10 | 页面能看到工具就被误认为有权执行；为了联调增加无身份 POST 执行端点 | GET 仅列注册目录，执行仍走 ToolManager 权限；文档明确未提供旁路执行接口 |
| API 信息最小化 | 5/10 | 把 handler、参数、风险或确认内部对象直接序列化给桌面；响应被修改反向污染注册表 | 显式选择 name/description，并基于 catalog 快照重建；字段集合和污染隔离测试验证 |
| 阶段综合验收 | 6/10 | 各专项测试单独通过，但组合入口中参数、权限、超时或异常顺序改变 | 使用一个真实 ToolManager 连续覆盖成功、前置拒绝、超时、未知异常和后续恢复 |

### 岗位要求关联与实践证据

- **小米职责1/3/6～7（Agent Runtime、Tooling、安全稳定性和可维护性）**：完成应用级工具发现接口和统一执行失败矩阵，证明工具目录与授权层分离；没有企业工具、MCP、容器 Sandbox 或生产负载指标。
- **字节质量 Agent 职责2～3（工具执行管控、调试和可复用框架）**：通过真实 HTTP 与结构化失败矩阵验证注册、校验、权限、超时和恢复能够协同工作；没有质量业务工作流、自动生成测试、代码评审 Agent 或效果评测。
- **腾讯职责1～3及要求1～2/6（工具执行引擎、Tool Use、Python 和质量保障）**：形成从应用目录到统一执行器的稳定接口并保留 50 项工具测试；尚未完成模型工具选择、多轮 Agent Loop、Planning 或 Reflection。
- **开源机制拆解实践**：对照 CowAgent 工具页接口选择兼容的最小响应形状，同时保留 YanAgent 显式 ToolDefinition/ToolManager 架构；不等于复制或完成参考项目的插件与 MCP 工具生态。
- **Verification Loop 实践**：将注册、发现、成功、前置拒绝、超时、未知失败和恢复组成可复现的阶段验收；这是工程验证闭环，不等于模型自主发现并修复缺陷。

### 面试可讲事实与边界

- 可以表述：为自研 Agent Runtime 建立应用级工具注册表和桌面发现接口，目录按名称稳定输出并只暴露必要展示字段。
- 可以表述：用真实回环 HTTP 和综合失败矩阵验证重复注册、参数、权限、超时、异常脱敏及失败后恢复，P03 共保留 50 项工具测试。
- 可以表述：把“工具可发现”和“工具获准执行”分层，避免工具管理页面或无身份 HTTP 接口绕过 Runtime 权限。
- 不可以表述：模型已经自动选择并调用工具、桌面已经显示工具执行卡片/确认弹窗、已接入 MCP/企业系统、文件和命令工具已经具备 OS Sandbox。这些属于 P04、P06 和 P08。

### 后续事项

- 下一项严格执行 P04-01：在统一上下文中加入身份、系统规则、工具使用说明、历史和当前输入，并保持内部消息格式供应商无关。
- P04-02 才使用 Fake Provider 接通 `模型 → 工具 → 模型` 非流式循环，保存 Assistant 原始工具调用和对应 Tool Result。
- P04-04/P04-05 再处理流式工具事件、桌面工具卡片和持久化还原；确认 UI 仍需单独接入可信确认结果。

## 2026-10-28：能力页空白修复

### 需求

修复桌面点击“能力”后整页白屏的问题，不扩展 MCP 配置功能范围。

### 实际完成内容

- 将 `GET /api/mcp/servers` 的空集合从对象 `{}` 修正为数组 `[]`，与桌面 `McpServersResult.servers` 契约保持一致。
- 保留 `/api/tools` 和 `/api/skills` 现有行为；本次只修正能力页并行加载时的数据形状错误。
- 增加真实回环 HTTP 回归测试，防止空 MCP 配置再次返回对象并触发前端 `servers.some(...)` 运行时异常。

### 涉及文件

- HTTP 接口：`app.py`
- 自动化测试：`tests/test_tool_interface.py`
- 开发记录：`workProcess.md`

### 验证结果

- `tests.test_tool_interface` 共 6 项测试通过，包含新增的空 MCP 列表真实回环 HTTP 回归测试；本机单次运行耗时 1.153 秒。
- 原有 `/api/tools` 目录、注册隔离、权限拒绝、超时和异常恢复测试继续通过，本次修复未影响工具目录与执行链路。

### 开发难点与评分

整体难度：**1/10**。问题是明确的接口数据形状不一致；关键是通过真实 HTTP 测试固定 `servers` 必须为数组，而不是只修改一行后依赖人工点击验证。

### 尚未完成事项

- 本次不实现 MCP 服务器的新增、保存、测试和运行管理；这里只修复当前空配置占位响应。

## 2026-10-28：P04-01 Prompt 与上下文组装

### 需求

按照 `docs/DEVELOPMENT_REQUIREMENTS.md` 和最新 `AGENTS.md` 完成 P04-01：模型请求中加入可信身份、系统规则、工具使用说明、完整历史和当前输入，继续使用供应商无关的内部 `Message` 格式，并让普通与 SSE 流式入口使用同一上下文契约。本次不提前实现 P04-02 的工具执行循环。

### 实际完成内容

- 新增 `PromptContextBuilder`，将运行时身份、固定系统规则、工具说明、完整持久化历史和当前 User 输入稳定组装为 `System → 历史 → 当前 User`。System Message 只进入本轮模型请求，不写入 `messages` 表。
- 新增不可变的 `RuntimeIdentity` 与 `ModelContext`。身份包含 `user_id / agent_id / session_id / request_id`，拒绝空值、超长值和控制字符；有 SessionStore 时身份从受信作用域取得，不接受用户正文覆盖。
- 系统规则明确事实约束、凭据脱敏、回复语言、工具使用边界和运行时职责：模型只能选择本轮真实提供的工具，必须使用原生 ToolCall，缺少真实 Tool Result 时不得声称已经执行。
- 复用统一 `Message` 契约复制历史和当前输入；模型请求前验证对话顺序及 Assistant ToolCall 与 Tool Result 的调用 ID 配对，拒绝持久化 System 注入和未完成工具轮次。
- 从应用级 `ToolManager` 取得真实模型 Schema，并复制为本轮快照。工具重名、字段不完整、参数顶层不是对象或非标准 JSON 会失败关闭；没有工具时显式发送空列表。
- 普通 `provider.complete(...)` 与流式 `provider.stream(...)` 现在都接收同一组 `context.messages / context.tools`，避免普通链路有 Prompt、流式链路仍使用旧格式。
- 保留阶段边界：模型返回 ToolCall 时现有聊天入口仍抛出 `UnexpectedToolCallError`，不会假装工具已执行；真正的 `模型 → 工具 → 模型` 循环和 Assistant/Tool 消息回写留给 P04-02。
- 修正测试 Echo Provider 对“首条一定是 User”的旧假设，改为读取最后一条当前 User 消息；否则新增 System Prompt 后会把长提示词逐字符流式回显并导致测试超时。
- 新增 `docs/P04_01_PROMPT_CONTEXT.md`，同步 README、实施路线、需求文档 v1.13、P02/P03 后续状态和岗位映射。

### 涉及文件

- Prompt、身份与上下文快照：`yanagent/context.py`
- 应用组装入口和普通 Provider 参数：`yanagent/chat.py`
- SSE 流式 Provider 参数：`yanagent/runtime/streaming.py`
- 自动化测试：`tests/test_prompt_context.py`、`tests/test_chat_history.py`、`tests/test_chat_integration.py`
- 实现说明：`docs/P04_01_PROMPT_CONTEXT.md`
- 状态与导航：`README.md`、`docs/DEVELOPMENT_REQUIREMENTS.md`、`docs/IMPLEMENTATION_ROADMAP.md`、`docs/P02_04_DESKTOP_SESSIONS.md`、`docs/P02_05_ISOLATION_RECOVERY.md`、`docs/P03_01_TOOL_REGISTRY.md`、`docs/P03_02_SAFE_TOOLS.md`、`docs/P03_03_TOOL_EXECUTION.md`、`docs/P03_04_PERMISSION_FOUNDATION.md`、`docs/P03_05_TOOL_INTERFACE.md`、`docs/TARGET_ROLES.md`
- 开发记录：`workProcess.md`

### 验证结果

- 新增 6 项 P04-01 测试：稳定顺序、四类可信身份、系统规则和工具摘要、完整工具历史配对、消息/Schema 快照隔离、空工具，以及 System 注入、未完成工具轮次、非法身份和工具重名失败路径全部通过。
- Prompt、历史和普通/流式聊天定向共 26 项测试通过；普通入口和 SSE Echo Provider 均验证首条为 System、末条为当前 User，并收到 `calculator / current_time` 的真实 Schema。
- 全量 `unittest discover` 共 194 项自动化测试通过，本机单次运行耗时 11.063 秒；Python 编译和 `git diff --check` 通过。本次只修改 Python 后端、测试和文档，没有桌面源码变化，因此未重复执行 `npm run build`。
- 本次没有外部网络请求、真实 API Key 或真实 DeepSeek 调用。既有 P01 的真实普通/流式模型证据继续保留，但不能据此宣称 P04-01 新 Prompt 已完成真实模型工具选择联调。

### 开发难点与评分

整体难度：**7/10**。核心不是拼一个字符串，而是建立模型输入与持久化历史之间的清晰边界，让身份、规则、工具 Schema 和工具调用关联在普通/流式两条路径上保持一致，同时不越过 P04-02 的执行范围。

| 难点 | 难度 | 容易出现的问题 | 实现方式与证据 |
|---|---:|---|---|
| 身份与系统规则可信边界 | 7/10 | 从用户文本提取身份导致 Prompt 注入；换行破坏固定结构；历史 System 消息覆盖运行规则 | 身份由 SessionStore/Runtime 传入并校验控制字符；持久化 System 失败关闭；非法身份与注入测试验证 |
| 持久化历史与模型上下文分层 | 8/10 | 每轮把 System Prompt 写入数据库；裁剪/改写历史污染真实记录；未完成 ToolCall 被下一条 User 掩盖 | System 只构建内存快照；历史/当前深复制；模型请求前检查完整工具配对，数据库仍保存原始业务消息 |
| 普通与流式一致性 | 7/10 | 普通调用携带工具但 SSE 仍传空列表；不同链路使用不同 Prompt 顺序 | `begin_chat()` 统一生成 `ChatContext`，两条 Provider 入口直接消费同一 messages/tools；定向 26 项测试通过 |
| 阶段边界 | 7/10 | 工具 Schema 已发送后直接在聊天入口临时执行，绕过权限、持久化和循环限制；或把 ToolCall 当普通文本 | 本次只开放模型选择能力，ToolCall 明确报错；P04-02 再统一接 ToolManager 和消息回写 |
| 旧测试隐含假设 | 6/10 | Echo Provider 固定读取第一条消息，新增 System 后回显长 Prompt 并表现为 SSE 超时 | 改为读取末条当前 User；普通和流式测试同时断言 System/User 顺序及真实工具 Schema |

### 岗位要求关联与实践证据

- **小米/大模型应用方向的模型与 Prompt 接入（DYG-要求2～3、XM-职责7）**：建立供应商无关的 Prompt/Context 构建层，将身份、规则、工具描述和多轮历史统一传给 Provider，并验证普通/流式一致性；没有完成多模型路由、Prompt 效果评测或生产 A/B 指标。
- **腾讯要求4与 Tool Use 工程基础**：模型现在收到严格的函数 Schema 和工具使用协议，为后续 ToolCall 提供稳定输入；本阶段没有执行工具、Planning、Reflection 或真实模型工具联调。
- **字节质量 Agent 职责2的上下文构造基础**：保持完整工具请求/结果关联，拒绝半轮历史和 System 注入，并用快照隔离防止 Provider 污染仓储数据；没有质量业务知识注入、自动测试生成或评测平台。
- **Skills 方向的可扩展点**：Context Builder 已形成统一系统信息入口，后续 P07 可以按优先级注入 Skill 指令；当前没有实现 SKILL.md 发现、解析、触发或版本管理，不能表述为 Skills 已接入。
- **Verification Loop 实践**：将顺序、身份、Schema、工具配对、普通/流式一致性和失败路径固化为确定性测试；这是上下文契约验证，不等于模型自主修复或线上效果评测。

### 面试可讲事实与边界

- 可以表述：为自研 Agent Runtime 设计独立 Prompt/Context Builder，把可信身份、系统规则、完整历史、当前输入和工具 Schema 组装成统一内部消息，并供普通与流式 Provider 复用。
- 可以表述：区分数据库完整历史与单次模型上下文，System Prompt 不落库，消息和 Schema 使用快照，工具调用历史必须按 ID 完整配对后才允许发起下一轮模型请求。
- 可以表述：通过 6 项新增和 26 项定向测试验证 Prompt 注入拒绝、非法身份、工具重名、空工具和两条调用链一致性。
- 不可以表述：模型已经能执行工具、桌面已经展示工具卡片、P04-01 新 Prompt 已完成真实 DeepSeek 工具选择验收、已有 Token 裁剪/摘要、Skills 或 MCP 注入。这些属于 P04-02～P04-05、P05、P07 和 P08。

### 后续事项

- 下一项严格执行 P04-02：先使用 Fake Provider 完成非流式 `模型 → 工具 → 模型`，保存 Assistant 原始 ToolCall 与对应 Tool Result，并验证下一轮输入顺序。
- P04-03 再增加多调用、最大轮数、总超时和连续失败限制；P04-04/P04-05 再接流式工具事件、桌面工具卡片与持久化恢复。
- P05-04 才实现 Token 预算、完整轮次裁剪和摘要；P07～P09 再将 Skills、MCP、记忆和知识检索按可信来源注入上下文。
