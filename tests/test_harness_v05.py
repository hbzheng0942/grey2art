"""Fixture-only job/semantic contracts; these doubles are not native evidence."""
import copy
import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/greybox-to-multistyle-art/runtime"))
from greybox import cli, core, continuity, engines, harness, intake
from workflow_fixtures import png


class FixtureAdapter:
    """No engine is launched; emitted files exercise only common-layer invariants."""
    def build(self, project, plan, output, executable=None):
        root = Path(plan["_resource_root"])
        root.mkdir(parents=True)
        output.mkdir(parents=True)
        scene = root / "scene.tscn"
        scene.write_text('[gd_scene format=3]\n[node name="Scene" type="Node3D"]\n')
        (project / "project.godot").write_text('config_version=5\n[application]\nrun/main_scene="res://' + scene.relative_to(project).as_posix() + '"\n')
        return {"ok": True, "engine": "godot", "scene": "res://" + scene.relative_to(project).as_posix(),
                "source_files": [str(scene)], "entities": {e["id"]: {"role": e["role"],
                    "node_path": "Scene/" + e["id"], "visual_path": "Scene/" + e["id"] + "/Visual"} for e in plan["entities"]}}

    def run(self, project, scene, config, output, executable=None):
        output.mkdir(parents=True)
        frame = output / "frame.png"
        frame.write_bytes(png(6))
        return {"ok": True, "native": True, "engine": "godot", "scene": scene,
                "frames": [str(frame)], "entities": {e["id"]: {"role": e["role"], "node_path": "Scene/" + e["id"],
                    "visual_path": "Scene/" + e["id"] + "/Visual"} for e in core.read(next(project.glob(".greybox-work/*/build-plan.json")))["entities"]},
                "checks": [{"name": n, "key": key, "passed": True, "actual": actual} for n, key, actual in
                           (("walk", "player_moved", True), ("complete", "objective_complete", True), ("reset", "restart_count", 1))],
                "test_double": True}

    def launch(self, *args):
        return {"ok": True, "test_double": True}


class HarnessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="greybox-harness-contract-")
        self.project = Path(self.temp.name) / "project"
        self.run = self.project / ".greybox-work/sample"
        self.plan = harness.starter(plan_id="sample")
        self.plan["validation"] = {"required_checks": ["walk", "complete", "reset"],
                                   "coverage": {"input": ["walk"], "loop": ["complete"], "reset": ["reset"]}}
        self.adapter = FixtureAdapter()
        self.patch = patch.object(harness, "_adapter", return_value=self.adapter)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def initialize(self):
        return harness.initialize(self.project, self.run, self.plan, source_ref="user:fixture-only")

    def built(self):
        self.initialize()
        return harness.build(self.run)

    def validated(self):
        self.built()
        return harness.validate(self.run)

    def test_init_has_no_styles_or_image_gates(self):
        result = self.initialize()
        self.assertTrue(result["ok"])
        self.assertFalse((self.run / "PLAN.json").exists())
        self.assertEqual(core.read(self.run / "job.json")["phase"], "initialized")

    def test_init_does_not_overwrite_prior_job(self):
        self.initialize()
        before = (self.run / "job.json").read_bytes()
        with self.assertRaises(core.WorkflowError):
            self.initialize()
        self.assertEqual((self.run / "job.json").read_bytes(), before)

    def test_native_build_has_semantic_map_and_owned_scene(self):
        self.built()
        state = core.read(self.run / "job.json")
        self.assertEqual(set(state["artifact"]["entities"]), {"floor", "token", "exit"})
        self.assertTrue(core.resolve_input(state["artifact"]["scene"], self.project).is_file())

    def test_existing_revision_is_not_overwritten(self):
        self.built()
        with self.assertRaisesRegex(core.WorkflowError, "revision exists"):
            harness.build(self.run)

    def test_native_input_coverage_is_distinct_from_smoke(self):
        self.plan["validation"] = {"required_checks": [], "coverage": {}}
        result = self.validated()
        self.assertTrue(result["ok"])
        self.assertFalse(result["handoff_ready"])
        with self.assertRaisesRegex(core.WorkflowError, "coverage"):
            harness.handoff(self.run, self.run / "handoff.json")

    def test_reusing_a_move_check_cannot_prove_loop_and_reset(self):
        self.plan["validation"] = {"required_checks": ["walk"], "coverage": {
            "input": ["walk"], "loop": ["walk"], "reset": ["walk"]}}
        value = self.validated()
        self.assertFalse(value["handoff_ready"])
        self.assertEqual(value["coverage"]["unproven_areas"], ["loop", "reset"])

    def test_empty_initial_state_cannot_prove_a_completed_loop(self):
        native = self.adapter.run
        def run(*args, **kwargs):
            result = native(*args, **kwargs)
            result["checks"][1].update(actual=False, expected=False)
            return result
        with patch.object(self.adapter, "run", side_effect=run):
            self.assertFalse(self.validated()["handoff_ready"])

    def test_handoff_is_readable_by_old_scene_conventions(self):
        self.validated()
        path = self.run / "handoff.json"
        result = harness.handoff(self.run, path)
        self.assertTrue(result["ok"])
        manifest = core.read(path)
        engines.validate_scene({"engine": manifest["engine"], "contract": {"scene": manifest["scene"]}})
        request = {"schema": 1, "kind": "greybox-intake-request", "intent": "art", "source_ref": "user:new-art-task",
                   "baseline": path.relative_to(self.project).as_posix()}
        routed = intake.route(request, self.project)
        self.assertEqual(routed["action"], "existing_art_intake")
        self.assertFalse(result["art_authorized"])
        self.assertFalse(manifest["paid_work_authorized"])

    def test_file_change_stales_old_evidence(self):
        self.validated()
        artifact = core.read(self.run / "job.json")["artifact"]
        scene = core.resolve_input(artifact["scene"], self.project)
        scene.write_text(scene.read_text() + "\n; edit\n")
        self.assertTrue(harness.status(self.run)["stale"])
        with self.assertRaises(core.WorkflowError):
            harness.handoff(self.run, self.run / "handoff.json")

    def test_native_edit_can_be_revalidated_without_regeneration(self):
        self.built()
        artifact = core.read(self.run / "job.json")["artifact"]
        p = core.resolve_input(artifact["scene"], self.project)
        p.write_text(p.read_text() + "\n; local edit\n")
        self.assertTrue(harness.validate(self.run)["ok"])
        self.assertFalse(harness.status(self.run)["stale"])

    def test_plan_change_requires_explicit_new_build(self):
        self.built()
        plan = core.read(self.run / "build-plan.json")
        plan["player"]["speed"] = 7
        core.write(self.run / "build-plan.json", plan)
        self.assertTrue(harness.status(self.run)["stale"])
        with self.assertRaisesRegex(core.WorkflowError, "Plan changed"):
            harness.validate(self.run)

    def test_handoff_detects_corrupt_output_pixels(self):
        self.validated()
        target = self.run / "handoff.json"
        harness.handoff(self.run, target)
        evidence = core.read(core.read(target)["native_evidence"]["path"])
        Path(evidence["frames"][0]["path"]).write_bytes(b"corrupt")
        self.assertFalse(harness.inspect_handoff(target, self.project)["ok"])

    def test_failed_build_preserves_last_good_scene(self):
        self.validated()
        previous = core.read(self.run / "job.json")["artifact"]["scene"]
        plan = copy.deepcopy(self.plan)
        plan["player"]["speed"] = 6
        with patch.object(self.adapter, "build", side_effect=RuntimeError("fixture failure")):
            with self.assertRaises(RuntimeError):
                harness.build(self.run, plan)
        state = core.read(self.run / "job.json")
        self.assertEqual(state["artifact"]["scene"], previous)
        self.assertIsNotNone(state["last_verified"])
        self.assertEqual(state["phase"], "failed")

    def test_common_continuity_reads_same_job_and_resumes_same_endpoint(self):
        self.initialize()
        plan = {"case_id": "sample", "writer": "host", "objective": "Build a greybox", "status": "active",
                "constraints": [], "quality_floor": [], "current_stage": "greybox/build", "remaining": ["native build"],
                "proposals": [], "references": {"workflow": str(self.run / "job.json"), "ledgers": [str(self.run / "job.json")]}}
        event = {"type": "requirement", "summary": "Create local greybox", "source_ref": "user:fixture-only", "scope": "greybox"}
        continuity.initialize(self.project, self.run, plan, event)
        focus = continuity.derive_focus(self.project, self.run)
        self.assertEqual(focus["workflow_kind"], "greybox-harness-job")
        self.assertEqual(focus["stop_at"], "greybox")
        routed = intake.route({"schema": 1, "kind": "greybox-intake-request", "intent": "resume", "source_ref": "user:continue",
                               "case_dir": self.run.relative_to(self.project).as_posix()}, self.project)
        self.assertEqual(routed["action"], "resume_case")
        self.assertEqual(routed["stop_at"], "greybox")
        self.assertEqual(routed["engine"], "godot")

    def test_initialized_resume_keeps_engine_before_any_engine_project_exists(self):
        self.initialize()
        request = {"schema": 1, "kind": "greybox-intake-request", "intent": "resume", "source_ref": "user:continue",
                   "run_dir": self.run.relative_to(self.project).as_posix()}
        value = intake.route(request, self.project)
        self.assertEqual(value["engine"], "godot")
        self.assertEqual(value["stop_at"], "greybox")

    def test_front_branch_keeps_original_unknown_service_tasks_visible(self):
        self.initialize()
        original = self.run / "original-provider.json"
        core.write(original, {"state": "unknown", "task_id": "retained-original-task"})
        plan = {"case_id": "sample", "writer": "host", "objective": "Adjust current greybox", "status": "active",
                "constraints": [], "quality_floor": [], "current_stage": "greybox/build", "remaining": [], "proposals": [],
                "references": {"workflow": str(self.run / "job.json"), "ledgers": [str(original)]}}
        continuity.initialize(self.project, self.run, plan, {"type": "change", "summary": "Work on greybox locally",
            "source_ref": "user:fixture-scope-change", "scope": "greybox"})
        focus = continuity.derive_focus(self.project, self.run)
        self.assertEqual(focus["unknown_submissions"][0]["state"], "unknown")
        self.assertEqual(focus["original_ledger_refs"], [str(original)])

    def test_cli_relative_job_path_is_project_relative_on_init_and_resume(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = cli.main(["greybox", "init", "--project", str(self.project), "--run-dir", "runs/relative",
                             "--engine", "godot", "--id", "relative", "--source-ref", "user:relative-job"])
        self.assertEqual(code, 0)
        self.assertTrue((self.project / "runs/relative/job.json").is_file())
        result = intake.route({"schema": 1, "kind": "greybox-intake-request", "intent": "resume", "source_ref": "user:continue",
                               "run_dir": "runs/relative"}, self.project)
        self.assertEqual(result["action"], "resume_greybox")
        self.assertEqual(result["engine"], "godot")

    def test_spatial_goal_does_not_require_win_or_reset(self):
        self.plan = harness.starter(goal="spatial", plan_id="sample")
        self.plan["validation"] = {"required_checks": ["walk"], "coverage": {"input": ["walk"]}}
        self.assertTrue(self.validated()["handoff_ready"])
        self.assertTrue(harness.handoff(self.run, self.run / "spatial.json")["ok"])

    def test_reject_unsafe_parameters_and_missing_semantics(self):
        for mutate in (lambda p: p["entities"][0].update(size=[-1, 2, 3]),
                       lambda p: p["entities"][0].update(role=""),
                       lambda p: p.update(engine="unreal"),
                       lambda p: p["player"].update(speed=float("nan"))):
            plan = copy.deepcopy(self.plan)
            mutate(plan)
            with self.assertRaises(core.WorkflowError):
                harness.validate_plan(plan, self.project)


if __name__ == "__main__":
    unittest.main()
