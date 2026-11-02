"""Offline supplier portfolios; synthetic costs, no provider/network calls."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1] / "skills/greybox-to-multistyle-art"
sys.path.insert(0, str(ROOT / "runtime"))
from greybox.core import WorkflowError, digest
from greybox.suppliers import (estimate_from_rate_card, inventory, invoke_adapter, load_catalog, portfolio_digest,
                               registry_digest, validate_portfolio, validate_registry,
                               validate_selection)

from modeling_ref_fixtures import write_reference_package

NOW = "2026-10-20T12:00:00Z"


class SupplierTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="supplier-offline-")
        self.base = Path(self.temp.name)
        self.receipt = self.file("evidence.txt", "Synthetic offline connection, operation and user-decision fixture")
        verified = {"state": "verified", "checked_at": "2020-01-01T00:00:00Z", "expires_at": "2099-01-01T00:00:00Z", "evidence": self.receipt}
        self.adapter = self.base / "adapter with spaces.py"
        self.adapter.write_text("import json,sys\nr=json.load(sys.stdin)\nprint(json.dumps({'ok':True,'provider':r['provider'],'method':r['method'],'request':r['request'],'task_id':'offline-1'}))\n")
        self.registry = {"schema": 1, "kind": "supplier-registry", "providers": [
            {"id": "lux3d", "label": "Lux", "desired": True, "configured": True,
             "binding": {"kind": "builtin_lux"}, "operations": ["image_to_3d", "rig", "retarget"],
             "verification": {"discovery": copy.deepcopy(verified), "connection": copy.deepcopy(verified), "operations": {"image_to_3d": copy.deepcopy(verified)}, "native": {}}},
            {"id": "nebula-studio", "label": "User's additional supplier", "desired": True, "configured": True,
             "binding": {"kind": "command", "argv": [str(Path(sys.executable).resolve()), str(self.adapter)], "adapter_path": str(self.adapter), "sha256": hashlib.sha256(self.adapter.read_bytes()).hexdigest(), "reviewed_local": True},
             "operations": ["image_to_3d"], "verification": {"connection": copy.deepcopy(verified), "operations": {"image_to_3d": copy.deepcopy(verified)}}},
            {"id": "future-vendor", "label": "Not configured", "desired": True, "configured": False,
             "binding": {"kind": "catalog_only"}, "operations": [], "verification": {}}
        ]}
        reference = write_reference_package(self.base, ["gate"])
        package = json.loads((self.base / reference["path"]).read_text())
        image = package["assets"][0]["views"][0]["image"]
        self.portfolio = {"schema": 1, "kind": "supplier-portfolio", "registry_sha256": registry_digest(self.registry),
                          "required_assets": ["gate"], "required_operations": {"gate": ["image_to_3d"]},
                          "recommended_option": "quality", "recommendation_rationale": "Synthetic quality/budget comparison", "options": []}
        for option_id, version, credits in (("quality", "G1", 10), ("economy", "G1-Turbo", 4)):
            oid = option_id + "-gate"
            self.portfolio["options"].append({"id": option_id, "rationale": "Synthetic alternative",
                "assets": [{"asset_id": "gate", "route": "hybrid", "rationale": "Exact joints plus generated visible form", "operation_ids": [oid]}],
                "operations": [{"id": oid, "asset_id": "gate", "provider": "lux3d", "operation": "image_to_3d", "model_version": version,
                                "parameters": {"version": version, "faceCount": 30000, "image_path": 0}, "inputs": [image], "modeling_references": reference,
                                 "rationale": "Task-specific fixture", "depends_on": [],
                                "pricing": self.price(credits)}]})

    def tearDown(self):
        self.temp.cleanup()

    def file(self, name, text):
        path = self.base / name
        path.write_text(text)
        return {"path": name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

    def price(self, credits):
        source = dict(self.receipt, checked_at="2020-01-01T00:00:00Z")
        return {"kind": "firm_quote", "source": source, "quoted_at": "2020-01-01T00:00:00Z", "expires_at": "2099-01-01T00:00:00Z",
                "quantity": 2, "wallet": "lux-cn", "unit_credits": credits,
                "conversion": {"amount_paid": "5", "credits_received": "100", "currency": "USD", "basis": "Synthetic fixture SKU, not a real vendor price", "source": source},
                "cash_due": {"amount": "0", "currency": "USD", "basis": "Synthetic existing wallet"}}

    def selected(self):
        return {"schema": 1, "kind": "supplier-selection", "gate": "H3", "actor": "user", "decision": "approved",
                "portfolio_sha256": portfolio_digest(self.portfolio), "registry_sha256": registry_digest(self.registry),
                "selected_option": "quality", "source_ref": "test-human-message-1", "evidence": self.receipt, "decided_at": "2020-01-01T00:00:00Z", "allowed_fallbacks": []}

    def rate_card(self):
        return {"schema": 1, "kind": "supplier-rate-card", "id": "synthetic-v1", "provider": "nebula-studio", "wallet": "nebula-wallet",
                "source": dict(self.receipt, checked_at="2020-01-01T00:00:00Z"),
                "rates": [{"id": "synthetic-base", "operation": "image_to_3d", "model_version": "model-one",
                           "parameter_domains": {"faceCount": {"values": [30000, 60000]}, "texture": {"values": [False, True], "default": False}},
                           "nonbillable_parameters": ["img"], "base": {"unit_credits": "10"},
                           "addons": [{"id": "synthetic-texture", "when": {"texture": True}, "unit_credits": "2"}]}]}

    def validate(self, **kw):
        return validate_portfolio(self.portfolio, self.registry, self.base, NOW, **kw)

    def test_open_inventory_retains_all_desired_suppliers(self):
        report = inventory(self.registry, self.base, NOW)
        self.assertEqual([p["id"] for p in report["suppliers"]], ["lux3d", "nebula-studio", "future-vendor"])
        self.assertTrue(report["suppliers"][1]["execution_ready"])
        self.assertFalse(report["suppliers"][2]["execution_ready"])

    def test_standard_and_turbo_are_explicit_costed_alternatives(self):
        report = self.validate()
        self.assertEqual(report["recommended_option"], "quality")
        self.assertEqual(report["options"][0]["wallet_credits"], {"lux-cn": "20"})
        self.assertEqual(report["options"][0]["allocated_money"], {"USD": "1"})
        self.assertEqual(report["options"][1]["wallet_credits"], {"lux-cn": "8"})

    def test_no_conversion_is_unknown_not_free(self):
        del self.portfolio["options"][0]["operations"][0]["pricing"]["conversion"]
        report = self.validate()["options"][0]
        self.assertEqual(report["allocated_money"], {})
        self.assertEqual(report["money_conversion_missing"], ["quality-gate"])

    def test_readiness_renewal_does_not_erase_scope_approval(self):
        selection = self.selected()
        before = registry_digest(self.registry)
        self.registry["providers"][0]["verification"]["connection"]["checked_at"] = "2021-01-01T00:00:00Z"
        self.registry["providers"][0]["desired"] = False
        self.assertEqual(registry_digest(self.registry), before)
        self.assertTrue(validate_selection(selection, self.portfolio, self.registry, self.base, NOW)["ok"])

    def test_route_or_price_drift_invalidates_selection(self):
        selection = self.selected()
        self.portfolio["options"][0]["operations"][0]["parameters"]["faceCount"] = 40000
        with self.assertRaises(WorkflowError):
            validate_selection(selection, self.portfolio, self.registry, self.base, NOW)

    def test_binding_drift_invalidates_registry_binding(self):
        self.registry["providers"][0]["operations"].append("export")
        with self.assertRaises(WorkflowError):
            self.validate()

    def test_evidence_file_drift_is_not_verified(self):
        (self.base / "evidence.txt").write_text("changed")
        with self.assertRaises(WorkflowError):
            inventory(self.registry, self.base, NOW)

    def test_nested_credentials_rejected(self):
        self.registry["providers"][0]["binding"]["config"] = {"authorization": "do-not-print"}
        with self.assertRaises(WorkflowError) as caught:
            inventory(self.registry, self.base, NOW)
        self.assertNotIn("do-not-print", str(caught.exception))

    def test_standard_turbo_parameters_and_policy(self):
        for option_index, key in ((0, "enablePbr"), (1, "customSize")):
            original = copy.deepcopy(self.portfolio)
            self.portfolio["options"][option_index]["operations"][0]["parameters"][key] = True
            with self.assertRaises(WorkflowError):
                self.validate()
            self.portfolio = original
        self.portfolio["effective_policy"] = {"lux_allowed_versions": ["G1"]}
        with self.assertRaises(WorkflowError):
            self.validate()

    def test_incomplete_asset_or_character_chain_rejected(self):
        self.portfolio["required_operations"]["gate"].append("rig")
        with self.assertRaises(WorkflowError):
            self.validate()

    def test_required_assets_cannot_disappear_in_cheaper_option(self):
        self.portfolio["options"][1]["assets"] = []
        with self.assertRaises(WorkflowError):
            self.validate()

    def test_dependency_chain_cannot_skip_or_cycle(self):
        self.portfolio["options"][0]["operations"][0]["depends_on"] = ["quality-gate"]
        with self.assertRaises(WorkflowError):
            self.validate()

    def test_expired_quote_is_visible_and_blocks_execution(self):
        self.portfolio["options"][0]["operations"][0]["pricing"]["expires_at"] = "2022-01-01T00:00:00Z"
        self.assertEqual(self.validate()["options"][0]["expired_prices"], ["quality-gate"])
        with self.assertRaises(WorkflowError):
            self.validate(for_execution="quality")

    def test_first_use_requires_explicit_qualification_probe(self):
        self.registry["providers"][0]["verification"]["operations"] = {}
        self.assertEqual(self.validate()["options"][0]["blocked_operations"], ["quality-gate"])
        self.portfolio["options"][0]["operations"][0]["qualification_probe"] = True
        selection = self.selected()
        with self.assertRaises(WorkflowError):
            validate_selection(selection, self.portfolio, self.registry, self.base, NOW)
        selection["allow_qualification_probes"] = ["quality-gate"]
        self.assertTrue(validate_selection(selection, self.portfolio, self.registry, self.base, NOW)["ok"])
        self.assertEqual(inventory(self.registry, self.base, NOW)["suppliers"][0]["operations_verified"], [])

    def test_fallback_needs_exact_scoped_operations_and_wallet_cap(self):
        selection = self.selected()
        selection["allowed_fallbacks"] = [{"option_id": "economy", "operation_ids": ["economy-gate"], "wallet_caps": {"lux-cn": "8"}}]
        self.assertTrue(validate_selection(selection, self.portfolio, self.registry, self.base, NOW)["ok"])
        selection["allowed_fallbacks"][0]["wallet_caps"]["lux-cn"] = "7"
        with self.assertRaises(WorkflowError):
            validate_selection(selection, self.portfolio, self.registry, self.base, NOW)

    def test_wallet_ids_cannot_cross_supplier_accounts(self):
        op = self.portfolio["options"][1]["operations"][0]
        op["provider"], op["model_version"] = "nebula-studio", "model-one"
        with self.assertRaises(WorkflowError):
            self.validate()
        op["pricing"]["wallet"] = "nebula-wallet"
        self.assertEqual(self.validate()["options"][1]["wallet_credits"], {"nebula-wallet": "8"})

    def test_adapter_quote_is_explicit_no_shell_invocation(self):
        response = invoke_adapter(self.registry, "nebula-studio", "quote", {"model": "v1"}, base=self.base)
        self.assertTrue(response["ok"])
        self.assertEqual(response["request"], {"model": "v1"})

    def test_adapter_submit_requires_bound_selection_and_exact_parameters(self):
        for option in self.portfolio["options"]:
            op = option["operations"][0]
            op["provider"], op["model_version"], op["pricing"]["wallet"] = "nebula-studio", "model-one", "nebula-wallet"
        op = self.portfolio["options"][0]["operations"][0]
        request = {key: op[key] for key in ("operation", "model_version", "parameters")}
        request["inputs"] = [{"path": str(self.base / row["path"]), "sha256": row["sha256"]} for row in op["inputs"]]
        with self.assertRaises(WorkflowError):
            invoke_adapter(self.registry, "nebula-studio", "submit", request, base=self.base)
        authorization = {"selection": self.selected(), "portfolio": self.portfolio, "operation_id": op["id"]}
        self.assertEqual(invoke_adapter(self.registry, "nebula-studio", "submit", request, base=self.base, authorization=authorization)["task_id"], "offline-1")
        request["parameters"] = {"version": "changed"}
        with self.assertRaises(WorkflowError):
            invoke_adapter(self.registry, "nebula-studio", "submit", request, base=self.base, authorization=authorization)

    def test_adapter_changes_require_review_again(self):
        self.adapter.write_text("raise Exception('changed')")
        with self.assertRaises(WorkflowError):
            invoke_adapter(self.registry, "nebula-studio", "capabilities", {}, base=self.base)

    def test_original_fetch_recovers_after_price_and_readiness_expiry(self):
        for option in self.portfolio["options"]:
            op = option["operations"][0]
            op["provider"], op["model_version"], op["pricing"]["wallet"] = "nebula-studio", "model-one", "nebula-wallet"
            op["pricing"]["expires_at"] = "2022-01-01T00:00:00Z"
        self.registry["providers"][1]["verification"]["operations"]["image_to_3d"]["expires_at"] = "2022-01-01T00:00:00Z"
        authorization = {"selection": self.selected(), "portfolio": self.portfolio, "operation_id": "quality-gate"}
        request = {"task_id": "already-submitted", "output_dir": str(self.base / "output")}
        self.assertTrue(invoke_adapter(self.registry, "nebula-studio", "fetch", request, base=self.base, authorization=authorization)["ok"])
        operation = self.portfolio["options"][0]["operations"][0]
        with self.assertRaises(WorkflowError):
            invoke_adapter(self.registry, "nebula-studio", "submit", {k: operation[k] for k in ("operation", "model_version", "parameters")}, base=self.base, authorization=authorization)

    def test_adapter_failures_do_not_expose_raw_output(self):
        self.adapter.write_text("import sys\nprint('SECRET_IN_PROVIDER_BODY')\nsys.exit(1)\n")
        self.registry["providers"][1]["binding"]["sha256"] = hashlib.sha256(self.adapter.read_bytes()).hexdigest()
        with self.assertRaises(WorkflowError) as caught:
            invoke_adapter(self.registry, "nebula-studio", "status", {"task_id": "existing"}, base=self.base)
        self.assertNotIn("SECRET_IN_PROVIDER_BODY", str(caught.exception))

    def test_catalog_is_descriptive_not_executable_or_closed_list(self):
        catalog = load_catalog()
        self.assertEqual({p["id"] for p in catalog["providers"]}, {"lux3d", "tripo", "meshy", "hitem3d", "rodin"})
        self.assertNotIn("binding", json.dumps(catalog))
        self.assertTrue(validate_registry(self.registry, self.base, NOW))

    def test_official_manual_calculator_prices_base_and_addon_without_api(self):
        card = self.rate_card()
        result = estimate_from_rate_card(card, "image_to_3d", "model-one", {"faceCount": 30000, "texture": True, "img": "reference"}, base=self.base, now=NOW)
        self.assertEqual(result["unit_credits"], "12")
        self.assertEqual(result["kind"], "rate_card_estimate")
        self.assertEqual(result["rate_card_audit"]["rule_ids"], ["synthetic-base", "synthetic-texture"])
        self.assertEqual(result["rate_card_audit"]["sha256"], digest(card))

    def test_manual_unknown_parameter_or_value_is_not_free(self):
        for parameters in ({"faceCount": 30000, "unpriced_addon": True}, {"faceCount": 90000}, {}):
            with self.assertRaises(WorkflowError):
                estimate_from_rate_card(self.rate_card(), "image_to_3d", "model-one", parameters, base=self.base, now=NOW)

    def test_ambiguous_manual_rates_require_resolution(self):
        card = self.rate_card()
        card["rates"].append(dict(copy.deepcopy(card["rates"][0]), id="overlapping-rate"))
        with self.assertRaises(WorkflowError):
            estimate_from_rate_card(card, "image_to_3d", "model-one", {"faceCount": 30000}, base=self.base, now=NOW)

    def test_manual_defaults_and_boolean_domain_are_exact(self):
        result = estimate_from_rate_card(self.rate_card(), "image_to_3d", "model-one", {"faceCount": 30000}, base=self.base, now=NOW)
        self.assertEqual(result["unit_credits"], "10")
        self.assertIs(result["rate_card_audit"]["effective_billing_parameters"]["texture"], False)
        with self.assertRaises(WorkflowError):
            estimate_from_rate_card(self.rate_card(), "image_to_3d", "model-one", {"faceCount": 30000, "texture": 1}, base=self.base, now=NOW)

    def test_manual_direct_currency_costs_are_supported(self):
        card = self.rate_card()
        rate = card["rates"][0]
        rate["base"] = {"direct_money": {"unit_amount": "0.20", "currency": "USD"}}
        rate["addons"][0]["direct_money"] = {"unit_amount": "0.05", "currency": "USD"}
        del rate["addons"][0]["unit_credits"]
        result = estimate_from_rate_card(card, "image_to_3d", "model-one", {"faceCount": 30000, "texture": True}, base=self.base, now=NOW)
        self.assertEqual(result["direct_money"], {"unit_amount": "0.25", "currency": "USD"})

    def test_manual_zero_requires_documented_reason(self):
        card = self.rate_card()
        card["rates"][0]["base"]["unit_credits"] = "0"
        with self.assertRaises(WorkflowError):
            estimate_from_rate_card(card, "image_to_3d", "model-one", {"faceCount": 30000}, base=self.base, now=NOW)
        card["rates"][0]["zero_cost_reason"] = "Synthetic no-charge operation fixture"
        self.assertEqual(estimate_from_rate_card(card, "image_to_3d", "model-one", {"faceCount": 30000}, base=self.base, now=NOW)["unit_credits"], "0")


if __name__ == "__main__":
    unittest.main()
