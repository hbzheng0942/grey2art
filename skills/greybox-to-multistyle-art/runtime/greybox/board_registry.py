"""Compile one asset/view registry into persistent production pages; no generation.

The registry is authored once. Scope, flattened views, descriptions and page
requests are derived, rather than separately reconstructed by the host agent.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import sys

from . import board_production as production, core, reference_boards as boards

PIXEL_FIELDS = ("min_subject_long_edge_px", "min_subject_short_edge_px",
                "critical_feature_fraction_of_short_edge", "min_feature_px")
VIEW_FIELDS = {"view_id", "role", "projected_aspect", "projected_dimensions",
               "simple_shape_validated", "requires_single", "single_exception",
               "requirements_source_ref", "model_source", *PIXEL_FIELDS}


def _text(value, message):
    core.require(production._concrete(value), message)
    return value


def _upstream_views(source):
    # The compiler adapts existing scope records; it never guesses view aliases
    # from an asset name, display label, or a count of requested views.
    if isinstance(source.get("asset_views"), list):
        return source["asset_views"]
    return production._source_views(source)


def flatten(registry):
    """Return views/descriptions derived from the same asset records."""
    core.require(isinstance(registry, dict) and registry.get("schema") == 1
                 and registry.get("kind") == "reference-board-registry",
                 "Expected reference-board-registry schema 1")
    _text(registry.get("source_ref"), "Registry needs its actual scope/decision source_ref; this is not human approval")
    assets = registry.get("assets")
    core.require(isinstance(assets, list) and assets, "Registry needs its complete assets list")
    defaults = registry.get("requirements", {})
    core.require(isinstance(defaults, dict) and not set(defaults) - {*PIXEL_FIELDS, "source_ref"},
                 "requirements may contain pixel minima and their source_ref")
    if defaults:
        _text(defaults.get("source_ref"), "Shared pixel requirements need their task basis source_ref")
    views, objects, seen = [], [], set()
    for asset in assets:
        core.require(isinstance(asset, dict) and core.safe_id(asset.get("asset_id")), "Registry asset needs a stable asset_id")
        core.require(asset["asset_id"] not in seen, "Registry repeats an asset_id")
        seen.add(asset["asset_id"])
        requested = asset.get("views")
        core.require(isinstance(requested, list) and requested, "Every registry asset needs explicit view_id/role objects")
        if "master_view_id" in asset:
            core.require(any(isinstance(view, dict) and view.get("view_id") == asset["master_view_id"] for view in requested),
                         "master_view_id must name one explicitly requested view")
        for view in requested:
            core.require(isinstance(view, dict) and not set(view) - VIEW_FIELDS,
                         "View contains unknown fields; put design/pose decisions on the asset")
            row = {key: copy.deepcopy(value) for key, value in defaults.items() if key in PIXEL_FIELDS}
            row.update(copy.deepcopy(view), asset_id=asset["asset_id"])
            boards._identity(row)
            boards._projected_aspect(row)
            boards._requirements(row)
            exception = row.get("single_exception")
            core.require(type(row.get("requires_single", False)) is bool, "requires_single must be boolean")
            if row.get("requires_single"):
                core.require(isinstance(exception, dict) and set(exception) == {"source_ref", "reason"},
                             "requires_single needs a sourced single_exception with a concrete reason")
                _text(exception.get("source_ref"), "Single exception needs its actual source_ref")
                _text(exception.get("reason"), "Single exception needs a concrete reason")
            else:
                core.require(exception is None, "single_exception is only valid with requires_single:true")
            subject = {key: copy.deepcopy(value) for key, value in asset.items() if key != "views"}
            subject.update(asset_id=row["asset_id"], view_id=row["view_id"], role=row["role"])
            # Use the existing category/pose/construction validator now, before
            # any derived files are written.
            objects.append(boards._description(subject, row))
            views.append(row)
    production._identity_rows(views, "Registry views", roles=True)
    return views, objects


def _validate_authority(registry, views, source):
    if source is None:
        core.require(registry.get("authority") == "registry",
                     "Provide a hash-bound upstream source, or explicitly use authority:registry for a new sourced scope")
        return
    core.require(registry.get("authority") in {None, "upstream"}, "Registry cannot replace a supplied upstream source")
    upstream = production._identity_rows(_upstream_views(source), "Upstream registry source")
    declared = production._identity_rows(views, "Registry views", roles=True)
    core.require(set(upstream) == set(declared), "Registry must cover exactly the upstream asset/views; omissions and additions are blocked")
    default_basis = registry.get("requirements", {}).get("source_ref")
    for identity, row in declared.items():
        previous = upstream[identity]
        core.require(previous.get("role", row["role"]) == row["role"], "Registry changes an upstream view orientation")
        basis = row.get("requirements_source_ref", default_basis)
        for field in PIXEL_FIELDS:
            if field in previous:
                if field in row and row[field] != previous[field]:
                    _text(basis, "Changing upstream pixel requirements needs an explicit requirements_source_ref")
                core.require(row.get(field, -1) >= previous[field] if field != "critical_feature_fraction_of_short_edge"
                             else row.get(field) == previous[field],
                             "Registry may not lower upstream pixel requirements or change their feature basis")
        if "requires_single" in previous:
            core.require(row.get("requires_single", False) == previous["requires_single"],
                         "Registry single exception differs from its upstream source; update the actual scope decision first")


def _write_immutable(path, value):
    if path.exists():
        core.require(path.is_file() and core.read(path) == value,
                     "Compiled registry inputs changed; use a new explicit workspace revision")
    else:
        core.write(path, value)


def _inputs(workspace):
    workspace = Path(workspace).resolve()
    return workspace.parent / (workspace.name + "-inputs")


def _load_compilation(workspace):
    workspace = Path(workspace).resolve()
    value = core.read(_inputs(workspace) / "compilation.json")
    core.require(value.get("schema") == 1 and value.get("kind") == "reference-board-registry-compilation"
                 and value.get("workspace") == str(workspace), "Expected this workspace's registry compilation")
    production._verify_files(value["frozen"])
    return value


def _start_exact(registry, project, workspace, *, registry_path, extra_frozen=None):
    """Compile immutable inputs and enter the existing production state machine."""
    project = Path(project).resolve()
    workspace = production._workspace(workspace, project)
    registry_path = production._path(registry_path, project)
    registry_raw = registry_path.read_bytes()
    core.require(json.loads(registry_raw) == registry, "Registry differs from its saved source")
    registry_ref = {"path": str(registry_path.relative_to(project)), "sha256": boards._sha(registry_raw)}
    core.require(not registry_path.is_relative_to(workspace), "Keep the authoritative registry outside the production workspace")
    views, objects = flatten(registry)
    source, source_path = None, None
    if registry.get("source") is not None:
        source_path, raw = boards._file(registry["source"], project, {})
        source = json.loads(raw)
        core.require(isinstance(source, dict), "Registry source must be a JSON object")
    _validate_authority(registry, views, source)
    ratio = registry.get("subject_fill_ratio", .65)
    core.require(type(ratio) in {int, float} and .3 <= ratio <= .9,
                 "subject_fill_ratio must be a planning assumption in 0.3..0.9")
    if "subject_fill_ratio" in registry:
        _text(registry.get("subject_fill_source_ref"), "An explicit subject_fill_ratio needs its planning/measurement source_ref")
    plan = {"schema": 1, "kind": "reference-board-plan-input",
            "channel_size": registry.get("channel_size"), "size_source_ref": registry.get("size_source_ref"),
            "views": views, "coherent_asset_groups": True, "subject_fill_ratio": ratio}
    # Validate actual supported canvas/requirements before persisting inputs.
    boards.plan(plan)
    prepared = {"schema": 1, "kind": "reference-board-prepare-input", "purpose": "modeling", "plan": plan,
                "objects": objects, "images": registry.get("images"),
                "capabilities": registry.get("capabilities"), "parameters": registry.get("parameters", {})}
    if "image_roles" in registry:
        prepared["image_roles"] = registry["image_roles"]
    compiled = _inputs(workspace)
    core.require(not core.inside(compiled, Path(__file__).resolve().parents[2]), "Installed Skill is read-only")
    scope = {"schema": 1, "kind": "reference-board-scope", "asset_views": views,
             "source_ref": registry["source_ref"], "registry": registry_ref}
    if source_path:
        scope["upstream"] = copy.deepcopy(registry["source"])
    files = {compiled / "scope.json": scope, compiled / "prepare.json": prepared}
    # Check *all* existing derived inputs before writing any changed attempt.
    for path, value in files.items():
        if path.exists():
            core.require(core.read(path) == value, "Compiled registry inputs changed; use a new explicit workspace revision")
    for path, value in files.items():
        _write_immutable(path, value)
    request = {"schema": 1, "kind": "reference-board-production-input",
               "host_session_id": registry.get("host_session_id"),
               "scope": {"source_ref": registry["source_ref"], "source": production._ref(compiled / "scope.json", project),
                         "asset_views": views},
               "prepare_spec": production._ref(compiled / "prepare.json", project),
               "forbidden_output_sha256": registry.get("forbidden_output_sha256", [])}
    if "native_binding" in registry:
        request["native_binding"] = registry["native_binding"]
    request_path = compiled / "production-request.json"
    _write_immutable(request_path, request)
    frozen = {str(registry_path): registry_ref["sha256"]}
    if source_path:
        frozen[str(source_path)] = registry["source"]["sha256"]
    production._verify_files(frozen)
    for path in [*files, request_path]:
        production._freeze(frozen, path)
    frozen.update(extra_frozen or {})
    production._verify_files(frozen)
    compilation = {"schema": 1, "kind": "reference-board-registry-compilation",
                   "workspace": str(workspace), "project": str(project),
                   "registry": registry_ref, "frozen": frozen,
                   "authority": "upstream" if source_path else "registry",
                   "view_count": len(views), "asset_count": len(registry["assets"]),
                   "subject_fill_ratio": ratio,
                   "subject_fill_basis": registry.get("subject_fill_source_ref", "Conservative planning assumption; not measured generation reliability")}
    _write_immutable(compiled / "compilation.json", compilation)
    production.prepare(request, project, workspace, request_path=request_path)
    # Keep actual source changes visible through the existing status/guard API,
    # not only through this convenience entry. Never alter a claim or dispatch.
    _, _, state = production._load(workspace)
    state["frozen"].update(frozen)
    production._freeze(state["frozen"], compiled / "compilation.json")
    core.write(workspace / "production.json", state)
    return _stage_jobs(workspace)


def _stage_jobs(workspace):
    """Read current page jobs; no claim, submission, crop or approval is created."""
    compilation = _load_compilation(workspace)
    workspace = Path(workspace).resolve()
    project = Path(compilation["project"])
    status = production.status(workspace)
    jobs = []
    prefix = [sys.executable, str(Path(__file__).resolve().parents[2] / "scripts" / "greybox.py")]
    for current in status["pages"]:
        page = core.read(workspace / "pages" / current["id"] / "state.json")
        request = core.read(production._path(page["request"]["path"], project))
        if not current["mapped"]:
            action = "map"
        elif current["claim_status"] == "pending":
            action = "recover_original_call"
        elif not current["invocation_recorded"]:
            action = "claim_then_invoke_exact_page"
        elif not current.get("crops"):
            action = "inspect_actual_board_and_crop"
        elif not current["crop_technical_pass"]:
            action = "inspect_failed_slots_and_repair_roi_or_report_image_defect"
        elif not current["visual_review_recorded"]:
            action = "inspect_each_crop_and_record_review"
        elif not current["complete"]:
            action = "resolve_recorded_visual_or_cross_view_failures"
        else:
            action = "complete"
        jobs.append({"id": current["id"], "slots": page["slots"], "request": page["request"],
                     "images": request["images"], "parameters": request["parameters"],
                     "prompt_file": str((workspace / "prepared" / current["id"]).with_suffix(".prompt.txt")),
                     "mapped": current["mapped"], "claim_status": current["claim_status"],
                     "next_action": action, "status": current})
    return {"ok": True, "workspace": str(workspace), "registry": compilation["registry"],
            "asset_count": compilation["asset_count"], "view_count": compilation["view_count"],
            "job_count": len(jobs), "jobs": jobs, "complete": status["complete"],
            "command_prefix": prefix, "production_status": status,
            "next_action": next((job for job in jobs if job["next_action"] != "complete"), None),
            "network": False, "submission": False, "human_acceptance": False,
            "boundary": "Prepared page jobs, not native generation or visual acceptance. Preserve pending original calls; never regenerate to recover a missing local record."}


def _workflow_dir(root):
    root = Path(root).resolve()
    return root.parent / (root.name + "-workflow")


def _lineage_path(workspace):
    return _inputs(workspace) / "lineage.json"


def _child_workspace(root):
    root = Path(root).resolve()
    return root.parent / (root.name + "-stage-002")


def _identity_list(rows):
    return [{"asset_id": row["asset_id"], "view_id": row["view_id"], "role": row["role"]} for row in rows]


def _workflow(workspace):
    workspace = Path(workspace).resolve()
    lineage = core.read(_lineage_path(workspace))
    core.require(lineage.get("schema") == 1 and lineage.get("kind") == "reference-board-stage-lineage"
                 and lineage.get("workspace") == str(workspace), "Invalid board stage lineage")
    project = Path(lineage["project"]).resolve()
    root = production._workspace(lineage["workflow_root"], project)
    expected = _workflow_dir(root) / "workflow.json"
    meta_path, raw = boards._file(lineage["workflow"], project, {})
    core.require(meta_path == expected, "Stage workflow reference escaped its declared workflow")
    meta = json.loads(raw)
    core.require(meta.get("schema") == 1 and meta.get("kind") == "reference-board-staged-workflow"
                 and meta.get("workflow_root") == str(root) and meta.get("project") == str(project),
                 "Invalid complete-scope workflow record")
    production._verify_files(meta["frozen"])
    if lineage["stage_index"] == 1:
        core.require(workspace == root and lineage["registry"] == meta["initial_registry"], "Initial stage lineage changed")
    else:
        core.require(lineage["stage_index"] == 2 and workspace == _child_workspace(root), "Unknown derived board stage")
        receipt_path, receipt_raw = boards._file(lineage["advancement"], project, {})
        receipt = json.loads(receipt_raw)
        core.require(receipt_path.parent == _workflow_dir(root) / "advances"
                     and receipt.get("workflow_root") == str(root) and receipt.get("child_workspace") == str(workspace)
                     and receipt.get("registry") == lineage["registry"], "Derived stage advancement changed")
        production._verify_files(receipt["frozen"])
        for master in receipt["source_masters"]:
            core.require(_current_master_matches(root, master),
                         "Advanced identity master is no longer the current qualified/reviewed source. Preserve this child, every original call and the remaining shared budget. Automatic advancement rebuilding is not supported; report the source change and resume through an explicitly revised registry/workspace without deleting claims: " + master["asset_id"])
        index = core.read(_workflow_dir(root) / "advancement.json")
        core.require(index.get("advancement") == lineage["advancement"], "Derived stage lost its registered advancement")
    boards._file(lineage["registry"], project, {})
    return root, project, meta, lineage


def workflow_root(workspace):
    """Resolve a verified workflow root, retaining legacy single-stage runs."""
    workspace = Path(workspace).resolve()
    if not _lineage_path(workspace).is_file():
        _load_compilation(workspace)
        return workspace
    return _workflow(workspace)[0]


def workflow_workspaces(workspace):
    """Verified stage enumeration for shared spending ceilings and recovery."""
    root = workflow_root(workspace)
    if not _lineage_path(root).is_file():
        return [root]
    _, project, meta, _ = _workflow(root)
    index_path = _workflow_dir(root) / "advancement.json"
    child = _child_workspace(root)
    if not index_path.is_file():
        core.require(not child.exists() and not _lineage_path(child).exists(), "Derived stage exists without its advancement record")
        return [root]
    index = core.read(index_path)
    receipt_path, raw = boards._file(index.get("advancement"), project, {})
    receipt = json.loads(raw)
    core.require(receipt.get("kind") == "reference-board-stage-advancement"
                 and receipt.get("workflow_root") == str(root)
                 and receipt.get("child_workspace") == str(child), "Invalid workflow advancement index")
    _workflow(child)
    return [root, child]


def _lineage_frozen(workspace):
    root, _, meta, lineage = _workflow(workspace)
    frozen = dict(meta["frozen"])
    for path in (_lineage_path(workspace), _workflow_dir(root) / "workflow.json"):
        production._freeze(frozen, path)
    if lineage["stage_index"] == 2:
        _, project, _, _ = _workflow(workspace)
        path = production._path(lineage["advancement"]["path"], project)
        frozen.update(core.read(path)["frozen"])
        production._freeze(frozen, path)
        production._freeze(frozen, _workflow_dir(root) / "advancement.json")
    return frozen


def _full_input(registry, project, registry_path):
    raw = registry_path.read_bytes()
    core.require(json.loads(raw) == registry, "Registry differs from its saved source")
    views, objects = flatten(registry)
    source, frozen = None, {str(registry_path): boards._sha(raw)}
    if registry.get("source"):
        path, raw = boards._file(registry["source"], project, {})
        source = json.loads(raw)
        core.require(isinstance(source, dict), "Registry upstream source must be a JSON object")
        frozen[str(path)] = registry["source"]["sha256"]
    _validate_authority(registry, views, source)
    return views, objects, frozen


def _optional_guide(registry):
    result = copy.deepcopy(registry)
    core.require(isinstance(result.get("capabilities"), dict) and result["capabilities"].get("edit") is True
                 and type(result["capabilities"].get("max_references")) is int and result["capabilities"]["max_references"] > 0,
                 "Declare the actual image-conditioned edit capability and reference capacity")
    core.require(isinstance(result.get("images"), list) and result["images"], "Registry requires actual style/master input images")
    roles = result.get("image_roles", [{"role": "style"} for _ in result.get("images", [])])
    core.require(isinstance(roles, list) and len(roles) == len(result["images"])
                 and all(isinstance(role, dict) and role.get("role") in {"style", "identity_master", "design_master"} for role in roles),
                 "Registry image_roles must match its actual ordered images")
    maximum = result["capabilities"]["max_references"]
    styles = sum(role.get("role") == "style" for role in roles)
    masters = any(role.get("role") in {"identity_master", "design_master"} for role in roles)
    adjustments = []
    if result["capabilities"].get("layout_guide", True) and styles + int(masters) + 1 > maximum:
        core.require(styles + int(masters) <= maximum,
                     "Required style and identity-master inputs exceed the channel; no reference can be dropped")
        result["capabilities"]["layout_guide"] = False
        adjustments.append({"kind": "omit_optional_layout_guide", "reason": "Preserve every required style/master within actual reference capacity",
                            "max_references": maximum, "style_images_preserved": styles})
    if adjustments:
        result.setdefault("stage_adjustments", []).extend(adjustments)
    return result


def _dependent_assets(registry, views, objects):
    plan = {"schema": 1, "kind": "reference-board-plan-input", "channel_size": registry.get("channel_size"),
            "size_source_ref": registry.get("size_source_ref"), "views": views,
            "coherent_asset_groups": True, "subject_fill_ratio": registry.get("subject_fill_ratio", .65)}
    effective, aliases, _ = boards._deduplicate(plan, {boards._identity(row): row for row in objects})
    layout = boards.plan(effective)
    core.require(not layout["unresolved"], "Complete registry contains unsupported subject/detail requirements; preserve the named unresolved views")
    roles = registry.get("image_roles", [{"role": "style"} for _ in registry.get("images", [])])
    boards._reference_budget_layout(layout, {boards._identity(row): row for row in effective["views"]}, aliases,
                                    roles, registry["capabilities"]["max_references"], registry["capabilities"].get("layout_guide", True))
    core.require(not layout["unresolved"], "Complete registry has unresolved reference capacity; preserve every required input")
    pages = {}
    for page in layout["boards"]:
        for slot in page["slots"]:
            pages.setdefault(slot["asset_id"], set()).add(page["id"])
    masters = {(role["asset_id"], view) for role in roles if role.get("role") == "identity_master"
               for view in role["target_view_ids"]}
    dependencies = []
    for asset in registry["assets"]:
        selected = [row for row in views if row["asset_id"] == asset["asset_id"]]
        if len(pages.get(asset["asset_id"], [])) <= 1 or all(boards._identity(row) in masters for row in selected):
            continue
        master_id = asset.get("master_view_id", selected[0]["view_id"])
        core.require(any(row["view_id"] == master_id for row in selected), "master_view_id must name one explicitly requested asset view")
        master = next(row for row in selected if row["view_id"] == master_id)
        dependencies.append({"asset_id": asset["asset_id"], "master_view_id": master_id, "role": master["role"],
                             "selection_basis": "Explicit asset.master_view_id" if "master_view_id" in asset else "First view in the original declared asset view order",
                             "target_view_ids": [row["view_id"] for row in selected if row["view_id"] != master_id],
                             "shared_aliases": [copy.deepcopy(row) for row in aliases if row["source_asset_id"] == asset["asset_id"]]})
    return dependencies


def _subset_registry(full, identities, scope_ref):
    result = copy.deepcopy(full)
    result.pop("authority", None)
    result["source"] = scope_ref
    result["assets"] = []
    for asset in full["assets"]:
        views = [copy.deepcopy(view) for view in asset["views"] if (asset["asset_id"], view["view_id"]) in identities]
        if views:
            item = copy.deepcopy(asset)
            item["views"] = views
            if item.get("master_view_id") not in {view["view_id"] for view in views}:
                item.pop("master_view_id", None)
            result["assets"].append(item)
    images, roles = [], []
    for image, role in zip(full.get("images", []), full.get("image_roles", [{"role": "style"} for _ in full.get("images", [])])):
        role = copy.deepcopy(role)
        if role["role"] == "design_master" and (role["asset_id"], role["view_id"]) not in identities:
            continue
        if role["role"] == "identity_master":
            role["target_view_ids"] = [view for view in role["target_view_ids"] if (role["asset_id"], view) in identities]
            if not role["target_view_ids"]:
                continue
        images.append(copy.deepcopy(image))
        roles.append(role)
    result["images"], result["image_roles"] = images, roles
    return result


def start(registry, project, workspace, *, registry_path):
    """Compile immediately executable pages, staging missing identity masters."""
    project = Path(project).resolve()
    workspace = production._workspace(workspace, project)
    registry_path = production._path(registry_path, project)
    if _lineage_path(workspace).is_file():
        root, _, meta, lineage = _workflow(workspace)
        reference = production._ref(registry_path, project)
        core.require(reference in (lineage["registry"], meta["full_registry"] if workspace == root else lineage["registry"]),
                     "Resume this stage with its original complete or derived registry")
        if reference == lineage["registry"]:
            _start_exact(registry, project, workspace, registry_path=registry_path, extra_frozen=_lineage_frozen(workspace))
        return next_jobs(workspace)
    views, objects, frozen = _full_input(registry, project, registry_path)
    effective = _optional_guide(registry)
    dependencies = _dependent_assets(effective, views, objects)
    if not dependencies:
        if effective != registry:
            effective_path = _inputs(workspace) / "effective-registry.json"
            _write_immutable(effective_path, effective)
            return _plain_result(_start_exact(effective, project, workspace, registry_path=effective_path, extra_frozen=frozen))
        return _plain_result(_start_exact(registry, project, workspace, registry_path=registry_path))
    selected_masters = {(row["asset_id"], row["master_view_id"]) for row in dependencies}
    dependent_ids = {row["asset_id"] for row in dependencies}
    aliases = {(row["asset_id"], row["view_id"]): (row["source_asset_id"], row["source_view_id"])
               for dependency in dependencies for row in dependency["shared_aliases"]}
    initial = [row for row in views if (aliases.get(boards._identity(row), boards._identity(row))[0] not in dependent_ids
                                       or aliases.get(boards._identity(row), boards._identity(row)) in selected_masters)]
    deferred = [row for row in views if boards._identity(row) not in {boards._identity(item) for item in initial}]
    directory = _workflow_dir(workspace)
    scope_path, initial_path = directory / "stage-001-scope.json", directory / "stage-001-registry.json"
    scope = {"schema": 1, "kind": "reference-board-scope", "asset_views": initial,
             "full_registry": production._ref(registry_path, project), "source_ref": registry["source_ref"]}
    _write_immutable(scope_path, scope)
    first = _subset_registry(effective, {boards._identity(row) for row in initial}, production._ref(scope_path, project))
    _write_immutable(initial_path, first)
    meta = {"schema": 1, "kind": "reference-board-staged-workflow", "workflow_root": str(workspace), "project": str(project),
            "full_registry": production._ref(registry_path, project), "frozen": frozen,
            "full_scope": _identity_list(views), "initial_scope": _identity_list(initial), "deferred_scope": _identity_list(deferred),
            "dependencies": dependencies, "initial_registry": production._ref(initial_path, project),
            "stage_adjustments": effective.get("stage_adjustments", []),
            "boundary": "Initial-stage completion is not complete-scope or multiview acceptance. Deferred views retain their original requirements."}
    meta_path = directory / "workflow.json"
    _write_immutable(meta_path, meta)
    lineage = {"schema": 1, "kind": "reference-board-stage-lineage", "workflow_root": str(workspace),
               "workspace": str(workspace), "project": str(project), "stage_index": 1,
               "registry": meta["initial_registry"], "workflow": production._ref(meta_path, project)}
    _write_immutable(_lineage_path(workspace), lineage)
    _start_exact(first, project, workspace, registry_path=initial_path, extra_frozen=_lineage_frozen(workspace))
    return next_jobs(workspace)


def _plain_result(result):
    _, _, state = production._load(result["workspace"])
    scope = _identity_list(state["scope"]["asset_views"])
    grouped = {}
    for row in scope:
        grouped.setdefault(row["asset_id"], set()).add(row["view_id"])
    return dict(result, workflow_root=result["workspace"], current_workspace=result["workspace"], stage_workspace=result["workspace"],
                stage_complete=result["complete"], full_scope=scope, deferred_views=[],
                full_scope_view_count=len(scope), prepared_view_count=len(scope),
                workflow_workspaces=[result["workspace"]], workflow_cross_view_status="covered_by_stage_production" if any(len(ids) > 1 for ids in grouped.values()) else "not_applicable")


def _qualified_master(workspace, asset_id, view_id):
    _, project, state = production._load(workspace)
    for page_id in state["pages"]:
        _, _, _, page_path, page = production._load_page(workspace, page_id)
        if not any(slot["asset_id"] == asset_id and slot["view_id"] == view_id for slot in page["slots"]):
            continue
        key = production.identity_key(asset_id, view_id)
        ref = page.get("crops", {}).get(key)
        if not ref or key in page.get("crop_errors", {}):
            return None, "Inspect/crop the source view and correct its recorded ROI or image defect."
        try:
            checked = boards.validate_crop_receipt(ref, project, asset_id=asset_id, view_id=view_id)
        except (ValueError, OSError) as error:
            return None, str(error)
        review = page.get("reviews", {}).get(key)
        if not review or review.get("verdict") != "pass" or review.get("status", "pass") != "pass" or review.get("image") != checked["output"]:
            return None, "Inspect the exact technically qualified source crop and record its visible per-view pass."
        # Full status verifies the stored review's immutable evidence and hash.
        production._page_status(project, page_path, page)
        return {"image": checked["output"], "board_crop_receipt": ref, "visual_review": review,
                "visual_review_file": page["review_ref"]}, None
    return None, "The original master view has no prepared page."


def _current_master_matches(workspace, master):
    """Recheck current pointers/hashes without pixel replay inside a host hook.

    Advancement already performed strict pixel replay and freezes that exact
    receipt, image and review. Equality to those immutable proofs is sufficient
    for subsequent dispatch checks; changed bytes are rejected by _load_page.
    """
    _, _, state = production._load(workspace)
    for page_id in state["pages"]:
        _, _, _, _, page = production._load_page(workspace, page_id)
        key = production.identity_key(master["asset_id"], master["master_view_id"])
        if key in page.get("crops", {}):
            return (not page.get("crop_errors", {}).get(key)
                    and page["crops"][key] == master["board_crop_receipt"]
                    and page.get("reviews", {}).get(key) == master["visual_review"])
    return False


def advance(workspace):
    """Compile deferred views from real qualified masters; never generates."""
    root = workflow_root(workspace)
    if not _lineage_path(root).exists():
        result = next_jobs(root)
        return dict(result, advanced=False, next_action=result["next_action"] or {"action": "no_deferred_views"})
    _, project, meta, _ = _workflow(root)
    directory = _workflow_dir(root)
    with core.locked(directory):
        index_path = directory / "advancement.json"
        if index_path.exists():
            _, raw = boards._file(core.read(index_path)["advancement"], project, {})
            receipt = json.loads(raw)
            child = Path(receipt["child_workspace"])
            child_registry = core.read(production._path(receipt["registry"]["path"], project))
            _start_exact(child_registry, project, child, registry_path=production._path(receipt["registry"]["path"], project),
                         extra_frozen=_lineage_frozen(child))
            return dict(next_jobs(child), advanced=True, created_workspace=str(child), child_registry=receipt["registry"])
        sources, waiting = {}, []
        for dependency in meta["dependencies"]:
            source, reason = _qualified_master(root, dependency["asset_id"], dependency["master_view_id"])
            if source is None:
                waiting.append(dict(dependency, next_action=reason))
            else:
                sources[dependency["asset_id"]] = source
        if waiting:
            return dict(next_jobs(root), advanced=False, waiting_for_masters=waiting,
                        next_action={"action": "wait_for_qualified_identity_master", "views": waiting,
                                     "command": ["boards", "advance", "--workspace", str(root)]})
        _, raw = boards._file(meta["full_registry"], project, {})
        full = json.loads(raw)
        views, _ = flatten(full)
        selected = {(row["asset_id"], row["view_id"]) for row in meta["deferred_scope"]}
        deferred = [row for row in views if boards._identity(row) in selected]
        scope_path, registry_path = directory / "stage-002-scope.json", directory / "stage-002-registry.json"
        scope = {"schema": 1, "kind": "reference-board-scope", "asset_views": deferred,
                 "full_registry": meta["full_registry"], "source_ref": full["source_ref"]}
        _write_immutable(scope_path, scope)
        child_registry = _subset_registry(full, selected, production._ref(scope_path, project))
        frozen = dict(meta["frozen"])
        master_records = []
        for dependency in meta["dependencies"]:
            asset = dependency["asset_id"]
            source = sources[asset]
            review = {"schema": 1, "kind": "reference-board-identity-source-review", "asset_id": asset,
                      "view_id": dependency["master_view_id"], "image_sha256": source["image"]["sha256"],
                      "verdict": "pass", "observation": source["visual_review"]["observation"],
                      "source_ref": source["visual_review"]["inspection_source_ref"],
                      "board_crop_receipt": source["board_crop_receipt"], "visual_review_file": source["visual_review_file"]}
            review_path = directory / "identity-sources" / (asset + "-" + core.digest(review) + ".json")
            _write_immutable(review_path, review)
            reference = production._ref(review_path, project)
            child_registry["images"].append(source["image"])
            child_registry["image_roles"].append({"role": "identity_master", "asset_id": asset,
                                                  "source_view_id": dependency["master_view_id"],
                                                  "target_view_ids": dependency["target_view_ids"], "source_review": reference})
            record = dict(dependency, image=source["image"], source_review=reference,
                          board_crop_receipt=source["board_crop_receipt"], visual_review_file=source["visual_review_file"],
                          visual_review=source["visual_review"])
            master_records.append(record)
            for ref in (source["image"], source["board_crop_receipt"], source["visual_review_file"], reference):
                path = production._path(ref["path"], project)
                core.require(core.file_hash(path) == ref["sha256"], "Qualified master evidence changed during advancement")
                frozen[str(path)] = ref["sha256"]
        child_registry = _optional_guide(child_registry)
        _write_immutable(registry_path, child_registry)
        for path in (scope_path, registry_path):
            production._freeze(frozen, path)
        child = _child_workspace(root)
        receipt = {"schema": 1, "kind": "reference-board-stage-advancement", "workflow_root": str(root),
                   "parent_workspace": str(root), "child_workspace": str(child), "registry": production._ref(registry_path, project),
                   "source_masters": master_records, "target_scope": meta["deferred_scope"], "frozen": frozen,
                   "stage_adjustments": child_registry.get("stage_adjustments", []),
                   "boundary": "Only deferred original views are prepared; all generation claims and the shared budget remain separate."}
        receipt_path = directory / "advances" / (core.digest(receipt) + ".json")
        _write_immutable(receipt_path, receipt)
        index = {"schema": 1, "kind": "reference-board-advancement-index", "advancement": production._ref(receipt_path, project)}
        _write_immutable(index_path, index)
        lineage = {"schema": 1, "kind": "reference-board-stage-lineage", "workflow_root": str(root), "workspace": str(child),
                   "project": str(project), "stage_index": 2, "registry": receipt["registry"],
                   "workflow": production._ref(directory / "workflow.json", project), "advancement": index["advancement"]}
        _write_immutable(_lineage_path(child), lineage)
        _start_exact(child_registry, project, child, registry_path=registry_path, extra_frozen=_lineage_frozen(child))
        return dict(next_jobs(child), advanced=True, created_workspace=str(child), child_registry=receipt["registry"])


def _workflow_images(root, meta):
    result = {}
    stages = workflow_workspaces(root)
    for workspace in stages:
        _, project, state = production._load(workspace)
        for page_id in state["pages"]:
            _, _, _, page_path, page = production._load_page(workspace, page_id)
            status = production._page_status(project, page_path, page)
            outcomes = {(row["asset_id"], row["view_id"]): row for row in status.get("crop_results", [])}
            for slot in page["slots"]:
                identity = boards._identity(slot)
                core.require(identity not in result, "A workflow repeats a generated original asset/view across stages")
                key = production.identity_key(*identity)
                ref = page.get("crops", {}).get(key)
                image, technical = None, False
                if ref:
                    checked = boards.validate_crop_receipt(ref, project, require_qualified=False)
                    image, technical = checked["output"], checked["technical_pass"] and not page.get("crop_errors", {}).get(key)
                result[identity] = {"asset_id": identity[0], "view_id": identity[1], "role": slot["role"],
                                    "image": image, "technical_pass": technical, "workspace": str(workspace)}
        for alias in state.get("aliases", []):
            source = result.get((alias["source_asset_id"], alias["source_view_id"]))
            if source:
                result[(alias["asset_id"], alias["view_id"])] = dict(source, asset_id=alias["asset_id"], view_id=alias["view_id"])
    return result


def _workflow_comparisons(root, meta, images):
    grouped = {}
    for row in meta["full_scope"]:
        grouped.setdefault(row["asset_id"], []).append(row)
    selected_path = _workflow_dir(root) / "cross-view-selection.json"
    selected = core.read(selected_path) if selected_path.exists() else {}
    rows = []
    project = Path(meta["project"])
    for asset, views in grouped.items():
        if len(views) < 2:
            continue
        required = [{"view_id": row["view_id"], "image": images.get((asset, row["view_id"]), {}).get("image")} for row in views]
        ready = all(row["image"] and images[(asset, row["view_id"])]["technical_pass"] for row in required)
        item = {"asset_id": asset, "required_images": required, "technical_ready": ready, "recorded": False, "verdict": None}
        reference = selected.get(asset)
        if reference:
            _, raw = boards._file(reference, project, {})
            review = json.loads(raw)
            core.require(review.get("asset_id") == asset and review.get("kind") == "reference-board-workflow-cross-view-review",
                         "Workflow comparison selection changed")
            if review.get("images") == required:
                item.update(recorded=True, verdict=review["verdict"], observation=review["observation"], review=reference)
        item["pass"] = ready and item["recorded"] and item["verdict"] == "pass"
        rows.append(item)
    return rows


def next_jobs(workspace):
    """Report stage work and complete original scope without hiding deferrals."""
    workspace = Path(workspace).resolve()
    if not _lineage_path(workspace).is_file():
        return _plain_result(_stage_jobs(workspace))
    root, _, meta, _ = _workflow(workspace)
    stages = workflow_workspaces(root)
    outputs = [_stage_jobs(stage) for stage in stages]
    current = next((row for row in outputs if not row["complete"]), outputs[-1])
    requested = next(row for row in outputs if row["workspace"] == str(workspace))
    images = _workflow_images(root, meta)
    comparisons = _workflow_comparisons(root, meta, images)
    prepared = {boards._identity(slot) for output in outputs for job in output["jobs"] for slot in job["slots"]}
    for stage in stages:
        _, _, state = production._load(stage)
        prepared.update((row["asset_id"], row["view_id"]) for row in state.get("aliases", []))
    full = {(row["asset_id"], row["view_id"]) for row in meta["full_scope"]}
    deferred = [dict(row, prepared=(row["asset_id"], row["view_id"]) in prepared) for row in meta["deferred_scope"]]
    complete = prepared == full and all(row["complete"] for row in outputs) and all(row["pass"] for row in comparisons)
    next_action = requested["next_action"]
    if requested["complete"] and len(stages) == 1:
        next_action = {"action": "advance_qualified_masters", "workspace": str(root), "command": ["boards", "advance", "--workspace", str(root)]}
    elif requested["complete"] and not current["complete"]:
        child_lineage = core.read(_lineage_path(current["workspace"]))
        next_action = {"action": "continue_original_scope_stage", "workspace": current["workspace"], "registry": child_lineage["registry"]}
    elif all(row["complete"] for row in outputs) and prepared == full and not all(row["pass"] for row in comparisons):
        next_action = {"action": "compare_all_original_asset_views", "workspace": str(root),
                       "command": ["boards", "compare", "--workspace", str(root), "--file", "ACTUAL_WORKFLOW_COMPARISONS.json"]}
    return dict(requested, complete=complete, stage_complete=requested["complete"], workflow_root=str(root),
                current_workspace=current["workspace"], stage_workspace=str(workspace), full_scope=meta["full_scope"],
                full_scope_view_count=len(full), prepared_view_count=len(prepared), deferred_views=deferred,
                master_dependencies=meta["dependencies"], workflow_workspaces=[str(path) for path in stages],
                stages=[{"workspace": row["workspace"], "stage_complete": row["complete"], "view_count": row["view_count"]} for row in outputs],
                workflow_cross_view_status="not_applicable" if not comparisons else "pass" if all(row["pass"] for row in comparisons) else "pending_or_failed",
                workflow_cross_view_reviews=comparisons, next_action=next_action)


def compare(workspace, reviews):
    """Record an explicit full-asset comparison including source and targets."""
    root, project, meta, _ = _workflow(workspace)
    rows = reviews.get("cross_view_reviews", []) if isinstance(reviews, dict) else reviews
    core.require(isinstance(rows, list) and rows, "Provide workflow cross_view_reviews with exact images")
    expected = {row["asset_id"]: row for row in _workflow_comparisons(root, meta, _workflow_images(root, meta))}
    validated = {}
    for row in rows:
        core.require(isinstance(row, dict) and row.get("asset_id") in expected and row["asset_id"] not in validated,
                     "Workflow review needs one distinct original multiview asset")
        asset = row["asset_id"]
        wanted = expected[asset]
        core.require(row.get("images") == wanted["required_images"] and all(item["image"] for item in wanted["required_images"]),
                     "Workflow comparison must bind every exact current source and target view image")
        core.require(row.get("verdict") in {"pass", "fail", "unclear"} and production._concrete(row.get("observation"))
                     and len(row["observation"].strip()) >= 12 and production._concrete(row.get("source_ref")),
                     "Workflow comparison needs a visible observation, verdict and actual inspection source")
        core.require(row["verdict"] != "pass" or wanted["technical_ready"], "Workflow multiview pass requires qualified source and target crops")
        validated[asset] = dict(row, schema=1, kind="reference-board-workflow-cross-view-review")
    directory = _workflow_dir(root)
    with core.locked(directory):
        path = directory / "cross-view-selection.json"
        selected = core.read(path) if path.exists() else {}
        for asset, document in validated.items():
            destination = directory / "comparisons" / (asset + "-" + core.digest(document) + ".json")
            _write_immutable(destination, document)
            selected[asset] = production._ref(destination, project)
        core.write(path, selected)
    return next_jobs(workspace)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    commands = parser.add_subparsers(dest="command", required=True)
    item = commands.add_parser("start", allow_abbrev=False)
    item.add_argument("--file", required=True)
    item.add_argument("--project", required=True)
    item.add_argument("--workspace", required=True)
    for name in ("next", "status", "advance", "compare"):
        item = commands.add_parser(name, allow_abbrev=False)
        item.add_argument("--workspace", required=True)
        if name == "compare":
            item.add_argument("--file", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "start":
            path = production._path(args.file, Path(args.project).resolve())
            result = start(core.read(path), args.project, args.workspace, registry_path=path)
        elif args.command == "advance":
            result = advance(args.workspace)
        elif args.command == "compare":
            result = compare(args.workspace, core.read(args.file))
        else:
            result = next_jobs(args.workspace)
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(json.dumps({"ok": False, "error": str(error),
                          "boundary": "Preserve the original registry, pages and pending image calls. Correct input with an explicit revision; preparation never generates images."}, ensure_ascii=True), file=sys.stderr)
        return 2
