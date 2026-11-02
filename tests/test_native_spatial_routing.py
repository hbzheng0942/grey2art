"""Carrier/endpoint routing stays separate from native production and gameplay."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills/greybox-to-multistyle-art'
sys.path.insert(0, str(SKILL / 'runtime'))
from greybox import core, host, host_cli, host_setup, intake, overview, task_context, knowledge
from test_host_setup import package, installer, report
from test_task_context import package as context_package


class NativeSpatialRoutingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='native-spatial-routing-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / 'workspace'
        self.project.mkdir()
        self.source = self.project / 'existing.blend'

    def request(self, intent='review', **kw):
        return {'schema': 1, 'kind': 'greybox-intake-request', 'intent': intent,
                'source_ref': 'user:scene-task', 'authoring_carrier': 'blender',
                'endpoint': 'spatial', **kw}

    def test_existing_source_review_requires_no_source_write_or_game_runtime(self):
        self.source.write_bytes(b'fixture source remains unchanged')
        before = self.source.read_bytes()
        value = intake.route(self.request(), self.source)
        self.assertEqual(value['action'], 'native_spatial_review')
        self.assertIsNone(value['runtime'])
        self.assertNotIn('file_write', value['required_capabilities'])
        self.assertNotIn('image_generate', value['required_capabilities'])
        self.assertFalse(value['dispatch'])
        self.assertFalse(value['paid_work_authorized'])
        self.assertEqual(value['native_verification'], 'unverified')
        self.assertEqual(self.source.read_bytes(), before)
        self.assertEqual(list(self.project.iterdir()), [self.source])

    def test_empty_workspace_create_does_not_need_future_blend_or_baseline(self):
        value = intake.route(self.request('create_greybox'), self.project)
        self.assertEqual(value['action'], 'native_spatial_create')
        self.assertEqual(value['inspection']['state'], 'empty_project')
        self.assertEqual(list(self.project.iterdir()), [])

    def test_directory_of_blends_is_spatial_existing_without_game_engine(self):
        self.source.write_bytes(b'fixture')
        value = intake.route(self.request('edit_greybox'), self.project)
        self.assertEqual(value['action'], 'native_spatial_edit')
        self.assertIsNone(value['engine'])
        self.assertEqual(value['inspection']['scenes'], ['existing.blend'])

    def test_workspace_discovery_prunes_cache_and_deep_assets_but_explicit_source_works(self):
        cached=self.project/'.venv/ignored.blend';cached.parent.mkdir();cached.write_bytes(b'cache')
        deep=self.project/'assets/a/b/deep.blend';deep.parent.mkdir(parents=True);deep.write_bytes(b'actual')
        value=intake.route(self.request('create_greybox'),self.project)
        self.assertEqual(value['action'],'inspect_existing_project')
        self.assertEqual(value['inspection']['scenes'],[])
        self.assertEqual(intake.route(self.request(),deep)['action'],'native_spatial_review')

    def test_source_can_infer_blender_without_changing_old_engine_meaning(self):
        self.source.write_bytes(b'fixture')
        request = self.request();request.pop('authoring_carrier')
        value = intake.route(request, self.source)
        self.assertEqual(value['authoring_carrier'], 'blender')
        self.assertEqual(value['action'], 'native_spatial_review')

    def test_review_missing_source_does_not_create_a_scene(self):
        value = intake.route(self.request(), self.source)
        self.assertEqual(value['action'], 'inspect_existing_project')
        self.assertNotIn('file_write', value['required_capabilities'])

    def test_conflicting_carrier_is_not_silently_reinterpreted(self):
        self.source.write_bytes(b'fixture')
        value = intake.route(self.request(authoring_carrier='unity'), self.source)
        self.assertEqual(value['action'], 'clarify_carrier')

    def test_blender_inside_game_project_needs_the_actual_blend_source(self):
        (self.project / 'project.godot').write_text('config_version=5')
        (self.project / 'main.tscn').write_text('fixture')
        value = intake.route(self.request('edit_greybox'), self.project)
        self.assertEqual(value['action'], 'clarify_carrier')

    def test_blender_is_never_a_playable_runtime(self):
        with self.assertRaisesRegex(core.WorkflowError, 'not a playable runtime'):
            intake.route(self.request(runtime='blender', endpoint='playable'), self.project)
        value = intake.route(self.request(endpoint='playable'), self.project)
        self.assertEqual(value['action'], 'choose_runtime')

    def test_runtime_goal_does_not_require_future_receipt_to_prepare_source(self):
        value = intake.route(self.request('create_greybox', endpoint='playable', runtime='godot'), self.project)
        self.assertEqual(value['action'], 'native_spatial_create')
        self.assertEqual(value['runtime'], 'godot')
        self.assertIn('before claiming playable', value['after_handoff'])

    def test_generic_game_review_is_not_an_edit_or_blender_route(self):
        (self.project / 'project.godot').write_text('config_version=5')
        (self.project / 'main.tscn').write_text('fixture')
        req={'schema':1,'kind':'greybox-intake-request','intent':'review','source_ref':'user:review'}
        value=intake.route(req,self.project)
        self.assertEqual(value['action'],'review_existing_project')
        self.assertNotIn('authoring_carrier',value)
        self.assertNotIn('file_write',value['required_capabilities'])

    def test_explicit_runtime_conflict_does_not_silently_edit_actual_engine(self):
        (self.project / 'project.godot').write_text('config_version=5')
        (self.project / 'main.tscn').write_text('fixture')
        request = {'schema': 1, 'kind': 'greybox-intake-request', 'intent': 'edit_greybox',
                   'source_ref': 'user:runtime-choice', 'runtime': 'unity', 'endpoint': 'playable'}
        value = intake.route(request, self.project)
        self.assertEqual(value['action'], 'clarify_engine')
        self.assertEqual(value['runtime'], 'unity')
        self.assertEqual(value['inspection']['engine'], 'godot')
        self.assertNotIn('file_write', value['required_capabilities'])
        self.assertFalse(value['dispatch'])

    def test_blender_art_keeps_art_intake_and_decision_checks(self):
        self.source.write_bytes(b'fixture')
        value = intake.route(self.request('art'), self.source)
        self.assertEqual(value['action'], 'existing_art_intake')
        self.assertFalse(value['paid_work_authorized'])

    def test_legacy_request_does_not_gain_new_fields_or_digest_defaults(self):
        request={'schema':1,'kind':'greybox-intake-request','intent':'create_greybox','source_ref':'user:old','engine':'godot'}
        value=intake.route(request,self.project)
        self.assertFalse({'authoring_carrier','runtime','endpoint'} & value.keys())
        original=deepcopy(value)
        self.assertEqual(intake.route(request,self.project), original)

    def test_spatial_overview_does_not_require_supplier_or_game_baseline(self):
        req=json.loads((SKILL/'schemas/native-spatial-overview-template.json').read_text())
        observed=report();observed['operations'].pop('file_write');observed['operations'].pop('image_generate')
        brief=overview.generate_overview(req,observed)
        self.assertEqual(brief['blockers'],[])
        self.assertEqual(brief['human_gates'],[])
        self.assertTrue(brief['host_readiness']['ok'])
        self.assertEqual(brief['target']['adapter_status'],'host_native_route')
        self.assertIsNone(brief['target']['engine'])
        self.assertEqual(brief['target']['native_verification'],'unverified')
        self.assertTrue(overview.validate_overview(brief)['ok'])
        self.assertNotIn('None',overview.render_overview(brief))

    def test_playable_endpoint_still_blocks_unverified_gameplay(self):
        req=json.loads((SKILL/'schemas/native-spatial-overview-template.json').read_text())
        req.update(endpoint='playable', target_engine='godot')
        brief=overview.generate_overview(req)
        self.assertTrue(any('gameplay host/baseline' in b for b in brief['blockers']))
        self.assertEqual(len(brief['human_gates']),5)

    def test_future_runtime_adapter_does_not_block_current_spatial_review(self):
        req=json.loads((SKILL/'schemas/native-spatial-overview-template.json').read_text())
        req['target_engine'] = 'unreal'
        brief = overview.generate_overview(req)
        self.assertEqual(brief['blockers'], [])
        self.assertEqual(brief['target']['engine'], 'unreal')
        self.assertNotEqual(brief['target']['adapter_status'], 'implemented_native_adapter')
        self.assertEqual(brief['target']['native_verification'], 'unverified')
        self.assertTrue(overview.validate_overview(brief)['ok'])
        req['endpoint'] = 'playable'
        playable = overview.generate_overview(req)
        self.assertTrue(any('runtime adapter' in b for b in playable['blockers']))

    def test_spatial_art_preserves_style_human_gates(self):
        req=json.loads((SKILL/'schemas/native-spatial-overview-template.json').read_text())
        req.update(delivery_mode='multistyle',style_count=2)
        brief=overview.generate_overview(req)
        self.assertEqual(len(brief['human_gates']),5)
        self.assertFalse(any('gameplay' in b for b in brief['blockers']))
        self.assertNotIn('playable',brief['human_gates'][-1]['decision'])

    def test_setup_and_verify_bind_blender_without_game_project_or_suppliers(self):
        skill,config=self.root/'package',self.root/'private'
        package(skill)
        with patch.object(host_setup,'installer_module',return_value=installer), patch.object(host,'_image_route',side_effect=AssertionError('inactive image route')):
            value=host_setup.setup('codex',config_dir=config,project=self.project,scope='spatial',operation='create',executables={'python':sys.executable,'blender':sys.executable},skill_root=skill)
        self.assertTrue(value['ok'])
        self.assertEqual(value['project']['engine'],'blender')
        self.assertFalse(value['project']['native_invocation_verified'])
        self.assertFalse(value['production_ready'])
        self.assertFalse(value['provider_calls'])
        self.assertIsNone(value['runtime'])
        self.assertEqual(list(self.project.iterdir()),[])

    def test_review_setup_accepts_blend_and_read_only_source_capabilities(self):
        skill,config=self.root/'package',self.root/'private';package(skill)
        self.source.write_bytes(b'keep')
        observed=report();observed['operations'].pop('file_write');observed['operations'].pop('image_generate')
        with patch.object(host_setup,'installer_module',return_value=installer):
            value=host_setup.setup('codex',config_dir=config,project=self.source,engine='blender',scope='spatial',operation='review',capability_report=observed,session_id='current',executables={'python':sys.executable,'blender':sys.executable},skill_root=skill)
        self.assertTrue(value['ok'])
        self.assertTrue(value['verification']['host_session_ready'])
        self.assertEqual(self.source.read_bytes(),b'keep')

    def test_spatial_runtime_and_playable_blender_setup_remain_separate(self):
        with self.assertRaisesRegex(core.WorkflowError,'authoring carrier'):
            host.verify('codex',scope='greybox',engine='blender')
        with self.assertRaisesRegex(core.WorkflowError,'does not prepare'):
            host_setup.setup(scope='spatial',runtime='lux')

    def test_cli_accepts_the_documented_spatial_operation(self):
        parser=argparse.ArgumentParser();host_cli.add_parser(parser.add_subparsers(dest='command'))
        args=parser.parse_args(['host','setup','--scope','spatial','--engine','blender','--operation','review','--project',str(self.source)])
        with patch.object(host_setup,'setup',return_value={'ok':True}) as call:
            self.assertTrue(host_cli.handle(args)['ok'])
        self.assertEqual(call.call_args.kwargs['operation'],'review')
        self.assertEqual(call.call_args.args[4],'spatial')

    def test_task_context_pins_spatial_project_identity_without_game_markers(self):
        skill=self.root/'context-package';context_package(skill)
        with patch.object(task_context,'SKILL',skill):
            captured=task_context.capture(self.project,engine='blender')
            self.assertEqual(captured['project'],{'root':str(self.project.resolve()),'engine':'blender'})
            self.assertEqual(task_context.validate_context(captured),captured)
            self.source.write_bytes(b'unchanged')
            from_file=task_context.capture(self.source)
        self.assertEqual(from_file['project'],captured['project'])
        self.assertEqual(self.source.read_bytes(),b'unchanged')

    def test_blender_knowledge_filter_is_navigation_not_a_runtime_adapter(self):
        value=knowledge.navigation('greybox',engine='blender')
        self.assertTrue(value['ok'])
        self.assertEqual(value['engine'],'blender')
        self.assertFalse(value.get('dispatch',False))
        self.assertEqual(knowledge.for_focus('greybox','blender')['engine'],'blender')


if __name__=='__main__':unittest.main()
