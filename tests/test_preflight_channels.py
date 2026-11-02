"""Host-channel binding checks only; synthetic discovery, no external calls."""
from pathlib import Path
import copy
import sys
import unittest
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_candidate as fixture
from workflow_fixtures import capabilities


class PreflightChannels(unittest.TestCase):
    def setUp(self):
        self.report = capabilities()

    def check(self, **kwargs):
        return fixture.workflow.check_capabilities(self.report, **kwargs)

    def test_channel_binding_required_even_with_available_label(self):
        self.report['capabilities']['image_generate'].pop('channel')
        self.assertFalse(self.check()['ok'])

    def test_no_bundled_image_adapter_is_falsely_claimed(self):
        self.report['capabilities']['image_generate']['channel']['kind'] = 'bundled_openapi'
        self.assertFalse(self.check()['ok'])

    def test_reference_conditioning_required_for_new_concept_work(self):
        self.report['capabilities']['image_generate']['channel']['supports'] = ['text_to_image']
        self.assertFalse(self.check()['ok'])

    def test_actual_mcp_image_callable_is_an_allowed_host_channel(self):
        channel = self.report['capabilities']['image_generate']['channel']
        channel.update(kind='mcp', target='synthetic_image_server/generate_image')
        self.assertTrue(self.check()['ok'])

    def test_image_api_channel_requires_clean_https_target(self):
        channel = self.report['capabilities']['image_generate']['channel']
        channel.update(kind='api', target='http://synthetic.invalid/generate')
        self.assertFalse(self.check()['ok'])
        channel['target'] = 'https://synthetic.invalid/generate?api_key=placeholder'
        self.assertFalse(self.check()['ok'])
        channel['target'] = 'https://synthetic.invalid/generate'
        self.assertTrue(self.check()['ok'])

    def test_lux_discovery_alone_does_not_claim_connection(self):
        self.report['capabilities']['lux']['verification']['level'] = 'discovered'
        self.assertFalse(self.check(require_lux=True)['ok'])
        self.report['capabilities']['lux']['verification']['level'] = 'connection_verified'
        self.assertTrue(self.check(require_lux=True)['ok'])

    def test_other_lux_transport_cannot_impersonate_bundled_executor(self):
        self.report['capabilities']['lux']['channel'].update(kind='mcp', target='synthetic/lux')
        self.assertFalse(self.check(require_lux=True)['ok'])

    def test_native_capture_is_required(self):
        self.report['capabilities'].pop('native_capture')
        self.assertFalse(self.check()['ok'])

    def test_optional_geometry_backend_is_required_when_declared(self):
        self.assertTrue(self.check()['ok'])
        self.assertFalse(self.check(required_capabilities=['geometry_backend'])['ok'])
        self.report['capabilities']['geometry_backend'] = copy.deepcopy(self.report['capabilities']['engine'])
        self.assertTrue(self.check(required_capabilities=['geometry_backend'])['ok'])

    def test_image_edit_support_is_checked_when_declared(self):
        self.report['capabilities']['image_edit'] = copy.deepcopy(self.report['capabilities']['engine'])
        self.report['capabilities']['image_edit']['channel']['supports'] = []
        self.assertFalse(self.check(required_capabilities=['image_edit'])['ok'])

    def test_task_region_must_match_verified_lux_account(self):
        t = fixture.Tests();t.setUp()
        try:
            t.generated();t.plan.pop('purpose', None)
            path, _ = t.gate()
            t.plan['workflow'] = {'path': str(path), 'sha256': fixture.core.file_hash(path)}
            t.prepare()
            report = capabilities('new-host')
            report['capabilities']['lux']['channel']['region'] = 'international'
            file = t.project / 'wrong-region.json';fixture.core.write(file, report)
            with self.assertRaises(ValueError):
                fixture.core.refresh_readiness(t.run, file, 'new-host')
            result = fixture.workflow.check_plan_capabilities(t.plan, t.project, report, 'new-host')
            self.assertFalse(result['ok'])
        finally:
            t.tearDown()

    def test_legacy_declaration_needs_operational_refresh(self):
        self.report['schema'] = 1
        with self.assertRaisesRegex(ValueError, 'refresh-readiness'):
            self.check()

    def test_plan_required_capabilities_reach_gate_and_refresh(self):
        t = fixture.Tests();t.setUp()
        try:
            t.plan.pop('purpose', None)
            t.plan['required_capabilities'] = ['geometry_backend']
            path, data = t.gate()
            t.plan['workflow'] = {'path': str(path), 'sha256': fixture.core.file_hash(path), 'session_id': 'test-session'}
            with self.assertRaisesRegex(ValueError, 'geometry_backend'):
                t.prepare()
            checkpoint = copy.deepcopy(data)
            fresh = capabilities('new-host')
            fresh['capabilities']['geometry_backend'] = copy.deepcopy(fresh['capabilities']['engine'])
            file = t.project / 'fresh.json';fixture.core.write(file, fresh)
            fixture.core.write(t.project / 'plan.json', t.plan)
            fixture.core.prepare(t.project / 'plan.json', t.project, t.run, file, 'new-host')
            self.assertEqual(fixture.core.read(path), checkpoint)
            fresh['capabilities'].pop('geometry_backend');fixture.core.write(file, fresh)
            with self.assertRaises(ValueError):
                fixture.core.refresh_readiness(t.run, file, 'new-host')
        finally:
            t.tearDown()


if __name__ == '__main__':
    unittest.main()
