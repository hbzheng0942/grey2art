"""Cheap operational rejection must precede pixel scans; no provider calls."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_candidate as fixture
from workflow_fixtures import capabilities

core, workflow = fixture.core, fixture.workflow


class ValidationOrder(unittest.TestCase):
    def setUp(self):
        self.t = fixture.Tests()
        self.t.setUp()

    def tearDown(self):
        self.t.tearDown()

    def production(self):
        self.t.generated()
        self.t.plan.pop('purpose', None)
        path, _ = self.t.gate()
        self.t.plan['workflow'] = {'path': str(path), 'sha256': core.file_hash(path)}

    def test_missing_capability_precedes_visual_dag(self):
        self.production()
        report = capabilities()
        report['capabilities'].pop('lux')
        with patch.object(workflow, 'inspect_workflow', side_effect=AssertionError('visual work started')):
            with self.assertRaisesRegex(ValueError, 'BLOCKED_CAPABILITY.*lux'):
                workflow.check_plan_gate(self.t.plan, self.t.project, report)

    def test_wrong_region_precedes_visual_dag(self):
        self.production()
        report = capabilities()
        report['capabilities']['lux']['channel']['region'] = 'international'
        with patch.object(workflow, 'inspect_workflow', side_effect=AssertionError('visual work started')):
            with self.assertRaisesRegex(ValueError, 'region'):
                workflow.check_plan_gate(self.t.plan, self.t.project, report)

    def test_prepare_checks_session_before_reference_pixels(self):
        self.production()
        path = self.t.project / 'plan.json'
        cap = self.t.project / 'current-capabilities.json'
        core.write(path, self.t.plan)
        core.write(cap, capabilities('old-session'))
        with patch.object(core, '_check_generation_reference', side_effect=AssertionError('pixels started')):
            with self.assertRaisesRegex(ValueError, 'another host session'):
                core.prepare(path, self.t.project, self.t.run, cap, 'new-session')
        self.assertFalse((self.t.run / 'run.json').exists())

    def test_expired_quote_rejects_before_source_snapshot(self):
        self.t.prepare()
        state = core.read(self.t.run / 'run.json')
        state['assets']['asset'] = {'state': 'quoted', 'region': 'cn', 'quoteId': 'q1'}
        state['quotes'] = {'cn': {'quote': {'quoteId': 'q1', 'expiresAt': '2020-01-01T00:00:00Z'}}}
        core.save_run(self.t.run, state)
        with patch.object(core, 'input_snapshot', side_effect=AssertionError('snapshot started')):
            with self.assertRaisesRegex(ValueError, 'Quote expired'):
                core.run(self.t.run, bridge=object())
        self.assertEqual(core.read(self.t.run / 'run.json')['assets']['asset']['state'], 'quoted')

    def test_recovery_does_not_consult_expired_quote(self):
        self.t.prepare()
        with patch.object(core, '_require_quote_current', side_effect=AssertionError('recovery checked quote')):
            result = core.run(self.t.run, adapter=fixture.FileAdapter(), recovery=True)
        self.assertTrue(result['ok'])

    def test_quote_rechecked_against_current_time(self):
        row = {'region': 'cn', 'quoteId': 'q1'}
        quotes = {'cn': {'quote': {'quoteId': 'q1', 'expiresAt':
            (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()}}}
        core._require_quote_current(row, quotes)
        quotes['cn']['quote']['expiresAt'] = '2020-01-01T00:00:00Z'
        with self.assertRaisesRegex(ValueError, 'Quote expired'):
            core._require_quote_current(row, quotes)


if __name__ == '__main__':
    unittest.main()
