"""模型选择、凭据隔离及有界备用链；仅重发模型输入，不执行或重放工具。"""

from __future__ import annotations

import logging
import asyncio
from copy import deepcopy
from contextlib import aclosing
from dataclasses import replace

from yanagent.config import AppConfig
from yanagent.errors import (
    AgentError, ConfigurationError, ModelConnectionError, ModelTimeoutError, ModelServerError,
    RateLimitError, EmptyModelResponseError, ModelStreamInterruptedError,
)
from .catalog import PROVIDERS
from .native import NativeProvider
from .openai_compatible import OpenAICompatibleProvider


LOGGER = logging.getLogger('yanagent.models.factory')
FALLBACK_ERRORS = (ModelConnectionError, ModelTimeoutError, ModelServerError, RateLimitError, EmptyModelResponseError)


def select_model(config: AppConfig, provider: str, model: str) -> AppConfig:
    """生成当前会话独立快照；不同供应商绝不复用主供应商凭据或入口。"""
    if provider not in PROVIDERS or not isinstance(model, str) or not model.strip():
        raise ConfigurationError(field='model_provider')
    if provider == config.model_provider:
        profile = config.provider_configs.get(provider, {})
        return replace(config, model=model, api_base=config.api_base or profile.get('api_base') or PROVIDERS[provider].api_base,
                       api_key=config.api_key or profile.get('api_key', ''))
    profile = config.provider_configs.get(provider, {})
    return replace(config, model_provider=provider, model=model,
                   api_base=profile.get('api_base') or PROVIDERS[provider].api_base,
                   api_key=profile.get('api_key', ''))


def create_single_provider(config: AppConfig):
    """根据公开协议创建一个供应商实例，兼容接口复用既有适配器。"""
    if config.model_provider not in PROVIDERS:
        raise ConfigurationError(field='model_provider')
    if PROVIDERS[config.model_provider].protocol == 'openai':
        return OpenAICompatibleProvider(config)
    return NativeProvider(config)


def create_provider_chain(config: AppConfig, factory=create_single_provider):
    """固定主模型和最多四个备用模型的配置；运行中改设置不影响本次快照。"""
    primary = factory(config)
    if not config.chat_fallback.get('enabled'):
        return primary
    candidates = [(config.model_provider, config.model, primary)]
    for link in config.chat_fallback.get('chain', []):
        pair = (link['provider'], link['model'])
        if pair == (config.model_provider, config.model):
            continue
        selected = select_model(config, *pair)
        selected.require_model_ready()
        candidates.append((*pair, factory(selected)))
    return FallbackProvider(candidates)


class FallbackProvider:
    """按序尝试备用模型，切换位置仅前进；部分流输出后禁止自动切换。"""

    name = 'fallback-chain'

    def __init__(self, candidates):
        """保存本次 Run 专属候选与当前选择，不与其他会话共享切换状态。"""
        self.candidates = candidates
        self.index = 0
        self.transitions = []
        self.failed_usage = {}

    def _remember_empty_usage(self, reply):
        """备用切换前保留空响应的已知用量，不把已知消耗静默丢掉。"""
        for key, value in reply.usage.items():
            previous = self.failed_usage.get(key, 0)
            self.failed_usage[key] = None if previous is None or value is None else previous + value

    def _attach_failed_usage(self, error):
        """失败向上抛出前移交已知用量，重试时避免同一份用量重复累计。"""
        usage = deepcopy(getattr(error, 'usage', {}))
        for key, value in self.failed_usage.items():
            previous = usage.get(key, 0)
            usage[key] = None if previous is None or value is None else previous + value
        error.usage = usage
        self.failed_usage = {}

    def _advance(self, error):
        """只对可恢复的模型故障切换；不因拒答、权限或非法请求绕过主模型。"""
        if not isinstance(error, FALLBACK_ERRORS) or self.index + 1 >= len(self.candidates):
            return False
        self.transitions.append({'provider': self.candidates[self.index][0],
                                 'model': self.candidates[self.index][1], 'error_code': error.code})
        self.index += 1
        provider, model, _ = self.candidates[self.index]
        LOGGER.warning('[factory.py][FallbackProvider._advance] 切换备用模型，错误码=%s，provider=%s，model=%s',
                       error.code, provider, model)
        return True

    def _tag(self, reply):
        """把实际使用的供应商和模型写入白名单元数据以供执行记录查询。"""
        reply.provider_metadata.update(provider=self.candidates[self.index][0], model=self.candidates[self.index][1])
        reply.provider_metadata['fallback_transitions'] = deepcopy(self.transitions)
        for key, value in self.failed_usage.items():
            previous = reply.usage.get(key, 0)
            reply.usage[key] = None if previous is None or value is None else previous + value
        self.failed_usage = {}
        return reply

    async def complete(self, messages, *, tools=()):
        """失败后只重发当前模型上下文，保留已有 Tool Result。"""
        while True:
            try:
                reply = await self.candidates[self.index][2].complete(messages, tools=tools)
                if not reply.content.strip() and not reply.tool_calls:
                    self._remember_empty_usage(reply)
                    raise EmptyModelResponseError()
                return self._tag(reply)
            except FALLBACK_ERRORS as error:
                previous_provider = self.candidates[self.index][0]
                if not self._advance(error):
                    self._attach_failed_usage(error)
                    raise
                if previous_provider == self.candidates[self.index][0] and error.retry_after_seconds:
                    await asyncio.sleep(error.retry_after_seconds)
            except AgentError as error:
                self._attach_failed_usage(error)
                raise

    async def stream(self, messages, *, tools=()):
        """首个对外增量前允许切换；已输出文本或工具参数时明确中断。"""
        while True:
            emitted = False
            completed = False
            try:
                async with aclosing(self.candidates[self.index][2].stream(messages, tools=tools)) as stream:
                    async for event in stream:
                        if event.kind in {'text_delta', 'tool_call_delta', 'reasoning_delta'}:
                            emitted = True
                        if event.kind == 'completed':
                            if event.reply is None or (not event.reply.content.strip() and not event.reply.tool_calls):
                                if event.reply is not None:
                                    self._remember_empty_usage(event.reply)
                                raise EmptyModelResponseError()
                            self._tag(event.reply)
                            completed = True
                        yield event
                if not completed:
                    raise EmptyModelResponseError()
                return
            except FALLBACK_ERRORS as error:
                if emitted or completed:
                    interrupted = ModelStreamInterruptedError()
                    interrupted.usage = deepcopy(getattr(error, 'usage', {}))
                    self._attach_failed_usage(interrupted)
                    raise interrupted from None
                previous_provider = self.candidates[self.index][0]
                if not self._advance(error):
                    self._attach_failed_usage(error)
                    raise
                if previous_provider == self.candidates[self.index][0] and error.retry_after_seconds:
                    await asyncio.sleep(error.retry_after_seconds)
            except AgentError as error:
                self._attach_failed_usage(error)
                raise
