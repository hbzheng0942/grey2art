"""Adversarial offline integrity checks. All art/user/native receipts are synthetic."""
from pathlib import Path
import copy
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1] / 'skills/greybox-to-multistyle-art'
sys.path.insert(0, str(ROOT / 'runtime'))
sys.dont_write_bytecode = True
from greybox import core, workflow
from workflow_fixtures import make_workflow, capabilities, approve, refresh_evidence, png


class WorkflowV2Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='gb-r2-gates-')
        self.project = Path(self.tmp.name) / 'project'
        shutil.copytree(ROOT / 'fixtures/godot-free', self.project)
        self.plan = core.read(self.project / 'plan.json')
        self.plan.pop('purpose')

    def tearDown(self):
        self.tmp.cleanup()

    def fixture(self, **kwargs):
        self.path, self.data = make_workflow(self.project, self.plan, **kwargs)
        return self.path, self.data

    def stage(self, sid, scope='ceramic'):
        return next(s for s in self.data['stages'] if s['id'] == sid and s['scope'] == scope)

    def value(self, stage, role):
        return core.read(next(e['path'] for e in stage['evidence'] if e['role'] == role))

    def save(self):
        core.write(self.path, self.data)

    def sample_mutation(self, role, mutate):
        self.fixture(expansion=True)
        sample = self.stage('representative_sample')
        value = self.value(sample, role)
        mutate(value)
        refresh_evidence(sample, role, value)
        approve(sample)  # Deliberately false outer acceptance must not mask a failed report.
        self.save()

    def test_schema1_never_infers_approval_migration(self):
        self.fixture()
        self.data['schema'] = 1
        self.save()
        with self.assertRaisesRegex(core.WorkflowError, 'Never infer approvals'):
            workflow.inspect_workflow(self.path, self.project)

    def test_replaced_direction_with_updated_file_hash_stales_selection(self):
        self.fixture()
        stage = self.stage('directions', 'shared')
        item = next(e for e in stage['evidence'] if e['role'] == 'concept_image')
        Path(item['path']).write_bytes(png(77))
        item['sha256'] = core.file_hash(item['path'])
        manifest = self.value(stage, 'directions_manifest')
        manifest['candidates'][0]['concept_sha256'] = item['sha256']
        refresh_evidence(stage, 'directions_manifest', manifest)
        stage['revision'] += 1
        self.save()
        with self.assertRaisesRegex(core.WorkflowError, 'Stale upstream'):
            workflow.inspect_workflow(self.path, self.project)

    def test_selection_cannot_rebind_directions_without_new_decision(self):
        self.fixture()
        stage = self.stage('selection', 'shared')
        value = self.value(stage, 'selection_decision')
        value['selected'][0]['concept_sha256'] = 'f' * 64
        refresh_evidence(stage, 'selection_decision', value)
        self.save()
        with self.assertRaisesRegex(core.WorkflowError, 'approval is stale'):
            workflow.inspect_workflow(self.path, self.project)

    def test_atlas_requires_actual_user_approval(self):
        self.fixture()
        self.stage('atlas')['actor'] = 'agent'
        self.save()
        with self.assertRaisesRegex(core.WorkflowError, 'actual user'):
            workflow.inspect_workflow(self.path, self.project)

    def test_spatial_approval_cannot_be_copied_from_another_scope(self):
        self.fixture()
        self.stage('spatial_design')['approval'] = copy.deepcopy(self.stage('spatial_design', 'orbital')['approval'])
        self.save()
        with self.assertRaisesRegex(core.WorkflowError, 'another scope'):
            workflow.inspect_workflow(self.path, self.project)

    def test_revision_change_alone_invalidates_old_approval(self):
        self.fixture()
        self.stage('atlas')['revision'] += 1
        self.save()
        with self.assertRaisesRegex(core.WorkflowError, 'approval is stale'):
            workflow.inspect_workflow(self.path, self.project)

    def test_missing_consumed_dependency_blocks(self):
        self.fixture()
        self.stage('art_proxy')['consumes'] = {}
        self.save()
        with self.assertRaisesRegex(core.WorkflowError, 'exact upstream'):
            workflow.inspect_workflow(self.path, self.project)

    def test_eight_images_must_not_reuse_one_file(self):
        self.fixture()
        stage = self.stage('directions', 'shared')
        images = [e for e in stage['evidence'] if e['role'] == 'concept_image']
        Path(images[1]['path']).write_bytes(Path(images[0]['path']).read_bytes())
        images[1]['sha256'] = images[0]['sha256']
        manifest = self.value(stage, 'directions_manifest')
        manifest['candidates'][1]['concept_sha256'] = images[0]['sha256']
        refresh_evidence(stage, 'directions_manifest', manifest)
        self.save()
        with self.assertRaisesRegex(core.WorkflowError, 'same image'):
            workflow.inspect_workflow(self.path, self.project)

    def test_palette_only_declared_variants_rejected(self):
        self.fixture()
        stage = self.stage('directions', 'shared')
        manifest = self.value(stage, 'directions_manifest')
        first = manifest['candidates'][0]['brief']
        manifest['candidates'][1]['brief'] = {**first, 'light_palette': 'different palette only'}
        refresh_evidence(stage, 'directions_manifest', manifest)
        self.save()
        with self.assertRaisesRegex(core.WorkflowError, 'substantive'):
            workflow.inspect_workflow(self.path, self.project)

    def test_smaller_user_scoped_set_allowed(self):
        self.fixture(candidate_count=2)
        self.assertTrue(workflow.inspect_workflow(self.path, self.project)['ok'])

    def test_smaller_set_without_actual_scope_blocked(self):
        self.fixture(candidate_count=2)
        stage = self.stage('directions', 'shared')
        value = self.value(stage, 'directions_manifest')
        value.pop('count_override')
        refresh_evidence(stage, 'directions_manifest', value)
        self.save()
        with self.assertRaisesRegex(core.WorkflowError, '8–10'):
            workflow.inspect_workflow(self.path, self.project)

    def test_approved_import_needs_explicit_bound_import_decision(self):
        self.fixture()
        self.data['concept_source'] = 'approved_import'
        self.save()
        with self.assertRaisesRegex(core.WorkflowError, 'imported candidate set'):
            workflow.inspect_workflow(self.path, self.project)

    def test_refreshed_capabilities_do_not_reapprove_design(self):
        self.fixture()
        preflight = self.stage('preflight', 'shared')
        archived = self.value(preflight, 'capability_report')
        archived['checked_at'] = '2020-01-01T00:00:00+00:00'
        refresh_evidence(preflight, 'capability_report', archived)
        self.save()
        before = self.path.read_bytes()
        with self.assertRaisesRegex(core.WorkflowError, 'expired'):
            workflow.inspect_workflow(self.path, self.project)
        result = workflow.inspect_workflow(self.path, self.project,
                    capability_report=capabilities('new-session'), expected_session='new-session')
        self.assertTrue(result['ok'])
        self.assertEqual(before, self.path.read_bytes())

    def test_operational_report_still_must_match_current_session(self):
        self.fixture()
        with self.assertRaisesRegex(core.WorkflowError, 'another host session'):
            workflow.inspect_workflow(self.path, self.project,
                capability_report=capabilities('old-session'), expected_session='new-session')

    def test_historical_integrity_inspection_can_skip_operational_freshness(self):
        self.fixture()
        stage = self.stage('preflight', 'shared')
        value = self.value(stage, 'capability_report')
        value['checked_at'] = '2020-01-01T00:00:00+00:00'
        refresh_evidence(stage, 'capability_report', value)
        self.save()
        result = workflow.inspect_workflow(self.path, self.project, require_current_capabilities=False)
        self.assertTrue(result['ok'])
        self.assertFalse(result['capabilities_current'])

    def test_actual_plan_must_match_production_evidence(self):
        self.fixture()
        self.plan['workflow'] = {'path': str(self.path), 'sha256': core.file_hash(self.path)}
        self.assertTrue(workflow.check_plan_gate(self.plan, self.project)['ok'])
        self.plan['bindings'][0]['uniform_scale'] = 0.6
        with self.assertRaisesRegex(core.WorkflowError, 'Executable plan differs'):
            workflow.check_plan_gate(self.plan, self.project)

    def test_even_new_production_approval_cannot_change_baseline_scene(self):
        expanded = copy.deepcopy(self.plan)
        expanded['contract']['scene'] = 'res://another-game.tscn'
        self.fixture(expansion=True, expanded_plan=expanded)
        expanded['workflow'] = {'path': str(self.path), 'sha256': core.file_hash(self.path), 'production_scope': 'expansion'}
        with self.assertRaisesRegex(core.WorkflowError, 'scene differs'):
            workflow.check_plan_gate(expanded, self.project)

    def test_same_check_ids_cannot_hide_changed_gameplay_expectations(self):
        expanded = copy.deepcopy(self.plan)
        expanded['contract']['validation']['steps'][0]['expect']['collision_count'] = 999
        self.fixture(expansion=True, expanded_plan=expanded)
        expanded['workflow'] = {'path': str(self.path), 'sha256': core.file_hash(self.path), 'production_scope': 'expansion'}
        with self.assertRaisesRegex(core.WorkflowError, 'validation differs'):
            workflow.check_plan_gate(expanded, self.project)

    def test_digest_excludes_only_receipt_fields(self):
        original = workflow.execution_plan_digest(self.plan)
        self.plan['workflow'] = {'path': 'new-receipt', 'session_id': 'new-session'}
        self.plan['operational_receipts'] = {'capabilities': 'fresh'}
        self.assertEqual(original, workflow.execution_plan_digest(self.plan))
        self.plan['effective_policy'] = {'allowed_versions': ['G1']}
        self.assertNotEqual(original, workflow.execution_plan_digest(self.plan))

    def test_expansion_accepts_current_plan_and_original_sample_plan(self):
        expanded = copy.deepcopy(self.plan)
        expanded['bindings'][0]['uniform_scale'] = 1.02
        self.fixture(expansion=True, expanded_plan=expanded)
        expanded['workflow'] = {'path': str(self.path), 'sha256': core.file_hash(self.path), 'production_scope': 'expansion'}
        result = workflow.check_plan_gate(expanded, self.project)
        self.assertTrue(result['ok'])
        self.assertNotEqual(self.stage('representative_sample')['identity']['execution_plan_digest'], result['execution_plan_digest'])

    def test_expansion_requires_source_sample_receipt(self):
        self.fixture(expansion=True)
        stage = self.stage('representative_sample')
        stage['evidence'] = [e for e in stage['evidence'] if e['role'] != 'sample_source_production']
        approve(stage)
        self.save()
        with self.assertRaisesRegex(core.WorkflowError, 'sample_source_production'):
            workflow.inspect_workflow(self.path, self.project, expansion=True)

    def test_failed_technical_report_not_overridden_by_outer_acceptance(self):
        self.sample_mutation('technical_report', lambda d: d.update(passed=False))
        with self.assertRaisesRegex(core.WorkflowError, 'reports failure'):
            workflow.inspect_workflow(self.path, self.project, expansion=True)

    def test_failed_gameplay_report_not_overridden_by_outer_acceptance(self):
        self.sample_mutation('gameplay_report', lambda d: d.update(passed=False))
        with self.assertRaisesRegex(core.WorkflowError, 'reports failure'):
            workflow.inspect_workflow(self.path, self.project, expansion=True)

    def test_partial_gameplay_check_coverage_blocks(self):
        self.sample_mutation('gameplay_report', lambda d: d.update(passed_check_ids=['baseline']))
        with self.assertRaisesRegex(core.WorkflowError, 'incomplete required'):
            workflow.inspect_workflow(self.path, self.project, expansion=True)

    def test_alien_native_attempt_blocks(self):
        self.sample_mutation('technical_report', lambda d: d['identity'].update(attempt_id='alien-attempt'))
        with self.assertRaisesRegex(core.WorkflowError, 'another style/scene/attempt'):
            workflow.inspect_workflow(self.path, self.project, expansion=True)

    def test_alien_input_version_blocks(self):
        self.sample_mutation('gameplay_report', lambda d: d['identity'].update(input_digest='f' * 64))
        with self.assertRaisesRegex(core.WorkflowError, 'another style/scene/attempt'):
            workflow.inspect_workflow(self.path, self.project, expansion=True)

    def test_incomplete_concept_realization_blocks(self):
        self.sample_mutation('visual_review', lambda d: d.update(passed_feature_ids=['landmark-shape']))
        with self.assertRaisesRegex(core.WorkflowError, 'unmet critical'):
            workflow.inspect_workflow(self.path, self.project, expansion=True)

    def test_agent_visual_acceptance_is_not_human_acceptance(self):
        self.sample_mutation('visual_review', lambda d: d.update(actor='agent'))
        with self.assertRaisesRegex(core.WorkflowError, 'human visual'):
            workflow.inspect_workflow(self.path, self.project, expansion=True)

    def test_original_sample_source_files_remain_hash_bound(self):
        self.fixture(expansion=True)
        source = self.value(self.stage('representative_sample'), 'sample_source_production')
        path = next(e['path'] for e in source['evidence'] if e['role'] == 'assembly_recipe')
        Path(path).write_text('{}')
        with self.assertRaisesRegex(core.WorkflowError, 'evidence changed'):
            workflow.inspect_workflow(self.path, self.project, expansion=True)

    def test_sample_source_script_change_invalidates_h4(self):
        self.fixture(expansion=True)
        path = self.project / 'main.gd'
        path.write_text(path.read_text() + '\n# gameplay source changed after sample\n')
        with self.assertRaisesRegex(core.WorkflowError, 'Sample input file changed'):
            workflow.inspect_workflow(self.path, self.project, expansion=True)

    def test_sample_material_change_invalidates_h4(self):
        self.fixture(expansion=True)
        manifest = self.value(self.stage('representative_sample'), 'sample_inputs')
        path = Path(next(f['path'] for f in manifest['files'] if f['path'].endswith('.tres')))
        path.write_text(path.read_text().replace('roughness = 0.4', 'roughness = 0.0'))
        with self.assertRaisesRegex(core.WorkflowError, 'Sample input file changed'):
            workflow.inspect_workflow(self.path, self.project, expansion=True)

    def test_sample_asset_change_invalidates_h4(self):
        self.fixture(expansion=True)
        manifest = self.value(self.stage('representative_sample'), 'sample_inputs')
        path = Path(next(f['path'] for f in manifest['files'] if f['category'] == 'asset'))
        path.write_bytes(png(88))
        with self.assertRaisesRegex(core.WorkflowError, 'Sample input file changed'):
            workflow.inspect_workflow(self.path, self.project, expansion=True)

    def test_sample_project_render_settings_change_invalidates_h4(self):
        self.fixture(expansion=True)
        path = self.project / 'project.godot'
        path.write_text(path.read_text() + '\ntextures/default_filters/use_nearest_mipmap_filter=false\n')
        with self.assertRaisesRegex(core.WorkflowError, 'Sample input file changed'):
            workflow.inspect_workflow(self.path, self.project, expansion=True)

    def test_independent_new_expansion_files_do_not_invalidate_h4(self):
        self.fixture(expansion=True)
        before = workflow.evidence_dependencies(self.path, self.project)
        (self.project / 'new-independent-area.gd').write_text('extends Node3D\n')
        (self.project / 'new-independent-model.glb').write_bytes(b'SYNTHETIC UNREFERENCED NEW ASSET')
        self.assertTrue(workflow.inspect_workflow(self.path, self.project, expansion=True)['ok'])
        self.assertEqual(before, workflow.evidence_dependencies(self.path, self.project))

    def test_replaced_inputs_manifest_does_not_reuse_old_native_identity(self):
        self.fixture(expansion=True)
        stage = self.stage('representative_sample')
        inputs = self.value(stage, 'sample_inputs')
        inputs['note'] = 'changed manifest, old attempt receipts'
        refresh_evidence(stage, 'sample_inputs', inputs)
        approve(stage)
        self.save()
        with self.assertRaisesRegex(core.WorkflowError, 'Sample identity differs'):
            workflow.inspect_workflow(self.path, self.project, expansion=True)

    def test_inputs_manifest_cannot_omit_discoverable_source_dependency(self):
        self.fixture(expansion=True)
        stage = self.stage('representative_sample')
        inputs = self.value(stage, 'sample_inputs')
        inputs['files'] = [f for f in inputs['files'] if not f['path'].endswith('/main.gd')]
        refresh_evidence(stage, 'sample_inputs', inputs)
        approve(stage)
        self.save()
        with self.assertRaisesRegex(core.WorkflowError, 'omit a discoverable'):
            workflow.inspect_workflow(self.path, self.project, expansion=True)

    def test_inputs_manifest_cannot_authorize_external_resource(self):
        self.fixture(expansion=True)
        outside = Path(self.tmp.name) / 'outside-material.tres'
        outside.write_text('SYNTHETIC EXTERNAL FILE')
        stage = self.stage('representative_sample')
        inputs = self.value(stage, 'sample_inputs')
        inputs['files'].append({'id': 'external', 'path': str(outside), 'sha256': core.file_hash(outside), 'category': 'asset'})
        refresh_evidence(stage, 'sample_inputs', inputs)
        approve(stage)
        self.save()
        with self.assertRaisesRegex(core.WorkflowError, 'inside project'):
            workflow.inspect_workflow(self.path, self.project, expansion=True)

    def test_new_import_settings_for_sample_asset_invalidate_h4(self):
        self.fixture(expansion=True)
        inputs = self.value(self.stage('representative_sample'), 'sample_inputs')
        path = Path(next(f['path'] for f in inputs['files'] if f['category'] == 'asset') + '.import')
        path.write_text('[params]\ncompress/mode=0\n')
        with self.assertRaisesRegex(core.WorkflowError, 'import/render settings'):
            workflow.inspect_workflow(self.path, self.project, expansion=True)

    def test_walker_includes_and_verifies_nested_archived_production(self):
        self.fixture(expansion=True)
        source = self.value(self.stage('representative_sample'), 'sample_source_production')
        archived = next(e for e in source['evidence'] if e['role'] == 'assembly_recipe')
        dependencies = {f['path']: f['sha256'] for f in workflow.evidence_dependencies(self.path, self.project)}
        self.assertEqual(dependencies[str(Path(archived['path']).resolve())], archived['sha256'])
        Path(archived['path']).write_text('{}')
        with self.assertRaisesRegex(core.WorkflowError, 'dependency changed'):
            workflow.evidence_dependencies(self.path, self.project)

    def test_walker_includes_and_verifies_sample_resources(self):
        self.fixture(expansion=True)
        inputs = self.value(self.stage('representative_sample'), 'sample_inputs')
        asset = next(f for f in inputs['files'] if f['category'] == 'asset')
        dependencies = {f['path']: f['sha256'] for f in workflow.evidence_dependencies(self.path, self.project)}
        self.assertEqual(dependencies[asset['path']], asset['sha256'])
        Path(asset['path']).write_bytes(png(88))
        with self.assertRaisesRegex(core.WorkflowError, 'Sample input file changed'):
            workflow.evidence_dependencies(self.path, self.project)

    def test_walker_does_not_require_schema2_manifest_for_historical_workflow(self):
        self.fixture()
        self.data['schema'] = 1
        self.save()
        dependencies = workflow.evidence_dependencies(self.path, self.project)
        self.assertTrue(dependencies)
        self.assertNotIn(str(self.path), [f['path'] for f in dependencies])

    def test_h3_does_not_require_future_native_products(self):
        self.fixture()
        table = self.value(self.stage('production_plan'), 'production_table')
        self.assertFalse(core.resolve_input(table['sample_contract']['scene'], self.project).exists())
        self.assertTrue(workflow.inspect_workflow(self.path, self.project)['ok'])

    def test_sample_binds_current_producer_runtime(self):
        self.fixture(expansion=True)
        manifest = self.value(self.stage('representative_sample'), 'sample_inputs')
        self.assertEqual(manifest['producer_runtime_digest'], core.runtime_snapshot()['sha256'])
        self.assertTrue(workflow.inspect_workflow(self.path, self.project, expansion=True)['ok'])

    def test_different_producer_runtime_cannot_reuse_h4(self):
        self.fixture(expansion=True)
        stage = self.stage('representative_sample')
        manifest = self.value(stage, 'sample_inputs')
        manifest['producer_runtime_digest'] = 'f' * 64
        refresh_evidence(stage, 'sample_inputs', manifest)
        approve(stage)
        self.save()
        with self.assertRaisesRegex(core.WorkflowError, 'producer runtime changed'):
            workflow.inspect_workflow(self.path, self.project, expansion=True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
