import json
import unittest
from unittest.mock import AsyncMock

from app.stream_recovery import recover
from app.ollama_chat import completion


class Stream:
    def __init__(self, model, content='', tools=None, finish='length'):
        async def chunks():
            values = [{'model': model, 'choices': [{'delta': {
                'content': content, 'reasoning': 'thinking', **({'tool_calls': tools} if tools else {})}}]},
                {'model': model, 'choices': [{'delta': {}, 'finish_reason': finish}]}]
            for value in values:
                data = ('data: ' + json.dumps(value) + '\r\n\r\n').encode()
                # Exercise arbitrary chunk boundaries.
                yield data[:7]
                yield data[7:]
            yield b'data: [DONE]\n\n'
        self.body_iterator = chunks()
        self.background = AsyncMock()


class RecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_reasoning_only_length_switches_and_finishes(self):
        first = Stream('small')
        second = Stream('other', content='Hello', finish='stop')
        callback = AsyncMock(return_value=second)
        output = b''.join([chunk async for chunk in recover(first, callback)])
        self.assertIn(b'model_retry', output)
        self.assertIn(b'Hello', output)
        self.assertEqual(output.count(b'[DONE]'), 1)
        callback.assert_awaited_once_with(['small'])
        first.background.assert_awaited_once()
        second.background.assert_awaited_once()

    async def test_partial_answer_never_replayed(self):
        callback = AsyncMock()
        output = b''.join([chunk async for chunk in recover(Stream('small', content='Partial'), callback)])
        callback.assert_not_awaited()
        self.assertIn(b'Partial', output)

    async def test_tool_calls_never_replayed(self):
        callback = AsyncMock()
        _ = [chunk async for chunk in recover(Stream('small', tools=[{'index': 0}]), callback)]
        callback.assert_not_awaited()

    async def test_attempts_bounded(self):
        callback = AsyncMock(side_effect=[Stream('second'), Stream('third')])
        output = b''.join([chunk async for chunk in recover(Stream('first'), callback)])
        self.assertEqual(callback.await_count, 2)
        self.assertEqual(output.count(b'[DONE]'), 1)
        self.assertIn(b'length', output)

    async def test_no_alternative_preserves_limit(self):
        callback = AsyncMock(return_value=None)
        output = b''.join([chunk async for chunk in recover(Stream('first'), callback)])
        self.assertIn(b'length', output)
        self.assertNotIn(b'model_retry', output)

    def test_native_mapping_preserves_reasoning_usage_and_finish(self):
        value = completion({'model': 'small', 'message': {'content': '', 'thinking': 'Thought'},
                            'done': True, 'done_reason': 'length', 'prompt_eval_count': 2, 'eval_count': 3}, stream=True)
        self.assertEqual(value['choices'][0]['delta']['reasoning'], 'Thought')
        self.assertEqual(value['choices'][0]['finish_reason'], 'length')
        self.assertEqual(value['usage']['total_tokens'], 5)


if __name__ == '__main__':
    unittest.main()
