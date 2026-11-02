"""Scheduler fairness, crash reporting and UTF-8 contracts; no remote I/O."""
from collections import Counter
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
SKILL = Path(__file__).resolve().parents[1] / "skills/greybox-to-multistyle-art"
sys.path.insert(0, str(SKILL / "runtime"))
from greybox import execution, execution_capacity, execution_cli, host_execution, image_jobs
from greybox.execution_process import atomic_json, read_json


class Clock:
    def __init__(self):
        self.now = 1024.
    def time(self):
        return self.now
    def sleep(self, seconds):
        self.now += seconds


class Finished:
    pid = 12345
    def poll(self):
        return 0
    def wait(self, **kwargs):
        return 0


class ExecutionReliabilityTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path, self.state = self.root / "queue.json", self.root / "state"
        self.queue = {"schema": 1, "kind": "greybox-execution-queue",
                      "pools": {"shared": {"capacity": 3, "source_ref": "synthetic-offline"}},
                      "sources": [{"kind": "image", "path": str(self.root / "ledger"),
                                   "pools": {"fixture": "shared"}}],
                      "limits": {"tick_interval": .03125, "poll_interval": .125}}
        atomic_json(self.path, self.queue)

    def test_rate_limited_status_polling_does_not_starve_later_tasks(self):
        clock, counts = Clock(), Counter()
        tasks = {str(i): {"id": str(i), "state": "active", "action": "status", "pool": "shared", "next_at": 0}
                 for i in range(3)}
        class Backend:
            @staticmethod
            def scan(source):
                return deepcopy(list(tasks.values()))
            @staticmethod
            def prepare(source, tid, action, lease):
                tasks[tid]["lease"] = deepcopy(lease)
                return {"source": source, "id": tid, "action": action,
                        "lease": lease, "request_hash": "synthetic"}
            @staticmethod
            def commit(source, ticket, outcome):
                tasks[ticket["id"]].pop("lease", None)
                tasks[ticket["id"]]["next_at"] = clock.time() + .125
                return {}
        self.queue["pools"]["shared"]["rate_limits"] = {"status": 16}
        atomic_json(self.path, self.queue)
        dispatch_times = []
        def launch(ticket):
            counts[ticket["id"]] += 1
            dispatch_times.append(clock.time())
            with execution_capacity.CapacityStore(self.state / "capacity.sqlite3", {}) as store:
                execution._commit(ticket, {"ok": True, "result": {}}, store)
            return Finished()
        with patch.object(execution, "_backend", return_value=Backend), \
             patch.object(execution, "_launch", side_effect=launch), \
             patch.object(execution, "time", clock), patch.object(execution_capacity, "time", clock):
            result = execution.run(self.path, self.state, max_seconds=1)
        self.assertEqual(result["phase"], "bounded_exit")
        self.assertGreaterEqual(min(counts[tid] for tid in tasks), 4)
        self.assertLessEqual(max(counts.values()) - min(counts.values()), 1)
        self.assertTrue(all(b - a >= 1 / 16 for a, b in zip(dispatch_times, dispatch_times[1:])),
                        "Fairness must preserve the actual account QPS limit")

    def test_fatal_error_publishes_failed_status_without_private_message(self):
        for during_start in (True, False):
            with self.subTest(during_start=during_start):
                calls = [RuntimeError("private-token-never-publish")] if during_start else [
                    ([], [{"code": "SOURCE_UNAVAILABLE"}]), RuntimeError("private-token-never-publish")]
                # Keep the first loop active for a later-loop failure.
                pending = (self.queue["sources"][0], {"id": "waiting", "state": "unknown",
                           "pool": "shared", "action": "status", "next_at": 10**20})
                if not during_start:
                    calls[0] = ([pending], [])
                with patch.object(execution, "_scan", side_effect=calls):
                    with self.assertRaisesRegex(RuntimeError, "private-token"):
                        execution.run(self.path, self.state)
                result = execution.status(self.path, self.state)
                self.assertEqual(result["phase"], "failed")
                self.assertFalse(result["running"])
                self.assertEqual(result["error"]["type"], "RuntimeError")
                self.assertNotIn("private-token", json.dumps(result))

    def test_start_reports_an_immediate_coordinator_failure(self):
        statuses = [{"running": False}, {"pid": Finished.pid, "phase": "failed", "running": False}]
        with patch.object(execution, "status", side_effect=statuses), \
             patch.object(execution, "spawn", return_value=Finished()):
            result = execution.start(self.path, self.state)
        self.assertFalse(result["started"])
        self.assertEqual(result["code"], "EXECUTOR_START_FAILED")

    def test_image_and_native_job_lock_contention_is_a_typed_error(self):
        with image_jobs._lock(self.root):
            with self.assertRaises(image_jobs.ImageError) as error:
                with image_jobs._lock(self.root):
                    pass
        self.assertEqual(error.exception.code, "IMAGE_JOB_BUSY")
        self.assertEqual(error.exception.category, "local")
        with image_jobs._lock(self.root):
            pass

    def test_native_cli_reads_utf8_even_under_ansi_defaults(self):
        request = self.root / "request.json"
        request.write_text(json.dumps({"tool_arguments": {"prompt": "陶瓷风格"}}, ensure_ascii=False), encoding="utf-8")
        original = Path.read_text
        def ansi_default(path, *args, **kwargs):
            kwargs.setdefault("encoding", "cp1252")
            return original(path, *args, **kwargs)
        with patch.object(Path, "read_text", ansi_default), patch("sys.stdout", new=io.StringIO()):
            code = execution_cli.main(["native-reserve", "--file", str(request), "--job-dir", str(self.root / "job"),
                                       "--tool", "synthetic-tool", "--source-ref", "offline"])
        self.assertEqual(code, 0)
        _, data = host_execution._job(self.root / "job")
        self.assertEqual(data["request"]["tool_arguments"]["prompt"], "陶瓷风格")

    def test_actual_cli_preserves_non_ascii_input_with_utf8_mode_disabled(self):
        request = self.root / "request.json"
        request.write_text(json.dumps({"tool_arguments": {"prompt": "纸艺城堡"}}, ensure_ascii=False), encoding="utf-8")
        result = subprocess.run([sys.executable, "-B", str(SKILL / "scripts/executor.py"), "native-reserve",
                                 "--file", str(request), "--job-dir", str(self.root / "native"),
                                 "--tool", "synthetic-tool", "--source-ref", "offline"],
                                env={**os.environ, "PYTHONUTF8": "0", "PYTHONIOENCODING": "cp1252"},
                                capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        _, data = host_execution._job(self.root / "native")
        self.assertEqual(data["request"]["tool_arguments"]["prompt"], "纸艺城堡")


if __name__ == "__main__":
    unittest.main()
