"""Production control is exercised with tiny local fixtures; no cloud or engine."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] / "skills/greybox-to-multistyle-art"
sys.path.insert(0, str(ROOT / "runtime"))
from greybox import core, production_control as pc
from workflow_fixtures import png


class ProductionControlTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        self.plan = {"styles": [{"id": "first"}, {"id": "later"}], "assets": [],
            "workspace": {"schema": 1, "case_id": "case", "root": "art/case", "engine": "godot", "asset_owners": {}}}
        self.workflow = self.project / "workflow.json"
        core.write(self.workflow, {"selected_styles": ["first", "later"], "stages": []})
        self.path = pc.control_path(self.project, self.plan)
        pc.initialize(self.project, self.plan, self.workflow)

    def configure(self, assets=("a", "b"), pilot=("a",), interactions=()):
        data = core.read(self.path)
        families = {"family": {"profile": {"structure": "solid", "method": "preserve mesh", "skeleton": "none", "engine": "godot"},
            "asset_ids": list(assets), "pilot_asset_ids": list(pilot), "required_interactions": list(interactions), "runtime_profile": None}}
        combos = {"view": {"style_id": "first", "asset_ids": list(assets), "required_interactions": list(interactions), "state": "queued"}}
        pc.configure(self.project, self.path, {"families": families, "combinations": combos}, data["revision"])

    def evidence(self, name, value):
        p = self.project / name
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(value, bytes): p.write_bytes(value)
        else: core.write(p, value)
        return {"path": str(p), "sha256": core.file_hash(p)}

    def native(self, assets=("a",), interactions=(), visible=True, continuous=False, **extra):
        source = {a: self.evidence(a + ".glb", b"synthetic-local-not-a-model") for a in assets}
        media = [{**self.evidence("native-" + str(i) + ".png", png(i)), "camera_id": "main",
                  **({"sequence_id": "play", "time_seconds": i * .1} if continuous else {})}
                 for i in range(3 if continuous else 1)]
        report = {"schema": 1, "kind": "native-composition-check", "engine": "godot", "passed": True,
                  "reviewer": "synthetic-reviewer", "source_ref": "synthetic://not-a-real-review", "camera_id": "main",
                  "checks": {"imports": True, "materials": True, "scale": True, "visibility": visible,
                             "interaction_continuity": True}, "assets": source, "covered_interactions": list(interactions),
                  "media": media, **extra}
        if continuous:
            report["continuous_sequence"] = {"id": "play", "from_seconds": 0, "to_seconds": .2, "max_gap_seconds": .11}
        return self.evidence("report.json", report)

    def submit(self, asset, run="run-1", operation="image_to_3d", request="1" * 64):
        return pc.guard_submission(self.project, self.plan, asset, operation, self.project / run, request)

    def test_missing_and_unfinished_control_need_explicit_configuration(self):
        with self.assertRaisesRegex(ValueError, "unfinished"):
            pc.ensure_prepared(self.project, self.plan)
        self.path.unlink()
        with self.assertRaisesRegex(ValueError, "scripts/production_control.py init"):
            pc.ensure_prepared(self.project, self.plan)

    def test_first_style_only_and_reuse_cannot_bypass_it(self):
        self.configure()
        self.assertEqual(pc.assess(self.project, self.path)["active_styles"], ["first"])
        pc.guard_style(self.project, self.plan, "first")
        with self.assertRaisesRegex(ValueError, "queued"):
            pc.guard_style(self.project, self.plan, "later")
        before = self.workflow.read_bytes()
        with self.assertRaises(ValueError):
            pc.activate_styles(self.project, self.path, ["later"])
        self.assertEqual(self.workflow.read_bytes(), before)

    def test_current_combination_can_finish_eight_assets_but_second_waits(self):
        assets = ["a" + str(i) for i in range(8)]
        self.configure(assets + ["next"], assets + ["next"])
        data = core.read(self.path)
        data["combinations"]["view"]["asset_ids"] = assets
        data["combinations"]["next-view"] = {"style_id": "first", "asset_ids": ["next"], "required_interactions": [], "state": "queued"}
        core.write(self.path, data)
        for asset in assets: self.submit(asset)
        with self.assertRaisesRegex(ValueError, "backlog"):
            self.submit("next")
        pc.integrate(self.project, self.path, "view", self.native(assets))
        self.submit("next")

    def test_family_pilot_reusable_only_after_actual_bound_native_evidence(self):
        self.configure()
        self.submit("a")
        with self.assertRaisesRegex(ValueError, "pilot"):
            self.submit("b")
        pc.qualify(self.project, self.path, "family", self.native())
        self.submit("b")
        (self.project / "a.glb").write_bytes(b"changed")
        self.assertIn("family", pc.assess(self.project, self.path)["qualification_errors"])

    def test_changed_processing_profile_cannot_reuse_old_qualification(self):
        self.configure()
        pc.qualify(self.project, self.path, "family", self.native())
        data = core.read(self.path)
        families = data["families"]
        families["family"]["profile"]["skeleton"] = "different-rig"
        with self.assertRaisesRegex(ValueError, "fresh qualification"):
            pc.configure(self.project, self.path, {"families": families}, data["revision"])

    def test_numeric_contact_does_not_replace_visibility_or_continuity(self):
        self.configure(interactions=["wipe"])
        with self.assertRaisesRegex(ValueError, "visibility"):
            pc.qualify(self.project, self.path, "family", self.native(interactions=["wipe"], visible=False))
        with self.assertRaisesRegex(ValueError, "continuous"):
            pc.qualify(self.project, self.path, "family", self.native(interactions=["wipe"]))
        result = pc.qualify(self.project, self.path, "family", self.native(interactions=["wipe"], continuous=True))
        self.assertEqual(result["qualified_families"], ["family"])

    def test_cross_run_claim_and_unknown_outcome_cannot_reset_identity(self):
        self.configure()
        first = self.submit("a")
        self.assertEqual(self.submit("a")["claim_id"], first["claim_id"])
        with self.assertRaisesRegex(ValueError, "another attempt"):
            self.submit("a", "run-2")
        self.assertEqual(len(core.read(self.path)["claims"]), 1)

    def test_terminal_failed_claim_releases_only_original_attempt(self):
        self.configure()
        request = core.digest({"operation": "image_to_3d", "parameters": {"quality": 1}})
        first = self.submit("a", request=request)
        directory = self.project / "run-1"; directory.mkdir()
        value = {"kind": "greybox-art-run", "assets": {"a": {"state": "unknown", "operation": "image_to_3d", "parameters": {"quality": 1}}}}
        ref = self.evidence("run-1/run.json", value)
        with self.assertRaisesRegex(ValueError, "Unknown/inflight"):
            pc.reconcile_claim(self.project, self.path, first["claim_id"], ref, "inspect")
        value["assets"]["a"]["state"] = "failed"
        ref = self.evidence("run-1/run.json", value)
        pc.reconcile_claim(self.project, self.path, first["claim_id"], ref, "confirmed original failure")
        self.submit("a", "run-2", request="2" * 64)
        self.assertEqual(len(core.read(self.path)["claims"][first["claim_id"]]["history"]), 1)

    def test_repair_budget_accumulates_across_scripts_agents_and_issue_aliases(self):
        self.configure()
        pc.open_repair(self.project, self.path, "uv", ["a"], "UV tearing", max_attempts=2, max_active_minutes=30)
        for i in range(2):
            pc.begin_repair(self.project, self.path, "uv", "script-" + str(i), "agent-" + str(i))
            pc.finish_repair(self.project, self.path, "uv", 10, self.evidence("attempt-" + str(i) + ".json", {"not_fixed": True}), "still tears")
        with self.assertRaisesRegex(ValueError, "exhausted"):
            pc.begin_repair(self.project, self.path, "uv", "new-script", "new-agent")
        with self.assertRaisesRegex(ValueError, "Same defect"):
            pc.open_repair(self.project, self.path, "renamed", ["a"], "uv tearing")
        with self.assertRaisesRegex(ValueError, "repair limit"):
            self.submit("a")
        pc.resolve_repair(self.project, self.path, "uv", "verified_fallback", "preserve original geometry", self.native())
        self.submit("a")
        self.assertEqual(len(core.read(self.path)["repairs"]["uv"]["attempts"]), 2)

    def test_pure_reuse_can_start_and_integrate_without_generation(self):
        self.configure(assets=["a"], pilot=["a"])
        pc.start_combination(self.project, self.path, "view")
        pc.integrate(self.project, self.path, "view", self.native())
        result = pc.assess(self.project, self.path)
        self.assertEqual(result["claims"], 0)
        self.assertEqual(result["integration_backlog"], 0)

    def test_configuration_cas_preserves_concurrent_history(self):
        self.configure()
        revision = core.read(self.path)["revision"]
        self.submit("a")
        with self.assertRaisesRegex(ValueError, "changed"):
            pc.configure(self.project, self.path, {"max_open_combinations": 2}, revision)

    def test_inflight_repair_allows_only_its_explicit_submission(self):
        self.configure()
        pc.open_repair(self.project, self.path, "fix", ["a"], "native artifact", max_attempts=2)
        identity = {"asset_id": "a", "operation": "image_to_3d", "run_dir": str(self.project / "run-1"), "request_digest": "1" * 64}
        pc.begin_repair(self.project, self.path, "fix", "provider repair", "worker", submission=identity)
        with self.assertRaisesRegex(ValueError, "repair limit"):
            self.submit("a", "wrong-run")
        self.submit("a")
        self.assertIn("inflight", core.read(self.path)["repairs"]["fix"])

    def test_local_inflight_repair_is_visible_to_focus_and_blocks_repetition(self):
        self.configure()
        pc.open_repair(self.project, self.path, "fix", ["a"], "local defect")
        pc.begin_repair(self.project, self.path, "fix", "local adjustment", "worker")
        self.assertEqual(pc.assess(self.project, self.path)["repair_blockers"]["a"], ["fix"])
        with self.assertRaisesRegex(ValueError, "repair limit"):
            self.submit("a")

    def test_ready_but_visually_failed_output_has_bounded_repair_path(self):
        self.configure()
        request = core.digest({"operation": "image_to_3d", "parameters": {"quality": 1}})
        first = self.submit("a", request=request)
        rejected = self.native(visible=False)
        report = core.read(rejected["path"]); report["passed"] = False
        rejected = self.evidence("report.json", report)
        ledger = {"kind": "greybox-art-run", "assets": {"a": {"state": "ready", "operation": "image_to_3d",
                  "parameters": {"quality": 1}, "artifact": report["assets"]["a"]}}}
        original = self.evidence("run-1/run.json", ledger)
        pc.open_repair(self.project, self.path, "visible", ["a"], "unreadable silhouette", max_attempts=1)
        pc.reconcile_claim(self.project, self.path, first["claim_id"], original, "native visual failure", repair_issue="visible", quality_evidence=rejected)
        with self.assertRaisesRegex(ValueError, "bounded repair"):
            self.submit("a", "run-2", request="2" * 64)
        identity = {"asset_id": "a", "operation": "image_to_3d", "run_dir": str(self.project / "run-2"), "request_digest": "2" * 64}
        pc.begin_repair(self.project, self.path, "visible", "preserve UV", "worker-two", submission=identity)
        self.submit("a", "run-2", request="2" * 64)
        self.assertEqual(len(core.read(self.path)["claims"][first["claim_id"]]["history"]), 1)

    def test_runtime_profile_requires_matching_engine_target_and_per_asset_targets(self):
        self.configure(assets=["a", "b"], pilot=["a", "b"])
        profile = {"schema": 1, "kind": "runtime-profile", "engine": "godot", "target": "desktop",
                   "budgets": [{"id": "a-triangles", "metric": "triangles", "classification": "target", "limit": 3000,
                       "unit": "triangles", "source_ref": "synthetic://target", "asset_ids": ["a"]},
                      {"id": "b-triangles", "metric": "triangles", "classification": "hard", "limit": 5000,
                       "unit": "triangles", "source_ref": "synthetic://target", "asset_ids": ["b"]}]}
        ref = self.evidence("profile.json", profile)
        data = core.read(self.path); data["families"]["family"]["runtime_profile"] = ref
        core.write(self.path, data)
        targets = {"a": [{"budget_id": "a-triangles", "value": 3000}], "b": [{"budget_id": "b-triangles", "value": 5000}]}
        with self.assertRaisesRegex(ValueError, "target environment"):
            pc.qualify(self.project, self.path, "family", self.native(["a", "b"], runtime_target="mobile", targets_by_asset=targets))
        with self.assertRaisesRegex(ValueError, "targets_by_asset"):
            pc.qualify(self.project, self.path, "family", self.native(["a", "b"], runtime_target="desktop", targets=targets["a"]))
        pc.qualify(self.project, self.path, "family", self.native(["a", "b"], runtime_target="desktop", targets_by_asset=targets))
        data = core.read(self.path); data["families"]["family"]["profile"]["engine"] = "unity"
        core.write(self.path, data)
        with self.assertRaisesRegex(ValueError, "engines differ"):
            pc.assess(self.project, self.path)

    def test_old_lead_h4_cannot_unlock_a_changed_baseline_or_selection(self):
        self.configure()
        stages = [{"id": s, "scope": "shared", "revision": 1, "evidence": []} for s in ("baseline", "directions", "selection")]
        core.write(self.workflow, {"selected_styles": ["first", "later"], "stages": stages})
        old = copy.deepcopy(stages)
        old[0]["revision"] = 2
        archive = self.project / "old-workflow.json"
        core.write(archive, {"selected_styles": ["first", "later"], "stages": old})
        with self.assertRaisesRegex(ValueError, "different baseline"):
            pc.activate_styles(self.project, self.path, ["later"], workflow_path=archive)

    def test_exhausted_repair_cannot_bypass_with_pure_reuse_assembly(self):
        self.configure()
        self.plan["bindings"] = [{"source": {"asset_id": "a"}}]
        pc.open_repair(self.project, self.path, "fix", ["a"], "bad UV", max_attempts=1)
        pc.begin_repair(self.project, self.path, "fix", "native inspection", "worker")
        pc.guard_style(self.project, self.plan, "first")
        pc.finish_repair(self.project, self.path, "fix", 10, self.evidence("still-bad.json", {"bad": True}), "still bad")
        with self.assertRaisesRegex(ValueError, "exhausted/deferred"):
            pc.guard_style(self.project, self.plan, "first")

    def test_actual_supplier_recovery_is_not_blocked_by_missing_control(self):
        import test_supplier_jobs_r3 as supplier_fixture
        from greybox import supplier_jobs
        f = supplier_fixture.SupplierJobTests("test_submit_reservation_is_persisted_before_any_command")
        f.setUp()
        try:
            f.prepare(); f.advance(max_submissions=1)
            pc.control_path(f.project, f.portfolio).unlink()
            f.adapter.calls.clear()
            f.advance(max_submissions=3)
            self.assertIn(("hero-model", "status"), f.adapter.calls)
            self.assertFalse(any(method == "submit" for _, method in f.adapter.calls))
        finally:
            f.tearDown()

    def test_legacy_claim_rejection_releases_only_the_unsubmitted_control_claim(self):
        import test_supplier_jobs_r3 as supplier_fixture
        from greybox import supplier_jobs
        f = supplier_fixture.SupplierJobTests("test_submit_reservation_is_persisted_before_any_command")
        f.setUp()
        try:
            f.prepare()
            state = core.read(f.run / "supplier-run.json")
            operation = f.portfolio["options"][0]["operations"][0]
            legacy = supplier_jobs._guard_paths(state, operation)[0]
            core.write(legacy, {"phase": "unknown", "claim_path": "original-unknown-run"})
            result = f.advance(max_submissions=1)
            self.assertEqual(result["operations"]["hero-model"]["state"], "blocked_duplicate")
            control = core.read(pc.control_path(f.project, f.portfolio))
            claim = control["claims"][core.digest(["supplier-case", "hero", "image_to_3d"])]
            self.assertEqual(claim["terminal_state"], "not_submitted")
            self.assertEqual(core.read(legacy)["phase"], "unknown")
            self.assertNotIn(("hero-model", "submit"), f.adapter.calls)
        finally:
            f.tearDown()


if __name__ == "__main__":
    unittest.main()
