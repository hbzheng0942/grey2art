"""Behavioral tests of the shipped scheduler; no billable or external traffic."""
from __future__ import annotations

import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import multiprocessing
import os
from pathlib import Path
import subprocess
import signal
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
SKILL = Path(__file__).resolve().parents[1] / "skills" / "greybox-to-multistyle-art"
sys.path.insert(0, str(SKILL / "runtime"))
from greybox import execution, image_execution, image_jobs
from greybox.execution_capacity import CapacityStore
from greybox.execution_process import atomic_json, read_json
from greybox.execution_process import exclusive


def capacity_contender(path, start, output, index):
    with CapacityStore(path, {"account": {"capacity": 3, "source_ref": "synthetic-concurrency-policy"}}) as store:
        start.wait(5)
        got = store.claim_pending("job-" + str(index), "account", "synthetic-project-" + str(index),
                                  "action-" + str(index), os.getpid())
        output.put((index, got))


def rate_contender(path, start, output):
    with CapacityStore(path, {"account": {"capacity": 3, "source_ref": "synthetic-rate-policy",
                                         "rate_limits": {"submit": .1}}}) as store:
        start.wait(5)
        output.put(store.allow_action("account", "submit"))


class CapacityTests(unittest.TestCase):
    def test_real_processes_share_capacity_without_remote_lease_expiry(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = str(Path(temporary) / "capacity.sqlite3")
            pools = {"account": {"capacity": 3, "source_ref": "synthetic-concurrency-policy"}}
            with CapacityStore(path, pools):
                pass
            ctx = multiprocessing.get_context("spawn")
            start, output = ctx.Event(), ctx.Queue()
            processes = [ctx.Process(target=capacity_contender, args=(path, start, output, i)) for i in range(6)]
            try:
                for process in processes:
                    process.start()
                start.set()
                results = [output.get(timeout=10) for _ in processes]
                for process in processes:
                    process.join(timeout=5)
                    self.assertEqual(process.exitcode, 0)
                self.assertEqual(sum(got for _, got in results), 3)
                with CapacityStore(path, pools) as store:
                    self.assertEqual(store.snapshot()["account"]["occupied"], 3)
                    self.assertFalse(store.reserve("new", "account", "another-project"))
                    winner = next(index for index, got in results if got)
                    store.release("job-" + str(winner))  # Explicit synthetic remote terminal.
                    self.assertTrue(store.reserve("new", "account", "another-project"))
            finally:
                for process in processes:
                    if process.is_alive():
                        process.kill()
                    process.join(timeout=5)
                output.close()

    def test_dispatch_claim_cannot_be_stolen_by_another_live_queue(self):
        with tempfile.TemporaryDirectory() as temporary:
            with CapacityStore(Path(temporary) / "capacity.sqlite3", {"a": {"capacity": 1, "source_ref": "fixture"}}) as store:
                self.assertTrue(store.claim_pending("job", "a", "project/job", "first", os.getpid()))
                self.assertFalse(store.claim_pending("job", "a", "project/job", "second", os.getpid()))
                store.release_claim("job", "second")
                self.assertTrue(store.contains("job"))
                store.release_claim("job", "first")
                self.assertFalse(store.contains("job"))

    def test_adoption_preserves_unknown_even_above_reconfigured_capacity(self):
        with tempfile.TemporaryDirectory() as temporary:
            with CapacityStore(Path(temporary) / "capacity.sqlite3", {"a": {"capacity": 1, "source_ref": "fixture"}}) as store:
                self.assertTrue(store.reserve("known-running", "a", "project/one", adopt=True))
                self.assertTrue(store.reserve("unknown", "a", "project/two", adopt=True))
                self.assertEqual(store.snapshot()["a"]["occupied"], 2)
                self.assertFalse(store.reserve("new", "a", "project/three"))
                with self.assertRaises(ValueError):
                    store.reserve("unknown", "other-account", "project/two", adopt=True)

    def test_capacity_provenance_and_conflicts_are_explicit(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "capacity.sqlite3"
            with CapacityStore(path, {"a": {"capacity": 2, "source_ref": "fixture"}}) as store:
                store.cooldown("a", .15)
                self.assertFalse(store.reserve("new", "a", "project"))
            with self.assertRaises(ValueError):
                CapacityStore(path, {"a": {"capacity": 3, "source_ref": "conflicting-queue"}})

    def test_request_rate_is_atomic_across_queues_and_method_specific(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = str(Path(temporary) / "capacity.sqlite3")
            policy = {"account": {"capacity": 3, "source_ref": "synthetic-rate-policy", "rate_limits": {"submit": .1}}}
            with CapacityStore(path, policy):
                pass
            ctx = multiprocessing.get_context("spawn")
            start, output = ctx.Event(), ctx.Queue()
            processes = [ctx.Process(target=rate_contender, args=(path, start, output)) for _ in range(4)]
            try:
                for process in processes:
                    process.start()
                start.set()
                self.assertEqual(sum(output.get(timeout=10) for _ in processes), 1)
                for process in processes:
                    process.join(timeout=5)
                    self.assertEqual(process.exitcode, 0)
                with CapacityStore(path, policy) as store:
                    self.assertTrue(store.allow_action("account", "status"))
                    store.cooldown_action("account", "status", .5)
                    self.assertFalse(store.allow_action("account", "status"))
                    self.assertTrue(store.allow_action("account", "fetch"))
            finally:
                for process in processes:
                    if process.is_alive():
                        process.kill()
                    process.join(timeout=5)
                output.close()


class QueueTests(unittest.TestCase):
    def queue(self, root):
        return {"schema": 1, "kind": "greybox-execution-queue",
                "pools": {"a": {"capacity": 3, "source_ref": "synthetic-only"}},
                "sources": [{"kind": "image", "path": str(root / "job"), "pools": {"fixture": "a"}}]}

    def test_queue_requires_actual_capacity_and_fixed_backend(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            document = self.queue(root)
            self.assertEqual(execution.validate_queue(document)["limits"]["max_status"], 8)
            document["sources"][0]["kind"] = "untrusted.python.module"
            with self.assertRaises(ValueError):
                execution.validate_queue(document)
            document = self.queue(root)
            document["pools"]["a"].pop("source_ref")
            with self.assertRaises(ValueError):
                execution.validate_queue(document)

    def test_task_key_is_canonical_across_queue_aliases(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.assertEqual(execution.task_key({"kind": "image", "path": str(root / "x" / ".." / "job")}, "id"),
                             execution.task_key({"kind": "image", "path": str(root / "job")}, "id"))

    def test_stale_live_pid_record_is_not_proof_of_queue_ownership(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            queue = root / "queue.json"
            atomic_json(queue, self.queue(root))
            _, _, directory = execution._location(queue, root / "state")
            atomic_json(directory / "status.json", {"phase": "running", "pid": os.getpid(), "heartbeat": time.time()})
            self.assertFalse(execution.status(queue, root / "state")["running"])
            with exclusive(directory / ".owner.lock"):
                self.assertTrue(execution.status(queue, root / "state")["running"])

    def test_source_intervals_reject_nonfinite_strings_and_negative_values(self):
        with tempfile.TemporaryDirectory() as temporary:
            for name in ("poll_interval", "retry_interval"):
                for value in ("NaN", "1.0", float("nan"), float("inf"), -1, 0, None, True):
                    document = self.queue(Path(temporary))
                    document["sources"][0][name] = value
                    with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                        execution.validate_queue(document)


class LocalImageProvider:
    """Returns failed terminal jobs so scheduler tests need no image dependencies."""
    def __init__(self):
        self.lock = threading.Lock()
        self.tasks, self.events = {}, []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def respond(self, document):
                raw = json.dumps(document).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                try:
                    self.wfile.write(raw)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def do_POST(self):
                document = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                name = document["name"]
                with owner.lock:
                    identity = "task-" + str(len(owner.tasks))
                    duration = 1.0 if name == "slow" else .02
                    owner.tasks[identity] = {"name": name, "done": time.time() + duration}
                    owner.events.append(("created", name, time.time()))
                if name == "lost-response":
                    time.sleep(.8)
                self.respond({"state": "submitted", "provider_task_id": identity})

            def do_GET(self):
                identity = self.path.strip("/")
                with owner.lock:
                    task = owner.tasks[identity]
                    state = "failed" if time.time() >= task["done"] else "running"
                    if state == "failed":
                        owner.events.append(("terminal", task["name"], time.time()))
                self.respond({"state": state, "provider_task_id": identity})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = "http://127.0.0.1:" + str(self.server.server_port)

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


class ActualBackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="execution-core-test-")
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {"GREYBOX_SYNTHETIC_EXECUTION_KEY": "synthetic-not-a-provider-key"})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def configure(self, source_text):
        adapter = self.root / "synthetic-adapter.py"
        adapter.write_text(source_text)
        image_jobs.configure("fixture", {"kind": "custom", "credential_env": "GREYBOX_SYNTHETIC_EXECUTION_KEY",
            "capabilities": {"generate": True, "edit": False, "max_references": 0, "parameters": []},
            "adapter": {"source": str(adapter), "sha256": hashlib.sha256(adapter.read_bytes()).hexdigest(),
                        "argv": [sys.executable, "-B", "{adapter}"],
                        "documentation": {"source_ref": "synthetic-local-test-protocol"}}}, self.root / "profiles")

    def reserve(self, name):
        folder = self.root / name
        image_jobs.reserve("fixture", {"operation": "generate", "prompt": name, "images": [], "parameters": {}},
                           folder, config_dir=self.root / "profiles", authorization={"source_ref": "synthetic-test-only"})
        return {"kind": "image", "path": str(folder), "pools": {"fixture": "shared"}}

    def configure_http(self, provider):
        self.configure('''import json,sys,urllib.request
r=json.load(sys.stdin)
base=''' + repr(provider.base) + '''
if r['action']=='submit':
    req=urllib.request.Request(base,data=json.dumps({'name':r['request']['prompt']}).encode(),method='POST')
else:
    req=urllib.request.Request(base+'/'+r['task_id'])
with urllib.request.urlopen(req,timeout=2) as response:
    print(response.read().decode())
''')

    def http_queue(self, names):
        return {"schema": 1, "kind": "greybox-execution-queue",
                "pools": {"shared": {"capacity": 2, "source_ref": "synthetic-capacity"}},
                "sources": [self.reserve(name) for name in names],
                "limits": {"poll_interval": .025, "tick_interval": .01,
                           "submit_timeout": 2, "status_timeout": 2, "fetch_timeout": 2}}

    def test_actual_image_backend_rolls_before_slow_sibling_terminal(self):
        provider = LocalImageProvider()
        try:
            self.configure_http(provider)
            queue = self.http_queue(["fast", "slow", "next"])
            path = self.root / "queue.json"
            atomic_json(path, queue)
            result = execution.run(path, self.root / "state", max_seconds=5)
            self.assertEqual(result["phase"], "blocked", json.dumps(result))  # Confirmed failed synthetic outputs.
            self.assertEqual(len(provider.tasks), 3)
            created = next(at for event, name, at in provider.events if event == "created" and name == "next")
            slow_done = next(task["done"] for task in provider.tasks.values() if task["name"] == "slow")
            self.assertLess(created, slow_done)
            self.assertEqual(result["pools"]["shared"]["occupied"], 0)
            self.assertEqual(list((self.root / "state" / "actions").glob("*/provider-result.json")), [])
            self.assertTrue(all(read_json(path).get("committed") for path in (self.root / "state" / "actions").glob("*/ticket.json")))
        finally:
            provider.close()

    def test_detached_executor_dispatches_while_controller_is_idle(self):
        provider = LocalImageProvider()
        try:
            self.configure_http(provider)
            queue = self.http_queue(["first", "second", "third"])
            path, state = self.root / "queue.json", self.root / "state"
            atomic_json(path, queue)
            started = execution.start(path, state)
            self.assertTrue(started["started"])
            time.sleep(1.6)  # No controller/agent step, query or command during this interval.
            self.assertEqual(len(provider.tasks), 3, json.dumps(execution.status(path, state)))
            deadline = time.monotonic() + 3
            while execution.status(path, state).get("running") and time.monotonic() < deadline:
                time.sleep(.02)
            self.assertFalse(execution.status(path, state)["running"])
            self.assertEqual(execution.status(path, state)["pools"]["shared"]["occupied"], 0)
        finally:
            provider.close()

    @unittest.skipIf(os.name == "nt", "POSIX SIGKILL fault cut; Windows supervisor path remains separately qualified")
    def test_restart_after_accepted_post_before_id_imports_original_receipt(self):
        provider = LocalImageProvider()
        try:
            self.configure_http(provider)
            queue = self.http_queue(["lost-response", "other", "later"])
            path, state = self.root / "queue.json", self.root / "state"
            atomic_json(path, queue)
            started = execution.start(path, state)
            deadline = time.monotonic() + 3
            while not any(task["name"] == "lost-response" for task in provider.tasks.values()) and time.monotonic() < deadline:
                time.sleep(.005)
            self.assertTrue(any(task["name"] == "lost-response" for task in provider.tasks.values()))
            cut = read_json(self.root / "lost-response" / "job.json")
            self.assertEqual(cut["state"], "submitting")
            self.assertFalse(cut.get("provider_task_id"))
            os.kill(started["pid"], signal.SIGKILL)
            deadline = time.monotonic() + 2
            while execution.alive(started["pid"]) and time.monotonic() < deadline:
                time.sleep(.005)
            result = execution.run(path, state, max_seconds=5)
            self.assertEqual(result["phase"], "blocked", json.dumps(result))
            names = [task["name"] for task in provider.tasks.values()]
            self.assertEqual(sorted(names), ["later", "lost-response", "other"])
            recovered = read_json(self.root / "lost-response" / "job.json")
            self.assertEqual(recovered["state"], "failed")
            self.assertTrue(recovered.get("provider_task_id"))
        finally:
            provider.close()

    def test_actual_action_supervisor_enforces_total_deadline_and_no_resubmit(self):
        marker = self.root / "adapter-invoked"
        self.configure('''import json,sys,time
from pathlib import Path
json.load(sys.stdin)
Path(''' + repr(str(marker)) + ''').write_text('invoked')
time.sleep(4)
''')
        source = self.reserve("deadline")
        task = image_execution.scan(source)[0]
        directory = self.root / "action"
        directory.mkdir()
        lease = {"id": "deadline-action", "owner_pid": os.getpid(), "deadline": time.time() + .5,
                 "receipt_path": str(directory / "receipt.json"), "ticket_path": str(directory / "ticket.json"),
                 "pool": "shared", "task_key": execution.task_key(source, task["id"])}
        ticket = image_execution.prepare(source, task["id"], "submit", lease)
        ticket.update(execution_state_dir=str(self.root / "state"), execution_queue=str(self.root / "queue.json"))
        atomic_json(lease["ticket_path"], ticket)
        started = time.monotonic()
        execution._worker(Path(lease["ticket_path"]))
        self.assertLess(time.monotonic() - started, 1.5)
        outcome = read_json(lease["receipt_path"])["outcome"]
        self.assertEqual(outcome["error"]["acceptance"], "unknown")
        self.assertTrue(marker.exists())
        image_execution.commit(source, ticket, outcome)
        self.assertEqual(image_jobs.resume(source["path"])["state"], "unknown")

    def test_committed_action_payload_is_compact_and_duplicate_receipt_is_bound(self):
        self.configure("import json,sys\njson.load(sys.stdin)\nprint(json.dumps({'state':'failed'}))\n")
        source = self.reserve("recorded")
        queue = {"schema": 1, "kind": "greybox-execution-queue",
                 "pools": {"shared": {"capacity": 1, "source_ref": "synthetic-capacity"}}, "sources": [source]}
        path, state = self.root / "queue.json", self.root / "state"
        atomic_json(path, queue)
        claimed = execution.claim(path, state)
        ticket_path = claimed["ticket_path"]
        result = {"state": "failed", "provider_task_id": "synthetic-original"}
        execution.record(ticket_path, result)
        compact = read_json(ticket_path)
        self.assertTrue(compact["committed"])
        self.assertNotIn("snapshot", compact)
        self.assertTrue(execution.record(ticket_path, result)["duplicate"])
        with self.assertRaises(ValueError):
            execution.record(ticket_path, {"state": "cancelled", "provider_task_id": "different"})

    def test_ticket_enrichment_write_failure_restores_known_unsent_job(self):
        self.configure("import json,sys\njson.load(sys.stdin)\nprint(json.dumps({'state':'failed'}))\n")
        source = self.reserve("write-failure")
        path, state = self.root / "queue.json", self.root / "state"
        pools = {"shared": {"capacity": 1, "source_ref": "synthetic-capacity"}}
        task = image_execution.scan(source)[0]
        original = execution.atomic_json

        def fail_enrichment(destination, document):
            if Path(destination).name == "ticket.json" and "execution_state_dir" in document:
                raise OSError("Synthetic action metadata disk failure")
            return original(destination, document)

        with CapacityStore(state / "capacity.sqlite3", pools) as store:
            with patch.object(execution, "atomic_json", side_effect=fail_enrichment):
                with self.assertRaises(OSError):
                    execution._prepare(source, task, state, path, execution.DEFAULTS, store)
            self.assertEqual(store.snapshot()["shared"]["occupied"], 0)
        data = read_json(Path(source["path"]) / "job.json")
        self.assertEqual(data["state"], "reserved")
        self.assertNotIn("execution_lease", data)

    def test_original_ticket_terminal_refresh_without_original_queue(self):
        self.configure("import json,sys\njson.load(sys.stdin)\nprint(json.dumps({'state':'failed'}))\n")
        source = self.reserve("terminal-refresh")
        queue = {"schema": 1, "kind": "greybox-execution-queue",
                 "pools": {"shared": {"capacity": 1, "source_ref": "synthetic-capacity"}}, "sources": [source]}
        path, state = self.root / "queue.json", self.root / "state"
        atomic_json(path, queue)
        claimed = execution.claim(path, state)
        self.assertFalse(execution.refresh_ticket(claimed["ticket_path"])["released"])
        data = read_json(Path(source["path"]) / "job.json")
        data.update(state="cancelled")  # Synthetic confirmed original-task terminal.
        data.pop("execution_lease", None)
        atomic_json(Path(source["path"]) / "job.json", data)
        path.unlink()  # The original source need not appear in a future queue.
        self.assertTrue(execution.refresh_ticket(claimed["ticket_path"])["released"])
        with CapacityStore(state / "capacity.sqlite3", {}) as store:
            self.assertEqual(store.snapshot()["shared"]["occupied"], 0)

    def test_unenriched_ticket_dead_owner_recovers_as_known_unsent(self):
        marker = self.root / "invocations"
        self.configure("import json,sys\nfrom pathlib import Path\njson.load(sys.stdin)\nwith Path(" + repr(str(marker)) + ").open('a') as f: f.write('create\\n')\nprint(json.dumps({'state':'failed'}))\n")
        source = self.reserve("raw-ticket")
        task = image_execution.scan(source)[0]
        state = self.root / "state"
        directory = state / "actions" / "raw-before-enrichment"
        directory.mkdir(parents=True)
        lease = {"id": "raw-before-enrichment", "owner_pid": 99999999, "deadline": time.time() + 30,
                 "receipt_path": str(directory / "receipt.json"), "ticket_path": str(directory / "ticket.json"),
                 "pool": "shared", "task_key": execution.task_key(source, task["id"])}
        image_execution.prepare(source, task["id"], "submit", lease)
        self.assertTrue(Path(lease["ticket_path"]).exists())
        with self.assertRaises(ValueError):
            execution._worker(Path(lease["ticket_path"]))
        self.assertFalse(marker.exists())
        queue = {"schema": 1, "kind": "greybox-execution-queue",
                 "pools": {"shared": {"capacity": 1, "source_ref": "synthetic-capacity"}}, "sources": [source],
                 "limits": {"poll_interval": .01, "tick_interval": .01}}
        path = self.root / "queue.json"
        atomic_json(path, queue)
        result = execution.run(path, state, max_seconds=3)
        self.assertEqual(result["phase"], "blocked", json.dumps(result))
        self.assertEqual(marker.read_text().splitlines(), ["create"])
        self.assertEqual(read_json(Path(source["path"]) / "job.json")["state"], "failed")
        self.assertEqual(result["pools"]["shared"]["occupied"], 0)

    def test_invalid_manual_error_cannot_poison_lease_or_receipt(self):
        self.configure("import json,sys\njson.load(sys.stdin)\nprint(json.dumps({'state':'failed'}))\n")
        source = self.reserve("invalid-outcome")
        queue = {"schema": 1, "kind": "greybox-execution-queue",
                 "pools": {"shared": {"capacity": 1, "source_ref": "synthetic-capacity"}}, "sources": [source]}
        path = self.root / "queue.json"
        atomic_json(path, queue)
        claimed = execution.claim(path, self.root / "state")
        for value in (float("nan"), float("inf"), -1, "NaN", True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                execution.record(claimed["ticket_path"], {"ok": False, "error": {
                    "acceptance": "not_accepted", "category": "rate_limit", "retry_after": value}})
        self.assertFalse(Path(claimed["lease"]["receipt_path"]).exists())
        self.assertEqual(read_json(Path(source["path"]) / "job.json")["execution_lease"]["id"], claimed["action_id"])

    def test_stale_first_source_does_not_consume_healthy_sources_rate_budget(self):
        provider = LocalImageProvider()
        try:
            self.configure_http(provider)
            queue = self.http_queue(["stale", "healthy"])
            queue["pools"]["shared"]["rate_limits"] = {"submit": .1}
            stale = self.root / "stale" / "job.json"
            data = read_json(stale)
            data["runtime_binding"]["image_jobs_sha256"] = "synthetic-stale-runtime"
            atomic_json(stale, data)
            path = self.root / "queue.json"
            atomic_json(path, queue)
            result = execution.run(path, self.root / "state", max_seconds=1.)
            self.assertEqual(result["phase"], "bounded_exit")
            self.assertEqual([task["name"] for task in provider.tasks.values()], ["healthy"])
            self.assertEqual(read_json(stale)["state"], "reserved")
        finally:
            provider.close()

    def _enriched_ticket(self, source, action_id, seconds=.3):
        task = image_execution.scan(source)[0]
        directory = self.root / action_id
        directory.mkdir()
        lease = {"id": action_id, "owner_pid": os.getpid(), "deadline": time.time() + seconds,
                 "receipt_path": str(directory / "receipt.json"), "ticket_path": str(directory / "ticket.json"),
                 "pool": "shared", "task_key": execution.task_key(source, task["id"])}
        ticket = image_execution.prepare(source, task["id"], "submit", lease)
        ticket.update(execution_state_dir=str(self.root / "state"), execution_queue=str(self.root / "queue.json"))
        atomic_json(lease["ticket_path"], ticket)
        return ticket

    def test_expired_supervisor_replay_preserves_accepted_unknown_and_create_count(self):
        provider = LocalImageProvider()
        process = None
        try:
            self.configure_http(provider)
            source = self.reserve("lost-response")
            ticket = self._enriched_ticket(source, "expired-replay", .3)
            path = Path(ticket["lease"]["ticket_path"])
            process = execution.spawn([sys.executable, "-B", str(Path(execution.__file__)), "_invoke", str(path)],
                                      stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            deadline = time.monotonic() + 2
            while not provider.tasks and time.monotonic() < deadline:
                time.sleep(.005)
            self.assertEqual(len(provider.tasks), 1)  # Actual loopback POST was accepted.
            self.assertTrue(path.with_name("invoke.started").exists())
            execution.kill_tree(process)  # Lose the create response before provider-result is durable.
            self.assertFalse(path.with_name("provider-result.json").exists())
            time.sleep(max(0., ticket["lease"]["deadline"] - time.time()) + .02)
            execution._worker(path)
            receipt_path = Path(ticket["lease"]["receipt_path"])
            original = receipt_path.read_bytes()
            outcome = read_json(receipt_path)["outcome"]
            self.assertEqual(outcome["error"]["acceptance"], "unknown")
            execution._worker(path)
            execution._invoke_child(path)
            self.assertEqual(receipt_path.read_bytes(), original)
            self.assertEqual(len(provider.tasks), 1)
            image_execution.commit(source, ticket, outcome)
            self.assertEqual(image_jobs.resume(source["path"])["state"], "unknown")
            self.assertEqual(len(provider.tasks), 1)
        finally:
            if process is not None and process.poll() is None:
                execution.kill_tree(process)
            provider.close()

    def test_expired_supervisor_imports_original_result_and_rejects_conflicting_receipt(self):
        provider = LocalImageProvider()
        try:
            self.configure_http(provider)
            source = self.reserve("original-result")
            ticket = self._enriched_ticket(source, "original-result-action", .3)
            path = Path(ticket["lease"]["ticket_path"])
            execution._invoke_child(path)
            self.assertEqual(len(provider.tasks), 1)
            self.assertTrue(path.with_name("provider-result.json").exists())
            time.sleep(max(0., ticket["lease"]["deadline"] - time.time()) + .02)
            execution._worker(path)
            receipt_path = Path(ticket["lease"]["receipt_path"])
            original = receipt_path.read_bytes()
            outcome = read_json(receipt_path)["outcome"]
            self.assertTrue(outcome["ok"])
            self.assertTrue(outcome["result"].get("provider_task_id"))
            path.with_name("provider-result.json").unlink()
            execution._worker(path)  # Existing original receipt wins even after transport cleanup.
            with self.assertRaises(ValueError):
                execution._write_receipt_once(ticket, execution._timeout("submit"))
            self.assertEqual(receipt_path.read_bytes(), original)
            self.assertEqual(len(provider.tasks), 1)
        finally:
            provider.close()

    def test_expired_enriched_ticket_without_marker_is_still_unknown(self):
        self.configure("import json,sys\njson.load(sys.stdin)\nprint(json.dumps({'state':'failed'}))\n")
        source = self.reserve("expired-no-marker")
        ticket = self._enriched_ticket(source, "expired-no-marker-action", .02)
        path = Path(ticket["lease"]["ticket_path"])
        time.sleep(.03)
        execution._worker(path)
        outcome = read_json(ticket["lease"]["receipt_path"])["outcome"]
        self.assertEqual(outcome["error"]["acceptance"], "unknown")
        self.assertFalse(path.with_name("invoke.started").exists())


if __name__ == "__main__":
    unittest.main()
