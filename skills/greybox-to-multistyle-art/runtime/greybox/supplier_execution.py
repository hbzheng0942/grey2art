"""Leased supplier actions for the common executor, using the original ledger.

Preparation and receipt commits hold the existing short run lock. Network calls,
live quotation, downloads and canonical publication run in the isolated action
worker. This module never creates a second task or cost ledger.
"""
from __future__ import annotations

import copy
import json
import math
import os
from pathlib import Path
import time

from . import core, supplier_jobs as jobs, suppliers


ACTIVE = {"submitting", "submitted", "queued", "running", "unknown", "recovery_required"}
TERMINAL = {"succeeded", "ready", "artifact_recovery", "failed", "cancelled"}
BLOCKED = {"failed", "cancelled", "rejected", "budget_exceeded", "blocked_duplicate", "recovery_required", "preflight_blocked"}


def _source(source):
    core.require(isinstance(source, dict) and source.get("kind") == "supplier", "Expected a supplier execution source")
    run = Path(source.get("path", "")).expanduser().resolve()
    core.require((run / "supplier-run.json").is_file(), "Supplier execution needs an existing prepared run")
    pools = source.get("pools")
    core.require(isinstance(pools, dict), "Bind supplier IDs to confirmed shared account pools")
    return run, pools


def _operation(option, oid):
    operation = next((item for item in option["operations"] if item["id"] == oid), None)
    core.require(operation is not None, "Execution names an operation outside the frozen portfolio")
    return operation


def _run_limit(source, portfolio, provider):
    limits = dict(portfolio.get("execution_limits", {}).get("max_inflight_per_provider", {}))
    override = source.get("execution_limits")
    if override is not None:
        core.require(isinstance(override, dict) and isinstance(override.get("source_ref"), str)
                     and override["source_ref"].strip(), "Operational concurrency override needs its actual source_ref")
        changes = override.get("max_inflight_per_provider", {})
        core.require(isinstance(changes, dict), "Operational concurrency overrides must be a provider map")
        limits.update(changes)
    core.require(isinstance(limits, dict) and all(core.safe_id(k) and type(v) is int and v > 0
                 for k, v in limits.items()), "Run concurrency limits must be positive integers")
    return limits.get(provider)


def _runnable(source, state, portfolio, operation):
    if state.get("cost_overrun"):
        return "budget_overrun"
    if portfolio.get("workspace") is None:
        return "historical_recovery_only"
    if not all(state["operations"][d]["state"] == "ready" for d in operation.get("depends_on", [])):
        return "dependency"
    if any(jobs._artifact_problems(state["operations"][d], cached=True) for d in operation.get("depends_on", [])):
        return "dependency_artifact_recovery"
    limit = _run_limit(source, portfolio, operation["provider"])
    occupied = sum(row.get("provider") == operation["provider"] and row.get("state") in ACTIVE
                   for row in state["operations"].values())
    if limit is not None and occupied >= limit:
        return "run_capacity"
    return None


def scan(source):
    run, pools = _source(source)
    state, portfolio, _, _, option = jobs._load(run)
    result = []
    for operation in option["operations"]:
        oid = operation["id"]
        row = state["operations"][oid]
        provider = operation["provider"]
        core.require(isinstance(pools.get(provider), str) and pools[provider].strip(),
                     "Missing shared account pool binding for supplier: " + provider)
        observed = row["state"]
        occupied = observed in ACTIVE
        terminal = observed in TERMINAL
        reason, action = None, None
        if observed == "ready":
            normalized = "blocked" if jobs._artifact_problems(row, cached=True) else "ready"
            reason = "artifact_recovery_required" if normalized == "blocked" else None
        elif observed in {"succeeded", "artifact_recovery"}:
            normalized, action = "download", "fetch"
        elif observed in {"unknown", "submitting", "recovery_required"} and not row.get("execution"):
            normalized, reason = "unknown", "reconcile_original_submission"
        elif observed in {"submitted", "queued", "running"} or observed == "submitting" and row.get("execution"):
            normalized, action = "active", "status" if row.get("task_id") else None
        elif observed in BLOCKED:
            normalized, reason = "blocked", observed
        else:
            reason = _runnable(source, state, portfolio, operation)
            normalized, action = "pending", None if reason else "submit"
        if row.get("execution"):
            action = None  # Only the executor may recover that exact action receipt.
        result.append({"id": oid, "state": normalized, "pool": pools[provider], "action": action,
                       "next_at": float(row.get("execution_next_at", 0)),
                       "lease": copy.deepcopy(row.get("execution")), "occupied": occupied,
                       "remote_terminal": terminal, "deferred_reason": reason})
    return result


def _submission_gate(run, state, portfolio, registry, selection, option):
    """Same pre-production authorities as the legacy one-step runner."""
    core.require(not state.get("cost_overrun"), "Actual supplier charge exceeded its approved reservation")
    core.require(portfolio.get("workspace") is not None, "Historical runs permit original task recovery only")
    suppliers.validate_selection(selection, portfolio, registry, base=state["project"])
    jobs._validate_run_path(portfolio, Path(state["project"]), run)
    jobs._validate_publish_paths(option, state["project"], portfolio)
    if state["expansion"]:
        from . import account_profiles
        for operation in option["operations"]:
            provider = next(p for p in registry["providers"] if p["id"] == operation["provider"])
            profile = provider.get("account_profile")
            profile_sha = account_profiles.profile_digest(provider["id"], profile) if profile is not None else None
            core.require(suppliers._verification(provider.get("verification", {}).get("operations", {}).get(operation["operation"]),
                         state["project"], account_profile_sha256=profile_sha),
                         "Qualification-only operation cannot enter expansion")
    core.require(core.file_hash(state["workflow"]["path"]) == state["workflow"]["sha256"], "Workflow changed")
    core.require(core.runtime_snapshot()["sha256"] == state["runtime_digest"], "Producer runtime changed")
    readiness = core.read(run / "supplier-readiness.json")
    core.require(core.digest(readiness) == state["readiness"]["sha256"], "Readiness receipt changed")
    jobs._gate(portfolio, selection, state["workflow"]["path"], state["project"], readiness,
               state["readiness"]["session_id"], state["expansion"])
    for operation in option["operations"]:
        core.require(jobs._inputs(operation, state["project"]) == state["inputs"][operation["id"]], "Operation inputs changed")
    for oid, row in state["operations"].items():
        if row.get("state") == "ready":
            core.require(not jobs._artifact_problems(row),
                         "Completed artifacts missing or changed for " + oid + "; use supplier-jobs recover-artifacts")


def _metadata_gate(run, state, selection):
    """Bound parent-side checks; expensive source validation stays in worker."""
    core.require(selection.get("gate") == "H3" and selection.get("actor") == "user"
                 and selection.get("decision") == "approved", "Supplier production needs its actual H3 decision")
    core.require(isinstance(selection.get("source_ref"), str) and selection["source_ref"].strip(),
                 "Supplier decision needs its actual source reference")
    core.require(core.file_hash(state["workflow"]["path"]) == state["workflow"]["sha256"], "Workflow changed")
    readiness = core.read(run / "supplier-readiness.json")
    core.require(core.digest(readiness) == state["readiness"]["sha256"], "Readiness receipt changed")


def _lease(lease):
    core.require(isinstance(lease, dict) and isinstance(lease.get("id"), str) and lease["id"], "Action needs its unique lease ID")
    core.require(type(lease.get("deadline")) in {int, float} and lease["deadline"] > time.time(), "Action deadline must be in the future")
    for name in ("receipt_path", "ticket_path"):
        core.require(isinstance(lease.get(name), str) and Path(lease[name]).is_absolute(), "Action needs absolute private receipt/ticket paths")
    return copy.deepcopy(lease)


def prepare(source, oid, action, lease):
    run, pools = _source(source)
    lease = _lease(lease)
    core.require(action in {"submit", "status", "fetch"}, "Unsupported supplier execution action")
    with core.locked(run):
        state, portfolio, registry, selection, option = jobs._load(run)
        operation = _operation(option, oid)
        row = state["operations"][oid]
        core.require(not row.get("execution"), "Original action is still leased; recover its receipt before another invocation")
        core.require(pools.get(operation["provider"]), "Supplier account pool binding is missing")
        provider = next(p for p in registry["providers"] if p["id"] == operation["provider"])
        jobs._freeze_account_profile(row, provider)
        if action == "submit":
            core.require(row["state"] == "pending" and not row.get("task_id"), "Only an unsubmitted pending operation may create a task")
            core.require(not _runnable(source, state, portfolio, operation), "Supplier operation is not ready for submission")
            _metadata_gate(run, state, selection)
            from .production_control import guard_submission
            guard_submission(state["project"], portfolio, operation["asset_id"], operation["operation"], run, core.digest(operation))
            try:
                row["claim_path"] = jobs._claim(state, run, operation)
            except (ValueError, OSError):
                row["state"] = "blocked_duplicate"
                core.write(run / "supplier-run.json", state)
                from .production_control import release_unsubmitted
                if oid not in state["reservations"]:
                    release_unsubmitted(state["project"], portfolio, operation["asset_id"], operation["operation"], run, core.digest(operation))
                raise
            # A single operation keeps one original budget reservation across
            # proven-unaccepted capacity/limit responses; no retry ledger reset.
            if oid not in state["reservations"]:
                jobs._reserve(state, operation)
            row.update(state="submitting", provider=operation["provider"], request_digest=core.digest(operation))
            row["submission_attempts"] = row.get("submission_attempts", 0) + 1
            request = {k: copy.deepcopy(operation[k]) for k in ("operation", "model_version", "parameters")}
            request.update(inputs=state["inputs"][oid],
                           dependencies={d: {k: v for k, v in state["operations"][d].items()
                                             if k in {"provider", "task_id", "artifacts", "state"}}
                                         for d in operation.get("depends_on", [])},
                           quote=operation["pricing"], output_dir=str(run / "outputs" / oid))
        else:
            core.require(row.get("task_id"), "Task recovery requires its original provider ID")
            allowed = {"submitted", "queued", "running"} if action == "status" else {"succeeded", "artifact_recovery"}
            core.require(row["state"] in allowed, "Supplier action does not match the original task state")
            request = jobs._context(operation, row)
            if action == "fetch":
                request = jobs._fetch_request(run, state, portfolio, operation, row, action_id=lease["id"])
        ticket = {"kind": "supplier", "source": copy.deepcopy(source), "id": oid, "action": action, "lease": lease,
                  "operation": copy.deepcopy(operation), "request": request,
                  "binding": {"portfolio_digest": state["portfolio_digest"], "registry_digest": state["registry_digest"],
                              "selection_digest": state["selection_digest"], "workflow": state["workflow"]}}
        if row.get("artifact_recovery"):
            ticket["artifact_recovery"] = copy.deepcopy(row["artifact_recovery"])
        ticket["request_hash"] = core.digest(ticket)
        # Write ahead: a persisted action lease must never refer to a ticket
        # that has not reached disk. No child can start before this returns.
        from .execution_process import atomic_json
        atomic_json(lease["ticket_path"], ticket)
        row["execution"] = {**lease, "action": action, "request_hash": ticket["request_hash"]}
        if source.get("execution_limits") is not None:
            row["execution_limits_source"] = copy.deepcopy(source["execution_limits"])
        core.write(run / "supplier-run.json", state)
    return ticket


def _ticket(ticket):
    core.require(isinstance(ticket, dict), "Supplier action ticket must be an object")
    # The coordinator adds its own operational locations after backend prepare;
    # they do not alter the bound supplier request or its original lease.
    digest = core.digest({k: v for k, v in ticket.items()
                          if k not in {"request_hash", "execution_state_dir", "execution_queue"}})
    core.require(digest == ticket.get("request_hash"), "Supplier action request binding changed")
    run, _ = _source(ticket["source"])
    state, portfolio, registry, selection, option = jobs._load(run)
    operation = _operation(option, ticket["id"])
    core.require(core.digest(operation) == core.digest(ticket["operation"]), "Frozen supplier operation changed")
    binding = ticket["binding"]
    core.require(all(state[k] == binding[k] for k in ("portfolio_digest", "registry_digest", "selection_digest", "workflow")),
                 "Supplier action provenance changed")
    row = state["operations"][ticket["id"]]
    core.require(row.get("artifact_recovery") == ticket.get("artifact_recovery"),
                 "Original artifact recovery identity changed after action preparation")
    lease = row.get("execution", {})
    core.require(lease.get("id") == ticket["lease"]["id"] and lease.get("request_hash") == digest,
                 "Supplier action no longer owns its original lease")
    return run, state, portfolio, registry, selection, operation, row


def _start_submit(ticket):
    """An action ticket may cross the creation boundary only once."""
    marker = Path(ticket["lease"]["ticket_path"]).with_name("invoked.json")
    marker.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        fd = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        error = RuntimeError("Original action was already invoked; reconcile its receipt")
        error.code = "EXECUTION_ALREADY_INVOKED"
        error.category = "protocol"
        error.unknown_submission = True
        raise error from None
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump({"id": ticket["lease"]["id"], "request_hash": ticket["request_hash"], "started_at": core.now()}, handle)
        handle.flush()
        os.fsync(handle.fileno())
    _, state, _, _, _, operation, row = _ticket(ticket)
    claim = core.read(row["claim_path"])
    core.write(row["claim_path"], {**claim, "phase": "attempted", "attempted_at": core.now()})
    jobs._guard_update(state, operation, row, "attempted")


def _receipts(request, preflight=None):
    metadata = {k: request[k] for k in ("_live_quote_receipt", "_submitted_parameters", "_upload_receipt") if k in request}
    if preflight is not None:
        metadata["_character_preflight"] = preflight
    return metadata


def _stat(path):
    observed = Path(path).stat()
    return {"bytes": observed.st_size, "mtime_ns": observed.st_mtime_ns,
            "inode": observed.st_ino, "device": observed.st_dev}


def _interval(source, key, default):
    value = source.get(key, default)
    core.require(type(value) in {int, float} and math.isfinite(value) and 0 <= value <= 86400,
                 "Execution interval must be a finite nonnegative number")
    return float(value)


def invoke(ticket):
    """One isolated action. Never edits the supplier lifecycle or cost ledger."""
    from .execution_errors import classify_error, response_error
    request = copy.deepcopy(ticket["request"])
    started, preflight = False, None
    try:
        run, state, portfolio, registry, selection, operation, row = _ticket(ticket)
        if ticket["action"] == "submit":
            # Recheck the actual immutable authorities immediately before any
            # upload/quote/create, even when dispatch waited on a local worker.
            _submission_gate(run, state, portfolio, registry, selection,
                             next(o for o in portfolio["options"] if o["id"] == state["selected_option"]))
            from . import character_gate
            preflight = character_gate.for_supplier(operation, state, run, registry)
            _start_submit(ticket)
        authorization = {"selection": selection, "portfolio": portfolio, "operation_id": operation["id"]}
        started = True
        response = jobs._invoke(registry, operation, ticket["action"], request, authorization, state["project"])
        if not isinstance(response, dict) or response.get("ok") is not True:
            return {"provider_result": response if isinstance(response, dict) else {},
                    "execution_error": response_error(response, ticket["action"]),
                    "request_receipts": _receipts(request, preflight)}
        if ticket["action"] == "status":
            core.require(response.get("state") in {"queued", "running", "succeeded", "failed", "cancelled"},
                         "Provider query did not return a known task state")
            core.require(not response.get("task_id") or str(response["task_id"]) == row["task_id"],
                         "Provider query returned another task identity")
        if ticket["action"] == "fetch":
            response = {**response, **jobs._accept_fetch(run, state, portfolio, operation, row, response, request["output_dir"])}
            # Full byte/container checks happened above in the isolated worker.
            # The coordinator checks these cheap immutable-output observations.
            response["artifact_observations"] = [{"path": a["path"], "sha256": a["sha256"], **_stat(a["path"])}
                                                  for a in response["artifacts"]]
        return {"provider_result": response, "request_receipts": _receipts(request, preflight)}
    except Exception as exc:
        error = classify_error(exc, ticket["action"])
        if ticket["action"] == "submit" and not started and getattr(exc, "unknown_submission", None) is not True:
            error["acceptance"] = "not_accepted"
            if isinstance(exc, core.WorkflowError):
                error["code"] = "SUPPLIER_PREFLIGHT_BLOCKED"
                error["local_reason"] = str(exc)[:512]
        return {"execution_error": error, "request_receipts": _receipts(request, preflight)}


def _unaccepted(state, operation, row, retryable):
    """Retain attempt history but permit retry of a confirmed unaccepted POST."""
    if row.get("claim_path"):
        claim = core.read(row["claim_path"])
        phase = "reserved" if retryable else "rejected"
        core.write(row["claim_path"], {**claim, "phase": phase, "not_accepted_at": core.now()})
        jobs._guard_update(state, operation, row, phase)


def _summary(state):
    observed = {row["state"] for row in state["operations"].values()}
    state["state"] = ("blocked" if state.get("cost_overrun") or observed & (BLOCKED | {"unknown"}) else
                      "assets_ready" if observed <= {"ready"} else "waiting")


def commit(source, ticket, outcome):
    run, _ = _source(source)
    core.require(core.digest(source) == core.digest(ticket.get("source")), "Receipt source differs from its action ticket")
    with core.locked(run):
        state, portfolio, _, _, option = jobs._load(run)
        operation = _operation(option, ticket["id"])
        row = state["operations"][ticket["id"]]
        completed = row.get("execution_completed", {})
        if completed.get("id") == ticket["lease"]["id"]:
            core.require(completed.get("request_hash") == ticket.get("request_hash") and
                         completed.get("outcome_hash") == core.digest(outcome), "Conflicting duplicate supplier receipt")
            return {"duplicate": True, "state": row["state"]}
        _ticket(ticket)
        core.require(isinstance(outcome, dict) and type(outcome.get("ok")) is bool, "Action outcome needs boolean ok")
        wrapped = outcome.get("result", {}) if outcome["ok"] else {}
        core.require(isinstance(wrapped, dict), "Supplier action result must be an object")
        jobs._submission_receipts(row, wrapped.get("request_receipts", {}))
        if wrapped.get("request_receipts", {}).get("_character_preflight") is not None:
            row["character_preflight"] = wrapped["request_receipts"]["_character_preflight"]
        response = wrapped.get("provider_result", wrapped)
        core.require(isinstance(response, dict), "Supplier provider result must be an object")
        error = outcome.get("error") if not outcome["ok"] else wrapped.get("execution_error")
        blocked = []
        action = ticket["action"]
        result = {"state": row["state"]}
        if error is not None:
            core.require(isinstance(error, dict), "Action error must be structured")
            row["execution_error"] = copy.deepcopy(error)
            row["execution_error_count"] = row.get("execution_error_count", 0) + 1
            delay = error.get("retry_after")
            if delay is None:
                delay = min(86400., _interval(source, "retry_interval", 2) * 2 ** min(row["execution_error_count"] - 1, 5))
            core.require(type(delay) in {int, float} and math.isfinite(delay) and delay >= 0,
                         "Retry cooldown must be a finite nonnegative number")
            row["execution_next_at"] = time.time() + max(.05, float(delay))
            result.update(acceptance=error.get("acceptance", "unknown"),
                          category=error.get("category"), retry_after=error.get("retry_after"))
            if action == "submit":
                if response.get("task_id"):
                    row["task_id"] = str(response["task_id"])
                if isinstance(response.get("recovery"), dict):
                    row["recovery"] = response["recovery"]
                acceptance = error.get("acceptance", "unknown")
                if row.get("task_id"):
                    acceptance = "accepted"
                    claim = core.read(row["claim_path"])
                    core.write(row["claim_path"], {**claim, "phase": "accepted", "task_id": row["task_id"],
                               "recovery": row.get("recovery", {}), "accepted_at": core.now()})
                    jobs._record_cost(state, ticket["id"], row, response, blocked)
                retryable = acceptance == "not_accepted" and error.get("category") in {"capacity", "rate_limit", "network", "timeout", "local"}
                preflight = acceptance == "not_accepted" and error.get("code") == "SUPPLIER_PREFLIGHT_BLOCKED"
                row["state"] = "preflight_blocked" if preflight else ("pending" if retryable else "rejected" if acceptance == "not_accepted" else "unknown")
                if acceptance == "not_accepted":
                    _unaccepted(state, operation, row, retryable)
                else:
                    jobs._guard_update(state, operation, row, "unknown")
                result.update(acceptance=acceptance, category=error.get("category"), retry_after=error.get("retry_after"))
            # A failed query/download retains the original task and its state.
            row["last_error"] = "Action incomplete; retain original task identity and recover without generation"
        elif action == "submit":
            core.require(isinstance(response, dict), "Supplier create result must be an object")
            if response.get("task_id"):
                row["task_id"] = str(response["task_id"])
            if isinstance(response.get("recovery"), dict):
                row["recovery"] = response["recovery"]
            if row.get("task_id"):
                claim = core.read(row["claim_path"])
                core.write(row["claim_path"], {**claim, "phase": "accepted", "task_id": row["task_id"],
                           "recovery": row.get("recovery", {}), "accepted_at": core.now()})
                jobs._record_cost(state, ticket["id"], row, response, blocked)
            if response.get("ok") is True and isinstance(response.get("task_id"), str) and response["task_id"].strip():
                row.update(state="recovery_required" if response.get("state") == "recovery_required" else "submitted",
                           submitted_at=core.now(), execution_next_at=0)
                jobs._guard_update(state, operation, row, "recovery_required" if row["state"] == "recovery_required" else "accepted")
                result["acceptance"] = "accepted"
            else:
                # A malformed create reply cannot prove that no task was created.
                row["state"] = "unknown"
                jobs._guard_update(state, operation, row, "unknown")
                result["acceptance"] = "unknown"
        elif action == "status":
            observed = response.get("state")
            core.require(response.get("ok") is True and observed in {"queued", "running", "succeeded", "failed", "cancelled"},
                         "Query needs an actual known provider state")
            core.require(not response.get("task_id") or str(response["task_id"]) == row["task_id"], "Query returned another task identity")
            jobs._record_cost(state, ticket["id"], row, response, blocked)
            row.update(state=observed, checked_at=core.now(),
                       execution_next_at=time.time() + _interval(source, "poll_interval", 2)
                       if observed in {"queued", "running"} else 0)
        else:
            core.require(response.get("ok") is True and isinstance(response.get("artifacts"), list) and response["artifacts"],
                         "Fetch needs verified published artifacts")
            artifacts = response["artifacts"]
            observations = response.get("artifact_observations", [])
            core.require(len(observations) == len(artifacts), "Fetch needs isolated worker output observations")
            by_path = {a["path"]: a for a in observations}
            for artifact in artifacts:
                observation = by_path.get(artifact["path"], {})
                core.require(observation.get("sha256") == artifact.get("sha256")
                             and all(observation.get(k) == value for k, value in _stat(artifact["path"]).items()),
                             "Published output changed after its isolated worker validation")
            jobs._record_cost(state, ticket["id"], row, response, blocked)
            jobs._finish_artifact_recovery(row, response)
            row.update(state="ready", artifacts=artifacts, execution_next_at=0)
        row["execution_completed"] = {"id": ticket["lease"]["id"], "request_hash": ticket["request_hash"],
                                      "outcome_hash": core.digest(outcome), "at": core.now()}
        if error is None:
            row.pop("execution_error", None)
            row.pop("execution_error_count", None)
            row.pop("last_error", None)
        row.pop("execution", None)
        _summary(state)
        if blocked:
            state["blockers"] = list(dict.fromkeys(state.get("blockers", []) + blocked))
        state["events"].append({"at": core.now(), "execution_action": action, "operation_id": ticket["id"], "state": row["state"]})
        core.write(run / "supplier-run.json", state)
        return {**result, "state": row["state"], "occupied": row["state"] in ACTIVE,
                "remote_terminal": row["state"] in TERMINAL}


def retry_preflight(source, source_ref):
    """Recheck corrected known-unsent work; never reset an accepted/unknown task."""
    core.require(isinstance(source_ref, str) and source_ref.strip(), "Bind the actual correction or continuation source")
    run, _ = _source(source)
    count = 0
    with core.locked(run):
        state, _, _, _, option = jobs._load(run)
        for operation in option['operations']:
            row = state['operations'][operation['id']]
            error = row.get('execution_error', {})
            if row['state'] != 'preflight_blocked':
                continue
            core.require(not row.get('task_id') and not row.get('execution') and
                         error.get('code') == 'SUPPLIER_PREFLIGHT_BLOCKED' and error.get('acceptance') == 'not_accepted',
                         "Only proven unsubmitted preparation can be rechecked")
            _unaccepted(state, operation, row, retryable=True)
            row.update(state='pending', execution_next_at=0)
            row['preflight_recheck_source'] = source_ref
            count += 1
        _summary(state)
        core.write(run / 'supplier-run.json', state)
    return count
