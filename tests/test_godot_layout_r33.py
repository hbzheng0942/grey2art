"""Stable style output and native dependency ownership; no paid/model calls."""
from pathlib import Path
import copy
import json
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1] / "skills/greybox-to-multistyle-art"
sys.path.insert(0, str(ROOT / "runtime"))
from greybox import godot


class GodotLayoutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="gb-layout-")
        self.project = (Path(self.temp.name) / "project").resolve()
        self.project.mkdir()
        self.write("project.godot", '[application]\nrun/main_scene="res://main.tscn"\n')
        self.write("main.tscn", '[gd_scene load_steps=2 format=3]\n[ext_resource type="Script" path="res://main.gd" id="1"]\n[node name="Main" type="Node3D"]\nscript = ExtResource("1")\n')
        self.write("main.gd", "extends Node3D\n")
        self.plan = {"workspace": {"schema": 1, "case_id": "case", "root": "art/case", "engine": "godot", "shared_asset_ids": []},
                     "styles": [{"id": "coast"}, {"id": "moon"}],
                     "contract": {"scene": "res://main.tscn"},
                     "bindings": [{"id": "tree", "owner": ".", "source": {"route": "procedural", "primitive": "box"}}]}
        self.run = self.project / "art/case/shared/production/runs/first"

    def tearDown(self):
        self.temp.cleanup()

    def write(self, relative, value):
        path = self.project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(value, bytes):
            path.write_bytes(value)
        else:
            path.write_text(value)
        return path

    def asset(self, relative, body=None):
        self.write(relative, body or '[gd_scene format=3]\n[node name="Asset" type="Node3D"]\n')
        self.plan["bindings"][0]["source"] = {"route": "reuse", "path": "res://" + relative}

    def assemble(self, run=None, style="coast"):
        return godot.assemble(self.project, run or self.run, self.plan, style)

    def test_formal_entries_are_owned_by_style_not_run(self):
        original = (self.project / "main.tscn").read_bytes()
        artifact = self.assemble()
        self.assertTrue(artifact["entry_scene"].startswith("res://art/case/styles/coast/runtime/revisions/"))
        self.assertNotIn("production/runs", artifact["entry_scene"])
        self.assertEqual(original, (self.project / "main.tscn").read_bytes())
        self.assertEqual(artifact["layout"], "case-style-v1")
        self.assertTrue(artifact["dependency_audit"]["ok"])
        self.assertTrue(all(x["retention"] in ("canonical_revision", "canonical_tool") for x in artifact["owned_files"]))

    def test_unchanged_inputs_reuse_exact_revision_and_file_inodes(self):
        first = self.assemble()
        inodes = {item["path"]: Path(item["path"]).stat().st_ino for item in first["owned_files"]}
        second = self.assemble(self.run.with_name("second"))
        self.assertEqual(first["entry_scene"], second["entry_scene"])
        self.assertEqual(first["revision_sha256"], second["revision_sha256"])
        self.assertEqual(inodes, {item["path"]: Path(item["path"]).stat().st_ino for item in second["owned_files"]})

    def test_generic_adapters_are_shared_once_across_styles(self):
        coast = self.assemble()
        first = {item["path"]: Path(item["path"]).stat().st_ino for item in coast["owned_files"] if item.get("role") == "tool"}
        moon = self.assemble(style="moon")
        second = {item["path"]: Path(item["path"]).stat().st_ino for item in moon["owned_files"] if item.get("role") == "tool"}
        self.assertEqual(first, second)
        self.assertEqual(len(first), 3)
        self.assertTrue(all("/shared/tools/godot/" in path for path in first))
        self.assertTrue(all(item["retention"] == "canonical_tool" for item in moon["owned_files"] if item.get("role") == "tool"))
        self.assertEqual(list((self.project / "art/case/styles").rglob("*.gd")), [])
        self.assertEqual(coast["validator"], moon["validator"])
        self.assertNotEqual(coast["manifest"], moon["manifest"])

    def test_changed_source_gets_new_revision_and_retains_old_files(self):
        first = self.assemble()
        self.write("main.gd", "extends Node3D\n# Source revision\n")
        second = self.assemble(self.run.with_name("second"))
        self.assertNotEqual(first["entry_scene"], second["entry_scene"])
        self.assertTrue(all(Path(item["path"]).exists() for item in first["owned_files"]))

    def test_human_changed_revision_is_not_overwritten(self):
        artifact = self.assemble()
        entry = godot.project_path(self.project, artifact["entry_scene"])
        entry.write_text(entry.read_text() + "\n# Human edit\n")
        with self.assertRaisesRegex(ValueError, "overwrite a changed artifact"):
            self.assemble(self.run.with_name("another"))
        self.assertIn("Human edit", entry.read_text())

    def test_rollback_retains_canonical_revision(self):
        artifact = self.assemble()
        result = godot.rollback(artifact)
        self.assertTrue(result["passed"])
        self.assertEqual(result["removed"], [])
        self.assertEqual(len(result["retained"]), len(artifact["owned_files"]))
        godot._check_artifact(artifact)

    def test_legacy_artifact_keeps_paths_and_reversible_ownership(self):
        self.plan.pop("workspace")
        artifact = self.assemble(self.project / "art/experiments/old")
        self.assertEqual(artifact["entry_scene"], "res://art/experiments/old/coast/play.tscn")
        self.assertNotIn("layout", artifact)
        self.assertTrue(godot.rollback(artifact)["removed"])

    def test_old_run_cannot_be_new_workspace_output(self):
        with self.assertRaisesRegex(ValueError, "production/runs"):
            self.assemble(self.project / "art/experiments/new")

    def test_sibling_style_assets_are_not_implicit_shared(self):
        self.asset("art/case/styles/moon/assets/tree/model.tscn")
        with self.assertRaisesRegex(ValueError, "ownership audit"):
            self.assemble()

    def test_transitive_material_reference_to_downloads_is_blocked(self):
        self.write("art/case/shared/production/runs/old/downloads/material.tres", '[gd_resource type="StandardMaterial3D" format=3]\n[resource]\n')
        self.asset("art/case/styles/coast/assets/tree/model.tscn", '[gd_scene format=3]\n[ext_resource type="Material" path="res://art/case/shared/production/runs/old/downloads/material.tres" id="1"]\n[node name="Tree" type="Node3D"]\n')
        with self.assertRaisesRegex(ValueError, "ownership audit"):
            self.assemble()
        self.assertFalse((self.project / "art/case/styles/coast/runtime").exists())

    def test_gd_comments_and_text_literals_are_not_native_dependencies(self):
        self.write("main.gd", 'extends Node3D\n# load("res://art/experiments/missing.tres")\nvar note = \'load("res://art/experiments/missing.tres")\'\n')
        self.assertTrue(self.assemble()["dependency_audit"]["ok"])

    def test_real_load_is_followed_and_missing_input_rejected(self):
        self.write("main.gd", 'extends Node3D\nvar mesh = preload("res://missing.tres")\n')
        with self.assertRaisesRegex(ValueError, "dependency is missing"):
            self.assemble()

    def test_computed_load_needs_explicit_source_manifest(self):
        self.write("main.gd", 'extends Node3D\nfunc read_asset(path):\n    return load(path)\n')
        with self.assertRaisesRegex(ValueError, "contract.source_paths"):
            self.assemble()
        self.write("dynamic.tres", '[gd_resource type="Resource" format=3]\n[resource]\n')
        self.plan["contract"]["source_paths"] = ["res://dynamic.tres"]
        self.assertTrue(self.assemble()["dependency_audit"]["ok"])

    def test_gltf_external_texture_is_hashed_and_changes_stale_artifact(self):
        texture = self.write("art/case/styles/coast/assets/tree/texture.png", b"small-test-image")
        self.asset("art/case/styles/coast/assets/tree/model.gltf", json.dumps({"asset": {"version": "2.0"}, "images": [{"uri": "texture.png"}]}))
        artifact = self.assemble()
        self.assertIn(str(texture), [item["path"] for item in artifact["sources"]])
        texture.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "source changed"):
            godot._check_artifact(artifact)

    def test_glb_external_texture_escape_to_old_run_is_blocked(self):
        self.write("art/case/shared/production/runs/old/texture.png", b"small-test-image")
        doc = json.dumps({"asset": {"version": "2.0"}, "images": [{"uri": "../../../../shared/production/runs/old/texture.png"}]}).encode()
        doc += b" " * (-len(doc) % 4)
        blob = struct.pack("<4sIIII", b"glTF", 2, 20 + len(doc), len(doc), 0x4E4F534A) + doc
        self.asset("art/case/styles/coast/assets/tree/model.glb", blob)
        with self.assertRaisesRegex(ValueError, "ownership audit"):
            self.assemble()

    def test_external_glb_texture_url_is_blocked(self):
        self.asset("art/case/styles/coast/assets/tree/model.gltf", json.dumps({"images": [{"uri": "https://example.org/texture.png"}]}))
        with self.assertRaisesRegex(ValueError, "external URL"):
            self.assemble()

    def test_shared_asset_and_own_style_asset_both_remain_canonical(self):
        self.plan["workspace"]["shared_asset_ids"] = ["tree"]
        self.asset("art/case/shared/assets/tree/model.tscn")
        artifact = self.assemble()
        manifest = json.loads(godot.project_path(self.project, artifact["manifest"]).read_text())
        self.assertEqual(manifest["bindings"][0]["source"]["path"], "res://art/case/shared/assets/tree/model.tscn")
        self.assertEqual(list((self.project / "art/case/styles/coast/runtime").rglob("model.tscn")), [])

    def test_actual_shader_include_is_followed_without_url_comment_confusion(self):
        included = self.write("art/case/styles/coast/assets/tree/color.gdshaderinc", "vec3 tint() { return vec3(1.0); }\n")
        self.asset("art/case/styles/coast/assets/tree/shader.gdshader", '#include "res://art/case/styles/coast/assets/tree/color.gdshaderinc"\nshader_type spatial;\n')
        self.assertIn(str(included), [item["path"] for item in self.assemble()["sources"]])

    def test_uid_only_dependency_is_explicitly_blocked(self):
        self.write("main.gd", 'extends Node3D\nvar model = load("uid://unknown")\n')
        with self.assertRaisesRegex(ValueError, "UID-only"):
            self.assemble()

    def test_explicit_read_only_external_baseline_alias_remains_supported(self):
        external = self.project.parent / "existing-gameplay"
        external.mkdir()
        source = external / "helper.gd"
        source.write_text("extends Resource\n")
        (self.project / "gameplay-link").symlink_to(external, target_is_directory=True)
        self.write("main.gd", 'extends Node3D\nvar helper = preload("res://gameplay-link/helper.gd")\n')
        self.plan["contract"]["dependency_roots"] = [str(external)]
        artifact = self.assemble()
        self.assertIn(str(source), [item["path"] for item in artifact["sources"]])
        self.assertTrue(artifact["dependency_audit"]["ok"])

    def test_formal_owned_output_symlink_cannot_redirect_a_write(self):
        artifact = self.assemble()
        entry = godot.project_path(self.project, artifact["entry_scene"])
        protected = self.write("human.tscn", entry.read_bytes())
        entry.unlink()
        entry.symlink_to(protected)
        with self.assertRaisesRegex(ValueError, "canonical|symlink|role"):
            self.assemble(self.run.with_name("next"))
        self.assertFalse((self.project / "ownership.json").exists())
        self.assertTrue(entry.is_symlink())

    def test_launch_logs_stay_in_run_evidence(self):
        artifact = self.assemble()
        with patch.object(godot, "engine", return_value=sys.executable):
            result = godot.launch(self.project, artifact)
        self.assertTrue(Path(result["log"]).is_relative_to(self.run / "evidence/coast/launch-logs"))
        self.assertEqual(list((self.project / "art/case/styles/coast/runtime").rglob("*.log")), [])


if __name__ == "__main__":
    unittest.main()
