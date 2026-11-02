"""Usage feedback behavior with tiny local records; no provider or engine calls."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1] / "skills/greybox-to-multistyle-art"
sys.path.insert(0, str(ROOT / "runtime"))
from greybox import continuity, core, feedback, production_control


class UsageFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="usage-feedback-offline-")
        self.addCleanup(self.temporary.cleanup)
        self.project = Path(self.temporary.name)
        self.case = self.project / "art/case-a"
        self.workflow = self.project / "workflow.json"
        core.write(self.workflow, {
            "schema": 2, "kind": "greybox-art-workflow", "selected_styles": ["a"],
            "stages": [{"id": "baseline", "scope": "shared", "status": "draft", "evidence": []}],
        })
        plan = {
            "case_id": "case-a", "writer": "integrator", "objective": "Two playable styles",
            "current_stage": "shared/baseline", "status": "active",
            "constraints": ["Preserve collision"], "quality_floor": ["Complete native sample"],
            "remaining": ["Baseline", "H1"], "proposals": [],
            "references": {"workflow": "workflow.json", "ledgers": [], "approved_inputs": []},
        }
        self.event = {
            "type": "requirement", "summary": "Synthetic task", "scope": "case",
            "source_ref": "fixture-message-1", "evidence": [],
        }
        continuity.initialize(self.project, self.case, plan, self.event)

    def receipt(self, name="evidence/check.json", value=None):
        path = self.project / name
        core.write(path, value if value is not None else {"fixture": True, "passed": False})
        return {"path": name, "sha256": core.file_hash(path)}

    def update(self, event=None, changes=None):
        plan = core.read(self.case / "PLAN.json")
        return continuity.update(
            self.project, self.case, "integrator", plan["revision"], core.file_hash(self.workflow),
            event or self.event, changes,
        )

    def cli(self, *arguments):
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts/greybox.py"), "feedback", *arguments],
            capture_output=True, text=True, timeout=15,
        )
        return result

    def observation(self, event_id="obs-1", issue_id="missing-master", **changes):
        value = {
            "schema": 1, "kind": "greybox-usage-observation", "event_id": event_id,
            "issue_id": issue_id, "type": "failure", "stage": "a/references",
            "summary": "Reference board omitted an approved master",
            "source_ref": "fixture-tool-result-1", "basis": "observed",
            "expected": "Every required view uses its approved master",
            "actual": "Side view used only the scene concept",
            "context": {"host": "workbuddy", "model": None, "engine": "godot", "session_ref": "fixture-session-1"},
            "mechanisms": ["multi-component", "reference-transfer"],
            "evidence": [self.receipt()],
            "project_status": "open", "skill_status": "untriaged",
            "next_test": "Missing master must fail; the complete request must pass",
        }
        value.update(changes)
        return value

    def record(self, value=None, revision=None, writer="integrator", checkpoint=None):
        plan = core.read(self.case / "PLAN.json")
        return feedback.record(
            self.project, self.case, value or self.observation(), writer,
            plan["revision"] if revision is None else revision,
            core.file_hash(self.workflow) if checkpoint is None else checkpoint,
        )

    def test_observation_is_bound_to_progress_and_recap_is_read_only(self):
        before_workflow = self.workflow.read_bytes()
        result = self.record()
        self.assertTrue(result["ok"])
        self.assertFalse(result["reused"])
        plan_before = (self.case / "PLAN.json").read_bytes()
        progress_before = (self.case / "PROGRESS.jsonl").read_bytes()
        report = feedback.build_recap(self.project, self.case)
        self.assertEqual(len(report["issues"]), 1)
        issue = report["issues"][0]
        self.assertEqual(issue["issue_id"], "missing-master")
        self.assertEqual(issue["expected"], "Every required view uses its approved master")
        self.assertEqual(issue["context"]["host"], "workbuddy")
        self.assertIsNone(issue["context"].get("model"))
        self.assertTrue(issue["evidence_current"])
        self.assertEqual(len(report["regression_candidates"]), 1)
        self.assertEqual(plan_before, (self.case / "PLAN.json").read_bytes())
        self.assertEqual(progress_before, (self.case / "PROGRESS.jsonl").read_bytes())
        self.assertEqual(before_workflow, self.workflow.read_bytes())
        rows = [json.loads(line) for line in progress_before.splitlines()]
        observation_hash = core.file_hash(core.resolve_input(result["observation_path"], self.project))
        self.assertIn(observation_hash, [receipt["sha256"] for receipt in rows[-1]["evidence"]])

    def test_observation_records_actual_package_identity_without_certifying_runtime(self):
        result = self.record()
        envelope = core.read(core.resolve_input(result["observation_path"], self.project))
        self.assertEqual(envelope["skill"]["manifest_sha256"], core.file_hash(ROOT / "MANIFEST.json"))
        self.assertIn("not a fresh whole-package validation", envelope["skill"]["identity_scope"])
        report = feedback.build_recap(self.project, self.case)
        self.assertEqual(report["issues"][0]["events"][0]["skill"], envelope["skill"])

    def test_unknown_model_in_new_session_does_not_inherit_prior_known_model(self):
        self.record(self.observation(context={"host": "workbuddy", "model": "fixture-model", "engine": "godot", "session_ref": "session-one"}))
        self.record(self.observation("obs-2", type="attempt", method="Inspect from second host",
            context={"host": "codex", "model": None, "engine": "godot", "session_ref": "session-two"}))
        context = feedback.build_recap(self.project, self.case)["issues"][0]["context"]
        self.assertEqual(context["host"], "codex")
        self.assertEqual(context["session_ref"], "session-two")
        self.assertIsNone(context.get("model"))

    def test_exact_retry_is_idempotent_even_with_old_revision(self):
        observation = self.observation()
        first = self.record(observation, revision=1)
        before_plan = (self.case / "PLAN.json").read_bytes()
        before_progress = (self.case / "PROGRESS.jsonl").read_bytes()
        second = self.record(copy.deepcopy(observation), revision=1)
        self.assertTrue(second["reused"])
        self.assertEqual(first["event_seq"], second["event_seq"])
        self.assertEqual(before_plan, (self.case / "PLAN.json").read_bytes())
        self.assertEqual(before_progress, (self.case / "PROGRESS.jsonl").read_bytes())

    def test_conflicting_event_id_never_overwrites_original_observation(self):
        observation = self.observation()
        result = self.record(observation)
        observation_path = core.resolve_input(result["observation_path"], self.project)
        original = observation_path.read_bytes()
        with self.assertRaises(ValueError):
            self.record({**observation, "summary": "Different event pretending to be the same"})
        self.assertEqual(original, observation_path.read_bytes())
        self.assertEqual(core.read(self.case / "PLAN.json")["revision"], 2)

    def test_rejected_stale_record_is_invisible_and_can_be_retried(self):
        observation = self.observation()
        self.update({**self.event, "type": "change", "summary": "Unrelated concurrent plan update"})
        with self.assertRaises(ValueError):
            self.record(observation, revision=1)
        self.assertEqual(feedback.build_recap(self.project, self.case)["issues"], [])
        self.record(observation)
        self.assertEqual(len(feedback.build_recap(self.project, self.case)["issues"]), 1)

    def test_foreign_writer_and_changed_checkpoint_cannot_append(self):
        observation = self.observation()
        for options in ({"writer": "other-worker"}, {"checkpoint": "0" * 64}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.record(observation, **options)
        self.assertEqual(core.read(self.case / "PLAN.json")["revision"], 1)
        self.assertEqual(feedback.build_recap(self.project, self.case)["issues"], [])

    def test_interrupted_record_recovers_once_on_same_event_retry(self):
        observation = self.observation()
        actual_write = core.write
        def interrupt_plan(path, value):
            if Path(path).resolve() == (self.case / "PLAN.json").resolve():
                raise OSError("synthetic interrupted plan replacement")
            return actual_write(path, value)
        with patch.object(core, "write", side_effect=interrupt_plan):
            with self.assertRaises(OSError):
                self.record(observation, revision=1)
        result = self.record(observation, revision=1)
        self.assertTrue(result["reused"])
        self.assertFalse((self.case / ".progress-transaction.json").exists())
        self.assertEqual(core.read(self.case / "PLAN.json")["revision"], 2)
        self.assertEqual(len((self.case / "PROGRESS.jsonl").read_text().splitlines()), 2)

    def test_evidence_tamper_keeps_issue_visible_and_unresolved(self):
        observation = self.observation()
        self.record(observation)
        fixed = self.observation("obs-2", type="resolution", project_status="fixed")
        self.record(fixed)
        core.write(self.project / "evidence/check.json", {"changed_after_review": True})
        report = feedback.build_recap(self.project, self.case)
        self.assertFalse(report["issues"][0]["evidence_current"])
        self.assertTrue(report["warnings"])
        self.assertGreater(feedback.focus_summary(self.project, self.case)["total_unresolved"], 0)

    def test_observation_file_tamper_is_reported_not_reinterpreted(self):
        result = self.record()
        path = core.resolve_input(result["observation_path"], self.project)
        value = core.read(path)
        value["project_status"] = "fixed"
        value["skill_status"] = "verified"
        core.write(path, value)
        report = feedback.build_recap(self.project, self.case)
        self.assertTrue(report["warnings"])
        self.assertFalse(any(issue["skill_status"] == "verified" for issue in report["issues"]))

    def test_workaround_and_cross_session_reopen_keep_skill_unresolved(self):
        self.record()
        self.record(self.observation("obs-2", type="resolution", project_status="workaround",
                                     method="Manually include the known master"))
        report = feedback.build_recap(self.project, self.case)
        self.assertEqual(report["issues"][0]["project_status"], "workaround")
        self.assertNotEqual(report["issues"][0]["skill_status"], "verified")
        self.record(self.observation("obs-3", type="reopen", project_status="open",
                                     context={"host": "codex", "model": None, "engine": "godot", "session_ref": "fixture-session-2"}))
        report = feedback.build_recap(self.project, self.case)
        self.assertEqual(len(report["issues"]), 1)
        self.assertEqual(report["issues"][0]["project_status"], "open")
        self.assertEqual(len(report["issues"][0]["events"]), 3)

    def test_manual_episode_dedup_does_not_count_creative_decisions_as_rescue(self):
        self.record()
        for event_id, episode_id, kind in [
            ("obs-2", "rescue-1", "rescue"), ("obs-3", "rescue-1", "rescue"),
            ("obs-4", "rescue-2", "rescue"), ("obs-5", "choice-1", "creative_decision"),
            ("obs-6", "scope-1", "scope_change"),
        ]:
            self.record(self.observation(event_id, type="intervention", basis="user_reported",
                intervention={"episode_id": episode_id, "kind": kind}))
        result = feedback.build_recap(self.project, self.case)["interventions"]
        self.assertEqual(result["rescue"], 2)
        self.assertEqual(result["creative_decision"], 1)
        self.assertEqual(result["scope_change"], 1)
        self.assertEqual(result["observed_episodes"], 4)
        self.assertIn("coverage", result)

    def test_normal_creative_and_scope_interventions_do_not_become_pending_defects(self):
        for index, kind in enumerate(("creative_decision", "scope_change")):
            observation = self.observation("obs-" + str(index), "choice-" + str(index),
                type="intervention", basis="user_reported",
                intervention={"episode_id": "choice-" + str(index), "kind": kind})
            for field in ("expected", "actual", "project_status", "skill_status", "next_test"):
                observation.pop(field)
            self.record(observation)
        report = feedback.build_recap(self.project, self.case)
        self.assertEqual(report["interventions"]["creative_decision"], 1)
        self.assertEqual(report["interventions"]["scope_change"], 1)
        self.assertEqual(report["interventions"]["rescue"], 0)
        self.assertFalse(any(issue["is_defect_candidate"] for issue in report["issues"]))
        focus = feedback.focus_summary(self.project, self.case)
        self.assertEqual(focus["total_unresolved"], 0)
        self.assertEqual(focus["issues"], [])
        self.assertEqual(report["regression_candidates"], [])

    def test_measurement_unknowns_stay_unknown_and_repeated_measurement_is_not_added(self):
        costs = {"measurement_id": "measure-1", "scope": "one-local-attempt", "source_ref": "fixture-timer-1",
                 "active_seconds": 4.0, "elapsed_seconds": 8.0, "input_tokens": None,
                 "cached_input_tokens": None, "output_tokens": None, "actual_cost": None, "currency": None}
        self.record(self.observation(costs=costs))
        self.record(self.observation("obs-2", type="attempt", method="Check request mapping", costs=costs))
        report = feedback.build_recap(self.project, self.case)
        self.assertEqual(len(report["measurements"]), 1)
        self.assertIsNone(report["measurements"][0]["input_tokens"])
        self.assertIsNone(report["measurements"][0]["actual_cost"])
        self.assertEqual(report["measurements"][0]["active_seconds"], 4.0)
        self.assertEqual(report["coverage"]["token_measurements"], "unknown")

    def test_fixed_and_verified_claims_require_evidence_and_regression_identity(self):
        invalid = [
            self.observation(type="resolution", project_status="fixed", evidence=[]),
            self.observation(type="resolution", skill_status="verified"),
            self.observation(type="regression", skill_status="verified", evidence=[]),
        ]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.record(value)
        before = self.receipt("evidence/before.json", {"case": "original-before", "passed": False})
        after = self.receipt("evidence/after.json", {"case": "original-after", "passed": True})
        holdout = self.receipt("evidence/holdout.json", {"case": "new-layout", "passed": True})
        self.record(self.observation(type="regression", project_status="fixed", skill_status="verified",
            regression={"before": before, "after": after, "holdout": holdout}))
        report = feedback.build_recap(self.project, self.case)
        self.assertEqual(report["issues"][0]["skill_status"], "verified")

    def test_copied_regression_evidence_does_not_establish_a_holdout(self):
        before = self.receipt("evidence/before.json", {"passed": False})
        after = self.receipt("evidence/after.json", {"passed": True})
        holdout = self.receipt("evidence/holdout.json", {"passed": True})
        with self.assertRaises(ValueError):
            self.record(self.observation(type="regression", project_status="fixed", skill_status="verified",
                regression={"before": before, "after": after, "holdout": holdout}))
        self.assertEqual(core.read(self.case / "PLAN.json")["revision"], 1)

    def test_evidence_escape_and_invalid_numeric_costs_rejected(self):
        invalid = [
            self.observation(evidence=[{"path": "../outside.json", "sha256": "0" * 64}]),
            self.observation(event_id="../escape"),
            self.observation(costs={"measurement_id": "measure-1", "scope": "attempt", "source_ref": "timer", "input_tokens": -1}),
            self.observation(costs={"measurement_id": "measure-1", "scope": "attempt", "source_ref": "timer", "active_seconds": float("nan")}),
            self.observation(costs={"measurement_id": "measure-1", "scope": "attempt", "source_ref": "timer", "input_tokens": True}),
        ]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.record(value)
        self.assertEqual(core.read(self.case / "PLAN.json")["revision"], 1)

    def test_production_repairs_are_derived_without_mutating_their_ledger(self):
        plan = {"styles": [{"id": "a"}], "assets": [],
            "workspace": {"schema": 1, "case_id": "case-a", "root": "art/case-a", "engine": "godot", "asset_owners": {}}}
        production_control.initialize(self.project, plan, self.workflow)
        path = production_control.control_path(self.project, plan)
        production_control.configure(self.project, path, {
            "families": {"solid": {"profile": {"structure": "solid", "method": "preserve", "skeleton": "none", "engine": "godot"},
                "asset_ids": ["asset-a"], "pilot_asset_ids": ["asset-a"], "required_interactions": [], "runtime_profile": None}},
            "combinations": {"sample": {"style_id": "a", "asset_ids": ["asset-a"], "required_interactions": [], "state": "queued"}},
        }, core.read(path)["revision"])
        production_control.open_repair(self.project, path, "uv-tear", ["asset-a"], "UV tearing")
        production_control.begin_repair(self.project, path, "uv-tear", "preserve islands", "fixture-worker")
        production_control.finish_repair(self.project, path, "uv-tear", 2.5, self.receipt(), "Still tears")
        before = path.read_bytes()
        report = feedback.build_recap(self.project, self.case)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(len(report["repairs"]), 1)
        self.assertIn("uv-tear", json.dumps(report["repairs"]))
        self.assertNotIn("claims", report["repairs"][0])
        self.assertIs(report["repairs"][0].get("inflight"), False)

    def test_malformed_nested_control_records_warn_without_mutation_or_crash(self):
        path = self.case / "shared/production/CONTROL.json"
        malformed = ["not-an-object", {"attempts": ["not-an-attempt"]}, {"attempts": [], "disposition": []}]
        for repair in malformed:
            with self.subTest(repair=repair):
                core.write(path, {"case_id": "case-a", "repairs": {"broken": repair}})
                before = path.read_bytes()
                report = feedback.build_recap(self.project, self.case)
                self.assertTrue(report["warnings"])
                self.assertEqual(report["repairs"], [])
                self.assertEqual(path.read_bytes(), before)

    def test_ordinary_failure_is_visible_without_claiming_it_was_classified(self):
        self.update({**self.event, "type": "failure", "summary": "Unclassified engine import failed"})
        report = feedback.build_recap(self.project, self.case)
        self.assertEqual(report["issues"], [])
        self.assertEqual(len(report["unclassified_failures"]), 1)
        self.assertIn("Unclassified engine import failed", json.dumps(report["unclassified_failures"]))
        self.assertTrue((self.case / "feedback/recap.json").is_file())
        self.assertTrue((self.case / "feedback/recap.md").is_file())

    def test_focus_is_bounded_while_total_unresolved_remains_visible(self):
        for index in range(5):
            self.record(self.observation("obs-" + str(index), "issue-" + str(index), summary="Detailed observed failure. " * 45))
        before = (self.case / "PROGRESS.jsonl").read_bytes()
        focus = continuity.derive_focus(self.project, self.case)["usage_feedback"]
        self.assertEqual(focus["total_unresolved"], 5)
        self.assertLessEqual(len(focus["issues"]), 3)
        self.assertTrue(all(len(issue["summary"]) <= 240 for issue in focus["issues"]))
        self.assertEqual(before, (self.case / "PROGRESS.jsonl").read_bytes())

    def test_focus_skips_artifact_hashing_and_labels_unchecked_freshness(self):
        asset = self.project / "evidence/representative-asset.bin"
        asset.parent.mkdir()
        asset.write_bytes(b"synthetic-shared-asset" * 12000)
        evidence = {"path": asset.relative_to(self.project).as_posix(), "sha256": core.file_hash(asset)}
        self.record(self.observation("obs-pending", "pending", evidence=[evidence]))
        regression = {
            "before": self.receipt("evidence/before.json", {"stage": "before", "passed": False}),
            "after": self.receipt("evidence/after.json", {"stage": "after", "passed": True}),
            "holdout": self.receipt("evidence/holdout.json", {"case": "held-out", "passed": True}),
        }
        self.record(self.observation("obs-fixed", "fixed", type="regression", evidence=[evidence],
                                     project_status="fixed", skill_status="verified", regression=regression))
        asset.write_bytes(b"artifact changed since the declared outcome")
        real_hash = core.file_hash
        artifact_paths = {asset.resolve()} | {core.resolve_input(ref["path"], self.project) for ref in regression.values()}
        def guard_artifact_hash(path):
            self.assertNotIn(Path(path).resolve(), artifact_paths, "Routine FOCUS rehashed artifact evidence")
            return real_hash(path)
        with patch.object(core, "file_hash", side_effect=guard_artifact_hash):
            focus = feedback.focus_summary(self.project, self.case)
        self.assertFalse(focus["coverage"]["artifact_evidence_checked"])
        self.assertEqual(focus["total_unresolved"], 1)
        self.assertEqual(focus["issues"][0]["issue_id"], "pending")
        self.assertIsNone(focus["issues"][0]["evidence_current"])
        checked = feedback.build_recap(self.project, self.case)
        self.assertTrue(checked["coverage"]["artifact_evidence_checked"])
        self.assertFalse(next(issue for issue in checked["issues"] if issue["issue_id"] == "fixed")["evidence_current"])

    def test_unchanged_refresh_does_not_rewrite_report_files(self):
        self.record()
        first = feedback.refresh(self.project, self.case)
        paths = [Path(first["recap_json"]), Path(first["recap_markdown"])]
        before = [(path.read_bytes(), path.stat().st_mtime_ns) for path in paths]
        second = feedback.refresh(self.project, self.case)
        self.assertFalse(second["changed"])
        self.assertEqual(before, [(path.read_bytes(), path.stat().st_mtime_ns) for path in paths])

    def test_automatic_recap_skips_large_evidence_but_explicit_recap_checks_it(self):
        asset = self.project / "evidence/representative-asset.bin"
        asset.parent.mkdir()
        asset.write_bytes(b"synthetic-shared-asset" * 12000)
        evidence = {"path": asset.relative_to(self.project).as_posix(), "sha256": core.file_hash(asset)}
        self.record(self.observation(evidence=[evidence]))
        control = self.case / "shared/production/CONTROL.json"
        core.write(control, {"case_id": "case-a", "repairs": {"asset-fix": {
            "attempts": [{"method": "local-repair", "evidence": evidence}], "disposition": {}}}})
        asset.write_bytes(b"changed since recording")
        real_hash = core.file_hash

        def guard_artifact_hash(path):
            self.assertNotEqual(Path(path).resolve(), asset.resolve(), "Automatic recap rehashed asset evidence")
            return real_hash(path)

        with patch.object(core, "file_hash", side_effect=guard_artifact_hash):
            result = self.update({**self.event, "type": "review", "summary": "Next local review"})
        self.assertTrue(result["usage_feedback"]["ok"])
        self.assertFalse(result["usage_feedback"]["artifact_evidence_checked"])
        report = core.read(self.case / "feedback/recap.json")
        self.assertIsNone(report["issues"][0]["evidence_current"])
        self.assertIsNone(report["repairs"][0]["evidence_current"])
        self.assertIn("Artifact evidence checked: False", (self.case / "feedback/recap.md").read_text())
        checked = feedback.refresh(self.project, self.case)
        self.assertTrue(checked["artifact_evidence_checked"])
        report = core.read(self.case / "feedback/recap.json")
        self.assertFalse(report["issues"][0]["evidence_current"])
        self.assertFalse(report["repairs"][0]["evidence_current"])

    def test_cli_record_and_recap_work_in_fresh_process(self):
        source = self.project / "observation.json"
        core.write(source, self.observation())
        result = self.cli("record", "--project", str(self.project), "--case", "art/case-a", "--input", "observation.json",
            "--writer", "integrator", "--expected-revision", "1", "--checkpoint-sha256", core.file_hash(self.workflow))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(json.loads(result.stdout)["ok"])
        result = self.cli("recap", "--project", str(self.project), "--case", "art/case-a")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(json.loads(result.stdout)["ok"])
        report = core.read(self.case / "feedback/recap.json")
        self.assertEqual(report["issues"][0]["issue_id"], "missing-master")

    def test_export_omits_private_sources_and_redacts_obvious_sensitive_text(self):
        secret = "sk-test-secret-abcdef1234567890"
        private_url = "https://files.example.invalid/model?signature=private-recovery-token"
        observation = self.observation(summary="Blocked at " + str(self.project / "private/source.glb") + " " + private_url + " " + secret)
        observation["source_ref"] = "private-conversation-message-unique"
        self.record(observation)
        output = self.project / "feedback-share"
        result = feedback.export_report(self.project, self.case, output)
        self.assertTrue(result["ok"])
        self.assertFalse(result["uploaded"])
        self.assertTrue(result["review_required"])
        text = Path(result["json"]).read_text() + Path(result["markdown"]).read_text()
        for value in (str(self.project), private_url, "private-recovery-token", secret, "private-conversation-message-unique"):
            self.assertNotIn(value, text)
        self.assertIn("missing-master", text)
        self.assertIn("review", text.lower())

    def test_export_cannot_overwrite_project_root_or_observation_evidence(self):
        result = self.record()
        observation_path = core.resolve_input(result["observation_path"], self.project)
        before = observation_path.read_bytes()
        for output in (self.project, self.case / "feedback/observations", self.project.parent / "outside-feedback"):
            with self.subTest(output=output), self.assertRaises(ValueError):
                feedback.export_report(self.project, self.case, output)
        self.assertEqual(before, observation_path.read_bytes())

    def test_export_preserves_unrelated_existing_output_file(self):
        self.record()
        output = self.project / "feedback-share"
        output.mkdir()
        foreign = output / "usage-feedback.json"
        foreign.write_text('{"kind":"unrelated-user-work","value":"preserve"}\n')
        original = foreign.read_bytes()
        with self.assertRaises(ValueError):
            feedback.export_report(self.project, self.case, output)
        self.assertEqual(original, foreign.read_bytes())

    def test_legacy_case_focus_is_read_only_and_does_not_claim_coverage(self):
        before = {p.name: p.read_bytes() for p in self.case.iterdir() if p.is_file()}
        feedback_before = {p.name: p.read_bytes() for p in (self.case / "feedback").glob("*") if p.is_file()}
        focus = continuity.derive_focus(self.project, self.case)
        self.assertIn("usage_feedback", focus)
        self.assertTrue(focus["usage_feedback"]["ok"])
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.case.iterdir() if p.is_file()})
        self.assertEqual(feedback_before, {p.name: p.read_bytes() for p in (self.case / "feedback").glob("*") if p.is_file()})

    def test_explicit_triage_is_preserved_without_inventing_it_for_legacy_observations(self):
        legacy = self.observation()
        normalized = feedback.validate_observation(self.project, legacy)
        self.assertNotIn("triage", normalized)
        self.record(legacy)
        issue = feedback.build_recap(self.project, self.case)["issues"][0]
        self.assertEqual(issue["triage"], {"category": "unknown", "severity": "unknown", "fingerprint": None})
        triage = {"category": "skill_guidance", "severity": "major", "fingerprint": "approved-master-omitted"}
        self.record(self.observation("obs-2", type="attempt", triage=triage, method="Include missing reference"))
        self.record(self.observation("obs-3", type="resolution", project_status="workaround"))
        issue = feedback.build_recap(self.project, self.case)["issues"][0]
        self.assertEqual(issue["triage"], triage)
        self.assertIsNone(issue["events"][0]["triage"])
        self.assertEqual(issue["events"][1]["triage"], triage)
        self.assertEqual(issue["latest_method"], "Include missing reference")
        self.assertEqual((issue["event_count"], issue["attempt_count"]), (3, 1))

    def test_invalid_triage_is_rejected_before_progress_changes(self):
        invalid = [None, [], {"category": "guaranteed-root-cause"}, {"category": []},
                   {"severity": "critical"}, {"severity": []}, {"fingerprint": "../unsafe"},
                   {"category": "unknown", "auto_confirmed": True}]
        for triage in invalid:
            with self.subTest(triage=triage), self.assertRaises(ValueError):
                self.record(self.observation(triage=triage))
        self.assertEqual(core.read(self.case / "PLAN.json")["revision"], 1)

    def test_markdown_compacts_history_and_keeps_latest_method_without_deleting_json_events(self):
        original_receipts = []
        for index in range(8):
            result = self.record(self.observation("event-" + str(index), type="attempt",
                summary="history-marker-" + str(index) + " " + "Long observation. " * 100,
                method="Most recent method" if index == 2 else None))
            path = self.project / result["observation_path"]
            original_receipts.append((path, path.read_bytes()))
        refreshed = feedback.refresh(self.project, self.case)
        markdown = Path(refreshed["recap_markdown"]).read_text()
        report = core.read(Path(refreshed["recap_json"]))
        issue = report["issues"][0]
        self.assertEqual(len(issue["events"]), 8)
        self.assertEqual((issue["event_count"], issue["attempt_count"]), (8, 8))
        self.assertEqual(issue["latest_method"], "Most recent method")
        for index in range(5):
            self.assertNotIn("history-marker-" + str(index), markdown)
        for index in range(5, 8):
            self.assertIn("history-marker-" + str(index), markdown)
        self.assertIn("Most recent method", markdown)
        self.assertLess(len(markdown), 6000)
        for path, content in original_receipts:
            self.assertEqual(path.read_bytes(), content)

    def test_markdown_shows_latest_recorder_and_unknown_environment_without_inheritance(self):
        self.record(self.observation(context={"host": "workbuddy", "model": "old-host-model", "engine": "godot"}))
        self.record(self.observation("obs-2", type="attempt", context={"host": "codex", "model": None, "engine": None}))
        report = feedback.build_recap(self.project, self.case)
        text = feedback._markdown(report)
        self.assertIn("Recorder Skill: " + feedback.VERSION, text)
        self.assertIn(core.file_hash(ROOT / "MANIFEST.json"), text)
        self.assertIn("Host: codex; model: unknown; engine: unknown", text)
        self.assertNotIn("old-host-model", text)
        self.assertEqual(report["issues"][0]["events"][0]["context"]["model"], "old-host-model")
        self.assertIn("historical backfill", text)

    def test_markdown_prioritizes_unresolved_issues_and_labels_omitted_content(self):
        for index in range(13):
            self.record(self.observation("decision-" + str(index), "closed-choice-" + str(index),
                type="intervention", intervention={"episode_id": "choice-" + str(index), "kind": "creative_decision"}))
        self.record(self.observation("unresolved", "z-last-open-issue"))
        report = feedback.build_recap(self.project, self.case)
        text = feedback._markdown(report)
        self.assertEqual(len(report["issues"]), 14)
        self.assertIn("Recorded issues: 14; unresolved: 1", text)
        self.assertIn("z-last-open-issue", text)
        self.assertIn("Additional issues in JSON: 2", text)

    def test_reported_blocker_precedes_lower_severity_unresolved_issues(self):
        for issue_id, severity in [("a-unknown", "unknown"), ("b-minor", "minor"),
                                   ("c-major", "major"), ("z-blocker", "blocker")]:
            self.record(self.observation(issue_id, issue_id, triage={"severity": severity}))
        report = feedback.build_recap(self.project, self.case)
        self.assertEqual([issue["issue_id"] for issue in report["issues"]],
                         ["z-blocker", "c-major", "b-minor", "a-unknown"])
        self.assertTrue(all(issue["triage"]["category"] == "unknown" for issue in report["issues"]))

    def test_issue_draft_is_redacted_local_and_explicit_about_missing_reproduction(self):
        secret = "sk-draft-secret-abcdef1234567890"
        private_url = "https://private.example.invalid/source?token=original-job"
        self.record(self.observation(summary="Problem " + private_url + " " + secret,
            method="Inspect " + str(self.project / "private/input.glb")))
        plan_before = (self.case / "PLAN.json").read_bytes()
        progress_before = (self.case / "PROGRESS.jsonl").read_bytes()
        result = feedback.export_report(self.project, self.case, "feedback-share")
        draft = Path(result["issue_draft"]).read_text()
        self.assertIn("Minimal reproduction: unknown", draft)
        self.assertIn("usage-feedback.md and usage-feedback.json", draft)
        self.assertIn("Remaining state: project=open; Skill=untriaged", draft)
        for private in (secret, private_url, str(self.project)):
            self.assertNotIn(private, draft)
        self.assertFalse(result["uploaded"])
        self.assertEqual(plan_before, (self.case / "PLAN.json").read_bytes())
        self.assertEqual(progress_before, (self.case / "PROGRESS.jsonl").read_bytes())

    def test_issue_draft_does_not_overwrite_user_work_and_export_retry_is_idempotent(self):
        self.record()
        output = self.project / "feedback-share"
        output.mkdir()
        draft = output / "issue-draft.md"
        draft.write_text("User-authored issue draft\n")
        with self.assertRaisesRegex(ValueError, "unrelated issue draft"):
            feedback.export_report(self.project, self.case, output)
        self.assertEqual(draft.read_text(), "User-authored issue draft\n")
        self.assertFalse((output / "usage-feedback.json").exists())
        draft.unlink()
        first = feedback.export_report(self.project, self.case, output)
        paths = [Path(first[key]) for key in ("json", "markdown", "issue_draft")]
        before = [(p.read_bytes(), p.stat().st_mtime_ns) for p in paths]
        second = feedback.export_report(self.project, self.case, output)
        self.assertFalse(second["changed"])
        self.assertEqual(before, [(p.read_bytes(), p.stat().st_mtime_ns) for p in paths])

    def test_export_preserves_reproduction_steps_added_to_generated_issue_draft(self):
        self.record()
        result = feedback.export_report(self.project, self.case, "feedback-share")
        draft = Path(result["issue_draft"])
        user_edit = draft.read_text() + "\nMinimal steps supplied by user: open scene, select object, import.\n"
        draft.write_text(user_edit)
        original_json = Path(result["json"]).read_bytes()
        original_markdown = Path(result["markdown"]).read_bytes()
        with self.assertRaisesRegex(ValueError, "Issue draft was edited"):
            feedback.export_report(self.project, self.case, "feedback-share")
        self.assertEqual(draft.read_text(), user_edit)
        self.assertEqual(Path(result["json"]).read_bytes(), original_json)
        self.assertEqual(Path(result["markdown"]).read_bytes(), original_markdown)
        refreshed = feedback.export_report(self.project, self.case, "feedback-share-new")
        self.assertTrue(Path(refreshed["issue_draft"]).is_file())

    def test_feedback_refresh_failure_does_not_undo_committed_progress(self):
        event = {**self.event, "type": "failure", "summary": "Synthetic import failure"}
        with patch.object(feedback, "refresh", side_effect=OSError("synthetic report disk error")):
            result = self.update(event)
        self.assertTrue(result["ok"])
        self.assertFalse(result["usage_feedback"]["ok"])
        self.assertEqual(core.read(self.case / "PLAN.json")["revision"], 2)
        self.assertEqual(len((self.case / "PROGRESS.jsonl").read_text().splitlines()), 2)

    def test_feedback_summary_failure_does_not_block_original_focus(self):
        with patch.object(feedback, "focus_summary", side_effect=ValueError("synthetic feedback corruption")):
            result = continuity.derive_focus(self.project, self.case)
        self.assertTrue(result["ok"])
        self.assertEqual(result["objective"], "Two playable styles")
        self.assertFalse(result["usage_feedback"]["ok"])

    def test_recurring_failure_reopens_verified_issue_and_preserves_failure_stage(self):
        before = self.receipt("evidence/before.json", {"phase": "before", "passed": False})
        after = self.receipt("evidence/after.json", {"phase": "after", "passed": True})
        holdout = self.receipt("evidence/holdout.json", {"phase": "holdout", "passed": True})
        self.record(self.observation(type="regression", project_status="fixed", skill_status="verified",
            regression={"before": before, "after": after, "holdout": holdout}))
        self.assertEqual(feedback.focus_summary(self.project, self.case)["total_unresolved"], 0)
        recurring = self.observation("obs-2", stage="b/native")
        recurring.pop("project_status")
        recurring.pop("skill_status")
        self.record(recurring)
        self.update(changes={"current_stage": "shared/delivery"})
        report = feedback.build_recap(self.project, self.case)
        issue = report["issues"][0]
        self.assertEqual((issue["project_status"], issue["skill_status"]), ("open", "untriaged"))
        self.assertEqual([event["stage"] for event in issue["events"]], ["a/references", "b/native"])
        self.assertEqual(issue["stage"], "b/native")
        self.assertEqual(report["regression_candidates"][0]["stage"], "b/native")
        self.assertEqual(feedback.focus_summary(self.project, self.case)["total_unresolved"], 1)
        exported = feedback.export_report(self.project, self.case, "exports")
        self.assertIn("b/native", Path(exported["markdown"]).read_text())

    def test_broken_approved_input_can_be_reported_without_relaxing_production_validation(self):
        asset = self.receipt("evidence/approved.json", {"original": True})
        self.update(changes={"references": {"workflow": "workflow.json", "approved_inputs": [asset], "ledgers": []}})
        core.write(self.project / asset["path"], {"changed": True})
        original = core.read(self.case / "PLAN.json")
        result = self.record(self.observation(issue_id="stale-input", actual="Approved input no longer matches"))
        self.assertTrue(result["ok"])
        self.assertFalse(result["production_context_validated"])
        current = core.read(self.case / "PLAN.json")
        for key in set(original) - {"revision", "progress_seq"}:
            self.assertEqual(current[key], original[key])
        with self.assertRaisesRegex(ValueError, "Approved input"):
            self.update()
        with self.assertRaisesRegex(ValueError, "Approved input"):
            continuity.derive_focus(self.project, self.case)
        self.assertEqual(feedback.build_recap(self.project, self.case)["issues"][0]["issue_id"], "stale-input")

    def test_missing_checkpoint_can_be_reported_but_cannot_resume_work(self):
        last_hash = core.file_hash(self.workflow)
        self.workflow.unlink()
        result = self.record(self.observation(issue_id="missing-checkpoint"), checkpoint=last_hash)
        self.assertTrue(result["ok"])
        self.assertFalse(result["checkpoint_available"])
        with self.assertRaisesRegex(ValueError, "workflow is missing"):
            continuity.derive_focus(self.project, self.case)
        with self.assertRaises(ValueError):
            continuity.record_observation(self.project, self.case, "integrator", 2, last_hash,
                {**self.event, "type": "decision_reference"})

    def test_meaningful_events_and_stage_change_refresh_after_commit(self):
        cases = [
            ({**self.event, "type": "failure"}, None),
            ({**self.event, "type": "review"}, None),
            ({**self.event, "type": "handoff"}, None),
            ({**self.event, "type": "pause"}, {"status": "paused"}),
            ({**self.event, "type": "completed"}, {"status": "complete"}),
            ({**self.event, "type": "change"}, {"current_stage": "shared/concepts"}),
        ]
        for event, changes in cases:
            with self.subTest(event=event["type"], changes=changes):
                prior = core.read(self.case / "PLAN.json")["revision"]
                def observe_commit(project, case, verify_artifacts=True):
                    self.assertFalse(verify_artifacts)
                    self.assertEqual(core.read(Path(case) / "PLAN.json")["revision"], prior + 1)
                    self.assertFalse((Path(case) / ".progress-transaction.json").exists())
                    return {"ok": True, "fixture": True}
                with patch.object(feedback, "refresh", side_effect=observe_commit) as refresh:
                    result = self.update(event, changes)
                refresh.assert_called_once()
                self.assertTrue(result["usage_feedback"]["ok"])


if __name__ == "__main__":
    unittest.main()
