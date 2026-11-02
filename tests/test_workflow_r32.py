"""Offline production-policy regression probes; all approvals/images are synthetic."""
from pathlib import Path
import copy
import hashlib
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] / "skills/greybox-to-multistyle-art"
sys.path.insert(0, str(ROOT / "runtime"))
sys.dont_write_bytecode = True
from greybox import core, workflow
from workflow_fixtures import make_workflow, approve, refresh_evidence, evidence, png, review_fixture


class ImageConditionedWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="gb-r32-gates-")
        self.project = Path(self.tmp.name) / "project"
        shutil.copytree(ROOT / "fixtures/godot-free", self.project)
        self.plan = core.read(self.project / "plan.json")
        self.plan.pop("purpose")
        self.path, self.data = make_workflow(self.project, self.plan)

    def tearDown(self):
        self.tmp.cleanup()

    def stage(self, sid, scope="ceramic"):
        return next(s for s in self.data["stages"] if s["id"] == sid and s["scope"] == scope)

    def value(self, sid, role, scope="ceramic"):
        return core.read(next(e["path"] for e in self.stage(sid, scope)["evidence"] if e["role"] == role))

    def save(self):
        core.write(self.path, self.data)

    def rechain(self):
        """New synthetic decisions, never a migration or actual user authority."""
        digests = {}
        for stage in self.data["stages"]:
            sid, scope = stage["id"], stage["scope"]
            stage["consumes"] = {d: digests[d] for d in workflow.dependencies(sid, scope)}
            if sid == "selection":
                selection = self.value(sid, "selection_decision", scope)
                selection["directions_digest"] = digests["shared/directions"]
                refresh_evidence(stage, "selection_decision", selection)
            elif sid == "spatial_design":
                graph = self.value(sid, "spatial_graph", scope)
                graph["atlas_digest"] = digests[scope + "/atlas"]
                refresh_evidence(stage, "spatial_graph", graph)
            elif sid == "production_plan":
                recipe = self.value(sid, "assembly_recipe", scope)
                recipe["spatial_design_digest"] = digests[scope + "/spatial_design"]
                refresh_evidence(stage, "assembly_recipe", recipe)
            review_fixture(stage)
            if sid in workflow.HUMAN_STAGES:
                approve(stage)
            digests[scope + "/" + sid] = workflow.stage_digest(stage)
        self.save()

    def mutate(self, sid, role, change, scope="ceramic"):
        value = self.value(sid, role, scope)
        change(value)
        refresh_evidence(self.stage(sid, scope), role, value)
        self.rechain()

    def large(self, mode="continuous"):
        baseline = self.value("baseline", "spatial_contract", "shared")
        baseline["spatial_scope"].update(mode=mode, segments=[
            {"id": "region-start", "space_ids": ["start"]},
            {"id": "region-end", "space_ids": ["end"]}])
        refresh_evidence(self.stage("baseline", "shared"), "spatial_contract", baseline)
        for n, sid in enumerate(self.data["selected_styles"]):
            atlas = self.value("atlas", "atlas_manifest", sid)
            stage = self.stage("atlas", sid)
            for i, space in enumerate(("start", "end")):
                item = evidence(self.project, sid + "-region-" + space + ".png", "concept_image", png(150 + n * 2 + i), sid + "-region-" + space)
                stage["evidence"].append(item)
                atlas["views"].append({"id": "region-" + space, "segment_id": "region-" + space,
                    "role": "key_scene", "camera_id": "camera-" + space, "space_ids": [space],
                    "concept_image_id": item["id"], "concept_sha256": item["sha256"]})
            refresh_evidence(stage, "atlas_manifest", atlas)
        self.rechain()

    def test_complete_current_workflow_passes(self):
        result = workflow.inspect_workflow(self.path, self.project)
        self.assertTrue(result["production_policy_current"])
        self.assertEqual(result["ready_for"], "representative_production")

    def test_legacy_workflow_is_readable_but_cannot_start_new_production(self):
        self.data.pop("production_policy")
        self.save()
        result = workflow.inspect_workflow(self.path, self.project)
        self.assertFalse(result["production_policy_current"])
        self.assertEqual(result["ready_for"], "historical_integrity")
        self.plan["workflow"] = {"path": str(self.path), "sha256": core.file_hash(self.path)}
        with self.assertRaisesRegex(core.WorkflowError, "BLOCKED_WORKFLOW_POLICY"):
            workflow.check_plan_gate(self.plan, self.project)

    def test_new_workflow_requires_explicit_baseline_spatial_scope(self):
        self.mutate("baseline", "spatial_contract", lambda b: b.pop("spatial_scope"), "shared")
        with self.assertRaisesRegex(core.WorkflowError, "baseline spatial_scope"):
            workflow.inspect_workflow(self.path, self.project)

    def test_approved_spatial_design_cannot_be_skipped(self):
        self.data["stages"] = [s for s in self.data["stages"] if s["id"] != "spatial_design"]
        self.save()
        with self.assertRaisesRegex(core.WorkflowError, "BLOCKED_STAGE_MISSING.*spatial_design"):
            workflow.inspect_workflow(self.path, self.project)

    def test_atlas_cannot_shrink_authoritative_baseline_spaces(self):
        self.mutate("atlas", "atlas_manifest", lambda a: a.update(required_space_ids=["start"]))
        with self.assertRaisesRegex(core.WorkflowError, "cannot shrink"):
            workflow.inspect_workflow(self.path, self.project)

    def test_atlas_cannot_omit_authoritative_transition(self):
        self.mutate("atlas", "atlas_manifest", lambda a: a.update(required_transition_ids=[]))
        with self.assertRaisesRegex(core.WorkflowError, "baseline transitions"):
            workflow.inspect_workflow(self.path, self.project)

    def test_continuous_atlas_with_expansions_passes(self):
        self.large()
        self.assertTrue(workflow.inspect_workflow(self.path, self.project)["ok"])

    def test_large_atlas_with_expansions_passes(self):
        self.large("large")
        self.assertTrue(workflow.inspect_workflow(self.path, self.project)["ok"])

    def test_large_single_overview_cannot_substitute_for_expansion(self):
        self.large()
        stage = self.stage("atlas")
        atlas = self.value("atlas", "atlas_manifest")
        atlas["views"] = [v for v in atlas["views"] if v["role"] != "key_scene"]
        stage["evidence"] = [e for e in stage["evidence"] if e["role"] != "concept_image" or e["id"] == atlas["views"][0]["concept_image_id"]]
        refresh_evidence(stage, "atlas_manifest", atlas)
        self.rechain()
        with self.assertRaisesRegex(core.WorkflowError, "every baseline region/segment"):
            workflow.inspect_workflow(self.path, self.project)

    def test_large_key_scenes_need_distinct_cameras(self):
        self.large()
        self.mutate("atlas", "atlas_manifest", lambda a: [v.update(camera_id="same") for v in a["views"] if v["role"] == "key_scene"])
        with self.assertRaisesRegex(core.WorkflowError, "distinct actual images and cameras"):
            workflow.inspect_workflow(self.path, self.project)

    def test_segment_must_cover_its_own_spaces(self):
        self.large()
        self.mutate("atlas", "atlas_manifest", lambda a: next(v for v in a["views"] if v.get("segment_id") == "region-end").update(space_ids=["start"]))
        with self.assertRaisesRegex(core.WorkflowError, "omit spaces in their baseline segment"):
            workflow.inspect_workflow(self.path, self.project)

    def test_large_scope_needs_multiple_explicit_segments(self):
        self.mutate("baseline", "spatial_contract", lambda b: b["spatial_scope"].update(mode="large", segments=[{"id": "all", "space_ids": ["start", "end"]}]), "shared")
        with self.assertRaisesRegex(core.WorkflowError, "at least two"):
            workflow.inspect_workflow(self.path, self.project)

    def test_spatial_design_cannot_be_only_space_id_list(self):
        self.mutate("spatial_design", "spatial_graph", lambda g: g.pop("space_designs"))
        with self.assertRaisesRegex(core.WorkflowError, "per-space art intent"):
            workflow.inspect_workflow(self.path, self.project)

    def test_spatial_design_requires_near_mid_far_composition(self):
        self.mutate("spatial_design", "spatial_graph", lambda g: g["space_designs"][0].pop("background"))
        with self.assertRaisesRegex(core.WorkflowError, "needs background"):
            workflow.inspect_workflow(self.path, self.project)

    def test_spatial_design_requires_boundary_continuity(self):
        self.mutate("spatial_design", "spatial_graph", lambda g: g["boundaries"][0].update(continuity_rule=""))
        with self.assertRaisesRegex(core.WorkflowError, "continuity/assembly"):
            workflow.inspect_workflow(self.path, self.project)

    def test_production_table_cannot_omit_asset_package(self):
        self.mutate("production_plan", "production_table", lambda t: t.pop("asset_proposals"))
        with self.assertRaisesRegex(core.WorkflowError, "actual per-asset/source"):
            workflow.inspect_workflow(self.path, self.project)

    def test_assembly_recipe_cannot_be_empty(self):
        self.mutate("production_plan", "assembly_recipe", lambda r: r.update(assemblies=[]))
        with self.assertRaisesRegex(core.WorkflowError, "actual placement/fitting"):
            workflow.inspect_workflow(self.path, self.project)

    def test_assembly_recipe_cannot_omit_material_integration(self):
        self.mutate("production_plan", "assembly_recipe", lambda r: r["assemblies"][0].pop("material_and_lighting"))
        with self.assertRaisesRegex(core.WorkflowError, "material_and_lighting"):
            workflow.inspect_workflow(self.path, self.project)

    def test_assembly_recipe_requires_every_proposed_source(self):
        self.mutate("production_plan", "assembly_recipe", lambda r: r["assemblies"].pop())
        with self.assertRaisesRegex(core.WorkflowError, "omits proposed assets"):
            workflow.inspect_workflow(self.path, self.project)

    def test_assembly_dependencies_cannot_cycle(self):
        def cycle(r):
            r["assemblies"][0]["depends_on"] = [r["assemblies"][1]["id"]]
            r["assemblies"][1]["depends_on"] = [r["assemblies"][0]["id"]]
        self.mutate("production_plan", "assembly_recipe", cycle)
        with self.assertRaisesRegex(core.WorkflowError, "contain a cycle"):
            workflow.inspect_workflow(self.path, self.project)

    def test_text_to_3d_proposal_cannot_pass_approval(self):
        def generation(t):
            t["asset_proposals"][0].update(route="generated", generation={"operation": "text_to_3d"})
        self.mutate("production_plan", "production_table", generation)
        with self.assertRaisesRegex(core.WorkflowError, "text_to_3d cannot"):
            workflow.inspect_workflow(self.path, self.project)

    def test_generated_proposal_requires_actual_modeling_reference_package(self):
        self.mutate("production_plan", "production_table", lambda t: t["asset_proposals"][0].update(route="generated", generation={"operation": "image_to_3d"}))
        with self.assertRaisesRegex(core.WorkflowError, "hashed modeling-reference package"):
            workflow.inspect_workflow(self.path, self.project)


    def reference_package(self, mode="single"):
        from modeling_ref_fixtures import write_reference_package
        atlas = self.value("atlas", "atlas_manifest")
        table = self.value("production_plan", "production_table")
        asset = table["asset_proposals"][0]
        asset.update(route="generated", generation={"operation": "image_to_3d" if mode == "single" else "multiview_to_3d"})
        table["modeling_references"] = write_reference_package(self.project, [asset["asset_id"]], style_id="ceramic",
            selected_concept_sha256=atlas["direction_concept_sha256"], mode=mode)
        refresh_evidence(self.stage("production_plan"), "production_table", table)
        visual = self.value("production_plan", "visual_package")
        next(b for b in visual["bom"] if b["asset_id"] == asset["asset_id"])["reference_status"] = "production_ready"
        refresh_evidence(self.stage("production_plan"), "visual_package", visual)
        self.rechain()
        return table["modeling_references"]

    def test_actual_single_image_package_passes_approved_workflow(self):
        self.reference_package()
        self.assertTrue(workflow.inspect_workflow(self.path, self.project)["ok"])

    def test_actual_multiview_package_passes_approved_workflow(self):
        self.reference_package("multiview")
        self.assertTrue(workflow.inspect_workflow(self.path, self.project)["ok"])

    def test_reference_package_cannot_bind_another_selected_concept(self):
        reference = self.reference_package()
        path = core.resolve_input(reference["path"], self.project)
        package = core.read(path)
        package["selected_concept_sha256"] = "f" * 64
        core.write(path, package)
        self.mutate("production_plan", "production_table", lambda t: t["modeling_references"].update(sha256=core.file_hash(path)))
        with self.assertRaisesRegex(core.WorkflowError, "concept"):
            workflow.inspect_workflow(self.path, self.project)

    def test_dependency_walker_binds_indirect_modeling_reference_images(self):
        reference = self.reference_package()
        package_path = core.resolve_input(reference["path"], self.project)
        package = core.read(package_path)
        image = package["assets"][0]["views"][0]["image"]
        image_path = core.resolve_input(image["path"], self.project)
        records = {d["path"]: d["sha256"] for d in workflow.evidence_dependencies(self.path, self.project)}
        self.assertEqual(records[str(package_path)], reference["sha256"])
        self.assertEqual(records[str(image_path)], image["sha256"])
        image_path.write_bytes(png(99))
        with self.assertRaises(core.WorkflowError):
            workflow.evidence_dependencies(self.path, self.project)

    def test_reference_package_cannot_change_without_new_h3_bytes(self):
        reference = self.reference_package()
        path = core.resolve_input(reference["path"], self.project)
        path.write_text(path.read_text() + " ")
        with self.assertRaisesRegex(core.WorkflowError, "package missing, changed"):
            workflow.inspect_workflow(self.path, self.project)


    def generated_execution(self):
        from modeling_ref_fixtures import write_reference_package
        reference = write_reference_package(self.project, ['hero'], style_id='ceramic',
            selected_concept_sha256=hashlib.sha256(png(1)).hexdigest())
        master = core.read(core.resolve_input(reference['path'], self.project))['assets'][0]['views'][0]['image']
        self.plan["assets"] = [{"id": "hero", "route": "generated", "reason": "SYNTHETIC test only",
            "generation": {"operation": "image_to_3d", "region": "cn", "parameters": {"version": "G1", "faceCount": 30000},
                           "reference": master, "modeling_references": reference}}]
        self.plan["bindings"][0]["source"] = {"asset_id": "hero"}
        self.plan["bindings"][0].pop("styles", None)
        self.path, self.data = make_workflow(self.project, self.plan)
        self.plan["workflow"] = {"path": str(self.path), "sha256": core.file_hash(self.path)}
        ref = self.value("production_plan", "production_table")["modeling_references"]
        package = core.read(core.resolve_input(ref["path"], self.project))
        return package["assets"][0]["views"][0]["image"]

    def test_actual_lux_image_bytes_must_match_each_h3_style_package(self):
        image = self.generated_execution()
        with patch.object(core, "_check_generation_reference", return_value={"mode": "single", "images": [{**image, "sha256": "f" * 64}]}):
            with self.assertRaisesRegex(core.WorkflowError, "submitted image bytes/order differ"):
                workflow.check_plan_gate(self.plan, self.project)

    def test_shared_asset_can_have_style_specific_packages_with_same_image_bytes(self):
        image = self.generated_execution()
        with patch.object(core, "_check_generation_reference", return_value={"mode": "single", "images": [image]}):
            self.assertTrue(workflow.check_plan_gate(self.plan, self.project)["ok"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
