"""Persistent, scope-bound S7 board production; never invokes an image service.

The upstream scope, prepare request, image bytes and effective pixel requirements
remain frozen. Independent pages have independent state and one exclusive claim.
Native execution and pixel-reading evidence are recorded, not self-certified.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import uuid

from . import board_native, core, image_adapters, reference_boards as boards


def _path(value, project):
    return boards._path(str(value), project)


def identity_key(asset_id, view_id):
    """Filesystem/state identity without delimiter ambiguity in legal IDs."""
    core.require(core.safe_id(asset_id) and core.safe_id(view_id), "Invalid asset/view identity")
    return asset_id[:24] + "-" + core.digest([asset_id, view_id])


def _identity_rows(rows, label, roles=False):
    core.require(isinstance(rows, list) and rows, label + " needs an explicit asset/view list")
    result = {}
    for row in rows:
        core.require(isinstance(row, dict) and core.safe_id(row.get("asset_id"))
                     and core.safe_id(row.get("view_id")), label + " has an invalid asset/view")
        key = row["asset_id"], row["view_id"]
        core.require(key not in result, label + " repeats an asset/view")
        if roles:
            core.require(row.get("role") in boards.ROLES, label + " needs explicit view orientations")
        result[key] = row
    return result


def _source_views(source):
    if source.get("kind") == "reference-board-scope":
        return source.get("asset_views")
    if isinstance(source.get("reference_views"), list):
        return source["reference_views"]
    if isinstance(source.get("asset_proposals"), list):
        rows = []
        for asset in source["asset_proposals"]:
            views = asset.get("approved_reference_views")
            core.require(isinstance(views, list) and views,
                         "Upstream BOM needs explicit approved_reference_views; view aliases are never guessed")
            for view in views:
                core.require(isinstance(view, dict), "BOM approved_reference_views need explicit view_id objects")
                rows.append(dict(view, asset_id=asset.get("asset_id")))
        return rows
    raise core.WorkflowError("Scope source needs reference-board-scope.asset_views or explicit upstream reference_views")


def _concrete(text):
    return isinstance(text, str) and bool(text.strip()) and not boards._placeholder(text)


def _freeze(frozen, path):
    path = Path(path).resolve()
    core.require(path.is_file(), "Frozen board-production input is missing: " + str(path))
    frozen[str(path)] = core.file_hash(path)


def _verify_files(frozen):
    for name, sha in frozen.items():
        path = Path(name)
        core.require(path.is_file() and core.file_hash(path) == sha,
                     "Frozen board-production input or artifact changed: " + name)


def _ref(path, project):
    path = Path(path).resolve()
    return {"path": str(path.relative_to(project)), "sha256": core.file_hash(path)}


def _read_ref(ref, project, frozen):
    path, raw = boards._file(ref, project, {})
    _freeze(frozen, path)
    value = json.loads(raw)
    core.require(isinstance(value, dict), "Bound board-production JSON must be an object")
    return path, value


def _workspace(value, project=None):
    workspace = Path(value).resolve() if project is None else _path(value, project)
    core.require(not core.inside(workspace, Path(__file__).resolve().parents[2]), "Installed Skill is read-only")
    return workspace


def _load(workspace):
    workspace = _workspace(workspace)
    state = core.read(workspace / "production.json")
    core.require(state.get("schema") == 1 and state.get("kind") == "reference-board-production-state"
                 and state.get("workspace") == str(workspace), "Expected the original board-production workspace")
    project = Path(state["project"]).resolve()
    core.require(core.inside(workspace, project), "Board-production workspace escaped its project")
    _verify_files(state["frozen"])
    _, raw = boards._file(state["request"], project, {})
    request = json.loads(raw)
    core.require(core.digest(request) == state["request_digest"] and request["scope"] == state["scope"]
                 and request.get("host_session_id") == state.get("host_session_id"),
                 "Production state differs from its frozen source request")
    if state["preparation_status"] == "ready":
        prepared = core.read(workspace / "prepared" / "preparation.json")
        expected_pages = {row["id"]: {"slots": row["slots"], "request": row["request"]} for row in prepared["prepared"]}
        core.require(not prepared.get("unresolved") and state["pages"] == expected_pages
                     and state["aliases"] == prepared.get("aliases", []),
                     "Production pages differ from the frozen complete preparation")
    return workspace, project, state


def _load_page(workspace, page_id):
    workspace, project, state = _load(workspace)
    core.require(page_id in state.get("pages", {}), "Unknown board-production page")
    page_path = workspace / "pages" / page_id / "state.json"
    page = core.read(page_path)
    core.require(page.get("id") == page_id and page.get("slots") == state["pages"][page_id]["slots"]
                 and page.get("request") == state["pages"][page_id]["request"],
                 "Page scope differs from the frozen preparation")
    _verify_files(page.get("frozen", {}))
    if page.get("mapped"):
        dispatch_path, raw = boards._file(page["dispatch"], project, {})
        dispatch = json.loads(raw)
        core.require(dispatch_path.parent == page_path.parent and bool(re.fullmatch(r"dispatch(?:-[0-9a-f]{64})?\.json", dispatch_path.name))
                     and dispatch["request"] == page["request"]
                     and dispatch["binding"] == page["binding"] and dispatch["host"] == page["host"],
                     "Mapped page differs from the original request, binding or host")
        binding_path, binding_raw = boards._file(page["binding"], project, {})
        arguments, images = board_native._arguments(core.read(_path(page["request"]["path"], project)), json.loads(binding_raw), project)
        core.require(dispatch["tool_arguments"] == arguments and dispatch["images"] == images,
                     "Mapped dispatch no longer reproduces its frozen complete request")
        if page.get("invocation_recorded"):
            claim_path = page_path.parent / "claim.json"
            claim_value = core.read(claim_path)
            completion = core.read(page_path.parent / "completion.json")
            _guard_evidence({"workspace": str(workspace), "project": str(project), "page_id": page_id,
                             "host": dispatch["host"], "tool": dispatch["tool"],
                             "host_session_id": claim_value.get("host_session_id"),
                             "dispatch": {"sha256": core.file_hash(dispatch_path)},
                             "claim": claim_value, "claim_file": {"sha256": core.file_hash(claim_path)}},
                            page["source_ref"], arguments, completion.get("tool_result"), page["board"]["sha256"])
    return workspace, project, state, page_path, page


@contextlib.contextmanager
def _page_lock(workspace, page_id):
    """OS-owned lock: process exit releases it; the inode is never replaced."""
    path = workspace / "pages" / page_id / "operation.lock"
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    acquired = False
    try:
        if os.name == "nt":
            import msvcrt
            if os.fstat(fd).st_size == 0:
                os.write(fd, b"\0")
            os.lseek(fd, 0, os.SEEK_SET)
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                acquired = True
            except OSError as error:
                raise core.WorkflowError("Page bookkeeping is busy; reconcile locally without repeating ImageGen") from error
        else:
            import fcntl
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except OSError as error:
                raise core.WorkflowError("Page bookkeeping is busy; reconcile locally without repeating ImageGen") from error
        yield
    finally:
        if acquired:
            if os.name == "nt":
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def prepare(request, project, workspace, *, request_path):
    """Bind an independent declared upstream scope and prepare all complete pages."""
    project = Path(project).resolve()
    workspace = _workspace(workspace, project)
    core.require(isinstance(request, dict) and request.get("schema") == 1
                 and request.get("kind") == "reference-board-production-input", "Expected reference-board-production-input schema 1")
    request_path = _path(request_path, project)
    core.require(core.read(request_path) == request, "Production request differs from its saved source")
    scope = request.get("scope", {})
    core.require(isinstance(scope, dict) and _concrete(scope.get("source_ref")),
                 "Scope needs its actual upstream decision/source reference; it is not automatic human approval")
    declared = _identity_rows(scope.get("asset_views"), "Declared scope", roles=True)
    frozen = {}
    _freeze(frozen, request_path)
    source_path, source = _read_ref(scope.get("source"), project, frozen)
    spec_path, spec = _read_ref(request.get("prepare_spec"), project, frozen)
    core.require(len({source_path, spec_path, request_path}) == 3,
                 "Scope source must be independent from the production request and prepare specification")
    upstream = _identity_rows(_source_views(source), "Upstream scope")
    plan_rows = _identity_rows(spec.get("plan", {}).get("views"), "Prepare plan", roles=True)
    objects = _identity_rows(spec.get("objects"), "Prepare objects")
    core.require(set(upstream) == set(declared) == set(plan_rows) == set(objects),
                 "Upstream scope, declared scope, plan and object descriptions must cover exactly the same asset/views")
    for key, row in declared.items():
        core.require(row["role"] == plan_rows[key]["role"]
                     and objects[key].get("role", row["role"]) == row["role"]
                     and upstream[key].get("role", row["role"]) == row["role"],
                     "Upstream scope or prepared orientation changed")
        for authority in (upstream[key], row):
            for requirement in ("min_subject_long_edge_px", "min_subject_short_edge_px", "min_feature_px"):
                if requirement in authority:
                    core.require(plan_rows[key].get(requirement, -1) >= authority[requirement],
                                 "Prepare plan lowers an upstream/declared pixel requirement")
            if "critical_feature_fraction_of_short_edge" in authority:
                core.require(plan_rows[key].get("critical_feature_fraction_of_short_edge") == authority["critical_feature_fraction_of_short_edge"],
                             "Prepare plan changes an upstream critical-feature basis")
        for field in ("function", "appearance", "structure"):
            core.require(_concrete(objects[key].get(field)), "Every production object needs concrete " + field + "; placeholders are blocked")
        contract = objects[key].get("modeling_contract", {})
        if "structure" in contract:
            core.require(_concrete(contract["structure"]), "Placeholder modeling construction is blocked")
    for image in spec.get("images", []):
        path, _ = boards._file(image, project, {})
        _freeze(frozen, path)
    for role in spec.get("image_roles", []):
        if role.get("role") == "identity_master":
            core.require(isinstance(role.get("source_review"), dict),
                         "Production identity_master needs its hash-bound passing source_review; relabeling an unreviewed or failed image is blocked")
            _read_ref(role["source_review"], project, frozen)
    manifest = Path(__file__).resolve().parents[2] / "MANIFEST.json"
    if manifest.is_file():
        _freeze(frozen, manifest)
    if (workspace / "production.json").exists():
        _, _, current = _load(workspace)
        core.require(current["request_digest"] == core.digest(request), "Existing production scope changed; use a new explicit revision")
        if current.get("preparation_status") == "ready":
            return status(workspace)
        core.require(not any((workspace / "pages").glob("*/claim.json")),
                     "An existing claimed page cannot be overwritten by re-preparation; reconcile the original production")
    else:
        core.ensure_directory(workspace)
        core.require(not any(workspace.iterdir()), "Use an empty task-owned board-production workspace")
    state = {"schema": 1, "kind": "reference-board-production-state", "project": str(project),
             "workspace": str(workspace), "request": _ref(request_path, project), "request_digest": core.digest(request), "created_at": core.now(),
             "scope": scope, "scope_binding": "declared-source-bound", "human_approval": False,
             "host_session_id": request.get("host_session_id"), "frozen": frozen, "pages": {},
             "aliases": [], "preparation_status": "preparing", "forbidden_output_sha256": request.get("forbidden_output_sha256", [])}
    core.write(workspace / "production.json", state)
    if not (workspace / "context.json").exists():
        core.write(workspace / "context.json", {
            "schema": 1, "kind": "reference-board-operational-context",
            "active_host_session_id": state.get("host_session_id"),
            "history": [{"host_session_id": state.get("host_session_id"), "bound_at": core.now(), "event": "prepare"}]})
    try:
        result = boards.prepare(spec, project, str(workspace / "prepared"), request_path=spec_path)
        core.require(not result.get("unresolved"), "Unresolved board views block production; preserve requirements and repair the responsible input route")
        pages = result.get("prepared", [])
        generated = {boards._identity(slot) for page in pages for slot in page["slots"]}
        aliases = result.get("aliases", [])
        alias_ids = {(row["asset_id"], row["view_id"]) for row in aliases}
        core.require(generated | alias_ids == set(declared), "Prepared pages and explicit model aliases do not cover the frozen upstream scope")
        asset_pages = {}
        for prepared in pages:
            for slot in prepared["slots"]:
                asset_pages.setdefault(slot["asset_id"], set()).add(prepared["id"])
        masters = {(role["asset_id"], view) for role in spec.get("image_roles", [])
                   if role.get("role") == "identity_master" for view in role["target_view_ids"]}
        gaps = [{"asset_id": slot["asset_id"], "view_id": slot["view_id"]}
                for prepared in pages for slot in prepared["slots"]
                if len(asset_pages[slot["asset_id"]]) > 1 and boards._identity(slot) not in masters]
        state["unbound_identity_views"] = gaps
        core.require(not gaps,
                     "Split multiview production needs a passing identity_master/source_review for every target view; use one joint design page or bind a qualified master")
        for path in (workspace / "prepared").iterdir():
            if path.is_file():
                _freeze(state["frozen"], path)
        state["aliases"] = aliases
        for prepared in pages:
            page_id = prepared["id"]
            state["pages"][page_id] = {"slots": prepared["slots"], "request": prepared["request"]}
            core.write(workspace / "pages" / page_id / "state.json", {
                "id": page_id, "slots": prepared["slots"], "request": prepared["request"],
                "input_roles": prepared.get("input_roles", []),
                "frozen": {}, "mapped": False, "crops": {}, "reviews": {}})
        state["preparation_status"] = "ready"
        core.write(workspace / "production.json", state)
        binding = request.get("native_binding")
        if binding is not None:
            binding_path, _ = _read_ref(binding, project, {})
            for page_id in state["pages"]:
                map_native(workspace, page_id, binding_path)
        return status(workspace)
    except (ValueError, OSError, KeyError, TypeError) as error:
        state["last_error"] = str(error)
        if state["preparation_status"] == "ready":
            state["next_action"] = "map each unmapped page with a compatible binding at a new explicit path; preserve the original scope, inputs and page requests"
            core.write(workspace / "production.json", state)
            return status(workspace)
        state["preparation_status"] = "blocked"
        state["next_action"] = ("prepare/qualify source master then bind targets; preserve the declared scope and pixel requirements"
                                if state.get("unbound_identity_views") else "repair the named input or capability gap; preserve scope and pixel requirements")
        core.write(workspace / "production.json", state)
        raise


def map_native(workspace, page_id, binding_path):
    workspace, project, state, page_path, page = _load_page(workspace, page_id)
    binding_path = _path(binding_path, project)
    binding = core.read(binding_path)
    with _page_lock(workspace, page_id):
        _, _, _, page_path, page = _load_page(workspace, page_id)
        if page.get("mapped"):
            if page["binding"]["sha256"] == core.file_hash(binding_path):
                return inspect_claim(workspace, page_id)
        core.require(not (page_path.parent / "claim.json").exists(),
                     "Claimed page cannot be remapped; reconcile its original dispatch and call")
        binding_ref = _ref(binding_path, project)
        attempt = {"binding": binding_ref, "mapped_at": core.now()}
        try:
            filename = "dispatch-" + binding_ref["sha256"] + ".json"
            result = board_native.prepare(core.read(_path(page["request"]["path"], project)), binding, project,
                                          str(page_path.parent / filename), request_path=page["request"]["path"],
                                          binding_path=binding_path)
            page.update(mapped=True, binding=binding_ref, dispatch=result["dispatch"], host=binding["host"], mapping_error=None)
            attempt.update(result="mapped", dispatch=result["dispatch"])
            _freeze(page["frozen"], _path(result["dispatch"]["path"], project))
        except (ValueError, OSError, KeyError, TypeError) as error:
            page.update(mapped=False, mapping_error=str(error))
            attempt.update(result="failed", error=str(error))
            raise
        finally:
            _freeze(page["frozen"], binding_path)
            page.setdefault("mapping_attempts", []).append(attempt)
            core.write(page_path, page)
    return inspect_claim(workspace, page_id)


def inspect_claim(workspace, page_id):
    """Read-only hook API; raises WorkflowError/OSError for stale or invalid data."""
    workspace, project, state, page_path, page = _load_page(workspace, page_id)
    core.require(page.get("mapped"), "Page has no exact native dispatch yet")
    core.require(state.get("preparation_status") == "ready", "Blocked or unresolved production cannot dispatch a partial scope")
    dispatch_path = _path(page["dispatch"]["path"], project)
    dispatch = core.read(dispatch_path)
    claim_path = page_path.parent / "claim.json"
    claim = {"status": "unclaimed"}
    claim_ref = None
    context = _context(workspace, state)
    if claim_path.is_file():
        claim = core.read(claim_path)
        core.require(claim.get("dispatch_sha256") == core.file_hash(dispatch_path)
                     and claim.get("page_id") == page_id and isinstance(claim.get("id"), str),
                     "Claim differs from its exact page dispatch")
        claim = dict(claim, status="recorded" if page.get("invocation_recorded") else "pending")
        if page.get("source_ref"):
            claim["source_ref"] = page["source_ref"]
        claim_ref = {"path": str(claim_path), "sha256": core.file_hash(claim_path)}
    return {"ok": True, "workspace": str(workspace), "project": str(project),
            "host_session_id": claim.get("host_session_id", state.get("host_session_id")) if claim_ref else context["active_host_session_id"],
            "active_host_session_id": context["active_host_session_id"], "host": page["host"], "page_id": page_id,
            "dispatch": {"path": str(dispatch_path), "sha256": core.file_hash(dispatch_path)},
            "tool": dispatch["tool"], "tool_arguments": dispatch["tool_arguments"],
            "claim": claim, "claim_file": claim_ref}


def _context(workspace, state):
    path = workspace / "context.json"
    if not path.is_file():
        return {"schema": 1, "kind": "reference-board-operational-context",
                "active_host_session_id": state.get("host_session_id"), "history": []}
    value = core.read(path)
    core.require(value.get("schema") == 1 and value.get("kind") == "reference-board-operational-context"
                 and isinstance(value.get("history"), list), "Invalid board operational context")
    return value


def bind_session(workspace, session_id):
    """Refresh operational context; never clear or relabel an existing claim."""
    workspace, project, state = _load(workspace)
    core.require(isinstance(session_id, str) and bool(re.fullmatch(r"\S+", session_id))
                 and _concrete(session_id), "Provide the actual current host session ID")
    context = _context(workspace, state)
    previous = context["active_host_session_id"]
    if session_id != previous:
        context["history"].append({"host_session_id": session_id, "previous_host_session_id": previous,
                                   "bound_at": core.now(), "event": "bind-session"})
        context["active_host_session_id"] = session_id
        core.write(workspace / "context.json", context)
    pending = []
    for page_id in state["pages"]:
        path = workspace / "pages" / page_id / "claim.json"
        if path.is_file():
            page = core.read(path.parent / "state.json")
            if not page.get("invocation_recorded"):
                claim_value = core.read(path)
                pending.append({"page_id": page_id, "claim_id": claim_value["id"],
                                "host_session_id": claim_value.get("host_session_id", state.get("host_session_id"))})
    return {"ok": True, "workspace": str(workspace), "active_host_session_id": session_id,
            "pending_original_calls": pending, "history_count": len(context["history"]),
            "boundary": "Only operational session context changed. Scope, images, dispatches and all original pending claims remain bound; reconcile unknown outcomes without resubmission."}


def claim(workspace, page_id):
    info = inspect_claim(workspace, page_id)
    core.require(info["claim"]["status"] == "unclaimed", "Page already claimed; reconcile the original outcome, never reissue an uncertain call")
    path = Path(info["workspace"]) / "pages" / page_id / "claim.json"
    value = {"status": "pending", "id": str(uuid.uuid4()), "page_id": page_id,
             "dispatch_sha256": info["dispatch"]["sha256"], "claimed_at": core.now(),
             "host_session_id": info["host_session_id"]}
    try:
        with path.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as error:
        raise core.WorkflowError("Page was claimed concurrently; do not invoke twice") from error
    _, _, _, page_path, page = _load_page(workspace, page_id)
    _freeze(page["frozen"], path)
    core.write(page_path, page)
    return dict(inspect_claim(workspace, page_id), next_action="invoke_exactly_once_under_existing_authority",
                boundary="A local claim is not paid-call authorization or proof of native execution.")


def verify(workspace, page_id, actual_arguments):
    info = inspect_claim(workspace, page_id)
    core.require(info["claim"]["status"] == "pending", "Native invocation needs an unrecorded one-time page claim")
    core.require(info["host_session_id"] == info["active_host_session_id"],
                 "This pending claim belongs to a previous host session; reconcile its original call, never invoke it again")
    core.require(isinstance(actual_arguments, dict) and actual_arguments == info["tool_arguments"],
                 "Actual native arguments differ from the frozen page dispatch")
    return info


def _native_receipt(receipt_path, dispatch, actual, image_hash, source_ref):
    receipt = core.read(receipt_path)
    core.require(receipt.get("kind") == "reference-image-generation-receipt"
                 and receipt.get("invocation_recorded") is True and receipt.get("tool") == dispatch["tool"]
                 and receipt.get("source_ref") == source_ref and receipt.get("actual_tool_arguments") == actual
                 and receipt.get("output_sha256") == image_hash
                 and receipt.get("actual_input_image_sha256") == [row["sha256"] for row in dispatch["images"]],
                 "Original native receipt changed or belongs to another outcome")


def _workbuddy_failed(result):
    return isinstance(result, dict) and (
        bool(result.get("error") or result.get("isError") or result.get("is_error"))
        or result.get("success") is False or result.get("ok") is False
        or ("status" in result and result["status"] not in {"completed", "succeeded", "success"}))


def _workbuddy_payload(result):
    """Decode known host transport wrappers, keeping the unmodified raw receipt."""
    for _ in range(6):
        if _workbuddy_failed(result):
            break
        if isinstance(result, str):
            result = json.loads(result)
        elif isinstance(result, dict) and result.get("type") == "text" and isinstance(result.get("text"), str):
            result = json.loads(result["text"])
        elif isinstance(result, dict) and isinstance(result.get("content"), list) and len(result["content"]) == 1:
            result = result["content"][0]
        elif isinstance(result, dict) and isinstance(result.get("content"), str):
            result = json.loads(result["content"])
        else:
            break
    return result


def _workbuddy_result(result, output_hash):
    """Bind the actual host-returned file; an unknown outcome stays pending."""
    result = _workbuddy_payload(result)
    core.require(isinstance(result, dict) and result.get("type") == "image_gen_tool_result"
                 and result.get("status", "completed") in {"completed", "succeeded", "success"}
                 and not _workbuddy_failed(result),
                 "WorkBuddy record needs its real completed ImageGen result; unknown/failed calls stay pending")
    images = result.get("images")
    core.require(isinstance(images, list) and len(images) == 1 and isinstance(images[0], dict),
                 "Actual ImageGen result must contain exactly one returned image")
    path = images[0].get("localPath")
    core.require(isinstance(path, str) and Path(path).is_absolute() and Path(path).is_file()
                 and core.file_hash(path) == output_hash, "Actual ImageGen returned path does not match the recorded output bytes")
    return result


def _workbuddy_same_result(left, right):
    # WorkBuddy's ImageGen returns S as JSON content and {...S, credit} as
    # rawResponse to the hook. Preserve both originals; only this declared
    # billing metadata is excluded from the business-result comparison.
    def comparable(value):
        value = _workbuddy_payload(value)
        return {key: item for key, item in value.items() if key != "credit"} if isinstance(value, dict) else value
    return core.digest(comparable(left)) == core.digest(comparable(right))


def _guard_evidence(info, source_ref, actual_arguments, tool_result, output_hash):
    """Read existing host facts without importing the hook's execution code."""
    workspace = Path(info["workspace"])
    claim_id = info["claim"]["id"]
    pre_path = workspace / "host-guard" / "claims" / (hashlib.sha256(claim_id.encode()).hexdigest() + ".json")
    post_path = workspace / "host-guard" / "results" / (hashlib.sha256(source_ref.encode()).hexdigest() + ".json")
    pre = None
    for conflict_path in (workspace / "host-guard" / "conflicts").glob("*.json"):
        conflict = core.read(conflict_path)
        core.require(not (conflict.get("source_ref") == source_ref and conflict.get("page_id") == info["page_id"]),
                     "Guard retained contradictory original host results; reconcile the conflict before production can complete")
    if pre_path.exists():
        pre = core.read(pre_path)
        core.require(pre.get("schema") == 1 and pre.get("kind") == "workbuddy-board-hook-claim"
                     and pre.get("page_id") == info["page_id"] and pre.get("claim_id") == claim_id
                     and pre.get("claim_sha256") == info["claim_file"]["sha256"]
                     and pre.get("dispatch_sha256") == info["dispatch"]["sha256"],
                     "Guard Pre evidence conflicts with the original claim/dispatch; production blocked")
        core.require(pre.get("source_ref") == source_ref
                     and pre.get("event", {}).get("tool_input") == actual_arguments
                     and pre.get("event", {}).get("tool_name") == info.get("tool")
                     and pre.get("event", {}).get("session_id") == info.get("host_session_id")
                     and pre.get("event", {}).get("tool_use_id", pre.get("event", {}).get("call_id")) == source_ref,
                     "Guard Pre original host call ID or arguments conflict; production blocked")
    if post_path.exists():
        post = core.read(post_path)
        core.require(pre is not None and post.get("schema") == 1 and post.get("kind") == "workbuddy-board-hook-result"
                     and post.get("source_ref") == source_ref and post.get("page_id") == info["page_id"]
                     and post.get("pre_event_sha256") == core.file_hash(pre_path),
                     "Guard Post evidence conflicts with the original Pre event; production blocked")
        event = post.get("event", {})
        core.require(event.get("tool_input") == actual_arguments and _workbuddy_same_result(event.get("tool_response"), tool_result),
                     "Guard Post actual arguments/result conflict with the local record; production blocked")
        _workbuddy_result(event["tool_response"], output_hash)
    execution_pre_path = workspace / "host-guard" / "execution-claims" / (hashlib.sha256(claim_id.encode()).hexdigest() + ".json")
    execution_post_path = workspace / "host-guard" / "execution-results" / (hashlib.sha256(source_ref.encode()).hexdigest() + ".json")
    deferred = info.get("host") == "workbuddy" and info.get("tool") == "DeferExecuteTool"
    if deferred and (pre is not None or execution_pre_path.exists() or execution_post_path.exists()):
        core.require(pre is not None and execution_pre_path.is_file(),
                     "Guard deferred wrapper is not ImageGen execution proof; original inner Pre is required")
        execution_pre = core.read(execution_pre_path)
        core.require(execution_pre.get("schema") == 1 and execution_pre.get("kind") == "workbuddy-board-hook-execution-claim"
                     and execution_pre.get("page_id") == info["page_id"] and execution_pre.get("claim_id") == claim_id
                     and execution_pre.get("claim_sha256") == info["claim_file"]["sha256"]
                     and execution_pre.get("dispatch_sha256") == info["dispatch"]["sha256"]
                     and execution_pre.get("source_ref") == source_ref
                     and execution_pre.get("outer_pre_sha256") == core.file_hash(pre_path),
                     "Guard inner Pre claim/dispatch/outer evidence conflicts; production blocked")
        arguments = actual_arguments.get("params")
        core.require(actual_arguments.get("toolName") == "ImageGen" and isinstance(arguments, dict),
                     "Guard deferred ImageGen needs its exact frozen params envelope")

        def validate_inner_event(event, expected_events):
            outer_event = pre.get("event", {})
            core.require(event.get("tool_name") == "ImageGen"
                         and event.get("hook_event_name") in expected_events
                         and event.get("session_id") == info.get("host_session_id")
                         and event.get("generation_id") == outer_event.get("generation_id")
                         and event.get("tool_use_id", event.get("call_id")) == source_ref
                         and ("call_id" not in event or event["call_id"] == source_ref)
                         and core.digest(event.get("tool_input")) == core.digest(arguments)
                         and isinstance(event.get("cwd"), str)
                         and isinstance(outer_event.get("cwd"), str)
                         and Path(event["cwd"]).resolve() == Path(outer_event["cwd"]).resolve()
                         and Path(event["cwd"]).resolve().is_relative_to(Path(info["project"])),
                         "Guard inner original event identity or params conflict; production blocked")

        validate_inner_event(execution_pre.get("event", {}), {"PreToolUse"})
        if execution_post_path.exists():
            execution_post = core.read(execution_post_path)
            core.require(execution_post.get("schema") == 1
                         and execution_post.get("kind") == "workbuddy-board-hook-execution-result"
                         and execution_post.get("page_id") == info["page_id"]
                         and execution_post.get("claim_id") == claim_id
                         and execution_post.get("claim_sha256") == info["claim_file"]["sha256"]
                         and execution_post.get("dispatch_sha256") == info["dispatch"]["sha256"]
                         and execution_post.get("source_ref") == source_ref
                         and execution_post.get("outer_pre_sha256") == core.file_hash(pre_path)
                         and execution_post.get("execution_pre_sha256") == core.file_hash(execution_pre_path),
                         "Guard inner Post evidence conflicts with its original execution Pre")
            event = execution_post.get("event", {})
            validate_inner_event(event, {"PostToolUse", "PostToolUseFailure"})
            core.require(_workbuddy_same_result(event.get("tool_response"), tool_result),
                         "Guard inner Post result conflicts with the original returned result")
            _workbuddy_result(event.get("tool_response"), output_hash)


def record(workspace, page_id, actual_arguments, image, *, source_ref, tool_result=None):
    workspace, project, state, page_path, page = _load_page(workspace, page_id)
    info = inspect_claim(workspace, page_id)
    core.require(info["claim"]["status"] in {"pending", "recorded"}, "Record requires the page's original one-time claim")
    core.require(actual_arguments == info["tool_arguments"], "Actual native arguments differ from the frozen page dispatch")
    core.require(_concrete(source_ref), "Record needs its original native invocation source_ref")
    image = Path(image).resolve()
    image_info = image_adapters.image_info(image)
    if info["host"] == "workbuddy":
        _workbuddy_result(tool_result, image_info["sha256"])
    dispatch = core.read(info["dispatch"]["path"])
    forbidden = set(state.get("forbidden_output_sha256", [])) | {row["sha256"] for row in dispatch["images"]}
    core.require(image_info["sha256"] not in forbidden, "An input/layout/historical image cannot impersonate a new board")
    completion = {"source_ref": source_ref, "actual_arguments": actual_arguments,
                  "output_sha256": image_info["sha256"], "tool_result": tool_result}
    with _page_lock(workspace, page_id):
        _, _, _, page_path, page = _load_page(workspace, page_id)
        _guard_evidence(info, source_ref, actual_arguments, tool_result, image_info["sha256"])
        completed_path = page_path.parent / "completion.json"
        if completed_path.is_file():
            core.require(core.read(completed_path) == completion,
                         "Only the original call, arguments and output may resume; never replace an unknown outcome")
        else:
            core.write(completed_path, completion)
        if page.get("invocation_recorded"):
            _native_receipt(_path(page["generation_receipt"]["path"], project), dispatch, actual_arguments,
                            image_info["sha256"], source_ref)
            return _page_status(project, page_path, page)
        # Keep an existing project-contained output canonical; import only a
        # genuinely external new image once, content-addressed in this case.
        if core.inside(image, project):
            board = image
        else:
            suffix = image.suffix.lower() if image.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"} else ".image"
            board = workspace / "outputs" / (image_info["sha256"] + suffix)
            core.ensure_directory(board.parent)
            if board.exists():
                core.require(core.file_hash(board) == image_info["sha256"], "Canonical board hash changed")
            else:
                shutil.copy2(image, board)
        record_root = page_path.parent / "native-record"
        receipt = record_root / "receipt-0.json"
        if not receipt.is_file():
            attempt = 0
            candidate = record_root
            while candidate.exists():
                attempt += 1
                candidate = page_path.parent / ("native-record-recovery-" + str(attempt))
                if (candidate / "receipt-0.json").is_file():
                    receipt = candidate / "receipt-0.json"
                    break
            if not receipt.is_file():
                result = board_native.record(dispatch, actual_arguments, board, candidate, project, source_ref=source_ref)
                receipt = Path(result["receipt"]["path"])
        _native_receipt(receipt, dispatch, actual_arguments, image_info["sha256"], source_ref)
        page.update(invocation_recorded=True, source_ref=source_ref,
                    board=_ref(board, project), generation_receipt=_ref(receipt, project))
        for path in (completed_path, board, receipt, Path(info["claim_file"]["path"])):
            _freeze(page["frozen"], path)
        core.write(page_path, page)
    return _page_status(project, page_path, page)


def _save_review_pointer(page, page_path, project):
    """Publish the current subset without rewriting any historical observation."""
    document = {"schema": 1, "kind": "reference-board-visual-review", "reviews": list(page.get("reviews", {}).values()),
                "boundary": "Recorded reviewer observations, not automatic pixel judgment or human acceptance."}
    path = page_path.parent / "reviews" / ("review-" + core.digest(document) + ".json")
    if not path.exists():
        core.write(path, document)
    page["review_ref"] = _ref(path, project)
    _freeze(page["frozen"], path)


def crop(workspace, page_id, observed):
    """Inspect selected slots independently; ROI attempts never repeat ImageGen."""
    workspace, project, state, page_path, page = _load_page(workspace, page_id)
    core.require(page.get("invocation_recorded"), "Record the original board call before cropping")
    rows = _identity_rows(observed, "Observed crop ROIs", roles=True)
    slots = {boards._identity(row): row for row in page["slots"]}
    core.require(bool(rows) and set(rows).issubset(slots), "Observed crops must name a nonempty subset of frozen page slots")
    rectangles = []
    for key, row in rows.items():
        core.require(row["role"] == slots[key]["role"], "Crop orientation differs from frozen requirements")
        roi = row.get("roi")
        core.require(isinstance(roi, list) and len(roi) == 4 and all(type(value) is int for value in roi),
                     "Supply observed integer ROIs; layout regions are not default crop coordinates")
        rectangles.append(tuple(roi))
        for name, value in slots[key]["requirements"].items():
            core.require(name not in row or row[name] == value, "Crop may not lower frozen subject/detail requirements")
    core.require(len(set(rectangles)) == len(rectangles), "Different page slots cannot reuse an identical ROI")
    # A partial repair cannot relabel an already selected sibling's pixels.
    for key, slot in slots.items():
        name = identity_key(*key)
        if key not in rows and name in page.get("crops", {}):
            prior = core.read(_path(page["crops"][name]["path"], project))
            core.require(tuple(prior["recipe"]["roi"]) not in rectangles,
                         "Different page slots cannot reuse an identical ROI")
    with _page_lock(workspace, page_id):
        _, _, _, page_path, page = _load_page(workspace, page_id)
        for key, row in rows.items():
            name = identity_key(*key)
            recipe = {"schema": 1, "kind": "reference-board-crop-request", "asset_id": key[0], "view_id": key[1],
                      "role": row["role"], "roi": row["roi"], "padding": 24, "qualification_mode": "inspection",
                      "selected_concept_sha256": core.read(_path(page["request"]["path"], project))["images"][0]["sha256"],
                      "board": page["board"], "generation_receipt": page["generation_receipt"],
                      **slots[key]["requirements"]}
            attempt_dir = page_path.parent / "crop-attempts" / name / core.digest(recipe)
            request = dict(recipe, output=str((attempt_dir / "crop.png").relative_to(project)),
                           receipt_output=str((attempt_dir / "crop.receipt.json").relative_to(project)))
            request_path = attempt_dir / "request.json"
            outcome_path = attempt_dir / "outcome.json"
            if request_path.exists():
                core.require(core.read(request_path) == request, "Crop attempt source changed")
            else:
                core.write(request_path, request)
            if outcome_path.exists():
                outcome = core.read(outcome_path)
                core.require(outcome.get("request") == _ref(request_path, project), "Crop attempt outcome lost its original request")
            else:
                outcome = {"schema": 1, "kind": "reference-board-crop-attempt", "asset_id": key[0], "view_id": key[1],
                           "request": _ref(request_path, project)}
                try:
                    result = boards.crop(request, project, request_path=request_path)
                    checked = boards.validate_crop_receipt(result["board_crop_receipt"], project, require_qualified=False)
                    outcome.update(ok=True, crop=result["board_crop_receipt"], technical_pass=checked["technical_pass"],
                                   qualification_failures=checked["qualification_failures"])
                except (core.WorkflowError, OSError) as error:
                    outcome.update(ok=False, error=str(error), error_type=type(error).__name__,
                                   next_action="Correct only this slot's observed ROI and run crop again; no new ImageGen call is needed.")
                core.write(outcome_path, outcome)
            attempt_ref = _ref(outcome_path, project)
            attempts = page.setdefault("crop_attempts", {}).setdefault(name, [])
            if attempt_ref not in attempts:
                attempts.append(attempt_ref)
            _freeze(page["frozen"], request_path)
            _freeze(page["frozen"], outcome_path)
            if outcome["ok"]:
                checked = boards.validate_crop_receipt(outcome["crop"], project, asset_id=key[0], view_id=key[1],
                                                      role=row["role"], require_qualified=False)
                core.require(checked["technical_pass"] == outcome["technical_pass"]
                             and checked["qualification_failures"] == outcome["qualification_failures"],
                             "Crop attempt qualification differs from its replayed receipt")
                prior = page["crops"].get(name)
                page["crops"][name] = outcome["crop"]
                page.setdefault("crop_errors", {}).pop(name, None)
                receipt = core.read(_path(outcome["crop"]["path"], project))
                _freeze(page["frozen"], _path(receipt["output"]["path"], project))
                _freeze(page["frozen"], _path(outcome["crop"]["path"], project))
                if prior != outcome["crop"] and name in page.get("reviews", {}):
                    page["reviews"].pop(name)
                    _save_review_pointer(page, page_path, project)
            else:
                page.setdefault("crop_errors", {})[name] = {"attempt": attempt_ref, "error": outcome["error"],
                                                            "next_action": outcome["next_action"]}
            core.write(page_path, page)
    return _page_status(project, page_path, page)


def _cross_view_status(project, state):
    """Bind declared cross-view observations to all current crops of each asset."""
    grouped = {}
    for row in state["scope"]["asset_views"]:
        grouped.setdefault(row["asset_id"], []).append(row)
    grouped = {asset: rows for asset, rows in grouped.items() if len(rows) > 1}
    if not grouped:
        return []
    pages, outputs, qualified, owner = {}, {}, {}, {}
    for page_id in state["pages"]:
        _, _, _, _, page = _load_page(state["workspace"], page_id)
        pages[page_id] = page
        for slot in page["slots"]:
            owner.setdefault(slot["asset_id"], page_id)
            name = identity_key(slot["asset_id"], slot["view_id"])
            crop_ref = page.get("crops", {}).get(name)
            if crop_ref:
                check = boards.validate_crop_receipt(crop_ref, project, asset_id=slot["asset_id"],
                                                     view_id=slot["view_id"], role=slot["role"], require_qualified=False)
                receipt = core.read(_path(crop_ref["path"], project))
                outputs[boards._identity(slot)] = receipt["output"]
                qualified[boards._identity(slot)] = check["technical_pass"] and name not in page.get("crop_errors", {})
    for alias in state["aliases"]:
        source = alias["source_asset_id"], alias["source_view_id"]
        if source in outputs:
            outputs[alias["asset_id"], alias["view_id"]] = outputs[source]
            qualified[alias["asset_id"], alias["view_id"]] = qualified.get(source, False)
        if alias["source_asset_id"] in owner:
            owner.setdefault(alias["asset_id"], owner[alias["source_asset_id"]])
    result = []
    for asset, views in grouped.items():
        owner_id = owner.get(asset)
        required = [{"view_id": row["view_id"], "image": outputs.get((asset, row["view_id"]))} for row in views]
        entry = {"asset_id": asset, "owner_page": owner_id, "required_images": required,
                 "technical_ready": all(qualified.get((asset, row["view_id"]), False) for row in views),
                 "recorded": False, "verdict": "missing", "observation": None,
                 "next_action": "Read and compare all named current crops; record a separate cross_view_reviews declaration."}
        ref = pages.get(owner_id, {}).get("cross_view_reviews", {}).get(asset)
        if ref:
            _, raw = boards._file(ref, project, {})
            review = json.loads(raw)
            actual = {row["view_id"]: row["image"] for row in review["images"]}
            expected = {row["view_id"]: row["image"] for row in required}
            if actual == expected and all(expected.values()):
                entry.update(recorded=True, verdict=review["verdict"], observation=review["observation"],
                             source_ref=review["source_ref"], next_action=None if review["verdict"] == "pass" else
                             "Use the cross-view observation to locate the inconsistent view; preserve good siblings and bind only the needed repair scope.")
            else:
                entry.update(verdict="stale", prior_review=ref,
                             next_action="A current crop changed; compare all current views again and record a new cross-view review. Prior evidence is preserved.")
        result.append(entry)
    return result


def review(workspace, page_id, reviews):
    workspace, project, state, page_path, page = _load_page(workspace, page_id)
    cross_reviews = reviews.get("cross_view_reviews", []) if isinstance(reviews, dict) else []
    supplied = reviews.get("reviews", []) if isinstance(reviews, dict) else reviews
    core.require(isinstance(cross_reviews, list), "cross_view_reviews must be a list")
    rows = _identity_rows(supplied, "Per-crop visual reviews", roles=True) if supplied else {}
    core.require(rows or cross_reviews, "Provide per-crop or cross-view observations")
    slots = {boards._identity(row): row for row in page["slots"]}
    core.require(set(rows).issubset(set(slots)), "Visual reviews contain a view outside the frozen page")
    result = {}
    for key, row in rows.items():
        name = identity_key(*key)
        core.require(row["role"] == slots[key]["role"], "Review view differs from the frozen page")
        core.require(name in page.get("crops", {}), "Finish actual crops for each named view before its visual review")
        crop_ref = page["crops"][name]
        boards.validate_crop_receipt(crop_ref, project, require_qualified=False)
        actual_image = core.read(_path(crop_ref["path"], project))["output"]
        core.require(row.get("image") == actual_image, "Visual review must bind its exact current crop path and hash")
        core.require(row.get("verdict") in {"pass", "fail", "unclear"}
                     and _concrete(row.get("observation")) and len(row["observation"].strip()) >= 12
                     and _concrete(row.get("inspection_source_ref")),
                     "Each crop needs a concrete pixel observation, verdict and actual image-reading source reference")
        result[name] = row
    expected_cross = {row["asset_id"]: row for row in _cross_view_status(project, state)}
    validated_cross = {}
    for row in cross_reviews:
        core.require(isinstance(row, dict) and row.get("asset_id") in expected_cross
                     and row["asset_id"] not in validated_cross, "Cross-view review needs a distinct scoped multiview asset")
        asset = row["asset_id"]
        expected = expected_cross[asset]
        core.require(expected["owner_page"] == page_id,
                     "Record this cross-view review on its owner page: " + str(expected["owner_page"]))
        images = row.get("images")
        core.require(isinstance(images, list) and len(images) == len(expected["required_images"])
                     and all(isinstance(image, dict) for image in images)
                     and len({image.get("view_id") for image in images}) == len(images)
                     and {image.get("view_id"): image.get("image") for image in images} ==
                     {image["view_id"]: image["image"] for image in expected["required_images"]}
                     and all(image["image"] for image in expected["required_images"]),
                     "Cross-view review must bind every exact current crop path/hash for the asset")
        verdicts = [row[key] for key in ("verdict", "status") if key in row]
        core.require(verdicts and len(set(verdicts)) == 1 and verdicts[0] in {"pass", "fail", "unclear"}
                     and _concrete(row.get("observation")) and len(row["observation"].strip()) >= 12
                     and _concrete(row.get("source_ref")), "Cross-view review needs a consistent verdict, concrete comparison and actual observation source")
        core.require(verdicts[0] != "pass" or expected["technical_ready"],
                     "Cross-view pass requires every current view to pass its frozen crop technical checks")
        validated_cross[asset] = dict(row, verdict=verdicts[0])
    with _page_lock(workspace, page_id):
        _, _, _, page_path, page = _load_page(workspace, page_id)
        for name, row in result.items():
            current = page.get("crops", {}).get(name)
            core.require(current and core.read(_path(current["path"], project))["output"] == row["image"],
                         "Crop changed during visual review; inspect its current image before recording")
        combined = dict(page.get("reviews", {}), **result)
        document = {"schema": 1, "kind": "reference-board-visual-review", "reviews": list(combined.values()),
                    "boundary": "Recorded reviewer observations, not automatic pixel judgment or human acceptance."}
        review_path = page_path.parent / "reviews" / ("review-" + core.digest(document) + ".json")
        if not review_path.exists():
            core.write(review_path, document)
        page["reviews"] = combined
        page["review_ref"] = _ref(review_path, project)
        # A repair may supersede a previous review, while exact image identity
        # remains frozen and every prior actual crop stays independently bound.
        page["frozen"][str(review_path)] = core.file_hash(review_path)
        for asset, row in validated_cross.items():
            document = dict(row, schema=1, kind="reference-board-cross-view-review",
                            boundary="Recorded comparison and image-source binding; not algorithmic 3D consistency proof.")
            cross_path = page_path.parent / "cross-view-reviews" / (asset + "-" + core.digest(document) + ".json")
            if not cross_path.exists():
                core.write(cross_path, document)
            page.setdefault("cross_view_reviews", {})[asset] = _ref(cross_path, project)
            _freeze(page["frozen"], cross_path)
        core.write(page_path, page)
    return _page_status(project, page_path, page)


def _page_status(project, page_path, page):
    claim_path = page_path.parent / "claim.json"
    invoked = page.get("invocation_recorded") is True
    if invoked:
        core.require(claim_path.is_file(), "Recorded page lost its original claim")
        _, board_raw = boards._file(page["board"], project, {})
        receipt_path, _ = boards._file(page["generation_receipt"], project, {})
        dispatch = core.read(_path(page["dispatch"]["path"], project))
        _native_receipt(receipt_path, dispatch, dispatch["tool_arguments"], page["board"]["sha256"], page["source_ref"])
    expected = {identity_key(row["asset_id"], row["view_id"]) for row in page["slots"]}
    core.require(set(page.get("crops", {})).issubset(expected), "Current crops contain a view outside the frozen page")
    crop_results = []
    for slot in page["slots"]:
        key = identity_key(slot["asset_id"], slot["view_id"])
        ref = page.get("crops", {}).get(key)
        error = page.get("crop_errors", {}).get(key)
        item = {"asset_id": slot["asset_id"], "view_id": slot["view_id"], "role": slot["role"],
                "crop_available": bool(ref), "technical_pass": False,
                "qualification_failures": [], "error": error}
        if ref:
            check = boards.validate_crop_receipt(ref, project, asset_id=slot["asset_id"], view_id=slot["view_id"],
                                                role=slot["role"], require_qualified=False)
            receipt = core.read(_path(ref["path"], project))
            core.require(receipt["board"] == page["board"] and receipt["generation_receipt"] == page["generation_receipt"]
                         and all(receipt["recipe"].get(name) == value for name, value in slot["requirements"].items()),
                         "Crop receipt differs from its original board invocation or frozen requirements")
            item.update(technical_pass=check["technical_pass"] and not error,
                        qualification_failures=check["qualification_failures"], image=receipt["output"])
        crop_results.append(item)
    technical = bool(crop_results) and all(row["technical_pass"] for row in crop_results)
    if page.get("reviews"):
        _, raw = boards._file(page["review_ref"], project, {})
        document = json.loads(raw)
        actual_reviews = {identity_key(row["asset_id"], row["view_id"]): row for row in document["reviews"]}
        core.require(actual_reviews == page["reviews"], "Page review state differs from the actual recorded review evidence")
        for key, row in actual_reviews.items():
            core.require(key in page["crops"] and row["image"] == core.read(_path(page["crops"][key]["path"], project))["output"],
                         "Review observation does not bind its exact current crop")
    visual_recorded = set(page.get("reviews", {})) == expected
    visual_pass = visual_recorded and all(row["verdict"] == "pass" for row in page["reviews"].values())
    _, _, state = _load(page_path.parents[2])
    context = _context(page_path.parents[2], state)
    claim_session = core.read(claim_path).get("host_session_id", state.get("host_session_id")) if claim_path.is_file() else None
    assets = {row["asset_id"] for row in page["slots"]}
    cross_reviews = [row for row in _cross_view_status(project, state) if row["asset_id"] in assets]
    cross_pass = all(row["recorded"] and row["verdict"] == "pass" and row["technical_ready"] for row in cross_reviews)
    repair_views = [{"asset_id": row["asset_id"], "view_id": row["view_id"], "role": row["role"],
                     "verdict": row["verdict"], "observation": row["observation"],
                     "repair_layer": row.get("repair_layer", "inspect_recorded_observation"),
                     "repair_action": row.get("repair_action", "Repair only this view in an explicitly bound revision; preserve successful sibling masters.")}
                    for row in page.get("reviews", {}).values() if row["verdict"] in {"fail", "unclear"}]
    # Missing downstream artifacts are expected until the original invocation
    # has been recorded. Do not misreport an ungenerated page as a crop fault.
    for row in crop_results if invoked else []:
        if row["technical_pass"]:
            continue
        failure = row["error"]
        messages = [item["observation"] for item in row["qualification_failures"]]
        observation = failure["error"] if failure else ("; ".join(messages) or "No current crop is available for this frozen slot.")
        codes = {item["code"] for item in row["qualification_failures"]}
        boundary = bool(codes & {"nonwhite_boundary", "blank_subject"}) or ("small_canvas" in codes and "subject_pixels" not in codes)
        action = (failure["next_action"] if failure else
                  "Inspect and correct only this slot's ROI, then rerun crop without a new image call." if boundary else
                  "The original subject lacks required detail or is missing; preserve the crop for inspection and plan only the failed view's repair within the existing scope and budget." if messages else
                  "Locate this slot in the actual board and submit its observed ROI; do not use template cells as coordinates.")
        repair_views = [prior for prior in repair_views if (prior["asset_id"], prior["view_id"]) != (row["asset_id"], row["view_id"])]
        repair_views.append({"asset_id": row["asset_id"], "view_id": row["view_id"], "role": row["role"],
                             "verdict": "fail" if row["crop_available"] or failure else "missing",
                             "observation": observation, "repair_layer": "crop_roi" if boundary or failure or not messages else "subject_detail",
                             "repair_action": action})
    if not page.get("mapped"):
        phase, next_action = "map", "Map this unclaimed page with a compatible binding at a new explicit path."
    elif not invoked and claim_path.exists():
        phase, next_action = "recover", "Recover the original pending page call and record its actual result; do not claim or submit it again."
    elif not invoked:
        phase, next_action = "claim", "Claim this prepared page once, then invoke its exact mapped tool arguments and record the original result."
    elif repair_views:
        phase, next_action = "crop" if any(not row["crop_available"] for row in crop_results) else "repair", repair_views[0]["repair_action"]
    elif not visual_recorded:
        phase, next_action = "review", "Inspect the available current crop images and record their per-view visual observations."
    elif not cross_pass:
        phase, next_action = "cross_view_review", next((row["next_action"] for row in cross_reviews if row["next_action"]),
                                                       "Compare the current views of each multiview asset and record their cross-view observations.")
    else:
        phase, next_action = "complete", None
    return {"id": page["id"], "mapped": page.get("mapped") is True,
            "mapping_error": page.get("mapping_error"),
            "next_action": next_action,
            "phase": phase,
            "claim_status": "recorded" if invoked else ("pending" if claim_path.exists() else "unclaimed"),
            "claim_host_session_id": claim_session,
            "handoff_pending": claim_path.exists() and not invoked and claim_session != context["active_host_session_id"],
            "invocation_recorded": invoked, "crop_technical_pass": technical,
            "crop_available": bool(page.get("crops")), "all_crops_available": set(page.get("crops", {})) == expected,
            "available_crop_count": len(page.get("crops", {})), "crop_results": crop_results,
            "crop_errors": page.get("crop_errors", {}), "crop_attempts": page.get("crop_attempts", {}),
            "visual_review_recorded": visual_recorded, "visual_all_pass": visual_pass,
            "complete": invoked and technical and visual_pass and cross_pass, "view_count": len(expected),
            "host_trace_verified": False, "human_acceptance": False,
            "board": page.get("board"), "crops": page.get("crops", {}),
            "repair_views": repair_views,
            "missing_review_views": [{"asset_id": row["asset_id"], "view_id": row["view_id"]}
                                     for row in page["slots"] if identity_key(row["asset_id"], row["view_id"]) not in page.get("reviews", {})],
            "identity_continuity_verified": False,
            "cross_view_review_pass": cross_pass, "cross_view_reviews": cross_reviews,
            "identity_master_bound": any(row.get("role") == "identity_master" for row in page.get("input_roles", [])),
            "design_mode": "identity_conditioned" if any(row.get("role") == "identity_master" for row in page.get("input_roles", [])) else
                           ("joint_design_exploration" if len({row["asset_id"] for row in page["slots"]}) < len(page["slots"]) else "independent_asset_views"),
            "boundary": "Visual verdicts are recorded observations. Completion does not certify host execution, 3D usability or human acceptance."}


def status(workspace):
    workspace, project, state = _load(workspace)
    pages = []
    for page_id in state["pages"]:
        _, _, _, page_path, page = _load_page(workspace, page_id)
        pages.append(_page_status(project, page_path, page))
    return {"ok": True, "workspace": str(workspace), "scope_binding": state["scope_binding"],
            "active_host_session_id": _context(workspace, state)["active_host_session_id"],
            "human_approval": False, "preparation_status": state["preparation_status"], "pages": pages,
            "declared_view_count": len(state["scope"]["asset_views"]), "explicit_reused_views": len(state["aliases"]),
            "complete": state["preparation_status"] == "ready" and bool(pages) and all(row["complete"] for row in pages),
            "repair_views": [dict(row, page_id=page["id"]) for page in pages for row in page["repair_views"]],
            "identity_continuity_verified": False,
            "unbound_identity_views": state.get("unbound_identity_views", []),
            "cross_view_reviews": _cross_view_status(project, state),
            "host_trace_verified": False, "human_acceptance": False, "network": False, "submission": False,
            "last_error": state.get("last_error") if state["preparation_status"] != "ready" or any(not row["mapped"] for row in pages) else None,
            "next_action": state.get("next_action") if state["preparation_status"] != "ready" or any(not row["mapped"] for row in pages) else
                           next((row["next_action"] for row in pages if row.get("next_action")), None),
            "boundary": "Declared upstream scope is hash-bound, not inferred approval. This command never submits image jobs."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "map", "status", "claim", "verify", "record", "crop", "review", "bind-session"):
        item = commands.add_parser(name)
        item.add_argument("--workspace", required=True)
        if name == "prepare":
            item.add_argument("--file", required=True)
            item.add_argument("--project", required=True)
        elif name not in {"status", "bind-session"}:
            item.add_argument("--page", required=True)
        if name == "map":
            item.add_argument("--binding", required=True)
        if name in {"verify", "record"}:
            item.add_argument("--arguments", required=True)
        if name == "record":
            item.add_argument("--image", required=True)
            item.add_argument("--source-ref", required=True)
            item.add_argument("--tool-result")
        if name in {"crop", "review"}:
            item.add_argument("--file", required=True)
        if name == "bind-session":
            item.add_argument("--session-id", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            project = Path(args.project).resolve()
            path = _path(args.file, project)
            result = prepare(core.read(path), project, args.workspace, request_path=path)
        elif args.command == "map":
            result = map_native(args.workspace, args.page, args.binding)
        elif args.command == "status":
            result = status(args.workspace)
        elif args.command == "claim":
            result = claim(args.workspace, args.page)
        elif args.command == "bind-session":
            result = bind_session(args.workspace, args.session_id)
        elif args.command == "verify":
            result = verify(args.workspace, args.page, core.read(args.arguments))
        elif args.command == "record":
            result = record(args.workspace, args.page, core.read(args.arguments), args.image, source_ref=args.source_ref,
                            tool_result=core.read(args.tool_result) if args.tool_result else None)
        elif args.command == "crop":
            result = crop(args.workspace, args.page, core.read(args.file))
        else:
            result = review(args.workspace, args.page, core.read(args.file))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(json.dumps({"ok": False, "error": str(error), "boundary": "Do not repeat an uncertain image invocation; recover the original page call."}, ensure_ascii=False), file=sys.stderr)
        return 2
