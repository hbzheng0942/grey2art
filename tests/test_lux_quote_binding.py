"""An approved quote must accompany the exact provider creation request."""
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/greybox-to-multistyle-art/runtime'))
from greybox import lux


class QuoteBindingTests(unittest.TestCase):
    def test_quote_id_reaches_create_without_changing_body(self):
        submit = Mock(return_value='123')
        module = SimpleNamespace(submit_task=submit, ApiBusinessRejection=type('Rejection', (Exception,), {}))
        quote = 'quote_' + 'a' * 32
        payload = {'modelUrl': 'https://example.com/reviewed.glb'}
        with patch.object(lux, '_validate', return_value={'operation':'rig', 'endpoint':{'path':'/rig'}, 'parameters':payload}), \
             patch.object(lux, '_base', return_value='https://api.aholo3d.cn'), \
             patch.object(lux, 'credential_provider', return_value='fixture'), \
             patch.object(lux, '_module', return_value=module):
            result = lux._submit('rig', payload, 'cn', quote)
        self.assertEqual(submit.call_args.kwargs['content_id'], quote)
        self.assertEqual(submit.call_args.args[1], payload)
        self.assertEqual(result['taskId'], '123')

    def test_invalid_quote_cannot_reach_provider(self):
        with patch.object(lux, '_validate', return_value={}), patch.object(lux, '_module') as module:
            with self.assertRaises(lux.LuxError):
                lux._submit('rig', {}, 'cn', 'invented')
        module.assert_not_called()
