"""Offline route/task binding checks; synthetic files are not generated models."""
from pathlib import Path
import copy
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1] / 'skills/greybox-to-multistyle-art'
sys.path.insert(0, str(ROOT / 'runtime'))
sys.dont_write_bytecode = True
from greybox import asset_routes, core, image_policy, suppliers
from modeling_ref_fixtures import write_reference_package
from workflow_fixtures import synthetic_glb_bytes


class ModelTaskBindingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='gb-route-task-')
        self.project = Path(self.temp.name)
        self.package = write_reference_package(self.project, ['hero'], style_id='ceramic')
        package = core.read(core.resolve_input(self.package['path'], self.project))
        master = package['assets'][0]['views'][0]['image']
        self.op = {'id': 'make-hero', 'asset_id': 'hero', 'provider': 'synthetic-vendor-a',
            'operation': 'image_to_3d', 'parameters': {'image_path': 0}, 'inputs': [master]}
        self.registry = {'providers': [{'id': 'synthetic-vendor-a'}]}
        self.portfolio = {'options': [{'id': 'chosen', 'operations': [self.op]}]}
        self.selection = {'source_ref': 'synthetic://not-a-user-approval'}
        self.run = self.project / 'art/synthetic-supplier-run'
        self.run.mkdir(parents=True)
        self.model = self.run / 'source.glb'
        self.model.write_bytes(synthetic_glb_bytes())
        (self.project / 'project.godot').write_text('[application]\nrun/main_scene="res://play.tscn"\n')
        self.scene = self.project / 'play.tscn'
        self.scene.write_text('[gd_scene load_steps=2 format=3]\n'
            '[ext_resource type="PackedScene" path="res://art/synthetic-supplier-run/source.glb" id="1"]\n'
            '[node name="Sample" type="Node3D"]\n[node name="Hero" parent="." instance=ExtResource("1")]\n')
        self.output = {'path': str(self.model), 'sha256': core.file_hash(self.model)}
        self.state = {'schema': 1, 'kind': 'supplier-job-run', 'project': str(self.project),
            'portfolio_digest': core.digest(self.portfolio), 'registry_digest': suppliers.registry_digest(self.registry),
            'selection_digest': core.digest(self.selection), 'selected_option': 'chosen',
            'inputs': {'make-hero': image_policy.image_inputs(self.op, self.project)},
            'operations': {'make-hero': {'state': 'ready', 'task_id': 'original-task-1', 'artifacts': [self.output]}}}
        self.table = {'style_id': 'ceramic', 'asset_proposals': [{'asset_id': 'hero', 'route': 'generated',
            'generation': {'operation': 'image_to_3d'}}], 'modeling_references': self.package,
            'supplier_portfolio_digest': self.state['portfolio_digest']}
        self.binding = {'asset_id': 'hero', 'run_dir': str(self.run), 'operation_id': 'make-hero',
            'task_id': 'original-task-1', 'source_output': self.output, 'realized_output': self.output}
        self.inputs = {'scene': 'res://play.tscn', 'model_task_bindings': [self.binding],
                       'files': [{'id': 'hero', **self.output, 'category': 'asset'}]}
        self.save()

    def tearDown(self):
        self.temp.cleanup()

    def save(self):
        for name, value in [('supplier-run.json', self.state), ('supplier-portfolio.json', self.portfolio),
                            ('supplier-registry.json', self.registry), ('supplier-selection.json', self.selection)]:
            core.write(self.run / name, value)

    def check(self):
        asset_routes.validate_model_tasks(self.inputs, self.table, self.project)

    def test_completed_original_image_task_and_model_pass(self):
        self.check()

    def test_same_contract_accepts_a_different_supplier(self):
        self.op['provider'] = 'synthetic-vendor-b'
        self.registry['providers'][0]['id'] = self.op['provider']
        self.state['portfolio_digest'] = core.digest(self.portfolio)
        self.state['registry_digest'] = suppliers.registry_digest(self.registry)
        self.table['supplier_portfolio_digest'] = self.state['portfolio_digest']
        self.save()
        self.check()

    def test_native_or_reuse_work_does_not_require_ai_percentage(self):
        self.table['asset_proposals'][0]['route'] = 'reuse'
        self.inputs['model_task_bindings'] = []
        self.check()

    def test_missing_actual_model_task_blocks_sample(self):
        self.inputs['model_task_bindings'] = []
        with self.assertRaisesRegex(core.WorkflowError, 'every AI/generated or hybrid'):
            self.check()

    def test_hybrid_cannot_hide_missing_model_task(self):
        self.table['asset_proposals'][0]['route'] = 'hybrid'
        self.inputs['model_task_bindings'] = []
        with self.assertRaisesRegex(core.WorkflowError, 'every AI/generated or hybrid'):
            self.check()

    def test_pending_or_failed_task_cannot_be_procedural_substitute(self):
        for state in ('pending', 'submitted', 'unknown_submission', 'failed'):
            with self.subTest(state=state):
                self.state['operations']['make-hero']['state'] = state
                self.save()
                with self.assertRaisesRegex(core.WorkflowError, 'pending, failed'):
                    self.check()

    def test_original_task_id_cannot_be_replaced(self):
        self.binding['task_id'] = 'invented-replacement'
        with self.assertRaisesRegex(core.WorkflowError, 'original task ID'):
            self.check()

    def test_original_output_cannot_be_replaced_by_local_placeholder(self):
        placeholder = self.project / 'placeholder.glb'
        placeholder.write_bytes(b'procedural-placeholder')
        self.binding['source_output'] = {'path': str(placeholder), 'sha256': core.file_hash(placeholder)}
        with self.assertRaisesRegex(core.WorkflowError, 'does not belong'):
            self.check()

    def test_unapproved_image_input_cannot_satisfy_model_route(self):
        self.state['inputs']['make-hero'][0]['sha256'] = '0' * 64
        self.save()
        with self.assertRaisesRegex(core.WorkflowError, 'input images differ'):
            self.check()

    def test_generated_source_must_remain_in_sample_identity(self):
        self.inputs['files'] = []
        with self.assertRaisesRegex(core.WorkflowError, 'retain generated source'):
            self.check()

    def test_unused_download_in_file_inventory_does_not_complete_model_route(self):
        self.scene.write_text('[gd_scene format=3]\n[node name="StillProcedural" type="Node3D"]\n')
        with self.assertRaisesRegex(core.WorkflowError, 'consumption is unverified'):
            self.check()

    def test_model_reference_in_comment_does_not_prove_native_consumption(self):
        script = self.project / 'sample.gd'
        script.write_text('extends Node3D\n# load("res://art/synthetic-supplier-run/source.glb")\n')
        self.scene.write_text('[gd_scene load_steps=2 format=3]\n'
            '[ext_resource type="Script" path="res://sample.gd" id="1"]\n'
            '[node name="StillProcedural" type="Node3D"]\nscript=ExtResource("1")\n')
        with self.assertRaisesRegex(core.WorkflowError, 'consumption is unverified'):
            self.check()

    def test_actual_assembly_manifest_connects_a_dynamic_loader_to_the_model(self):
        script = self.project / 'sample.gd'
        script.write_text('extends Node3D\n@export var manifest_path: String\nfunc use_model(path):\n    return load(path)\n')
        core.write(self.project / 'assembly.json', {'bindings': [{'id': 'hero', 'source': {
            'path': 'res://art/synthetic-supplier-run/source.glb'}}]})
        self.scene.write_text('[gd_scene load_steps=2 format=3]\n'
            '[ext_resource type="Script" path="res://sample.gd" id="1"]\n'
            '[node name="Sample" type="Node3D"]\nscript=ExtResource("1")\nmanifest_path="res://assembly.json"\n')
        self.check()

    def test_unresolved_computed_loader_does_not_admit_inventory_only_model(self):
        script = self.project / 'sample.gd'
        script.write_text('extends Node3D\nfunc use_model(path):\n    return load(path)\n')
        self.scene.write_text('[gd_scene load_steps=2 format=3]\n'
            '[ext_resource type="Script" path="res://sample.gd" id="1"]\n'
            '[node name="Sample" type="Node3D"]\nscript=ExtResource("1")\n')
        with self.assertRaisesRegex(core.WorkflowError, 'consumption is unverified'):
            self.check()

    def test_changed_realized_model_needs_processing_lineage(self):
        refined = self.project / 'refined.glb'
        refined.write_bytes(synthetic_glb_bytes('refined'))
        record = {'path': str(refined), 'sha256': core.file_hash(refined)}
        self.binding['realized_output'] = record
        self.inputs['files'].append({'id': 'refined', **record, 'category': 'asset'})
        self.scene.write_text(self.scene.read_text().replace('art/synthetic-supplier-run/source.glb', 'refined.glb'))
        with self.assertRaisesRegex(core.WorkflowError, 'processing method/source'):
            self.check()
        self.binding['processing'] = {'method': 'SYNTHETIC local refinement', 'source_ref': 'synthetic://tool-result',
            'input_sha256': self.output['sha256'], 'output_sha256': record['sha256']}
        self.check()

    def test_future_expansion_does_not_require_unstarted_assets(self):
        # H4 receives its archived original source table, not the future table.
        future_table = copy.deepcopy(self.table)
        future_table['asset_proposals'].append({'asset_id': 'future', 'route': 'generated',
                                              'generation': {'operation': 'image_to_3d'}})
        self.check()
        with self.assertRaisesRegex(core.WorkflowError, 'every AI/generated or hybrid'):
            asset_routes.validate_model_tasks(self.inputs, future_table, self.project)


if __name__ == '__main__':
    unittest.main()
