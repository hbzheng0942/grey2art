"""Case/style ownership, stable resource locations and version-bound navigation.

This module creates only small manifests.  It never migrates, copies or deletes
existing projects/assets, and a navigation pointer never grants human approval.
"""
from __future__ import annotations

import copy
from pathlib import Path, PurePosixPath
import re

from . import core

POINTERS = ("development", "last_verified", "user_accepted")
TRANSIENT = {"downloads", "experiments", "archive", "archives", "scratch", "staging", "draft", "drafts"}
STYLE_ROLES = {"concept": "concepts", "design": "design", "reference": "references",
               "runtime": "runtime", "dcc": "dcc", "plan": "production/plans", "evidence": "production/runs"}


def is_workspace(plan):
    return isinstance(plan, dict) and isinstance(plan.get("workspace"), dict)


def _relative(value, label):
    core.require(isinstance(value, str) and value and "\\" not in value,
                 label + " must be a canonical project-relative POSIX path")
    p = PurePosixPath(value)
    core.require(not p.is_absolute() and value == p.as_posix()
                 and all(part not in (".", "..", "") for part in p.parts)
                 and not value.startswith("res://") and ":" not in value,
                 label + " must be a canonical project-relative POSIX path")
    return value


def style_ids(plan):
    values = plan.get("styles", plan.get("selected_styles", []))
    core.require(isinstance(values, list), "Workspace styles must be a list")
    ids = [row.get("id", row.get("style_id")) if isinstance(row, dict) else row for row in values]
    core.require(all(core.safe_id(sid) for sid in ids) and len(ids) == len(set(ids)),
                 "Workspace styles need unique stable IDs")
    return ids


def owner(value, allow_shared=True):
    core.require(isinstance(value, dict), "Declare artifact ownership as style or shared")
    scope = value.get("scope")
    core.require(scope in (("style", "shared") if allow_shared else ("style",)), "Invalid ownership scope")
    if scope == "style":
        core.require(core.safe_id(value.get("style_id")), "Style ownership requires style_id")
        core.require(set(value) <= {"scope", "style_id"}, "Unknown ownership fields")
        return {"scope": "style", "style_id": value["style_id"]}
    core.require(set(value) == {"scope"}, "Shared ownership must not carry a style_id")
    return {"scope": "shared"}


def normalize_workspace(plan, required=False):
    value = plan.get("workspace")
    if value is None:
        core.require(not required, "R3.3 production requires plan.workspace; inventory existing projects before migration")
        return None
    core.require(isinstance(value, dict) and value.get("schema") == 1, "Expected workspace schema 1")
    core.require(core.safe_id(value.get("case_id")), "Workspace needs a stable case_id")
    root = _relative(value.get("root", "art/" + value["case_id"]), "workspace.root")
    core.require(root == "art/" + value["case_id"], "Workspace root must be art/<case_id>")
    engine = value.get("engine", "godot")
    core.require(engine in ("godot", "unity", "blender", "threejs"), "Unsupported workspace engine mapping")
    defaults = {"unity": ("Assets/Art/" + value["case_id"], "Assets/Art/" + value["case_id"]),
                "threejs": ("public/art/" + value["case_id"], "src/art/" + value["case_id"])}
    default_resource, default_code = defaults.get(engine, (root, root))
    resource_root = _relative(value.get("resource_root", default_resource), "workspace.resource_root")
    code_root = _relative(value.get("code_root", default_code), "workspace.code_root")
    for path, role in ((resource_root, "resource_root"), (code_root, "code_root")):
        core.require(PurePosixPath(path).name == value["case_id"], "Engine mapping must end in its owning case_id")
        if engine == "unity":
            core.require(path.startswith("Assets/") and len(PurePosixPath(path).parts) >= 3,
                         "Unity " + role + " must be inside Assets/<case-group>/<case_id>")
        elif engine == "threejs":
            prefix = "public/" if role == "resource_root" else "src/"
            core.require(path.startswith(prefix) and len(PurePosixPath(path).parts) >= 3,
                         "Three.js " + role + " must be inside " + prefix + "<case-group>/<case_id>")
        else:
            core.require(path == root, "This adapter keeps code and resources inside the logical case root")
    shared = value.get("shared_asset_ids", [])
    core.require(isinstance(shared, list) and all(core.safe_id(a) for a in shared) and len(shared) == len(set(shared)),
                 "shared_asset_ids must contain unique asset IDs")
    owners = value.get("asset_owners", {})
    core.require(isinstance(owners, dict) and all(core.safe_id(a) for a in owners), "asset_owners must map stable asset IDs")
    sids = style_ids(plan)
    normalized = {}
    for aid, declaration in owners.items():
        normalized[aid] = owner(declaration)
    for asset in plan.get("assets", []):
        aid = asset.get("id", asset.get("asset_id"))
        core.require(core.safe_id(aid), "Workspace asset needs id/asset_id")
        if asset.get("ownership") is not None:
            declared = owner(asset["ownership"])
            core.require(aid not in normalized or normalized[aid] == declared, "Conflicting asset ownership declarations")
            normalized[aid] = declared
    for aid in shared:
        core.require(aid not in normalized or normalized[aid] == {"scope": "shared"}, "Shared asset conflicts with style ownership")
        normalized[aid] = {"scope": "shared"}
    for declared in normalized.values():
        core.require(declared["scope"] == "shared" or declared["style_id"] in sids, "Asset owner is not a declared style")
    result = copy.deepcopy(value)
    result.update(schema=1, root=root, engine=engine, resource_root=resource_root, code_root=code_root,
                  shared_asset_ids=sorted(shared), asset_owners=normalized)
    if engine == "unity":
        engine_tools = _relative(value.get("engine_tool_root", "Assets/GreyboxArtRuntime"), "workspace.engine_tool_root")
        core.require(engine_tools == "Assets/GreyboxArtRuntime", "Unity bridge uses one canonical Assets/GreyboxArtRuntime tool root")
        result["engine_tool_root"] = engine_tools
    return result


def workspace(plan, project=None):
    result = normalize_workspace(plan, required=True)
    if project is not None:
        _safe_project_path(project, result["root"])
        _safe_project_path(project, result["resource_root"])
        _safe_project_path(project, result["code_root"])
    return result


def _safe_project_path(project, relative):
    project = Path(project).resolve()
    p = project / _relative(relative, "Output path")
    return _owned_path(p, project)


def _owned_path(path, project):
    """Outputs cannot borrow another owner's path through an in-project link."""
    project_alias = Path(project).absolute()
    project_root = project_alias.resolve()
    lexical = Path(path).absolute()
    # The caller selected this project. Host aliases such as macOS /tmp are
    # part of that trusted prefix, while child aliases remain unnormalized.
    if lexical.is_relative_to(project_alias):
        lexical = project_root / lexical.relative_to(project_alias)
    resolved = lexical.resolve()
    core.require(core.inside(resolved, project_root), "Output path escapes project through a symlink")
    core.require(lexical == resolved, "Owned output path cannot be redirected through a symlink")
    return resolved


def roots(project, plan, style_id=None):
    config = workspace(plan, project)
    case = _safe_project_path(project, config["root"])
    resources = _safe_project_path(project, config["resource_root"])
    code = _safe_project_path(project, config["code_root"])
    result = {"case": case, "shared": case / "shared", "styles": case / "styles",
              "resource_case": resources, "code_case": code, "production": case / "shared/production",
              "runs": case / "shared/production/runs", "plans": case / "shared/production/plans",
              "assets": resources / "shared/assets",
              "baseline": case / "shared/baseline", "directions": case / "shared/directions",
              "tools": code / "shared/tools", "logical_tools": case / "shared/tools", "index": case / "index.json"}
    if config.get("engine_tool_root"):
        result["engine_tools"] = _safe_project_path(project, config["engine_tool_root"])
    if style_id is not None:
        core.require(style_id in style_ids(plan), "Unknown workspace style")
        style = case / "styles" / style_id
        result.update(style=style, resource_style=resources / "styles" / style_id, code_style=code / "styles" / style_id,
                      assets=resources / "styles" / style_id / "assets",
                      runtime=code / "styles" / style_id / "runtime", dcc=code / "styles" / style_id / "dcc",
                      production=style / "production", runs=style / "production/runs",
                      concepts=style / "concepts", design=style / "design", references=style / "references",
                      plans=style / "production/plans", metadata=style / "style.json")
    for p in result.values():
        _owned_path(p, project)
    return result


def case_root(project, plan):
    return roots(project, plan)["case"]


def style_root(project, plan, style_id):
    return roots(project, plan, style_id)["style"]


def runtime_root(project, plan, style_id):
    return roots(project, plan, style_id)["runtime"]


def run_root(project, plan, run_id, style_id=None):
    core.require(core.safe_id(run_id), "Invalid run ID")
    return _owned_path(roots(project, plan, style_id)["runs"] / run_id, project)


def asset_owner(plan, asset_id):
    core.require(core.safe_id(asset_id), "Invalid asset ID")
    config = workspace(plan)
    declared = config["asset_owners"].get(asset_id)
    core.require(declared is not None, "Every workspace asset requires explicit style/shared ownership: " + asset_id)
    return declared


def asset_path(project, plan, asset_id, style_id=None, filename="model.glb"):
    declared = asset_owner(plan, asset_id)
    expected = declared.get("style_id")
    core.require(style_id is None or style_id == expected, "Asset path style conflicts with its owner")
    filename = _relative(filename, "Asset filename")
    core.require("/" not in filename and filename not in ("asset.json", "style.json"), "Use a plain asset filename")
    return _owned_path(roots(project, plan, expected)["assets"] / asset_id / filename, project)


def validate_output(project, plan, path, role, style_id=None, asset_id=None):
    text = str(path)
    lexical = (Path(project).resolve() / text[6:]) if text.startswith("res://") else Path(text)
    if not lexical.is_absolute():
        lexical = Path(project).resolve() / lexical
    p = _owned_path(lexical, project)
    r = roots(project, plan, style_id)
    if role in ("asset", "model", "texture"):
        core.require(asset_id is not None, "Asset output needs asset_id")
        declared = asset_owner(plan, asset_id)
        core.require(declared.get("style_id") == style_id, "Asset output conflicts with its ownership")
        expected = roots(project, plan, style_id)["assets"] / asset_id
    elif role in ("run", "supplier-run"):
        expected = r["runs"]
    elif role in ("baseline", "direction", "tool"):
        core.require(style_id is None, "Shared content cannot carry style ownership")
        expected = r[{"baseline": "baseline", "direction": "directions", "tool": "tools"}[role]]
        if role == "tool" and r.get("engine_tools") and core.inside(p, r["engine_tools"]):
            expected = r["engine_tools"]
    elif role in STYLE_ROLES:
        core.require(style_id is not None or role == "plan", "Style-specific content needs style_id")
        key = {"concept": "concepts", "reference": "references", "plan": "plans",
               "evidence": "runs"}.get(role, role)
        expected = r[key]
        if role == "reference" and asset_id:
            core.require(core.safe_id(asset_id), "Invalid reference asset ID")
            expected = expected / asset_id
    else:
        raise core.WorkflowError("Unknown output role: " + str(role))
    core.require(p != expected.resolve() and core.inside(p, expected), "Output path does not match its declared case/style/asset role")
    return p


def record_artifact(project, plan, path, role, style_id=None, asset_id=None, provenance=None, write_manifest=False):
    p = validate_output(project, plan, path, role, style_id, asset_id)
    core.require(p.is_file() and not p.is_symlink(), "Artifact must be an existing regular owned file")
    row = {"path": str(p), "sha256": core.file_hash(p), "case_id": workspace(plan)["case_id"],
           "style_id": style_id, "asset_id": asset_id, "role": role,
           "ownership": {"scope": "style", "style_id": style_id} if style_id else {"scope": "shared"}}
    if provenance is not None:
        row["provenance"] = copy.deepcopy(provenance)
    if write_manifest:
        core.require(role in ("asset", "model", "texture") and asset_id, "Only stable assets have asset manifests")
        root = roots(project, plan, style_id)["assets"] / asset_id
        with core.locked(root):
            manifest_path = root / "asset.json"
            manifest = core.read(manifest_path) if manifest_path.exists() else {
                "schema": 1, "kind": "greybox-owned-asset", "case_id": row["case_id"],
                "asset_id": asset_id, "ownership": row["ownership"], "files": []}
            core.require(manifest.get("asset_id") == asset_id and manifest.get("case_id") == row["case_id"]
                         and manifest.get("ownership") == row["ownership"], "Existing asset manifest belongs to another owner")
            entries = {item["path"]: item for item in manifest["files"]}
            entries[row["path"]] = row
            manifest["files"] = [entries[k] for k in sorted(entries)]
            manifest["updated_at"] = core.now()
            core.write(manifest_path, manifest)
        register(project, plan)
    elif role in ("run", "supplier-run"):
        _register_run_record(project, plan, row, style_id)
    else:
        with core.locked(case_root(project, plan)):
            index = _read_index(project, plan)
            _merge_styles(plan, index)
            index.setdefault("artifacts", {})[row["path"]] = copy.deepcopy(row)
            _write_navigation(project, plan, index)
    return row


def _transient_source(project, path):
    """A project's parent folder is not part of its internal ownership layout."""
    project, path = Path(project).resolve(), Path(path).resolve()
    parts = path.relative_to(project).parts if core.inside(path, project) else path.parts
    return bool(set(parts) & TRANSIENT) or any(
        parts[i:i + 2] == ("production", "runs") for i in range(len(parts) - 1))


def _register_run_record(project, plan, row, style_id=None):
    """Persist a link to the one owning ledger, never its private contents."""
    r = roots(project, plan, style_id)
    relative = Path(row["path"]).relative_to(r["runs"])
    core.require(len(relative.parts) >= 2 and core.safe_id(relative.parts[0]), "Run records need runs/<run_id>/<file>")
    run_id = relative.parts[0]
    value = copy.deepcopy(row)
    value.update(run_id=run_id, run_root=str(r["runs"] / run_id))
    with core.locked(case_root(project, plan)):
        index = _read_index(project, plan)
        _merge_styles(plan, index)
        key = (style_id or "shared") + "/" + run_id
        index.setdefault("production_runs", {})[key] = value
        _write_navigation(project, plan, index)
    return value


def register_asset(project, plan, asset_id, record):
    """Register an unchanged canonical reuse source without copying its bytes."""
    declared = asset_owner(plan, asset_id)
    style_id = declared.get("style_id")
    core.require(isinstance(record, dict) and record.get("path") and record.get("sha256"),
                 "Canonical asset registration needs source path and hash")
    p = core.resolve_input(record["path"], project)
    core.require(p.is_file() and core.file_hash(p) == record["sha256"], "Canonical source hash changed")
    core.require(not _transient_source(project, p),
        "Formal assets cannot be registered from run/download/draft/archive locations")
    row = copy.deepcopy(record)
    row.update(path=str(p), case_id=workspace(plan)["case_id"], asset_id=asset_id,
               style_id=style_id, role=record.get("role", "asset"), ownership=declared,
               storage="canonical_reference")
    target = _owned_path(roots(project, plan, style_id)["assets"] / asset_id, project)
    with core.locked(target):
        manifest_path = target / "asset.json"
        manifest = core.read(manifest_path) if manifest_path.is_file() else {
            "schema": 1, "kind": "greybox-owned-asset", "case_id": row["case_id"],
            "asset_id": asset_id, "ownership": declared, "files": []}
        core.require(manifest.get("case_id") == row["case_id"] and manifest.get("asset_id") == asset_id
                     and manifest.get("ownership") == declared, "Canonical asset manifest has conflicting ownership")
        entries = {item["path"]: item for item in manifest["files"]}
        entries[str(p)] = row
        manifest.update(files=[entries[k] for k in sorted(entries)], updated_at=core.now())
        core.write(manifest_path, manifest)
    register(project, plan)
    return {"ok": True, "manifest": str(manifest_path), "artifact": row}


def audit_dependencies(project, plan, style_id, paths, source_role="art", dependency_roots=None):
    """Check the caller's dependency closure; do not guess computed engine loads."""
    project = Path(project).resolve()
    r = roots(project, plan, style_id)
    allowed_baselines = [core.resolve_input(p, project) for p in (dependency_roots or [])]
    reused = {}
    for asset in plan.get("assets", []):
        source = asset.get("source", {})
        if source.get("path") and source.get("sha256"):
            asset_ownership = asset_owner(plan, asset.get("id", asset.get("asset_id")))
            if asset_ownership["scope"] == "shared" or asset_ownership.get("style_id") == style_id:
                reused[str(core.resolve_input(source["path"], project))] = source["sha256"]
    issues, records = [], []
    for item in paths:
        text = item.get("path") if isinstance(item, dict) else item
        role = item.get("role", source_role) if isinstance(item, dict) else source_role
        p = core.resolve_input(text, project)
        reason = None
        declared_baseline = role == "baseline" and any(core.inside(p, q) for q in allowed_baselines)
        transient = _transient_source(project, p)
        if not p.is_file():
            reason = "MISSING_DEPENDENCY"
        elif declared_baseline:
            dependency_owner = {"scope": "baseline", "read_only": True}
        elif str(p) in reused and not transient:
            if core.file_hash(p) != reused[str(p)]:
                reason = "REUSED_ASSET_HASH_DRIFT"
            else:
                dependency_owner = {"scope": "canonical_reuse", "read_only": True}
        elif not core.inside(p, project):
            reason = "EXTERNAL_DEPENDENCY_NOT_DECLARED"
        else:
            parts = set(p.relative_to(project).parts)
            if parts & TRANSIENT or ("production" in parts and "runs" in parts):
                reason = "TRANSIENT_ART_DEPENDENCY"
            elif core.inside(p, r["runtime"]) or core.inside(p, r["dcc"]) or core.inside(p, r["assets"]):
                dependency_owner = {"scope": "style", "style_id": style_id}
            elif core.inside(p, r["resource_case"] / "shared/assets") or core.inside(p, r["tools"]) or core.inside(p, r["logical_tools"]):
                dependency_owner = {"scope": "shared"}
            elif (core.inside(p, project / "art") or core.inside(p, r["resource_case"].parent)
                  or core.inside(p, r["code_case"].parent)):
                reason = "UNCLASSIFIED_OR_OTHER_STYLE_ART_DEPENDENCY"
            else:
                dependency_owner = {"scope": "baseline", "read_only": True}
        if reason:
            issues.append({"code": reason, "path": str(p)})
        else:
            records.append({"path": str(p), "sha256": core.file_hash(p), "ownership": dependency_owner})
    return {"ok": not issues, "issues": issues, "dependencies": records}


def _style_names(plan):
    result = {}
    for item in plan.get("styles", plan.get("selected_styles", [])):
        if isinstance(item, dict):
            result[item.get("id", item.get("style_id"))] = item.get("name", item.get("label", item.get("id", item.get("style_id"))))
        else:
            result[item] = item
    return result


def _read_index(project, plan):
    config = workspace(plan, project)
    r = roots(project, plan)
    if not r["index"].exists():
        collisions = [r["case"] / "README.md"]
        if r["styles"].is_dir():
            collisions.extend(r["styles"].glob("*/style.json"))
        core.require(not any(path.exists() for path in collisions),
                     "Unregistered case contains existing navigation metadata; inventory before migration and preserve unmanaged files")
    index = core.read(r["index"]) if r["index"].is_file() else {
        "schema": 1, "kind": "greybox-case-index", "case_id": config["case_id"],
        "root": config["root"], "engine": config["engine"], "resource_root": config["resource_root"],
        "code_root": config["code_root"], "styles": {}}
    core.require(index.get("schema") == 1 and index.get("kind") == "greybox-case-index"
                 and index.get("case_id") == config["case_id"] and index.get("engine") == config["engine"]
                 and index.get("root") == config["root"] and index.get("resource_root") == config["resource_root"]
                 and index.get("code_root", index.get("resource_root")) == config["code_root"],
                 "Existing case index has a different identity or resource mapping; inventory before migration")
    core.require(isinstance(index.get("styles"), dict) and all(core.safe_id(sid) for sid in index["styles"]),
                 "Existing case index contains invalid style identities")
    for sid, row in index["styles"].items():
        core.require(row.get("schema") == 1 and row.get("kind") == "greybox-style-index"
                     and row.get("case_id") == config["case_id"] and row.get("style_id") == sid
                     and row.get("root") == config["root"] + "/styles/" + sid
                     and row.get("resource_root") == config["resource_root"] + "/styles/" + sid
                     and row.get("code_root", row.get("resource_root")) == config["code_root"] + "/styles/" + sid,
                     "Existing style metadata has conflicting ownership or paths")
    return index


def _pointer_health(project, pointer):
    errors = []
    for row in pointer.get("files", []):
        p = core.resolve_input(row["path"], project)
        if not p.is_file() or core.file_hash(p) != row["sha256"]:
            errors.append({"code": "POINTER_FILE_DRIFT", "path": row["path"]})
    current = pointer.get("files", [])
    if not current or pointer.get("snapshot_hash") != core.digest(current):
        errors.append({"code": "POINTER_SNAPSHOT_CORRUPT"})
    if not any(row["path"] == pointer.get("entry") for row in current):
        errors.append({"code": "POINTER_ENTRY_NOT_BOUND"})
    proof = pointer.get("proof")
    if proof is not None:
        p = core.resolve_input(proof.get("path", ""), project)
        if not p.is_file() or core.file_hash(p) != proof.get("sha256"):
            errors.append({"code": "POINTER_PROOF_DRIFT"})
    return {"current": not errors, "issues": errors}


def _render(project, index):
    rows = ["# " + index["case_id"], "", "Carrier: `" + index["engine"] + "`.", "",
            "Each entry identifies exact resource bytes; folder recency is not authority.", ""]
    if index["engine"] == "blender":
        rows.extend(["Blender entries are DCC/spatial projects; they do not establish playable acceptance.", ""])
    else:
        rows.extend(["| Style | Development | Last verified | User accepted |", "| --- | --- | --- | --- |"])
    def link(pointer):
        if not pointer:
            return "—"
        p = core.resolve_input(pointer["entry"], project)
        label = pointer.get("snapshot_hash", "")[:12]
        state = "" if _pointer_health(project, pointer)["current"] else " [stale]"
        return "[" + label + "](" + str(p) + ")" + state
    if index["engine"] != "blender":
        for sid, style in sorted(index["styles"].items()):
            rows.append("| " + str(style.get("name", sid)).replace("|", "\\|") + " | "
                        + " | ".join(link(style.get("pointers", {}).get(key)) for key in POINTERS) + " |")
    rows.extend(["", "Shared content", ""])
    for label, value in index.get("links", {}).items():
        rows.append("- [" + label + "](" + str(core.resolve_input(value["path"], project)) + ")"
                    + ("" if value["exists"] else " (planned; directory not created)"))
    for sid, style in sorted(index["styles"].items()):
        rows.extend(["", str(style.get("name", sid)) + " (`" + sid + "`)", ""])
        for label, value in style.get("links", {}).items():
            rows.append("- [" + label + "](" + str(core.resolve_input(value["path"], project)) + ")"
                        + ("" if value["exists"] else " (planned; directory not created)"))
        for asset in style.get("assets", []):
            rows.append("- Asset `" + asset["asset_id"] + "`: [manifest]("
                        + str(core.resolve_input(asset["manifest"], project)) + "), " + str(asset["file_count"]) + " canonical file(s)")
        for run in style.get("production_runs", []):
            rows.append("- Run `" + run["run_id"] + "`: [frozen plan](" + run["path"] + ")")
        if style.get("artifacts"):
            counts = {}
            for artifact in style["artifacts"]:
                counts[artifact["role"]] = counts.get(artifact["role"], 0) + 1
            rows.append("- Registered artifact ownership: " + ", ".join(key + " " + str(value) for key, value in sorted(counts.items()))
                        + "; [full records](" + str(core.resolve_input(style["root"] + "/style.json", project)) + ")")
        if index["engine"] == "blender":
            for entry in style.get("dcc_entries", []):
                rows.append("- DCC project: [" + Path(entry["path"]).name + "](" + entry["path"] + ")")
    common_runs = [row for row in index.get("production_runs", {}).values() if row.get("style_id") is None]
    if common_runs:
        rows.extend(["", "Shared production runs", ""])
        for run in sorted(common_runs, key=lambda row: row["run_id"]):
            rows.append("- `" + run["run_id"] + "`: [frozen plan](" + run["path"] + ")")
    shared = [a for a in index.get("assets", {}).values() if a["ownership"]["scope"] == "shared"]
    if shared:
        rows.extend(["", "Shared assets", ""])
        for asset in sorted(shared, key=lambda row: row["asset_id"]):
            rows.append("- `" + asset["asset_id"] + "`: [manifest](" + str(core.resolve_input(asset["manifest"], project)) + ")")
    return "\n".join(rows) + "\n"


def _write_navigation(project, plan, index):
    r = roots(project, plan)
    config = workspace(plan)
    index["code_root"] = config["code_root"]
    def links(values):
        return {key: {"path": str(p.relative_to(Path(project).resolve())), "exists": p.exists()}
                for key, p in values.items()}
    index["links"] = links({"baseline": r["baseline"], "directions": r["directions"], "tools": r["tools"],
                            "assets": r["assets"], "production plans": r["production"] / "plans", "production runs": r["runs"]})
    assets = index.setdefault("assets", {})
    for aid, declared in config["asset_owners"].items():
        base = r["resource_case"] / ("styles/" + declared["style_id"] if declared["scope"] == "style" else "shared")
        manifest_path = base / "assets" / aid / "asset.json"
        _owned_path(manifest_path, project)
        if manifest_path.is_file():
            manifest = core.read(manifest_path)
            core.require(manifest.get("case_id") == config["case_id"] and manifest.get("asset_id") == aid
                         and manifest.get("ownership") == declared, "Asset navigation manifest has conflicting ownership")
            assets[aid] = {"asset_id": aid, "ownership": declared,
                           "manifest": str(manifest_path.relative_to(Path(project).resolve())),
                           "sha256": core.file_hash(manifest_path), "file_count": len(manifest.get("files", []))}
    index["updated_at"] = core.now()
    for sid, style in index["styles"].items():
        # A partial style production run must retain the other style records.
        path = r["styles"] / sid / "style.json"
        _owned_path(path, project)
        if path.is_file():
            previous = core.read(path)
            core.require(previous.get("schema") == 1 and previous.get("kind") == "greybox-style-index"
                         and previous.get("case_id") == config["case_id"] and previous.get("style_id") == sid,
                         "Existing style.json is not owned navigation metadata; inventory before migration")
        logical = r["styles"] / sid
        resources = r["resource_case"] / "styles" / sid
        code = r["code_case"] / "styles" / sid
        style["code_root"] = config["code_root"] + "/styles/" + sid
        style["carrier"] = config["engine"]
        style["links"] = links({"concepts": logical / "concepts", "design and recipe": logical / "design",
                                "modeling references": logical / "references", "assets": resources / "assets",
                                ("scripts" if config["engine"] == "blender" else "runtime"): code / "runtime",
                                "DCC projects": code / "dcc", "asset plans and quotes": logical / "production/plans",
                                "production runs": logical / "production/runs"})
        style["assets"] = [assets[aid] for aid in sorted(assets) if assets[aid]["ownership"].get("style_id") == sid]
        style["production_runs"] = [row for _, row in sorted(index.get("production_runs", {}).items()) if row.get("style_id") == sid]
        style["artifacts"] = [row for _, row in sorted(index.get("artifacts", {}).items()) if row.get("style_id") == sid]
        style["dcc_entries"] = [row for row in style["artifacts"] if row["role"] == "dcc" and Path(row["path"]).suffix.lower() == ".blend"]
        core.write(path, style)
    core.write(r["index"], index)
    # Text is atomic using the same write+replace discipline as JSON manifests.
    import os
    import tempfile
    path = r["case"] / "README.md"
    fd, temporary = tempfile.mkstemp(prefix=".README.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            output.write(_render(project, index))
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _merge_styles(plan, index):
    names = _style_names(plan)
    config = workspace(plan)
    for sid, name in names.items():
        existing = index["styles"].get(sid)
        if existing is None:
            index["styles"][sid] = {"schema": 1, "kind": "greybox-style-index", "case_id": config["case_id"],
                "style_id": sid, "name": name, "root": config["root"] + "/styles/" + sid,
                "resource_root": config["resource_root"] + "/styles/" + sid,
                "code_root": config["code_root"] + "/styles/" + sid,
                "pointers": {}, "pointer_history": []}
        else:
            core.require(existing.get("case_id") == config["case_id"] and existing.get("style_id") == sid,
                         "Existing style metadata has conflicting ownership")
            existing["name"] = name


def register(project, plan):
    r = roots(project, plan)
    with core.locked(r["case"]):
        index = _read_index(project, plan)
        _merge_styles(plan, index)
        _write_navigation(project, plan, index)
    return {"ok": True, "case_id": index["case_id"], "index": str(r["index"]), "styles": sorted(index["styles"])}


def update_pointer(project, plan, style_id, kind, entry, files, plan_hash, proof=None):
    core.require(workspace(plan)["engine"] != "blender",
                 "Blender DCC/spatial entries use role dcc; they cannot establish playable navigation pointers")
    core.require(kind in POINTERS, "Unknown navigation pointer")
    core.require(isinstance(plan_hash, str) and re.fullmatch(r"[0-9a-f]{64}", plan_hash), "Pointer needs exact plan_hash")
    entry_path = validate_output(project, plan, entry, "runtime", style_id)
    rows = {}
    for item in files:
        p = core.resolve_input(item.get("path") if isinstance(item, dict) else item, project)
        core.require(p.is_file(), "Pointer references missing files")
        sha = core.file_hash(p)
        core.require(not isinstance(item, dict) or item.get("sha256", sha) == sha, "Pointer source changed since review")
        # Caller includes the full engine dependency closure (source + owned files).
        rows[str(p)] = {"path": str(p), "sha256": sha}
    core.require(str(entry_path) in rows, "Pointer must bind its exact playable entry bytes")
    ordered = [rows[k] for k in sorted(rows)]
    proof_value = None
    if proof is not None:
        core.require(isinstance(proof, dict) and proof.get("path") and proof.get("sha256"), "Pointer proof needs path and sha256")
        proof_path = core.resolve_input(proof["path"], project)
        core.require(proof_path.is_file() and core.file_hash(proof_path) == proof["sha256"], "Pointer proof changed since review")
        proof = {"path": str(proof_path), "sha256": proof["sha256"]}
        proof_value = core.read(proof_path)
    if kind == "last_verified":
        core.require(isinstance(proof_value, dict) and (proof_value.get("passed") is True or proof_value.get("result", {}).get("passed") is True),
                     "Last verified pointer needs actual passed native validation")
        core.require(proof_value.get("style_id") == style_id
                     and proof_value.get("plan_hash", proof_value.get("planHash")) == plan_hash,
                     "Native pointer proof belongs to another style/plan")
        supplied = sorted(({"path": str(core.resolve_input(item["path"], project)), "sha256": item["sha256"]}
                           for item in proof_value.get("files", [])), key=lambda row: row["path"])
        core.require(supplied == ordered, "Native pointer proof must bind the complete reviewed file snapshot")
    if kind == "user_accepted":
        core.require(isinstance(proof_value, dict) and proof_value.get("kind") == "human-delivery-acceptance"
                     and proof_value.get("actor") == "user" and proof_value.get("decision") == "accepted"
                     and bool(proof_value.get("source_ref")) and bool(proof_value.get("manifestHash")),
                     "User accepted pointer needs the existing exact H5 receipt; navigation never grants approval")
        manifest = proof_value.get("manifest")
        core.require(isinstance(manifest, dict) and core.digest(manifest) == proof_value["manifestHash"]
                     and manifest.get("planHash") == plan_hash, "User pointer proof has an invalid delivery manifest")
        matches = [s for s in manifest.get("styles", []) if s.get("id") == style_id]
        core.require(len(matches) == 1 and core.resolve_input(matches[0].get("entry_scene", ""), project) == entry_path,
                     "H5 proof did not accept this style/entry")
        accepted_files = (matches[0].get("owned_files", []) + matches[0].get("sources", [])
                          + matches[0].get("native_evidence", []) + matches[0].get("native_reports", []))
        accepted_map = {str(core.resolve_input(item["path"], project)): item["sha256"] for item in accepted_files}
        core.require(accepted_map == {item["path"]: item["sha256"] for item in ordered},
                     "H5 pointer files differ from the user-reviewed delivery")
    pointer = {"entry": str(entry_path), "files": ordered, "snapshot_hash": core.digest(ordered),
               "plan_hash": plan_hash, "recorded_at": core.now()}
    if proof is not None:
        pointer["proof"] = copy.deepcopy(proof)
    r = roots(project, plan)
    with core.locked(r["case"]):
        index = _read_index(project, plan)
        _merge_styles(plan, index)
        style = index["styles"][style_id]
        previous = style["pointers"].get(kind)
        if previous and all(previous.get(k) == pointer.get(k) for k in
                            ("entry", "snapshot_hash", "plan_hash", "proof")):
            pointer = previous
        elif previous:
            style["pointer_history"].append({"kind": kind, **previous})
        style["pointers"][kind] = pointer
        _write_navigation(project, plan, index)
    return {"ok": True, "style_id": style_id, "kind": kind, "pointer": pointer}


def read_navigation(project, plan):
    index = _read_index(project, plan)
    result = copy.deepcopy(index)
    for style in result["styles"].values():
        for kind, pointer in style.get("pointers", {}).items():
            pointer["health"] = _pointer_health(project, pointer)
            development = style.get("pointers", {}).get("development")
            # Verification adds native evidence to its snapshot. Compare the
            # development resource closure, allowing those additional receipts.
            pointer_files = {row["path"]: row["sha256"] for row in pointer.get("files", [])}
            pointer["matches_development"] = bool(development and development.get("files")
                and development["entry"] == pointer["entry"] and development["plan_hash"] == pointer["plan_hash"]
                and all(pointer_files.get(row["path"]) == row["sha256"] for row in development["files"]))
    return {"ok": True, "navigation": result, "index": str(roots(project, plan)["index"])}


def rollback_development(project, plan, run_dir):
    """Withdraw only the development pointer owned by this exact run.

    Resource bytes and verified/accepted snapshots remain available.  Matching
    an entry path alone is insufficient: content may be reused by a newer run.
    """
    rolled_run = str(core.resolve_input(run_dir, project))
    cleared, preserved, conflicts = [], [], []
    with core.locked(case_root(project, plan)):
        index = _read_index(project, plan)
        for sid, style in index["styles"].items():
            pointer = style.get("pointers", {}).get("development")
            if not pointer:
                continue
            proof = pointer.get("proof", {})
            proof_path = core.resolve_input(proof.get("path", ""), project)
            if not proof.get("sha256") or not proof_path.is_file() or core.file_hash(proof_path) != proof["sha256"]:
                conflicts.append({"style_id": sid, "reason": "Development ownership proof is missing or changed; pointer preserved"})
                preserved.append(sid)
                continue
            try:
                value = core.read(proof_path)
                core.require(isinstance(value, dict), "Development proof must be an object")
                owner_run = value.get("run_dir")
                core.require(isinstance(owner_run, str) and owner_run, "Development proof has no run owner")
            except (OSError, ValueError, TypeError) as error:
                conflicts.append({"style_id": sid, "reason": "Development ownership proof is invalid; pointer preserved"})
                preserved.append(sid)
                continue
            if str(core.resolve_input(owner_run, project)) != rolled_run:
                preserved.append(sid)
                continue
            style.setdefault("pointer_history", []).append({"kind": "development", **pointer,
                "reason": "rollback", "rolled_run": rolled_run, "withdrawn_at": core.now()})
            del style["pointers"]["development"]
            cleared.append(sid)
        if cleared:
            _write_navigation(project, plan, index)
    return {"ok": not conflicts, "cleared": cleared, "preserved": preserved, "conflicts": conflicts}


def inventory(project, plan=None):
    """Read-only inventory. Existing study/experiment paths can remain referenced."""
    project = Path(project).resolve()
    scan_root = case_root(project, plan) if plan is not None and is_workspace(plan) else project / "art"
    rows = []
    if scan_root.is_dir():
        # No symlink traversal, no content copying; large cache trees are omitted.
        import os
        for directory, dirs, files in os.walk(scan_root, followlinks=False):
            dirs[:] = sorted(d for d in dirs if d not in (".git", ".godot", "node_modules", "__pycache__")
                             and not (Path(directory) / d).is_symlink())
            for name in sorted(files):
                p = Path(directory) / name
                if p.is_symlink():
                    rows.append({"path": str(p), "type": "symlink", "resolved": str(p.resolve()), "action": "inspect_before_migration"})
                else:
                    rows.append({"path": str(p), "bytes": p.stat().st_size, "sha256": core.file_hash(p),
                                 "action": "inventory_only_no_move"})
    return {"ok": True, "mode": "inventory_only", "project": str(project), "root": str(scan_root),
            "files": rows, "migration": "Resolve ownership and engine dependencies; preserve frozen records and canonical assets before any explicit migration"}
