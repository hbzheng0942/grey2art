"""Offline work scheduling/review contracts. No tools, engines or providers run."""
from pathlib import Path
import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1] / "skills/greybox-to-multistyle-art"
sys.path.insert(0, str(ROOT / "runtime"))
from greybox.workgraph import WorkgraphError, evaluate_review, inspect_workgraph, task_fingerprint


class WorkgraphTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="workgraph-offline-")
        self.project = Path(self.temp.name)
        self.input = self.file("baseline.json", "frozen baseline")
        self.graph = {"schema": 1, "kind": "greybox-workgraph", "integrator": "integrator",
                      "resource_caps": {"image": 1, "lux": 1, "cpu": 2, "gpu": 1, "import": 1},
                      "leases": [], "tasks": [self.task("asset", resources={"lux": 1}),
                                               self.task("terrain", resources={"cpu": 1}),
                                               self.task("scene", ["asset", "terrain"], publish=True)]}

    def tearDown(self):
        self.temp.cleanup()

    def file(self, path, content):
        p = self.project / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return {"path": path, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}

    def task(self, tid, deps=None, resources=None, publish=False):
        return {"id": tid, "owner": "integrator" if publish else tid + "-worker", "style": "style-a",
                "assembly": "entry", "kind": "publish" if publish else "work", "state": "pending",
                "estimate_minutes": 10, "depends_on": deps or [], "inputs": [copy.deepcopy(self.input)],
                "allowed_output_dirs": ["out/" + tid], "outputs": ["out/" + tid + "/result.json"],
                "resources": resources or {"import": 1}, "exclusive_locks": ["publication"] if publish else [],
                "acceptance_criteria": [{"id": "reviewed", "description": "Fixture criterion only"}]}

    def inspect(self):
        path = self.project / "graph.json"
        path.write_text(json.dumps(self.graph))
        return inspect_workgraph("graph.json", self.project)

    def complete(self, tid):
        result = self.inspect()
        task = next(t for t in self.graph["tasks"] if t["id"] == tid)
        out = self.file(task["outputs"][0], tid + " output")
        evidence = self.file("evidence/" + tid + ".txt", tid + " evidence")
        task["completion"] = {"spec_sha256": task_fingerprint(task),
                              "dependency_sha256": {d: result["completion_sha256"][d] for d in task["depends_on"]},
                              "outputs": [out], "criteria_passed": ["reviewed"], "evidence": [evidence]}
        task["state"] = "completed"

    def test_independent_resources_form_same_wave(self):
        result = self.inspect()
        self.assertEqual(set(result["recommended_wave"]), {"asset", "terrain"})
        self.assertEqual(result["states"]["scene"], "waiting")

    def test_shared_dependency_critical_path_has_priority(self):
        self.graph["tasks"].append(self.task("other", resources={"lux": 1}))
        result = self.inspect()
        self.assertIn("asset", result["recommended_wave"])
        self.assertEqual(result["deferred_ready"]["other"], "resource_capacity")

    def priority(self, task, tier):
        task["visual_priority"] = {"tier": tier, "rationale": "Fixture visual responsibility"}
        return task

    def test_complete_composition_beats_three_hour_small_prop_polish(self):
        polish = self.priority(self.task("small-prop", resources={"cpu": 1}), "polish")
        polish["estimate_minutes"] = 180
        sky = self.priority(self.task("sky-ground-light", resources={"cpu": 1}), "composition")
        self.graph["tasks"] = [polish, sky]
        self.graph["resource_caps"]["cpu"] = 1
        result = self.inspect()
        self.assertEqual(result["recommended_wave"], ["sky-ground-light"])
        self.assertEqual(result["deferred_ready"]["small-prop"], "resource_capacity")

    def test_sample_dependency_inherits_composition_priority(self):
        source = self.priority(self.task("reference", resources={"cpu": 1}), "style")
        sample = self.priority(self.task("sample", ["reference"]), "composition")
        unrelated = self.priority(self.task("unrelated", resources={"cpu": 1}), "style")
        unrelated["estimate_minutes"] = 180
        self.graph["tasks"] = [source, sample, unrelated]
        self.graph["resource_caps"]["cpu"] = 1
        result = self.inspect()
        self.assertEqual(result["recommended_wave"], ["reference"])
        self.assertEqual(result["effective_visual_tiers"]["reference"], "composition")

    def test_fairness_and_stagnation_stay_within_tier(self):
        self.graph["resource_caps"]["cpu"] = 1
        self.graph["tasks"] = [self.priority(self.task(tid, resources={"cpu": 1}), tier)
                               for tid, tier in [("one", "composition"), ("two", "composition"), ("polish", "polish")]]
        self.graph["observations"] = {"one": {"ready_wait_rounds": 5, "no_progress_rounds": 2},
                                      "two": {"ready_wait_rounds": 2}, "polish": {"ready_wait_rounds": 1000}}
        self.assertEqual(self.inspect()["recommended_wave"], ["two"])
        self.graph["observations"]["one"]["no_progress_rounds"] = 0
        self.assertEqual(self.inspect()["recommended_wave"], ["one"])

    def test_active_work_reminder_does_not_kill_or_release_running_job(self):
        self.graph["tasks"][0]["state"] = "running"
        self.graph["leases"] = [{"task_id": "asset", "owner": "asset-worker"}]
        self.graph["observations"] = {"asset": {"active_minutes": 30, "no_progress_rounds": 2}}
        result = self.inspect()
        self.assertEqual(result["states"]["asset"], "running")
        self.assertEqual(result["resource_use_with_wave"]["lux"], 1)
        self.assertIn("terrain", result["recommended_wave"])
        self.assertEqual(result["work_unit_reminders"]["asset"]["action"], "reassess_at_safe_boundary")

    def test_external_wait_does_not_consume_active_work_budget(self):
        self.graph["observations"] = {"asset": {"active_minutes": 1, "external_wait_minutes": 180}}
        self.assertNotIn("asset", self.inspect()["work_unit_reminders"])

    def test_observations_do_not_invalidate_completed_receipts(self):
        self.complete("asset")
        before = self.inspect()["task_spec_sha256"]
        self.graph["observations"] = {"asset": {"active_minutes": 30, "ready_wait_rounds": 4}}
        result = self.inspect()
        self.assertEqual(before, result["task_spec_sha256"])
        self.assertEqual(result["states"]["asset"], "completed")

    def test_unknown_submission_is_not_reissued_and_local_work_continues(self):
        self.graph["observations"] = {"asset": {"submission_state": "unknown"}}
        result = self.inspect()
        self.assertEqual(result["states"]["asset"], "reconciliation_required")
        self.assertEqual(result["states"]["scene"], "waiting")
        self.assertEqual(result["recommended_wave"], ["terrain"])

    def test_explicit_visual_policy_requires_bounded_classified_tasks(self):
        self.graph["scheduling_policy"] = "visual-completeness-v1"
        with self.assertRaisesRegex(WorkgraphError, "requires visual_priority and work_unit"):
            self.inspect()
        for task in self.graph["tasks"]:
            self.priority(task, "composition")
            task["work_unit"] = {"observable_result": "Complete sample", "stop_condition": "Output or blocker",
                                 "active_minutes_budget": 25}
        self.assertEqual(self.inspect()["unclassified_tasks"], [])

    def test_completed_requires_actual_output_and_evidence(self):
        self.complete("asset")
        self.assertEqual(self.inspect()["states"]["asset"], "completed")
        (self.project / "out/asset/result.json").write_text("unexpected changed asset")
        result = self.inspect()
        self.assertEqual(result["states"]["asset"], "stale")
        self.assertEqual(result["states"]["scene"], "stale")
        self.assertEqual(result["states"]["terrain"], "ready")

    def test_spec_revision_invalidates_completed_descendants(self):
        self.complete("asset")
        self.complete("terrain")
        self.complete("scene")
        self.graph["tasks"][0]["acceptance_criteria"][0]["description"] = "new requirement"
        result = self.inspect()
        self.assertEqual(result["states"]["asset"], "stale")
        self.assertEqual(result["states"]["scene"], "stale")
        self.assertEqual(result["states"]["terrain"], "completed")

    def test_rerecorded_upstream_invalidates_old_consumer_receipt(self):
        self.complete("asset")
        self.complete("terrain")
        self.complete("scene")
        task = self.graph["tasks"][0]
        task["completion"]["outputs"] = [self.file(task["outputs"][0], "approved revision")]
        result = self.inspect()
        self.assertEqual(result["states"]["asset"], "completed")
        self.assertEqual(result["states"]["scene"], "stale")

    def test_missing_or_false_criteria_never_complete(self):
        self.complete("asset")
        self.graph["tasks"][0]["completion"]["criteria_passed"] = []
        self.assertEqual(self.inspect()["states"]["asset"], "stale")

    def test_cycles_and_output_overlap_rejected(self):
        for mutate in (lambda: self.graph["tasks"][0]["depends_on"].append("scene"),
                       lambda: self.graph["tasks"][1].update(allowed_output_dirs=["out/asset/nested"], outputs=["out/asset/nested/file.json"])):
            original = copy.deepcopy(self.graph)
            mutate()
            with self.assertRaises(WorkgraphError):
                self.inspect()
            self.graph = original

    def test_symlink_escape_and_file_escape_rejected(self):
        with tempfile.TemporaryDirectory(prefix="workgraph-outside-") as outside:
            (self.project / "escape").symlink_to(outside, target_is_directory=True)
            self.graph["tasks"][0]["allowed_output_dirs"] = ["escape/assets"]
            self.graph["tasks"][0]["outputs"] = ["escape/assets/result.json"]
            with self.assertRaises(WorkgraphError):
                self.inspect()
        with self.assertRaises(WorkgraphError):
            inspect_workgraph("../outside.json", self.project)

    def test_publication_requires_integrator_and_lock(self):
        self.graph["tasks"][2]["owner"] = "asset-worker"
        with self.assertRaises(WorkgraphError):
            self.inspect()
        self.graph["tasks"][2]["owner"] = "integrator"
        self.graph["tasks"][2]["exclusive_locks"] = []
        with self.assertRaises(WorkgraphError):
            self.inspect()

    def test_running_lease_reserves_capacity(self):
        self.graph["tasks"][0]["state"] = "running"
        self.graph["leases"] = [{"task_id": "asset", "owner": "asset-worker"}]
        self.graph["tasks"].append(self.task("other", resources={"lux": 1}))
        result = self.inspect()
        self.assertEqual(result["states"]["asset"], "running")
        self.assertNotIn("other", result["recommended_wave"])
        self.assertIn("terrain", result["recommended_wave"])

    def test_leases_cannot_overlap_publication(self):
        self.graph["tasks"] = [self.task("one", publish=True), self.task("two", publish=True)]
        self.graph["resource_caps"]["import"] = 2
        for task in self.graph["tasks"]:
            task["state"] = "running"
            self.graph["leases"].append({"task_id": task["id"], "owner": "integrator"})
        with self.assertRaises(WorkgraphError):
            self.inspect()

    def test_positive_resource_caps_required(self):
        self.graph["resource_caps"]["gpu"] = 0
        with self.assertRaises(WorkgraphError):
            self.inspect()

    def test_missing_future_output_waits_external_missing_input_is_stale(self):
        future = {"path": "out/asset/result.json", "sha256": hashlib.sha256(b"asset output").hexdigest()}
        self.graph["tasks"][2]["inputs"].append(future)
        result = self.inspect()
        self.assertEqual(result["states"]["scene"], "waiting")
        self.assertIn("awaiting_declared_upstream_output", result["reasons"]["scene"])
        self.complete("asset")
        self.complete("terrain")
        self.assertEqual(self.inspect()["states"]["scene"], "ready")
        self.graph["tasks"][2]["inputs"].append({"path": "external-missing.json", "sha256": "0" * 64})
        self.assertEqual(self.inspect()["states"]["scene"], "stale")

    def test_undeclared_internal_file_is_not_a_dependency_interface(self):
        receipt = self.file("out/asset/internal.txt", "internal work")
        self.graph["tasks"][2]["inputs"].append(receipt)
        with self.assertRaises(WorkgraphError):
            self.inspect()

    def test_command_is_read_only(self):
        self.inspect()
        before = {str(p.relative_to(self.project)): p.read_bytes() for p in self.project.rglob("*") if p.is_file()}
        result = subprocess.run([sys.executable, str(ROOT / "scripts/workgraph.py"), "inspect", "--project",
                                 str(self.project), "--file", "graph.json"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        after = {str(p.relative_to(self.project)): p.read_bytes() for p in self.project.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def review(self):
        return {"schema": 1, "kind": "greybox-review-budget",
                "budget": {"max_rounds": 3, "max_minutes": 30, "max_calls": 4, "max_no_progress_rounds": 2},
                "issues": [{"id": "floating", "severity": "blocking", "state": "open", "description": "Hero floats"}],
                "rounds": []}

    def test_unresolved_blocker_never_passes_on_exhaustion(self):
        data = self.review()
        data["rounds"] = [{"id": "r1", "minutes": 31, "calls": 1, "improvements": []}]
        result = evaluate_review(data, self.project)
        self.assertEqual(result["recommendation"], "change_method_or_escalate_blockers")
        self.assertEqual(result["unresolved_blockers"], ["floating"])
        self.assertFalse(result["accepted"])
        self.assertFalse(result["paid_retry_authorized"])

    def test_no_progress_new_hypothesis_does_not_reset_budget(self):
        data = self.review()
        data["rounds"] = [{"id": "r" + str(i), "minutes": 2, "calls": 0, "improvements": [],
                           "next_hypothesis": {"change": "Try changed contact anchor", "issue_ids": ["floating"]}} for i in (1, 2)]
        result = evaluate_review(data, self.project)
        self.assertTrue(result["no_progress_triggered"])
        self.assertEqual(result["recommendation"], "change_method_or_escalate_blockers")

    def test_fake_progress_and_unproven_resolution_rejected(self):
        data = self.review()
        before = self.file("before.txt", "same")
        data["rounds"] = [{"id": "r1", "minutes": 2, "calls": 0,
                           "improvements": [{"issue_id": "floating", "direction": "decrease",
                                             "before": dict(before, metric=2), "after": dict(before, metric=1)}]}]
        with self.assertRaises(WorkgraphError):
            evaluate_review(data, self.project)
        data["rounds"] = []
        data["issues"][0]["state"] = "resolved"
        with self.assertRaises(WorkgraphError):
            evaluate_review(data, self.project)

    def test_measured_improvement_allows_bounded_next_iteration(self):
        data = self.review()
        data["rounds"] = [{"id": "r1", "minutes": 2, "calls": 1,
                           "improvements": [{"issue_id": "floating", "direction": "decrease",
                                             "before": dict(self.file("before.txt", "gap 20"), metric=20),
                                             "after": dict(self.file("after.txt", "gap 5"), metric=5)}]}]
        result = evaluate_review(data, self.project)
        self.assertEqual(result["recommendation"], "continue_within_existing_scope_and_budget")
        self.assertEqual(result["unresolved_blockers"], ["floating"])

    def test_polish_stops_and_never_claims_acceptance(self):
        data = self.review()
        data["issues"][0]["severity"] = "polish"
        data["rounds"] = [{"id": "r1", "minutes": 30, "calls": 0, "improvements": []}]
        result = evaluate_review(data, self.project)
        self.assertEqual(result["recommendation"], "stop_polish_and_present")
        self.assertFalse(result["accepted"])

    def test_zero_call_budget_allows_local_review_without_call_authority(self):
        data = self.review()
        data["budget"]["max_calls"] = 0
        result = evaluate_review(data, self.project)
        self.assertEqual(result["recommendation"], "plan_first_bounded_iteration")
        self.assertFalse(result["calls_allowed"])
        self.assertEqual(result["remaining_calls"], 0)
        self.assertFalse(result["paid_retry_authorized"])

    def test_observed_art_progress_requires_current_evidence_and_reviewer(self):
        data = self.review()
        improvement = {"issue_id": "floating", "mode": "observed", "reviewer": "art-reviewer",
                       "criterion": "contact grounding", "observation": "The base now meets the plinth; the rear gap still needs repair.",
                       "before": self.file("before.txt", "native review before"),
                       "after": self.file("after.txt", "native review after")}
        data["rounds"] = [{"id": "r1", "minutes": 2, "calls": 0, "improvements": [improvement]}]
        result = evaluate_review(data, self.project)
        self.assertEqual(result["recommendation"], "continue_within_existing_scope_and_budget")
        self.assertFalse(result["accepted"])
        del improvement["reviewer"]
        with self.assertRaises(WorkgraphError):
            evaluate_review(data, self.project)

    def test_polish_progress_cannot_reset_blocker_streak(self):
        data = self.review()
        data["issues"].append({"id": "gloss", "severity": "polish", "state": "open", "description": "Gloss preference"})
        data["rounds"] = [{"id": "r" + str(i), "minutes": 2, "calls": 0,
                           "improvements": [{"issue_id": "gloss", "mode": "observed", "reviewer": "reviewer",
                                             "criterion": "surface gloss", "observation": "Surface gloss is more consistent.",
                                             "before": self.file("before-" + str(i) + ".txt", "before " + str(i)),
                                             "after": self.file("after-" + str(i) + ".txt", "after " + str(i))}]} for i in (1, 2)]
        result = evaluate_review(data, self.project)
        self.assertTrue(result["no_progress_triggered"])
        self.assertEqual(result["no_progress_focus"], ["floating"])
        self.assertEqual(result["recommendation"], "change_method_or_escalate_blockers")

    def test_repeated_hypothesis_is_not_new(self):
        data = self.review()
        data["budget"]["max_no_progress_rounds"] = 4
        data["rounds"] = [{"id": "r" + str(i), "minutes": 1, "calls": 0, "improvements": [],
                           "next_hypothesis": {"change": "Adjust support anchor", "issue_ids": ["floating"]}} for i in (1, 2)]
        result = evaluate_review(data, self.project)
        self.assertFalse(result["latest_hypothesis_is_new"])
        self.assertEqual(result["recommendation"], "require_new_hypothesis_before_iteration")


if __name__ == "__main__":
    unittest.main()
