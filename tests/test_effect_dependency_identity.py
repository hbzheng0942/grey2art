"""Effect inputs remain visible to native provenance without computed-path inference."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/greybox-to-multistyle-art/runtime"))
from greybox import core, effects, engines, godot


class EffectDependencyIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="gb-effect-dependencies-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / "project.godot").write_text('[application]\nrun/main_scene="res://main.tscn"\n')
        (self.root / "main.tscn").write_text('[gd_scene format=3]\n[node name="Main" type="Node3D"]\n')
        self.config = {"scene": "res://main.tscn", "effects": {"water": {}}}
        self.target = self.root / "art/look"

    def plan(self, scene, workspace):
        value = {"engine": "godot", "contract": {"scene": scene}}
        if workspace:
            value["workspace"] = {"schema": 1, "case_id": "test", "engine": "godot"}
        return value

    def snapshot(self, scene, workspace):
        return {row["path"]: row["sha256"] for row in engines.dependency_snapshot(
            self.root, self.plan(scene, workspace))}

    def texture(self, name, color=(128, 128, 255)):
        from PIL import Image
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (4, 4), color).save(path)
        return path

    def test_each_shader_mutation_invalidates_both_snapshot_modes(self):
        artifact = effects.apply_godot(self.root, self.config, self.target)
        for workspace in (False, True):
            first = self.snapshot(artifact["entry_scene"], workspace)
            for kind in ("water", "grass", "ground"):
                with self.subTest(workspace=workspace, shader=kind):
                    shader = self.target / (kind + ".gdshader")
                    original = shader.read_bytes()
                    self.assertIn(str(shader), first)
                    shader.write_bytes(original + b"\n// changed visual source\n")
                    changed = self.snapshot(artifact["entry_scene"], workspace)
                    self.assertNotEqual(first[str(shader)], changed[str(shader)])
                    shader.write_bytes(original)

    def test_all_texture_roles_and_path_forms_are_hash_bound(self):
        recipe = {"water": {}, "grass": {"count": 1}, "ground": {}}
        roles = {"water": ("shore_mask", "normal_texture"), "grass": ("density_mask",),
                 "ground": ("texture", "secondary_texture", "blend_mask")}
        paths = []
        for index, (family, fields) in enumerate(roles.items()):
            for field in fields:
                path = self.texture("textures/" + field + ".png")
                paths.append(path)
                recipe[family][field] = ("res://" + path.relative_to(self.root).as_posix()
                    if index == 0 else str(path) if index == 1 else path.relative_to(self.root).as_posix())
        artifact = effects.apply_godot(self.root, {"scene": "res://main.tscn", "effects": recipe}, self.target)
        for workspace in (False, True):
            first = self.snapshot(artifact["entry_scene"], workspace)
            for path in paths:
                with self.subTest(workspace=workspace, texture=path.name):
                    original = path.read_bytes()
                    self.assertEqual(first[str(path)], core.file_hash(path))
                    self.texture(path.relative_to(self.root), (30, 40, 50))
                    self.assertNotEqual(first[str(path)], self.snapshot(artifact["entry_scene"], workspace)[str(path)])
                    path.write_bytes(original)

    def test_deleted_declared_shader_or_texture_is_rejected_in_both_modes(self):
        texture = self.texture("normal.png")
        self.config["effects"]["water"]["normal_texture"] = "normal.png"
        artifact = effects.apply_godot(self.root, self.config, self.target)
        for path in (self.target / "water.gdshader", texture):
            original = path.read_bytes()
            path.unlink()
            for workspace in (False, True):
                with self.subTest(workspace=workspace, missing=path.name), self.assertRaisesRegex(ValueError, "dependency is missing"):
                    self.snapshot(artifact["entry_scene"], workspace)
            path.write_bytes(original)

    def test_resource_comments_do_not_create_missing_dependency_failures(self):
        scene = self.root / "main.tscn"
        scene.write_text(scene.read_text() + '\n; [ext_resource type="Texture2D" path="res://missing.png" id="ignored"]\n')
        for workspace in (False, True):
            self.assertNotIn(str(self.root / "missing.png"), self.snapshot("res://main.tscn", workspace))

    def test_relative_explicit_resource_is_checked_without_broad_project_scan(self):
        texture = self.texture("native/tex.png")
        scene = self.root / "native/main.tscn"
        scene.write_text('[gd_scene load_steps=2 format=3]\n[ext_resource type="Texture2D" path="tex.png" id="1"]\n[node name="Main" type="Node3D"]\n')
        (self.root / "unrelated.gd").write_text('extends Node\n# "res://not-an-input.png"\n')
        for workspace in (False, True):
            result = self.snapshot("res://native/main.tscn", workspace)
            self.assertIn(str(texture), result)
            self.assertNotIn(str(self.root / "unrelated.gd"), result)

    def test_absent_texture_fails_before_output_is_staged(self):
        self.config["effects"]["water"]["normal_texture"] = "missing.png"
        with self.assertRaisesRegex(ValueError, "existing project resource"):
            effects.apply_godot(self.root, self.config, self.target)
        self.assertFalse(self.target.exists())

    def test_assembly_has_the_same_explicit_effect_dependency_closure(self):
        for workspace in (False, True):
            with self.subTest(workspace=workspace):
                plan = self.plan("res://main.tscn", workspace)
                plan.update(styles=[{"id": "ink", "effects": {"water": {}}}], bindings=[])
                if workspace:
                    plan["workspace"].update(root="art/test", shared_asset_ids=[])
                    run = self.root / "art/test/shared/production/runs/first"
                else:
                    run = self.root / "art/experiments/first"
                artifact = godot.assemble(self.root, run, plan, "ink")
                capture_plan = self.plan(artifact["entry_scene"], workspace)
                # The existing art adapter's declared dynamic asset inputs live in
                # its assembly manifest; effect resources no longer need inference.
                capture_plan["contract"]["source_paths"] = [artifact["manifest"]]
                first = {r["path"]: r["sha256"] for r in engines.dependency_snapshot(self.root, capture_plan)}
                shader = next(Path(row["path"]) for row in artifact["owned_files"] if row["path"].endswith("water.gdshader"))
                self.assertIn(str(shader), first)
                shader.write_text(shader.read_text() + "\n// changed assembly effect\n")
                changed = {r["path"]: r["sha256"] for r in engines.dependency_snapshot(self.root, capture_plan)}
                self.assertNotEqual(first[str(shader)], changed[str(shader)])


if __name__ == "__main__":
    unittest.main()
