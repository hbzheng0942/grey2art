"""Offline behavioral tests; all pixels, reviews and decisions are synthetic."""
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
from workflow_fixtures import make_workflow, approve, refresh_evidence, review_fixture, png


class CompleteVisualSampleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='gb-visual-workflow-')
        self.project = Path(self.tmp.name) / 'project'
        shutil.copytree(ROOT / 'fixtures/godot-free', self.project)
        self.plan = core.read(self.project / 'plan.json')
        self.plan.pop('purpose')
        self.plan['styles'] = self.plan['styles'][:1]
        self.path, self.data = make_workflow(self.project, self.plan)

    def tearDown(self):
        self.tmp.cleanup()

    def stage(self, sid, scope='ceramic'):
        return next(s for s in self.data['stages'] if s['id'] == sid and s['scope'] == scope)

    def value(self, sid, role):
        return core.read(next(e['path'] for e in self.stage(sid)['evidence'] if e['role'] == role))

    def save(self):
        core.write(self.path, self.data)

    def rechain(self):
        digests = {}
        for stage in self.data['stages']:
            sid, scope = stage['id'], stage['scope']
            stage['consumes'] = {d: digests[d] for d in workflow.dependencies(sid, scope)}
            if sid == 'selection':
                item = next(e for e in stage['evidence'] if e['role'] == 'selection_decision')
                value = core.read(item['path']); value['directions_digest'] = digests['shared/directions']
                refresh_evidence(stage, 'selection_decision', value)
            elif sid == 'spatial_design':
                value = self.value(sid, 'spatial_graph'); value['atlas_digest'] = digests[scope + '/atlas']
                refresh_evidence(stage, 'spatial_graph', value)
            elif sid == 'production_plan':
                value = self.value(sid, 'assembly_recipe'); value['spatial_design_digest'] = digests[scope + '/spatial_design']
                refresh_evidence(stage, 'assembly_recipe', value)
            review_fixture(stage)
            if sid in workflow.HUMAN_STAGES:
                approve(stage)
            digests[scope + '/' + sid] = workflow.stage_digest(stage)
        self.save()

    def mutate(self, sid, role, mutation):
        value = self.value(sid, role)
        mutation(value)
        refresh_evidence(self.stage(sid), role, value)
        self.rechain()

    def check(self, expansion=False):
        return workflow.inspect_workflow(self.path, self.project, expansion=expansion)

    def test_complete_visual_sample_and_expansion_pass_offline(self):
        self.assertEqual(self.check()['ready_for'], 'representative_production')
        self.path, self.data = make_workflow(self.project, self.plan, expansion=True)
        self.assertEqual(self.check(True)['ready_for'], 'expansion_production')

    def scoped_expansion(self):
        views = [{'id': space + '-overview', 'camera_id': space + '-camera', 'state_id': 'playing',
            'framing': 'whole_composition', 'space_ids': [space], 'required_layers': sorted(workflow.COMPOSITION_LAYERS)}
            for space in ('start', 'end')]
        self.path, self.data = make_workflow(self.project, self.plan, expansion=True,
            sample_space_ids=['start'], expansion_space_ids=['start'], observation_views=views)
        self.assertTrue(self.check(True)['ok'])

    def expand_current_production(self, spaces, view_ids):
        stage = self.stage('production_plan')
        table = self.value('production_plan', 'production_table')
        table.update(production_space_ids=spaces, production_view_ids=view_ids)
        for feature in table['visual_features']:
            feature['native_view_ids'] = view_ids
        refresh_evidence(stage, 'production_table', table)
        recipe = self.value('production_plan', 'assembly_recipe')
        for assembly in recipe['assemblies']:
            assembly['space_ids'] = spaces
        refresh_evidence(stage, 'assembly_recipe', recipe)
        stage['revision'] += 1
        approve(stage)
        self.save()

    def test_expansion_adds_approved_end_space_without_rewriting_start_sample(self):
        self.scoped_expansion()
        sample = copy.deepcopy(self.stage('representative_sample'))
        sample_contract = copy.deepcopy(self.value('production_plan', 'production_table')['sample_contract'])
        source = self.value('representative_sample', 'sample_source_production')
        source_files = {e['path']: Path(e['path']).read_bytes() for e in source['evidence']}
        self.expand_current_production(['start', 'end'], ['start-overview', 'end-overview'])
        self.assertEqual(self.check(True)['ready_for'], 'expansion_production')
        self.assertEqual(self.stage('representative_sample'), sample)
        self.assertEqual(self.value('production_plan', 'production_table')['sample_contract'], sample_contract)
        self.assertEqual(sample_contract['sample_space_ids'], ['start'])
        self.assertEqual(sample_contract['required_view_ids'], ['start-overview'])
        for path, content in source_files.items():
            self.assertEqual(Path(path).read_bytes(), content)

    def test_expansion_cannot_add_unapproved_space(self):
        self.scoped_expansion()
        self.expand_current_production(['start', 'secret'], ['start-overview'])
        with self.assertRaisesRegex(core.WorkflowError, 'unknown baseline spaces'):
            self.check(True)

    def test_expansion_needs_views_for_new_spaces_not_only_old_sample(self):
        self.scoped_expansion()
        self.expand_current_production(['start', 'end'], ['start-overview'])
        with self.assertRaisesRegex(core.WorkflowError, 'every approved observation'):
            self.check(True)

    def test_expansion_scope_cannot_use_representative_gate_to_skip_h4(self):
        self.scoped_expansion()
        self.expand_current_production(['start', 'end'], ['start-overview', 'end-overview'])
        with self.assertRaisesRegex(core.WorkflowError, 'Expansion scope requires the H4'):
            self.check(False)

    def test_only_text_h3_is_not_producible(self):
        stage = self.stage('production_plan')
        stage['evidence'] = [e for e in stage['evidence'] if e['role'] not in {'bom_board', 'assembly_map'}]
        approve(stage); self.save()
        with self.assertRaisesRegex(core.WorkflowError, 'actual BOM'):
            self.check()

    def test_png_signature_without_pixels_is_not_a_board(self):
        item = next(e for e in self.stage('production_plan')['evidence'] if e['role'] == 'bom_board')
        Path(item['path']).write_bytes(b'\x89PNG\r\n\x1a\nnot-an-image')
        item['sha256'] = core.file_hash(item['path'])
        approve(self.stage('production_plan')); self.save()
        with self.assertRaisesRegex(core.WorkflowError, 'PNG'):
            self.check()

    def test_bom_must_include_every_committed_source(self):
        self.mutate('production_plan', 'visual_package', lambda v: v['bom'].pop())
        with self.assertRaisesRegex(core.WorkflowError, 'BOM omits'):
            self.check()

    def test_assembly_annotation_must_match_recipe(self):
        self.mutate('production_plan', 'visual_package', lambda v: v['assembly_annotations'][0].update(asset_ids=['invented']))
        with self.assertRaisesRegex(core.WorkflowError, 'annotation assets'):
            self.check()

    def test_bom_region_outside_image_is_rejected(self):
        self.mutate('production_plan', 'visual_package', lambda v: v['bom'][0].update(region=[.9, 0, .2, 1]))
        with self.assertRaisesRegex(core.WorkflowError, 'bounded normalized'):
            self.check()

    def test_missing_design_cannot_be_labelled_complete_h3(self):
        self.mutate('production_plan', 'visual_package', lambda v: v['bom'][0].update(reference_status='missing'))
        with self.assertRaisesRegex(core.WorkflowError, 'missing/reference-only'):
            self.check()

    def test_dominant_procedural_form_requires_actual_match_evidence(self):
        self.mutate('production_plan', 'production_table', lambda v: v['asset_proposals'][0].pop('procedural_visual_match'))
        with self.assertRaisesRegex(core.WorkflowError, 'Dominant procedural appearance'):
            self.check()

    def test_dominant_form_cannot_skip_route_evaluation(self):
        self.mutate('production_plan', 'production_table', lambda t: t['asset_proposals'][0].pop('route_evaluation'))
        with self.assertRaisesRegex(core.WorkflowError, 'explicit generated/reuse/procedural'):
            self.check()

    def test_environment_label_cannot_waive_dominant_form_evidence(self):
        def conceal(table):
            for feature in table['visual_features']:
                feature['responsibility'] = 'environment'
            table['asset_proposals'][0].pop('procedural_visual_match')
        self.mutate('production_plan', 'production_table', conceal)
        with self.assertRaisesRegex(core.WorkflowError, 'even when its responsibility is environment'):
            self.check()

    def test_hybrid_label_cannot_replace_a_real_model_operation(self):
        def conceal(table):
            table['asset_proposals'][0].update(route='hybrid', generated_visual_role='SYNTHETIC shell',
                                              controlled_structure_role='SYNTHETIC support')
        self.mutate('production_plan', 'production_table', conceal)
        self.mutate('production_plan', 'visual_package', lambda v: v['bom'][0].update(reference_status='production_ready'))
        with self.assertRaisesRegex(core.WorkflowError, 'actual image-conditioned model operation'):
            self.check()

    def test_missing_feature_kind_cannot_hide_form_as_native_work(self):
        self.mutate('production_plan', 'production_table', lambda t: t['visual_features'][0].pop('feature_kind'))
        with self.assertRaisesRegex(core.WorkflowError, 'needs feature_kind'):
            self.check()

    def test_rule_expressible_style_is_not_forced_to_buy_ai_models(self):
        self.assertTrue(all(a['route'] in {'procedural', 'reuse'} for a in self.value('production_plan', 'production_table')['asset_proposals']))
        self.assertTrue(self.check()['ok'])

    def test_reused_appearance_with_procedural_structure_needs_no_new_ai_task(self):
        self.plan['bindings'][0]['source'] = {'route': 'reuse', 'path': 'res://raw_probe.tscn'}
        self.plan['bindings'][0].pop('styles', None)
        self.path, self.data = make_workflow(self.project, self.plan, expansion=True, initialize_control=False)
        table = self.value('production_plan', 'production_table')
        self.assertEqual({a['route'] for a in table['asset_proposals']}, {'reuse', 'procedural'})
        self.assertEqual(self.value('representative_sample', 'sample_inputs')['model_task_bindings'], [])
        self.assertTrue(self.check(True)['ok'])

    def test_generated_label_without_generation_cannot_bypass_route_reason(self):
        self.mutate('production_plan', 'production_table', lambda v: v['asset_proposals'][0].update(route='generated'))
        visual = self.value('production_plan', 'visual_package')
        visual['bom'][0]['reference_status'] = 'production_ready'
        refresh_evidence(self.stage('production_plan'), 'visual_package', visual)
        self.rechain()
        with self.assertRaisesRegex(core.WorkflowError, 'actual image-conditioned'):
            self.check()

    def test_main_visual_responsibility_cannot_be_omitted(self):
        self.mutate('production_plan', 'production_table', lambda v: v.update(visual_features=[]))
        with self.assertRaisesRegex(core.WorkflowError, 'visual features'):
            self.check()

    def test_environment_cannot_be_unowned_future_work(self):
        self.mutate('production_plan', 'production_table', lambda v: v['composition_owners'].pop('environment'))
        with self.assertRaisesRegex(core.WorkflowError, 'visual layer needs an assembly owner'):
            self.check()

    def test_h3_cannot_omit_a_required_gameplay_state_in_its_sample_spaces(self):
        stage = self.stage('baseline', 'shared')
        item = next(e for e in stage['evidence'] if e['role'] == 'spatial_contract')
        value = core.read(item['path'])
        additional = copy.deepcopy(value['observations']['views'][0])
        additional.update(id='interaction', state_id='interacting', framing='interaction')
        value['observations']['views'].append(additional)
        refresh_evidence(stage, 'spatial_contract', value)
        proxy_stage = self.stage('art_proxy')
        item = next(e for e in proxy_stage['evidence'] if e['role'] == 'proxy_capture')
        second_image = dict(item, id='second-proxy-image')
        second_path = Path(item['path']).with_name('second-proxy.png')
        second_path.write_bytes(png(19)); second_image.update(path=str(second_path), sha256=core.file_hash(second_path))
        proxy_stage['evidence'].append(second_image)
        value = self.value('art_proxy', 'native_proxy')
        second_capture = copy.deepcopy(value['captures'][0])
        second_capture.update(view_id='interaction', state_id='interacting', framing='interaction',
            image_id=second_image['id'], path=second_image['path'], sha256=second_image['sha256'])
        value['captures'].append(second_capture)
        refresh_evidence(proxy_stage, 'native_proxy', value)
        self.rechain()
        with self.assertRaisesRegex(core.WorkflowError, 'every approved view/state'):
            self.check()

    def test_far_future_backlog_does_not_expand_current_sample_gate(self):
        self.mutate('production_plan', 'production_table', lambda v: v.update(future_backlog=[{'asset_id': 'later-' + str(i)} for i in range(40)]))
        self.assertTrue(self.check()['ok'])

    def test_s6_can_expose_missing_layers_without_claiming_h4_quality(self):
        def mark_missing(value):
            capture = value['captures'][0]
            capture['visible_layers'].remove('environment')
            capture['missing_layers'] = ['environment']
        self.mutate('art_proxy', 'native_proxy', mark_missing)
        self.assertTrue(self.check()['ok'])

    def test_unresolved_spatial_risk_still_blocks_production(self):
        self.mutate('art_proxy', 'risk_review', lambda v: v['risks'][0].update(status='unresolved', next_action='SYNTHETIC resolve support'))
        with self.assertRaisesRegex(core.WorkflowError, 'unresolved production risk'):
            self.check()

    def test_s6_needs_actual_observation_pixels(self):
        stage = self.stage('art_proxy')
        stage['evidence'] = [e for e in stage['evidence'] if e['role'] != 'proxy_capture']
        self.rechain()
        with self.assertRaisesRegex(core.WorkflowError, 'actual native composition'):
            self.check()

    def sample_mutate(self, mutation):
        self.path, self.data = make_workflow(self.project, self.plan, expansion=True)
        value = self.value('representative_sample', 'native_sample')
        mutation(value)
        refresh_evidence(self.stage('representative_sample'), 'native_sample', value)
        approve(self.stage('representative_sample')); self.save()

    def test_h4_closeup_cannot_replace_whole_composition(self):
        self.sample_mutate(lambda v: v['captures'][0].update(framing='interaction'))
        with self.assertRaisesRegex(core.WorkflowError, 'camera/state/framing'):
            self.check(True)

    def test_h4_missing_environment_is_not_a_complete_sample(self):
        def missing(value):
            value['captures'][0]['visible_layers'].remove('environment')
            value['captures'][0]['missing_layers'] = ['environment']
        self.sample_mutate(missing)
        with self.assertRaisesRegex(core.WorkflowError, 'missing composition layers'):
            self.check(True)

    def test_review_input_builder_is_read_only_and_does_not_pass_review(self):
        stage = self.stage('production_plan')
        stage.pop('review'); stage.pop('approval'); stage['status'] = 'draft'; self.save()
        before = self.path.read_bytes()
        inputs = workflow.build_review_inputs(self.path, self.project, 'ceramic/production_plan')
        self.assertEqual(before, self.path.read_bytes())
        self.assertIn('bom_and_assembly_readable', inputs['criteria'])
        self.assertNotIn('ok', inputs)
        self.assertGreaterEqual(sum('dimensions' in a for a in inputs['artifacts']), 4)
        self.assertNotIn('review', inputs['stage_content'])

    def test_review_digest_has_no_approval_recursion(self):
        before = workflow.build_review_inputs(self.path, self.project, 'ceramic/production_plan')['input_digest']
        stage = self.stage('production_plan')
        stage['review']['source_ref'] = 'synthetic://changed-review-record'
        stage['approval']['source_ref'] = 'synthetic://changed-user-record'
        self.save()
        self.assertEqual(before, workflow.build_review_inputs(self.path, self.project, 'ceramic/production_plan')['input_digest'])

    def test_new_user_acceptance_does_not_refresh_stale_review(self):
        stage = self.stage('production_plan')
        stage['revision'] += 1
        stage['approval']['stage_digest'] = workflow.stage_digest(stage)
        self.save()
        with self.assertRaisesRegex(core.WorkflowError, 'review is stale'):
            self.check()

    def review_mutate(self, mutation):
        stage = self.stage('production_plan')
        mutation(stage['review'])
        stage['approval']['stage_digest'] = workflow.stage_digest(stage)
        self.save()

    def test_self_review_cannot_claim_independence(self):
        self.review_mutate(lambda r: r.update(reviewer=copy.deepcopy(self.stage('production_plan')['producer'])))
        with self.assertRaisesRegex(core.WorkflowError, 'Producer cannot'):
            self.check()

    def test_review_pass_boolean_cannot_cover_missing_criteria(self):
        self.review_mutate(lambda r: r.update(passed=True, coverage=[]))
        with self.assertRaisesRegex(core.WorkflowError, 'criterion coverage'):
            self.check()

    def test_review_must_bind_examined_images(self):
        self.review_mutate(lambda r: r.update(examined_images=[]))
        with self.assertRaisesRegex(core.WorkflowError, 'actual required images'):
            self.check()

    def test_open_blocker_cannot_be_overridden_by_pass_field(self):
        self.review_mutate(lambda r: r.update(passed=True, findings=[{'id': 'missing-ground', 'severity': 'blocker', 'status': 'open', 'note': 'SYNTHETIC missing contact'}]))
        with self.assertRaisesRegex(core.WorkflowError, 'unresolved blocker'):
            self.check()

    def test_declared_serial_fallback_exposes_its_limitation(self):
        self.review_mutate(lambda r: r.update(independence='unverified_serial', reviewer=self.stage('production_plan')['producer'], limitation='SYNTHETIC host lacks subagents'))
        self.assertEqual(self.check()['pre_handoff_reviews']['ceramic/production_plan']['independence'], 'unverified_serial')

    def test_legacy_inspection_preserves_frozen_identity_but_cannot_begin_new_run(self):
        self.data['production_policy'] = workflow.LEGACY_PRODUCTION_POLICY
        self.save()
        before = self.path.read_bytes()
        digest = workflow.stage_digest(self.stage('production_plan'))
        result = self.check()
        self.assertEqual(result['ready_for'], 'historical_integrity')
        self.assertEqual(digest, result['stage_digests']['ceramic/production_plan'])
        self.assertEqual(before, self.path.read_bytes())
        self.plan['workflow'] = {'path': str(self.path), 'sha256': core.file_hash(self.path)}
        with self.assertRaisesRegex(core.WorkflowError, 'BLOCKED_WORKFLOW_POLICY'):
            workflow.check_plan_gate(self.plan, self.project)
        self.assertTrue(workflow.check_plan_gate(self.plan, self.project, allow_legacy_policy=True)['ok'])

    def test_previous_visual_policy_keeps_historical_identity_and_recovery(self):
        self.data['production_policy'] = workflow.PREVIOUS_PRODUCTION_POLICY
        self.save()
        before = self.path.read_bytes()
        result = self.check()
        self.assertEqual(result['ready_for'], 'historical_integrity')
        self.assertFalse(result['production_policy_current'])
        self.assertEqual(before, self.path.read_bytes())
        self.plan['workflow'] = {'path': str(self.path), 'sha256': core.file_hash(self.path)}
        with self.assertRaisesRegex(core.WorkflowError, 'BLOCKED_WORKFLOW_POLICY'):
            workflow.check_plan_gate(self.plan, self.project)
        self.assertTrue(workflow.check_plan_gate(self.plan, self.project, allow_legacy_policy=True)['ok'])

    def test_v3_expansion_preserves_an_archived_v2_sample_without_rewriting_h3(self):
        self.path, self.data = make_workflow(self.project, self.plan, expansion=True, initialize_control=False)
        sample = self.stage('representative_sample')
        source_item = next(e for e in sample['evidence'] if e['role'] == 'sample_source_production')
        source = core.read(source_item['path'])
        source_table_item = next(e for e in source['evidence'] if e['role'] == 'production_table')
        original = core.read(source_table_item['path'])
        for feature in original['visual_features']:
            feature.pop('feature_kind')
        for asset in original['asset_proposals']:
            asset.pop('route_evaluation')
        original.pop('asset_route_contract')
        refresh_evidence(source, 'production_table', original)
        approve(source)
        core.write(source_item['path'], source)
        source_item['sha256'] = core.file_hash(source_item['path'])
        source_digest = workflow.stage_digest(source)

        context = copy.deepcopy(self.data)
        context['production_policy'] = workflow.PREVIOUS_PRODUCTION_POLICY
        context['stages'] = [source if s['id'] == 'production_plan' else s for s in context['stages']
                             if s['id'] != 'representative_sample']
        context_path = self.project / 'art/workflow/original-v2-workflow.json'
        core.write(context_path, context)
        frozen_h3 = Path(source_table_item['path']).read_bytes()
        table = self.value('production_plan', 'production_table')
        table['sample_contract']['source_production_digest'] = source_digest
        table['sample_source_workflow'] = {'path': str(context_path), 'sha256': core.file_hash(context_path)}
        refresh_evidence(self.stage('production_plan'), 'production_table', table)
        approve(self.stage('production_plan'))
        sample['consumes'] = {'ceramic/production_plan': source_digest}
        approve(sample)
        self.save()
        result = self.check(True)
        self.assertEqual(result['ready_for'], 'expansion_production')
        self.assertEqual(result['historical_sample_sources']['ceramic']['production_policy'], workflow.PREVIOUS_PRODUCTION_POLICY)
        self.assertEqual(Path(source_table_item['path']).read_bytes(), frozen_h3)

    def test_changing_context_policy_cannot_downgrade_a_v3_h3_route_contract(self):
        import hashlib
        from modeling_ref_fixtures import write_reference_package
        from workflow_fixtures import png
        reference = write_reference_package(self.project, ['hero'], style_id='ceramic',
            selected_concept_sha256=hashlib.sha256(png(1)).hexdigest())
        master = core.read(core.resolve_input(reference['path'], self.project))['assets'][0]['views'][0]['image']
        self.plan['assets'] = [{'id': 'hero', 'route': 'generated', 'reason': 'SYNTHETIC test only',
            'generation': {'operation': 'image_to_3d', 'region': 'cn', 'parameters': {'version': 'G1', 'faceCount': 30000},
                           'reference': master, 'modeling_references': reference}}]
        self.plan['bindings'][0]['source'] = {'asset_id': 'hero'}
        self.plan['bindings'][0].pop('styles', None)
        self.path, self.data = make_workflow(self.project, self.plan, expansion=True, initialize_control=False)
        sample = self.stage('representative_sample')
        source = self.value('representative_sample', 'sample_source_production')
        context = copy.deepcopy(self.data)
        context['production_policy'] = workflow.PREVIOUS_PRODUCTION_POLICY
        context['stages'] = [source if s['id'] == 'production_plan' else s for s in context['stages']
                             if s['id'] != 'representative_sample']
        path = self.project / 'art/workflow/relabeled-context.json'
        core.write(path, context)
        table = self.value('production_plan', 'production_table')
        table['sample_source_workflow'] = {'path': str(path), 'sha256': core.file_hash(path)}
        refresh_evidence(self.stage('production_plan'), 'production_table', table)
        approve(self.stage('production_plan'))
        inputs = self.value('representative_sample', 'sample_inputs')
        inputs['model_task_bindings'] = []
        refresh_evidence(sample, 'sample_inputs', inputs)
        approve(sample)
        self.save()
        with self.assertRaisesRegex(core.WorkflowError, 'every AI/generated or hybrid'):
            self.check(True)


if __name__ == '__main__':
    unittest.main()
