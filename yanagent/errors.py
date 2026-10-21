"""统一应用错误；只暴露受控说明，不携带供应商响应正文或凭据。"""

from __future__ import annotations

from typing import Any


CONFIG_FIELDS = frozenset({
    "host", "port", "model_provider", "api_base", "model", "api_key",
    "request_timeout", "permission_mode",
})


class AgentError(Exception):
    """提供稳定错误码、安全说明与重试提示，供后续 Provider 和 HTTP 层使用。"""

    code = "agent_error"
    message = "Agent 操作失败。"
    retryable = False

    def __init__(self, *, status_code: int | None = None) -> None:
        """仅保存合法的上游 HTTP 错误状态，不接受任意异常正文。"""
        self.status_code = (
            status_code if type(status_code) is int and 400 <= status_code <= 599 else None
        )
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        """生成可供日志或接口使用的安全错误对象；状态码表示上游状态。"""
        result = {"code": self.code, "message": self.message, "retryable": self.retryable}
        if self.status_code is not None:
            result["upstream_status"] = self.status_code
        return result


class ConfigurationError(AgentError):
    """标识配置读取、保存、格式或字段错误，使用固定原因而非原始输入。"""

    code = "configuration_error"
    _reasons = {
        "invalid": "配置字段类型或取值不合法，请检查配置说明。",
        "unknown_field": "配置包含不支持的字段，请检查配置说明。",
        "invalid_json": "配置必须是无重复字段的有效 JSON 对象。",
        "read_failed": "无法读取配置文件，请检查路径与读取权限。",
        "write_failed": "无法保存配置文件，请检查目录、权限和磁盘空间。",
        "missing_model": "模型调用前必须配置 API Base 和模型名称。",
        "missing_key": "模型调用前必须配置 API Key。",
        "masked_key": "脱敏占位符不能作为 API Key 保存，请省略该字段或输入新密钥。",
    }

    def __init__(self, *, reason: str = "invalid", field: str | None = None) -> None:
        """限制原因和字段为已知值，避免坏配置或路径中的敏感值被回显。"""
        self.reason = reason if reason in self._reasons else "invalid"
        self.field = field if field in CONFIG_FIELDS else None
        self.message = self._reasons[self.reason]
        if self.field is not None:
            self.message = f"{self.field}：{self.message}"
        super().__init__()

    def to_dict(self) -> dict[str, Any]:
        """补充固定原因和可定位的配置字段，不包含配置值。"""
        result = super().to_dict()
        result["reason"] = self.reason
        if self.field is not None:
            result["field"] = self.field
        return result


class AuthenticationError(AgentError):
    """标识模型供应商拒绝凭据；不等同于 YanAgent 用户登录失败。"""

    code = "authentication_error"
    message = "模型服务认证失败，请检查 API Key。"


class PermissionDeniedError(AgentError):
    """标识凭据没有访问目标模型服务的权限。"""

    code = "permission_denied"
    message = "模型服务拒绝访问，请检查账号或模型权限。"


class ModelNotFoundError(AgentError):
    """标识模型或 API 路径不存在；仅凭 404 不断言是哪一种。"""

    code = "model_not_found"
    message = "模型或接口不存在，请检查模型名称和 API Base。"


class InvalidRequestError(AgentError):
    """标识模型请求参数被拒绝，后续适配器可据此反馈配置问题。"""

    code = "invalid_request"
    message = "模型服务拒绝请求，请检查模型及请求参数。"


class RateLimitError(AgentError):
    """标识上游限流；可重试只是提示，不自动发起重试。"""

    code = "rate_limit"
    message = "模型服务请求受限，请稍后重试并检查配额。"
    retryable = True


class ModelTimeoutError(AgentError):
    """标识模型连接或读取超时，与配置值错误分开。"""

    code = "model_timeout"
    message = "模型请求超时，请检查网络或调整超时设置。"
    retryable = True


class ModelConnectionError(AgentError):
    """标识未得到 HTTP 响应的网络连接失败。"""

    code = "model_connection_error"
    message = "无法连接模型服务，请检查网络和 API Base。"
    retryable = True


class ModelResponseError(AgentError):
    """标识响应格式或工具参数损坏，不将原始正文放入错误信息。"""

    code = "model_response_error"
    message = "模型响应格式不符合约定，请检查兼容接口或模型配置。"


class EmptyModelResponseError(ModelResponseError):
    """标识响应没有可用文本，也没有可执行的工具请求。"""

    code = "empty_model_response"
    message = "模型没有返回文本或工具调用，请稍后重试或检查模型配置。"


class ModelRefusalError(ModelResponseError):
    """标识模型明确拒绝或过滤了本次输出。"""

    code = "model_refusal"
    message = "模型拒绝回答或输出被过滤，请调整请求。"


class ModelServerError(AgentError):
    """标识模型供应商的 HTTP 5xx 服务端错误。"""

    code = "model_server_error"
    message = "模型服务暂时异常，请稍后重试。"
    retryable = True


def map_http_error(status_code: int) -> AgentError:
    """按实际 HTTP 状态分类；不从正文猜测状态，也不接收响应正文。"""
    if type(status_code) is not int or not 400 <= status_code <= 599:
        raise ValueError("需要 400～599 范围内的 HTTP 错误状态码")
    error_type = {
        401: AuthenticationError,
        403: PermissionDeniedError,
        404: ModelNotFoundError,
        408: ModelTimeoutError,
        429: RateLimitError,
    }.get(status_code)
    if error_type is None:
        error_type = ModelServerError if status_code >= 500 else InvalidRequestError
    return error_type(status_code=status_code)
