"""Original-task restoration tests; every provider/asset/decision is synthetic."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import patch
import uuid

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/greybox-to-multistyle-art/runtime"))
import test_supplier_jobs_r3 as fixture
from greybox import core, supplier_execution as backend, supplier_jobs as jobs


class ArtifactRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.f = fixture.SupplierJobTests("test_submit_reservation_is_persisted_before_any_command")
        self.f.setUp()
        self.f.prepare()
        self.f.adapter.done.add("hero-model")
        jobs.step(self.f.run, invoker=self.f.adapter)
        self.original = deepcopy(self.state()["operations"]["hero-model"])
        self.path = Path(self.original["artifacts"][0]["path"])
        self.source = {"kind": "supplier", "path": str(self.f.run),
                       "pools": {"character-vendor": "character-account", "environment-vendor": "environment-account"}}

    def tearDown(self):
        self.f.tearDown()

    def state(self):
        return core.read(self.f.run / "supplier-run.json")

    def fresh_fixture(self):
        self.f.tearDown()
        self.f = fixture.SupplierJobTests("test_submit_reservation_is_persisted_before_any_command")
        self.f.setUp()
        self.f.prepare()
        self.f.adapter.done.add("hero-model")
        self.source["path"] = str(self.f.run)

    def queue(self):
        return jobs.recover_artifacts(self.f.run, "hero-model", "synthetic://missing-or-damaged-observation")

    def ticket(self):
        key = uuid.uuid4().hex
        lease = {"id": key, "owner_pid": os.getpid(), "deadline": time.time() + 30,
                 "receipt_path": str(self.f.project / "actions" / key / "receipt.json"),
                 "ticket_path": str(self.f.project / "actions" / key / "ticket.json")}
        return backend.prepare(self.source, "hero-model", "fetch", lease)

    def finish(self, ticket, adapter=None):
        with patch.object(jobs, "_invoke", side_effect=adapter or self.f.adapter):
            response = backend.invoke(ticket)
        return backend.commit(self.source, ticket, {"ok": True, "result": response}), response

    def test_status_and_scan_do_not_call_missing_ready_bytes_complete(self):
        self.path.unlink()
        result = jobs.status(self.f.run)
        self.assertFalse(result["ok"])
        self.assertEqual(result["state"], "artifact_recovery_required")
        self.assertEqual(result["artifact_problems"]["hero-model"][0]["problem"], "missing")
        tasks = {t["id"]: t for t in backend.scan(self.source)}
        self.assertEqual(tasks["hero-model"]["deferred_reason"], "artifact_recovery_required")
        self.assertEqual(tasks["hero-rig"]["deferred_reason"], "dependency_artifact_recovery")
        self.assertIsNone(tasks["hero-model"]["action"])

    def test_polling_reuses_stat_bound_checks_but_gates_always_hash(self):
        jobs._ARTIFACT_CHECKS.clear()
        row = self.state()["operations"]["hero-model"]
        with patch.object(core, "file_hash", wraps=core.file_hash) as hash_file:
            self.assertEqual(jobs._artifact_problems(row, cached=True), [])
            self.assertEqual(jobs._artifact_problems(row, cached=True), [])
            self.assertEqual(hash_file.call_count, 1)
            self.assertEqual(jobs._artifact_problems(row), [])
            self.assertEqual(hash_file.call_count, 2)
            original = self.path.read_bytes()
            self.path.write_bytes(b"X" + original[1:])  # Same size, different contents/stat identity.
            self.assertTrue(jobs._artifact_problems(row, cached=True))
            self.assertEqual(hash_file.call_count, 3)

    def test_executor_restores_only_original_task_and_original_hash(self):
        self.path.unlink()
        before = self.state()
        self.queue()
        queued = self.state()
        self.assertEqual(queued["reservations"], before["reservations"])
        task = next(t for t in backend.scan(self.source) if t["id"] == "hero-model")
        self.assertEqual((task["action"], task["occupied"], task["remote_terminal"]), ("fetch", False, True))
        ticket = self.ticket()
        self.assertEqual(ticket["request"]["task_id"], self.original["task_id"])
        result, _ = self.finish(ticket)
        self.assertEqual(result["state"], "ready")
        row = self.state()["operations"]["hero-model"]
        self.assertEqual(row["artifacts"], self.original["artifacts"])
        self.assertEqual(core.file_hash(self.path), self.original["artifacts"][0]["sha256"])
        self.assertEqual(self.state()["reservations"], before["reservations"])
        self.assertEqual(self.f.adapter.calls.count(("hero-model", "submit")), 1)
        self.assertEqual(self.f.adapter.calls[-1], ("hero-model", "fetch"))
        self.assertEqual(row["artifact_recovery_history"][0]["task_id"], self.original["task_id"])
        self.assertNotIn("artifact_recovery", row)

    def test_changed_original_is_preserved_before_exact_restore(self):
        damaged = b"synthetic damaged unique bytes"
        self.path.write_bytes(damaged)
        self.queue()
        self.finish(self.ticket())
        history = self.state()["operations"]["hero-model"]["artifact_recovery_history"][-1]
        preserved = history["preserved"]
        self.assertEqual(len(preserved), 1)
        self.assertEqual(Path(preserved[0]["path"]).read_bytes(), damaged)
        self.assertEqual(preserved[0]["original_path"], str(self.path))
        self.assertEqual(core.file_hash(self.path), self.original["artifacts"][0]["sha256"])

    def test_different_redownload_bytes_are_rejected_without_overwriting(self):
        damaged = b"keep this original damaged content"
        self.path.write_bytes(damaged)
        self.queue()
        def changed(*args):
            response = self.f.adapter(*args)
            Path(response["artifacts"][0]["path"]).write_bytes(b"different provider result")
            return response
        result, response = self.finish(self.ticket(), changed)
        self.assertIn("execution_error", response)
        self.assertEqual(result["state"], "artifact_recovery")
        self.assertEqual(self.path.read_bytes(), damaged)
        self.assertNotIn("artifact_recovery_history", self.state()["operations"]["hero-model"])
        self.assertEqual(self.f.adapter.calls.count(("hero-model", "submit")), 1)
        # A subsequent exact re-fetch resumes this same restoration attempt.
        self.finish(self.ticket())
        self.assertEqual(core.file_hash(self.path), self.original["artifacts"][0]["sha256"])

    def test_wrong_role_is_rejected_even_with_original_bytes(self):
        self.path.unlink()
        self.queue()
        def wrong_role(*args):
            response = self.f.adapter(*args)
            response["artifacts"][0]["role"] = "another-role"
            return response
        result, _ = self.finish(self.ticket(), wrong_role)
        self.assertEqual(result["state"], "artifact_recovery")
        self.assertFalse(self.path.exists())
        self.assertEqual(self.state()["operations"]["hero-rig"]["state"], "pending")

    def test_wrong_task_identity_cannot_restore_an_original_artifact(self):
        self.path.unlink()
        self.queue()
        def wrong_task(*args):
            return {**self.f.adapter(*args), "task_id": "another-provider-task"}
        result, _ = self.finish(self.ticket(), wrong_task)
        self.assertEqual(result["state"], "artifact_recovery")
        self.assertFalse(self.path.exists())

    def test_manual_recovery_wrong_task_cannot_contaminate_original_cost(self):
        self.path.unlink()
        self.queue()
        before = self.state()
        def wrong_task(*args):
            return {**self.f.adapter(*args), "task_id": "another-provider-task", "consumed_credits": 999}
        jobs.step(self.f.run, invoker=wrong_task)
        after = self.state()
        self.assertEqual(after["reservations"], before["reservations"])
        self.assertNotIn("cost_overrun", after)
        self.assertNotIn("consumed_credits", after["operations"]["hero-model"])
        self.assertNotIn("cost_observations", after["operations"]["hero-model"])
        self.assertEqual(after["operations"]["hero-model"]["state"], "artifact_recovery")
        self.assertFalse(self.path.exists())

    def test_original_duplicate_auxiliary_bytes_restore_to_distinct_paths(self):
        self.fresh_fixture()
        def with_auxiliary(registry, operation, method, request, authorization, project):
            response = self.f.adapter(registry, operation, method, request, authorization, project)
            if method == "fetch":
                response["artifacts"] = list(response["artifacts"])
                for name in ("metadata-a.json", "metadata-b.json"):
                    path = Path(request["output_dir"]) / name
                    path.write_text("{}")
                    response["artifacts"].append({"path": str(path), "role": "metadata", "format": "json"})
            return response
        jobs.step(self.f.run, invoker=with_auxiliary)
        original = deepcopy(self.state()["operations"]["hero-model"])
        self.assertEqual(original["state"], "ready")
        self.assertEqual(len(original["artifacts"]), 3)
        metadata = [item for item in original["artifacts"] if item.get("role") == "metadata"]
        self.assertEqual(len({item["sha256"] for item in metadata}), 1)
        for item in original["artifacts"]:
            Path(item["path"]).unlink()
        self.queue()
        result, _ = self.finish(self.ticket(), with_auxiliary)
        self.assertEqual(result["state"], "ready")
        restored = self.state()["operations"]["hero-model"]["artifacts"]
        self.assertEqual(restored, original["artifacts"])
        self.assertEqual(len({item["path"] for item in restored}), 3)
        for item in restored:
            self.assertEqual(core.file_hash(item["path"]), item["sha256"])
        self.assertEqual(self.f.adapter.calls.count(("hero-model", "submit")), 1)

    def test_fresh_manual_fetch_rejects_wrong_task_before_publish_or_cost(self):
        self.fresh_fixture()
        def wrong_fetch(registry, operation, method, request, authorization, project):
            response = self.f.adapter(registry, operation, method, request, authorization, project)
            if method == "fetch":
                response.update(task_id="another-provider-task", consumed_credits=999)
            return response
        jobs.step(self.f.run, invoker=wrong_fetch)
        after = self.state()
        row = after["operations"]["hero-model"]
        self.assertEqual(row["state"], "succeeded")
        self.assertEqual(row["task_id"], "original-hero-model")
        self.assertNotIn("artifacts", row)
        self.assertNotIn("consumed_credits", row)
        self.assertNotIn("cost_overrun", after)
        published = self.f.project / self.f.portfolio["options"][0]["operations"][0]["publish"]["path"]
        self.assertFalse(published.exists())
        self.assertEqual(self.f.adapter.calls.count(("hero-model", "submit")), 1)

    def test_manual_query_checks_identity_before_recording_cost(self):
        self.fresh_fixture()
        def wrong_status(registry, operation, method, request, authorization, project):
            response = self.f.adapter(registry, operation, method, request, authorization, project)
            if method == "status":
                response.update(task_id="another-provider-task", consumed_credits=999)
            return response
        jobs.step(self.f.run, invoker=wrong_status)
        after = self.state()
        self.assertEqual(after["operations"]["hero-model"]["state"], "submitted")
        self.assertNotIn("cost_overrun", after)
        self.assertNotIn("consumed_credits", after["operations"]["hero-model"])
        self.assertNotIn(("hero-model", "fetch"), self.f.adapter.calls)

    def test_changed_recovery_context_is_rejected_before_adapter_invocation(self):
        self.path.unlink()
        self.queue()
        state = self.state()
        state["operations"]["hero-model"]["submitted_parameters"] = {"synthetic": "changed-after-recovery-request"}
        core.write(self.f.run / "supplier-run.json", state)
        before = list(self.f.adapter.calls)
        with self.assertRaisesRegex(ValueError, "original task"):
            self.ticket()
        self.assertEqual(self.f.adapter.calls, before)

    def test_lost_restoration_receipt_keeps_preserved_content_on_retry(self):
        damaged = b"unique local content before lost restoration receipt"
        self.path.write_bytes(damaged)
        self.queue()
        ticket = self.ticket()
        with patch.object(jobs, "_invoke", side_effect=self.f.adapter):
            first = backend.invoke(ticket)
        self.assertNotIn("execution_error", first)
        # The worker's side effect completed, but its receipt was unavailable.
        backend.commit(self.source, ticket, {"ok": False, "error": {
            "code": "ACTION_TIMEOUT", "category": "timeout", "acceptance": "accepted"}})
        self.assertEqual(self.state()["operations"]["hero-model"]["state"], "artifact_recovery")
        self.finish(self.ticket())
        history = self.state()["operations"]["hero-model"]["artifact_recovery_history"][-1]
        self.assertEqual(len(history["preserved"]), 1)
        self.assertEqual(Path(history["preserved"][0]["path"]).read_bytes(), damaged)
        self.assertEqual(self.f.adapter.calls.count(("hero-model", "submit")), 1)

    def test_existing_runtime_drift_does_not_require_a_new_generation(self):
        self.path.unlink()
        state = self.state()
        state["runtime_digest"] = "synthetic-older-runtime"
        core.write(self.f.run / "supplier-run.json", state)
        self.queue()
        self.finish(self.ticket())
        self.assertTrue(self.path.is_file())
        self.assertEqual(self.f.adapter.calls.count(("hero-model", "submit")), 1)

    def test_manual_step_uses_same_restoration_and_keeps_pending_task_dependencies(self):
        self.path.unlink()
        self.queue()
        self.f.adapter.fail_fetch.add("hero-model")
        first = jobs.step(self.f.run, invoker=self.f.adapter)
        self.assertEqual(first["operations"]["hero-model"]["state"], "artifact_recovery")
        self.assertEqual(first["operations"]["hero-rig"]["state"], "pending")
        self.f.adapter.fail_fetch.clear()
        jobs.step(self.f.run, invoker=self.f.adapter)
        self.assertEqual(self.state()["operations"]["hero-model"]["state"], "ready")
        self.assertEqual(self.f.adapter.calls.count(("hero-model", "submit")), 1)

    def test_intact_unknown_and_leased_work_cannot_be_reset(self):
        with self.assertRaises(ValueError):
            self.queue()
        self.path.unlink()
        state = self.state()
        state["operations"]["hero-model"]["execution"] = {"id": "synthetic-active-lease"}
        core.write(self.f.run / "supplier-run.json", state)
        with self.assertRaises(ValueError):
            self.queue()
        state["operations"]["hero-model"].pop("execution")
        state["operations"]["hero-model"]["state"] = "unknown"
        core.write(self.f.run / "supplier-run.json", state)
        with self.assertRaises(ValueError):
            self.queue()

    @unittest.skipIf(os.name == "nt", "Symlink creation permission varies on Windows")
    def test_redirected_canonical_path_is_not_restored_through_symlink(self):
        self.path.unlink()
        external = self.f.project / "unrelated.glb"
        external.write_bytes(b"unrelated unique content")
        self.path.symlink_to(external)
        with self.assertRaisesRegex(ValueError, "redirected"):
            self.queue()
        self.assertEqual(external.read_bytes(), b"unrelated unique content")

    def test_public_cli_queues_recovery_without_network_or_another_approval(self):
        self.path.unlink()
        script = ROOT / "skills/greybox-to-multistyle-art/scripts/greybox.py"
        result = subprocess.run([sys.executable, "-B", str(script), "supplier-jobs", "recover-artifacts",
            "--run-dir", str(self.f.run), "--operation-id", "hero-model", "--source-ref", "synthetic://cli-observation"],
            capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(json.loads(result.stdout)["operations"]["hero-model"]["state"], "artifact_recovery")
        self.assertEqual(self.f.adapter.calls.count(("hero-model", "submit")), 1)


if __name__ == "__main__":
    unittest.main()
