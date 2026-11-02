"""Production image-route controls. Synthetic files only; no paid/network calls."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1] / "skills/greybox-to-multistyle-art"
sys.path.insert(0, str(ROOT / "runtime"))
from greybox import core, image_policy, supplier_jobs
from greybox.providers import tripo
from modeling_ref_fixtures import write_reference_package


class ImageRoutesR32(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="image-policy-offline-")
        self.project = Path(self.temp.name)
        self.operation = self.make()

    def tearDown(self):
        self.temp.cleanup()

    def make(self, provider="lux3d", mode="single"):
        reference = write_reference_package(self.project, ["prop"], mode=mode)
        package = core.read(core.resolve_input(reference["path"], self.project))
        inputs = [v["image"] for v in package["assets"][0]["views"]]
        parameters = {"version": "G1", "faceCount": 30000}
        if provider not in {"rodin", "hitem3d"}:
            parameters["image_path" if mode == "single" else "image_paths"] = 0 if mode == "single" else list(range(len(inputs)))
        return {"id": "prop-model", "asset_id": "prop", "provider": provider,
                "operation": "image_to_3d" if mode == "single" or provider in {"lux3d", "rodin"} else "multiview_to_3d",
                "model_version": "G1", "parameters": parameters, "inputs": inputs,
                "modeling_references": reference, "pricing": {"kind": "rate_card_estimate"}}

    def check(self, operation=None):
        return image_policy.validate_operation(operation or self.operation, self.project)

    def test_single_image_matches_reviewed_upload_bytes(self):
        checked = self.check()
        self.assertEqual(checked["mode"], "single")
        self.assertEqual(checked["images"][0]["sha256"], self.operation["inputs"][0]["sha256"])

    def test_lux_multiview_uses_actual_image_operation(self):
        checked = self.check(self.make(mode="multiview"))
        self.assertEqual(checked["mode"], "multiview")
        self.assertEqual(len(checked["images"]), 2)

    def test_text_routes_rejected_even_if_image_is_attached(self):
        for name in image_policy.TEXT_OPERATIONS:
            with self.subTest(name=name):
                operation = deepcopy(self.operation); operation["operation"] = name
                with self.assertRaisesRegex(core.WorkflowError, "text-to-3D"):
                    self.check(operation)

    def test_custom_operation_name_cannot_hide_prompt_generation(self):
        for name in ("generate_from_prompt", "custom_mesh", "text2model"):
            with self.subTest(name=name):
                operation = {"provider": "custom-provider", "operation": name, "parameters": {"prompt": "new mesh"}}
                with self.assertRaisesRegex(core.WorkflowError, "Unknown production operation"):
                    self.check(operation)

    def test_generic_raw_supplier_capability_still_reports_text(self):
        result = tripo.dispatch("capabilities", {})
        self.assertIn("text_to_3d", result["operations"])
        self.assertIn("multiview_to_3d", result["operations"])

    def test_remote_tokens_and_text_fields_cannot_bypass_local_inputs(self):
        for key, value in (("img", "https://example.invalid/image.png"), ("input", "upload-token"),
                           ("input_from", "previous-task"), ("prompt", "different design"),
                           ("texture_prompt", "different material")):
            with self.subTest(key=key):
                operation = deepcopy(self.operation); operation["parameters"][key] = value
                with self.assertRaises(core.WorkflowError): self.check(operation)

    def test_unbound_single_image_path_is_rejected(self):
        self.operation["parameters"]["image_path"] = "other.png"
        with self.assertRaisesRegex(core.WorkflowError, "exactly one approved"):
            self.check()

    def test_missing_image_cannot_be_called_image_to_3d(self):
        self.operation["inputs"] = []
        with self.assertRaisesRegex(core.WorkflowError, "local image inputs"):
            self.check()

    def test_changed_source_bytes_invalidate_submission(self):
        core.resolve_input(self.operation["inputs"][0]["path"], self.project).write_bytes(b"changed")
        with self.assertRaisesRegex(core.WorkflowError, "changed"):
            self.check()

    def test_distinct_view_order_is_bound(self):
        operation = self.make(mode="multiview")
        operation["parameters"]["image_paths"] = [1, 0]
        with self.assertRaisesRegex(core.WorkflowError, "order differ"):
            self.check(operation)

    def test_duplicate_views_are_not_multiview(self):
        operation = self.make(mode="multiview")
        operation["parameters"]["image_paths"] = [0, 0]
        with self.assertRaisesRegex(core.WorkflowError, "distinct views"):
            self.check(operation)

    def test_reviewed_multiview_cannot_fall_back_to_single(self):
        operation = self.make(mode="multiview")
        operation["parameters"].pop("image_paths")
        operation["parameters"]["image_path"] = 0
        with self.assertRaises(core.WorkflowError): self.check(operation)

    def test_tripo_views_are_named_and_match_capability(self):
        operation = self.make(provider="tripo", mode="multiview")
        operation["parameters"]["image_paths"] = [{"front": 0}, {"back": 1}]
        self.assertEqual(self.check(operation)["mode"], "multiview")
        operation["parameters"]["image_paths"] = [{"front": 0}, {"top": 1}]
        with self.assertRaisesRegex(core.WorkflowError, "named views"):
            self.check(operation)

    def test_multiview_vendor_labels_cannot_misidentify_images(self):
        for provider in ("tripo", "hitem3d", "rodin"):
            with self.subTest(provider=provider):
                operation = self.make(provider=provider, mode="multiview")
                if provider == "tripo":
                    operation["parameters"]["image_paths"] = [{"front": 0}, {"right": 1}]
                elif provider == "hitem3d":
                    operation["parameters"]["multi_images_bit"] = "1001"
                else:
                    operation["parameters"].update(tier="Gen-2.5-Medium", image_label=["F", "R"])
                with self.assertRaisesRegex(core.WorkflowError, "orientations"):
                    self.check(operation)

    def test_rodin_legacy_multiview_uses_concat_and_no_unsupported_labels(self):
        operation = self.make(provider="rodin", mode="multiview")
        operation["parameters"]["tier"] = "Regular"
        with self.assertRaisesRegex(core.WorkflowError, "concat"):
            self.check(operation)
        operation["parameters"]["condition_mode"] = "concat"
        self.assertTrue(self.check(operation)["ok"])

    def test_uploaded_source_drift_blocks_generation(self):
        request = {"parameters": self.operation["parameters"], "inputs": supplier_jobs._inputs(self.operation, self.project),
                   "output_dir": str(self.project / "art/experiments/r/outputs/prop")}
        def change_source(path, region):
            Path(path).write_bytes(b"changed during upload")
            return {"url": "https://synthetic.invalid/source.png"}
        with patch("greybox.lux.upload", side_effect=change_source), self.assertRaisesRegex(core.WorkflowError, "during upload"):
            supplier_jobs._lux_parameters(self.operation, request, self.project, "cn")

    def test_lux_cannot_invent_a_multiview_endpoint(self):
        operation = self.make(mode="multiview")
        operation["operation"] = "multiview_to_3d"
        with self.assertRaisesRegex(core.WorkflowError, "Lux uses image_to_3d"):
            self.check(operation)

    def test_meshy_image_enhancement_is_explicit_and_not_silent(self):
        operation = self.make(provider="meshy")
        operation["model_version"] = "meshy-7.1"
        with self.assertRaisesRegex(core.WorkflowError, "image_enhancement"):
            self.check(operation)
        operation["parameters"]["image_enhancement"] = False
        self.assertTrue(self.check(operation)["ok"])

    def test_rig_remesh_and_existing_assets_are_not_forced_through_generation(self):
        for name in ("rig", "retarget", "rig_check", "remesh", "material_transfer", "texture", "export"):
            self.assertEqual(image_policy.validate_operation({"operation": name}, self.project)["images"], [])
        plan = core.read(ROOT / "fixtures/godot-free/plan.json")
        self.assertEqual(core.validate_plan(plan)["generationTasks"], 0)

    def test_lux_upload_receipt_reuses_unchanged_bytes_and_actual_payload(self):
        operation = self.operation
        request = {"parameters": operation["parameters"], "inputs": supplier_jobs._inputs(operation, self.project),
                   "output_dir": str(self.project / "art/experiments/r/outputs/prop")}
        with patch("greybox.lux.upload", return_value={"url": "https://synthetic.invalid/source.png"}) as upload:
            first = supplier_jobs._lux_parameters(operation, request, self.project, "cn")
            second = supplier_jobs._lux_parameters(operation, request, self.project, "cn")
        self.assertEqual(upload.call_count, 1)
        self.assertEqual(first, second)
        self.assertEqual(first["img"], "https://synthetic.invalid/source.png")
        self.assertNotIn("image_path", first)
        context = supplier_jobs._context(operation, {"task_id": "original", "submitted_parameters": first})
        self.assertEqual(context["accepted_request"]["parameters"], first)

    def test_lux_multiview_upload_preserves_order(self):
        operation = self.make(mode="multiview")
        request = {"parameters": operation["parameters"], "inputs": supplier_jobs._inputs(operation, self.project),
                   "output_dir": str(self.project / "art/experiments/r/outputs/prop")}
        with patch("greybox.lux.upload", side_effect=[{"url": "https://synthetic.invalid/front.png"}, {"url": "https://synthetic.invalid/back.png"}]):
            parameters = supplier_jobs._lux_parameters(operation, request, self.project, "cn")
        self.assertEqual(parameters["imgs"], ["https://synthetic.invalid/front.png", "https://synthetic.invalid/back.png"])
        self.assertNotIn("img", parameters)

    def test_lux_uploaded_payload_rejects_input_substitution(self):
        request = {"parameters": self.operation["parameters"], "inputs": [{"path": "other.png", "sha256": "b" * 64}],
                   "output_dir": str(self.project / "art/experiments/r/outputs/prop")}
        with patch("greybox.lux.upload") as upload, self.assertRaisesRegex(core.WorkflowError, "upload bytes differ"):
            supplier_jobs._lux_parameters(self.operation, request, self.project, "cn")
        upload.assert_not_called()


if __name__ == "__main__": unittest.main()
