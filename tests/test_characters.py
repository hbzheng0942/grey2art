"""Offline evidence integrity tests with tiny synthetic files, never provider calls."""
from copy import deepcopy
import io
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1] / "skills/greybox-to-multistyle-art"
sys.path.insert(0, str(ROOT / "runtime"))
from greybox.characters import CHECKS, VIEWS, inspect_glb, make_template, validate_preflight, write_inspection
from greybox.core import file_hash


def model(path, rig=False, external=False, bad_bounds=False):
    blob = struct.pack("<9f", 0, 0, 0, 1, 0, 0, 0, 1, 0)
    doc = {"asset": {"version": "2.0", "generator": "synthetic-test"},
           "buffers": [{"byteLength": len(blob)}], "bufferViews": [{"buffer": 0, "byteLength": len(blob)}],
           "accessors": [{"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3",
                          "min": [0, 0, 0], "max": [float("nan") if bad_bounds else 1, 1, 0]}],
           "nodes": [{"mesh": 0}], "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}]}
    if rig:
        doc["nodes"].extend([{"name": "joint"}])
        doc["nodes"][0]["skin"] = 0
        doc["skins"] = [{"joints": [1]}]
        for key, component, data in (("JOINTS_0", 5121, bytes(12)), ("WEIGHTS_0", 5126, struct.pack("<12f", *([1, 0, 0, 0] * 3)))):
            doc["bufferViews"].append({"buffer": 0, "byteOffset": len(blob), "byteLength": len(data)})
            doc["accessors"].append({"bufferView": len(doc["bufferViews"]) - 1, "componentType": component, "type": "VEC4", "count": 3})
            doc["meshes"][0]["primitives"][0]["attributes"][key] = len(doc["accessors"]) - 1
            blob += data
        doc["buffers"][0]["byteLength"] = len(blob)
    if external:
        doc["images"] = [{"uri": "texture.png"}]
    encoded = json.dumps(doc).encode()
    encoded += b" " * (-len(encoded) % 4)
    blob += b"\x00" * (-len(blob) % 4)
    path.write_bytes(struct.pack("<4sII", b"glTF", 2, 28 + len(encoded) + len(blob))
                     + struct.pack("<I4s", len(encoded), b"JSON") + encoded
                     + struct.pack("<I4s", len(blob), b"BIN\x00") + blob)
    return doc


def png(path, color):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(bytes([0, color, 0, 0]))) + chunk(b"IEND", b""))


class CharacterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "model.glb"
        self.report = self.root / "inspection.json"

    def tearDown(self):
        self.temp.cleanup()

    def reviewed(self, rig=False, external=False):
        model(self.source, rig=rig, external=external)
        write_inspection(self.source, self.report)
        receipt = make_template(self.report)
        receipt.update(category="humanoid", use="rig", reviewer="test-actor")
        receipt["pose"] = {"label": "A-like", "status": "pass", "observation": "Observed arms lowered and separated."}
        for i, record in enumerate(receipt["views"]):
            path = self.root / (record["view"] + ".png")
            png(path, i * 40)
            record.update(path=str(path), sha256=file_hash(path))
        for check in receipt["checks"]:
            check.update(status="pass", observation="Synthetic review fixture only.", views=["front", "side"])
        return receipt

    def test_structural_report_cannot_claim_pose_or_world_dimensions(self):
        model(self.source)
        result = inspect_glb(self.source)
        self.assertEqual(result["source"]["sha256"], file_hash(self.source))
        self.assertEqual(result["counts"]["position_vertices"], 3)
        self.assertEqual(result["counts"]["skins"], 0)
        self.assertTrue(result["node_transforms"][0]["default_identity"])
        self.assertEqual(result["positions"][0]["declared_local_bounds"]["max"], [1, 1, 0])
        self.assertNotIn("pose", result)
        self.assertNotIn("world_bounds", result)

    def test_truncated_container_nonfinite_bounds_and_fake_geometry_fail(self):
        self.source.write_bytes(b"not a glb")
        with self.assertRaises(ValueError):
            inspect_glb(self.source)
        model(self.source, bad_bounds=True)
        with self.assertRaisesRegex(ValueError, "finite"):
            inspect_glb(self.source)
        model(self.source)
        self.source.write_bytes(self.source.read_bytes()[:-4])
        with self.assertRaisesRegex(ValueError, "container"):
            inspect_glb(self.source)

    def test_template_never_manufactures_visual_review(self):
        model(self.source)
        write_inspection(self.source, self.report)
        receipt = make_template(self.report)
        self.assertEqual(receipt["category"], "unknown")
        self.assertTrue(all(c["status"] == "unclear" for c in receipt["checks"]))
        self.assertFalse(validate_preflight(receipt, provider="lux3d")["ok"])

    def test_rig_requires_fresh_source_report_and_all_views(self):
        receipt = self.reviewed()
        self.assertTrue(validate_preflight(receipt, provider="lux3d")["ok"])
        for section in ("source", "inspection"):
            stale = deepcopy(receipt)
            stale[section]["sha256"] = "0" * 64
            self.assertFalse(validate_preflight(stale, provider="lux3d")["ok"])
        stale = deepcopy(receipt)
        stale["views"][0]["sha256"] = "0" * 64
        self.assertFalse(validate_preflight(stale, provider="lux3d")["ok"])
        receipt["views"].pop()
        self.assertFalse(validate_preflight(receipt, provider="lux3d")["ok"])

    def test_rehashed_forged_inspection_is_not_accepted(self):
        receipt = self.reviewed()
        report = json.loads(self.report.read_text())
        report["counts"]["skins"] = 20
        self.report.write_text(json.dumps(report))
        receipt["inspection"]["sha256"] = file_hash(self.report)
        result = validate_preflight(receipt, provider="lux3d")
        self.assertFalse(result["ok"])
        self.assertIn("contents differ", result["errors"][0])

    def test_source_override_must_bind_exact_bytes_but_can_relocate(self):
        receipt = self.reviewed()
        relocated = self.root / "relocated.glb"
        relocated.write_bytes(self.source.read_bytes())
        self.assertTrue(validate_preflight(receipt, relocated, "lux3d")["ok"])
        model(relocated, rig=True)
        self.assertFalse(validate_preflight(receipt, relocated, "lux3d")["ok"])

    def test_relative_receipt_paths_resolve_beside_receipt(self):
        receipt = self.reviewed()
        for record in [receipt["source"], receipt["inspection"], *receipt["views"]]:
            record["path"] = Path(record["path"]).name
        path = self.root / "preflight.json"
        path.write_text(json.dumps(receipt))
        self.assertTrue(validate_preflight(path, provider="meshy")["ok"])

    def test_nonhuman_rig_is_not_admitted_to_lux_or_meshy(self):
        receipt = self.reviewed()
        receipt["category"] = "quadruped"
        for provider in ("lux3d", "lux", "meshy"):
            self.assertFalse(validate_preflight(receipt, provider=provider)["ok"])
        self.assertTrue(validate_preflight(receipt, provider="tripo")["ok"])
        self.assertFalse(validate_preflight(receipt)["ok"])

    def test_failed_unclear_or_empty_reviews_cannot_pass_rig(self):
        receipt = self.reviewed()
        for status in ("fail", "unclear"):
            edited = deepcopy(receipt)
            edited["checks"][0]["status"] = status
            self.assertFalse(validate_preflight(edited, provider="lux3d")["ok"])
        receipt["pose"]["observation"] = ""
        self.assertFalse(validate_preflight(receipt, provider="lux3d")["ok"])

    def test_duplicate_images_and_text_disguised_as_view_fail(self):
        receipt = self.reviewed()
        receipt["views"][1].update(path=receipt["views"][0]["path"], sha256=receipt["views"][0]["sha256"])
        self.assertFalse(validate_preflight(receipt, provider="lux3d")["ok"])
        record = receipt["views"][0]
        Path(record["path"]).write_text("This is not an image")
        record["sha256"] = file_hash(record["path"])
        self.assertFalse(validate_preflight(receipt, provider="lux3d")["ok"])

    def test_external_resources_cannot_sneak_past_source_hash(self):
        receipt = self.reviewed(external=True)
        result = validate_preflight(receipt, provider="lux3d")
        self.assertFalse(result["ok"])
        self.assertIn("External", result["errors"][0])

    def test_static_and_existing_rig_do_not_require_new_rig_or_pose_pass(self):
        receipt = self.reviewed(rig=True)
        receipt["pose"].update(status="unclear", label="not-needed", observation="Using existing rig, no new rest-pose requirement.")
        receipt["checks"][1]["status"] = "unclear"
        for use in ("static", "reuse-rig"):
            receipt["use"] = use
            self.assertTrue(validate_preflight(receipt)["ok"])

    def test_claiming_reuse_cannot_invent_a_skin(self):
        receipt = self.reviewed()
        receipt["use"] = "reuse-rig"
        self.assertFalse(validate_preflight(receipt)["ok"])

    def test_inspection_preserves_source_and_refuses_existing_output(self):
        model(self.source)
        before = self.source.read_bytes()
        write_inspection(self.source, self.report)
        with self.assertRaises(FileExistsError):
            write_inspection(self.source, self.report)
        with self.assertRaises(FileExistsError):
            write_inspection(self.source, self.source)
        self.assertEqual(self.source.read_bytes(), before)

    def test_cli_is_standalone_offline_and_help_exits_normally(self):
        script = ROOT / "scripts/character_check.py"
        model(self.source)
        for args in (("--help",), ("inspect", "--file", str(self.source), "--output", str(self.report))):
            proc = subprocess.run([sys.executable, str(script), *args], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["source"]["sha256"], file_hash(self.source))
        proc = subprocess.run([sys.executable, str(script), "template", "--inspection", str(self.report),
                               "--output", str(self.root / "receipt.json")], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        proc = subprocess.run([sys.executable, str(script), "validate", "--receipt", str(self.root / "receipt.json"),
                               "--provider", "lux3d"], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 1)
        self.assertFalse(json.loads(proc.stdout)["ok"])


if __name__ == "__main__":
    unittest.main()
