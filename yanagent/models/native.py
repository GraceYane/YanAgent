"""Claude Messages 与 Gemini GenerateContent 的文本及函数工具原生适配。"""

from __future__ import annotations

import json
import uuid
from contextlib import aclosing
from copy import deepcopy
from urllib.parse import quote

from yanagent.contracts import ModelReply, ToolCall
from yanagent.errors import (
    AuthenticationError, InvalidRequestError, PermissionDeniedError, RateLimitError,
    EmptyModelResponseError, ModelRefusalError, ModelResponseError, ModelServerError, ModelOutputLimitError,
)
from yanagent.events import ModelStreamEvent
from .openai_compatible import prepare_request
from .transport import UrllibJsonTransport, UrllibSseTransport, strict_json_loads
from .normalization import normalize_usage, finish_reason as normalize_finish, reasoning_text, thinking_protocol, model_options, context_limits


class NativeProvider:
    """复用有大小限制、无重定向的 JSON/SSE 传输，实现原生请求转换。"""

    def __init__(self, config, *, transport=None, stream_transport=None):
        """固定本次请求配置，可注入离线协议测试传输。"""
        self.config = config
        self.name = config.model_provider
        self.show_reasoning = config.enable_thinking and thinking_protocol(config) != 'none'
        self.transport = transport if transport is not None else UrllibJsonTransport()
        self.stream_transport = stream_transport if stream_transport is not None else UrllibSseTransport()

    def request(self, messages, tools, stream):
        """将内部完整对话转换为供应商协议；从不执行工具。"""
        self.config.require_model_ready()
        prepare_request(messages, tools)
        system = '\n\n'.join(m.content for m in messages if m.role == 'system')
        output_limit = context_limits(self.config)[1]
        protocol = thinking_protocol(self.config)
        if self.name == 'claude':
            converted = []
            for message in messages:
                if message.role == 'system':
                    continue
                if message.role == 'tool':
                    role, parts = 'user', [{'type': 'tool_result', 'tool_use_id': message.tool_call_id,
                        'content': message.content, 'is_error': message.is_error}]
                else:
                    role = message.role
                    state = message.metadata.get('provider_state', {})
                    parts = deepcopy(state.get('claude_thinking', [])) if (
                        state.get('provider') == self.name and state.get('model') == self.config.model) else []
                    parts += ([{'type': 'text', 'text': message.content}] if message.content else [])
                    parts += [{'type': 'tool_use', 'id': c.id, 'name': c.name, 'input': c.arguments}
                              for c in message.tool_calls]
                    if state.get('provider') == self.name and state.get('model') == self.config.model and state.get('claude_content'):
                        parts = deepcopy(state['claude_content'])
                if converted and converted[-1]['role'] == role:
                    converted[-1]['content'].extend(parts)
                else:
                    converted.append({'role': role, 'content': parts})
            payload = {'model': self.config.model, 'messages': converted, 'max_tokens': output_limit,
                       'stream': stream}
            if self.config.enable_thinking and protocol in {'claude-enabled', 'claude-adaptive'}:
                if protocol == 'claude-adaptive':
                    payload['thinking'] = {'type': 'adaptive'}
                    effort = self.config.reasoning_effort_by_model.get(f'claude:{self.config.model.lower()}', 'high')
                    if effort not in {'low', 'medium', 'high'}:
                        raise InvalidRequestError()
                    payload['output_config'] = {'effort': effort}
                else:
                    budget = model_options(self.config).get('thinking_budget', 1024)
                    if budget < 1024 or budget >= output_limit:
                        raise InvalidRequestError()
                    payload['thinking'] = {'type': 'enabled', 'budget_tokens': budget}
            if system:
                payload['system'] = system
            if tools:
                payload['tools'] = [{'name': t['name'], 'description': t.get('description', ''), 'input_schema': t['parameters']} for t in tools]
            return self.config.api_base.rstrip('/') + '/messages', {
                'x-api-key': self.config.api_key, 'anthropic-version': '2023-06-01',
                'Content-Type': 'application/json', 'Accept': 'text/event-stream' if stream else 'application/json',
            }, payload
        contents = []
        names = {call.id: call.name for m in messages for call in m.tool_calls}
        native_calls = {call_id: part for m in messages
            for call_id, part in m.metadata.get('provider_state', {}).get('gemini_calls', {}).items()
            if m.metadata['provider_state'].get('provider') == self.name and m.metadata['provider_state'].get('model') == self.config.model}
        for message in messages:
            if message.role == 'system':
                continue
            role = 'model' if message.role == 'assistant' else 'user'
            if message.role == 'tool':
                parts = [{'functionResponse': {'id': message.tool_call_id,
                    'name': names.get(message.tool_call_id, message.name),
                    'response': {'error' if message.is_error else 'result': message.content}}}]
                original_call = native_calls.get(message.tool_call_id, {}).get('functionCall', {})
                if original_call and 'id' not in original_call:
                    parts[0]['functionResponse'].pop('id')
            else:
                parts = ([{'text': message.content}] if message.content else [])
                saved = message.metadata.get('provider_state', {})
                native = saved.get('gemini_calls', {}) if (
                    saved.get('provider') == self.name and saved.get('model') == self.config.model) else {}
                for call in message.tool_calls:
                    part = deepcopy(native.get(call.id, {'functionCall': {'id': call.id, 'name': call.name, 'args': call.arguments}}))
                    parts.append(part)
                if native and saved.get('gemini_parts'):
                    parts = deepcopy(saved['gemini_parts'])
                elif (saved.get('provider') == self.name and saved.get('model') == self.config.model and saved.get('gemini_parts')):
                    parts = deepcopy(saved['gemini_parts'])
            if contents and contents[-1]['role'] == role:
                contents[-1]['parts'].extend(parts)
            else:
                contents.append({'role': role, 'parts': parts})
        payload = {'contents': contents, 'generationConfig': {'maxOutputTokens': output_limit}}
        if protocol in {'gemini-budget', 'gemini-level'}:
            thinking = {'includeThoughts': self.config.enable_thinking}
            if self.config.enable_thinking:
                if protocol == 'gemini-budget':
                    thinking['thinkingBudget'] = model_options(self.config).get('thinking_budget', min(1024, output_limit))
                else:
                    effort = self.config.reasoning_effort_by_model.get(f'gemini:{self.config.model.lower()}', 'high')
                    if effort not in {'low', 'medium', 'high'}:
                        raise InvalidRequestError()
                    thinking['thinkingLevel'] = effort.upper()
            elif self.config.model.lower().startswith('gemini-2.5-flash'):
                thinking['thinkingBudget'] = 0
            payload['generationConfig']['thinkingConfig'] = thinking
        if system:
            payload['systemInstruction'] = {'parts': [{'text': system}]}
        if tools:
            payload['tools'] = [{'functionDeclarations': [
                {'name': t['name'], 'description': t.get('description', ''), 'parametersJsonSchema': t['parameters']}
                for t in tools]}]
        method = 'streamGenerateContent?alt=sse' if stream else 'generateContent'
        url = self.config.api_base.rstrip('/') + '/models/' + quote(self.config.model, safe='') + ':' + method
        return url, {'x-goog-api-key': self.config.api_key, 'Content-Type': 'application/json',
                     'Accept': 'text/event-stream' if stream else 'application/json'}, payload

    async def complete(self, messages, *, tools=()):
        """隔离损坏的原生响应，始终向调用方返回统一模型错误。"""
        try:
            return await self._complete(messages, tools=tools)
        except (KeyError, TypeError, ValueError, AttributeError, IndexError):
            raise ModelResponseError() from None

    async def _complete(self, messages, *, tools=()):
        """发送原生完整请求，转换为统一文本、工具请求和用量。"""
        url, headers, payload = self.request(messages, tools, False)
        data = await self.transport.post_json(url=url, headers=headers, payload=payload, timeout=self.config.request_timeout)
        reply = self.parse_claude(data, show_reasoning=self.show_reasoning) if self.name == 'claude' else self.parse_gemini(data, show_reasoning=self.show_reasoning)
        reply.provider_metadata.update(provider=self.name, model=self.config.model)
        reply.validate()
        self._check_empty_limit(reply)
        return reply

    @staticmethod
    def _check_empty_limit(reply):
        """无正文的额度截断不能作为空响应重试或触发备用工具执行。"""
        if not reply.content.strip() and not reply.tool_calls and reply.finish_reason in {'length', 'context_length'}:
            error = ModelOutputLimitError()
            error.usage = reply.usage
            raise error

    @staticmethod
    def parse_claude(data, *, show_reasoning=False):
        """只从公开 text/tool_use 字段提取正文和工具，不把思考块混入答案。"""
        if type(data) is not dict or type(data.get('content')) is not list:
            raise ModelResponseError()
        text, calls, thoughts, blocks = [], [], [], []
        for part in data['content']:
            if part.get('type') == 'text':
                text.append(part['text'])
            elif part.get('type') == 'tool_use':
                calls.append(ToolCall(part['id'], part['name'], part['input']))
            elif part.get('type') == 'thinking':
                thoughts.append(reasoning_text(part.get('thinking')))
                blocks.append(deepcopy(part))
            elif part.get('type') == 'redacted_thinking':
                blocks.append(deepcopy(part))
            else:
                raise ModelResponseError()
        reason = data.get('stop_reason')
        if reason == 'refusal':
            raise ModelRefusalError()
        usage = normalize_usage(data.get('usage', {}), 'claude')
        return ModelReply(content=''.join(text), tool_calls=calls,
            finish_reason=normalize_finish(reason, 'claude', bool(calls)), usage=usage,
            reasoning=''.join(thoughts) if show_reasoning else '', provider_metadata={
                **({'claude_thinking': blocks} if blocks else {}), 'claude_content': deepcopy(data['content']),
            })

    @staticmethod
    def parse_gemini(data, *, show_reasoning=False, partial=False):
        """读取单候选的文本及完整函数参数，并保留函数调用的 opaque 签名用于下轮回传。"""
        candidates = data.get('candidates', [])
        if data.get('promptFeedback', {}).get('blockReason'):
            raise ModelRefusalError()
        if not candidates:
            if data.get('promptFeedback', {}).get('blockReason'):
                raise ModelRefusalError()
            raise EmptyModelResponseError()
        if len(candidates) != 1:
            raise ModelResponseError()
        candidate = candidates[0]
        reason = candidate.get('finishReason')
        if reason in {'SAFETY', 'RECITATION', 'PROHIBITED_CONTENT', 'BLOCKLIST'}:
            raise ModelRefusalError()
        text, calls, saved, thoughts = [], [], {}, []
        for part in candidate.get('content', {}).get('parts', []):
            if 'text' in part and not part.get('thought'):
                text.append(part['text'])
            elif part.get('thought') and 'text' in part:
                thoughts.append(reasoning_text(part['text']))
            if 'functionCall' in part:
                value = part['functionCall']
                call_id = value.get('id') or 'call_' + uuid.uuid4().hex
                call = ToolCall(call_id, value['name'], value.get('args', {}))
                calls.append(call)
                saved[call_id] = {'functionCall': deepcopy(value)}
                if 'thoughtSignature' in part:
                    saved[call_id]['thoughtSignature'] = deepcopy(part['thoughtSignature'])
        usage = normalize_usage(data.get('usageMetadata', {}), 'gemini')
        return ModelReply(content=''.join(text), tool_calls=calls,
            finish_reason=normalize_finish(reason, 'gemini', bool(calls), partial=partial),
            usage=usage, provider_metadata={
                **({'gemini_calls': saved} if saved else {}),
                'gemini_parts': deepcopy(candidate.get('content', {}).get('parts', [])),
            }, reasoning=''.join(thoughts) if show_reasoning else '')

    async def stream(self, messages, *, tools=()):
        """确保解析异常受控，关闭生成器时也释放原生 SSE 连接。"""
        try:
            async with aclosing(self._stream(messages, tools=tools)) as stream:
                async for event in stream:
                    yield event
        except (KeyError, TypeError, ValueError, AttributeError, IndexError):
            raise ModelResponseError() from None

    async def _stream(self, messages, *, tools=()):
        """转换原生 SSE；只有观察到供应商终止事件后才产生 completed。"""
        url, headers, payload = self.request(messages, tools, True)
        text, calls, saved, usage, reason, finished = [], [], {}, {}, None, False
        blocks, thinking_blocks, text_blocks, thoughts, gemini_parts = {}, {}, {}, [], []
        async with aclosing(self.stream_transport.stream_data(
            url=url, headers=headers, payload=payload, timeout=self.config.request_timeout,
        )) as stream:
            async for raw in stream:
                data = strict_json_loads(raw)
                if type(data) is not dict:
                    raise ModelResponseError()
                if self.name == 'gemini':
                    if finished and data.get('candidates'):
                        raise ModelResponseError()
                    if not data.get('candidates'):
                        if data.get('usageMetadata'):
                            usage.update(data['usageMetadata'])
                            continue
                    reply = self.parse_gemini(data, show_reasoning=self.show_reasoning, partial=True)
                    if reply.reasoning:
                        thoughts.append(reply.reasoning)
                        yield ModelStreamEvent('reasoning_delta', content=reply.reasoning)
                    if reply.content:
                        text.append(reply.content)
                        yield ModelStreamEvent('text_delta', content=reply.content)
                    for call in reply.tool_calls:
                        index = len(calls)
                        calls.append(call)
                        yield ModelStreamEvent('tool_call_delta', tool_index=index,
                            tool_call_id=call.id, tool_name=call.name, arguments_delta=json.dumps(call.arguments, ensure_ascii=False))
                    saved.update(reply.provider_metadata.get('gemini_calls', {}))
                    gemini_parts.extend(reply.provider_metadata.get('gemini_parts', []))
                    usage.update(data.get('usageMetadata', {}))
                    if data['candidates'][0].get('finishReason'):
                        reason, finished = data['candidates'][0]['finishReason'], True
                    continue
                kind = data.get('type')
                if kind == 'error':
                    error_type = data.get('error', {}).get('type')
                    error_class = {
                        'rate_limit_error': RateLimitError,
                        'authentication_error': AuthenticationError,
                        'permission_error': PermissionDeniedError,
                        'invalid_request_error': InvalidRequestError,
                        'overloaded_error': ModelServerError,
                        'api_error': ModelServerError,
                    }.get(error_type, ModelResponseError)
                    raise error_class()
                if kind == 'message_start':
                    usage.update(data['message'].get('usage', {}))
                elif kind == 'content_block_start':
                    block = data['content_block']
                    if data['index'] in blocks or data['index'] in thinking_blocks or data['index'] in text_blocks:
                        raise ModelResponseError()
                    if block.get('type') == 'tool_use':
                        blocks[data['index']] = [block['id'], block['name'], '', block.get('input', {})]
                        yield ModelStreamEvent('tool_call_delta', tool_index=data['index'],
                                               tool_call_id=block['id'], tool_name=block['name'])
                    elif block.get('type') == 'text':
                        text_blocks[data['index']] = deepcopy(block)
                        if block.get('text'):
                            text.append(block['text'])
                            yield ModelStreamEvent('text_delta', content=block['text'])
                    elif block.get('type') in {'thinking', 'redacted_thinking'}:
                        thinking_blocks[data['index']] = deepcopy(block)
                        initial = reasoning_text(block.get('thinking')) if block['type'] == 'thinking' else ''
                        if initial and self.show_reasoning:
                            thoughts.append(initial)
                            yield ModelStreamEvent('reasoning_delta', content=initial)
                elif kind == 'content_block_delta':
                    delta = data['delta']
                    if delta['type'] == 'text_delta':
                        text.append(delta['text'])
                        text_blocks.setdefault(data['index'], {'type': 'text', 'text': ''})['text'] += delta['text']
                        yield ModelStreamEvent('text_delta', content=delta['text'])
                    elif delta['type'] == 'input_json_delta':
                        blocks[data['index']][2] += delta['partial_json']
                        yield ModelStreamEvent('tool_call_delta', tool_index=data['index'], arguments_delta=delta['partial_json'])
                    elif delta['type'] in {'thinking_delta', 'signature_delta'}:
                        block = thinking_blocks[data['index']]
                        key = 'thinking' if delta['type'] == 'thinking_delta' else 'signature'
                        value = reasoning_text(delta.get(key))
                        block[key] = block.get(key, '') + value
                        if key == 'thinking' and value and self.show_reasoning:
                            thoughts.append(value)
                            yield ModelStreamEvent('reasoning_delta', content=value)
                elif kind == 'message_delta':
                    reason = data['delta'].get('stop_reason')
                    usage.update(data.get('usage', {}))
                elif kind == 'message_stop':
                    finished = True
                    break
        if not finished:
            raise ModelResponseError()
        if self.name == 'claude':
            if reason is None:
                raise ModelResponseError()
            if reason == 'refusal':
                raise ModelRefusalError()
            calls = [ToolCall(value[0], value[1], strict_json_loads(value[2]) if value[2] else value[3]) for value in blocks.values()]
        reason = normalize_finish(reason, self.name, bool(calls))
        reply = ModelReply(content=''.join(text), tool_calls=calls, finish_reason=reason, usage=normalize_usage(usage, self.name),
            reasoning=''.join(thoughts), provider_metadata={
                **({'gemini_calls': saved} if saved else {}),
                **({'gemini_parts': gemini_parts} if gemini_parts else {}),
                **({'claude_thinking': [thinking_blocks[key] for key in sorted(thinking_blocks)]} if thinking_blocks else {}),
            })
        if self.name == 'claude':
            content_blocks = {**thinking_blocks, **text_blocks}
            for index, value in blocks.items():
                content_blocks[index] = {'type': 'tool_use', 'id': value[0], 'name': value[1],
                    'input': strict_json_loads(value[2]) if value[2] else value[3]}
            reply.provider_metadata['claude_content'] = [content_blocks[index] for index in sorted(content_blocks)]
        reply.validate()
        reply.provider_metadata.update(provider=self.name, model=self.config.model)
        self._check_empty_limit(reply)
        yield ModelStreamEvent('completed', reply=reply)
