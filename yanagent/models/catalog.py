"""供应商目录及当前适配能力；示例模型名可被用户目录覆盖，不代表账号可用性。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderSpec:
    """声明协议、默认入口和已实现的文本/工具能力。"""

    id: str
    label: str
    protocol: str
    api_base: str
    models: tuple[str, ...]
    streaming: bool = True
    tool_calling: bool = True


PROVIDERS = {
    spec.id: spec for spec in (
        ProviderSpec('openai-compatible', 'OpenAI 兼容接口', 'openai', '', ('gpt-4o-mini', 'deepseek-chat', 'qwen-plus')),
        ProviderSpec('openai', 'OpenAI / GPT', 'openai', 'https://api.openai.com/v1', ('gpt-4o-mini',)),
        ProviderSpec('deepseek', 'DeepSeek', 'openai', 'https://api.deepseek.com', ('deepseek-flash', 'deepseek-chat')),
        ProviderSpec('qwen', 'Qwen / 通义千问', 'openai', '', ('qwen-plus', 'qwen-turbo')),
        ProviderSpec('claude', 'Claude / Anthropic', 'claude', 'https://api.anthropic.com/v1', ('claude-sonnet-4-5',)),
        ProviderSpec('gemini', 'Google Gemini', 'gemini', 'https://generativelanguage.googleapis.com/v1beta', ('gemini-2.5-flash',)),
    )
}
