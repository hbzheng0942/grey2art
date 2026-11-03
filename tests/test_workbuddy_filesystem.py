"""Broker-preserving filesystem compatibility; no host configuration changes."""
import errno
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/greybox-to-multistyle-art/runtime"))
from greybox import core


class WorkBuddyFilesystem(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_existing_directory_eexist_still_visits_broker_and_allows_json_write(self):
        sentinel = self.root / "sentinel"
        sentinel.write_bytes(b"preserve existing content")
        before = sentinel.read_bytes(), sentinel.stat()
        mkdir = Path.mkdir
        calls = []

        def broker(path, *args, **kwargs):
            calls.append((path, kwargs))
            if path.exists():
                raise FileExistsError(errno.EEXIST, "broker returned EEXIST", str(path))
            return mkdir(path, *args, **kwargs)

        with patch.object(Path, "mkdir", broker):
            core.write(self.root / "record.json", {"actual": "new task record"})
        self.assertEqual(core.read(self.root / "record.json"), {"actual": "new task record"})
        self.assertTrue(calls)
        self.assertTrue(calls[0][1]["exist_ok"])
        self.assertEqual((sentinel.read_bytes(), sentinel.stat()), before)

    def test_existing_regular_file_is_never_treated_as_directory(self):
        target = self.root / "existing-file"
        target.write_bytes(b"untouched")
        with self.assertRaises(FileExistsError):
            core.ensure_directory(target)
        self.assertEqual(target.read_bytes(), b"untouched")

    def test_os_workflow_lock_preserves_existing_directory_broker_behavior(self):
        mkdir = Path.mkdir
        def broker(path, *args, **kwargs):
            if path.is_dir():
                raise FileExistsError(errno.EEXIST, "broker returned EEXIST", str(path))
            return mkdir(path, *args, **kwargs)
        with patch.object(Path, "mkdir", broker):
            with core.locked(self.root):
                with self.assertRaises(core.WorkflowLockBusy):
                    with core.locked(self.root):
                        pass
            with core.locked(self.root):
                pass

    def test_host_permission_denial_remains_failure_for_an_existing_directory(self):
        with patch.object(Path, "mkdir", side_effect=PermissionError(errno.EACCES, "host policy denied")):
            with self.assertRaises(PermissionError):
                core.write(self.root / "record.json", {"must_not": "write"})
        self.assertFalse((self.root / "record.json").exists())

    def test_unrelated_filesystem_errors_are_not_suppressed(self):
        for failure in (OSError(errno.EIO, "broker I/O failure"), FileExistsError(errno.EIO, "unexpected code")):
            with self.subTest(failure=failure), patch.object(Path, "mkdir", side_effect=failure):
                with self.assertRaises(OSError):
                    core.ensure_directory(self.root)

    def test_missing_directory_and_exclusive_file_creation_keep_native_semantics(self):
        directory = self.root / "new/nested"
        core.ensure_directory(directory)
        path = directory / "exclusive-claim"
        with path.open("x") as stream:
            stream.write("original")
        core.ensure_directory(directory)
        with self.assertRaises(FileExistsError):
            path.open("x")
        self.assertEqual(path.read_text(), "original")
