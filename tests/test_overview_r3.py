"""Offline scope/host/character contracts. No external tools or paid calls."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1] / "skills/greybox-to-multistyle-art"
sys.path.insert(0, str(ROOT / "runtime"))
from greybox.core import WorkflowError
from greybox.overview import (BASE_HOST_OPERATIONS, HOST_FEATURES, character_graph,
                              check_host_capabilities, generate_overview,
                              render_overview, validate_overview, validate_production_scope)


def host(host_id="workbuddy"):
    return {"schema": 1, "kind": "host-capability-report", "host_id": host_id,
            "session_id": "actual-session", "checked_at": datetime.now(timezone.utc).isoformat(),
            "operations": {name: {"status": "available", "evidence": "discovery-receipt.json",
                "channel": {"kind": "host_tool", "target": "actual." + name,
                            "supports": sorted(features)},
                "verification": {"level": "discovered", "evidence": "discovery-receipt.json"}}
                for name, features in HOST_FEATURES.items()}}


def intake():
    value = json.loads((ROOT / "schemas/overview-template.json").read_text())
    value["character"] = {"presence": "none"}
    return value


def animated():
    return {"presence": "required", "source": "new", "deformation": "required",
            "rig": "new", "animation": "reuse", "motion_ref": "walk.fbx",
            "retarget": "required"}


class OverviewTests(unittest.TestCase):
    def test_early_brief_carries_no_authorization_or_new_gate(self):
        brief = generate_overview(intake())
        self.assertTrue(validate_overview(brief)["ok"])
        self.assertFalse(brief["grants_authorization"])
        self.assertEqual([x["id"] for x in brief["human_gates"]], ["H1", "H2", "H3", "H4", "H5"])
        self.assertEqual(brief["character_graph"]["state"], "skipped")
        self.assertLess(len(render_overview(brief).splitlines()), 30)

    def test_scene_file_cannot_claim_playable_even_with_self_declared_baseline(self):
        value = intake()
        value["input"] = {"mode": "playable", "format": ".blend", "baseline_verified": True,
                          "baseline_evidence": "unrelated-screenshot.png"}
        with self.assertRaisesRegex(WorkflowError, "scene-only"):
            generate_overview(value)

    def test_spatial_only_input_requires_native_game_host_before_playable_delivery(self):
        value = intake()
        value["input"] = {"mode": "spatial_only", "format": "glb", "baseline_verified": False}
        brief = generate_overview(value)
        self.assertTrue(any("gameplay host/baseline" in x for x in brief["blockers"]))

    def test_playable_baseline_evidence_is_required(self):
        value = intake()
        value["input"]["baseline_verified"] = True
        with self.assertRaisesRegex(WorkflowError, "evidence"):
            generate_overview(value)
        value["input"]["baseline_evidence"] = "native-baseline-report.json"
        self.assertEqual(generate_overview(value)["target"]["baseline_status"], "verified_evidence_declared")

    def test_runtime_selection_does_not_claim_a_new_adapter_exists(self):
        value = intake()
        for engine in ("threejs",):
            value["target_engine"] = engine
            brief = generate_overview(value)
            self.assertEqual(brief["target"]["adapter_status"], "planned_unverified")
            self.assertTrue(any("separate integration" in x for x in brief["blockers"]))
        value["target_engine"] = "unity"
        brief = generate_overview(value)
        self.assertEqual(brief["target"]["adapter_status"], "implemented_native_adapter")
        self.assertEqual(brief["target"]["baseline_status"], "unverified")
        self.assertFalse(any("separate integration" in x for x in brief["blockers"]))
        value["target_engine"] = "blender"
        with self.assertRaisesRegex(WorkflowError, "geometry backend"):
            generate_overview(value)

    def test_scope_changes_require_regeneration(self):
        brief = generate_overview(intake())
        brief["intake"]["style_count"] = 3
        with self.assertRaisesRegex(WorkflowError, "intake changed"):
            validate_overview(brief)

    def test_necessary_character_node_cannot_be_deleted(self):
        value = intake()
        value["character"] = animated()
        brief = generate_overview(value)
        brief["character_graph"]["nodes"] = [n for n in brief["character_graph"]["nodes"]
                                               if n["id"] != "character_contact_check"]
        with self.assertRaisesRegex(WorkflowError, "required work omitted"):
            validate_overview(brief)

    def test_character_presence_none_does_not_require_rig_tools(self):
        graph = character_graph({"presence": "none"})
        self.assertEqual(graph["nodes"], [])
        self.assertEqual(graph["required_tools"], [])
        with self.assertRaisesRegex(WorkflowError, "No-character"):
            character_graph({"presence": "none", "rig": "new"})

    def test_new_animated_character_has_inspection_rig_retarget_contact_native_chain(self):
        graph = character_graph(animated())
        ids = [n["id"] for n in graph["nodes"]]
        self.assertEqual(ids, ["character_model", "character_inspect", "character_scale_fit",
                              "character_rig", "character_deformation_check", "character_motion",
                              "character_retarget", "character_contact_check", "character_export",
                              "character_native_check"])
        seen = set()
        for node in graph["nodes"]:
            self.assertLessEqual(set(node["depends_on"]), seen)
            seen.add(node["id"])
        self.assertTrue({"rig", "retarget", "contact_review", "native_character_validation"}
                        <= set(graph["required_tools"]))
        self.assertNotIn("mesh_edit", graph["required_tools"])

    def test_mesh_edit_only_for_explicit_repair_or_remesh_need(self):
        for operation, node_id in (("repair", "character_cleanup"), ("remesh", "character_remesh")):
            value = animated()
            value["mesh_processing"] = operation
            with self.assertRaisesRegex(WorkflowError, "concrete defect"):
                character_graph(value)
            value["mesh_processing_reason"] = "Measured source budget exceeds the declared device limit"
            graph = character_graph(value)
            self.assertIn(node_id, [node["id"] for node in graph["nodes"]])
            self.assertIn("mesh_edit", graph["required_tools"])
            self.assertLess([node["id"] for node in graph["nodes"]].index(node_id),
                            [node["id"] for node in graph["nodes"]].index("character_rig"))

    def test_new_static_character_does_not_require_edit_or_skeleton(self):
        graph = character_graph({"presence": "required", "source": "new", "deformation": "none",
                                 "rig": "none", "animation": "none", "retarget": "none"})
        self.assertIn("mesh_inspect", graph["required_tools"])
        self.assertFalse({"mesh_edit", "rig", "motion_generate"} & set(graph["required_tools"]))

    def test_remesh_cannot_keep_existing_rig_as_if_topology_were_unchanged(self):
        value = animated()
        value.update(source="reuse", asset_ref="pet.glb", rig="existing", mesh_processing="remesh",
                     mesh_processing_reason="Measured runtime budget exceeded")
        with self.assertRaisesRegex(WorkflowError, "changes topology"):
            character_graph(value)
        value["rig"] = "new"
        self.assertIn("character_remesh", [node["id"] for node in character_graph(value)["nodes"]])

    def test_unresolved_mesh_processing_cannot_be_silently_skipped(self):
        value = animated(); value["mesh_processing"] = "uncertain"
        graph = character_graph(value)
        self.assertEqual(graph["state"], "needs_scope")
        self.assertIn("mesh_processing", graph["unresolved"])

    def test_historical_overview_keeps_original_derived_cleanup_and_digest(self):
        value = intake(); value["character"] = animated()
        brief = generate_overview(value, character_policy="legacy-v1")
        original = deepcopy(brief)
        self.assertNotIn("character_policy", brief)
        self.assertIn("mesh_edit", brief["character_graph"]["required_tools"])
        self.assertTrue(validate_overview(brief)["ok"])
        self.assertEqual(brief, original)
        brief["character_policy"] = "needs-driven-v2"
        with self.assertRaisesRegex(WorkflowError, "required work omitted"):
            validate_overview(brief)

    def test_static_character_reuses_asset_without_skeletal_work(self):
        graph = character_graph({"presence": "required", "source": "reuse", "asset_ref": "npc.glb",
                                 "deformation": "none", "rig": "none", "animation": "none", "retarget": "none"})
        ids = [n["id"] for n in graph["nodes"]]
        self.assertEqual(ids, ["character_reuse_check", "character_scale_fit", "character_export", "character_native_check"])
        self.assertNotIn("rig", graph["required_tools"])

    def test_rigid_motion_does_not_introduce_a_skeleton(self):
        graph = character_graph({"presence": "required", "source": "reuse", "asset_ref": "robot.glb",
                                 "deformation": "none", "rig": "none", "animation": "new", "retarget": "none"})
        self.assertIn("rigid_animation", graph["required_tools"])
        self.assertNotIn("rig", graph["required_tools"])
        self.assertIn("contact_review", graph["required_tools"])

    def test_unknown_character_scope_blocks_dependent_work(self):
        graph = character_graph({"presence": "uncertain"})
        self.assertEqual(graph["state"], "needs_scope")
        self.assertEqual([n["id"] for n in graph["nodes"]], ["character_scope"])
        self.assertEqual(graph["required_tools"], ["human_input"])

    def test_deforming_character_cannot_omit_necessary_rig(self):
        value = animated()
        value["rig"] = "none"
        with self.assertRaisesRegex(WorkflowError, "Deforming characters"):
            character_graph(value)

    def test_reused_motion_on_new_skeleton_needs_compatibility_or_retarget(self):
        value = animated()
        value["retarget"] = "none"
        with self.assertRaisesRegex(WorkflowError, "verified skeleton compatibility"):
            character_graph(value)
        value.update(skeleton_compatible_verified=True, compatibility_evidence="skeleton-map-report.json")
        self.assertNotIn("retarget", character_graph(value)["required_tools"])

    def test_reused_motion_on_existing_rig_also_requires_compatibility(self):
        value = animated()
        value.update(source="reuse", asset_ref="hero.glb", rig="existing", retarget="none")
        with self.assertRaises(WorkflowError):
            character_graph(value)
        value.update(skeleton_compatible_verified=True, compatibility_evidence="actual-skeleton-map.json")
        self.assertNotIn("retarget", character_graph(value)["required_tools"])

    def test_reuse_requires_named_asset_and_motion(self):
        value = animated()
        del value["motion_ref"]
        with self.assertRaisesRegex(WorkflowError, "motion_ref"):
            character_graph(value)

    def test_current_host_can_be_bound_without_codex_names(self):
        report = host("custom-agent")
        result = check_host_capabilities(report, expected_host="custom-agent", expected_session="actual-session")
        self.assertTrue(result["ok"])
        self.assertEqual(result["collaboration"], "parallel_available")

    def test_optional_subagents_fall_back_to_same_sequential_workflow(self):
        report = host()
        del report["operations"]["delegate"]
        result = check_host_capabilities(report)
        self.assertTrue(result["ok"])
        self.assertEqual(result["collaboration"], "sequential_fallback")

    def test_image_generator_without_reference_images_is_blocked(self):
        report = host()
        report["operations"]["image_generate"]["channel"]["supports"] = ["text_to_image"]
        result = check_host_capabilities(report, list(BASE_HOST_OPERATIONS) + ["image_generate"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["blockers"], [{"operation": "image_generate", "reason": "required-feature-missing"}])
        self.assertFalse(generate_overview(intake(), report)["host_readiness"]["ok"])

    def test_host_profile_and_blank_discovery_template_do_not_establish_readiness(self):
        with self.assertRaisesRegex(WorkflowError, "static host profile"):
            check_host_capabilities({"schema": 1, "kind": "host-profile"})
        report = json.loads((ROOT / "schemas/host-template.json").read_text())
        report.update(session_id="actual-session", checked_at=datetime.now(timezone.utc).isoformat())
        self.assertFalse(check_host_capabilities(report)["ok"])

    def test_another_session_and_expired_host_report_cannot_be_reused(self):
        report = host()
        with self.assertRaisesRegex(WorkflowError, "another session"):
            check_host_capabilities(report, expected_session="new-session")
        report["checked_at"] = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        with self.assertRaisesRegex(WorkflowError, "expired"):
            check_host_capabilities(report)

    def test_manual_channel_cannot_claim_pixel_inspection(self):
        report = host()
        report["operations"]["image_inspect"]["channel"]["kind"] = "manual"
        self.assertFalse(check_host_capabilities(report)["ok"])

    def test_secrets_are_rejected_without_printing_values(self):
        report = host()
        report["api_key"] = "private-value-must-not-appear"
        with self.assertRaises(WorkflowError) as caught:
            check_host_capabilities(report)
        self.assertNotIn("private-value-must-not-appear", str(caught.exception))
        self.assertIn("credentials", str(caught.exception))


class ProductionScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="overview-scope-offline-")
        self.base = Path(self.temp.name)
        self.value = intake()
        self.value["character"] = animated()
        self.brief = generate_overview(self.value)
        self.evidence = self.file("SYNTHETIC-discovery.json", {"fixture_only": True})
        overview = self.file("overview.json", self.brief)
        self.portfolio = {"overview": overview, "required_assets": ["hero", "environment"],
                          "character_assets": ["hero"], "options": []}
        for option_id in ("balanced", "economical"):
            self.portfolio["options"].append({"id": option_id,
                "assets": [{"asset_id": "hero", "operation_ids": ["hero-model", "hero-rig"]},
                           {"asset_id": "environment", "operation_ids": []}],
                "operations": [{"id": "hero-model", "asset_id": "hero", "operation": "image_to_3d"},
                               {"id": "hero-rig", "asset_id": "hero", "operation": "rig"}],
                "character_work": self.manual_work()})

    def tearDown(self):
        self.temp.cleanup()

    def file(self, name, value):
        from greybox.core import file_hash, write
        path = self.base / name
        write(path, value)
        return {"path": str(path), "sha256": file_hash(path)}

    def manual_work(self):
        return [{"asset_id": "hero", "node_id": node["id"], "route": "manual",
                 "capabilities": list(node["required_tools"]),
                 "route_reason": "Fixture explicitly binds the artist's established processing route",
                 "supplier_evaluation": "Fixture assumes no configured applicable supplier; no cloud calls",
                 "handoff": {"owner": "artist", "action": "Perform the declared character work",
                             "resume_requirement": "Return source, output hashes and named check evidence"}}
                for node in self.brief["character_graph"]["nodes"]]

    def check(self):
        return validate_production_scope(self.brief, self.portfolio, self.base)

    def test_full_functional_chain_can_be_human_assisted_without_forced_paid_operations(self):
        self.assertTrue(self.check()["ok"])
        self.assertFalse(self.check()["grants_authorization"])

    def test_cheaper_option_cannot_silently_drop_rig_or_native_validation(self):
        for missing in ("character_rig", "character_native_check"):
            with self.subTest(missing=missing):
                document = deepcopy(self.portfolio)
                document["options"][1]["character_work"] = [record for record in document["options"][1]["character_work"]
                                                             if record["node_id"] != missing]
                with self.assertRaisesRegex(WorkflowError, "omits required character function"):
                    validate_production_scope(self.brief, document, self.base)

    def test_supplier_rig_binds_same_asset_and_actual_function(self):
        record = next(r for r in self.portfolio["options"][0]["character_work"] if r["node_id"] == "character_rig")
        record.clear()
        record.update(asset_id="hero", node_id="character_rig", route="supplier", capabilities=["rig"], operation_id="hero-rig",
                      route_reason="Suitable installed rigging operation avoids custom rig code")
        self.assertTrue(self.check()["ok"])
        record["operation_id"] = "hero-model"
        with self.assertRaisesRegex(WorkflowError, "does not implement"):
            self.check()
        record["operation_id"] = "unpriced-rig"
        with self.assertRaisesRegex(WorkflowError, "costed operation"):
            self.check()

    def test_local_inspection_requires_actual_channel_evidence_and_all_functions(self):
        record = next(r for r in self.portfolio["options"][0]["character_work"] if r["node_id"] == "character_inspect")
        record.update(route="local", channel={"kind": "cli", "target": "installed-blender-command",
                      "supports": ["mesh_inspect", "mesh_edit"]}, evidence=[self.evidence])
        record.pop("handoff")
        self.assertTrue(self.check()["ok"])
        record["channel"]["supports"] = ["mesh_edit"]
        with self.assertRaisesRegex(WorkflowError, "supporting its functions"):
            self.check()

    def test_custom_processing_needs_supplier_comparison_but_reuse_does_not(self):
        record = next(r for r in self.portfolio["options"][0]["character_work"] if r["node_id"] == "character_rig")
        record.pop("supplier_evaluation")
        with self.assertRaisesRegex(WorkflowError, "supplier_evaluation"):
            self.check()
        record.update(route="reuse", evidence=[self.evidence])
        record.pop("route_reason")
        self.assertTrue(self.check()["ok"])

    def test_supplier_processing_needs_suitability_reason(self):
        record = next(r for r in self.portfolio["options"][0]["character_work"] if r["node_id"] == "character_rig")
        record.update(route="supplier", operation_id="hero-rig")
        record.pop("route_reason")
        with self.assertRaisesRegex(WorkflowError, "route_reason"):
            self.check()

    def test_historical_portfolio_keeps_original_work_without_new_route_fields(self):
        self.brief = generate_overview(self.value, character_policy="legacy-v1")
        self.portfolio["overview"] = self.file("overview.json", self.brief)
        for option in self.portfolio["options"]:
            option["character_work"] = self.manual_work()
            for record in option["character_work"]:
                record.pop("route_reason")
                record.pop("supplier_evaluation")
        self.assertTrue(self.check()["ok"])

    def test_reused_checks_require_current_hash_bound_evidence(self):
        record = next(r for r in self.portfolio["options"][0]["character_work"] if r["node_id"] == "character_deformation_check")
        record.update(route="reuse", evidence=[self.evidence])
        record.pop("handoff")
        self.assertTrue(self.check()["ok"])
        Path(self.evidence["path"]).write_text("Changed deformation inspection")
        with self.assertRaisesRegex(WorkflowError, "missing or changed"):
            self.check()

    def test_character_asset_id_must_exist_in_every_option(self):
        self.portfolio["character_assets"] = ["unscoped-character"]
        with self.assertRaisesRegex(WorkflowError, "actual asset scope"):
            self.check()

    def test_required_characters_cannot_be_omitted_by_empty_list(self):
        self.portfolio["character_assets"] = []
        with self.assertRaisesRegex(WorkflowError, "scoped character_assets"):
            self.check()

    def test_environment_only_batch_needs_explicit_h3_bound_deferral(self):
        self.portfolio["character_assets"] = []
        self.portfolio["character_deferral"] = {"scope": "excluded_from_this_batch", "reason": "This H3 batch only builds environment assets"}
        for option in self.portfolio["options"]:
            option["character_work"] = []
        result = self.check()
        self.assertTrue(result["deferred"])
        self.assertIn("character_rig", result["remaining_nodes"])

    def test_no_character_branch_needs_no_rig_or_motion_bindings(self):
        self.value["character"] = {"presence": "none"}
        self.brief = generate_overview(self.value)
        self.portfolio["overview"] = self.file("overview-none.json", self.brief)
        self.portfolio["character_assets"] = []
        for option in self.portfolio["options"]:
            option["character_work"] = []
        self.assertEqual(self.check()["character_state"], "skipped")

    def test_changed_or_different_overview_cannot_bind_the_scope(self):
        self.brief = generate_overview({**self.value, "style_count": 3})
        with self.assertRaisesRegex(WorkflowError, "different workflow overview"):
            self.check()

    def test_incomplete_manual_handoff_is_not_a_functional_route(self):
        self.portfolio["options"][0]["character_work"][0]["handoff"].pop("resume_requirement")
        with self.assertRaisesRegex(WorkflowError, "resumable evidence"):
            self.check()


if __name__ == "__main__":
    unittest.main()
