"""WorkBuddy's scoped board entry: prepare jobs, verify hooks and bind a session.

The host agent still invokes its native tool. This module never generates,
authorizes spending, retries a provider or clears an uncertain claim.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
from types import SimpleNamespace

from . import board_production as production, core, workbuddy_board_guard as guard


def _paths(workspace):
    workspace = Path(workspace).resolve()
    control = workspace.parent / (workspace.name + "-workbuddy")
    return workspace, control, control / "scope.json", control / "entry.json"


def _write_once(path, value):
    if path.exists():
        core.require(core.read(path) == value, "Existing board entry changed; retain this run and use an explicit new scope")
    else:
        core.write(path, value)


def _entry(workspace):
    workspace, control, scope, entry_path = _paths(workspace)
    entry = core.read(entry_path)
    core.require(entry.get("kind") == "workbuddy-board-entry" and entry.get("schema") == 1
                 and entry.get("workspace") == str(workspace), "Use the original WorkBuddy board entry")
    registered, project, actual = guard._registration(scope)
    core.require(actual == workspace and str(project) == entry["project"], "Board entry registration changed")
    return workspace, control, scope, entry


def _workflow(workspace):
    from . import board_registry
    root = Path(board_registry.workflow_root(workspace)).resolve()
    stages = [Path(path).resolve() for path in board_registry.workflow_workspaces(workspace)]
    core.require(root in stages and Path(workspace).resolve() in stages, "WorkBuddy workflow lineage is incomplete")
    return root, stages


def _used_calls(stages):
    used = 0
    for stage in stages:
        state = core.read(stage / "production.json")
        used += sum((stage / "pages" / page / "claim.json").is_file() for page in state["pages"])
    return used


def _budget(workspace, entry):
    root, stages = _workflow(workspace)
    core.require(entry.get("budget_workspace", str(workspace)) == str(root), "Budget root differs from the original workflow")
    if root != Path(workspace).resolve():
        owner_path = _paths(root)[3]
        core.require(entry.get("budget_entry") == {"path": str(owner_path), "sha256": core.file_hash(owner_path)},
                     "Original workflow spending ceiling changed")
        owner = core.read(owner_path)
        core.require(entry["limit"] == owner["limit"] and entry["project"] == owner["project"],
                     "A dependent stage cannot reset the original spending ceiling")
    return root, stages


def _switch_stage(workspace, stages):
    for other in stages:
        if other == workspace:
            continue
        _, _, scope, entry_path = _paths(other)
        if not scope.is_file() or not entry_path.is_file() or core.read(scope).get("active") is not True:
            continue
        state = core.read(other / "production.json")
        pending = [page for page in state["pages"]
                   if (other / "pages" / page / "claim.json").is_file()
                   and not core.read(other / "pages" / page / "state.json").get("invocation_recorded")]
        core.require(not pending, "Recover original pending calls before switching workflow stages: " + ", ".join(pending))
        cleanup(other)


def start(registry, project, workspace, *, settings=None, max_calls=0, max_credits=0,
          quote_upper_credits=0, limit_source_ref="No paid-call authorization supplied"):
    from . import board_registry
    project = Path(project).resolve()
    workspace, control, scope, entry_path = _paths(production._workspace(workspace, project))
    core.require(project.is_dir() and workspace != project, "Choose the actual WorkBuddy project and a task-owned workspace")
    selected = Path(settings or Path.home() / ".workbuddy/settings.json").expanduser().resolve()
    core.require(selected.is_file(), "WorkBuddy settings not found; select its actual settings file")
    core.require(type(max_calls) is int and max_calls >= 0
                 and all(type(v) in (int, float) and math.isfinite(v) and v >= 0 for v in (max_credits, quote_upper_credits)),
                 "Call and credit ceilings must be nonnegative")
    core.require(bool(limit_source_ref.strip()), "Record the source of the local spending ceiling")
    # Compile first. An invalid registry must not leave installed hooks behind.
    registry_path = production._path(str(registry), project)
    prepared = board_registry.start(core.read(registry_path), project, workspace, registry_path=registry_path)
    budget_root, stages = _workflow(workspace)
    limit = {"max_calls": max_calls, "max_credits": max_credits,
             "quote_upper_credits": quote_upper_credits, "source_ref": limit_source_ref}
    budget_ref = None
    if budget_root != workspace:
        _, _, _, owner = _entry(budget_root)
        core.require(str(selected) == owner["settings"], "Dependent stages use their original WorkBuddy settings")
        if max_calls or max_credits or quote_upper_credits:
            core.require(all(limit[key] == owner["limit"][key] for key in ("max_calls", "max_credits", "quote_upper_credits")),
                         "Dependent stages cannot reset the original call/credit ceiling")
        limit = owner["limit"]
        owner_path = _paths(budget_root)[3]
        budget_ref = {"path": str(owner_path), "sha256": core.file_hash(owner_path)}
    entry = {"schema": 1, "kind": "workbuddy-board-entry", "project": str(project),
             "workspace": str(workspace), "settings": str(selected),
             "limit": limit, "budget_workspace": str(budget_root),
             "boundary": "Local ceilings restrict existing authorization; they do not create it."}
    if budget_ref is not None:
        entry["budget_entry"] = budget_ref
    _write_once(entry_path, entry)
    with core.locked(_paths(budget_root)[1]):
        _switch_stage(workspace, stages)
        if not scope.exists():
            guard.activate(SimpleNamespace(project=str(project), workspace=str(workspace), scope=str(scope),
                                           hooks_output=str(control / "proposed-hooks.json"), discover_session=True,
                                           session_id=None))
        else:
            registered, actual_project, actual_workspace = guard._registration(scope)
            core.require(actual_project == project and actual_workspace == workspace,
                         "Existing S7 registration belongs to another scope; preserve it")
            if registered.get("active") is not True:
                registered["active"] = True
                core.write(scope, registered)
            # A new chat cannot reuse proof of an older chat's hook loading.
            guard.renew_probe(scope)
        registration = core.read(scope)
        entry_ref = {"path": str(entry_path), "sha256": core.file_hash(entry_path)}
        core.require(registration.get("board_entry", entry_ref) == entry_ref,
                     "Registered entry/ceiling changed; preserve this scope")
        registration["board_entry"] = entry_ref
        core.write(scope, registration)
        installation = guard.install(scope, selected)
        probe = guard.probe_status(scope)
    return {"ok": True, "workspace": str(workspace), "workflow_root": str(budget_root), "production": prepared,
            "hook_installation": installation, "carrier_probe": probe,
            "next_action": "Run carrier_probe.command unchanged as one native WorkBuddy Bash call. "
                           "Expected exit 2 means the Pre hook blocked the harmless probe; then bind the current live tool schema.",
            "boundary": "Settings may take time to reload. No native image call or provider request was made."}


def _ready(workspace):
    workspace, control, scope, entry = _entry(workspace)
    registered, _, _ = guard._registration(scope)
    core.require(registered.get("active") is True, "This S7 registration is inactive")
    entry_path = control / "entry.json"
    core.require(registered.get("board_entry") == {"path": str(entry_path), "sha256": core.file_hash(entry_path)},
                 "Registered entry or spending ceiling changed; do not create another claim")
    actual_settings = core.read(Path(entry["settings"]))
    for event, expected in guard._hook_settings(scope)["hooks"].items():
        core.require(all(item in actual_settings.get("hooks", {}).get(event, []) for item in expected),
                     "This entry's hooks are no longer installed; reinstall this scope before claiming")
    probe = guard.probe_status(scope)
    core.require(probe.get("probe_passed") and probe.get("host_session_id"),
                 "The current original native Bash probe has not passed; do not invoke ImageGen")
    core.require(registered.get("host_session_id") == probe["host_session_id"]
                 and registered.get("session_binding") == "bound", "Bind this probe's real host session first")
    return workspace, control, scope, entry, probe


def check_dispatch_limit(workspace, registration):
    """Guard-side ceiling check, including claims made via the lower-level CLI."""
    reference = registration.get("board_entry")
    if reference is None:
        return  # Historical manually registered scopes retain their contract.
    workspace, control, scope, entry_path = _paths(workspace)
    core.require(reference == {"path": str(entry_path), "sha256": core.file_hash(entry_path)},
                 "Registered WorkBuddy entry or spending ceiling changed")
    entry = core.read(entry_path)
    core.require(entry.get("workspace") == str(workspace)
                 and entry.get("project") == registration["project"], "WorkBuddy ceiling belongs to another scope")
    _, stages = _budget(workspace, entry)
    claimed = _used_calls(stages)
    limit = entry["limit"]
    quote = limit["quote_upper_credits"]
    core.require(quote > 0 and 0 < claimed <= limit["max_calls"]
                 and claimed * quote <= limit["max_credits"],
                 "Registered WorkBuddy call/credit ceiling blocks this native dispatch")


def bind(workspace, binding):
    workspace, control, scope, entry = _entry(workspace)
    probe = guard.probe_status(scope)
    core.require(probe.get("probe_passed") and probe.get("host_session_id"),
                 "No current original carrier probe; no native page can be mapped or claimed")
    path = production._path(str(binding), Path(entry["project"]))
    value = core.read(path)
    core.require(value.get("host") == "workbuddy" and value.get("tool") in {"ImageGen", "DeferExecuteTool"},
                 "Use this session's real WorkBuddy ImageGen schema")
    core.require(production._concrete(value.get("source_ref")), "Binding needs the actual current tool-schema source")
    guard.bind_session(scope, probe["host_session_id"])
    state = core.read(workspace / "production.json")
    failures = []
    for page_id in state["pages"]:
        page = core.read(workspace / "pages" / page_id / "state.json")
        if (workspace / "pages" / page_id / "claim.json").exists():
            continue
        try:
            production.map_native(workspace, page_id, path)
        except (ValueError, OSError) as error:
            failures.append({"page_id": page_id, "error": str(error)})
    return {**next_job(workspace), "ok": not failures, "mapping_errors": failures}


def next_job(workspace):
    from . import board_registry
    workspace, control, scope, entry = _entry(workspace)
    status = production.status(workspace)
    probe = guard.probe_status(scope)
    jobs = []
    for page in status["pages"]:
        if page["claim_status"] == "pending":
            action = "Recover this original pending call; do not claim or submit it again."
        elif page["invocation_recorded"]:
            action = "Inspect the original board, crop or repair only its slots, then review the current crops."
        elif page["mapped"]:
            action = "Claim this prepared page once within the existing spending scope, then invoke its exact call-ready arguments."
        else:
            action = "Pass the free native probe, then bind the current ImageGen schema."
        jobs.append({**page, "next_action": action})
    workflow = board_registry.next_jobs(workspace)
    root, stages = _budget(workspace, entry)
    return {"ok": True, "workspace": str(workspace), "workflow_root": str(root), "carrier_probe": probe,
            "limit": entry["limit"], "reserved_calls": _used_calls(stages), "jobs": jobs,
            "stage_complete": status["complete"], "complete": workflow["complete"], "workflow": workflow,
            "new_generation_calls": 0, "human_acceptance": False}


def claim(workspace, page_id):
    workspace, control, scope, entry, probe = _ready(workspace)
    # The call/credit ceiling spans all pages, so per-page claim exclusivity
    # alone is insufficient for simultaneous dispatches of different pages.
    root, _ = _budget(workspace, entry)
    with core.locked(_paths(root)[1]):
        return _claim_locked(workspace, page_id, entry)


def _claim_locked(workspace, page_id, entry):
    production.status(workspace)
    _, stages = _budget(workspace, entry)
    limit = entry["limit"]
    used = _used_calls(stages)
    quote = limit["quote_upper_credits"]
    core.require(quote > 0 and used < limit["max_calls"]
                 and (used + 1) * quote <= limit["max_credits"],
                 "Local call/credit ceiling reached or no current quoted upper cost supplied; no new page claim")
    info = production.claim(workspace, page_id)
    production.verify(workspace, page_id, info["tool_arguments"])
    folder = workspace / "pages" / page_id
    arguments = folder / "actual-arguments.json"
    ready = folder / "call-ready.json"
    _write_once(arguments, info["tool_arguments"])
    _write_once(ready, {"tool": info["tool"], "tool_arguments": info["tool_arguments"],
                        "page_id": page_id, "claim": info["claim_file"]})
    return dict(info, arguments_path=str(arguments), call_ready_path=str(ready),
                reserved_calls=used + 1, reserved_credit_upper=(used + 1) * quote,
                next_action="Invoke tool with tool_arguments exactly once. DeferExecuteTool receives the one existing envelope; do not wrap it again.")


def cleanup(workspace):
    workspace, control, scope, entry = _entry(workspace)
    result = guard.uninstall(scope, entry["settings"])
    registered = core.read(scope)
    registered["active"] = False
    core.write(scope, registered)
    return {"ok": True, "hook_cleanup": result, "active": False,
            "production_and_pending_calls_preserved": True}


def resume(workspace):
    """Enter an already compiled dependent stage without rebuilding its registry."""
    from . import board_registry
    compilation = board_registry._load_compilation(workspace)
    root, _ = _workflow(workspace)
    _, _, _, owner = _entry(root)
    project = Path(compilation["project"])
    registry_path = production._path(compilation["registry"]["path"], project)
    return start(registry_path, project, workspace, settings=owner["settings"],
                 **{key: owner["limit"][key] for key in ("max_calls", "max_credits", "quote_upper_credits")},
                 limit_source_ref=owner["limit"]["source_ref"])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("start", "resume", "bind", "next", "claim", "probe-status", "renew-probe", "cleanup"):
        item = sub.add_parser(name, allow_abbrev=False)
        item.add_argument("--workspace", required=True)
        if name == "start":
            item.add_argument("--file", required=True)
            item.add_argument("--project", required=True)
            item.add_argument("--settings")
            item.add_argument("--max-calls", type=int, default=0)
            item.add_argument("--max-credits", type=float, default=0)
            item.add_argument("--quote-upper-credits", type=float, default=0)
            item.add_argument("--limit-source-ref", default="No paid-call authorization supplied")
        if name == "bind":
            item.add_argument("--binding", required=True)
        if name == "claim":
            item.add_argument("--page", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "start":
            result = start(args.file, args.project, args.workspace, settings=args.settings,
                           max_calls=args.max_calls, max_credits=args.max_credits,
                           quote_upper_credits=args.quote_upper_credits, limit_source_ref=args.limit_source_ref)
        elif args.command == "bind":
            result = bind(args.workspace, args.binding)
        elif args.command == "resume":
            result = resume(args.workspace)
        elif args.command == "claim":
            result = claim(args.workspace, args.page)
        elif args.command == "next":
            result = next_job(args.workspace)
        elif args.command == "cleanup":
            result = cleanup(args.workspace)
        else:
            _, _, scope, _ = _entry(args.workspace)
            result = guard.probe_status(scope) if args.command == "probe-status" else guard.renew_probe(scope)
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(json.dumps({"ok": False, "error": str(error),
                          "boundary": "Preserve this scope and original calls; no image was generated by this command."}, ensure_ascii=True), file=sys.stderr)
        return 2
