"""模型设置接口适配，兼容既有桌面目录、凭据卡片与备用链界面。"""

from copy import deepcopy
from dataclasses import replace

from yanagent.config import AppConfig, MASKED_SECRET
from yanagent.errors import RequestValidationError
from .catalog import PROVIDERS
from .factory import select_model
from .normalization import context_limits, reasoning_capability


def model_names(config, provider):
    """返回用户维护的目录与内置示例，隐藏项不会重新混入目录。"""
    profile = config.provider_configs.get(provider, {})
    names = ([config.model] if config.model_provider == provider and config.model else [])
    names += profile.get('models', []) + list(PROVIDERS[provider].models)
    return list(dict.fromkeys(n for n in names if n not in profile.get('hidden', [])))


def models_payload(config):
    """仅暴露脱敏凭据与已实现能力；未实现的视觉和语音入口保持关闭。"""
    providers = []
    provider_models = {}
    for provider, spec in PROVIDERS.items():
        profile = select_model(config, provider, config.model or 'unselected')
        names = model_names(config, provider)
        provider_models[provider] = names
        options = config.provider_configs.get(provider, {}).get('model_options', {})
        catalog = [{'name': n, 'capabilities': ['text'],
            **{key: value for key, value in options.get(n, {}).items() if key in {'context_window', 'max_output_tokens'}}} for n in names]
        providers.append({
            'id': provider, 'label': {'zh': spec.label, 'en': spec.label},
            'configured': bool(profile.api_key and profile.api_base), 'is_custom': False,
            'active': provider == config.model_provider, 'api_key_field': 'api_key', 'api_base_field': 'api_base',
            'api_key_masked': MASKED_SECRET if profile.api_key else '', 'api_base': profile.api_base,
            'api_base_default': spec.api_base, 'api_base_placeholder': spec.api_base or '请输入账号对应的 API Base',
            'catalog': catalog, 'seed': [{'name': n, 'capabilities': ['text']} for n in spec.models],
            'effective': catalog, 'models': names, 'hidden': config.provider_configs.get(provider, {}).get('hidden', []),
            'capability_declaration': {'protocol': spec.protocol, 'text': True, 'streaming': spec.streaming,
                                       'tool_calling': spec.tool_calling, 'vision': False},
        })
    empty = {'editable': False, 'current_provider': '', 'current_model': '', 'providers': []}
    return {'status': 'success', 'providers': providers, 'capabilities': {
        'chat': {'editable': True, 'current_provider': config.model_provider, 'current_model': config.model,
                 'context_window': context_limits(config, include_fallback=True)[0],
                 'providers': list(PROVIDERS), 'provider_models': provider_models},
        'chat_fallback': {'editable': True, **deepcopy(config.chat_fallback), 'providers': list(PROVIDERS),
                          'provider_models': provider_models, 'primary_provider': config.model_provider, 'primary_model': config.model},
        **{name: dict(empty) for name in ('vision', 'asr', 'tts', 'embedding', 'image')},
        'search': {'editable': False, 'providers': [], 'available': False},
    }}


def save_model_action(store, payload):
    """在文件配置层更新目录/凭据，避免把环境变量覆盖的密钥回写到磁盘。"""
    if type(payload) is not dict:
        raise RequestValidationError(reason='invalid_json', field='body')
    action = payload.get('action')
    config = AppConfig(**store._read_file())
    profiles = deepcopy(config.provider_configs)
    provider = payload.get('provider_id')
    if action == 'set_capability' and payload.get('capability') == 'chat_fallback':
        if set(payload) - {'action', 'capability', 'enabled', 'chain'}:
            raise RequestValidationError(reason='unknown_field', field='body')
        result = store.save({'chat_fallback': {'enabled': payload.get('enabled', False), 'chain': payload.get('chain', [])}})
        return {'status': 'success', 'applied': result.to_dict()}
    if type(provider) is not str or provider not in PROVIDERS:
        raise RequestValidationError(reason='unsupported', field='provider_id')
    current = profiles.setdefault(provider, {})
    if provider == config.model_provider:
        current.update(api_key=config.api_key, api_base=config.api_base)
    updates = {}
    if action == 'set_provider':
        allowed = {'action', 'provider_id', 'api_key', 'api_base'}
        if not {'api_key', 'api_base'} & set(payload):
            raise RequestValidationError(reason='missing', field='updates')
        for key in ('api_key', 'api_base'):
            if key in payload and payload[key] != MASKED_SECRET:
                current[key] = payload[key]
        if not current.get('api_base'):
            current['api_base'] = PROVIDERS[provider].api_base or ('https://api.openai.com/v1' if provider == 'openai-compatible' else '')
        if provider == config.model_provider:
            updates.update(api_key=current.get('api_key', ''), api_base=current.get('api_base', ''))
    elif action == 'set_capability':
        allowed = {'action', 'capability', 'provider_id', 'model'}
        if payload.get('capability') != 'chat' or type(payload.get('model')) is not str or not payload['model'].strip():
            raise RequestValidationError(reason='invalid', field='model')
        # 保存旧主模型配置，切换时不会把其密钥带到新供应商。
        profiles.setdefault(config.model_provider, {}).update(api_key=config.api_key, api_base=config.api_base)
        selected = select_model(replace(config, provider_configs=profiles), provider, payload['model'])
        updates.update(model_provider=provider, model=selected.model, api_base=selected.api_base, api_key=selected.api_key)
    elif action == 'delete_provider':
        allowed = {'action', 'provider_id'}
        profiles.pop(provider, None)
        if provider == config.model_provider:
            updates.update(api_base='', api_key='', model='')
    elif action == 'save_catalog':
        allowed = {'action', 'provider_id', 'models', 'hidden'}
        models = payload.get('models', [])
        if type(models) is not list or any(type(item) is not dict or type(item.get('name')) is not str for item in models):
            raise RequestValidationError(reason='invalid', field='model')
        if any(set(item) - {'name', 'capabilities', 'context_window', 'max_output_tokens'} or item.get('capabilities', ['text']) != ['text'] for item in models):
            raise RequestValidationError(reason='unsupported', field='capability')
        options = current.setdefault('model_options', {})
        # 目录提交的是完整覆盖层；恢复预设时删除旧预算，保留手工声明的协议选项。
        for saved in options.values():
            saved.pop('context_window', None)
            saved.pop('max_output_tokens', None)
        for item in models:
            saved = options.setdefault(item['name'], {})
            for key in ('context_window', 'max_output_tokens'):
                saved.pop(key, None)
                if key in item:
                    saved[key] = item[key]
        current.update(models=[item['name'] for item in models], hidden=payload.get('hidden', []))
    else:
        raise RequestValidationError(reason='unsupported', field='action')
    if set(payload) - allowed:
        raise RequestValidationError(reason='unknown_field', field='body')
    updates['provider_configs'] = profiles
    result = store.save(updates)
    return {'status': 'success', 'applied': result.to_dict()}
