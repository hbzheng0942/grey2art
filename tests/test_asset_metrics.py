"""Stored topology measurements using tiny synthetic GLBs, never service calls."""
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
SKILL = Path(__file__).resolve().parents[1] / "skills/greybox-to-multistyle-art"
sys.path.insert(0, str(SKILL / "runtime"))
from greybox.asset_metrics import compare_assets, inspect_asset, write_report
from greybox.core import file_hash


def source(vertex_count=3, indices=None, component=5123, mode=4):
    blob = struct.pack("<" + "f" * vertex_count * 3, *([0.0] * vertex_count * 3))
    doc = {"asset": {"version": "2.0"}, "buffers": [{"byteLength": len(blob)}],
           "bufferViews": [{"buffer": 0, "byteLength": len(blob)}],
           "accessors": [{"bufferView": 0, "componentType": 5126, "count": vertex_count,
                          "type": "VEC3", "min": [0, 0, 0], "max": [0, 0, 0]}],
           "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "mode": mode}]}],
           "nodes": [{"mesh": 0}], "scenes": [{"nodes": [0]}], "scene": 0}
    if indices is not None:
        formats = {5121: "B", 5123: "H", 5125: "I"}
        data = struct.pack("<" + formats[component] * len(indices), *indices)
        doc["bufferViews"].append({"buffer": 0, "byteOffset": len(blob), "byteLength": len(data)})
        doc["accessors"].append({"bufferView": 1, "componentType": component,
                                 "count": len(indices), "type": "SCALAR"})
        doc["meshes"][0]["primitives"][0]["indices"] = 1
        blob += data
        doc["buffers"][0]["byteLength"] = len(blob)
    return doc, blob


def write_glb(path, doc, blob):
    encoded = json.dumps(doc).encode()
    encoded += b" " * (-len(encoded) % 4)
    blob += b"\0" * (-len(blob) % 4)
    path.write_bytes(struct.pack("<4sII", b"glTF", 2, 28 + len(encoded) + len(blob))
                     + struct.pack("<I4s", len(encoded), b"JSON") + encoded
                     + struct.pack("<I4s", len(blob), b"BIN\0") + blob)


class AssetMetricsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="greybox-metrics-")
        self.root = Path(self.temp.name)
        self.model = self.root / "model.glb"

    def tearDown(self):
        self.temp.cleanup()

    def measure(self, doc, blob):
        write_glb(self.model, doc, blob)
        return inspect_asset(self.model)

    def test_nonindexed_triangles_are_stored_counts_not_declared_bounds(self):
        doc, blob = source(vertex_count=6)
        doc["accessors"][0]["max"] = [10000, 20000, 30000]
        result = self.measure(doc, blob)
        self.assertEqual(result["geometry"]["unique_mesh_triangles"], 2)
        self.assertEqual(result["geometry"]["default_scene"]["triangles"], 2)
        self.assertEqual(result["source"]["sha256"], file_hash(self.model))
        self.assertEqual(result["source"]["bytes"], self.model.stat().st_size)
        self.assertEqual(result["source"]["filename"], "model.glb")
        text = json.dumps(result)
        self.assertNotIn(str(self.root), text)
        self.assertNotIn("world_bounds", text)
        self.assertNotIn("dimensions", text.replace("No world dimensions", ""))

    def test_all_unsigned_index_component_widths_decode_actual_values(self):
        for component in (5121, 5123, 5125):
            with self.subTest(component=component):
                result = self.measure(*source(vertex_count=4, indices=[2, 0, 3], component=component))
                self.assertEqual(result["geometry"]["unique_mesh_triangles"], 1)
                self.assertTrue(result["geometry"]["primitives"][0]["indexed"])

    def test_strip_and_fan_topology(self):
        for mode in (5, 6):
            for indices in (None, [0, 1, 2, 3, 4]):
                with self.subTest(mode=mode, indexed=indices is not None):
                    result = self.measure(*source(vertex_count=5, indices=indices, mode=mode))
                    self.assertEqual(result["geometry"]["unique_mesh_triangles"], 3)

    def test_points_and_lines_are_known_zero_triangles(self):
        result = self.measure(*source(vertex_count=4, mode=1))
        self.assertEqual(result["geometry"]["unique_mesh_triangles"], 0)
        self.assertEqual(result["geometry"]["default_scene"]["status"], "measured")

    def test_unique_meshes_and_scene_instances_have_different_counts(self):
        doc, blob = source(vertex_count=6, indices=[0, 1, 2])
        doc["meshes"].append({"primitives": [{"attributes": {"POSITION": 0}}]})
        doc["nodes"] = [{"mesh": 0, "children": [1]}, {"mesh": 0}]
        result = self.measure(doc, blob)
        self.assertEqual(result["counts"]["meshes"], 2)
        self.assertEqual(result["geometry"]["unique_mesh_triangles"], 3)
        self.assertEqual(result["geometry"]["default_scene"]["mesh_instances"], 2)
        self.assertEqual(result["geometry"]["default_scene"]["triangles"], 2)

    def test_absent_default_scene_is_unknown_not_first_scene_or_zero(self):
        doc, blob = source()
        del doc["scene"]
        result = self.measure(doc, blob)
        self.assertEqual(result["geometry"]["unique_mesh_triangles"], 1)
        self.assertEqual(result["geometry"]["default_scene"]["status"], "unknown")
        self.assertIsNone(result["geometry"]["default_scene"]["triangles"])

    def test_compression_and_gpu_instancing_are_rejected_with_fallback_present(self):
        for extension in ("KHR_draco_mesh_compression", "EXT_meshopt_compression", "EXT_mesh_gpu_instancing"):
            with self.subTest(extension=extension):
                doc, blob = source()
                doc["extensionsUsed"] = [extension]
                with self.assertRaisesRegex(ValueError, "unsupported"):
                    self.measure(doc, blob)
        doc, blob = source()
        doc["meshes"][0]["primitives"][0]["extensions"] = {"KHR_draco_mesh_compression": {}}
        with self.assertRaisesRegex(ValueError, "unsupported"):
            self.measure(doc, blob)

    def test_sparse_accessor_is_not_measured_as_dense_count(self):
        doc, blob = source()
        doc["accessors"][0]["sparse"] = {"count": 1}
        with self.assertRaisesRegex(ValueError, "Sparse"):
            self.measure(doc, blob)

    def test_declared_accessor_range_must_fit_actual_storage(self):
        doc, blob = source()
        doc["accessors"][0]["count"] = 6
        with self.assertRaisesRegex(ValueError, "bufferView"):
            self.measure(doc, blob)
        doc, blob = source()
        doc["buffers"][0]["byteLength"] += 12
        doc["bufferViews"][0]["byteLength"] += 12
        with self.assertRaisesRegex(ValueError, "BIN"):
            self.measure(doc, blob)

    def test_bad_stored_indices_cannot_pass_by_accessor_count(self):
        for indices in ([0, 1, 3], [0, 1, 65535]):
            with self.subTest(indices=indices):
                with self.assertRaisesRegex(ValueError, "POSITION range"):
                    self.measure(*source(indices=indices))

    def test_invalid_primitive_and_position_shapes_fail(self):
        with self.assertRaisesRegex(ValueError, "multiple of three"):
            self.measure(*source(vertex_count=4))
        doc, blob = source()
        doc["accessors"][0]["type"] = "SCALAR"
        with self.assertRaisesRegex(ValueError, "VEC3"):
            self.measure(doc, blob)
        doc, blob = source()
        doc["meshes"][0]["primitives"][0]["mode"] = 10
        with self.assertRaisesRegex(ValueError, "mode"):
            self.measure(doc, blob)

    def test_cycles_or_repeated_scene_nodes_are_not_infinite_or_double_counted(self):
        doc, blob = source()
        doc["nodes"][0]["children"] = [0]
        with self.assertRaisesRegex(ValueError, "cycle"):
            self.measure(doc, blob)
        doc, blob = source()
        doc["scenes"][0]["nodes"] = [0, 0]
        with self.assertRaisesRegex(ValueError, "repeated"):
            self.measure(doc, blob)

    def test_embedded_image_storage_bytes_are_not_texture_memory(self):
        doc, blob = source()
        doc["bufferViews"].append({"buffer": 0, "byteOffset": len(blob), "byteLength": 8})
        doc["images"] = [{"bufferView": 1, "mimeType": "image/png"},
                          {"bufferView": 1, "mimeType": "image/png"},
                          {"uri": "data:image/png;base64,QUJDRA=="}]
        doc["textures"] = [{"source": 0}, {"source": 1}]
        doc["materials"] = [{}]
        blob += b"syntheti"
        doc["buffers"][0]["byteLength"] = len(blob)
        result = self.measure(doc, blob)
        self.assertEqual(result["embedded_images"]["payload_bytes"], 12)
        self.assertEqual(result["embedded_images"]["buffer_view_payload_bytes"], 8)
        self.assertEqual(result["counts"]["textures"], 2)
        self.assertEqual(result["counts"]["materials"], 1)
        self.assertEqual(result["verification"]["runtime_performance"], "unverified")

    def test_external_resources_and_invalid_data_uri_are_rejected(self):
        for changes in ({"buffers": [{"uri": "secret.bin", "byteLength": 36}]},
                        {"images": [{"uri": "private.png"}]},
                        {"images": [{"uri": "data:image/png;base64,A==="}]}):
            doc, blob = source()
            doc.update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.measure(doc, blob)

    def test_comparison_reports_deltas_without_qualification(self):
        first, second = self.root / "before.glb", self.root / "after.glb"
        write_glb(first, *source(vertex_count=6))
        write_glb(second, *source())
        result = compare_assets(first, second)
        self.assertEqual(result["delta_after_minus_before"]["unique_mesh_triangles"], -1)
        self.assertEqual(result["delta_after_minus_before"]["default_scene_triangles"], -1)
        self.assertTrue(all(value == "unverified" for value in result["verification"].values()))
        self.assertNotIn(str(self.root), json.dumps(result))

    def test_unknown_scene_delta_remains_unknown(self):
        first, second = self.root / "before.glb", self.root / "after.glb"
        doc, blob = source()
        del doc["scene"]
        write_glb(first, doc, blob)
        write_glb(second, *source())
        self.assertIsNone(compare_assets(first, second)["delta_after_minus_before"]["default_scene_triangles"])

    def test_write_report_protects_source_existing_report_and_symlink(self):
        result = self.measure(*source())
        original = self.model.read_bytes()
        with self.assertRaises(FileExistsError):
            write_report(result, self.model)
        report = self.root / "metrics.json"
        write_report(result, report)
        old_report = report.read_bytes()
        with self.assertRaises(FileExistsError):
            write_report({"changed": True}, report)
        link = self.root / "alias.json"
        try:
            link.symlink_to(self.model)
        except OSError:
            pass
        else:
            with self.assertRaises(FileExistsError):
                write_report(result, link)
        self.assertEqual(self.model.read_bytes(), original)
        self.assertEqual(report.read_bytes(), old_report)

    def test_changed_source_during_measurement_fails(self):
        write_glb(self.model, *source())
        with patch("greybox.asset_metrics.file_hash", return_value="0" * 64):
            with self.assertRaisesRegex(ValueError, "Source changed"):
                inspect_asset(self.model)

    def test_public_cli_outputs_shareable_report_and_protects_old_output(self):
        write_glb(self.model, *source())
        output = self.root / "metrics.json"
        command = [sys.executable, "-B", str(SKILL / "scripts/asset_metrics.py"), "inspect",
                   "--input", str(self.model), "--output", str(output)]
        run = subprocess.run(command, capture_output=True, text=True, timeout=15)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(json.loads(run.stdout)["geometry"]["unique_mesh_triangles"], 1)
        self.assertNotIn(str(self.root), run.stdout)
        again = subprocess.run(command, capture_output=True, text=True, timeout=15)
        self.assertEqual(again.returncode, 2)
        self.assertNotIn(str(self.root), again.stdout)


if __name__ == "__main__":
    unittest.main()
