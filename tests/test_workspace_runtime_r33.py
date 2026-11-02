"""Synthetic execution/ownership checks; no actual H5, image generation or cloud API."""
from pathlib import Path
import copy,json,sys,tempfile,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/greybox-to-multistyle-art/runtime'))
from greybox import core,delivery,layout,cli
import test_delivery as native
from workflow_fixtures import make_workflow

class WorkspaceRuntime(unittest.TestCase):
    def setUp(self):
        self.fixture=native.DeliveryTests();self.fixture.setUp();self.addCleanup(self.fixture.tearDown)
        self.project=self.fixture.project
    def nav(self):return layout.read_navigation(self.project,self.fixture.plan)['navigation']['styles']['ceramic']
    def test_workspace_cli_cannot_write_inside_installed_skill(self):
        import contextlib,io
        plan=self.project/'draft.json';core.write(plan,{'workspace':{'schema':1,'case_id':'readonly'},'styles':[]})
        output=io.StringIO()
        with contextlib.redirect_stderr(output):
            result=cli.main(['workspace','register','--file',str(plan),'--project',str(cli.SKILL)])
        self.assertNotEqual(result,0);self.assertIn('read-only',output.getvalue())
        self.assertFalse((cli.SKILL/'art/readonly').exists())
    def test_new_production_missing_workspace_stops_without_creating_run(self):
        core.write(self.project/'missing.json',self.fixture.plan)
        with self.assertRaisesRegex(ValueError,'workspace'):core.prepare(self.project/'missing.json',self.project,self.fixture.run)
        self.assertFalse(self.fixture.run.exists())
    def test_core_populates_distinct_development_verified_accepted_states(self):
        self.fixture.ready();row=self.nav();self.assertTrue(row['pointers']['last_verified']['health']['current'])
        self.assertTrue(row['pointers']['last_verified']['matches_development']);self.assertNotIn('user_accepted',row['pointers'])
        self.fixture.accept();row=self.nav();self.assertTrue(row['pointers']['user_accepted']['health']['current'])
        self.assertTrue(row['pointers']['user_accepted']['matches_development'])
        entry=Path(row['pointers']['development']['entry'])
        self.assertIn('/styles/ceramic/runtime/revisions/',str(entry));self.assertNotIn('/production/runs/',str(entry))
    def test_new_development_preserves_exact_accepted_version_and_files(self):
        self.fixture.ready();self.fixture.accept();old=copy.deepcopy(self.nav()['pointers']['user_accepted'])
        oldbytes={r['path']:Path(r['path']).read_bytes() for r in old['files']}
        plan=copy.deepcopy(self.fixture.plan);plan['bindings'][0]['uniform_scale']=1.2
        checkpoint,_=make_workflow(self.project,plan);plan['workflow']={'path':str(checkpoint),'sha256':core.file_hash(checkpoint)}
        path=self.project/'plan-next.json';core.write(path,plan);run=layout.run_root(self.project,plan,'next')
        core.prepare(path,self.project,run);core.run(run,adapter=native.NativeFileAdapter())
        row=layout.read_navigation(self.project,plan)['navigation']['styles']['ceramic']
        self.assertEqual(row['pointers']['user_accepted']['entry'],old['entry']);self.assertFalse(row['pointers']['user_accepted']['matches_development'])
        self.assertTrue(all(Path(path).read_bytes()==body for path,body in oldbytes.items()))
    def test_native_report_drift_marks_navigation_stale(self):
        self.fixture.ready();self.fixture.accept();state=core.read(self.fixture.run/'run.json')
        report=Path(state['validation']['ceramic']['result']['attempt_dir'])/'native-report.json';report.write_text('{}')
        row=self.nav();self.assertFalse(row['pointers']['last_verified']['health']['current']);self.assertFalse(row['pointers']['user_accepted']['health']['current'])
    def test_rollback_retains_versions_and_only_withdraws_own_development(self):
        self.fixture.ready();self.fixture.accept();entry=Path(self.nav()['pointers']['development']['entry'])
        result=core.rollback(self.fixture.run);self.assertTrue(result['ok']);self.assertTrue(result['retainedCanonical']);self.assertTrue(entry.is_file())
        pointers=self.nav()['pointers'];self.assertNotIn('development',pointers);self.assertIn('user_accepted',pointers)
    def test_native_pointer_rejects_omitted_checks_and_failed_check_ids(self):
        self.fixture.ready();state,plan=core.load_run(self.fixture.run);sid='ceramic'
        before=self.nav()['pointers']['last_verified']['snapshot_hash']
        for changes in [{'passed_check_ids':[]},{'failed_check_ids':['baseline']}]:
            bad=copy.deepcopy(state);bad['validation'][sid]['result'].update(changes)
            core._workspace_verified_pointer(self.fixture.run,bad,plan,sid)
            self.assertEqual(self.nav()['pointers']['last_verified']['snapshot_hash'],before)
    def test_generated_download_moves_to_owned_content_version_without_copy(self):
        plan={'workspace':{'schema':1,'case_id':'storage','asset_owners':{'palm':{'scope':'style','style_id':'coast'}}},'styles':[{'id':'coast'}],
              'assets':[{'id':'palm','route':'generated','generation':{'operation':'image_to_3d','parameters':{'version':'G1'}}}]}
        folder=layout.run_root(self.project,plan,'one')/'downloads/palm';folder.mkdir(parents=True);source=folder/'mesh.glb';source.write_bytes(b'SYNTHETIC GLB CONTENT NOT A REAL MODEL')
        inode=source.stat().st_ino;record=core._canonical(source,self.project,plan,'palm',owned_root=folder.parent)
        target=core.resolve_input(record['path'],self.project);self.assertEqual(target.stat().st_ino,inode);self.assertFalse(source.exists())
        self.assertIn('/styles/coast/assets/palm/model-',str(target));self.assertTrue((target.parent/'asset.json').exists())
        duplicate=folder/'again.glb';duplicate.write_bytes(target.read_bytes());core._canonical(duplicate,self.project,plan,'palm',owned_root=folder.parent)
        self.assertFalse(duplicate.exists());self.assertEqual(target.stat().st_ino,inode)
    def test_reuse_keeps_one_original_canonical_source(self):
        source=self.project/'original-model.glb';source.write_bytes(b'SYNTHETIC')
        plan={'workspace':{'schema':1,'case_id':'reuse','asset_owners':{'palm':{'scope':'shared'}}},'styles':[{'id':'coast'},{'id':'paper'}],
              'assets':[{'id':'palm','route':'reuse','source':{'path':str(source),'sha256':core.file_hash(source)}}]}
        inode=source.stat().st_ino;record=core._canonical(source,self.project,plan,'palm');self.assertEqual(core.resolve_input(record['path'],self.project),source.resolve())
        self.assertEqual(source.stat().st_ino,inode);self.assertEqual(len(list((self.project/'art/reuse').rglob('*.glb'))),0)
    def test_run_symlink_alias_is_rejected_before_journal_creation(self):
        plan=copy.deepcopy(self.fixture.plan);checkpoint,_=make_workflow(self.project,plan);plan['workflow']={'path':str(checkpoint),'sha256':core.file_hash(checkpoint)}
        path=self.project/'symlink-plan.json';core.write(path,plan);runs=layout.roots(self.project,plan)['runs'];runs.mkdir(parents=True)
        target=runs/'real';target.mkdir();alias=runs/'alias';alias.symlink_to(target,target_is_directory=True)
        with self.assertRaises(ValueError):core.prepare(path,self.project,alias)
        self.assertFalse((target/'run.json').exists())
