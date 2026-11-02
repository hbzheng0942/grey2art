"""Directory ownership and recovery tests; synthetic H3 and local files only."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1] / "skills/greybox-to-multistyle-art"
sys.path.insert(0, str(ROOT / "runtime"))
from greybox import core, supplier_jobs
import test_supplier_jobs_r3 as prior


class SupplierLayoutR33(unittest.TestCase):
    def setUp(self):
        self.f = prior.SupplierJobTests("test_submit_reservation_is_persisted_before_any_command")
        self.f.setUp()
        self.addCleanup(self.f.tearDown)
        f = self.f
        f.portfolio["workspace"] = {"schema": 1, "case_id": "supplier-case", "root": "art/supplier-case",
            "engine": "godot", "shared_asset_ids": [], "asset_owners": {
                "hero": {"scope": "style", "style_id": "ceramic"},
                "environment": {"scope": "style", "style_id": "orbital"}}}
        f.run = f.project / "art/supplier-case/shared/production/runs/production-one"
        for op in f.portfolio["options"][0]["operations"]:
            sid = f.portfolio["workspace"]["asset_owners"][op["asset_id"]]["style_id"]
            filename = "rigged.glb" if op["operation"] == "rig" else "model.glb"
            op["publish"] = {"path": f"art/supplier-case/styles/{sid}/assets/{op['asset_id']}/{filename}"}
        f.rebind_portfolio()

    def prepare(self):
        # The unchanged R3.2 fixture tests actual H1/H2/H3 elsewhere. This isolates
        # ownership/publication using a synthetic approved supplier portfolio.
        with patch.object(supplier_jobs, "_gate", return_value={"ok": True}):
            return self.f.prepare()

    def test_new_supplier_prepare_requires_a_workspace_contract(self):
        self.f.portfolio.pop("workspace")
        self.f.rebind_portfolio()
        with self.assertRaisesRegex(core.WorkflowError, "approved workspace"):
            self.prepare()
        self.assertFalse((self.f.run / "supplier-run.json").exists())

    def test_optional_rig_check_report_is_evidence_and_needs_no_fake_glb_publish(self):
        option = deepcopy(self.f.portfolio["options"][0])
        operation = option["operations"][0]
        operation["operation"] = "rig_check"
        operation.pop("publish")
        supplier_jobs._validate_publish_paths(option, self.f.project, self.f.portfolio)

    def test_recorded_historical_task_recovers_but_cannot_start_pending_jobs(self):
        f = self.f
        self.prepare()
        with patch.object(supplier_jobs, "_gate", return_value={"ok": True}):
            f.advance(max_submissions=1)
        # Construct a synthetic historical ledger, preserving its accepted ID.
        # It is test data, not migration of an actual frozen production record.
        f.portfolio.pop("workspace")
        f.selection["portfolio_sha256"] = core.digest(f.portfolio)
        state = core.read(f.run / "supplier-run.json")
        state.pop("workspace")
        state["portfolio_digest"] = core.digest(f.portfolio)
        state["selection_digest"] = core.digest(f.selection)
        core.write(f.run / "supplier-portfolio.json", f.portfolio)
        core.write(f.run / "supplier-selection.json", f.selection)
        core.write(f.run / "supplier-run.json", state)
        f.adapter.done.add("hero-model")
        with patch.object(supplier_jobs, "_gate", return_value={"ok": True}):
            result = f.advance(max_submissions=16)
        self.assertEqual(result["operations"]["hero-model"]["state"], "ready")
        self.assertEqual(result["operations"]["hero-model"]["task_id"], "original-hero-model")
        self.assertEqual(result["operations"]["environment-model"]["state"], "pending")
        self.assertEqual(f.adapter.calls.count(("hero-model", "submit")), 1)
        self.assertNotIn(("environment-model", "submit"), f.adapter.calls)

    def test_mixed_batch_uses_case_shared_production_run_and_registers_identity(self):
        self.prepare()
        state = core.read(self.f.run / "supplier-run.json")
        self.assertEqual(state["workspace"]["case_id"], "supplier-case")
        self.assertEqual(state["run_id"], "production-one")
        index = core.read(self.f.project / "art/supplier-case/index.json")
        self.assertIn("shared/production-one", index["production_runs"])
        self.assertNotIn("subscription_key", str(index["production_runs"]))

    def test_workspace_run_cannot_escape_to_legacy_experiments(self):
        self.f.run = self.f.project / "art/experiments/new-workspace-run"
        with self.assertRaisesRegex(core.WorkflowError, "production/runs"):
            self.prepare()
        self.assertFalse((self.f.run / "supplier-run.json").exists())

    def test_mixed_style_portfolio_cannot_hide_in_one_style_run(self):
        self.f.run = self.f.project / "art/supplier-case/styles/ceramic/production/runs/mixed"
        with self.assertRaisesRegex(core.WorkflowError, "production/runs"):
            self.prepare()

    def test_single_style_portfolio_can_use_its_style_production_run(self):
        f = self.f
        f.portfolio["required_assets"] = ["hero"]
        f.portfolio["required_operations"] = {"hero": ["image_to_3d", "rig"]}
        option = f.portfolio["options"][0]
        option["assets"] = [a for a in option["assets"] if a["asset_id"] == "hero"]
        option["operations"] = [o for o in option["operations"] if o["asset_id"] == "hero"]
        f.run = f.project / "art/supplier-case/styles/ceramic/production/runs/style-one"
        f.rebind_portfolio()
        self.prepare()
        self.assertTrue((f.run / "supplier-run.json").is_file())

    def test_workspace_requires_explicit_asset_owner_before_creation_or_spend(self):
        del self.f.portfolio["workspace"]["asset_owners"]["hero"]
        self.f.rebind_portfolio()
        with self.assertRaisesRegex(core.WorkflowError, "asset_owners"):
            self.prepare()
        self.assertFalse(self.f.adapter.calls)

    def test_publish_cannot_cross_style_or_use_a_supplier_named_asset_folder(self):
        f = self.f
        operation = f.portfolio["options"][0]["operations"][0]
        for bad in ("art/supplier-case/styles/orbital/assets/hero/model.glb",
                    "art/supplier-case/styles/ceramic/assets/lux3d/model.glb",
                    "art/supplier-case/shared/assets/hero/model.glb"):
            with self.subTest(path=bad):
                operation["publish"]["path"] = bad
                f.rebind_portfolio()
                with self.assertRaises(core.WorkflowError):
                    self.prepare()
                self.assertFalse((f.run / "supplier-run.json").exists())

    def test_a_shared_model_needs_explicit_shared_asset_registration(self):
        f = self.f
        f.portfolio["workspace"]["asset_owners"]["hero"] = {"scope": "shared"}
        f.rebind_portfolio()
        with self.assertRaisesRegex(core.WorkflowError, "shared_asset_ids"):
            self.prepare()
        f.portfolio["workspace"]["shared_asset_ids"] = ["hero"]
        for op in f.portfolio["options"][0]["operations"]:
            if op["asset_id"] == "hero":
                op["publish"]["path"] = "art/supplier-case/shared/assets/hero/" + ("rigged.glb" if op["operation"] == "rig" else "model.glb")
        f.rebind_portfolio()
        self.prepare()

    def test_every_new_generated_operation_declares_a_stable_publish_path(self):
        del self.f.portfolio["options"][0]["operations"][0]["publish"]
        self.f.rebind_portfolio()
        with self.assertRaisesRegex(core.WorkflowError, "stable publish path"):
            self.prepare()
        self.assertFalse(self.f.adapter.calls)

    def test_operation_cannot_override_the_h3_approved_asset_owner(self):
        self.f.portfolio["options"][0]["operations"][0]["ownership"] = {"scope": "style", "style_id": "orbital"}
        self.f.rebind_portfolio()
        with self.assertRaisesRegex(core.WorkflowError, "ownership conflicts"):
            self.prepare()

    def test_published_model_has_owner_and_vendor_provenance_without_copy(self):
        f = self.f
        operation = f.portfolio["options"][0]["operations"][0]
        source = f.project / "downloaded.glb"; source.write_bytes(b"synthetic-publication-file")
        inode, digest = source.stat().st_ino, core.file_hash(source)
        result = supplier_jobs._publish(operation, [{"path": str(source), "sha256": digest, "role": "model"}],
            f.project, f.portfolio, provenance={"task_id": "original-task", "run_id": "production-one"})
        target = Path(result[0]["path"])
        self.assertFalse(source.exists())
        self.assertEqual(target.stat().st_ino, inode)
        self.assertEqual(result[0]["ownership"], {"scope": "style", "style_id": "ceramic"})
        manifest = core.read(target.parent / "asset.json")
        rendered = str(manifest)
        for value in ("hero", "ceramic", "character-vendor", "original-task", digest):
            self.assertIn(value, rendered)
        self.assertNotIn("subscription_key", rendered)

    def test_unity_publication_obeys_assets_resource_mapping(self):
        f = self.f
        f.portfolio["workspace"]["engine"] = "unity"
        op = deepcopy(f.portfolio["options"][0]["operations"][0])
        op["publish"] = {"path": "Assets/Art/supplier-case/styles/ceramic/assets/hero/model.glb"}
        source = f.project / "unity-output.glb"; source.write_bytes(prior.synthetic_glb())
        result = supplier_jobs._publish(op, [{"path": str(source), "sha256": core.file_hash(source)}], f.project, f.portfolio)
        self.assertIn("/Assets/Art/supplier-case/styles/ceramic/assets/hero/", result[0]["path"])
        self.assertTrue(Path(result[0]["path"]).is_file())

    def test_animation_bundle_can_publish_multiple_distinct_approved_clip_paths(self):
        f = self.f
        op = deepcopy(f.portfolio["options"][0]["operations"][0])
        op["publish"] = {"path": "art/supplier-case/styles/ceramic/assets/hero/animations/walk.glb",
            "role": "animation", "animation_id": "walk", "additional": [{
                "path": "art/supplier-case/styles/ceramic/assets/hero/animations/run.glb",
                "role": "animation", "animation_id": "run"}]}
        artifacts = []
        for name in ("walk", "run"):
            path = f.project / (name + ".glb"); path.write_bytes(name.encode())
            artifacts.append({"path": str(path), "sha256": core.file_hash(path), "role": "animation", "animation_id": name})
        result = supplier_jobs._publish(op, artifacts, f.project, f.portfolio)
        self.assertTrue(all(item["published"] for item in result))
        self.assertEqual({Path(item["path"]).name for item in result}, {"walk.glb", "run.glb"})
        manifest = core.read(Path(result[0]["path"]).parents[1] / "asset.json")
        self.assertIn("walk.glb", str(manifest)); self.assertIn("run.glb", str(manifest))

    def test_additional_publication_collision_does_not_move_any_source(self):
        f = self.f
        one = f.project / "one.glb"; one.write_bytes(b"one")
        two = f.project / "two.glb"; two.write_bytes(b"two")
        bad = f.project / "art/assets/existing.glb"; bad.parent.mkdir(parents=True); bad.write_bytes(b"prior")
        operation = {"publish": {"path": "art/assets/first.glb", "role": "model", "additional": [
            {"path": "art/assets/existing.glb", "role": "animation", "animation_id": "walk"}]}}
        artifacts = [{"path": str(one), "sha256": core.file_hash(one), "role": "model"},
                     {"path": str(two), "sha256": core.file_hash(two), "role": "animation", "animation_id": "walk"}]
        with self.assertRaisesRegex(core.WorkflowError, "overwrite"):
            supplier_jobs._publish(operation, artifacts, f.project)
        self.assertTrue(one.exists()); self.assertTrue(two.exists())
        self.assertFalse((f.project / "art/assets/first.glb").exists())

    def test_scoped_unknown_guards_allow_other_case_without_erasing_legacy_guard(self):
        f = self.f
        op = f.portfolio["options"][0]["operations"][0]
        state = {"project": str(f.project), "selection_digest": "a" * 64, "workspace": f.portfolio["workspace"]}
        claim = supplier_jobs._claim(state, f.run, op)
        supplier_jobs._guard_update(state, op, {"claim_path": claim}, "unknown")
        other = deepcopy(state); other["selection_digest"] = "b" * 64
        other["workspace"]["case_id"] = "another-case"
        supplier_jobs._claim(other, f.project / "art/another-case/shared/production/runs/next", op)
        legacy = {"project": str(f.project), "selection_digest": "c" * 64}
        legacy_claim = supplier_jobs._claim(legacy, f.project / "art/experiments/legacy", op)
        supplier_jobs._guard_update(legacy, op, {"claim_path": legacy_claim}, "unknown")
        third = deepcopy(other); third["selection_digest"] = "d" * 64; third["workspace"]["case_id"] = "third-case"
        with self.assertRaisesRegex(core.WorkflowError, "legacy run"):
            supplier_jobs._claim(third, f.project / "art/third-case/shared/production/runs/next", op)


if __name__ == "__main__":
    unittest.main()
