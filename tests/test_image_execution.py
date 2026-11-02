"""Behavioral tests of real image ledgers with synthetic provider responses."""
from copy import deepcopy
import base64
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import uuid

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1] / "skills/greybox-to-multistyle-art"
sys.path.insert(0, str(ROOT / "runtime"))
from greybox import image_adapters as adapters, image_jobs as jobs, image_execution as backend

try:
    from PIL import Image
except ImportError:
    Image = None


@unittest.skipIf(Image is None, "Pillow is required for actual image fixtures")
class ImageExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="image-execution-")
        self.root = Path(self.temp.name)
        self.config = self.root / "profiles"
        self.env = patch.dict(os.environ, {"GREYBOX_EXECUTION_TEST_KEY": "synthetic-not-a-real-key"})
        self.env.start()
        self.style = self.root / "style.png"
        self.output = self.root / "output.png"
        Image.new("RGB", (12, 12), "blue").save(self.style)
        Image.new("RGB", (12, 12), "green").save(self.output)
        self.profile = {"kind": "openai", "model": "synthetic-model", "base_url": "https://synthetic.invalid/v1",
                        "credential_env": "GREYBOX_EXECUTION_TEST_KEY"}
        jobs.configure("fixture", self.profile, self.config)
        self.folder = self.root / "job"
        self.request = {"operation": "edit", "prompt": "Synthetic reference", "images": [
            {"path": str(self.style), "sha256": jobs.provider_http.file_hash(self.style)}], "parameters": {}}
        jobs.reserve("fixture", self.request, self.folder, authorization={"source_ref": "synthetic-fixture"}, config_dir=self.config)
        self.source = {"kind": "image", "path": str(self.folder), "pools": {"fixture": "shared-account"}, "poll_interval": .01}

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def lease(self):
        return {"id": uuid.uuid4().hex, "owner_pid": os.getpid(), "deadline": time.time() + 10,
                "receipt_path": str(self.root / "receipt.json"), "ticket_path": str(self.root / "ticket.json")}

    def prepare(self, action):
        return backend.prepare(self.source, backend.scan(self.source)[0]["id"], action, self.lease())

    def test_reservation_does_not_invoke_and_sync_result_releases_before_fetch(self):
        self.assertEqual(backend.scan(self.source)[0]["state"], "pending")
        ticket = self.prepare("submit")
        self.assertTrue(backend.scan(self.source)[0]["occupied"])

        def actual_submit(profile, request):
            self.assertEqual(request["images"][0]["sha256"], self.request["images"][0]["sha256"])
            with jobs._lock(self.folder):
                pass  # The isolated network action does not hold the job lock.
            return {"state": "succeeded", "items": [{"b64_json": base64.b64encode(self.output.read_bytes()).decode()}]}

        with patch.object(adapters, "submit", side_effect=actual_submit) as submit:
            result = backend.invoke(ticket)
        self.assertEqual(submit.call_count, 1)
        self.assertNotIn("items", result)
        self.assertNotIn("b64_json", str(result))
        backend.commit(self.source, ticket, {"ok": True, "result": result})
        task = backend.scan(self.source)[0]
        self.assertEqual((task["state"], task["action"], task["occupied"]), ("download", "fetch", False))
        self.assertFalse((self.folder / "receipt-0.json").exists())
        ticket = self.prepare("fetch")
        original = jobs._download_item
        import hashlib
        folder, snapshot = jobs._job(self.folder)
        canonical = Path(snapshot["asset_dir"])
        canonical.mkdir(parents=True)
        prefix = ".image-fetch-" + hashlib.sha256((str(folder) + ":" + snapshot["job_id"]).encode()).hexdigest()[:20] + "-"
        abandoned = canonical / (prefix + "abandoned")
        abandoned.mkdir()
        (abandoned / "partial.image").write_bytes(b"synthetic partial bytes from a killed action")
        neighbor = canonical / ".image-fetch-another-job-do-not-remove"
        neighbor.mkdir()

        def download(item, target):
            with jobs._lock(self.folder):
                pass
            return original(item, target)

        with patch.object(jobs, "_download_item", side_effect=download):
            result = backend.invoke(ticket)
        self.assertFalse(abandoned.exists())
        self.assertTrue(neighbor.exists())
        self.assertEqual(jobs._job(self.folder)[1]["state"], "succeeded")
        backend.commit(self.source, ticket, {"ok": True, "result": result})
        data = jobs._job(self.folder)[1]
        self.assertEqual(data["state"], "downloaded")
        receipt = jobs._read(data["outputs"][0]["receipt"]["path"])
        self.assertEqual(receipt["actual_input_image_sha256"], [self.request["images"][0]["sha256"]])

    def test_async_poll_keeps_original_identity_and_has_no_implicit_resubmit(self):
        # A registered custom adapter supplies actual async semantics.
        folder, data = jobs._job(self.folder)
        source = self.root / "adapter.py"
        source.write_text("import json; print(json.dumps({'state':'running','provider_task_id':'original'}))\n")
        data["profile"] = {"schema": "greybox.image-profile/v1", "kind": "custom",
            "credential_env": "GREYBOX_EXECUTION_TEST_KEY",
            "capabilities": {"generate": True, "edit": True, "max_references": 1, "parameters": []},
            "adapter": {"source": str(source), "sha256": jobs.provider_http.file_hash(source),
                        "argv": [sys.executable, "{adapter}"], "documentation": {"source_ref": "synthetic-manual"}}}
        data["profile_sha256"] = adapters.fingerprint(data["profile"])
        jobs._save(folder, data)
        ticket = self.prepare("submit")
        backend.commit(self.source, ticket, {"ok": True, "result": {"state": "submitted", "provider_task_id": "original"}})
        self.assertEqual(backend.scan(self.source)[0]["action"], "status")
        ticket = self.prepare("status")
        with patch.object(adapters, "status", return_value={"state": "running", "provider_task_id": "original"}) as status:
            response = backend.invoke(ticket)
        status.assert_called_once_with(data["profile"], "original")
        backend.commit(self.source, ticket, {"ok": True, "result": response})
        self.assertEqual(jobs._job(self.folder)[1]["provider_task_id"], "original")
        self.assertGreater(backend.scan(self.source)[0]["next_at"], time.time() - .1)

    def test_timeout_unknown_blocks_new_create_and_keeps_capacity(self):
        ticket = self.prepare("submit")
        backend.commit(self.source, ticket, {"ok": False, "error": {"code": "ACTION_TIMEOUT", "category": "timeout", "acceptance": "unknown"}})
        task = backend.scan(self.source)[0]
        self.assertEqual((task["state"], task["action"], task["occupied"]), ("unknown", None, True))
        with self.assertRaises(adapters.ImageError):
            self.prepare("submit")
        with patch.object(adapters, "submit") as submit:
            self.assertTrue(jobs.resume(self.folder)["reconciliation_required"])
        submit.assert_not_called()

    def test_explicit_capacity_refusal_remains_pending_and_obeys_cooldown(self):
        ticket = self.prepare("submit")
        backend.commit(self.source, ticket, {"ok": False, "error": {"code": "FULL", "category": "capacity", "acceptance": "not_accepted", "retry_after": 2}})
        task = backend.scan(self.source)[0]
        self.assertEqual((task["state"], task["occupied"]), ("pending", False))
        self.assertGreater(task["next_at"], time.time() + 1)

    def test_duplicate_receipts_are_idempotent_and_wrong_lease_rejected(self):
        ticket = self.prepare("submit")
        response = {"ok": True, "result": {"state": "succeeded", "items": [{"path": str(self.output)}]}}
        wrong = deepcopy(ticket)
        wrong["lease"]["id"] = "wrong-action"
        with self.assertRaises(adapters.ImageError):
            backend.commit(self.source, wrong, response)
        backend.commit(self.source, ticket, response)
        backend.commit(self.source, ticket, response)
        with self.assertRaises(adapters.ImageError):
            backend.commit(self.source, ticket, {"ok": True, "result": {"state": "cancelled"}})

    def test_same_action_id_does_not_allow_pool_or_deadline_tampering(self):
        ticket = self.prepare('submit')
        for field, value in [('deadline', time.time() + 999), ('pool', 'different-account')]:
            wrong = deepcopy(ticket)
            wrong['lease'][field] = value
            with self.assertRaises(adapters.ImageError):
                backend.invoke(wrong)

    def test_legacy_commands_cannot_race_an_executor_action(self):
        ticket = self.prepare("submit")
        with self.assertRaises(adapters.ImageError):
            jobs.execute(self.folder)
        backend.commit(self.source, ticket, {"ok": True, "result": {"state": "succeeded", "items": [{"path": str(self.output)}]}})
        self.prepare("fetch")
        with self.assertRaises(adapters.ImageError):
            jobs.fetch(self.folder)

    def test_changed_input_fails_before_any_network(self):
        Image.new("RGB", (12, 12), "red").save(self.style)
        ticket = self.prepare("submit")
        with patch.object(adapters, "submit") as submit:
            with self.assertRaises(adapters.ImageError):
                backend.invoke(ticket)
        submit.assert_not_called()

    def test_failed_and_cancelled_are_terminal_without_new_generation(self):
        for state in ("failed", "cancelled"):
            with self.subTest(state=state):
                if state == "cancelled":
                    self.folder = self.root / "cancelled-job"
                    jobs.reserve("fixture", self.request, self.folder, authorization={"source_ref": "synthetic-fixture"}, config_dir=self.config)
                    self.source["path"] = str(self.folder)
                ticket = self.prepare("submit")
                backend.commit(self.source, ticket, {"ok": True, "result": {"state": state}})
                task = backend.scan(self.source)[0]
                self.assertTrue(task["remote_terminal"])
                self.assertFalse(task["occupied"])
                self.assertIsNone(task["action"])

    def test_same_ticket_cannot_invoke_create_twice(self):
        ticket = self.prepare("submit")
        with patch.object(adapters, "submit", return_value={"state": "succeeded", "items": [{"path": str(self.output)}]}) as submit:
            backend.invoke(ticket)
            with self.assertRaises(adapters.ImageError) as raised:
                backend.invoke(ticket)
        self.assertTrue(raised.exception.unknown_submission)
        self.assertEqual(submit.call_count, 1)

    def test_changed_ticket_payload_fails_before_provider_invocation(self):
        ticket = self.prepare("submit")
        ticket["request"]["prompt"] = "A changed unapproved prompt"
        with patch.object(adapters, "submit") as submit:
            with self.assertRaises(adapters.ImageError):
                backend.invoke(ticket)
        submit.assert_not_called()

    def test_explicit_adapter_error_keeps_structured_refusal(self):
        ticket = self.prepare("submit")
        response = {"ok": False, "state": "failed", "error": {"code": "FULL", "category": "capacity",
                    "acceptance": "not_accepted", "retry_after": 3}}
        with patch.object(adapters, "submit", return_value=response):
            with self.assertRaises(adapters.ImageError) as raised:
                backend.invoke(ticket)
        self.assertEqual(raised.exception.category, "capacity")
        self.assertEqual(raised.exception.acceptance, "not_accepted")
        self.assertEqual(raised.exception.retry_after, 3)

    def test_changed_output_after_worker_verification_is_rejected_by_stat(self):
        ticket = self.prepare("submit")
        backend.commit(self.source, ticket, {"ok": True, "result": {"state": "succeeded", "items": [{"path": str(self.output)}]}})
        ticket = self.prepare("fetch")
        result = backend.invoke(ticket)
        Path(result["outputs"][0]["path"]).write_bytes(b"Changed after worker verified the image")
        with self.assertRaises(adapters.ImageError):
            backend.commit(self.source, ticket, {"ok": True, "result": result})


if __name__ == "__main__":
    unittest.main()
