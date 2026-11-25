# P06-02：响应差异统一

完成日期：2026-11-25。范围为现有 Chat Completions、Claude Messages、Gemini generateContent 三种协议的文本/函数工具差异，不包含厂商内置搜索、代码执行、图片和语音。

## 本次结果与使用方式

- 在「设置 → 基础设置」启用 Thinking 后，适配器按已声明协议发送控制参数；供应商确实返回可展示字段时，通过独立 `reasoning` SSE 事件显示在思考区域，正文仍只取答案字段。
- 已完成的公开思考内容随 Assistant 保存，刷新历史可以还原为 thinking 步骤。签名、密文和 redacted 数据只在内部协议状态中保存，桌面历史、答案和调试日志不会展示它们。
- 在「设置 → 模型 → 编辑模型目录」填写模型的上下文窗口和最大输出 Token。实际预算取用户全局上限、当前模型声明及备用链约束；恢复默认目录会清除旧的目录预算覆盖。
- 回答因输出或上下文上限结束时，桌面显示内容可能不完整的提示。只有思考而没有答案、且已经耗尽上限时，返回 `model_output_limit`，不把它当成普通空响应补请求。
- Token 展示改用统一的输入、输出、总数、缓存和推理计数，兼容旧历史字段；缺失值显示未知，不把推理子计数再加到已经包含它的总数中。

重启后端并加载新桌面构建后使用。没有修改用户真实模型配置，也没有把本地代码用于训练模型。

## 统一响应与字段边界

`ModelReply` 增加独立 `reasoning` 文本字段，默认空串且不进入对象的调试 repr；`provider_metadata` 继续存放原生续接状态。转换成 Assistant 时，两者分别进入 metadata.reasoning 与 metadata.provider_state。流式协议增加 `reasoning_delta`，Runtime 将其转换成既有桌面 `reasoning` 事件，并校验已发思考/正文与 completed 响应一致。

| 协议 | 答案来源 | 允许展示的思考来源 | 必要内部回传状态 |
|---|---|---|---|
| DeepSeek | message/delta.content | 明确 DeepSeek 协议的 reasoning_content | 同供应商、同模型的 reasoning_content |
| Qwen | message/delta.content | 明确 Qwen 协议的 reasoning_content | 若服务返回 encrypted_content，则原样回传，不解释密文 |
| OpenAI Chat | message/delta.content | 不把任意 reasoning 字段视为公开正文 | 只处理公开 Token 用量与 reasoning_effort；没有实现 Responses API 的 reasoning summary |
| Claude | text 块及 text_delta | thinking 块的 thinking 文本及 thinking_delta | 完整 thinking/signature 与 redacted_thinking 块 |
| Gemini | 非 thought 的 text part | thought=true 的 text part | 原始 parts，包括签名和函数调用，保持顺序与内容 |

不从未知厂商的任意 `reasoning`、`thinking` 或对象字段拼接答案，也不解析答案里的标签来推测内部思考。这里只转发供应商公开给客户端的内容，不恢复、推断或解密隐藏推理。是否返回可展示内容取决于具体模型和服务；开关打开不保证一定出现思考文字。

Claude 签名通过 signature_delta 拼接，签名本身不发给桌面；正文、Thinking 与工具块交错时保留完整原序，不将所有 Thinking 块搬到前面。Gemini 缺少原生函数调用 ID 时只生成内部配对 ID，不往已签名的 functionCall 中补写 ID；结果消息在原调用未提供原生 ID 时也不强加 ID。切换模型时不携带旧模型的签名，改用统一文本/工具消息重建输入。

debug_log 对 provider_state、reasoning、reasoning_content、thinking、signature 和 encrypted_content 等字段统一隐藏；原始响应和 opaque 数据不写入错误说明。已有流程日志仍可查看来源、模型、消息数、工具数、结束原因与 Usage 字段名。公开思考内容会按会话消息持久化，这不是加密存储或敏感信息自动审查功能。

## Thinking 请求策略

供应商和模型的准确选项可配置在 `provider_configs.<provider>.model_options.<model>` 中：

```json
{
  "provider_configs": {
    "claude": {
      "model_options": {
        "your-model-id": {
          "context_window": 200000,
          "max_output_tokens": 8192,
          "thinking_protocol": "claude-adaptive"
        }
      }
    }
  }
}
```

示例数值只是展示配置格式，不是对任意模型容量的声明。模型 ID、窗口和支持的思考模式应依据实际供应商文档设置。

| thinking_protocol | 请求控制 |
|---|---|
| none | 不启用对应思考控制/公开展示，保留已收到的必要原生续接状态 |
| deepseek | thinking.type=enabled/disabled |
| qwen | enable_thinking；历史有密文时增加 preserve_thinking |
| openai | 已启用时发送 reasoning_effort；Chat 接口不承诺思考正文 |
| claude-enabled | thinking.type=enabled、budget_tokens；预算至少 1024 且小于有效输出上限 |
| claude-adaptive | thinking.type=adaptive 与 output_config.effort |
| gemini-budget | thinkingConfig.includeThoughts 与 thinkingBudget |
| gemini-level | thinkingConfig.includeThoughts 与 thinkingLevel |

可选 thinking_budget 为正整数，原生请求还验证其协议约束。low/medium/high effort 从既有 `reasoning_effort_by_model` 的 `供应商:小写模型名` 键读取。未配置时使用相应协议默认值；不自动发送其他未实现厂商参数。

默认依据明确的供应商及少量模型族：通用兼容入口只有 DeepSeek/Qwen 名称前缀会启用对应字段，未知兼容服务默认 none；OpenAI 的已知推理模型族使用 openai；Claude 4.6 的两个明确型号族选 adaptive，其余默认手动预算；Gemini 2.5 选 budget，其余默认 level。新型号或代理服务不保证符合默认判断，应通过 thinking_protocol 明确覆盖，或设为 none。关闭 Gemini 的公开展示不保证所有型号停止内部推理：只有已知允许零预算的 2.5 Flash 系列会明确发送零预算。

## 结束原因与工具安全

| 内部原因 | 代表来源 | 行为 |
|---|---|---|
| stop | OpenAI stop、Claude end_turn/stop_sequence、Gemini STOP | 完成普通答案 |
| tool_calls | OpenAI tool_calls、Claude tool_use、Gemini STOP 且有 functionCall | 参数完整、结构正确后交给既有工具权限与执行链路 |
| length | OpenAI length、Claude max_tokens、Gemini MAX_TOKENS | 保留已有文本并提示截断；无正文则明确报输出上限错误 |
| context_length | Claude model_context_window_exceeded | 保留已有文本并提示上下文截断；无正文则明确报错 |

拒答/安全过滤转换为既有 model_refusal，不能借备用链绕过。缺失或未知结束原因、Claude pause_turn（尚未支持服务端工具）、Gemini MALFORMED_FUNCTION_CALL 等不作为成功答案。工具请求与结束原因必须匹配，即使截断时参数恰好仍是合法 JSON，也不能执行。完整终止后不接受额外的正文/工具增量；只允许明确的 Usage 尾帧。Claude message_stop 后立即关闭流，Gemini 必须看到候选结束原因。

已经发出公开思考增量也算向用户产生输出，发生故障后禁止自动换模型或重放，以免拼接两套回答。必要的已知错误 Usage 在流中断转换时继续传到执行记录；无法获知的服务端消耗保持未知。

## Token 口径

- OpenAI/DeepSeek/Qwen：prompt_tokens→input_tokens、completion_tokens→output_tokens、total_tokens 原样保留。缓存命中/未命中、prompt_tokens_details.cached_tokens 与 completion_tokens_details.reasoning_tokens 分别映射为子计数。推理与缓存已经包含在相应总量中，不重复加总。
- Claude：原生 input_tokens 不含 cache_read_input_tokens 和 cache_creation_input_tokens，因此内部 input_tokens 为三项之和；另保留缓存读取、创建子计数。output_tokens 取供应商累计值，total_tokens 为已知输入与输出之和。
- Gemini：promptTokenCount 已包含缓存；内部 output_tokens 为已知 candidatesTokenCount 加 thoughtsTokenCount，推理另列子计数；totalTokenCount 以供应商返回为准，工具提示 Token 单独保留，不再重复加到已报告总数。
- 缺失字段不补零，显式 null 与零区别保留；非法负数、布尔、字符串和小数计数拒绝。OpenAI/Gemini 未报告 total 时不推算一个看似精确的总数。
- 流式用量帧视为累计快照，采用最新字段，不能把每帧再求和。任务级仍按各次模型调用累计。这里只记录 Token，不计算厂商价格或实际账单。

## 模型窗口与上下文预算

模型目录支持 context_window、max_output_tokens，用户高级选项另支持 thinking_protocol、thinking_budget。目录和旧字符串列表保持兼容；预算验证拒绝非法类型，恢复预设会移除旧的窗口/输出覆盖，但保留手工思考协议选项。

窗口取全局用户上限与模型声明的较小值；全局设置为 0 时采用已声明模型窗口，未知模型继续保守使用 64000。输出预算同时受全局 max_output_tokens、模型输出声明和窗口四分之一上限约束。没有把内置型号示例误当成实时厂商容量数据库。

聊天准备、自动摘要判断、手动压缩用量、普通/流式循环使用同一解析函数；开启备用链时预先考虑候选的最小窗口。各 Provider 请求使用自己的有效输出上限。必要的 provider_state 序列化数据也计入保守估算，避免 Thinking/签名回传被当成零成本。该估算可能偏大，不等于厂商 tokenizer、精确计费或官方计数接口；服务端 token-count API 尚未接入。

## 验证与边界

- 新增 19 项 P06-02 专项，全量 275 项离线测试通过。覆盖三种 Token 口径、公开字段开关、完整/流式 Thinking、交错签名/密文续接、未知/截断结束、停止后多余帧、备用禁止重放、自动窗口、目录重置、日志隐藏及真实后台循环/SQLite 历史还原。
- 2026-11-25 使用现有 openai-compatible/deepseek-flash 配置，跑通非流式 calculator 请求、本地一次计算和第二轮流式答案。两次已知总 Token 为 413、436；第二轮识别缓存命中 256。只发送 1+1 问题，没有项目内容或聊天历史。当前服务本次返回 reasoning_tokens=0，没有真实 Thinking 正文样本，不能宣称真实思考展示已验收。
- Renderer 构建、Python compileall、git diff --check 通过。TypeScript 仍只报告原有 ChannelsPage 图标类型及重复 user_seq；未报告本次新增类型错误。没有启动 Electron 做界面点击验收。
- Claude、Gemini、Qwen、OpenAI 官方缺少凭据，原生和厂商专属行为用离线协议帧验证；DeepSeek 官方直连也未验证。尚未覆盖任意代理的私有字段、所有未来型号、Responses API、原生服务端工具、多模态和外部计费系统。
- 中断前尚未完成的思考增量保留在本次内存事件流中；本项没有增加每个增量的跨重启持久化。已完成 Assistant 的公开思考和必要协议状态可持久化。

## 参考依据

参考 CowAgentByYan HEAD `1fa66340` 的 `agent/protocol/agent_stream.py` 中公开思考事件、缓存用量、Gemini 签名与窗口预留处理，以及 `channel/web/core/providers.py` 的目录配置。保留 YanAgent 的统一数据契约和权限/执行边界，没有复制其整套运行循环。

官方依据：[DeepSeek Thinking 与回传](https://api-docs.deepseek.com/guides/thinking_mode/)、[Qwen Thinking](https://help.aliyun.com/en/model-studio/deep-thinking)、[Qwen 摘要和密文](https://help.aliyun.com/en/model-studio/cot-summary)、[Claude Thinking](https://platform.claude.com/docs/en/build-with-claude/extended-thinking)、[Claude 结束原因](https://platform.claude.com/docs/en/build-with-claude/handling-stop-reasons)、[Gemini 响应与 Token 字段](https://ai.google.dev/api/generate-content)、[OpenAI Reasoning](https://platform.openai.com/docs/guides/reasoning)。接口公开字段随服务更新，以实际模型和请求格式为准。
