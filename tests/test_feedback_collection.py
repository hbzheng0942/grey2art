"""Offline collection keeps case identity, diagnosis and missing data distinct."""
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
from greybox import core, feedback_collection


class FeedbackCollectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="feedback-collection-offline-")
        self.addCleanup(self.temporary.cleanup)
        self.project = Path(self.temporary.name)

    def export(self, filename="inbox/a/usage-feedback.json", case_id="case-a", revision=1, issue_changes=None, **changes):
        issue = {"issue_id": "missing-master", "summary": "Approved input was omitted", "stage": "shared/references",
                 "mechanisms": ["reference-transfer"], "project_status": "open", "skill_status": "untriaged",
                 "is_defect_candidate": True, "context": {"host": "codex", "model": None, "engine": "godot"},
                 "events": [{"type": "failure", "skill": {"version": "0.14.0-alpha.1", "manifest_sha256": "a" * 64},
                             "context": {"host": "codex", "model": None, "engine": "godot"}}]}
        issue.update(issue_changes or {})
        report = {"schema": 1, "kind": "greybox-usage-feedback-export", "case_id": case_id,
                  "plan_revision": revision, "issues": [issue], "interventions": {"rescue": 2},
                  "coverage": {"observation_count": 1}, "uploaded": False}
        report.update(changes)
        core.write(self.project / filename, report)
        return report

    def manifest(self, entries):
        path = self.project / "collection-input.json"
        core.write(path, {"schema": 1, "kind": "greybox-feedback-collection-input", "exports": entries})
        return path

    def build(self, entries):
        return feedback_collection.build(self.project, self.manifest(entries))[0]

    def test_case_local_issue_ids_do_not_establish_shared_cause(self):
        self.export()
        self.export("inbox/b/usage-feedback.json", "case-b")
        report = self.build([{"sample_id": "sample-a", "path": "inbox/a/usage-feedback.json"},
                             {"sample_id": "sample-b", "path": "inbox/b/usage-feedback.json"}])
        self.assertEqual(report["sample_count"], 2)
        self.assertEqual(report["issue_count"], 2)
        self.assertEqual(report["known_unresolved_issues"], 2)
        self.assertEqual(report["confirmed_fingerprint_groups"], [])
        self.assertEqual(len(report["similarity_candidates"]), 1)
        self.assertEqual(report["similarity_candidates"][0]["basis"], "similar_stage_and_mechanisms_only")

    def test_explicit_fingerprints_group_different_issue_names(self):
        triage = {"category": "skill_guidance", "severity": "major", "fingerprint": "master-binding"}
        self.export(issue_changes={"triage": triage})
        self.export("inbox/b/usage-feedback.json", "case-b", issue_changes={"issue_id": "different-id", "triage": triage})
        report = self.build([{"sample_id": "sample-a", "path": "inbox/a/usage-feedback.json"},
                             {"sample_id": "sample-b", "path": "inbox/b/usage-feedback.json"}])
        self.assertEqual(report["confirmed_fingerprint_groups"][0]["sample_count"], 2)
        self.assertEqual(report["confirmed_fingerprint_groups"][0]["fingerprint"], "master-binding")
        self.assertEqual(report["similarity_candidates"], [])

    def test_maintainer_can_supply_grouping_without_modifying_export(self):
        self.export()
        before = (self.project / "inbox/a/usage-feedback.json").read_bytes()
        report = self.build([{"sample_id": "sample-a", "path": "inbox/a/usage-feedback.json",
                              "issue_fingerprints": {"missing-master": "confirmed-binding"}}])
        self.assertEqual(report["confirmed_fingerprint_groups"][0]["fingerprint"], "confirmed-binding")
        self.assertEqual(before, (self.project / "inbox/a/usage-feedback.json").read_bytes())

    def test_duplicate_content_even_reformatted_is_counted_once(self):
        original = self.export()
        (self.project / "copy.json").write_text(json.dumps(original, sort_keys=True), encoding="utf-8")
        report = self.build([{"sample_id": "sample-a", "path": "inbox/a/usage-feedback.json"},
                             {"sample_id": "other-name", "path": "copy.json"}])
        self.assertEqual(report["sample_count"], 1)
        self.assertEqual(report["known_rescue_episodes"], 2)
        self.assertEqual(report["duplicate_exports_skipped"], 1)

    def test_duplicate_export_with_conflicting_grouping_is_rejected(self):
        self.export()
        with self.assertRaisesRegex(ValueError, "conflicting declared fingerprints"):
            self.build([{"sample_id": "a", "path": "inbox/a/usage-feedback.json"},
                        {"sample_id": "a", "path": "inbox/a/usage-feedback.json", "issue_fingerprints": {"missing-master": "different"}}])

    def test_unknown_issue_fingerprint_override_is_rejected(self):
        self.export()
        with self.assertRaisesRegex(ValueError, "unknown issue"):
            self.build([{"sample_id": "a", "path": "inbox/a/usage-feedback.json",
                         "issue_fingerprints": {"typo-id": "same-mechanism"}}])

    def test_only_latest_revision_per_stable_sample_is_counted(self):
        self.export("old.json", revision=1)
        self.export("new.json", revision=3, issue_changes={"project_status": "fixed", "skill_status": "verified"})
        for entries in ([{"sample_id": "one", "path": "old.json"}, {"sample_id": "one", "path": "new.json"}],
                        [{"sample_id": "one", "path": "new.json"}, {"sample_id": "one", "path": "old.json"}]):
            with self.subTest(entries=entries):
                report = self.build(entries)
                self.assertEqual(report["sample_count"], 1)
                self.assertEqual(report["samples"][0]["plan_revision"], 3)
                self.assertEqual(report["superseded_exports_skipped"], 1)
                self.assertEqual(report["known_unresolved_issues"], 0)

    def test_same_revision_conflict_or_reused_sample_for_other_case_is_rejected(self):
        self.export("one.json")
        self.export("conflict.json", issue_changes={"summary": "Different snapshot"})
        self.export("other.json", case_id="case-b", revision=2)
        for filename in ("conflict.json", "other.json"):
            with self.subTest(filename=filename), self.assertRaises(ValueError):
                self.build([{"sample_id": "one", "path": "one.json"}, {"sample_id": "one", "path": filename}])

    def test_missing_metrics_and_status_stay_unknown(self):
        self.export(interventions={}, coverage={}, issue_changes={"project_status": None, "skill_status": None})
        report = self.build([{"sample_id": "one", "path": "inbox/a/usage-feedback.json"}])
        self.assertIsNone(report["known_rescue_episodes"])
        self.assertEqual(report["samples_missing_rescue_measurement"], 1)
        self.assertIsNone(report["samples"][0]["observation_count"])
        self.assertEqual(report["unknown_issue_status_count"], 1)
        self.assertIsNone(report["cost_totals"])
        self.assertIn("unknown", feedback_collection.markdown(report))

    def test_project_workaround_does_not_close_skill_issue(self):
        self.export(issue_changes={"project_status": "fixed", "skill_status": "untriaged"})
        report = self.build([{"sample_id": "one", "path": "inbox/a/usage-feedback.json"}])
        self.assertEqual(report["known_unresolved_issues"], 1)

    def test_creative_decision_is_not_an_unresolved_defect(self):
        self.export(issue_changes={"is_defect_candidate": False})
        report = self.build([{"sample_id": "one", "path": "inbox/a/usage-feedback.json"}])
        self.assertEqual(report["known_unresolved_issues"], 0)

    def test_packages_and_environments_are_preserved_and_private_text_is_redacted(self):
        self.export(issue_changes={"summary": "Failure at /private/project secret=not-for-sharing https://private.example/asset"})
        report = self.build([{"sample_id": "one", "path": "inbox/a/usage-feedback.json"}])
        issue = report["samples"][0]["issues"][0]
        self.assertEqual(issue["recorder_packages"][0]["manifest_sha256"], "a" * 64)
        self.assertEqual(issue["contexts"][0]["engine"], "godot")
        text = json.dumps(report)
        self.assertNotIn("/private/project", text)
        self.assertNotIn("not-for-sharing", text)
        self.assertNotIn("private.example", text)

    def test_collection_preserves_expected_actual_method_and_next_check(self):
        self.export(issue_changes={"expected": "Every page uses the approved master",
                                   "actual": "The side page omitted the master",
                                   "latest_method": "Bind the approved input before dispatch",
                                   "next_test": "Replay the side-page input contract",
                                   "events": [{"type": "attempt", "method": "Old request repair"},
                                              {"type": "attempt", "method": "Another request repair"}]})
        report = self.build([{"sample_id": "one", "path": "inbox/a/usage-feedback.json"}])
        issue = report["samples"][0]["issues"][0]
        self.assertEqual(issue["expected"], "Every page uses the approved master")
        self.assertEqual(issue["actual"], "The side page omitted the master")
        self.assertEqual(issue["latest_method"], "Bind the approved input before dispatch")
        self.assertEqual(issue["latest_method_source"], "reported_issue_summary")
        self.assertEqual(issue["attempt_count"], 2)
        text = feedback_collection.markdown(report)
        for content in (issue["expected"], issue["actual"], issue["latest_method"], issue["next_test"], "recorded attempts: 2"):
            self.assertIn(content, text)

    def test_legacy_export_derives_reported_method_without_inventing_missing_fields(self):
        self.export(issue_changes={"events": [{"type": "attempt", "method": "First method"},
                                              {"type": "attempt", "method": "Latest reported method"},
                                              {"type": "failure"}]})
        report = self.build([{"sample_id": "one", "path": "inbox/a/usage-feedback.json"}])
        issue = report["samples"][0]["issues"][0]
        self.assertEqual(issue["latest_method"], "Latest reported method")
        self.assertEqual(issue["latest_method_source"], "reported_event")
        self.assertIsNone(issue["expected"])
        self.assertIsNone(issue["actual"])
        self.assertIsNone(issue["next_test"])
        text = feedback_collection.markdown(report)
        self.assertIn("Expected: unknown → actual: unknown", text)
        self.assertIn("Latest method (reported_event): Latest reported method", text)
        self.assertIn("Next test: unknown", text)

    def test_invalid_or_oversized_input_is_rejected(self):
        self.export()
        valid = {"sample_id": "a", "path": "inbox/a/usage-feedback.json"}
        for changes in ({"sample_id": "../escape"}, {"issue_fingerprints": {"missing-master": "not a safe id"}}, {"path": "../outside.json"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.build([{**valid, **changes}])
        with patch.object(feedback_collection, "MAX_TOTAL_BYTES", 10), self.assertRaises(ValueError):
            self.build([valid])
        oversized = self.project / "too-large.json"
        oversized.write_text(" " * (feedback_collection.MAX_BYTES + 1))
        with self.assertRaisesRegex(ValueError, "too large"):
            self.build([{**valid, "path": "too-large.json"}])

    def test_input_symlink_escape_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="collection-outside-") as other:
            target = Path(other) / "outside.json"
            core.write(target, {})
            (self.project / "linked.json").symlink_to(target)
            with self.assertRaises(ValueError):
                self.build([{"sample_id": "a", "path": "linked.json"}])

    def test_collection_is_idempotent_and_never_overwrites_unrelated_files(self):
        self.export()
        path = self.manifest([{"sample_id": "a", "path": "inbox/a/usage-feedback.json"}])
        before = (self.project / "inbox/a/usage-feedback.json").read_bytes()
        first = feedback_collection.collect(self.project, path, "review")
        self.assertTrue(first["changed"])
        second = feedback_collection.collect(self.project, path, "review")
        self.assertFalse(second["changed"])
        self.assertFalse(second["uploaded"])
        self.assertEqual(before, (self.project / "inbox/a/usage-feedback.json").read_bytes())
        md = self.project / "review/collection.md"
        md.write_text("User notes", encoding="utf-8")
        with self.assertRaises(ValueError):
            feedback_collection.collect(self.project, path, "review")
        self.assertEqual(md.read_text(), "User notes")

    def test_input_cannot_be_collection_output(self):
        self.export("review/collection.json")
        path = self.manifest([{"sample_id": "a", "path": "review/collection.json"}])
        with self.assertRaisesRegex(ValueError, "overwrite input"):
            feedback_collection.collect(self.project, path, "review")

    def test_non_export_raw_case_ledgers_are_rejected(self):
        self.export("raw.json", kind="greybox-usage-recap")
        with self.assertRaisesRegex(ValueError, "feedback export"):
            self.build([{"sample_id": "a", "path": "raw.json"}])

    def test_cli_collect_needs_no_case_and_other_commands_still_need_case(self):
        self.export()
        path = self.manifest([{"sample_id": "a", "path": "inbox/a/usage-feedback.json"}])
        command = [sys.executable, str(ROOT / "scripts/greybox.py"), "feedback"]
        result = subprocess.run(command + ["collect", "--project", str(self.project), "--input", str(path), "--output", "review"],
                                capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertTrue(json.loads(result.stdout)["ok"])
        missing = subprocess.run(command + ["recap", "--project", str(self.project)], capture_output=True, text=True, timeout=15)
        self.assertEqual(missing.returncode, 2)
        self.assertIn("needs --case", json.loads(missing.stdout)["error"])


if __name__ == "__main__":
    unittest.main()
