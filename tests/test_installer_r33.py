"""Source-only installation, symlink preservation and failure rollback; no user install."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1] / "skills/greybox-to-multistyle-art"
spec = importlib.util.spec_from_file_location("greybox_installer_r33", ROOT / "scripts/install.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallerR33(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="greybox-installer-r33-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "incoming"
        self.destination = self.root / "codex/skills" / installer.NAME
        self.backups = self.root / "codex/skill-backups" / installer.NAME
        self.package(self.source, "new-version")

    def package(self, source, version):
        rows = []
        for name, text in (("SKILL.md", "---\nname: greybox-to-multistyle-art\ndescription: Test fixture only.\n---\n" + version),
                           ("scripts/greybox.py", "# synthetic CLI " + version),
                           ("runtime/greybox/cli.py", "# synthetic runtime " + version)):
            path = source / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text)
            rows.append({"path": name, "bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        (source / "MANIFEST.json").write_text(json.dumps({"schema": 1, "name": installer.NAME, "version": version, "files": rows}))

    def backup_entries(self):
        return [p for p in self.backups.glob("*") if not p.name.startswith(".")]

    def install(self, replace=False):
        return installer.install(self.source, self.destination, replace)

    def link(self, target):
        self.destination.parent.mkdir(parents=True, exist_ok=True)
        self.destination.symlink_to(target, target_is_directory=True)

    def test_fresh_source_only_install_does_not_copy_unmanifested_assets(self):
        (self.source / "unique-unshipped-model.glb").write_bytes(b"not in the package")
        result = self.install()
        self.assertEqual(result["status"], "installed")
        self.assertFalse(self.destination.is_symlink())
        self.assertFalse((self.destination / "unique-unshipped-model.glb").exists())
        self.assertEqual(installer.verified_files(self.destination)[0]["version"], "new-version")
        self.assertEqual(self.backup_entries(), [])

    def test_symlink_itself_moves_outside_discovery_without_touching_target(self):
        old = self.root / "historical-product"; old.mkdir(); preserved = old / "UNIQUE.txt"; preserved.write_text("old target")
        inode, payload = preserved.stat().st_ino, preserved.read_bytes()
        self.link(old)
        result = self.install(replace=True)
        previous = Path(result["previous"])
        self.assertTrue(previous.is_symlink())
        self.assertEqual(os.readlink(previous), str(old))
        self.assertFalse(previous.is_relative_to(self.destination.parent))
        self.assertEqual(preserved.stat().st_ino, inode); self.assertEqual(preserved.read_bytes(), payload)
        self.assertEqual(installer.verified_files(self.destination)[0]["version"], "new-version")

    def test_broken_symlink_is_preserved_without_reading_its_target(self):
        self.link(self.root / "missing-target")
        result = self.install(replace=True)
        self.assertTrue(Path(result["previous"]).is_symlink())
        self.assertFalse(Path(result["previous"]).exists())

    def test_relative_symlink_preserves_literal_link_for_restoration(self):
        self.link("../../historical-product")
        result = self.install(replace=True)
        self.assertEqual(os.readlink(result["previous"]), "../../historical-product")

    def test_replace_flag_required_for_an_existing_link(self):
        self.link(self.root / "missing")
        with self.assertRaisesRegex(ValueError, "--replace"):
            self.install()
        self.assertTrue(self.destination.is_symlink()); self.assertEqual(self.backup_entries(), [])

    def test_locally_edited_verified_install_moves_intact_without_a_snapshot(self):
        self.package(self.destination, "old-version")
        changed = self.destination / "runtime/greybox/cli.py"; changed.write_text("unique local edit")
        unique = self.destination / "local-notes.md"; unique.write_text("unique untracked work")
        old_inode, unique_inode = self.destination.stat().st_ino, unique.stat().st_ino
        result = self.install(replace=True); previous = Path(result["previous"])
        self.assertEqual(previous.stat().st_ino, old_inode)
        self.assertEqual((previous / "local-notes.md").stat().st_ino, unique_inode)
        self.assertEqual((previous / "runtime/greybox/cli.py").read_text(), "unique local edit")
        self.assertEqual((previous / "local-notes.md").read_text(), "unique untracked work")

    def test_unmanifested_recognizable_skill_is_preserved(self):
        self.destination.mkdir(parents=True)
        (self.destination / "SKILL.md").write_text("---\nname: 'greybox-to-multistyle-art'\ndescription: Old.\n---\nUnique")
        result = self.install(replace=True)
        self.assertIn("Unique", (Path(result["previous"]) / "SKILL.md").read_text())

    def test_unknown_regular_directory_is_refused(self):
        self.destination.mkdir(parents=True)
        unique = self.destination / "not-a-skill.txt"; unique.write_text("preserve")
        with self.assertRaisesRegex(ValueError, "unknown non-skill"):
            self.install(replace=True)
        self.assertEqual(unique.read_text(), "preserve"); self.assertEqual(self.backup_entries(), [])

    def test_identical_package_is_idempotent_and_creates_no_backup(self):
        self.install()
        notes = self.destination / "local-notes.md"; notes.write_text("untouched")
        inode = self.destination.stat().st_ino
        result = self.install(replace=True)
        self.assertEqual(result["status"], "already-installed"); self.assertEqual(result["copiedBytes"], 0)
        self.assertEqual(self.destination.stat().st_ino, inode)
        self.assertEqual(notes.read_text(), "untouched"); self.assertEqual(self.backup_entries(), [])

    def test_same_version_changed_hash_is_preserved_and_updated(self):
        self.package(self.destination, "new-version")
        (self.destination / "SKILL.md").write_text("---\nname: greybox-to-multistyle-art\n---\nlocally changed")
        result = self.install(replace=True)
        self.assertEqual(result["status"], "installed")
        self.assertIn("locally changed", (Path(result["previous"]) / "SKILL.md").read_text())

    def test_stage_swap_failure_restores_original_symlink_and_removes_scratch(self):
        self.link("../../old-relative-target")
        actual = installer.os.replace
        def fail_stage(source, target):
            if Path(source).name.startswith("." + installer.NAME + "-install-"):
                raise OSError("synthetic stage swap failure")
            return actual(source, target)
        with patch.object(installer.os, "replace", side_effect=fail_stage):
            with self.assertRaisesRegex(OSError, "stage swap failure"):
                self.install(replace=True)
        self.assertTrue(self.destination.is_symlink())
        self.assertEqual(os.readlink(self.destination), "../../old-relative-target")
        self.assertEqual(self.backup_entries(), [])
        self.assertFalse((self.backups / ".install.lock").exists())
        self.assertFalse(list(self.destination.parent.glob(".*-install-*")))

    def test_stage_swap_failure_restores_edited_regular_skill_inode(self):
        self.package(self.destination, "old-version")
        inode = self.destination.stat().st_ino
        actual = installer.os.replace
        def fail_stage(source, target):
            if Path(source).name.startswith("." + installer.NAME + "-install-"):
                raise OSError("synthetic stage swap failure")
            return actual(source, target)
        with patch.object(installer.os, "replace", side_effect=fail_stage), self.assertRaises(OSError):
            self.install(replace=True)
        self.assertEqual(self.destination.stat().st_ino, inode)
        self.assertEqual(installer.verified_files(self.destination)[0]["version"], "old-version")

    def test_invalid_source_does_not_move_or_modify_existing_install(self):
        self.link("../../original-target")
        (self.source / "SKILL.md").write_text("changed after manifest")
        with self.assertRaisesRegex(ValueError, "checksum"):
            self.install(replace=True)
        self.assertEqual(os.readlink(self.destination), "../../original-target")
        self.assertEqual(self.backup_entries(), [])

    def test_backup_symlink_into_host_discovery_is_refused(self):
        self.destination.parent.mkdir(parents=True)
        (self.root / "codex/skill-backups").symlink_to(self.destination.parent, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "outside the host"):
            self.install()
        self.assertFalse(self.destination.exists())

    def test_other_install_lock_is_preserved(self):
        self.backups.mkdir(parents=True)
        lock = self.backups / ".install.lock"; lock.write_text("other process")
        with self.assertRaisesRegex(ValueError, "Another install"):
            self.install()
        self.assertEqual(lock.read_text(), "other process")

    def test_source_symlink_and_manifest_alias_are_refused(self):
        alias = self.root / "incoming-link"; alias.symlink_to(self.source, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "regular directory"):
            installer.verified_files(alias)
        manifest = json.loads((self.source / "MANIFEST.json").read_text())
        manifest["files"][1]["path"] = "scripts//greybox.py"
        (self.source / "MANIFEST.json").write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "Unsafe"):
            installer.verified_files(self.source)

    def test_source_package_size_is_bounded_before_copy(self):
        manifest = json.loads((self.source / "MANIFEST.json").read_text())
        manifest["files"][0]["bytes"] = installer.MAX_PACKAGE_BYTES + 1
        (self.source / "MANIFEST.json").write_text(json.dumps(manifest))
        with self.assertRaisesRegex(ValueError, "small-package"):
            self.install()
        self.assertFalse(self.destination.exists())


if __name__ == "__main__":
    unittest.main()
