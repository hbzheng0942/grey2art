"""Private synthetic credentials only; no real accounts or network requests."""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1] / "skills/greybox-to-multistyle-art"
sys.path.insert(0, str(ROOT / "runtime"))
from greybox import provider_credentials as credentials, provider_adapter, provider_http
from greybox.providers import meshy, hitem3d


@unittest.skipUnless(os.name == "posix", "Private-file permission contract is POSIX-only")
class ProviderCredentials(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        env = patch.dict(os.environ, {"GREYBOX_CONFIG_HOME": str(self.base / "config")}, clear=True)
        env.start()
        self.addCleanup(env.stop)

    def save(self, region="international", name="MESHY_API_KEY", value="synthetic-private-value"):
        return credentials.save("meshy", region, {name: value})

    def test_private_storage_preserves_other_region_provider_and_alias(self):
        path = self.save()
        self.save("cn", value="synthetic-cn")
        self.save(name="MESHY_TEAM_API_KEY", value="synthetic-team")
        credentials.save("tripo", "international", {"TRIPO_API_KEY": "synthetic-tripo"})
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(credentials.load("meshy", "international", "MESHY_API_KEY"), "synthetic-private-value")
        self.assertEqual(credentials.load("meshy", "cn", "MESHY_API_KEY"), "synthetic-cn")
        self.assertEqual(credentials.load("meshy", "international", "MESHY_TEAM_API_KEY"), "synthetic-team")
        self.assertEqual(credentials.load("meshy", "cn", "MESHY_TEAM_API_KEY"), "")
        self.assertEqual(credentials.load("tripo", "international", "TRIPO_API_KEY"), "synthetic-tripo")

    def test_environment_wins_and_empty_explicit_value_does_not_switch_account(self):
        path = self.save()
        path.write_text("malformed")
        with patch.dict(os.environ, {"MESHY_API_KEY": "synthetic-environment"}):
            self.assertEqual(credentials.load("meshy", "international", "MESHY_API_KEY"), "synthetic-environment")
        for invalid in ["", "\nsecret", "secret\x7f"]:
            with patch.dict(os.environ, {"MESHY_API_KEY": invalid}), self.assertRaises(ValueError):
                credentials.load("meshy", "international", "MESHY_API_KEY")

    def test_corrupt_or_public_store_fails_closed_without_exposing_content(self):
        path = self.save()
        for mode, content in [(0o644, path.read_text()), (0o600, "PRIVATE-CORRUPT-TOKEN")]:
            path.write_text(content)
            path.chmod(mode)
            with self.assertRaises(ValueError) as error:
                credentials.load("meshy", "international", "MESHY_API_KEY")
            self.assertNotIn("PRIVATE-CORRUPT-TOKEN", str(error.exception))
        result = provider_adapter.dispatch("meshy", "capabilities", {})
        self.assertFalse(result["configured"])
        self.assertIn("credential_error", result)

    def test_symlink_hardlink_and_public_directory_are_rejected(self):
        path = self.save()
        original = path.parent / "original.json"
        path.rename(original)
        path.symlink_to(original)
        with self.assertRaises(ValueError): credentials.load("meshy", "international", "MESHY_API_KEY")
        path.unlink()
        os.link(original, path)
        with self.assertRaises(ValueError): credentials.load("meshy", "international", "MESHY_API_KEY")
        path.unlink()
        original.rename(path)
        path.parent.chmod(0o755)
        with self.assertRaises(ValueError): self.save()

    def test_atomic_failure_and_existing_lock_preserve_other_accounts(self):
        path = self.save()
        original = path.read_bytes()
        with patch.object(credentials.os, "replace", side_effect=OSError("synthetic failure")), self.assertRaises(OSError):
            self.save("cn")
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual({p.name for p in path.parent.iterdir()}, {"providers.json", ".providers.lock"})
        lock = path.parent / ".providers.lock"
        with credentials.exclusive(lock):
            with self.assertRaisesRegex(ValueError, "locked"):
                self.save("cn")
        self.assertEqual(path.read_bytes(), original)
        self.assertTrue(lock.exists())
        self.save("cn")
        self.assertEqual(credentials.load("meshy", "international", "MESHY_API_KEY"), "synthetic-private-value")

    def test_stale_credential_lock_does_not_block_saving(self):
        path = credentials.store_path()
        path.parent.mkdir(parents=True, mode=0o700)
        (path.parent / ".providers.lock").touch(mode=0o600)
        self.save()
        self.assertEqual(credentials.load("meshy", "international", "MESHY_API_KEY"), "synthetic-private-value")

    def test_terminal_setup_hides_value_and_nonterminal_input_is_refused(self):
        output, errors = io.StringIO(), io.StringIO()
        with patch("sys.stdin.isatty", return_value=True), patch("getpass.getpass", return_value="synthetic-only-secret"), contextlib.redirect_stdout(output):
            self.assertEqual(credentials.configure(["--provider", "meshy", "--region", "international"]), 0)
        self.assertNotIn("synthetic-only-secret", output.getvalue())
        self.assertFalse(json.loads(output.getvalue())["connection_verified"])
        with patch("sys.stdin.isatty", return_value=False), patch("getpass.getpass") as prompt, contextlib.redirect_stderr(errors):
            self.assertEqual(credentials.configure(["--provider", "meshy", "--region", "international"]), 1)
        prompt.assert_not_called()

    def test_saved_key_is_used_only_for_bound_region_and_host(self):
        self.save()
        result = provider_adapter.dispatch("meshy", "capabilities", {})
        self.assertTrue(result["configured"])
        self.assertFalse(result["connection_verified"])
        cn = {"account_profile": {"account_system": "cn", "account_ref": "team", "wallet": "mesh-cn", "credential_env": "MESHY_API_KEY"}}
        self.assertFalse(provider_adapter.dispatch("meshy", "capabilities", cn)["configured"])
        client = meshy._client()
        with patch.object(provider_http.request, "build_opener") as build:
            build.return_value.open.return_value.__enter__.return_value.read.return_value = b'{"balance":1}'
            client.request("GET", "/openapi/v1/balance")
            request = build.return_value.open.call_args.args[0]
            self.assertEqual(request.full_url, "https://api.meshy.ai/openapi/v1/balance")
            self.assertEqual(request.headers["Authorization"], "Bearer synthetic-private-value")
        with patch.object(provider_http.request, "build_opener") as build, self.assertRaises(provider_http.ProviderError):
            meshy._client(cn).request("GET", "/openapi/v1/balance")
        build.assert_not_called()

    def test_hitem_pair_uses_exact_profile_names(self):
        credentials.save("hitem3d", "public", {"HITEM3D_TEAM_ID": "synthetic-id", "HITEM3D_TEAM_SECRET": "synthetic-secret"})
        request = {"account_profile": {"account_system": "public", "account_ref": "team", "wallet": "hi-team", "credential_envs": ["HITEM3D_TEAM_ID", "HITEM3D_TEAM_SECRET"]}}
        with patch.object(provider_http.ApiClient, "request", return_value={"code": 200, "data": {"accessToken": "synthetic-token"}}) as api:
            self.assertEqual(hitem3d._client(request).credential_provider(), "synthetic-token")
        self.assertEqual(api.call_args.args[:2], ("POST", "/open-api/v1/auth/token"))


if __name__ == "__main__": unittest.main()
