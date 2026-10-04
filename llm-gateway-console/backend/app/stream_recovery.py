"""Bounded, visible recovery from reasoning-only generation-limit failures.

Never retry after final-answer text or tool calls: replay could duplicate work.
Never evaluate answer quality from finish_reason alone.
"""
import codecs
import json
import re


async def events(chunks):
    decoder = codecs.getincrementaldecoder('utf-8')()
    buffer = ''
    async for chunk in chunks:
        buffer += decoder.decode(chunk)
        while match := re.search(r'\r?\n\r?\n', buffer):
            event, buffer = buffer[:match.start()], buffer[match.end():]
            if len(event) > 2 * 1024 * 1024:
                raise ValueError('Oversized stream event')
            yield event
        if len(buffer) > 2 * 1024 * 1024:
            raise ValueError('Oversized partial stream event')
    buffer += decoder.decode(b'', final=True)
    if buffer.strip():
        yield buffer


async def recover(initial, next_response, *, max_attempts=3):
    response = initial
    failed_models = []
    for attempt in range(1, max_attempts + 1):
        content = False
        tools = False
        limit = False
        model = None
        tail = []
        tail_size = 0
        try:
            async for event in events(response.body_iterator):
                frame = (event + '\n\n').encode()
                data = '\n'.join(line[5:].lstrip(' ') for line in event.splitlines() if line.startswith('data:'))
                value = None
                if data and data.strip() != '[DONE]':
                    value = json.loads(data)
                    if isinstance(value.get('model'), str):
                        model = value['model']
                    for choice in value.get('choices', []):
                        delta = choice.get('delta', {})
                        content |= bool(delta.get('content'))
                        tools |= bool(delta.get('tool_calls'))
                        limit |= choice.get('finish_reason') == 'length'
                if limit and not content and not tools:
                    tail.append(frame)
                    tail_size += len(frame)
                    if tail_size > 2 * 1024 * 1024:
                        raise ValueError('Oversized terminal stream events')
                else:
                    yield frame
        finally:
            await response.body_iterator.aclose()
            if response.background:
                await response.background()
        if not limit or content or tools or not model or attempt >= max_attempts:
            for frame in tail:
                yield frame
            return
        failed_models.append(model)
        try:
            replacement = await next_response(failed_models)
        except Exception:
            replacement = None
        if replacement is None:
            for frame in tail:
                yield frame
            return
        response = replacement
        try:
            yield ('data: ' + json.dumps({'object': 'chat.completion.chunk', 'model': model,
                'choices': [], 'gateway': {'event': 'model_retry',
                'attempt': attempt + 1, 'failed_model': model,
                'reason': 'generation_limit_without_final_answer'}}) + '\n\n').encode()
        except BaseException:
            await response.body_iterator.aclose()
            if response.background:
                await response.background()
            raise
