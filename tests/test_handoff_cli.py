"""CLI handoff integration with synthetic host/native receipts only."""
from pathlib import Path
import json
import subprocess
import sys
import unittest
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_candidate as candidate
import test_delivery as native
from workflow_fixtures import capabilities

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / 'skills/greybox-to-multistyle-art/scripts/greybox.py'
CHECKER = ROOT / 'skills/greybox-to-multistyle-art/scripts/workflow_check.py'


class HandoffCLI(unittest.TestCase):
    def call(self, args, expected=0, script=CLI):
        result = subprocess.run([sys.executable, '-B', str(script), *map(str, args)], capture_output=True, text=True)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(result.stdout if expected == 0 else result.stderr)

    def test_capability_refresh_keeps_actual_plan_scope(self):
        fixture = candidate.Tests();fixture.setUp()
        try:
            fixture.plan.pop('purpose', None)
            path, _ = fixture.gate()
            fixture.plan['workflow'] = {'path': str(path), 'sha256': candidate.core.file_hash(path), 'session_id': 'test-session'}
            plan = fixture.project / 'plan.json';candidate.core.write(plan, fixture.plan)
            report = fixture.project / 'fresh.json';candidate.core.write(report, capabilities('handoff-cli'))
            from greybox import layout
            fixture.run = layout.run_root(fixture.project, fixture.plan, fixture.run.name)
            self.call(['plan', '--file', plan, '--project', fixture.project, '--run-dir', fixture.run,
                       '--capabilities', report, '--session-id', 'handoff-cli'])
            frozen = (fixture.run / 'plan.frozen.json').read_bytes()
            self.call(['refresh-readiness', '--run-dir', fixture.run, '--file', report, '--session-id', 'wrong'], 2)
            self.call(['refresh-readiness', '--run-dir', fixture.run, '--file', report, '--session-id', 'handoff-cli'])
            status = self.call(['status', '--run-dir', fixture.run])
            self.assertEqual(status['operationalReadiness']['state'], 'current')
            self.assertFalse(status['deliveryAcceptance']['accepted'])
            self.assertEqual(frozen, (fixture.run / 'plan.frozen.json').read_bytes())
            checked = self.call(['plan', '--file', plan, '--project', fixture.project, '--capabilities', report,
                                 '--session-id', 'handoff-cli'], script=CHECKER)
            self.assertTrue(checked['ok'])
        finally:
            fixture.tearDown()

    def test_h5_requires_reviewed_version_and_status_detects_later_drift(self):
        fixture = native.DeliveryTests();fixture.setUp()
        try:
            fixture.ready()
            proposal = self.call(['delivery-manifest', '--run-dir', fixture.run])
            self.assertEqual(proposal['acceptance']['status'], 'pending')
            args = ['accept-delivery', '--run-dir', fixture.run, '--actor', 'user',
                    '--source-ref', 'synthetic://handoff-cli-user', '--note', 'SYNTHETIC OFFLINE ACCEPTANCE ONLY']
            self.call([*args, '--manifest-hash', '0' * 64], 2)
            self.call([*args, '--manifest-hash', proposal['manifestHash']], 2)
            inputs = self.call(['delivery-review-inputs', '--run-dir', fixture.run])
            review = fixture.review_document()
            self.assertEqual(inputs['input_digest'], review['receipt']['input_digest'])
            review_path = fixture.run / 'synthetic-review.json'
            native.core.write(review_path, review)
            self.call(['record-delivery-review', '--run-dir', fixture.run, '--file', review_path])
            accepted = self.call([*args, '--manifest-hash', proposal['manifestHash']])
            self.assertTrue(accepted['accepted'])
            status = self.call(['status', '--run-dir', fixture.run])
            self.assertEqual(status['delivery'], 'accepted')
            state = native.core.read(fixture.run / 'run.json')
            Path(native.core.resolve_input(state['artifacts']['ceramic']['entry_scene'], fixture.project)).write_text('# changed after synthetic H5')
            status = self.call(['status', '--run-dir', fixture.run])
            self.assertEqual(status['delivery'], 'not-accepted')
            self.assertEqual(status['deliveryAcceptance']['status'], 'stale')
        finally:
            fixture.tearDown()


if __name__ == '__main__':
    unittest.main()
