"""H3 pre-approval quotation tests; synthetic bridge, no provider/engine calls."""
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from io import StringIO
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_candidate as fixture
from greybox import quote_preview
from workflow_fixtures import capabilities, make_workflow, png
from modeling_ref_fixtures import write_reference_package
import hashlib


class QuoteBridge:
    """Test seam only; refuses any model execution operation."""
    def __init__(self):
        self.calls = []
        self.change_quote = None
        self.after_quote = None

    def validate(self, operation, parameters, region=None):
        self.calls.append(("validate", operation, copy.deepcopy(parameters), region))
        return {"ok": True}

    def upload(self, path, region):
        self.calls.append(("upload", path, region))
        return {"ok": True, "url": "https://signed.example/reference.png?signature=PRIVATE"}

    def quote_items_for(self, operation, parameters, sequence="1"):
        self.calls.append(("quote_items_for", operation, copy.deepcopy(parameters), sequence))
        return {sequence: {"operation": operation, "parameters": copy.deepcopy(parameters)}}

    def quote(self, items, region):
        self.calls.append(("quote", copy.deepcopy(items), region))
        current = datetime.now(timezone.utc)
        quote = {"quoteId": "quote_" + "a" * 32, "quotedAt": current.isoformat(),
                 "expiresAt": (current + timedelta(minutes=10)).isoformat(),
                 "estimatedCreditsTotal": 12 * len(items), "details": {key: 12 for key in items}}
        if self.change_quote:
            self.change_quote(quote)
        if self.after_quote:
            self.after_quote()
        return {"ok": True, "quote": quote}

    def submit(self, *args, **kwargs):
        raise AssertionError("Preview must never submit models")

    def status(self, *args, **kwargs):
        raise AssertionError("Preview must never poll model tasks")

    def fetch(self, *args, **kwargs):
        raise AssertionError("Preview must never fetch models")


class QuotePreview(unittest.TestCase):
    def setUp(self):
        self.t = fixture.Tests()
        self.t.setUp()
        self.t.generated()
        self.t.plan.pop("purpose", None)
        reference = write_reference_package(self.t.project, ["hero"], style_id="ceramic",
            selected_concept_sha256=hashlib.sha256(png(1)).hexdigest())
        generation = self.t.plan["assets"][0]["generation"]
        generation["modeling_references"] = reference
        package = fixture.core.read(self.t.project / reference["path"])
        generation["reference"] = package["assets"][0]["views"][0]["image"]
        self.checkpoint_path, self.checkpoint = make_workflow(self.t.project, self.t.plan, initialize_control=False)
        # H3 and native proxy have not occurred. Only H1/H2 can justify pricing.
        self.checkpoint["stages"] = [stage for stage in self.checkpoint["stages"]
            if stage["id"] not in {"art_proxy", "production_plan", "representative_sample"}]
        self.save_checkpoint()
        self.cap_file = self.t.project / "current-capabilities.json"
        fixture.core.write(self.cap_file, capabilities())
        self.output = self.t.project / "art/quotes/initial.json"
        self.bridge = QuoteBridge()

    def tearDown(self):
        self.t.tearDown()

    def save_checkpoint(self):
        fixture.core.write(self.checkpoint_path, self.checkpoint)
        self.t.plan["workflow"] = {"path": str(self.checkpoint_path),
            "sha256": fixture.core.file_hash(self.checkpoint_path), "session_id": "test-session"}
        self.save_plan()

    def save_plan(self):
        fixture.core.write(self.t.project / "plan.json", self.t.plan)

    def preview(self, **changes):
        arguments = {"plan_file": self.t.project / "plan.json", "project": self.t.project,
                     "output": self.output, "capability_file": self.cap_file,
                     "session_id": "test-session", "bridge": self.bridge}
        arguments.update(changes)
        return quote_preview.preview(**arguments)

    def test_h3_absent_can_quote_and_produces_no_execution_authority(self):
        summary = self.preview()
        self.assertEqual(summary["next"], "H3")
        self.assertFalse(summary["paid_generation_authorized"])
        self.assertEqual(summary["regional_totals"], {"cn": 12})
        self.assertEqual(summary["assets"][0]["version"], "G1")
        self.assertEqual(summary["assets"][0]["faceCount"], 30000)
        self.assertEqual(summary["assets"][0]["quoted_credits"], 12)
        self.assertFalse(list(self.t.project.rglob("run.json")))
        self.assertFalse(list(self.t.project.rglob("approval.json")))
        # The separate quote receipt cannot satisfy H3 or authorize core.run.
        with self.assertRaisesRegex(ValueError, "BLOCKED_STAGE_MISSING"):
            fixture.core.prepare(self.t.project / "plan.json", self.t.project, self.t.run,
                                 self.cap_file, "test-session")
        self.assertFalse((self.t.run / "run.json").exists())
        self.assertEqual({call[0] for call in self.bridge.calls}, {"validate", "upload", "quote_items_for", "quote"})

    def test_missing_h2_blocks_before_provider_calls(self):
        self.checkpoint["stages"] = [stage for stage in self.checkpoint["stages"] if stage["id"] != "spatial_design"]
        self.save_checkpoint()
        with self.assertRaisesRegex(ValueError, "BLOCKED_STAGE_MISSING"):
            self.preview()
        self.assertEqual(self.bridge.calls, [])
        self.assertFalse(self.output.exists())

    def test_missing_h1_blocks_before_provider_calls(self):
        self.checkpoint["stages"] = [stage for stage in self.checkpoint["stages"] if stage["id"] != "selection"]
        self.save_checkpoint()
        with self.assertRaisesRegex(ValueError, "BLOCKED_STAGE_MISSING"):
            self.preview()
        self.assertEqual(self.bridge.calls, [])

    def test_receipt_binds_actual_plan_workflow_capabilities_and_parameters(self):
        result = self.preview()
        receipt = fixture.core.read(self.output)
        self.assertEqual(receipt["kind"], "greybox-quote-preview")
        original = receipt.pop("receipt_hash")
        self.assertEqual(original, fixture.core.digest(receipt))
        self.assertEqual(original, result["receipt_hash"])
        self.assertEqual(receipt["plan"]["sha256"], fixture.core.file_hash(self.t.project / "plan.json"))
        self.assertEqual(receipt["workflow"]["sha256"], fixture.core.file_hash(self.checkpoint_path))
        self.assertEqual(receipt["capabilities"]["sha256"], fixture.core.file_hash(self.cap_file))
        request = receipt["requests"][0]
        self.assertEqual(request["parameters_hash"], fixture.core.digest(request["parameters"]))
        self.assertEqual(result["sha256"], fixture.core.file_hash(self.output))
        self.assertFalse(self.output.stat().st_mode & 0o077)

    def test_local_reference_is_uploaded_once_and_signed_url_is_not_in_summary(self):
        generation = self.t.plan["assets"][0]["generation"]
        reference = fixture.core.resolve_input(generation["reference"]["path"], self.t.project)
        self.save_plan()
        captured = StringIO()
        with redirect_stdout(captured):
            result = self.preview()
        self.assertEqual(captured.getvalue(), "")
        self.assertNotIn("signed.example", json.dumps(result))
        receipt = fixture.core.read(self.output)
        self.assertIn("signed.example", receipt["requests"][0]["parameters"]["img"])
        self.assertEqual(receipt["requests"][0]["reference"]["sha256"], fixture.core.file_hash(reference))
        self.assertEqual(sum(call[0] == "upload" for call in self.bridge.calls), 1)

    def test_changed_reference_hash_blocks_before_upload(self):
        generation = self.t.plan["assets"][0]["generation"]
        reference = fixture.core.resolve_input(generation["reference"]["path"], self.t.project)
        generation["reference"] = {"path": str(reference), "sha256": "0" * 64}
        self.save_plan()
        with self.assertRaisesRegex(ValueError, "hash changed"):
            self.preview()
        self.assertEqual(self.bridge.calls, [])

    def test_missing_explicit_version_blocks_before_quote(self):
        self.t.plan["assets"][0]["generation"]["parameters"].pop("version")
        self.save_plan()
        with self.assertRaisesRegex(ValueError, "explicit G1 or G1-Turbo"):
            self.preview()
        self.assertEqual(self.bridge.calls, [])

    def test_mcp_channel_cannot_impersonate_bundled_quote_bridge(self):
        report = capabilities()
        report["capabilities"]["lux"]["channel"]["kind"] = "mcp"
        fixture.core.write(self.cap_file, report)
        with self.assertRaisesRegex(ValueError, "BLOCKED_CAPABILITY"):
            self.preview()
        self.assertEqual(self.bridge.calls, [])

    def test_wrong_session_and_unverified_account_block(self):
        for change in ("session", "connection"):
            with self.subTest(change=change):
                report = capabilities()
                if change == "session":
                    report["session_id"] = "another-host"
                else:
                    report["capabilities"]["lux"]["verification"]["level"] = "discovered"
                fixture.core.write(self.cap_file, report)
                with self.assertRaises(ValueError):
                    self.preview()
                self.assertEqual(self.bridge.calls, [])

    def test_unverified_region_blocks_before_provider_calls(self):
        self.t.plan["assets"][0]["generation"]["region"] = "international"
        self.save_plan()
        with patch.object(quote_preview.workflow, "inspect_workflow", side_effect=AssertionError("visual checks started")):
            with self.assertRaisesRegex(ValueError, "region"):
                self.preview()
        self.assertEqual(self.bridge.calls, [])

    def test_unknown_or_inconsistent_price_is_refused(self):
        changes = [lambda q: q.pop("details"), lambda q: q["details"].update({"1": None}),
                   lambda q: q.update(estimatedCreditsTotal=13), lambda q: q.update(estimatedCreditsTotal=True)]
        for change in changes:
            with self.subTest(change=change):
                self.bridge.change_quote = change
                with self.assertRaisesRegex(ValueError, "cost|total"):
                    self.preview()
                self.assertFalse(self.output.exists())
                self.assertFalse(list(self.t.project.rglob("run.json")))

    def test_expired_quote_is_refused(self):
        self.bridge.change_quote = lambda q: q.update(expiresAt="2020-01-01T00:00:00+00:00")
        with self.assertRaisesRegex(ValueError, "expired"):
            self.preview()
        self.assertFalse(self.output.exists())

    def test_existing_output_is_preserved_without_provider_calls(self):
        self.output.parent.mkdir(parents=True)
        self.output.write_text("existing unique work")
        with self.assertRaisesRegex(ValueError, "already exists"):
            self.preview()
        self.assertEqual(self.output.read_text(), "existing unique work")
        self.assertEqual(self.bridge.calls, [])

    def test_outside_project_and_run_output_are_rejected(self):
        for target in (self.t.project.parent / "outside.json", self.t.project / "art/experiments/x/run.json"):
            with self.subTest(target=target):
                with self.assertRaises(ValueError):
                    self.preview(output=target)
                self.assertFalse(target.exists())
                self.assertEqual(self.bridge.calls, [])

    def test_skill_install_output_is_rejected(self):
        install = Path(quote_preview.__file__).resolve().parents[2]
        with self.assertRaisesRegex(ValueError, "skill installation"):
            quote_preview._target(install / "NEVER-WRITE-PREVIEW.json", install)

    def test_workflow_hash_drift_blocks_before_quote(self):
        self.checkpoint_path.write_text(self.checkpoint_path.read_text() + "\n")
        with self.assertRaisesRegex(ValueError, "missing/changed"):
            self.preview()
        self.assertEqual(self.bridge.calls, [])

    def test_approved_baseline_cannot_be_changed_in_draft(self):
        self.t.plan["contract"]["scene"] = "res://different-scene.tscn"
        self.save_plan()
        with self.assertRaisesRegex(ValueError, "differs from approved gameplay baseline"):
            self.preview()
        self.assertEqual(self.bridge.calls, [])

    def test_source_drift_during_quote_does_not_publish_receipt(self):
        source = self.t.project / "main.gd"
        self.bridge.after_quote = lambda: source.write_text(source.read_text() + "\n# drift\n")
        with self.assertRaisesRegex(ValueError, "inputs changed"):
            self.preview()
        self.assertFalse(self.output.exists())

    def test_output_created_during_quote_is_never_overwritten(self):
        def create_unique_output():
            self.output.parent.mkdir(parents=True, exist_ok=True)
            self.output.write_text("created concurrently")
        self.bridge.after_quote = create_unique_output
        with self.assertRaisesRegex(ValueError, "already exists"):
            self.preview()
        self.assertEqual(self.output.read_text(), "created concurrently")


if __name__ == "__main__":
    unittest.main(verbosity=2)
