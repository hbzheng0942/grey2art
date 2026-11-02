"""Synthetic HTTP and process fixtures; never contact a paid image service."""
import base64
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch
from urllib import error

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1] / "skills/greybox-to-multistyle-art"
sys.path.insert(0, str(ROOT / "runtime"))
from greybox import core, image_adapters as adapters, image_cli, image_jobs as jobs, modeling_refs, provider_http

try:
    from PIL import Image, ImageDraw
except ImportError:
    Image = None


class Response(io.BytesIO):
    def __init__(self, value=None, raw=None, url="https://cdn.example.com/result.png"):
        super().__init__(raw if raw is not None else json.dumps(value or {}).encode())
        self.url = url

    def geturl(self):
        return self.url


class Opener:
    def __init__(self, responses=None, failure=None):
        self.responses = list(responses or [])
        self.failure = failure
        self.calls = []

    def open(self, req, timeout):
        self.calls.append((req, timeout))
        if self.failure:
            raise self.failure
        return self.responses.pop(0)


@unittest.skipIf(Image is None, "Pillow is required for real pixel fixtures")
class ImageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = self.root / "config"
        self.profile = {"kind": "openai", "base_url": "https://api.example.com/v1", "model": "fixture-image-model", "credential_env": "GREYBOX_FIXTURE_IMAGE_KEY"}
        self.environment = patch.dict(os.environ, {"GREYBOX_FIXTURE_IMAGE_KEY": "fixture-secret-do-not-print"})
        self.environment.start()
        jobs.configure("fixture", self.profile, self.config)
        self.input = self.png("concept.png", color="royalblue")
        self.output = self.png("output.png", color="coral")

    def tearDown(self):
        self.environment.stop()
        self.temp.cleanup()

    def png(self, name, color, size=(512, 512), alpha=False):
        path = self.root / name
        image = Image.new("RGBA" if alpha else "RGB", size, (255, 255, 255, 0) if alpha else "white")
        ImageDraw.Draw(image).rectangle((size[0] // 4, size[1] // 4, size[0] * 3 // 4, size[1] * 3 // 4), fill=color)
        image.save(path)
        return path

    def ref(self, path):
        return {"path": str(path), "sha256": provider_http.file_hash(path)}

    def request(self, edit=False):
        return {"operation": "edit" if edit else "generate", "prompt": "Synthetic fixture only", "images": [self.ref(self.input)] if edit else [], "parameters": {}}

    def submit(self, request_doc=None, name="fixture", folder="job", **kwargs):
        return jobs.submit(name, request_doc or self.request(), self.root / folder, config_dir=self.config,
                           authorization={"source_ref": "synthetic-fixture-not-paid-authority"}, background=False, **kwargs)

    def b64(self):
        return base64.b64encode(self.output.read_bytes()).decode()

    def test_offline_profile_keeps_only_environment_reference(self):
        with patch.object(adapters.ImageHttp, "call") as call:
            result = jobs.profile_report("fixture", self.config)
        call.assert_not_called()
        self.assertTrue(result["credentials"]["configured"])
        self.assertFalse(result["operation_verified"])
        self.assertNotIn("fixture-secret", json.dumps(result))
        self.assertNotIn("fixture-secret", (self.config / "fixture.json").read_text())
        with self.assertRaises(adapters.ImageError):
            jobs.configure("bad", dict(self.profile, api_key="never-store"), self.config)
        with self.assertRaises(adapters.ImageError):
            jobs.configure("bad", dict(self.profile, capabilities={"parameters": ["model"]}), self.config)

    def test_text_generation_real_pixels_receipt_and_base64_not_retained(self):
        opener = Opener([Response({"created": 123, "data": [{"b64_json": self.b64()}], "usage": {"images": 1, "private_url": "do-not-print"}})])
        with patch.object(adapters.request, "build_opener", return_value=opener):
            result = self.submit()
        self.assertEqual(result["state"], "downloaded")
        self.assertEqual(len(opener.calls), 1)
        req = opener.calls[0][0]
        self.assertEqual(req.full_url, "https://api.example.com/v1/images/generations")
        self.assertEqual(json.loads(req.data)["model"], self.profile["model"])
        self.assertEqual(req.headers["Authorization"], "Bearer fixture-secret-do-not-print")
        record = result["outputs"][0]
        self.assertEqual((record["width"], record["height"]), (512, 512))
        self.assertEqual(Path(record["path"]).read_bytes(), self.output.read_bytes())
        receipt = jobs._read(record["receipt"]["path"])
        self.assertEqual(receipt["actual_input_image_sha256"], [])
        self.assertEqual(receipt["output_sha256"], record["sha256"])
        self.assertTrue(receipt["invocation_recorded"])
        response = jobs._read(self.root / "job/provider-response.json")
        self.assertNotIn("b64_json", json.dumps(response))
        self.assertEqual(response["items"][0]["path"], record["path"])
        self.assertNotIn("private_url", json.dumps(result))
        self.assertNotIn("fixture-secret", (self.root / "job/job.json").read_text())

    def test_multiple_reference_multipart_image_array_mask_and_exact_bytes(self):
        second = self.png("second.png", "green")
        mask = self.png("mask.png", "black", alpha=True)
        doc = self.request(True)
        doc["images"].append(self.ref(second))
        doc["mask"] = self.ref(mask)
        opener = Opener([Response({"data": [{"b64_json": self.b64()}]})])
        with patch.object(adapters.request, "build_opener", return_value=opener):
            result = self.submit(doc)
        req = opener.calls[0][0]
        self.assertTrue(req.full_url.endswith("/images/edits"))
        self.assertEqual(req.data.count(b'name="image[]"'), 2)
        self.assertIn(b'name="mask"', req.data)
        self.assertIn(self.input.read_bytes(), req.data)
        self.assertIn(second.read_bytes(), req.data)
        self.assertIn(mask.read_bytes(), req.data)
        receipt = jobs._read(result["outputs"][0]["receipt"]["path"])
        self.assertEqual(receipt["actual_input_image_sha256"], [provider_http.file_hash(self.input), provider_http.file_hash(second)])

    def test_single_reference_uses_standard_image_field(self):
        opener = Opener([Response({"data": [{"b64_json": self.b64()}]})])
        with patch.object(adapters.request, "build_opener", return_value=opener):
            self.submit(self.request(True))
        body = opener.calls[0][0].data
        self.assertIn(b'name="image";', body)
        self.assertNotIn(b'name="image[]"', body)

    def test_inline_json_exceeding_old_3d_limit_is_supported(self):
        opener = Opener([Response({"data": [{"b64_json": self.b64()}], "fixture_padding": "x" * (17 * 1024 * 1024)})])
        with patch.object(adapters.request, "build_opener", return_value=opener):
            self.assertEqual(self.submit()["state"], "downloaded")

    def test_reference_receipt_passes_existing_modeling_contract(self):
        opener = Opener([Response({"data": [{"b64_json": self.b64()}]})])
        with patch.object(adapters.request, "build_opener", return_value=opener):
            result = self.submit(self.request(True))
        output = result["outputs"][0]
        views = [{"id": "fixture-front", "role": "front", "origin": "host_generated", "image": {"path": output["path"], "sha256": output["sha256"]}, "generation_receipt": output["receipt"]}]
        package = {"schema": 1, "kind": "modeling-reference-package", "policy": modeling_refs.POLICY, "style_id": "fixture-style", "selected_concept_sha256": provider_http.file_hash(self.input), "assets": [{"asset_id": "fixture", "mode": "single", "views": views, "review": {"actor": "agent", "note": "Synthetic control fixture; no production aesthetics claim", "images_digest": core.digest(views), "criteria": {name: True for name in modeling_refs.CRITERIA}}}]}
        self.assertTrue(modeling_refs.validate_package(package, self.root)["ok"])

    def test_unsupported_capabilities_fail_before_http_and_reservation(self):
        jobs.configure("limited", dict(self.profile, capabilities={"max_references": 1, "mask": False, "size": False, "transparent_background": False}), self.config)
        for parameters in [{"size": "1024x1024"}, {"background": "transparent"}, {"seed": 1}]:
            with self.subTest(parameters=parameters), patch.object(adapters.ImageHttp, "call") as call:
                with self.assertRaises(adapters.ImageError):
                    self.submit(dict(self.request(), parameters=parameters), name="limited")
                call.assert_not_called()
                self.assertFalse((self.root / "job").exists())

    def test_offline_request_validation_needs_no_key_and_never_reserves(self):
        with patch.dict(os.environ, {"GREYBOX_FIXTURE_IMAGE_KEY": ""}), patch.object(adapters.ImageHttp, "call") as call:
            result = jobs.validate("fixture", self.request(True), config_dir=self.config)
        call.assert_not_called()
        self.assertFalse(result["submission"])
        self.assertFalse(result["network"])
        self.assertEqual(result["input_image_sha256"], [provider_http.file_hash(self.input)])
        self.assertFalse((self.root / "job").exists())

    def test_mask_mismatch_and_wrong_hash_fail_before_http(self):
        doc = self.request(True)
        doc["mask"] = self.ref(self.png("small.png", "black", size=(128, 128), alpha=True))
        with self.assertRaises(adapters.ImageError):
            self.submit(doc)
        doc = self.request(True)
        doc["images"][0]["sha256"] = "a" * 64
        with self.assertRaises(adapters.ImageError):
            self.submit(doc)
        self.assertFalse((self.root / "job").exists())

    def test_no_authorization_no_key_and_no_post(self):
        with patch.object(adapters.ImageHttp, "call") as call:
            with self.assertRaises(adapters.ImageError):
                jobs.submit("fixture", self.request(), self.root / "job", authorization={}, config_dir=self.config)
            with patch.dict(os.environ, {"GREYBOX_FIXTURE_IMAGE_KEY": ""}):
                with self.assertRaises(adapters.ImageError):
                    self.submit()
            call.assert_not_called()
        self.assertFalse((self.root / "job").exists())

    def test_unknown_network_submission_is_never_reposted(self):
        opener = Opener(failure=error.URLError("api-key=do-not-leak"))
        with patch.object(adapters.request, "build_opener", return_value=opener):
            result = self.submit()
            self.assertEqual(result["state"], "unknown")
            for _ in range(3):
                self.assertEqual(jobs.resume(self.root / "job")["state"], "unknown")
        self.assertEqual(len(opener.calls), 1)
        self.assertNotIn("do-not-leak", json.dumps(result))
        with self.assertRaises(adapters.ImageError):
            self.submit()

    def test_known_rejection_and_server_unknown_are_distinguished(self):
        for code, state in [(400, "rejected"), (401, "rejected"), (408, "unknown"), (429, "rejected"), (500, "unknown")]:
            with self.subTest(code=code):
                opener = Opener(failure=error.HTTPError("https://private/?secret", code, "secret", {}, None))
                with patch.object(adapters.request, "build_opener", return_value=opener):
                    self.assertEqual(self.submit(folder="job-" + str(code))["state"], state)
                self.assertEqual(len(opener.calls), 1)

    def test_malformed_create_response_is_unknown(self):
        for index, raw in enumerate([b"not json", b"[]", b'{"data":[]}']):
            with patch.object(adapters.request, "build_opener", return_value=Opener([Response(raw=raw)])):
                self.assertEqual(self.submit(folder="bad-" + str(index))["state"], "unknown")

    def test_api_redirect_preserves_auth_boundary(self):
        redirect = provider_http._NoRedirect()
        req = adapters.request.Request("https://api.example.com/v1/images/generations", data=b"{}", headers={"Authorization": "Bearer private"})
        with self.assertRaises(provider_http.ProviderError) as caught:
            redirect.redirect_request(req, None, 307, "", {}, "https://attacker.example.com/")
        self.assertTrue(caught.exception.unknown_submission)

    def test_url_download_no_api_auth_and_shared_canonical_dedup(self):
        opener = Opener([Response({"data": [{"url": "https://cdn.example.com/result.png?signed=private"}]}), Response(raw=self.output.read_bytes())])
        with patch.object(adapters.request, "build_opener", return_value=opener), patch.object(provider_http, "public_url", side_effect=lambda url: url):
            first = self.submit()
        self.assertNotIn("Authorization", opener.calls[1][0].headers)
        self.assertNotIn("signed=", json.dumps(first))
        with patch.object(adapters.request, "build_opener", return_value=Opener([Response({"data": [{"b64_json": self.b64()}]})])):
            second = self.submit(folder="job-second")
        self.assertEqual(first["outputs"][0]["path"], second["outputs"][0]["path"])
        self.assertEqual(len(list((self.root / "image-assets").glob("*.png"))), 1)
        self.assertEqual(list((self.root / "image-assets").glob(".image-fetch-*")), [])

    def test_corrupt_download_can_fetch_again_without_generation(self):
        opener = Opener([Response({"data": [{"url": "https://cdn.example.com/image.png"}]}), Response(raw=b"truncated-image"), Response(raw=self.output.read_bytes())])
        with patch.object(adapters.request, "build_opener", return_value=opener), patch.object(provider_http, "public_url", side_effect=lambda url: url):
            with self.assertRaises(adapters.ImageError):
                self.submit()
            self.assertEqual(jobs.status(self.root / "job", remote=False)["state"], "succeeded")
            result = jobs.resume(self.root / "job")
        self.assertEqual(result["state"], "downloaded")
        self.assertEqual(sum(req.get_method() == "POST" for req, _ in opener.calls), 1)

    def test_unknown_sync_job_recovers_original_saved_response(self):
        with patch.object(adapters.request, "build_opener", return_value=Opener(failure=TimeoutError())):
            self.submit()
        original = self.root / "original-private-response.json"
        original.write_text(json.dumps({"data": [{"b64_json": self.b64()}]}))
        with patch.object(adapters.ImageHttp, "call") as call:
            result = jobs.resume(self.root / "job", response_file=original, source_ref="synthetic-original-provider-log")
            call.assert_not_called()
        self.assertEqual(result["state"], "downloaded")

    def test_killed_worker_stays_unresolved_and_profile_changes_do_not_redirect(self):
        with patch.object(jobs.subprocess, "Popen"):
            jobs.submit("fixture", self.request(), self.root / "job", config_dir=self.config, authorization={"source_ref": "fixture"})
        folder, data = jobs._job(self.root / "job")
        data["state"] = "submitting"
        jobs._save(folder, data)
        jobs.configure("fixture", dict(self.profile, base_url="https://other.example.com/v1"), self.config)
        with patch.object(adapters.ImageHttp, "call") as call:
            self.assertTrue(jobs.resume(folder)["reconciliation_required"])
            call.assert_not_called()
        self.assertEqual(jobs._job(folder)[1]["profile"]["base_url"], self.profile["base_url"])

    def test_worker_start_failure_can_invoke_once_and_changed_inputs_cannot(self):
        with patch.object(jobs.subprocess, "Popen", side_effect=OSError()):
            result = jobs.submit("fixture", self.request(True), self.root / "job", config_dir=self.config, authorization={"source_ref": "fixture"})
        self.assertEqual(result["state"], "reserved")
        self.input.write_bytes(self.output.read_bytes())
        with patch.object(adapters.ImageHttp, "call") as call, self.assertRaises(adapters.ImageError):
            jobs.execute(self.root / "job")
        call.assert_not_called()

    def test_lux_text_image_and_mixed_create_inputs(self):
        from greybox import lux
        jobs.configure("lux-fixture", {"kind": "lux", "region": "cn"}, self.config)
        for index, (with_image, prompt) in enumerate([(False, "Text image"), (True, None), (True, "Image and text")]):
            doc = self.request(with_image)
            doc["prompt"] = prompt
            opener = Opener([Response({"f": None, "c": "0", "m": "", "d": 123 + index})])
            captured = []
            def upload(path, region):
                captured.append((Path(path).read_bytes(), region))
                return {"url": "https://cdn.example.com/input.png"}
            # This tests request construction with a fake upload. Do not probe
            # or bootstrap a real private runtime when requests is unavailable.
            with patch.object(lux, "_runtime_python", return_value=sys.executable), patch.object(lux, "setup") as setup, patch.object(lux, "credential_provider", return_value="lux-fixture-key"), patch.object(adapters, "_lux_upload_image", side_effect=upload), patch.object(adapters.request, "build_opener", return_value=opener):
                result = self.submit(doc, name="lux-fixture", folder="lux-" + str(index))
            setup.assert_not_called()
            self.assertEqual(result["state"], "submitted")
            payload = json.loads(opener.calls[0][0].data)
            self.assertEqual("img" in payload, with_image)
            self.assertEqual("prompt" in payload, prompt is not None)
            self.assertNotIn("version", payload)
            self.assertNotIn("enablePbr", payload)
            self.assertEqual(opener.calls[0][0].headers["Authorization"], "lux-fixture-key")
            if with_image:
                self.assertEqual(captured[0][0], self.input.read_bytes())

    def test_lux_upload_isolates_environment_proxy_preserving_tls_and_pinned_session(self):
        from greybox import lux
        session = types.SimpleNamespace(trust_env=True, verify=True, close=lambda: None)
        uploader = types.SimpleNamespace(upload_file=lambda path, **kwargs: {"url": "https://cdn.example.com/input.png"})
        with patch.dict(sys.modules, {"requests": types.SimpleNamespace(Session=lambda: session)}), patch.object(lux, "_module", return_value=uploader) as module, patch.object(uploader, "upload_file", wraps=uploader.upload_file) as upload, patch.object(session, "close") as close:
            result = adapters._lux_upload_direct(self.input, "cn")
        self.assertEqual(result["url"], "https://cdn.example.com/input.png")
        self.assertFalse(session.trust_env)
        self.assertTrue(session.verify)
        self.assertIs(upload.call_args.kwargs["session"], session)
        self.assertIs(upload.call_args.kwargs["credential_provider"], lux.credential_provider)
        module.assert_called_once_with("asset_uploader")
        close.assert_called_once()

    def test_lux_upload_private_runtime_uses_same_session_isolated_helper(self):
        from greybox import lux
        response = subprocess.CompletedProcess([], 0, json.dumps({"ok": True, "data": {"url": "https://cdn.example.com/input.png"}}), "")
        with patch.object(adapters.importlib.util, "find_spec", return_value=None), patch.object(lux, "_runtime_python", return_value=sys.executable), patch.object(adapters.subprocess, "run", return_value=response) as run:
            result = adapters._lux_upload_image(self.input, "cn")
        self.assertTrue(result["url"].startswith("https://"))
        self.assertIn("_lux_upload_worker", run.call_args.args[0][-1])
        self.assertTrue(run.call_args.kwargs["capture_output"])
        self.assertEqual(json.loads(run.call_args.kwargs["input"]), {"path": str(self.input), "region": "cn"})

    def test_lux_upload_failure_is_sanitized_and_closes_session(self):
        from greybox import lux
        session = types.SimpleNamespace(trust_env=True, verify=True, close=lambda: None)
        def fail(*args, **kwargs): raise RuntimeError("private-upload-url-and-key")
        with patch.dict(sys.modules, {"requests": types.SimpleNamespace(Session=lambda: session)}), patch.object(lux, "_module", return_value=types.SimpleNamespace(upload_file=fail)), patch.object(session, "close") as close:
            with self.assertRaises(adapters.ImageError) as caught: adapters._lux_upload_direct(self.input, "cn")
        self.assertNotIn("private-upload", str(caught.exception))
        self.assertFalse(caught.exception.unknown_submission)
        close.assert_called_once()

    def test_lux_poll_recovery_with_original_task_id_and_result(self):
        from greybox import lux
        jobs.configure("lux-fixture", {"kind": "lux", "region": "cn"}, self.config)
        opener = Opener([Response({"f": None, "c": "0", "m": "", "d": 42}), Response({"f": None, "c": "0", "m": "", "d": {"taskId": 42, "bizId": "LUX_3D", "status": 3, "outputs": [{"content": "https://cdn.example.com/image.png"}]}}), Response(raw=self.output.read_bytes())])
        with patch.object(lux, "credential_provider", return_value="lux-fixture-key"), patch.object(adapters.request, "build_opener", return_value=opener), patch.object(provider_http, "public_url", side_effect=lambda url: url):
            self.assertEqual(self.submit(name="lux-fixture")["state"], "submitted")
            self.assertEqual(jobs.resume(self.root / "job")["state"], "downloaded")
        self.assertEqual(sum(req.get_method() == "POST" for req, _ in opener.calls), 1)
        self.assertIn("taskid=42", opener.calls[1][0].full_url)

    def test_custom_adapter_source_manual_binding_and_process_protocol(self):
        source = self.root / "adapter.py"
        source.write_text("import json,sys\nr=json.load(sys.stdin)\nassert r['schema']=='greybox.image-adapter/v1'\nprint(json.dumps({'state':'succeeded','provider_task_id':'fixture-task','items':[{'path':" + repr(str(self.output)) + "}]}))\n")
        manual = self.root / "api-manual.txt"
        manual.write_text("Synthetic API protocol fixture, not a production endpoint")
        profile = {"kind": "custom", "credential_env": "GREYBOX_FIXTURE_IMAGE_KEY", "capabilities": {"generate": True, "edit": False, "max_references": 0, "parameters": []}, "adapter": {"source": str(source), "sha256": provider_http.file_hash(source), "argv": [sys.executable, "{adapter}"], "documentation": {"source_ref": "synthetic-fixture-manual", "path": str(manual), "sha256": provider_http.file_hash(manual)}}}
        jobs.configure("custom", profile, self.config)
        wrong = json.loads(json.dumps(profile))
        wrong["adapter"]["argv"] = [sys.executable, "-c", "print('unbound')", "{adapter}"]
        with self.assertRaises(adapters.ImageError):
            jobs.configure("unbound", wrong, self.config)
        self.assertEqual(self.submit(name="custom")["state"], "downloaded")
        source.write_text(source.read_text() + "# changed\n")
        with self.assertRaises(adapters.ImageError):
            jobs.load_profile("custom", self.config)
        source.write_text(source.read_text().removesuffix("# changed\n"))
        manual.write_text("changed API manual")
        with self.assertRaises(adapters.ImageError):
            jobs.load_profile("custom", self.config)

    def test_real_detached_custom_worker_continues_without_host(self):
        source = self.root / "worker-adapter.py"
        source.write_text("import json,sys,time\njson.load(sys.stdin)\ntime.sleep(0.1)\nprint(json.dumps({'state':'succeeded','items':[{'path':" + repr(str(self.output)) + "}]}))\n")
        profile = {"kind": "custom", "credential_env": "GREYBOX_FIXTURE_IMAGE_KEY", "capabilities": {"generate": True, "edit": False, "max_references": 0, "parameters": []}, "adapter": {"source": str(source), "sha256": provider_http.file_hash(source), "argv": [sys.executable, "{adapter}"], "documentation": {"source_ref": "synthetic-manual-fixture"}}}
        jobs.configure("custom", profile, self.config)
        result = jobs.submit("custom", self.request(), self.root / "job", config_dir=self.config, authorization={"source_ref": "synthetic-fixture"})
        self.assertIn("worker_pid", result)
        for _ in range(100):
            result = jobs.status(self.root / "job", remote=False)
            if result["state"] == "downloaded":
                break
            time.sleep(0.05)
        self.assertEqual(result["state"], "downloaded")

    def test_native_receipt_has_actual_input_lineage_without_copy(self):
        result = jobs.record_native(self.output, self.root / "native", tool="synthetic-host-tool", source_ref="actual-fixture-call", actual_arguments={"prompt": "fixture"}, images=[self.ref(self.input)])
        receipt = jobs._read(result["receipt"]["path"])
        self.assertEqual(receipt["actual_input_image_sha256"], [provider_http.file_hash(self.input)])
        self.assertEqual(result["output"]["path"], str(self.output.resolve()))
        self.assertEqual(len(list((self.root / "native").iterdir())), 1)

    def test_cli_standalone_capabilities_and_shared_parser(self):
        completed = subprocess.run([sys.executable, "-B", str(ROOT / "scripts/image.py"), "capabilities", "--profile", "fixture", "--config-dir", str(self.config)], capture_output=True, text=True, timeout=20)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["profile"], "fixture")
        import argparse
        parser = argparse.ArgumentParser()
        image_cli.add_parser(parser.add_subparsers(dest="command"))
        args = parser.parse_args(["image", "capabilities", "--profile", "fixture", "--config-dir", str(self.config)])
        self.assertTrue(image_cli.handle(args)["offline_only"])

    def test_install_directory_and_mutated_job_binding_are_rejected(self):
        with self.assertRaises(adapters.ImageError):
            jobs.configure("bad", self.profile, ROOT / "scratch-test-never-created")
        with patch.object(jobs.subprocess, "Popen"):
            jobs.submit("fixture", self.request(), self.root / "job", config_dir=self.config, authorization={"source_ref": "fixture"})
        path = self.root / "job/job.json"
        doc = jobs._read(path)
        doc["request"]["prompt"] = "tampered"
        jobs._write(path, doc)
        with self.assertRaises(adapters.ImageError):
            jobs.status(path.parent, remote=False)


    def test_opaque_remote_task_id_is_preserved_after_charged_submission(self):
        task = "projects/p/locations/us/operations/42"
        with patch.object(jobs.subprocess, "Popen"):
            jobs.submit("fixture", self.request(), self.root / "opaque", config_dir=self.config, authorization={"source_ref": "fixture"})
        with patch.object(adapters, "submit", return_value={"state": "submitted", "provider_task_id": task}):
            result = jobs.execute(self.root / "opaque")
        self.assertEqual(result["state"], "submitted")
        self.assertEqual(result["provider_task_id"], task)

    def test_malformed_post_submit_response_is_unknown_and_retained(self):
        with patch.object(jobs.subprocess, "Popen"):
            jobs.submit("fixture", self.request(), self.root / "malformed", config_dir=self.config, authorization={"source_ref": "fixture"})
        response = {"state": "unrecognized", "provider_task_id": "remote-charged-id"}
        with patch.object(adapters, "submit", return_value=response):
            result = jobs.execute(self.root / "malformed")
        self.assertEqual(result["state"], "unknown")
        self.assertEqual(jobs._read(self.root / "malformed/provider-response.json"), response)

    def test_partial_fetch_resume_does_not_redownload_expired_completed_image(self):
        response = {"state": "succeeded", "items": [{"url": "https://example.com/first"}, {"url": "https://example.com/second"}]}
        def initial(item, target):
            if item["url"].endswith("second"):
                raise adapters.ImageError("interrupted")
            target.write_bytes(self.output.read_bytes())
            return adapters.image_info(target)
        with patch.object(adapters, "submit", return_value=response), patch.object(jobs, "_download_item", side_effect=initial):
            with self.assertRaises(adapters.ImageError):
                self.submit(folder="partial")
        downloaded = []
        def retry(item, target):
            downloaded.append(item["url"])
            if item["url"].endswith("first"):
                raise adapters.ImageError("expired signed URL")
            target.write_bytes(self.output.read_bytes())
            return adapters.image_info(target)
        with patch.object(jobs, "_download_item", side_effect=retry):
            result = jobs.fetch(self.root / "partial")
        self.assertEqual(result["state"], "downloaded")
        self.assertEqual(downloaded, ["https://example.com/second"])

    def test_stale_poll_cannot_revert_downloaded_state_after_lock(self):
        from contextlib import contextmanager
        with patch.object(adapters, "submit", return_value={"state": "running", "provider_task_id": "42"}):
            self.submit(folder="race")
        @contextmanager
        def completed_before_lock(folder):
            path = Path(folder) / "job.json"
            data = jobs._read(path)
            data["state"] = "downloaded"
            jobs._write(path, data)
            yield
        with patch.object(jobs, "_lock", completed_before_lock), patch.object(adapters, "status") as remote:
            result = jobs.status(self.root / "race")
        self.assertEqual(result["state"], "downloaded")
        remote.assert_not_called()


if __name__ == "__main__":
    unittest.main()
