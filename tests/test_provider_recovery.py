"""Offline profiled recovery through the real runner and Rodin adapter; no cloud calls."""
import copy
import unittest
from unittest.mock import patch

import test_supplier_jobs_r31 as forward_fixture
from test_supplier_jobs_r3 import synthetic_glb
from test_meshy_tripo import FakeAPI, mesh_request, mesh_task, TASK as MESHY_TASK
from greybox import account_profiles, core, supplier_jobs, suppliers
from greybox.provider_http import ProviderError
from greybox.providers import meshy, rodin

TASK, JOB = forward_fixture.TASK, forward_fixture.JOB


class ProfiledRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = forward_fixture.SupplierForwardR31()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.f = self.fixture.f
        self.operation = self.fixture.configure_builtin_rodin()
        self.profile = copy.deepcopy(self.f.registry["providers"][0]["account_profile"])
        self.profile_sha = account_profiles.profile_digest("rodin", self.profile)
        self.f.prepare()

    def row(self):
        return core.read(self.f.run / "supplier-run.json")["operations"]["hero-model"]

    def client(self, *, unknown=False, complete=False):
        test = self

        class Client:
            calls = []

            def request(self, method, path, payload=None, files=None):
                self.calls.append(path)
                if path == "/api/v2/rodin":
                    # The identity must be durable before the submission can be ambiguous.
                    row = test.row()
                    test.assertEqual(row["state"], "submitting")
                    test.assertEqual(row["account_profile"], test.profile)
                    test.assertEqual(row["account_profile_sha256"], test.profile_sha)
                    if unknown:
                        raise ProviderError("Synthetic unknown POST outcome", unknown_submission=True)
                    return {"uuid": TASK}  # Accepted UUID but missing private subscription key.
                if path == "/api/v2/status":
                    return {"jobs": [{"uuid": JOB, "status": "Done" if complete else "Generating"}]}
                if path == "/api/v2/download":
                    return {"list": [{"name": "model.glb", "url": "https://cdn.example/model.glb"}]}
                raise AssertionError("Unexpected synthetic API operation")

            def download(self, url, output_dir, filename):
                target = output_dir / filename
                target.write_bytes(synthetic_glb())
                return {"path": str(target), "sha256": core.file_hash(target)}

        return Client()

    def reconcile(self, **extra):
        return supplier_jobs.reconcile(self.f.run, "hero-model", TASK, "Synthetic inspection of original account task",
            recovery={"task_uuid": TASK, "subscription_key": "synthetic-private-key", **extra})

    def test_unknown_post_keeps_profile_before_response_and_recovers_without_resubmit(self):
        client = self.client(unknown=True)
        with patch.object(rodin, "_client", return_value=client):
            supplier_jobs.step(self.f.run)
            self.assertEqual(self.row()["state"], "unknown")
            self.assertNotIn("recovery", self.row())
            self.reconcile()
            result = supplier_jobs.step(self.f.run)
        self.assertEqual(result["operations"]["hero-model"]["state"], "running")
        self.assertEqual(client.calls, ["/api/v2/rodin", "/api/v2/status"])
        self.assertNotIn("synthetic-private-key", str(result))

    def test_missing_identifier_merge_preserves_account_through_status_and_fetch(self):
        client = self.client(complete=True)
        with patch.object(rodin, "_client", return_value=client):
            supplier_jobs.step(self.f.run)
            self.assertEqual(self.row()["state"], "recovery_required")
            self.reconcile()
            self.assertEqual(self.row()["recovery"]["account_profile"], self.profile)
            self.assertEqual(self.row()["recovery"]["account_profile_sha256"], self.profile_sha)
            result = supplier_jobs.step(self.f.run)
        self.assertEqual(result["operations"]["hero-model"]["state"], "ready")
        self.assertEqual(client.calls.count("/api/v2/rodin"), 1)
        self.assertIn("/api/v2/download", client.calls)
        self.assertNotIn("synthetic-private-key", str(result))

    def test_reconciliation_cannot_replace_account_or_task_identity(self):
        with patch.object(rodin, "_client", return_value=self.client()):
            supplier_jobs.step(self.f.run)
        before = core.read(self.f.run / "supplier-run.json")
        changed = {**self.profile, "account_ref": "another-account"}
        for extra in ({"account_profile": changed}, {"account_profile_sha256": "a" * 64},
                      {"task_uuid": JOB}, {"provider": "meshy"}):
            with self.subTest(extra=sorted(extra)), self.assertRaises(core.WorkflowError):
                self.reconcile(**extra)
            self.assertEqual(core.read(self.f.run / "supplier-run.json"), before)

    def test_pre_freeze_profiled_run_restores_identity_from_frozen_registry(self):
        client = self.client()
        with patch.object(rodin, "_client", return_value=client):
            supplier_jobs.step(self.f.run)
            ledger = core.read(self.f.run / "supplier-run.json")
            row = ledger["operations"]["hero-model"]
            for key in ("account_profile", "account_profile_sha256"):
                row.pop(key)
                row["recovery"].pop(key)
            core.write(self.f.run / "supplier-run.json", ledger)
            self.reconcile()
            result = supplier_jobs.step(self.f.run)
        self.assertEqual(self.row()["account_profile"], self.profile)
        self.assertEqual(result["operations"]["hero-model"]["state"], "running")
        self.assertEqual(client.calls.count("/api/v2/rodin"), 1)

    def test_unprofiled_legacy_context_keeps_original_route(self):
        row = {"task_id": TASK, "recovery": {"task_uuid": TASK, "subscription_key": "synthetic-private-key"}}
        supplier_jobs._freeze_account_profile(row, {"id": "rodin", "binding": {"kind": "builtin_api"}})
        request = supplier_jobs._context(self.operation, row)
        self.assertNotIn("account_profile", row)
        self.assertNotIn("account_profile", request["accepted_request"])
        self.assertEqual(account_profiles.bind_request("rodin", "status", request), request)

    def test_task_id_only_meshy_recovery_needs_no_fabricated_provider_receipt(self):
        profile = {"account_system": "cn", "account_ref": "synthetic-meshy",
                   "credential_env": "MESHY_TEST_API_KEY", "wallet": "meshy-test"}
        row = {"task_id": MESHY_TASK}  # Reconciled ID; the POST yielded no receipt.
        supplier_jobs._freeze_account_profile(row, {"id": "meshy", "binding": {"kind": "builtin_api"},
                                                  "account_profile": profile})
        context = supplier_jobs._context(mesh_request(), row)
        self.assertEqual(context["recovery"], {})
        bound = account_profiles.inject_registry("meshy", "status", context, profile)
        response = meshy.dispatch("status", bound, FakeAPI([mesh_task(status="IN_PROGRESS")]))
        self.assertTrue(response["ok"])
        self.assertEqual(response["account_profile"], profile)
        self.assertEqual(response["state"], "running")

    def test_expansion_cannot_borrow_other_account_operation_verification(self):
        # An explicitly authorized first-use probe is valid for a sample, but it
        # must not make another account's operation evidence valid for expansion.
        provider = self.f.registry["providers"][0]
        provider["verification"]["operations"]["image_to_3d"]["account_profile_sha256"] = "a" * 64
        self.operation["qualification_probe"] = True
        self.f.selection["allow_qualification_probes"] = ["hero-model"]
        self.f.selection["portfolio_sha256"] = suppliers.portfolio_digest(self.f.portfolio)
        self.assertTrue(suppliers.validate_selection(self.f.selection, self.f.portfolio,
                                                    self.f.registry, base=self.f.project)["ok"])
        ledger = core.read(self.f.run / "supplier-run.json")
        ledger.update(expansion=True, portfolio_digest=suppliers.portfolio_digest(self.f.portfolio),
                      selection_digest=core.digest(self.f.selection))
        for name, value in (("supplier-registry.json", self.f.registry),
                            ("supplier-portfolio.json", self.f.portfolio),
                            ("supplier-selection.json", self.f.selection), ("supplier-run.json", ledger)):
            core.write(self.f.run / name, value)
        calls = []

        def invoke(*args):
            calls.append(args[2])
            return {"ok": True, "task_id": TASK, "state": "running"}

        # Isolate this account gate from H4 authoring and unrelated concurrent
        # source edits; all selection/profile/operation checks remain real.
        with patch.object(supplier_jobs, "_gate", return_value={}), \
             patch.object(core, "runtime_snapshot", return_value={"sha256": ledger["runtime_digest"]}):
            result = supplier_jobs.step(self.f.run, invoker=invoke)
        self.assertEqual(calls, [])
        self.assertEqual(result["operations"]["hero-model"]["state"], "pending")
        self.assertTrue(result["blockers"])


if __name__ == "__main__":
    unittest.main()
