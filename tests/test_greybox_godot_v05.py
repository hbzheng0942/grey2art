"""Synthetic authoring and native-input boundary checks; no paid services."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/greybox-to-multistyle-art/runtime"))
from greybox import greybox_godot as adapter


def plan():
    return {"schema": 1, "kind": "greybox-build-plan", "id": "walk-and-gather", "engine": "godot", "goal": "playable", "_resource_root": "generated/revision-1", "player": {"position": [0, 0, 0], "speed": 5, "height": 1.8, "radius": .35, "view": "top_down"}, "camera": {"offset": [0, 12, 8]}, "objective": {"required_ids": ["token"], "goal_id": "exit"}, "entities": [{"id": "ground", "role": "walkable_custom_role", "shape": "box", "position": [0, -.25, 0], "size": [20, .5, 20], "color": [.3, .3, .3, 1], "collider": True, "behavior": "none"}, {"id": "token", "role": "resource", "shape": "sphere", "position": [2, .5, 0], "size": [1, 1, 1], "color": [0, 1, 0, 1], "collider": False, "behavior": "collectible"}, {"id": "exit", "role": "destination", "shape": "cylinder", "position": [4, .5, 0], "size": [1, 1, 1], "color": [0, 0, 1, 1], "collider": False, "behavior": "goal", "interaction_anchor": [0, .25, 0]}]}


class GodotGreyboxV05(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="greybox-godot-v05-")
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "project"
        self.project.mkdir()
        self.output = Path(self.temp.name) / "evidence"

    def build(self, value=None):
        return adapter.build(self.project, value or plan(), self.output)

    def test_editable_native_scene_and_semantic_node_bindings(self):
        result = self.build()
        scene = adapter.project_path(self.project, result["scene"]).read_text()
        self.assertTrue(result["ok"])
        self.assertIn('type="CharacterBody3D"', scene)
        self.assertIn('type="StaticBody3D"', scene)
        self.assertIn('type="Area3D"', scene)
        self.assertIn('type="SphereMesh"', scene)
        self.assertIn('type="CylinderMesh"', scene)
        ground, token, destination = [result["entities"][key] for key in ("ground", "token", "exit")]
        self.assertEqual(ground["role"], "walkable_custom_role")
        self.assertTrue(token["visual_nodes"][0].endswith("/Visual"))
        self.assertTrue(token["collision_nodes"][0].endswith("/Trigger/CollisionShape3D"))
        self.assertTrue(destination["interaction_anchor"]["node_path"].endswith("/InteractionAnchor"))
        self.assertEqual(destination["interaction_anchor"]["local"], [0, .25, 0])
        self.assertEqual(destination["interaction_anchor"]["world"], [4.0, .75, 0.0])
        self.assertTrue(all(Path(path).is_file() and Path(path).is_absolute() for path in result["source_files"]))
        self.assertNotIn("_resource_root", json.loads((self.project / "generated/revision-1/plan.json").read_text()))

    def test_existing_main_scene_and_renderer_are_preserved_byte_exactly(self):
        config = b'config_version=5\n[application]\nrun/main_scene="res://Existing.tscn"\n[rendering]\nrenderer/rendering_method="mobile"\n'
        (self.project / "project.godot").write_bytes(config)
        result = self.build()
        self.assertFalse(result["created_project"])
        self.assertEqual(config, (self.project / "project.godot").read_bytes())

    def test_rotated_camera_offset_keeps_authored_world_coordinates(self):
        value = plan()
        value["camera"]["offset"] = [8, 12, 0]
        result = self.build(value)
        saved = json.loads((adapter.project_path(self.project, result["scene"]).parent / "plan.json").read_text())
        self.assertEqual(saved["camera"]["offset"], [8, 12, 0])
        self.assertEqual(saved["entities"][1]["position"], [2, .5, 0])
        self.assertEqual(result["entities"]["token"]["bounds"]["center"], [2, .5, 0])

    def test_fresh_resource_root_cannot_overwrite_existing_files(self):
        self.build()
        with self.assertRaisesRegex(ValueError, "fresh and empty"):
            adapter.build(self.project, plan(), self.output / "second")

    def test_outside_or_symlink_resource_root_is_rejected(self):
        value = plan()
        value["_resource_root"] = "../outside"
        with self.assertRaisesRegex(ValueError, "inside"):
            self.build(value)
        external = Path(self.temp.name) / "external"
        external.mkdir()
        (self.project / "redirect").symlink_to(external, target_is_directory=True)
        value["_resource_root"] = "redirect/version"
        with self.assertRaisesRegex(ValueError, "inside"):
            self.build(value)

    def test_unsupported_fields_and_inexact_collision_shapes_are_explicit(self):
        value = plan()
        value["entities"][0]["fake_feature"] = True
        with self.assertRaisesRegex(ValueError, "fake_feature"):
            self.build(value)
        value = plan()
        value["entities"][1]["size"] = [1, 2, 1]
        with self.assertRaisesRegex(ValueError, "equal x/y/z"):
            self.build(value)

    def test_project_script_extension_and_exported_properties_are_bound(self):
        custom = self.project / "station.gd"
        custom.write_text('extends Node3D\n@export var station_kind := "workbench"\nfunc greybox_interact(player):\n\tpass\n')
        value = plan()
        value["entities"][0].update(script="res://station.gd", properties={"station_kind": "kitchen"})
        result = self.build(value)
        self.assertIn(str(custom.resolve()), result["source_files"])
        scene = adapter.project_path(self.project, result["scene"]).read_text()
        self.assertIn('station_kind = "kitchen"', scene)
        self.assertIn('path="res://station.gd"', scene)

    def test_external_script_and_protected_properties_are_rejected(self):
        value = plan()
        value["entities"][0]["script"] = "../outside.gd"
        with self.assertRaisesRegex(ValueError, "inside"):
            self.build(value)
        value = plan()
        value["entities"][0]["properties"] = {"position": [5, 5, 5]}
        with self.assertRaisesRegex(ValueError, "entity.script"):
            self.build(value)

    def test_probe_only_accepts_actual_input_and_known_expectations(self):
        for invalid in [{"teleport": [4, 0, 0]}, {"steps": [{"frames": 3, "actions": {"teleport": 1}}]}, {"steps": [{"frames": 3, "expect": {"invented": True}}]}, {"steps": [{"frames": 0}]}, {"steps": [{"frames": 3, "actions": {"move_right": 2}}]}, {"headless": True}, {"capture_frames": [9999]}]:
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                adapter._probe(invalid, self.output, "playable")
        probe = adapter._probe({}, self.output, "spatial")
        self.assertEqual(probe["steps"][0]["actions"], {"move_right": 1})

    def test_no_native_report_is_failure_not_synthetic_success(self):
        result = self.build()
        response = type("Response", (), {"returncode": 0, "stdout": "Godot", "stderr": ""})()
        with patch.object(adapter, "_engine", return_value="/synthetic/godot"), patch.object(adapter.subprocess, "run", return_value=response):
            native = adapter.run(self.project, result["scene"], {}, self.output / "run")
        self.assertFalse(native["ok"])
        self.assertEqual(native["frames"], [])
        self.assertIn("did not write", native["error"])

    def test_native_entity_bindings_are_forwarded_without_plan_path_refill(self):
        result = self.build()
        output = self.output / "actual-binding-run"
        actual = {"token": {"id": "token", "role": "resource", "node_path": "Greybox/World/EditedToken", "visual_path": "Greybox/World/EditedToken/ChangedVisual", "bounds": {"center": [3, .5, 0], "size": [1, 1, 1]}, "binding_source": "native_scene_initial_state"}}
        response = type("Response", (), {"returncode": 0, "stdout": "Godot", "stderr": ""})()
        def invoke(*args, **kwargs):
            (output / "native-report.json").write_text(json.dumps({"ok": True, "checks": [], "frames": [], "telemetry": {}, "entities": actual}))
            return response
        with patch.object(adapter, "_engine", return_value="/synthetic/godot"), patch.object(adapter.subprocess, "run", side_effect=invoke):
            native = adapter.run(self.project, result["scene"], {"capture_frames": []}, output)
        self.assertEqual(native["entities"], actual)
        self.assertNotEqual(native["entities"]["token"]["node_path"], result["entities"]["token"]["node_path"])

    def test_common_optional_defaults_are_written_to_native_plan(self):
        value = plan()
        value.pop("player")
        value.pop("camera")
        for entity in value["entities"]:
            entity.pop("color")
            entity.pop("collider")
            entity.pop("behavior")
        result = self.build(value)
        saved = json.loads((adapter.project_path(self.project, result["scene"]).parent / "plan.json").read_text())
        self.assertEqual(saved["player"]["height"], 1.8)
        self.assertEqual(saved["entities"][0]["behavior"], "none")
        self.assertEqual(saved["camera"]["offset"], [0, 12, 8])

    def test_numeric_range_validation_and_unique_step_identity(self):
        valid = {"steps": [{"id": "collision", "frames": 20, "expect": {"player_position": {"min": [-2, -1, -1], "max": [-1, 1, 1]}, "distance_travelled": {"min": 1}}}]}
        self.assertEqual(adapter._probe(valid, self.output, "spatial")["steps"][0]["id"], "collision")
        for expected in [{"state": {"min": 1}}, {"distance_travelled": {"min": 2, "max": 1}}, {"player_position": {"min": [1, 2]}}, {"player_position": {"fake": [1, 2, 3]}}]:
            with self.subTest(expected=expected), self.assertRaises(ValueError):
                adapter._probe({"steps": [{"frames": 20, "expect": expected}]}, self.output, "spatial")
        with self.assertRaisesRegex(ValueError, "unique"):
            adapter._probe({"steps": [{"id": "same", "frames": 2}, {"id": "same", "frames": 2}]}, self.output, "spatial")

    def test_missing_explicit_engine_never_falls_back(self):
        with patch.object(adapter, "engine") as discover, self.assertRaisesRegex(ValueError, "no fallback"):
            adapter._engine(self.project / "not-installed")
        discover.assert_not_called()

if __name__ == "__main__":
    unittest.main()
