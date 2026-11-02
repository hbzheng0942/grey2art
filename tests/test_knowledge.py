"""Stage navigation, on-demand reads and observational FOCUS compatibility."""
import contextlib
import io
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
from greybox import continuity, core, knowledge


class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="knowledge-offline-")
        self.root = Path(self.temp.name) / "skill"
        (self.root / "schemas").mkdir(parents=True)
        (self.root / "references").mkdir()
        self.index = {"schema": 1, "kind": "greybox-knowledge-index",
                      "workflow_stages": {"directions": "concept"},
                      "stages": {"concept": {"aliases": ["H1"], "read": ["references/concept.md"],
                                             "topics": ["optional"], "review_questions": ["Which actual image?"],
                                             "command_hints": ["python scripts/greybox.py image --help"]}},
                      "topics": {"optional": {"read": ["references/optional.md"]}}}
        (self.root / "references/concept.md").write_text("A small concept example.\n", encoding="utf-8")
        (self.root / "references/optional.md").write_text("Optional detail.\n", encoding="utf-8")
        self.write_index()

    def tearDown(self):
        self.temp.cleanup()

    def write_index(self):
        (self.root / knowledge.INDEX).write_text(json.dumps(self.index), encoding="utf-8")

    def test_navigation_reads_index_only_not_reference_text_or_optional_files(self):
        original = Path.read_text
        def only_index(path, *args, **kwargs):
            self.assertEqual(path, (self.root / knowledge.INDEX).resolve())
            return original(path, *args, **kwargs)
        # A missing optional file is not a reason to read unrelated detail or
        # block the current stage. Explicitly requesting it must fail below.
        (self.root / "references/optional.md").unlink()
        with patch.object(Path, "read_text", only_index), patch.object(Path, "read_bytes", side_effect=AssertionError("text not requested")):
            result = knowledge.navigation("style-a/directions", root=self.root)
        self.assertTrue(result["ok"])
        self.assertEqual([x["path"] for x in result["read_next"]], ["references/concept.md"])
        self.assertFalse(result["reading_bytes"]["unselected_topics_loaded"])
        with self.assertRaisesRegex(ValueError, "missing"):
            knowledge.navigation("H1", topics=["optional"], root=self.root)

    def test_unknown_stage_never_defaults_to_execution(self):
        for stage in (None, "", "make something nice", "asset/build", "../../production", "new/H99"):
            with self.subTest(stage=stage):
                result = knowledge.navigation(stage, root=self.root)
                self.assertFalse(result["ok"])
                self.assertIsNone(result["stage"])
                self.assertEqual(result["read_next"], [])
                self.assertEqual(result["command_hints"], [])
                self.assertEqual(result["stage_choices"], ["concept"])

    def test_asset_category_adds_required_guidance_without_loading_other_categories(self):
        self.index["asset_categories"] = {"humanoid": {"read_by_stage": {"concept": ["references/optional.md"]}},
                                          "prop": {"read_by_stage": {}}}
        self.write_index()
        human = knowledge.navigation("concept", asset_category="humanoid", root=self.root)
        prop = knowledge.navigation("concept", asset_category="prop", root=self.root)
        self.assertEqual(len(human["read_next"]), 2)
        self.assertEqual(len(prop["read_next"]), 1)
        self.assertEqual(human["reading_bytes"]["required"], human["reading_bytes"]["selected_total"])
        self.assertFalse(human["paid_work_authorized"])
        bad = knowledge.navigation("concept", asset_category="unknown", root=self.root)
        self.assertFalse(bad["ok"])
        self.assertEqual(bad["read_next"], [])

    def test_asset_category_cannot_escape_package_or_reference_unknown_stage(self):
        self.index["asset_categories"] = {"humanoid": {"read_by_stage": {"concept": ["../private.md"]}}}
        self.write_index()
        with self.assertRaises(ValueError):
            knowledge.navigation("concept", asset_category="humanoid", root=self.root)
        self.index["asset_categories"]["humanoid"]["read_by_stage"] = {"unknown": []}
        self.write_index()
        with self.assertRaises(ValueError):
            knowledge.navigation("concept", root=self.root)

    def test_requested_topic_is_exact_and_deduplicated(self):
        result = knowledge.navigation("h1", topics=["optional", "optional"], root=self.root)
        self.assertEqual(len(result["read_next"]), 2)
        self.assertEqual(result["reading_bytes"]["selected_total"],
                         sum(p.stat().st_size for p in (self.root / "references").glob("*.md")))
        result = knowledge.navigation("concept", topics=["../../secret"], root=self.root)
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "topic_required")
        self.assertEqual(result["read_next"], [])

    def test_path_traversal_absolute_paths_and_symlink_escapes_rejected(self):
        outside = self.root.parent / "private.md"
        outside.write_text("PRIVATE", encoding="utf-8")
        (self.root / "references/escape.md").symlink_to(outside)
        for path in ("../private.md", str(outside), "references/../../private.md", "references/escape.md", "references\\escape.md"):
            self.index["stages"]["concept"]["read"] = [path]
            self.write_index()
            with self.subTest(path=path), self.assertRaises(ValueError):
                knowledge.navigation("concept", root=self.root)

    def test_engine_selection_never_loads_unrelated_engine(self):
        result = knowledge.navigation("H4", engine="godot")
        self.assertNotIn("references/unity-runtime.md", [x["path"] for x in result["read_next"]])
        result = knowledge.navigation("H4", engine="unity")
        self.assertIn("references/unity-runtime.md", [x["path"] for x in result["read_next"]])
        with self.assertRaisesRegex(ValueError, "Unknown engine"):
            knowledge.navigation("H4", engine="unreal")

    def test_methods_are_direct_reads_and_protocols_remain_explicit_topics(self):
        references = knowledge.navigation("references")
        self.assertEqual([x["path"] for x in references["read_next"]],
                         ["references/asset-routes.md", "references/modeling-references.md"])
        protocol = knowledge.navigation("references", topics=["modeling-reference-protocol"])
        self.assertIn("references/modeling-reference-protocol.md", [x["path"] for x in protocol["read_next"]])
        delivery = knowledge.navigation("H5")
        self.assertEqual([x["path"] for x in delivery["read_next"]], ["references/human-decisions.md"])
        expanded = knowledge.navigation("H5", topics=["workflow"])
        self.assertIn("references/workflow-vnext.md", [x["path"] for x in expanded["read_next"]])

    def test_real_workflow_aliases_and_greybox_scope_are_explicit(self):
        from greybox import workflow
        index = knowledge._load(ROOT)
        self.assertEqual(set(index["workflow_stages"]), set(workflow.ROLES))
        for stage in workflow.ROLES:
            self.assertTrue(knowledge.navigation("style-a/" + stage)["ok"], stage)
        for stage, expected in (("H1", "concept"), ("H2", "spatial"), ("H3", "production"),
                                ("H4", "native"), ("H5", "delivery"), ("S6", "native"),
                                ("greybox/build", "greybox"), ("greybox/handoff", "greybox")):
            self.assertEqual(knowledge.navigation(stage)["stage"], expected)
        for i in range(11):
            self.assertTrue(knowledge.navigation("S" + str(i))["ok"])

    def test_audit_reports_inventory_separate_from_optional_reading_cost(self):
        (self.root / "references/orphan.md").write_text("An unrelated document.\n", encoding="utf-8")
        (self.root / "references/duplicate.md").write_bytes((self.root / "references/concept.md").read_bytes())
        result = knowledge.audit(self.root)
        self.assertTrue(result["ok"])
        self.assertIn("references/orphan.md", result["orphan_references"])
        self.assertEqual(result["duplicate_content"], [["references/concept.md", "references/duplicate.md"]])
        metrics = result["stage_reading_bytes"]["concept"]["common"]
        self.assertEqual(metrics["direct_read_bytes"], (self.root / "references/concept.md").stat().st_size)
        self.assertEqual(metrics["all_optional_additional_bytes"], (self.root / "references/optional.md").stat().st_size)
        self.assertGreater(result["inventory"]["reference_bytes"], metrics["direct_read_bytes"] + metrics["all_optional_additional_bytes"])

    def test_audit_finds_duplicate_routes_missing_links_and_invalid_index_paths(self):
        self.index["stages"]["concept"]["read"] *= 2
        self.index["topics"]["optional"]["read"] = ["../outside.md"]
        self.write_index()
        (self.root / "references/concept.md").write_text("[missing](missing.md) [outside](../../private.md)", encoding="utf-8")
        result = knowledge.audit(self.root)
        self.assertFalse(result["ok"])
        self.assertTrue(result["errors"])
        self.assertEqual(len(result["duplicate_routes"]), 1)
        self.assertEqual({x["reason"] for x in result["broken_links"]}, {"missing", "outside_package"})

    def test_audit_distinguishes_indirectly_linked_docs_from_orphans(self):
        (self.root / "references/linked.md").write_text("Only needed from the example.", encoding="utf-8")
        (self.root / "references/concept.md").write_text("[example](linked.md)", encoding="utf-8")
        result = knowledge.audit(self.root)
        self.assertIn("references/linked.md", result["unrouted_references"])
        self.assertNotIn("references/linked.md", result["orphan_references"])

    def test_duplicate_alias_is_not_silently_overwritten(self):
        self.index["stages"]["concept"]["aliases"].append("h1")
        self.write_index()
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            knowledge.navigation("H1", root=self.root)
        self.assertFalse(knowledge.audit(self.root)["ok"])

    def test_cli_help_and_missing_stage_are_nonexecuting(self):
        script = ROOT / "scripts/knowledge.py"
        help_result = subprocess.run([sys.executable, str(script), "--help"], capture_output=True, text=True)
        self.assertEqual(help_result.returncode, 0)
        result = subprocess.run([sys.executable, str(script), "next"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)["status"], "stage_required")


class KnowledgeFocusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="knowledge-focus-")
        self.project = Path(self.temp.name)
        self.case = "art/case"
        core.write(self.project / "workflow.json", {"schema": 2, "kind": "greybox-art-workflow",
                   "selected_styles": ["a"], "stages": [{"id": "baseline", "scope": "shared", "status": "draft", "evidence": []}]})
        self.plan = {"case_id": "case-a", "writer": "integrator", "objective": "Preserved task",
                     "current_stage": "shared/baseline", "status": "active", "constraints": [],
                     "quality_floor": [], "remaining": ["Baseline"], "proposals": [],
                     "references": {"workflow": "workflow.json", "ledgers": [], "approved_inputs": []}}
        self.event = {"type": "requirement", "summary": "Actual fixture task", "scope": "case",
                      "source_ref": "fixture-user-1", "evidence": []}
        continuity.initialize(self.project, self.case, self.plan, self.event)

    def tearDown(self):
        self.temp.cleanup()

    def snapshot(self):
        return {p.relative_to(self.project).as_posix(): p.read_bytes() for p in self.project.rglob("*") if p.is_file()}

    def test_focus_navigation_does_not_rewrite_ledger_or_resume_token(self):
        before = self.snapshot()
        result = continuity.derive_focus(self.project, self.case)
        self.assertEqual(result["learning"]["stage"], "intake")
        self.assertFalse(result["workflow_check"]["ok"])
        self.assertEqual(before, self.snapshot())
        with patch.object(knowledge, "navigation", side_effect=ValueError("broken documentation index")):
            degraded = continuity.derive_focus(self.project, self.case)
        self.assertEqual(degraded["learning"]["status"], "navigation_unavailable")
        for key in ("resume_token", "workflow_check", "next_action", "authorization_refs", "unknown_submissions"):
            self.assertEqual(degraded[key], result[key])
        self.assertEqual(before, self.snapshot())

    def test_case_cli_uses_observed_stage_and_preserves_existing_next_action(self):
        focus = continuity.derive_focus(self.project, self.case)
        before = self.snapshot()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            rc = knowledge.main(["next", "--project", str(self.project), "--case", self.case])
        result = json.loads(output.getvalue())
        self.assertEqual(rc, 0)
        self.assertEqual(result["stage"], "intake")
        self.assertEqual(result["case_next_action"], focus["next_action"])
        self.assertEqual(before, self.snapshot())

    def test_unknown_case_stage_remains_unknown_without_disabling_focus(self):
        token = continuity.derive_focus(self.project, self.case)["resume_token"]
        continuity.update(self.project, self.case, "integrator", 1, token["checkpoint_sha256"],
                          self.event, {"current_stage": "custom/not-yet-defined"})
        result = continuity.derive_focus(self.project, self.case)
        self.assertTrue(result["ok"])
        self.assertEqual(result["learning"]["status"], "stage_required")
        self.assertEqual(result["current_stage"], "custom/not-yet-defined")

    def test_case_cli_retains_observed_unity_engine_without_repeating_flag(self):
        from greybox import harness
        run = self.project / "runs/unity-greybox"
        case = "art/unity-case"
        harness.initialize(self.project, run, harness.starter(engine="unity"),
                           source_ref="fixture-user-unity")
        plan = {**self.plan, "case_id": "unity-case", "current_stage": "greybox/build",
                "references": {"workflow": str(run / "job.json"),
                               "ledgers": [str(run / "job.json")]}}
        continuity.initialize(self.project, case, plan, self.event)
        focus = continuity.derive_focus(self.project, case)
        self.assertEqual(focus["learning"]["engine"], "unity")
        before = self.snapshot()
        for flags, expected_engine in (([], "unity"), (["--engine", "godot"], "godot")):
            with self.subTest(flags=flags):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    rc = knowledge.main(["next", "--project", str(self.project), "--case", case,
                                         "--topic", "engine", *flags])
                result = json.loads(output.getvalue())
                self.assertEqual(rc, 0)
                self.assertEqual(result["engine"], expected_engine)
                paths = [item["path"] for item in result["read_next"]]
                self.assertEqual("references/unity-runtime.md" in paths, expected_engine == "unity")
                self.assertEqual(result["case_next_action"], focus["next_action"])
                self.assertEqual(before, self.snapshot())
                self.assertEqual(continuity.derive_focus(self.project, case)["resume_token"],
                                 focus["resume_token"])

    def test_interrupted_transaction_still_requires_original_recovery(self):
        token = continuity.derive_focus(self.project, self.case)["resume_token"]
        real_write = core.write
        def fail_plan(path, value):
            if Path(path).name == "PLAN.json":
                raise OSError("simulated interruption")
            return real_write(path, value)
        with patch.object(core, "write", side_effect=fail_plan), self.assertRaises(OSError):
            continuity.update(self.project, self.case, "integrator", 1, token["checkpoint_sha256"],
                              self.event, {"current_stage": "shared/directions"})
        with self.assertRaisesRegex(ValueError, "Interrupted"):
            continuity.derive_focus(self.project, self.case)
        continuity.recover(self.project, self.case, "integrator")
        result = continuity.derive_focus(self.project, self.case)
        self.assertEqual(result["learning"]["stage"], "concept")
        self.assertEqual(result["latest_event_seq"], 2)
        self.assertEqual(len((self.project / self.case / "PROGRESS.jsonl").read_text().splitlines()), 2)


if __name__ == "__main__":
    unittest.main()
