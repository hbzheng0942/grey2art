"""Offline regression suite. Test doubles never call Godot, an image model, or Lux."""
from pathlib import Path
import base64,copy,hashlib,json,shutil,subprocess,sys,tempfile,unittest
from unittest.mock import patch
sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1]/'skills/greybox-to-multistyle-art'
sys.path.insert(0,str(ROOT/'runtime'))
from greybox import core,godot,workflow,cli
from workflow_fixtures import make_workflow, png
from modeling_ref_fixtures import write_reference_package
PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j4e0AAAAASUVORK5CYII=')

class FileAdapter:
    def assemble(self,*args,**kwargs): return godot.assemble(*args,**kwargs)
    def validate(self,project,artifact,*args,**kwargs):
        m=core.read(godot.project_path(project,artifact['manifest']))
        ids=[s.get('id',s.get('name')) for s in m['contract']['validation']['steps'] if s.get('expect')]
        return {'passed':True,'gameplay_verified':True,'assertions':len(ids),'passed_check_ids':ids,'test_double':True}

class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='gb-review-')
        self.project=Path(self.tmp.name)/'project'
        shutil.copytree(ROOT/'fixtures/godot-free',self.project)
        self.plan=core.read(self.project/'plan.json');self.run=self.project/'art/experiments/run'
    def tearDown(self): self.tmp.cleanup()
    def prepare(self):
        if self.plan.get('workspace'):
            from greybox import layout
            self.run=layout.run_root(self.project,self.plan,self.run.name)
        core.write(self.project/'plan.json',self.plan)
        core.prepare(self.project/'plan.json',self.project,self.run)
    def assembled(self,style=None):
        self.prepare();core.run(self.run,adapter=FileAdapter(),style=style)
        return core.read(self.run/'run.json')
    def generated(self):
        aid='hero'
        package_ref=write_reference_package(self.project,[aid],style_id='ceramic',selected_concept_sha256=hashlib.sha256(png(1)).hexdigest())
        reference=core.read(core.resolve_input(package_ref['path'],self.project))['assets'][0]['views'][0]['image']
        self.plan['assets']=[{'id':aid,'route':'generated','reason':'OFFLINE ONLY', 'generation':{'operation':'image_to_3d','region':'cn','modeling_references':package_ref,'reference':reference,'parameters':{'version':'G1','faceCount':30000}}}]
        self.plan['bindings'][0]['source']={'asset_id':aid};self.plan['bindings'][0].pop('styles',None)
    def test_two_style_coverage(self):
        self.assembled();v=core.validate(self.run,adapter=FileAdapter());self.assertEqual(v['state'],'validated');self.assertEqual(v['delivery'],'not-accepted')
    def test_one_style_does_not_complete_two(self):
        self.assembled('ceramic');v=core.validate(self.run,adapter=FileAdapter());self.assertEqual(v['state'],'partially_validated');self.assertEqual(v['coverage']['missing_styles'],['orbital'])
    def test_no_gameplay_checks_requires_explicit_technical(self):
        self.plan['contract'].pop('validation')
        with self.assertRaises(core.WorkflowError):core.validate_plan(self.plan)
    def test_technical_only_not_playable(self):
        self.plan['contract']['validation']={'mode':'technical_only','steps':[]}
        self.assembled();v=core.validate(self.run,adapter=FileAdapter());self.assertEqual(v['state'],'technical_validated');self.assertFalse(v['coverage']['gameplay_passed'])
    def test_missing_required_ids_not_verified(self):
        self.assembled();adapter=FileAdapter();adapter.validate=lambda *a,**k:{'passed':True,'gameplay_verified':True,'assertions':9,'passed_check_ids':['baseline']}
        v=core.validate(self.run,adapter=adapter);self.assertEqual(v['state'],'gameplay_unverified');self.assertFalse(v['ok'])
    def test_false_gameplay_not_overridden(self):
        self.assembled();adapter=FileAdapter();adapter.validate=lambda *a,**k:{'passed':True,'gameplay_verified':False,'assertions':0}
        self.assertEqual(core.validate(self.run,adapter=adapter)['state'],'gameplay_unverified')
    def test_missing_source_rejected(self):
        self.plan['bindings'][0].pop('source');self.plan['bindings'][0].pop('styles')
        with self.assertRaises(core.WorkflowError):core.validate_plan(self.plan)
    def test_style_override_missing_source_rejected(self):
        self.plan['bindings'][0]['styles']['orbital']['source']={}
        with self.assertRaises(core.WorkflowError):core.validate_plan(self.plan)
    def test_single_style_explicit(self):
        self.plan['styles']=self.plan['styles'][:1];self.plan['delivery_mode']='single_style';core.validate_plan(self.plan)
    def test_implicit_single_style_rejected(self):
        self.plan['styles']=self.plan['styles'][:1]
        with self.assertRaises(core.WorkflowError):core.validate_plan(self.plan)
    def test_plan_changed_still_status_rollback(self):
        self.assembled();p=core.read(self.run/'plan.json');p['styles'][0]['title']='Changed';core.write(self.run/'plan.json',p)
        self.assertTrue(core.status(self.run)['stale']);self.assertTrue(core.rollback(self.run)['ok'])
    def test_plan_corrupt_still_status_rollback(self):
        self.assembled();(self.run/'plan.json').write_text('{broken')
        self.assertTrue(core.status(self.run)['stale']);self.assertTrue(core.rollback(self.run)['ok'])
    def test_frozen_plan_corrupt_diagnostic_survives(self):
        self.assembled();(self.run/'plan.frozen.json').write_text('{bad')
        self.assertTrue(core.status(self.run)['ok']);self.assertTrue(core.rollback(self.run)['ok'])
    def test_mutated_owned_file_health_and_preservation(self):
        self.assembled();p=self.run/'ceramic/play.tscn';p.write_text(p.read_text()+'\n# human edit\n')
        self.assertEqual(core.status(self.run)['health'],'stale')
        r=core.rollback(self.run);self.assertFalse(r['ok']);self.assertTrue(p.exists())
    def test_interrupted_assembly_is_journaled(self):
        self.prepare();a=FileAdapter()
        def crash(*args,**kw):godot.assemble(*args,**kw);raise RuntimeError('injected after write')
        a.assemble=crash
        with self.assertRaises(RuntimeError):core.run(self.run,adapter=a)
        self.assertTrue((self.run/'ceramic/play.tscn').exists());core.rollback(self.run)
        self.assertFalse((self.run/'ceramic/play.tscn').exists())
    def test_unrelated_file_survives_rollback(self):
        self.assembled();p=self.run/'notes.txt';p.write_text('user notes');core.rollback(self.run);self.assertTrue(p.exists())
    def test_import_settings_change_is_visible(self):
        p=self.project/'test.glb';p.write_bytes(b'offline fixture, not a real model');self.plan['bindings'][0]['source']={'route':'reuse','path':'res://test.glb'}
        side=self.project/'test.glb.import';side.write_text('root_scale=1');a=core.input_snapshot(self.project,self.plan)
        side.write_text('root_scale=3');b=core.input_snapshot(self.project,self.plan);self.assertNotEqual(a['sha256'],b['sha256'])
    def test_import_settings_appearance_is_visible(self):
        p=self.project/'test.glb';p.write_bytes(b'offline-only');self.plan['bindings'][0]['source']={'route':'reuse','path':'res://test.glb'}
        a=core.input_snapshot(self.project,self.plan);(self.project/'test.glb.import').write_text('scale=1');b=core.input_snapshot(self.project,self.plan);self.assertNotEqual(a['sha256'],b['sha256'])
    def test_unused_paid_task_rejected(self):
        self.generated();self.plan['bindings'][0]['source']={'route':'procedural','primitive':'box'}
        with self.assertRaises(core.WorkflowError):core.validate_plan(self.plan)
    def test_terminal_failures_have_no_submit_or_poll(self):
        self.generated();self.prepare();state=core.read(self.run/'run.json');state['assets']['hero']={'state':'failed','taskId':42};core.save_run(self.run,state)
        class Never:
            def __getattr__(self,name):raise AssertionError('unexpected provider operation: '+name)
        r=core.run(self.run,adapter=FileAdapter(),bridge=Never(),recovery=True)
        self.assertEqual(r['next'],'resolve_blockers');self.assertEqual(r['blockers'][0]['action'],'inspect_and_revise_task')
    def test_unknown_never_submits(self):
        self.generated();self.prepare();state=core.read(self.run/'run.json');state['assets']['hero']={'state':'unknown'};core.save_run(self.run,state)
        class Never:
            def __getattr__(self,name):raise AssertionError('unexpected provider operation: '+name)
        r=core.run(self.run,adapter=FileAdapter(),bridge=Never());self.assertEqual(r['blockers'][0]['action'],'reconcile_existing_task')
    def test_engine_version_rejected_with_project(self):
        with patch.object(godot,'engine',return_value=sys.executable),patch.object(subprocess,'run',return_value=subprocess.CompletedProcess([],0,'3.5.stable','')):
            self.assertIn('engine_error',godot.inspect(self.project))
    def test_import_timeout_keeps_output(self):
        with patch.object(godot,'engine',return_value=sys.executable),patch.object(subprocess,'run',side_effect=subprocess.TimeoutExpired([],1,output=b'partial-log',stderr=b'err-log')):
            r=godot.import_resources(self.project)
        self.assertFalse(r['passed']);self.assertIn('partial-log',r['log']);self.assertTrue(r['timed_out'])
    def test_failed_launch_keeps_log(self):
        state=self.assembled();a=state['artifacts']['ceramic']
        with patch.object(godot,'engine',return_value=sys.executable):r=godot.launch(self.project,a)
        self.assertFalse(r['ok']);self.assertTrue(Path(r['log']).exists());self.assertEqual(r['state'],'failed')
    def test_old_success_is_not_current_success(self):
        a=self.assembled()['artifacts']['ceramic'];out=self.run/'evidence/ceramic';out.mkdir(parents=True);core.write(out/'native-report.json',{'passed':True,'marker':'OLD'})
        with patch.object(godot,'engine',return_value=sys.executable),patch.object(subprocess,'run',return_value=subprocess.CompletedProcess([],0,'','')):r=godot.validate(self.project,a,out)
        self.assertFalse(r['passed']);self.assertNotIn('marker',r);self.assertNotEqual(r['attempt_dir'],str(out))
    def _native_report(self,artifact,wrong=False,outside=False):
        def mock(args,**kw):
            out=Path(args[args.index('--output')+1]);attempt=args[args.index('--attempt-id')+1]
            m=core.read(godot.project_path(self.project,artifact['manifest']))
            captures=[]
            for n in range(1+len(m['contract']['validation']['steps'])):
                p=(self.project if outside else out)/(str(n)+'.png');p.write_bytes(PNG);captures.append(str(p))
            core.write(out/'native-report.json',{'passed':True,'errors':[],'attempt_id':'bad' if wrong else attempt,'scene':artifact['entry_scene'],'binding_digest':artifact['binding_digest'],'captures':captures,'gameplay_verified':True,'passed_check_ids':['baseline','collect','transition']})
            return subprocess.CompletedProcess(args,0,'','')
        return mock
    def test_current_attempt_receipt_can_pass(self):
        a=self.assembled()['artifacts']['ceramic']
        with patch.object(godot,'engine',return_value=sys.executable),patch.object(subprocess,'run',side_effect=self._native_report(a)):r=godot.validate(self.project,a,self.run/'evidence/ceramic')
        self.assertTrue(r['passed']);self.assertEqual(len(r['evidence']),4)
    def test_wrong_attempt_rejected(self):
        a=self.assembled()['artifacts']['ceramic']
        with patch.object(godot,'engine',return_value=sys.executable),patch.object(subprocess,'run',side_effect=self._native_report(a,wrong=True)):r=godot.validate(self.project,a,self.run/'evidence/ceramic')
        self.assertFalse(r['passed'])
    def test_foreign_capture_rejected(self):
        a=self.assembled()['artifacts']['ceramic']
        with patch.object(godot,'engine',return_value=sys.executable),patch.object(subprocess,'run',side_effect=self._native_report(a,outside=True)):r=godot.validate(self.project,a,self.run/'evidence/ceramic')
        self.assertFalse(r['passed'])
    def caps(self):
        from workflow_fixtures import capabilities
        return capabilities()
    def test_capability_missing_image_blocks(self):
        d=self.caps();d['capabilities'].pop('image_generate');self.assertFalse(workflow.check_capabilities(d)['ok'])
    def test_capability_missing_lux_blocks_generated_route(self):
        d=self.caps();d['capabilities'].pop('lux');self.assertFalse(workflow.check_capabilities(d,True)['ok'])
    def test_procedural_route_does_not_require_lux(self):
        d=self.caps();d['capabilities'].pop('lux');self.assertTrue(workflow.check_capabilities(d,False)['ok'])
    def test_capability_other_session_is_not_reused(self):
        with self.assertRaises(ValueError):workflow.check_capabilities(self.caps(),expected_session='other')
    def test_capability_receipt_expired(self):
        d=self.caps();d['checked_at']='2020-01-01T00:00:00+00:00'
        with self.assertRaises(ValueError):workflow.check_capabilities(d)
    def test_production_without_concepts_cannot_prepare(self):
        from workspace_fixtures import attach_workspace
        attach_workspace(self.plan)
        self.plan.pop('purpose')
        with self.assertRaisesRegex(core.WorkflowError,'BLOCKED_WORKFLOW'):self.prepare()
    def gate(self):
        return make_workflow(self.project,self.plan)
    def test_full_gate_integrity(self):
        p,d=self.gate();self.assertTrue(workflow.inspect_workflow(p,self.project)['ok'])
    def test_atlas_cannot_be_skipped(self):
        p,d=self.gate();d['stages']=[s for s in d['stages'] if not(s['id']=='atlas' and s['scope']=='ceramic')];core.write(p,d)
        with self.assertRaisesRegex(core.WorkflowError,'atlas'):workflow.inspect_workflow(p,self.project)
    def test_stale_concept_blocks_gate(self):
        p,d=self.gate();image=next(e['path'] for s in d['stages'] for e in s['evidence'] if e['role']=='concept_image');Path(image).write_bytes(b'changed')
        with self.assertRaisesRegex(core.WorkflowError,'evidence changed'):workflow.inspect_workflow(p,self.project)
    def test_agent_cannot_record_selection_as_self_approval(self):
        p,d=self.gate();next(s for s in d['stages'] if s['id']=='selection')['actor']='agent';core.write(p,d)
        with self.assertRaisesRegex(core.WorkflowError,'actual user'):workflow.inspect_workflow(p,self.project)
    def test_expansion_requires_sample(self):
        p,d=self.gate()
        with self.assertRaisesRegex(core.WorkflowError,'representative_sample'):workflow.inspect_workflow(p,self.project,expansion=True)
    def test_production_gate_integrates_prepare(self):
        p,d=self.gate();self.plan.pop('purpose');self.plan['workflow']={'path':str(p),'sha256':core.file_hash(p),'session_id':'test-session'};self.prepare();self.assertTrue((self.run/'run.json').exists())
    def test_ready_style_builds_while_other_model_waits(self):
        self.generated()
        self.plan['bindings'][0]['styles']={'ceramic':{'source':{'route':'procedural','primitive':'box'}}}
        self.prepare();state=core.read(self.run/'run.json');state['assets']['hero']={'state':'submitted','taskId':42,'region':'cn'};core.save_run(self.run,state)
        class Waiting:
            def status(self,*a):return {'status':1}
        r=core.run(self.run,adapter=FileAdapter(),bridge=Waiting())
        self.assertEqual(r['styles'],['ceramic']);self.assertEqual(r['blockedStyles'],{'orbital':['hero']})
        self.assertEqual(r['state'],'waiting_provider')
    def test_terminal_failure_does_not_stop_ready_style(self):
        self.generated()
        self.plan['bindings'][0]['styles']={'ceramic':{'source':{'route':'procedural','primitive':'box'}}}
        self.prepare();state=core.read(self.run/'run.json');state['assets']['hero']={'state':'failed','taskId':42,'region':'cn'};core.save_run(self.run,state)
        class Never:
            def __getattr__(self,name):raise AssertionError('unexpected provider '+name)
        r=core.run(self.run,adapter=FileAdapter(),bridge=Never())
        self.assertEqual(r['styles'],['ceramic']);self.assertEqual(r['next'],'resolve_blockers')
    def test_proxy_has_separate_non_circular_gate(self):
        p,d=self.gate();d['stages']=[s for s in d['stages'] if s['id'] not in ('art_proxy','production_plan')];core.write(p,d)
        self.plan['purpose']='art_proxy';self.plan['workflow']={'path':str(p),'sha256':core.file_hash(p),'session_id':'test-session'}
        self.assembled();r=core.validate(self.run,adapter=FileAdapter());self.assertEqual(r['state'],'proxy_validated');self.assertEqual(r['delivery'],'not-accepted')
    def test_proxy_cannot_skip_atlas(self):
        p,d=self.gate();d['stages']=[s for s in d['stages'] if s['id']!='atlas'];core.write(p,d)
        self.plan['purpose']='art_proxy';self.plan['workflow']={'path':str(p),'sha256':core.file_hash(p)}
        with self.assertRaisesRegex(core.WorkflowError,'atlas'):self.prepare()
    def test_proxy_cannot_spend(self):
        self.generated();self.plan['purpose']='art_proxy'
        with self.assertRaisesRegex(core.WorkflowError,'paid generation'):core.validate_plan(self.plan)
    def test_expired_receipt_has_actionable_message(self):
        d=self.caps();d['checked_at']='2020-01-01T00:00:00+00:00'
        with self.assertRaisesRegex(core.WorkflowError,'expired'):workflow.check_capabilities(d)
    def test_unknown_input_not_silent_fallback(self):
        self.plan['contract']['validation']['steps'][0]['input_mode']='mouse_magic'
        with self.assertRaisesRegex(core.WorkflowError,'Unsupported input'):core.validate_plan(self.plan)
    def test_partial_scope_not_ok(self):
        self.assembled('ceramic');v=core.validate(self.run,adapter=FileAdapter());self.assertFalse(v['ok'])
    def test_playable_cannot_empty_required_ids(self):
        self.plan['contract']['validation']['required_checks']=[]
        with self.assertRaisesRegex(core.WorkflowError,'nonempty'):core.validate_plan(self.plan)
    def test_prior_scoped_user_authority_can_be_reused(self):
        p,d=self.gate()
        original=copy.deepcopy(d)
        self.assertTrue(workflow.inspect_workflow(p,self.project)['ok'])
        self.assertTrue(workflow.inspect_workflow(p,self.project)['ok'])
        self.assertEqual(core.read(p),original)  # No rewritten/inferred approvals on resume.
    def test_production_plan_cannot_self_authorize(self):
        p,d=self.gate()
        next(s for s in d['stages'] if s['id']=='production_plan')['actor']='agent';core.write(p,d)
        with self.assertRaisesRegex(core.WorkflowError,'scope authority'):workflow.inspect_workflow(p,self.project)
    def test_capability_future_timestamp_rejected(self):
        d=self.caps();d['checked_at']='2099-01-01T00:00:00+00:00'
        with self.assertRaisesRegex(core.WorkflowError,'expired'):workflow.check_capabilities(d)
    def test_duplicate_styles_rejected(self):
        p,d=self.gate();d['selected_styles'].append(d['selected_styles'][0]);core.write(p,d)
        with self.assertRaisesRegex(core.WorkflowError,'unique'):workflow.inspect_workflow(p,self.project)
    def test_source_stays_immutable_on_additive_build(self):
        before=(self.project/'main.gd').read_bytes();self.assembled();self.assertEqual(before,(self.project/'main.gd').read_bytes())

if __name__=='__main__':unittest.main(verbosity=2)
