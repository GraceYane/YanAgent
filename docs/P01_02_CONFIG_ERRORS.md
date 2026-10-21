# P01-02：配置与统一错误

状态：已完成并通过离线验收。日期：2026-10-21。

本次交付独立的配置读写模块和统一错误分类。P01-03 才实现模型请求；P01-04 才将配置和模型接口接到桌面端。因此当前运行 `npm run dev` 仍然只能得到骨架回复，不能用真实聊天验收本任务。

## 1. 文件与调用关系

| 文件 | 作用 |
|---|---|
| `yanagent/config/settings.py` | `AppConfig` 字段校验、`ConfigStore` 读取/保存/环境覆盖 |
| `yanagent/config/__init__.py` | 导出配置模块公共入口 |
| `yanagent/errors.py` | 统一异常、稳定错误码、HTTP 状态映射 |
| `config.example.json` | 不含凭据的配置模板 |
| `tests/test_config.py`、`tests/test_errors.py` | 26 项新增离线行为测试 |
| `examples/config_demo.py` | 可直接运行的配置与错误演示 |

```text
内置默认值 → 合法文件配置 → 非空环境变量覆盖 → AppConfig 生效快照
                                                   ↓
                                  require_model_ready() 检查完整性
                                                   ↓
                                      后续 P01-03 的 Provider

局部更新 → 合并文件值（不混入环境值）→ 校验文件及生效配置
        → 同目录临时文件 → flush/fsync → 原子替换 → 返回生效快照
```

## 2. 配置字段

| 文件字段 | 环境变量 | 默认值与规则 |
|---|---|---|
| `model_provider` | `YAN_MODEL_PROVIDER` | `openai-compatible`；本阶段仅接受这一种协议标识，不代表已实现 Provider |
| `api_base` | `YAN_API_BASE` | 空字符串；非空时要求 HTTP(S) 地址，可用本地服务；禁止 URL 用户名/密码、查询串和片段 |
| `model` | `YAN_MODEL` | 空字符串；非空时为供应商模型标识，不预设远端模型清单 |
| `api_key` | `YAN_API_KEY` | 空字符串；隐藏打印；全星号占位符不能作为真实密钥 |
| `request_timeout` | `YAN_REQUEST_TIMEOUT` | 60 秒；数值且 `0 < 值 <= 3600`；拒绝布尔值、NaN、Infinity |
| `host` | `YAN_WEB_HOST` | `127.0.0.1`；非空，无空白及 URL 路径等分隔符 |
| `port` | `YAN_WEB_PORT` | 9876；整数，范围 1～65535；拒绝布尔值 |
| `permission_mode` | `YAN_PERMISSION_MODE` | `ask`；允许 `deny / ask / allow`，只是保留配置字段，执行权限在 P03 实现 |

字段名沿用骨架中的 `model_provider` 等命名。文本不允许首尾空白、控制字符和无效 Unicode 代理字符。文件中的数字必须使用 JSON 数字；环境变量中的端口、超时分别显式解析为整数、浮点数。

`request_timeout` 是后续单次模型请求的超时设置，不是整个 Agent Run 的时限；当前配置模块本身不会执行请求或计时。

## 3. 路径与覆盖优先级

配置路径优先级：

1. `ConfigStore(path=...)` 的显式路径。
2. 非空的 `YAN_CONFIG_PATH` 环境变量。
3. YanAgent 项目根目录的 `config.json`，根据模块位置确定，不跟随启动工作目录变化。

相对自定义路径相对于创建 `ConfigStore` 时的工作目录解析。路径的父目录需要已存在；保存不会自行创建目录。

配置值优先级为：**非空环境变量 > 文件 > 默认值**。只读取表中的专属变量，不读取 CowAgent 配置、`COW_DATA_DIR` 或通用的 `OPENAI_API_KEY`。

- 环境变量值为精确空字符串 `""` 时视为未覆盖，兼容部署时的空占位；不能用它清除文件密钥。
- 文件值和最终生效值均需合法。环境变量不能掩盖坏文件；非法环境覆盖报错，不静默回退。
- `ConfigStore` 创建时复制环境。修改进程环境后需重新创建实例；文件则每次 `load/save` 都重新读取。
- 文件不存在时只返回默认值，不自动落盘；文件损坏、重复字段、未知字段时明确报错，不自动替换为模板。
- UTF-8 与 UTF-8 BOM 文件均可读取，保存统一使用 UTF-8。

这里是 P01 的独立模型配置路径；P02 的数据库/数据目录和 P12 的安装包路径仍需按阶段实现。`app.py` 旧骨架中的端口逻辑尚未改接本模块，不能把配置模块的路径规则理解为桌面端已接通。

## 4. Python 使用方式

```python
from yanagent.config import ConfigStore
from yanagent.errors import ConfigurationError

store = ConfigStore()
try:
    config = store.load()
    print(config.to_dict())  # API Key 已完全隐藏
    config.require_model_ready()  # 检查 Base、模型和 Key；不会请求远端
except ConfigurationError as error:
    print(error.to_dict())
```

首次可将 `config.example.json` 复制为项目根目录的 `config.json`，填写供应商提供的 API Base 和模型名。密钥可通过 `YAN_API_KEY` 注入，不必写入文件；示例中不提供真实密钥。

保存接口接受**局部更新字典**：

```python
config = store.save({"request_timeout": 30})
print(config.to_dict())
```

- 省略 `api_key`：保留文件原密钥。
- 提交新的非空密钥：替换文件密钥。
- 提交 `api_key=""`：清除文件密钥；若环境仍有密钥，生效值仍由环境提供。
- 提交 `********` 等全星号：拒绝保存。不要把 `config.to_dict()` 当成更新请求原样传回。
- 保存不会把生效快照中的环境模型、环境密钥写入文件，返回值仍是环境覆盖后的结果。
- 若文件写入或替换失败，原文件保留；不会回退为原地截断写入。临时文件尽力清理，操作系统拒绝删除时可能残留。

配置快照不可直接赋值修改。新的配置通过 `save` 后再次 `load` 或使用 `save` 的返回值获得。

## 5. 脱敏范围与保存边界

`AppConfig.to_dict()` 对任何长度的非空密钥统一显示 `********`；`repr/str(config)` 不包含 `api_key` 字段。统一错误只包含固定说明、已知字段名、错误码和可重试提示，不保存输入值、磁盘路径、响应正文或底层异常字符串。解析和 I/O 错误转换时抑制底层异常链的正常打印。

这些措施不等于加密存储。Provider 仍需通过 `config.api_key` 取得真实密钥；显式 `dataclasses.asdict(config)` 也能读取原始字段，不应写入日志。用户选择保存密钥时，文件内是明文。Windows 文件访问依赖目录 ACL，本任务不提供凭据保险库或系统沙箱。

保存使用同目录临时文件及 `os.replace`，验证了写入/替换失败时不破坏原文件。本阶段不提供跨进程写锁、并发更新合并或断电持久性保证；并发更新存在最后一次写入覆盖前次的限制。默认配置及本次临时目录模式已加入 Git 忽略规则；自定义到其他位置的配置需要使用者自行管理。

## 6. 统一错误

| 异常 / 错误码 | 来源或含义 | 可重试提示 |
|---|---|---|
| `ConfigurationError` / `configuration_error` | 配置格式、字段、读写或缺少必要值 | 否 |
| `AuthenticationError` / `authentication_error` | 上游 HTTP 401，模型服务拒绝凭据 | 否 |
| `PermissionDeniedError` / `permission_denied` | 上游 HTTP 403 | 否 |
| `ModelNotFoundError` / `model_not_found` | 上游 HTTP 404；可能是模型或 API 路径错误 | 否 |
| `InvalidRequestError` / `invalid_request` | 其他上游 HTTP 4xx | 否 |
| `RateLimitError` / `rate_limit` | 上游 HTTP 429 | 是 |
| `ModelTimeoutError` / `model_timeout` | 上游 HTTP 408 或后续传输层明确超时 | 是 |
| `ModelConnectionError` / `model_connection_error` | 后续传输层连接失败 | 是 |
| `ModelServerError` / `model_server_error` | 上游 HTTP 5xx | 是 |

`map_http_error(status_code)` 只接受 400～599 的整数错误码，不从文本猜测状态；`to_dict()` 产生可 JSON 序列化的对象。`upstream_status` 是供应商响应状态，并不是 YanAgent HTTP API 必须原样返回的状态。缺少 Key 是配置未完成；远端拒绝已配置 Key 才是认证错误。

`retryable=True` 只表达可考虑重试，当前未实现自动重试。配额不足、输出已推送或已有工具副作用时是否能重试，仍需运行时决定。连接/超时异常捕获和 HTTP 映射的真实调用点在 P01-03 接入。

## 7. 验收步骤

在 YanAgent 根目录执行，无需启动后端、Electron 或配置真实密钥：

```powershell
cd C:\Users\1\Documents\ChatGPT\langgraph\code\YanAgent
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -X utf8 -W error -m examples.config_demo
.\.venv\Scripts\python.exe -X utf8 -W error -m compileall -q -f app.py yanagent tests examples
```

2026-10-21 结果：**49 项测试通过**，其中本次新增配置测试 22 项、错误测试 4 项，原有 23 项通过。编译检查与演示通过。

演示应看到：环境模型覆盖文件模型；密钥为星号；保存超时不改变文件的模型/密钥；负超时报 `configuration_error`；模拟 HTTP 429 报 `rate_limit`；最后显示“验收通过”。所有演示密钥均为无效测试字符串，不请求网络，项目内隔离临时目录在正常退出时自动清理。

测试覆盖损坏 JSON、重复键、非法 URL/字段/环境变量、缺少 Key、脱敏回写保护、清除密钥、模拟 `fsync/replace` 失败及旧文件保留。本机系统临时目录受沙箱权限限制，测试和演示改用项目内独立临时目录，不修改系统权限。

下一项：**P01-03 非流式 Provider 与 Fake Provider**。真实 API 调用、桌面设置保存和聊天结果不属于本次已验证范围。
