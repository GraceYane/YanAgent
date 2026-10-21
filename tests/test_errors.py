"""统一错误码、状态映射和安全输出的离线验收。"""

import json
import unittest

from yanagent.errors import (
    AgentError, AuthenticationError, ConfigurationError, InvalidRequestError,
    ModelConnectionError, ModelNotFoundError, ModelServerError, ModelTimeoutError,
    PermissionDeniedError, RateLimitError, map_http_error,
)


class ErrorTests(unittest.TestCase):
    """验证错误可以稳定分类，并且不会要求上层解析任意异常字符串。"""

    def test_http_status_mapping(self) -> None:
        """认证、权限、模型路径、限流、超时及服务端状态分别映射。"""
        for status, expected in (
            (400, InvalidRequestError), (401, AuthenticationError), (403, PermissionDeniedError),
            (404, ModelNotFoundError), (408, ModelTimeoutError), (422, InvalidRequestError),
            (429, RateLimitError), (500, ModelServerError), (503, ModelServerError),
        ):
            with self.subTest(status=status):
                error = map_http_error(status)
                self.assertIsInstance(error, expected)
                self.assertEqual(error.to_dict()["upstream_status"], status)

    def test_retry_hint_and_json_shape(self) -> None:
        """可重试提示与错误类别一致，输出可 JSON 往返且不包含异常对象。"""
        for error in (AgentError(), ConfigurationError(), AuthenticationError(),
                      PermissionDeniedError(), ModelNotFoundError(), InvalidRequestError(),
                      RateLimitError(), ModelTimeoutError(), ModelConnectionError(), ModelServerError()):
            result = error.to_dict()
            self.assertEqual(json.loads(json.dumps(result)), result)
            self.assertEqual(str(error), result["message"])
            self.assertEqual(result["retryable"], isinstance(error, (
                RateLimitError, ModelTimeoutError, ModelConnectionError, ModelServerError,
            )))

    def test_bad_status_is_not_guessed_from_text(self) -> None:
        """成功码、布尔值和数字字符串均不能冒充 HTTP 错误状态。"""
        for status in (200, 399, 600, True, None, "429", "tokens 4000"):
            with self.subTest(status=status), self.assertRaises(ValueError):
                map_http_error(status)

    def test_untrusted_reason_and_field_are_not_echoed(self) -> None:
        """任意错误原因、字段或状态内容不会进入展示字典或异常字符串。"""
        secret = "test-secret-do-not-print"
        error = ConfigurationError(reason=secret, field=secret)
        self.assertNotIn(secret, json.dumps(error.to_dict()) + str(error) + repr(error))
        self.assertEqual(error.reason, "invalid")
        self.assertNotIn("upstream_status", AuthenticationError(status_code=secret).to_dict())


if __name__ == "__main__":
    unittest.main()
