"""Case recovery/navigation tests; no engine, image or model call is made."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1] / "skills/greybox-to-multistyle-art"
sys.path.insert(0, str(ROOT / "runtime"))
from greybox import continuity, core


class ContinuityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="continuity-offline-")
        self.project = Path(self.temp.name)
        self.case = self.project / "art/continuity"
        self.workflow = {"schema": 2, "kind": "greybox-art-workflow", "selected_styles": ["a"],
                         "stages": [{"id": "baseline", "scope": "shared", "status": "draft", "evidence": []}]}
        core.write(self.project / "workflow.json", self.workflow)
        self.plan = {"case_id": "case-a", "writer": "integrator", "objective": "Two playable styles",
                     "current_stage": "shared/baseline", "status": "active", "constraints": ["Preserve collision"],
                     "quality_floor": ["Complete environment and hero in native sample"], "remaining": ["Baseline", "H1"],
                     "proposals": [], "references": {"workflow": "workflow.json", "ledgers": [], "approved_inputs": []}}
        self.event = {"type": "requirement", "summary": "Actual fixture task", "scope": "case",
                      "source_ref": "fixture-user-message-1", "evidence": []}
        continuity.initialize(self.project, self.case, self.plan, self.event)

    def tearDown(self):
        self.temp.cleanup()

    def token(self):
        return continuity.derive_focus(self.project, self.case)["resume_token"]

    def update(self, changes=None, event=None, revision=None, writer="integrator"):
        token = self.token()
        return continuity.update(self.project, self.case, writer, revision or token["plan_revision"],
                                 token["checkpoint_sha256"], event or self.event, changes)

    def test_questions_and_proposals_do_not_become_approval_or_change(self):
        before = (self.case / "PLAN.json").read_bytes()
        for text, kind in [("Meshy 会不会更好？", "inquiry"), ("建议改用 Meshy", "proposal"),
                           ("这批改 Meshy", "change"), ("补 BOM", "change"), ("继续", "continue"),
                           ("批准 H3 这批资产", "approval_candidate"), ("先暂停", "pause"),
                           ("Don't approve yet", "clarify")]:
            result = continuity.classify_message(text)
            self.assertEqual(result["category"], kind)
            self.assertFalse(result["approval_granted"])
            self.assertFalse(result["changes_plan"])
        self.assertEqual(before, (self.case / "PLAN.json").read_bytes())

    def test_interruption_and_new_process_restore_same_objective_proposals_and_gates(self):
        self.update({"proposals": ["Consider Meshy; not accepted"]}, {**self.event, "type": "proposal"})
        result = subprocess.run([sys.executable, str(ROOT / "scripts/progress.py"), "focus", "--project",
                                 str(self.project), "--case", "art/continuity"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        focus = json.loads(result.stdout)
        self.assertEqual(focus["objective"], "Two playable styles")
        self.assertEqual(focus["pending_proposals"], ["Consider Meshy; not accepted"])
        self.assertEqual(focus["current_stage"], "shared/baseline")
        self.assertFalse(focus["workflow_check"]["ok"])
        self.assertIn("spatial_contract", focus["missing_roles"])
        self.assertEqual(focus["resume_token"]["plan_revision"], 2)

    def test_old_revision_and_foreign_writer_cannot_overwrite(self):
        self.update({"remaining": ["New bounded task"]})
        with self.assertRaisesRegex(ValueError, "Stale plan revision"):
            self.update({"remaining": ["Old task"]}, revision=1)
        with self.assertRaisesRegex(ValueError, "designated plan writer"):
            self.update({"remaining": ["Other agent task"]}, writer="worker")
        self.assertEqual(core.read(self.case / "PLAN.json")["remaining"], ["New bounded task"])

    def test_checkpoint_or_plan_drift_invalidates_resume_token(self):
        token = self.token()
        self.workflow["stages"][0]["revision"] = 2
        core.write(self.project / "workflow.json", self.workflow)
        with self.assertRaisesRegex(ValueError, "Plan or workflow changed"):
            continuity.check_resume_token(self.project, self.case, token)
        with self.assertRaisesRegex(ValueError, "checkpoint changed"):
            continuity.update(self.project, self.case, "integrator", 1, token["checkpoint_sha256"], self.event)

    def test_journal_recovers_crash_between_append_and_plan_replace_once(self):
        real_write = core.write
        def fail_plan(path, value):
            if Path(path).name == "PLAN.json":
                raise OSError("simulated interrupted replace")
            return real_write(path, value)
        with patch.object(core, "write", side_effect=fail_plan):
            with self.assertRaises(OSError):
                self.update({"remaining": ["Revised after interruption"]})
        with self.assertRaisesRegex(ValueError, "Interrupted case update"):
            self.token()
        # The designated writer resumes its own journal; stale caller CAS then
        # fails instead of applying the same semantic change a second time.
        with self.assertRaisesRegex(ValueError, "Stale plan revision"):
            continuity.update(self.project, self.case, "integrator", 1,
                              core.file_hash(self.project / "workflow.json"), self.event)
        focus = continuity.derive_focus(self.project, self.case)
        self.assertEqual(focus["remaining"], ["Revised after interruption"])
        rows = (self.case / "PROGRESS.jsonl").read_text().splitlines()
        self.assertEqual(len(rows), 2)
        self.assertEqual([json.loads(r)["seq"] for r in rows], [1, 2])

    def test_journal_cannot_overwrite_unknown_manual_change(self):
        original_recover = continuity._recover
        def interrupt_commit(case):
            if (case / ".progress-transaction.json").exists():
                raise OSError("interrupt")
            return original_recover(case)
        with patch.object(continuity, "_recover", side_effect=interrupt_commit):
            with self.assertRaises(OSError):
                self.update({"remaining": ["Pending"]})
        current = core.read(self.case / "PLAN.json")
        current["remaining"] = ["External unique edit"]
        core.write(self.case / "PLAN.json", current)
        with self.assertRaisesRegex(ValueError, "Plan changed during interrupted"):
            continuity.update(self.project, self.case, "integrator", 1,
                              core.file_hash(self.project / "workflow.json"), self.event)
        self.assertEqual(core.read(self.case / "PLAN.json")["remaining"], ["External unique edit"])

    def test_two_concurrent_writers_cannot_lose_an_update(self):
        token = self.token()
        for name in ("one", "two"):
            core.write(self.project / (name + ".json"), {"event": self.event, "changes": {"remaining": [name]}})
        args = [sys.executable, str(ROOT / "scripts/progress.py"), "update", "--project", str(self.project),
                "--case", "art/continuity", "--writer", "integrator", "--expected-revision", "1",
                "--checkpoint-sha256", token["checkpoint_sha256"], "--input"]
        processes = [subprocess.Popen(args + [name + ".json"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                     for name in ("one", "two")]
        output = [p.communicate(timeout=10) for p in processes]
        self.assertEqual(sorted(p.returncode for p in processes), [0, 2], output)
        self.assertEqual(core.read(self.case / "PLAN.json")["revision"], 2)
        self.assertEqual(len((self.case / "PROGRESS.jsonl").read_text().splitlines()), 2)

    def test_focus_detects_stale_workflow_approval_without_copying_authority(self):
        from workflow_fixtures import make_workflow
        shutil.copytree(ROOT / "fixtures/godot-free", self.project, dirs_exist_ok=True)
        execution = core.read(self.project / "plan.json")
        execution.pop("purpose")
        path, data = make_workflow(self.project, execution)
        self.update({"references": {**self.plan["references"], "workflow": str(path)},
                     "current_stage": "ceramic/production_plan"})
        self.assertTrue(continuity.derive_focus(self.project, self.case)["workflow_check"]["ok"])
        stage = next(s for s in data["stages"] if s["id"] == "selection")
        stage["revision"] += 1
        core.write(path, data)
        focus = continuity.derive_focus(self.project, self.case)
        self.assertFalse(focus["workflow_check"]["ok"])
        self.assertIn("approval is stale", focus["workflow_check"]["error"])
        self.assertTrue(all(r["check"] == "source_reference_only_use_workflow_gate" for r in focus["authorization_refs"]))

    def test_focus_current_policy_reports_h3_boards_and_s6_capture_missing(self):
        from greybox import workflow
        self.workflow["production_policy"] = workflow.PRODUCTION_POLICY
        self.workflow["stages"] = [{"id": "production_plan", "scope": "a", "status": "draft",
                                    "evidence": [{"role": r} for r in workflow.ROLES["production_plan"]]},
                                   {"id": "art_proxy", "scope": "a", "status": "draft",
                                    "evidence": [{"role": r} for r in workflow.ROLES["art_proxy"]]}]
        core.write(self.project / "workflow.json", self.workflow)
        self.update({"current_stage": "a/production_plan"})
        focus = continuity.derive_focus(self.project, self.case)
        self.assertEqual(set(focus["missing_roles"]), {"bom_board", "assembly_map", "visual_package"})
        self.update({"current_stage": "a/art_proxy"})
        self.assertEqual(continuity.derive_focus(self.project, self.case)["missing_roles"], ["proxy_capture"])

    def test_focus_h4_cannot_report_h3_ready_as_sample_completion(self):
        from workflow_fixtures import make_workflow
        shutil.copytree(ROOT / "fixtures/godot-free", self.project, dirs_exist_ok=True)
        execution = core.read(self.project / "plan.json")
        execution.pop("purpose")
        path, _ = make_workflow(self.project, execution)
        self.update({"references": {**self.plan["references"], "workflow": str(path)},
                     "current_stage": "ceramic/representative_sample"})
        focus = continuity.derive_focus(self.project, self.case)
        self.assertFalse(focus["workflow_check"]["ok"])
        self.assertEqual(focus["workflow_check"]["inspection_scope"], "expansion")
        self.assertIn("representative_sample", focus["workflow_check"]["error"])
        self.assertIn("native_capture", focus["missing_roles"])

    def test_focus_lead_does_not_wait_for_queued_style_h2(self):
        from workflow_fixtures import make_workflow
        shutil.copytree(ROOT / "fixtures/godot-free", self.project, dirs_exist_ok=True)
        execution = core.read(self.project / "plan.json"); execution.pop("purpose")
        selected = [s["id"] for s in execution["styles"]]
        execution["styles"] = execution["styles"][:1]
        path, _ = make_workflow(self.project, execution, selected_styles=selected)
        self.update({"references": {**self.plan["references"], "workflow": str(path)},
                     "current_stage": selected[0] + "/production_plan"})
        focus = continuity.derive_focus(self.project, self.case)
        self.assertTrue(focus["workflow_check"]["ok"])
        self.assertEqual(focus["workflow_check"]["active_styles"], selected[:1])
        self.assertEqual(focus["queued_styles"], selected[1:])

    def test_focus_sibling_h4_does_not_force_current_style_expansion(self):
        from workflow_fixtures import make_workflow
        shutil.copytree(ROOT / "fixtures/godot-free", self.project, dirs_exist_ok=True)
        execution = core.read(self.project / "plan.json"); execution.pop("purpose")
        selected = [s["id"] for s in execution["styles"]]
        execution["styles"] = execution["styles"][1:]
        path, data = make_workflow(self.project, execution, selected_styles=selected)
        # Incomplete sibling data must not be inspected while recovering this branch.
        data["stages"].append({"id": "representative_sample", "scope": selected[0], "status": "accepted", "evidence": []})
        core.write(path, data)
        self.update({"references": {**self.plan["references"], "workflow": str(path)},
                     "current_stage": selected[1] + "/production_plan"})
        focus = continuity.derive_focus(self.project, self.case)
        self.assertTrue(focus["workflow_check"]["ok"])
        self.assertEqual(focus["workflow_check"]["style_phases"], {selected[1]: "representative"})

    def test_operational_phase_cannot_hide_current_h4_requirement(self):
        from workflow_fixtures import make_workflow
        from greybox import production_control
        shutil.copytree(ROOT / "fixtures/godot-free", self.project, dirs_exist_ok=True)
        execution = core.read(self.project / "plan.json"); execution.pop("purpose")
        execution["styles"] = execution["styles"][:1]
        path, _ = make_workflow(self.project, execution)
        control = production_control.control_path(self.project, execution)
        self.update({"references": {**self.plan["references"], "workflow": str(path), "production_control": str(control)},
                     "current_stage": "ceramic/representative_sample"})
        focus = continuity.derive_focus(self.project, self.case)
        self.assertEqual(focus["production_control"]["style_phases"]["ceramic"], "representative")
        self.assertEqual(focus["workflow_check"]["style_phases"]["ceramic"], "expansion")
        self.assertFalse(focus["workflow_check"]["ok"])
        self.assertIn("production_control_sha256", focus["resume_token"])

    def test_focus_reports_stale_plan_stage_without_rolling_back_active_control(self):
        from workflow_fixtures import make_workflow
        from greybox import production_control
        shutil.copytree(ROOT / "fixtures/godot-free", self.project, dirs_exist_ok=True)
        execution = core.read(self.project / "plan.json"); execution.pop("purpose")
        selected = [s["id"] for s in execution["styles"]]
        path, _ = make_workflow(self.project, execution, expansion=True)
        control = production_control.control_path(self.project, execution)
        production_control.activate_styles(self.project, control, selected[1:], workflow_path=path)
        before = control.read_bytes()
        self.update({"references": {**self.plan["references"], "workflow": str(path), "production_control": str(control)},
                     "current_stage": selected[0] + "/representative_sample"})
        focus = continuity.derive_focus(self.project, self.case)
        self.assertFalse(focus["stage_scope_matches_active"])
        self.assertEqual(focus["workflow_check"]["active_styles"], selected[1:])
        self.assertIn("update PLAN.current_stage", focus["next_action"])
        self.assertEqual(control.read_bytes(), before)

    def test_no_duplicate_approval_or_budget_ledger_allowed(self):
        for key in ("approval", "budget", "supplier_tasks"):
            with self.assertRaisesRegex(ValueError, "Unsupported plan changes"):
                self.update({key: {"approved": True}})

    def test_unknown_submission_survives_changed_plan_and_unrelated_proposal(self):
        core.write(self.project / "supplier-run.json", {"operations": {"hero": {"state": "unknown", "task_id": None}}})
        self.update({"references": {**self.plan["references"], "ledgers": ["supplier-run.json"]},
                     "proposals": ["Potential new provider"]}, {**self.event, "type": "proposal"})
        focus = continuity.derive_focus(self.project, self.case)
        self.assertEqual(focus["unknown_submissions"][0]["pointer"], "/operations/hero")
        self.assertIn("Reconcile original", focus["next_action"])
        self.assertFalse(focus["workflow_check"]["ok"])

    def test_missing_ledger_is_error_not_evidence_of_no_submission(self):
        focus = continuity.derive_focus(self.project, self.case)
        self.assertEqual(focus["ledger_coverage"], "no_ledgers_declared_not_proof_of_no_submissions")
        with self.assertRaisesRegex(ValueError, "ledger is missing"):
            self.update({"references": {**self.plan["references"], "ledgers": ["missing.json"]}})

    def test_pause_requires_sourced_event_and_continue_does_not_resume(self):
        with self.assertRaisesRegex(ValueError, "corresponding sourced event"):
            self.update({"status": "paused"})
        self.update({"status": "paused"}, {**self.event, "type": "pause", "source_ref": "actual-pause-message"})
        continuity.classify_message("continue")
        self.assertEqual(continuity.derive_focus(self.project, self.case)["status"], "paused")

    def test_all_case_paths_remain_inside_project(self):
        with self.assertRaisesRegex(ValueError, "escapes project"):
            continuity.derive_focus(self.project, "../outside")


if __name__ == "__main__":
    unittest.main()
