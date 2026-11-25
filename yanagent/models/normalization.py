"""厂商公开字段的白名单归一化、Thinking 策略与模型预算解析。"""

from dataclasses import replace
import logging
from yanagent.errors import ModelResponseError, ModelRefusalError


LOGGER = logging.getLogger('yanagent.models.normalization')


def model_options(config):
    """读取当前供应商和准确模型 ID 对应的用户声明，不猜测上下文大小。"""
    return config.provider_configs.get(config.model_provider, {}).get('model_options', {}).get(config.model, {})


def thinking_protocol(config):
    """已知模型族选取公开协议，用户可用模型选项明确覆盖或禁用。"""
    options = model_options(config)
    if 'thinking_protocol' in options:
        return options['thinking_protocol']
    vendor, name = config.model_provider, config.model.lower()
    if vendor == 'deepseek' or (vendor == 'openai-compatible' and name.startswith('deepseek')):
        return 'deepseek'
    if vendor == 'qwen' or (vendor == 'openai-compatible' and name.startswith(('qwen', 'qwq'))):
        return 'qwen'
    if vendor == 'openai' and name.startswith(('o1', 'o3', 'o4', 'gpt-5', 'gpt-6')):
        return 'openai'
    if vendor == 'claude':
        return 'claude-adaptive' if any(version in name for version in ('opus-4-6', 'sonnet-4-6')) else 'claude-enabled'
    if vendor == 'gemini':
        return 'gemini-budget' if name.startswith('gemini-2.5') else 'gemini-level'
    return 'none'


def context_limits(config, *, include_fallback=False):
    """取用户总上限与模型声明的较小值；备用链按最小窗口提前预留空间。"""
    options = model_options(config)
    window = min(config.max_context_tokens or options.get('context_window', 64_000), options.get('context_window', 1_000_000))
    output = min(config.max_output_tokens, options.get('max_output_tokens', 128_000), max(1, window // 4))
    if include_fallback and config.chat_fallback.get('enabled'):
        limits = [context_limits(replace(config, model_provider=link['provider'], model=link['model']))
                  for link in config.chat_fallback.get('chain', [])]
        window = min([window, *[pair[0] for pair in limits]])
        output = min(max([output, *[pair[1] for pair in limits]]), max(1, window // 4))
    LOGGER.debug('[normalization.py][context_limits] 模型预算已解析，provider=%s，model=%s，窗口=%d，输出预留=%d，包含备用=%s',
                 config.model_provider, config.model, window, output, include_fallback)
    return window, output


def reasoning_capability(config):
    """向既有设置界面声明可用的思考控制；不宣称 OpenAI Chat 提供思考正文。"""
    protocol = thinking_protocol(config)
    efforts = ['low', 'medium', 'high'] if protocol in {'openai', 'claude-adaptive', 'gemini-level'} else []
    return {'supported': protocol != 'none', 'options': [{'value': item, 'label': item} for item in efforts], 'default': 'high'}


def reasoning_text(value):
    """只接受供应商公开的文本字段，拒绝对象被字符串化后泄露到答案。"""
    if value is None:
        return ''
    if type(value) is not str:
        raise ModelResponseError()
    return value


def usage_fields(data, mapping):
    """复制明确返回的非负计数，缺失保持未知，禁止布尔值冒充 Token。"""
    if type(data) is not dict:
        raise ModelResponseError()
    result = {}
    for source, target in mapping.items():
        if source in data:
            value = data[source]
            if value is not None and (type(value) is not int or value < 0):
                raise ModelResponseError()
            result[target] = value
    return result


def normalize_usage(data, vendor='openai'):
    """统一总量、缓存与推理子计数，子计数不再次叠加已包含它的总数。"""
    if vendor == 'claude':
        result = usage_fields(data, {'input_tokens': 'input_tokens', 'output_tokens': 'output_tokens',
            'cache_read_input_tokens': 'cached_input_tokens', 'cache_creation_input_tokens': 'cache_creation_input_tokens'})
        # Claude input_tokens 不包含缓存读取和创建；缺失字段不凭空补零。
        if 'input_tokens' in result:
            values = [result['input_tokens'], result.get('cached_input_tokens', 0), result.get('cache_creation_input_tokens', 0)]
            result['input_tokens'] = None if None in values else sum(values)
    elif vendor == 'gemini':
        result = usage_fields(data, {'promptTokenCount': 'input_tokens', 'candidatesTokenCount': 'output_tokens',
            'thoughtsTokenCount': 'reasoning_tokens', 'cachedContentTokenCount': 'cached_input_tokens',
            'toolUsePromptTokenCount': 'tool_input_tokens', 'totalTokenCount': 'total_tokens'})
        if 'output_tokens' in result and 'reasoning_tokens' in result:
            values = [result['output_tokens'], result['reasoning_tokens']]
            result['output_tokens'] = None if None in values else sum(values)
    else:
        result = usage_fields(data, {'prompt_tokens': 'input_tokens', 'completion_tokens': 'output_tokens',
            'total_tokens': 'total_tokens', 'prompt_cache_hit_tokens': 'cached_input_tokens',
            'prompt_cache_miss_tokens': 'uncached_input_tokens'})
        for field, mapping in (
            ('prompt_tokens_details', {'cached_tokens': 'cached_input_tokens'}),
            ('completion_tokens_details', {'reasoning_tokens': 'reasoning_tokens'}),
        ):
            if data.get(field) is not None:
                result.update(usage_fields(data[field], mapping))
    if vendor == 'claude' and 'input_tokens' in result and 'output_tokens' in result:
        values = [result['input_tokens'], result['output_tokens'], result.get('tool_input_tokens', 0)]
        result['total_tokens'] = None if None in values else sum(values)
    return result


def finish_reason(reason, vendor, has_calls, *, partial=False):
    """收敛正常结束/工具/截断，拒答或未知结束不能伪装成完成或执行工具。"""
    if partial and reason is None:
        return None
    if vendor == 'gemini' and reason in {'SAFETY', 'RECITATION', 'PROHIBITED_CONTENT', 'BLOCKLIST', 'SPII', 'IMAGE_SAFETY'}:
        raise ModelRefusalError()
    if reason in {'refusal', 'content_filter'}:
        raise ModelRefusalError()
    maps = {
        'openai': {'stop': 'stop', 'tool_calls': 'tool_calls', 'length': 'length'},
        'claude': {'end_turn': 'stop', 'stop_sequence': 'stop', 'tool_use': 'tool_calls',
                   'max_tokens': 'length', 'model_context_window_exceeded': 'context_length'},
        'gemini': {'STOP': 'tool_calls' if has_calls else 'stop', 'MAX_TOKENS': 'length'},
    }
    if type(reason) is not str or reason not in maps[vendor]:
        raise ModelResponseError()
    result = maps[vendor][reason]
    if (result == 'tool_calls') != bool(has_calls):
        raise ModelResponseError()
    return result
