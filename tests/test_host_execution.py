"""Actual native receipt integrity without invoking or inventing a host tool."""
from copy import deepcopy
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
import uuid

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1] / "skills/greybox-to-multistyle-art"
sys.path.insert(0, str(ROOT / "runtime"))
from greybox import host_execution as backend, image_jobs as jobs, image_adapters as adapters

try:
    from PIL import Image
except ImportError:
    Image = None


@unittest.skipIf(Image is None, "Pillow is required for actual output validation")
class HostExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="host-execution-")
        self.root = Path(self.temp.name)
        self.image = self.root / "style.png"
        self.output = self.root / "output.png"
        Image.new("RGB", (12, 12), "blue").save(self.image)
        Image.new("RGB", (12, 12), "green").save(self.output)
        self.request = {"tool_arguments": {"prompt": "Synthetic reference", "referenced_image_paths": [str(self.image)]},
                        "images": [{"path": str(self.image), "sha256": jobs.provider_http.file_hash(self.image)}]}
        self.folder = self.root / "native"
        backend.reserve(self.request, self.folder, authorization={"source_ref": "synthetic-existing-task"}, tool="synthetic-native")
        self.source = {"kind": "native", "path": str(self.folder), "pools": {"synthetic-native": "shared-account"}}

    def tearDown(self):
        self.temp.cleanup()

    def claim(self):
        task = backend.scan(self.source)[0]
        lease = {"id": uuid.uuid4().hex, "owner_pid": os.getpid(), "deadline": time.time() + 20,
                 "receipt_path": str(self.root / "receipt.json"), "ticket_path": str(self.root / "ticket.json")}
        return backend.prepare(self.source, task["id"], "submit", lease)

    def receipt(self, ticket, **overrides):
        return {"state": "succeeded", "action_id": ticket["lease"]["id"], "attempt_id": ticket["attempt_id"],
                "request_hash": ticket["request_hash"], "actual_arguments": self.request["tool_arguments"],
                "source_ref": "synthetic-actual-invocation", "output_path": str(self.output), **overrides}

    def test_same_action_id_cannot_change_original_capacity_lease(self):
        ticket = self.claim()
        wrong = deepcopy(ticket)
        wrong['lease']['pool'] = 'different-account'
        with self.assertRaises(adapters.ImageError):
            backend.commit(self.source, wrong, {'ok': True, 'result': self.receipt(ticket)})

    def test_native_route_needs_no_api_profile_and_never_claims_independence(self):
        task = backend.scan(self.source)[0]
        self.assertEqual(task["execution_mode"], "agent_driven")
        self.assertFalse(backend.capabilities({"independent_dispatch": True})["independent_dispatch"])
        ticket = self.claim()
        with self.assertRaises(adapters.ImageError):
            backend.invoke(ticket)

    def test_receipt_binds_exact_action_attempt_inputs_and_arguments(self):
        ticket = self.claim()
        for change in [{"action_id": "other"}, {"attempt_id": "other"}, {"request_hash": "other"},
                       {"actual_arguments": {"prompt": "Dropped style input"}}]:
            with self.subTest(change=change):
                with self.assertRaises(adapters.ImageError):
                    backend.commit(self.source, ticket, {"ok": True, "result": self.receipt(ticket, **change)})
        result = {"ok": True, "result": self.receipt(ticket)}
        completed = backend.commit(self.source, ticket, result)
        self.assertEqual(completed["state"], "ready")
        receipt = jobs._read(completed["outputs"][0]["receipt"]["path"])
        self.assertEqual(receipt["actual_input_image_sha256"], [self.request["images"][0]["sha256"]])
        self.assertEqual(completed, backend.commit(self.source, ticket, result))
        with self.assertRaises(adapters.ImageError):
            backend.commit(self.source, ticket, {"ok": True, "result": self.receipt(ticket, source_ref="conflicting-source")})

    def test_local_image_cannot_be_listed_but_omitted_from_actual_arguments(self):
        bad = deepcopy(self.request)
        bad["tool_arguments"] = {"prompt": "Only words"}
        with self.assertRaises(adapters.ImageError):
            backend.reserve(bad, self.root / "bad", authorization={"source_ref": "synthetic"}, tool="synthetic-native")

    def test_unknown_keeps_occupancy_and_cannot_be_claimed_again(self):
        ticket = self.claim()
        backend.commit(self.source, ticket, {"ok": False, "error": {"code": "ACTION_TIMEOUT", "acceptance": "unknown"}})
        task = backend.scan(self.source)[0]
        self.assertEqual((task["state"], task["action"], task["occupied"]), ("unknown", None, True))
        with self.assertRaises(adapters.ImageError):
            self.claim()

    def test_async_native_has_explicit_terminal_settlement_without_fake_query(self):
        ticket = self.claim()
        backend.commit(self.source, ticket, {"ok": True, "result": self.receipt(ticket, state="submitted", provider_task_id="original-native-task")})
        task = backend.scan(self.source)[0]
        self.assertEqual((task["state"], task["action"], task["occupied"]), ("active", None, True))
        terminal = {"state": "succeeded", "actual_arguments": self.request["tool_arguments"],
                    "source_ref": "synthetic-original-task-query-result", "output_path": str(self.output)}
        with self.assertRaises(adapters.ImageError):
            backend.settle(self.folder, "different-task", terminal)
        complete = backend.settle(self.folder, "original-native-task", terminal)
        self.assertEqual(complete["state"], "ready")
        self.assertFalse(backend.scan(self.source)[0]["occupied"])

    def test_failed_terminal_frees_native_capacity(self):
        ticket = self.claim()
        backend.commit(self.source, ticket, {"ok": True, "result": self.receipt(ticket, state="submitted", provider_task_id="original-native-task")})
        backend.settle(self.folder, "original-native-task", {"state": "failed", "actual_arguments": self.request["tool_arguments"], "source_ref": "synthetic-terminal-failure"})
        task = backend.scan(self.source)[0]
        self.assertTrue(task["remote_terminal"])
        self.assertFalse(task["occupied"])

    def test_uploaded_reference_mapping_reuses_verified_board_dispatch(self):
        from test_board_native import NativeBoards
        from greybox import core
        fixture = NativeBoards("test_codex_preserves_prompt_order_and_does_not_claim_invocation")
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.binding.update(host="workbuddy", tool="actual.synthetic.native-tool", input_transport="https_urls",
            uploads=[dict(row, url="https://example.invalid/" + str(index) + ".png", source_ref="synthetic-actual-upload")
                     for index, row in enumerate(fixture.refs)])
        fixture.prepare()
        dispatch = fixture.dispatch()
        request = {"tool_arguments": dispatch["tool_arguments"], "images": dispatch["images"],
                   "native_dispatch": {"path": "dispatch.json", "sha256": core.file_hash(fixture.project / "dispatch.json")}}
        folder = fixture.project / "execution-job"
        backend.reserve(request, folder, authorization={"source_ref": "synthetic-existing-task"},
                        tool=dispatch["tool"], base=fixture.project)
        source = {"kind": "native", "path": str(folder), "pools": {dispatch["tool"]: "shared-account"}}
        task = backend.scan(source)[0]
        ticket = backend.prepare(source, task["id"], "submit", {"id": uuid.uuid4().hex, "deadline": time.time() + 10,
                                 "ticket_path": str(fixture.project / "action-ticket.json")})
        result = {"state": "succeeded", "action_id": ticket["lease"]["id"], "attempt_id": ticket["attempt_id"],
                  "request_hash": ticket["request_hash"], "actual_arguments": dispatch["tool_arguments"],
                  "source_ref": "synthetic-real-host-call", "output_path": str(fixture.output())}
        self.assertEqual(backend.commit(source, ticket, {"ok": True, "result": result})["state"], "ready")

    def test_ticket_cannot_change_native_arguments_even_with_matching_receipt(self):
        ticket = self.claim()
        ticket["tool_arguments"] = {"prompt": "Changed after claim"}
        result = self.receipt(ticket, actual_arguments=ticket["tool_arguments"])
        with self.assertRaises(adapters.ImageError):
            backend.commit(self.source, ticket, {"ok": True, "result": result})

    def test_late_synchronous_receipt_recovers_unknown_original_without_new_call(self):
        ticket = self.claim()
        actual = self.receipt(ticket)
        backend.commit(self.source, ticket, {"ok": False, "error": {"code": "ACTION_DEADLINE", "acceptance": "unknown"}})
        with self.assertRaises(adapters.ImageError):
            backend.settle(self.folder, receipt={**actual, "action_id": "unrelated-action"})
        completed = backend.settle(self.folder, receipt=actual)
        self.assertEqual(completed["state"], "ready")
        self.assertEqual(backend.settle(self.folder, receipt=actual), completed)
        saved = jobs._read(completed["outputs"][0]["receipt"]["path"])
        self.assertEqual(saved["action_id"], ticket["lease"]["id"])


if __name__ == "__main__":
    unittest.main()
