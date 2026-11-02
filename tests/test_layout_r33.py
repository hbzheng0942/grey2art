"""Case ownership and pointer integrity; all native/H5 proofs are synthetic."""
import copy
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1] / "skills/greybox-to-multistyle-art"
sys.path.insert(0, str(ROOT / "runtime"))
sys.dont_write_bytecode = True
from greybox import core, layout


class LayoutTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="gb-r33-layout-")
        self.project = (Path(self.tmp.name) / "project").resolve()
        self.project.mkdir()
        self.plan = {"styles": [{"id": "sunset", "name": "落日海岸"}, {"id": "paper"}],
                     "workspace": {"schema": 1, "case_id": "hole", "root": "art/hole", "engine": "godot",
                                   "asset_owners": {"palm": {"scope": "style", "style_id": "sunset"},
                                                    "shared-prop": {"scope": "shared"}}}, "assets": []}
        self.plan_hash = core.digest(self.plan)

    def tearDown(self):
        self.tmp.cleanup()

    def file(self, relative, text="test"):
        p = self.project / relative
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return {"path": str(p), "sha256": core.file_hash(p)}

    def scene(self, revision="a"):
        return self.file("art/hole/styles/sunset/runtime/revisions/" + revision + "/play.tscn", "[gd_scene]")

    def proof(self, value, name="proof.json"):
        p = self.project / "art/hole/styles/sunset/production/runs/test" / name
        core.write(p, value)
        return {"path": str(p), "sha256": core.file_hash(p)}

    def native_proof(self, files):
        return self.proof({"style_id": "sunset", "plan_hash": self.plan_hash, "passed": True,
                           "files": copy.deepcopy(files), "synthetic_test_only": True})

    def acceptance(self, scene):
        manifest = {"planHash": self.plan_hash, "styles": [{"id": "sunset", "entry_scene": scene["path"],
                    "owned_files": [scene], "sources": [], "native_evidence": []}]}
        return self.proof({"kind": "human-delivery-acceptance", "actor": "user", "decision": "accepted",
                           "source_ref": "synthetic://test-only", "manifest": manifest,
                           "manifestHash": core.digest(manifest)}, "acceptance.json")

    def test_roots_separate_shared_and_style_content(self):
        roots = layout.roots(self.project, self.plan)
        self.assertEqual(roots["runs"], self.project / "art/hole/shared/production/runs")
        self.assertEqual(layout.run_root(self.project, self.plan, "run", "sunset"),
                         self.project / "art/hole/styles/sunset/production/runs/run")
        self.assertEqual(layout.runtime_root(self.project, self.plan, "sunset"),
                         self.project / "art/hole/styles/sunset/runtime")

    def test_asset_identity_and_ownership_select_paths(self):
        self.assertEqual(layout.asset_path(self.project, self.plan, "palm"),
                         self.project / "art/hole/styles/sunset/assets/palm/model.glb")
        self.assertEqual(layout.asset_path(self.project, self.plan, "shared-prop"),
                         self.project / "art/hole/shared/assets/shared-prop/model.glb")
        with self.assertRaises(core.WorkflowError):
            layout.asset_path(self.project, self.plan, "palm", "paper")

    def test_assets_need_explicit_owners_even_if_bound_once(self):
        self.plan["assets"] = [{"id": "unowned"}]
        with self.assertRaisesRegex(core.WorkflowError, "explicit"):
            layout.asset_owner(self.plan, "unowned")

    def test_conflicting_owner_fields_rejected(self):
        self.plan["assets"] = [{"id": "palm", "ownership": {"scope": "shared"}}]
        with self.assertRaisesRegex(core.WorkflowError, "Conflicting"):
            layout.workspace(self.plan)

    def test_shared_shorthand_cannot_override_style(self):
        self.plan["workspace"]["shared_asset_ids"] = ["palm"]
        with self.assertRaises(core.WorkflowError):
            layout.workspace(self.plan)

    def test_portfolio_selected_styles_and_asset_id_supported(self):
        self.plan["selected_styles"] = [s["id"] for s in self.plan.pop("styles")]
        self.plan["assets"] = [{"asset_id": "tree", "ownership": {"scope": "style", "style_id": "paper"}}]
        self.assertEqual(layout.asset_owner(self.plan, "tree")["style_id"], "paper")
        self.assertEqual(layout.register(self.project, self.plan)["styles"], ["paper", "sunset"])

    def test_invalid_case_paths_and_style_paths_rejected(self):
        for value in ("art/../hole", "/art/hole", "art//hole", "art/hole/", "res://art/hole", "art/other"):
            with self.subTest(value=value):
                plan = copy.deepcopy(self.plan)
                plan["workspace"]["root"] = value
                with self.assertRaises(core.WorkflowError):
                    layout.workspace(plan)
        with self.assertRaises(core.WorkflowError):
            layout.run_root(self.project, self.plan, "../run")

    def test_symlinked_case_cannot_escape_project(self):
        external = Path(self.tmp.name) / "elsewhere"
        external.mkdir()
        (self.project / "art").mkdir()
        (self.project / "art/hole").symlink_to(external, target_is_directory=True)
        with self.assertRaisesRegex(core.WorkflowError, "symlink"):
            layout.roots(self.project, self.plan)

    def test_symlinked_child_cannot_escape_project(self):
        external = Path(self.tmp.name) / "elsewhere"
        external.mkdir()
        (self.project / "art/hole/styles/sunset").mkdir(parents=True)
        (self.project / "art/hole/styles/sunset/assets").symlink_to(external, target_is_directory=True)
        with self.assertRaisesRegex(core.WorkflowError, "symlink"):
            layout.asset_path(self.project, self.plan, "palm")

    def test_same_project_case_alias_cannot_claim_another_case(self):
        (self.project / "art/other").mkdir(parents=True)
        (self.project / "art/hole").symlink_to(self.project / "art/other", target_is_directory=True)
        with self.assertRaisesRegex(core.WorkflowError, "symlink"):
            layout.register(self.project, self.plan)
        self.assertFalse((self.project / "art/other/index.json").exists())

    def test_same_project_asset_alias_cannot_claim_another_style(self):
        other = self.project / "art/hole/styles/paper/assets/tree"
        other.mkdir(parents=True)
        palm = self.project / "art/hole/styles/sunset/assets/palm"
        palm.parent.mkdir(parents=True)
        palm.symlink_to(other, target_is_directory=True)
        with self.assertRaisesRegex(core.WorkflowError, "symlink"):
            layout.asset_path(self.project, self.plan, "palm")
        with self.assertRaisesRegex(core.WorkflowError, "symlink"):
            layout.validate_output(self.project, self.plan, palm / "model.glb", "asset", "sunset", "palm")

    def test_trusted_project_alias_is_supported_without_relaxing_internal_aliases(self):
        alias = Path(self.tmp.name) / "selected-project"
        alias.symlink_to(self.project, target_is_directory=True)
        output = alias / "art/hole/styles/sunset/design/spatial.json"
        expected = self.project / "art/hole/styles/sunset/design/spatial.json"
        self.assertEqual(layout.validate_output(alias, self.plan, output, "design", "sunset"), expected)
        self.file("art/hole/styles/sunset/design/spatial.json", "{}")
        layout.record_artifact(alias, self.plan, output, "design", "sunset")
        self.assertTrue((self.project / "art/hole/index.json").is_file())
        internal = self.project / "art/hole/styles/sunset/design/alias"
        target = self.project / "art/hole/styles/paper/design"
        target.mkdir(parents=True)
        internal.symlink_to(target, target_is_directory=True)
        with self.assertRaisesRegex(core.WorkflowError, "symlink"):
            layout.validate_output(alias, self.plan, alias / "art/hole/styles/sunset/design/alias/plan.json", "design", "sunset")
        run_target = self.project / "art/hole/shared/production/runs/actual"
        run_target.mkdir(parents=True)
        run_link = self.project / "art/hole/shared/production/runs/linked"
        run_link.symlink_to(run_target, target_is_directory=True)
        with self.assertRaisesRegex(core.WorkflowError, "symlink"):
            layout.validate_output(alias, self.plan, alias / "art/hole/shared/production/runs/linked/plan.json", "run")

    def test_workspace_record_cli_supports_selected_project_alias(self):
        alias = Path(self.tmp.name) / "cli-project-alias"
        alias.symlink_to(self.project, target_is_directory=True)
        plan_path = self.project / "workspace-plan.json"
        core.write(plan_path, self.plan)
        source = self.file("art/hole/styles/sunset/design/recipe.json", "{}")
        result = subprocess.run([sys.executable, str(ROOT / "scripts/greybox.py"), "workspace", "record",
            "--file", str(plan_path), "--project", str(alias), "--style-id", "sunset", "--role", "design",
            "--path", str(alias / "art/hole/styles/sunset/design/recipe.json")], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(core.read(self.project / "art/hole/index.json")["artifacts"][source["path"]]["role"], "design")

    def test_engine_mapping_keeps_unity_resources_inside_assets(self):
        self.plan["workspace"]["engine"] = "unity"
        self.assertEqual(layout.runtime_root(self.project, self.plan, "sunset"),
                         self.project / "Assets/Art/hole/styles/sunset/runtime")
        self.assertEqual(layout.style_root(self.project, self.plan, "sunset"), self.project / "art/hole/styles/sunset")
        self.plan["workspace"]["resource_root"] = "Somewhere/hole"
        with self.assertRaises(core.WorkflowError):
            layout.workspace(self.plan)

    def test_threejs_served_assets_source_code_and_logical_art_have_separate_roots(self):
        self.plan["workspace"]["engine"] = "threejs"
        roots = layout.roots(self.project, self.plan, "sunset")
        self.assertEqual(roots["style"], self.project / "art/hole/styles/sunset")
        self.assertEqual(roots["assets"], self.project / "public/art/hole/styles/sunset/assets")
        self.assertEqual(roots["runtime"], self.project / "src/art/hole/styles/sunset/runtime")
        self.assertEqual(roots["tools"], self.project / "src/art/hole/shared/tools")
        for role, path, kwargs in (("runtime", roots["runtime"] / "main.ts", {"style_id": "sunset"}),
                                   ("tool", roots["tools"] / "materials.ts", {}),
                                   ("asset", roots["assets"] / "palm/model.glb", {"style_id": "sunset", "asset_id": "palm"})):
            self.assertEqual(layout.validate_output(self.project, self.plan, path, role, **kwargs), path)

    def test_threejs_mapping_cannot_publish_code_or_assets_into_wrong_carrier(self):
        self.plan["workspace"]["engine"] = "threejs"
        for field, path in (("resource_root", "src/art/hole"), ("code_root", "public/art/hole"),
                            ("code_root", "src/art/other"), ("resource_root", "public/hole")):
            plan = copy.deepcopy(self.plan)
            plan["workspace"][field] = path
            with self.subTest(field=field, path=path), self.assertRaises(core.WorkflowError):
                layout.workspace(plan)

    def test_threejs_dependency_closure_blocks_sibling_assets_and_code(self):
        self.plan["workspace"]["engine"] = "threejs"
        good = [self.file("src/art/hole/styles/sunset/runtime/main.ts"),
                self.file("src/art/hole/shared/tools/materials.ts"),
                self.file("public/art/hole/styles/sunset/assets/palm/model.glb"),
                self.file("public/art/hole/shared/assets/shared-prop/model.glb")]
        bad = [self.file("src/art/hole/styles/paper/runtime/main.ts"),
               self.file("public/art/hole/styles/paper/assets/tree/model.glb")]
        self.assertTrue(layout.audit_dependencies(self.project, self.plan, "sunset", good)["ok"])
        result = layout.audit_dependencies(self.project, self.plan, "sunset", good + bad)
        self.assertEqual(len(result["issues"]), 2)

    def test_unity_runtime_code_and_asset_mapping_preserves_logical_design(self):
        self.plan["workspace"]["engine"] = "unity"
        self.plan["workspace"]["code_root"] = "Assets/SceneCode/hole"
        r = layout.roots(self.project, self.plan, "sunset")
        self.assertEqual(r["runtime"], self.project / "Assets/SceneCode/hole/styles/sunset/runtime")
        self.assertEqual(r["assets"], self.project / "Assets/Art/hole/styles/sunset/assets")
        self.assertEqual(r["design"], self.project / "art/hole/styles/sunset/design")
        layout.register(self.project, self.plan)
        style = core.read(self.project / "art/hole/styles/sunset/style.json")
        self.assertEqual(style["code_root"], "Assets/SceneCode/hole/styles/sunset")
        self.assertEqual(style["resource_root"], "Assets/Art/hole/styles/sunset")

    def test_threejs_navigation_records_actual_code_and_resource_paths(self):
        self.plan["workspace"]["engine"] = "threejs"
        layout.register(self.project, self.plan)
        style = core.read(self.project / "art/hole/styles/sunset/style.json")
        self.assertEqual(style["links"]["runtime"]["path"], "src/art/hole/styles/sunset/runtime")
        self.assertEqual(style["links"]["assets"]["path"], "public/art/hole/styles/sunset/assets")
        self.assertEqual(style["links"]["design and recipe"]["path"], "art/hole/styles/sunset/design")

    def test_blender_dcc_project_registration_does_not_create_playable_acceptance(self):
        self.plan["workspace"]["engine"] = "blender"
        source = self.file("art/hole/styles/sunset/dcc/project.blend", "synthetic file only; not native Blender evidence")
        layout.record_artifact(self.project, self.plan, source["path"], "dcc", "sunset")
        style = core.read(self.project / "art/hole/styles/sunset/style.json")
        self.assertEqual(style["carrier"], "blender")
        self.assertEqual(style["dcc_entries"][0]["sha256"], source["sha256"])
        self.assertEqual(style["pointers"], {})
        readme = (self.project / "art/hole/README.md").read_text()
        self.assertIn("do not establish playable acceptance", readme)
        self.assertNotIn("| User accepted |", readme)
        with self.assertRaisesRegex(core.WorkflowError, "cannot establish playable"):
            layout.update_pointer(self.project, self.plan, "sunset", "development", source["path"], [source], self.plan_hash)

    def test_role_path_ownership_blocks_cross_style_and_run_assets(self):
        for p in ("art/hole/styles/paper/assets/palm/model.glb", "art/hole/shared/production/runs/run/downloads/palm.glb",
                  "art/hole/styles/sunset/assets/lux/model.glb", "art/assets/palm/model.glb"):
            with self.subTest(path=p), self.assertRaises(core.WorkflowError):
                layout.validate_output(self.project, self.plan, p, "asset", "sunset", "palm")

    def test_case_runs_are_valid_for_frozen_ledgers(self):
        p = "art/hole/shared/production/runs/run/supplier-portfolio.json"
        self.assertEqual(layout.validate_output(self.project, self.plan, p, "supplier-run"), self.project / p)

    def test_cross_style_plan_is_shared_but_art_design_is_style_owned(self):
        p = "art/hole/shared/production/plans/portfolio.json"
        self.assertEqual(layout.validate_output(self.project, self.plan, p, "plan"), self.project / p)
        with self.assertRaises(core.WorkflowError):
            layout.validate_output(self.project, self.plan, "art/hole/shared/design/coast.json", "design")

    def test_formal_dependency_audit_rejects_transient_and_sibling_paths(self):
        good = self.scene()
        old = self.file("art/experiments/old/downloads/model.glb")
        sibling = self.file("art/hole/styles/paper/assets/tree/model.glb")
        generic = self.file("art/assets/tree/model.glb")
        result = layout.audit_dependencies(self.project, self.plan, "sunset", [good, old, sibling, generic])
        self.assertFalse(result["ok"])
        self.assertEqual(len(result["issues"]), 3)
        self.assertEqual(result["dependencies"][0]["ownership"]["style_id"], "sunset")

    def test_declared_unchanged_reuse_never_copies_bytes(self):
        source = self.file("canonical/palm.glb")
        self.plan["assets"] = [{"id": "palm", "source": source}]
        result = layout.register_asset(self.project, self.plan, "palm", source)
        manifest = core.read(result["manifest"])
        self.assertEqual(manifest["files"][0]["path"], source["path"])
        self.assertFalse(layout.asset_path(self.project, self.plan, "palm").exists())
        self.assertTrue(layout.audit_dependencies(self.project, self.plan, "sunset", [source])["ok"])

    def test_registered_reuse_cannot_whitelist_transient_assets(self):
        source = self.file("art/experiments/old/model.glb")
        self.plan["assets"] = [{"id": "palm", "source": source}]
        with self.assertRaisesRegex(core.WorkflowError, "run/download"):
            layout.register_asset(self.project, self.plan, "palm", source)
        self.assertFalse(layout.audit_dependencies(self.project, self.plan, "sunset", [source])["ok"])

    def test_project_parent_names_do_not_reclassify_formal_assets_as_transient(self):
        for parent in ("runs/native", "production/runs/native", "experiments/native"):
            with self.subTest(parent=parent):
                self.project = (Path(self.tmp.name) / parent / "project").resolve()
                self.project.mkdir(parents=True)
                source = self.file("art/hole/styles/sunset/assets/palm/model.glb")
                self.plan["assets"] = [{"id": "palm", "source": source}]
                self.assertTrue(layout.register_asset(self.project, self.plan, "palm", source)["ok"])
                self.assertTrue(layout.audit_dependencies(self.project, self.plan, "sunset", [source])["ok"])
                transient = self.file("art/hole/shared/production/runs/old/downloads/palm.glb")
                self.plan["assets"] = [{"id": "palm", "source": transient}]
                with self.assertRaisesRegex(core.WorkflowError, "run/download"):
                    layout.register_asset(self.project, self.plan, "palm", transient)
                self.assertFalse(layout.audit_dependencies(self.project, self.plan, "sunset", [transient])["ok"])

    def test_external_baseline_requires_explicit_read_only_root(self):
        external = Path(self.tmp.name) / "baseline"
        external.mkdir()
        scene = external / "base.tscn"
        scene.write_text("[gd_scene]")
        self.assertFalse(layout.audit_dependencies(self.project, self.plan, "sunset", [scene])["ok"])
        result = layout.audit_dependencies(self.project, self.plan, "sunset", [scene], source_role="baseline", dependency_roots=[external])
        self.assertTrue(result["ok"])
        self.assertTrue(result["dependencies"][0]["ownership"]["read_only"])

    def test_record_artifact_keeps_supplier_in_provenance_not_directory(self):
        path = layout.asset_path(self.project, self.plan, "palm")
        path.parent.mkdir(parents=True)
        path.write_bytes(b"model")
        row = layout.record_artifact(self.project, self.plan, path, "asset", "sunset", "palm",
                                     {"provider": "lux3d"}, write_manifest=True)
        self.assertEqual(row["provenance"]["provider"], "lux3d")
        self.assertEqual(core.read(path.parent / "asset.json")["ownership"]["style_id"], "sunset")

    def test_nonasset_ownership_is_durable_without_capturing_command_stdout(self):
        source = self.file("art/hole/styles/sunset/design/spatial-recipe.json", "{\"schema\":1}")
        layout.record_artifact(self.project, self.plan, source["path"], "design", style_id="sunset")
        index = core.read(self.project / "art/hole/index.json")
        row = index["artifacts"][source["path"]]
        self.assertEqual(row["case_id"], "hole")
        self.assertEqual(row["style_id"], "sunset")
        self.assertEqual(row["role"], "design")
        self.assertEqual(row["sha256"], source["sha256"])
        style = core.read(self.project / "art/hole/styles/sunset/style.json")
        self.assertEqual(style["artifacts"], [row])

    def test_registration_preserves_other_styles_in_partial_plan(self):
        layout.register(self.project, self.plan)
        partial = copy.deepcopy(self.plan)
        partial["styles"] = [partial["styles"][0]]
        layout.register(self.project, partial)
        nav = layout.read_navigation(self.project, partial)["navigation"]
        self.assertEqual(set(nav["styles"]), {"sunset", "paper"})
        self.assertTrue((self.project / "art/hole/README.md").is_file())

    def test_unindexed_case_metadata_collision_preserves_unmanaged_content(self):
        for relative in ("art/hole/README.md", "art/hole/styles/sunset/style.json"):
            with self.subTest(path=relative):
                existing = self.file(relative, "unique unmanaged documentation")
                before = Path(existing["path"]).read_bytes()
                with self.assertRaisesRegex(core.WorkflowError, "inventory before migration"):
                    layout.register(self.project, self.plan)
                self.assertEqual(Path(existing["path"]).read_bytes(), before)
                self.assertFalse((self.project / "art/hole/index.json").exists())
                Path(existing["path"]).unlink()

    def test_existing_managed_case_cannot_overwrite_unowned_style_metadata(self):
        layout.register(self.project, self.plan)
        path = self.project / "art/hole/styles/sunset/style.json"
        path.write_text('{"kind":"other-project","case_id":"not-hole"}')
        before = path.read_bytes()
        with self.assertRaisesRegex(core.WorkflowError, "not owned navigation"):
            layout.register(self.project, self.plan)
        self.assertEqual(path.read_bytes(), before)

    def test_corrupt_existing_index_cannot_escape_ownership(self):
        layout.register(self.project, self.plan)
        p = self.project / "art/hole/index.json"
        value = core.read(p)
        value["styles"]["../escape"] = value["styles"].pop("paper")
        core.write(p, value)
        with self.assertRaises(core.WorkflowError):
            layout.register(self.project, self.plan)

    def test_three_pointers_stay_distinct_and_old_acceptance_is_not_latest(self):
        scene = self.scene("a")
        layout.update_pointer(self.project, self.plan, "sunset", "development", scene["path"], [scene], self.plan_hash)
        layout.update_pointer(self.project, self.plan, "sunset", "last_verified", scene["path"], [scene], self.plan_hash, self.native_proof([scene]))
        layout.update_pointer(self.project, self.plan, "sunset", "user_accepted", scene["path"], [scene], self.plan_hash, self.acceptance(scene))
        newer = self.scene("b")
        layout.update_pointer(self.project, self.plan, "sunset", "development", newer["path"], [newer], self.plan_hash)
        nav = layout.read_navigation(self.project, self.plan)["navigation"]["styles"]["sunset"]
        self.assertFalse(nav["pointers"]["user_accepted"]["matches_development"])
        self.assertTrue(nav["pointers"]["user_accepted"]["health"]["current"])
        self.assertEqual(len(nav["pointer_history"]), 1)

    def test_repeated_pointer_does_not_create_history_noise(self):
        scene = self.scene()
        for _ in range(2):
            layout.update_pointer(self.project, self.plan, "sunset", "development", scene["path"], [scene], self.plan_hash)
        nav = layout.read_navigation(self.project, self.plan)["navigation"]["styles"]["sunset"]
        self.assertEqual(nav["pointer_history"], [])

    def test_verified_evidence_extras_do_not_hide_same_development_version(self):
        scene = self.scene("first")
        evidence = self.file("art/hole/shared/production/runs/test/evidence/report.json", "passed")
        layout.update_pointer(self.project, self.plan, "sunset", "development", scene["path"], [scene], self.plan_hash)
        layout.update_pointer(self.project, self.plan, "sunset", "last_verified", scene["path"], [scene, evidence],
                              self.plan_hash, self.native_proof([scene, evidence]))
        nav = layout.read_navigation(self.project, self.plan)["navigation"]["styles"]["sunset"]
        self.assertTrue(nav["pointers"]["last_verified"]["matches_development"])
        newer = self.scene("second")
        layout.update_pointer(self.project, self.plan, "sunset", "development", newer["path"], [newer], self.plan_hash)
        nav = layout.read_navigation(self.project, self.plan)["navigation"]["styles"]["sunset"]
        self.assertFalse(nav["pointers"]["last_verified"]["matches_development"])

    def test_changed_runtime_marks_verified_pointer_stale(self):
        scene = self.scene()
        layout.update_pointer(self.project, self.plan, "sunset", "last_verified", scene["path"], [scene], self.plan_hash, self.native_proof([scene]))
        Path(scene["path"]).write_text("changed")
        pointer = layout.read_navigation(self.project, self.plan)["navigation"]["styles"]["sunset"]["pointers"]["last_verified"]
        self.assertFalse(pointer["health"]["current"])

    def test_verified_pointer_requires_exact_proof_snapshot(self):
        scene = self.scene()
        proof = self.native_proof([])
        with self.assertRaisesRegex(core.WorkflowError, "complete reviewed"):
            layout.update_pointer(self.project, self.plan, "sunset", "last_verified", scene["path"], [scene], self.plan_hash, proof)

    def test_proof_file_drift_marks_pointer_stale(self):
        scene = self.scene()
        proof = self.native_proof([scene])
        layout.update_pointer(self.project, self.plan, "sunset", "last_verified", scene["path"], [scene], self.plan_hash, proof)
        core.write(proof["path"], {"passed": False})
        pointer = layout.read_navigation(self.project, self.plan)["navigation"]["styles"]["sunset"]["pointers"]["last_verified"]
        self.assertFalse(pointer["health"]["current"])

    def test_navigation_cannot_turn_agent_note_into_human_acceptance(self):
        scene = self.scene()
        proof = self.proof({"actor": "agent", "decision": "accepted", "passed": True})
        with self.assertRaisesRegex(core.WorkflowError, "existing exact H5"):
            layout.update_pointer(self.project, self.plan, "sunset", "user_accepted", scene["path"], [scene], self.plan_hash, proof)

    def test_h5_pointer_rejects_another_entry_or_unreviewed_bytes(self):
        scene = self.scene("a")
        proof = self.acceptance(scene)
        newer = self.scene("b")
        with self.assertRaisesRegex(core.WorkflowError, "this style/entry"):
            layout.update_pointer(self.project, self.plan, "sunset", "user_accepted", newer["path"], [newer], self.plan_hash, proof)

    def test_h5_pointer_binds_native_reports_and_detects_report_drift(self):
        scene = self.scene()
        report = self.file("art/hole/shared/production/runs/test/evidence/native.log", "native test passed")
        proof = self.acceptance(scene)
        receipt = core.read(proof["path"])
        receipt["manifest"]["styles"][0]["native_reports"] = [report]
        receipt["manifestHash"] = core.digest(receipt["manifest"])
        core.write(proof["path"], receipt)
        proof["sha256"] = core.file_hash(proof["path"])
        with self.assertRaisesRegex(core.WorkflowError, "differ from"):
            layout.update_pointer(self.project, self.plan, "sunset", "user_accepted", scene["path"], [scene], self.plan_hash, proof)
        layout.update_pointer(self.project, self.plan, "sunset", "user_accepted", scene["path"], [scene, report], self.plan_hash, proof)
        Path(report["path"]).write_text("native log changed")
        pointer = layout.read_navigation(self.project, self.plan)["navigation"]["styles"]["sunset"]["pointers"]["user_accepted"]
        self.assertFalse(pointer["health"]["current"])

    def test_inventory_does_not_modify_or_follow_existing_archive(self):
        item = self.file("art/experiments/old/model.glb", "unique old data")
        before = sorted(str(p.relative_to(self.project)) for p in self.project.rglob("*"))
        inventory = layout.inventory(self.project)
        self.assertEqual(inventory["mode"], "inventory_only")
        self.assertEqual(inventory["files"][0]["sha256"], item["sha256"])
        self.assertEqual(before, sorted(str(p.relative_to(self.project)) for p in self.project.rglob("*")))

    def test_rollback_withdraws_only_owned_development_and_preserves_accepted_history(self):
        scene = self.scene()
        run_dir = layout.run_root(self.project, self.plan, "rolled")
        proof = self.proof({"run_dir": str(run_dir), "synthetic_test_only": True}, "development.json")
        layout.update_pointer(self.project, self.plan, "sunset", "development", scene["path"], [scene], self.plan_hash, proof)
        layout.update_pointer(self.project, self.plan, "sunset", "last_verified", scene["path"], [scene], self.plan_hash, self.native_proof([scene]))
        layout.update_pointer(self.project, self.plan, "sunset", "user_accepted", scene["path"], [scene], self.plan_hash, self.acceptance(scene))
        before = layout.read_navigation(self.project, self.plan)["navigation"]["styles"]["sunset"]
        result = layout.rollback_development(self.project, self.plan, run_dir)
        self.assertEqual(result["cleared"], ["sunset"])
        after = layout.read_navigation(self.project, self.plan)["navigation"]["styles"]["sunset"]
        self.assertNotIn("development", after["pointers"])
        self.assertEqual(after["pointers"]["last_verified"]["snapshot_hash"], before["pointers"]["last_verified"]["snapshot_hash"])
        self.assertEqual(after["pointers"]["user_accepted"]["snapshot_hash"], before["pointers"]["user_accepted"]["snapshot_hash"])
        self.assertEqual(after["pointer_history"][-1]["reason"], "rollback")
        self.assertTrue(Path(scene["path"]).is_file())

    def test_rollback_preserves_newer_run_pointer_even_with_identical_entry(self):
        scene = self.scene()
        old = layout.run_root(self.project, self.plan, "old")
        newer = layout.run_root(self.project, self.plan, "newer")
        for name, run in (("old-development.json", old), ("new-development.json", newer)):
            proof = self.proof({"run_dir": str(run)}, name)
            layout.update_pointer(self.project, self.plan, "sunset", "development", scene["path"], [scene], self.plan_hash, proof)
        result = layout.rollback_development(self.project, self.plan, old)
        self.assertEqual(result["cleared"], [])
        pointer = layout.read_navigation(self.project, self.plan)["navigation"]["styles"]["sunset"]["pointers"]["development"]
        self.assertEqual(core.read(pointer["proof"]["path"])["run_dir"], str(newer))


if __name__ == "__main__":
    unittest.main()
