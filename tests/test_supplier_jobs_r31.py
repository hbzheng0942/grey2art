"""Independent forward tests of R3.1 supplier integration; offline only.

Compose the older fixture without inheriting/importing its TestCase into discovery.
Synthetic user decisions and tiny local output never establish real acceptance.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
import hashlib
import struct
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1] / "skills/greybox-to-multistyle-art"
sys.path.insert(0, str(ROOT / "runtime"))
from greybox import core, supplier_jobs, suppliers, provider_adapter, account_profiles
from greybox.providers import rodin
import test_supplier_jobs_r3 as old_fixture

TASK = "123e4567-e89b-12d3-a456-426614174000"
JOB = "223e4567-e89b-12d3-a456-426614174000"


class SupplierForwardR31(unittest.TestCase):
    def setUp(self):
        self.f = old_fixture.SupplierJobTests("test_submit_reservation_is_persisted_before_any_command")
        self.f.setUp()
        self.addCleanup(self.f.tearDown)

    def test_settlement_during_polling_blocks_new_spend_and_is_not_double_counted(self):
        f = self.f
        f.prepare()
        f.advance(max_submissions=1)
        calls = []
        def invoke(registry, operation, method, request, authorization, project):
            calls.append((operation['id'], method))
            if method == 'status':
                return {'ok': True, 'state': 'running', 'consumed_credits': 11}
            raise AssertionError('No new paid operation is allowed after settlement exceeds the reservation')
        result = supplier_jobs.step(f.run, invoker=invoke, max_submissions=3)
        self.assertEqual(result['operations']['hero-model']['consumed_credits'], '11')
        self.assertEqual(result['cost_overrun'], 'hero-model')
        supplier_jobs.step(f.run, invoker=invoke, max_submissions=3)
        row = core.read(f.run/'supplier-run.json')['operations']['hero-model']
        self.assertEqual(len(row['cost_observations']), 1)
        self.assertFalse(any(method == 'submit' for _, method in calls))

    def configure_builtin_rodin(self):
        f = self.f
        provider = f.registry["providers"][0]
        provider.update(id="rodin", label="Rodin", binding={"kind": "builtin_api"}, operations=["image_to_3d"])
        provider["verification"]["operations"].pop("rig")
        provider["account_profile"] = {"account_system": "public", "account_ref": "synthetic-rodin-account",
            "credential_env": "RODIN_TEST_API_KEY", "wallet": "rodin-wallet"}
        profile_sha = account_profiles.profile_digest("rodin", provider["account_profile"])
        provider["verification"]["connection"]["account_profile_sha256"] = profile_sha
        provider["verification"]["operations"]["image_to_3d"]["account_profile_sha256"] = profile_sha
        f.registry["providers"] = [provider]
        option = f.portfolio["options"][0]
        operation = option["operations"][0]
        image = core.resolve_input(f.reference_images["hero"]["path"], f.project)
        operation.update(provider="rodin", model_version="Gen-2.5", parameters={"tier": "Gen-2.5-Medium", "quality_override": 20000},
                         inputs=[{"path": str(image), "sha256": core.file_hash(image)}])
        operation["pricing"].update(wallet="rodin-wallet", unit_credits="0.5")
        option["operations"] = [operation]
        option["assets"] = [option["assets"][0]]
        option["assets"][0]["operation_ids"] = [operation["id"]]
        f.portfolio["required_assets"] = ["hero"]
        f.portfolio["required_operations"] = {"hero": ["image_to_3d"]}
        f.portfolio["registry_sha256"] = suppliers.registry_digest(f.registry)
        f.selection["registry_sha256"] = suppliers.registry_digest(f.registry)
        f.rebind_portfolio()
        return operation

    def test_same_h3_operation_cannot_submit_in_two_runs(self):
        f = self.f
        first = f.run
        f.prepare()
        second = f.project / "art/supplier-case/shared/production/runs/second-run"
        supplier_jobs.prepare(f.project, second, f.registry, f.portfolio, f.selection, f.checkpoint,
                              f.capabilities, "test-session")
        submitted, lock = [], threading.Lock()
        def invoke(registry, operation, method, request, authorization, project):
            if method == "submit":
                with lock: submitted.append(operation["id"])
                return {"ok": True, "task_id": "original-" + operation["id"]}
            return {"ok": True, "state": "running"}
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda path: supplier_jobs.step(path, invoker=invoke, max_submissions=1), [first, second]))
        self.assertEqual(submitted.count("hero-model"), 1)
        # A contender can safely defer while the other thread is publishing its
        # lock metadata. Once both finish, it must identify the original claim.
        for index, path in enumerate([first, second]):
            if results[index]["operations"]["hero-model"]["state"] == "pending":
                results[index] = supplier_jobs.step(path, invoker=invoke, max_submissions=1)
        states = [result["operations"]["hero-model"]["state"] for result in results]
        self.assertEqual(sorted(states), ["blocked_duplicate", "running"])
        self.assertEqual(submitted.count("hero-model"), 1)
        self.assertEqual(len(list((f.project / "art/.supplier-claims").glob("*hero-model.json"))), 1)

    def test_new_h3_metadata_cannot_bypass_an_unresolved_original_submission(self):
        f = self.f; f.prepare(); f.adapter.ambiguous.add("hero-model")
        first = f.advance(max_submissions=1)
        self.assertEqual(first["operations"]["hero-model"]["state"], "unknown")
        f.selection["decided_at"] = "2020-01-02T00:00:00Z"
        second_run = f.project / "art/supplier-case/shared/production/runs/new-h3-run"
        supplier_jobs.prepare(f.project, second_run, f.registry, f.portfolio, f.selection, f.checkpoint,
                              f.capabilities, "test-session")
        calls = []
        def invoke(registry, operation, method, request, authorization, project):
            calls.append((operation["id"], method))
            return {"ok": True, "task_id": "new-" + operation["id"], "state": "running"}
        result = supplier_jobs.step(second_run, invoker=invoke, max_submissions=1)
        self.assertNotIn(("hero-model", "submit"), calls)
        self.assertIn(result["operations"]["hero-model"]["state"], {"blocked_duplicate", "pending"})
        original = core.read(f.run / "supplier-run.json")["operations"]["hero-model"]
        self.assertEqual(original["state"], "unknown")
        self.assertEqual(f.adapter.calls.count(("hero-model", "submit")), 1)

    def test_accepted_missing_rodin_subscription_preserves_uuid_and_never_reissues(self):
        f = self.f; self.configure_builtin_rodin(); f.prepare()
        class Client:
            calls = []
            def request(inner, method, path, payload=None, files=None):
                inner.calls.append(path)
                return {"uuid": TASK, "consumed": 0.5}
        client = Client()
        with patch.object(rodin, "_client", return_value=client):
            first = supplier_jobs.step(f.run)
            supplier_jobs.step(f.run)
        row = first["operations"]["hero-model"]
        self.assertEqual(row["task_id"], TASK)
        self.assertEqual(row["state"], "recovery_required")
        self.assertEqual(client.calls, ["/api/v2/rodin"])
        recovery = core.read(f.run / "supplier-run.json")["operations"]["hero-model"]["recovery"]
        self.assertEqual(recovery["task_uuid"], TASK)
        self.assertEqual(recovery["account_profile_sha256"], account_profiles.profile_digest("rodin", f.registry["providers"][0]["account_profile"]))
        self.assertNotIn('"recovery":', json.dumps(first))

    def test_reconcile_cannot_change_a_known_accepted_uuid(self):
        f = self.f; f.prepare()
        def invoke(*args):
            return {"ok": True, "task_id": TASK, "state": "recovery_required", "recovery": {"task_uuid": TASK}}
        supplier_jobs.step(f.run, invoker=invoke)
        with self.assertRaisesRegex(core.WorkflowError, "Cannot replace"):
            supplier_jobs.reconcile(f.run, "hero-model", "different-task", "Synthetic attempted replacement")
        supplier_jobs.reconcile(f.run, "hero-model", TASK, "Synthetic account inspection", recovery={"task_uuid": TASK, "subscription_key": "private-key"})
        ledger = core.read(f.run / "supplier-run.json")
        self.assertEqual(ledger["operations"]["hero-model"]["recovery"]["subscription_key"], "private-key")

    def test_private_recovery_reaches_status_fetch_but_not_public_status(self):
        f = self.f; f.prepare()
        observed = []
        def invoke(registry, operation, method, request, authorization, project):
            if method == "submit":
                return {"ok": True, "task_id": "original-" + operation["id"], "recovery": {"subscription_key": "private-recovery-secret"}}
            observed.append((method, deepcopy(request)))
            if method == "status": return {"ok": True, "state": "succeeded"}
            output = Path(request["output_dir"]); output.mkdir(parents=True, exist_ok=True)
            artifact = output / "synthetic.glb"; artifact.write_bytes(old_fixture.synthetic_glb())
            return {"ok": True, "artifacts": [{"path": str(artifact)}]}
        result = supplier_jobs.step(f.run, invoker=invoke, max_submissions=1)
        self.assertEqual([method for method, _ in observed], ["status", "fetch"])
        for _, request in observed:
            self.assertEqual(request["recovery"]["subscription_key"], "private-recovery-secret")
            self.assertEqual(request["accepted_request"]["operation"], "image_to_3d")
        self.assertNotIn("private-recovery-secret", json.dumps(result))
        self.assertNotIn("private-recovery-secret", json.dumps(supplier_jobs.status(f.run)))
        self.assertNotIn("private-recovery-secret", json.dumps(provider_adapter.public_result(result)))

    def test_per_provider_inflight_cap_survives_steps_without_blocking_another_provider(self):
        f = self.f
        option = f.portfolio["options"][0]
        # A different declared processing operation tests provider capacity.
        # Reissuing the same case asset/image-to-3D is now a bounded repair.
        provider = f.registry["providers"][1]
        provider["operations"].append("remesh")
        provider["verification"]["operations"]["remesh"] = deepcopy(provider["verification"]["operations"]["image_to_3d"])
        f.portfolio["registry_sha256"] = suppliers.registry_digest(f.registry)
        f.selection["registry_sha256"] = suppliers.registry_digest(f.registry)
        extra = f.operation("environment-second", "environment", "environment-vendor", "remesh", 20)
        option["operations"].append(extra)
        option["assets"][1]["operation_ids"].append(extra["id"])
        f.portfolio["execution_limits"] = {"max_inflight_per_provider": {"character-vendor": 1, "environment-vendor": 1}}
        f.rebind_portfolio(); f.prepare()
        first = f.advance(max_submissions=16)
        second = f.advance(max_submissions=16)
        self.assertEqual(first["operations"]["hero-model"]["state"], "running")
        self.assertEqual(first["operations"]["environment-model"]["state"], "running")
        self.assertEqual(second["operations"]["environment-second"]["state"], "pending")
        self.assertNotIn(("environment-second", "submit"), f.adapter.calls)
        f.adapter.done.add("environment-model")
        third = f.advance(max_submissions=16)
        self.assertEqual(third["operations"]["environment-second"]["state"], "running")
        self.assertEqual(f.adapter.calls.count(("environment-second", "submit")), 1)

    def test_definite_rejection_and_ambiguous_post_are_distinct_and_not_reissued(self):
        for outcome, expected in ((False, "rejected"), (True, "unknown")):
            with self.subTest(unknown=outcome):
                f = self.f
                # Each case has a separate scope, but no mutable input or provider identity changes.
                if (f.run / "supplier-run.json").exists():
                    self.f.tearDown(); self.f = old_fixture.SupplierJobTests("test_submit_reservation_is_persisted_before_any_command")
                    self.f.setUp(); self.addCleanup(self.f.tearDown); f = self.f
                f.prepare(); calls = []
                def invoke(registry, operation, method, request, authorization, project):
                    calls.append((operation["id"], method))
                    return {"ok": False, "state": "unknown" if outcome else "rejected", "unknown_submission": outcome,
                            "error": {"message": "Safe provider failure", "unknown_submission": outcome}}
                first = supplier_jobs.step(f.run, invoker=invoke, max_submissions=1)
                supplier_jobs.step(f.run, invoker=invoke, max_submissions=1)
                self.assertEqual(first["operations"]["hero-model"]["state"], expected)
                self.assertEqual(calls.count(("hero-model", "submit")), 1)

    def test_ambiguous_attempt_still_counts_toward_submission_step_bound(self):
        f = self.f; f.prepare(); calls = []
        def invoke(registry, operation, method, request, authorization, project):
            calls.append((operation["id"], method))
            return {"ok": False, "unknown_submission": True}
        supplier_jobs.step(f.run, invoker=invoke, max_submissions=1)
        self.assertEqual(calls, [("hero-model", "submit")])

    def test_cross_provider_dependency_excludes_private_recovery(self):
        f = self.f
        environment = f.portfolio["options"][0]["operations"][1]
        environment["depends_on"] = ["hero-model"]
        f.rebind_portfolio(); f.prepare(); captures = []
        def invoke(registry, operation, method, request, authorization, project):
            if method == "submit":
                if operation["id"] == "environment-model": captures.append(deepcopy(request["dependencies"]))
                return {"ok": True, "task_id": "original-" + operation["id"], "recovery": {"subscription_key": "private-parent-secret"}}
            if method == "status": return {"ok": True, "state": "succeeded"}
            output = Path(request["output_dir"]); output.mkdir(parents=True, exist_ok=True)
            path = output / "synthetic.glb"; path.write_bytes(old_fixture.synthetic_glb())
            return {"ok": True, "artifacts": [{"path": str(path)}]}
        supplier_jobs.step(f.run, invoker=invoke, max_submissions=3)
        self.assertEqual(len(captures), 1)
        self.assertNotIn("private-parent-secret", json.dumps(captures))
        self.assertNotIn("recovery", captures[0]["hero-model"])
        self.assertEqual(captures[0]["hero-model"]["provider"], "character-vendor")
        self.assertTrue(captures[0]["hero-model"]["artifacts"])

    def test_builtin_registry_and_custom_reviewed_commands_coexist(self):
        f = self.f
        verify = deepcopy(f.registry["providers"][0]["verification"])
        verify["operations"].pop("rig")
        f.registry["providers"].append({"id": "rodin", "label": "Rodin", "desired": True, "configured": False,
            "binding": {"kind": "builtin_api"}, "operations": ["image_to_3d"], "verification": verify})
        self.assertEqual(suppliers.validate_registry(f.registry, f.project), f.registry)
        self.assertEqual(f.registry["providers"][0]["binding"]["kind"], "command")
        f.registry["providers"][-1]["id"] = "user-new-vendor"
        with self.assertRaisesRegex(core.WorkflowError, "unsupported"):
            suppliers.validate_registry(f.registry, f.project)

    def test_actual_rodin_receipt_enforces_the_approved_credit_reservation(self):
        f = self.f; self.configure_builtin_rodin(); f.prepare()
        class Client:
            calls = []
            def request(inner, method, path, payload=None, files=None):
                inner.calls.append(path)
                if path == "/api/v2/rodin":
                    return {"uuid": TASK, "jobs": {"subscription_key": "private-job-key", "uuids": [JOB]}, "consumed": 1.0}
                return {"jobs": [{"uuid": JOB, "status": "Generating"}]}
        with patch.object(rodin, "_client", return_value=Client()):
            result = supplier_jobs.step(f.run)
        self.assertEqual(result["cost_overrun"], "hero-model")
        self.assertEqual(result["operations"]["hero-model"]["consumed_credits"], "1.0")
        self.assertNotIn("private-job-key", json.dumps(result))

    def test_real_rodin_dispatch_runner_status_and_fetch_complete_offline(self):
        f = self.f; self.configure_builtin_rodin(); f.prepare()
        data = json.dumps({"asset": {"version": "2.0"}, "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}]}).encode()
        data += b" " * (-len(data) % 4)
        model = b"glTF" + struct.pack("<IIII", 2, 20 + len(data), len(data), 0x4E4F534A) + data
        class Client:
            calls = []
            def request(inner, method, path, payload=None, files=None):
                inner.calls.append((method, path, deepcopy(payload)))
                if path == "/api/v2/rodin":
                    return {"uuid": TASK, "jobs": {"subscription_key": "private-job-key", "uuids": [JOB]}, "consumed": 0.5}
                if path == "/api/v2/status": return {"jobs": [{"uuid": JOB, "status": "Done"}]}
                return {"list": [{"name": "model.glb", "url": "https://cdn.example/model.glb?signature=private"}]}
            def download(inner, url, output_dir, filename):
                path = Path(output_dir) / filename; path.write_bytes(model)
                return {"path": str(path), "sha256": hashlib.sha256(model).hexdigest(), "bytes": len(model)}
        client = Client()
        with patch.object(rodin, "_client", return_value=client):
            result = supplier_jobs.step(f.run)
        self.assertEqual(result["state"], "assets_ready")
        self.assertEqual(result["operations"]["hero-model"]["state"], "ready")
        self.assertEqual([path for _, path, _ in client.calls], ["/api/v2/rodin", "/api/v2/status", "/api/v2/status", "/api/v2/download"])
        self.assertEqual(client.calls[-1][2], {"task_uuid": TASK})
        self.assertNotIn("private-job-key", json.dumps(result))
        self.assertNotIn("signature=private", json.dumps(result))
        artifact = result["operations"]["hero-model"]["artifacts"][0]
        self.assertEqual(artifact["sha256"], hashlib.sha256(model).hexdigest())

    def test_h3_declared_publish_moves_one_primary_glb_to_stable_source_path(self):
        f = self.f
        operation = f.portfolio["options"][0]["operations"][0]
        operation["publish"] = {"path": "art/supplier-case/styles/ceramic/assets/hero/model.glb", "role": "model"}
        f.rebind_portfolio(); f.prepare()
        original = {}
        def invoke(registry, operation, method, request, authorization, project):
            if method == "submit": return {"ok": True, "task_id": "original-" + operation["id"]}
            if method == "status": return {"ok": True, "state": "succeeded"}
            path = Path(request["output_dir"]) / "downloaded.glb"
            path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b"synthetic-glb-for-publish-move-only")
            original.update(path=path, inode=path.stat().st_ino, digest=core.file_hash(path))
            return {"ok": True, "artifacts": [{"path": str(path), "role": "model", "validation": {"synthetic": True}}]}
        result = supplier_jobs.step(f.run, invoker=invoke, max_submissions=1)
        row = result["operations"]["hero-model"]
        self.assertEqual(row["state"], "ready")
        published = row["artifacts"][0]
        target = f.project / "art/supplier-case/styles/ceramic/assets/hero/model.glb"
        self.assertEqual(Path(published["path"]).resolve(), target.resolve())
        self.assertTrue(published["published"])
        self.assertEqual(published["role"], "model")
        self.assertEqual(published["validation"], {"synthetic": True})
        self.assertEqual(target.stat().st_ino, original["inode"])
        self.assertEqual(core.file_hash(target), original["digest"])
        self.assertFalse(original["path"].exists())
        future_input = {"inputs": [{"path": "art/supplier-case/styles/ceramic/assets/hero/model.glb", "sha256": published["sha256"]}]}
        self.assertEqual(supplier_jobs._inputs(future_input, f.project),
                         [{"path": str(target.resolve()), "sha256": published["sha256"]}])

    def test_publish_requires_exactly_one_approved_primary_glb(self):
        for count in (0, 2):
            with self.subTest(primary_count=count):
                output = self.f.project / ("publish-fixture-" + str(count)); output.mkdir()
                artifacts = []
                for index in range(count):
                    path = output / ("model" + str(index) + ".glb"); path.write_bytes(b"synthetic")
                    artifacts.append({"path": str(path), "sha256": core.file_hash(path), "bytes": path.stat().st_size, "role": "model"})
                operation = {"publish": {"path": "art/assets/missing-or-ambiguous.glb", "role": "model"}}
                with self.assertRaisesRegex(core.WorkflowError, "exactly one primary"):
                    supplier_jobs._publish(operation, artifacts, self.f.project)
                self.assertTrue(all(Path(artifact["path"]).exists() for artifact in artifacts))
                self.assertFalse((self.f.project / "art/assets/missing-or-ambiguous.glb").exists())

    def test_duplicate_publish_paths_are_rejected_before_run_preparation(self):
        f = self.f
        operations = f.portfolio["options"][0]["operations"]
        operations[0]["publish"] = {"path": "art/supplier-case/styles/ceramic/assets/hero/shared.glb"}
        operations[2]["publish"] = {"path": "res://art/supplier-case/styles/ceramic/assets/hero/shared.glb"}
        f.rebind_portfolio()
        with self.assertRaisesRegex(core.WorkflowError, "unique publish path"):
            f.prepare()
        self.assertFalse((f.run / "supplier-run.json").exists())
        self.assertFalse(f.adapter.calls)

    def test_parallel_publish_cannot_overwrite_a_just_published_different_asset(self):
        f = self.f
        source_dir = f.project / "generated"; source_dir.mkdir()
        first_source = source_dir / "first.glb"; first_source.write_bytes(b"first-generated-version")
        second_source = source_dir / "second.glb"; second_source.write_bytes(b"second-generated-version")
        operation = {"publish": {"path": "art/assets/race.glb"}}
        first_artifacts = [{"path": str(first_source), "sha256": core.file_hash(first_source)}]
        second_artifacts = [{"path": str(second_source), "sha256": core.file_hash(second_source)}]
        entered_rename, release_rename = threading.Event(), threading.Event()
        actual_rename = supplier_jobs.os.rename
        def paused_rename(source, target):
            if Path(source) == first_source:
                entered_rename.set()
                if not release_rename.wait(3): raise AssertionError("Test did not release publication")
            return actual_rename(source, target)
        with patch.object(supplier_jobs.os, "rename", side_effect=paused_rename), ThreadPoolExecutor(max_workers=1) as pool:
            first = pool.submit(supplier_jobs._publish, operation, first_artifacts, f.project)
            self.assertTrue(entered_rename.wait(3))
            try:
                with self.assertRaises(core.WorkflowError):
                    supplier_jobs._publish(operation, second_artifacts, f.project)
                self.assertTrue(second_source.exists())
            finally:
                release_rename.set()
            self.assertTrue(first.result(timeout=3)[0]["published"])
        target = f.project / "art/assets/race.glb"
        self.assertEqual(target.read_bytes(), b"first-generated-version")
        self.assertEqual(second_source.read_bytes(), b"second-generated-version")
        with self.assertRaisesRegex(core.WorkflowError, "overwrite a different asset version"):
            supplier_jobs._publish(operation, second_artifacts, f.project)
        self.assertEqual(target.read_bytes(), b"first-generated-version")
        self.assertTrue(second_source.exists())


if __name__ == "__main__":
    unittest.main()
