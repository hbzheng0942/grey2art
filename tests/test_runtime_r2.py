"""Offline policy and operational-readiness regressions; no service/engine calls."""
from pathlib import Path
import sys
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_candidate as fixture


class RuntimeR2(unittest.TestCase):
    def setUp(self):
        self.t = fixture.Tests()
        self.t.setUp()

    def tearDown(self):
        self.t.tearDown()

    def test_task_based_selection_allows_both_versions_without_override(self):
        self.t.generated()
        self.t.plan.pop('effective_policy', None)
        for version in ('G1', 'G1-Turbo'):
            with self.subTest(version=version):
                self.t.plan['assets'][0]['generation']['parameters']['version'] = version
                fixture.core.validate_plan(self.t.plan)

    def test_explicit_user_version_restriction_is_respected(self):
        self.t.generated()
        self.t.plan['effective_policy'] = {'lux_selection': 'user_override',
                                           'allowed_versions': ['G1']}
        fixture.core.validate_plan(self.t.plan)
        self.t.plan['assets'][0]['generation']['parameters']['version'] = 'G1-Turbo'
        with self.assertRaisesRegex(ValueError, 'effective user policy'):
            fixture.core.validate_plan(self.t.plan)

    def test_both_versions_need_no_separate_turbo_exception(self):
        self.t.generated()
        self.t.plan['effective_policy'] = {'lux_selection': 'task_based',
                                           'allowed_versions': ['G1', 'G1-Turbo']}
        self.t.plan['assets'][0]['generation']['parameters']['version'] = 'G1-Turbo'
        fixture.core.validate_plan(self.t.plan)

    def test_new_generation_requires_an_explicit_version(self):
        self.t.generated()
        parameters = self.t.plan['assets'][0]['generation']['parameters']
        for version in (None, '', 'G2'):
            with self.subTest(version=version):
                if version is None:
                    parameters.pop('version', None)
                else:
                    parameters['version'] = version
                with self.assertRaisesRegex(ValueError, 'explicit G1 or G1-Turbo'):
                    fixture.core.validate_plan(self.t.plan)

    def test_face_count_is_explicit_and_within_supported_bounds(self):
        self.t.generated()
        parameters = self.t.plan['assets'][0]['generation']['parameters']
        for count in (None, True, 9999, 300001, 30000.0):
            with self.subTest(faceCount=count):
                if count is None:
                    parameters.pop('faceCount', None)
                else:
                    parameters['faceCount'] = count
                with self.assertRaisesRegex(ValueError, 'faceCount'):
                    fixture.core.validate_plan(self.t.plan)
        for count in (10000, 300000):
            with self.subTest(faceCount=count):
                parameters['faceCount'] = count
                fixture.core.validate_plan(self.t.plan)

    def test_turbo_omits_g1_only_custom_size(self):
        self.t.generated()
        parameters = self.t.plan['assets'][0]['generation']['parameters']
        parameters.update(version='G1-Turbo', customSize={'height': 1})
        with self.assertRaisesRegex(ValueError, 'G1-Turbo must omit customSize'):
            fixture.core.validate_plan(self.t.plan)

    def test_generated_asset_requires_a_selection_rationale(self):
        self.t.generated()
        for reason in (None, '', '   '):
            with self.subTest(reason=reason):
                self.t.plan['assets'][0]['reason'] = reason
                with self.assertRaisesRegex(ValueError, 'selection rationale'):
                    fixture.core.validate_plan(self.t.plan)

    def test_g1_omits_turbo_only_parameter(self):
        self.t.generated()
        self.t.plan['assets'][0]['generation']['parameters']['enablePbr'] = True
        with self.assertRaisesRegex(ValueError, 'G1 must omit'):
            fixture.core.validate_plan(self.t.plan)

    def test_historical_turbo_source_is_reusable(self):
        self.t.plan['assets'] = [{'id': 'existing', 'route': 'reuse',
            'source': {'path': 'res://historical.glb'}, 'provenance': {'version': 'G1-Turbo'}}]
        fixture.core.validate_plan(self.t.plan)

    def capabilities_file(self, **changes):
        report = self.t.caps()
        report.update(session_id='new-host', **changes)
        path = self.t.project / 'fresh-capabilities.json'
        fixture.core.write(path, report)
        return path

    def test_readiness_refresh_preserves_plan_and_does_not_grant_spend(self):
        self.t.prepare()
        frozen = (self.t.run / 'plan.frozen.json').read_bytes()
        before = fixture.core.read(self.t.run / 'run.json')
        result = fixture.core.refresh_readiness(self.t.run, self.capabilities_file(), 'new-host')
        after = fixture.core.read(self.t.run / 'run.json')
        self.assertTrue(result['ok'])
        self.assertEqual(before['planHash'], after['planHash'])
        self.assertEqual(before['inputs'], after['inputs'])
        self.assertEqual(before['approval'], after['approval'])
        self.assertEqual(frozen, (self.t.run / 'plan.frozen.json').read_bytes())

    def test_wrong_host_does_not_write_readiness(self):
        self.t.prepare()
        with self.assertRaises(ValueError):
            fixture.core.refresh_readiness(self.t.run, self.capabilities_file(), 'different-host')
        self.assertFalse((self.t.run / 'operational-readiness.json').exists())

    def test_expired_report_does_not_replace_working_readiness(self):
        self.t.prepare()
        fixture.core.refresh_readiness(self.t.run, self.capabilities_file(), 'new-host')
        path = self.t.run / 'operational-readiness.json'
        before = path.read_bytes()
        with self.assertRaises(ValueError):
            fixture.core.refresh_readiness(self.t.run,
                self.capabilities_file(checked_at='2020-01-01T00:00:00+00:00'), 'new-host')
        self.assertEqual(before, path.read_bytes())

    def test_tampered_operational_report_is_rejected(self):
        self.t.prepare()
        fixture.core.refresh_readiness(self.t.run, self.capabilities_file(), 'new-host')
        (self.t.run / 'operational-readiness.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'receipt changed'):
            fixture.core._read_readiness(self.t.run, fixture.core.read(self.t.run / 'run.json'))

    def production(self, generated=False):
        if generated:
            self.t.generated()
        self.t.plan.pop('purpose', None)
        path, _ = self.t.gate()
        self.t.plan['workflow'] = {'path': str(path), 'sha256': fixture.core.file_hash(path),
                                  'session_id': 'test-session'}
        self.t.prepare()

    def test_expired_capability_recovery_keeps_same_run(self):
        self.production(generated=True)
        state = fixture.core.read(self.t.run / 'run.json')
        state['assets']['hero'] = {'state': 'submitted', 'taskId': 42, 'region': 'cn'}
        fixture.core.save_run(self.t.run, state)
        class Waiting:
            def status(self, *args):
                return {'status': 1}
            def submit(self, *args, **kwargs):
                raise AssertionError('Recovery must not submit')
        class Later(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime.now(timezone.utc) + timedelta(days=2)
        with patch.object(fixture.workflow, 'datetime', Later):
            result = fixture.core.run(self.t.run, bridge=Waiting(), recovery=True)
        self.assertEqual(result['next'], 'refresh-readiness')
        self.assertEqual(result['resume'], 'same-run')
        self.assertEqual(result['pending'], ['hero'])
        self.assertEqual(result['state'], 'readiness_blocked_recovered')
        self.assertEqual(fixture.core.status(self.t.run)['health'], 'current')

    def test_readiness_blocked_recovery_does_not_submit_or_assemble(self):
        self.production(generated=True)
        fixture.core.refresh_readiness(self.t.run, self.capabilities_file(), 'new-host')
        (self.t.run / 'operational-readiness.json').write_text('{}')
        class Never:
            def __getattr__(self, name):
                raise AssertionError('Unexpected execution: ' + name)
        result = fixture.core.run(self.t.run, bridge=Never(), adapter=Never(), recovery=True)
        self.assertEqual(result['next'], 'refresh-readiness')
        self.assertEqual(result['failures'][0]['state'], 'blocked_readiness')
        fixture.core.refresh_readiness(self.t.run, self.capabilities_file(), 'new-host')
        self.assertEqual(fixture.core.status(self.t.run)['operationalReadiness']['state'], 'current')

    def test_source_drift_still_requires_revised_run(self):
        self.production()
        p = self.t.project / 'main.gd'
        p.write_text(p.read_text() + '\n# changed source\n')
        result = fixture.core.run(self.t.run, adapter=fixture.FileAdapter(), recovery=True)
        self.assertEqual(result['next'], 'revise_reusing_recovered_results')
        self.assertEqual(result['state'], 'source_changed_recovered')

    def test_prepare_with_current_capabilities_preserves_old_checkpoint(self):
        self.t.plan.pop('purpose', None)
        path, _ = self.t.gate()
        checkpoint = path.read_bytes()
        self.t.plan['workflow'] = {'path': str(path), 'sha256': fixture.core.file_hash(path),
                                  'session_id': 'test-session'}
        fixture.core.write(self.t.project / 'plan.json', self.t.plan)
        from greybox import layout
        self.t.run = layout.run_root(self.t.project, self.t.plan, self.t.run.name)
        fixture.core.prepare(self.t.project / 'plan.json', self.t.project, self.t.run,
                             self.capabilities_file(), 'new-host')
        self.assertEqual(checkpoint, path.read_bytes())
        self.assertEqual(fixture.core.status(self.t.run)['operationalReadiness']['session_id'], 'new-host')


    def test_nested_sample_evidence_drift_stales_status_and_validation(self):
        self.t.plan.pop('purpose', None)
        path, checkpoint = fixture.make_workflow(self.t.project, self.t.plan, expansion=True)
        self.t.plan['workflow'] = {'path': str(path), 'sha256': fixture.core.file_hash(path),
                                  'session_id': 'test-session', 'production_scope': 'expansion'}
        self.t.assembled()
        sample = next(s for s in checkpoint['stages'] if s['id'] == 'representative_sample')
        archived = fixture.core.read(next(e['path'] for e in sample['evidence'] if e['role'] == 'sample_source_production'))
        recipe = Path(next(e['path'] for e in archived['evidence'] if e['role'] == 'assembly_recipe'))
        recipe.write_text('{}')
        self.assertEqual(fixture.core.status(self.t.run)['health'], 'stale')
        with self.assertRaisesRegex(ValueError, 'dependency changed'):
            fixture.core.validate(self.t.run, adapter=fixture.FileAdapter())

if __name__ == '__main__':
    unittest.main(verbosity=2)
