"""验证 P01-04 配置适配、普通聊天和桌面 HTTP 契约。"""

from __future__ import annotations

import asyncio
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from app import create_server
from yanagent.chat import DEFAULT_API_BASE, PROVIDER_ID, YanAgentApplication
from yanagent.config import ConfigStore, MASKED_SECRET
from yanagent.contracts import ModelReply, ToolCall
from yanagent.errors import (
    AuthenticationError, ConfigurationError, RequestValidationError, UnexpectedToolCallError,
)
from yanagent.models import FakeProvider


class ChatApplicationTests(unittest.TestCase):
    """直接测试应用层，隔离 HTTP 传输对业务断言的影响。"""

    def setUp(self) -> None:
        """为每个用例创建独立配置文件和可预测的 Fake Provider。"""
        self.temporary = tempfile.TemporaryDirectory()
        self.store = ConfigStore(Path(self.temporary.name) / "config.json", environ={})

    def tearDown(self) -> None:
        """清理用例使用的临时配置目录。"""
        self.temporary.cleanup()

    def test_config_and_models_payload_mask_secret(self) -> None:
        """桌面两套查询接口应一致展示当前模型且不泄露密钥。"""
        self.store.save({
            "api_base": "https://example.invalid/v1",
            "model": "demo-model",
            "api_key": "top-secret",
        })
        application = YanAgentApplication(self.store)

        config = application.config_payload()
        models = application.models_payload()

        self.assertEqual(config["model"], "demo-model")
        self.assertEqual(config["api_keys"]["api_key"], MASKED_SECRET)
        self.assertNotIn("top-secret", json.dumps([config, models], ensure_ascii=False))
        self.assertTrue(models["providers"][0]["configured"])
        self.assertEqual(models["capabilities"]["chat"]["current_model"], "demo-model")

    def test_legacy_config_and_models_actions_persist_supported_fields(self) -> None:
        """旧配置页和模型控制台动作都应写入同一份精简配置。"""
        application = YanAgentApplication(self.store)
        application.save_config({
            "updates": {
                "bot_type": PROVIDER_ID,
                "model": "first-model",
                "agent_permission_mode": "allow",
                "cow_lang": "zh",
            }
        })
        application.save_model_action({
            "action": "set_provider",
            "provider_id": PROVIDER_ID,
            "api_key": "real-key",
        })
        application.save_model_action({
            "action": "set_capability",
            "capability": "chat",
            "provider_id": PROVIDER_ID,
            "model": "second-model",
        })

        saved = self.store.load()
        self.assertEqual(saved.model, "second-model")
        self.assertEqual(saved.permission_mode, "allow")
        self.assertEqual(saved.api_key, "real-key")
        self.assertEqual(saved.api_base, DEFAULT_API_BASE)

    def test_chat_returns_inline_reply_and_records_only_current_turn(self) -> None:
        """普通聊天应返回非流式完整回答，且 P02 前只发送本次用户消息。"""
        fake = FakeProvider([
            ModelReply(
                content="你好，我是 YanAgent。",
                finish_reason="stop",
                usage={"input_tokens": 4, "output_tokens": 7},
            )
        ])
        application = YanAgentApplication(self.store, provider_factory=lambda _config: fake)

        result = asyncio.run(application.chat({
            "session_id": "session-1",
            "message": "你好",
            "stream": True,
            "attachments": [],
            "is_voice": False,
            "agent_id": "default",
        }))

        self.assertEqual(result["status"], "success")
        self.assertFalse(result["stream"])
        self.assertEqual(result["inline_reply"], "你好，我是 YanAgent。")
        self.assertTrue(result["request_id"].startswith("run-"))
        self.assertEqual([item.role for item in fake.calls[0].messages], ["user"])
        self.assertEqual(fake.calls[0].messages[0].content, "你好")
        self.assertEqual(fake.calls[0].tools, [])

    def test_missing_model_configuration_fails_before_network(self) -> None:
        """未填写模型设置时，应用层应返回配置错误而不是尝试访问网络。"""
        application = YanAgentApplication(self.store)

        with self.assertRaises(ConfigurationError) as caught:
            asyncio.run(application.chat({"session_id": "s1", "message": "你好"}))

        self.assertEqual(caught.exception.reason, "missing_model")

    def test_chat_rejects_bad_input_before_consuming_fake(self) -> None:
        """缺少会话、空消息和附件应在调用模型前得到明确字段错误。"""
        fake = FakeProvider([ModelReply(content="不会被消费")])
        application = YanAgentApplication(self.store, provider_factory=lambda _config: fake)
        cases = [
            ({"message": "你好"}, "session_id"),
            ({"session_id": "s1", "message": "   "}, "message"),
            ({"session_id": "s1", "message": "你好", "attachments": [{}]}, "attachments"),
        ]
        for payload, field in cases:
            with self.subTest(field=field):
                with self.assertRaises(RequestValidationError) as caught:
                    asyncio.run(application.chat(payload))
                self.assertEqual(caught.exception.field, field)
        self.assertEqual(fake.remaining, 1)
        self.assertEqual(fake.calls, [])

    def test_chat_does_not_execute_unexpected_tool_call(self) -> None:
        """P01-04 未启用工具时，模型异常返回工具请求必须显式失败。"""
        fake = FakeProvider([
            ModelReply(tool_calls=[ToolCall(id="call-1", name="shell", arguments={})])
        ])
        application = YanAgentApplication(self.store, provider_factory=lambda _config: fake)

        with self.assertRaises(UnexpectedToolCallError):
            asyncio.run(application.chat({"session_id": "s1", "message": "执行命令"}))


class ChatHttpIntegrationTests(unittest.TestCase):
    """通过真实回环 HTTP 验证桌面端使用的状态、字段和错误包络。"""

    def setUp(self) -> None:
        """在随机回环端口启动注入 Fake Provider 的线程服务。"""
        self.temporary = tempfile.TemporaryDirectory()
        store = ConfigStore(Path(self.temporary.name) / "config.json", environ={})
        outcome = (
            AuthenticationError()
            if self._testMethodName == "test_provider_error_maps_to_http_without_original_secret"
            else ModelReply(content="HTTP 联调成功", finish_reason="stop")
        )
        self.fake = FakeProvider([outcome])
        application = YanAgentApplication(store, provider_factory=lambda _config: self.fake)
        self.server = create_server("127.0.0.1", 0, application=application)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self) -> None:
        """停止 HTTP 服务并清理临时目录，避免用例间共享端口或配置。"""
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)
        self.temporary.cleanup()

    def _request(
        self, path: str, *, method: str = "GET", payload: dict[str, object] | None = None,
    ) -> tuple[int, dict[str, object]]:
        """发送 UTF-8 JSON 请求，并把成功或 HTTP 错误统一解析为状态与对象。"""
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            self.base_url + path,
            data=body,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            response = urlopen(request, timeout=3)
        except HTTPError as error:
            with error:
                return error.code, json.loads(error.read().decode("utf-8"))
        with response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def test_desktop_message_contract_over_real_http(self) -> None:
        """桌面传 stream=true 时，后端应按 P01-04 返回 inline_reply 而非 SSE。"""
        status, body = self._request("/message", method="POST", payload={
            "session_id": "desktop-session",
            "message": "你好",
            "stream": True,
            "attachments": [],
            "is_voice": False,
            "lang": "zh",
            "agent_id": "default",
        })

        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "success")
        self.assertEqual(body["inline_reply"], "HTTP 联调成功")
        self.assertFalse(body["stream"])

    def test_invalid_message_has_structured_http_error(self) -> None:
        """坏消息应返回 400、稳定错误码和安全中文说明。"""
        status, body = self._request(
            "/message", method="POST", payload={"session_id": "s1", "message": ""},
        )

        self.assertEqual(status, 400)
        self.assertEqual(body["status"], "error")
        self.assertEqual(body["error"]["code"], "request_validation_error")
        self.assertEqual(body["error"]["field"], "message")
        self.assertFalse(body["stream"])

    def test_provider_error_maps_to_http_without_original_secret(self) -> None:
        """Provider 认证失败应映射 401，且响应中不出现测试凭据。"""
        status, body = self._request(
            "/message", method="POST", payload={"session_id": "s1", "message": "你好"},
        )

        self.assertEqual(status, 401)
        self.assertEqual(body["error"]["code"], "authentication_error")
        self.assertNotIn("secret", json.dumps(body, ensure_ascii=False))

    def test_models_and_config_endpoints_match_desktop_paths(self) -> None:
        """模型查询、保存和旧配置查询应使用桌面客户端写死的真实路径。"""
        save_status, _ = self._request("/api/models", method="POST", payload={
            "action": "set_provider",
            "provider_id": PROVIDER_ID,
            "api_base": "https://example.invalid/v1",
            "api_key": "http-key",
        })
        model_status, models = self._request("/api/models")
        config_status, config = self._request("/config")

        self.assertEqual((save_status, model_status, config_status), (200, 200, 200))
        self.assertTrue(models["providers"][0]["configured"])
        self.assertEqual(config["api_keys"]["api_key"], MASKED_SECRET)
        self.assertNotIn("http-key", json.dumps([models, config], ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
