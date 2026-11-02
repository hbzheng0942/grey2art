"""Portable Blender contracts; actual Blender checks run separately, without generation."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1] / "skills/greybox-to-multistyle-art"
sys.path.insert(0, str(ROOT / "runtime"))
from greybox.blender import (build_script, digest, prepare_job, read_glb,
                             validate_job, validate_native_admission, verify_result)


def glb(path, document):
    blob = json.dumps(document).encode()
    blob += b" " * (-len(blob) % 4)
    path.write_bytes(struct.pack("<4sII", b"glTF", 2, 20 + len(blob)) + struct.pack("<I4s", len(blob), b"JSON") + blob)


class BlenderBackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.job = {"schema": 1, "job_id": "test-job", "asset_id": "crate",
                    "kind": "diagnostic_cube", "output_dir": str(self.root / "job"),
                    "normalize": {"unit_scale": 1, "anchor": "base_center"}, "render": False}

    def tearDown(self):
        self.temp.cleanup()

    def completed(self):
        output = Path(self.job["output_dir"])
        output.mkdir()
        glb(output / "asset.glb", {"asset": {"version": "2.0"}, "nodes": [{"mesh": 0, "extras": {"stable_id": "crate:mesh:000"}}]})
        report = {"status": "complete", "job_sha256": hashlib.sha256(json.dumps(self.job, sort_keys=True).encode()).hexdigest(),
                  "input": None, "user_state_restored": True, "dimensions_m": [1, 1, 1],
                  "output": {"sha256": digest(output / "asset.glb")}}
        (output / "report.json").write_text(json.dumps(report))
        return output, report

    def test_build_is_offline_and_does_not_save_or_open_user_blend(self):
        script = build_script(self.job)
        compile(script, "blender-job", "exec")
        self.assertFalse(Path(self.job["output_dir"]).exists())
        self.assertNotIn("save_as_mainfile", script)
        self.assertNotIn("open_mainfile", script)
        self.assertIn("user_state_restored", script)

    def test_existing_output_and_unrelated_directory_are_refused(self):
        output = Path(self.job["output_dir"])
        output.mkdir()
        (output / "user-file.txt").write_text("preserve")
        with self.assertRaisesRegex(ValueError, "unrelated"):
            prepare_job(self.job)
        self.assertEqual((output / "user-file.txt").read_text(), "preserve")

    def test_job_script_recovery_requires_exact_content(self):
        first = prepare_job(self.job)
        self.assertEqual(first, prepare_job(self.job))
        Path(first["script_path"]).write_text("changed")
        with self.assertRaisesRegex(ValueError, "changed"):
            prepare_job(self.job)

    def test_rigs_and_unsupported_operations_are_not_flattened(self):
        self.job["kind"] = "character_fbx"
        with self.assertRaisesRegex(ValueError, "rigs"):
            validate_job(self.job)
        self.job["kind"] = "diagnostic_cube"
        self.job["operations"] = [{"type": "remesh"}]
        with self.assertRaisesRegex(ValueError, "Only.*bevel"):
            validate_job(self.job)

    def test_nonuniform_fitting_and_invalid_scales_are_refused(self):
        for scale in (0, -1, True, float("nan")):
            self.job["normalize"]["unit_scale"] = scale
            with self.assertRaises(ValueError):
                validate_job(self.job)
        self.job["normalize"] = {"scale_xyz": [1, 2, 3]}
        with self.assertRaisesRegex(ValueError, "uniform"):
            validate_job(self.job)

    def test_input_hash_and_embedded_dependency_admission(self):
        path = self.root / "source.glb"
        glb(path, {"asset": {"version": "2.0"}})
        self.job.update(kind="static_glb", input={"path": str(path), "sha256": digest(path)})
        self.assertTrue(validate_job(self.job)["ok"])
        self.job["input"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "hash"):
            validate_job(self.job)
        glb(path, {"images": [{"uri": "../mutable.png"}]})
        self.job["input"]["sha256"] = digest(path)
        with self.assertRaisesRegex(ValueError, "external dependencies"):
            validate_job(self.job)

    def test_completed_output_is_bound_to_input_job_and_export(self):
        output, report = self.completed()
        self.assertTrue(verify_result(self.job)["ok"])
        (output / "asset.glb").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "changed"):
            verify_result(self.job)

    def test_stable_ids_and_user_document_state_required(self):
        output, report = self.completed()
        report["user_state_restored"] = False
        with self.assertRaisesRegex(ValueError, "state"):
            verify_result(self.job, report)
        report["user_state_restored"] = True
        glb(output / "asset.glb", {"nodes": [{"mesh": 0}]})
        report["output"]["sha256"] = digest(output / "asset.glb")
        with self.assertRaisesRegex(ValueError, "stable"):
            verify_result(self.job, report)

    def test_native_export_is_not_native_import_acceptance(self):
        output, report = self.completed()
        self.assertEqual(verify_result(self.job)["native_admission"], "pending")
        receipt = {"engine": "godot", "asset_sha256": digest(output / "asset.glb"),
                   "status": "passed", "evidence_path": str(self.root / "missing.json"),
                   "checks": {"mesh_bounds": True, "materials": True, "stable_ids": True}}
        with self.assertRaisesRegex(ValueError, "evidence"):
            validate_native_admission(self.job, receipt)

    def test_native_evidence_contents_not_just_pass_flag(self):
        output, report = self.completed()
        evidence = self.root / "native.json"
        evidence.write_text(json.dumps({"status": "passed"}))
        receipt = {"engine": "godot", "asset_sha256": digest(output / "asset.glb"),
                   "status": "passed", "evidence_path": str(evidence), "evidence_sha256": digest(evidence),
                   "checks": {"mesh_bounds": True, "materials": True, "stable_ids": True}}
        with self.assertRaisesRegex(ValueError, "contents"):
            validate_native_admission(self.job, receipt)
        actual = {key: receipt[key] for key in ("engine", "asset_sha256", "status", "checks")}
        evidence.write_text(json.dumps(actual))
        receipt["evidence_sha256"] = digest(evidence)
        self.assertTrue(validate_native_admission(self.job, receipt)["ok"])
        actual["checks"]["materials"] = False
        evidence.write_text(json.dumps(actual))
        receipt["evidence_sha256"] = digest(evidence)
        with self.assertRaisesRegex(ValueError, "materials"):
            validate_native_admission(self.job, receipt)

    def test_changed_job_cannot_reuse_completed_report(self):
        self.completed()
        self.job["normalize"]["target_height_m"] = 2
        with self.assertRaisesRegex(ValueError, "match"):
            verify_result(self.job)

    def test_duplicate_semantic_anchor_names_refused(self):
        self.job["semantic_anchors"] = [{"id": "support", "position_m": [0, 0, 0]}] * 2
        with self.assertRaisesRegex(ValueError, "unique"):
            validate_job(self.job)

    def test_truncated_glb_rejected(self):
        path = self.root / "bad.glb"
        path.write_bytes(b"glTF")
        with self.assertRaisesRegex(ValueError, "Truncated"):
            read_glb(path)


if __name__ == "__main__":
    unittest.main()
