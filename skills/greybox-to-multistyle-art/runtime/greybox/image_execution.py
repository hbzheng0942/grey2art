"""Short-lock image ledger backend for the shared execution scheduler.

Provider calls and artifact I/O happen in the isolated action worker. Only
prepare/commit mutate job.json, and every result binds the exact action lease.
"""
from __future__ import annotations

from copy import deepcopy
import os
from pathlib import Path
import stat
import time

from . import image_adapters as adapters, image_jobs as jobs, provider_http
from .execution_process import atomic_json


def _stat(path):
    value = Path(path).lstat()
    jobs.require(stat.S_ISREG(value.st_mode), "Image worker output must remain a regular file")
    return {"size": value.st_size, "mtime_ns": value.st_mtime_ns, "ino": value.st_ino, "dev": value.st_dev}


def _stage_response(folder, response, action, expected_task_id=None):
    """Save large transport bodies once in the worker; return small metadata."""
    jobs.require(isinstance(response, dict), "Image adapter returned a malformed response")
    path = folder / "provider-response.json"
    jobs._write(path, response)
    state = response.get("state")
    valid = state in {"submitted", "running", "succeeded", "failed", "cancelled"}
    if state in {"submitted", "running"}:
        identity = response.get("provider_task_id")
        valid = valid and isinstance(identity, str) and bool(identity.strip())
    if state == "succeeded":
        valid = valid and isinstance(response.get("items"), list) and bool(response["items"])
    if action == "status":
        valid = valid and str(response.get("provider_task_id")) == str(expected_task_id)
    if not valid:
        raise adapters.ImageError("Image adapter result is malformed; preserve the original invocation", code="IMAGE_RESULT_INVALID",
                                  category="protocol", acceptance="unknown" if action == "submit" else "accepted",
                                  unknown_submission=action == "submit")
    result = {key: response[key] for key in ("state", "provider_task_id", "usage", "actual_cost") if key in response}
    result["saved_response"] = {"path": str(path), "sha256": provider_http.file_hash(path), "stat": _stat(path)}
    result["items_count"] = len(response["items"]) if isinstance(response.get("items"), list) else 0
    return result


def _result(response, action):
    if isinstance(response, dict) and response.get("ok") is False:
        from .execution_errors import response_error
        error = response_error(response, action)
        raise adapters.ImageError(error["message"], code=error["code"], category=error["category"],
                                  acceptance=error["acceptance"], retry_after=error.get("retry_after"),
                                  provider_code=error.get("provider_code"),
                                  unknown_submission=action == "submit" and error["acceptance"] != "not_accepted")
    return response


def _pool(source, data):
    pool = source.get("pools", {}).get(data["profile_name"])
    jobs.require(isinstance(pool, str) and pool.strip(), "Bind this image profile to an explicit shared account pool")
    return pool


def scan(source):
    folder, data = jobs._job(source["path"])
    state = data["state"]
    mapped = {"reserved": ("pending", "submit"), "submitted": ("active", "status"),
              "running": ("active", "status"), "succeeded": ("download", "fetch"),
              "downloaded": ("ready", None), "submitting": ("unknown", None),
              "unknown": ("unknown", None)}
    status, action = mapped.get(state, ("blocked", None))
    if action == "status" and data["profile"]["kind"] == "openai":
        status, action = "unknown", None
    active = status in {"active", "unknown"}
    return [{"id": data["job_id"], "state": status, "pool": _pool(source, data),
             "action": action, "next_at": data.get("execution_next_at", 0),
             "lease": data.get("execution_lease"), "occupied": active,
             "remote_active": active, "remote_terminal": state in {"succeeded", "downloaded", "failed", "cancelled"},
             "execution_mode": "autonomous", "ledger": str(folder / "job.json"),
             "deferred_reason": "reconciliation_required" if status == "unknown" else data.get("execution_deferred_reason")}]


def _check_ticket(data, ticket):
    jobs.require(data["job_id"] == ticket["id"] and data["request_sha256"] == ticket["request_hash"],
                 "Image action belongs to another request or attempt")
    jobs.require(data.get("execution_lease") == ticket["lease"],
                 "Image action lease is stale or belongs to another worker")
    jobs.require(data["profile_sha256"] == ticket["profile_hash"], "Image action profile changed")
    jobs.require(adapters.fingerprint(ticket["request"]) == ticket["request_hash"] and
                 adapters.fingerprint(ticket["profile"]) == ticket["profile_hash"],
                 "Image action payload differs from its bound request or profile")


def prepare(source, task_id, action, lease):
    folder, _ = jobs._job(source["path"])
    with jobs._lock(folder):
        _, data = jobs._job(folder)
        jobs.require(data["job_id"] == task_id, "Unknown image task identity")
        jobs.require(not data.get("execution_lease"), "An image action already owns this job")
        jobs.require(scan(source)[0]["action"] == action, "Image action is not currently ready")
        jobs.require(isinstance(lease, dict) and isinstance(lease.get("id"), str), "Image execution needs an action lease")
        if action == "submit":
            jobs.require(data["state"] == "reserved", "Never resubmit an existing image invocation")
            binding = data.get("runtime_binding", {})
            jobs.require(binding.get("image_jobs_sha256") == provider_http.file_hash(jobs.__file__) and
                         binding.get("image_adapters_sha256") == provider_http.file_hash(adapters.__file__),
                         "Reserved image runtime changed; revise the unsubmitted request before dispatch")
            jobs.require(data.get("authorization", {}).get("source_ref"), "Image submission has no authorization source")
            for item in data["request"]["images"] + ([data["request"]["mask"]] if data["request"].get("mask") else []):
                jobs.require(Path(item["path"]).is_file(), "Approved image input is missing")
            jobs._validate_profile(data["profile"])
            data.update(state="submitting", invocation_started_at=jobs.now())
        data["execution_lease"] = deepcopy(lease)
        ticket = {"kind": "image", "source": deepcopy(source), "id": task_id, "action": action,
                  "lease": deepcopy(lease), "request_hash": data["request_sha256"],
                  "profile_hash": data["profile_sha256"], "profile": deepcopy(data["profile"]),
                  "request": deepcopy(data["request"]), "provider_task_id": data.get("provider_task_id")}
        atomic_json(lease["ticket_path"], ticket)
        jobs._save(folder, data)
        return ticket


def invoke(ticket):
    """Execute exactly one action; no job lock and no task-ledger writes."""
    folder, data = jobs._job(ticket["source"]["path"])
    _check_ticket(data, ticket)
    profile = jobs._validate_profile(ticket["profile"])
    action = ticket["action"]
    if action == "submit":
        jobs.require(data["state"] == "submitting", "Image create intent is no longer current")
        for item in ticket["request"]["images"] + ([ticket["request"]["mask"]] if ticket["request"].get("mask") else []):
            jobs.require(provider_http.file_hash(item["path"]) == item["sha256"], "Approved image input changed before invocation")
        marker = Path(ticket["lease"]["ticket_path"]).parent / "image-submit.started"
        try:
            descriptor = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            raise adapters.ImageError("Original image action was already invoked; reconcile it instead of creating again", unknown_submission=True, code="IMAGE_ACTION_ALREADY_INVOKED") from None
        with os.fdopen(descriptor, "w") as stream:
            stream.write(ticket["lease"]["id"])
            stream.flush()
            os.fsync(stream.fileno())
        return _stage_response(folder, _result(adapters.submit(profile, ticket["request"]), action), action)
    if action == "status":
        jobs.require(data.get("provider_task_id") == ticket["provider_task_id"], "Original image task ID changed")
        return _stage_response(folder, _result(adapters.status(profile, ticket["provider_task_id"]), action), action, ticket["provider_task_id"])
    jobs.require(action == "fetch", "Unsupported image execution action")
    snapshot = jobs._fetch_outputs(folder, deepcopy(data))
    return {"state": "downloaded", "outputs": snapshot["outputs"],
            "provider_response_sha256": snapshot.get("provider_response_sha256"),
            "output_stats": [{"path": output["path"], "sha256": output["sha256"], "stat": _stat(output["path"]),
                              "receipt_path": output["receipt"]["path"], "receipt_sha256": output["receipt"]["sha256"],
                              "receipt_stat": _stat(output["receipt"]["path"])} for output in snapshot["outputs"]]}


def commit(source, ticket, outcome):
    folder, _ = jobs._job(source["path"])
    fingerprint = adapters.fingerprint(outcome)
    with jobs._lock(folder):
        _, data = jobs._job(folder)
        previous = data.get("execution_committed", {}).get(ticket["lease"]["id"])
        if previous:
            jobs.require(previous == fingerprint, "Conflicting duplicate image action receipt")
            return jobs._summary(folder, data)
        _check_ticket(data, ticket)
        action = ticket["action"]
        if outcome.get("ok") is True:
            result = outcome.get("result")
            jobs.require(isinstance(result, dict), "Image action needs a real result object")
            if action == "fetch":
                jobs.require(result.get("state") == "downloaded" and result.get("outputs"), "Image fetch returned no verified outputs")
                proofs = result.get("output_stats", [])
                jobs.require(isinstance(proofs, list) and len(proofs) == len(result["outputs"]), "Image fetch needs worker verification fingerprints")
                for output, proof in zip(result["outputs"], proofs):
                    jobs.require(proof.get("path") == output["path"] and proof.get("sha256") == output["sha256"] and
                                 _stat(output["path"]) == proof.get("stat"), "Fetched image bytes changed after worker verification")
                    receipt = output.get("receipt", {})
                    jobs.require(proof.get("receipt_path") == receipt["path"] and proof.get("receipt_sha256") == receipt["sha256"] and
                                 _stat(receipt["path"]) == proof.get("receipt_stat"), "Image generation receipt changed after worker verification")
                data.update(state="downloaded", outputs=result["outputs"],
                            provider_response_sha256=result.get("provider_response_sha256"))
            else:
                state = result.get("state")
                jobs.require(state in {"submitted", "running", "succeeded", "failed", "cancelled"}, "Unknown image provider state")
                if state in {"submitted", "running"}:
                    jobs.require(isinstance(result.get("provider_task_id"), str) and result["provider_task_id"].strip(),
                                 "Async image result needs its actual provider task ID")
                if action == "status":
                    jobs.require(str(result.get("provider_task_id")) == str(data.get("provider_task_id")),
                                 "Image poll returned a different original task ID")
                if state == "succeeded":
                    jobs.require(result.get("items_count", len(result.get("items", []))) > 0, "Succeeded image response has no outputs")
                saved = result.get("saved_response")
                if saved:
                    jobs.require(saved.get("path") == str(folder / "provider-response.json") and
                                 _stat(saved["path"]) == saved.get("stat"), "Original image response changed after worker verification")
                    data["execution_response_sha256"] = saved["sha256"]
                jobs._accept_response(folder, data, result, response_saved=bool(saved))
            data.pop("error", None)
            data.pop("execution_deferred_reason", None)
            data["execution_next_at"] = time.time() + float(source.get("poll_interval", 1.0)) if data["state"] in {"submitted", "running"} else 0.
        else:
            error = outcome.get("error", {})
            category = error.get("category", "network")
            acceptance = error.get("acceptance", "unknown" if action == "submit" else "accepted")
            if action == "submit":
                retryable = acceptance == "not_accepted" and category in {"capacity", "rate_limit", "network", "timeout", "local"}
                data["state"] = "reserved" if retryable else ("rejected" if acceptance == "not_accepted" else "unknown")
            data["error"] = {"code": error.get("code", "IMAGE_ACTION_INCOMPLETE"),
                             "message": "Image action incomplete; preserve the original invocation and recovery evidence"}
            data["execution_deferred_reason"] = "reconciliation_required" if data["state"] == "unknown" else category
            data["execution_next_at"] = time.time() + max(.1, float(error.get("retry_after") or source.get("retry_interval", 1.0)))
        data.pop("execution_lease", None)
        committed = data.setdefault("execution_committed", {})
        committed[ticket["lease"]["id"]] = fingerprint
        while len(committed) > 64:
            committed.pop(next(iter(committed)))
        jobs._save(folder, data)
        return jobs._summary(folder, data)
