"""读取独立配置、应用环境覆盖、验证字段，并原子保存文件配置。"""

from __future__ import annotations

import json
import math
import os
import tempfile
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from yanagent.errors import CONFIG_FIELDS, ConfigurationError


MASKED_SECRET = "********"
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config.json"
ENV_FIELDS = {
    "YAN_WEB_HOST": "host",
    "YAN_WEB_PORT": "port",
    "YAN_MODEL_PROVIDER": "model_provider",
    "YAN_API_BASE": "api_base",
    "YAN_MODEL": "model",
    "YAN_API_KEY": "api_key",
    "YAN_REQUEST_TIMEOUT": "request_timeout",
    "YAN_PERMISSION_MODE": "permission_mode",
}


def _validate_text(value: Any, name: str, *, allow_empty: bool = False) -> None:
    """检查无首尾空白、无控制字符的文本；未配置的模型字段可为空串。"""
    if (
        type(value) is not str
        or (not allow_empty and not value)
        or value != value.strip()
        or any(ord(char) < 32 or ord(char) == 127 or 0xD800 <= ord(char) <= 0xDFFF for char in value)
    ):
        raise ConfigurationError(field=name)


def _validate_api_base(value: str) -> None:
    """检查 HTTP(S) 基础地址；拒绝 URL 凭据、查询参数及片段中的密钥。"""
    if not value:
        return
    try:
        parsed = urlsplit(value)
        valid = (
            parsed.scheme in {"http", "https"}
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
            and "?" not in value
            and "#" not in value
            and "\\" not in value
            and not any(char.isspace() for char in value)
            and (parsed.port is None or 1 <= parsed.port <= 65535)
        )
    except ValueError:
        valid = False
    if not valid:
        raise ConfigurationError(field="api_base") from None


@dataclass(frozen=True)
class AppConfig:
    """一次读取产生的不可变生效配置；允许未填密钥时进入后续设置页面。"""

    host: str = "127.0.0.1"
    port: int = 9876
    model_provider: str = "openai-compatible"
    api_base: str = ""
    model: str = ""
    api_key: str = field(default="", repr=False)
    request_timeout: float = 600.0
    permission_mode: str = "ask"
    max_context_tokens: int = 64_000
    max_context_turns: int = 20
    max_agent_steps: int = 20
    enable_thinking: bool = False
    reasoning_effort_by_model: dict[str, str] = field(default_factory=dict)
    subagent_enabled: bool = False
    self_evolution_enabled: bool = False
    provider_configs: dict[str, dict[str, Any]] = field(default_factory=dict, repr=False)
    chat_fallback: dict[str, Any] = field(default_factory=lambda: {"enabled": False, "chain": []})
    max_output_tokens: int = 4096

    def __post_init__(self) -> None:
        """构造时统一校验类型、允许值及超时范围，不接受隐式类型转换。"""
        for name in ("host", "model_provider", "permission_mode"):
            _validate_text(getattr(self, name), name)
        for name in ("api_base", "model", "api_key"):
            _validate_text(getattr(self, name), name, allow_empty=True)
        if any(char.isspace() or char in "/\\?#@" for char in self.host):
            raise ConfigurationError(field="host")
        if type(self.port) is not int or not 1 <= self.port <= 65535:
            raise ConfigurationError(field="port")
        if self.model_provider not in {"openai-compatible", "openai", "deepseek", "qwen", "claude", "gemini"}:
            raise ConfigurationError(field="model_provider")
        if type(self.max_output_tokens) is not int or not 1 <= self.max_output_tokens <= 128_000:
            raise ConfigurationError(field="max_output_tokens")
        if type(self.provider_configs) is not dict:
            raise ConfigurationError(field="provider_configs")
        for provider, profile in self.provider_configs.items():
            if provider not in {"openai-compatible", "openai", "deepseek", "qwen", "claude", "gemini"} or type(profile) is not dict:
                raise ConfigurationError(field="provider_configs")
            if set(profile) - {"api_key", "api_base", "models", "hidden", "model_options"}:
                raise ConfigurationError(field="provider_configs")
            for name in ("api_key", "api_base"):
                _validate_text(profile.get(name, ""), name, allow_empty=True)
            key = profile.get("api_key", "")
            if key and set(key) == {"*"}:
                raise ConfigurationError(reason="masked_key", field="provider_configs")
            _validate_api_base(profile.get("api_base", ""))
            options = profile.get('model_options', {})
            if type(options) is not dict or len(options) > 200:
                raise ConfigurationError(field='provider_configs')
            for model_name, option in options.items():
                _validate_text(model_name, 'model')
                if type(option) is not dict or set(option) - {'context_window', 'max_output_tokens', 'thinking_protocol', 'thinking_budget'}:
                    raise ConfigurationError(field='provider_configs')
                for key, maximum in (('context_window', 1_000_000), ('max_output_tokens', 128_000), ('thinking_budget', 128_000)):
                    if key in option and (type(option[key]) is not int or not 1 <= option[key] <= maximum):
                        raise ConfigurationError(field='provider_configs')
                protocols = {'none', 'claude-enabled', 'claude-adaptive'} if provider == 'claude' else (
                    {'none', 'gemini-budget', 'gemini-level'} if provider == 'gemini' else {'none', 'openai', 'deepseek', 'qwen'})
                if 'thinking_protocol' in option and (type(option['thinking_protocol']) is not str or option['thinking_protocol'] not in protocols):
                    raise ConfigurationError(field='provider_configs')
            for name in ("models", "hidden"):
                values = profile.get(name, [])
                if type(values) is not list or len(values) > 200:
                    raise ConfigurationError(field="provider_configs")
                for value in values:
                    _validate_text(value, "model")
                    if len(value) > 256:
                        raise ConfigurationError(field="model")
        fallback = self.chat_fallback
        if (type(fallback) is not dict or set(fallback) - {"enabled", "chain"}
            or type(fallback.get("enabled", False)) is not bool
            or type(fallback.get("chain", [])) is not list or len(fallback.get("chain", [])) > 4):
            raise ConfigurationError(field="chat_fallback")
        seen = set()
        for link in fallback.get("chain", []):
            if type(link) is not dict or set(link) != {"provider", "model"}:
                raise ConfigurationError(field="chat_fallback")
            _validate_text(link["provider"], "model_provider")
            _validate_text(link["model"], "model")
            if link["provider"] not in {"openai-compatible", "openai", "deepseek", "qwen", "claude", "gemini"}:
                raise ConfigurationError(field="chat_fallback")
            pair = (link["provider"], link["model"])
            if pair in seen:
                raise ConfigurationError(field="chat_fallback")
            seen.add(pair)
        if fallback.get("enabled") and not seen:
            raise ConfigurationError(field="chat_fallback")
        if self.permission_mode not in {"deny", "ask", "allow"}:
            raise ConfigurationError(field="permission_mode")
        if type(self.max_context_tokens) is not int or not 0 <= self.max_context_tokens <= 1_000_000:
            raise ConfigurationError(field="max_context_tokens")
        if type(self.max_context_turns) is not int or not 1 <= self.max_context_turns <= 500:
            raise ConfigurationError(field="max_context_turns")
        if type(self.max_agent_steps) is not int or not 1 <= self.max_agent_steps <= 999:
            raise ConfigurationError(field="max_agent_steps")
        for name in ("enable_thinking", "subagent_enabled", "self_evolution_enabled"):
            if type(getattr(self, name)) is not bool:
                raise ConfigurationError(field=name)
        if type(self.reasoning_effort_by_model) is not dict or any(
            type(key) is not str or not key.strip() or type(value) is not str
            for key, value in self.reasoning_effort_by_model.items()
        ):
            raise ConfigurationError(field="model")
        if (
            type(self.request_timeout) not in (int, float)
            or not 0 < self.request_timeout <= 3600
            or not math.isfinite(self.request_timeout)
        ):
            raise ConfigurationError(field="request_timeout")
        if self.api_key and set(self.api_key) == {"*"}:
            raise ConfigurationError(reason="masked_key", field="api_key")
        _validate_api_base(self.api_base)

    def require_model_ready(self) -> None:
        """模型调用前检查必要配置；只验证完整性，不验证远端密钥是否有效。"""
        for name in ("api_base", "model"):
            if not getattr(self, name):
                raise ConfigurationError(reason="missing_model", field=name)
        if not self.api_key:
            raise ConfigurationError(reason="missing_key", field="api_key")

    def to_dict(self) -> dict[str, Any]:
        """返回默认安全的展示字典，短密钥和长密钥均完全隐藏。"""
        result = asdict(self)
        result["api_key"] = MASKED_SECRET if self.api_key else ""
        for profile in result["provider_configs"].values():
            if "api_key" in profile:
                profile["api_key"] = MASKED_SECRET if profile["api_key"] else ""
        return result


def _check_fields(data: Any) -> dict[str, Any]:
    """检查配置或局部更新为已知字段的对象，禁止静默忽略拼写错误。"""
    if type(data) is not dict:
        raise ConfigurationError(reason="invalid_json")
    if any(key not in CONFIG_FIELDS for key in data):
        raise ConfigurationError(reason="unknown_field")
    return dict(data)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """在 JSON 解析阶段拒绝重复键，避免后一个密钥悄悄覆盖前一个。"""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ConfigurationError(reason="invalid_json")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    """拒绝标准 JSON 不支持的 NaN 和 Infinity 字面量。"""
    raise ConfigurationError(reason="invalid_json")


class ConfigStore:
    """管理文件值与生效值；环境只覆盖读取结果，保存使用独立文件层。"""

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        """确定显式路径或 YAN_CONFIG_PATH，并捕获当前环境以便测试和复现。"""
        self._environ = dict(os.environ if environ is None else environ)
        selected = path if path is not None else self._environ.get("YAN_CONFIG_PATH")
        if selected is None or selected == "":
            selected = DEFAULT_CONFIG_PATH
        try:
            self.path = Path(selected).expanduser().resolve()
        except (TypeError, ValueError, OSError, RuntimeError):
            raise ConfigurationError(reason="read_failed") from None

    def _read_file(self) -> dict[str, Any]:
        """读 UTF-8（兼容 BOM）文件；不存在表示首次配置，损坏时绝不覆盖。"""
        try:
            raw = self.path.read_text(encoding="utf-8-sig")
        except FileNotFoundError:
            return {}
        except UnicodeError:
            raise ConfigurationError(reason="invalid_json") from None
        except (OSError, ValueError):
            raise ConfigurationError(reason="read_failed") from None
        try:
            data = json.loads(raw, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
        except (ValueError, RecursionError):
            raise ConfigurationError(reason="invalid_json") from None
        data = _check_fields(data)
        AppConfig(**data)
        return data

    def _effective(self, file_values: dict[str, Any]) -> AppConfig:
        """应用非空环境覆盖；数字显式解析，空串占位不清除文件值。"""
        values = dict(file_values)
        selected = self._environ.get('YAN_MODEL_PROVIDER')
        if selected and selected != file_values.get('model_provider', 'openai-compatible'):
            # 环境切换供应商时也必须隔离文件层的主模型凭据。
            profile = file_values.get('provider_configs', {}).get(selected, {}) if type(selected) is str else {}
            values.update(api_key=profile.get('api_key', ''), api_base=profile.get('api_base', ''), model='')
        for env_name, name in ENV_FIELDS.items():
            raw = self._environ.get(env_name)
            if raw is None or raw == "":
                continue
            if type(raw) is not str:
                raise ConfigurationError(field=name)
            try:
                if name == "port":
                    values[name] = int(raw)
                elif name == "request_timeout":
                    values[name] = float(raw)
                else:
                    values[name] = raw
            except (ValueError, OverflowError):
                raise ConfigurationError(field=name) from None
        return AppConfig(**values)

    def load(self) -> AppConfig:
        """按内置默认值、文件、非空环境变量的优先级返回校验后的快照。"""
        return self._effective(self._read_file())

    def save(self, updates: dict[str, Any]) -> AppConfig:
        """局部更新文件后返回生效快照；省略密钥保留原值，空串明确清除。"""
        updates = _check_fields(updates)
        file_values = self._read_file()
        updates = deepcopy(updates)
        # 在读取嵌套档案前验证原始更新，非法结构应返回配置错误。
        AppConfig(**{**file_values, **updates})
        previous = AppConfig(**file_values)
        selected_provider = updates.get('model_provider', previous.model_provider)
        profiles = deepcopy(updates.get('provider_configs', previous.provider_configs))
        if type(profiles) is not dict:
            raise ConfigurationError(field='provider_configs')
        if selected_provider != previous.model_provider:
            profiles.setdefault(previous.model_provider, {}).update(api_key=previous.api_key, api_base=previous.api_base)
            target = profiles.get(selected_provider, {}) if type(selected_provider) is str else {}
            updates.setdefault('api_key', target.get('api_key', ''))
            updates.setdefault('api_base', target.get('api_base', ''))
            updates.setdefault('model', '')
        if type(selected_provider) is str:
            target = profiles.setdefault(selected_provider, {})
            if type(target) is not dict:
                raise ConfigurationError(field='provider_configs')
            for name in ('api_key', 'api_base'):
                if name in updates:
                    target[name] = updates[name]
        updates['provider_configs'] = profiles
        file_values.update(updates)
        saved = AppConfig(**file_values)
        effective = self._effective(file_values)
        # 落盘需要原始密钥，仅在此内部保存边界使用 asdict。
        payload = json.dumps(asdict(saved), ensure_ascii=False, allow_nan=False, indent=2) + "\n"
        self._write_atomic(payload)
        return effective

    def _write_atomic(self, payload: str) -> None:
        """同目录写临时文件后替换；失败不退回原地截断写入，并尽力清理临时文件。"""
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", newline="\n", dir=self.path.parent,
                prefix=f".{self.path.name}.", suffix=".tmp", delete=False,
            ) as handle:
                temporary = Path(handle.name)
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        except (OSError, ValueError, UnicodeError):
            raise ConfigurationError(reason="write_failed") from None
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    # 操作系统拒绝删除时可能残留临时文件；不能因此回退为破坏原文件。
                    pass
