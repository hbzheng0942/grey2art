"""Greybox host verification must not require inactive suppliers or DCCs."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/greybox-to-multistyle-art/runtime"))
from greybox import core, host


class ScopedHostTests(unittest.TestCase):
    def test_greybox_needs_no_image_route_or_unrelated_configured_blender(self):
        with tempfile.TemporaryDirectory(prefix="greybox-host-scope-") as temp:
            folder = Path(temp)
            host.configure("codex", {"python": sys.executable, "godot": sys.executable}, config_dir=folder)
            data, path = host._load("codex", folder)
            data["executables"]["blender"] = str(folder / "missing-old-blender")
            core.write(path, data)
            with patch.object(host, "_image_route", side_effect=AssertionError("inactive image service must not be accessed")):
                value = host.verify("codex", folder, scope="greybox", engine="godot")
            self.assertTrue(value["ok"])
            self.assertEqual(value["checks"]["image_route"]["status"], "not_required_for_greybox")
            self.assertFalse(value["host_session_ready"])
            self.assertNotIn("image_generate", [r.get("capability") for r in value["remediation"]])

    def test_legacy_art_verification_keeps_image_requirement(self):
        with tempfile.TemporaryDirectory(prefix="greybox-host-art-") as temp:
            host.configure("codex", {"python": sys.executable}, config_dir=temp)
            value = host.verify("codex", temp)
            self.assertFalse(value["ok"])
            self.assertEqual(value["scope"], "art")

    def test_selected_engine_is_required_for_branch_scope(self):
        with self.assertRaisesRegex(core.WorkflowError, "selected"):
            host.verify("codex", scope="greybox")


if __name__ == "__main__":
    unittest.main()
