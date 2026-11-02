"""Fault categories must survive adapter boundaries without leaking bodies."""
from datetime import datetime, timezone
from email.utils import format_datetime
import io
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/greybox-to-multistyle-art/runtime'))
from greybox import execution_errors as errors, image_adapters, lux, provider_http


class ExecutionErrorTests(unittest.TestCase):
    def test_unknown_submit_never_becomes_a_safe_retry(self):
        for error in [TimeoutError('private body'), OSError('private URL'), ValueError('malformed receipt')]:
            normalized = errors.classify_error(error, 'submit')
            self.assertEqual(normalized['acceptance'], 'unknown')
            self.assertNotIn('private', normalized['message'])
        self.assertEqual(errors.classify_error(TimeoutError(), 'status')['acceptance'], 'accepted')

    def test_retry_after_delay_date_and_invalid(self):
        now = 1_000_000
        stamp = datetime.fromtimestamp(now + 12, timezone.utc)
        self.assertEqual(errors.retry_after('7'), 7)
        self.assertEqual(errors.retry_after(format_datetime(stamp), now), 12)
        for value in [None, 'secret-not-a-date', 'nan', 'inf', True]:
            self.assertIsNone(errors.retry_after(value))

    def test_failed_receipt_requires_explicit_non_acceptance(self):
        self.assertEqual(errors.response_error({'ok': False}, 'submit')['acceptance'], 'unknown')
        value = errors.response_error({'ok': False, 'unknown_submission': False,
                                      'error': {'code': 'GENERATION_CONCURRENCY_LIMIT_EXCEEDED'}}, 'submit')
        self.assertEqual((value['category'], value['acceptance']), ('capacity', 'not_accepted'))

    def test_supplier_http_429_retains_rate_and_acceptance(self):
        opener = SimpleNamespace(open=lambda *a, **k: (_ for _ in ()).throw(
            HTTPError('https://example.com', 429, 'secret response', {'Retry-After': '9'}, io.BytesIO())))
        client = provider_http.ApiClient('https://example.com', ['example.com'], credential_provider=lambda: 'synthetic')
        with patch.object(provider_http.request, 'build_opener', return_value=opener):
            with self.assertRaises(provider_http.ProviderError) as caught:
                client.request('POST', '/tasks', {})
        value = errors.classify_error(caught.exception, 'submit')
        self.assertEqual((value['category'], value['acceptance'], value['retry_after']), ('rate_limit', 'not_accepted', 9))
        self.assertNotIn('secret', str(caught.exception))

    def test_image_http_503_creation_stays_unknown(self):
        opener = SimpleNamespace(open=lambda *a, **k: (_ for _ in ()).throw(
            HTTPError('https://example.com', 503, 'secret response', {}, io.BytesIO())))
        client = image_adapters.ImageHttp({'base_url': 'https://example.com'}, credential_provider=lambda: 'synthetic')
        with patch.object(image_adapters.request, 'build_opener', return_value=opener):
            with self.assertRaises(image_adapters.ImageError) as caught:
                client.call('POST', '/images', {})
        self.assertEqual(errors.classify_error(caught.exception, 'submit')['acceptance'], 'unknown')

    def test_lux_concurrency_code_survives_bridge(self):
        class Rejection(Exception):
            code = 'GENERATION_CONCURRENCY_LIMIT_EXCEEDED'
        module = SimpleNamespace(ApiBusinessRejection=Rejection,
                                 submit_task=lambda *a, **k: (_ for _ in ()).throw(Rejection()))
        with patch.object(lux, '_validate', return_value={'endpoint': {'path': '/create'}, 'parameters': {}}), \
             patch.object(lux, '_base', return_value='https://example.com'), \
             patch.object(lux, 'credential_provider', return_value=lambda: 'synthetic'), \
             patch.object(lux, '_module', return_value=module):
            with self.assertRaises(lux.LuxError) as caught:
                lux._submit('image_to_3d', {}, 'cn')
        value = errors.classify_error(caught.exception, 'submit')
        self.assertEqual((value['category'], value['acceptance']), ('capacity', 'not_accepted'))
        self.assertEqual(caught.exception.to_dict()['provider_code'], Rejection.code)

    def test_lux_image_concurrency_code_survives_image_adapter(self):
        response = {'f': None, 'c': 'GENERATION_CONCURRENCY_LIMIT_EXCEEDED', 'm': 'private provider text', 'd': None}
        with patch.object(lux, 'credential_provider', return_value=lambda: 'synthetic'), \
             patch.object(image_adapters.ImageHttp, 'call', return_value=response):
            with self.assertRaises(image_adapters.ImageError) as caught:
                image_adapters.lux_call({'kind': 'lux', 'region': 'cn'}, document={
                    'operation': 'generate', 'prompt': 'synthetic', 'images': [], 'parameters': {}})
        value = errors.classify_error(caught.exception, 'submit')
        self.assertEqual((value['category'], value['acceptance']), ('capacity', 'not_accepted'))
        self.assertNotIn('private', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
