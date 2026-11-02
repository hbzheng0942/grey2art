"""Real local ledger transitions with mocked Lux networking; no paid calls."""
from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch

import test_supplier_jobs_r3 as fixtures
from greybox import core, lux, production_control, supplier_jobs, suppliers


class LuxPreflightTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.SupplierJobTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        f = self.fixture
        f.registry["providers"][0].update(id="lux3d", binding={"kind": "builtin_lux"})
        for operation in f.portfolio["options"][0]["operations"]:
            if operation["provider"] == "character-vendor":
                operation.update(provider="lux3d", region="cn")
                if operation["operation"] == "image_to_3d":
                    operation.update(model_version="G1", parameters={"version": "G1", "faceCount": 30000, "image_path": 0})
                else:
                    operation["parameters"] = {"modelUrl": "https://assets.example.com/source.glb"}
        f.portfolio["registry_sha256"] = suppliers.registry_digest(f.registry)
        f.selection["registry_sha256"] = suppliers.registry_digest(f.registry)
        f.rebind_portfolio()
        f.prepare()
        self.operation = f.portfolio["options"][0]["operations"][0]
        # Keep an independent sibling already ready, so this test never launches its external adapter.
        state = self.state()
        sibling = f.project / "synthetic-environment.glb"
        sibling.write_bytes(fixtures.synthetic_glb())
        state["operations"]["environment-model"].update(state="ready", artifacts=[{
            "path": str(sibling), "sha256": core.file_hash(sibling), "role": "model"}])
        core.write(f.run / "supplier-run.json", state)
        self.control = production_control.control_path(f.project, f.portfolio)
        self.control_before = self.control.read_bytes()
        self.quote_value = {"ok": True, "region": "cn", "quote": {
            "quoteId": "quote_" + "a" * 32, "estimatedCreditsTotal": 10}}
        for name, value in (("upload", {"url": "https://assets.example.com/reference.png"}),
                            ("quote_items_for", {"1": {"synthetic": True}}),
                            ("quote", self.quote_value), ("submit", {"ok": True, "taskId": 42}),
                            ("status", {"ok": True, "state": "running"})):
            patcher = patch.object(lux, name, return_value=value)
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)

    def state(self):
        return core.read(self.fixture.run / "supplier-run.json")

    def advance(self):
        return supplier_jobs.step(self.fixture.run, max_submissions=1)

    def assert_unsubmitted(self):
        state = self.state()
        self.assertEqual(state["operations"]["hero-model"]["state"], "pending")
        self.assertNotIn("task_id", state["operations"]["hero-model"])
        self.assertNotIn("claim_path", state["operations"]["hero-model"])
        self.assertNotIn("hero-model", state["reservations"])
        self.assertEqual(state["events"][-1]["submission_attempts"], 0)
        self.assertEqual(self.control.read_bytes(), self.control_before)
        self.submit.assert_not_called()

    def test_quote_timeout_resumes_same_run_without_claim_charge_or_double_quote(self):
        self.quote.side_effect = [lux.LuxError("NETWORK", "synthetic timeout", retryable=True), self.quote_value]
        self.advance()
        self.assert_unsubmitted()
        self.assertEqual(self.state()["operations"]["hero-model"]["pre_submit_error"]["code"], "LIVE_QUOTE_FAILED")

        def submit_checked(*args, **kwargs):
            state = self.state()
            row = state["operations"]["hero-model"]
            self.assertEqual(row["state"], "submitting")
            self.assertIn("hero-model", state["reservations"])
            self.assertTrue(Path(row["claim_path"]).is_file())
            self.assertEqual(row["live_quote_receipt"]["quote_id"], kwargs["quote_id"])
            self.assertEqual(core.file_hash(row["live_quote_receipt"]["path"]), row["live_quote_receipt"]["sha256"])
            self.assertEqual(row["submitted_parameters"], args[1])
            return {"ok": True, "taskId": 42}
        self.submit.side_effect = submit_checked
        self.advance()
        row = self.state()["operations"]["hero-model"]
        self.assertEqual(row["state"], "running")
        self.assertNotIn("pre_submit_error", row)
        self.assertNotIn("operational_blocker", row)
        self.assertEqual(self.quote.call_count, 2)
        self.submit.assert_called_once()
        self.upload.assert_called_once()  # Resume reuses the hash-bound upload.
        self.advance()  # Accepted task polling never quotes or submits again.
        self.assertEqual(self.quote.call_count, 2)
        self.submit.assert_called_once()

    def test_upload_failure_can_resume_without_quote_or_claim(self):
        self.upload.side_effect = lux.LuxError("NETWORK", "synthetic upload timeout", retryable=True)
        self.advance()
        self.assert_unsubmitted()
        self.quote.assert_not_called()
        self.upload.side_effect = None
        self.advance()
        self.assertEqual(self.state()["operations"]["hero-model"]["state"], "running")
        self.quote.assert_called_once()
        self.submit.assert_called_once()

    def test_failed_preparation_still_bounds_new_work_per_step(self):
        state = self.state()
        state["operations"]["environment-model"]["state"] = "pending"
        core.write(self.fixture.run / "supplier-run.json", state)
        self.quote.side_effect = lux.LuxError("NETWORK", "synthetic timeout", retryable=True)
        with patch.object(suppliers, "invoke_adapter") as independent_adapter:
            self.advance()
        self.assert_unsubmitted()
        independent_adapter.assert_not_called()
        self.quote.assert_called_once()

    def test_quote_receipt_write_failure_is_not_a_post_and_can_resume(self):
        original_write = core.write
        def write(path, value):
            if Path(path).name.startswith("lux-quote-"):
                raise OSError("synthetic unavailable receipt storage")
            return original_write(path, value)
        with patch.object(core, "write", side_effect=write):
            self.advance()
        self.assert_unsubmitted()
        self.advance()
        self.assertEqual(self.state()["operations"]["hero-model"]["state"], "running")
        self.submit.assert_called_once()

    def test_over_budget_retains_quote_evidence_but_never_reserves_or_submits(self):
        self.quote_value["quote"]["estimatedCreditsTotal"] = 11
        self.advance()
        self.assert_unsubmitted()
        row = self.state()["operations"]["hero-model"]
        self.assertEqual(row["pre_submit_error"]["code"], "QUOTE_EXCEEDS_APPROVED_BUDGET")
        self.assertEqual(row["live_quote_receipt"]["estimated_credits"], "11")
        self.advance()
        self.assert_unsubmitted()

    def test_real_post_unknown_remains_unretryable_and_keeps_reservation(self):
        self.submit.side_effect = lux.LuxError("SUBMISSION_UNKNOWN", "synthetic unknown POST", unknown_submission=True)
        self.advance()
        state = self.state()
        self.assertEqual(state["operations"]["hero-model"]["state"], "unknown")
        self.assertIn("hero-model", state["reservations"])
        self.assertIn("live_quote_receipt", state["operations"]["hero-model"])
        self.advance()
        self.quote.assert_called_once()
        self.submit.assert_called_once()

    def test_control_dry_run_preserves_every_byte_then_normal_guard_commits(self):
        args = (self.fixture.project, self.fixture.portfolio, "hero", "image_to_3d", self.fixture.run, core.digest(self.operation))
        result = production_control.guard_submission(*args, dry_run=True)
        self.assertTrue(result["dry_run"])
        self.assertEqual(self.control.read_bytes(), self.control_before)
        production_control.guard_submission(*args)
        self.assertNotEqual(self.control.read_bytes(), self.control_before)

    def test_existing_control_rejection_stops_upload_and_quote(self):
        production_control.guard_submission(self.fixture.project, self.fixture.portfolio, "hero", "image_to_3d",
                                            self.fixture.run.parent / "other-run", "other-request")
        self.advance()
        self.upload.assert_not_called()
        self.quote.assert_not_called()
        self.submit.assert_not_called()
        self.assertNotIn("hero-model", self.state()["reservations"])

    def test_control_is_rechecked_after_quote_before_claiming(self):
        def quote(*args):
            production_control.guard_submission(self.fixture.project, self.fixture.portfolio, "hero", "image_to_3d",
                                                self.fixture.run.parent / "other-run", "other-request")
            return self.quote_value
        self.quote.side_effect = quote
        self.advance()
        self.quote.assert_called_once()
        self.submit.assert_not_called()
        self.assertNotIn("hero-model", self.state()["reservations"])

    def test_explicit_invoker_double_never_calls_real_lux_preparation(self):
        supplier_jobs.step(self.fixture.run, invoker=self.fixture.adapter, max_submissions=1)
        self.upload.assert_not_called()
        self.quote.assert_not_called()
        self.submit.assert_not_called()
        self.assertEqual(self.fixture.adapter.calls, [("hero-model", "submit"), ("hero-model", "status")])

    def test_forged_request_receipt_cannot_bypass_direct_invoke_quote(self):
        request = {"parameters": deepcopy(self.operation["parameters"]), "inputs": self.state()["inputs"]["hero-model"],
                   "output_dir": str(self.fixture.run / "outputs" / "hero-model"),
                   "_live_quote_receipt": {"quote_id": "quote_" + "b" * 32, "estimated_credits": "0"}}
        self.quote_value["quote"]["estimatedCreditsTotal"] = 11
        with self.assertRaisesRegex(lux.LuxError, "approved operation allows"):
            supplier_jobs._invoke(self.fixture.registry, self.operation, "submit", request, {}, self.fixture.project)
        self.quote.assert_called_once()
        self.submit.assert_not_called()


if __name__ == "__main__": unittest.main()
