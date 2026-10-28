"""P03-05 工具列表 HTTP 接口与 P03 阶段综合验收测试。"""

from __future__ import annotations

import asyncio
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import urlopen

from app import create_server
from yanagent.chat import YanAgentApplication
from yanagent.config import ConfigStore
from yanagent.contracts import ToolCall
from yanagent.tools import (
    ToolAlreadyRegisteredError,
    ToolDefinition,
    ToolManager,
    calculator_definition,
)


def _definition(name: str, handler) -> ToolDefinition:
    """构造接收一个必填字符串的低风险全局验收工具。"""
    return ToolDefinition(
        name=name,
        description=f"P03-05 验收工具 {name}",
        parameters={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
        },
        handler=handler,
        risk_level="low",
        parallel_safe=True,
        scope="global",
    )


class ToolCatalogApplicationTests(unittest.TestCase):
    """验证应用级工具注册表和桌面目录负载保持稳定隔离。"""

    def test_default_catalog_lists_safe_tools_without_internal_fields(self) -> None:
        """默认应用列出计算器和时间工具，且不泄露参数或权限内部元数据。"""
        with tempfile.TemporaryDirectory() as directory:
            application = YanAgentApplication(
                ConfigStore(Path(directory) / "config.json", environ={})
            )
            first = application.tools_payload()
            self.assertEqual(first["status"], "success")
            self.assertEqual(
                [item["name"] for item in first["tools"]],
                ["calculator", "current_time"],
            )
            for item in first["tools"]:
                self.assertEqual(set(item), {"name", "description"})

            first["tools"][0]["description"] = "polluted"
            second = application.tools_payload()
            self.assertNotEqual(second["tools"][0]["description"], "polluted")

    def test_injected_empty_registry_is_respected(self) -> None:
        """测试或未来 Agent 注入的注册表不会被默认工具静默覆盖。"""
        with tempfile.TemporaryDirectory() as directory:
            manager = ToolManager()
            application = YanAgentApplication(
                ConfigStore(Path(directory) / "config.json", environ={}),
                tool_manager=manager,
            )
            self.assertIs(application.tool_manager, manager)
            self.assertEqual(application.tools_payload()["tools"], [])


class ToolCatalogHttpTests(unittest.TestCase):
    """通过真实回环 HTTP 验证桌面能力页依赖的目录契约。"""

    def setUp(self) -> None:
        """启动带默认安全工具的独立本地服务。"""
        self.temporary = tempfile.TemporaryDirectory()
        store = ConfigStore(Path(self.temporary.name) / "config.json", environ={})
        self.server = create_server("127.0.0.1", 0, config_store=store)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self) -> None:
        """停止回环服务并清理临时配置目录。"""
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.temporary.cleanup()

    def test_tools_endpoint_returns_real_registered_catalog(self) -> None:
        """桌面 GET 请求获得真实注册工具，而不是旧的空占位数组。"""
        with urlopen(self.base_url + "/api/tools", timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
            self.assertEqual(
                response.headers.get_content_type(), "application/json"
            )
        self.assertEqual(payload["status"], "success")
        self.assertEqual(
            [item["name"] for item in payload["tools"]],
            ["calculator", "current_time"],
        )
        self.assertTrue(all(item["description"] for item in payload["tools"]))

    def test_empty_mcp_servers_endpoint_returns_array(self) -> None:
        """空 MCP 配置仍返回数组，避免能力页按数组读取时发生白屏。"""
        with urlopen(self.base_url + "/api/mcp/servers", timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
            self.assertEqual(
                response.headers.get_content_type(), "application/json"
            )
        self.assertEqual(payload, {"status": "success", "servers": []})


class ToolStageAcceptanceTests(unittest.IsolatedAsyncioTestCase):
    """把 P03 要求的注册、校验、权限、超时和失败路径做一次综合验收。"""

    async def test_duplicate_and_pre_handler_failures_are_closed(self) -> None:
        """重复注册、非法参数和权限拒绝均明确失败且不进入 handler。"""
        executions = 0

        async def handler(_arguments: dict[str, object]) -> str:
            """记录是否有非法调用越过执行前闸门。"""
            nonlocal executions
            executions += 1
            return "unexpected"

        manager = ToolManager()
        definition = _definition("guarded", handler)
        manager.register(definition)
        with self.assertRaises(ToolAlreadyRegisteredError):
            manager.register(definition)

        invalid = await manager.execute(
            ToolCall(id="invalid-1", name="guarded", arguments={}),
            permission_mode="allow",
        )
        denied = await manager.execute(
            ToolCall(id="denied-1", name="guarded", arguments={"value": "ok"}),
            permission_mode="deny",
        )
        self.assertTrue(invalid.is_error)
        self.assertTrue(denied.is_error)
        self.assertEqual(executions, 0)

    async def test_success_timeout_and_failure_keep_structured_results(self) -> None:
        """计算成功关联调用 ID，超时和异常失败后管理器仍可继续服务。"""
        attempts = 0

        async def slow_handler(_arguments: dict[str, object]) -> str:
            """等待超过管理器期限以触发结构化超时。"""
            await asyncio.sleep(10)
            return "late"

        async def unstable_handler(_arguments: dict[str, object]) -> str:
            """第一次抛出未知异常，第二次返回成功用于验证恢复。"""
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("不应进入公开结果的内部细节")
            return "recovered"

        manager = ToolManager(timeout_seconds=0.01)
        manager.register(calculator_definition())
        manager.register(_definition("slow", slow_handler))
        manager.register(_definition("unstable", unstable_handler))

        calculated = await manager.execute(
            ToolCall(
                id="calculator-1",
                name="calculator",
                arguments={"expression": "(2 + 3) * 4"},
            ),
            permission_mode="allow",
        )
        timed_out = await manager.execute(
            ToolCall(id="slow-1", name="slow", arguments={"value": "wait"}),
            permission_mode="allow",
        )
        failed = await manager.execute(
            ToolCall(id="unstable-1", name="unstable", arguments={"value": "first"}),
            permission_mode="allow",
        )
        recovered = await manager.execute(
            ToolCall(id="unstable-2", name="unstable", arguments={"value": "second"}),
            permission_mode="allow",
        )

        self.assertEqual(calculated.tool_call_id, "calculator-1")
        self.assertEqual(calculated.content, "20")
        self.assertFalse(calculated.is_error)
        self.assertTrue(timed_out.is_error)
        self.assertIn("超时", timed_out.content)
        self.assertTrue(failed.is_error)
        self.assertNotIn("内部细节", failed.content)
        self.assertFalse(recovered.is_error)
        self.assertEqual(recovered.content, "recovered")
