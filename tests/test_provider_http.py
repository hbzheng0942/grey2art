"""No-network supplier transport, auth isolation, unknown-submission and integrity tests."""
import io
import json
import os
from pathlib import Path
import socket
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib import error
import zipfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1] / "skills/greybox-to-multistyle-art"
sys.path.insert(0, str(ROOT / "runtime"))
from greybox import provider_http as http


class Response(io.BytesIO):
    def __init__(self, body=b"{}", url="https://cdn.example.com/model.glb"):
        super().__init__(body)
        self.url = url
    def geturl(self):
        return self.url


class Opener:
    def __init__(self, response=None, failure=None):
        self.response = response or Response()
        self.failure = failure
        self.calls = []
    def open(self, req, timeout):
        self.calls.append((req, timeout))
        if self.failure:
            raise self.failure
        return self.response


class TransportTests(unittest.TestCase):
    def client(self):
        return http.ApiClient("https://api.meshy.ai", {"api.meshy.ai"}, "MESHY_API_KEY")

    def test_missing_key_stops_before_network(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(http.request, "build_opener") as opener:
            with self.assertRaises(http.ProviderError) as context:
                self.client().request("POST", "/openapi/v1/image-to-3d", {})
            self.assertFalse(context.exception.unknown_submission)
            opener.assert_not_called()

    def test_auth_only_exact_official_host_and_no_proxy(self):
        opener = Opener(Response(b'{"result":"task"}'))
        with patch.dict(os.environ, {"MESHY_API_KEY": "test-secret"}), patch.object(http.request, "build_opener", return_value=opener) as build:
            self.assertEqual(self.client().request("POST", "/openapi/v1/image-to-3d", {"a": True})["result"], "task")
            self.assertEqual(opener.calls[0][0].headers["Authorization"], "Bearer test-secret")
            self.assertIsInstance(build.call_args.args[1], http._NoRedirect)
            self.assertEqual(build.call_args.args[0].proxies, {})
        with self.assertRaises(http.ProviderError):
            http.ApiClient("https://api.meshy.ai.evil.example", {"api.meshy.ai"}, "MESHY_API_KEY")

    def test_memory_only_credential_provider(self):
        opener = Opener()
        with patch.object(http.request, "build_opener", return_value=opener):
            client = http.ApiClient("https://api.meshy.ai", {"api.meshy.ai"}, credential_provider=lambda: "memory-token")
            client.request("GET", "/openapi/v1/balance")
            self.assertEqual(opener.calls[0][0].headers["Authorization"], "Bearer memory-token")

    def test_post_network_failure_is_unknown_and_never_retried(self):
        opener = Opener(failure=error.URLError("api-key=DO-NOT-LEAK"))
        with patch.dict(os.environ, {"MESHY_API_KEY": "test-secret"}), patch.object(http.request, "build_opener", return_value=opener):
            with self.assertRaises(http.ProviderError) as context:
                self.client().request("POST", "/openapi/v1/image-to-3d", {})
            self.assertTrue(context.exception.unknown_submission)
            self.assertNotIn("DO-NOT-LEAK", str(context.exception))
            self.assertEqual(len(opener.calls), 1)

    def test_http_rejection_and_ambiguous_server_outcomes(self):
        for status, unknown in [(400, False), (401, False), (402, False), (408, True), (429, False), (500, True), (503, True)]:
            with self.subTest(status=status):
                opener = Opener(failure=error.HTTPError("https://secret/", status, "TOKEN", {}, None))
                with patch.dict(os.environ, {"MESHY_API_KEY": "test-secret"}), patch.object(http.request, "build_opener", return_value=opener):
                    with self.assertRaises(http.ProviderError) as context:
                        self.client().request("POST", "/openapi/v1/image-to-3d", {})
                    self.assertEqual(context.exception.unknown_submission, unknown)
                    self.assertEqual(context.exception.code, status)
                    self.assertNotIn("TOKEN", str(context.exception))

    def test_malformed_post_response_cannot_be_definite_rejection(self):
        for body in [b"not-json", b"[]", b"null"]:
            with self.subTest(body=body):
                opener = Opener(Response(body))
                with patch.dict(os.environ, {"MESHY_API_KEY": "test-secret"}), patch.object(http.request, "build_opener", return_value=opener):
                    with self.assertRaises(http.ProviderError) as context:
                        self.client().request("POST", "/create", {})
                    self.assertTrue(context.exception.unknown_submission)

    def test_api_redirect_cannot_forward_authorization(self):
        redirect = http._NoRedirect()
        req = http.request.Request("https://api.meshy.ai/create", data=b"{}", headers={"Authorization": "Bearer secret"})
        with self.assertRaises(http.ProviderError) as context:
            redirect.redirect_request(req, None, 307, "", {}, "https://attacker.example/")
        self.assertTrue(context.exception.unknown_submission)

    def test_download_url_guards(self):
        for url in ["http://example.com/a", "file:///tmp/key", "https://127.0.0.1/a", "https://[::1]/a", "https://169.254.169.254/key", "https://user:pass@example.com/a", "https://example.com:8443/a", "https://a.local/key"]:
            with self.subTest(url=url), self.assertRaises(http.ProviderError):
                http.public_url(url)
        private = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.2", 443))]
        with patch.object(http.socket, "getaddrinfo", return_value=private), self.assertRaises(http.ProviderError):
            http.public_url("https://private.example/key")

    def test_download_redirect_checks_new_host(self):
        redirect = http._PublicRedirect()
        req = http.request.Request("https://cdn.example.com/model.glb")
        with self.assertRaises(http.ProviderError):
            redirect.redirect_request(req, None, 302, "", {}, "https://127.0.0.1/key")

    def test_download_noauth_exclusive_reuse_and_collision(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            with patch.object(http, "public_url", side_effect=lambda url: url), patch.object(http.request, "build_opener", return_value=Opener(Response(b"mesh"))) as build:
                artifact = self.client().download("https://cdn.example.com/model.glb?signed=secret", folder, "task.glb")
                self.assertEqual(Path(artifact["path"]).read_bytes(), b"mesh")
                req = build.return_value.calls[0][0]
                self.assertNotIn("Authorization", req.headers)
            with patch.object(http, "public_url", side_effect=lambda url: url), patch.object(http.request, "build_opener", return_value=Opener(Response(b"mesh"))):
                same = self.client().download("https://cdn.example.com/model.glb", folder, "task.glb")
                self.assertEqual(same["sha256"], artifact["sha256"])
            with patch.object(http, "public_url", side_effect=lambda url: url), patch.object(http.request, "build_opener", return_value=Opener(Response(b"other"))), self.assertRaises(http.ProviderError):
                self.client().download("https://cdn.example.com/model.glb", folder, "task.glb")
            self.assertEqual((folder / "task.glb").read_bytes(), b"mesh")
            self.assertEqual(list(folder.glob("*.part")), [])

    def test_multipart_repeated_files_and_header_injection(self):
        body, mime = http.multipart({"quality": "high"}, [("images", ("a.png", b"a", "image/png")), ("images", ("b.png", b"b", "image/png"))])
        self.assertEqual(body.count(b'name="images"'), 2)
        self.assertIn("boundary=greybox-", mime)
        with self.assertRaises(http.ProviderError):
            http.multipart({}, [("images", ('a.png"\r\nX-Key: leak', b"a", "image/png"))])

    def test_glb_required_geometry_rig_and_animation(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "model.glb"
            doc = {"asset": {"version": "2.0"}, "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}]}
            def save():
                body = json.dumps(doc).encode(); body += b" " * (-len(body) % 4)
                path.write_bytes(b"glTF" + struct.pack("<IIII", 2, 20 + len(body), len(body), 0x4e4f534a) + body)
            save()
            http.validate_artifact(path, require_geometry=True)
            with self.assertRaises(http.ProviderError): http.validate_artifact(path, require_rig=True)
            with self.assertRaises(http.ProviderError): http.validate_artifact(path, require_animation=True)
            doc["skins"] = [{"joints": [0]}]
            doc["animations"] = [{"channels": [{}], "samplers": [{}]}]
            save()
            http.validate_artifact(path, require_geometry=True, require_rig=True, require_animation=True)
            path.write_bytes(b"glTF")
            with self.assertRaises(http.ProviderError): http.validate_artifact(path)

    def test_zip_structure_checked_without_extracting(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "model.zip"
            path.write_bytes(b"PK\x03\x04")
            with self.assertRaises(http.ProviderError): http.validate_artifact(path)
            with zipfile.ZipFile(path, "w") as archive: archive.writestr("../never-extracted", "source")
            http.validate_artifact(path)
            self.assertFalse((Path(temporary).parent / "never-extracted").exists())

    def test_output_directory_task_ownership(self):
        with tempfile.TemporaryDirectory() as temporary:
            http.output_owner(temporary, "meshy", "task-a")
            http.output_owner(temporary, "meshy", "task-a")
            with self.assertRaises(http.ProviderError): http.output_owner(temporary, "tripo", "task-a")
            with self.assertRaises(http.ProviderError): http.output_owner(temporary, "meshy", "task-b")


if __name__ == "__main__": unittest.main()
