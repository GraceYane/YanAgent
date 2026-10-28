"""聊天应用层：连接桌面接口、配置存储与统一模型 Provider。"""

from __future__ import annotations

import asyncio
import logging
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from yanagent.config import AppConfig, ConfigStore, MASKED_SECRET
from yanagent.context import ModelContext, PromptContextBuilder, RuntimeIdentity
from yanagent.contracts import Message, ModelReply
from yanagent.errors import (
    AgentError,
    ConfigurationError,
    RequestValidationError,
    SessionAlreadyExistsError,
    SessionNotFoundError,
    UnexpectedToolCallError,
)
from yanagent.models import ModelProvider, OpenAICompatibleProvider
from yanagent.sessions import RunStore, SessionStore
from yanagent.sessions.runs import TerminalRunStatus
from yanagent.tools import ToolManager, register_safe_example_tools


LOGGER = logging.getLogger("yanagent.chat")
PROVIDER_ID = "openai-compatible"
DEFAULT_API_BASE = "https://api.openai.com/v1"
DEFAULT_MODEL_SUGGESTIONS = ("gpt-4o-mini", "deepseek-chat", "qwen-plus")
MAX_MESSAGE_CHARS = 200_000
ProviderFactory = Callable[[AppConfig], ModelProvider]


@dataclass(frozen=True)
class PreparedChat:
    """完成同步校验后的单轮聊天快照，可交给常驻异步运行环境执行。"""

    session_id: str
    message: Message
    config: AppConfig
    provider: ModelProvider


@dataclass(frozen=True)
class ChatContext:
    """本轮模型输入及已落库用户消息序号，供完成事件关联桌面气泡。"""

    messages: tuple[Message, ...]
    tools: tuple[dict[str, Any], ...]
    user_sequence: int | None


def _require_text(
    payload: dict[str, Any], field: str, *, maximum: int = 256, allow_multiline: bool = False,
) -> str:
    """读取必填文本，拒绝空白、控制字符和超过接口上限的值。"""
    value = payload.get(field)
    if value is None:
        raise RequestValidationError(reason="missing", field=field)
    if (
        type(value) is not str
        or not value.strip()
        or len(value) > maximum
        or any(
            ord(char) < 32 and (not allow_multiline or char not in "\n\r\t")
            for char in value
        )
    ):
        reason = "too_large" if type(value) is str and len(value) > maximum else "invalid"
        raise RequestValidationError(reason=reason, field=field)
    return value


def _ensure_keys(payload: dict[str, Any], allowed: set[str]) -> None:
    """拒绝接口未声明的字段，防止拼写错误被静默忽略。"""
    if any(type(key) is not str or key not in allowed for key in payload):
        raise RequestValidationError(reason="unknown_field", field="body")


class YanAgentApplication:
    """封装聊天、会话历史和配置接口，供 HTTP 与离线测试共同调用。"""

    def __init__(
        self,
        config_store: ConfigStore | None = None,
        *,
        provider_factory: ProviderFactory | None = None,
        session_store: SessionStore | None = None,
        run_store: RunStore | None = None,
        tool_manager: ToolManager | None = None,
        context_builder: PromptContextBuilder | None = None,
    ) -> None:
        """注入配置、Provider、仓储、工具注册表和统一上下文构建器。"""
        self.config_store = config_store if config_store is not None else ConfigStore()
        self.provider_factory = (
            provider_factory if provider_factory is not None else OpenAICompatibleProvider
        )
        self.session_store = session_store
        self.run_store = run_store
        if tool_manager is None:
            tool_manager = ToolManager()
            register_safe_example_tools(tool_manager)
        elif not isinstance(tool_manager, ToolManager):
            raise TypeError("tool_manager 必须是 ToolManager")
        self.tool_manager = tool_manager
        if context_builder is None:
            context_builder = PromptContextBuilder()
        elif not isinstance(context_builder, PromptContextBuilder):
            raise TypeError("context_builder 必须是 PromptContextBuilder")
        self.context_builder = context_builder
        self._config_lock = threading.RLock()

    def tools_payload(self) -> dict[str, Any]:
        """返回桌面工具页使用的注册目录，不暴露 handler、参数或权限内部字段。"""
        tools = [
            {"name": item["name"], "description": item["description"]}
            for item in self.tool_manager.catalog()
        ]
        LOGGER.info(
            "[chat.py][YanAgentApplication.tools_payload] 已生成工具列表，数量=%d",
            len(tools),
        )
        return {"status": "success", "tools": tools}

    def load_config(self) -> AppConfig:
        """读取一次经过文件和环境覆盖后的不可变配置快照。"""
        with self._config_lock:
            return self.config_store.load()

    def save_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        """接收桌面旧配置字段，只把 P01-02 支持的设置持久化。"""
        if type(payload) is not dict:
            raise RequestValidationError(reason="invalid_json", field="body")
        _ensure_keys(payload, {"updates"})
        updates = payload.get("updates")
        if type(updates) is not dict:
            raise RequestValidationError(reason="invalid", field="updates")

        allowed = {
            "host", "port", "model_provider", "api_base", "model", "api_key",
            "request_timeout", "permission_mode", "bot_type", "agent_permission_mode",
            "use_linkai", "cow_lang",
        }
        if any(type(key) is not str or key not in allowed for key in updates):
            raise RequestValidationError(reason="unknown_field", field="updates")

        normalized: dict[str, Any] = {}
        for key, value in updates.items():
            if key in {"use_linkai", "cow_lang"}:
                # 复制界面会发送这两个产品层字段；P01 配置不持久化它们。
                continue
            target = {
                "bot_type": "model_provider",
                "agent_permission_mode": "permission_mode",
            }.get(key, key)
            if target == "api_key" and value == MASKED_SECRET:
                continue
            normalized[target] = value

        if not normalized:
            config = self.load_config()
        else:
            with self._config_lock:
                config = self.config_store.save(normalized)
        LOGGER.info(
            "[chat.py][YanAgentApplication.save_config] 配置保存完成，变更字段=%s",
            sorted(normalized),
        )
        return {"status": "success", "applied": config.to_dict()}

    def config_payload(self) -> dict[str, Any]:
        """把精简配置映射为复制桌面端 `/config` 所需的兼容字段。"""
        config = self.load_config()
        models = self._model_names(config)
        return {
            "status": "success",
            "use_agent": True,
            "title": "YanAgent",
            "model": config.model,
            "bot_type": config.model_provider,
            "use_linkai": False,
            "channel_type": "web",
            "agent_max_context_tokens": 64_000,
            "agent_max_context_turns": 20,
            "agent_max_steps": 20,
            "agent_permission_mode": config.permission_mode,
            "permission_modes": ["deny", "ask", "allow"],
            "enable_thinking": False,
            "reasoning_effort": "",
            "reasoning_effort_by_model": {},
            "subagent_enabled": False,
            "self_evolution_enabled": False,
            "api_bases": {"api_base": config.api_base},
            "api_keys": {"api_key": MASKED_SECRET if config.api_key else ""},
            "providers": {
                PROVIDER_ID: {
                    "label": {"zh": "OpenAI 兼容接口", "en": "OpenAI-compatible"},
                    "models": models,
                    "api_base_key": "api_base",
                    "api_base_default": DEFAULT_API_BASE,
                    "api_base_placeholder": DEFAULT_API_BASE,
                    "api_key_field": "api_key",
                }
            },
        }

    def models_payload(self) -> dict[str, Any]:
        """返回模型控制台可渲染的单 Provider 目录和聊天能力状态。"""
        config = self.load_config()
        models = self._model_names(config)
        catalog = [{"name": name, "capabilities": ["text"]} for name in models]
        empty = {"editable": False, "current_provider": "", "current_model": "", "providers": []}
        capabilities = {
            "chat": {
                "editable": True,
                "current_provider": config.model_provider,
                "current_model": config.model,
                "providers": [PROVIDER_ID],
                "provider_models": {PROVIDER_ID: models},
            },
            "vision": dict(empty),
            "asr": dict(empty),
            "tts": dict(empty),
            "embedding": dict(empty),
            "image": dict(empty),
            "search": {"editable": False, "providers": [], "available": False},
        }
        return {
            "status": "success",
            "providers": [{
                "id": PROVIDER_ID,
                "label": {"zh": "OpenAI 兼容接口", "en": "OpenAI-compatible"},
                "configured": bool(config.api_base and config.api_key),
                "is_custom": False,
                "active": True,
                "api_key_field": "api_key",
                "api_base_field": "api_base",
                "api_key_masked": MASKED_SECRET if config.api_key else "",
                "api_base": config.api_base,
                "api_base_default": DEFAULT_API_BASE,
                "api_base_placeholder": DEFAULT_API_BASE,
                "catalog": catalog,
                "hidden": [],
                "seed": catalog,
                "effective": catalog,
                "models": models,
            }],
            "capabilities": capabilities,
        }

    def save_model_action(self, payload: dict[str, Any]) -> dict[str, Any]:
        """处理本阶段的凭据保存、聊天模型选择和清除动作。"""
        if type(payload) is not dict:
            raise RequestValidationError(reason="invalid_json", field="body")
        action = payload.get("action")
        if type(action) is not str:
            raise RequestValidationError(reason="missing", field="action")

        if action == "set_provider":
            _ensure_keys(payload, {"action", "provider_id", "api_key", "api_base"})
            self._require_provider(payload)
            updates = {
                key: payload[key]
                for key in ("api_key", "api_base")
                if key in payload and payload[key] != MASKED_SECRET
            }
            if not updates:
                raise RequestValidationError(reason="missing", field="updates")
        elif action == "set_capability":
            _ensure_keys(payload, {"action", "capability", "provider_id", "model"})
            self._require_provider(payload)
            if payload.get("capability") != "chat":
                raise RequestValidationError(reason="unsupported", field="capability")
            updates = {"model": _require_text(payload, "model", maximum=256)}
        elif action == "delete_provider":
            _ensure_keys(payload, {"action", "provider_id"})
            self._require_provider(payload)
            updates = {"api_base": "", "api_key": "", "model": ""}
        else:
            raise RequestValidationError(reason="unsupported", field="action")

        with self._config_lock:
            if (
                action == "set_provider"
                and "api_key" in updates
                and "api_base" not in updates
                and not self.config_store.load().api_base
            ):
                updates["api_base"] = DEFAULT_API_BASE
            config = self.config_store.save(updates)
        LOGGER.info(
            "[chat.py][YanAgentApplication.save_model_action] 模型配置动作完成，动作=%s，变更字段=%s",
            action,
            sorted(updates),
        )
        return {"status": "success", "applied": config.to_dict()}

    async def chat(
        self, payload: dict[str, Any], *, request_id: str | None = None,
    ) -> dict[str, Any]:
        """校验一条桌面消息，调用非流式 Provider 并返回内联完整回答。"""
        request_id = request_id or f"run-{uuid.uuid4().hex}"
        prepared = self.prepare_chat(payload)
        LOGGER.info(
            "[chat.py][YanAgentApplication.chat] 开始普通聊天请求，request_id=%s，provider=%s，model=%s",
            request_id,
            prepared.config.model_provider,
            prepared.config.model or "<未配置>",
        )
        context = await self.begin_chat(prepared, request_id=request_id)
        run_started = await self.start_run(prepared, request_id=request_id)
        try:
            reply = await prepared.provider.complete(
                context.messages, tools=context.tools,
            )
            if reply.tool_calls:
                raise UnexpectedToolCallError()
            assistant_sequence = await self.finish_chat(
                prepared, reply, request_id=request_id,
            )
            if run_started:
                await self.finish_run(
                    request_id,
                    prepared.session_id,
                    status="completed",
                    finish_reason=reply.finish_reason,
                    usage=reply.usage,
                )
        except asyncio.CancelledError:
            if run_started:
                await self.finish_run(
                    request_id,
                    prepared.session_id,
                    status="cancelled",
                    finish_reason="cancelled",
                )
            raise
        except AgentError as error:
            if run_started:
                await self.finish_run(
                    request_id,
                    prepared.session_id,
                    status="failed",
                    finish_reason="error",
                    error_code=error.code,
                )
            raise
        except Exception:
            if run_started:
                await self.finish_run(
                    request_id,
                    prepared.session_id,
                    status="failed",
                    finish_reason="error",
                    error_code="unexpected_error",
                )
            raise
        LOGGER.info(
            "[chat.py][YanAgentApplication.chat] 普通聊天请求完成，request_id=%s，上下文消息数=%d，输出字符数=%d",
            request_id, len(context.messages), len(reply.content),
        )
        return {
            "status": "success",
            "request_id": request_id,
            "stream": False,
            "inline_reply": reply.content,
            "speaker": "default",
            "received_session_id": prepared.session_id,
            "finish_reason": reply.finish_reason,
            "usage": reply.usage,
            "user_seq": context.user_sequence,
            "bot_seq": assistant_sequence,
        }

    async def start_run(self, prepared: PreparedChat, *, request_id: str) -> bool:
        """在用户消息落库后创建运行记录；无 RunStore 的离线模式返回 False。"""
        if self.run_store is None:
            return False
        await self.run_store.create(
            request_id,
            prepared.session_id,
            status="running",
            metadata={
                "provider": prepared.config.model_provider,
                "model": prepared.config.model,
            },
        )
        return True

    async def finish_run(
        self,
        request_id: str,
        session_id: str,
        *,
        status: TerminalRunStatus,
        finish_reason: str | None = None,
        error_code: str | None = None,
        usage: dict[str, int | None] | None = None,
    ) -> bool:
        """保存 Run 终态；重复完成返回 False，并留下可定位的中文日志。"""
        if self.run_store is None:
            return False
        try:
            changed = await self.run_store.finish(
                request_id,
                session_id,
                status=status,
                finish_reason=finish_reason,
                error_code=error_code,
                usage={} if usage is None else usage,
            )
        except AgentError as error:
            if status == "completed":
                raise
            LOGGER.error(
                "[chat.py][YanAgentApplication.finish_run] 失败路径的 Run 终态保存失败，request_id=%s，error_code=%s",
                request_id,
                error.code,
            )
            return False
        if not changed:
            LOGGER.warning(
                "[chat.py][YanAgentApplication.finish_run] Run 不存在或已进入终态，request_id=%s，目标状态=%s",
                request_id,
                status,
            )
        return changed

    def recover_runs_on_startup(self) -> int:
        """在 HTTP 接流量前中断上次进程遗留的活动 Run。"""
        if self.run_store is None:
            return 0
        return self.run_store.recover_unfinished_on_startup()

    async def begin_chat(
        self, prepared: PreparedChat, *, request_id: str
    ) -> ChatContext:
        """加载历史、组装统一模型上下文，再持久化本轮用户消息。"""
        current = Message(
            role="user",
            content=prepared.message.content,
            metadata={"request_id": request_id},
        )
        if self.session_store is None:
            assembled = self._assemble_model_context(
                prepared, request_id=request_id, history=[], current=current,
            )
            LOGGER.info(
                "[chat.py][YanAgentApplication.begin_chat] 未注入会话仓储，使用无状态测试模式，request_id=%s",
                request_id,
            )
            return ChatContext(
                messages=assembled.messages,
                tools=assembled.tools,
                user_sequence=None,
            )
        # 生产持久化链路在落库前先拒绝缺失配置，避免留下从未调用模型的消息。
        # 无仓储的离线 Fake Provider 模式由 Provider 自己决定是否要求配置。
        prepared.config.require_model_ready()
        await self._ensure_session(prepared.session_id)
        stored = await self.session_store.complete_history(prepared.session_id)
        assembled = self._assemble_model_context(
            prepared,
            request_id=request_id,
            history=[record.message for record in stored],
            current=current,
        )
        current_records = await self.session_store.append(prepared.session_id, [current])
        LOGGER.info(
            "[chat.py][YanAgentApplication.begin_chat] 统一上下文已组装且用户消息已落库，request_id=%s，session_id=%s，历史消息数=%d，工具数=%d",
            request_id,
            prepared.session_id,
            len(stored),
            len(assembled.tools),
        )
        return ChatContext(
            messages=assembled.messages,
            tools=assembled.tools,
            user_sequence=current_records[0].sequence,
        )

    def _assemble_model_context(
        self,
        prepared: PreparedChat,
        *,
        request_id: str,
        history: list[Message],
        current: Message,
    ) -> ModelContext:
        """把可信身份、历史、当前输入和工具快照交给统一构建器。"""
        user_id = self.session_store.user_id if self.session_store is not None else "local"
        agent_id = self.session_store.agent_id if self.session_store is not None else "default"
        identity = RuntimeIdentity(
            user_id=user_id,
            agent_id=agent_id,
            session_id=prepared.session_id,
            request_id=request_id,
        )
        return self.context_builder.build(
            identity=identity,
            history=history,
            current=current,
            tools=self.tool_manager.schemas(),
        )

    async def finish_chat(
        self, prepared: PreparedChat, reply: ModelReply, *, request_id: str
    ) -> int | None:
        """在回答对外标记完成前保存完整 Assistant 消息并返回稳定序号。"""
        if self.session_store is None:
            return None
        assistant = reply.to_message()
        assistant.metadata["request_id"] = request_id
        assistant.metadata["usage"] = reply.usage
        records = await self.session_store.append(prepared.session_id, [assistant])
        LOGGER.info(
            "[chat.py][YanAgentApplication.finish_chat] Assistant 完整回答已落库，request_id=%s，session_id=%s",
            request_id,
            prepared.session_id,
        )
        return records[0].sequence

    async def _ensure_session(self, session_id: str) -> None:
        """保证目标会话存在，并处理并发首次创建造成的重复竞态。"""
        if self.session_store is None:
            return
        try:
            await self.session_store.get(session_id)
            return
        except SessionNotFoundError:
            pass
        try:
            await self.session_store.create(
                session_id,
                metadata={"created_by": "chat"},
            )
        except SessionAlreadyExistsError:
            # 另一请求可能刚在 get 与 create 之间创建了同一会话。
            pass
        LOGGER.info(
            "[chat.py][YanAgentApplication._ensure_session] 会话已就绪，session_id=%s",
            session_id,
        )

    def prepare_chat(self, payload: dict[str, Any]) -> PreparedChat:
        """同步固定请求、配置和 Provider；具体 Provider 在执行前检查必需配置。"""
        session_id, message = self._validate_chat_payload(payload)
        config = self.load_config()
        return PreparedChat(
            session_id=session_id,
            message=Message(role="user", content=message),
            config=config,
            provider=self.provider_factory(config),
        )

    def _validate_chat_payload(self, payload: dict[str, Any]) -> tuple[str, str]:
        """检查聊天正文及本阶段允许的兼容字段，不执行附件或语音请求。"""
        if type(payload) is not dict:
            raise RequestValidationError(reason="invalid_json", field="body")
        allowed = {
            "session_id", "message", "stream", "attachments", "is_voice", "lang",
            "agent_id", "speaker_agent_id",
        }
        _ensure_keys(payload, allowed)
        session_id = _require_text(payload, "session_id", maximum=256)
        message = _require_text(
            payload, "message", maximum=MAX_MESSAGE_CHARS, allow_multiline=True,
        )
        if "stream" in payload and type(payload["stream"]) is not bool:
            raise RequestValidationError(reason="invalid", field="stream")
        if payload.get("attachments") not in (None, []):
            raise RequestValidationError(reason="unsupported", field="attachments")
        if payload.get("is_voice") not in (None, False):
            raise RequestValidationError(reason="unsupported", field="is_voice")
        for field in ("agent_id", "speaker_agent_id"):
            if payload.get(field) not in (None, "", "default"):
                raise RequestValidationError(reason="unsupported", field=field)
        if "lang" in payload and payload["lang"] is not None and type(payload["lang"]) is not str:
            raise RequestValidationError(reason="invalid", field="body")
        return session_id, message

    def _require_provider(self, payload: dict[str, Any]) -> None:
        """保证桌面动作只修改当前阶段唯一的兼容 Provider。"""
        if payload.get("provider_id") != PROVIDER_ID:
            raise RequestValidationError(reason="unsupported", field="provider_id")

    def _model_names(self, config: AppConfig) -> list[str]:
        """优先展示已保存模型；未配置时提供可替换的常见示例名称。"""
        names = ([config.model] if config.model else []) + list(DEFAULT_MODEL_SUGGESTIONS)
        return list(dict.fromkeys(name for name in names if name))


def ensure_application_ready(application: YanAgentApplication) -> None:
    """启动阶段验证配置文件可读，但不要求此时已经填写模型密钥。"""
    try:
        application.load_config()
    except ConfigurationError:
        LOGGER.exception("[chat.py][ensure_application_ready] 配置加载失败，服务拒绝启动")
        raise
