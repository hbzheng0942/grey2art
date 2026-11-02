"""Versioned plans, resumable provider work and conflict-aware art ownership.

No workflow step grants approval. The host records actual human authorization.
Provider POSTs are never retried automatically after an ambiguous outcome.
"""
from __future__ import annotations

import contextlib
import errno
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from datetime import datetime, timezone

from . import VERSION


class WorkflowError(ValueError):
    pass


def require(ok, message):
    if not ok:
        raise WorkflowError(message)


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def ensure_directory(path):
    """Use the host's mkdir broker, including its permission checks.

    Some WorkBuddy shims omit exist_ok from the broker request. Only tolerate
    its EEXIST for a directory, as Path.mkdir(exist_ok=True) would normally do.
    """
    path = Path(path)
    try:
        path.mkdir(parents=True, exist_ok=True)
    except FileExistsError as error:
        if error.errno != errno.EEXIST or not path.is_dir():
            raise


def write(path, value):
    path = Path(path)
    ensure_directory(path.parent)
    fd, name = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def safe_id(value):
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", value)


def inside(path, root):
    return Path(path).resolve().is_relative_to(Path(root).resolve())


def resolve_input(path, project):
    text = str(path)
    return ((Path(project) / text[6:]) if text.startswith("res://") else
            (Path(text) if Path(text).is_absolute() else Path(project) / text)).resolve()


def validate_plan(plan):
    require(plan.get("schema") == 1 and plan.get("kind", "greybox-art-plan") == "greybox-art-plan",
            "Expected greybox-art-plan schema 1")
    require(safe_id(plan.get("id")), "Invalid plan id")
    purpose = plan.get("purpose", "production")
    require(purpose in ("production", "art_proxy", "technical_fixture"), "Unknown purpose; never silently downgrade a production run")
    require(not (purpose == "art_proxy" and any(a.get("generation") for a in plan.get("assets", []))), "Art proxy cannot contain paid generation tasks")
    styles = plan.get("styles", [])
    ids = [s.get("id") for s in styles]
    mode = plan.get("delivery_mode", "multistyle")
    require(mode in ("single_style", "multistyle"), "Declare single_style or multistyle delivery_mode")
    require(len(ids) >= (2 if mode == "multistyle" else 1) and all(safe_id(i) for i in ids) and len(set(ids)) == len(ids),
            "Style count must match the explicit delivery_mode; do not duplicate a fake second style")
    contract = plan.get("contract", {})
    from . import engines
    engines.validate_scene(plan)
    validation = contract.get("validation", {})
    require(validation.get("mode", "playable") in ("playable", "technical_only"), "Unknown validation mode")
    steps = validation.get("steps", [])
    require(isinstance(steps, list), "validation.steps must be a list")
    require(all(s.get("input_mode", "action_state") in ("action_state", "input_event") for s in steps), "Unsupported input mode; provide a native adapter instead of silently replacing the input path")
    check_ids = [s.get("id", s.get("name")) for s in steps if s.get("expect")]
    require(all(safe_id(i) for i in check_ids) and len(check_ids) == len(set(check_ids)), "Expected checks need unique stable IDs/names")
    if validation.get("mode", "playable") == "playable":
        require(check_ids, "Playable delivery requires declared gameplay checks; use explicit technical_only for diagnostics")
    required = validation.get("required_checks", check_ids)
    require(isinstance(required, list) and set(required).issubset(set(check_ids)), "required_checks must refer to declared checks")
    require(validation.get("mode", "playable") != "playable" or bool(required), "Playable delivery requires nonempty required_checks")
    policy = plan.get("effective_policy", {})
    require(policy.get("lux_selection", "task_based") in ("task_based", "user_override"),
            "Resolve the current user policy explicitly; historical defaults are not authority")
    assets = plan.get("assets", [])
    asset_ids = [a.get("id") for a in assets]
    require(all(safe_id(i) for i in asset_ids) and len(asset_ids) == len(set(asset_ids)),
            "Duplicate or invalid asset id")
    if plan.get("workspace") is not None:
        from . import layout
        layout.normalize_workspace(plan, required=True)
        for asset in assets:
            layout.asset_owner(plan, asset["id"])
    calls = 0
    for a in assets:
        require(a.get("route") in ("reuse", "procedural", "generated", "hybrid"), "Invalid production route")
        g = a.get("generation")
        if g:
            require(a["route"] in ("generated", "hybrid"), "Reuse/procedural assets cannot hide generation tasks")
            require(g.get("region") in ("cn", "international"), "Generation needs an explicit region")
            p = g.get("parameters", {})
            require(g.get("operation") in ("image_to_3d", "text_to_3d", "remesh", "articulate", "rig", "retarget", "material_transfer", "export"),
                    "Unsupported provider operation")
            if purpose != "technical_fixture":
                require(g["operation"] != "text_to_3d", "This skill requires approved image-to-3D; text-to-3D production is prohibited")
                if g["operation"] == "image_to_3d":
                    require(isinstance(g.get("modeling_references"), dict), "Production generation must bind its reviewed modeling-reference package")
                    require(g.get("reference", {}).get("path") or g.get("references"), "Production image-to-3D needs approved local reference bytes")
                    require(not set(p) & {"img", "imgs", "prompt", "text"}, "Production image parameters must use the bound local references, not remote/prompt bypasses")
            if g["operation"] in ("image_to_3d", "text_to_3d"):
                require(p.get("version") in ("G1", "G1-Turbo"),
                        "Choose an explicit G1 or G1-Turbo version per asset; there is no blanket default")
                require(p["version"] in policy.get("allowed_versions", ["G1", "G1-Turbo"]),
                        "Generation version conflicts with effective user policy")
                require(type(p.get("faceCount")) is int and 10000 <= p["faceCount"] <= 300000,
                        "Generation faceCount must be an explicit integer in 10000..300000")
                require(not (p["version"] == "G1" and "enablePbr" in p), "G1 must omit enablePbr")
                require(not (p["version"] == "G1-Turbo" and "customSize" in p), "G1-Turbo must omit customSize")
            require(isinstance(a.get("reason"), str) and a["reason"].strip(), "Generated asset needs its selection rationale")
            calls += 1
        elif a["route"] == "generated":
            require(a.get("source", {}).get("path"), "Generated asset needs an existing source or a generation task")
    bindings = plan.get("bindings", [])
    gate = plan.get("workflow", {})
    native_workflow = (purpose == "production" and isinstance(gate, dict)
                       and isinstance(gate.get("path"), str) and bool(gate["path"].strip())
                       and isinstance(gate.get("sha256"), str)
                       and re.fullmatch(r"[a-f0-9]{64}", gate["sha256"]) is not None)
    # Shape only: prepare/check_plan_gate still verify the actual H3 native
    # owners, scoped evidence and approval before any binding-free production.
    require(isinstance(bindings, list) and (bindings or native_workflow),
            "Plan has no art bindings; native-only production needs its workflow path/hash")
    seen = set()
    for b in bindings:
        require(safe_id(b.get("id")) and b["id"] not in seen, "Invalid/duplicate binding id")
        seen.add(b["id"])
        require(isinstance(b.get("owner"), str) and b["owner"], "Each binding needs a logical owner node path")
        require(isinstance(b.get("uniform_scale", 1), (int, float)) and b.get("uniform_scale", 1) > 0,
                "uniform_scale must be positive")
        require("baseOffsetY" not in b, "Unconsumed baseOffsetY: express the placement using anchor")
        for sid in ids:
            source = b.get("styles", {}).get(sid, {}).get("source", b.get("source"))
            require(isinstance(source, dict) and bool(source), "Every binding/style needs an explicit source; placeholders are never implicit")
            if source.get("asset_id"):
                require(source["asset_id"] in asset_ids, "Unknown binding asset_id")
            else:
                require(source.get("path") or source.get("primitive") in ("box", "sphere", "cylinder"), "Source needs a path, asset_id, or explicit supported primitive")
    used_assets = set()
    for b in bindings:
        for sid in ids:
            ref = b.get("styles", {}).get(sid, {}).get("source", b.get("source", {}))
            if ref.get("asset_id"):
                used_assets.add(ref["asset_id"])
    for asset in assets:
        require(not asset.get("generation") or asset["id"] in used_assets,
                "Generated task is not used by any style binding; remove it or define its real output dependency")
    # Keys are rejected without ever echoing their values.
    def secrets(value):
        if isinstance(value, dict):
            for k, v in value.items():
                require(k.lower().replace("_", "") not in ("apikey", "authorization", "accesstoken", "secret"),
                        "Credentials must not be stored in production plans")
                secrets(v)
        elif isinstance(value, list):
            for v in value:
                secrets(v)
    secrets(plan)
    return {"styles": ids, "assets": len(assets), "generationTasks": calls,
            "routes": {r: sum(a["route"] == r for a in assets) for r in ("reuse", "procedural", "generated", "hybrid")}}


def _generation_operation(asset, project):
    """Neutral, hash-bound image operation for the legacy Godot/Lux runner."""
    generation = asset["generation"]
    references = generation.get("references") or ([generation["reference"]] if generation.get("reference") else [])
    inputs = [{"path": str(resolve_input(ref["path"], project)), "sha256": ref.get("sha256")} for ref in references]
    parameters = dict(generation.get("parameters", {}))
    if generation["operation"] == "image_to_3d":
        require(not set(parameters) & {"img", "imgs", "image_path", "image_paths"}, "Use generation.reference(s) as the sole approved image input")
        parameters["image_path" if len(inputs) == 1 else "image_paths"] = 0 if len(inputs) == 1 else list(range(len(inputs)))
    return {"id": asset["id"], "asset_id": asset["id"], "provider": "lux3d", "operation": generation["operation"],
            "model_version": parameters.get("version"), "parameters": parameters, "inputs": inputs,
            "modeling_references": generation.get("modeling_references")}


def _check_generation_reference(asset, project):
    from . import image_policy
    return image_policy.validate_operation(_generation_operation(asset, project), project)


def input_snapshot(project, plan):
    project = Path(project).resolve()
    from . import engines
    engine_name = engines.name(plan, project)
    files = {}
    excluded = {".git", ".godot", ".venv", "node_modules", "art", "dist", "runs",
                "Library", "Temp", "Logs", "obj", "Builds", "UserSettings"}
    generated_roots = []
    if engine_name == "unity":
        generated_roots.append(project / "Assets/GreyboxArtRuntime")
        if not plan.get("workspace"):
            generated_roots.append(project / "Assets/Art/Greybox")
        if plan.get("workspace"):
            from . import layout
            mapped = layout.roots(project, plan)
            generated_roots.extend(mapped[k] for k in ("resource_case", "code_case", "engine_tools") if k in mapped)
    # Engine source is inexpensive to hash. Large assets are hashed only when referenced.
    for folder, dirs, names in os.walk(project, followlinks=False):
        dirs[:] = [n for n in dirs if n not in excluded and not (Path(folder) / n).is_symlink()
                   and not any(inside(Path(folder) / n, p) for p in generated_roots)]
        for n in names:
            p = Path(folder) / n
            if not p.is_symlink() and (p.suffix in (".gd", ".gdshader", ".tscn", ".tres", ".cs",
                    ".unity", ".prefab", ".shader", ".hlsl", ".shadergraph", ".asmdef", ".compute") or n == "project.godot"):
                files[str(p.relative_to(project))] = file_hash(p)
        require(len(files) <= 10000, "Too many sources; supply a bounded project adapter")
    for config in engines.configuration_files(project, plan):
        require(config.is_file(), "Project configuration is missing: " + config.name)
        files[str(config.relative_to(project))] = file_hash(config)
    scene = resolve_input(plan["contract"]["scene"], project)
    require(inside(scene, project) and scene.is_file(), "Baseline scene is missing or outside project")
    for a in plan.get("assets", []):
        generation = a.get("generation", {})
        references = list(generation.get("references", []))
        if generation.get("modeling_references"):
            references.append(generation["modeling_references"])
        for ref in [a.get("source", {}), generation.get("reference", {})] + references:
            if ref.get("path"):
                p = resolve_input(ref["path"], project)
                require(p.is_file(), "Missing referenced asset: " + str(p))
                h = file_hash(p)
                require(not ref.get("sha256") or ref["sha256"] == h, "Referenced asset hash changed")
                files[str(p)] = h
    for b in plan.get("bindings", []):
        refs = [b.get("source", {})] + [v.get("source", {}) for v in b.get("styles", {}).values() if isinstance(v, dict)]
        for ref in refs:
            if ref.get("path"):
                p = resolve_input(ref["path"], project)
                require(p.is_file(), "Missing binding asset")
                files[str(p)] = file_hash(p)
    for source in plan.get("contract", {}).get("source_paths", []):
        p = resolve_input(source, project)
        require(p.is_file(), "Declared source dependency is missing")
        files[str(p)] = file_hash(p)
    declared_sources = {str(resolve_input(path, project)) for path in files}
    declared_sources.add(str(scene))
    for item in engines.dependency_snapshot(project, plan):
        dependency = Path(item["path"]).resolve()
        if engine_name == "unity" and any(inside(dependency, root) for root in generated_roots):
            # Unity's compile-time source scan also sees the installed bridge and
            # new style shaders. Their integrity belongs to runtime/owned-file
            # receipts, not the frozen greybox baseline. Explicitly declared
            # sources (and their .meta identity) remain baseline dependencies.
            declared = str(dependency) in declared_sources or (
                dependency.suffix == ".meta" and str(dependency.with_suffix("")) in declared_sources)
            if not declared:
                continue
        files[item["path"]] = item["sha256"]
    if plan.get("workflow", {}).get("path"):
        workflow_path = resolve_input(plan["workflow"]["path"], project)
        files[str(workflow_path)] = file_hash(workflow_path)
        from .workflow import evidence_dependencies
        for item in evidence_dependencies(workflow_path, project):
            files[item["path"]] = item["sha256"]
    import_settings = {}
    for name in list(files):
        p = Path(name) if Path(name).is_absolute() else project / name
        sidecar = engines.import_sidecar(p, engine_name)
        if p.suffix.lower() in (".glb", ".gltf", ".fbx", ".obj", ".blend", ".png", ".jpg", ".jpeg", ".webp", ".exr"):
            import_settings[str(sidecar)] = file_hash(sidecar) if sidecar.is_file() else None
    return {"files": files, "importSettings": import_settings, "sha256": digest({"files": files, "importSettings": import_settings})}


def runtime_snapshot():
    root = Path(__file__).resolve().parents[1]
    files = {p.relative_to(root).as_posix(): file_hash(p)
             for directory in (root / "greybox", root / "godot", root / "unity", root / "blender", root / "greybox_templates")
             for p in directory.rglob("*") if p.is_file() and p.suffix in
             (".py", ".gd", ".gdshader", ".cs", ".shader", ".hlsl", ".asmdef", ".compute", ".json")}
    manifest = root / "vendor" / "manifest.json"
    if manifest.is_file():
        files["vendor/manifest.json"] = file_hash(manifest)
    return {"files": files, "sha256": digest(files)}


def process_alive(pid):
    require(type(pid) is int and pid > 0, "Invalid lock PID")
    if os.name == "nt":
        # os.kill(pid, 0) terminates Windows processes on some Python versions.
        import ctypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() != 87  # access denied is not proof of death
        try:
            code = ctypes.c_ulong()
            return not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


@contextlib.contextmanager
def locked(run_dir):
    path = Path(run_dir) / ".workflow.lock"
    ensure_directory(path.parent)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        try:
            pid = int(read(path)["pid"])
            alive = process_alive(pid)
        except (ValueError, KeyError, OSError):
            raise WorkflowError("Run lock needs inspection; do not remove a live worker lock")
        else:
            require(not alive, "Run is owned by a live process")
            path.unlink()
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.write(fd, json.dumps({"pid": os.getpid(), "createdAt": now()}).encode())
    os.close(fd)
    try:
        yield
    finally:
        path.unlink(missing_ok=True)


def load_run(run_dir, check_inputs=True):
    root = Path(run_dir).resolve()
    state = read(root / "run.json")
    require(Path(state["runDir"]).resolve() == root, "Run journal root mismatch")
    current = None
    try:
        current = read(root / "plan.json")
    except (OSError, ValueError):
        if check_inputs:
            raise WorkflowError("Current plan missing/corrupt; status and rollback remain available") from None
    if check_inputs:
        require(current is not None and state["planHash"] == digest(current), "Plan changed: fork a revised run; old authorization cannot be reused")
        require(input_snapshot(state["project"], current)["sha256"] == state["inputs"]["sha256"],
                "Source/asset/import drift: old approval and evidence are stale; create a revised run")
        require(state.get("runtime", {}).get("sha256") == runtime_snapshot()["sha256"],
                "Runtime recipe changed: old evidence is stale; create a revised run")
        return state, current
    # Recovery never consumes a changed current plan. New runs retain a frozen copy.
    frozen = root / "plan.frozen.json"
    if frozen.is_file():
        try:
            plan = read(frozen)
            if digest(plan) != state["planHash"]:
                plan = {"styles": [], "assets": [], "_recovery_plan_missing": True}
        except (OSError, ValueError):
            plan = {"styles": [], "assets": [], "_recovery_plan_missing": True}
    elif current is not None and digest(current) == state["planHash"]:
        plan = current
    else:
        plan = {"schema": 1, "styles": [], "assets": [], "_recovery_plan_missing": True}
    return state, plan


def save_run(run_dir, state):
    state["updatedAt"] = now()
    write(Path(run_dir) / "run.json", state)


def _workspace_run_path(project, plan, run_dir):
    from . import layout
    try:
        layout.validate_output(project, plan, run_dir, "run")
        return None
    except WorkflowError:
        styles = [s["id"] for s in plan.get("styles", [])]
        require(len(styles) == 1, "Multi-style run belongs in case/shared/production/runs")
        layout.validate_output(project, plan, run_dir, "run", style_id=styles[0])
        return styles[0]


def _workspace_files(artifact, result=None):
    rows = artifact.get("owned_files", []) + artifact.get("sources", [])
    if result is not None:
        rows += result.get("evidence", [])
        from .delivery import _auxiliary
        rows += _auxiliary(result, artifact.get("project", artifact.get("project_root")))
    return [{"path": k, "sha256": v} for k, v in sorted({str(Path(r["path"]).resolve()): r["sha256"] for r in rows}.items())]


def _workspace_verified_pointer(run_dir, state, plan, sid):
    from . import layout
    artifact = state["artifacts"][sid]
    result = state["validation"][sid]["result"]
    contract = plan.get("contract", {}).get("validation", {})
    required = set(contract.get("required_checks", [s.get("id", s.get("name")) for s in contract.get("steps", []) if s.get("expect")]))
    hashes = lambda rows: {str(Path(r["path"]).resolve()): r["sha256"] for r in rows}
    valid = (result.get("passed") is True and result.get("gameplay_verified") is True
             and required <= set(result.get("passed_check_ids", []))
             and result.get("scene") == artifact["entry_scene"] and result.get("binding_digest") == artifact["binding_digest"]
             and result.get("attempt_id") and not result.get("errors") and not result.get("native_errors")
             and not result.get("failed_check_ids")
             and hashes(result.get("artifact_hashes", [])) == hashes(artifact.get("owned_files", []))
             and hashes(result.get("source_hashes", [])) == hashes(artifact.get("sources", []))
             and result.get("returncode", 0) == 0 and bool(result.get("evidence")))
    if not valid:
        return  # Technical/proxy/failed evidence never promotes a playable pointer.
    files = _workspace_files(artifact, result)
    receipt = {"schema": 1, "kind": "greybox-native-verification", "style_id": sid,
               "plan_hash": state["planHash"], "passed": True, "run_dir": str(run_dir),
               "files": files, "result": result}
    path = Path(run_dir) / "navigation-receipts" / (sid + "-" + digest(receipt) + ".json")
    if not path.exists():
        write(path, receipt)
    layout.update_pointer(state["project"], plan, sid, "last_verified", artifact["entry_scene"], files,
                          state["planHash"], proof={"path": str(path), "sha256": file_hash(path)})


def prepare(plan_file, project, run_dir, capability_file=None, session_id=None):
    plan = read(plan_file)
    info = validate_plan(plan)
    project_alias = Path(project).absolute()
    project = project_alias.resolve()
    run_alias = Path(run_dir).absolute()
    run_dir = project / run_alias.relative_to(project_alias) if run_alias.is_relative_to(project_alias) else run_alias
    from . import layout
    layout.normalize_workspace(plan, required=plan.get("purpose", "production") == "production")
    capability_report = read(capability_file) if capability_file else None
    if capability_report is not None:
        require(session_id, "A fresh capability report needs the current host --session-id")
    if plan.get("purpose", "production") != "technical_fixture":
        from .workflow import check_plan_gate
        check_plan_gate(plan, project, capability_report=capability_report, expected_session=session_id)
        for asset in plan.get("assets", []):
            if asset.get("generation"):
                _check_generation_reference(asset, project)
    if plan.get("purpose", "production") == "production":
        from .production_control import ensure_prepared
        ensure_prepared(project, plan)
    run_dir = Path(run_dir).absolute()
    from . import layout
    layout.normalize_workspace(plan, required=plan.get("purpose", "production") == "production")
    if layout.is_workspace(plan):
        _workspace_run_path(project, plan, run_dir)
    else:
        require(inside(run_dir, project / "art" / "experiments"), "Legacy diagnostic run-dir must be inside project/art/experiments")
    run_dir = run_dir.resolve()
    with locked(run_dir):
        require(not (run_dir / "run.json").exists(), "Run already exists; use status/resume or a new run id")
        state = {"schema": 1, "kind": "greybox-art-run", "version": VERSION, "createdAt": now(),
                 "project": str(project), "runDir": str(run_dir), "planHash": digest(plan),
                 "policyHash": digest(plan.get("effective_policy", {})), "inputs": input_snapshot(project, plan),
                 "runtime": runtime_snapshot(),
                 "state": "planned", "assets": {}, "quotes": {}, "approval": None,
                 "artifacts": {}, "validation": {}, "ownedFiles": [], "events": []}
        write(run_dir / "plan.json", plan)
        write(run_dir / "plan.frozen.json", plan)
        if capability_report is not None:
            _store_readiness(run_dir, state, capability_report, session_id)
        save_run(run_dir, state)
    if layout.is_workspace(plan):
        layout.register(project, plan)
        run_style = _workspace_run_path(project, plan, run_dir)
        layout.record_artifact(project, plan, run_dir / "plan.frozen.json", "run", style_id=run_style,
                               provenance={"ledger_path": str(run_dir / "run.json")})
    return {"ok": True, "runDir": str(run_dir), "planHash": state["planHash"], **info,
            "next": "quote then record user approval" if info["generationTasks"] else "run"}



def _store_readiness(run_dir, state, report, session_id):
    path = Path(run_dir) / "operational-readiness.json"
    write(path, report)
    state["operationalReadiness"] = {"path": str(path.resolve()), "sha256": file_hash(path),
                                    "session_id": session_id, "recordedAt": now()}


def _read_readiness(run_dir, state):
    receipt = state.get("operationalReadiness")
    if not receipt:
        return None, None
    path = Path(receipt["path"])
    require(inside(path, run_dir) and path.is_file(), "Operational receipt missing; refresh-readiness")
    require(file_hash(path) == receipt["sha256"], "Operational receipt changed; refresh-readiness")
    return read(path), receipt["session_id"]


def _check_workflow_gate(run_dir, state, plan, require_current_capabilities=True):
    from .workflow import check_plan_gate
    report, session_id = (_read_readiness(run_dir, state) if require_current_capabilities else (None, None))
    return check_plan_gate(plan, state["project"], capability_report=report, expected_session=session_id,
                           require_current_capabilities=require_current_capabilities,
                           allow_legacy_policy=not require_current_capabilities)


def _concept_source(plan, project):
    reference = plan.get("workflow", {}).get("path")
    if not reference:
        return "approved_import"
    return read(resolve_input(reference, project)).get("concept_source", "generate")


def refresh_readiness(run_dir, capability_file, session_id):
    """Refresh host facts without rewriting creative approvals or granting spend."""
    from .workflow import check_plan_capabilities
    require(session_id, "Identify the current host session")
    report = read(capability_file)
    with locked(run_dir):
        state, plan = load_run(run_dir, check_inputs=False)
        require(not plan.get("_recovery_plan_missing"), "Frozen plan unavailable; inspect status first")
        assessment = check_plan_capabilities(plan, state["project"], report, session_id)
        require(assessment["ok"], "Required current capability missing; readiness was not changed")
        _store_readiness(run_dir, state, report, session_id)
        state["events"].append({"type": "readiness_refreshed", "at": now(), "session_id": session_id})
        save_run(run_dir, state)
    return {"ok": True, "session_id": session_id, "planHash": state["planHash"],
            "note": "Operational facts refreshed; creative approvals and spending scope unchanged. Run still checks source/workflow drift."}


def readiness_status(run_dir, state, plan):
    if plan.get("purpose") == "technical_fixture":
        return {"state": "diagnostic", "note": "No production capability claim"}
    try:
        from .workflow import check_plan_capabilities
        report, session_id = _read_readiness(run_dir, state)
        if report is None:
            reference = plan.get("workflow", {})
            checkpoint = read(resolve_input(reference["path"], state["project"]))
            preflight = next(s for s in checkpoint.get("stages", []) if s.get("id") == "preflight" and s.get("scope") == "shared")
            evidence = next(e for e in preflight.get("evidence", []) if e.get("role") == "capability_report")
            path = resolve_input(evidence["path"], state["project"])
            require(file_hash(path) == evidence["sha256"], "Archived preflight evidence changed")
            report, session_id = read(path), reference.get("session_id")
        assessment = check_plan_capabilities(plan, state["project"], report, session_id)
        return {"state": "current" if assessment["ok"] else "blocked", "session_id": session_id,
                "blockers": assessment["blockers"]}
    except (ValueError, OSError, KeyError, TypeError, StopIteration) as error:
        return {"state": "needs_refresh", "reason": str(error), "next": "refresh-readiness"}


def quote_run(run_dir, bridge=None):
    if bridge is None:
        from . import lux as bridge
    with locked(run_dir):
        state, plan = load_run(run_dir)
        if plan.get("purpose", "production") != "technical_fixture":
            _check_workflow_gate(run_dir, state, plan)
        groups = {}
        previous_approval = state.get("approval")
        if previous_approval:
            state.setdefault("approvalHistory", []).append(previous_approval)
            if previous_approval.get("allowQuoteRefresh"):
                state["pendingQuoteRefreshAuthorization"] = previous_approval
            else:
                state.pop("pendingQuoteRefreshAuthorization", None)
        elif state.get("state") == "quoting":
            # A narrowly scoped, inactive authorization survives interruption.
            # Never recover arbitrary history or make it eligible for submit.
            previous_approval = state.get("pendingQuoteRefreshAuthorization")
        # Persist invalidation before any upload/quote. An interrupted refresh
        # must never leave a new request eligible under an old quote approval.
        state.update(approval=None, quoteHash=None, state="quoting")
        save_run(run_dir, state)
        for asset in plan.get("assets", []):
            g = asset.get("generation")
            if not g or state["assets"].get(asset["id"], {}).get("taskId"):
                continue
            require(state["assets"].get(asset["id"], {}).get("state") not in ("submitting", "unknown"),
                    "Unknown submission must be reconciled before another quote")
            parameters = dict(g["parameters"])
            if plan.get("purpose", "production") != "technical_fixture":
                _check_generation_reference(asset, state["project"])
            references = g.get("references") or ([g["reference"]] if g.get("reference", {}).get("path") else [])
            if references:
                require(not set(parameters) & {"img", "imgs"}, "Use bound local reference bytes instead of remote parameter overrides")
                urls = []
                for reference in references:
                    ref = resolve_input(reference["path"], state["project"])
                    ref_hash = file_hash(ref)
                    require(not reference.get("sha256") or reference["sha256"] == ref_hash, "Reference image changed")
                    cache_key = g["region"] + ":" + ref_hash
                    cache = state.setdefault("uploads", {}).get(cache_key)
                    if cache is None:
                        cache = bridge.upload(str(ref), g["region"])
                        state["uploads"][cache_key] = cache
                        save_run(run_dir, state)
                    url = cache.get("url") or cache.get("data", {}).get("url")
                    require(url, "Uploader returned no URL")
                    urls.append(url)
                parameters["img" if len(urls) == 1 else "imgs"] = urls[0] if len(urls) == 1 else urls
            bridge.validate(g["operation"], parameters)
            row = {"operation": g["operation"], "region": g["region"], "parameters": parameters,
                   "parametersHash": digest(parameters), "state": "prepared"}
            state["assets"][asset["id"]] = row
            groups.setdefault(g["region"], []).append((asset["id"], row))
        summaries = []
        for region, rows in groups.items():
            items = {}
            for seq, (_, row) in enumerate(rows, 1):
                items.update(bridge.quote_items_for(row["operation"], row["parameters"], str(seq)))
            result = bridge.quote(items, region)
            q = result.get("quote", result.get("data", {}).get("quote", {}))
            require(q.get("quoteId"), "Quote returned no quoteId")
            require(isinstance(q.get("estimatedCreditsTotal"), (int, float)) and q["estimatedCreditsTotal"] >= 0,
                    "Quote must return a nonnegative explicit total")
            state["quotes"][region] = result
            for seq, (asset_id, row) in enumerate(rows, 1):
                detail = q.get("details", {}).get(str(seq))
                if detail is None and len(rows) == 1:
                    detail = q["estimatedCreditsTotal"]
                row.update(state="quoted", quoteId=q["quoteId"], quotedCredits=detail if isinstance(detail, (int, float)) else None)
            summaries.append({"region": region, "quoteId": q["quoteId"],
                              "estimatedCredits": q.get("estimatedCreditsTotal"), "expiresAt": q.get("expiresAt"),
                              "assets": [a for a, _ in rows]})
            save_run(run_dir, state)
        require(groups, "No unsubmitted tasks to quote")
        state.update(state="quoted", approval=None)
        state["quoteHash"] = digest(state["quotes"])
        scope = {aid: {k: row[k] for k in ("operation", "region", "parametersHash")}
                 for aid, row in state["assets"].items() if row.get("parametersHash")}
        state["productionScopeHash"] = digest(scope)
        if (previous_approval and previous_approval.get("allowQuoteRefresh") and
                previous_approval.get("scopeHash") == state["productionScopeHash"] and
                previous_approval.get("planHash") == state["planHash"] and
                previous_approval.get("policyHash") == state["policyHash"]):
            ceilings = previous_approval.get("creditCeilings", {})
            reserved = {}
            known = True
            for aid, row in state["assets"].items():
                if row.get("taskId"):
                    # Reserve the quote actually committed on POST, not an
                    # obsolete per-asset estimate from the initial approval.
                    cost = row.get("submissionCredits", row.get("quotedCredits"))
                    if not isinstance(cost, (int, float)) or cost < 0:
                        known = False
                    else:
                        reserved[row["region"]] = reserved.get(row["region"], 0) + cost
            new_totals = {s["region"]: s["estimatedCredits"] for s in summaries}
            within = known and all(
                0 <= reserved.get(region, 0) + new_totals.get(region, 0) <= ceilings.get(region, -1)
                for region in set(reserved) | set(new_totals))
            if within:
                state["approval"] = {**previous_approval, "quoteHash": state["quoteHash"], "refreshedAt": now()}
                state["state"] = "authorized"
        state.pop("pendingQuoteRefreshAuthorization", None)
        save_run(run_dir, state)
        return {"ok": True, "planHash": state["planHash"], "quoteHash": state["quoteHash"],
                "approvalRetained": bool(state["approval"]), "quotes": summaries}


def approve(run_dir, actor, note, quote_hash=None, allow_quote_refresh=False):
    require(actor == "user" and isinstance(note, str) and note.strip(), "Record actual user approval with its evidence text")
    with locked(run_dir):
        state, plan = load_run(run_dir)
        if any(a.get("generation") for a in plan.get("assets", [])):
            require(state.get("quotes") and quote_hash == state.get("quoteHash"), "Approval must bind the current quote hash")
            require(state.get("quoteHash") == digest(state["quotes"]), "Quote receipt changed")
        state["approval"] = {"actor": actor, "evidence": note, "planHash": state["planHash"],
                             "quoteHash": state.get("quoteHash"), "policyHash": state["policyHash"], "recordedAt": now(),
                             "scopeHash": state.get("productionScopeHash"), "allowQuoteRefresh": allow_quote_refresh,
                             "assetCreditCeilings": {aid: row.get("quotedCredits") for aid, row in state["assets"].items() if row.get("parametersHash")},
                             "creditCeilings": {region: q.get("quote", {}).get("estimatedCreditsTotal", -1)
                                                for region, q in state["quotes"].items()}}
        state["state"] = "authorized"
        state.pop("pendingQuoteRefreshAuthorization", None)
        save_run(run_dir, state)
        return {"ok": True, "state": state["state"], "planHash": state["planHash"]}


def _check_approval(state):
    a = state.get("approval") or {}
    require(a.get("actor") == "user" and a.get("planHash") == state["planHash"] and
            a.get("quoteHash") == state.get("quoteHash") and a.get("policyHash") == state["policyHash"] and
            state.get("quoteHash") == digest(state["quotes"]),
            "Matching first-batch user confirmation is required")
    scope = {}
    for aid, row in state["assets"].items():
        if row.get("parametersHash"):
            require(row["parametersHash"] == digest(row["parameters"]), "Prepared request changed after quotation")
            scope[aid] = {k: row[k] for k in ("operation", "region", "parametersHash")}
    require(a.get("scopeHash") == digest(scope), "Production scope changed after confirmation")


def _canonical(source, project, plan=None, asset_id=None, owned_root=None):
    from .engines import name as engine_name, resource_path
    source = Path(source).resolve()
    project = Path(project).resolve()
    require(source.is_file(), "Missing completed asset")
    h = file_hash(source)
    if plan is not None and plan.get("workspace"):
        from . import layout
        require(asset_id, "Workspace publication needs stable asset identity")
        if owned_root is None:
            # Existing canonical inputs retain one copy and their source provenance.
            provenance = {"route": "reuse"}
            if engine_name(plan, project) == "unity" and not inside(source, project / "Assets"):
                from . import unity
                require(source.suffix.lower() == ".glb", "External Unity models must be self-contained GLB; qualify other formats and dependencies inside Assets first")
                dest = layout.asset_path(project, plan, asset_id, filename="model-" + h[:16] + ".glb")
                admitted = unity.admit_asset(project, source, dest)
                source = resolve_input(admitted["path"], project)
                provenance["admission"] = admitted
            record = {"path": str(source), "sha256": h, "role": "model", "provenance": provenance}
            layout.register_asset(project, plan, asset_id, record)
        else:
            require(inside(source, owned_root), "Generated output is outside this run's owned download directory")
            require(source.suffix.lower() == ".glb", "Publish a self-contained GLB")
            dest = layout.asset_path(project, plan, asset_id, filename="model-" + h[:16] + ".glb")
            with locked(dest.parent):
                if dest.exists():
                    require(file_hash(dest) == h, "Canonical asset content-hash collision; preserve both inputs")
                    if source != dest:
                        source.unlink()  # Only the verified duplicate in this run's owned download tree.
                else:
                    ensure_directory(dest.parent)
                    os.rename(source, dest)  # Never silently copy a large model or cross a filesystem.
                    require(file_hash(dest) == h, "Canonical publication failed integrity verification")
            source = dest
            asset = next(a for a in plan["assets"] if a["id"] == asset_id)
            generation = asset.get("generation", {})
            layout.register_asset(project, plan, asset_id, {"path": str(dest), "sha256": h, "role": "model",
                "provenance": {"provider": "lux3d", "operation": generation.get("operation"),
                               "model_version": generation.get("parameters", {}).get("version"), "route": asset["route"]}})
        return {"path": resource_path(source, project, plan), "sha256": h}
    if engine_name(plan, project) == "unity" and not inside(source, project / "Assets"):
        from . import unity
        require(source.suffix.lower() == ".glb", "External Unity models must be self-contained GLB; qualify other formats and dependencies inside Assets first")
        return unity.admit_asset(project, source, project / "Assets/Art/Greybox/shared/assets" / h / "source.glb")
    if inside(source, project):
        return {"path": resource_path(source, project, plan), "sha256": h}
    require(source.suffix.lower() == ".glb", "External assets must be self-contained GLB; import scene/sidecar dependencies explicitly")
    dest = project / "art" / "assets" / "sha256" / h / "source.glb"
    if dest.exists():
        require(file_hash(dest) == h, "Canonical store collision")
    else:
        ensure_directory(dest.parent)
        shutil.copy2(source, dest)
        require(file_hash(dest) == h, "Canonical asset copy failed verification")
    return {"path": resource_path(dest, project, plan), "sha256": h}


def _fetch_paths(result):
    found = []
    def visit(v):
        if isinstance(v, dict):
            for k, item in v.items():
                if k in ("path", "localPath", "local_path", "file") and isinstance(item, str) and Path(item).suffix.lower() == ".glb" and Path(item).is_file():
                    found.append(item)
                elif k not in ("url", "urls"):
                    visit(item)
        elif isinstance(v, list):
            for item in v:
                visit(item)
    visit(result)
    return list(dict.fromkeys(found))


def _require_quote_current(row, quotes):
    """Cheap rejection before image scans, and rechecked immediately before POST."""
    q = quotes.get(row.get("region"), {}).get("quote", {})
    require(row.get("quoteId") == q.get("quoteId"), "Prepared quote ID changed")
    expiry = q.get("expiresAt")
    if expiry:
        if isinstance(expiry, (int, float)):
            stamp = expiry / 1000 if expiry > 1e11 else expiry
        else:
            parsed = datetime.fromisoformat(str(expiry).replace("Z", "+00:00"))
            require(parsed.tzinfo is not None, "Quote expiry needs a timezone")
            stamp = parsed.timestamp()
        require(datetime.now(timezone.utc).timestamp() < stamp,
                "Quote expired; run quote. Explicitly authorized within-budget refresh retains approval")


def run(run_dir, godot_path=None, style=None, bridge=None, adapter=None, recovery=False):
    # CLI paths are relative to the caller, while the adapter resolves resources
    # relative to the project. Canonicalize before crossing that boundary.
    run_dir = Path(run_dir).resolve()
    if bridge is None:
        from . import lux as bridge
    with locked(run_dir):
        if not recovery:
            # This is rejection only. Full source/approval checks still follow;
            # recovery must remain available for already submitted tasks.
            preview = read(run_dir / "run.json")
            for row in preview.get("assets", {}).values():
                if row.get("state") == "quoted" and not row.get("taskId"):
                    _require_quote_current(row, preview.get("quotes", {}))
        state, plan = load_run(run_dir, check_inputs=not recovery)
        if adapter is None:
            from . import engines
            adapter = engines.adapter(plan, state["project"])
        require(not plan.get("_recovery_plan_missing"), "Frozen production plan unavailable; status, reconcile and safe rollback remain available")
        stale = False
        if recovery:
            try:
                load_run(run_dir)
            except (WorkflowError, OSError, ValueError):
                stale = True
        require(state["state"] not in ("rolled_back", "rollback_conflict"), "Run was rolled back; create a new run")
        operational_blocker = None
        if not stale and plan.get("purpose", "production") != "technical_fixture":
            try:
                # Recovery separates immutable creative/source integrity from
                # refreshable host facts. Neither permits new work when blocked.
                _check_workflow_gate(run_dir, state, plan, require_current_capabilities=not recovery)
            except (WorkflowError, ValueError, OSError):
                if not recovery:
                    raise
                stale = True  # Recover already submitted tasks, never new production.
            if recovery and not stale:
                readiness = readiness_status(run_dir, state, plan)
                if readiness["state"] != "current":
                    operational_blocker = readiness
        legacy_layout = plan.get("purpose", "production") == "production" and not plan.get("workspace")
        require(not legacy_layout or recovery, "Legacy production paths are recovery-only; register a case/style workspace for a new approved run")
        stale = stale or legacy_layout
        recover_only = stale or operational_blocker is not None
        pending, failures = [], []
        for asset in plan.get("assets", []):
            aid = asset["id"]
            if asset.get("source", {}).get("path") and not asset.get("generation"):
                if recover_only:
                    continue
                state["assets"][aid] = {"state": "ready", "artifact": _canonical(resolve_input(asset["source"]["path"], state["project"]), Path(state["project"]), plan, aid)}
                continue
            g = asset.get("generation")
            if not g:
                continue
            row = state["assets"].get(aid, {})
            if row.get("state") in ("submitting", "unknown"):
                failures.append({"asset": aid, "state": row["state"], "reason": "Reconcile the original task ID; never resubmit"})
                continue
            if row.get("state") in ("failed", "cancelled", "rejected", "partial"):
                failures.append({"asset": aid, "state": row["state"], "reason": "Inspect result; revised task/selection and current authorization are required"})
                continue
            if row.get("state") == "ready":
                require(file_hash(resolve_input(row["artifact"]["path"], state["project"])) == row["artifact"]["sha256"], "Completed asset changed")
                continue
            if not row.get("taskId"):
                if recover_only:
                    failures.append({"asset": aid,
                        "state": "blocked_stale" if stale else "blocked_readiness",
                        "reason": "Source drift blocks new submission; existing tasks can recover" if stale else
                                  "Refresh current capabilities before new submission; existing tasks can recover"})
                    continue
                _check_approval(state)
                require(g.get("operation") != "text_to_3d", "This skill cannot submit text-to-3D; revise to an approved image-conditioned route")
                if plan.get("purpose", "production") != "technical_fixture":
                    _check_generation_reference(asset, state["project"])
                require(row.get("state") == "quoted", "Quote the actual request before submitting")
                from . import character_gate
                try:
                    preflight = character_gate.require_preflight("lux3d", row["operation"], row["parameters"],
                        run_dir, aid, preflight=g.get("character_preflight"), base=state["project"])
                    if preflight is not None:
                        row["character_preflight"] = preflight
                except (ValueError, OSError, KeyError, TypeError) as error:
                    failures.append({"asset": aid, "state": "operationally_blocked", "reason": str(error)})
                    continue
                _require_quote_current(row, state["quotes"])
                if plan.get("purpose", "production") == "production":
                    from .production_control import guard_submission
                    try:
                        guard_submission(state["project"], plan, aid, row["operation"], run_dir,
                                         digest({"operation": row["operation"], "parameters": row["parameters"]}))
                    except (ValueError, OSError, KeyError, TypeError) as error:
                        failures.append({"asset": aid, "state": "operationally_blocked", "reason": str(error)})
                        continue
                row["state"] = "submitting"
                row["submissionCredits"] = row.get("quotedCredits")
                state["assets"][aid] = row
                save_run(run_dir, state)
                try:
                    result = bridge.submit(row["operation"], row["parameters"], row["region"], quote_id=row["quoteId"])
                    task_id = result.get("taskId")
                    require(task_id is not None, "Provider did not return a task ID")
                    row.update(taskId=task_id, state="submitted", submittedAt=now())
                    save_run(run_dir, state)
                except Exception as error:
                    definite = hasattr(error, "unknown_submission") and not error.unknown_submission
                    row["state"] = "rejected" if definite else "unknown"
                    save_run(run_dir, state)
                    raise WorkflowError(("Submission rejected for " + aid + "; inspect and re-quote the corrected request") if definite else
                                        ("Submission outcome uncertain for " + aid + "; never resubmit automatically")) from None
            result = bridge.status(row["taskId"], row["region"])
            row["lastStatus"] = result
            row["lastCheckedAt"] = now()
            data = result.get("data", result)
            status = data.get("status", result.get("status"))
            if status in (4, 5, 6, "failed", "FAILED", "cancelled", "CANCELLED"):
                row["state"] = "cancelled" if status in (6, "cancelled", "CANCELLED") else "failed"
                save_run(run_dir, state)
                failures.append({"asset": aid, "state": row["state"], "reason": "Paid retries require a revised approved task"})
                continue
            if status not in (3, "success", "succeeded", "SUCCEEDED"):
                pending.append(aid)
                save_run(run_dir, state)
                continue
            row["state"] = "completed"
            save_run(run_dir, state)
            try:
                fetched = bridge.fetch(row["taskId"], row["region"], str(Path(run_dir) / "downloads" / aid),
                                       accepted_request={"operation": row["operation"], "parameters": row["parameters"]})
            except Exception as error:
                row.update(state="download_failed", lastError=type(error).__name__)
                failures.append({"asset": aid, "state": row["state"], "reason": "Resume retries download only"})
                save_run(run_dir, state)
                continue
            paths = _fetch_paths(fetched)
            row["download"] = fetched
            if not fetched.get("ok", True) or fetched.get("state") == "partial" or len(paths) != 1:
                row.update(state="partial" if paths else "download_failed")
                failures.append({"asset": aid, "state": row["state"], "reason": "Keep all outputs; select one complete GLB explicitly in a revised reuse plan"})
                save_run(run_dir, state)
                continue
            row.update(state="ready", artifact=_canonical(paths[0], Path(state["project"]), plan, aid, owned_root=Path(run_dir) / "downloads"), download=fetched)
            save_run(run_dir, state)
        if stale:
            state["state"] = "source_changed_recovered"
            save_run(run_dir, state)
            return {"ok": False, "state": state["state"], "pending": pending, "failures": failures,
                    "blockers": blocker_actions(state), "next": "revise_reusing_recovered_results"}
        if operational_blocker is not None:
            state["state"] = "readiness_blocked_recovered"
            save_run(run_dir, state)
            return {"ok": False, "state": state["state"], "pending": pending, "failures": failures,
                    "blockers": blocker_actions(state), "operationalReadiness": operational_blocker,
                    "next": "refresh-readiness", "resume": "same-run"}
        targets = [s["id"] for s in plan["styles"]]
        require(style is None or style in targets, "Unknown style")
        changed, blocked_styles = False, {}
        for sid in ([style] if style else targets):
            # Each style consumes only its own effective sources. Unready siblings
            # do not stop already-ready styles; complete-scope acceptance is separate.
            if plan.get("purpose", "production") == "production" and sid not in state["artifacts"]:
                from .production_control import guard_style
                try:
                    guard_style(state["project"], plan, sid)
                except (ValueError, OSError, KeyError, TypeError) as error:
                    blocked_styles[sid] = ["operational_control: " + str(error)]
                    continue
            resolved = json.loads(json.dumps(plan))
            effective = []
            missing = set()
            for original in resolved["bindings"]:
                b = json.loads(json.dumps(original))
                b.update(b.pop("styles", {}).get(sid, {}))
                source = b["source"]
                if source.get("asset_id"):
                    aid = source["asset_id"]
                    if state["assets"].get(aid, {}).get("state") != "ready":
                        missing.add(aid)
                    else:
                        source.pop("asset_id")
                        source.update(state["assets"][aid]["artifact"])
                effective.append(b)
            if missing:
                blocked_styles[sid] = sorted(missing)
                continue
            resolved["bindings"] = effective
            existing = state["artifacts"].get(sid)
            if existing:
                for item in existing.get("owned_files", []):
                    require(Path(item["path"]).is_file() and file_hash(item["path"]) == item["sha256"],
                            "Owned art changed; preserve manual edits and create a revised run")
                continue
            artifact = adapter.assemble(state["project"], str(run_dir), resolved, sid, godot_path=godot_path)
            changed = True
            state["artifacts"][sid] = artifact
            files = {f["path"]: f for f in state["ownedFiles"]}
            for f in artifact.get("owned_files", []):
                if plan.get("workspace"):
                    from . import layout
                    if f.get("retention") == "canonical_tool" and f.get("role") == "tool":
                        layout.validate_output(state["project"], plan, f["path"], "tool")
                    else:
                        layout.validate_output(state["project"], plan, f["path"], "runtime", style_id=sid)
                        require(f.get("retention") == "canonical_revision", "Formal revision ownership must retain its immutable source files")
                else:
                    from . import engines
                    if engines.name(plan, state["project"]) == "unity":
                        engines.validate_unity_owned(state["project"], plan, sid, artifact, f)
                    else:
                        require(inside(f["path"], run_dir), "Adapter attempted ownership outside this run")
                files[f["path"]] = f
            state["ownedFiles"] = list(files.values())
            state["validation"].pop(sid, None)
            save_run(run_dir, state)
        needs_import = changed or not state.get("import", {}).get("passed", True)
        if state["artifacts"] and needs_import and hasattr(adapter, "import_resources"):
            imported = adapter.import_resources(state["project"], godot_path=godot_path)
            state["import"] = imported
            save_run(run_dir, state)
            require(imported.get("passed", False), "Native resource import failed; see the persisted import log before retry")
        if failures:
            state["state"] = "partial_failure"
        elif pending or blocked_styles:
            state["state"] = "waiting_provider"
        elif changed or state["state"] not in ("validated", "technical_validated", "partially_validated", "validation_failed", "gameplay_unverified"):
            state["state"] = "assembled"
        save_run(run_dir, state)
        if plan.get("workspace"):
            from . import layout
            for sid, artifact in state["artifacts"].items():
                dev_files = _workspace_files(artifact)
                dev_receipt = {"schema": 1, "kind": "greybox-development", "style_id": sid,
                               "plan_hash": state["planHash"], "run_dir": str(run_dir), "files": dev_files}
                dev_path = run_dir / "navigation-receipts" / (sid + "-dev-" + digest(dev_receipt) + ".json")
                if not dev_path.exists():
                    write(dev_path, dev_receipt)
                layout.update_pointer(state["project"], plan, sid, "development", artifact["entry_scene"], dev_files,
                                      state["planHash"], proof={"path": str(dev_path), "sha256": file_hash(dev_path)})
        return {"ok": not failures, "state": state["state"], "styles": list(state["artifacts"]),
                "pending": pending, "failures": failures, "blockedStyles": blocked_styles,
                "blockers": blocker_actions(state), "unchanged": not changed,
                "next": "resolve_blockers" if failures else ("resume_after_provider_wait" if pending or blocked_styles else ("play" if state["state"] == "validated" else "validate"))}


def reconcile(run_dir, asset_id, task_id, note):
    require(note.strip(), "Reconciliation needs provider evidence")
    with locked(run_dir):
        state, _ = load_run(run_dir, check_inputs=False)
        row = state["assets"].get(asset_id, {})
        require(row.get("state") in ("unknown", "submitting"), "Only uncertain submissions may be reconciled")
        require(task_id, "Recover an existing provider task ID; this action never creates another task")
        row.update(taskId=task_id, state="submitted", reconciliation={"evidence": note, "recordedAt": now()})
        save_run(run_dir, state)
        return {"ok": True, "asset": asset_id, "state": row["state"]}


def validate(run_dir, godot_path=None, style=None, adapter=None):
    run_dir = Path(run_dir).resolve()
    with locked(run_dir):
        state, plan = load_run(run_dir)
        if adapter is None:
            from . import engines
            adapter = engines.adapter(plan, state["project"])
        require(state["state"] not in ("rolled_back", "rollback_conflict"), "Rolled-back art cannot be validated")
        require(state["artifacts"], "Assemble first")
        for sid in ([style] if style else list(state["artifacts"])):
            require(sid in state["artifacts"], "Style has not been assembled")
            artifact = state["artifacts"][sid]
            for f in artifact.get("owned_files", []):
                require(Path(f["path"]).is_file() and file_hash(f["path"]) == f["sha256"], "Art files changed; old assembly is stale")
            result = adapter.validate(state["project"], artifact, str(run_dir / "evidence" / sid), godot_path=godot_path)
            if sid in state["validation"]:
                state.setdefault("validationHistory", []).append({"style": sid, **state["validation"][sid]})
            state["validation"][sid] = {"result": result, "planHash": state["planHash"],
                "inputHash": state["inputs"]["sha256"], "recordedAt": now()}
            save_run(run_dir, state)
        coverage = validation_coverage(state, plan)
        state["coverage"] = coverage
        if not coverage["technical_passed"]:
            state["state"] = "validation_failed"
        elif not coverage["scope_complete"]:
            state["state"] = "partially_validated"
        elif coverage["validation_mode"] == "technical_only":
            state["state"] = "technical_validated"
        elif not coverage["gameplay_passed"]:
            state["state"] = "gameplay_unverified"
        else:
            state["state"] = "validated"
        if plan.get("purpose") == "art_proxy" and state["state"] in ("validated", "technical_validated"):
            state["state"] = "proxy_validated"
        save_run(run_dir, state)
        if plan.get("workspace"):
            for sid in ([style] if style else list(state["artifacts"])):
                _workspace_verified_pointer(run_dir, state, plan, sid)
        return {"ok": coverage["scope_complete"] and coverage["technical_passed"] and (coverage["validation_mode"] == "technical_only" or coverage["gameplay_passed"]),
                "state": state["state"], "coverage": coverage, "results": state["validation"],
                "artAcceptance": "pending-human-review", "delivery": "not-accepted"}


def play(run_dir, style, godot_path=None, adapter=None):
    state, plan = load_run(run_dir)
    if adapter is None:
        from . import engines
        adapter = engines.adapter(plan, state["project"])
    require(state["state"] not in ("rolled_back", "rollback_conflict"), "Rolled-back art cannot be launched")
    require(style in state["artifacts"], "Assemble this style first")
    return adapter.launch(state["project"], state["artifacts"][style], godot_path=godot_path)


def rollback(run_dir):
    with locked(run_dir):
        state, plan = load_run(run_dir, check_inputs=False)
        removed, conflicts, retained = [], [], []
        owned = {f["path"]: f for f in state["ownedFiles"]}
        for journal in Path(run_dir).glob("*/ownership.json"):
            if not journal.is_symlink():
                for f in read(journal).get("files", []):
                    owned.setdefault(f["path"], f)
        for item in sorted(owned.values(), key=lambda x: len(x["path"]), reverse=True):
            p = Path(item["path"])
            if not plan.get("workspace") and item.get("retention") in {"canonical_revision", "canonical_tool"}:
                from . import engines
                if engines.name(plan, state["project"]) == "unity":
                    matches = [(sid, artifact) for sid, artifact in state.get("artifacts", {}).items()
                               if item in artifact.get("owned_files", [])]
                    require(matches, "Canonical Unity rollback file has no bound artifact owner")
                    sid, artifact = matches[0]
                    engines.validate_unity_owned(state["project"], plan, sid, artifact, item)
                    retained.append(str(p))
                    continue
            if plan.get("workspace") and item.get("retention") == "canonical_tool" and item.get("role") == "tool":
                from . import layout
                layout.validate_output(state["project"], plan, p, "tool")
                retained.append(str(p))
                continue
            if plan.get("workspace") and item.get("retention") == "canonical_revision":
                from . import layout
                candidates = [s["id"] for s in plan["styles"] if inside(p, layout.runtime_root(state["project"], plan, s["id"]))]
                require(len(candidates) == 1, "Canonical rollback file is outside its registered style runtime")
                retained.append(str(p))
                continue
            require(inside(p, run_dir), "Ownership outside run directory")
            if not p.exists():
                continue
            if not p.is_file() or file_hash(p) != item["sha256"]:
                conflicts.append(str(p))
                continue
            try:
                p.unlink()
                removed.append(str(p))
            except OSError:
                conflicts.append(str(p))
        state["state"] = "rollback_conflict" if conflicts else "rolled_back"
        if state["validation"]:
            state.setdefault("validationHistory", []).append({"invalidatedAt": now(), "reason": "rollback", "results": state["validation"]})
            state["validation"] = {}
        state["approval"] = None
        state.pop("pendingQuoteRefreshAuthorization", None)
        state["events"].append({"type": "rollback", "at": now(), "removed": removed, "conflicts": conflicts, "retainedCanonical": retained})
        save_run(run_dir, state)
        if plan.get("workspace"):
            from . import layout
            layout.rollback_development(state["project"], plan, run_dir)
        return {"ok": not conflicts, "state": state["state"], "removed": removed, "preservedConflicts": conflicts,
                "retainedCanonical": retained}


def status(run_dir):
    state, plan = load_run(run_dir, check_inputs=False)
    stale, health = None, []
    if plan.get("_recovery_plan_missing"):
        health.append({"code": "FROZEN_PLAN_UNAVAILABLE", "action": "inspect_saved_journal_or_safe_rollback"})
    try:
        load_run(run_dir)
    except (WorkflowError, OSError, ValueError) as error:
        stale = str(error)
    if state["state"] not in ("rolled_back", "rollback_conflict"):
        for artifact in state.get("artifacts", {}).values():
            for item in artifact.get("owned_files", []) + artifact.get("sources", []):
                p = Path(item["path"])
                if not p.is_file() or file_hash(p) != item["sha256"]:
                    health.append({"code": "ARTIFACT_OR_SOURCE_DRIFT", "path": str(p)})
        for entry in state.get("validation", {}).values():
            for item in entry.get("result", {}).get("evidence", []):
                p = Path(item["path"])
                if not p.is_file() or file_hash(p) != item["sha256"]:
                    health.append({"code": "EVIDENCE_DRIFT", "path": str(p)})
    if health:
        stale = stale or "Generated output or evidence changed; historical validation is not current"
    rolled = state["state"] in ("rolled_back", "rollback_conflict")
    from .delivery import acceptance_status
    final_acceptance = acceptance_status(run_dir, state, plan)
    return {"ok": True, "version": VERSION, "state": state["state"], "health": "stale" if stale else "current",
        "healthIssues": health, "planHash": state["planHash"], "approved": bool(state.get("approval")) and not stale,
        "stale": stale, "blockers": blocker_actions(state),
        "assets": {k: {p: v[p] for p in ("state", "taskId", "region", "operation", "lastCheckedAt") if p in v} for k, v in state["assets"].items()},
        "styles": [] if rolled else list(state["artifacts"]), "plannedStyles": [s["id"] for s in plan.get("styles", [])],
        "historicalStyles": list(state["artifacts"]) if rolled else [], "validation": list(state["validation"]),
        "operationalReadiness": readiness_status(run_dir, state, plan),
        "coverage": state.get("coverage", {}),
        "artAcceptance": "accepted" if final_acceptance["accepted"] else "pending-human-review",
        "delivery": "accepted" if final_acceptance["accepted"] else "not-accepted",
        "deliveryAcceptance": final_acceptance,
        **({"workspace": __import__("greybox.layout", fromlist=["read_navigation"]).read_navigation(state["project"], plan)} if plan.get("workspace") else {})}


def blocker_actions(state):
    policies = {
        "unknown": ("reconcile_existing_task", "operator", False),
        "submitting": ("reconcile_existing_task", "operator", False),
        "failed": ("inspect_and_revise_task", "agent_then_user_for_new_spend", True),
        "cancelled": ("inspect_and_revise_task", "agent_then_user_for_new_spend", True),
        "rejected": ("correct_request_and_requote", "agent_then_user", True),
        "partial": ("inspect_outputs_and_select_reuse", "agent", False),
        "download_failed": ("resume_download_only", "agent", False),
    }
    return [{"asset": aid, "code": row["state"].upper(), "action": policies[row["state"]][0],
             "actor": policies[row["state"]][1], "mayRequireNewSpend": policies[row["state"]][2],
             "taskId": row.get("taskId")}
            for aid, row in state.get("assets", {}).items() if row.get("state") in policies]


def validation_coverage(state, plan):
    declared = plan.get("contract", {}).get("validation", {})
    steps = declared.get("steps", [])
    required = set(declared.get("required_checks", [s.get("id", s.get("name")) for s in steps if s.get("expect")]))
    planned = {s["id"] for s in plan["styles"]}
    rows = state.get("validation", {})
    technical = bool(rows) and all(v["result"].get("passed") is True for v in rows.values())
    missing = {}
    gameplay = bool(rows) and bool(required)
    for sid, value in rows.items():
        result = value["result"]
        found = set(result.get("passed_check_ids", []))
        missing[sid] = sorted(required - found)
        gameplay = gameplay and result.get("gameplay_verified") is True and not missing[sid]
    return {"planned_styles": sorted(planned), "assembled_styles": sorted(state["artifacts"]),
        "validated_styles": sorted(rows), "missing_styles": sorted(planned - set(rows)),
        "scope_complete": planned == set(state["artifacts"]) == set(rows),
        "technical_passed": technical, "gameplay_passed": bool(gameplay and technical),
        "missing_checks": missing, "validation_mode": declared.get("mode", "playable")}
