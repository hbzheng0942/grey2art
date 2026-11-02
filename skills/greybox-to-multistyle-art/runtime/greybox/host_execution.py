"""Native-tool action/receipt contract without pretending to invoke host tools.

Use the shared executor's bounded claim/record commands for capacity ownership.
These jobs remain agent-driven until an actual independent bridge is implemented
and qualified; a capability declaration alone never supplies such a bridge.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import time
import uuid

from . import image_adapters as adapters, image_jobs as jobs, provider_http
from .execution_process import atomic_json


def _validate_inputs(request, tool, base):
    """Bind actual outbound references, including existing host-upload mappings."""
    images = request.get("images", [])
    for image in images:
        jobs.require(provider_http.file_hash(image["path"]) == image["sha256"], "Actual native input bytes changed")
    reference = request.get("native_dispatch")
    if reference:
        from . import board_native, reference_boards as boards
        project = Path(base).resolve()
        _, raw = boards._file(reference, project, {})
        dispatch = json.loads(raw)
        jobs.require(dispatch.get("schema") == 1 and dispatch.get("kind") == "reference-board-native-dispatch" and
                     dispatch.get("invocation_recorded") is False, "Native dispatch must be an unchanged prepared board mapping")
        _, input_raw = boards._file(dispatch.get("request"), project, {})
        _, binding_raw = boards._file(dispatch.get("binding"), project, {})
        binding = json.loads(binding_raw)
        arguments, bound = board_native._arguments(json.loads(input_raw), binding, project)
        expected = [{"path": image["path"], "sha256": image["sha256"]} for image in images]
        jobs.require(dispatch.get("tool") == tool == binding["tool"] and dispatch.get("host") == binding["host"] and
                     dispatch.get("tool_arguments") == arguments == request["tool_arguments"] and
                     dispatch.get("images") == bound == expected,
                     "Native dispatch differs from the complete ordered request or upload mapping")
    elif images:
        def strings(value):
            if isinstance(value, str):
                return [value]
            if isinstance(value, dict):
                return [item for child in value.values() for item in strings(child)]
            if isinstance(value, list):
                return [item for child in value for item in strings(child)]
            return []
        values = [str(Path(value).resolve()) if Path(value).is_absolute() else value
                  for value in strings(request["tool_arguments"])]
        jobs.require(all(image["path"] in values for image in images),
                     "Native local arguments must include every input path; URL transport needs a prepared native_dispatch")


def reserve(request, job_dir, *, authorization, tool, binding=None, base=None):
    jobs.require(isinstance(request, dict) and set(request) <= {"tool_arguments", "images", "purpose", "native_dispatch"}, "Native request needs exact tool arguments and input image hashes")
    jobs.require(isinstance(request.get("tool_arguments"), dict), "Bind actual native tool arguments before claiming")
    jobs.require(isinstance(tool, str) and tool.strip(), "Bind the actual native tool name")
    jobs.require(isinstance(authorization, dict) and isinstance(authorization.get("source_ref"), str) and authorization["source_ref"].strip(), "Native image work needs its existing authorization source")
    folder = jobs._external(job_dir)
    jobs.require(not folder.exists(), "Native invocation already exists; reconcile its original attempt")
    project = Path(base or folder.parent).resolve()
    images = [jobs._record_input(row, project) for row in request.get("images", [])]
    bound = {**deepcopy(request), "images": images}
    _validate_inputs(bound, tool, project)
    jobs.require(not authorization.get("request_sha256") or authorization["request_sha256"] == adapters.fingerprint(bound),
                 "Native authorization binds another request")
    data = {"schema": "greybox.native-job/v1", "job_id": uuid.uuid4().hex,
            "state": "reserved", "created_at": jobs.now(), "tool": tool,
            "request": bound, "request_sha256": adapters.fingerprint(bound),
            "authorization": deepcopy(authorization), "binding": deepcopy(binding or {}),
            "project": str(project),
            "execution_mode": "agent_driven", "independent_dispatch": False}
    folder.mkdir(parents=True, mode=0o700)
    jobs._write(folder / "job.json", data)
    return _summary(folder, data)


def _job(path):
    folder = jobs._external(path)
    data = jobs._read(folder / "job.json")
    jobs.require(data.get("schema") == "greybox.native-job/v1", "Unsupported native invocation ledger")
    jobs.require(adapters.fingerprint(data["request"]) == data["request_sha256"], "Native request binding changed")
    return folder, data


def _summary(folder, data):
    return {"ok": data["state"] not in {"unknown", "failed", "cancelled"}, "job_id": data["job_id"],
            "job_dir": str(folder), "state": data["state"], "tool": data["tool"],
            "request_hash": data["request_sha256"], "execution_mode": "agent_driven",
            "independent_dispatch": False, "capability_gap": "native_independent_dispatch_unavailable",
            "outputs": data.get("outputs", [])}


def capabilities(binding=None):
    return {"invocation_channel": "host_native", "execution_mode": "agent_driven",
            "independent_dispatch": False, "supported_actions": ["claim", "record", "settle"],
            "capability_gap": "No registered and qualified independent native invocation implementation"}


def scan(source):
    folder, data = _job(source["path"])
    pool = source.get("pools", {}).get(data["tool"])
    jobs.require(isinstance(pool, str) and pool.strip(), "Bind the native tool to its actual shared account pool")
    state = data["state"]
    status, action = {"reserved": ("pending", "submit"), "submitting": ("unknown", None),
                      "unknown": ("unknown", None), "submitted": ("active", None),
                      "running": ("active", None), "ready": ("ready", None)}.get(state, ("blocked", None))
    active = status in {"active", "unknown"}
    return [{"id": data["job_id"], "state": status, "action": action, "pool": pool,
             "next_at": data.get("execution_next_at", 0), "lease": data.get("execution_lease"),
             "occupied": active, "remote_active": active,
             "remote_terminal": state in {"ready", "failed", "cancelled"},
             "execution_mode": "agent_driven", "independent_dispatch": False,
             "deferred_reason": "native_independent_dispatch_unavailable", "ledger": str(folder / "job.json")}]


def prepare(source, task_id, action, lease):
    folder, _ = _job(source["path"])
    with jobs._lock(folder):
        _, data = _job(folder)
        jobs.require(task_id == data["job_id"] and not data.get("execution_lease"), "Native action is unknown or already leased")
        jobs.require(scan(source)[0]["action"] == action, "Native action is not ready")
        jobs.require(action == "submit", "Native queries need their actual host mapping; reconcile a terminal original result with settle")
        _validate_inputs(data["request"], data["tool"], data["project"])
        if action == "submit":
            jobs.require(data["state"] == "reserved" and data["authorization"].get("source_ref"), "Native attempt cannot be resubmitted")
            data.update(state="submitting", invocation_started_at=jobs.now())
            data["submission_action_id"] = lease["id"]
            data["submission_ticket_path"] = lease.get("ticket_path")
        data["execution_lease"] = deepcopy(lease)
        ticket = {"kind": "native", "source": deepcopy(source), "id": task_id, "action": action,
                  "lease": deepcopy(lease), "request_hash": data["request_sha256"],
                  "attempt_id": data["job_id"], "tool": data["tool"],
                  "tool_arguments": deepcopy(data["request"]["tool_arguments"]),
                  "images": deepcopy(data["request"]["images"]), "provider_task_id": data.get("provider_task_id")}
        atomic_json(lease["ticket_path"], ticket)
        jobs._write(folder / "job.json", data)
        return ticket


def invoke(ticket):
    raise adapters.ImageError("Native tools require the actual host to execute the claimed action; autonomous native dispatch is unavailable", code="NATIVE_DISPATCH_UNAVAILABLE", category="capability", acceptance="not_accepted")


def commit(source, ticket, outcome, *, _settlement=False):
    folder, initial = _job(source["path"])
    fingerprint = adapters.fingerprint(outcome)
    result = outcome.get("result", {})
    output = None
    jobs.require(ticket["tool"] == initial["tool"] and ticket["tool_arguments"] == initial["request"]["tool_arguments"] and
                 ticket["images"] == initial["request"]["images"], "Native action payload differs from its immutable request")
    if outcome.get("ok") is True:
        jobs.require(result.get("action_id") == ticket["lease"]["id"] and result.get("attempt_id") == ticket["attempt_id"] and
                     result.get("request_hash") == ticket["request_hash"], "Native receipt does not match the claimed action and request")
        jobs.require(result.get("actual_arguments") == ticket["tool_arguments"], "Native tool arguments differ from the approved exact mapping")
        jobs.require(isinstance(result.get("source_ref"), str) and result["source_ref"].strip(), "Native receipt needs actual invocation evidence")
        jobs.require(result.get("state") in {"submitted", "running", "succeeded", "failed", "cancelled"}, "Native receipt has an unsupported state")
        _validate_inputs(initial["request"], initial["tool"], initial["project"])
        if result["state"] == "succeeded":
            output = adapters.image_info(result.get("output_path", ""))
            output["path"] = str(jobs._external(result["output_path"]))
        if result["state"] in {"submitted", "running"}:
            jobs.require(isinstance(result.get("provider_task_id"), str) and result["provider_task_id"].strip(), "Async native result needs its actual task identity")
    with jobs._lock(folder):
        _, data = _job(folder)
        if _settlement and data.get("native_settlement_sha256"):
            jobs.require(data["native_settlement_sha256"] == result.get("settlement_sha256"), "Conflicting duplicate native settlement")
            return _summary(folder, data)
        previous = data.get("execution_committed", {}).get(ticket["lease"]["id"])
        if previous:
            jobs.require(previous == fingerprint, "Conflicting duplicate native receipt")
            return _summary(folder, data)
        valid_lease = data.get("execution_lease") == ticket["lease"]
        if _settlement:
            valid_lease = (not data.get("execution_lease") and data["state"] in {"submitted", "running", "unknown"}
                           and data.get("provider_task_id") == ticket.get("provider_task_id"))
        jobs.require(data["job_id"] == ticket["attempt_id"] and data["request_sha256"] == ticket["request_hash"] and valid_lease,
                     "Native action lease is stale")
        if outcome.get("ok") is True:
            if ticket["action"] == "settle":
                jobs.require(str(result.get("provider_task_id")) == str(data.get("provider_task_id")), "Native status receipt belongs to another original task")
            if output:
                receipt = {"schema": 1, "kind": "reference-image-generation-receipt", "tool": data["tool"],
                           "actual_input_image_sha256": [row["sha256"] for row in ticket["images"]],
                           "output_sha256": output["sha256"], "invocation_recorded": True,
                           "actual_tool_arguments": result["actual_arguments"], "source_ref": result["source_ref"],
                           "action_id": data.get("submission_action_id", result["action_id"]),
                           "record_action_id": result["action_id"], "attempt_id": result["attempt_id"], "request_hash": result["request_hash"]}
                path = folder / "receipt-0.json"
                jobs._write(path, receipt)
                data.update(state="ready", outputs=[dict(output, receipt={"path": str(path), "sha256": provider_http.file_hash(path)})])
            else:
                data["state"] = result["state"]
            if result.get("provider_task_id"):
                data["provider_task_id"] = str(result["provider_task_id"])
            if ticket["action"] == "settle":
                data["native_settlement_sha256"] = result["settlement_sha256"]
        else:
            error = outcome.get("error", {})
            if ticket["action"] == "submit":
                data["state"] = "reserved" if error.get("acceptance") == "not_accepted" else "unknown"
            data["error"] = {"code": error.get("code", "NATIVE_ACTION_INCOMPLETE"), "message": "Reconcile the actual original host invocation"}
        data.pop("execution_lease", None)
        data["execution_next_at"] = time.time() + float(source.get("poll_interval", 1.0))
        committed = data.setdefault("execution_committed", {})
        committed[ticket["lease"]["id"]] = fingerprint
        while len(committed) > 64:
            committed.pop(next(iter(committed)))
        jobs._write(folder / "job.json", data)
        return _summary(folder, data)


def settle(job_dir, provider_task_id=None, receipt=None):
    """Record an original native terminal result, without invoking a tool.

    A query tool mapping is not inferred from the original generation arguments.
    Async work binds its saved task ID; late synchronous work binds the exact
    original action/attempt/request receipt instead of inventing a task ID.
    """
    jobs.require(isinstance(receipt, dict) and receipt.get("state") in {"succeeded", "failed", "cancelled"},
                 "Native settle only accepts a confirmed original terminal result")
    folder, _ = _job(job_dir)
    supplied_fingerprint = adapters.fingerprint({"provider_task_id": provider_task_id, "receipt": receipt})
    lease = {"id": uuid.uuid4().hex, "owner_pid": None, "deadline": time.time() + 60}
    with jobs._lock(folder):
        _, data = _job(folder)
        if data.get("native_settlement_sha256"):
            jobs.require(data["native_settlement_sha256"] == supplied_fingerprint, "Conflicting duplicate native settlement")
            return _summary(folder, data)
        jobs.require(data["state"] in {"submitted", "running", "unknown"} and not data.get("execution_lease"),
                     "Native settle needs an unresolved original task without a current action lease")
        if data.get("provider_task_id"):
            jobs.require(isinstance(provider_task_id, str) and provider_task_id and data["provider_task_id"] == provider_task_id,
                         "Native settle cannot replace or invent the original task identity")
        else:
            jobs.require(provider_task_id is None and data["state"] == "unknown" and
                         receipt.get("action_id") == data.get("submission_action_id") and
                         receipt.get("attempt_id") == data["job_id"] and receipt.get("request_hash") == data["request_sha256"],
                         "Unknown synchronous native work needs the exact original action, attempt and request receipt")
        ticket = {"kind": "native", "source": {"kind": "native", "path": str(folder)},
                  "id": data["job_id"], "action": "settle", "lease": lease,
                  "request_hash": data["request_sha256"], "attempt_id": data["job_id"],
                  "tool": data["tool"], "tool_arguments": deepcopy(data["request"]["tool_arguments"]),
                  "images": deepcopy(data["request"]["images"]), "provider_task_id": provider_task_id}
    result = {**deepcopy(receipt),
              "action_id": lease["id"], "attempt_id": ticket["attempt_id"], "request_hash": ticket["request_hash"],
              "settlement_sha256": supplied_fingerprint}
    if provider_task_id:
        result["provider_task_id"] = provider_task_id
    # This is a local terminal observation, with no provider call to reserve.
    # Pixel validation is outside the lock; commit compares the original task
    # identity again and atomically saves the actual result and dedup receipt.
    return commit(ticket["source"], ticket, {"ok": True, "result": result}, _settlement=True)
