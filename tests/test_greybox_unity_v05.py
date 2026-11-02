"""Contract and failure tests for the production Unity greybox authoring path."""
from __future__ import annotations

import json
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/greybox-to-multistyle-art/runtime"))
from greybox import greybox_unity as adapter


def plan():
    return {"schema": 1, "kind": "greybox-build-plan", "id": "route-courier", "engine": "unity", "goal": "playable", "player": {"position": [0, .02, 0]}, "entities": [
        {"id": "ground", "role": "walkable-courtyard", "shape": "box", "position": [0, -.5, 0], "size": [20, 1, 20], "collider": True},
        {"id": "parcel", "role": "recoverable-parcel", "shape": "sphere", "position": [2, .6, 0], "size": [.6, .6, .6], "collider": True, "behavior": "collectible"},
        {"id": "arrival", "role": "delivery-exit", "shape": "box", "position": [4, .5, 0], "size": [1, 1, 1], "collider": True, "behavior": "goal"}], "objective": {"required_ids": ["parcel"], "goal_id": "arrival"}}


class UnityAuthoringContract(unittest.TestCase):
    def test_spatial_does_not_need_win_or_lose_system(self):
        value = plan(); value["goal"] = "spatial"; value.pop("objective")
        result = adapter._plan(value)
        self.assertEqual(result["goal"], "spatial")
        self.assertEqual(result["objective"]["required_ids"], [])

    def test_semantic_roles_are_open_and_anchors_local(self):
        result = adapter._plan(plan())
        self.assertEqual(result["entities"][0]["role"], "walkable-courtyard")
        self.assertEqual(result["entities"][1]["interaction_anchor"], [0, 0, 0])

    def test_nonblocking_interactive_entities_keep_interaction_bounds(self):
        value = plan(); value["entities"][1]["collider"] = False
        self.assertFalse(adapter._plan(value)["entities"][1]["collider"])

    def test_component_extension_is_explicit_and_typed(self):
        value = plan(); value["entities"][1].update(component_type="MyGame.Parcel", properties={"points": 4, "usable": True, "message": "hello", "offset": [0, 1, 0]})
        result = adapter._plan(value)["entities"][1]["properties"]
        self.assertEqual([row["kind"] for row in result], ["number", "bool", "string", "vector"])
        value["entities"][1]["properties"]["unknown"] = {"nested": "unsupported"}
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            adapter._plan(value)

    def test_unknown_fields_do_not_silently_disappear(self):
        for key in ("teleport", "script", "mesh"):
            value = plan(); value["entities"][1][key] = "unhandled"
            with self.assertRaisesRegex(ValueError, "Unsupported"):
                adapter._plan(value)

    def test_collectible_objective_must_bind_real_entities(self):
        value = plan(); value["objective"]["required_ids"] = ["missing"]
        with self.assertRaisesRegex(ValueError, "distinct collectibles"):
            adapter._plan(value)
        value = plan(); value["objective"]["goal_id"] = "parcel"
        with self.assertRaisesRegex(ValueError, "goal entity"):
            adapter._plan(value)

    def test_replay_makes_no_state_setter_available(self):
        result = adapter._run_config({"steps": [{"actions": {"move_right": 1}, "frames": 30, "expect": {"collected_count": 1}}]})
        self.assertEqual(result["steps"][0]["actions"], {"move_right": 1})
        for actions in ({"player_position": [2, 0, 0]}, {"move_right": 10}, {"collect": "parcel"}):
            with self.assertRaises(ValueError):
                adapter._run_config({"steps": [{"actions": actions}]})

    def test_existing_builtin_is_preserved_and_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "ProjectSettings").mkdir(); (root / "Packages").mkdir()
            (root / "ProjectSettings/ProjectVersion.txt").write_text("m_EditorVersion: 6000.3.26f1\n")
            (root / "Packages/manifest.json").write_text('{"dependencies":{}}')
            with patch.object(adapter.unity, "engine", return_value="Unity"), patch.object(adapter.subprocess, "run") as native:
                with self.assertRaisesRegex(ValueError, "not converted"):
                    adapter._project(root, "Unity", root)
                native.assert_not_called()
                self.assertEqual(json.loads((root / "Packages/manifest.json").read_text()), {"dependencies": {}})

    def test_stable_toolroot_refuses_unowned_content(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / adapter.TOOL_ROOT).mkdir(parents=True)
            with self.assertRaisesRegex(ValueError, "another owner"):
                adapter._install(root)

    def test_runtime_is_shared_and_visuals_have_separate_collision(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            files = adapter._install(root)
            again = adapter._install(root)
            self.assertEqual(files, again)
            self.assertTrue((root / adapter.TOOL_ROOT / "GreyboxController.cs").is_file())
            source = (root / adapter.TOOL_ROOT / "Editor/AuthoringBridge.cs").read_text()
            self.assertIn('Child("Collision", owner)', source)
            self.assertIn('Child("Logic", owner)', source)
            self.assertIn('visual.name = "Visual"', source)

    def test_receipt_from_other_invocation_cannot_certify_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "evidence"; output.mkdir()
            def execute(command, **kwargs):
                (output / "native-report.json").write_text(json.dumps({"ok": True, "request_id": "old", "operation": "build", "scene": "Assets/Greybox/test/Greybox.unity"}))
                return type("Result", (), {"returncode": 0, "stdout": "", "stderr": ""})()
            with patch.object(adapter.subprocess, "run", side_effect=execute):
                report = adapter._invoke(root, "Unity", {"operation": "build", "scene": "Assets/Greybox/test/Greybox.unity"}, output)
            self.assertFalse(report["ok"])
            self.assertIn("Native receipt identity mismatch", report["errors"])

    def test_scene_cannot_escape_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "outside.unity").write_text("fake")
            with self.assertRaisesRegex(ValueError, "Assets scene"):
                adapter._scene(root, "outside.unity")

    def test_position_range_assertions_measure_collision_and_movement(self):
        self.assertTrue(adapter._matches([1.65, -.001, 0], {"min": [1.5, -.1, -.1], "max": [1.8, .1, .1]}))
        self.assertFalse(adapter._matches([1.65, -.001, 0], {"min": [2, -.1, -.1]}))
        with self.assertRaisesRegex(ValueError, "min/max"):
            adapter._matches(4, {"skip": True})

    def test_run_returns_actual_scene_paths_and_metric_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); scene = root / "Assets/Greybox/case/r1/Greybox.unity"
            scene.parent.mkdir(parents=True); scene.write_text("scene")
            output = root / "evidence"; output.mkdir()
            frame = output / "frame-000.png"; frame.write_bytes(b"\x89PNG\r\n\x1a\nactual-receipt-fixture")
            native = {"ok": True, "play_mode": True, "graphics_device": "Metal", "entities": [{"id": "wall", "node_path": "Greybox_case/Entities/renamed-wall", "visual_path": "Greybox_case/Entities/renamed-wall/Visual", "role": "barrier"}], "snapshots": [{"restart_count": 2}], "captures": [{"path": str(frame), "sha256": hashlib.sha256(frame.read_bytes()).hexdigest()}]}
            with patch.object(adapter.unity, "engine", return_value="Unity"), patch.object(adapter, "_invoke", return_value=native):
                result = adapter.run(root, str(scene), {"capture_frames": 1, "steps": [{"id": "reset", "actions": {"restart": 1}, "expect": {"restart_count": 2}}]}, output)
            self.assertTrue(result["ok"])
            self.assertEqual(result["entities"]["wall"]["node_path"], "Greybox_case/Entities/renamed-wall")
            reset = next(item for item in result["checks"] if item["name"] == "step-reset:restart_count")
            self.assertEqual((reset["key"], reset["step"]), ("restart_count", 0))


if __name__ == "__main__":
    unittest.main()
