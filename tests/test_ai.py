import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException
from app import ai


class FakeClient:
    events = []
    options = {}

    def __init__(self, **kwargs):
        self.responses = self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def create(self, **kwargs):
        FakeClient.options = kwargs
        async def generate():
            for event in self.events:
                yield SimpleNamespace(**event)
        return generate()


class StreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_completed_stream_is_successful(self):
        FakeClient.events = [{'type': 'response.output_text.delta', 'delta': '근거 답변'}, {'type': 'response.completed'}]
        with patch.object(ai, 'AsyncOpenAI', FakeClient):
            self.assertEqual(await ai.answer({'evidence': []}, 'test', 'test-model'), '근거 답변')
        self.assertFalse(FakeClient.options['store'])
        self.assertTrue(FakeClient.options['stream'])
        self.assertNotIn('max_output_tokens', FakeClient.options)

    async def test_missing_completion_and_failed_stream_are_errors(self):
        for events in ([{'type': 'response.output_text.delta', 'delta': 'partial'}],
                       [{'type': 'response.output_text.delta', 'delta': 'partial'}, {'type': 'response.failed'}],
                       [{'type': 'response.incomplete'}]):
            FakeClient.events = events
            with patch.object(ai, 'AsyncOpenAI', FakeClient):
                with self.assertRaises(HTTPException):
                    await ai.answer({}, 'test', 'test-model')

    async def test_approved_evaluation_request_has_output_bound(self):
        FakeClient.events = [{'type': 'response.output_text.delta', 'delta': 'ok'}, {'type': 'response.completed'}]
        with patch.object(ai, 'AsyncOpenAI', FakeClient):
            await ai.answer({}, 'test', 'gpt-6-luna', max_output_tokens=4096, reasoning_effort='low')
        self.assertEqual(FakeClient.options['max_output_tokens'], 4096)
        self.assertEqual(FakeClient.options['reasoning'], {'effort': 'low'})
