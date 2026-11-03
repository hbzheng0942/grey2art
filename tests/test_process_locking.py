"""Real-process locking/liveness regressions, including Windows CI."""
import errno
import io
import json
import multiprocessing
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/greybox-to-multistyle-art/runtime"))
from greybox import core, execution, execution_process
from greybox.execution_capacity import CapacityStore


def hold_lock(directory, entered):
    with core.locked(directory):
        entered.set()
        # Do not terminate a process while it owns an Event's internal lock.
        time.sleep(15)


def contend(directory, start, active, output):
    start.wait(10)
    acquired = 0
    deadline = time.monotonic() + 10
    try:
        while acquired < 10 and time.monotonic() < deadline:
            try:
                with core.locked(directory):
                    with active.get_lock():
                        active.value += 1
                        if active.value != 1:
                            raise AssertionError("overlapping critical sections")
                    time.sleep(.002)
                    with active.get_lock():
                        active.value -= 1
                    acquired += 1
            except core.WorkflowLockBusy:
                time.sleep(.001)
        output.put({"acquired": acquired})
    except Exception as error:
        output.put({"error": type(error).__name__, "message": str(error)})


class ProcessLockingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.ctx = multiprocessing.get_context("spawn")

    def test_live_child_survives_status_and_capacity_owner_checks(self):
        child = subprocess.Popen([sys.executable, "-B", "-c", "import time; time.sleep(30)"])
        try:
            queue = self.root / "queue.json"
            _, _, directory = execution._location(queue, self.root / "state")
            execution_process.atomic_json(directory / "status.json",
                {"phase": "running", "pid": child.pid, "heartbeat": time.time()})
            with execution_process.exclusive(directory / ".owner.lock"):
                for _ in range(5):
                    self.assertTrue(execution.status(queue, self.root / "state")["running"])
                    self.assertTrue(core.process_alive(child.pid))
            with CapacityStore(self.root / "capacity.sqlite3", {"a": {"capacity": 1, "source_ref": "offline-test"}}) as store:
                self.assertTrue(store.claim_pending("task", "a", "ledger", "owner", child.pid))
                self.assertFalse(store.claim_pending("task", "a", "ledger", "contender", os.getpid()))
            self.assertIsNone(child.poll(), "Liveness checks must never terminate the owner")
        finally:
            if child.poll() is None:
                child.terminate()
            child.wait(timeout=5)
        self.assertFalse(execution_process.alive(child.pid))

    def test_invalid_pids_are_never_signalled(self):
        with patch.object(execution_process.os, "kill") as kill:
            for pid in (None, "invalid", 0, -1):
                self.assertFalse(execution_process.alive(pid))
            kill.assert_not_called()

    def test_windows_atomic_replace_retries_without_exposing_partial_data(self):
        source, target = self.root / "new", self.root / "current"
        source.write_bytes(b"new document")
        target.write_bytes(b"original")
        attempts = []
        actual_replace = os.replace
        def replace(a, b):
            attempts.append(1)
            self.assertEqual(target.read_bytes(), b"original")
            if len(attempts) < 3:
                error = PermissionError("synthetic sharing violation")
                error.winerror = 5
                raise error
            return actual_replace(a, b)
        with patch.object(execution_process, "os", SimpleNamespace(name="nt", replace=replace)):
            execution_process.replace_file(source, target)
        self.assertEqual(len(attempts), 3)
        self.assertEqual(target.read_bytes(), b"new document")
        self.assertFalse(source.exists())

    def test_permanent_windows_permission_error_has_bounded_retries(self):
        error = PermissionError("synthetic permanent denial")
        error.winerror = 5
        with patch.object(execution_process, "os", SimpleNamespace(name="nt")), \
             patch.object(execution_process.os, "replace", side_effect=error, create=True) as replace, \
             patch.object(execution_process.time, "monotonic", side_effect=[0., .01, .02]), \
             patch.object(execution_process.time, "sleep"):
            with self.assertRaises(PermissionError) as raised:
                execution_process.replace_file("source", "target", retry_timeout=.02)
        self.assertIs(raised.exception, error)
        self.assertEqual(replace.call_count, 2)

    def test_nonsharing_errors_do_not_retry(self):
        for platform, code in (("posix", 5), ("nt", 87)):
            error = PermissionError("unrelated permission error")
            error.winerror = code
            with self.subTest(platform=platform, code=code), \
                 patch.object(execution_process, "os", SimpleNamespace(name=platform)), \
                 patch.object(execution_process.os, "replace", side_effect=error, create=True) as replace:
                with self.assertRaises(PermissionError):
                    execution_process.replace_file("source", "target")
                self.assertEqual(replace.call_count, 1)

    @unittest.skipUnless(os.name == "nt", "Real Windows reader-handle sharing behavior")
    def test_atomic_json_waits_for_real_windows_reader_to_close(self):
        target = self.root / "status.json"
        execution_process.atomic_json(target, {"revision": 1})
        started, finished, errors = threading.Event(), threading.Event(), []
        def write():
            started.set()
            try:
                execution_process.atomic_json(target, {"revision": 2})
            except Exception as error:
                errors.append(error)
            finally:
                finished.set()
        worker = threading.Thread(target=write)
        try:
            with target.open("rb"):
                worker.start()
                self.assertTrue(started.wait(2))
                self.assertFalse(finished.wait(.05), "Replacement must wait for the open reader")
        finally:
            if worker.ident is not None:
                worker.join(timeout=3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(execution_process.read_json(target), {"revision": 2})

    def test_windows_acquires_byte_lock_before_inspecting_file_contents(self):
        class LockFile(io.BytesIO):
            def fileno(self):
                return 17
            def read(self, *args):
                raise AssertionError("contender read a protected byte before ownership")
            def write(self, *args):
                raise AssertionError("contender wrote a protected byte before ownership")
        calls = []
        msvcrt = SimpleNamespace(LK_NBLCK=2, locking=lambda *args: calls.append(args))
        with patch.object(execution_process, "os", SimpleNamespace(name="nt")), \
             patch.dict(sys.modules, {"msvcrt": msvcrt}), \
             patch.object(Path, "open", return_value=LockFile()):
            with execution_process.exclusive(self.root / "lock"):
                pass
        self.assertEqual(calls, [(17, 2, 1)])

    @unittest.skipIf(os.name == "nt", "POSIX permission errors; Windows uses process handles")
    def test_permission_denied_is_not_proof_of_death(self):
        with patch.object(execution_process.os, "kill", side_effect=PermissionError(errno.EPERM, "denied")):
            self.assertTrue(execution_process.alive(123))

    def test_empty_or_partial_metadata_is_recovered_without_unlinking(self):
        path = self.root / ".workflow.lock"
        for contents in (b"", b'{"pid":', json.dumps({"pid": 2147483647}).encode()):
            path.write_bytes(contents)
            with patch.object(Path, "unlink", side_effect=AssertionError("lock inode must remain stable")):
                with core.locked(self.root):
                    with self.assertRaises(core.WorkflowLockBusy):
                        with core.locked(self.root):
                            self.fail("recursive independent owner acquired the lock")
                with core.locked(self.root):
                    pass
            self.assertTrue(path.exists())

    def test_workflow_lock_rejects_hardlink_before_writing(self):
        victim = self.root / "unrelated.txt"
        victim.write_bytes(b"preserve these bytes")
        os.link(victim, self.root / ".workflow.lock")
        with self.assertRaisesRegex(ValueError, "single-link"):
            with core.locked(self.root):
                self.fail("acquired an aliased lock")
        self.assertEqual(victim.read_bytes(), b"preserve these bytes")

    def test_live_legacy_pid_is_not_taken_over(self):
        core.write(self.root / ".workflow.lock", {"pid": os.getpid()})
        with self.assertRaises(core.WorkflowLockBusy):
            with core.locked(self.root):
                self.fail("legacy owner was stolen")

    def test_reacquiring_lock_does_not_rewrite_its_marker(self):
        with core.locked(self.root):
            pass
        path = self.root / ".workflow.lock"
        before = path.read_bytes(), path.stat().st_mtime_ns
        with core.locked(self.root):
            pass
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)

    def test_process_termination_releases_lock_without_deleting_metadata(self):
        entered = self.ctx.Event()
        worker = self.ctx.Process(target=hold_lock, args=(self.root, entered))
        worker.start()
        try:
            self.assertTrue(entered.wait(10))
            with self.assertRaises(core.WorkflowLockBusy):
                with core.locked(self.root):
                    pass
            worker.terminate()
            worker.join(timeout=5)
            self.assertFalse(worker.is_alive())
            self.assertTrue((self.root / ".workflow.lock").exists())
            with core.locked(self.root):
                pass
        finally:
            if worker.is_alive():
                worker.terminate()
            worker.join(timeout=5)

    def test_six_processes_recover_stale_lock_without_overlapping(self):
        core.write(self.root / ".workflow.lock", {"pid": 2147483647})
        start, active, output = self.ctx.Event(), self.ctx.Value("i", 0), self.ctx.Queue()
        workers = [self.ctx.Process(target=contend, args=(self.root, start, active, output)) for _ in range(6)]
        try:
            for worker in workers:
                worker.start()
            start.set()
            results = [output.get(timeout=15) for _ in workers]
            self.assertEqual(results, [{"acquired": 10}] * 6)
            for worker in workers:
                worker.join(timeout=5)
                self.assertEqual(worker.exitcode, 0)
            self.assertEqual(active.value, 0)
        finally:
            for worker in workers:
                if worker.is_alive():
                    worker.terminate()
                worker.join(timeout=5)
            output.close()


if __name__ == "__main__":
    unittest.main()
