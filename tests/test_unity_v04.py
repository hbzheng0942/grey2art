import json
import errno
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/greybox-to-multistyle-art/runtime"))
from greybox import unity


class UnityV04Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.write("ProjectSettings/ProjectVersion.txt", "m_EditorVersion: 6000.3.26f1\n")
        self.write("Packages/manifest.json", json.dumps({"dependencies": {"com.unity.render-pipelines.universal": "17.3.0"}}))
        self.write("Assets/Main.unity", "%YAML 1.1\n")
        self.write("ProjectSettings/EditorBuildSettings.asset", "  m_Scenes:\n  - enabled: 1\n    path: Assets/Main.unity\n")

    def write(self, name, data):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data if isinstance(data, bytes) else data.encode())
        return path

    def test_inventory_uses_project_version_and_manifest(self):
        with patch.object(unity, "engine", return_value="Unity"):
            info = unity.inspect(self.root)
        self.assertEqual(info["main_scene"], "Assets/Main.unity")
        self.assertEqual(info["version"], "6000.3.26f1")
        self.assertEqual(info["render_pipeline"], "urp")

    def test_guid_closure_and_code_settings_invalidate_sources(self):
        material = self.write("Assets/Shared.mat", "name: Shared\n")
        self.write("Assets/Shared.mat.meta", "guid: " + "a" * 32)
        self.write("Assets/Main.unity", "m_Material: {fileID: 1, guid: " + "a" * 32 + ", type: 2}\n")
        code = self.write("Assets/Gameplay.cs", "class Gameplay {}")
        snap = unity.dependency_snapshot(self.root, {"contract": {"scene": "Assets/Main.unity"}})
        paths = {row["path"] for row in snap}
        self.assertIn(str(material), paths)
        self.assertIn(str(code), paths)
        self.assertIn(str(self.root / "Packages/manifest.json"), paths)
        artifact = {"sources": snap}
        code.write_text("class Gameplay { int changed; }")
        with self.assertRaisesRegex(ValueError, "changed"):
            unity._check_artifact(artifact)

    def test_reject_external_or_godot_resource_and_traversal(self):
        for path in ("../escape.unity", "res://main.tscn", "/tmp/external.unity"):
            with self.assertRaises(ValueError):
                unity.project_path(self.root, path)
        with self.assertRaisesRegex(ValueError, "Assets"):
            unity._request(self.root, "assemble", {"output_root": "art/scene"}, self.root / "evidence")

    def test_install_bridge_preserves_local_edits(self):
        installed = unity.install_bridge(self.root)
        self.assertTrue(installed["files"])
        bridge = Path(installed["files"][0]["path"])
        bridge.write_text("// user work")
        with self.assertRaisesRegex(ValueError, "local changes"):
            unity.install_bridge(self.root)
        self.assertEqual(bridge.read_text(), "// user work")

    def test_packages_add_pin_without_upgrading_existing(self):
        self.write("Packages/manifest.json", json.dumps({"dependencies": {"com.unity.render-pipelines.universal": "17.3.1"}}))
        receipt = unity.configure_packages(self.root)
        self.assertEqual(receipt["packages"]["com.unity.render-pipelines.universal"], "17.3.1")
        self.assertEqual(receipt["changed"], {"com.unity.cloud.gltfast": unity.GLTFAST_VERSION})

    def test_request_retains_masks_exclusions_and_reference_paths(self):
        req = unity._request(self.root, "capture", {"effects": {"grass": {"exclude_rects": [[0, 0, 1, 1]], "density_mask": "Assets/mask.png"}}}, self.root / "evidence")
        self.assertEqual(req["recipes"]["grass"]["exclusions"], [{"bounds": [0, 0, 1, 1]}])
        self.assertEqual(req["recipes"]["grass"]["density_mask"], "Assets/mask.png")

    def invoke(self, callback):
        with patch.object(unity, "engine", return_value="Unity"), patch.object(unity.subprocess, "run", side_effect=callback):
            return unity.run(self.root, "inspect", output=self.root / "evidence")

    def test_exit_zero_without_report_cannot_succeed(self):
        result = self.invoke(lambda *a, **k: subprocess.CompletedProcess(a, 0, "", ""))
        self.assertFalse(result["ok"])
        self.assertIn("did not produce", result["errors"][0])

    def test_stale_receipt_rejected_even_exit_zero(self):
        self.write("evidence/report.json", json.dumps({"ok": True, "request_id": "old", "operation": "inspect", "binding_digest": "old"}))
        result = self.invoke(lambda *a, **k: subprocess.CompletedProcess(a, 0, "", ""))
        self.assertFalse(result["ok"])
        self.assertTrue(any("request_id" in error for error in result["errors"]))

    def test_bound_receipt_and_real_graphics_command(self):
        def execute(command, **kwargs):
            self.assertNotIn("-nographics", command)
            req = json.loads(Path(command[command.index("-greyboxRequest") + 1]).read_text())
            self.write("evidence/report.json", json.dumps({"ok": True, "request_id": req["request_id"], "operation": req["operation"], "binding_digest": req["binding_digest"], "errors": []}))
            return subprocess.CompletedProcess(command, 0, "", "")
        result = self.invoke(execute)
        self.assertTrue(result["ok"])

    def test_unsupported_recipe_parameter_rejected_instead_of_silent_drop(self):
        with self.assertRaisesRegex(ValueError, "Unsupported Unity water"):
            unity._recipes({"water": {"unsupported_quality": "high"}})
        with self.assertRaises(ValueError):
            unity._recipes({"ground": {"tile_scale": float("nan")}})

    def test_common_effect_semantics_convert_to_native_parameters(self):
        recipes = unity._recipes({"lighting": {"exposure": 2, "bloom": True}, "grass": {"y": 3}})
        self.assertEqual(recipes["lighting"]["exposure"], 1)
        self.assertEqual(recipes["lighting"]["bloom"], .25)
        self.assertEqual(recipes["grass"]["ground_y"], 3)
        with self.assertRaisesRegex(ValueError, "positive brightness"):
            unity._recipes({"lighting": {"exposure": 0}})

    def test_gameplay_contract_not_structural_assertions_drives_verification(self):
        contract = {"validation": {"steps": [{"id": "move", "hook": {"path": "Gameplay", "method": "Probe"}, "expect": {"moved": True, "score": 2}}]}}
        req = unity._request(self.root, "validate", {"artifact": {"contract": contract, "entry_scene": "Assets/Main.unity"}}, self.root / "evidence")
        self.assertEqual(req["validation_steps"][0]["hook_path"], "Gameplay")
        self.assertEqual({e["key"]: e["kind"] for e in req["validation_steps"][0]["expectations"]}, {"moved": "bool", "score": "number"})
        with self.assertRaisesRegex(ValueError, "explicit gameplay hook"):
            unity._request(self.root, "validate", {"plan": {"contract": {"validation": {"steps": [{"input_action": "jump"}]}}}}, self.root / "evidence")

    def test_uniform_envelope_and_bottom_anchor_are_explicit(self):
        binding = {"id": "asset", "owner": "Gameplay", "anchor_mode": "bottom_center", "normalize": {"mode": "uniform_bounds", "target_size": [1, 2, 3]}, "source": {"primitive": "box"}}
        req = unity._request(self.root, "assemble", {"bindings": [binding]}, self.root / "evidence")
        self.assertEqual(req["bindings"][0]["normalize"]["target_size"], [1, 2, 3])
        binding["normalize"]["target_size"] = [1, 0, 3]
        with self.assertRaisesRegex(ValueError, "positive dimensions"):
            unity._request(self.root, "assemble", {"bindings": [binding]}, self.root / "evidence")

    def test_direct_validation_binds_sources_and_rejects_native_mutation(self):
        code = self.write("Assets/Gameplay.cs", "class Gameplay {}")
        def execute(command, **kwargs):
            req = json.loads(Path(command[command.index("-greyboxRequest") + 1]).read_text())
            Path(req["report"]).write_text(json.dumps({"ok": True, "request_id": req["request_id"], "operation": req["operation"], "binding_digest": req["binding_digest"], "captures": [], "errors": []}))
            code.write_text("class Gameplay { int changed; }")
            return subprocess.CompletedProcess(command, 0, "", "")
        with patch.object(unity, "engine", return_value="Unity"), patch.object(unity.subprocess, "run", side_effect=execute):
            result = unity.run(self.root, "validate", {"scene": "Assets/Main.unity"}, output=self.root / "evidence")
        self.assertFalse(result["passed"])
        self.assertTrue(result["source_hashes"])
        self.assertTrue(any("source changed" in error for error in result["errors"]))

    def test_admission_small_copy_is_bounded_and_records_canonical_provenance(self):
        source = self.write("canonical/source.glb", b"model-bytes")
        with patch.object(unity, "_apfs_clone", side_effect=OSError(errno.ENOTSUP, "fixture unsupported")):
            admitted = unity.admit_asset(self.root, source, "Assets/Art/model.glb")
        self.assertEqual(admitted["method"], "bounded-copy")
        self.assertEqual(admitted["sha256"], unity.digest(source))
        target = self.root / admitted["path"]
        target.write_bytes(b"independent-edit")
        self.assertEqual(source.read_bytes(), b"model-bytes")
        with self.assertRaisesRegex(ValueError, "overwrite changed"):
            unity.admit_asset(self.root, source, admitted["path"])
        self.assertTrue((self.root / "art/asset-admission.json").is_file())

    def test_admission_never_falls_back_for_large_or_clone_only_transfer(self):
        source = self.write("canonical/source.glb", b"model-bytes")
        with patch.object(unity, "_apfs_clone", side_effect=OSError(errno.ENOTSUP, "fixture unsupported")):
            with self.assertRaisesRegex(ValueError, "bounded-copy limits"):
                unity.admit_asset(self.root, source, "Assets/large.glb", max_copy_bytes=1)
            with self.assertRaisesRegex(ValueError, "no copy fallback"):
                unity.admit_asset(self.root, source, "Assets/clone-only.glb", require_clone=True)
        self.assertFalse((self.root / "Assets/large.glb").exists())

    def test_owned_rebuild_requires_matching_parameters_and_owned_hashes(self):
        scene = self.root / "Assets/Main.unity"
        previous = {"project": str(self.root), "output_root": "Assets/Art/revision", "binding_digest": "binding",
                    "owned_files": [{"path": str(scene), "sha256": unity.digest(scene)}]}
        req = {"operation": "assemble", "output_root": previous["output_root"], "binding_digest": "binding"}
        unity._check_owned_rebuild(self.root, previous, req)
        with self.assertRaisesRegex(ValueError, "identical assembly"):
            unity._check_owned_rebuild(self.root, previous, {**req, "binding_digest": "changed"})
        scene.write_text("user changed scene")
        with self.assertRaisesRegex(ValueError, "changed"):
            unity._check_owned_rebuild(self.root, previous, req)

    def test_build_settings_are_hashed_without_cross_style_scene_closure(self):
        guid = "b" * 32
        other = self.write("Assets/OtherStyle.unity", "a different scene")
        self.write("Assets/OtherStyle.unity.meta", "guid: " + guid)
        self.write("ProjectSettings/EditorBuildSettings.asset", "path: Assets/Main.unity\nguid: " + guid)
        rows = unity.dependency_snapshot(self.root, {"contract": {"scene": "Assets/Main.unity"}})
        self.assertIn(str(self.root / "ProjectSettings/EditorBuildSettings.asset"), {r["path"] for r in rows})
        self.assertNotIn(str(other), {r["path"] for r in rows})

    @unittest.skipUnless(sys.platform == "darwin", "APFS clonefile is a macOS operation")
    def test_actual_apfs_admission_preserves_metadata_and_independent_later_edits(self):
        source = self.write("canonical/source.glb", b"original-small-model")
        source.chmod(0o640)
        receipt = unity.admit_asset(self.root, source, "Assets/Art/cloned.glb", require_clone=True)
        self.assertEqual(receipt["method"], "apfs-clonefile")
        target = self.root / receipt["path"]
        self.assertNotEqual(source.stat().st_ino, target.stat().st_ino)
        self.assertEqual(unity._asset_metadata(source), unity._asset_metadata(target))
        target.write_bytes(b"clone edit")
        self.assertEqual(source.read_bytes(), b"original-small-model")
        source.write_bytes(b"source edit")
        self.assertEqual(target.read_bytes(), b"clone edit")

    def test_admission_serializes_ledger_and_target_ownership(self):
        from greybox import core
        source = self.write("canonical/source.glb", b"model")
        with core.locked(self.root / "art/asset-admission"):
            with self.assertRaisesRegex(core.WorkflowError, "live process"):
                unity.admit_asset(self.root, source, "Assets/Art/model.glb")
        self.assertFalse((self.root / "Assets/Art/model.glb").exists())

    def test_shader_closure_is_selected_style_specific_while_csharp_stays_global(self):
        matguid, shaderguid = "a"*32, "c"*32
        self.write("Assets/Main.unity", "material: {guid: "+matguid+"}\n")
        self.write("Assets/ceramic/scene.mat", "shader: {guid: "+shaderguid+"}\n")
        self.write("Assets/ceramic/scene.mat.meta", "guid: "+matguid)
        shader=self.write("Assets/ceramic/surface.shader", '#include "surface.hlsl"\n')
        self.write("Assets/ceramic/surface.shader.meta", "guid: "+shaderguid)
        include=self.write("Assets/ceramic/surface.hlsl", "float4 color;")
        unrelated=self.write("Assets/orbital/new.shader", "unrelated shader")
        global_cs=self.write("Assets/orbital/Behaviour.cs", "class Behaviour {}")
        plan={"contract":{"scene":"Assets/Main.unity"}}
        before=unity.dependency_snapshot(self.root,plan)
        paths={r["path"] for r in before}
        self.assertIn(str(shader),paths);self.assertIn(str(include),paths);self.assertIn(str(global_cs),paths)
        self.assertNotIn(str(unrelated),paths)
        unrelated.write_text("changed other-style shader")
        self.assertEqual(before,unity.dependency_snapshot(self.root,plan))

    def test_shadergraph_embedded_texture_guids_are_bound(self):
        guid="d"*32
        texture=self.write("Assets/ceramic/color.png",b"texture-data")
        self.write("Assets/ceramic/color.png.meta","guid: "+guid)
        self.write("Assets/ceramic/surface.shadergraph",json.dumps({"m_SerializedTexture":json.dumps({"texture":{"guid":guid}})}))
        rows=unity.dependency_snapshot(self.root,{"contract":{"scene":"Assets/Main.unity","source_paths":["Assets/ceramic/surface.shadergraph"]}})
        self.assertIn(str(texture),{r["path"] for r in rows})

    def test_export_scene_list_defaults_and_rejects_invalid_or_duplicate_scenes(self):
        req=unity._request(self.root,"export",{},self.root/"evidence")
        self.assertEqual(req["build_scenes"],["Assets/Main.unity"])
        self.write("Assets/Other.unity","other scene")
        req=unity._request(self.root,"export",{"build_scenes":["Assets/Other.unity","Assets/Main.unity"]},self.root/"evidence")
        self.assertEqual(req["build_scenes"],["Assets/Other.unity","Assets/Main.unity"])
        for scenes in ([],["Assets/Missing.unity"],["Assets/Main.unity"]*2,["ProjectSettings/ProjectVersion.txt"],"Assets/Main.unity"):
            with self.assertRaises(ValueError): unity._request(self.root,"export",{"build_scenes":scenes},self.root/"evidence")

    def test_export_binds_additional_scene_closure_and_rejects_build_mutation(self):
        guid="e"*32
        secondary=self.write("Assets/Other.unity","material: {guid: "+guid+"}\n")
        material=self.write("Assets/Other.mat","secondary material")
        self.write("Assets/Other.mat.meta","guid: "+guid)
        self.write("Assets/Unselected.unity","unselected scene")
        def execute(command,**kwargs):
            req=json.loads(Path(command[command.index("-greyboxRequest")+1]).read_text())
            Path(req["report"]).write_text(json.dumps({"ok":True,"request_id":req["request_id"],"operation":req["operation"],
                "binding_digest":req["binding_digest"],"build_scenes":req["build_scenes"],"errors":[]}))
            material.write_text("changed during native build")
            return subprocess.CompletedProcess(command,0,"","")
        with patch.object(unity,"engine",return_value="Unity"),patch.object(unity.subprocess,"run",side_effect=execute):
            result=unity.run(self.root,"export",{"build_scenes":["Assets/Main.unity","Assets/Other.unity"]},output=self.root/"evidence")
        self.assertFalse(result["ok"])
        paths={row["path"] for row in result["source_hashes"]}
        self.assertIn(str(secondary),paths);self.assertIn(str(material),paths)
        self.assertNotIn(str(self.root/"Assets/Unselected.unity"),paths)
        self.assertTrue(any("source changed" in error for error in result["errors"]))

    def test_export_freezes_automatic_resources_and_rejects_new_packed_inputs(self):
        resource=self.write("Assets/Nested/Resources/unreferenced.json",'{"color":"ivory"}')
        def execute(command,**kwargs):
            req=json.loads(Path(command[command.index("-greyboxRequest")+1]).read_text())
            new=self.write("Assets/CreatedDuringBuild.mat","not a pre-build input")
            Path(req["report"]).write_text(json.dumps({"ok":True,"request_id":req["request_id"],"operation":req["operation"],
                "binding_digest":req["binding_digest"],"build_scenes":req["build_scenes"],
                "packed_sources":[{"path":"Assets/CreatedDuringBuild.mat"}],"errors":[]}))
            return subprocess.CompletedProcess(command,0,"","")
        with patch.object(unity,"engine",return_value="Unity"),patch.object(unity.subprocess,"run",side_effect=execute):
            result=unity.run(self.root,"export",output=self.root/"evidence")
        self.assertIn(str(resource),{row["path"] for row in result["source_hashes"]})
        self.assertFalse(result["ok"])
        self.assertTrue(any("unfrozen project source" in error for error in result["errors"]))

    def test_export_rejects_shader_include_created_during_build(self):
        self.write("Assets/Resources/Surface.shader",'#include "Late.hlsl"\n')
        def execute(command,**kwargs):
            req=json.loads(Path(command[command.index("-greyboxRequest")+1]).read_text())
            self.write("Assets/Resources/Late.hlsl","float4 late_color;")
            Path(req["report"]).write_text(json.dumps({"ok":True,"request_id":req["request_id"],"operation":req["operation"],
                "binding_digest":req["binding_digest"],"build_scenes":req["build_scenes"],"errors":[]}))
            return subprocess.CompletedProcess(command,0,"","")
        with patch.object(unity,"engine",return_value="Unity"),patch.object(unity.subprocess,"run",side_effect=execute):
            result=unity.run(self.root,"export",output=self.root/"evidence")
        self.assertFalse(result["ok"])
        self.assertTrue(any("new source dependency" in error and "Late.hlsl" in error for error in result["errors"]))

    def test_export_records_only_verified_pinned_package_metadata_outputs(self):
        producer="com.unity.test-framework.performance"
        reported_version="3.5.0"
        self.write("Packages/packages-lock.json",json.dumps({"dependencies":{producer:{"version":"3.5.0"}}}))
        def execute(command,**kwargs):
            req=json.loads(Path(command[command.index("-greyboxRequest")+1]).read_text())
            evidence=self.write(str(Path(req["evidence_root"])/"generated-PerformanceTestRunInfo.json"),'{"Editor":{"Version":"6000.3.26f1"}}')
            generated={"path":"Assets/Resources/PerformanceTestRunInfo.json","sha256":unity.digest(evidence),"evidence":str(evidence),"producer":producer,"producer_version":reported_version}
            Path(req["report"]).write_text(json.dumps({"ok":True,"request_id":req["request_id"],"operation":req["operation"],
                "binding_digest":req["binding_digest"],"build_scenes":req["build_scenes"],"generated_inputs":[generated],"packed_sources":[{"path":generated["path"]}],"errors":[]}))
            return subprocess.CompletedProcess(command,0,"","")
        with patch.object(unity,"engine",return_value="Unity"),patch.object(unity.subprocess,"run",side_effect=execute):
            result=unity.run(self.root,"export",output=self.root/"evidence")
        self.assertTrue(result["ok"],result["errors"])
        self.assertTrue(result["generated_inputs"])
        reported_version="3.5.1"
        with patch.object(unity,"engine",return_value="Unity"),patch.object(unity.subprocess,"run",side_effect=execute):
            rejected=unity.run(self.root,"export",output=self.root/"evidence")
        self.assertFalse(rejected["ok"])
        self.assertTrue(any("unsupported generated metadata producer" in error for error in rejected["errors"]))


if __name__ == "__main__":
    unittest.main()
