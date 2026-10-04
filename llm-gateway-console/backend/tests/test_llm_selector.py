"""Isolated selector contract tests; no Ollama, database or downloads."""
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app.llm_selector import request_context, select_candidates
from app.model_router import Candidate


class Reply:
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def raise_for_status(self):
        pass

    async def aiter_bytes(self):
        yield json.dumps(self.value).encode()


class Client:
    def __init__(self, envelope):
        self.envelope = envelope
        self.sent = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def stream(self, method, url, **kwargs):
        self.sent = kwargs['json']
        return Reply(self.envelope)


class SelectorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.settings = SimpleNamespace(router_selector_url='http://127.0.0.1:11434',
            router_selector_model='qwen3.5:2b', router_selector_timeout_seconds=1)
        self.candidates = [Candidate(i, name,
            {'id': i, 'name': 'Node', 'priority': 1, 'api_key': 'DO_NOT_SEND'},
            0, {}, []) for i, name in enumerate(['new-model:small', 'new-model:large'], 1)]
        self.payload = {'messages': [{'role': 'user', 'content': 'Hello'}]}
        self.policy = {'preference': 'balanced', 'required_capabilities': []}

    async def run_choice(self, choice, *, done_reason='stop', fallback=None):
        client = Client({'response': json.dumps(choice), 'done': True, 'done_reason': done_reason})
        with patch('app.llm_selector.get_settings', return_value=self.settings), \
             patch('app.llm_selector.httpx.AsyncClient', return_value=client), \
             patch('app.llm_selector.fetch_one', return_value=fallback):
            result = await select_candidates(self.payload, self.candidates, self.policy)
        return result, client.sent

    async def test_dynamic_choice_and_no_credentials_or_thinking(self):
        (rows, policy), sent = await self.run_choice({'selected_model': 'new-model:small'})
        self.assertEqual([row.model_id for row in rows], [1])
        self.assertEqual(policy['selection']['decision_type'], 'local_llm_selection')
        self.assertFalse(sent['think'])
        self.assertNotIn('DO_NOT_SEND', json.dumps(sent))
        self.assertEqual(sent['format']['properties']['selected_model']['enum'],
                         ['new-model:large', 'new-model:small'])

    async def test_out_of_scope_name_is_not_forwarded(self):
        with self.assertRaises(HTTPException) as error:
            await self.run_choice({'selected_model': 'not-permitted'})
        self.assertEqual(error.exception.status_code, 503)

    async def test_incomplete_generation_uses_only_configured_eligible_fallback(self):
        (rows, policy), _ = await self.run_choice({'selected_model': 'new-model:large'},
            done_reason='length', fallback={'fallback_model_id': 1})
        self.assertEqual(rows[0].model_id, 1)
        self.assertEqual(policy['selection']['decision_type'], 'fallback_selector_error')

    async def test_ineligible_default_does_not_bypass_scope(self):
        with self.assertRaises(HTTPException):
            await self.run_choice({'selected_model': 'not-permitted'}, fallback={'fallback_model_id': 999})

    async def test_min_quality_is_not_fabricated(self):
        self.payload['routing'] = {'min_quality': 0.8}
        with self.assertRaises(HTTPException):
            await self.run_choice({'selected_model': 'new-model:small'})

    def test_context_is_bounded_and_excludes_system_and_assistant(self):
        messages = [{'role': 'system', 'content': 'secret-system'},
                    {'role': 'assistant', 'content': 'private-reasoning'}]
        messages += [{'role': 'user', 'content': str(i) * 600} for i in range(4)]
        result = request_context({'messages': messages})
        self.assertEqual(len(result['previous_user_messages']), 2)
        self.assertEqual(len(result['previous_user_messages'][0]), 512)
        self.assertNotIn('secret', json.dumps(result))
        self.assertNotIn('private', json.dumps(result))


if __name__ == '__main__':
    unittest.main()
