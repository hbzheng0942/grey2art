"""Portable production contracts plus optional real background Blender execution."""
from copy import deepcopy
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import zlib

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1] / "skills/greybox-to-multistyle-art"
sys.path.insert(0, str(ROOT / "runtime"))
from greybox import blender_jobs, core


class BlenderProductionV04(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="blender-production-v04-tests-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.job = {"schema": 1, "kind": "blender-production-job", "job_id": "test-bake",
                    "fixture": "diagnostic_cube", "operation": "bake", "output_dir": str(self.root / "output"),
                    "bake": {"resolution": 32, "channels": ["base_color", "normal", "ao"],
                             "uv": {"mode": "smart_project", "name": "BakeUV"}, "normal_convention": "opengl", "samples": 1}}

    def scatter(self):
        job = {key: value for key, value in self.job.items() if key != "bake"}
        job.update(operation="scatter", scatter={"count": 10, "seed": 17, "bounds_xy": [-3, -3, 3, 3],
                                                  "exclude_rects": [[-1, -1, 1, 1]], "scale": [.8, 1.2]})
        return job

    def render(self):
        job = {key: value for key, value in self.job.items() if key != "bake"}
        job.update(operation="render", render={"resolution": [32, 32], "frames": [1, 2], "samples": 1,
                    "view_transform": "Standard", "camera": {"position": [2, -3, 2], "target": [0, 0, .5],
                    "projection": "orthographic", "ortho_scale": 2}, "lights": [{"type": "AREA", "position": [2, -2, 4], "energy": 300}],
                    "environment": {"color": [.05, .05, .05], "strength": .5}, "turntable_degrees_per_frame": 20})
        return job

    def test_offline_validation_is_nonmutating_and_requires_explicit_uv(self):
        self.assertTrue(blender_jobs.validate(self.job)["ok"])
        self.assertFalse(Path(self.job["output_dir"]).exists())
        self.job["bake"].pop("uv")
        with self.assertRaisesRegex(ValueError, "UV"):
            blender_jobs.validate(self.job)

    def test_original_assets_and_existing_outputs_are_never_overwritten(self):
        path = Path(self.job["output_dir"]); path.mkdir(); unique = path / "unique.glb"; unique.write_bytes(b"keep")
        with self.assertRaisesRegex(ValueError, "prior/unrelated"):
            blender_jobs.validate(self.job)
        self.assertEqual(unique.read_bytes(), b"keep")

    def test_bake_normal_convention_and_channels_are_explicit(self):
        for value in (None, "auto", "dx"):
            self.job["bake"]["normal_convention"] = value
            with self.assertRaisesRegex(ValueError, "normals"):
                blender_jobs.validate(self.job)
        self.job["bake"]["normal_convention"] = "directx"
        self.assertTrue(blender_jobs.validate(self.job)["ok"])
        self.job["bake"]["channels"] = ["base_color", "base_color"]
        with self.assertRaisesRegex(ValueError, "channels"):
            blender_jobs.validate(self.job)

    def test_unimplemented_or_misspelled_options_fail_explicitly(self):
        self.job["bake"]["resoluton"] = 64
        with self.assertRaisesRegex(ValueError, "silently"):
            blender_jobs.validate(self.job)
        job = self.scatter(); job["scatter"]["bounds_xy"] = [1, 1, 0, 0]
        with self.assertRaisesRegex(ValueError, "positive area"):
            blender_jobs.validate(job)

    def test_numeric_bounds_reject_bool_and_nan(self):
        for value in (True, 0, 8192, float("nan")):
            self.job["bake"]["resolution"] = value
            with self.assertRaises(ValueError):
                blender_jobs.validate(self.job)

    def test_scatter_preserves_deterministic_seed_and_positive_uniform_scale(self):
        job = self.scatter(); self.assertTrue(blender_jobs.validate(job)["ok"])
        job["scatter"]["seed"] = -1
        with self.assertRaisesRegex(ValueError, "seed"):
            blender_jobs.validate(job)
        job["scatter"]["seed"] = 0; job["scatter"]["scale"] = [2, 1]
        with self.assertRaisesRegex(ValueError, "uniform scale"):
            blender_jobs.validate(job)

    def test_render_requires_real_camera_lights_frames_and_color_management(self):
        job = self.render(); self.assertTrue(blender_jobs.validate(job)["ok"])
        job["render"]["camera"]["position"] = job["render"]["camera"]["target"]
        with self.assertRaisesRegex(ValueError, "differ"):
            blender_jobs.validate(job)
        job = self.render(); job["render"]["frames"] = [1, 1]
        with self.assertRaisesRegex(ValueError, "distinct"):
            blender_jobs.validate(job)
        job = self.render(); job["render"]["lights"] = []
        with self.assertRaisesRegex(ValueError, "lights"):
            blender_jobs.validate(job)

    def test_glb_source_hash_and_embedded_dependencies_are_checked(self):
        source = self.root / "source.glb"
        blob = json.dumps({"asset": {"version": "2.0"}, "images": [{"uri": "outside.png"}]}).encode()
        blob += b" " * (-len(blob) % 4)
        source.write_bytes(struct.pack("<4sII", b"glTF", 2, 20 + len(blob)) + struct.pack("<I4s", len(blob), b"JSON") + blob)
        self.job.pop("fixture"); self.job["input"] = {"path": str(source), "sha256": core.file_hash(source)}
        with self.assertRaisesRegex(ValueError, "external dependencies"):
            blender_jobs.validate(self.job)
        self.job["input"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "hash changed"):
            blender_jobs.validate(self.job)

    def test_changed_worker_or_output_cannot_reuse_old_production_report(self):
        output = Path(self.job["output_dir"]); output.mkdir()
        for name in ("recipe.blend", "asset.glb", "textures/test_base_color.png", "textures/test_normal.png", "textures/test_ao.png"):
            path = output / name; path.parent.mkdir(exist_ok=True); path.write_bytes(name.encode())
        report = {"status": "complete", "job_sha256": core.digest(self.job), "worker_sha256": core.file_hash(blender_jobs.WORKER), "input": None,
                  "outputs": [{"path": str(p.relative_to(output)), "sha256": core.file_hash(p)} for p in output.rglob("*") if p.is_file()]}
        core.write(output / "report.json", report)
        self.assertTrue(blender_jobs.verify(self.job)["ok"])
        report["worker_sha256"] = "0" * 64; core.write(output / "report.json", report)
        with self.assertRaisesRegex(ValueError, "differs"):
            blender_jobs.verify(self.job)
        report["worker_sha256"] = core.file_hash(blender_jobs.WORKER); core.write(output / "report.json", report)
        (output / "asset.glb").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "changed"):
            blender_jobs.verify(self.job)

    @unittest.skipUnless(os.environ.get("GREYBOX_BLENDER_TEST_BIN"), "Set GREYBOX_BLENDER_TEST_BIN for real isolated bake/scatter/render")
    def test_real_background_bake_scatter_render_and_determinism(self):
        executable = os.environ["GREYBOX_BLENDER_TEST_BIN"]
        for job in (self.job, self.scatter(), self.render()):
            job["output_dir"] = str(self.root / job["operation"])
            result = blender_jobs.execute(job, executable)
            self.assertTrue(result["invocation_verified"])
            self.assertEqual(result["native_admission"], "pending")
        first = core.read(self.root / "scatter/instances.json")
        second_job = self.scatter(); second_job["output_dir"] = str(self.root / "scatter-second")
        blender_jobs.execute(second_job, executable)
        second = core.read(self.root / "scatter-second/instances.json")
        self.assertEqual(first["instances"], second["instances"])
        self.assertNotEqual(core.file_hash(self.root / "render/frames/frame-000001.png"), core.file_hash(self.root / "render/frames/frame-000002.png"))
        mask = self.root / "density.png"
        def chunk(kind, payload):
            return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xffffffff)
        rows = b"".join(b"\0" + b"\xff\xff\xff" * 4 + b"\0\0\0" * 4 for _ in range(8))
        mask.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 8, 8, 8, 2, 0, 0, 0))
                         + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))
        masked = self.scatter(); masked.pop("fixture")
        prototype = self.root / "scatter/prototype.glb"
        masked["input"] = {"path": str(prototype), "sha256": core.file_hash(prototype)}
        masked["scatter"]["density_mask"] = {"path": str(mask), "sha256": core.file_hash(mask)}
        masked["output_dir"] = str(self.root / "masked")
        blender_jobs.execute(masked, executable)
        instances = core.read(self.root / "masked/instances.json")
        self.assertTrue(all(row["translation_m"][0] < 0 for row in instances["instances"]))
        self.assertFalse((self.root / "masked/prototype.glb").exists())
        directx = deepcopy(self.job); directx["output_dir"] = str(self.root / "directx")
        directx["bake"]["normal_convention"] = "directx"
        blender_jobs.execute(directx, executable)
        self.assertTrue((self.root / "directx/textures/mesh-000_normal_gltf.png").is_file())


if __name__ == "__main__":
    unittest.main()
