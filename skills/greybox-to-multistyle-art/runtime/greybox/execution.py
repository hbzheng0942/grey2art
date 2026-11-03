"""Continuous, process-isolated execution over existing project task ledgers.

The coordinator performs no provider I/O. Each action has a durable ticket and
an independent supervisor enforcing an absolute deadline on its network child.
Only fixed shipped backends are imported; queue data cannot load Python code.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from greybox.execution_capacity import CapacityStore
from greybox.execution_process import alive, atomic_json, exclusive, kill_tree, read_json, spawn

BACKENDS = {"supplier": "supplier_execution", "image": "image_execution", "native": "host_execution"}
DEFAULTS = {"submit_timeout": 300., "status_timeout": 30., "fetch_timeout": 300.,
            "poll_interval": 2., "max_submit": 8, "max_status": 8, "max_fetch": 2,
            "tick_interval": .05, "retry_interval": 2.}
TERMINAL_STATES = {"ready", "download", "failed", "cancelled", "rejected"}


def _backend(source):
    return importlib.import_module("greybox." + BACKENDS[source["kind"]])


def task_key(source, task_id):
    identity = [source["kind"], str(Path(source["path"]).expanduser().resolve()), str(task_id)]
    return hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest()


def validate_queue(document):
    if not isinstance(document, dict) or document.get("schema") != 1 or document.get("kind") != "greybox-execution-queue":
        raise ValueError("Expected greybox-execution-queue schema 1")
    if not isinstance(document.get("pools"), dict) or not document["pools"]:
        raise ValueError("Declare actual account pools and their capacity provenance")
    normalized = json.loads(json.dumps(document, allow_nan=False))
    for key, pool in normalized["pools"].items():
        if not isinstance(key, str) or not key.strip() or not isinstance(pool, dict):
            raise ValueError("Account pool needs a stable non-secret ID")
        if type(pool.get("capacity")) is not int or not 1 <= pool["capacity"] <= 100000:
            raise ValueError("Account pool capacity must be an explicit positive integer")
        if not isinstance(pool.get("source_ref"), str) or not pool["source_ref"].strip():
            raise ValueError("Account capacity requires a real source_ref")
        rates = pool.get("rate_limits", {})
        if not isinstance(rates, dict) or any(method not in {"submit", "status", "fetch"} or
            type(qps) not in {int, float} or not math.isfinite(qps) or qps <= 0 or qps > 100000
            for method, qps in rates.items()):
            raise ValueError("Pool rate_limits must map submit/status/fetch to confirmed positive QPS values")
    sources = normalized.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("Queue needs existing task-ledger sources")
    identities = set()
    for source in sources:
        if not isinstance(source, dict) or not isinstance(source.get("kind"), str) or source.get("kind") not in BACKENDS:
            raise ValueError("Source kind must be supplier, image or native")
        if not isinstance(source.get("path"), str):
            raise ValueError("Execution source path must be a string")
        path = Path(source.get("path", "")).expanduser()
        if not path.is_absolute():
            raise ValueError("Execution source paths must be absolute")
        source["path"] = str(path.resolve())
        for override in ("poll_interval", "retry_interval"):
            value = source.get(override)
            if override in source and (type(value) not in {int, float} or not math.isfinite(value) or not .005 <= value <= 86400):
                raise ValueError("Source execution intervals must be finite positive durations")
        identity = (source["kind"], source["path"])
        if identity in identities:
            raise ValueError("The same task-ledger source is listed twice")
        identities.add(identity)
        bindings = source.get("pools")
        if not isinstance(bindings, dict) or not bindings or any(not isinstance(key, str) or not key.strip() or
                not isinstance(value, str) or value not in normalized["pools"] for key, value in bindings.items()):
            raise ValueError("Every source needs bindings to declared account pools")
    limits = normalized.get("limits", {})
    if not isinstance(limits, dict) or set(limits) - set(DEFAULTS):
        raise ValueError("Unsupported execution limits")
    limits = {**DEFAULTS, **limits}
    for name, value in limits.items():
        if name.startswith("max_"):
            valid = type(value) is int and 1 <= value <= 128
        else:
            valid = type(value) in {int, float} and math.isfinite(value) and .005 <= value <= 86400
        if not valid:
            raise ValueError("Invalid execution limit: " + name)
    normalized["limits"] = limits
    for source in sources:
        source.setdefault("poll_interval", limits["poll_interval"])
        source.setdefault("retry_interval", limits["retry_interval"])
    return normalized


def _state_root(state_dir=None):
    if state_dir is None:
        from greybox.host import config_root
        state_dir = config_root() / "execution"
    root = Path(state_dir).expanduser().resolve()
    skill = Path(__file__).resolve().parents[2]
    if root == skill or skill in root.parents:
        raise ValueError("Execution runtime state must remain outside installed skill files")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return root


def _location(queue_file, state_dir=None):
    path = Path(queue_file).expanduser().resolve()
    root = _state_root(state_dir)
    identity = hashlib.sha256(str(path).encode()).hexdigest()
    directory = root / "queues" / identity
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path, root, directory


def _classify(exc, action):
    from greybox.execution_errors import classify_error
    return classify_error(exc, action)


def _timeout(action):
    return {"ok": False, "error": {"code": "ACTION_DEADLINE_EXCEEDED", "category": "timeout",
            "acceptance": "unknown" if action == "submit" else "accepted",
            "message": "Action exceeded its absolute deadline; preserve the original invocation"}}


def _not_started():
    return {"ok": False, "error": {"code": "ACTION_NOT_STARTED", "category": "network",
            "acceptance": "not_accepted", "message": "No provider invocation began; restore the original pending task"}}


def _task_occupied(task):
    if "occupied" in task:
        return bool(task["occupied"])
    if "remote_active" in task:
        return bool(task["remote_active"])
    return task["state"] in {"active", "unknown"}


def _task_terminal(task):
    if "remote_terminal" in task:
        return bool(task["remote_terminal"])
    return task["state"] in TERMINAL_STATES


def _scan(queue):
    tasks, errors = [], []
    for source in queue["sources"]:
        try:
            scanned = _backend(source).scan(source)
            for task in scanned:
                if task.get("pool") not in queue["pools"]:
                    raise ValueError("Source task refers to an undeclared account pool")
                tasks.append((source, task))
        except Exception as error:
            # Do not infer terminality or release capacity from a missing ledger.
            errors.append({"source": source["path"], "code": "SOURCE_UNAVAILABLE",
                           "message": type(error).__name__})
    return tasks, errors


def _binding(ticket):
    return {"action_id": ticket["lease"]["id"], "request_hash": ticket["request_hash"]}


def _check_outcome(ticket, document):
    if not isinstance(document, dict) or document.get("binding") != _binding(ticket):
        raise ValueError("Action receipt does not match its original ticket")
    outcome = document.get("outcome")
    _validate_outcome(outcome)
    return outcome


def _validate_outcome(outcome):
    if not isinstance(outcome, dict) or type(outcome.get("ok")) is not bool:
        raise ValueError("Invalid execution outcome")
    if outcome["ok"]:
        if not isinstance(outcome.get("result"), dict):
            raise ValueError("Successful action outcome needs its result object")
    else:
        from greybox.execution_errors import ACCEPTANCE, CATEGORIES
        error = outcome.get("error")
        if not isinstance(error, dict) or not isinstance(error.get("acceptance"), str) or not isinstance(error.get("category"), str) or error.get("acceptance") not in ACCEPTANCE or error.get("category") not in CATEGORIES:
            raise ValueError("Failed action outcome needs explicit acceptance and category")
        if "retry_after" in error:
            value = error["retry_after"]
            if type(value) not in {int, float} or not math.isfinite(value) or not 0 <= value <= 31536000:
                raise ValueError("retry_after must be finite nonnegative seconds")


def _commit(ticket, outcome, store):
    result = _backend(ticket["source"]).commit(ticket["source"], ticket, outcome)
    error = outcome.get("error", {}) if not outcome.get("ok") else {}
    if isinstance(result, dict) and result.get("category"):
        error = result
    delay = error.get("retry_after")
    delay = 2. if delay is None else delay
    if error.get("category") in {"capacity", "concurrency", "capacity_full"}:
        store.cooldown(ticket["lease"]["pool"], delay)
    elif error.get("category") in {"rate_limit", "rate_limited"}:
        store.cooldown_action(ticket["lease"]["pool"], ticket["action"], delay)
    # The source ledger is authoritative. Re-scan before releasing, including
    # acceptance-aware rejected/blocked states and output-pending terminal jobs.
    for task in _backend(ticket["source"]).scan(ticket["source"]):
        if str(task["id"]) == str(ticket["id"]):
            if _task_terminal(task) or (not _task_occupied(task) and not task.get("lease")):
                store.release(ticket["lease"]["task_key"])
            if task["state"] != "unknown":
                _compact_committed(ticket, outcome)
            break
    return result


def _outcome_hash(outcome):
    return hashlib.sha256(json.dumps(outcome, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _write_receipt_once(ticket, outcome):
    """The first durable action outcome is immutable, including across replays."""
    path = Path(ticket["lease"]["receipt_path"])
    document = {"binding": _binding(ticket), "outcome": outcome}
    with exclusive(path.with_name(".receipt.lock")):
        if path.exists():
            previous = read_json(path)
            if previous.get("committed"):
                same = previous.get("binding") == _binding(ticket) and previous.get("outcome_sha256") == _outcome_hash(outcome)
            else:
                same = previous == document
            if not same:
                raise ValueError("Conflicting receipt for an existing action")
            return
        atomic_json(path, document)


def _compact_committed(ticket, outcome):
    """The project ledger now owns recovery facts; retain only a small receipt.

    In particular do not keep transport base64 bodies alongside canonical images
    or a full portfolio copy for every status poll. Unknown receipts stay intact.
    """
    digest = _outcome_hash(outcome)
    compact = {key: ticket[key] for key in ("kind", "source", "id", "action", "lease", "request_hash", "execution_state_dir", "execution_queue") if key in ticket}
    compact.update(committed=True, outcome_sha256=digest)
    receipt_path = Path(ticket["lease"]["receipt_path"])
    with exclusive(receipt_path.with_name(".receipt.lock")):
        if receipt_path.exists():
            previous = read_json(receipt_path)
            previous_hash = previous.get("outcome_sha256") if previous.get("committed") else _outcome_hash(_check_outcome(ticket, previous))
            if previous.get("binding") != _binding(ticket) or previous_hash != digest:
                raise ValueError("Cannot compact a conflicting original action receipt")
        atomic_json(ticket["lease"]["ticket_path"], compact)
        atomic_json(receipt_path, {"binding": _binding(ticket), "committed": True, "outcome_sha256": digest})
    directory = Path(ticket["lease"]["ticket_path"]).parent
    for name in ("provider-result.json", "invoke.started", "worker.json"):
        try:
            (directory / name).unlink(missing_ok=True)
        except OSError:
            pass


def _prepare(source, task, root, queue_path, limits, store):
    action = task["action"]
    identity = task_key(source, task["id"])
    action_id = uuid.uuid4().hex
    directory = root / "actions" / action_id
    lease = {"id": action_id, "owner_pid": os.getpid(),
             "deadline": time.time() + limits[action + "_timeout"],
             "receipt_path": str(directory / "receipt.json"),
             "ticket_path": str(directory / "ticket.json"),
             "pool": task["pool"], "task_key": identity}
    if action == "submit" and not store.claim_pending(identity, task["pool"], source["path"], action_id, os.getpid()):
        return None
    if store.rate_wait(task["pool"], action) > 0:
        if action == "submit":
            store.release_claim(identity, action_id)
        return None
    ticket = None
    try:
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        ticket = _backend(source).prepare(source, task["id"], action, lease)
        if not isinstance(ticket, dict) or ticket.get("lease") != lease or not ticket.get("request_hash"):
            raise ValueError("Backend returned an invalid bound action ticket")
        if not store.allow_action(task["pool"], action):
            # Gates run before a rate token is consumed. A stale task must not
            # repeatedly take the only token and starve unrelated ready work.
            _commit(ticket, {"ok": False, "error": {"code": "DISPATCH_RATE_DEFERRED", "category": "rate_limit",
                "acceptance": "not_accepted" if action == "submit" else "accepted",
                "retry_after": store.rate_wait(task["pool"], action),
                "message": "Another queue claimed this method's dispatch time"}}, store)
            return None
        ticket.update(kind=source["kind"], source=source, id=task["id"], action=action,
                      execution_state_dir=str(root), execution_queue=str(queue_path))
        atomic_json(lease["ticket_path"], ticket)
        return ticket
    except Exception:
        safely_unsent = ticket is None
        if ticket is None:
            try:
                current = next(item for item in _backend(source).scan(source) if str(item["id"]) == str(task["id"]))
                if (current.get("lease") or {}).get("id") == action_id:
                    safely_unsent = False
            except Exception:
                safely_unsent = False
        if ticket is not None:
            # Preparation never calls a provider. If metadata enrichment fails
            # after the backend committed its lease, settle that known-unsent
            # action rather than leave a dangling lease or free a live slot.
            try:
                _backend(source).commit(source, ticket, {"ok": False, "error": {
                    "code": "ACTION_RECORD_WRITE_FAILED", "category": "network",
                    "acceptance": "not_accepted", "message": "Local action record failed before worker start"}})
                safely_unsent = True
            except Exception:
                safely_unsent = False
        if action == "submit" and safely_unsent:
            store.release_claim(identity, action_id)
        if safely_unsent:
            # Task-owned, never-invoked attempt only. Avoid creating an empty
            # staging directory every retry of an input/readiness gate.
            for name in ("ticket.json", "receipt.json", "provider-result.json", "worker.json", "invoke.started"):
                try:
                    (directory / name).unlink(missing_ok=True)
                except OSError:
                    pass
            try:
                directory.rmdir()
            except OSError:
                pass
        raise


def _launch(ticket):
    process = spawn([sys.executable, "-B", str(Path(__file__).resolve()), "_worker", ticket["lease"]["ticket_path"]],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return process


def _dispatch_identity(source, task):
    # Source paths were already canonicalized when validating the queue.
    return source["kind"], source["path"], str(task["id"])


def _dispatch_order(tasks, after):
    """Resume after the previous winner so rate tokens cannot pin the head."""
    if after is not None:
        for index, (source, task) in enumerate(tasks):
            if _dispatch_identity(source, task) == after:
                return tasks[index + 1:] + tasks[:index + 1]
    return tasks


def run(queue_file, state_dir=None, max_seconds=None, once=False):
    """Run without model turns. max_seconds/once bound only the coordinator.

    Accepted action supervisors retain their deadlines and durable receipts if
    this process stops. A later run imports receipts instead of reissuing POST.
    """
    if max_seconds is not None and (type(max_seconds) not in {int, float} or not math.isfinite(max_seconds) or max_seconds <= 0):
        raise ValueError("max_seconds must be a finite positive duration")
    path, root, directory = _location(queue_file, state_dir)
    queue = validate_queue(read_json(path))
    original_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    limits = queue["limits"]
    started = time.time()
    processes = {}
    deferred = {}
    issues = []
    phase = "running"
    status_path = directory / "status.json"
    iterations = 0
    cursors = {}
    with exclusive(directory / ".owner.lock"), CapacityStore(root / "capacity.sqlite3", queue["pools"]) as store:
        summary = {"schema": 1, "kind": "greybox-execution-status", "pid": os.getpid(),
                   "phase": "starting", "queue_file": str(path), "heartbeat": time.time(),
                   "started_at": started}
        try:
            atomic_json(status_path, summary)
            while True:
                now = time.time()
                tasks, errors = _scan(queue)
                issues = list(errors)
                changed = False
                for source, task in tasks:
                    identity = task_key(source, task["id"])
                    if _task_occupied(task):
                        store.reserve(identity, task["pool"], source["path"], adopt=True)
                    elif _task_terminal(task):
                        store.release(identity)
                    lease = task.get("lease")
                    if not lease:
                        continue
                    receipt = Path(lease["receipt_path"])
                    ticket_path = Path(lease["ticket_path"])
                    try:
                        if receipt.exists():
                            ticket = read_json(ticket_path)
                            outcome = _check_outcome(ticket, read_json(receipt))
                            _commit(ticket, outcome, store)
                            changed = True
                        elif ticket_path.exists():
                            ticket = read_json(ticket_path)
                            owner = lease.get("owner_pid")
                            raw = "execution_state_dir" not in ticket or "execution_queue" not in ticket
                            if raw and type(owner) is int and owner > 0 and not alive(owner):
                                # Canonical worker entrypoints reject raw tickets;
                                # metadata enrichment precedes every launch.
                                _commit(ticket, _not_started(), store)
                                changed = True
                            elif now > float(lease["deadline"]) + 1.:
                                _commit(ticket, _timeout(ticket["action"]), store)
                                changed = True
                        elif now > float(lease["deadline"]) + 1.:
                            # A supervisor normally writes its timeout receipt
                            # at deadline. Missing supervisor result is unknown.
                            ticket = read_json(ticket_path)
                            _commit(ticket, _timeout(ticket["action"]), store)
                            changed = True
                    except Exception as error:
                        issues.append({"source": source["path"], "task": task["id"],
                                       "code": "ACTION_RECONCILIATION_REQUIRED", "message": type(error).__name__})
                for action_id, process in list(processes.items()):
                    if process.poll() is not None:
                        process.wait()
                        del processes[action_id]
                if changed:
                    tasks, errors = _scan(queue)
                    issues.extend(errors)
                # A changed queue cannot silently widen submissions while the
                # current executor still owns its original operational scope.
                queue_current = hashlib.sha256(path.read_bytes()).hexdigest() == original_hash
                active_counts = {action: sum(task.get("lease", {}).get("action") == action
                                 for _, task in tasks if task.get("lease"))
                                 for action in ("submit", "status", "fetch")}
                # Older/new backends need not copy action into their lease.
                for _, task in tasks:
                    lease = task.get("lease")
                    if lease and not lease.get("action"):
                        try:
                            active_counts[read_json(lease["ticket_path"])["action"]] += 1
                        except (OSError, ValueError, KeyError):
                            pass
                actionable = False
                gaps = []
                deferred_reasons = {}
                # Submit first after consuming every available completion;
                # status/fetch run in independent process capacity pools.
                for action in ("submit", "status", "fetch"):
                    for source, task in _dispatch_order(tasks, cursors.get(action)):
                        if task.get("lease") or task.get("action") != action:
                            continue
                        key = task_key(source, task["id"])
                        if task.get("execution_mode") == "agent_driven" or source["kind"] == "native":
                            gaps.append({"source": source["path"], "task": task["id"],
                                         "code": "INDEPENDENT_DISPATCH_UNAVAILABLE", "execution_mode": "agent_driven"})
                            deferred_reasons[key] = "agent_driven"
                            continue
                        actionable = True
                        if not queue_current and action == "submit":
                            issues.append({"code": "QUEUE_CHANGED", "message": "New submissions paused; recover original work"})
                            deferred_reasons[key] = "queue_changed"
                            continue
                        defer_key = (task_key(source, task["id"]), action)
                        if max(float(task.get("next_at", 0) or 0), deferred.get(defer_key, 0)) > now or active_counts[action] >= limits["max_" + action]:
                            deferred_reasons[key] = ("action_capacity" if active_counts[action] >= limits["max_" + action] else
                                                     "prepare_blocked" if deferred.get(defer_key, 0) > now else "next_poll")
                            continue
                        ticket = None
                        try:
                            ticket = _prepare(source, task, root, path, limits, store)
                            if ticket is None:
                                snapshot = store.snapshot()[task["pool"]]
                                deferred_reasons[key] = ("pool_cooldown" if snapshot["cooldown_until"] > now else
                                    "pool_capacity" if snapshot["available"] == 0 else
                                    "request_rate" if store.rate_wait(task["pool"], action) > 0 else "claimed_elsewhere")
                                continue
                            process = _launch(ticket)
                            processes[ticket["lease"]["id"]] = process
                            cursors[action] = _dispatch_identity(source, task)
                            active_counts[action] += 1
                            deferred_reasons[key] = "action_in_progress"
                        except Exception as error:
                            deferred[defer_key] = time.time() + limits["retry_interval"]
                            deferred_reasons[key] = "prepare_blocked"
                            if ticket is not None:
                                # No child was started, so this local failure is
                                # a definite non-submission, not a paid retry.
                                try:
                                    _commit(ticket, {"ok": False, "error": {
                                        "code": "ACTION_START_FAILED", "category": "local",
                                        "acceptance": "not_accepted", "retry_after": limits["retry_interval"],
                                        "message": "Action worker did not start"}}, store)
                                except Exception:
                                    pass
                            issues.append({"source": source["path"], "task": task["id"],
                                           "code": "ACTION_PREPARE_BLOCKED", "message": type(error).__name__})
                iterations += 1
                summary = {"schema": 1, "kind": "greybox-execution-status", "pid": os.getpid(),
                           "phase": "running", "queue_file": str(path), "heartbeat": time.time(),
                           "started_at": started, "iterations": iterations, "pools": store.snapshot(),
                           "source_errors": issues, "capability_gaps": gaps,
                           "active_actions": sum(active_counts.values()), "task_count": len(tasks),
                           "tasks": [{"id": task["id"], "source": source["path"], "state": task["state"],
                                      "deferred_reason": deferred_reasons.get(task_key(source, task["id"]),
                                          "action_in_progress" if task.get("lease") else task.get("deferred_reason"))}
                                     for source, task in tasks]}
                atomic_json(status_path, summary)
                has_leases = any(task.get("lease") for _, task in tasks)
                if once or max_seconds is not None and time.time() - started >= max_seconds:
                    phase = "bounded_exit"
                    break
                if not actionable and not has_leases and not processes:
                    phase = "blocked" if gaps or issues or any(task["state"] != "ready" for _, task in tasks) else "complete"
                    break
                time.sleep(limits["tick_interval"])
        except Exception as error:
            phase = "failed"
            summary["error"] = {"code": "EXECUTOR_FAILED", "type": type(error).__name__,
                                "message": "Coordinator stopped; preserve original ledgers and receipts before resuming."}
            raise
        finally:
            for process in processes.values():
                threading.Thread(target=process.wait, daemon=True).start()
            summary.update(phase=phase, heartbeat=time.time())
            try:
                atomic_json(status_path, summary)
            except Exception:
                if phase != "failed":
                    raise  # Do not mask an earlier fault when storage also failed.
    return summary


def status(queue_file, state_dir=None):
    path, root, directory = _location(queue_file, state_dir)
    status_path = directory / "status.json"
    try:
        result = read_json(status_path)
    except FileNotFoundError:
        return {"phase": "not_started", "queue_file": str(path), "running": False}
    result["running"] = result.get("phase") in {"starting", "running"} and alive(result.get("pid"))
    if result["running"]:
        try:
            with exclusive(directory / ".owner.lock"):
                result["running"] = False  # PID reuse or an unreaped stale record.
        except ValueError:
            pass
    result["heartbeat_age_seconds"] = max(0., time.time() - result.get("heartbeat", 0))
    return result


def start(queue_file, state_dir=None):
    path, root, directory = _location(queue_file, state_dir)
    validate_queue(read_json(path))
    with exclusive(directory / ".start.lock"):
        current = status(path, root)
        if current.get("running"):
            return {"started": False, "pid": current["pid"], "status_file": str(directory / "status.json")}
        process = spawn([sys.executable, "-B", str(Path(__file__).resolve()), "_run", str(path), str(root)],
                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        threading.Thread(target=process.wait, daemon=True).start()
        deadline = time.monotonic() + 1.
        while time.monotonic() < deadline:
            current = status(path, root)
            if current.get("pid") == process.pid:
                if current.get("phase") == "failed":
                    return {"started": False, "code": "EXECUTOR_START_FAILED",
                            "status_file": str(directory / "status.json")}
                return {"started": True, "pid": process.pid, "status_file": str(directory / "status.json")}
            if process.poll() is not None:
                return {"started": False, "code": "EXECUTOR_START_FAILED", "status_file": str(directory / "status.json")}
            time.sleep(.01)
        return {"started": True, "pid": process.pid, "startup_verified": False,
                "status_file": str(directory / "status.json")}


def claim(queue_file, state_dir=None, action=None):
    """Claim one host-mediated action without inventing autonomous tool access."""
    path, root, _ = _location(queue_file, state_dir)
    queue = validate_queue(read_json(path))
    tasks, errors = _scan(queue)
    with CapacityStore(root / "capacity.sqlite3", queue["pools"]) as store:
        for source, task in tasks:
            if _task_occupied(task):
                store.reserve(task_key(source, task["id"]), task["pool"], source["path"], adopt=True)
            elif _task_terminal(task):
                store.release(task_key(source, task["id"]))
        for source, task in tasks:
            if task.get("lease") or not task.get("action") or action and task["action"] != action:
                continue
            if float(task.get("next_at", 0) or 0) > time.time():
                continue
            ticket = _prepare(source, task, root, path, queue["limits"], store)
            if ticket is not None:
                return {"claimed": True, "execution_mode": "agent_driven", "ticket_path": ticket["lease"]["ticket_path"],
                        "action_id": ticket["lease"]["id"], "request_hash": ticket["request_hash"],
                        "lease": ticket["lease"]}
    return {"claimed": False, "source_errors": errors}


def record(ticket_path, outcome, state_dir=None):
    ticket = read_json(ticket_path)
    if not isinstance(outcome, dict):
        raise ValueError("Execution result must be an object")
    if "ok" not in outcome:
        outcome = {"ok": True, "result": outcome}
    _validate_outcome(outcome)
    if ticket.get("committed"):
        if ticket.get("outcome_sha256") != _outcome_hash(outcome):
            raise ValueError("Conflicting duplicate receipt for a committed action")
        return {"recorded": True, "duplicate": True, "action_id": ticket["lease"]["id"]}
    root = _state_root(ticket["execution_state_dir"])
    if state_dir is not None and _state_root(state_dir) != root:
        raise ValueError("Receipt state directory differs from its original ticket")
    with CapacityStore(root / "capacity.sqlite3", {}) as store:
        _write_receipt_once(ticket, outcome)
        return _commit(ticket, outcome, store)


def refresh_ticket(ticket_path, state_dir=None):
    """Release a slot only from the original ledger's confirmed remote terminal.

    This lets an explicit native/manual reconciliation update capacity without
    depending on whether the original source is in the next queue document.
    """
    ticket = read_json(ticket_path)
    root = _state_root(state_dir or ticket.get("execution_state_dir"))
    if state_dir is not None and ticket.get("execution_state_dir") and _state_root(ticket["execution_state_dir"]) != root:
        raise ValueError("Capacity refresh differs from its original state directory")
    identity = task_key(ticket["source"], ticket["id"])
    if ticket["lease"].get("task_key") != identity:
        raise ValueError("Capacity refresh task identity differs from its original lease")
    for task in _backend(ticket["source"]).scan(ticket["source"]):
        if str(task["id"]) == str(ticket["id"]):
            terminal = _task_terminal(task)
            if terminal:
                with CapacityStore(root / "capacity.sqlite3", {}) as store:
                    store.release(identity)
            return {"released": terminal, "remote_terminal": terminal, "state": task["state"]}
    raise ValueError("Original task is unavailable; retain its reservation")


def _invoke_child(ticket_path):
    ticket = read_json(ticket_path)
    if ticket.get("committed"):
        return
    _dispatch_ready(ticket, ticket_path)
    marker = Path(ticket_path).with_name("invoke.started")
    try:
        fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        # Never overwrite another child's result or invoke the same POST twice.
        return
    else:
        with os.fdopen(fd, "w") as handle:
            handle.write(str(os.getpid()))
            handle.flush()
            os.fsync(handle.fileno())
    try:
        result = _backend(ticket["source"]).invoke(ticket)
        outcome = {"ok": True, "result": result}
    except Exception as error:
        outcome = {"ok": False, "error": _classify(error, ticket["action"])}
    atomic_json(Path(ticket_path).with_name("provider-result.json"), {"binding": _binding(ticket), "outcome": outcome})


def _worker(ticket_path):
    """Supervisor survives model/coordinator pauses and owns its network child."""
    with exclusive(Path(ticket_path).with_name(".worker.lock")):
        _supervise(ticket_path)


def _supervise(ticket_path):
    ticket = read_json(ticket_path)
    if ticket.get("committed"):
        return
    _dispatch_ready(ticket, ticket_path)
    lease = ticket["lease"]
    process = None
    try:
        receipt_path = Path(lease["receipt_path"])
        if receipt_path.exists():
            existing = read_json(receipt_path)
            if existing.get("committed"):
                if existing.get("binding") != _binding(ticket):
                    raise ValueError("Original receipt binding differs from this action")
            else:
                _check_outcome(ticket, existing)
            return  # Never overwrite an original result during supervisor replay.
        original_result = Path(ticket_path).with_name("provider-result.json")
        if original_result.exists():
            try:
                outcome = _check_outcome(ticket, read_json(original_result))
            except (OSError, ValueError):
                outcome = _timeout(ticket["action"])
            _write_receipt_once(ticket, outcome)
            return
        remaining = float(lease["deadline"]) - time.time()
        if remaining <= 0:
            # Enrichment makes a ticket dispatchable. A previous child may have
            # sent POST before its marker/result became observable. Deadline or
            # marker absence cannot prove non-acceptance for such a ticket.
            outcome = _timeout(ticket["action"])
        else:
            process = spawn([sys.executable, "-B", str(Path(__file__).resolve()), "_invoke", str(ticket_path)],
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            atomic_json(Path(ticket_path).with_name("worker.json"), {"supervisor_pid": os.getpid(), "network_pid": process.pid})
            try:
                process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                kill_tree(process)
                try:
                    outcome = _check_outcome(ticket, read_json(original_result))
                except (OSError, ValueError):
                    outcome = _timeout(ticket["action"])
            else:
                try:
                    document = read_json(Path(ticket_path).with_name("provider-result.json"))
                    outcome = _check_outcome(ticket, document)
                except (OSError, ValueError):
                    outcome = _timeout(ticket["action"])
        _write_receipt_once(ticket, outcome)
    finally:
        if process is not None and process.poll() is None:
            kill_tree(process)


def _dispatch_ready(ticket, ticket_path):
    for key in ("execution_state_dir", "execution_queue"):
        if not isinstance(ticket.get(key), str) or not Path(ticket[key]).is_absolute():
            raise ValueError("An unenriched action ticket cannot invoke a provider")
    if Path(ticket["lease"]["ticket_path"]).resolve() != Path(ticket_path).resolve():
        raise ValueError("Worker ticket path differs from its original action")
    if ticket["lease"].get("task_key") != task_key(ticket["source"], ticket["id"]):
        raise ValueError("Worker task identity differs from its original lease")


def _main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) == 2 and args[0] in {"_worker", "_invoke"}:
        (_worker if args[0] == "_worker" else _invoke_child)(Path(args[1]))
        return 0
    if len(args) == 3 and args[0] == "_run":
        run(args[1], args[2])
        return 0
    raise ValueError("Use the public execution CLI; internal worker arguments are fixed")


if __name__ == "__main__":
    raise SystemExit(_main())
