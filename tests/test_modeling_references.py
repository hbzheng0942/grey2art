import copy
import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/greybox-to-multistyle-art/runtime'))
from greybox import core,modeling_refs,cli
from modeling_ref_fixtures import write_reference_package,png_bytes

class ModelingReferences(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.project=Path(self.temp.name)
        self.ref=write_reference_package(self.project,['gate'],style_id='paper')
        self.path=self.project/self.ref['path'];self.package=core.read(self.path)
    def save(self):core.write(self.path,self.package);self.ref['sha256']=core.file_hash(self.path)
    def review(self):
        row=self.package['assets'][0];row['review']['images_digest']=core.digest(row['views'])
    def validate(self,**kw):return modeling_refs.validate_package(self.package,self.project,**kw)
    def test_real_pixel_audit_and_bound_style_pass(self):
        result=self.validate(style_id='paper',expected_asset_ids=['gate'],selected_concept_sha256='a'*64)
        self.assertTrue(result['ok']);self.assertEqual(len(result['dependencies']),2)
        stats=modeling_refs.audit_image(result['assets']['gate']['images'][0]['path'])
        self.assertEqual(stats['width'],512);self.assertEqual(stats['border_white_fraction'],1)
        self.assertGreater(stats['nonwhite_fraction'],.2)
    def test_style_swap_and_changed_concept_rejected(self):
        for kw in [{'style_id':'orbital'},{'selected_concept_sha256':'b'*64},{'expected_asset_ids':['missing']}]:
            with self.assertRaises(ValueError):self.validate(**kw)
    def test_changed_image_invalidates_review_before_submit(self):
        image=self.project/self.package['assets'][0]['views'][0]['image']['path'];image.write_bytes(png_bytes(color=(200,10,10)))
        with self.assertRaisesRegex(ValueError,'changed'):self.validate()
    def test_dark_background_rejected_even_with_pass_claim(self):
        view=self.package['assets'][0]['views'][0];image=self.project/view['image']['path'];image.write_bytes(png_bytes(background=(20,20,20)))
        view['image']['sha256']=core.file_hash(image);view['origin']='user_provided';view['provenance']={'source_ref':'fixture revised image'};self.review()
        with self.assertRaisesRegex(ValueError,'white background'):self.validate()
    def test_blank_white_reference_rejected(self):
        view=self.package['assets'][0]['views'][0];image=self.project/view['image']['path'];image.write_bytes(png_bytes(color=(255,255,255)))
        view['image']['sha256']=core.file_hash(image);self.review()
        with self.assertRaises(ValueError):self.validate()
    def test_stale_review_and_failed_semantic_criterion_rejected(self):
        row=self.package['assets'][0];row['review']['images_digest']='b'*64
        with self.assertRaisesRegex(ValueError,'stale'):self.validate()
        self.review();row['review']['criteria']['no_baked_shadows']=False
        with self.assertRaisesRegex(ValueError,'checks'):self.validate()
    def test_generated_image_without_style_input_receipt_rejected(self):
        view=self.package['assets'][0]['views'][0];path=self.project/view['generation_receipt']['path'];receipt=core.read(path)
        receipt['actual_input_image_sha256']=['b'*64];core.write(path,receipt);view['generation_receipt']['sha256']=core.file_hash(path);self.review()
        with self.assertRaisesRegex(ValueError,'style-conditioned'):self.validate()
    def test_imported_reference_needs_actual_provenance(self):
        view=self.package['assets'][0]['views'][0];view['origin']='user_provided';view.pop('generation_receipt');self.review()
        with self.assertRaisesRegex(ValueError,'provenance'):self.validate()
        view['provenance']={'source_ref':'user supplied asset reference message'};self.review();self.assertTrue(self.validate()['ok'])
    def test_multiview_checks_distinct_images_roles_and_review(self):
        ref=write_reference_package(self.project,['gate'],style_id='paper',mode='multiview');self.package=core.read(self.project/ref['path'])
        result=self.validate();self.assertEqual(result['assets']['gate']['mode'],'multiview')
        views=self.package['assets'][0]['views'];views[1]=copy.deepcopy(views[0]);views[1]['id']='other';views[1]['role']='back';self.review()
        with self.assertRaisesRegex(ValueError,'Duplicate image'):self.validate()
    def test_multiview_with_same_orientation_rejected(self):
        ref=write_reference_package(self.project,['gate'],style_id='paper',mode='multiview');self.package=core.read(self.project/ref['path'])
        self.package['assets'][0]['views'][1]['role']='front';self.review()
        with self.assertRaisesRegex(ValueError,'orientations'):self.validate()
    def test_corrupt_pixels_cannot_pass_magic_header_only(self):
        view=self.package['assets'][0]['views'][0];image=self.project/view['image']['path'];image.write_bytes(b'\x89PNG\r\n\x1a\nnot pixels')
        view['image']['sha256']=core.file_hash(image);self.review()
        with self.assertRaisesRegex(ValueError,'PNG'):self.validate()
    def test_tiny_image_is_not_accepted_as_reference(self):
        view=self.package['assets'][0]['views'][0];image=self.project/view['image']['path'];image.write_bytes(png_bytes(width=16,height=16))
        view['image']['sha256']=core.file_hash(image);self.review()
        with self.assertRaisesRegex(ValueError,'256px'):self.validate()
    def test_operation_uses_specific_asset_and_package_hash(self):
        self.save();op={'asset_id':'gate','modeling_references':self.ref}
        result=modeling_refs.validate_operation_reference(op,self.project)
        self.assertEqual(result['mode'],'single');self.assertEqual(len(result['dependencies']),3)
        op['asset_id']='other'
        with self.assertRaises(ValueError):modeling_refs.validate_operation_reference(op,self.project)
    def test_path_escape_and_swapped_package_rejected(self):
        self.save();bad=copy.deepcopy(self.ref);bad['path']='../elsewhere.json'
        with self.assertRaises(ValueError):modeling_refs.validate_operation_reference({'asset_id':'gate','modeling_references':bad},self.project)
        self.ref['sha256']='b'*64
        with self.assertRaises(ValueError):modeling_refs.validate_operation_reference({'asset_id':'gate','modeling_references':self.ref},self.project)
    def test_cli_audits_and_validates_without_generating(self):
        self.save()
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(cli.main(['references','validate','--file',str(self.path),'--project',str(self.project)]),0)
        self.assertIn('"ok": true',output.getvalue())

    def test_derived_input_requires_master_lineage(self):
        view=self.package['assets'][0]['views'][0];view['master']=copy.deepcopy(view['image'])
        derived=self.project/'derived.png';derived.write_bytes(png_bytes(color=(62,121,181)))
        view['image']={'path':'derived.png','sha256':core.file_hash(derived)};self.review()
        with self.assertRaisesRegex(ValueError,'lineage'):self.validate()
        view['derivation']={'source_sha256':view['master']['sha256'],'method':'provider-specific background preparation','tool':'synthetic-fixture'};self.review()
        self.assertTrue(self.validate()['ok'])

    def test_blank_derived_submission_rejected_despite_valid_master(self):
        view=self.package['assets'][0]['views'][0];view['master']=copy.deepcopy(view['image'])
        image=self.project/'empty.png';image.write_bytes(png_bytes(color=(255,255,255)))
        view['image']={'path':'empty.png','sha256':core.file_hash(image)}
        view['derivation']={'source_sha256':view['master']['sha256'],'method':'bad preprocessing','tool':'fixture'};self.review()
        with self.assertRaisesRegex(ValueError,'Blank|empty'):self.validate()
    def test_illegal_png_chunk_order_rejected(self):
        raw=png_bytes();first_end=8+12+13;second_len=int.from_bytes(raw[first_end:first_end+4],'big');second_end=first_end+12+second_len
        reordered=raw[:8]+raw[first_end:second_end]+raw[8:first_end]+raw[second_end:]
        with self.assertRaisesRegex(ValueError,'IHDR'):modeling_refs._decode(reordered)

    def test_style_input_receipt_rejects_nonlist_container(self):
        view=self.package['assets'][0]['views'][0];path=self.project/view['generation_receipt']['path'];receipt=core.read(path)
        for malformed in ['a'*64,{'a'*64:True},[]]:
            receipt['actual_input_image_sha256']=malformed;core.write(path,receipt);view['generation_receipt']['sha256']=core.file_hash(path);self.review()
            with self.assertRaisesRegex(ValueError,'SHA256 list'):self.validate()

    def current(self, category='prop', use='static', mode='single', **extra):
        if mode == 'multiview':
            ref=write_reference_package(self.project,['gate'],style_id='paper',mode=mode)
            self.package=core.read(self.project/ref['path'])
        self.package['policy']=modeling_refs.CURRENT_POLICY
        row=self.package['assets'][0]
        row['modeling_contract']={'category':category,'use':use,
            'structure':'Synthetic box volume with a visible support face; not a generated character.',**extra}
        if 'pose' in extra:
            for view in row['views']:view['pose']=extra['pose']
        self.current_review()
        return row

    def current_review(self):
        row=self.package['assets'][0]
        row['review']={'actor':'agent','images_digest':core.digest(row['views']),
            'contract_digest':core.digest(row['modeling_contract']),
            'observations':[{'view_id':v['id'],'status':'pass',
                'observation':'Synthetic colored rectangle fixture; only record binding is under test.',
                'source_ref':'synthetic://pixel-observation/'+v['id']} for v in row['views']]}
        if len(row['views'])>1:
            row['review']['cross_view_observation']='Synthetic distinct fixture views; no real anatomy/pose qualification claim.'

    def test_v2_prop_has_no_character_fields_and_legacy_has_explicit_boundary(self):
        legacy=self.validate()
        self.assertTrue(legacy['legacy'])
        self.assertIn('not established',legacy['assets']['gate']['contract_review'])
        row=self.current()
        current=self.validate()
        self.assertFalse(current['legacy'])
        self.assertEqual(current['assets']['gate']['modeling_contract'],row['modeling_contract'])
        self.assertNotIn('pose',row['modeling_contract'])
        self.assertIn('not actual image viewing',current['review_boundary'])

    def test_new_contract_cannot_be_replaced_by_old_boolean_checklist(self):
        self.package['policy']=modeling_refs.CURRENT_POLICY
        with self.assertRaisesRegex(ValueError,'modeling_contract'):self.validate()
        row=self.current();row['review'].pop('observations')
        row['review']['criteria']={key:True for key in modeling_refs.CRITERIA}
        with self.assertRaisesRegex(ValueError,'pixel observation'):self.validate()
        self.package['policy']=modeling_refs.POLICY
        with self.assertRaisesRegex(ValueError,'pixel observation'):self.validate()

    def test_skeletal_humanoid_requires_one_explicit_pose_and_details(self):
        row=self.current('humanoid','skeletal_animation')
        for pose in [None,'neutral','A/T','natural_stance',True,{}]:
            row['modeling_contract']['pose']=pose;self.current_review()
            with self.subTest(pose=pose),self.assertRaisesRegex(ValueError,'one A or T'):self.validate()
        for pose in ['A','T']:
            row['modeling_contract']['pose']=pose
            row['views'][0]['pose']=pose;self.current_review()
            with self.assertRaisesRegex(ValueError,'limb/joint separation'):self.validate()
            row['modeling_contract']['pose_details']='Arms clear of torso, separate legs and visible wrist joints.'
            self.current_review();self.assertTrue(self.validate()['ok'])
            row['modeling_contract'].pop('pose_details')

    def test_animal_stance_and_static_sculpture_do_not_assume_humanoid_rig(self):
        row=self.current('animal','skeletal_animation',pose='natural_stance',
            pose_details='Four visible separated legs support the body; tail clear of hind legs.')
        self.assertTrue(self.validate()['ok'])
        row['modeling_contract']['pose']='T';self.current_review()
        with self.assertRaisesRegex(ValueError,'natural_stance'):self.validate()
        self.current('humanoid','static',pose='fixed')
        self.assertTrue(self.validate()['ok'])

    def test_multiview_camera_roles_do_not_change_declared_body_pose(self):
        row=self.current('humanoid','skeletal_animation',mode='multiview',pose='A',
            pose_details='Separated arms and legs.')
        self.assertTrue(self.validate()['ok'])
        row['views'][1]['pose']='T';self.current_review()
        with self.assertRaisesRegex(ValueError,'same selected body pose'):self.validate()
        row['views'][1]['pose']='A';self.current_review()
        row['review'].pop('cross_view_observation')
        with self.assertRaisesRegex(ValueError,'same-object/pose observation'):self.validate()

    def test_v2_observations_cover_actual_views_and_block_failed_or_unseen(self):
        row=self.current(mode='multiview')
        for status in ['fail','unclear']:
            row['review']['observations'][0]['status']=status
            with self.subTest(status=status),self.assertRaisesRegex(ValueError,'cannot enter'):self.validate()
        self.current_review();row['review']['observations'][0]['source_ref']=''
        with self.assertRaisesRegex(ValueError,'actual pixel-inspection'):self.validate()
        self.current_review();row['review']['observations'][1]['view_id']=row['views'][0]['id']
        with self.assertRaisesRegex(ValueError,'exact unique view IDs'):self.validate()
        self.current_review();row['review']['observations'][0]['observation']=''
        with self.assertRaisesRegex(ValueError,'visible findings'):self.validate()

    def test_changed_modeling_decisions_invalidate_review(self):
        row=self.current()
        row['modeling_contract']['structure']='Changed shape with a new opening.'
        with self.assertRaisesRegex(ValueError,'stale.*modeling contract'):self.validate()
        self.current_review();self.assertTrue(self.validate()['ok'])

    def test_only_relevant_assets_need_interfaces_or_deformation_plan(self):
        for category in ['architecture','mechanism']:
            row=self.current(category,'rigid_motion' if category=='mechanism' else 'static')
            with self.assertRaisesRegex(ValueError,'interfaces'):self.validate()
            row['modeling_contract']['interfaces']=['Base contact and a separately described connection plane.']
            self.current_review();self.assertTrue(self.validate()['ok'])
        row=self.current('vegetation','skeletal_animation')
        with self.assertRaisesRegex(ValueError,'deformation plan'):self.validate()
        row['modeling_contract']['deformation_plan']='Use an existing qualified branch skin for wind; no humanoid auto-rig.'
        self.current_review();self.assertTrue(self.validate()['ok'])

    def test_v2_malformed_declarations_fail_with_bounded_validation_errors(self):
        for field,value in [('category',{}),('use',[]),('structure',False)]:
            row=self.current();row['modeling_contract'][field]=value;self.current_review()
            with self.subTest(field=field),self.assertRaises(ValueError):self.validate()
        row=self.current();row['views'][0]['id']=[]
        row['review']['images_digest']=core.digest(row['views'])
        with self.assertRaises(ValueError):self.validate()

    def test_operation_keeps_v2_modeling_contract_for_downstream_routing(self):
        row=self.current();self.save()
        result=modeling_refs.validate_operation_reference({'asset_id':'gate','modeling_references':self.ref},self.project)
        self.assertEqual(result['modeling_contract'],row['modeling_contract'])
        self.assertEqual(result['contract_review'],'reviewer-declared-v2')
