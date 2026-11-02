"""Portable host discovery/setup; all writes stay in temporary test roots."""
import argparse
import base64
import hashlib
import importlib.util
import io
import json
import os
import plistlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1] / "skills/greybox-to-multistyle-art"
sys.path.insert(0, str(ROOT / "runtime"))
from greybox import host, host_cli, mcp_bridge

spec = importlib.util.spec_from_file_location("installer_v04", ROOT / "scripts/install.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class HostsV04(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="greybox-host-v04-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root / "private"

    def configure(self, **kwargs):
        return host.configure("workbuddy", {"python": sys.executable}, config_dir=self.config, **kwargs)

    def test_discovery_has_no_writes_or_native_tool_claims(self):
        result = host.discover(config_dir=self.config)
        self.assertFalse(self.config.exists())
        self.assertTrue(result["programs"]["python"]["available"])
        self.assertFalse(result["session_verified"])
        self.assertTrue(any(row["capability"] == "image_inspect" for row in result["remediation"]))

    def test_configuration_persists_exact_paths_and_route_across_processes(self):
        self.configure(image_profile="art-default", image_config_dir=self.root / "image-profiles")
        result = host.discover(config_dir=self.config)
        self.assertEqual(result["programs"]["python"]["path"], str(Path(sys.executable).absolute()))
        data = json.loads(Path(result["profile_path"]).read_text())
        self.assertEqual(data["image_profile"], "art-default")
        self.assertEqual(data["image_config_dir"], str(self.root / "image-profiles"))
        if os.name != "nt":
            self.assertEqual(Path(result["profile_path"]).stat().st_mode & 0o777, 0o600)

    def test_config_update_preserves_unrelated_image_routing(self):
        self.configure(image_profile="existing")
        self.configure()
        self.assertEqual(host.discover(config_dir=self.config)["image_profile"], "existing")

    def test_missing_explicit_engine_never_falls_back_to_path(self):
        result = host.discover(executables={"unity": self.root / "missing-editor"}, config_dir=self.config)
        self.assertFalse(result["programs"]["unity"]["available"])
        self.assertEqual(result["programs"]["unity"]["source"], "configured")
        with self.assertRaisesRegex(ValueError, "does not exist"):
            host.configure(executables={"unity": self.root / "missing"}, config_dir=self.config)
        self.assertFalse((self.config / "hosts/workbuddy.json").exists())
        self.assertFalse((self.config / ".host.lock").exists())

    def test_windows_unity_detected_outside_path(self):
        binary = self.root / "Program Files/Unity/Hub/Editor/6000.3.26f1/Editor/Unity.exe"
        binary.parent.mkdir(parents=True); binary.write_bytes(b"synthetic")
        result = host.discover(config_dir=self.config, platform="win32", home=self.root,
                               environ={"PATH": "", "ProgramFiles": str(self.root / "Program Files"), "LOCALAPPDATA": str(self.root / "Local")})
        self.assertEqual(result["programs"]["unity"]["path"], str(binary))
        self.assertEqual(result["programs"]["unity"]["source"], "application-directory")

    def test_mac_app_directory_supplements_path(self):
        binary = self.root / "Applications/Blender.app/Contents/MacOS/Blender"
        binary.parent.mkdir(parents=True); binary.write_bytes(b"synthetic")
        with patch.object(host.shutil, "which", return_value=None):
            result = host.discover(config_dir=self.config, platform="darwin", home=self.root, environ={"PATH": ""})
        self.assertTrue(result["programs"]["blender"]["available"])
        self.assertIn(str(binary), [result["programs"]["blender"]["path"], *result["programs"]["blender"].get("alternatives", [])])

    def test_mac_bundle_uses_declared_executable_and_downloaded_godot(self):
        bundle = self.root / "Applications/WorkBuddy.app"
        binary = bundle / "Contents/MacOS/Electron"; binary.parent.mkdir(parents=True); binary.write_bytes(b"app")
        with (bundle / "Contents/Info.plist").open("wb") as out:
            plistlib.dump({"CFBundleExecutable": "Electron"}, out)
        godot = self.root / "Downloads/Godot.app/Contents/MacOS/Godot"
        godot.parent.mkdir(parents=True); godot.write_bytes(b"engine")
        with patch.object(host.shutil, "which", return_value=None):
            result = host.discover(config_dir=self.config, platform="darwin", home=self.root, environ={"PATH": ""})
        self.assertTrue(result["programs"]["workbuddy"]["available"])
        self.assertIn(str(binary), [result["programs"]["workbuddy"]["path"], *result["programs"]["workbuddy"].get("alternatives", [])])
        self.assertTrue(result["programs"]["godot"]["available"])

    def test_verify_invokes_python_but_never_claims_pixel_reading(self):
        self.configure(image_profile="images")
        with patch.object(host, "_image_route", return_value={"ok": True, "generation_invoked": False}):
            result = host.verify(config_dir=self.config)
        self.assertTrue(result["configuration_verified"])
        self.assertTrue(result["checks"]["python"]["ok"])
        self.assertFalse(result["host_session_ready"])
        self.assertFalse(result["production_ready"])

    def test_missing_route_returns_action_and_can_be_repaired(self):
        self.configure()
        result = host.verify(config_dir=self.config)
        self.assertFalse(result["ok"])
        self.assertEqual(result["checks"]["image_route"]["status"], "missing")
        self.configure(image_profile="replacement")
        with patch.object(host, "_image_route", return_value={"ok": True}):
            self.assertTrue(host.verify(config_dir=self.config)["ok"])

    def test_dead_configured_interpreter_is_reported_without_switching(self):
        binary = self.root / "python"; binary.write_bytes(b"test")
        host.configure(executables={"python": binary}, config_dir=self.config)
        binary.unlink()
        result = host.verify(config_dir=self.config)
        self.assertFalse(result["checks"]["python"]["ok"])
        self.assertIn("python", result["checks"]["configured_paths"]["missing"])

    def test_occupied_config_lock_is_not_removed(self):
        self.config.mkdir()
        lock = self.config / ".host.lock"; lock.write_text("other")
        with self.assertRaisesRegex(ValueError, "owns the lock"):
            self.configure()
        self.assertEqual(lock.read_text(), "other")

    def test_connector_is_generated_without_unresolved_paths_or_credentials(self):
        destination = self.root / "connector with spaces"
        result = self.configure(image_profile="art", connector_dir=destination)
        cli = json.loads((destination / "cli.json").read_text())
        meta = json.loads((destination / "connector-meta.json").read_text())
        self.assertEqual(cli["runtime"], {"type": "python", "version": "3.11"})
        self.assertEqual(meta["type"], "cli")
        self.assertEqual(meta["minWorkbuddyVersion"], "5.0.0")
        self.assertIn(str(ROOT), cli["init"]["darwin"])
        self.assertNotIn("{{", (destination / "skills/greybox-host-bridge/SKILL.md").read_text())
        self.assertNotIn("auth", cli)
        self.assertTrue((destination / "icon.svg").exists())
        self.assertEqual(result["connector"]["skill_root"], str(ROOT))
        with self.assertRaisesRegex(ValueError, "new connector directory"):
            self.configure(connector_dir=destination)

    def test_cli_hook_runs_with_common_parser(self):
        parser = argparse.ArgumentParser(); subs = parser.add_subparsers(dest="command")
        host_cli.add_parser(subs)
        args = parser.parse_args(["host", "discover", "--host", "claude-code", "--config-dir", str(self.config)])
        self.assertEqual(host_cli.handle(args)["host"], "claude-code")

    def test_mcp_uses_same_cli_argv_without_shell(self):
        response = subprocess.CompletedProcess([], 0, '{"ok":true}', '')
        with patch.object(mcp_bridge.subprocess, "run", return_value=response) as run:
            result = mcp_bridge.call_tool("greybox_cli", {"argv": ["host", "discover", "--host", "codex"]})
        self.assertFalse(result["isError"])
        self.assertEqual(run.call_args.args[0][-4:], ["host", "discover", "--host", "codex"])
        self.assertNotIn("shell", run.call_args.kwargs)

    def test_mcp_timeout_does_not_retry(self):
        with patch.object(mcp_bridge.subprocess, "run", side_effect=subprocess.TimeoutExpired("test", 55)) as run:
            result = mcp_bridge.call_tool("greybox_cli", {"argv": ["image", "submit"]})
        self.assertTrue(result["isError"])
        self.assertEqual(run.call_count, 1)
        self.assertIn("persisted task", result["content"][0]["text"])

    def test_mcp_protocol_writes_only_json_and_rejects_nonimage(self):
        source = io.StringIO('{"jsonrpc":"2.0","id":1,"method":"initialize"}\n{"jsonrpc":"2.0","method":"notifications/initialized"}\n{"jsonrpc":"2.0","id":2,"method":"tools/list"}\n')
        out = io.StringIO(); mcp_bridge.serve(source, out)
        rows = [json.loads(line) for line in out.getvalue().splitlines()]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]["result"]["tools"][1]["name"], "greybox_image")
        text = self.root / "file.png"; text.write_text("secret text")
        with self.assertRaisesRegex(ValueError, "PNG"):
            mcp_bridge.call_tool("greybox_image", {"path": str(text)})

    def test_host_install_destinations_and_explicit_override(self):
        self.assertEqual(installer.host_skills_dir("codex", self.root), self.root / ".codex/skills")
        self.assertEqual(installer.host_skills_dir("claude-code", self.root), self.root / ".claude/skills")
        self.assertEqual(installer.host_skills_dir("workbuddy", self.root, self.root / "chosen"), self.root / "chosen")
        with self.assertRaisesRegex(ValueError, "explicitly"):
            installer.host_skills_dir("workbuddy", self.root)

    def package(self, destination, version):
        rows = []
        for name in ("SKILL.md", "scripts/greybox.py", "runtime/greybox/cli.py"):
            path = destination / name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("---\nname: greybox-to-multistyle-art\n---\n" + version)
            rows.append({"path": name, "bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        (destination / "MANIFEST.json").write_text(json.dumps({"schema": 1, "name": installer.NAME, "version": version, "files": rows}))

    def test_upgrade_and_rollback_preserve_both_source_versions_by_rename(self):
        incoming, destination = self.root / "incoming", self.root / "host/skills" / installer.NAME
        self.package(incoming, "new"); self.package(destination, "old")
        original_inode = destination.stat().st_ino
        unique = destination / "unique.txt"; unique.write_text("keep")
        result = installer.install(incoming, destination, replace=True)
        restored = installer.rollback(destination, result["previous"])
        self.assertEqual(destination.stat().st_ino, original_inode)
        self.assertEqual(unique.read_text(), "keep")
        self.assertEqual(installer.verified_files(Path(restored["preserved"]))[0]["version"], "new")
        self.assertEqual(restored["copiedBytes"], 0)

    def test_rollback_rejects_foreign_backup(self):
        incoming, destination = self.root / "foreign", self.root / "host/skills" / installer.NAME
        self.package(incoming, "old")
        with self.assertRaisesRegex(ValueError, "exact host"):
            installer.rollback(destination, incoming)

    def test_private_bootstrap_does_not_write_into_skill_or_occupied_directory(self):
        with self.assertRaisesRegex(ValueError, "outside"):
            installer.bootstrap_dependencies(ROOT, ROOT / "private-test-runtime")
        occupied = self.root / "occupied"; occupied.mkdir(); (occupied / "unique.txt").write_text("keep")
        with self.assertRaisesRegex(ValueError, "non-venv"):
            installer.bootstrap_dependencies(ROOT, occupied)
        self.assertEqual((occupied / "unique.txt").read_text(), "keep")
        self.assertFalse((self.root / ".occupied.bootstrap.lock").exists())


if __name__ == "__main__":
    unittest.main()
