"""Offline quote-refresh authorization/accounting regressions; no service calls."""
from pathlib import Path
import copy
import shutil
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1] / "skills/greybox-to-multistyle-art"
sys.path.insert(0, str(ROOT / "runtime"))
from greybox import core
from workflow_fixtures import png


class QuoteInterrupted(RuntimeError):
    pass


class PollInterrupted(RuntimeError):
    """Stop after one persisted submission, before any subsequent asset submits."""


class NoEngine:
    def __getattr__(self, name):
        raise AssertionError("Offline quote test must not invoke engine: " + name)


class OfflineBridge:
    def __init__(self, run_dir):
        self.run_dir = run_dir
        self.prices = {"a": 10, "b": 10, "c": 10}
        self.include_details = True
        self.fail_next_quote = False
        self.quote_count = 0
        self.submissions = []
        self.pre_submit_rows = []

    def validate(self, operation, parameters):
        if operation != "image_to_3d" or parameters.get("version") != "G1":
            raise AssertionError("Unexpected offline generation parameters")

    def quote_items_for(self, operation, parameters, sequence):
        return {sequence: Path(parameters["img"]).stem}

    def upload(self, path, region):
        return {"url": "https://synthetic.invalid/" + Path(path).name}

    def quote(self, items, region):
        self.quote_count += 1
        if self.fail_next_quote:
            self.fail_next_quote = False
            raise QuoteInterrupted("injected quote failure; no provider was called")
        quote = {"quoteId": "offline-q-" + str(self.quote_count),
                 "estimatedCreditsTotal": sum(self.prices[aid] for aid in items.values())}
        if self.include_details:
            quote["details"] = {seq: self.prices[aid] for seq, aid in items.items()}
        return {"quote": quote}

    def submit(self, operation, parameters, region, quote_id=None):
        aid = Path(parameters["img"]).stem
        # Observe the journal at the POST boundary: current cost must already be frozen.
        self.pre_submit_rows.append(copy.deepcopy(core.read(self.run_dir / "run.json")["assets"][aid]))
        self.submissions.append({"asset": aid, "quote_id": quote_id, "price": self.prices[aid]})
        return {"taskId": "offline-task-" + aid}

    def status(self, task_id, region):
        raise PollInterrupted("injected polling interruption after persisted submission")

    def __getattr__(self, name):
        raise AssertionError("Unexpected provider operation in offline test: " + name)


class QuoteRecoveryR2Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="quote-r2-offline-")
        self.project = Path(self.temp.name) / "project"
        # Small source-only test_candidate fixture; no real project/assets copied.
        shutil.copytree(ROOT / "fixtures/godot-free", self.project)
        plan = core.read(self.project / "plan.json")
        plan["assets"] = []
        for aid, binding in zip(("a", "b", "c"), plan["bindings"]):
            image = self.project / (aid + ".png")
            image.write_bytes(png(ord(aid)))
            plan["assets"].append({"id": aid, "route": "generated", "reason": "OFFLINE accounting fixture",
                                   "generation": {"operation": "image_to_3d", "region": "cn",
                                                  "reference": {"path": str(image), "sha256": core.file_hash(image)},
                                                  "parameters": {"version": "G1", "faceCount": 30000}}})
            binding["source"] = {"asset_id": aid}
            binding.pop("styles", None)
        core.write(self.project / "plan.json", plan)
        self.run_dir = self.project / "art/experiments/quote-r2"
        core.prepare(self.project / "plan.json", self.project, self.run_dir)
        self.bridge = OfflineBridge(self.run_dir)

    def tearDown(self):
        self.temp.cleanup()

    def state(self):
        return core.read(self.run_dir / "run.json")

    def quote(self):
        return core.quote_run(self.run_dir, bridge=self.bridge)

    def authorize(self, allow=True):
        result = self.quote()
        core.approve(self.run_dir, "user", "Offline fixture: approve up to 30 credits for a/b/c",
                     quote_hash=result["quoteHash"], allow_quote_refresh=allow)
        return copy.deepcopy(self.state()["approval"])

    def submit_a(self):
        with self.assertRaises(PollInterrupted):
            core.run(self.run_dir, bridge=self.bridge, adapter=NoEngine())
        self.assertEqual([s["asset"] for s in self.bridge.submissions], ["a"])
        row = self.state()["assets"]["a"]
        self.assertEqual(row["state"], "submitted")
        self.assertEqual(row["taskId"], "offline-task-a")
        return row

    def refreshed_and_submitted(self):
        original = self.authorize()
        self.bridge.prices = {"a": 20, "b": 5, "c": 5}
        self.assertTrue(self.quote()["approvalRetained"])
        self.assertEqual(self.state()["approval"]["creditCeilings"], original["creditCeilings"])
        row = self.submit_a()
        self.assertEqual(row.get("submissionCredits"), 20)
        self.assertEqual(self.bridge.pre_submit_rows[0].get("submissionCredits"), 20)
        return original

    def test_refreshed_submitted_cost_cannot_expand_original_30_budget_to_40(self):
        self.refreshed_and_submitted()
        self.bridge.prices = {"a": 20, "b": 10, "c": 10}
        result = self.quote()
        self.assertEqual(result["quotes"][0]["assets"], ["b", "c"])
        self.assertEqual(result["quotes"][0]["estimatedCredits"], 20)
        self.assertFalse(result["approvalRetained"])
        self.assertIsNone(self.state()["approval"])
        with self.assertRaises(core.WorkflowError):
            core._check_approval(self.state())
        self.assertEqual(len(self.bridge.submissions), 1)

    def test_remaining_10_at_exact_original_ceiling_retains_authorization(self):
        original = self.refreshed_and_submitted()
        result = self.quote()
        self.assertTrue(result["approvalRetained"])
        self.assertEqual(result["quotes"][0]["estimatedCredits"], 10)
        self.assertEqual(self.state()["approval"]["creditCeilings"], {"cn": 30})
        self.assertEqual(self.state()["approval"]["evidence"], original["evidence"])
        core._check_approval(self.state())

    def test_historical_row_fallback_uses_actual_quoted_20_not_initial_asset_ceiling_10(self):
        self.refreshed_and_submitted()
        state = self.state()
        del state["assets"]["a"]["submissionCredits"]
        self.assertEqual(state["assets"]["a"]["quotedCredits"], 20)
        self.assertEqual(state["approval"]["assetCreditCeilings"]["a"], 10)
        core.save_run(self.run_dir, state)
        self.bridge.prices = {"a": 20, "b": 10, "c": 10}
        self.assertFalse(self.quote()["approvalRetained"])

    def test_missing_per_asset_submitted_cost_fails_closed_without_guessing(self):
        self.bridge.include_details = False
        self.authorize()
        row = self.submit_a()
        self.assertIsNone(row.get("submissionCredits"))
        self.assertIsNone(row.get("quotedCredits"))
        self.bridge.include_details = True
        self.bridge.prices = {"a": 10, "b": 5, "c": 5}
        self.assertFalse(self.quote()["approvalRetained"])
        self.assertIsNone(self.state()["approval"])

    def test_missing_submitted_row_cost_cannot_fall_back_to_old_approval_allocation(self):
        self.refreshed_and_submitted()
        state = self.state()
        state["assets"]["a"].pop("submissionCredits", None)
        state["assets"]["a"].pop("quotedCredits", None)
        self.assertEqual(state["approval"]["assetCreditCeilings"]["a"], 10)
        core.save_run(self.run_dir, state)
        self.assertFalse(self.quote()["approvalRetained"])

    def test_interrupted_refresh_blocks_submission_then_recovers_explicit_scope_authority(self):
        original = self.authorize()
        self.bridge.fail_next_quote = True
        with self.assertRaises(QuoteInterrupted):
            self.quote()
        interrupted = self.state()
        self.assertIsNone(interrupted["approval"])
        self.assertIsNone(interrupted["quoteHash"])
        self.assertEqual(interrupted["state"], "quoting")
        self.assertTrue(interrupted.get("pendingQuoteRefreshAuthorization", {}).get("allowQuoteRefresh"))
        with self.assertRaises(core.WorkflowError):
            core.run(self.run_dir, bridge=self.bridge, adapter=NoEngine())
        self.assertEqual(self.bridge.submissions, [])
        result = self.quote()
        self.assertTrue(result["approvalRetained"])
        current = self.state()["approval"]
        for key in ("actor", "evidence", "planHash", "policyHash", "scopeHash", "creditCeilings"):
            self.assertEqual(current[key], original[key], key)
        self.assertEqual(current["quoteHash"], result["quoteHash"])
        core._check_approval(self.state())
        self.assertEqual(self.bridge.submissions, [])

    def test_interrupted_refresh_without_opt_in_never_recovers_from_history(self):
        self.authorize(allow=False)
        self.bridge.fail_next_quote = True
        with self.assertRaises(QuoteInterrupted):
            self.quote()
        self.assertTrue(self.state().get("approvalHistory"))
        result = self.quote()
        self.assertFalse(result["approvalRetained"])
        self.assertIsNone(self.state()["approval"])
        with self.assertRaises(core.WorkflowError):
            core.run(self.run_dir, bridge=self.bridge, adapter=NoEngine())
        self.assertEqual(self.bridge.submissions, [])

    def test_historical_opt_in_cannot_override_newer_non_refresh_authorization(self):
        self.authorize(allow=True)
        # A fresh actual user decision supersedes the older refresh permission.
        result = self.quote()
        core.approve(self.run_dir, "user", "Offline fixture: this quote only; no refresh permission",
                     quote_hash=result["quoteHash"], allow_quote_refresh=False)
        self.bridge.fail_next_quote = True
        with self.assertRaises(QuoteInterrupted):
            self.quote()
        self.assertTrue(any(a.get("allowQuoteRefresh") for a in self.state()["approvalHistory"]))
        self.assertFalse(self.quote()["approvalRetained"])
        self.assertIsNone(self.state()["approval"])


if __name__ == "__main__":
    unittest.main()
