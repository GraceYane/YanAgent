# P03-01 工具注册与统一 Schema

状态：已完成  
完成日期：2026-10-23  
后续状态：P03-02～P03-04 已完成；下一项为 P03-05 测试与接口

## 1. 本阶段交付

P03-01 建立工具系统的第一层：定义“一个工具必须描述什么”、阻止同名工具互相覆盖，并把内部定义导出为现有 ModelProvider 可以接收的供应商无关 Schema。

P03-01 完成时不执行工具，`ToolManager.execute()` 当时明确抛出未实现错误；后续 P03-02 已实现时间与计算器，P03-03 已实现参数校验、超时和结果收口，P03-04 已完成权限基础。

## 2. ToolDefinition

每个工具必须提供以下字段：

| 字段 | 作用 | 当前约定 |
|---|---|---|
| `name` | 模型调用和注册表查找使用的唯一名称 | 1～64 位 ASCII 字母、数字、下划线或连字符 |
| `description` | 告诉模型何时使用工具 | 非空，最多 2000 字符 |
| `parameters` | 工具参数 JSON Schema | 顶层必须是封闭的 object Schema |
| `handler` | 后续执行时调用的异步处理函数 | 必须可调用；P03-01 不执行 |
| `risk_level` | 权限策略使用的风险级别 | `low / medium / high` |
| `parallel_safe` | 同一轮多个调用能否安全并行 | 布尔值，默认 `False` |
| `scope` | 工具可访问数据或资源的归属范围 | `global / user / agent / session / workspace` |
| `requires_confirmation` | 确认策略的显式元数据 | 布尔值；P03-04 已接入执行语义 |

风险级别定义为：`low` 表示纯计算或只读低风险能力，`medium` 为有限状态修改，`high` 为敏感或明显外部副作用。P03-04 已把它与 `deny / ask / allow` 组合；即使是 `allow`，中高风险工具仍需要确认。

作用范围表达工具设计上的数据边界，不代表用户已经获得授权：

- `global`：不依赖用户私有状态的纯能力，例如时间和计算。
- `user`：访问当前用户数据。
- `agent`：访问当前 Agent 的配置或私有数据。
- `session`：只作用于当前会话。
- `workspace`：访问当前任务绑定的工作区。

## 3. Schema 约定

参数 Schema 在构造时复制并检查：

- 只允许标准 JSON 类型，不允许循环引用、非字符串对象键、`NaN` 或 `Infinity`。
- 顶层 `type` 必须是 `object`。
- `properties` 必须是对象。
- `required` 必须是唯一的非空字符串列表，并且只能引用已声明属性。
- 顶层 `additionalProperties` 固定为 `false`；未填写时自动补齐，防止模型提交未声明字段。
- 构造、注册、读取和导出均使用独立 Schema 快照，外部修改返回值不会污染注册表。

P03-01 只验证统一工具契约使用的结构子集，不宣称实现了完整 JSON Schema 标准验证器。P03-03 会针对真实调用参数实现必填、类型、未知字段及嵌套值校验。

## 4. 注册和发现

`ToolManager` 使用线程锁保护注册表：

```text
ToolDefinition 校验并复制
            ↓
ToolManager.register
            ├─ 名称不存在 → 保存定义快照
            └─ 名称已存在 → ToolAlreadyRegisteredError，不覆盖原工具
```

即使两个线程同时注册同名工具，也只允许一个成功。`names()`、`get()`、`schemas()` 和 `catalog()` 都返回快照：

- `schemas()` 只导出 `name + description + parameters`，可以直接交给 ModelProvider。
- `catalog()` 额外包含风险、并行、范围和确认元数据，供后续权限、调度和管理接口使用。
- Schema 按工具名排序，避免注册先后改变模型请求内容和测试结果。

内部安全元数据不会发给模型；OpenAI-compatible Provider 继续在适配层把统一 Schema 包装成 `{"type":"function","function":...}`。

## 5. 与 CowAgentByYan 的参考关系

参考项目的 `BaseTool` 使用 `name / description / params / parallel_safe` 描述工具，`ToolManager` 负责装载和创建工具。YanAgent 保留这些核心概念，但使用显式不可替换的 `ToolDefinition`、注册快照和统一风险/范围字段，避免把插件装载、MCP 生命周期和权限执行提前混入 P03-01。

## 6. 验证证据

`tests/test_tool_registry.py` 新增 11 项测试，覆盖：

- 合法定义规范化。
- 非法名称、元数据和参数 Schema。
- 调用方 Schema 与注册表快照隔离。
- 同名注册拒绝且不覆盖原 handler。
- 两线程并发注册只产生一个成功结果。
- 工具名称和 Schema 稳定排序。
- 模型 Schema 不包含风险等内部字段。
- 导出结果可以直接通过现有 `prepare_request()` 转成 Provider 请求。
- 修改导出结果不会污染下次导出。
- `execute()` 仍明确属于后续阶段。

全量 148 项测试通过，Python 编译检查和 `git diff --check` 通过。

## 7. 当前边界

- `current_time` 和受限计算器已由 P03-02 实现；详见 [安全示例工具](P03_02_SAFE_TOOLS.md)。
- `ToolCall.arguments`、未知工具、超时、异常和大结果已由 P03-03 处理；详见 [统一工具执行](P03_03_TOOL_EXECUTION.md)。
- `risk_level`、`scope` 和 `requires_confirmation` 已由 P03-04 接入权限决策，详见 [工具权限基础](P03_04_PERMISSION_FOUNDATION.md)。
- 尚无桌面或 HTTP 工具列表接口；P03-05 接通。
- 尚未把工具 Schema 注入真实聊天，也没有模型→工具→模型循环；P04 完成。
