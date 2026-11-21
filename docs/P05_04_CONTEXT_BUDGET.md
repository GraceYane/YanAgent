# P05-04 上下文预算

状态：已实现，行为验证待补

## 本项交付

- `AppConfig` 支持上下文窗口上限、最多历史轮数和 Agent 模型轮数配置。上下文窗口为 0 时使用本地默认估算窗口 64,000 Token。
- 新增统一上下文用量估算：分列系统提示、工具 Schema、历史消息、摘要记忆和输出预留。界面从 `/api/sessions/{id}/context_usage` 查询用量，显示估算标记及各部分占用。
- 新聊天在组装上下文时，超过预算或历史轮数上限后优先压缩被移除的旧完整轮次；摘要成功则把摘要作为历史参考加入系统提示，保留完整 Session 消息用于回看。摘要失败时记录错误并对本次模型输入裁剪旧轮次，不破坏已有消息。
- 每轮模型调用前，AgentLoop 再按当前上下文和工具 Schema 预算裁剪最旧的完整轮次，保持 Assistant 工具调用与 Tool Result 配对。裁剪只影响传给模型的快照，不删除持久化历史。
- 执行工具前按本轮剩余预算计算结果字符上限。预算不足以保存最小结果时跳过工具，避免执行后无空间回写；其余结果使用既有截断标记。
- 提供手动摘要较早历史、清空模型上下文边界和桌面用量展示。清空操作不删除时间线中的历史消息；上下文边界与摘要存于 Session 元数据。
- 自动摘要模型用量并入后续 AgentLoop Run 累计用量；手动摘要的模型用量当前不关联到已有 Run。

## 估算与边界

- 当前用 UTF-8 字节数近似 Token 数并加 8% 余量，不调用特定模型 Tokenizer，中文、英文、代码和厂商分词差异可能造成偏差。界面明确标记为估算。
- 64,000 是本地默认值，不代表服务端模型真实上下文窗口；用户可在设置中调整窗口和最大历史轮数。Provider 请求目前没有统一的最大输出 Token 字段，输出预算在 YanAgent 本地作为输入裁剪与工具结果截断依据。
- 工具处理器仍可能先生成较大的字符串，当前预算在结果回写前截断，不能限制工具内部的峰值内存。后续工具接口可按字节流或分页返回来进一步控制。
- 摘要通过当前配置的模型生成；不可用、超时或空输出时自动路径退回到当前请求的完整轮次裁剪。历史原文仍保留，因此清空和压缩不构成历史删除。
- 用量是持久化上下文快照的启发式估算，不包含供应商隐藏模板、服务端工具协议开销或模型 tokenizer 的实际计数。

## 接口与文件

- `GET /api/sessions/{session_id}/context_usage`：返回窗口、输入预算、预留输出、估算用量与拆分。
- `POST /api/sessions/{session_id}/clear_context`：设置新的模型上下文起点，保留历史记录。
- `POST /api/sessions/{session_id}/compact_context`：摘要较早完整轮次，保留最近两轮及全部持久化历史。
- 核心实现见 `yanagent/context.py`、`yanagent/chat.py`、`yanagent/runtime/agent_loop.py`、`yanagent/sessions/store.py` 和 `yanagent/tools/manager.py`；HTTP 路由在 `app.py`，桌面显示在 `desktop/src/renderer/src/components/ContextUsagePopover.tsx`。

## 验证情况

本次应运行 Python 静态编译、桌面 Renderer 构建（若依赖可用）与 `git diff --check`；不以这些静态检查替代行为测试。尚需行为验证自动摘要成功/失败、摘要边界持久化、清空后重新对话、工具结果预算及 Assistant/Tool 配对、配置边界、身份隔离和桌面接口兼容性。

## 岗位要求关联

关联 `docs/TARGET_ROLES.md` 的“Session、上下文和数据隔离”及“性能与 Token 成本”。当前实现给出上下文裁剪、摘要和用量估算的工程路径；没有真实 tokenizer 计数、成本基线或压缩率/延迟测量，不能据此声称 Token 成本已经下降。
