"""Synthetic image/scene evidence only; no real art judgment or approval."""
from pathlib import Path
import copy
import io
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr

ROOT = Path(__file__).resolve().parents[1] / 'skills/greybox-to-multistyle-art'
sys.path.insert(0, str(ROOT / 'runtime'))
sys.dont_write_bytecode = True
from greybox import core, effects, engines, pre_handoff, scene_review, scene_review_cli, workflow
from workflow_fixtures import make_workflow, refresh_evidence, png, evidence, approve


class SceneComparisonTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='gb-scene-comparison-')
        self.project = Path(self.tmp.name) / 'project'
        shutil.copytree(ROOT / 'fixtures/godot-free', self.project)
        self.plan = core.read(self.project / 'plan.json')
        self.plan.pop('purpose', None)
        self.plan['styles'] = self.plan['styles'][:1]
        self.path, self.data = make_workflow(self.project, self.plan, expansion=True, initialize_control=False)
        self.sample = self.stage('representative_sample')

    def tearDown(self):
        self.tmp.cleanup()

    def stage(self, sid, scope='ceramic'):
        return next(s for s in self.data['stages'] if s['id'] == sid and s['scope'] == scope)

    def declared(self):
        self.source_item = next(e for e in self.sample['evidence'] if e['role'] == 'sample_source_production')
        self.source = core.read(self.source_item['path'])
        self.table_item = next(e for e in self.source['evidence'] if e['role'] == 'production_table')
        self.table = core.read(self.table_item['path'])
        self.table['sample_contract']['scene_comparison'] = scene_review.CONTRACT
        refresh_evidence(self.source, 'production_table', self.table)
        self.save_source()
        return scene_review.inputs_for_stage(self.data, self.project, self.sample)

    def save_source(self):
        core.write(self.source_item['path'], self.source)
        self.source_item['sha256'] = core.file_hash(self.source_item['path'])
        self.sample['consumes'] = {'ceramic/production_plan': workflow.stage_digest(self.source)}

    def passed(self, inputs):
        report = scene_review.draft(inputs)
        report.update(reviewer={'agent_id': 'synthetic-reviewer', 'task_id': 'synthetic-review'}, source_ref='synthetic://offline-review')
        for i, row in enumerate(report['comparisons']):
            row.update(status='pass', observation='SYNTHETIC observation for ' + row['id'])
            row.pop('next_action')
            if row['id'].startswith('feature/'):
                row['target']['region'] = [0, i / 4, 1, .25]
                row['actual']['region'] = [0, i / 4, 1, .25]
            for layer in row.get('layers', []):
                layer.update(status='pass', observation='SYNTHETIC observed ' + layer['id'])
                layer.pop('next_action')
        return report

    def test_draft_surfaces_all_unreviewed_layers_without_acceptance(self):
        inputs = self.declared()
        result = scene_review.inspect_report(scene_review.draft(inputs), inputs)
        self.assertFalse(result['ok'])
        self.assertFalse(result['human_visual_acceptance'])
        self.assertEqual(len(result['blockers']), 3 + len(workflow.COMPOSITION_LAYERS) + 1)

    def test_distinct_regions_on_shared_sheet_are_valid(self):
        inputs = self.declared()
        report = self.passed(inputs)
        # One concept sheet/capture legitimately covers several different features.
        self.assertEqual(report['comparisons'][0]['actual']['path'], report['comparisons'][1]['actual']['path'])
        self.assertTrue(scene_review.inspect_report(report, inputs)['ok'])

    def test_repeated_pair_and_observation_cannot_claim_distinct_features(self):
        inputs = self.declared()
        report = self.passed(inputs)
        first, second = report['comparisons'][:2]
        second.update(target=copy.deepcopy(first['target']), actual=copy.deepcopy(first['actual']), observation=first['observation'])
        with self.assertRaisesRegex(core.WorkflowError, 'repeats the same image regions'):
            scene_review.inspect_report(report, inputs)

    def test_unrelated_image_cannot_cover_feature(self):
        inputs = self.declared()
        report = self.passed(inputs)
        report['comparisons'][0]['actual'].update(path=str(self.project / 'unrelated.png'))
        with self.assertRaisesRegex(core.WorkflowError, 'does not match the required'):
            scene_review.inspect_report(report, inputs)

    def test_every_feature_and_whole_scene_are_required(self):
        inputs = self.declared()
        for index in (0, 2):
            report = self.passed(inputs)
            report['comparisons'].pop(index)
            with self.assertRaisesRegex(core.WorkflowError, 'omits required feature/view'):
                scene_review.inspect_report(report, inputs)

    def test_fail_and_unclear_report_next_actions_and_block(self):
        inputs = self.declared()
        for status in ('fail', 'unclear'):
            report = self.passed(inputs)
            report['comparisons'][0].update(status=status, observation='SYNTHETIC floor is still flat', next_action='Restore the agreed floor relief')
            result = scene_review.inspect_report(report, inputs)
            self.assertFalse(result['ok'])
            self.assertEqual(result['blockers'][0]['next_action'], 'Restore the agreed floor relief')

    def test_layer_failure_blocks_even_if_outer_row_claims_pass(self):
        inputs = self.declared()
        report = self.passed(inputs)
        layer = report['comparisons'][-1]['layers'][0]
        layer.update(status='fail', observation='SYNTHETIC missing ground contact', next_action='Correct contact and recapture')
        self.assertFalse(scene_review.inspect_report(report, inputs)['ok'])

    def test_layer_coverage_and_whole_image_cannot_be_reduced(self):
        inputs = self.declared()
        report = self.passed(inputs)
        report['comparisons'][-1]['layers'].pop()
        with self.assertRaisesRegex(core.WorkflowError, 'every required visual layer'):
            scene_review.inspect_report(report, inputs)
        report = self.passed(inputs)
        report['comparisons'][-1]['actual']['region'] = [0, 0, .1, .1]
        with self.assertRaisesRegex(core.WorkflowError, 'full image'):
            scene_review.inspect_report(report, inputs)

    def test_invalid_and_nonfinite_regions_rejected(self):
        inputs = self.declared()
        for box in ([0, 0, 2, 1], [0, 0, float('nan'), 1], [False, 0, 1, 1]):
            report = self.passed(inputs)
            report['comparisons'][0]['actual']['region'] = box
            with self.assertRaisesRegex(core.WorkflowError, 'bounded normalized'):
                scene_review.inspect_report(report, inputs)

    def test_changed_native_pixels_and_source_are_stale(self):
        inputs = self.declared()
        report = self.passed(inputs)
        image = next(e for e in self.sample['evidence'] if e['role'] == 'native_capture')
        Path(image['path']).write_bytes(png(73))
        with self.assertRaisesRegex(core.WorkflowError, 'image missing or stale'):
            scene_review.inputs_for_stage(self.data, self.project, self.sample)
        image['sha256'] = core.file_hash(image['path'])
        manifest_item = next(e for e in self.sample['evidence'] if e['role'] == 'native_sample')
        manifest = core.read(manifest_item['path'])
        manifest['captures'][0]['sha256'] = image['sha256']
        refresh_evidence(self.sample, 'native_sample', manifest)
        current = scene_review.inputs_for_stage(self.data, self.project, self.sample)
        with self.assertRaisesRegex(core.WorkflowError, 'stale for the current'):
            scene_review.inspect_report(report, current)
        native = core.resolve_input(self.sample['identity']['scene'], self.project)
        native.write_text(native.read_text() + '\n# changed source\n')
        with self.assertRaisesRegex(core.WorkflowError, 'Sample input file changed'):
            scene_review.inputs_for_stage(self.data, self.project, self.sample)

    def test_historical_contract_stays_valid_without_comparison(self):
        self.assertEqual(scene_review.validate_stage(self.data, self.project, self.sample), {'required': False})
        self.assertTrue(workflow.inspect_workflow(self.path, self.project, expansion=True)['ok'])

    def test_declared_contract_needs_report(self):
        self.declared()
        with self.assertRaisesRegex(core.WorkflowError, 'exactly one scene_comparison'):
            scene_review.validate_stage(self.data, self.project, self.sample)

    def test_unknown_contract_cannot_silently_downgrade(self):
        self.declared()
        self.table['sample_contract']['scene_comparison'] = 'invented-contract'
        refresh_evidence(self.source, 'production_table', self.table)
        self.save_source()
        with self.assertRaisesRegex(core.WorkflowError, 'Unknown scene comparison contract'):
            scene_review.validate_stage(self.data, self.project, self.sample)

    def early_inputs(self):
        self.declared()
        proxy = self.stage('art_proxy')
        manifest = core.read(next(e['path'] for e in proxy['evidence'] if e['role'] == 'native_proxy'))
        manifest['scene'] = self.plan['contract']['scene']
        manifest['source_files'] = engines.dependency_snapshot(self.project, self.plan)
        refresh_evidence(proxy, 'native_proxy', manifest)
        return scene_review.proxy_inputs(self.data, self.project, 'ceramic', self.table_item['path'])

    def test_early_proxy_needs_no_h4_stage_or_approved_production(self):
        inputs = self.early_inputs()
        self.data['stages'] = [s for s in self.data['stages'] if s['id'] not in {'production_plan', 'representative_sample'}]
        current = scene_review.proxy_inputs(self.data, self.project, 'ceramic', self.table_item['path'])
        self.assertEqual(current, inputs)
        result = scene_review.inspect_report(self.passed(inputs), inputs)
        self.assertTrue(result['ok'])
        self.assertEqual(result['purpose'], 'risk_and_composition_only')
        self.assertFalse(result['human_visual_acceptance'])
        self.assertFalse(inputs['production_table_approved'])

    def test_old_proxy_cannot_backfill_current_source_identity(self):
        self.declared()
        with self.assertRaisesRegex(core.WorkflowError, 'actual scene and source_files'):
            scene_review.proxy_inputs(self.data, self.project, 'ceramic', self.table_item['path'])

    def test_proxy_stale_source_and_missing_dependencies_are_rejected(self):
        self.early_inputs()
        scene = core.resolve_input(self.plan['contract']['scene'], self.project)
        scene.write_text(scene.read_text() + '\n# source drift\n')
        with self.assertRaisesRegex(core.WorkflowError, 'Probe source missing, changed'):
            scene_review.proxy_inputs(self.data, self.project, 'ceramic', self.table_item['path'])
        proxy = self.stage('art_proxy')
        manifest = core.read(next(e['path'] for e in proxy['evidence'] if e['role'] == 'native_proxy'))
        manifest['source_files'] = [{'path': str(scene), 'sha256': core.file_hash(scene)}]
        refresh_evidence(proxy, 'native_proxy', manifest)
        with self.assertRaisesRegex(core.WorkflowError, 'omit native dependencies'):
            scene_review.proxy_inputs(self.data, self.project, 'ceramic', self.table_item['path'])

    def test_probe_report_cannot_be_relabelled_h4(self):
        inputs = self.early_inputs()
        report = self.passed(inputs)
        report['purpose'] = 'h4_comparison'
        with self.assertRaisesRegex(core.WorkflowError, 'cannot stand in for H4'):
            scene_review.inspect_report(report, inputs)

    def test_effect_shader_omission_and_mutation_invalidate_proxy_evidence(self):
        self.early_inputs()
        artifact = effects.apply_godot(self.project, {"scene": self.plan['contract']['scene'],
            "effects": {"water": {}}}, self.project / "art/effect-probe")
        proxy = self.stage('art_proxy')
        manifest = core.read(next(e['path'] for e in proxy['evidence'] if e['role'] == 'native_proxy'))
        manifest['scene'] = artifact['entry_scene']
        complete = engines.dependency_snapshot(self.project, {'contract': {'scene': artifact['entry_scene']}})
        manifest['source_files'] = complete
        refresh_evidence(proxy, 'native_proxy', manifest)
        scene_review.proxy_inputs(self.data, self.project, 'ceramic', self.table_item['path'])
        manifest['source_files'] = [row for row in complete if not row['path'].endswith('water.gdshader')]
        refresh_evidence(proxy, 'native_proxy', manifest)
        with self.assertRaisesRegex(core.WorkflowError, 'omit native dependencies'):
            scene_review.proxy_inputs(self.data, self.project, 'ceramic', self.table_item['path'])
        manifest['source_files'] = complete
        refresh_evidence(proxy, 'native_proxy', manifest)
        shader = self.project / 'art/effect-probe/water.gdshader'
        shader.write_text(shader.read_text() + '\n// changed effect source\n')
        with self.assertRaisesRegex(core.WorkflowError, 'Probe source missing, changed'):
            scene_review.proxy_inputs(self.data, self.project, 'ceramic', self.table_item['path'])

    def test_proxy_declared_missing_layer_cannot_be_relabelled_pass(self):
        self.early_inputs()
        proxy = self.stage('art_proxy')
        manifest = core.read(next(e['path'] for e in proxy['evidence'] if e['role'] == 'native_proxy'))
        manifest['captures'][0]['visible_layers'].remove('environment')
        manifest['captures'][0]['missing_layers'] = ['environment']
        refresh_evidence(proxy, 'native_proxy', manifest)
        inputs = scene_review.proxy_inputs(self.data, self.project, 'ceramic', self.table_item['path'])
        with self.assertRaisesRegex(core.WorkflowError, 'declares this layer missing'):
            scene_review.inspect_report(self.passed(inputs), inputs)
        report = self.passed(inputs)
        layer = next(layer for layer in report['comparisons'][-1]['layers'] if layer['id'] == 'environment')
        layer.update(status='unclear', observation='SYNTHETIC environment not yet visible', next_action='Assemble environment and recapture')
        self.assertFalse(scene_review.inspect_report(report, inputs)['ok'])

    def test_full_proxy_can_review_focused_sample_views(self):
        views = [{'id': space + '-view', 'camera_id': space + '-camera', 'state_id': 'playing',
            'framing': 'whole_composition', 'space_ids': [space], 'required_layers': sorted(workflow.COMPOSITION_LAYERS)}
            for space in ('start', 'end')]
        self.path, self.data = make_workflow(self.project, self.plan, expansion=True, initialize_control=False,
            sample_space_ids=['start'], observation_views=views)
        self.sample = self.stage('representative_sample')
        inputs = self.early_inputs()
        self.assertEqual({row['native_view_id'] for row in inputs['comparisons']}, {'start-view'})
        self.assertTrue(scene_review.inspect_report(self.passed(inputs), inputs)['ok'])

    def test_cli_draft_is_exclusive_and_check_returns_nonzero_for_gaps(self):
        self.declared()
        core.write(self.path, self.data)
        output = self.project / 'review-draft.json'
        common = ['--workflow', str(self.path), '--project', str(self.project), '--style', 'ceramic']
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(scene_review_cli.main(['draft', *common, '--output', str(output)]), 0)
            before = output.read_bytes()
            self.assertEqual(scene_review_cli.main(['draft', *common, '--output', str(output)]), 2)
            self.assertEqual(output.read_bytes(), before)
            self.assertEqual(scene_review_cli.main(['check', *common, '--report', str(output)]), 2)

    def test_h3_new_contract_requires_criterion_specific_artifact_roles(self):
        self.declared()
        inputs = pre_handoff.review_inputs(self.data, self.project, self.source)
        self.assertEqual(inputs['scene_comparison_contract'], scene_review.CONTRACT)
        wrong = {'coverage': [{'id': key, 'evidence': [{'path': a['path'], 'sha256': a['sha256']} for a in inputs['artifacts'] if a['role'] == 'concept_image']}
                              for key in scene_review.H3_CRITERION_ROLES]}
        with self.assertRaisesRegex(core.WorkflowError, 'relevant evidence roles'):
            scene_review.validate_criterion_roles(wrong, inputs)
        right = {'coverage': [{'id': key, 'evidence': [{'path': a['path'], 'sha256': a['sha256']} for a in inputs['artifacts']
                                     if a['stage'] == inputs['stage'] and a['role'] in roles]}
                              for key, roles in scene_review.H3_CRITERION_ROLES.items()]}
        scene_review.validate_criterion_roles(right, inputs)
        old_inputs = dict(inputs)
        old_inputs.pop('scene_comparison_contract')
        scene_review.validate_criterion_roles(wrong, old_inputs)

    def test_integrated_workflow_checks_new_contract(self):
        self.declared()
        # Rebuild synthetic H3 review with criterion-specific local roles.
        def approve_h3(stage):
            approve(stage)
            inputs = pre_handoff.review_inputs(self.data, self.project, stage)
            all_artifacts = [{'path': a['path'], 'sha256': a['sha256']} for a in inputs['artifacts']]
            for check in stage['review']['coverage']:
                check['evidence'] = all_artifacts
            stage['approval']['stage_digest'] = workflow.stage_digest(stage)
        approve_h3(self.source)
        self.save_source()
        current = self.stage('production_plan')
        table = core.read(next(e['path'] for e in current['evidence'] if e['role'] == 'production_table'))
        table['sample_contract']['scene_comparison'] = scene_review.CONTRACT
        table['sample_contract']['source_production_digest'] = workflow.stage_digest(self.source)
        refresh_evidence(current, 'production_table', table)
        approve_h3(current)
        inputs = scene_review.inputs_for_stage(self.data, self.project, self.sample)
        report = self.passed(inputs)
        self.sample['evidence'].append(evidence(self.project, 'comparison.json', 'scene_comparison', report))
        approve(self.sample)
        core.write(self.path, self.data)
        checked = workflow.inspect_workflow(self.path, self.project, expansion=True)
        self.assertTrue(checked['scene_comparisons']['ceramic']['ok'])
        report['comparisons'][0].update(status='fail', observation='SYNTHETIC visibly missing form', next_action='Repair and capture again')
        refresh_evidence(self.sample, 'scene_comparison', report)
        approve(self.sample)
        core.write(self.path, self.data)
        with self.assertRaisesRegex(core.WorkflowError, 'unresolved items'):
            workflow.inspect_workflow(self.path, self.project, expansion=True)


if __name__ == '__main__':
    unittest.main()
