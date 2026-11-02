"""Native admission rejects false green process/report combinations."""
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1] / "skills/greybox-to-multistyle-art"
sys.path.insert(0, str(ROOT / "runtime"))
from greybox.blender import digest
from greybox.blender_godot import fatal_log_lines, native_admit, verify_godot_admission


class BlenderGodotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        output = self.root / "blender"
        output.mkdir()
        self.job = {"schema": 1, "job_id": "test", "asset_id": "crate", "kind": "diagnostic_cube", "output_dir": str(output)}
        blob = json.dumps({"nodes": [{"mesh": 0, "extras": {"stable_id": "crate:mesh:000"}}]}).encode()
        blob += b" " * (-len(blob) % 4)
        (output / "asset.glb").write_bytes(struct.pack("<4sII", b"glTF", 2, 20 + len(blob)) + struct.pack("<I4s", len(blob), b"JSON") + blob)
        (output / "report.json").write_text(json.dumps({"status": "complete", "job_sha256": hashlib.sha256(json.dumps(self.job, sort_keys=True).encode()).hexdigest(),
            "input": None, "user_state_restored": True, "dimensions_m": [1, 2, 3],
            "output": {"sha256": digest(output / "asset.glb")}, "materials": []}))
        self.engine = self.root / "godot"
        self.engine.write_bytes(b"test executable binding")
        self.extra_log = ""
        self.returncode = 0
        self.wrong_identity = False

    def tearDown(self):
        self.temp.cleanup()

    def simulated_process(self, args, **kwargs):
        if args[-1] == "--version":
            return subprocess.CompletedProcess(args, 0, "4.7.2.stable.official\n", "")
        config = json.loads(Path(args[-1]).read_text())
        actual = {"engine": "godot", "attempt": config["attempt"], "status": "passed",
                  "asset_sha256": "0" * 64 if self.wrong_identity else config["asset_sha256"],
                  "checks": {"mesh_bounds": True, "stable_ids": True, "materials": True}}
        Path(config["output_path"]).write_text(json.dumps(actual))
        return subprocess.CompletedProcess(args, self.returncode, "Godot Engine test\n" + self.extra_log, "")

    def run_probe(self):
        with patch("greybox.blender_godot.engine", return_value=str(self.engine)), patch("greybox.blender_godot.subprocess.run", side_effect=self.simulated_process):
            return native_admit(self.job)

    def test_log_error_parser_detects_engine_script_parser_errors(self):
        for line in ("ERROR: Condition !is_inside_tree", "SCRIPT ERROR: Parse Error", "  Parse Error: bad type", "E 0:00:01: engine failure"):
            self.assertEqual(fatal_log_lines(line), [line])
        self.assertFalse(fatal_log_lines("WARNING: sample\nImport complete: 0 errors"))

    def test_exit_zero_pass_report_with_engine_error_is_rejected(self):
        self.extra_log = "ERROR: Condition !is_inside_tree is true\n"
        with self.assertRaisesRegex(ValueError, "engine error"):
            self.run_probe()
        self.assertEqual(len(list((Path(self.job["output_dir"]) / "native-godot").glob("*/admission.json"))), 0)

    def test_nonzero_process_rejected_even_if_report_passes(self):
        self.returncode = 2
        with self.assertRaisesRegex(ValueError, "engine error"):
            self.run_probe()

    def test_wrong_asset_identity_rejected(self):
        self.wrong_identity = True
        with self.assertRaisesRegex(ValueError, "native checks failed"):
            self.run_probe()

    def test_completed_receipt_binds_actual_runtime_and_log(self):
        receipt = self.run_probe()
        self.assertTrue(verify_godot_admission(self.job, receipt)["ok"])
        report = json.loads(Path(receipt["evidence_path"]).read_text())
        self.assertEqual(json.loads(Path(report["bindings"]["probe_config"]["path"]).read_text())["expected_dimensions_m"], [1, 3, 2])
        Path(report["log"]["path"]).write_text("ERROR: changed log")
        with self.assertRaisesRegex(ValueError, "Changed native admission evidence"):
            verify_godot_admission(self.job, receipt)

    def test_runtime_changed_after_probe_invalidates_receipt(self):
        receipt = self.run_probe()
        self.engine.write_bytes(b"changed executable")
        with self.assertRaisesRegex(ValueError, "runtime binding changed"):
            verify_godot_admission(self.job, receipt)

    def test_repeated_probe_uses_new_attempt_and_no_asset_copy(self):
        first = self.run_probe()
        second = self.run_probe()
        self.assertNotEqual(first["attempt"], second["attempt"])
        native = Path(self.job["output_dir"]) / "native-godot"
        self.assertEqual(list(native.rglob("*.glb")), [])
        self.assertEqual(list(native.rglob(".godot")), [])

    def test_native_output_cannot_follow_symlink(self):
        other = self.root / "other"
        other.mkdir()
        (Path(self.job["output_dir"]) / "native-godot").symlink_to(other, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "canonical"):
            self.run_probe()


if __name__ == "__main__":
    unittest.main()
