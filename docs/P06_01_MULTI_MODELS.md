# P06-01：多模型与备用链

完成日期：2026-11-25。实现范围为文本对话、函数工具调用、供应商选择与备用模型；P06 整体仍在进行中。

后续更新：P06-02 已补齐公开思考、协议状态原序续接、结束原因、Token 口径与模型预算，最新行为见 [响应差异统一](P06_02_RESPONSE_NORMALIZATION.md)；下文保留本阶段完成时的验证范围。

## 使用入口

1. 在桌面「设置 → 模型」填写对应供应商的 API Key、API Base，维护模型目录。
2. 在聊天模型卡片选择全局供应商和模型。内置模型名称仅为可编辑示例，不表示账号一定可用，也不是最新模型列表；可填写服务商实际提供的模型 ID。
3. 在会话输入框的模型菜单选择当前会话模型。会话只保存供应商和模型引用，凭据仍从配置读取；选择恢复默认可回到全局配置。更改只影响之后准备的任务，已排队或执行中的任务保留自己的快照。
4. 在全局聊天模型卡片的备用模型按钮中启用备用链。默认关闭，最多四个不同的「供应商 + 模型」组合，按顺序尝试。各供应商需先配置自己的凭据；不完整的备用配置会在任务准备阶段报错。
5. 展开回答下方「执行记录与恢复」，成功模型步骤可看到实际使用的供应商、模型和此前发生的备用切换。

后端和桌面需要重新启动/构建以加载改动。本次没有代替用户修改真实凭据或全局模型选择。

## 供应商与协议

| 配置 ID | 协议 | 默认 API Base | 当前范围 |
|---|---|---|---|
| `openai-compatible` | Chat Completions | 用户填写 | 兼容原有 DeepSeek 等中转服务配置 |
| `openai` | Chat Completions | `https://api.openai.com/v1` | GPT 文本、函数工具、流式 |
| `deepseek` | Chat Completions | `https://api.deepseek.com` | DeepSeek 文本、函数工具、流式 |
| `qwen` | 兼容 Chat Completions | 用户填写 | 通义千问文本、函数工具、流式 |
| `claude` | Anthropic Messages | `https://api.anthropic.com/v1` | 原生文本、tool_use/tool_result、SSE |
| `gemini` | Google generateContent | `https://generativelanguage.googleapis.com/v1beta` | 原生文本、functionCall/functionResponse、SSE |

Qwen 的地址与账号地域、接入方式有关，故不自动填入一个固定地域的地址。通用兼容入口也保留用户原来的地址。能力声明表示适配器已实现的文本/流式/函数工具接口，不表示每个用户输入的任意模型都支持这些能力；视觉、语音和图像能力未开放。

工厂位于 `yanagent/models/factory.py`，目录位于 `catalog.py`，原生转换位于 `native.py`。前四个入口复用已有严格校验的兼容适配器；Claude 和 Gemini 使用原生协议，避免把所有供应商强行当作兼容 Chat Completions 服务。

Claude 请求将 system 单独传递，工具转换为 input_schema，结果转换为 tool_result；使用 x-api-key 和 anthropic-version。Gemini 请求将 systemInstruction、contents 和 functionDeclarations 分开，工具结果为 functionResponse；密钥只放 x-goog-api-key，不拼到 URL。原生完整响应和 SSE 均转换为已有 ModelReply / ModelStreamEvent，因此继续复用同一个 AgentLoop、权限检查与工具执行器。

Gemini 返回函数调用的 thoughtSignature 时，仅把函数调用协议状态保存在 Assistant 元数据中，下一轮原样回传。普通答案不包含 thought 文本；调试日志隐藏不透明签名，模型步骤日志只接受供应商、模型和备用切换白名单。此处是必要的协议衔接，不是完整 Thinking 展示功能。

## 配置和凭据隔离

保留旧 `model_provider / model / api_key / api_base` 字段，旧配置不需迁移；增加独立的 `provider_configs`、`chat_fallback` 和原生请求输出上限 `max_output_tokens`。以下只展示结构，不含凭据：

```json
{
  "model_provider": "openai-compatible",
  "model": "your-primary-model",
  "api_base": "https://your-gateway.example/v1",
  "api_key": "",
  "provider_configs": {
    "claude": {"api_key": "", "api_base": "https://api.anthropic.com/v1", "models": ["your-claude-model"]},
    "gemini": {"api_key": "", "models": ["your-gemini-model"]}
  },
  "chat_fallback": {"enabled": false, "chain": [{"provider": "gemini", "model": "your-gemini-model"}]},
  "max_output_tokens": 4096
}
```

- 切换供应商会选取目标供应商档案的地址和密钥，绝不继承原主供应商密钥。旧配置入口及环境变量切换也执行隔离；仅切供应商而未指定新模型时清空旧模型，要求明确选择。
- 同供应商换模型可复用该供应商凭据。清空密钥会同步清空活动档案，不会从旧档案中恢复已清除的密钥。
- 公开接口对所有嵌套密钥脱敏；脱敏占位符只表示保留原值，不能当作真实密钥保存。
- 配置保存基于文件层，环境覆盖只影响生效快照，不会把环境密钥复制到文件。原有显式 `YAN_API_KEY / YAN_API_BASE / YAN_MODEL` 环境覆盖仍有效。
- 原有配置文件本身仍保存用户配置的凭据，本项没有实现系统密钥库。

模型设置沿用 `/api/models` 的 set_provider、set_capability、save_catalog、delete_provider 动作。模型目录为内置示例加用户维护目录，支持隐藏预设；本项不提供远程自动发现和自定义供应商注册。

`GET/POST /api/sessions/{id}/settings` 返回/更新当前会话引用，provider/model 同时设为 null 表示恢复全局。会话设置存在 SQLite metadata.model_settings 下，事务合并时保留摘要和上下文状态。不能通过此接口写 API Key 或邀请其他 Agent；权限字段仅复用已有 deny/ask/allow 设置。

## 备用链的执行边界

```text
当前轮模型请求 → 主模型暂时性失败 → 备用一 → 备用二 → 返回本轮响应
                      ↑ 同一份完整上下文，包含已有 Tool Result
```

每个 Run 持有独立的链实例，位置只向后移动；一次切换后，后续模型轮次继续使用该候选，不在主备之间反复跳转。链耗尽后保留原有 P05-05 有限补请求/退避策略，所有请求和等待受 Run 总期限与取消控制。

允许切换的故障为连接失败、超时、429、5xx 和完全空响应。认证失败、权限失败、拒答、非法请求和坏响应结构不自动切换。原生 Claude SSE 的错误事件同样按类型映射，避免把认证失败一律误判为服务器故障。相同供应商切换遵守已返回的 Retry-After；跨供应商可转向独立服务。

- **尚未输出增量**：允许备用接管本轮。
- **已输出文字或工具参数**：中断并保留部分结果，不自动拼接备用答案或重放流。
- **之前轮次已经执行工具**：只重发带工具结果的模型输入，绝不重新运行之前轮次。后续模型再次请求相同写工具，仍受已有同 Run 指纹保护。
- **权限和副作用**：备用模型不能越过本地权限、确认、超时和执行日志边界。模型切换本身没有执行工具的能力。
- **用量**：空响应有明确 Usage 时跨切换/补请求累计一次；缺失服务端用量保持未知。备用内的多次请求在同一次模型步骤中合计，并附切换轨迹，尚未提供每个供应商内部尝试的独立耗时和费用分摊。

## 验证与未测范围

- 最终全量离线测试 256 项；多模型专项 20 项，包含六入口契约、两种原生工具和 SSE、凭据隔离、文件/环境切换、会话重建后恢复选择、真实本机 HTTP 设置与聊天、拒答不切换、部分流不切换、空响应用量和工具只执行一次。
- 2026-11-24 使用现有 `openai-compatible / deepseek-flash` 配置完成真实非流式及流式调用，均成功；仅发送「只回复 OK」，没有发送项目文件、聊天历史或执行工具。返回已知总 Token 分别为 46 和 42。这只证明当前接入服务的连通性，不证明 DeepSeek 官方直连接口或其他供应商账号可用。
- OpenAI 官方、DeepSeek 官方直连、Qwen、Claude 和 Gemini 没有对应凭据，真实调用未测；原生协议使用离线响应和 SSE 验证。没有在 Electron 中点击验收全部模型设置，也没有实测跨供应商限流切换。
- Renderer 生产构建通过。TypeScript 全仓检查仍报告既有 ChannelsPage.tsx 的 IconComponent/Lucide size 类型不兼容以及 types.ts 的重复 user_seq；本次新增模型功能未产生检查报告中的错误。字体引用、Browserslist 数据和 bundle 体积提示仍存在。
- Python 静态编译和 git diff --check 通过。P06-02 继续完善厂商 Thinking、Usage、终止原因和上下文窗口差异；当前预算仍使用本地估算，不声称所有模型完整能力已接入。
- P06-03～06 的工作区、文件命令、网页、多模态及产物并行尚未实施；P05 专项产品验收不会因本项回归自动通过。

## 参考依据

参考仓库 CowAgentByYan 的 `channel/web/core/providers.py` 模型设置/凭据选择以及 `tests/test_fallback_provider_credentials.py` 的备用凭据回归，检查时 HEAD 为 `1fa66340`，未修改参考仓库。设计重点是备用必须同时切换模型、地址和密钥，而不只是改模型名称。

原生及兼容协议对照官方文档：[DeepSeek 工具调用](https://api-docs.deepseek.com/guides/tool_calls/)、[Claude Messages](https://platform.claude.com/docs/en/api/messages/create)、[Claude 流式事件](https://platform.claude.com/docs/en/build-with-claude/streaming)、[Gemini 函数调用](https://ai.google.dev/gemini-api/docs/function-calling)、[Gemini generateContent](https://ai.google.dev/api/generate-content)、[Qwen 兼容接口](https://help.aliyun.com/en/model-studio/compatibility-of-openai-with-dashscope)。模型示例目录不作为厂商实时型号、价格或上下文窗口的权威来源。
