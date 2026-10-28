import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace

TEST_DATA = tempfile.TemporaryDirectory()
os.environ['DATA_DIR'] = TEST_DATA.name
from fastapi.testclient import TestClient
from app import main, auth
from tests import test_architecture


class WebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = test_architecture.ArchitectureTests()
        cls.fixture.setUp()
        main.root = cls.fixture.root
        cls.client = TestClient(main.app)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        cls.fixture.tearDown()
        TEST_DATA.cleanup()

    def test_evidence_query_and_unavailable_oauth_are_explicit(self):
        result = self.client.post('/api/ask', json={'question': 'store_order 연결 모델', 'mode': 'evidence'})
        self.assertEqual(result.status_code, 200)
        self.assertTrue(result.json()['relations'])
        self.assertTrue(result.json()['evidence'])
        self.assertEqual(result.json()['source']['fingerprint'], self.client.get('/api/stats').json()['fingerprint'])
        self.assertEqual(self.client.get('/api/auth/chatgpt').status_code, 503)
        self.assertEqual(self.client.post('/api/ask', json={'question': '질문', 'mode': 'ai'}).status_code, 401)

    def test_model_selection_stays_with_the_signed_browser_session(self):
        key = 'sk-test-key-not-real-long-enough'
        with patch('app.auth.httpx.AsyncClient') as factory:
            network = factory.return_value.__aenter__.return_value
            network.get = AsyncMock(return_value=SimpleNamespace(status_code=200))
            connected = self.client.post('/api/auth/api-key', json={'key': key})
        self.assertEqual(connected.status_code, 200)
        self.assertNotIn(key, self.client.cookies.get('session'))
        changed = self.client.post('/api/auth/model', json={'model': 'gpt-6-luna'})
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(self.client.get('/api/auth/status').json()['selected_model'], 'gpt-6-luna')
        other_browser = TestClient(main.app)
        self.assertFalse(other_browser.get('/api/auth/status').json()['connected'])
        self.assertEqual(other_browser.post('/api/auth/model', json={'model': 'gpt-6.1-sol'}).status_code, 401)
        self.assertEqual(self.client.post('/api/auth/logout').status_code, 200)
        other_browser.close()

    def test_unknown_source_and_cross_origin_requests_rejected(self):
        self.assertEqual(self.client.get('/api/evidence/../../etc/passwd').status_code, 404)
        result = self.client.post('/api/reindex', headers={'origin': 'https://untrusted.example'})
        self.assertEqual(result.status_code, 403)
        with patch.dict(os.environ, {'ADMIN_TOKEN': 'admin-secret'}):
            self.assertEqual(self.client.post('/api/reindex').status_code, 403)

    def test_session_tokens_are_encrypted_and_isolated(self):
        from starlette.requests import Request
        request = Request({'type': 'http', 'session': {}})
        auth.save(request, {'provider': 'openai', 'key': 'sk-test-secret-not-real'})
        self.assertEqual(auth.load(request)['key'], 'sk-test-secret-not-real')
        other = Request({'type': 'http', 'session': {}})
        self.assertIsNone(auth.load(other))
        self.assertNotIn(b'sk-test-secret-not-real', Path(auth.DB_PATH).read_bytes())
        self.assertNotIn('key', request.session)
        self.assertEqual(self.client.get('/api/auth/status').json()['connected'], False)
