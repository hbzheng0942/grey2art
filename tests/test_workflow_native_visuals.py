"""Synthetic native visual ownership contracts; never native execution evidence."""
from pathlib import Path
import copy
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1] / 'skills/greybox-to-multistyle-art'
sys.path.insert(0, str(ROOT / 'runtime'))
sys.dont_write_bytecode = True
from greybox import core, layout, scene_review, workflow
from workflow_fixtures import make_workflow, approve, refresh_evidence, review_fixture, evidence


class NativeVisualOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='gb-native-visuals-')
        self.project = Path(self.tmp.name) / 'project'
        shutil.copytree(ROOT / 'fixtures/godot-free', self.project)
        self.plan = core.read(self.project / 'plan.json')
        self.plan.pop('purpose')
        self.plan['styles'] = self.plan['styles'][:1]
        self.plan['delivery_mode'] = 'single_style'
        self.path, self.data = make_workflow(self.project, self.plan, initialize_control=False)

    def tearDown(self):
        self.tmp.cleanup()

    def stage(self, sid, scope='ceramic'):
        return next(s for s in self.data['stages'] if s['id'] == sid and s['scope'] == scope)

    def value(self, role):
        return core.read(next(e['path'] for e in self.stage('production_plan')['evidence'] if e['role'] == role))

    def write(self, role, value):
        refresh_evidence(self.stage('production_plan'), role, value)

    def save(self):
        digests = {}
        for stage in self.data['stages']:
            sid, scope = stage['id'], stage['scope']
            stage['consumes'] = {d: digests[d] for d in workflow.dependencies(sid, scope)}
            if sid == 'selection':
                item = next(e for e in stage['evidence'] if e['role'] == 'selection_decision')
                value = core.read(item['path']); value['directions_digest'] = digests['shared/directions']
                refresh_evidence(stage, 'selection_decision', value)
            elif sid == 'spatial_design':
                item = next(e for e in stage['evidence'] if e['role'] == 'spatial_graph')
                value = core.read(item['path']); value['atlas_digest'] = digests[scope + '/atlas']
                refresh_evidence(stage, 'spatial_graph', value)
            elif sid == 'production_plan':
                value = self.value('assembly_recipe'); value['spatial_design_digest'] = digests[scope + '/spatial_design']
                self.write('assembly_recipe', value)
            review_fixture(stage)
            if sid in workflow.HUMAN_STAGES:
                approve(stage)
            digests[scope + '/' + sid] = workflow.stage_digest(stage)
        core.write(self.path, self.data)
        self.plan['workflow'] = {'path': str(self.path), 'sha256': core.file_hash(self.path)}

    def native(self, only=False, keep_bindings=False):
        table, recipe, package = (self.value(role) for role in ('production_table', 'assembly_recipe', 'visual_package'))
        unit = copy.deepcopy(recipe['assemblies'][0])
        unit.update(id='native-lighting', asset_ids=[], native_realization={
            'kind': 'lighting', 'target': 'SYNTHETIC existing scene WorldEnvironment',
            'method': 'SYNTHETIC native environment settings', 'evidence_image_id': 'ceramic-map-image'})
        recipe['assemblies'] = [unit] if only else recipe['assemblies'] + [unit]
        annotation = {'assembly_id': unit['id'], 'asset_ids': [], 'image_id': 'ceramic-map-image', 'region': [0, 0, 1, 1]}
        package['assembly_annotations'] = [annotation] if only else package['assembly_annotations'] + [annotation]
        features = table['visual_features'] if only else table['visual_features'][1:]
        for feature in features:
            feature.update(asset_ids=[], assembly_ids=[unit['id']], responsibility='environment', feature_kind='light')
        if only:
            table['asset_proposals'] = []
            package['bom'] = []
            table['composition_owners'] = {layer: [unit['id']] for layer in workflow.COMPOSITION_LAYERS}
            if not keep_bindings:
                self.plan.update(assets=[], bindings=[])
            plan_digest = workflow.execution_plan_digest(self.plan)
            table['execution_plan_digest'] = recipe['execution_plan_digest'] = plan_digest
            table['sample_contract']['execution_plan_digest'] = plan_digest
            scope = self.value('scope_decision'); scope['execution_plan_digest'] = plan_digest
            self.write('scope_decision', scope)
        else:
            table['composition_owners']['lighting_materials'] = [unit['id']]
        for role, value in [('production_table', table), ('assembly_recipe', recipe), ('visual_package', package)]:
            self.write(role, value)
        self.save()

    def check(self):
        return workflow.check_plan_gate(self.plan, self.project, require_current_capabilities=False)

    def mutate(self, role, change):
        value = self.value(role); change(value); self.write(role, value); self.save()

    def test_existing_asset_bound_plan_remains_valid(self):
        self.save()
        self.assertTrue(self.check()['ok'])

    def test_native_effect_has_own_responsibility_without_fake_asset(self):
        self.native()
        self.assertTrue(self.check()['ok'])

    def test_native_only_production_can_have_empty_asset_catalog_and_bom(self):
        self.native(only=True)
        result = self.check()
        self.assertTrue(result['ok'])
        self.assertEqual(result['production_asset_proposals']['ceramic'], [])
        self.assertEqual(core.validate_plan(self.plan)['generationTasks'], 0)

    def test_form_cannot_be_satisfied_only_by_native_environment_owner(self):
        self.native(only=True)
        self.mutate('production_table', lambda t: t['visual_features'][0].update(feature_kind='form'))
        with self.assertRaisesRegex(core.WorkflowError, 'Form requirements need actual asset sources'):
            self.check()

    def test_public_prepare_keeps_native_only_workflow_and_control_gates(self):
        from production_control_fixtures import fixture_control
        self.native(only=True)
        fixture_control(self.project, self.plan, self.path)
        plan_path = self.project / 'native-plan.json'
        core.write(plan_path, self.plan)
        run = layout.run_root(self.project, self.plan, 'native-only')
        core.prepare(plan_path, self.project, run)
        state = core.read(run / 'run.json')
        self.assertEqual(state['state'], 'planned')
        self.assertEqual(state['assets'], {})
        self.assertEqual(state['artifacts'], {})

    def test_binding_free_shape_does_not_authorize_missing_or_stale_workflow(self):
        self.native(only=True)
        without_workflow = copy.deepcopy(self.plan); without_workflow.pop('workflow')
        with self.assertRaisesRegex(core.WorkflowError, 'native-only production needs its workflow'):
            core.validate_plan(without_workflow)
        self.plan['workflow']['sha256'] = '0' * 64
        self.assertEqual(core.validate_plan(self.plan)['generationTasks'], 0)
        plan_path = self.project / 'invalid-native-plan.json'; core.write(plan_path, self.plan)
        run = layout.run_root(self.project, self.plan, 'invalid-native')
        with self.assertRaisesRegex(core.WorkflowError, 'Workflow receipt missing/changed'):
            core.prepare(plan_path, self.project, run)
        self.assertFalse((run / 'run.json').exists())

    def test_public_prepare_rejects_unknown_native_owner_before_run_creation(self):
        self.native(only=True)
        self.mutate('production_table', lambda t: t['visual_features'][0].update(assembly_ids=['unknown-owner']))
        plan_path = self.project / 'invalid-native-plan.json'; core.write(plan_path, self.plan)
        run = layout.run_root(self.project, self.plan, 'invalid-native')
        with self.assertRaisesRegex(core.WorkflowError, 'unknown or non-native assembly'):
            core.prepare(plan_path, self.project, run)
        self.assertFalse((run / 'run.json').exists())

    def test_binding_free_plan_still_requires_an_approved_native_owner(self):
        self.plan['bindings'] = []
        plan_digest = workflow.execution_plan_digest(self.plan)
        for role in ('production_table', 'assembly_recipe', 'scope_decision'):
            value = self.value(role); value['execution_plan_digest'] = plan_digest
            if role == 'production_table':
                value['sample_contract']['execution_plan_digest'] = plan_digest
            self.write(role, value)
        self.save()
        with self.assertRaisesRegex(core.WorkflowError, 'needs approved native assembly owners'):
            self.check()

    def test_native_owner_cannot_hide_executable_inline_mesh_sources(self):
        for source in ({'primitive': 'box'}, {'route': 'reuse', 'path': 'res://raw_probe.tscn'}):
            with self.subTest(source=source):
                self.plan['bindings'] = [{'id': 'actual-mesh', 'owner': 'Target', 'source': source}]
                self.native(only=True, keep_bindings=True)
                with self.assertRaisesRegex(core.WorkflowError, 'omits an executable asset source'):
                    self.check()

    def test_missing_native_owner_is_not_a_skip_route(self):
        self.native()
        self.mutate('production_table', lambda t: t['visual_features'][1].update(assembly_ids=[]))
        with self.assertRaisesRegex(core.WorkflowError, 'needs asset families or a declared native'):
            self.check()

    def test_unknown_or_asset_only_assembly_is_not_a_native_owner(self):
        self.native()
        asset_unit = self.value('assembly_recipe')['assemblies'][0]['id']
        for owner in ('unknown-owner', asset_unit):
            self.mutate('production_table', lambda t: t['visual_features'][1].update(assembly_ids=[owner]))
            with self.assertRaisesRegex(core.WorkflowError, 'unknown or non-native assembly'):
                self.check()

    def test_native_owner_needs_actual_image_evidence(self):
        self.native()
        self.mutate('assembly_recipe', lambda r: r['assemblies'][-1]['native_realization'].update(evidence_image_id='unknown-image'))
        with self.assertRaisesRegex(core.WorkflowError, 'actual H3 BOM or assembly image'):
            self.check()

    def test_native_owner_requires_method_and_cannot_claim_mesh_generation(self):
        self.native()
        self.mutate('assembly_recipe', lambda r: r['assemblies'][-1]['native_realization'].update(method=''))
        with self.assertRaisesRegex(core.WorkflowError, 'mesh production stays in asset proposals'):
            self.check()
        self.mutate('assembly_recipe', lambda r: r['assemblies'][-1]['native_realization'].update(method='SYNTHETIC', kind='mesh'))
        with self.assertRaisesRegex(core.WorkflowError, 'mesh production stays in asset proposals'):
            self.check()

    def test_precise_geometry_cannot_be_delegated_only_to_native_effect(self):
        self.native()
        self.mutate('production_table', lambda t: t['visual_features'][1].update(responsibility='precise_geometry'))
        with self.assertRaisesRegex(core.WorkflowError, 'Precise geometry responsibility'):
            self.check()

    def test_native_assembly_cannot_silently_drop_its_mesh_responsibility(self):
        self.native()
        asset = self.value('production_table')['asset_proposals'][0]['asset_id']
        self.mutate('assembly_recipe', lambda r: r['assemblies'][-1].update(asset_ids=[asset]))
        self.mutate('visual_package', lambda p: p['assembly_annotations'][-1].update(asset_ids=[asset]))
        with self.assertRaisesRegex(core.WorkflowError, "omits its native assembly's asset"):
            self.check()

    def test_unmapped_native_work_is_not_complete_visual_responsibility(self):
        self.native()
        self.mutate('production_table', lambda t: t['visual_features'][1].update(
            assembly_ids=[], asset_ids=[a['asset_id'] for a in t['asset_proposals']]))
        with self.assertRaisesRegex(core.WorkflowError, 'omits native assembly owners'):
            self.check()

    def test_native_only_keeps_required_h3_boards(self):
        self.native(only=True)
        self.stage('production_plan')['evidence'] = [e for e in self.stage('production_plan')['evidence'] if e['role'] != 'bom_board']
        self.save()
        with self.assertRaisesRegex(core.WorkflowError, 'actual BOM'):
            self.check()

    def test_native_feature_still_blocks_h4_when_comparison_fails(self):
        self.path, self.data = make_workflow(self.project, self.plan, expansion=True, initialize_control=False)
        sample = self.stage('representative_sample')
        item = next(e for e in sample['evidence'] if e['role'] == 'sample_source_production')
        source = core.read(item['path'])
        table_item = next(e for e in source['evidence'] if e['role'] == 'production_table')
        table = core.read(table_item['path'])
        table['sample_contract']['scene_comparison'] = scene_review.CONTRACT
        table['visual_features'][1].update(asset_ids=[], assembly_ids=['native-lighting'], responsibility='environment')
        refresh_evidence(source, 'production_table', table)
        core.write(item['path'], source); item['sha256'] = core.file_hash(item['path'])
        sample['consumes'] = {'ceramic/production_plan': workflow.stage_digest(source)}
        inputs = scene_review.inputs_for_stage(self.data, self.project, sample)
        report = scene_review.draft(inputs)
        report.update(reviewer={'agent_id': 'synthetic-reviewer', 'task_id': 'synthetic-native-review'}, source_ref='synthetic://review')
        for row in report['comparisons']:
            row.update(status='pass', observation='SYNTHETIC ' + row['id'])
            for layer in row.get('layers', []):
                layer.update(status='pass', observation='SYNTHETIC ' + layer['id'])
        native = next(row for row in report['comparisons'] if row['id'].startswith('feature/material-language/'))
        native.update(status='fail', observation='SYNTHETIC missing lighting response', next_action='Repair native effect and recapture')
        sample['evidence'].append(evidence(self.project, 'native-feature-review.json', 'scene_comparison', report))
        with self.assertRaisesRegex(core.WorkflowError, 'feature/material-language'):
            scene_review.validate_stage(self.data, self.project, sample)


if __name__ == '__main__':
    unittest.main()
