"""Opt-in, project/session-scoped WorkBuddy command hooks for S7 boards.

Registration is independent of production preparation. Only explicit install /
uninstall commands edit the explicitly selected host settings. This module never
invokes an image service or marks an image as accepted.
PostToolUse retains original evidence in a sidecar; an absent/unknown response
keeps the original production claim pending.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import secrets
import shlex
import stat
import sys
import tempfile
import uuid

from . import core


def _json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write_once(path, value):
    path = Path(path)
    core.ensure_directory(path.parent)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def _safe_key(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _registration(scope_path):
    value = _json(scope_path)
    core.require(isinstance(value, dict) and value.get("kind") == "workbuddy-board-guard-scope"
                 and value.get("schema") == 1, "Unsupported board guard scope")
    project, workspace = Path(value["project"]).resolve(), Path(value["workspace"]).resolve()
    core.require(workspace.is_relative_to(project) and workspace != project,
                 "Guard workspace must be owned by the registered project")
    return value, project, workspace


def _script_command(scope_path, action="hook", nonce=None):
    script = Path(__file__).resolve().parents[2] / "scripts" / "workbuddy_board_guard.py"
    command = [sys.executable, str(script), action, "--scope", str(Path(scope_path).resolve())]
    if nonce is not None:
        command.extend(["--nonce", nonce])
    return shlex.join(command)


def _hook_settings(scope_path):
    command = _script_command(scope_path)
    return {"hooks": {name: [{**({"matcher": "^(ImageGen|DeferExecuteTool|Bash)$"} if name != "Stop" else {}),
                             "hooks": [{"type": "command", "command": command, "timeout": 15}]}]
                      for name in ("PreToolUse", "PostToolUse", "PostToolUseFailure", "Stop")}}


def _settings_snapshot(path):
    """Read only this explicitly selected file; retain its content in memory only."""
    try:
        with path.open("rb") as stream:
            before = os.fstat(stream.fileno())
            core.require(stat.S_ISREG(before.st_mode), "Selected settings must be a regular file")
            raw = stream.read()
            after = os.fstat(stream.fileno())
        current = path.stat()
    except FileNotFoundError:
        return {"exists": False, "sha256": None, "identity": None, "mode": 0o600, "raw": b""}
    identity = lambda info: (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_mode)
    core.require(identity(before) == identity(after) == identity(current),
                 "Settings changed concurrently while reading; retry after reviewing the selected file")
    return {"exists": True, "sha256": hashlib.sha256(raw).hexdigest(), "identity": identity(current),
            "mode": stat.S_IMODE(current.st_mode), "raw": raw}


def _assert_settings_unchanged(path, snapshot):
    core.require(_settings_snapshot(path) == snapshot,
                 "Settings changed concurrently; refusing to overwrite another writer's changes")


def _atomic_settings_write(path, raw, snapshot):
    """Best-effort CAS plus atomic replace; never claim a lock on other writers."""
    core.ensure_directory(path.parent)
    descriptor, name = tempfile.mkstemp(prefix="." + path.name + ".board-guard-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            os.fchmod(stream.fileno(), snapshot["mode"])
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        _assert_settings_unchanged(path, snapshot)
        if snapshot["exists"]:
            os.replace(temporary, path)
        else:
            # An exclusive link also closes the missing-file creation race.
            try:
                os.link(temporary, path)
            except FileExistsError as error:
                raise core.WorkflowError("Settings were created concurrently; refusing to overwrite them") from error
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def _change_installation(scope_path, settings_path, operation):
    scope, _, workspace = _registration(scope_path)
    if operation == "install":
        core.require(scope.get("active") is True and scope.get("stage") == "S7",
                     "Install requires an explicitly activated S7 registration")
    selected = Path(settings_path).expanduser().resolve()
    core.require(selected != Path(scope_path).resolve() and not selected.is_relative_to(workspace),
                 "Host settings must be separate from scope and production workspace")
    snapshot = _settings_snapshot(selected)
    settings = json.loads(snapshot["raw"].decode("utf-8")) if snapshot["exists"] else {}
    core.require(isinstance(settings, dict), "Selected settings must contain a JSON object")
    original = copy.deepcopy(settings)
    hooks = settings.setdefault("hooks", {}) if operation == "install" else settings.get("hooks", {})
    core.require(isinstance(hooks, dict), "Existing settings.hooks must be an object; preserve and review it")
    changes = {}
    for name, desired in _hook_settings(scope_path)["hooks"].items():
        entry = desired[0]
        canonical = entry["hooks"][0]
        expected_options = {key: value for key, value in entry.items() if key != "hooks"}
        existing = hooks.get(name, [])
        core.require(isinstance(existing, list), "Existing hook event must be an array: " + name)
        matched = False
        remaining = []
        for item in existing:
            core.require(isinstance(item, dict) and isinstance(item.get("hooks"), list),
                         "Existing hook entry is malformed: " + name)
            owns_options = {key: value for key, value in item.items() if key != "hooks"} == expected_options
            kept = []
            for hook in item["hooks"]:
                same_command = isinstance(hook, dict) and hook.get("type") == "command" and hook.get("command") == canonical["command"]
                if same_command and operation == "install":
                    core.require(owns_options and hook == canonical,
                                 "The same scope command already has different matcher/options; review it before installing: " + name)
                    matched = True
                if operation == "uninstall" and owns_options and hook == canonical:
                    changes.setdefault(name, []).append({**expected_options, "hooks": [canonical]})
                    continue
                kept.append(hook)
            if kept == item["hooks"]:
                remaining.append(item)
            elif kept:
                remaining.append({**item, "hooks": kept})
        if operation == "install":
            if not matched:
                hooks[name] = [*existing, entry]
                changes[name] = [entry]
        elif remaining != existing:
            if remaining:
                hooks[name] = remaining
            else:
                hooks.pop(name, None)
    changed = settings != original
    raw = (json.dumps(settings, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8") if changed else snapshot["raw"]
    receipt_dir = Path(scope_path).resolve().parent / (Path(scope_path).name + ".events") / "settings-receipts"
    core.ensure_directory(receipt_dir)
    if changed:
        _atomic_settings_write(selected, raw, snapshot)
    else:
        _assert_settings_unchanged(selected, snapshot)
    receipt = {"schema": 1, "kind": "workbuddy-board-hook-settings-change", "operation": operation,
               "scope": str(Path(scope_path).resolve()), "scope_sha256": _hash(scope_path),
               "settings_path": str(selected), "before_sha256": snapshot["sha256"],
               "after_sha256": hashlib.sha256(raw).hexdigest() if changed or snapshot["exists"] else None,
               "changed": changed, "entries_added" if operation == "install" else "entries_removed": changes,
               "host_hook_loading_verified": False,
               "boundary": "Explicit scoped configuration change only. No settings contents/credentials saved; no app restart or trust flag change."}
    receipt_path = receipt_dir / (uuid.uuid4().hex + ".json")
    _write_once(receipt_path, receipt)
    command = _script_command(scope_path)
    remaining_commands = sum(1 for name in _hook_settings(scope_path)["hooks"]
                             for entry in hooks.get(name, []) for hook in entry["hooks"]
                             if isinstance(hook, dict) and hook.get("type") == "command" and hook.get("command") == command)
    next_action = "User settings may be cached for 60 seconds. Verify actual WorkBuddy Bash Pre/Post/Stop events before ImageGen; configuration installation is not host enforcement proof."
    if operation == "uninstall" and remaining_commands:
        next_action = "Modified entries containing this exact scope command remain. Review them explicitly; only unchanged standard hooks were removed."
    return {"ok": True, "installed": bool(remaining_commands), "changed": changed,
            "settings": str(selected), "receipt": str(receipt_path), "host_hook_loading_verified": False,
            "remaining_scope_commands": remaining_commands, "settings_cache_seconds": 60,
            "next_action": next_action}


def install(scope_path, settings_path):
    return _change_installation(scope_path, settings_path, "install")


def uninstall(scope_path, settings_path):
    return _change_installation(scope_path, settings_path, "uninstall")


def _probe_command(scope_path, scope):
    nonce = scope.get("probe_nonce")
    core.require(isinstance(nonce, str) and len(nonce) == 32 and all(char in "0123456789abcdef" for char in nonce),
                 "This registration has no probe nonce; activate a fresh scoped registration")
    return _script_command(scope_path, "probe", nonce)


def _probe_dir(scope_path):
    path = Path(scope_path).resolve()
    return path.parent / (path.name + ".events") / "probe"


def _probe_hook(scope_path, event):
    """Only an exact harmless probe command crosses the ordinary Bash fast path."""
    if event.get("tool_name") != "Bash" or not isinstance(event.get("tool_input"), dict):
        return None
    try:
        scope, project, _ = _registration(scope_path)
        command = _probe_command(scope_path, scope)
    except (ValueError, OSError, KeyError, TypeError):
        return None
    if event["tool_input"].get("command") != command:
        return None
    if scope.get("active") is not True or scope.get("stage") != "S7":
        return None
    core.require(event.get("cwd") and Path(event["cwd"]).resolve().is_relative_to(project),
                 "The exact carrier probe must run in the registered native project")
    source = _source_ref(event)
    core.require(isinstance(event.get("session_id"), str) and event["session_id"].strip(),
                 "Carrier probe requires an original host session_id")
    pre = event.get("hook_event_name") == "PreToolUse"
    value = {"schema": 1, "kind": "workbuddy-board-carrier-probe-event", "event": event,
             "probe_nonce": scope["probe_nonce"], "probe_revision": scope.get("probe_revision", 1),
             "decision": "block_with_exit_2" if pre else "original_post_event_observed",
             "boundary": "Scoped native Bash hook evidence only; no provider or ImageGen invocation."}
    path = _probe_dir(scope_path) / (("pre-" if pre else "post-") + _safe_key(source) + ".json")
    if path.exists():
        core.require(_json(path) == value, "Carrier probe event changed for the same original call ID")
    else:
        _write_once(path, value)
    return {"ok": not pre, "action": "carrier_probe_blocked" if pre else "carrier_probe_post_retained",
            "source_ref": source, "host_session_id": event["session_id"], "evidence": str(path),
            "reason": "Intentional no-provider carrier probe: this exact Bash command must be blocked by PreToolUse."}, 2 if pre else 0


def probe(scope_path, nonce):
    scope, _, _ = _registration(scope_path)
    core.require(nonce == scope.get("probe_nonce"), "Probe nonce does not match this registration")
    path = _probe_dir(scope_path) / ("unexpected-execution-" + uuid.uuid4().hex + ".json")
    _write_once(path, {"schema": 1, "kind": "workbuddy-board-carrier-probe-unexpected-execution",
                       "scope_sha256": _hash(scope_path), "probe_nonce": nonce,
                       "probe_revision": scope.get("probe_revision", 1),
                       "probe_command": _probe_command(scope_path, scope),
                       "boundary": "The harmless command body executed: PreToolUse did not block it. This is a failed carrier probe; no provider was accessed."})
    return {"ok": False, "probe_passed": False, "unexpected_execution": True, "evidence": str(path)}, 2


def probe_status(scope_path):
    scope, _, _ = _registration(scope_path)
    directory = _probe_dir(scope_path)
    command = _probe_command(scope_path, scope)
    revision = scope.get("probe_revision", 1)
    pre, post, unexpected, historical_failed, historical_pre, historical_post = [], [], [], [], [], []
    archived_legacy = set()
    for path in (directory / "renewals").glob("*.json"):
        value = _json(path)
        # A receipt written before a failed scope update cannot retire an
        # active failure. Only completed revision transitions apply.
        target_revision = value.get("to_revision")
        if value.get("kind") == "workbuddy-board-carrier-probe-renewal" and type(target_revision) is int and target_revision <= revision:
            for ref in value.get("legacy_failed_attempts", []):
                archived_legacy.add((ref["path"], ref["sha256"]))
    for path in sorted(directory.glob("*.json")) if directory.exists() else []:
        value = _json(path)
        event = value.get("event", {})
        ref = {"path": str(path), "sha256": _hash(path)}
        if value.get("kind") == "workbuddy-board-carrier-probe-event":
            ref.update(host_session_id=event.get("session_id"), source_ref=_source_ref(event))
            current = event.get("tool_input", {}).get("command") == command
            if event.get("hook_event_name") == "PreToolUse":
                (pre if current else historical_pre).append(ref)
            else:
                (post if current else historical_post).append(ref)
        elif value.get("kind") == "workbuddy-board-carrier-probe-unexpected-execution":
            if "probe_nonce" in value:
                current = value["probe_nonce"] == scope["probe_nonce"]
            elif "probe_command" in value:
                current = value["probe_command"] == command
            else:
                # Pre-renewal builds did not retain a nonce in command-body
                # failure records. Keep them active until explicit renewal
                # archives that exact path/hash; never silently ignore them.
                current = (ref["path"], ref["sha256"]) not in archived_legacy
            (unexpected if current else historical_failed).append(ref)
    sessions = sorted({item["host_session_id"] for item in pre})
    return {"ok": True, "command": command, "probe_revision": revision, "pre_hook_observed": bool(pre),
            "probe_passed": bool(pre) and not unexpected, "unexpected_execution": bool(unexpected),
            "host_session_id": sessions[0] if len(sessions) == 1 else None, "observed_host_session_ids": sessions,
            "pre_events": pre, "post_events": post, "unexpected_execution_evidence": unexpected,
            "historical_failed_attempts": historical_failed, "historical_failed_attempt_count": len(historical_failed),
            "historical_pre_events": historical_pre, "historical_post_events": historical_post,
            "imagegen_interception_verified": False,
            "boundary": "Check the actual native tool call/blocked result against these original IDs. This proves only the exact Bash Pre hook; Post, Stop and ImageGen require their own real events."}


def renew_probe(scope_path):
    scope, _, _ = _registration(scope_path)
    core.require(scope.get("active") is True and scope.get("stage") == "S7", "Renewal requires an active S7 registration")
    old_command = _probe_command(scope_path, scope)
    revision = scope.get("probe_revision", 1)
    core.require(type(revision) is int and revision >= 1, "Invalid probe revision")
    nonce = secrets.token_hex(16)
    while nonce == scope["probe_nonce"]:
        nonce = secrets.token_hex(16)
    legacy = []
    for path in _probe_dir(scope_path).glob("*.json"):
        value = _json(path)
        if value.get("kind") == "workbuddy-board-carrier-probe-unexpected-execution" and "probe_nonce" not in value and "probe_command" not in value:
            legacy.append({"path": str(path), "sha256": _hash(path)})
    receipt = {"schema": 1, "kind": "workbuddy-board-carrier-probe-renewal",
               "from_revision": revision, "to_revision": revision + 1, "from_nonce": scope["probe_nonce"],
               "to_nonce": nonce, "previous_command": old_command, "legacy_failed_attempts": legacy,
               "boundary": "New no-provider probe identity only; all earlier failures and native call evidence remain intact."}
    destination = _probe_dir(scope_path) / "renewals" / (uuid.uuid4().hex + ".json")
    _write_once(destination, receipt)
    scope["probe_nonce"], scope["probe_revision"] = nonce, revision + 1
    core.write(Path(scope_path).resolve(), scope)
    return {"ok": True, "probe_revision": revision + 1, "command": _probe_command(scope_path, scope),
            "receipt": str(destination), "host_session_and_production_unchanged": True,
            "next_action": "Allow the settings cache to expire or reload WorkBuddy, then run only this new exact native Bash probe. Historical failures do not satisfy or invalidate the new identity."}


def _image_tool(event):
    name, value = event.get("tool_name"), event.get("tool_input")
    return name == "ImageGen" or (name == "DeferExecuteTool" and isinstance(value, dict)
                                  and value.get("toolName") == "ImageGen")


def _source_ref(event):
    source = event.get("tool_use_id", event.get("call_id"))
    core.require(isinstance(source, str) and source.strip(),
                 "This host hook did not supply an original tool_use_id/call_id; invocation remains blocked")
    if "tool_use_id" in event and "call_id" in event:
        core.require(event["tool_use_id"] == event["call_id"], "Host tool_use_id and call_id disagree")
    return source


def _same_arguments(left, right):
    # JSON type differences are significant too (for example true versus 1).
    encode = lambda value: json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return encode(left) == encode(right)


def _same_invocation(original, event):
    core.require(_source_ref(original) == _source_ref(event)
                 and original.get("session_id") == event.get("session_id")
                 and original.get("generation_id") == event.get("generation_id")
                 and original.get("cwd") and event.get("cwd")
                 and Path(original["cwd"]).resolve() == Path(event["cwd"]).resolve(),
                 "Hook project/session/generation/call ID differs from the original guarded invocation")


def _scope(scope_path, event):
    scope = _json(scope_path)
    core.require(isinstance(scope, dict) and scope.get("kind") == "workbuddy-board-guard-scope"
                 and scope.get("schema") == 1, "Unsupported board guard scope")
    if scope.get("active") is not True or scope.get("stage") != "S7":
        return None
    project = Path(scope["project"]).resolve()
    if event.get("cwd"):
        if not Path(event["cwd"]).resolve().is_relative_to(project):
            return None
        if not isinstance(scope.get("host_session_id"), str) or not scope["host_session_id"].strip():
            if event.get("hook_event_name") == "Stop":
                return None
            raise core.WorkflowError("guard_not_bound: this S7 registration is unbound-probe-only. "
                                     "Run the exact native Bash carrier probe, inspect its original session_id, "
                                     "then bind-session before any ImageGen call.")
        if event.get("session_id") != scope.get("host_session_id"):
            if event.get("hook_event_name") == "Stop":
                return None
            if event.get("hook_event_name") == "PreToolUse":
                raise core.WorkflowError("guard_not_bound: this project has an active S7 registration for another host session. "
                                         "Use explicit bind-session to resume the same task, preserving original claims; "
                                         "or deactivate that S7 registration before starting unrelated concept work here.")
            # A delayed original result from the previous session may still be
            # retained, but _post must match its exact pre-event/source_ref.
    elif event.get("hook_event_name") != "Stop":
        if event.get("session_id") != scope.get("host_session_id"):
            return None
        raise core.WorkflowError("Active S7 tool hook lacks its actual cwd; cannot verify project scope")
    elif not scope.get("host_session_id") or event.get("session_id") != scope.get("host_session_id"):
        return None
    workspace = Path(scope["workspace"]).resolve()
    core.require(workspace.is_relative_to(project) and workspace != project,
                 "Guard workspace must be owned by the registered project")
    return scope, project, workspace


def _pending_match(scope, project, workspace, event):
    from . import board_production
    state = _json(workspace / "production.json")
    core.require(state.get("kind") == "reference-board-production-state", "No prepared board production state")
    pages = state.get("pages")
    core.require(isinstance(pages, dict) and pages, "Prepare the S7 scope before calling ImageGen")
    matches, failures = [], []
    for page_id in pages:
        try:
            info = board_production.inspect_claim(workspace, page_id)
            core.require(info["project"] == str(project) and info["host"] == "workbuddy",
                         "Production dispatch belongs to another project or host")
            core.require(info.get("host_session_id") == scope["host_session_id"],
                         "Production must bind this exact original WorkBuddy session")
            core.require(info.get("active_host_session_id") == scope["host_session_id"],
                         "Production operational session differs from this guard registration")
            if info["tool"] == event["tool_name"] and _same_arguments(info["tool_arguments"], event.get("tool_input")):
                matches.append(info)
        except (ValueError, OSError, KeyError, TypeError) as error:
            failures.append(str(error))
    core.require(len(matches) == 1, "ImageGen must exactly match one frozen dispatch, including prompt and all images. "
                 + (failures[0] if failures else "Prepare/map/claim the intended page; do not handwrite a replacement call."))
    info = matches[0]
    core.require(info["claim"]["status"] == "pending" and info.get("claim_file"),
                 "This page needs its original unrecorded one-time production claim; do not repeat a recorded call")
    return info


def _claim_path(workspace, info):
    return workspace / "host-guard" / "claims" / (_safe_key(info["claim"]["id"]) + ".json")


def _execution_claim_path(workspace, claim_id):
    return workspace / "host-guard" / "execution-claims" / (_safe_key(claim_id) + ".json")


def _result_path(workspace, source, *, execution=False):
    return workspace / "host-guard" / ("execution-results" if execution else "results") / (_safe_key(source) + ".json")


def _original_claim(workspace, source, *, required=True):
    found = []
    for path in (workspace / "host-guard" / "claims").glob("*.json"):
        value = _json(path)
        if value.get("source_ref") == source:
            found.append((path, value))
    core.require(len(found) == 1 if required else len(found) <= 1,
                 "No unique original guarded invocation matches this event; reconcile host evidence")
    return found[0] if found else None


def _deferred_invocation(scope, project, workspace, event, original, *, execution_pre=False):
    """Verify the frozen wrapper and its one exact, same-call resolved target."""
    from . import board_production
    path, claim = original
    outer = claim["event"]
    _same_invocation(outer, event)
    envelope = outer.get("tool_input")
    core.require(claim.get("kind") == "workbuddy-board-hook-claim"
                 and outer.get("hook_event_name") == "PreToolUse"
                 and outer.get("tool_name") == "DeferExecuteTool"
                 and isinstance(envelope, dict) and envelope.get("toolName") == "ImageGen"
                 and isinstance(envelope.get("params"), dict) and event.get("tool_name") == "ImageGen"
                 and _same_arguments(envelope["params"], event.get("tool_input")),
                 "Resolved ImageGen must equal the complete frozen deferred params for the same original call")
    info = board_production.inspect_claim(workspace, claim["page_id"])
    core.require(info["project"] == str(project) and info["host"] == "workbuddy"
                 and info["tool"] == "DeferExecuteTool" and _same_arguments(info["tool_arguments"], envelope)
                 and info.get("host_session_id") == outer.get("session_id")
                 and info.get("claim_file") and claim.get("claim_id") == info["claim"]["id"]
                 and claim.get("claim_sha256") == info["claim_file"]["sha256"]
                 and claim.get("dispatch_sha256") == info["dispatch"]["sha256"]
                 and path == _claim_path(workspace, info),
                 "Deferred wrapper no longer matches its original project/session/claim/frozen dispatch")
    if execution_pre:
        core.require(info["claim"]["status"] == "pending"
                     and info.get("active_host_session_id") == scope["host_session_id"]
                     and not _result_path(workspace, claim["source_ref"]).exists(),
                     "The original deferred call has ended or changed session; reconcile it, never execute it again")
    return info


def _execution_pre(scope, project, workspace, event, original):
    path, outer = original
    info = _deferred_invocation(scope, project, workspace, event, original, execution_pre=True)
    value = {"schema": 1, "kind": "workbuddy-board-hook-execution-claim", "page_id": info["page_id"],
             "claim_id": info["claim"]["id"], "claim_sha256": info["claim_file"]["sha256"],
             "dispatch_sha256": info["dispatch"]["sha256"], "source_ref": _source_ref(event),
             "outer_pre_sha256": _hash(path), "event": event,
             "boundary": "One exact resolved ImageGen execution authorized for the reserved wrapper; outcome remains pending."}
    try:
        _write_once(_execution_claim_path(workspace, outer["claim_id"]), value)
    except FileExistsError as error:
        raise core.WorkflowError("This deferred claim already authorized its resolved ImageGen. Reconcile the original call; never replay it.") from error
    return {"ok": True, "action": "allow_exact_deferred_execution", "page_id": info["page_id"],
            "source_ref": value["source_ref"], "execution_authorized": True, "production_claim_still_pending": True}


def _pre(scope_path, scope, project, workspace, event):
    from . import board_workbuddy
    board_workbuddy.check_dispatch_limit(workspace, scope)
    source = _source_ref(event)
    original = _original_claim(workspace, source, required=False)
    if original:
        if event.get("tool_name") == "ImageGen" and original[1]["event"].get("tool_name") == "DeferExecuteTool":
            return _execution_pre(scope, project, workspace, event, original)
        raise core.WorkflowError("This host call already reached PreToolUse. Reconcile its original invocation; never replay it.")
    info = _pending_match(scope, project, workspace, event)
    value = {"schema": 1, "kind": "workbuddy-board-hook-claim", "page_id": info["page_id"],
             "claim_id": info["claim"]["id"], "claim_sha256": info["claim_file"]["sha256"],
             "dispatch_sha256": info["dispatch"]["sha256"], "scope_sha256": _hash(scope_path),
             "source_ref": source, "event": event,
             "boundary": ("Deferred wrapper reserved only; the same-call resolved ImageGen needs its own one-time execution authorization."
                          if event["tool_name"] == "DeferExecuteTool" else
                          "Direct ImageGen PreToolUse observed; outcome unknown until the original call is reconciled.")}
    try:
        _write_once(_claim_path(workspace, info), value)
    except FileExistsError as error:
        raise core.WorkflowError("This production claim already reached PreToolUse. Reconcile its original call; never resend.") from error
    return {"ok": True, "action": "allow_exact_claimed_call", "page_id": info["page_id"],
            "source_ref": source, "production_claim_still_pending": True,
            "execution_authorized": event["tool_name"] == "ImageGen"}


def _post(scope, project, workspace, event):
    # Do not require pending status here: the same original result may already
    # have been manually recorded before a delayed PostToolUse arrives.
    source = _source_ref(event)
    path, claim = _original_claim(workspace, source)
    original = claim["event"]
    _same_invocation(original, event)
    if original.get("tool_name") == "DeferExecuteTool" and event.get("tool_name") == "ImageGen":
        info = _deferred_invocation(scope, project, workspace, event, (path, claim))
        execution_path = _execution_claim_path(workspace, claim["claim_id"])
        execution = _json(execution_path)
        core.require(execution.get("kind") == "workbuddy-board-hook-execution-claim"
                     and execution.get("outer_pre_sha256") == _hash(path)
                     and execution.get("source_ref") == source and execution.get("page_id") == info["page_id"]
                     and execution.get("claim_id") == info["claim"]["id"]
                     and execution.get("claim_sha256") == info["claim_file"]["sha256"]
                     and execution.get("dispatch_sha256") == info["dispatch"]["sha256"],
                     "Resolved result lacks its exact original execution authorization")
        _same_invocation(execution["event"], event)
        core.require(execution["event"].get("tool_name") == event.get("tool_name")
                     and execution["event"].get("hook_event_name") == "PreToolUse"
                     and _same_arguments(execution["event"].get("tool_input"), event.get("tool_input")),
                     "Resolved result arguments differ from its original execution authorization")
        record = {"schema": 1, "kind": "workbuddy-board-hook-execution-result", "source_ref": source,
                  "page_id": info["page_id"], "claim_id": info["claim"]["id"],
                  "claim_sha256": info["claim_file"]["sha256"], "dispatch_sha256": info["dispatch"]["sha256"],
                  "outer_pre_sha256": _hash(path), "execution_pre_sha256": _hash(execution_path), "event": event,
                  "outcome": "host_response_observed" if "tool_response" in event else "unknown_or_failure_observed",
                  "boundary": "Original resolved-tool result only; outer wrapper evidence is retained separately."}
        destination = _result_path(workspace, source, execution=True)
        return _retain_post(destination, record, source)
    core.require(original.get("tool_name") == event.get("tool_name")
                 and _same_arguments(original.get("tool_input"), event.get("tool_input")),
                 "PostToolUse arguments/session differ from the original guarded call")
    record = {"schema": 1, "kind": "workbuddy-board-hook-result", "source_ref": source,
              "page_id": claim["page_id"], "pre_event_sha256": _hash(path), "event": event,
              "outcome": "host_response_observed" if "tool_response" in event else "unknown_or_failure_observed",
              "boundary": "Raw host evidence only. Run production record for the original call; this sidecar supplies no visual acceptance."}
    destination = _result_path(workspace, source)
    return _retain_post(destination, record, source)


def _retain_post(destination, record, source):
    if destination.exists():
        original = _json(destination)
        if not _same_arguments(original, record):
            inner = destination.parent.name == "execution-results"
            conflict = {"schema": 1, "kind": "workbuddy-board-hook-result-conflict",
                        "source_ref": source, "page_id": original["page_id"], "layer": "inner" if inner else "outer",
                        "original_result": {"path": str(destination.resolve()), "sha256": _hash(destination)},
                        "original_pre_sha256": original.get("execution_pre_sha256" if inner else "pre_event_sha256"),
                        "outer_pre_sha256": original.get("outer_pre_sha256", original.get("pre_event_sha256")),
                        "incoming_record": record, "reason": "same_layer_post_changed"}
            identity = json.dumps(conflict, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
            conflict_path = destination.parent.parent / "conflicts" / (_safe_key(identity) + ".json")
            try:
                _write_once(conflict_path, conflict)
            except FileExistsError:
                core.require(_same_arguments(_json(conflict_path), conflict), "Existing result-conflict receipt changed")
            raise core.WorkflowError("Original host result changed; both outcomes were retained for reconciliation: " + str(conflict_path))
    else:
        _write_once(destination, record)
    return {"ok": True, "action": "original_result_retained", "source_ref": source,
            "evidence": str(destination), "production_state_unchanged": True}


def _stop(scope_path, scope, project, workspace, event):
    from . import board_production
    if event.get("stop_hook_active") is True:
        return {"ok": True, "action": "allow_after_one_continuation",
                "boundary": "Do not trap the host in repeated Stop continuations; pending calls must be reconciled."}, 0
    def continue_once(reason):
        generation = event.get("generation_id")
        # Older carriers may omit generation_id. Then permit only one Stop
        # continuation for this registration, never invent a host generation.
        identity = generation if isinstance(generation, str) and generation else json.dumps(scope, sort_keys=True)
        # Registration precedes preparation. Never dirty the production
        # workspace merely by observing Stop: prepare requires it to be empty.
        registration = Path(scope_path).resolve()
        marker = registration.parent / (registration.name + ".events") / "stop" / (_safe_key(identity) + ".json")
        try:
            _write_once(marker, {"event": event, "reason": "one bounded local Stop continuation"})
        except FileExistsError:
            return {"ok": True, "action": "allow_after_one_continuation"}, 0
        return {"ok": False, "reason": reason}, 2

    try:
        state = board_production.status(workspace)
    except (ValueError, OSError, KeyError, TypeError):
        return continue_once("Registered S7 production is not prepared. Prepare the agreed asset-board scope, "
                             "then map/claim the exact page before ImageGen. Deactivate the scope only when leaving this S7 task.")
    pages = state.get("pages", [])
    if any(page.get("claim_status") == "pending" for page in pages):
        return {"ok": True, "action": "allow_pending_reconciliation_handoff",
                "reason": "An original image call is pending/unknown. Report its recovery source and reconcile it; never resend."}, 0
    if scope.get("board_entry"):
        from . import board_registry
        try:
            workflow = board_registry.next_jobs(workspace)
            state["complete"] = workflow["complete"]
        except (ValueError, OSError, KeyError, TypeError):
            return continue_once("The staged workflow evidence needs reconciliation. Preserve all original calls; "
                                 "inspect boards next before any further generation.")
    if state.get("complete") is True:
        return {"ok": True, "action": "allow_completed_scope", "next_action": "deactivate the S7 guard before changing stage"}, 0
    return continue_once("Active S7 has incomplete board pages. Continue the next ready page or finish its "
                         "actual result recording, observed crops and visual review; preserve accepted siblings. "
                         "If external input is required, report the concrete blocker. Do not replace this work with a plan-only answer.")


def handle(scope_path, event):
    core.require(isinstance(event, dict), "Hook input must be a JSON object")
    kind = event.get("hook_event_name")
    if kind not in {"PreToolUse", "PostToolUse", "PostToolUseFailure", "Stop"}:
        return {"ok": True, "action": "outside_event_scope"}, 0
    if kind != "Stop" and event.get("tool_name") == "Bash":
        observed = _probe_hook(scope_path, event)
        return observed if observed is not None else ({"ok": True, "action": "outside_tool_scope"}, 0)
    if kind != "Stop" and not _image_tool(event):
        return {"ok": True, "action": "outside_tool_scope"}, 0
    active = _scope(scope_path, event)
    if active is None:
        return {"ok": True, "action": "outside_registered_s7_scope"}, 0
    scope, project, workspace = active
    if kind == "Stop":
        return _stop(scope_path, scope, project, workspace, event)
    if kind == "PreToolUse":
        return _pre(scope_path, scope, project, workspace, event), 0
    return _post(scope, project, workspace, event), 0


def activate(args):
    project, workspace, output = (Path(value).resolve() for value in (args.project, args.workspace, args.scope))
    core.require(project.is_dir() and workspace.is_relative_to(project) and workspace != project,
                 "Select the actual project and a task-owned production workspace inside it")
    core.require(not output.is_relative_to(workspace)
                 and not Path(args.hooks_output).resolve().is_relative_to(workspace),
                 "Keep guard registration/proposed settings outside the initially empty production workspace")
    discover = getattr(args, "discover_session", False)
    core.require(discover or isinstance(args.session_id, str) and args.session_id.strip(),
                 "Provide an actual host session ID or explicitly discover the native session")
    value = {"schema": 1, "kind": "workbuddy-board-guard-scope", "active": True, "stage": "S7",
             "project": str(project), "workspace": str(workspace), "host_session_id": None if discover else args.session_id,
             "session_binding": "unbound-probe-only" if discover else "bound",
             "probe_nonce": secrets.token_hex(16), "probe_revision": 1}
    _write_once(output, value)
    _write_once(args.hooks_output, _hook_settings(output))
    return {"ok": True, "scope": str(output), "hooks_settings": str(Path(args.hooks_output).resolve()),
            "installed": False, "host_hook_loading_verified": False,
            "probe_command": _probe_command(output, value),
            "next_action": "Review scoped settings and verify the actual WorkBuddy carrier before enabling; no host settings were edited."}


def bind_session(scope_path, session_id):
    from . import board_production
    value = _json(scope_path)
    core.require(value.get("kind") == "workbuddy-board-guard-scope" and value.get("active") is True
                 and value.get("stage") == "S7", "Session handoff requires an active S7 registration")
    core.require(isinstance(session_id, str) and session_id.strip(), "Bind the actual new WorkBuddy session ID")
    project, workspace = Path(value["project"]).resolve(), Path(value["workspace"]).resolve()
    core.require(workspace.is_relative_to(project) and workspace != project, "Invalid task-owned production workspace")
    if (workspace / "production.json").is_file():
        board_production.bind_session(workspace, session_id)
    else:
        core.require(not (workspace / "host-guard" / "claims").exists(),
                     "Production state is missing while old guarded claims exist; recover it before rebinding")
    previous = value["host_session_id"]
    if previous != session_id:
        value.setdefault("handoffs", []).append({"from_session_id": previous, "to_session_id": session_id})
        value["host_session_id"] = session_id
    if previous != session_id or value.get("session_binding") != "bound":
        value["session_binding"] = "bound"
        core.write(Path(scope_path).resolve(), value)
    return {"ok": True, "active_host_session_id": session_id, "previous_host_session_id": previous,
            "original_claims_and_dispatches_preserved": True,
            "boundary": "Operational handoff only. Pending original calls may be reconciled, never resent."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    item = sub.add_parser("activate", help="Write scoped registration and proposed hooks; never install host settings")
    for option in ("project", "workspace", "scope", "hooks-output"):
        item.add_argument("--" + option, required=True)
    session = item.add_mutually_exclusive_group(required=True)
    session.add_argument("--session-id")
    session.add_argument("--discover-session", action="store_true")
    for name in ("deactivate", "status", "hook", "probe-status", "renew-probe"):
        sub.add_parser(name).add_argument("--scope", required=True)
    for name in ("install", "uninstall"):
        item = sub.add_parser(name)
        item.add_argument("--scope", required=True)
        item.add_argument("--settings", required=True)
    item = sub.add_parser("probe")
    item.add_argument("--scope", required=True)
    item.add_argument("--nonce", required=True)
    item = sub.add_parser("bind-session")
    item.add_argument("--scope", required=True)
    item.add_argument("--session-id", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "activate":
            result, code = activate(args), 0
        elif args.command == "deactivate":
            value = _json(args.scope)
            core.require(value.get("kind") == "workbuddy-board-guard-scope", "Not a board guard registration")
            value["active"] = False
            core.write(Path(args.scope).resolve(), value)
            result, code = {"ok": True, "active": False, "production_and_unknown_calls_preserved": True}, 0
        elif args.command == "status":
            result, code = {"ok": True, "scope": _json(args.scope), "host_settings_modified": False}, 0
        elif args.command == "bind-session":
            result, code = bind_session(args.scope, args.session_id), 0
        elif args.command == "install":
            result, code = install(args.scope, args.settings), 0
        elif args.command == "uninstall":
            result, code = uninstall(args.scope, args.settings), 0
        elif args.command == "probe":
            result, code = probe(args.scope, args.nonce)
        elif args.command == "probe-status":
            result, code = probe_status(args.scope), 0
        elif args.command == "renew-probe":
            result, code = renew_probe(args.scope), 0
        else:
            result, code = handle(args.scope, json.load(sys.stdin))
    except (ValueError, OSError, KeyError, TypeError) as error:
        # Exit 2 is a deliberate blocking decision, not a thrown hook-runner
        # exception which some carriers treat as fail-open.
        result, code = {"ok": False, "reason": "S7 board guard: " + str(error),
                        "next_action": "Inspect the exact scoped state and reconcile original calls; do not resend an unknown invocation."}, 2
    print(json.dumps(result, ensure_ascii=True, allow_nan=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
