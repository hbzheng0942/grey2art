"""Forward tests of persisted two-supplier jobs; all decisions/output are synthetic.

No external provider or engine is called. The invoker double inspects on-disk
reservation state at the command boundary and returns tiny non-model artifacts.
"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import struct
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1] / "skills/greybox-to-multistyle-art"
sys.path.insert(0, str(ROOT / "runtime"))
from greybox import core, supplier_jobs, suppliers, workflow
from greybox.overview import generate_overview
from workflow_fixtures import approve, capabilities, make_workflow, png, refresh_evidence
from modeling_ref_fixtures import write_reference_package


def synthetic_glb():
    """Tiny, valid untextured triangle; fixtures never establish art acceptance."""
    positions = struct.pack("<9f", 0, 0, 0, 1, 0, 0, 0, 1, 0)
    data = json.dumps({"asset": {"version": "2.0"}, "buffers": [{"byteLength": len(positions)}],
        "bufferViews": [{"buffer": 0, "byteLength": len(positions)}],
        "accessors": [{"bufferView": 0, "componentType": 5126, "count": 3, "type": "VEC3", "min": [0, 0, 0], "max": [1, 1, 0]}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}],
        "nodes": [{"mesh": 0}], "scenes": [{"nodes": [0]}], "scene": 0}).encode()
    data += b" " * (-len(data) % 4)
    return b"glTF" + struct.pack("<IIII", 2, 28 + len(data) + len(positions), len(data), 0x4E4F534A) + data + struct.pack("<II", len(positions), 0x004E4942) + positions


class OfflineAdapter:
    def __init__(self, testcase):
        self.test = testcase
        self.calls = []
        self.done = set()
        self.ambiguous = set()
        self.fail_fetch = set()
        self.overcharge = {}

    def __call__(self, registry, operation, method, request, authorization, project):
        oid = operation["id"]
        self.calls.append((oid, method))
        if method == "submit":
            state = core.read(self.test.run / "supplier-run.json")
            self.test.assertEqual(state["operations"][oid]["state"], "submitting")
            self.test.assertIn(oid, state["reservations"])
            self.test.assertEqual(state["reservations"][oid]["operation_digest"], core.digest(operation))
            if oid in self.ambiguous:
                raise TimeoutError("Synthetic timeout after provider may have accepted request")
            response = {"ok": True, "task_id": "original-" + oid}
            if oid in self.overcharge:
                response["consumed_credits"] = self.overcharge[oid]
            return response
        self.test.assertEqual(request["task_id"], "original-" + oid)
        if method == "status":
            return {"ok": True, "state": "succeeded" if oid in self.done else "running"}
        if oid in self.fail_fetch:
            raise OSError("Synthetic interrupted download")
        output = Path(request["output_dir"])
        output.mkdir(parents=True, exist_ok=True)
        artifact = output / "synthetic-triangle.glb"
        artifact.write_bytes(synthetic_glb())
        return {"ok": True, "artifacts": [{"path": str(artifact), "role": "model"}]}


class SupplierJobTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="supplier-jobs-offline-")
        self.project = Path(self.temp.name)
        self.run = self.project / "art/supplier-case/shared/production/runs/supplier-test"
        self.receipt = self.file("SYNTHETIC.txt", "Offline fixture: no actual user authorization or provider result")
        adapter = self.project / "explicit-reviewed-adapter.py"
        adapter.write_text("# Synthetic reviewed source; invoker boundary patched in tests\n")
        binding = {"kind": "command", "argv": [str(Path(sys.executable).resolve()), str(adapter)],
                   "adapter_path": str(adapter), "sha256": core.file_hash(adapter), "reviewed_local": True}
        verify = {"state": "verified", "checked_at": "2020-01-01T00:00:00Z",
                  "expires_at": "2099-01-01T00:00:00Z", "evidence": self.receipt}
        self.registry = {"schema": 1, "kind": "supplier-registry", "providers": []}
        for pid, ops in (("character-vendor", ["image_to_3d", "rig"]), ("environment-vendor", ["image_to_3d"])):
            self.registry["providers"].append({"id": pid, "label": pid, "configured": True, "desired": True,
                "binding": deepcopy(binding), "operations": ops,
                "verification": {"connection": deepcopy(verify),
                                 "operations": {op: deepcopy(verify) for op in ops}}})
        self.modeling_references = {}
        self.reference_images = {}
        for style, asset in (("ceramic", "hero"), ("orbital", "environment")):
            reference = write_reference_package(self.project, [asset], style_id=style,
                selected_concept_sha256=hashlib.sha256(png(1 if style == "ceramic" else 2)).hexdigest())
            package = core.read(self.project / reference["path"])
            self.modeling_references[asset] = reference
            self.reference_images[asset] = package["assets"][0]["views"][0]["image"]
        reference = self.reference_images["hero"]
        self.portfolio = {"schema": 1, "kind": "supplier-portfolio", "registry_sha256": suppliers.registry_digest(self.registry),
            "selected_styles": ["ceramic", "orbital"], "required_assets": ["hero", "environment"],
            "workspace": {"schema": 1, "case_id": "supplier-case", "root": "art/supplier-case", "engine": "godot",
                "shared_asset_ids": [], "asset_owners": {"hero": {"scope": "style", "style_id": "ceramic"},
                    "environment": {"scope": "style", "style_id": "orbital"}}},
            "required_operations": {"hero": ["image_to_3d", "rig"], "environment": ["image_to_3d"]},
            "recommended_option": "balanced", "recommendation_rationale": "Synthetic accepted-cost combination",
            "options": [{"id": "balanced", "rationale": "Synthetic two-wallet combination",
                "assets": [{"asset_id": "hero", "route": "generated", "rationale": "Visible deforming character",
                            "operation_ids": ["hero-model", "hero-rig"]},
                           {"asset_id": "environment", "route": "hybrid", "rationale": "Visible shell with exact joints",
                            "operation_ids": ["environment-model"]}],
                "operations": [self.operation("hero-model", "hero", "character-vendor", "image_to_3d", 10, inputs=[reference]),
                               self.operation("environment-model", "environment", "environment-vendor", "image_to_3d", 20),
                               self.operation("hero-rig", "hero", "character-vendor", "rig", 5, depends=["hero-model"])]}]}
        self.overview = generate_overview({"schema": 1, "kind": "workflow-overview-intake", "id": "synthetic-supplier-brief",
            "goals": ["Synthetic two-style producer forward test"],
            "input": {"mode": "playable", "format": "godot", "baseline_verified": False},
            "target_engine": "godot", "character": {"presence": "none"}})
        overview_path = self.project / "overview.json"
        core.write(overview_path, self.overview)
        self.portfolio["overview"] = {"path": str(overview_path), "sha256": core.file_hash(overview_path)}
        self.selection = {"schema": 1, "kind": "supplier-selection", "gate": "H3", "actor": "user", "decision": "approved",
            "portfolio_sha256": suppliers.portfolio_digest(self.portfolio), "registry_sha256": suppliers.registry_digest(self.registry),
            "selected_option": "balanced", "source_ref": "synthetic://test-only-user-message", "evidence": self.receipt,
            "decided_at": "2020-01-01T00:00:00Z", "allowed_fallbacks": []}
        plan = core.read(ROOT / "fixtures/godot-free/plan.json")
        (self.project / "project.godot").write_text('; SYNTHETIC OFFLINE native-evidence fixture only\nconfig_version=5\n')
        baseline = core.resolve_input(plan["contract"]["scene"], self.project)
        baseline.parent.mkdir(parents=True, exist_ok=True)
        baseline.write_text('[gd_scene format=3]\n[node name="SyntheticBaseline" type="Node3D"]\n')
        self.checkpoint, self.checkpoint_data = make_workflow(self.project, plan)
        for stage in self.checkpoint_data["stages"]:
            if stage["id"] == "production_plan":
                item = next(e for e in stage["evidence"] if e["role"] == "production_table")
                table = core.read(item["path"])
                asset_id = "hero" if stage["scope"] == "ceramic" else "environment"
                entry = next(a for a in self.portfolio["options"][0]["assets"] if a["asset_id"] == asset_id)
                proposal = {"asset_id": asset_id, "route": entry["route"], "reason": "SYNTHETIC actual portfolio source",
                    "generation": {"operation": "image_to_3d"}}
                if entry["route"] == "hybrid":
                    proposal.update(generated_visual_role="SYNTHETIC visible shell", controlled_structure_role="SYNTHETIC precise joints")
                table["asset_proposals"] = [proposal]
                proposal['route_evaluation'] = {route: 'SYNTHETIC considered ' + route for route in ('generated', 'reuse', 'procedural')}
                for feature in table["visual_features"]:
                    feature["asset_ids"] = [asset_id]
                recipe_item = next(e for e in stage["evidence"] if e["role"] == "assembly_recipe")
                recipe = core.read(recipe_item["path"])
                unit = recipe["assemblies"][0]
                unit.update(id="assemble-" + asset_id, asset_ids=[asset_id])
                recipe["assemblies"] = [unit]
                refresh_evidence(stage, "assembly_recipe", recipe)
                table["composition_owners"] = {layer: [unit["id"]] for layer in workflow.COMPOSITION_LAYERS}
                visual_item = next(e for e in stage["evidence"] if e["role"] == "visual_package")
                visual = core.read(visual_item["path"])
                visual["bom"] = [{**visual["bom"][0], "asset_id": asset_id, "reference_status": "production_ready"}]
                visual["assembly_annotations"] = [{**visual["assembly_annotations"][0], "assembly_id": unit["id"], "asset_ids": [asset_id]}]
                refresh_evidence(stage, "visual_package", visual)
                table["supplier_portfolio_digest"] = suppliers.portfolio_digest(self.portfolio)
                table["modeling_references"] = self.modeling_references["hero" if stage["scope"] == "ceramic" else "environment"]
                core.write(item["path"], table)
                item["sha256"] = core.file_hash(item["path"])
                approve(stage)
        self.checkpoint_data["production_policy"] = workflow.PRODUCTION_POLICY
        core.write(self.checkpoint, self.checkpoint_data)
        self.capabilities = capabilities()
        self.adapter = OfflineAdapter(self)
        from production_control_fixtures import fixture_control
        fixture_control(self.project, self.portfolio, self.checkpoint, legacy_multistyle=True)

    def tearDown(self):
        self.temp.cleanup()

    def file(self, name, content):
        path = self.project / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return {"path": str(path), "sha256": core.file_hash(path)}

    def operation(self, oid, asset, provider, operation, credits, depends=None, inputs=None):
        source = dict(self.receipt, checked_at="2020-01-01T00:00:00Z")
        parameters = {"quality": "declared"}
        if operation == "image_to_3d":
            parameters["image_path"] = 0
            inputs = [self.reference_images[asset]]
        return {"id": oid, "asset_id": asset, "provider": provider, "operation": operation,
                "model_version": "synthetic-v2", "parameters": parameters,
                "modeling_references": self.modeling_references.get(asset) if operation == "image_to_3d" else None,
                "rationale": "Synthetic task choice", "depends_on": depends or [], "inputs": inputs or [],
                "publish": {"path": "art/supplier-case/styles/" + ("ceramic" if asset == "hero" else "orbital") + "/assets/" + asset + "/" + oid + ".glb"},
                "pricing": {"kind": "firm_quote", "source": source, "quoted_at": "2020-01-01T00:00:00Z",
                            "expires_at": "2030-01-01T00:00:00Z", "quantity": 1,
                            "wallet": provider + "-wallet", "unit_credits": credits}}

    def prepare(self):
        return supplier_jobs.prepare(self.project, self.run, self.registry, self.portfolio, self.selection,
                                     self.checkpoint, self.capabilities, "test-session")

    def advance(self, **kwargs):
        return supplier_jobs.step(self.run, invoker=self.adapter, **kwargs)

    def rebind_portfolio(self):
        self.selection["portfolio_sha256"] = suppliers.portfolio_digest(self.portfolio)
        for stage in self.checkpoint_data["stages"]:
            if stage["id"] == "production_plan":
                item = next(e for e in stage["evidence"] if e["role"] == "production_table")
                table = core.read(item["path"])
                table["supplier_portfolio_digest"] = suppliers.portfolio_digest(self.portfolio)
                table["modeling_references"] = self.modeling_references["hero" if stage["scope"] == "ceramic" else "environment"]
                core.write(item["path"], table)
                item["sha256"] = core.file_hash(item["path"])
                approve(stage)
        core.write(self.checkpoint, self.checkpoint_data)

    def test_paid_asset_missing_from_owning_style_bom_cannot_prepare(self):
        self.modeling_references["hidden"] = write_reference_package(self.project, ["hidden"], style_id="ceramic-hidden",
            selected_concept_sha256=hashlib.sha256(png(1)).hexdigest())
        package_path = core.resolve_input(self.modeling_references["hidden"]["path"], self.project)
        package = core.read(package_path)
        package["style_id"] = "ceramic"
        core.write(package_path, package)
        self.modeling_references["hidden"]["sha256"] = core.file_hash(package_path)
        self.reference_images["hidden"] = package["assets"][0]["views"][0]["image"]
        option = self.portfolio["options"][0]
        operation = self.operation("hidden-model", "hidden", "character-vendor", "image_to_3d", 10)
        operation["publish"]["path"] = "art/supplier-case/styles/ceramic/assets/hidden/hidden-model.glb"
        option["operations"].append(operation)
        option["assets"].append({"asset_id": "hidden", "route": "generated", "rationale": "SYNTHETIC missing visible source", "operation_ids": ["hidden-model"]})
        self.portfolio["required_assets"].append("hidden")
        self.portfolio["required_operations"]["hidden"] = ["image_to_3d"]
        self.portfolio["workspace"]["asset_owners"]["hidden"] = {"scope": "style", "style_id": "ceramic"}
        self.rebind_portfolio()
        with self.assertRaisesRegex(core.WorkflowError, "visual BOM omits supplier asset.*ceramic/hidden"):
            self.prepare()
        self.assertFalse((self.run / "supplier-run.json").exists())
        self.assertEqual(self.adapter.calls, [])

    def test_selected_supplier_route_cannot_silently_change_bom_responsibility(self):
        self.portfolio["options"][0]["assets"][0]["route"] = "hybrid"
        self.rebind_portfolio()
        with self.assertRaisesRegex(core.WorkflowError, "visual route differs from H3 BOM"):
            self.prepare()
        self.assertFalse((self.run / "supplier-run.json").exists())

    def test_selected_generation_mode_must_match_its_h3_asset_proposal(self):
        stage = next(s for s in self.checkpoint_data["stages"] if s["id"] == "production_plan" and s["scope"] == "ceramic")
        item = next(e for e in stage["evidence"] if e["role"] == "production_table")
        table = core.read(item["path"])
        table["asset_proposals"][0]["generation"]["operation"] = "multiview_to_3d"
        refresh_evidence(stage, "production_table", table)
        approve(stage); core.write(self.checkpoint, self.checkpoint_data)
        with self.assertRaisesRegex(core.WorkflowError, "mesh operation differs from H3"):
            self.prepare()

    def test_shared_source_must_be_reviewed_in_each_owning_style_bom(self):
        self.portfolio["workspace"]["asset_owners"]["hero"] = {"scope": "shared"}
        self.portfolio["workspace"]["shared_asset_ids"] = ["hero"]
        for op in self.portfolio["options"][0]["operations"]:
            if op["asset_id"] == "hero":
                op["publish"]["path"] = "art/supplier-case/shared/assets/hero/" + op["id"] + ".glb"
        self.rebind_portfolio()
        with self.assertRaisesRegex(core.WorkflowError, "visual BOM omits supplier asset.*orbital/hero"):
            self.prepare()

    def test_authorized_fallback_route_requires_explicit_bom_mapping(self):
        alternate = deepcopy(self.portfolio["options"][0])
        alternate["id"] = "alternate"
        alternate["assets"][0]["route"] = "hybrid"
        self.portfolio["options"].append(alternate)
        self.selection["allowed_fallbacks"] = [{"option_id": "alternate", "wallet_caps": {
            "character-vendor-wallet": 15, "environment-vendor-wallet": 20}, "operation_ids": ["hero-model"]}]
        self.rebind_portfolio()
        with self.assertRaisesRegex(core.WorkflowError, "visual route differs from H3 BOM"):
            self.prepare()
        stage = next(s for s in self.checkpoint_data["stages"] if s["id"] == "production_plan" and s["scope"] == "ceramic")
        item = next(e for e in stage["evidence"] if e["role"] == "production_table")
        table = core.read(item["path"])
        table["asset_proposals"][0]["fallback_routes"] = {"alternate": "hybrid"}
        refresh_evidence(stage, "production_table", table)
        approve(stage); core.write(self.checkpoint, self.checkpoint_data)
        self.assertTrue(self.prepare()["ok"])

    def test_required_character_function_cannot_disappear_at_supplier_prepare(self):
        value = deepcopy(self.overview["intake"])
        value["character"] = {"presence": "required", "source": "new", "deformation": "required",
                              "rig": "new", "animation": "none", "retarget": "none"}
        self.overview = generate_overview(value)
        overview_path = Path(self.portfolio["overview"]["path"])
        core.write(overview_path, self.overview)
        self.portfolio["overview"]["sha256"] = core.file_hash(overview_path)
        self.portfolio["character_assets"] = ["hero"]
        for option in self.portfolio["options"]:
            option["character_work"] = [{"asset_id": "hero", "node_id": node["id"], "route": "manual",
                "capabilities": node["required_tools"],
                "handoff": {"owner": "artist", "action": "Synthetic work", "resume_requirement": "Return actual source and checks"}}
                for node in self.overview["character_graph"]["nodes"] if node["id"] != "character_rig"]
        self.rebind_portfolio()
        with self.assertRaisesRegex(core.WorkflowError, "omits required character function"):
            self.prepare()
        self.assertFalse((self.run / "supplier-run.json").exists())

    def test_submit_reservation_is_persisted_before_any_command(self):
        self.prepare()
        result = self.advance(max_submissions=1)
        self.assertEqual(result["operations"]["hero-model"]["task_id"], "original-hero-model")
        self.assertEqual(result["wallet_reservations"], {"character-vendor-wallet": "10"})
        self.assertEqual(self.adapter.calls, [("hero-model", "submit"), ("hero-model", "status")])

    def test_document_estimate_does_not_require_a_quote_query(self):
        for operation in self.portfolio['options'][0]['operations']:
            operation['pricing']['kind'] = 'rate_card_estimate'
            operation['pricing'].pop('expires_at')
        self.rebind_portfolio()
        self.prepare()
        result = self.advance()
        self.assertEqual(result['operations']['hero-model']['state'], 'running')
        self.assertFalse(any(method == 'quote' for _, method in self.adapter.calls))

    def _lux_estimate_fixture(self):
        operation = {'id': 'prop', 'asset_id': 'hero', 'provider': 'lux3d', 'region': 'cn', 'operation': 'image_to_3d',
            'model_version': 'G1', 'parameters': {'version': 'G1', 'faceCount': 30000, 'image_path': 0},
            'inputs': [self.reference_images['hero']], 'modeling_references': self.modeling_references['hero'],
            'pricing': {'kind': 'rate_card_estimate', 'unit_credits': '2', 'quantity': 2}}
        registry = {'providers': [{'id': 'lux3d', 'binding': {'kind': 'builtin_lux'}}]}
        request = {'parameters': operation['parameters'], 'inputs': supplier_jobs._inputs(operation, self.project),
                   'output_dir': str(self.run / 'outputs' / 'prop')}
        quote = {'ok': True, 'region': 'cn', 'quote': {'quoteId': 'quote_' + 'a' * 32, 'estimatedCreditsTotal': 4}}
        return operation, registry, request, quote

    def test_builtin_lux_checks_live_quote_and_saves_private_receipt_before_submit(self):
        operation, registry, request, quote = self._lux_estimate_fixture()
        operation['pricing']['quote_id'] = 'quote_' + 'b' * 32  # Must not reuse a historical quote.
        def submit_checked(name, parameters, region, quote_id):
            reference = request['_live_quote_receipt']
            receipt_path = Path(reference['path'])
            self.assertEqual(receipt_path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(reference['sha256'], core.file_hash(receipt_path))
            receipt = core.read(receipt_path)
            self.assertEqual(receipt['parameters']['img'], 'https://synthetic.invalid/private-ref.png')
            self.assertNotIn('image_path', receipt['parameters'])
            self.assertEqual(receipt['approved_credit_ceiling'], '4')
            self.assertEqual(quote_id, quote['quote']['quoteId'])
            return {'ok': True, 'taskId': 42}
        with patch('greybox.lux.upload', return_value={'url': 'https://synthetic.invalid/private-ref.png'}), \
             patch('greybox.lux.quote_items_for', return_value={'1': {'synthetic': True}}) as items, \
             patch('greybox.lux.quote', return_value=quote) as quote_call, \
             patch('greybox.lux.submit', side_effect=submit_checked):
            result = supplier_jobs._invoke(registry, operation, 'submit', request, {}, self.project)
        self.assertEqual(result['task_id'], '42')
        self.assertEqual(items.call_args.args[1]['img'], 'https://synthetic.invalid/private-ref.png')
        quote_call.assert_called_once_with({'1': {'synthetic': True}}, 'cn')
        self.assertNotIn('private-ref', json.dumps(result))
        self.assertNotIn('actual_credits', result)

    def test_builtin_lux_quote_failures_and_overruns_are_definitely_unsubmitted(self):
        from greybox.lux import LuxError
        for failure in ('overrun', 'query', 'invalid', 'write'):
            with self.subTest(failure=failure):
                operation, registry, request, quote = self._lux_estimate_fixture()
                if failure == 'overrun': quote['quote']['estimatedCreditsTotal'] = 5
                if failure == 'invalid': quote['quote']['estimatedCreditsTotal'] = float('nan')
                with patch('greybox.lux.upload', return_value={'url': 'https://synthetic.invalid/ref.png'}), \
                     patch('greybox.lux.quote_items_for', return_value={'1': {}}), \
                     patch('greybox.lux.quote', side_effect=LuxError('UPSTREAM', 'synthetic quote failed', unknown_submission=True) if failure == 'query' else None, return_value=quote), \
                     patch('greybox.lux.submit') as submit:
                    if failure == 'write':
                        with patch('greybox.supplier_jobs.core.write', side_effect=OSError('synthetic disk failure')), self.assertRaises(LuxError) as error:
                            supplier_jobs._invoke(registry, operation, 'submit', request, {}, self.project)
                    else:
                        with self.assertRaises(LuxError) as error:
                            supplier_jobs._invoke(registry, operation, 'submit', request, {}, self.project)
                self.assertFalse(error.exception.unknown_submission)
                submit.assert_not_called()
                if failure == 'overrun':
                    self.assertEqual(error.exception.code, 'QUOTE_EXCEEDS_APPROVED_BUDGET')
                    self.assertTrue(Path(request['_live_quote_receipt']['path']).is_file())
                    self.assertIn('approved operation allows 4', str(error.exception))

    def test_builtin_lux_unknown_generation_keeps_quote_and_unknown_boundary(self):
        from greybox.lux import LuxError
        operation, registry, request, quote = self._lux_estimate_fixture()
        with patch('greybox.lux.upload', return_value={'url': 'https://synthetic.invalid/ref.png'}), \
             patch('greybox.lux.quote_items_for', return_value={'1': {}}), \
             patch('greybox.lux.quote', return_value=quote), \
             patch('greybox.lux.submit', side_effect=LuxError('SUBMISSION_UNKNOWN', 'synthetic uncertain POST', unknown_submission=True)), \
             self.assertRaises(LuxError) as error:
            supplier_jobs._invoke(registry, operation, 'submit', request, {}, self.project)
        self.assertTrue(error.exception.unknown_submission)
        self.assertTrue(Path(request['_live_quote_receipt']['path']).is_file())

    def test_cash_reservation_and_overrun_persist_across_steps(self):
        price = self.portfolio['options'][0]['operations'][0]['pricing']
        price['unit_credits'] = 0
        price['direct_money'] = {'unit_amount': '0.50', 'currency': 'USD'}
        self.rebind_portfolio()
        self.prepare()
        def invoke(*args):
            response = self.adapter(*args)
            if args[2] == 'submit':
                response['consumed_money'] = {'amount': '0.75', 'currency': 'USD'}
            return response
        first = supplier_jobs.step(self.run, invoker=invoke, max_submissions=3)
        self.assertEqual(first['money_reservations'], {'USD': '0.50'})
        self.assertEqual(first['cost_overrun'], 'hero-model')
        supplier_jobs.step(self.run, invoker=invoke, max_submissions=3)
        self.assertNotIn(('environment-model', 'submit'), self.adapter.calls)

    def test_independent_environment_does_not_wait_for_hero_rig(self):
        self.prepare()
        self.adapter.done.add("environment-model")
        result = self.advance(max_submissions=2)
        self.assertEqual(result["operations"]["hero-model"]["state"], "running")
        self.assertEqual(result["operations"]["environment-model"]["state"], "ready")
        self.assertEqual(result["operations"]["hero-rig"]["state"], "pending")
        self.assertNotIn(("hero-rig", "submit"), self.adapter.calls)
        self.assertEqual(result["wallet_reservations"], {"character-vendor-wallet": "10", "environment-vendor-wallet": "20"})

    def test_hero_ready_then_rig_uses_recorded_parent_artifact(self):
        from greybox import characters
        operation = next(op for op in self.portfolio["options"][0]["operations"] if op["id"] == "hero-rig")
        operation["parameters"] = {"model_from": "hero-model"}
        self.rebind_portfolio()
        self.prepare()
        self.adapter.done.update({"hero-model", "environment-model", "hero-rig"})
        result = self.advance(max_submissions=3)
        row = result["operations"]["hero-model"]
        self.assertEqual(row["state"], "ready")
        self.assertEqual(result["operations"]["environment-model"]["state"], "ready")
        self.assertTrue(row["artifacts"])
        self.assertEqual(row["artifacts"][0]["sha256"], core.file_hash(row["artifacts"][0]["path"]))
        self.assertEqual(result["operations"]["hero-rig"]["state"], "pending")
        self.assertIn("completed GLB review", result["operations"]["hero-rig"]["operational_blocker"])
        self.assertNotIn(("hero-rig", "submit"), self.adapter.calls)
        self.assertEqual(result["wallet_reservations"], {"character-vendor-wallet": "10", "environment-vendor-wallet": "20"})

        # Bind actual fixture bytes; these tiny images and observations are not an art/pose acceptance claim.
        directory = self.run / "character-preflight"
        report = directory / "hero-inspection.json"
        characters.write_inspection(row["artifacts"][0]["path"], report)
        receipt = characters.make_template(report)
        receipt.update(category="humanoid", use="rig", reviewer="synthetic-test-actor")
        receipt["pose"] = {"label": "A-like", "status": "pass", "observation": "Synthetic test observation only."}
        for i, view in enumerate(receipt["views"]):
            image = directory / (view["view"] + ".png")
            image.write_bytes(png(i))
            view.update(path=str(image), sha256=core.file_hash(image))
        for check in receipt["checks"]:
            check.update(status="pass", observation="Synthetic fixture only.", views=["front", "side"])
        receipt["submission_binding"] = {"source_sha256": row["artifacts"][0]["sha256"],
            "parameters_sha256": core.digest(operation["parameters"])}
        core.write(directory / "hero-rig.json", receipt)

        result = self.advance(max_submissions=1)
        self.assertEqual(result["state"], "assets_ready")
        self.assertEqual(self.adapter.calls.count(("hero-rig", "submit")), 1)
        self.assertEqual(result["wallet_reservations"], {"character-vendor-wallet": "15", "environment-vendor-wallet": "20"})

    def test_ambiguous_submit_counts_toward_step_submission_bound(self):
        self.prepare()
        self.adapter.ambiguous.add("hero-model")
        result = self.advance(max_submissions=1)
        self.assertEqual([oid for oid, method in self.adapter.calls if method == "submit"], ["hero-model"])
        self.assertEqual(result["operations"]["environment-model"]["state"], "pending")

    def test_unknown_submit_is_not_repeated_and_cannot_change_vendor(self):
        self.prepare()
        self.adapter.ambiguous.add("hero-model")
        first = self.advance(max_submissions=1)
        self.assertEqual(first["operations"]["hero-model"]["state"], "unknown")
        self.advance(max_submissions=1)
        self.assertEqual(self.adapter.calls.count(("hero-model", "submit")), 1)
        changed = deepcopy(self.registry)
        changed["providers"][0]["operations"].append("retarget")
        with self.assertRaises(core.WorkflowError):
            self.advance(registry_refresh=changed)
        state = core.read(self.run / "supplier-run.json")
        frozen = core.read(self.run / "supplier-portfolio.json")
        frozen["options"][0]["operations"][0]["provider"] = "environment-vendor"
        core.write(self.run / "supplier-portfolio.json", frozen)
        with self.assertRaises(core.WorkflowError):
            self.advance()
        self.assertEqual(self.adapter.calls.count(("hero-model", "submit")), 1)
        self.assertIn("hero-model", state["reservations"])

    def test_ambiguous_submit_reconciles_to_original_task_without_new_charge(self):
        self.prepare()
        self.adapter.ambiguous.add("hero-model")
        self.advance(max_submissions=1)
        supplier_jobs.reconcile(self.run, "hero-model", "original-hero-model", "Synthetic provider account inspection")
        self.adapter.done.add("hero-model")
        result = self.advance(max_submissions=1)
        self.assertEqual(result["operations"]["hero-model"]["state"], "ready")
        self.assertEqual(self.adapter.calls.count(("hero-model", "submit")), 1)

    def test_input_drift_blocks_new_submissions_but_recovers_existing(self):
        self.prepare()
        self.advance(max_submissions=1)
        core.resolve_input(self.reference_images["hero"]["path"], self.project).write_bytes(b"Changed approved image after H3")
        self.adapter.done.add("hero-model")
        result = self.advance(max_submissions=3)
        self.assertEqual(result["operations"]["hero-model"]["state"], "ready")
        self.assertEqual(result["operations"]["environment-model"]["state"], "pending")
        self.assertEqual(result["operations"]["hero-rig"]["state"], "pending")
        self.assertIn(("hero-model", "fetch"), self.adapter.calls)
        self.assertNotIn(("environment-model", "submit"), self.adapter.calls)

    def test_expired_quote_blocks_new_submissions_but_keeps_task_poll_and_fetch(self):
        self.prepare()
        self.advance(max_submissions=1)
        self.adapter.done.add("hero-model")
        with patch.object(suppliers, "_now", return_value=datetime(2031, 1, 1, tzinfo=timezone.utc)):
            result = self.advance(max_submissions=3)
        self.assertEqual(result["operations"]["hero-model"]["state"], "ready")
        self.assertEqual(result["operations"]["environment-model"]["state"], "pending")
        self.assertEqual(result["operations"]["hero-rig"]["state"], "pending")
        self.assertEqual(self.adapter.calls.count(("hero-model", "submit")), 1)

    def test_changed_parent_artifact_blocks_dependent_submission(self):
        self.prepare()
        self.adapter.done.add("hero-model")
        first = self.advance(max_submissions=1)
        Path(first["operations"]["hero-model"]["artifacts"][0]["path"]).write_bytes(b"Changed after fetch")
        result = self.advance(max_submissions=3)
        self.assertEqual(result["operations"]["hero-rig"]["state"], "pending")
        self.assertNotIn(("hero-rig", "submit"), self.adapter.calls)

    def test_interrupted_fetch_retries_download_without_model_resubmission(self):
        self.prepare()
        self.adapter.done.add("hero-model")
        self.adapter.fail_fetch.add("hero-model")
        first = self.advance(max_submissions=1)
        self.assertEqual(first["operations"]["hero-model"]["task_id"], "original-hero-model")
        self.adapter.fail_fetch.clear()
        result = self.advance(max_submissions=1)
        self.assertEqual(result["operations"]["hero-model"]["state"], "ready")
        self.assertEqual(self.adapter.calls.count(("hero-model", "submit")), 1)
        self.assertEqual(self.adapter.calls.count(("hero-model", "fetch")), 2)

    def test_h1_h2_or_h3_cannot_be_removed_to_prepare_supplier_jobs(self):
        original = deepcopy(self.checkpoint_data)
        for stage_id in ("selection", "atlas", "production_plan"):
            with self.subTest(stage_id=stage_id):
                document = deepcopy(original)
                stage = next(s for s in document["stages"] if s["id"] == stage_id)
                stage.pop("approval")
                core.write(self.checkpoint, document)
                with self.assertRaises((core.WorkflowError, ValueError)):
                    self.prepare()
                self.assertFalse((self.run / "supplier-run.json").exists())
        core.write(self.checkpoint, original)

    def test_selection_source_must_match_actual_workflow_h3(self):
        self.selection["source_ref"] = "synthetic://a-different-user-message"
        with self.assertRaisesRegex(core.WorkflowError, "actual H3"):
            self.prepare()

    def test_h3_table_must_bind_the_exact_selected_portfolio(self):
        for stage in self.checkpoint_data["stages"]:
            if stage["id"] == "production_plan":
                item = next(e for e in stage["evidence"] if e["role"] == "production_table")
                table = core.read(item["path"])
                table["supplier_portfolio_digest"] = "0" * 64
                core.write(item["path"], table)
                item["sha256"] = core.file_hash(item["path"])
                approve(stage)
        core.write(self.checkpoint, self.checkpoint_data)
        with self.assertRaisesRegex(core.WorkflowError, "exact supplier portfolio"):
            self.prepare()

    def test_registry_readiness_refresh_preserves_h3_and_original_binding(self):
        self.prepare()
        selection_hash = core.file_hash(self.run / "supplier-selection.json")
        fresh = deepcopy(self.registry)
        fresh["providers"][0]["verification"]["connection"]["checked_at"] = "2021-01-01T00:00:00Z"
        fresh["providers"][0]["desired"] = False
        result = self.advance(registry_refresh=fresh, capabilities=capabilities("fresh-session"), session_id="fresh-session")
        self.assertEqual(result["operations"]["hero-model"]["state"], "running")
        self.assertEqual(core.file_hash(self.run / "supplier-selection.json"), selection_hash)

    def test_actual_overcharge_stops_later_new_submissions(self):
        self.prepare()
        self.adapter.overcharge["hero-model"] = 11
        result = self.advance(max_submissions=3)
        self.assertEqual(result["cost_overrun"], "hero-model")
        self.assertNotIn(("environment-model", "submit"), self.adapter.calls)
        self.assertEqual(result["operations"]["environment-model"]["state"], "pending")


if __name__ == "__main__":
    unittest.main()
