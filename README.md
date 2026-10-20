# YanAgent（核心能力待实现版）

YanAgent 是从 CowAgent 的桌面产品外壳中抽出的学习脚手架。项目保留 Electron + React 界面和一个可启动的轻量 Python 后端，但有意移除了成熟 Agent 项目最关键的实现。

你的目标不是调用现成 CowAgent 代码，而是按照这里预留的接口，亲手完成一个可持续执行、能调用工具、能管理上下文、能扩展 MCP/Skills、能运行多 Agent 的 Agent Runtime。

## 当前能做什么

- 启动 Python 骨架服务并通过 `/api/health` 健康检查。
- 启动 CowAgent 风格的 Electron/React 桌面界面。
- 在聊天框发送消息后，得到“Agent Runtime 尚未实现”的固定提示。
- 阅读各核心模块的接口、TODO 和验收条件，逐步替换占位实现。

## 已移除的核心实现

| 模块 | 入口 | 当前状态 |
|---|---|---|
| Agent 执行循环 | `yanagent/runtime/agent_loop.py` | 接口保留，实现为空 |
| 运行时调度 Bridge | `yanagent/runtime/bridge.py` | 接口保留，实现为空 |
| Session 与上下文 | `yanagent/sessions/store.py` | 接口保留，实现为空 |
| 模型适配层 | `yanagent/models/provider.py` | 接口保留，实现为空 |
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

1. 完成 `ModelProvider`，先实现一次普通非流式 LLM 调用。
2. 完成 `SessionStore`，使用 SQLite 保存消息和恢复历史。
3. 完成 `ToolManager`，实现工具注册、Schema、参数校验和执行。
4. 完成 `AgentLoop`，实现 `LLM -> tool call -> tool result -> LLM` 循环。
5. 完成流式事件协议，并把 `/message` 从固定提示接到 AgentLoop。
6. 完成 `AgentBridge`，解决 Session、Agent、模型、运行任务之间的路由与隔离。
7. 增加上下文裁剪、摘要、取消、超时、失败重试与 Token 统计。
8. 再开发 Memory、MCP、Skills、Multi-Agent 等差异化能力。

更细的任务拆分和验收标准见 [docs/IMPLEMENTATION_ROADMAP.md](docs/IMPLEMENTATION_ROADMAP.md)。

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
