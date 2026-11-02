"""Offline rig-source admission tests; synthetic observations do not prove anatomy."""
import base64
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1] / "skills/greybox-to-multistyle-art"
sys.path.insert(0, str(ROOT / "runtime"))
from greybox import character_gate, characters, core, supplier_jobs
from greybox.providers import meshy
import test_characters as character_fixtures
import test_supplier_jobs_r3 as supplier_fixtures


def reviewed(source, directory, parameters):
    """Actual synthetic file integrity, explicitly invented visual observations."""
    directory.mkdir(parents=True, exist_ok=True)
    report = directory / "inspection.json"
    characters.write_inspection(source, report)
    receipt = characters.make_template(report)
    receipt.update(category="humanoid", use="rig", reviewer="synthetic-test-actor")
    receipt["pose"] = {"label": "A-like", "status": "pass", "observation": "Synthetic fixture only; not a real character review."}
    for i, record in enumerate(receipt["views"]):
        path = directory / (record["view"] + ".png")
        character_fixtures.png(path, i * 40)
        record.update(path=str(path), sha256=core.file_hash(path))
    for check in receipt["checks"]:
        check.update(status="pass", observation="Synthetic fixture only.", views=["front", "side"])
    receipt["submission_binding"] = {"source_sha256": core.file_hash(source), "parameters_sha256": core.digest(parameters)}
    return receipt


class CharacterGateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.a, self.b = self.root / "a.glb", self.root / "b.glb"
        character_fixtures.model(self.a)
        character_fixtures.model(self.b, rig=True)
        self.artifacts = [{"path": str(p), "sha256": core.file_hash(p), "role": "model"} for p in (self.a, self.b)]
        self.path = self.root / "character-preflight" / "bind.json"
        self.receipt = None

    def admit(self, parameters, provider="meshy", inputs=(), dependencies=None, receipt=None):
        if self.receipt is None:
            self.receipt = reviewed(self.a, self.root / "review", parameters)
        value = deepcopy(receipt or self.receipt)
        value["submission_binding"]["parameters_sha256"] = core.digest(parameters)
        core.write(self.path, value)
        return character_gate.require_preflight(provider, "rig", parameters, self.root, "bind",
            sources=inputs, dependencies=dependencies or {})

    def dependencies(self, provider="meshy"):
        return {"a": {"state": "ready", "provider": provider, "task_id": "task-a", "artifacts": [self.artifacts[0]]},
                "b": {"state": "ready", "provider": provider, "task_id": "task-b", "artifacts": [self.artifacts[1]]}}

    def test_model_dependency_matches_adapter_and_cannot_borrow_another_review(self):
        dependencies = self.dependencies()
        self.assertTrue(self.admit({"model_from": "a"}, dependencies=dependencies))
        document = {"operation": "rig", "model_version": "rigging-v1", "parameters": {"model_from": "b"}, "dependencies": dependencies}
        _, payload = meshy.build_payload(document)
        self.assertEqual(base64.b64decode(payload["model_url"].split(",", 1)[1]), self.b.read_bytes())
        with self.assertRaisesRegex(ValueError, "another selected model"):
            self.admit(document["parameters"], dependencies=dependencies)

    def test_local_path_and_index_select_exact_input_not_any_hash(self):
        for selector in (0, str(self.a)):
            self.assertTrue(self.admit({"model_path": selector}, inputs=self.artifacts))
        for selector in (1, str(self.b)):
            with self.assertRaisesRegex(ValueError, "another selected model"):
                self.admit({"model_path": selector}, inputs=self.artifacts)

    def test_task_selectors_bind_the_selected_ready_provider_task(self):
        for provider, field in (("meshy", "input_task_from"), ("tripo", "input_from")):
            dependencies = self.dependencies(provider)
            self.assertTrue(self.admit({field: "a"}, provider=provider, dependencies=dependencies))
            with self.assertRaisesRegex(ValueError, "another selected model"):
                self.admit({field: "b"}, provider=provider, dependencies=dependencies)
        for provider, field in (("meshy", "input_task_id"), ("tripo", "input")):
            dependencies = self.dependencies(provider)
            self.assertTrue(self.admit({field: "task-a"}, provider=provider, dependencies=dependencies))
            with self.assertRaisesRegex(ValueError, "another selected model"):
                self.admit({field: "task-b"}, provider=provider, dependencies=dependencies)
            dependencies["duplicate"] = deepcopy(dependencies["a"])
            with self.assertRaisesRegex(ValueError, "one ready same-provider"):
                self.admit({field: "task-a"}, provider=provider, dependencies=dependencies)

    def test_missing_ambiguous_or_wrong_provider_sources_cannot_use_loose_glbs(self):
        for parameters in ({}, {"model_from": "a", "model_path": 0}, {"input_task_id": "missing"}):
            with self.assertRaises(ValueError):
                self.admit(parameters, inputs=self.artifacts, dependencies=self.dependencies())
        dependencies = self.dependencies()
        dependencies["a"]["artifacts"].append(self.artifacts[1])
        with self.assertRaisesRegex(ValueError, "exactly one primary"):
            self.admit({"model_from": "a"}, dependencies=dependencies)
        dependencies["a"]["artifacts"] = []
        with self.assertRaisesRegex(ValueError, "exactly one primary"):
            self.admit({"model_from": "a"}, inputs=self.artifacts, dependencies=dependencies)
        with self.assertRaisesRegex(ValueError, "same provider"):
            self.admit({"input_from": "b"}, provider="tripo", dependencies=self.dependencies())

    def test_source_and_view_hash_changes_invalidate_review(self):
        self.admit({"model_path": 0}, inputs=self.artifacts)
        character_fixtures.png(Path(self.receipt["views"][0]["path"]), 255)
        with self.assertRaisesRegex(ValueError, "hash changed"):
            self.admit({"model_path": 0}, inputs=self.artifacts)
        self.receipt = None
        # Recreate review images, then replace the exact source bytes.
        report = self.root / "review" / "inspection.json"
        report.unlink()
        self.admit({"model_path": 0}, inputs=self.artifacts)
        self.a.write_bytes(self.b.read_bytes())
        with self.assertRaisesRegex(ValueError, "hash changed"):
            self.admit({"model_path": 0}, inputs=self.artifacts)

    def test_remote_source_requires_unchanged_transfer_receipt_and_exact_url(self):
        parameters = {"modelUrl": "https://assets.example.com/source.glb"}
        with self.assertRaisesRegex(ValueError, "model-source binding"):
            self.admit(parameters, provider="lux3d")
        transfer = self.root / "transfer.json"
        core.write(transfer, {"kind": "model-source-binding", "method": "upload",
            "source": self.artifacts[0], "provider_source": parameters["modelUrl"]})
        self.receipt["submission_binding"]["source_receipt"] = {"path": str(transfer), "sha256": core.file_hash(transfer)}
        self.assertTrue(self.admit(parameters, provider="lux3d"))
        with self.assertRaisesRegex(ValueError, "differs from reviewed"):
            self.admit({"modelUrl": "https://assets.example.com/other.glb"}, provider="lux3d")
        transfer.write_text("{}")
        with self.assertRaisesRegex(ValueError, "receipt changed"):
            self.admit(parameters, provider="lux3d")

    def test_meshy_embedded_source_binds_actual_bytes(self):
        def uri(path): return "data:application/octet-stream;base64," + base64.b64encode(path.read_bytes()).decode()
        self.assertTrue(self.admit({"model_url": uri(self.a)}))
        with self.assertRaisesRegex(ValueError, "another selected model"):
            self.admit({"model_url": uri(self.b)})

    def test_for_supplier_does_not_flatten_dependencies_and_requires_custom_route(self):
        parameters = {"model_from": "b"}
        self.receipt = reviewed(self.a, self.root / "review", parameters)
        core.write(self.path, self.receipt)
        operation = {"id": "bind", "provider": "meshy", "operation": "rig", "parameters": parameters, "depends_on": ["a", "b"]}
        state = {"project": str(self.root), "inputs": {"bind": []}, "operations": self.dependencies()}
        with self.assertRaisesRegex(ValueError, "another selected model"):
            character_gate.for_supplier(operation, state, self.root)
        operation.update(provider="registered-rigger", parameters={"model_from": "a"})
        self.receipt["submission_binding"]["parameters_sha256"] = core.digest(operation["parameters"])
        core.write(self.path, self.receipt)
        with self.assertRaisesRegex(ValueError, "explicitly registered"):
            character_gate.for_supplier(operation, state, self.root)
        registry = {"providers": [{"id": "registered-rigger", "binding": {"kind": "command"}, "operations": ["rig"]}]}
        self.assertTrue(character_gate.for_supplier(operation, state, self.root, registry))

    def test_tripo_requires_its_ready_check_before_admission(self):
        operation = {"id": "bind", "provider": "tripo", "operation": "rig", "parameters": {"input_from": "a"}, "depends_on": ["a"]}
        state = {"project": str(self.root), "inputs": {"bind": []}, "operations": self.dependencies("tripo")}
        with self.assertRaisesRegex(ValueError, "rig_check dependency"):
            character_gate.for_supplier(operation, state, self.root)
        operation["parameters"]["rig_check_from"] = "check"
        operation["depends_on"].append("check")
        state["operations"]["check"] = {"state": "pending", "provider": "tripo", "artifacts": []}
        with self.assertRaisesRegex(ValueError, "not ready"):
            character_gate.for_supplier(operation, state, self.root)


class CharacterGateLedgerTests(unittest.TestCase):
    def setUp(self):
        self.fixture = supplier_fixtures.SupplierJobTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.operation = next(op for op in self.fixture.portfolio["options"][0]["operations"] if op["id"] == "hero-rig")
        self.operation["parameters"] = {"model_from": "hero-model"}
        self.fixture.rebind_portfolio()
        self.fixture.prepare()
        self.fixture.adapter.done.update({"hero-model", "environment-model"})
        self.fixture.advance(max_submissions=2)
        self.fixture.adapter.calls.clear()

    def test_missing_report_blocks_before_reserve_claim_or_submit(self):
        with patch.object(supplier_jobs, "_reserve", wraps=supplier_jobs._reserve) as reserve, patch.object(supplier_jobs, "_claim", wraps=supplier_jobs._claim) as claim:
            result = self.fixture.advance()
        reserve.assert_not_called()
        claim.assert_not_called()
        self.assertEqual(self.fixture.adapter.calls, [])
        self.assertEqual(result["operations"]["hero-rig"]["state"], "pending")
        self.assertIn("completed GLB review", result["operations"]["hero-rig"]["operational_blocker"])
        state = core.read(self.fixture.run / "supplier-run.json")
        self.assertNotIn("hero-rig", state["reservations"])

    def test_accepted_task_recovers_status_and_fetch_without_new_gate_or_charge(self):
        state = core.read(self.fixture.run / "supplier-run.json")
        state["operations"]["hero-rig"].update(state="running", provider="character-vendor", task_id="original-hero-rig")
        supplier_jobs._reserve(state, self.operation)
        original_reservations = deepcopy(state["reservations"])
        core.write(self.fixture.run / "supplier-run.json", state)
        self.fixture.adapter.done.add("hero-rig")
        with patch.object(character_gate, "for_supplier", side_effect=AssertionError("Recovery called new-submission gate")):
            result = self.fixture.advance()
        self.assertEqual(self.fixture.adapter.calls, [("hero-rig", "status"), ("hero-rig", "fetch")])
        self.assertEqual(result["operations"]["hero-rig"]["state"], "ready")
        self.assertEqual(core.read(self.fixture.run / "supplier-run.json")["reservations"], original_reservations)


if __name__ == "__main__": unittest.main()
