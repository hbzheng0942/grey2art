"""Feedback is discoverable from first use without changing production authority."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1] / "skills/greybox-to-multistyle-art"
sys.path.insert(0, str(ROOT / "runtime"))
from greybox import continuity, core


class FeedbackEntrypointTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="feedback-entrypoints-")
        self.addCleanup(temporary.cleanup)
        self.project = Path(temporary.name)
        self.case = self.project / "art/case-a"
        core.write(self.project / "workflow.json", {
            "schema": 2, "kind": "greybox-art-workflow", "selected_styles": ["a"],
            "stages": [{"id": "baseline", "scope": "shared", "status": "draft", "evidence": []}],
        })
        self.plan = {
            "case_id": "case-a", "writer": "integrator", "objective": "Playable art",
            "current_stage": "shared/baseline", "status": "active", "constraints": [],
            "quality_floor": [], "remaining": ["Baseline"], "proposals": [],
            "references": {"workflow": "workflow.json", "ledgers": [], "approved_inputs": []},
        }
        self.event = {"type": "requirement", "summary": "Synthetic task", "scope": "case",
                      "source_ref": "fixture-message", "evidence": []}

    def initialize(self):
        return continuity.initialize(self.project, self.case, self.plan, self.event)

    def test_first_case_has_feedback_entrypoint_and_unknown_coverage(self):
        result = self.initialize()
        self.assertTrue(result["usage_feedback"]["ok"])
        report_path = Path(result["usage_feedback"]["recap_json"])
        report = json.loads(report_path.read_text())
        self.assertEqual(report["coverage"]["observation_count"], 0)
        self.assertEqual(report["coverage"]["host_transcript"], "not_collected")
        self.assertFalse(report["coverage"]["artifact_evidence_checked"])
        self.assertEqual(core.read(self.case / "PLAN.json")["revision"], 1)

    def test_focus_exposes_report_paths_without_writing_or_granting_authority(self):
        self.initialize()
        before = {p: p.read_bytes() for p in self.case.rglob("*") if p.is_file()}
        result = continuity.derive_focus(self.project, self.case)["usage_feedback"]
        self.assertTrue(result["report_available"])
        self.assertTrue(Path(result["recap_markdown"]).is_file())
        self.assertTrue(Path(result["recap_json"]).is_file())
        self.assertIn("unknown", result["capture"])
        self.assertEqual(before, {p: p.read_bytes() for p in self.case.rglob("*") if p.is_file()})

    def test_report_failure_does_not_undo_initialized_case(self):
        with patch("greybox.feedback.refresh", side_effect=OSError("Synthetic report failure")):
            result = self.initialize()
        self.assertTrue(result["ok"])
        self.assertFalse(result["usage_feedback"]["ok"])
        self.assertEqual(core.read(self.case / "PLAN.json")["status"], "active")
        self.assertTrue((self.case / "PROGRESS.jsonl").is_file())
