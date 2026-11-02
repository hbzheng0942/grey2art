"""Leased production-backend tests using real synthetic workflow authorities."""
from copy import deepcopy
import base64
import json
import os
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch
import uuid

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/greybox-to-multistyle-art/runtime"))
import test_supplier_jobs_r3 as fixture
from greybox import core, supplier_execution as backend, supplier_jobs, suppliers


class SupplierExecutionTests(unittest.TestCase):
    def setUp(self):
        self.f = fixture.SupplierJobTests("test_submit_reservation_is_persisted_before_any_command")
        self.f.setUp()
        self.f.prepare()
        self.source = {"kind": "supplier", "path": str(self.f.run),
                       "pools": {"character-vendor": "character-account", "environment-vendor": "environment-account"}}

    def tearDown(self):
        self.f.tearDown()

    def lease(self):
        key = uuid.uuid4().hex
        return {"id": key, "owner_pid": os.getpid(), "deadline": time.time() + 30,
                "receipt_path": str(self.f.project / "actions" / key / "receipt.json"),
                "ticket_path": str(self.f.project / "actions" / key / "ticket.json")}

    def take(self, oid="hero-model", action="submit"):
        return backend.prepare(self.source, oid, action, self.lease())

    def finish(self, ticket):
        with patch.object(supplier_jobs, "_invoke", side_effect=self.f.adapter):
            response = backend.invoke(ticket)
        outcome = {"ok": True, "result": response}
        return backend.commit(self.source, ticket, outcome), outcome

    def state(self):
        return core.read(self.f.run / "supplier-run.json")

    def test_submission_reserves_original_cost_and_claim_before_network(self):
        ticket = self.take()
        row = self.state()["operations"]["hero-model"]
        self.assertEqual(row["state"], "submitting")
        self.assertEqual(self.state()["reservations"]["hero-model"]["credits"], "10")
        self.assertEqual(core.read(row["claim_path"])["phase"], "reserved")
        self.assertTrue(Path(ticket["lease"]["ticket_path"]).is_file())
        self.assertTrue(next(t for t in backend.scan(self.source) if t["id"] == "hero-model")["occupied"])
        result, _ = self.finish(ticket)
        self.assertEqual(result["acceptance"], "accepted")
        self.assertEqual(self.state()["operations"]["hero-model"]["task_id"], "original-hero-model")
        self.assertEqual(self.f.adapter.calls, [("hero-model", "submit")])

    def test_actual_network_boundary_runs_without_run_lock(self):
        ticket = self.take()
        ticket["execution_state_dir"] = str(self.f.project / "execution-state")
        ticket["execution_queue"] = str(self.f.project / "queue.json")
        def unlocked(*args):
            # The OS lock file persists; actual ownership must be available.
            with core.locked(self.f.run):
                return self.f.adapter(*args)
        with patch.object(supplier_jobs, "_invoke", side_effect=unlocked):
            response = backend.invoke(ticket)
        self.assertNotIn("execution_error", response)
        backend.commit(self.source, ticket, {"ok": True, "result": response})

    def test_same_action_ticket_cannot_invoke_create_twice(self):
        ticket = self.take()
        with patch.object(supplier_jobs, "_invoke", side_effect=self.f.adapter):
            first = backend.invoke(ticket)
            repeated = backend.invoke(ticket)
        self.assertIn("provider_result", first)
        self.assertEqual(repeated["execution_error"]["code"], "EXECUTION_ALREADY_INVOKED")
        self.assertEqual(repeated["execution_error"]["acceptance"], "unknown")
        self.assertEqual(self.f.adapter.calls.count(("hero-model", "submit")), 1)
        backend.commit(self.source, ticket, {"ok": True, "result": first})

    def test_real_reviewed_command_adapter_submit_query_fetch_path(self):
        # Rebuild only the small synthetic fixture so its reviewed executable
        # and all authorities bind the actual subprocess before preparation.
        self.f.tearDown()
        self.f = fixture.SupplierJobTests("test_submit_reservation_is_persisted_before_any_command")
        self.f.setUp()
        source = self.f.project / "explicit-reviewed-adapter.py"
        source.write_text('''import base64,json,sys
from pathlib import Path
r=json.load(sys.stdin)
method=r['method']; q=r['request']
out={'provider':r['provider'],'method':method,'ok':True}
if method=='submit': out['task_id']='real-command-'+Path(q['output_dir']).name
elif method=='status': out.update(state='succeeded',task_id=q['task_id'])
else:
    p=Path(q['output_dir']); p.mkdir(parents=True,exist_ok=True)
    a=p/'model.glb'; a.write_bytes(base64.b64decode(''' + repr(base64.b64encode(fixture.synthetic_glb()).decode()) + '''))
    out['artifacts']=[{'path':str(a),'role':'model'}]
print(json.dumps(out))
''')
        for provider in self.f.registry["providers"]:
            provider["binding"]["sha256"] = core.file_hash(source)
        self.f.portfolio["registry_sha256"] = suppliers.registry_digest(self.f.registry)
        self.f.selection["registry_sha256"] = suppliers.registry_digest(self.f.registry)
        self.f.rebind_portfolio()
        self.f.prepare()
        self.source["path"] = str(self.f.run)
        for action in ("submit", "status", "fetch"):
            ticket = self.take(action=action)
            result = backend.invoke(ticket)
            self.assertNotIn("execution_error", result, result)
            backend.commit(self.source, ticket, {"ok": True, "result": result})
        self.assertEqual(self.state()["operations"]["hero-model"]["state"], "ready")
        self.assertEqual(self.state()["operations"]["hero-model"]["task_id"], "real-command-hero-model")

    def test_no_second_prepare_while_original_action_is_leased(self):
        self.take()
        with self.assertRaises(ValueError):
            self.take()
        task = next(t for t in backend.scan(self.source) if t["id"] == "hero-model")
        self.assertIsNone(task["action"])
        self.assertIsNotNone(task["lease"])

    def test_ticket_write_failure_does_not_persist_an_unrecoverable_action(self):
        with patch('greybox.execution_process.atomic_json', side_effect=OSError('synthetic disk fault')):
            with self.assertRaises(OSError):
                self.take()
        row = self.state()['operations']['hero-model']
        self.assertEqual(row['state'], 'pending')
        self.assertNotIn('execution', row)
        ticket = self.take()
        self.assertTrue(Path(ticket['lease']['ticket_path']).is_file())
        self.assertEqual(self.f.adapter.calls, [])

    def test_workflow_drift_blocks_create_before_reservation_or_adapter(self):
        Path(self.f.checkpoint).write_text(Path(self.f.checkpoint).read_text() + "\n")
        with self.assertRaises(ValueError):
            self.take()
        row = self.state()["operations"]["hero-model"]
        self.assertEqual(row["state"], "pending")
        self.assertNotIn("hero-model", self.state()["reservations"])
        self.assertEqual(self.f.adapter.calls, [])

    def test_shared_guard_contention_keeps_task_pending_then_submits_once(self):
        with core.locked(self.f.project / "art/.supplier-claims/unresolved"):
            with self.assertRaises(core.WorkflowLockBusy):
                self.take()
        self.assertEqual(self.state()["operations"]["hero-model"]["state"], "pending")
        self.assertNotIn("hero-model", self.state()["reservations"])
        self.assertEqual(next(t for t in backend.scan(self.source) if t["id"] == "hero-model")["action"], "submit")
        self.finish(self.take())
        self.assertEqual(self.f.adapter.calls.count(("hero-model", "submit")), 1)

    def test_transient_claim_io_error_is_not_a_duplicate(self):
        with patch.object(supplier_jobs, "_claim", side_effect=OSError("synthetic temporary disk error")):
            with self.assertRaises(OSError):
                self.take()
        self.assertEqual(self.state()["operations"]["hero-model"]["state"], "pending")
        self.finish(self.take())
        self.assertEqual(self.f.adapter.calls.count(("hero-model", "submit")), 1)

    def test_guard_busy_before_invoke_is_retryable_without_provider_submission(self):
        ticket = self.take()
        with core.locked(self.f.project / "art/.supplier-claims/unresolved"):
            outcome = backend.invoke(ticket)
        error = outcome["execution_error"]
        self.assertEqual((error["code"], error["category"], error["acceptance"]),
                         ("WORKFLOW_LOCK_BUSY", "local", "not_accepted"))
        backend.commit(self.source, ticket, {"ok": True, "result": outcome})
        self.assertEqual(self.state()["operations"]["hero-model"]["state"], "pending")
        self.assertEqual(self.f.adapter.calls, [])
        self.finish(self.take())
        self.assertEqual(self.f.adapter.calls.count(("hero-model", "submit")), 1)

    def test_scan_counts_provider_occupancy_once_for_large_pending_queue(self):
        state, portfolio, registry, selection, option = supplier_jobs._load(self.f.run)
        template = option["operations"][0]
        option["operations"] = [{**template, "id": "pending-" + str(i)} for i in range(2000)]
        class Rows(dict):
            value_scans = 0
            def values(self):
                self.value_scans += 1
                return super().values()
        rows = Rows({op["id"]: {"state": "pending", "provider": op["provider"]} for op in option["operations"]})
        rows["pending-0"]["state"] = "running"
        state["operations"] = rows
        portfolio["execution_limits"] = {"max_inflight_per_provider": {"character-vendor": 1}}
        with patch.object(supplier_jobs, "_load", return_value=(state, portfolio, registry, selection, option)):
            tasks = backend.scan(self.source)
        self.assertEqual(len(tasks), 2000)
        self.assertTrue(all(t["deferred_reason"] == "run_capacity" for t in tasks[1:]))
        self.assertEqual(rows.value_scans, 1)
        self.assertEqual(self.f.adapter.calls, [])

    def test_worker_rechecks_provenance_before_create(self):
        ticket = self.take()
        Path(self.f.checkpoint).write_text(Path(self.f.checkpoint).read_text() + "\n")
        with patch.object(supplier_jobs, "_invoke") as invoke:
            response = backend.invoke(ticket)
        invoke.assert_not_called()
        self.assertEqual(response["execution_error"]["acceptance"], "not_accepted")
        backend.commit(self.source, ticket, {"ok": True, "result": response})
        self.assertEqual(self.state()["operations"]["hero-model"]["state"], "preflight_blocked")
        self.assertEqual(backend.retry_preflight(self.source, 'synthetic-corrected-preflight'), 1)
        self.assertEqual(self.state()["operations"]["hero-model"]["state"], "pending")

    def test_proven_unlaunched_supplier_action_can_be_prepared_again(self):
        ticket = self.take()
        backend.commit(self.source, ticket, {'ok': False, 'error': {
            'code': 'ACTION_NOT_STARTED', 'category': 'local', 'acceptance': 'not_accepted'}})
        self.assertEqual(self.state()['operations']['hero-model']['state'], 'pending')
        self.assertFalse(next(t for t in backend.scan(self.source) if t['id'] == 'hero-model')['occupied'])
        replacement = self.take()
        self.assertNotEqual(replacement['lease']['id'], ticket['lease']['id'])
        self.assertEqual(self.f.adapter.calls, [])

    def test_unknown_submit_retains_occupancy_without_repeat(self):
        ticket = self.take()
        self.f.adapter.ambiguous.add("hero-model")
        self.finish(ticket)
        row = self.state()["operations"]["hero-model"]
        self.assertEqual(row["state"], "unknown")
        task = next(t for t in backend.scan(self.source) if t["id"] == "hero-model")
        self.assertTrue(task["occupied"])
        self.assertIsNone(task["action"])
        with self.assertRaises(ValueError):
            self.take()
        # An unrelated supplier operation remains eligible in the same scan.
        self.assertEqual(next(t for t in backend.scan(self.source) if t["id"] == "environment-model")["action"], "submit")
        self.assertEqual(self.f.adapter.calls.count(("hero-model", "submit")), 1)

    def test_confirmed_capacity_rejection_reuses_original_reservation(self):
        ticket = self.take()
        error = {"code": "GENERATION_CONCURRENCY_LIMIT_EXCEEDED", "category": "capacity",
                 "acceptance": "not_accepted", "retry_after": .2, "message": "Confirmed full"}
        backend.commit(self.source, ticket, {"ok": False, "error": error})
        row = self.state()["operations"]["hero-model"]
        self.assertEqual(row["state"], "pending")
        self.assertEqual(core.read(row["claim_path"])["phase"], "reserved")
        self.assertFalse(next(t for t in backend.scan(self.source) if t["id"] == "hero-model")["occupied"])
        retry = self.take()
        self.finish(retry)
        self.assertEqual(len(self.state()["reservations"]), 1)
        self.assertEqual(self.state()["reservations"]["hero-model"]["credits"], "10")
        self.assertEqual(self.state()["operations"]["hero-model"]["submission_attempts"], 2)

    def test_remote_success_releases_slot_before_fetch_and_publication(self):
        self.finish(self.take())
        self.f.adapter.done.add("hero-model")
        result, _ = self.finish(self.take(action="status"))
        self.assertTrue(result["remote_terminal"])
        self.assertFalse(result["occupied"])
        task = next(t for t in backend.scan(self.source) if t["id"] == "hero-model")
        self.assertEqual((task["state"], task["action"]), ("download", "fetch"))
        self.assertNotIn("artifacts", self.state()["operations"]["hero-model"])
        self.finish(self.take(action="fetch"))
        row = self.state()["operations"]["hero-model"]
        self.assertEqual(row["state"], "ready")
        self.assertTrue(Path(row["artifacts"][0]["path"]).is_file())
        self.assertIn("/assets/hero/", row["artifacts"][0]["path"])

    def test_changed_output_after_worker_validation_is_not_committed(self):
        self.finish(self.take())
        self.f.adapter.done.add("hero-model")
        self.finish(self.take(action="status"))
        ticket = self.take(action="fetch")
        with patch.object(supplier_jobs, "_invoke", side_effect=self.f.adapter):
            response = backend.invoke(ticket)
        path = Path(response["provider_result"]["artifacts"][0]["path"])
        path.write_bytes(path.read_bytes() + b"changed")
        with self.assertRaisesRegex(ValueError, "changed after"):
            backend.commit(self.source, ticket, {"ok": True, "result": response})
        self.assertEqual(self.state()["operations"]["hero-model"]["state"], "succeeded")

    def test_poll_interval_and_query_retry_backoff_are_recorded(self):
        self.source.update(poll_interval=5, retry_interval=3)
        self.finish(self.take())
        before = time.time()
        self.finish(self.take(action="status"))
        self.assertGreaterEqual(self.state()["operations"]["hero-model"]["execution_next_at"], before + 5)
        for count in (1, 2):
            ticket = self.take(action="status")
            before = time.time()
            backend.commit(self.source, ticket, {"ok": False, "error": {
                "code": "QUERY_FAILED", "category": "network", "acceptance": "accepted", "message": "Interrupted query"}})
            row = self.state()["operations"]["hero-model"]
            self.assertGreaterEqual(row["execution_next_at"], before + 3 * 2 ** (count - 1))
            self.assertEqual(row["execution_error_count"], count)

    def test_stale_runtime_allows_original_query_and_fetch(self):
        self.finish(self.take())
        state = self.state()
        state["runtime_digest"] = "obsolete-runtime"
        core.write(self.f.run / "supplier-run.json", state)
        self.f.adapter.done.add("hero-model")
        self.finish(self.take(action="status"))
        self.finish(self.take(action="fetch"))
        self.assertEqual(self.state()["operations"]["hero-model"]["state"], "ready")
        # A cheap parent reservation is allowed, but isolated pre-POST source
        # validation rejects stale production without any adapter submission.
        self.finish(self.take("environment-model"))
        self.assertEqual(self.state()["operations"]["environment-model"]["state"], "preflight_blocked")
        self.assertNotIn(("environment-model", "submit"), self.f.adapter.calls)

    def test_query_deadline_preserves_original_id_for_recovery(self):
        self.finish(self.take())
        ticket = self.take(action="status")
        backend.commit(self.source, ticket, {"ok": False, "error": {
            "code": "ACTION_TIMEOUT", "category": "timeout", "acceptance": "accepted", "message": "Query timeout"}})
        row = self.state()["operations"]["hero-model"]
        self.assertEqual((row["state"], row["task_id"]), ("submitted", "original-hero-model"))
        self.assertNotIn("execution", row)
        self.finish(self.take(action="status"))
        self.assertEqual(self.f.adapter.calls.count(("hero-model", "submit")), 1)

    def test_actual_cost_overrun_blocks_new_spend_but_keeps_original_query(self):
        self.f.adapter.overcharge["hero-model"] = 99
        self.finish(self.take())
        state = self.state()
        self.assertEqual(state["cost_overrun"], "hero-model")
        self.assertEqual(state["operations"]["hero-model"]["consumed_credits"], "99")
        tasks = {task["id"]: task for task in backend.scan(self.source)}
        self.assertEqual(tasks["environment-model"]["deferred_reason"], "budget_overrun")
        self.assertIsNone(tasks["environment-model"]["action"])
        self.assertEqual(tasks["hero-model"]["action"], "status")

    def test_invalid_query_receipt_preserves_state_and_releases_action_lease(self):
        self.finish(self.take())
        ticket = self.take(action="status")
        with patch.object(supplier_jobs, "_invoke", return_value={"ok": True, "state": "invented"}):
            response = backend.invoke(ticket)
        self.assertIn("execution_error", response)
        backend.commit(self.source, ticket, {"ok": True, "result": response})
        row = self.state()["operations"]["hero-model"]
        self.assertEqual(row["task_id"], "original-hero-model")
        self.assertEqual(row["state"], "submitted")
        self.assertNotIn("execution", row)

    def test_failed_and_cancelled_are_terminal_without_fetch_or_retry(self):
        for observed in ("failed", "cancelled"):
            with self.subTest(observed=observed):
                oid = "hero-model" if observed == "failed" else "environment-model"
                self.finish(self.take(oid))
                ticket = self.take(oid, "status")
                backend.commit(self.source, ticket, {"ok": True, "result": {"ok": True, "state": observed}})
                task = next(t for t in backend.scan(self.source) if t["id"] == oid)
                self.assertEqual(task["state"], "blocked")
                self.assertTrue(task["remote_terminal"])
                self.assertFalse(task["occupied"])
                self.assertIsNone(task["action"])

    def test_ticket_hash_and_conflicting_duplicate_receipt_are_rejected(self):
        ticket = self.take()
        mutated = deepcopy(ticket)
        mutated["request"]["parameters"]["quality"] = "different"
        with self.assertRaises(ValueError):
            backend.commit(self.source, mutated, {"ok": True, "result": {}})
        _, outcome = self.finish(ticket)
        self.assertTrue(backend.commit(self.source, ticket, outcome)["duplicate"])
        with self.assertRaises(ValueError):
            backend.commit(self.source, ticket, {"ok": True, "result": {"ok": True, "task_id": "another"}})

    def test_explicit_run_cap_is_preserved_and_evidenced_override_is_operational(self):
        # Only scan capacity semantics; this does not fabricate a provider call.
        state = self.state()
        state["operations"]["hero-rig"].update(state="running", provider="character-vendor", task_id="synthetic-other-task")
        portfolio = core.read(self.f.run / "supplier-portfolio.json")
        portfolio["execution_limits"] = {"max_inflight_per_provider": {"character-vendor": 1}}
        # Keep immutable selection validation outside this read-only scan probe.
        core.write(self.f.run / "supplier-portfolio.json", portfolio)
        state["portfolio_digest"] = suppliers.portfolio_digest(portfolio)
        core.write(self.f.run / "supplier-run.json", state)
        task = next(t for t in backend.scan(self.source) if t["id"] == "hero-model")
        self.assertEqual(task["deferred_reason"], "run_capacity")
        upgraded = {**self.source, "execution_limits": {"max_inflight_per_provider": {"character-vendor": 2},
                                                       "source_ref": "synthetic://operational-limit-decision"}}
        self.assertEqual(next(t for t in backend.scan(upgraded) if t["id"] == "hero-model")["action"], "submit")
        unrelated = {**self.source, "execution_limits": {"max_inflight_per_provider": {"environment-vendor": 2},
                                                        "source_ref": "synthetic://other-limit-decision"}}
        self.assertEqual(next(t for t in backend.scan(unrelated) if t["id"] == "hero-model")["deferred_reason"], "run_capacity")


if __name__ == "__main__":
    unittest.main()
