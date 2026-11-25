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
    EmptyModelResponseError, ModelRefusalError, ModelResponseError, ModelServerError,
)
from yanagent.events import ModelStreamEvent
from .openai_compatible import prepare_request
from .transport import UrllibJsonTransport, UrllibSseTransport, strict_json_loads


def _usage(data, mapping):
    """只复制供应商明确返回的非负 Token 计数，缺失字段不补零。"""
    result = {}
    for source, target in mapping.items():
        if source in data:
            value = data[source]
            if type(value) is not int or value < 0:
                raise ModelResponseError()
            result[target] = value
    return result


class NativeProvider:
    """复用有大小限制、无重定向的 JSON/SSE 传输，实现原生请求转换。"""

    def __init__(self, config, *, transport=None, stream_transport=None):
        """固定本次请求配置，可注入离线协议测试传输。"""
        self.config = config
        self.name = config.model_provider
        self.transport = transport if transport is not None else UrllibJsonTransport()
        self.stream_transport = stream_transport if stream_transport is not None else UrllibSseTransport()

    def request(self, messages, tools, stream):
        """将内部完整对话转换为供应商协议；从不执行工具。"""
        self.config.require_model_ready()
        prepare_request(messages, tools)
        system = '\n\n'.join(m.content for m in messages if m.role == 'system')
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
                    parts = ([{'type': 'text', 'text': message.content}] if message.content else [])
                    parts += [{'type': 'tool_use', 'id': c.id, 'name': c.name, 'input': c.arguments}
                              for c in message.tool_calls]
                if converted and converted[-1]['role'] == role:
                    converted[-1]['content'].extend(parts)
                else:
                    converted.append({'role': role, 'content': parts})
            payload = {'model': self.config.model, 'messages': converted, 'max_tokens': self.config.max_output_tokens,
                       'stream': stream}
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
        for message in messages:
            if message.role == 'system':
                continue
            role = 'model' if message.role == 'assistant' else 'user'
            if message.role == 'tool':
                parts = [{'functionResponse': {'id': message.tool_call_id,
                    'name': names.get(message.tool_call_id, message.name),
                    'response': {'error' if message.is_error else 'result': message.content}}}]
            else:
                parts = ([{'text': message.content}] if message.content else [])
                saved = message.metadata.get('provider_state', {})
                native = saved.get('gemini_calls', {})
                for call in message.tool_calls:
                    part = deepcopy(native.get(call.id, {'functionCall': {'id': call.id, 'name': call.name, 'args': call.arguments}}))
                    parts.append(part)
            if contents and contents[-1]['role'] == role:
                contents[-1]['parts'].extend(parts)
            else:
                contents.append({'role': role, 'parts': parts})
        payload = {'contents': contents, 'generationConfig': {'maxOutputTokens': self.config.max_output_tokens}}
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
        reply = self.parse_claude(data) if self.name == 'claude' else self.parse_gemini(data)
        reply.provider_metadata.update(provider=self.name, model=self.config.model)
        reply.validate()
        return reply

    @staticmethod
    def parse_claude(data):
        """只从公开 text/tool_use 字段提取正文和工具，不把思考块混入答案。"""
        if type(data) is not dict or type(data.get('content')) is not list:
            raise ModelResponseError()
        text, calls = [], []
        for part in data['content']:
            if part.get('type') == 'text':
                text.append(part['text'])
            elif part.get('type') == 'tool_use':
                calls.append(ToolCall(part['id'], part['name'], part['input']))
            elif part.get('type') not in {'thinking', 'redacted_thinking'}:
                raise ModelResponseError()
        reason = data.get('stop_reason')
        if reason == 'refusal':
            raise ModelRefusalError()
        usage = _usage(data.get('usage', {}), {'input_tokens': 'input_tokens', 'output_tokens': 'output_tokens'})
        if 'input_tokens' in usage and 'output_tokens' in usage:
            usage['total_tokens'] = usage['input_tokens'] + usage['output_tokens']
        return ModelReply(content=''.join(text), tool_calls=calls,
            finish_reason={'end_turn': 'stop', 'tool_use': 'tool_calls', 'max_tokens': 'length', 'stop_sequence': 'stop'}.get(reason, reason), usage=usage)

    @staticmethod
    def parse_gemini(data):
        """读取单候选的文本及完整函数参数，并保留函数调用的 opaque 签名用于下轮回传。"""
        candidates = data.get('candidates', [])
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
        text, calls, saved = [], [], {}
        for part in candidate.get('content', {}).get('parts', []):
            if 'text' in part and not part.get('thought'):
                text.append(part['text'])
            if 'functionCall' in part:
                value = part['functionCall']
                call_id = value.get('id') or 'call_' + uuid.uuid4().hex
                call = ToolCall(call_id, value['name'], value.get('args', {}))
                calls.append(call)
                saved[call_id] = {'functionCall': deepcopy(value)}
                if 'thoughtSignature' in part:
                    saved[call_id]['thoughtSignature'] = deepcopy(part['thoughtSignature'])
                saved[call_id]['functionCall']['id'] = call_id
        usage = _usage(data.get('usageMetadata', {}), {
            'promptTokenCount': 'input_tokens', 'candidatesTokenCount': 'output_tokens', 'totalTokenCount': 'total_tokens',
        })
        return ModelReply(content=''.join(text), tool_calls=calls,
            finish_reason='tool_calls' if calls else {'STOP': 'stop', 'MAX_TOKENS': 'length'}.get(reason, reason),
            usage=usage, provider_metadata={'gemini_calls': saved} if saved else {})

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
        blocks = {}
        async with aclosing(self.stream_transport.stream_data(
            url=url, headers=headers, payload=payload, timeout=self.config.request_timeout,
        )) as stream:
            async for raw in stream:
                data = strict_json_loads(raw)
                if type(data) is not dict:
                    raise ModelResponseError()
                if self.name == 'gemini':
                    if not data.get('candidates'):
                        if data.get('usageMetadata'):
                            usage.update(_usage(data['usageMetadata'], {'promptTokenCount': 'input_tokens',
                                'candidatesTokenCount': 'output_tokens', 'totalTokenCount': 'total_tokens'}))
                            continue
                    reply = self.parse_gemini(data)
                    if reply.content:
                        text.append(reply.content)
                        yield ModelStreamEvent('text_delta', content=reply.content)
                    for call in reply.tool_calls:
                        index = len(calls)
                        calls.append(call)
                        yield ModelStreamEvent('tool_call_delta', tool_index=index,
                            tool_call_id=call.id, tool_name=call.name, arguments_delta=json.dumps(call.arguments, ensure_ascii=False))
                    saved.update(reply.provider_metadata.get('gemini_calls', {}))
                    usage.update(reply.usage)
                    if data['candidates'][0].get('finishReason'):
                        reason, finished = reply.finish_reason, True
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
                    usage.update(_usage(data['message'].get('usage', {}), {'input_tokens': 'input_tokens', 'output_tokens': 'output_tokens'}))
                elif kind == 'content_block_start':
                    block = data['content_block']
                    if block.get('type') == 'tool_use':
                        blocks[data['index']] = [block['id'], block['name'], '', block.get('input', {})]
                        yield ModelStreamEvent('tool_call_delta', tool_index=data['index'],
                                               tool_call_id=block['id'], tool_name=block['name'])
                    elif block.get('type') == 'text' and block.get('text'):
                        text.append(block['text'])
                        yield ModelStreamEvent('text_delta', content=block['text'])
                elif kind == 'content_block_delta':
                    delta = data['delta']
                    if delta['type'] == 'text_delta':
                        text.append(delta['text'])
                        yield ModelStreamEvent('text_delta', content=delta['text'])
                    elif delta['type'] == 'input_json_delta':
                        blocks[data['index']][2] += delta['partial_json']
                        yield ModelStreamEvent('tool_call_delta', tool_index=data['index'], arguments_delta=delta['partial_json'])
                elif kind == 'message_delta':
                    reason = data['delta'].get('stop_reason')
                    usage.update(_usage(data.get('usage', {}), {'input_tokens': 'input_tokens', 'output_tokens': 'output_tokens'}))
                elif kind == 'message_stop':
                    finished = True
        if not finished:
            raise ModelResponseError()
        if self.name == 'claude':
            if reason is None:
                raise ModelResponseError()
            if reason == 'refusal':
                raise ModelRefusalError()
            calls = [ToolCall(value[0], value[1], strict_json_loads(value[2]) if value[2] else value[3]) for value in blocks.values()]
            reason = {'end_turn': 'stop', 'tool_use': 'tool_calls', 'max_tokens': 'length', 'stop_sequence': 'stop'}.get(reason, reason)
            if 'input_tokens' in usage and 'output_tokens' in usage:
                usage['total_tokens'] = usage['input_tokens'] + usage['output_tokens']
        reply = ModelReply(content=''.join(text), tool_calls=calls, finish_reason=reason, usage=usage,
            provider_metadata={'gemini_calls': saved} if saved else {})
        reply.validate()
        reply.provider_metadata.update(provider=self.name, model=self.config.model)
        yield ModelStreamEvent('completed', reply=reply)
