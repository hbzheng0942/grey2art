"""Intent and actual-state routing, with no engine/provider invocation."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/greybox-to-multistyle-art/runtime"))
from greybox import core, intake


class IntakeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="greybox-intake-")
        self.project = Path(self.temp.name) / "project"

    def tearDown(self):
        self.temp.cleanup()

    def request(self, intent, **fields):
        return {"schema": 1, "kind": "greybox-intake-request", "intent": intent,
                "source_ref": "user:current-task", **fields}

    def scene(self):
        self.project.mkdir()
        (self.project / "project.godot").write_text('[application]\nrun/main_scene="res://main.tscn"\n')
        (self.project / "main.tscn").write_text('[gd_scene format=3]\n[node name="Main" type="Node3D"]\n')

    def test_discussion_does_not_inspect_or_require_engine(self):
        with patch.object(intake, "inspect", side_effect=AssertionError("discussion must not launch discovery")):
            value = intake.route(self.request("discuss"), self.project)
        self.assertEqual(value["action"], "discuss")
        self.assertFalse(value["dispatch"])

    def test_no_engine_is_not_silently_godot(self):
        value = intake.route(self.request("create_greybox"), self.project)
        self.assertEqual(value["action"], "choose_engine")
        self.assertIsNone(value["engine"])

    def test_greybox_stops_without_art_or_provider_requirements(self):
        value = intake.route(self.request("create_greybox", engine="unity"), self.project)
        self.assertEqual(value["action"], "greybox_create")
        self.assertEqual(value["stop_at"], "greybox")
        self.assertEqual(value["after_handoff"], "stop")
        self.assertFalse(value["paid_work_authorized"])
        self.assertNotIn("image_generate", value["required_capabilities"])

    def test_scene_does_not_certify_playability(self):
        self.scene()
        state = intake.inspect(self.project)
        self.assertEqual(state["state"], "spatial_existing")
        self.assertNotIn("playable", state["state"])

    def test_existing_greybox_art_uses_legacy_intake(self):
        self.scene()
        before = (self.project / "main.tscn").read_bytes()
        value = intake.route(self.request("art"), self.project)
        self.assertEqual(value["action"], "existing_art_intake")
        self.assertEqual((self.project / "main.tscn").read_bytes(), before)

    def test_shipped_art_intake_example_routes_existing_project_without_authoring(self):
        self.scene()
        before = {p.name: p.read_bytes() for p in self.project.iterdir()}
        request = json.loads((ROOT / "skills/greybox-to-multistyle-art/schemas/intake-art-request-template.json").read_text())
        request["source_ref"] = "user:actual-three-style-request"
        with patch.object(core, "write", side_effect=AssertionError("routing must not change the source")):
            value = intake.route(request, self.project)
        self.assertEqual(value["action"], "existing_art_intake")
        self.assertEqual(value["stop_at"], "art")
        self.assertFalse(value["paid_work_authorized"])
        self.assertEqual({p.name: p.read_bytes() for p in self.project.iterdir()}, before)

    def test_shipped_greybox_example_keeps_its_explicit_non_art_endpoint(self):
        request = json.loads((ROOT / "skills/greybox-to-multistyle-art/schemas/intake-request-template.json").read_text())
        request["source_ref"] = "user:actual-greybox-only-request"
        value = intake.route(request, self.project)
        self.assertEqual(value["action"], "greybox_create")
        self.assertEqual(value["stop_at"], "greybox")
        self.assertFalse(value["paid_work_authorized"])

    def test_existing_scene_edit_does_not_trigger_art(self):
        self.scene()
        value = intake.route(self.request("edit_greybox"), self.project)
        self.assertEqual(value["action"], "greybox_edit")
        self.assertEqual(value["stop_at"], "greybox")

    def test_end_to_end_only_recommends_later_art(self):
        value = intake.route(self.request("end_to_end", engine="godot"), self.project)
        self.assertEqual(value["action"], "greybox_create")
        self.assertEqual(value["stop_at"], "art")
        self.assertFalse(value["paid_work_authorized"])
        self.assertFalse(value["dispatch"])

    def test_greybox_only_intent_cannot_hide_an_art_endpoint(self):
        with self.assertRaisesRegex(core.WorkflowError, "conflicts"):
            intake.route(self.request("create_greybox", engine="godot", stop_at="art"), self.project)

    def test_resume_without_original_task_does_not_guess_art(self):
        self.scene()
        value = intake.route(self.request("resume"), self.project)
        self.assertEqual(value["action"], "locate_original_task")
        self.assertIsNone(value["stop_at"])

    def test_pause_is_no_dispatch_decision(self):
        value = intake.route(self.request("pause"), self.project)
        self.assertEqual(value["action"], "record_user_pause")
        self.assertFalse(value["dispatch"])

    def test_explicit_engine_conflict_needs_resolution(self):
        self.scene()
        value = intake.route(self.request("edit_greybox", engine="unity"), self.project)
        self.assertEqual(value["action"], "clarify_engine")
        self.assertTrue(value["requires_clarification"])

    def test_ambiguous_engine_does_not_migrate(self):
        self.scene()
        version = self.project / "ProjectSettings/ProjectVersion.txt"
        version.parent.mkdir()
        version.write_text("m_EditorVersion: 6000.3.26f1\n")
        value = intake.route(self.request("create_greybox"), self.project)
        self.assertEqual(value["action"], "clarify_engine")

    def test_unreal_is_explicit_optional_experiment(self):
        value = intake.route(self.request("create_greybox", engine="unreal"), self.project)
        self.assertEqual(value["action"], "ue_optional_experiment")
        self.assertEqual(value["native_support"], "knowledge_and_optional_experiment_only")

    def test_cache_scenes_do_not_change_project_state(self):
        self.project.mkdir()
        (self.project / "project.godot").write_text("config_version=5\n")
        cached = self.project / ".godot/imported/fake.tscn"
        cached.parent.mkdir(parents=True)
        cached.write_text("cache")
        self.assertEqual(intake.inspect(self.project)["state"], "empty_project")

    def test_nonempty_unknown_project_is_inspected_not_replaced(self):
        self.project.mkdir()
        (self.project / "unique-data.txt").write_text("keep")
        self.assertEqual(intake.route(self.request("create_greybox", engine="godot"), self.project)["action"], "inspect_existing_project")

    def test_material_ambiguities_are_explicit(self):
        value = intake.route(self.request("create_greybox", engine="unity", unresolved=["Target device changes the interaction design"]), self.project)
        self.assertEqual(value["action"], "clarify_material_choice")

    def test_context_interpretation_requires_actual_source(self):
        request = self.request("art")
        request.pop("source_ref")
        with self.assertRaises(core.WorkflowError):
            intake.route(request, self.project)

    def test_unknown_field_does_not_silently_authorize_execution(self):
        with self.assertRaises(core.WorkflowError):
            intake.route(self.request("art", auto_approve=True), self.project)


if __name__ == "__main__":
    unittest.main()
