# YanAgent 并发交错与 request_id 隔离说明

本文整理 YanAgent 在流式聊天中的并发交错、`request_id` 隔离、重复 ID 防护和相关源码位置。

## 1. 什么是交错执行

当请求 A 和请求 B 同时调用模型时，后端可能按下面的顺序收到模型增量：

```text
A：开始等待模型
B：开始等待模型
A：收到“今天”
B：收到“李白”
B：收到“是一个”
A：收到“天气很好”
B：收到“诗人”
```

这是正常的异步并发。一个请求等待网络返回时，事件循环可以继续处理另一个请求。主要的异步等待发生在：

```python
async for event in prepared.provider.stream([prepared.message], tools=[]):
```

代码位置：`yanagent/runtime/streaming.py` 的 `AgentRuntime._run_stream()`。

交错执行不等于内容混合。两个任务分别持有自己的运行记录：

```text
A任务：_run_stream(record_a, prepared_a)
B任务：_run_stream(record_b, prepared_b)
```

即使执行顺序交错，写入目标仍然不同：

```text
“今天”       → record_a
“李白”       → record_b
“是一个”     → record_b
“天气很好”   → record_a
“诗人”       → record_b
```

最终结果仍然是：

```text
record_a = “今天天气很好”
record_b = “李白是一个诗人”
```

可以把它理解为两个人同时向两个不同杯子倒水：倒水时间能够交错，但杯子从一开始就是分开的。

## 2. 为什么两个回答不会混在一起

### 2.1 每个请求生成独立编号

桌面端调用 `POST /message` 后，后端在 `app.py` 中生成新的运行编号：

```python
if path == "/message":
    request_id = f"run-{uuid.uuid4().hex}"
```

例如：

```text
A → request_id = run-111
B → request_id = run-222
```

### 2.2 每个请求创建独立的 RunRecord

`AgentRuntime.start_stream()` 为当前请求创建运行记录：

```python
record = RunRecord(
    request_id=request_id,
    session_id=prepared.session_id,
)
```

再以 `request_id` 为键保存：

```python
self._runs[request_id] = record
```

运行时的数据可以理解为：

```python
self._runs = {
    "run-111": record_a,
    "run-222": record_b,
}
```

`record_a` 和 `record_b` 是两个独立对象，各自拥有自己的 `_events` 列表。

### 2.3 模型增量只写入当前任务的 record

启动任务时，当前 `record` 会作为函数参数传入协程：

```python
future = asyncio.run_coroutine_threadsafe(
    self._run_stream(record, prepared),
    self._loop,
)
```

模型每返回一段内容，只会写入当前协程持有的 `record`：

```python
record.append("delta", {"content": event.content})
```

事件循环可以在 A、B 协程间切换，但切换不会把 A 的局部变量 `record_a` 替换为 B 的 `record_b`。

### 2.4 桌面端按 request_id 订阅结果

桌面端分别建立 SSE 连接：

```text
GET /stream?request_id=run-111
GET /stream?request_id=run-222
```

后端根据 ID 查找对应记录：

```python
record = self._runs.get(request_id)
```

因此：

```text
run-111 → 只能读取 record_a
run-222 → 只能读取 record_b
```

## 3. 如何在桌面聊天界面观察并发

并发不是通过某一句特殊提示词触发的，而是通过让两个请求在时间上重叠产生的。

同一个会话正在生成时，输入组件不允许继续发送：

```typescript
if (isStreaming) return
```

因此，可以使用两个会话人工观察并发。

### 操作步骤

1. 在当前会话发送一个耗时较长的任务：

   ```text
   你是任务A。请从A-001连续输出到A-200，每个编号单独一行，
   每行再写一句不少于20字的说明。不要省略，不要输出任何B开头的内容。
   ```

2. 不要等待回答完成，也不要点击停止。
3. 趁 A 仍在生成，点击右上角“新对话”。
4. 在新会话发送：

   ```text
   你是任务B。请从B-001连续输出到B-200，每个编号单独一行，
   每行再写一句不少于20字的说明。不要省略，不要输出任何A开头的内容。
   ```

5. 在两个会话之间来回切换。

正常现象是：

```text
会话A持续生成A-001、A-002……
会话B同时生成B-001、B-002……
```

不应该在同一个气泡中出现：

```text
A-001
B-001
A-002
B-002
```

“交错”指后端执行时间交错，不是界面内容混合。如果同一气泡混入另一个请求的正文，反而说明发生了串流错误。

人工验证受模型响应速度影响：如果 A 在发送 B 之前已经结束，就没有形成时间重叠。自动化并发测试比人工观察更稳定。

## 4. 把 request_id 写成固定值会怎样

假设将 ID 改成：

```python
request_id = "fixed-id"
```

按照当前实现，第二个请求不会覆盖第一个请求，而会被直接拒绝：

```python
with self._runs_lock:
    if request_id in self._runs:
        raise ValueError("request_id 不能重复")
    self._runs[request_id] = record
```

执行过程如下：

```text
请求A进入
fixed-id不存在
fixed-id → record_a
A正常执行

请求B进入
发现fixed-id已经存在
抛出“request_id不能重复”
B失败，不覆盖A
```

因此，保留当前重复检查时，固定 ID 的直接结果通常是后续请求失败，而不是两个回答混在一起。

运行记录会暂时保留，所以即使 A 已经完成，旧记录尚未清理时，紧接着使用同一固定 ID 发送 B 也可能失败。

### 删除重复检查的风险

如果删除重复检查，可能发生：

```python
self._runs["fixed-id"] = record_a
self._runs["fixed-id"] = record_b
```

第二次赋值会覆盖字典中的第一次映射。此时 A、B 协程仍可能分别向 `record_a`、`record_b` 写入，所以不一定会逐字拼成混合文本，但会出现严重的错误路由：

- A 的回答无法通过 `fixed-id` 找回；
- A 的订阅可能错误读取 B 的记录；
- 取消 A 时可能实际取消 B；
- A 的连接可能一直等待；
- 两个桌面请求可能都显示 B 的结果。

只有当 A 和 B 真正共享同一个 `RunRecord` 时，增量才更可能直接混入同一个事件列表。

因此这里有两道保护：

```text
UUID：尽量让每个请求天然不同
重复检查：即使意外碰撞，也安全失败，禁止覆盖
```

## 5. 重复 ID 判断是怎么运行的

`self._runs` 是一个 Python 字典：

```python
self._runs: dict[str, RunRecord] = {}
```

字典的键是 `request_id`，值是对应的 `RunRecord`：

```python
self._runs = {
    "run-111": record_a,
    "run-222": record_b,
}
```

表达式：

```python
request_id in self._runs
```

检查的是字典的键，等价于：

```python
request_id in self._runs.keys()
```

第一次收到 `fixed-id` 时：

```python
"fixed-id" in {}
```

结果为 `False`，随后保存：

```python
self._runs["fixed-id"] = record_a
```

第二次收到 `fixed-id` 时：

```python
"fixed-id" in {"fixed-id": record_a}
```

结果为 `True`，程序执行：

```python
raise ValueError("request_id 不能重复")
```

抛出异常后，后面的赋值不会继续执行，因此原有 `record_a` 不会被覆盖。

## 6. 为什么还需要 _runs_lock

如果没有锁，两个请求可能同时完成检查：

```text
A检查fixed-id：不存在
                         B检查fixed-id：也不存在
A准备写入
                         B也准备写入
A写入record_a
                         B覆盖为record_b
```

`with self._runs_lock:` 将“判断”和“写入”保护为一个整体。加锁后的顺序是：

```text
A获得锁
A检查：不存在
A写入record_a
A释放锁

B获得锁
B检查：已经存在
B抛出重复错误
B释放锁
```

`with` 代码块正常结束或抛出异常时都会释放锁。

因此真正重要的不是只有一行 `if`，而是下面三个动作构成一个受保护的整体：

```text
获得锁
  ↓
检查request_id
  ↓
不存在就立即保存
  ↓
释放锁
```

## 7. 自动化测试如何证明没有串流

并发测试使用 `EchoStreamProvider`，让每个请求逐字符返回自己的输入，并在每个字符之间主动让出事件循环：

```python
content = messages[0].content
for char in content:
    await asyncio.sleep(0.003)
    yield ModelStreamEvent(kind="text_delta", content=char)
```

测试同时创建两条运行：

```python
first_text = "甲请求-AAAA"
second_text = "乙请求-BBBB"
first_id = self._create_run("session-a", first_text)
second_id = self._create_run("session-b", second_text)
```

然后使用两个线程同时订阅两个 SSE：

```python
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
    first_future = executor.submit(self._read_content, first_id)
    second_future = executor.submit(self._read_content, second_id)
```

最后验证完整内容及排他性：

```python
self.assertEqual(first, (first_text, first_text))
self.assertEqual(second, (second_text, second_text))
self.assertNotIn("乙请求", first[0])
self.assertNotIn("甲请求", second[0])
```

这个测试专门验证请求路由与运行记录隔离，不验证模型知识或回答质量。

## 8. 源码索引

| 功能 | 文件与位置 |
|---|---|
| 生成唯一 `request_id` | `app.py`，`RequestHandler.do_POST()`，约第 263 行 |
| `RunRecord` 数据结构 | `yanagent/runtime/streaming.py`，约第 25 行 |
| 初始化 `_runs_lock` 和 `_runs` | `yanagent/runtime/streaming.py`，约第 129 行 |
| 创建记录、检查重复并登记运行 | `yanagent/runtime/streaming.py`，`AgentRuntime.start_stream()`，约第 164 行 |
| 消费模型增量并写入当前记录 | `yanagent/runtime/streaming.py`，`AgentRuntime._run_stream()`，约第 185 行 |
| 根据 ID 获取对应事件 | `yanagent/runtime/streaming.py`，`AgentRuntime.wait_events()`，约第 243 行 |
| SSE 路由与订阅 | `app.py`，`RequestHandler._stream()` 和 `do_GET()`，约第 168、194 行 |
| 前端阻止同一会话重复发送 | `desktop/src/renderer/src/components/ChatInput.tsx`，约第 369 行 |
| 前端按 ID 建立 SSE | `desktop/src/renderer/src/api/client.ts`，`createSSEStream()`，约第 332 行 |
| 并发 HTTP/SSE 隔离测试 | `tests/test_chat_integration.py`，`test_two_simultaneous_http_streams_do_not_mix()`，约第 483 行 |

## 9. 一句话总结

YanAgent 允许多个模型请求在时间上交错执行，但它在请求刚进入时就创建独立的 `request_id` 和 `RunRecord`；每个协程始终向自己的记录写入，桌面端也按 `request_id` 精确订阅。UUID 避免正常情况下的重复，锁内的重复检查负责在意外碰撞时安全失败。
