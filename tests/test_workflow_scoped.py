"""Scoped sequencing/focused H2 tests; all reviews and pixels are synthetic."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1] / 'skills/greybox-to-multistyle-art'
sys.path.insert(0, str(ROOT / 'runtime'))
from greybox import core, workflow, pre_handoff
from workflow_fixtures import make_workflow, approve, review_fixture, evidence, png


class ScopedWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='scoped-workflow-offline-')
        self.project = Path(self.tmp.name)
        shutil.copytree(ROOT / 'fixtures/godot-free', self.project, dirs_exist_ok=True)
        self.plan = core.read(self.project / 'plan.json')
        self.plan.pop('purpose')
        self.plan['styles'] = self.plan['styles'][:1]
        self.serial = 0

    def tearDown(self):
        self.tmp.cleanup()

    def stage(self, sid, scope='ceramic'):
        return next(s for s in self.data['stages'] if s['id'] == sid and s['scope'] == scope)

    def value(self, sid, role, scope='ceramic'):
        return self.read_stage(self.stage(sid, scope), role)

    def read_stage(self, stage, role):
        return core.read(next(e['path'] for e in stage['evidence'] if e['role'] == role))

    def replace(self, stage, role, value):
        # Changed small JSON only; original H2/H3 artifacts remain immutable.
        self.serial += 1
        item = next(e for e in stage['evidence'] if e['role'] == role)
        if core.digest(core.read(item['path'])) == core.digest(value):
            return
        path = self.project / 'art/workflow' / ('revision-' + str(self.serial) + '-' + role + '.json')
        core.write(path, value)
        item.update(path=str(path), sha256=core.file_hash(path))

    def rechain(self, rewrite_sample=False):
        digests = {}
        sample = next((s for s in self.data['stages'] if s['id'] == 'representative_sample'), None)
        for stage in self.data['stages']:
            sid, scope = stage['id'], stage['scope']
            if sid == 'representative_sample':
                if rewrite_sample:
                    approve(stage)
                continue
            stage['consumes'] = {d: digests[d] for d in workflow.dependencies(sid, scope)}
            if sid == 'selection':
                v = self.read_stage(stage, 'selection_decision'); v['directions_digest'] = digests['shared/directions']
                self.replace(stage, 'selection_decision', v)
            elif sid == 'spatial_design':
                v = self.read_stage(stage, 'spatial_graph'); v['atlas_digest'] = digests[scope + '/atlas']
                self.replace(stage, 'spatial_graph', v)
            elif sid == 'production_plan':
                v = self.read_stage(stage, 'assembly_recipe'); v['spatial_design_digest'] = digests[scope + '/spatial_design']
                self.replace(stage, 'assembly_recipe', v)
                if rewrite_sample and sample:
                    source = self.read_stage(sample, 'sample_source_production')
                    source['consumes'] = dict(stage['consumes'])
                    recipe = self.read_stage(source, 'assembly_recipe'); recipe['spatial_design_digest'] = digests[scope + '/spatial_design']
                    self.replace(source, 'assembly_recipe', recipe)
                    approve(source)
                    self.replace(sample, 'sample_source_production', source)
                    h = workflow.stage_digest(source)
                    table = self.read_stage(stage, 'production_table'); table['sample_contract']['source_production_digest'] = h
                    self.replace(stage, 'production_table', table)
                    sample['consumes'] = {scope + '/production_plan': h}
            review_fixture(stage)
            if sid in workflow.HUMAN_STAGES:
                approve(stage)
            digests[scope + '/' + sid] = workflow.stage_digest(stage)
        core.write(self.path, self.data)

    def focused(self, accepted=False):
        views = [{'id': s + '-overview', 'camera_id': s + '-camera', 'state_id': 'playing',
                  'framing': 'whole_composition', 'space_ids': [s], 'required_layers': sorted(workflow.COMPOSITION_LAYERS)}
                 for s in ('start', 'end', 'future')]
        self.path, self.data = make_workflow(self.project, self.plan, expansion=accepted, observation_views=views)
        baseline = self.value('baseline', 'spatial_contract', 'shared')
        baseline['spatial_scope'] = {'mode': 'continuous', 'space_ids': ['start', 'end', 'future'],
            'transition_ids': ['connector', 'exit'], 'segments': [
                {'id': 'region-' + s, 'space_ids': [s]} for s in ('start', 'end', 'future')]}
        self.replace(self.stage('baseline', 'shared'), 'spatial_contract', baseline)
        atlas = self.value('atlas', 'atlas_manifest')
        graph = self.value('spatial_design', 'spatial_graph')
        graph['boundaries'].append({'id': 'exit', 'from_space_id': 'end', 'to_space_id': 'future',
                                    'continuity_rule': 'SYNTHETIC preserve end-to-future support and sightline'})
        graph['transition_ids'].append('exit')
        atlas.update(scope_mode='focused', required_transition_ids=['connector', 'exit'],
            global_layout={'spaces': [{'space_id': s, 'intent': 'SYNTHETIC coarse ' + s} for s in ('start', 'end', 'future')],
                           'boundaries': copy.deepcopy(graph['boundaries'])})
        for i, s in enumerate(('start', 'end')):
            image = evidence(self.project, 'focus-' + s + '.png', 'concept_image', png(88 + i), 'focus-' + s)
            self.stage('atlas')['evidence'].append(image)
            atlas['views'].append({'id': 'focus-' + s, 'concept_image_id': image['id'], 'concept_sha256': image['sha256'],
                'camera_id': s + '-camera', 'role': 'key_scene', 'space_ids': [s], 'segment_id': 'region-' + s})
        image = evidence(self.project, 'focus-exit.png', 'concept_image', png(91), 'focus-exit')
        self.stage('atlas')['evidence'].append(image)
        atlas['views'].append({'id': 'focus-exit', 'concept_image_id': image['id'], 'concept_sha256': image['sha256'],
            'camera_id': 'exit-camera', 'role': 'transition', 'transition_id': 'exit', 'space_ids': ['end', 'future']})
        atlas['focus_contract'] = {'playable_loop': 'SYNTHETIC run, dodge, collect, exit',
            'entry': {'space_id': 'start', 'view_id': 'focus-start', 'interface': 'SYNTHETIC entry clearance'},
            'exit': {'space_id': 'end', 'view_id': 'focus-exit', 'interface': 'SYNTHETIC downstream seam'}}
        self.replace(self.stage('atlas'), 'atlas_manifest', atlas)
        self.replace(self.stage('spatial_design'), 'spatial_graph', graph)
        proxy = self.value('art_proxy', 'native_proxy')
        proxy['captures'] = [c for c in proxy['captures'] if c['view_id'] != 'future-overview']
        keep = {c['image_id'] for c in proxy['captures']}
        self.stage('art_proxy')['evidence'] = [e for e in self.stage('art_proxy')['evidence']
            if e['role'] != 'proxy_capture' or e['id'] in keep]
        self.replace(self.stage('art_proxy'), 'native_proxy', proxy)
        self.rechain(rewrite_sample=accepted)

    def expand_focus(self):
        source = self.value('representative_sample', 'sample_source_production')
        archived = copy.deepcopy(self.data)
        archived['stages'] = [source if s['id'] == 'production_plan' else s for s in archived['stages']
                              if s['id'] != 'representative_sample']
        path = self.project / 'art/workflow/first-slice-frozen.json'
        core.write(path, archived)
        old_h4 = copy.deepcopy(self.stage('representative_sample'))
        atlas = self.value('atlas', 'atlas_manifest')
        atlas['required_space_ids'].append('future')
        image = evidence(self.project, 'future-key.png', 'concept_image', png(99), 'future-key')
        self.stage('atlas')['evidence'].append(image)
        atlas['views'].append({'id': 'future-key', 'concept_image_id': image['id'], 'concept_sha256': image['sha256'],
            'camera_id': 'future-camera', 'role': 'key_scene', 'space_ids': ['future'], 'segment_id': 'region-future'})
        self.replace(self.stage('atlas'), 'atlas_manifest', atlas)
        graph = self.value('spatial_design', 'spatial_graph')
        graph['space_ids'].append('future')
        graph['space_designs'].append({'space_id': 'future', **{k: 'SYNTHETIC future ' + k for k in
            ('art_intent', 'gameplay_invariants', 'visual_freedom', 'foreground', 'midground', 'background')}})
        self.replace(self.stage('spatial_design'), 'spatial_graph', graph)
        proxy = self.value('art_proxy', 'native_proxy')
        image = evidence(self.project, 'future-proxy.png', 'proxy_capture', png(199), 'future-proxy')
        self.stage('art_proxy')['evidence'].append(image)
        proxy['captures'].append({**{k: image[k] for k in ('path', 'sha256')}, 'image_id': image['id'],
            'view_id': 'future-overview', 'camera_id': 'future-camera', 'state_id': 'playing', 'framing': 'whole_composition',
            'visible_layers': sorted(workflow.COMPOSITION_LAYERS), 'missing_layers': []})
        self.replace(self.stage('art_proxy'), 'native_proxy', proxy)
        table = self.value('production_plan', 'production_table')
        table['sample_source_workflow'] = {'path': str(path), 'sha256': core.file_hash(path)}
        table['production_space_ids'] = ['start', 'end', 'future']
        table['production_view_ids'] = [s + '-overview' for s in table['production_space_ids']]
        for f in table['visual_features']:
            f['native_view_ids'] = table['production_view_ids']
        self.replace(self.stage('production_plan'), 'production_table', table)
        recipe = self.value('production_plan', 'assembly_recipe')
        for a in recipe['assemblies']:
            a['space_ids'] = table['production_space_ids']
        self.replace(self.stage('production_plan'), 'assembly_recipe', recipe)
        self.rechain()
        self.assertEqual(self.stage('representative_sample'), old_h4)

    def test_first_selected_style_produces_without_queued_h2_h3(self):
        self.path, self.data = make_workflow(self.project, self.plan, selected_styles=['ceramic', 'paper'])
        self.assertTrue(workflow.inspect_workflow(self.path, self.project, ['ceramic'])['ok'])
        with self.assertRaisesRegex(ValueError, 'paper/atlas'):
            workflow.inspect_workflow(self.path, self.project)
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/workflow_check.py'), 'stages', '--file', str(self.path),
            '--project', str(self.project), '--style', 'ceramic', '--style-phase', 'ceramic=representative'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['selected_styles'], ['ceramic'])

    def test_priority_need_not_be_first_h1_style(self):
        path, _ = make_workflow(self.project, self.plan, selected_styles=['paper', 'ceramic'])
        self.assertTrue(workflow.inspect_workflow(path, self.project, ['ceramic'])['ok'])

    def test_phase_cannot_name_uninspected_style(self):
        path, _ = make_workflow(self.project, self.plan)
        with self.assertRaisesRegex(ValueError, 'Per-style phases'):
            workflow.inspect_workflow(path, self.project, ['ceramic'], style_phases={'paper': 'expansion'})

    def test_lead_h4_does_not_force_sibling_to_have_h4(self):
        full_plan = core.read(self.project / 'plan.json'); full_plan.pop('purpose')
        all_styles = [s['id'] for s in full_plan['styles']]
        _, both = make_workflow(self.project, full_plan)
        sibling_stages = [copy.deepcopy(s) for s in both['stages'] if s['scope'] == all_styles[1]]
        path, data = make_workflow(self.project, self.plan, expansion=True, selected_styles=all_styles)
        data['stages'].extend(sibling_stages)
        core.write(path, data)
        result = workflow.inspect_workflow(path, self.project, style_phases={all_styles[0]: 'expansion', all_styles[1]: 'representative'})
        self.assertEqual(result['ready_for'], 'mixed_scoped_production')
        self.assertNotIn(all_styles[1] + '/representative_sample', result['checked_stages'])

    def test_focus_preserves_full_baseline_and_only_deepens_first_connected_slice(self):
        self.focused()
        self.assertTrue(workflow.inspect_workflow(self.path, self.project)['ok'])
        self.assertEqual(self.value('baseline', 'spatial_contract', 'shared')['spatial_scope']['space_ids'], ['start', 'end', 'future'])
        self.assertEqual(self.value('atlas', 'atlas_manifest')['required_space_ids'], ['start', 'end'])

    def test_missing_coarse_future_or_entry_exit_blocks_focus(self):
        self.focused()
        atlas = self.value('atlas', 'atlas_manifest'); atlas['global_layout']['spaces'].pop()
        self.replace(self.stage('atlas'), 'atlas_manifest', atlas); self.rechain()
        with self.assertRaisesRegex(ValueError, 'coarse intent'):
            workflow.inspect_workflow(self.path, self.project)

    def test_missing_external_seam_cannot_hide_at_sample_edge(self):
        self.focused()
        atlas = self.value('atlas', 'atlas_manifest'); atlas['required_transition_ids'].remove('exit')
        self.replace(self.stage('atlas'), 'atlas_manifest', atlas); self.rechain()
        with self.assertRaisesRegex(ValueError, 'entry/exit transitions'):
            workflow.inspect_workflow(self.path, self.project)

    def test_one_picture_cannot_claim_both_entry_and_exit(self):
        self.focused()
        atlas = self.value('atlas', 'atlas_manifest'); atlas['focus_contract']['exit'] = dict(atlas['focus_contract']['entry'])
        self.replace(self.stage('atlas'), 'atlas_manifest', atlas); self.rechain()
        with self.assertRaisesRegex(ValueError, 'distinct actual observations'):
            workflow.inspect_workflow(self.path, self.project)

    def test_coarse_future_does_not_authorize_expansion(self):
        self.focused(accepted=True)
        table = self.value('production_plan', 'production_table'); table['production_space_ids'].append('future')
        self.replace(self.stage('production_plan'), 'production_table', table); self.rechain()
        with self.assertRaisesRegex(ValueError, 'current approved production scope'):
            workflow.inspect_workflow(self.path, self.project, expansion=True)

    def test_new_h2_scope_preserves_h4_and_original_review_inputs(self):
        self.focused(accepted=True)
        self.assertTrue(workflow.inspect_workflow(self.path, self.project, expansion=True)['ok'])
        before = pre_handoff.review_inputs(self.data, self.project, self.stage('representative_sample'))
        self.expand_focus()
        self.assertTrue(workflow.inspect_workflow(self.path, self.project, expansion=True)['ok'])
        self.assertEqual(pre_handoff.review_inputs(self.data, self.project, self.stage('representative_sample')), before)
        dependencies = workflow.evidence_dependencies(self.path, self.project)
        self.assertTrue(any(d['path'].endswith('first-slice-frozen.json') for d in dependencies))
        current = pre_handoff.review_inputs(self.data, self.project, self.stage('production_plan'))
        self.assertTrue(any(a['path'].endswith('future-key.png') for a in current['artifacts']))

    def test_expansion_cannot_reuse_h4_after_old_space_design_changes(self):
        self.focused(accepted=True); self.expand_focus()
        graph = self.value('spatial_design', 'spatial_graph'); graph['space_designs'][0]['foreground'] = 'Changed original playable shape'
        self.replace(self.stage('spatial_design'), 'spatial_graph', graph); self.rechain()
        with self.assertRaisesRegex(ValueError, 'changed original sample space designs'):
            workflow.inspect_workflow(self.path, self.project, expansion=True)

    def test_stale_archived_context_is_not_a_reusable_h4(self):
        self.focused(accepted=True); self.expand_focus()
        table = self.value('production_plan', 'production_table')
        Path(table['sample_source_workflow']['path']).write_text('{}')
        with self.assertRaisesRegex(ValueError, 'Frozen sample source workflow missing or changed'):
            workflow.inspect_workflow(self.path, self.project, expansion=True)

    def test_old_playable_loop_cannot_change_under_reused_h4(self):
        self.focused(accepted=True); self.expand_focus()
        atlas = self.value('atlas', 'atlas_manifest'); atlas['focus_contract']['playable_loop'] = 'Changed original action loop'
        self.replace(self.stage('atlas'), 'atlas_manifest', atlas); self.rechain()
        with self.assertRaisesRegex(ValueError, 'original sample playable loop'):
            workflow.inspect_workflow(self.path, self.project, expansion=True)

    def test_new_expansion_entry_exit_preserves_explicit_old_sample_contract(self):
        self.focused(accepted=True); self.expand_focus()
        atlas = self.value('atlas', 'atlas_manifest')
        atlas['sample_focus_contract'] = copy.deepcopy(atlas['focus_contract'])
        atlas['focus_contract']['exit'] = {'space_id': 'future', 'view_id': 'future-key', 'interface': 'SYNTHETIC new downstream endpoint'}
        atlas['focus_contract']['playable_loop'] = 'SYNTHETIC original loop followed by the new future area'
        self.replace(self.stage('atlas'), 'atlas_manifest', atlas); self.rechain()
        self.assertTrue(workflow.inspect_workflow(self.path, self.project, expansion=True)['ok'])

    def test_replacing_original_plan_drawing_invalidates_old_h4(self):
        self.focused(accepted=True); self.expand_focus()
        self.replace(self.stage('spatial_design'), 'plan_view', {'synthetic_test_only': True, 'layout': 'changed old space'})
        self.rechain()
        with self.assertRaisesRegex(ValueError, 'retain original sample plan/section'):
            workflow.inspect_workflow(self.path, self.project, expansion=True)

    def test_adding_expansion_plan_preserves_original_h4(self):
        self.focused(accepted=True); self.expand_focus()
        self.stage('spatial_design')['evidence'].append(evidence(self.project, 'future-plan.json', 'plan_view',
            {'synthetic_test_only': True, 'space_id': 'future', 'layout': 'new region only'}))
        self.rechain()
        self.assertTrue(workflow.inspect_workflow(self.path, self.project, expansion=True)['ok'])


if __name__ == '__main__':
    unittest.main()
