"""Deterministic grouping and broker-preserving install regressions; offline."""
import copy
import errno
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "skills/greybox-to-multistyle-art/runtime"))
from greybox import reference_boards as boards
spec = importlib.util.spec_from_file_location("board_entry_installer", ROOT / "skills/greybox-to-multistyle-art/scripts/install.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class BoardGroups(unittest.TestCase):
    def spec(self):
        return {"schema": 1, "kind": "reference-board-plan-input", "channel_size": [1536, 1024],
                "size_source_ref": "Offline replay of observed canvas dimensions", "coherent_asset_groups": True,
                "subject_fill_ratio": .65,
                "views": [{"asset_id": asset, "view_id": role, "role": role, "projected_aspect": 1.0,
                           "min_subject_long_edge_px": 300, "min_subject_short_edge_px": 250}
                          for role in ("front", "left", "back") for asset in ("vessel-a", "vessel-b")]}

    def test_interleaved_three_view_assets_are_not_split_by_backfill(self):
        result = boards.plan(self.spec())
        self.assertEqual([len(page["slots"]) for page in result["boards"]], [3, 3])
        self.assertEqual([{s["asset_id"] for s in p["slots"]} for p in result["boards"]],
                         [{"vessel-a"}, {"vessel-b"}])
        self.assertEqual([s["role"] for s in result["boards"][0]["slots"]], ["front", "left", "back"])

    def test_conservative_occupancy_changes_estimate_without_weakening_requirements(self):
        conservative = self.spec()
        expected = copy.deepcopy(conservative["views"])
        liberal = copy.deepcopy(conservative)
        liberal["subject_fill_ratio"] = .8
        low, high = boards.plan(conservative), boards.plan(liberal)
        self.assertLess(low["boards"][0]["slots"][0]["estimated_subject_size"][0],
                        high["boards"][0]["slots"][0]["estimated_subject_size"][0])
        self.assertEqual(conservative["views"], expected)
        self.assertEqual(low["boards"][0]["slots"][0]["requirements"], high["boards"][0]["slots"][0]["requirements"])

    def test_impossible_joint_views_remain_explicit_individual_pages_for_master_check(self):
        inputs = self.spec()
        for row in inputs["views"]:
            row["min_subject_long_edge_px"] = 600
        result = boards.plan(inputs)
        self.assertEqual(result["summary"]["ready_view_count"], 6)
        self.assertEqual([len(page["slots"]) for page in result["boards"]], [1] * 6)
        self.assertTrue(all(slot["requirements"]["min_subject_long_edge_px"] == 600
                            for page in result["boards"] for slot in page["slots"]))


class InstallerBroker(unittest.TestCase):
    def test_existing_directory_eexist_uses_the_original_broker(self):
        original = Path.mkdir
        calls = []
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)
            def shim(path, mode=0o777, parents=False, exist_ok=False):
                calls.append(str(path))
                # WorkBuddy's observed shim omits exist_ok in its request.
                return original(path, mode=mode, parents=parents, exist_ok=False)
            with patch.object(Path, "mkdir", shim):
                installer.ensure_directory(target)
                installer.ensure_directory(target / "child")
                installer.ensure_directory(target / "child")
            self.assertGreaterEqual(len(calls), 3)
            self.assertTrue((target / "child").is_dir())
        self.assertIs(Path.mkdir, original)

    def test_permission_and_file_errors_are_not_swallowed(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "file"
            path.write_text("not a directory")
            with self.assertRaises(FileExistsError):
                installer.ensure_directory(path)
            with patch.object(Path, "mkdir", side_effect=PermissionError(errno.EACCES, "denied")):
                with self.assertRaises(PermissionError):
                    installer.ensure_directory(Path(folder))


if __name__ == "__main__":
    unittest.main()
