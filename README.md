# YanAgent（核心能力待实现版）

YanAgent 是从 CowAgent 的桌面产品外壳中抽出的学习脚手架。项目保留 Electron + React 界面和一个可启动的轻量 Python 后端，但有意移除了成熟 Agent 项目最关键的实现。

你的目标不是调用现成 CowAgent 代码，而是按照这里预留的接口，亲手完成一个可持续执行、能调用工具、能管理上下文、能扩展 MCP/Skills、能运行多 Agent 的 Agent Runtime。

## 当前能做什么

- 启动 Python 骨架服务并通过 `/api/health` 健康检查。
- 启动 CowAgent 风格的 Electron/React 桌面界面。
- 配置 OpenAI-compatible 模型后，在聊天框发送消息并流式显示真实回答，也可停止生成。
- 启动后自动初始化独立的 `~/.yanagent/yanagent.db` 和 Schema v2。
- 后端已能创建、分页、重命名、置顶和删除会话，并以事务保存完整消息历史。
- 普通与流式聊天会自动落库；同一 Session 的下一轮模型调用会携带先前完整历史。
- 桌面会话列表、历史分页、用户消息时间线、重命名、置顶、删除和重新生成已接到 SQLite。
- 阅读各核心模块的接口、TODO 和验收条件，逐步替换占位实现。
- 使用 Python 普通/流式 Provider 或离线 Fake Provider；配置、SSE、取消和错误已接到桌面 HTTP 契约。

## 已移除的核心实现

| 模块 | 入口 | 当前状态 |
|---|---|---|
| Agent 执行循环 | `yanagent/runtime/agent_loop.py` | 接口保留，实现为空 |
| 运行时调度 Bridge | `yanagent/runtime/bridge.py` | 接口保留，实现为空 |
| Session 与上下文 | `yanagent/storage/`、`yanagent/sessions/`、`yanagent/chat.py` | P02-04 已完成聊天落库、重启恢复、完整历史输入和桌面会话管理；隔离恢复待 P02-05 |
| 模型适配层 | `yanagent/models/openai_compatible.py`、`yanagent/chat.py` | P01-05 已接通普通与流式桌面消息、增量组装和安全错误 |
| 最小流式 Runtime | `yanagent/runtime/streaming.py`、`yanagent/events.py`、`app.py` | 常驻事件循环、Run 隔离、SSE 回放、基本取消与终态清理已完成 |
| 工具系统 | `yanagent/tools/manager.py` | 接口保留，实现为空 |
| 长期记忆 | `yanagent/memory/service.py` | 接口保留，实现为空 |
| MCP Client | `yanagent/mcp/client.py` | 接口保留，实现为空 |
| Skills | `yanagent/skills/loader.py` | 接口保留，实现为空 |
| Multi-Agent | `yanagent/multi_agent/coordinator.py` | 接口保留，实现为空 |
| 多渠道接入 | 未复制 | 需要后续自行设计 |

原项目的 `agent/`、`bridge/`、`models/`、`channel/`、`plugins/`、`skills/` 等后端实现均没有复制进来，因此无法通过改一个 import 偷用原实现。

## 从源码启动

### 只启动后端骨架

项目当前已经创建了本地 `.venv`。如果以后换电脑或删除了它，请先用任意可用的 Python 3.10+ 重建：

```powershell
python -m venv .venv
```

本机的系统 `python` 命令若仍指向 Windows Store 占位程序，可以改用现有 Anaconda：

```powershell
& "D:\AAADownload\pAnaconda\install_path\python.exe" -m venv .venv
```

启动后端：

```powershell
cd C:\Users\1\Documents\ChatGPT\langgraph\code\YanAgent
.\.venv\Scripts\python.exe app.py
```

浏览器访问 `http://127.0.0.1:9876/api/health`，应得到 JSON 健康状态。

可通过环境变量改变端口：

```powershell
$env:YAN_WEB_PORT = "9899"
.\.venv\Scripts\python.exe app.py
```

### 启动桌面端

第一次运行先安装前端依赖：

```powershell
cd C:\Users\1\Documents\ChatGPT\langgraph\code\YanAgent\desktop
npm install
npm run dev
```

桌面端会自动从上一级目录启动 `app.py`。已有 `node_modules` 时，后续只需要执行 `npm run dev`。

## 推荐开发顺序

以 [开发需求与实施计划](docs/DEVELOPMENT_REQUIREMENTS.md) 为后续开发的主要依据，按任务编号逐项推进。

1. P01：统一数据结构、配置、单模型调用与桌面流式聊天。
2. P02：Session 持久化、多轮历史与会话管理。
3. P03：最小工具系统与权限基础。
4. P04：模型与工具循环执行的 Agent Loop。
5. P05：Bridge 调度、上下文管理、取消与运行稳定性。
6. P06～P10：多模型、完整工具、Skills、MCP、记忆知识库和 Multi-Agent。
7. P11～P12：Web、多渠道、定时、桌面交付与功能对照验收。

P01-01～P01-06、P02-01～P02-04 均已完成。P01 阶段验收见 [P01 验证与文档](docs/P01_06_VERIFICATION.md)；P02 实现见 [数据库基础](docs/P02_01_DATABASE.md)、[会话与消息存储](docs/P02_02_SESSION_STORE.md)、[历史与上下文接通](docs/P02_03_HISTORY_CONTEXT.md)和[桌面会话联调](docs/P02_04_DESKTOP_SESSIONS.md)。当前共 130 项测试通过，下一项任务是 **P02-05：隔离与恢复**；Token 预算和工具循环仍分别属于 P05、P03～P04。

可在项目根目录运行本次配置演示（使用无效测试密钥，不请求网络）：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m examples.config_demo
.\.venv\Scripts\python.exe -X utf8 -m examples.provider_demo
.\.venv\Scripts\python.exe -X utf8 -W error -m scripts.verify_p01_real_api
```

阶段导航见 [实施路线摘要](docs/IMPLEMENTATION_ROADMAP.md)，每次需求的实际开发记录追加到 [workProcess.md](workProcess.md)。

求职参考见 [目标岗位与开发成果映射](docs/TARGET_ROLES.md)。技术实现以 CowAgentByYan 为依据；后续需求与岗位要求重合时，在开发记录详细沉淀实现、设计取舍和验证证据。

## 验证骨架

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall app.py yanagent
```

前端验证：

```powershell
cd desktop
npm run build
```

## 与 CowAgent 的关系

桌面界面来自 CowAgent，遵循仓库中的 MIT License。YanAgent 的 Python Agent 核心不是 CowAgent 实现的改名副本，而是专门为重新实现而准备的空骨架。
