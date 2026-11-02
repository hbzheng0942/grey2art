"""Offline task entry, resume and original-ledger routing behavior."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1] / "skills/greybox-to-multistyle-art"
sys.path.insert(0, str(ROOT / "runtime"))
from greybox import continuity, core, task_context, task_context_cli


def package(root, version="0.7.0-alpha.1"):
    root.mkdir(parents=True, exist_ok=True)
    (root / "scripts").mkdir(exist_ok=True)
    (root / "scripts/greybox.py").write_text("import sys\nprint('fixture:' + repr(sys.argv[1:]))\n")
    rows = [{"path": "scripts/greybox.py", "bytes": (root / "scripts/greybox.py").stat().st_size,
             "sha256": core.file_hash(root / "scripts/greybox.py")}]
    core.write(root / "MANIFEST.json", {"name": "greybox-to-multistyle-art", "version": version,
               "files": rows, "sourceManifestSHA256": core.digest(rows)})


class TaskContextTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="task-context-offline-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.project = self.root / "game"
        self.project.mkdir()
        (self.project / "project.godot").write_text("config_version=5\n")
        self.skill = self.root / "skill"
        package(self.skill)
        self.skill_patch = patch.object(task_context, "SKILL", self.skill)
        self.skill_patch.start()
        self.addCleanup(self.skill_patch.stop)
        self.entries_patch = patch.object(task_context, "installed_entries", return_value=[])
        self.entries_patch.start()
        self.addCleanup(self.entries_patch.stop)
        self.report = {"host": "workbuddy", "session_id": "session-a", "model": "explicit-model-a",
                       "tool_schema_sha256": "a" * 64, "source_ref": "fixture-host-report"}
        self.case = self.project / "art/case-a"
        core.write(self.project / "workflow.json", {"schema": 2, "kind": "greybox-art-workflow", "selected_styles": ["a"],
            "stages": [{"id": "baseline", "scope": "shared", "status": "draft", "evidence": []}]})
        self.plan = {"case_id": "case-a", "writer": "integrator", "objective": "Two complete playable styles",
            "current_stage": "shared/baseline", "status": "active", "constraints": ["Preserve original tasks"],
            "quality_floor": ["Complete native composition"], "remaining": ["Finish baseline"], "proposals": [],
            "references": {"workflow": "workflow.json", "ledgers": [], "approved_inputs": []}}
        self.event = {"type": "requirement", "summary": "Actual fixture task", "scope": "case",
                      "source_ref": "fixture-user", "evidence": []}
        continuity.initialize(self.project, self.case, self.plan, self.event)

    def pin(self, report=None, revision=1):
        return task_context.pin(self.project, self.case, self.report if report is None else report,
            writer="integrator", expected_revision=revision,
            checkpoint_sha256=core.file_hash(self.project / "workflow.json"), source_ref="fixture-host-switch")

    def test_pin_records_actual_entry_and_preserves_plan_and_original_ledger(self):
        ledger = self.project / "old/run.json"
        core.write(ledger, {"schema": 1, "kind": "greybox-art-run", "assets": {"a": {"task_id": "original-task"}},
                            "approval": {"source_ref": "actual-prior-approval"}})
        previous = ledger.read_bytes()
        plan = core.read(self.case / "PLAN.json")
        continuity.update(self.project, self.case, "integrator", 1, core.file_hash(self.project / "workflow.json"),
                          self.event, {"references": {**plan["references"], "ledgers": ["old/run.json"]}})
        result = self.pin(revision=2)
        context = result["execution_context"]
        self.assertEqual(context["package"]["entry"], str(self.skill / "scripts/greybox.py"))
        self.assertEqual(context["python"]["executable"], str(Path(sys.executable).absolute()))
        saved = core.read(self.case / "PLAN.json")
        self.assertEqual(saved["objective"], self.plan["objective"])
        self.assertEqual(saved["remaining"], self.plan["remaining"])
        self.assertEqual(saved["revision"], 3)
        self.assertEqual(ledger.read_bytes(), previous)
        self.assertFalse(result["paid_work_authorized"])
        checked = task_context.inspect(self.project, self.case, self.report)
        self.assertEqual(checked["routes"][0]["route"], "legacy_core")

    def test_unchanged_context_passes_without_claiming_actual_invocation(self):
        self.pin()
        result = task_context.inspect(self.project, self.case, {**self.report, "source_ref": "new-observation-same-session"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["check"]["changed"], [])
        self.assertEqual(result["provider_calls"], 0)
        self.assertFalse(result["check"]["paid_work_authorized"])

    def test_stale_revision_cannot_repin_or_append_progress(self):
        self.pin()
        before = (self.case / "PROGRESS.jsonl").read_bytes()
        with self.assertRaisesRegex(ValueError, "Stale plan revision"):
            self.pin({**self.report, "session_id": "new-session"})
        self.assertEqual((self.case / "PROGRESS.jsonl").read_bytes(), before)

    def test_unknown_model_and_schema_remain_unknown(self):
        report = {"host": "workbuddy", "session_id": "session-a", "source_ref": "host-report-no-model"}
        result = self.pin(report)
        self.assertIsNone(result["execution_context"]["session"]["model"])
        checked = task_context.inspect(self.project, self.case, report)
        self.assertTrue(checked["ok"])
        self.assertEqual(checked["check"]["unknown_session_fields"], ["model", "tool_schema_sha256"])
        self.assertFalse(checked["check"]["session_identity_fully_observed"])

    def test_known_to_unknown_or_model_switch_requires_recheck(self):
        self.pin()
        for value in (None, "different-model"):
            result = task_context.inspect(self.project, self.case, {**self.report, "model": value})
            self.assertFalse(result["ok"])
            self.assertIn("session.model", result["check"]["changed"])
            self.assertIn("Refresh current-session", result["check"]["revalidate"][0])

    def test_capture_does_not_guess_model_or_host_from_environment(self):
        with patch.dict("os.environ", {"MODEL": "inferred-wrong", "CODEX_SESSION_ID": "inferred-wrong"}):
            captured = task_context.capture(self.project)
        self.assertTrue(all(captured["session"][key] is None for key in task_context.SESSION_FIELDS))
        with self.assertRaisesRegex(ValueError, "current host and session"):
            self.pin({})

    def test_explicit_identity_needs_source_reference(self):
        with self.assertRaisesRegex(ValueError, "source_ref"):
            task_context.capture(self.project, {"host": "codex", "model": "unsourced"})

    def test_python_identity_preserves_venv_launcher_instead_of_resolving_to_base(self):
        launcher = self.root / "venv/bin/python"
        launcher.parent.mkdir(parents=True)
        launcher.symlink_to(sys.executable)
        with patch.object(sys, "executable", str(launcher)), patch.object(sys, "prefix", str(self.root / "venv")):
            context = task_context.capture(self.project, self.report)
        self.assertEqual(context["python"]["executable"], str(launcher))
        self.assertEqual(context["python"]["prefix"], str(self.root / "venv"))

    def test_package_edit_without_manifest_refresh_is_detected(self):
        self.pin()
        with (self.skill / "scripts/greybox.py").open("a") as out:
            out.write("# new source\n")
        result = task_context.inspect(self.project, self.case, self.report)
        self.assertFalse(result["ok"])
        self.assertIn("package.integrity", result["check"]["changed"])
        self.assertIn("package.actual_source_sha256", result["check"]["changed"])
        with self.assertRaisesRegex(ValueError, "manifest"):
            self.pin(revision=2)

    def test_competing_installs_are_read_without_invocation_or_modification(self):
        self.entries_patch.stop()
        older = self.root / ".workbuddy/skills/greybox-to-multistyle-art"
        recent = self.root / ".codex/skills/greybox-to-multistyle-art"
        package(older, "0.6.0-alpha.1")
        package(recent, "0.7.0-alpha.1")
        broken = self.root / ".agents/skills/greybox-to-multistyle-art"
        broken.mkdir(parents=True)
        core.write(broken / "MANIFEST.json", ["broken-manifest"])
        with patch.object(task_context.subprocess, "run") as invoked:
            entries = task_context.installed_entries(home=self.root)
        self.assertEqual({row["version"] for row in entries if "version" in row}, {"0.6.0-alpha.1", "0.7.0-alpha.1"})
        self.assertTrue(any("error" in row for row in entries))
        self.assertTrue(all(not row["invoked"] for row in entries))
        self.assertTrue(all(row["integrity"] == "not_checked" for row in entries if "integrity" in row))
        invoked.assert_not_called()

    def test_project_container_resolves_actual_engine_root(self):
        captured = task_context.capture(self.root, self.report)
        self.assertEqual(captured["project"]["root"], str(self.project))

    def test_foreign_project_context_cannot_be_written_to_plan(self):
        other = self.root / "other"
        other.mkdir()
        (other / "project.godot").write_text("config_version=5\n")
        context = task_context.capture(other, self.report)
        with self.assertRaisesRegex(ValueError, "another project"):
            continuity.update(self.project, self.case, "integrator", 1, core.file_hash(self.project / "workflow.json"),
                              self.event, {"execution_context": context})

    def test_ledger_schema_routes_original_jobs_and_never_uses_filename_alone(self):
        cases = [({"schema": 1, "kind": "greybox-art-run"}, "legacy_core", None),
                 ({"schema": 1, "kind": "supplier-job-run"}, "executor", "supplier"),
                 ({"schema": "greybox.image-job/v1"}, "executor", "image"),
                 ({"schema": "greybox.native-job/v1"}, "executor", "native"),
                 ({"schema": 1, "kind": "greybox-execution-queue"}, "executor_queue", None),
                 ({"task_id": "unknown-shape"}, "unknown", None)]
        for data, route, backend in cases:
            name = "supplier-run.json" if backend == "supplier" else "job.json" if backend else "run.json"
            path = self.project / name
            core.write(path, data)
            before = path.read_bytes()
            result = task_context.ledger_route(path)
            self.assertEqual((result["route"], result["backend"]), (route, backend))
            self.assertFalse(result["migration_performed"])
            self.assertEqual(path.read_bytes(), before)

    def test_recognized_schema_at_wrong_filename_does_not_claim_executable_route(self):
        path = self.project / "old-custom-file.json"
        core.write(path, {"schema": 1, "kind": "supplier-job-run"})
        result = task_context.ledger_route(path)
        self.assertEqual(result["route"], "unsupported_location")
        self.assertIsNone(result["backend"])

    def test_legacy_focus_remains_readable_and_pinned_focus_requires_current_check(self):
        focus = continuity.derive_focus(self.project, self.case)
        self.assertIsNone(focus["execution_context"]["pinned"])
        self.pin()
        focus = continuity.derive_focus(self.project, self.case)
        self.assertEqual(focus["execution_context"]["pinned"]["session"]["session_id"], "session-a")
        self.assertFalse(focus["execution_context"]["current_session_checked"])

    def test_guard_runs_only_exact_python_and_skill_entry(self):
        self.pin()
        with patch.object(task_context.subprocess, "run", return_value=subprocess.CompletedProcess([], 7)) as launched:
            code = task_context.run(self.project, self.case, ["status", "--run-dir", "original"], self.report)
        self.assertEqual(code, 7)
        argv = launched.call_args.args[0]
        self.assertEqual(argv[:2], [str(Path(sys.executable).absolute()), str(self.skill / "scripts/greybox.py")])
        self.assertEqual(argv[2:], ["status", "--run-dir", "original"])
        self.assertEqual(launched.call_args.kwargs["cwd"], str(self.project))

    def test_guard_drift_and_unpinned_case_never_launch(self):
        with patch.object(task_context.subprocess, "run") as launched:
            with self.assertRaisesRegex(ValueError, "unpinned or changed"):
                task_context.run(self.project, self.case, ["status"], self.report)
            self.pin()
            with self.assertRaisesRegex(ValueError, "unpinned or changed"):
                task_context.run(self.project, self.case, ["status"], {**self.report, "session_id": "b"})
        launched.assert_not_called()

    def test_guard_rejects_forwarded_project_override_and_recursive_guard(self):
        self.pin()
        with patch.object(task_context.subprocess, "run") as launched:
            for args in (["host", "setup", "--project", str(self.root)], ["task-context", "pin"]):
                with self.assertRaises(ValueError):
                    task_context.run(self.project, self.case, args, self.report)
        launched.assert_not_called()

    def test_cli_run_forwards_arguments_after_separator(self):
        report_file = self.project / "session.json"
        core.write(report_file, self.report)
        with patch.object(task_context, "run", return_value=0) as run:
            code = task_context_cli.main(["run", "--project", str(self.project), "--case", str(self.case),
                "--session-report", str(report_file), "--", "image", "status", "--local", "--job-dir", "original-job"])
        self.assertEqual(code, 0)
        self.assertEqual(run.call_args.args[2], ["image", "status", "--local", "--job-dir", "original-job"])

    def test_guard_rejects_argparse_project_abbreviations_before_launch(self):
        self.pin()
        with patch.object(task_context.subprocess, "run") as launched:
            for option in ("--proj", "--proje", "--p"):
                for args in (["workspace", "paths", option, str(self.root)],
                             ["workspace", "paths", option + "=" + str(self.root)]):
                    with self.subTest(args=args), self.assertRaisesRegex(ValueError, "abbreviated"):
                        task_context.run(self.project, self.case, args, self.report)
            launched.assert_not_called()


if __name__ == "__main__":
    unittest.main()
