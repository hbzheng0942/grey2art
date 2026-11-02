"""Unmocked Unity dependency closure cannot pollute frozen baseline inputs."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/greybox-to-multistyle-art/runtime"))
from greybox import core, unity, engines


class EngineSourceIdentityV04(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="unity-source-identity-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        for name, text in {"ProjectSettings/ProjectVersion.txt": "m_EditorVersion: 6000.3.26f1\n",
                           "Packages/manifest.json": '{"dependencies":{}}',
                           "Assets/Main.unity": "%YAML 1.1\n--- scene baseline",
                           "Assets/Gameplay.cs": "class Gameplay {}"}.items():
            self.write(name, text)
        self.plan = {"engine": "unity", "styles": [{"id": "ink"}], "assets": [], "bindings": [],
                     "contract": {"scene": "Assets/Main.unity"},
                     "workspace": {"schema": 1, "case_id": "test", "engine": "unity", "asset_owners": {}}}

    def write(self, name, text):
        path = self.root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text)
        return path

    def test_new_bridge_and_style_code_are_artifact_outputs_not_baseline_drift(self):
        initial = core.input_snapshot(self.root, self.plan)
        bridge = self.write("Assets/GreyboxArtRuntime/Editor/GreyboxBridge.cs", "class GreyboxBridge {}")
        self.write("Assets/GreyboxArtRuntime/Editor/GreyboxBridge.cs.meta", "guid: " + "a" * 32)
        shader = self.write("Assets/Art/test/styles/ink/runtime/style.shader", "Shader style {}")
        native = unity.dependency_snapshot(self.root, self.plan)
        self.assertIn(str(bridge), {item["path"] for item in native})
        self.assertNotIn(str(shader), {item["path"] for item in native})
        self.assertEqual(initial["sha256"], core.input_snapshot(self.root, self.plan)["sha256"])
        self.write("Assets/Gameplay.cs", "class Gameplay { int changed; }")
        self.assertNotEqual(initial["sha256"], core.input_snapshot(self.root, self.plan)["sha256"])

    def test_explicit_source_under_engine_tools_and_its_meta_stay_hash_bound(self):
        path = self.write("Assets/GreyboxArtRuntime/Explicit.cs", "class Explicit {}")
        meta = self.write("Assets/GreyboxArtRuntime/Explicit.cs.meta", "guid: " + "b" * 32)
        self.plan["contract"]["source_paths"] = ["Assets/GreyboxArtRuntime/Explicit.cs"]
        initial = core.input_snapshot(self.root, self.plan)
        self.assertIn(str(path), initial["files"])
        self.assertIn(str(meta), initial["files"])
        path.write_text("class Explicit { int changed; }")
        self.assertNotEqual(initial["sha256"], core.input_snapshot(self.root, self.plan)["sha256"])

    def test_nonworkspace_unity_assembly_target_is_importable_and_stable(self):
        plan = {"id": "native-case", "engine": "unity", "contract": {"scene": "Assets/Main.unity"}}
        result = {"artifact": {"entry_scene": "Assets/Art/Greybox/native-case/ink/play.unity", "binding_digest": "hash"}}
        with patch("greybox.unity.run", return_value=result) as native:
            engines.UnityAdapter.assemble(self.root, self.root / "art/runs/one", plan, "ink")
        target = Path(native.call_args.kwargs["config"]["output_root"])
        self.assertTrue(core.inside(target, self.root / "Assets"))
        with patch("greybox.unity.run", return_value=result) as other:
            engines.UnityAdapter.assemble(self.root, self.root / "art/runs/two", plan, "ink")
        self.assertEqual(str(target), other.call_args.kwargs["config"]["output_root"])
        self.write("Assets/Gameplay.cs", "class Gameplay { int changed; }")
        with patch("greybox.unity.run", return_value=result) as changed:
            engines.UnityAdapter.assemble(self.root, self.root / "art/runs/three", plan, "ink")
        self.assertNotEqual(str(target), changed.call_args.kwargs["config"]["output_root"])

    def test_reused_unity_asset_outside_assets_uses_packaged_admission(self):
        source = self.write("canonical/model.glb", "canonical model")
        h = core.file_hash(source)
        self.plan["assets"] = [{"id": "model"}]
        self.plan["workspace"]["asset_owners"] = {"model": {"scope": "shared"}}
        def admit(project, path, target):
            self.assertEqual(path, source)
            self.assertTrue(core.inside(target, self.root / "Assets"))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
            return {"path": target.relative_to(self.root).as_posix(), "sha256": h}
        with patch("greybox.unity.admit_asset", side_effect=admit) as admitted:
            record = core._canonical(source, self.root, self.plan, "model")
        admitted.assert_called_once()
        self.assertTrue(record["path"].startswith("Assets/"))
        self.assertEqual(record["sha256"], h)
        self.assertTrue(source.is_file())

    def test_external_unity_formats_are_not_relabelled_as_glb(self):
        source = self.write("canonical/model.fbx", "fbx bytes")
        self.plan["assets"] = [{"id": "model"}]
        self.plan["workspace"]["asset_owners"] = {"model": {"scope": "shared"}}
        with patch("greybox.unity.admit_asset") as admitted:
            for plan in (self.plan, {"engine": "unity"}):
                with self.assertRaisesRegex(ValueError, "self-contained GLB"):
                    core._canonical(source, self.root, plan, "model")
        admitted.assert_not_called()

    def test_nonworkspace_core_registers_and_retains_exact_unity_revision(self):
        plan = {"schema": 1, "kind": "greybox-art-plan", "id": "native-case", "engine": "unity",
                "purpose": "technical_fixture", "delivery_mode": "single_style", "styles": [{"id": "ink"}],
                "assets": [], "contract": {"scene": "Assets/Main.unity", "validation": {"mode": "technical_only"}},
                "bindings": [{"id": "art", "owner": "Root", "source": {"primitive": "box"}}]}
        config = self.root / "plan.json"; core.write(config, plan)
        run = self.root / "art/experiments/one"
        core.prepare(config, self.root, run)
        revision = self.root / "Assets/Art/Greybox/native-case/ink/1234567890abcdef"
        file = self.write(str(revision.relative_to(self.root) / "play.unity"), "owned scene")
        tool = self.write("Assets/GreyboxArtRuntime/Editor/GreyboxBridge.cs", "owned tool")
        rows = [{"path": str(file), "sha256": core.file_hash(file), "retention": "canonical_revision"},
                {"path": str(tool), "sha256": core.file_hash(tool), "retention": "canonical_tool", "role": "tool"}]
        class Native:
            def assemble(self, *args, **kwargs):
                return {"entry_scene": file.relative_to(self_root).as_posix(), "output_root": str(revision),
                        "binding_digest": "bound", "owned_files": rows}
        self_root = self.root
        result = core.run(run, adapter=Native())
        self.assertEqual(result["state"], "assembled")
        rolled = core.rollback(run)
        self.assertTrue(rolled["ok"])
        self.assertEqual(set(rolled["retainedCanonical"]), {str(file), str(tool)})
        self.assertTrue(file.is_file() and tool.is_file())
        unrelated = {"path": str(self.root / "Assets/Gameplay.cs"), "retention": "canonical_revision"}
        with self.assertRaisesRegex(ValueError, "exact immutable revision"):
            engines.validate_unity_owned(self.root, plan, "ink", {"output_root": str(revision)}, unrelated)


if __name__ == "__main__":
    unittest.main()
