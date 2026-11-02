"""Offline dedicated Rodin/Hi3D protocol tests. No remote requests or paid calls."""
import base64
import copy
from decimal import Decimal
import hashlib
import json
import os
import io
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch
from urllib import error

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1] / "skills/greybox-to-multistyle-art"
sys.path.insert(0, str(ROOT / "runtime"))
from greybox.providers import rodin, hitem3d
from greybox import provider_http, provider_credentials

TASK = "123e4567-e89b-12d3-a456-426614174000"
JOB = "223e4567-e89b-12d3-a456-426614174000"
HI_TASK = "task.jjewelry-aigc-api.abc"


def glb():
    data = json.dumps({"asset": {"version": "2.0"}, "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}]}).encode()
    data += b" " * (-len(data) % 4)
    return b"glTF" + struct.pack("<IIII", 2, 20 + len(data), len(data), 0x4E4F534A) + data


class FakeAPI:
    def __init__(self, responses, content=None):
        self.responses = list(responses)
        self.calls, self.downloads = [], []
        self.content = content or glb()

    def request(self, method, path, payload=None, files=None):
        self.calls.append((method, path, payload, files))
        result = self.responses.pop(0)
        if isinstance(result, Exception): raise result
        return copy.deepcopy(result)

    def download(self, url, output_dir, filename):
        self.downloads.append((url, str(output_dir), filename))
        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
        target = output / filename
        target.write_bytes(self.content)
        return {"path": str(target), "sha256": hashlib.sha256(self.content).hexdigest(), "bytes": len(self.content)}


class DedicatedAdapters(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="rodin-hi3d-offline-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        storage = patch.object(provider_credentials, 'store_path', return_value=self.base / 'credentials/providers.json')
        storage.start()
        self.addCleanup(storage.stop)
        self.png = self.base / "front.png"
        self.png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"reference-fixture")
        self.image = {"path": str(self.png), "sha256": hashlib.sha256(self.png.read_bytes()).hexdigest()}
        self.rodin = {"operation": "image_to_3d", "model_version": "Gen-2.5", "parameters": {
            "tier": "Gen-2.5-Medium", "mesh_mode": "Raw", "quality_override": 20000}, "inputs": [self.image]}
        self.hi = {"operation": "image_to_3d", "model_version": "hi3dv3.0", "parameters": {
            "model": "hi3dv3.0", "request_type": 3, "resolution": "2048quality", "face": 2000000,
            "format": 2, "pbr": 1, "shading": 0.5}, "inputs": [self.image]}

    def rodin_recovery(self):
        return {"task_id": TASK, "recovery": {"task_uuid": TASK, "subscription_key": "private-job-key", "job_uuids": [JOB]},
                "output_dir": str(self.base / "rodin-output"), "accepted_request": self.rodin}

    def test_capabilities_are_offline_and_do_not_claim_live_verification(self):
        for adapter in (rodin, hitem3d):
            with self.subTest(adapter=adapter.PROVIDER), patch.dict(os.environ, {}, clear=True), patch.object(adapter, "_client", side_effect=AssertionError):
                result = adapter.dispatch("capabilities", {})
                self.assertTrue(result["ok"])
                self.assertFalse(result["configured"])
                self.assertFalse(result["connection_verified"])
                self.assertFalse(result["live_verified"])
                self.assertNotIn("rig", result["operations"])

    def test_validate_needs_no_credentials_or_network(self):
        for adapter, request in ((rodin, self.rodin), (hitem3d, self.hi)):
            with self.subTest(adapter=adapter.PROVIDER), patch.dict(os.environ, {}, clear=True), patch.object(adapter, "_client", side_effect=AssertionError):
                self.assertTrue(adapter.dispatch("validate", request)["ok"])

    def test_rodin_multipart_preserves_explicit_tier_and_repeated_images(self):
        request = copy.deepcopy(self.rodin)
        request["inputs"].append(self.image)
        request["parameters"]["image_label"] = ["F", "B"]
        api = FakeAPI([{"uuid": TASK, "jobs": {"subscription_key": "private-job-key", "uuids": [JOB]}, "consumed": 0.5}])
        result = rodin.dispatch("submit", request, api)
        self.assertTrue(result["ok"])
        self.assertEqual(result["task_id"], TASK)
        self.assertEqual(result["recovery"]["subscription_key"], "private-job-key")
        self.assertEqual(result["actual_credits"], "0.5")
        self.assertEqual(api.calls[0][0:2], ("POST", "/api/v2/rodin"))
        self.assertEqual(api.calls[0][2]["tier"], "Gen-2.5-Medium")
        self.assertEqual(api.calls[0][2]["image_label"], '["F","B"]')
        self.assertEqual([row[0] for row in api.calls[0][3]], ["images", "images"])

    def test_rodin_text_has_multipart_even_without_files(self):
        request = {"operation": "text_to_3d", "model_version": "Gen-2", "parameters": {"tier": "Gen-2", "prompt": "A ceramic vase"}}
        api = FakeAPI([{"uuid": TASK, "jobs": {"subscription_key": "job-key"}}])
        self.assertTrue(rodin.dispatch("submit", request, api)["ok"])
        self.assertEqual(api.calls[0][3], [])
        self.assertEqual(api.calls[0][2]["prompt"], "A ceramic vase")

    def test_rodin_prevents_legacy_fallback_and_wrong_family_controls(self):
        for mutate in (lambda r: r["parameters"].pop("tier"), lambda r: r.update(model_version="Gen-2"),
                       lambda r: r["parameters"].update(quality_override=2000000),
                       lambda r: r["parameters"].update(mesh_mode="Quad", quality_override=300000),
                       lambda r: r["parameters"].update(is_micro=True)):
            request = copy.deepcopy(self.rodin); mutate(request)
            api = FakeAPI([])
            self.assertFalse(rodin.dispatch("submit", request, api)["ok"])
            self.assertFalse(api.calls)

    def test_hash_drift_blocks_both_providers_before_submission(self):
        self.png.write_bytes(b"changed")
        for adapter, request in ((rodin, self.rodin), (hitem3d, self.hi)):
            api = FakeAPI([])
            self.assertFalse(adapter.dispatch("submit", request, api)["ok"])
            self.assertFalse(api.calls)

    def test_rodin_201_error_is_not_success(self):
        result = rodin.dispatch("submit", self.rodin, FakeAPI([{"error": "API_INSUFFICIENT_FUNDS", "message": "secret must never echo"}]))
        self.assertFalse(result["ok"])
        self.assertFalse(result["unknown_submission"])
        self.assertNotIn("secret", json.dumps(result))

    def test_rodin_unknown_server_error_is_not_definite_rejection(self):
        result = rodin.dispatch("submit", self.rodin, FakeAPI([{"error": "API_UNKNOWN", "message": "secret"}]))
        self.assertTrue(result["unknown_submission"])
        self.assertNotIn("secret", json.dumps(result))

    def test_rodin_missing_task_uuid_is_unknown(self):
        result = rodin.dispatch("submit", self.rodin, FakeAPI([{"jobs": {"subscription_key": "job-key"}}]))
        self.assertFalse(result["ok"])
        self.assertTrue(result["unknown_submission"])

    def test_rodin_missing_subscription_preserves_accepted_task_without_resubmit(self):
        result = rodin.dispatch("submit", self.rodin, FakeAPI([{"uuid": TASK}]))
        self.assertTrue(result["ok"])
        self.assertEqual(result["state"], "recovery_required")
        request = {"task_id": result["task_id"], "recovery": result["recovery"]}
        api = FakeAPI([])
        checked = rodin.dispatch("status", request, api)
        self.assertFalse(checked["ok"])
        self.assertEqual(checked["task_id"], TASK)
        self.assertFalse(api.calls)

    def test_rodin_status_uses_subscription_key_not_task_uuid(self):
        api = FakeAPI([{"jobs": [{"uuid": JOB, "status": "Done"}]}])
        result = rodin.dispatch("status", self.rodin_recovery(), api)
        self.assertEqual(result["state"], "succeeded")
        self.assertEqual(api.calls[0][2], {"subscription_key": "private-job-key"})
        self.assertNotIn("private-job-key", json.dumps(result))

    def test_rodin_all_jobs_required_and_failure_is_terminal(self):
        for jobs, expected in (([{"uuid": JOB, "status": "Done"}, {"uuid": TASK, "status": "Generating"}], "running"),
                               ([{"uuid": JOB, "status": "Failed"}], "failed")):
            self.assertEqual(rodin.dispatch("status", self.rodin_recovery(), FakeAPI([{"jobs": jobs}]))["state"], expected)
        self.assertFalse(rodin.dispatch("status", self.rodin_recovery(), FakeAPI([{"jobs": [{"uuid": TASK, "status": "Done"}]}]))["ok"])

    def test_rodin_fetch_checks_all_jobs_and_uses_generation_uuid(self):
        api = FakeAPI([{"jobs": [{"uuid": JOB, "status": "Done"}]}, {"list": [{"name": "model.glb", "url": "https://cdn.example/model.glb"}]}])
        result = rodin.dispatch("fetch", self.rodin_recovery(), api)
        self.assertTrue(result["ok"])
        self.assertEqual(api.calls[1][2], {"task_uuid": TASK})
        self.assertEqual(Path(result["artifacts"][0]["path"]).resolve(), (self.base / "rodin-output/model.glb").resolve())
        self.assertNotIn("cdn.example", json.dumps(result))

    def test_rodin_fetch_rejects_partial_artifacts_and_traversal(self):
        for listing in ([], [{"name": "../model.glb", "url": "https://cdn.example/a.glb"}],
                        [{"name": "render.png", "url": "https://cdn.example/a.png"}]):
            api = FakeAPI([{"jobs": [{"uuid": JOB, "status": "Done"}]}, {"list": listing}])
            self.assertFalse(rodin.dispatch("fetch", self.rodin_recovery(), api)["ok"])
            self.assertFalse(api.downloads)

    def test_rodin_rejects_malformed_download_and_preserves_original_task(self):
        api = FakeAPI([{"jobs": [{"uuid": JOB, "status": "Done"}]}, {"list": [{"name": "model.glb", "url": "https://cdn.example/a.glb"}]}], content=b"notglb")
        self.assertFalse(rodin.dispatch("fetch", self.rodin_recovery(), api)["ok"])

    def test_rodin_quote_is_local_official_rate_estimate(self):
        request = copy.deepcopy(self.rodin)
        request["parameters"].update(tier="Gen-2.5-Extreme-High", texture_mode="extreme-high")
        with patch.object(rodin, "_client", side_effect=AssertionError):
            result = rodin.dispatch("quote", request)
        self.assertEqual(result["unit_credits"], "3.0")
        self.assertEqual(result["kind"], "rate_card_estimate")
        self.assertEqual(result["network_calls"], 0)
        self.assertNotIn("actual_credits", result)

    def test_hitem_generation_payload_and_task(self):
        api = FakeAPI([{"code": 200, "data": {"task_id": HI_TASK}}])
        result = hitem3d.dispatch("submit", self.hi, api)
        self.assertTrue(result["ok"])
        self.assertEqual(result["task_id"], HI_TASK)
        self.assertEqual(api.calls[0][0:2], ("POST", "/open-api/v1/submit-task"))
        self.assertEqual(api.calls[0][2]["format"], "2")
        self.assertEqual(api.calls[0][3][0][0], "images")

    def test_hitem_multiview_requires_explicit_view_mapping(self):
        request = copy.deepcopy(self.hi)
        request["operation"] = "multiview_to_3d"
        request["inputs"].append(self.image)
        self.assertFalse(hitem3d.dispatch("validate", request)["ok"])
        request["parameters"]["multi_images_bit"] = "1010"
        parameters, files = hitem3d.validate(request)
        self.assertEqual(parameters["multi_images_bit"], "1010")
        self.assertEqual([field for field, _ in files], ["multi_images", "multi_images"])
        request["parameters"]["multi_images_bit"] = "0110"
        self.assertFalse(hitem3d.dispatch("validate", request)["ok"])

    def test_hitem_rejects_unsupported_text_rig_and_unknown_fields(self):
        for mutate in (lambda r: r.update(operation="text_to_3d"), lambda r: r.update(operation="rig"),
                       lambda r: r["parameters"].update(token="secret"), lambda r: r["parameters"].update(pbr=True),
                       lambda r: r["parameters"].update(shading=0.25)):
            request = copy.deepcopy(self.hi); mutate(request)
            api = FakeAPI([])
            self.assertFalse(hitem3d.dispatch("submit", request, api)["ok"])
            self.assertFalse(api.calls)

    def test_hitem_texture_support_and_mesh_hash(self):
        mesh = self.base / "geometry.glb"; mesh.write_bytes(glb())
        request = copy.deepcopy(self.hi)
        request["operation"] = "texture"
        request["parameters"]["request_type"] = 2
        request["inputs"].append({"path": str(mesh), "sha256": hashlib.sha256(mesh.read_bytes()).hexdigest()})
        self.assertTrue(hitem3d.dispatch("validate", request)["ok"])
        request["parameters"].update(model="hitem3dv2.1", resolution="1536pro")
        request["model_version"] = "hitem3dv2.1"
        self.assertFalse(hitem3d.dispatch("validate", request)["ok"])

    def test_hitem_response_codes_no_secret_echo(self):
        for code, unknown in ((30010000, False), (10031001, False), (10000000, True)):
            result = hitem3d.dispatch("submit", self.hi, FakeAPI([{"code": code, "data": {}, "msg": "server-secret"}]))
            self.assertEqual(result["unknown_submission"], unknown)
            self.assertNotIn("server-secret", json.dumps(result))

    def test_hitem_missing_task_id_is_unknown(self):
        self.assertTrue(hitem3d.dispatch("submit", self.hi, FakeAPI([{"code": 200, "data": {}}]))["unknown_submission"])

    def test_hitem_status_matches_exact_task(self):
        good = {"code": 200, "data": {"task_id": HI_TASK, "state": "success"}}
        self.assertEqual(hitem3d.dispatch("status", {"task_id": HI_TASK}, FakeAPI([good]))["state"], "succeeded")
        good["data"]["task_id"] = "different"
        self.assertFalse(hitem3d.dispatch("status", {"task_id": HI_TASK}, FakeAPI([good]))["ok"])

    def test_hitem_fetch_matches_approved_format_and_validates_geometry(self):
        request = {"task_id": HI_TASK, "accepted_request": self.hi, "output_dir": str(self.base / "hi-output")}
        data = {"code": 200, "data": {"task_id": HI_TASK, "state": "success", "url": "https://cdn.example/a.glb?signature=private"}}
        result = hitem3d.dispatch("fetch", request, FakeAPI([data]))
        self.assertTrue(result["ok"])
        self.assertNotIn("signature", json.dumps(result))
        self.assertTrue(result["artifacts"][0]["validation"]["geometry_checked"])
        request["accepted_request"] = copy.deepcopy(self.hi)
        request["accepted_request"]["parameters"]["format"] = 4
        self.assertFalse(hitem3d.dispatch("fetch", request, FakeAPI([data]))["ok"])

    def test_hitem_archive_is_preserved_without_untrusted_extraction(self):
        request = {"task_id": HI_TASK, "accepted_request": self.hi, "output_dir": str(self.base / "hi-output")}
        data = {"code": 200, "data": {"task_id": HI_TASK, "state": "success", "url": "https://cdn.example/a.zip"}}
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as bundle: bundle.writestr("model.glb", glb())
        result = hitem3d.dispatch("fetch", request, FakeAPI([data], archive.getvalue()))
        self.assertTrue(result["ok"])
        self.assertTrue(result["artifacts"][0]["container"])
        self.assertEqual({p.name for p in (self.base / "hi-output").iterdir()}, {"model.zip", ".supplier-owner.json"})

    def test_hitem_texture_can_consume_hash_bound_ready_dependency(self):
        mesh = self.base / "dependency.glb"; mesh.write_bytes(glb())
        request = copy.deepcopy(self.hi)
        request["operation"] = "texture"
        request["parameters"].update(request_type=2, mesh_dependency="generated_mesh")
        request["dependencies"] = {"generated_mesh": {"state": "ready", "artifacts": [
            {"path": str(mesh), "sha256": hashlib.sha256(mesh.read_bytes()).hexdigest()}]}}
        parameters, files = hitem3d.validate(request)
        self.assertNotIn("mesh_dependency", parameters)
        self.assertEqual(files[-1], ("mesh", str(mesh.resolve())))
        mesh.write_bytes(b"drift")
        self.assertFalse(hitem3d.dispatch("validate", request)["ok"])

    def test_fetch_output_directory_rejects_another_job(self):
        output = self.base / "owned-output"
        provider_http.output_owner(output, "different-provider", "different-task")
        request = self.rodin_recovery(); request["output_dir"] = str(output)
        api = FakeAPI([{"jobs": [{"uuid": JOB, "status": "Done"}]},
                       {"list": [{"name": "model.glb", "url": "https://cdn.example/a.glb"}]}])
        self.assertFalse(rodin.dispatch("fetch", request, api)["ok"])
        self.assertFalse(api.downloads)

    def test_hitem_local_rate_card_prices_geometry_texture_pbr_separately(self):
        with patch.object(hitem3d, "_client", side_effect=AssertionError):
            result = hitem3d.dispatch("quote", self.hi)
        self.assertEqual(result["unit_credits"], "45")
        self.assertEqual(result["components"], {"geometry": 30, "texture": 10, "pbr": 5})
        self.assertEqual(Decimal(result["list_price"]["amount"]), Decimal("0.90"))
        self.assertEqual(result["network_calls"], 0)
        self.assertNotIn("actual_credits", result)
        master = copy.deepcopy(self.hi)
        master["parameters"]["resolution"] = "2048master"
        self.assertEqual(hitem3d.dispatch("quote", master)["unit_credits"], "145")
        request = copy.deepcopy(self.hi)
        request["parameters"].update(request_type=1)
        request["parameters"].pop("pbr")
        self.assertEqual(hitem3d.dispatch("quote", request)["unit_credits"], "30")

    def test_rodin_real_http_auth_and_no_submit_retry(self):
        client = rodin._client()
        class Opener:
            def __init__(self, status): self.status, self.calls = status, []
            def open(self, request, timeout):
                self.calls.append(request)
                raise error.HTTPError(request.full_url, self.status, "untrusted", {}, None)
        for status, unknown in ((401, False), (429, False), (503, True), (408, True)):
            opener = Opener(status)
            with patch.dict(os.environ, {"RODIN_API_KEY": "private-api-key"}), patch.object(provider_http.request, "build_opener", return_value=opener):
                result = rodin.dispatch("submit", self.rodin, client)
            self.assertFalse(result["ok"])
            self.assertEqual(result["unknown_submission"], unknown)
            self.assertEqual(len(opener.calls), 1)
            request = opener.calls[0]
            self.assertEqual(request.get_header("Authorization"), "Bearer private-api-key")
            self.assertIn("multipart/form-data", request.get_header("Content-type"))
            self.assertNotIn("private-api-key", json.dumps(result))

    def test_malicious_download_result_cannot_claim_another_jobs_file(self):
        class WrongDownload(FakeAPI):
            def download(inner, url, output_dir, filename):
                return {"path": str(self.png), "sha256": self.image["sha256"], "bytes": self.png.stat().st_size}
        rodin_api = WrongDownload([{"jobs": [{"uuid": JOB, "status": "Done"}]},
                                  {"list": [{"name": "model.glb", "url": "https://cdn.example/a.glb"}]}])
        self.assertFalse(rodin.dispatch("fetch", self.rodin_recovery(), rodin_api)["ok"])
        hi_api = WrongDownload([{"code": 200, "data": {"task_id": HI_TASK, "state": "success", "url": "https://cdn.example/a.glb"}}])
        self.assertFalse(hitem3d.dispatch("fetch", {"task_id": HI_TASK, "accepted_request": self.hi,
                         "output_dir": str(self.base / "hi-output")}, hi_api)["ok"])

    def test_provider_transport_failure_unknown_only_for_submission(self):
        for adapter, request in ((rodin, self.rodin), (hitem3d, self.hi)):
            result = adapter.dispatch("submit", request, FakeAPI([provider_http.ProviderError("Safe transport failed", unknown_submission=True)]))
            self.assertTrue(result["unknown_submission"])

    def test_readonly_account_probes_do_not_submit(self):
        for adapter, response, path in ((rodin, {"balance": 3}, "/api/v2/check_balance"),
                                        (hitem3d, {"code": 200, "data": {"totalBalance": "14.00"}}, "/open-api/v1/balance")):
            api = FakeAPI([response])
            result = adapter.dispatch("account", {}, api)
            self.assertTrue(result["connection_verified"])
            self.assertFalse(result["spending_authorized"])
            self.assertEqual(api.calls, [("GET", path, None, None)])

    def test_hitem_basic_to_bearer_token_is_memory_only(self):
        clients, calls = [], []
        class Client:
            def __init__(self, base, **kwargs):
                self.options = kwargs; clients.append(self)
            def request(self, method, path, payload=None, files=None):
                auth = self.options["auth_prefix"] if "auth_prefix" in self.options else "Bearer "
                value = self.options["credential_provider"]()
                calls.append((method, path, auth + value))
                if path.endswith("/auth/token"):
                    return {"code": 200, "data": {"accessToken": "private-access-token", "tokenType": "Bearer"}}
                return {"code": 200, "data": {"totalBalance": 14}}
        with patch.dict(os.environ, {"HITEM3D_CLIENT_ID": "test-ak", "HITEM3D_CLIENT_SECRET": "test-sk"}), patch.object(hitem3d, "ApiClient", Client):
            result = hitem3d.dispatch("account", {})
        self.assertTrue(result["ok"])
        self.assertEqual(calls[0], ("POST", "/open-api/v1/auth/token", "Basic " + base64.b64encode(b"test-ak:test-sk").decode()))
        self.assertEqual(calls[1], ("GET", "/open-api/v1/balance", "Bearer private-access-token"))
        self.assertNotIn("private-access-token", json.dumps(result))
        self.assertNotIn("test-sk", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
