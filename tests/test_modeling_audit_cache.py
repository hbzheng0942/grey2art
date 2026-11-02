"""Content-bound pixel measurements may be reused; approval checks may not."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"skills/greybox-to-multistyle-art/runtime"))
from greybox import core, modeling_refs
from modeling_ref_fixtures import png_bytes, write_reference_package


class ModelingAuditCache(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.images = [png_bytes(width=256, height=256, color=(40+i, 120, 180)) for i in range(12)]

    def setUp(self):
        modeling_refs._audit.cache_clear()
        self.addCleanup(modeling_refs._audit.cache_clear)

    def test_eleven_and_twelve_masters_over_twenty_four_scans_decode_once_each(self):
        for count in (11, 12):
            with self.subTest(masters=count):
                modeling_refs._audit.cache_clear()
                with mock.patch.object(modeling_refs, "_audit_pixels", wraps=modeling_refs._audit_pixels) as compute:
                    for _ in range(24):
                        for raw in self.images[:count]:
                            stats = modeling_refs._audit(raw)
                            self.assertEqual(stats["nonwhite_bbox"], [64, 64, 191, 191])
                    self.assertEqual(compute.call_count, count)
                info = modeling_refs._audit.cache_info()
                self.assertEqual((info.hits, info.misses, info.currsize), (23*count, count, count))

    def test_changed_content_at_same_path_only_reaudits_affected_image(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = [Path(folder)/f"master-{i}.png" for i in range(11)]
            for path, raw in zip(paths, self.images):
                path.write_bytes(raw)
            with mock.patch.object(modeling_refs, "_audit_pixels", wraps=modeling_refs._audit_pixels) as compute:
                before = [modeling_refs.audit_image(path) for path in paths]
                paths[4].write_bytes(self.images[11])
                after = [modeling_refs.audit_image(path) for path in paths]
                self.assertEqual(compute.call_count, 12)
                self.assertEqual(compute.call_args.args, (self.images[11],))
            for i, (old, new) in enumerate(zip(before, after)):
                self.assertEqual(old["path"], new["path"])
                self.assertEqual(old["sha256"] == new["sha256"], i != 4)
        self.assertEqual(modeling_refs._audit.cache_info().hits, 10)

    def test_identical_content_reuses_measurements_but_keeps_current_path(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = [Path(folder)/name for name in ("first.png", "second.png")]
            for path in paths:
                path.write_bytes(self.images[0])
            first, second = (modeling_refs.audit_image(path) for path in paths)
        self.assertNotEqual(first["path"], second["path"])
        self.assertEqual(first["sha256"], second["sha256"])
        self.assertEqual(modeling_refs._audit.cache_info().hits, 1)

    def test_audit_rule_version_change_recomputes_same_bytes(self):
        with mock.patch.object(modeling_refs, "_audit_pixels", wraps=modeling_refs._audit_pixels) as compute:
            modeling_refs._audit(self.images[0])
            with mock.patch.object(modeling_refs, "PIXEL_AUDIT_VERSION", "changed-rules"):
                modeling_refs._audit(self.images[0])
                modeling_refs._audit(self.images[0])
            self.assertEqual(compute.call_count, 2)
        self.assertEqual(modeling_refs._audit.cache_info().hits, 1)

    def test_reduced_safety_limits_cannot_reuse_earlier_result(self):
        modeling_refs._audit(self.images[0])
        with mock.patch.object(modeling_refs, "MAX_PIXELS", 255*255):
            with self.assertRaisesRegex(ValueError, "safe pixel limit"):
                modeling_refs._audit(self.images[0])
        with mock.patch.object(modeling_refs, "MAX_IMAGE_BYTES", len(self.images[0])-1):
            with self.assertRaisesRegex(ValueError, "exceeds"):
                modeling_refs._audit(self.images[0])

    def test_returned_dict_and_nested_list_mutation_cannot_poison_cache(self):
        first = modeling_refs._audit(self.images[0])
        first["width"] = 1
        first["nonwhite_bbox"][0] = -999
        first["semantic_checks"] = "approved"
        second = modeling_refs._audit(self.images[0])
        self.assertEqual(second["width"], 256)
        self.assertEqual(second["nonwhite_bbox"], [64, 64, 191, 191])
        self.assertIn("visual review required", second["semantic_checks"])

    def test_failed_audit_is_retried_and_not_stored(self):
        corrupt = b"\x89PNG\r\n\x1a\ncorrupt"
        with mock.patch.object(modeling_refs, "_audit_pixels", wraps=modeling_refs._audit_pixels) as compute:
            for _ in range(2):
                with self.assertRaisesRegex(ValueError, "PNG"):
                    modeling_refs._audit(corrupt)
            self.assertEqual(compute.call_count, 2)
        info = modeling_refs._audit.cache_info()
        self.assertEqual((info.hits, info.misses, info.currsize), (0, 2, 0))

    def test_mutable_input_cannot_change_between_digest_and_decode(self):
        with self.assertRaisesRegex(ValueError, "immutable image bytes"):
            modeling_refs._audit(bytearray(self.images[0]))
        self.assertEqual(modeling_refs._audit.cache_info().currsize, 0)

    def test_default_bound_retains_only_digest_keys_and_immutable_numbers(self):
        measured = modeling_refs._audit_pixels(self.images[0])
        limit = modeling_refs.AUDIT_CACHE_MAXSIZE
        self.assertGreaterEqual(limit, 11)
        # Capacity behavior does not require decoding 257 equivalent fixtures.
        with mock.patch.object(modeling_refs, "_audit_pixels", return_value=measured) as compute:
            for i in range(limit+1):
                modeling_refs._audit(f"unique-content-{i}".encode())
            self.assertEqual(modeling_refs._audit.cache_info().currsize, limit)
            modeling_refs._audit(b"unique-content-0")
            self.assertEqual(compute.call_count, limit+2)
        for key, value in modeling_refs._audit_cache.items():
            self.assertEqual(len(key[-1]), 32)
            self.assertIsInstance(value, tuple)
            self.assertTrue(all(isinstance(item, (int, float)) for item in value[:-1]))
            self.assertIsInstance(value.nonwhite_bbox, tuple)
        modeling_refs._audit.cache_clear()
        self.assertEqual(modeling_refs._audit.cache_info(), (0, 0, limit, 0))

    def test_recent_hit_preserved_when_oldest_entry_is_evicted(self):
        with mock.patch.object(modeling_refs, "AUDIT_CACHE_MAXSIZE", 3):
            with mock.patch.object(modeling_refs, "_audit_pixels", wraps=modeling_refs._audit_pixels) as compute:
                for index in (0, 1, 2, 0, 3, 0, 1):
                    modeling_refs._audit(self.images[index])
                self.assertEqual(compute.call_count, 5)
            info = modeling_refs._audit.cache_info()
            self.assertEqual((info.hits, info.misses, info.currsize), (2, 5, 3))

    def test_warm_pixel_cache_does_not_cache_visual_review_pass(self):
        with tempfile.TemporaryDirectory() as folder:
            project = Path(folder)
            ref = write_reference_package(project, ["gate"])
            package = core.read(project/ref["path"])
            self.assertTrue(modeling_refs.validate_package(package, project)["ok"])
            package["assets"][0]["review"]["criteria"]["no_baked_shadows"] = False
            with self.assertRaisesRegex(ValueError, "checks"):
                modeling_refs.validate_package(package, project)


if __name__ == "__main__":
    unittest.main()
