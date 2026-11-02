"""Offline shared budget checks; no renderer or provider call."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/greybox-to-multistyle-art/runtime'))
from greybox import core, runtime_profile


class RuntimeProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        self.profile = {'schema': 1, 'kind': 'runtime-profile', 'engine': 'godot',
            'target': 'synthetic scene/device target, not real performance evidence',
            'budgets': [{'id': 'pet-faces', 'metric': 'mesh_faces', 'unit': 'triangles',
                         'limit': 3000, 'classification': 'target',
                         'source_ref': 'synthetic://initial-estimate', 'asset_ids': ['pet']}]}

    def bind(self):
        path = self.project / 'profile.json'
        core.write(path, self.profile)
        return {'path': 'profile.json', 'sha256': core.file_hash(path)}

    def test_exact_target_is_not_performance_acceptance(self):
        result = runtime_profile.validate_targets(self.bind(), [{'budget_id': 'pet-faces', 'value': 3000}], self.project, 'pet')
        self.assertTrue(result['ok'])
        self.assertFalse(result['performance_verified'])

    def test_provisional_change_needs_real_evidence(self):
        reference = self.bind()
        target = {'budget_id': 'pet-faces', 'value': 6000, 'reason': 'measured scene has headroom'}
        with self.assertRaisesRegex(core.WorkflowError, 'measured evidence'):
            runtime_profile.validate_targets(reference, [target], self.project, 'pet')
        path = self.project / 'measurement.json'
        core.write(path, {'synthetic_offline_only': True})
        target['evidence'] = [{'path': path.name, 'sha256': core.file_hash(path)}]
        self.assertTrue(runtime_profile.validate_targets(reference, [target], self.project, 'pet')['ok'])
        path.write_text('changed')
        with self.assertRaisesRegex(core.WorkflowError, 'changed'):
            runtime_profile.validate_targets(reference, [target], self.project, 'pet')

    def test_hard_limit_cannot_be_overridden_by_reason(self):
        self.profile['budgets'][0]['classification'] = 'hard'
        with self.assertRaisesRegex(core.WorkflowError, 'hard runtime limit'):
            runtime_profile.validate_targets(self.bind(), [{'budget_id': 'pet-faces', 'value': 6000,
                'reason': 'worker preference'}], self.project, 'pet')

    def test_missing_other_asset_and_mixed_unit_rejected(self):
        ref = self.bind()
        for targets, asset in [([], 'pet'), ([{'budget_id': 'pet-faces', 'value': 3000}], 'chair'),
                               ([{'budget_id': 'pet-faces', 'value': 3000, 'unit': 'quads'}], 'pet')]:
            with self.subTest(targets=targets, asset=asset), self.assertRaises(core.WorkflowError):
                runtime_profile.validate_targets(ref, targets, self.project, asset)

    def test_profile_change_invalidates_all_bound_targets(self):
        ref = self.bind()
        self.profile['budgets'][0]['limit'] = 6000
        self.bind()
        with self.assertRaisesRegex(core.WorkflowError, 'changed'):
            runtime_profile.validate_targets(ref, [{'budget_id': 'pet-faces', 'value': 3000}], self.project, 'pet')

    def test_empty_profile_does_not_invent_budget(self):
        self.profile['budgets'] = []
        result = runtime_profile.validate_targets(self.bind(), [], self.project, 'pet')
        self.assertEqual(result['target_ids'], [])
        self.assertFalse(result['performance_verified'])

    def test_invalid_numbers_and_unknown_targets_rejected(self):
        ref = self.bind()
        for target in [{'budget_id': 'pet-faces', 'value': True}, {'budget_id': 'pet-faces', 'value': float('inf')},
                       {'budget_id': 'unknown', 'value': 3000}]:
            with self.subTest(target=target), self.assertRaises(core.WorkflowError):
                runtime_profile.validate_targets(ref, [target], self.project, 'pet')


if __name__ == '__main__':
    unittest.main()
