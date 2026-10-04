"""Native local Ollama text chat with explicit runtime context and SSE mapping."""
import json
import asyncio
import time
from urllib.parse import urlparse

import httpx

from .config import get_settings

_cache = {}


def native_base(endpoint):
    url = urlparse(endpoint)
    if url.scheme not in {'http', 'https'} or url.hostname not in {'127.0.0.1', 'localhost', '::1'} or url.port != 11434:
        return None
    if url.path.rstrip('/') not in {'', '/v1'}:
        return None
    return endpoint.rstrip('/').removesuffix('/v1')


async def _runtime_metadata(endpoint, model):
    base = native_base(endpoint)
    if not base:
        return None
    key = (base, model, get_settings().ollama_chat_context_tokens)
    cached = _cache.get(key)
    if cached and cached[0] > time.monotonic():
        return cached[1]
    try:
        async with httpx.AsyncClient(timeout=3, follow_redirects=False) as client:
            async with client.stream('POST', base + '/api/show', json={'model': model}) as reply:
                reply.raise_for_status()
                body = bytearray()
                async for chunk in reply.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > 2 * 1024 * 1024:
                        raise ValueError('Oversized metadata')
        details = json.loads(body)
        limits = [value for name, value in details.get('model_info', {}).items()
                  if name.endswith('.context_length') and isinstance(value, int)
                  and not isinstance(value, bool) and value > 0]
        if not limits or 'completion' not in details.get('capabilities', []):
            return None
        metadata = {'context_tokens': min(min(limits), max(2048, get_settings().ollama_chat_context_tokens)),
                    'capabilities': ['text'] + [c for c in ('vision', 'tools') if c in details.get('capabilities', [])]}
        if len(_cache) >= 256:
            _cache.clear()
        _cache[key] = (time.monotonic() + 30, metadata)
        return metadata
    except (httpx.HTTPError, ValueError, TypeError, AttributeError):
        return None


async def runtime_metadata(endpoint, model):
    try:
        return await asyncio.wait_for(_runtime_metadata(endpoint, model), timeout=4)
    except TimeoutError:
        return None


def text_chat_supported(payload):
    # Unsupported fields continue through OpenAI compatibility unchanged.
    allowed = {'model', 'messages', 'stream', 'stream_options', 'temperature',
               'top_p', 'seed', 'stop', 'max_tokens', 'max_completion_tokens', 'think'}
    return (set(payload).issubset(allowed) and isinstance(payload.get('messages'), list)
            and all(message.get('role') in {'system', 'user', 'assistant'}
                    and isinstance(message.get('content'), str)
                    for message in payload['messages']))


async def chat_request(provider, payload, default_url):
    if not text_chat_supported(payload):
        return default_url, payload, False
    metadata = await runtime_metadata(provider['endpoint_url'], payload['model'])
    if not metadata:
        return default_url, payload, False
    options = {'num_ctx': metadata['context_tokens'], 'num_predict': payload.get(
        'max_completion_tokens', payload.get('max_tokens', -1))}
    for field in ('temperature', 'top_p', 'seed', 'stop'):
        if field in payload:
            options[field] = payload[field]
    if isinstance(options.get('stop'), str):
        options['stop'] = [options['stop']]
    body = {'model': payload['model'], 'messages': payload['messages'],
            'stream': payload.get('stream', False), 'options': options}
    if 'think' in payload:
        body['think'] = payload['think']
    return native_base(provider['endpoint_url']) + '/api/chat', body, True


def completion(value, *, stream):
    if value.get('error'):
        return {'error': {'message': str(value['error'])[:500]}}
    message = value.get('message', {})
    content = {'content': message.get('content', ''), 'reasoning': message.get('thinking', '')}
    done = value.get('done', False)
    result = {'model': value.get('model'), 'object': 'chat.completion.chunk' if stream else 'chat.completion',
              'choices': [{'index': 0, 'delta' if stream else 'message': {'role': 'assistant', **content},
                           'finish_reason': (value.get('done_reason') or 'stop') if done else None}]}
    if done:
        prompt = value.get('prompt_eval_count', 0)
        generated = value.get('eval_count', 0)
        result['usage'] = {'prompt_tokens': prompt, 'completion_tokens': generated, 'total_tokens': prompt + generated}
    return result


async def stream_chunks(response):
    async for line in response.aiter_lines():
        if not line.strip():
            continue
        if len(line) > 2 * 1024 * 1024:
            raise ValueError('Oversized Ollama stream event')
        value = json.loads(line)
        yield ('data: ' + json.dumps(completion(value, stream=True)) + '\n\n').encode()
        if value.get('done'):
            yield b'data: [DONE]\n\n'
