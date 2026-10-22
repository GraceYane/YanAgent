# P01-06 验证与阶段验收

日期：2026-10-22  
状态：已完成

## 1. 验收范围

P01-06 不再增加新的聊天架构，而是把 P01-01～P01-05 已实现的配置、Provider、Runtime、HTTP/SSE 和桌面链路放到同一套验收中，验证：

- 配置完整性、密钥脱敏和安全错误；
- 非流式与流式模型调用；
- 缺少密钥、错误密钥、无效模型、超时、限流和空响应；
- 桌面停止生成到后端取消的链路；
- 两条并发请求的 request_id、增量和最终结果隔离；
- 真实外部模型与桌面端显示。

P01 仍只处理当前一条用户消息。多轮上下文、历史持久化和重启恢复属于 P02；工具执行循环属于 P03～P04。

## 2. 新增验收工具

真实 API 验证脚本：

```powershell
cd C:\Users\1\Documents\ChatGPT\langgraph\code\YanAgent
.\.venv\Scripts\python.exe -X utf8 -W error -m scripts.verify_p01_real_api
```

脚本从已被 Git 忽略的本地 `config.json` 或 `YAN_*` 环境变量读取配置，依次执行一次非流式和一次流式请求。输出只包含 Provider、API 主机、模型、超时、耗时、增量数、模型回答和 Usage；不会输出 API Key、Authorization 头或配置文件原文。失败时只输出统一错误码与安全中文说明。

## 3. 自动化验证矩阵

| 验收项 | 验证方式 | 结果 |
|---|---|---|
| 配置、环境覆盖、原子保存、密钥脱敏 | `tests/test_config.py` | 通过 |
| 非流式请求和响应转换 | Provider 单元测试、真实回环 HTTP | 通过 |
| 流式文本、工具参数和完成响应 | Provider 单元测试、真实回环 SSE | 通过 |
| 错误密钥 | 回环 HTTP 401、SSE 安全错误事件 | `authentication_error` |
| 无效模型/API 路径 | 回环 HTTP 404、SSE 安全错误事件 | `model_not_found` |
| 限流 | 回环 HTTP 429、SSE 安全错误事件 | `rate_limit` |
| 超时 | 受控 Provider/传输超时、SSE 安全错误事件 | `model_timeout` |
| 空响应 | 正常结束但无文本/工具的真实回环 SSE | `empty_model_response` |
| 缺少密钥 | 配置校验和 SSE 安全错误事件 | `configuration_error` |
| 停止生成 | 阻塞 Provider + 真实 `/message`、`/stream`、`/cancel` | Provider 收到取消；客户端收到 `cancelled + done` |
| 两请求隔离 | 两条并发真实回环 HTTP/SSE，逐字符交错 | 两个 request_id、增量和 done 均不串流 |
| 敏感信息保护 | 响应/日志断言；上游错误正文含测试秘密 | HTTP/SSE 与异常均不回显 |

全量命令：

```powershell
.\.venv\Scripts\python.exe -X utf8 -W error -m unittest discover -s tests -q
.\.venv\Scripts\python.exe -X utf8 -W error -m compileall -q -f app.py yanagent tests examples scripts
cd desktop
npm run build
```

结果：100 项 Python 测试通过，Python 编译检查通过，Vite renderer 与 TypeScript main 生产构建通过。构建仍显示项目已有的字体文件、Browserslist、动态/静态 import 和大 chunk 提示，这些不是 P01-06 新增失败。

## 4. 真实 DeepSeek 验收记录

本地配置：OpenAI-compatible、`api.deepseek.com`、`deepseek-flash`、60 秒超时。模型名与地址按 [DeepSeek 官方首次调用文档](https://api-docs.deepseek.com/quick_start/agent_integrations/) 核对；凭据没有写入源码、测试、本文或终端输出。

2026-10-21 运行 `scripts.verify_p01_real_api`：

| 模式 | 回答 | 耗时 | 增量 | Usage |
|---|---|---:|---:|---|
| 非流式 | `普通调用通过` | 1.999 秒 | 1 | input 45 / output 53 / total 98 |
| 流式 | `流式调用通过` | 1.144 秒 | 4 | input 46 / output 51 / total 97 |

这些是一次开发机实测，不代表生产延迟、吞吐或成本承诺。

## 5. 真实桌面验收记录

2026-10-22 从源码启动 Electron 桌面端，由桌面进程启动当前 `app.py`：

1. 输入“这是 YanAgent P01 桌面验收。请只回复：桌面流式通过”。
2. 用户消息立即进入聊天时间线，生成阶段显示等待气泡和停止按钮。
3. DeepSeek 增量结束后，Assistant 气泡显示“桌面流式通过”，输入框和发送按钮恢复可用。
4. 再发送长输出请求，生成阶段停止按钮可见且可点击，点击后界面最终恢复发送状态。

第 4 步的 DeepSeek 输出完成很快，人工截图无法单独证明外部 socket 恰好在完成前被关闭。因此取消的后台证据来自确定性的阻塞 Provider 真实 HTTP 测试：`POST /cancel` 返回取消数量 1，Provider 的 `finally` 收到取消，SSE 以 `cancelled + done(finish_reason=cancelled)` 有限结束。这里明确区分“桌面交互已观察”和“后台取消由受控自动化证明”，不把竞态写成虚假外部结论。

## 6. 阶段结论与边界

P01 的单模型聊天链路已完成：桌面任务接入、配置快照、OpenAI-compatible 普通/流式调用、统一响应、SSE 回写、可识别错误、基本取消和并发 Run 隔离均有证据。

当前不能据此声称具备多轮 Session、持久化、工具执行、Agent Loop、MCP、Skills、Memory、Multi-Agent、Sandbox、云端 Runtime 或生产级 SLA。下一阶段是 P02-01：建立 SQLite 数据库基础、Schema 版本和核心表。
