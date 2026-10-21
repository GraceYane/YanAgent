"""真实本地 HTTP 联调；绑定回环随机端口，不访问公网或使用真实密钥。"""

from __future__ import annotations

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from yanagent.config import AppConfig
from yanagent.contracts import Message
from yanagent.errors import AuthenticationError, ModelResponseError, RateLimitError
from yanagent.models import OpenAICompatibleProvider


class LocalHandler(BaseHTTPRequestHandler):
    """本地兼容服务，通过模型名选择固定文本、工具、错误或重定向响应。"""

    def log_message(self, fmt, *args) -> None:
        """测试不打印请求日志，避免把测试正文混入验收输出。"""

    def do_POST(self) -> None:
        """读取真实 JSON 请求并保存测试记录，返回受控 HTTP 响应。"""
        data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.received.append((self.path, dict(self.headers), data))
        model = data["model"]
        if model == "redirect":
            self.send_response(307)
            self.send_header("Location", "/redirected")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        status = {"auth": 401, "limited": 429}.get(model, 200)
        if status != 200:
            payload = {"error": {"message": "test-secret-do-not-echo"}}
        elif model == "tool":
            payload = {"choices": [{"message": {"role": "assistant", "content": None,
                "tool_calls": [{"id": "c1", "type": "function", "function": {
                    "name": "calculator", "arguments": '{"x": 1}'}}]}, "finish_reason": "tool_calls"}]}
        else:
            payload = {"choices": [{"message": {"role": "assistant", "content": "本地测试回复：你好"},
                                    "finish_reason": "stop"}],
                       "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8}}
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class LocalHttpTests(unittest.IsolatedAsyncioTestCase):
    """通过默认传输完成真实回环请求，补充纯替身测试无法覆盖的连接链路。"""

    @classmethod
    def setUpClass(cls) -> None:
        """启动仅监听本机的测试服务器，端口由系统分配。"""
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), LocalHandler)
        cls.server.received = []
        cls.worker = threading.Thread(target=cls.server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        cls.worker.start()

    @classmethod
    def tearDownClass(cls) -> None:
        """停止并关闭服务器，等待服务线程退出。"""
        cls.server.shutdown()
        cls.server.server_close()
        cls.worker.join(timeout=2)

    def setUp(self) -> None:
        """每次测试清空请求记录，防止把上一用例的请求计入结果。"""
        self.server.received.clear()

    def provider(self, model="normal") -> OpenAICompatibleProvider:
        """创建使用固定无效密钥和本地随机端口的真实 Provider。"""
        return OpenAICompatibleProvider(AppConfig(
            api_base=f"http://127.0.0.1:{self.server.server_port}/v1", model=model,
            api_key="local-test-key", request_timeout=3,
        ))

    async def test_real_http_text_and_wire_request(self) -> None:
        """校验实际 POST 路径、认证头、UTF-8 输入及返回用量。"""
        reply = await self.provider().complete([Message("user", "你好")])
        self.assertEqual(reply.content, "本地测试回复：你好")
        self.assertEqual(reply.usage, {"input_tokens": 5, "output_tokens": 3, "total_tokens": 8})
        path, headers, body = self.server.received[0]
        self.assertEqual(path, "/v1/chat/completions")
        self.assertEqual(headers["Authorization"], "Bearer local-test-key")
        self.assertEqual(body["messages"][0]["content"], "你好")
        self.assertFalse(body["stream"])

    async def test_real_http_tool_response(self) -> None:
        """通过真实 HTTP 返回工具调用，确认参数字符串被还原为对象。"""
        reply = await self.provider("tool").complete([Message("user", "计算")])
        self.assertEqual(reply.tool_calls[0].arguments, {"x": 1})
        self.assertEqual(reply.tool_calls[0].id, "c1")

    async def test_real_http_errors_are_classified_without_retry(self) -> None:
        """真实 401 和 429 分别分类，各只发送一次请求且不透传错误正文。"""
        for model, error_type in (("auth", AuthenticationError), ("limited", RateLimitError)):
            with self.assertRaises(error_type) as caught:
                await self.provider(model).complete([Message("user", "hi")])
            self.assertNotIn("test-secret", str(caught.exception))
        self.assertEqual(len(self.server.received), 2)

    async def test_redirect_is_not_followed(self) -> None:
        """携带密钥的请求遇到重定向后停止，不请求第二个地址。"""
        with self.assertRaises(ModelResponseError):
            await self.provider("redirect").complete([Message("user", "hi")])
        self.assertEqual(len(self.server.received), 1)


if __name__ == "__main__":
    unittest.main()
