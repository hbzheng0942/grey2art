"""Cross-engine source identity and effects admission; no native processes."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from argparse import Namespace

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/greybox-to-multistyle-art/runtime"))
from greybox import core, effects, engines, workflow, engine_cli


class EngineTests(unittest.TestCase):
    def test_explicit_conflicting_engine_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            engines.name({"engine": "unity", "workspace": {"engine": "godot"}})

    def test_historical_default_and_unity_scene_contract(self):
        self.assertEqual(engines.name({}), "godot")
        self.assertEqual(engines.validate_scene({"engine": "unity", "contract": {"scene": "Assets/Main.unity"}}), "unity")
        with self.assertRaisesRegex(ValueError, "Assets"):
            engines.validate_scene({"engine": "unity", "contract": {"scene": "res://Main.tscn"}})

    def test_unity_snapshot_tracks_render_settings_source_and_import_meta(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            for name, text in {"ProjectSettings/ProjectVersion.txt": "m_EditorVersion: 6000.3.26f1",
                    "ProjectSettings/GraphicsSettings.asset": "pipeline: first", "Packages/manifest.json": "{}",
                    "Assets/Main.unity": "scene", "Assets/Logic.cs": "class Logic {}",
                    "Assets/art.glb": "asset", "Assets/art.glb.meta": "guid: abc"}.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)
            plan = {"engine": "unity", "contract": {"scene": "Assets/Main.unity"},
                    "assets": [{"source": {"path": "Assets/art.glb"}}]}
            with patch("greybox.engines.dependency_snapshot", return_value=[]):
                first = core.input_snapshot(root, plan)
                self.assertIn("Assets/Logic.cs", first["files"])
                self.assertIn(str(root / "Assets/art.glb.meta"), first["importSettings"])
                for name in ["Assets/Logic.cs", "ProjectSettings/GraphicsSettings.asset", "Assets/art.glb.meta"]:
                    path = root / name
                    original = path.read_text()
                    path.write_text(original + " changed")
                    self.assertNotEqual(first["sha256"], core.input_snapshot(root, plan)["sha256"])
                    path.write_text(original)

    def test_effects_reject_typo_and_invalid_density_bounds(self):
        with self.assertRaisesRegex(ValueError, "Unsupported water"):
            effects.validate({"water": {"speeed": 1}})
        with self.assertRaisesRegex(ValueError, "bounds"):
            effects.validate({"grass": {"bounds": [2, 0, 1, 3]}})
        with self.assertRaisesRegex(ValueError, "finite"):
            effects.validate({"water": {"speed": float("nan")}})
        self.assertEqual(effects.validate({"grass": {"count": 0, "seed": 42}})["grass"]["count"], 0)

    def test_lookdev_is_owned_incremental_scene_and_preserves_baseline(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "Main.tscn").write_text('[gd_scene format=3]\n[node name="Main" type="Node3D"]\n')
            before = core.file_hash(root / "Main.tscn")
            config = {"scene": "res://Main.tscn", "effects": {"water": {"size": [2, 3]}}}
            result = effects.apply_godot(root, config, root / "art/look")
            self.assertEqual(before, core.file_hash(root / "Main.tscn"))
            self.assertFalse(result["native_verified"])
            self.assertIn("water", result["effects"])
            self.assertEqual(len(result["owned_files"]), 5)
            self.assertEqual(result["entry_scene"], effects.apply_godot(root, config, root / "art/look")["entry_scene"])

    def test_effect_recipe_ranges_and_aliases_fail_before_native_execution(self):
        invalid = [
            {"water": {"roughness": 1.1}}, {"water": {"shore_width": 0}},
            {"water": {"depth_distance": -1}}, {"water": {"amplitude": -0.2}},
            {"water": {"deep_color": [0, "bad", 0]}}, {"water": {"normal_texture": False}},
            {"grass": {"mask_threshold": 1.1}}, {"grass": {"width": 0}},
            {"grass": {"chunk_size": False}}, {"grass": {"height": -1}},
            {"grass": {"y": 0, "ground_y": 1}}, {"grass": {"wind": -1}},
            {"grass": {"cull_distance": -1}}, {"grass": {"exclude_rects": "bad"}},
            {"lighting": {"exposure": 0}}, {"lighting": {"bloom": 1}},
            {"ground": {"tile_scale": -2}}, {"water": {"size": [True, 2]}},
        ]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                effects.validate(value)
        valid = {"water": {"roughness": 0, "speed": -0.5, "deep_color": [0, 0.2, 0.3],
                           "normal_texture": "res://normal.png", "shore_width": 0.2, "depth_distance": 2},
                 "grass": {"y": -1, "ground_y": -1, "width": 0.12, "chunk_size": 4,
                           "density_mask": "res://density.png", "mask_threshold": 0.3, "cull_distance": 0}}
        self.assertEqual(effects.validate(valid), valid)

    def test_effect_texture_inputs_are_decoded_hashed_and_keep_data_interpretation(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("normal", "mask", "albedo"):
                Image.new("RGB", (4, 4), (128, 128, 255)).save(root / (name + ".png"))
            config = {"water": {"normal_texture": "res://normal.png"},
                      "grass": {"density_mask": "mask.png"}, "ground": {"texture": "albedo.png"}}
            textures = effects.dependencies(effects.validate(config), root)
            by_usage = {item["usage"]: item for item in textures}
            self.assertEqual(by_usage["normal_texture"]["color_space"], "linear-data")
            self.assertEqual(by_usage["density_mask"]["sha256"], core.file_hash(root / "mask.png"))
            self.assertEqual(by_usage["texture"]["color_space"], "srgb")
            (root / "mask.png").write_bytes(b"corrupt")
            with self.assertRaisesRegex(ValueError, "decoded"):
                effects.dependencies(config, root)
            config["grass"]["density_mask"] = "../outside.png"
            with self.assertRaisesRegex(ValueError, "project resource"):
                effects.dependencies(config, root)

    def test_cli_unity_raw_plan_reaches_native_plan_input(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            plan = {"engine": "unity", "contract": {"scene": "Assets/Main.unity"}, "bindings": [{"id": "x"}]}
            core.write(root / "plan.json", plan)
            args = Namespace(project=root, engine="unity", file=root / "plan.json", action="assemble",
                             output=root / "evidence", style="ceramic", executable=None, native=False)
            with patch("greybox.unity.run", return_value={"ok": True}) as call:
                engine_cli.handle(args)
            self.assertEqual(call.call_args.kwargs["config"]["plan"], plan)
            self.assertEqual(call.call_args.kwargs["config"]["style_id"], "ceramic")

    def test_export_cannot_pass_using_stale_preexisting_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            core.write(root / "config.json", {"preset": "macOS"})
            output = root / "old.zip"
            output.write_bytes(b"old")
            args = Namespace(project=root, engine="godot", file=root / "config.json", action="export",
                             output=output, executable=None)
            with patch("greybox.engine_cli.subprocess.run") as native:
                with self.assertRaisesRegex(ValueError, "already exists"):
                    engine_cli.handle(args)
            native.assert_not_called()


if __name__ == "__main__":
    unittest.main()
