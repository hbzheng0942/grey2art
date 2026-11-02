"""Carrier-specific actual dependency syntax; native inspection is never gameplay acceptance."""
import base64
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1] / "skills/greybox-to-multistyle-art"
sys.path.insert(0, str(ROOT / "runtime"))
from greybox import core, engine_workspace as ew, layout
from test_supplier_jobs_r3 import synthetic_glb


class EngineWorkspaceR33(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="engine-workspace-r33-")
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name).resolve()
        self.plan = {"styles": [{"id": "red"}, {"id": "blue"}], "workspace": {
            "schema": 1, "case_id": "case", "root": "art/case", "engine": "threejs",
            "shared_asset_ids": [], "asset_owners": {"tree": {"scope": "style", "style_id": "red"}}}}
        self.counter = 0

    def file(self, path, body=b"tiny synthetic fixture"):
        p = Path(path) if Path(path).is_absolute() else self.project / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(body.encode() if isinstance(body, str) else body)
        return p

    def meta(self, path, guid=None):
        self.counter += 1
        guid = guid or ("%032x" % self.counter)
        self.file(str(path) + ".meta", "fileFormatVersion: 2\nguid: " + guid + "\n")
        return guid

    def entry(self, text, engine="threejs", ext=".js"):
        self.plan["workspace"]["engine"] = engine
        role = "dcc" if engine == "blender" else "runtime"
        p = layout.roots(self.project, self.plan, "red")[role] / ("entry" + ext)
        self.file(p, text)
        if engine == "unity": self.meta(p)
        return p

    def audit(self, path, deps=None):
        return ew.audit(self.project, self.plan, "red", path, deps)

    def test_three_import_loader_and_gltf_embedded_external_files_form_closure(self):
        entry = self.entry("import './view.js';\nconst l = new GLTFLoader(); l.load('/art/case/styles/red/assets/tree/model.gltf');")
        view = self.file(entry.parent / "view.js", "// loader.load('/missing-comment.png');\nexport const value=1;")
        root = layout.roots(self.project, self.plan, "red")["assets"] / "tree"
        model = self.file(root / "model.gltf", json.dumps({"asset": {"version": "2.0"}, "buffers": [{"uri": "mesh.bin"}], "images": [{"uri": "leaf.png"}]}))
        mesh = self.file(root / "mesh.bin"); image = self.file(root / "leaf.png")
        result = self.audit(entry)
        self.assertTrue(result["ok"]); self.assertFalse(result["native_verified"])
        self.assertEqual({Path(row["path"]) for row in result["artifacts"]}, {entry, view, model, mesh, image})

    def test_three_bare_packages_require_real_manifest_and_lock_provenance(self):
        entry = self.entry("import {Scene} from 'three';")
        self.file("package.json", json.dumps({"dependencies": {"three": "0.180.0"}}))
        lock = self.file("package-lock.json", "{}")
        result = self.audit(entry)
        self.assertEqual(result["external_modules"], ["three"])
        self.assertIn(str(lock), {r["path"] for r in result["artifacts"]})
        lock.unlink()
        with self.assertRaisesRegex(core.WorkflowError, "lockfile"):
            self.audit(entry)

    def test_three_dynamic_paths_require_hash_bound_per_source_declaration(self):
        entry = self.entry("loader.load(selectedModel);")
        model = self.file(layout.roots(self.project, self.plan, "red")["assets"] / "tree/model.glb", synthetic_glb())
        with self.assertRaisesRegex(core.WorkflowError, "for_source"):
            self.audit(entry)
        row = {"path": str(model), "sha256": core.file_hash(model), "for_source": str(entry)}
        self.assertTrue(self.audit(entry, [row])["ok"])
        row["for_source"] = str(entry.parent / "unrelated.js")
        with self.assertRaisesRegex(core.WorkflowError, "for_source"):
            self.audit(entry, [row])

    def test_three_new_url_is_module_relative_and_imported_asset_bindings_work(self):
        entry = self.entry("import modelURL from './mesh.glb?url'; loader.load(modelURL); loader.load(new URL('./mesh.glb', import.meta.url).href);")
        model = self.file(entry.parent / "mesh.glb", synthetic_glb())
        result = self.audit(entry)
        self.assertTrue(result["ok"]); self.assertIn(str(model), {r["path"] for r in result["artifacts"]})

    def test_three_set_path_and_comments_do_not_fabricate_dependencies(self):
        entry = self.entry("/* import './missing.js'; */ loader.setPath('/art/case/styles/red/assets/tree/'); loader.load('model.glb');")
        model = self.file(layout.roots(self.project, self.plan, "red")["assets"] / "tree/model.glb", synthetic_glb())
        self.assertEqual({r["path"] for r in self.audit(entry)["artifacts"]}, {str(entry), str(model)})

    def test_three_missing_remote_and_sibling_resources_fail(self):
        entry = self.entry("loader.load('/art/case/styles/blue/assets/tree/model.glb');")
        self.file(layout.roots(self.project, self.plan, "blue")["assets"] / "tree/model.glb", synthetic_glb())
        self.assertFalse(self.audit(entry)["ok"])
        entry.write_text("loader.load('https://example.com/model.glb');")
        with self.assertRaisesRegex(core.WorkflowError, "must be local"):
            self.audit(entry)
        entry.write_text("import './missing.js';")
        with self.assertRaisesRegex(core.WorkflowError, "missing"):
            self.audit(entry)

    def test_three_gltf_remote_texture_is_rejected(self):
        entry = self.entry("loader.load('/art/case/styles/red/assets/tree/model.gltf');")
        self.file(layout.roots(self.project, self.plan, "red")["assets"] / "tree/model.gltf", json.dumps({"asset": {"version": "2.0"}, "images": [{"uri": "https://example.com/image.png"}]}))
        with self.assertRaisesRegex(ValueError, "external URL"):
            self.audit(entry)

    def test_three_html_css_source_dependencies_are_real_fields(self):
        entry = self.entry('<!-- <script src="/missing.js"></script> --><script src="./main.js"></script>', ext=".html")
        js = self.file(entry.parent / "main.js", "export const a=1;")
        self.assertIn(str(js), {r["path"] for r in self.audit(entry)["artifacts"]})

    def test_multiline_import_and_export_follow_sibling_style_modules(self):
        for keyword in ("import", "export"):
            with self.subTest(keyword=keyword):
                entry = self.entry(keyword + " {\n sky\n} from '../../blue/runtime/sky.js';")
                self.file(entry.parent / "../../blue/runtime/sky.js", "export const sky=1;")
                self.assertFalse(self.audit(entry)["ok"])

    def test_html_absolute_public_source_and_document_relative_image_namespaces(self):
        entry = self.entry('<script src="/art/case/styles/red/runtime/app.js"></script><img src="local.png">', ext=".html")
        module = self.file("public/art/case/styles/red/runtime/app.js", "export const a=1;")
        image = self.file(entry.parent / "local.png")
        paths = {r["path"] for r in self.audit(entry)["artifacts"]}
        self.assertIn(str(module), paths); self.assertIn(str(image), paths)
        self.file("art/case/styles/red/runtime/app.js", "export const conflicting=1;")
        with self.assertRaisesRegex(core.WorkflowError, "ambiguous"):
            self.audit(entry)

    def test_each_loader_path_prefix_applies_only_to_subsequent_loads(self):
        entry = self.entry("loader.setPath('/art/case/styles/blue/assets/tree/'); loader.load('model.glb'); loader.setPath('/art/case/styles/red/assets/tree/'); loader.load('model.glb');")
        for sid in ("red", "blue"):
            self.file(layout.roots(self.project, self.plan, sid)["assets"] / "tree/model.glb", synthetic_glb())
        result = self.audit(entry)
        self.assertFalse(result["ok"])
        self.assertEqual(len([r for r in result["artifacts"] if r["path"].endswith("model.glb")]), 2)

    def test_unity_package_meta_importer_remaps_are_part_of_the_closure(self):
        entry = self.entry("%YAML 1.1\n--- !u!1 &1\nGameObject: {}\n", "unity", ".unity")
        sibling = self.file(layout.roots(self.project, self.plan, "blue")["assets"] / "tree/texture.png")
        sibling_guid = self.meta(sibling)
        package = self.file("Packages/embedded/model.fbx")
        guid = self.meta(package)
        with Path(str(package) + ".meta").open("a") as stream:
            stream.write("ModelImporter:\n  texture: {fileID: 1, guid: " + sibling_guid + ", type: 3}\n")
        entry.write_text(entry.read_text() + "m_Model: {fileID: 1, guid: " + guid + ", type: 3}\n")
        result = self.audit(entry)
        self.assertFalse(result["ok"])
        self.assertIn(str(package) + ".meta", {r["path"] for r in result["artifacts"]})

    def test_unity_yaml_guid_closure_preserves_original_meta_sidecars(self):
        entry = self.entry("%YAML 1.1\n--- !u!1 &1\nGameObject:\n  m_ObjectHideFlags: 0\n", "unity", ".unity")
        root = layout.roots(self.project, self.plan, "red")["assets"] / "tree"
        image = self.file(root / "leaf.png"); image_guid = self.meta(image)
        material = self.file(root / "leaf.mat", "%YAML 1.1\n--- !u!21 &1\nMaterial:\n  m_Texture: {fileID: 2800000, guid: " + image_guid + ", type: 3}\n")
        material_guid = self.meta(material)
        entry.write_text(entry.read_text() + "  m_Material: {fileID: 2100000, guid: " + material_guid + ", type: 2}\n")
        result = self.audit(entry)
        self.assertTrue(result["ok"]); self.assertFalse(result["native_verified"])
        self.assertEqual(len(result["artifacts"]), 6)
        self.assertIn(str(image) + ".meta", {r["path"] for r in result["artifacts"]})

    def test_unity_missing_and_ambiguous_guid_are_failures(self):
        guid = "a" * 32
        entry = self.entry("%YAML 1.1\n--- !u!1 &1\nObject: {fileID: 1, guid: " + guid + ", type: 2}\n", "unity", ".prefab")
        with self.assertRaisesRegex(core.WorkflowError, "missing or ambiguous"):
            self.audit(entry)
        for name in ("one", "two"):
            asset = self.file("Assets/Art/case/styles/red/assets/tree/" + name + ".png"); self.meta(asset, guid)
        with self.assertRaisesRegex(core.WorkflowError, "missing or ambiguous"):
            self.audit(entry)

    def test_unity_builtin_and_commented_or_quoted_guids_do_not_need_assets(self):
        entry = self.entry("%YAML 1.1\n--- !u!21 &1\nMaterial:\n  m_Shader: {fileID: 46, guid: 0000000000000000f000000000000000, type: 0}\n  m_Text: \"guid: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\"\n# guid: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\n", "unity", ".mat")
        self.assertTrue(self.audit(entry)["ok"])

    def test_unity_binary_yaml_and_missing_meta_fail_without_claiming_native_pass(self):
        entry = self.entry(b"binary serialized fixture", "unity", ".asset")
        with self.assertRaisesRegex(core.WorkflowError, "Force Text"):
            self.audit(entry)
        entry.write_text("%YAML 1.1\n--- !u!1 &1\nGameObject: {}\n")
        Path(str(entry) + ".meta").unlink()
        with self.assertRaisesRegex(core.WorkflowError, "meta sidecar"):
            self.audit(entry)

    def test_unity_sibling_style_guid_resolves_then_fails_ownership(self):
        entry = self.entry("%YAML 1.1\n--- !u!1 &1\nGameObject: {}\n", "unity", ".unity")
        sibling = self.file(layout.roots(self.project, self.plan, "blue")["assets"] / "tree/model.glb", synthetic_glb())
        guid = self.meta(sibling)
        entry.write_text(entry.read_text() + "m_Mesh: {fileID: 1, guid: " + guid + ", type: 3}\n")
        self.assertFalse(self.audit(entry)["ok"])

    def test_godot_delegates_actual_resource_fields_ignoring_comment_urls(self):
        entry = self.entry('[gd_scene load_steps=2 format=3]\n; res://missing.tscn\n[ext_resource type="PackedScene" path="res://art/case/styles/red/assets/tree/model.glb" id="1"]\n[node name="root" type="Node3D"]\n', "godot", ".tscn")
        model = self.file(layout.roots(self.project, self.plan, "red")["assets"] / "tree/model.glb", synthetic_glb())
        result = self.audit(entry)
        self.assertEqual({r["path"] for r in result["artifacts"]}, {str(entry), str(model)})
        self.assertFalse(result["native_verified"])

    def test_formal_dependencies_cannot_reference_supplier_run_outputs(self):
        entry = self.entry("loader.load('/art/case/styles/red/production/runs/old/downloaded.glb');")
        # Public-transient path is rejected even if the byte exists.
        self.file("public/art/case/styles/red/production/runs/old/downloaded.glb", synthetic_glb())
        self.assertFalse(self.audit(entry)["ok"])

    def test_blender_verified_receipt_is_bound_to_source_inspector_log_and_dependencies(self):
        entry = self.entry(b"synthetic blend placeholder; not executed", "blender", ".blend")
        image = self.file(layout.roots(self.project, self.plan, "red")["assets"] / "tree/image.png")
        observed = {"source": {"path": str(entry), "sha256": core.file_hash(entry)}, "dependencies": [str(image)], "version": "synthetic"}
        stdout = ew.BLENDER_MARKER + json.dumps(observed)
        report = {"schema": 1, "kind": "blender-dependency-inspection", "source": observed["source"],
            "inspector": {"script_sha256": ew.BLENDER_SCRIPT_SHA256, "sha256": "a" * 64, "returncode": 0},
            "stdout": stdout, "stdout_sha256": hashlib.sha256(stdout.encode()).hexdigest(),
            "dependencies": [{"path": str(image), "sha256": core.file_hash(image)}]}
        receipt = self.file("inspection.json", json.dumps(report))
        self.plan["workspace"]["blender_dependency_report"] = {"path": str(receipt), "sha256": core.file_hash(receipt)}
        result = self.audit(entry)
        self.assertTrue(result["ok"]); self.assertFalse(result["actual_blender_inspection"])
        self.assertEqual(result["mode"], "spatial_only"); self.assertFalse(result["native_verified"])
        image.write_bytes(b"changed")
        with self.assertRaisesRegex(core.WorkflowError, "missing or changed"):
            self.audit(entry)

    @unittest.skipUnless(Path("/Applications/Blender.app/Contents/MacOS/Blender").is_file(), "Blender CLI not installed")
    def test_actual_blender_read_only_file_inspection_finds_external_image(self):
        binary = "/Applications/Blender.app/Contents/MacOS/Blender"
        self.plan["workspace"]["engine"] = "blender"
        entry = layout.roots(self.project, self.plan, "red")["dcc"] / "scene.blend"
        entry.parent.mkdir(parents=True, exist_ok=True)
        image = self.file(layout.roots(self.project, self.plan, "red")["assets"] / "tree/image.png",
            base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII="))
        script = "import bpy; bpy.data.images.load(" + repr(str(image)) + ").use_fake_user=True; bpy.ops.wm.save_as_mainfile(filepath=" + repr(str(entry)) + ")"
        generated = subprocess.run([binary, "--background", "--factory-startup", "--disable-autoexec", "--python-expr", script], capture_output=True, text=True, timeout=60)
        self.assertEqual(generated.returncode, 0, generated.stderr)
        before = core.file_hash(entry)
        result = self.audit(entry)
        self.assertTrue(result["ok"]); self.assertTrue(result["actual_blender_inspection"])
        self.assertFalse(result["native_verified"]); self.assertEqual(result["mode"], "spatial_only")
        self.assertEqual(core.file_hash(entry), before)
        self.assertIn(str(image), {r["path"] for r in result["artifacts"]})
        self.assertFalse(Path(str(entry) + "1").exists())
        if os.environ.get("GREYBOX_CARRIER_EVIDENCE"):
            core.write(os.environ["GREYBOX_CARRIER_EVIDENCE"], {"test": self.id(), "passed": True,
                "fixture_retained": False, "fixture_lifecycle": "Tiny task-owned fixture deleted after test; no live Blender scene changed",
                "native_verified": False, "mode": result["mode"], "artifacts": result["artifacts"],
                "inspections": result["inspections"], "source_sha256_after": core.file_hash(entry)})


if __name__ == "__main__":
    unittest.main()
