"""Isolated installer/rollback recovery, including real process death."""
from contextlib import contextmanager
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

import test_installer_r33 as fixtures

installer = fixtures.installer


class InstallerRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.InstallerR33("test_fresh_source_only_install_does_not_copy_unmanifested_assets")
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.lock = self.f.backups / ".install.lock"

    def test_stale_pid_or_partial_marker_allows_install_and_idempotent_reuse(self):
        self.f.backups.mkdir(parents=True)
        for contents in (b"2147483647", b"", b"greybox-installer-"):
            with self.subTest(contents=contents):
                self.lock.write_bytes(contents)
                self.f.install(replace=True)
                with installer._operation_lock(self.lock, "install"):
                    pass
        self.assertEqual(installer.verified_files(self.f.destination)[0]["version"], "new-version")

    def test_live_legacy_owner_is_preserved(self):
        self.f.backups.mkdir(parents=True)
        child = subprocess.Popen([sys.executable, "-B", "-c", "import time; time.sleep(30)"])
        try:
            self.lock.write_text(str(child.pid))
            with self.assertRaisesRegex(ValueError, "Another install"):
                self.f.install()
            self.assertIsNone(child.poll(), "The liveness probe must not terminate the owner")
            self.assertEqual(self.lock.read_text(), str(child.pid))
            self.assertFalse(self.f.destination.exists())
        finally:
            if child.poll() is None:
                child.terminate()
            child.wait(timeout=5)

    def test_crashed_process_releases_install_ownership_without_unlink(self):
        ready = self.f.root / "ready"
        code = """import importlib.util,sys,time
from pathlib import Path
spec=importlib.util.spec_from_file_location('installer',sys.argv[1])
installer=importlib.util.module_from_spec(spec);spec.loader.exec_module(installer)
with installer._operation_lock(Path(sys.argv[2]),'install'):
    Path(sys.argv[3]).write_text('ready')
    time.sleep(30)
"""
        process = subprocess.Popen([sys.executable, "-B", "-c", code, installer.__file__, str(self.lock), str(ready)],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic() + 10
            while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(.01)
            self.assertTrue(ready.exists())
            with self.assertRaisesRegex(ValueError, "Another install"):
                self.f.install()
            process.terminate()
            process.wait(timeout=5)
            self.assertTrue(self.lock.exists())
            self.assertEqual(self.f.install()["status"], "installed")
        finally:
            if process.poll() is None:
                process.terminate()
            process.communicate(timeout=5)

    def test_rollback_recovers_stale_install_lock(self):
        self.f.install()
        self.f.package(self.f.source, "later-version")
        previous = self.f.install(replace=True)["previous"]
        self.lock.write_text("2147483647")
        result = installer.rollback(self.f.destination, Path(previous))
        self.assertEqual(result["status"], "rolled-back")
        self.assertEqual(installer.verified_files(self.f.destination)[0]["version"], "new-version")
        self.assertEqual(installer.verified_files(result["preserved"])[0]["version"], "later-version")

    def test_runtime_that_arrives_before_lock_ownership_is_not_deleted_on_failure(self):
        runtime = self.f.root / "runtime"
        requirements = self.f.source / "connectors/workbuddy/requirements.txt"
        requirements.parent.mkdir(parents=True)
        requirements.write_text("requests\n", encoding="utf-8")
        actual_lock = installer._operation_lock
        @contextmanager
        def previous_owner_finishes(path, operation):
            runtime.mkdir()
            (runtime / "pyvenv.cfg").write_text("synthetic existing runtime")
            (runtime / "keep.txt").write_text("previous owner's work")
            executable = runtime / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            executable.parent.mkdir()
            executable.write_text("synthetic interpreter; never executed")
            with actual_lock(path, operation):
                yield
        with patch.object(installer, "_operation_lock", previous_owner_finishes), \
             patch.object(installer, "probe_python", return_value={"ok": True}), \
             patch.object(installer, "select_python", return_value={"path": sys.executable}), \
             patch.object(installer.subprocess, "run", side_effect=OSError("synthetic failure")):
            with self.assertRaisesRegex(ValueError, "bootstrap failed"):
                installer.bootstrap_dependencies(self.f.source, runtime)
        self.assertEqual((runtime / "keep.txt").read_text(), "previous owner's work")
        with actual_lock(self.f.root / ".runtime.bootstrap.lock", "bootstrap"):
            pass


if __name__ == "__main__":
    unittest.main()
