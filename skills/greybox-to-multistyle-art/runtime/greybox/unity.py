"""Incremental Unity 6 URP adapter. Native success requires a bound JSON receipt.

Only the small bridge, art scene variant and generated art resources are written.
Source scenes, gameplay scripts, package caches and imported assets are never copied.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid
import stat

RUNTIME = Path(__file__).resolve().parents[1] / "unity"
GLTFAST_VERSION = "6.20.0"
URP_VERSION = "17.3.0"
BRIDGE_PATH = "Assets/GreyboxArtRuntime"
RECIPE_FIELDS = {
    "lighting": {"enabled", "light_path", "sun_energy", "sun_rotation", "color", "ambient_color", "ambient_energy", "fog_density", "fog_color", "exposure", "bloom"},
    "water": {"enabled", "position", "size", "color", "deep_color", "normal_texture", "shore_mask", "speed", "amplitude", "shore_width", "depth_distance", "roughness"},
    "grass": {"enabled", "bounds", "color", "count", "seed", "height", "width", "wind", "cull_distance", "chunk_size", "ground_y", "y", "density_mask", "mask_threshold", "exclude_rects", "exclusions"},
    "ground": {"enabled", "position", "size", "color", "secondary_color", "texture", "secondary_texture", "blend_mask", "tile_scale", "blend_scale"},
}


def _recipes(value):
    if isinstance(value, list):
        value = {row["type"]: {k: v for k, v in row.items() if k != "type"} for row in value}
    if not isinstance(value, dict) or set(value) - set(RECIPE_FIELDS):
        raise ValueError("Unity effects must use lighting/water/grass/ground recipes")
    result = json.loads(json.dumps(value, allow_nan=False))
    for kind, recipe in result.items():
        if not isinstance(recipe, dict) or set(recipe) - RECIPE_FIELDS[kind]:
            raise ValueError("Unsupported Unity " + kind + " recipe fields: " + str(sorted(set(recipe) - RECIPE_FIELDS[kind]) if isinstance(recipe, dict) else recipe))
        for key, item in recipe.items():
            if key in {"position", "sun_rotation"} and (not isinstance(item, list) or len(item) != 3):
                raise ValueError("Unity recipe " + key + " needs three coordinates")
            if key == "size" and (not isinstance(item, list) or len(item) != 2 or any(v <= 0 for v in item)):
                raise ValueError("Unity surface size needs two positive dimensions")
            if key == "bounds" and (not isinstance(item, list) or len(item) != 4 or item[2] <= item[0] or item[3] <= item[1]):
                raise ValueError("Unity grass bounds need xmin,zmin,xmax,zmax with positive area")
        if kind == "lighting":
            if "exposure" in recipe:
                if not isinstance(recipe["exposure"], (int, float)) or recipe["exposure"] <= 0:
                    raise ValueError("Common exposure is a positive brightness multiplier (1 is neutral)")
                recipe["exposure"] = math.log2(recipe["exposure"])
            if isinstance(recipe.get("bloom"), bool):
                recipe["bloom"] = .25 if recipe["bloom"] else 0
        if kind == "grass":
            if "y" in recipe:
                if "ground_y" in recipe and recipe["ground_y"] != recipe["y"]:
                    raise ValueError("Unity grass y/ground_y disagree")
                recipe["ground_y"] = recipe.pop("y")
            if "exclude_rects" in recipe:
                recipe["exclusions"] = [{"bounds": row} for row in recipe.pop("exclude_rects")]
            for item in recipe.get("exclusions", []):
                bounds = item.get("bounds", [])
                if len(bounds) != 4 or bounds[2] < bounds[0] or bounds[3] < bounds[1]:
                    raise ValueError("Unity grass exclusion rectangles need ordered xmin,zmin,xmax,zmax")
    return result


def digest(path):
    hasher = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _asset_metadata(path):
    value = Path(path).stat()
    result = {"size": value.st_size, "mode": stat.S_IMODE(value.st_mode), "mtime_ns": value.st_mtime_ns}
    if sys.platform == "darwin":
        result.update(uid=value.st_uid, gid=value.st_gid, flags=value.st_flags)
        names = subprocess.run(["/usr/bin/xattr", str(path)], check=True, capture_output=True, text=True).stdout.splitlines()
        result["xattrs"] = {name: "".join(subprocess.run(["/usr/bin/xattr", "-px", name, str(path)], check=True, capture_output=True, text=True).stdout.split()) for name in sorted(names)}
    return result


def _apfs_clone(source, target):
    import ctypes
    import errno
    if sys.platform != "darwin":
        raise OSError(errno.ENOTSUP, "APFS clonefile is unavailable on this platform")
    libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
    clone = libc.clonefile
    clone.argtypes, clone.restype = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_int], ctypes.c_int
    if clone(os.fsencode(source), os.fsencode(target), 0) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), str(target))


def admit_asset(project, source, destination, *, max_copy_bytes=64*1024*1024,
                max_total_copy_bytes=256*1024*1024, require_clone=False):
    """Admit a canonical external asset without a project/asset-tree snapshot.

    Source content stays immutable. APFS clones share blocks with independent
    future writes; other filesystems may copy only within explicit small limits.
    Canonical destinations are ordinary project files, portable to Unity imports
    and Players. No mutable hard link or unsupported external symlink is created.
    """
    from .core import locked
    root = Path(project).resolve()
    with locked(root / "art/asset-admission"):
        return _admit_asset(root, source, destination, max_copy_bytes=max_copy_bytes,
                            max_total_copy_bytes=max_total_copy_bytes, require_clone=require_clone)


def _admit_asset(project, source, destination, *, max_copy_bytes, max_total_copy_bytes, require_clone):
    import errno
    root = Path(project).resolve()
    source = Path(source).expanduser()
    source = (source if source.is_absolute() else root / source).resolve()
    target = project_path(root, destination, assets_only=True)
    if not source.is_file():
        raise ValueError("Canonical Unity asset source is missing: " + str(source))
    if target.is_symlink():
        raise ValueError("Unity asset admission requires an owned regular destination")
    expected = digest(source)
    metadata = _asset_metadata(source)
    ledger_path = root / "art/asset-admission.json"
    ledger = _json(ledger_path) if ledger_path.is_file() else {"schema": 1, "assets": []}
    previous = next((row for row in ledger["assets"] if row["path"] == resource(root, target)), None)
    if target.exists():
        if digest(target) != expected:
            raise ValueError("Refusing to overwrite changed Unity asset: " + str(target))
        if previous and previous["sha256"] != expected:
            raise ValueError("Unity admission provenance changed; preserve the prior version and choose another destination")
        return previous or {"path": resource(root, target), "sha256": expected, "bytes": source.stat().st_size,
                            "method": "existing-content-verified", "provenance": {"original_source": str(source), "canonical_source": str(target), "manifest": str(ledger_path)}}
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.with_name(target.name + "." + uuid.uuid4().hex + ".admitting")
    before = shutil.disk_usage(root).free
    clone_error = None
    try:
        try:
            _apfs_clone(source, staging)
            method = "apfs-clonefile"
        except OSError as exc:
            clone_error = str(exc)
            if staging.exists():
                staging.unlink()
            unsupported = {errno.EXDEV, errno.ENOTSUP, errno.EINVAL, errno.ENOSYS, getattr(errno, "EOPNOTSUPP", errno.ENOTSUP)}
            if require_clone or exc.errno not in unsupported:
                raise ValueError("Verified asset clone unavailable; no copy fallback was taken: " + clone_error) from exc
            copied = sum(row["bytes"] for row in ledger["assets"] if row.get("method") == "bounded-copy")
            if metadata["size"] > max_copy_bytes or copied + metadata["size"] > max_total_copy_bytes:
                raise ValueError("Asset admission would exceed bounded-copy limits; place/reuse the canonical asset on a clone-capable project volume or explicitly configure a measured transfer") from exc
            shutil.copy2(source, staging)
            method = "bounded-copy"
        if digest(staging) != expected or _asset_metadata(staging) != metadata:
            raise ValueError("Admitted Unity asset content/metadata verification failed")
        if staging.stat().st_ino == source.stat().st_ino and staging.stat().st_dev == source.stat().st_dev:
            raise ValueError("Admitted Unity asset must have an independent inode")
        os.replace(staging, target)
        row = {"path": resource(root, target), "sha256": expected, "bytes": metadata["size"], "method": method,
               "provenance": {"original_source": str(source), "canonical_source": str(target), "manifest": str(ledger_path),
                              "original_metadata": metadata, "admitted_metadata": _asset_metadata(target),
                              "clone_error": clone_error, "filesystem_available_before": before,
                              "filesystem_available_after": shutil.disk_usage(root).free}}
        ledger["assets"].append(row)
        _json(ledger_path, ledger)
        return row
    finally:
        if staging.exists():
            staging.unlink()


def _json(path, data=None):
    path = Path(path)
    if data is None:
        return json.loads(path.read_text(encoding="utf-8"))
    from .core import write
    write(path, data)
    return data


def engine(executable=None, project=None):
    version = None
    if project:
        version_file = Path(project) / "ProjectSettings/ProjectVersion.txt"
        if version_file.is_file():
            match = re.search(r"^m_EditorVersion:\s*(\S+)", version_file.read_text(encoding="utf-8"), re.M)
            version = match.group(1) if match else None
    candidates = [executable, os.environ.get("UNITY_BIN"), shutil.which("Unity"), shutil.which("unity")]
    versions = [version] if version else []
    hub_roots = [Path("/Applications/Unity/Hub/Editor"), Path.home() / "Applications/Unity/Hub/Editor",
                 Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "Unity/Hub/Editor"]
    for hub in hub_roots:
        if not version and hub.is_dir():
            versions = sorted([p.name for p in hub.iterdir() if p.is_dir()], reverse=True)
        for item in versions:
            candidates += [hub / item / "Unity.app/Contents/MacOS/Unity", hub / item / "Editor/Unity.exe"]
    for value in candidates:
        if not value:
            continue
        candidate = Path(value).expanduser()
        if candidate.suffix == ".app":
            candidate = candidate / "Contents/MacOS/Unity"
        if candidate.is_file():
            return str(candidate.resolve())
    raise ValueError("Unity Editor unavailable for the recorded project version; configure UNITY_BIN or executable")


def project_path(project, value, assets_only=False):
    root = Path(project).resolve()
    value = str(value)
    if value.startswith("res://"):
        raise ValueError("Unity resources use Assets/ or Packages/ paths, never res://")
    path = Path(value)
    lexical = path if path.is_absolute() else root / path
    canonical = lexical.resolve()
    if not canonical.is_relative_to(root):
        raise ValueError("Unity output/resource must be inside the project: " + value)
    if assets_only and not canonical.is_relative_to(root / "Assets"):
        raise ValueError("Unity scene/runtime outputs must be inside Assets/: " + value)
    return canonical


def resource(project, path):
    return project_path(project, path).relative_to(Path(project).resolve()).as_posix()


def inspect(project, executable=None):
    root = Path(project).resolve()
    version = root / "ProjectSettings/ProjectVersion.txt"
    manifest = root / "Packages/manifest.json"
    if not version.is_file() or not manifest.is_file() or not (root / "Assets").is_dir():
        raise ValueError("Expected an existing Unity project with Assets, Packages/manifest.json and ProjectSettings/ProjectVersion.txt")
    text = version.read_text(encoding="utf-8")
    match = re.search(r"^m_EditorVersion:\s*(\S+)", text, re.M)
    packages = _json(manifest).get("dependencies", {})
    build = root / "ProjectSettings/EditorBuildSettings.asset"
    scenes = []
    if build.is_file():
        scenes = re.findall(r"^\s*path:\s*(Assets/[^\r\n]+\.unity)\s*$", build.read_text(encoding="utf-8"), re.M)
    result = {"engine": "unity", "project": str(root), "version": match.group(1) if match else None,
              "main_scene": scenes[0] if scenes else None, "build_scenes": scenes,
              "render_pipeline": "urp" if "com.unity.render-pipelines.universal" in packages else "unconfigured",
              "packages": packages, "project_sha256": digest(version),
              "coverage": "static inventory; native inspect resolves active pipeline, GUIDs, components and references"}
    try:
        result["executable"] = engine(executable, root)
    except ValueError as exc:
        result["engine_error"] = str(exc)
    return result


def dependency_snapshot(project, plan=None):
    """GUID closure plus code/settings and explicit dynamic inputs, excluding caches.

    Unity's native AssetDatabase closure is also recorded by the bridge. A static
    audit cannot discover computed Addressables/Resources loads: declare those in
    contract.source_paths. C#/shader/pipeline changes must invalidate evidence.
    """
    root = Path(project).resolve()
    plan = plan or {}
    contract = plan.get("contract", {})
    initial = []
    for directory in ("ProjectSettings", "Packages"):
        initial += [p for p in (root / directory).glob("*") if p.is_file()]
    guid_paths = {}
    for meta in (root / "Assets").rglob("*.meta"):
        match = re.search(r"^guid:\s*([a-f0-9]{32})", meta.read_text(errors="replace"), re.M)
        if match:
            guid_paths[match.group(1)] = meta.with_suffix("")
    # Include project scripts/shaders and their assemblies: serialized GUID closure
    # alone omits compile-time dependencies and dynamically loaded game logic.
    code = {".cs", ".asmdef", ".asmref", ".rsp"}
    initial += [p for p in (root / "Assets").rglob("*") if p.is_file() and p.suffix.lower() in code]
    if plan.get("include_resources"):
        # Unity adds Resources content even when no selected scene references it.
        initial += [p for p in (root / "Assets").rglob("*") if p.is_file() and "Resources" in p.relative_to(root / "Assets").parts[:-1]]
    scene = contract.get("scene") or inspect(root).get("main_scene")
    if scene:
        initial.append(project_path(root, scene))
    for scene in plan.get("build_scenes", contract.get("build_scenes", [])):
        initial.append(project_path(root, scene, assets_only=True))
    for path in contract.get("source_paths", []):
        initial.append(project_path(root, path))
    for binding in plan.get("bindings", []):
        sources = [binding.get("source", {})] + [v.get("source", {}) for v in binding.get("styles", {}).values()]
        initial += [project_path(root, s["path"]) for s in sources if s.get("path")]
    found, pending = {}, initial
    shader_types = {".shader", ".hlsl", ".cginc", ".compute", ".shadergraph", ".shadersubgraph"}
    text_types = {".unity", ".prefab", ".asset", ".mat", ".controller", ".overridecontroller", ".playable", ".meta"} | shader_types
    while pending:
        path = pending.pop().resolve()
        if str(path) in found:
            continue
        if not path.is_file():
            raise ValueError("Declared Unity source dependency is missing: " + str(path))
        found[str(path)] = {"path": str(path), "sha256": digest(path)}
        meta = path.with_name(path.name + ".meta")
        if meta.is_file() and str(meta) not in found:
            pending.append(meta)
        # BuildSettings is itself bound, but other selectable scenes are not
        # dependencies of the explicitly selected scene. Following its GUIDs
        # creates cyclic source closures between independently assembled styles.
        if path.suffix.lower() in text_types and path.name != "EditorBuildSettings.asset":
            text = path.read_text(encoding="utf-8", errors="replace")
            guids = re.findall(r"\bguid:\s*([a-f0-9]{32})", text)
            guids += re.findall(r'"guid"\s*:\s*"([a-f0-9]{32})"', text)
            if path.suffix.lower() in (".shadergraph", ".shadersubgraph"):
                # ShaderGraph embeds serialized texture/graph references inside
                # JSON strings as well as ordinary GUID-valued object fields.
                for literal in re.findall(r'"(?:\\.|[^"\\])*"', text):
                    if "guid" not in literal:
                        continue
                    try:
                        decoded = json.loads(literal)
                    except ValueError:
                        continue
                    guids += re.findall(r'"guid"\s*:\s*"([a-f0-9]{32})"', decoded)
            for guid in guids:
                dependency = guid_paths.get(guid)
                if dependency and dependency.is_file():
                    pending.append(dependency)
            if path.suffix.lower() in shader_types - {".shadergraph", ".shadersubgraph"}:
                code_text = re.sub(r"/\*.*?\*/|//[^\n]*", "", text, flags=re.S)
                for include in re.findall(r'^\s*#\s*include(?:_with_pragmas)?\s*[<"]([^>"\r\n]+)[>"]', code_text, re.M):
                    candidate = project_path(root, include if include.startswith(("Assets/", "Packages/")) else path.parent / include)
                    # Built-in and registry package includes are represented by
                    # the engine/package locks; project-local includes are bytes.
                    if candidate.is_file():
                        pending.append(candidate)
        if path.suffix.lower() == ".gltf":
            doc = _json(path)
            for item in doc.get("buffers", []) + doc.get("images", []):
                uri = item.get("uri", "")
                if uri and not uri.startswith("data:"):
                    from urllib.parse import unquote, urlparse
                    if urlparse(uri).scheme:
                        raise ValueError("Unity source glTF must use local dependencies: " + uri)
                    pending.append(project_path(root, path.parent / unquote(uri)))
    return sorted(found.values(), key=lambda row: row["path"])


def configure_packages(project, gltfast=True, urp=True):
    """Add missing pinned packages; never silently upgrade an existing project."""
    root = Path(project).resolve()
    path = root / "Packages/manifest.json"
    doc = _json(path)
    dependencies = doc.setdefault("dependencies", {})
    required = {}
    if gltfast:
        required["com.unity.cloud.gltfast"] = GLTFAST_VERSION
    if urp:
        required["com.unity.render-pipelines.universal"] = URP_VERSION
    changes = {}
    for name, version in required.items():
        if name not in dependencies:
            dependencies[name] = version
            changes[name] = version
    if changes:
        _json(path, doc)
    return {"changed": changes, "packages": dependencies, "lock_file": str(root / "Packages/packages-lock.json")}


def install_bridge(project):
    root = Path(project).resolve()
    target = root / BRIDGE_PATH
    marker = target / ".greybox-managed.json"
    previous = _json(marker).get("files", {}) if marker.is_file() else {}
    files = {str(p.relative_to(RUNTIME)).replace(os.sep, "/"): p for p in RUNTIME.rglob("*") if p.is_file()}
    for name, source in files.items():
        path = project_path(root, target / name, assets_only=True)
        if path.exists() and digest(path) != digest(source) and previous.get(name) != digest(path):
            raise ValueError("Bridge contains local changes; preserve them before upgrading: " + str(path))
    written, growth = [], 0
    for name, source in files.items():
        path = target / name
        if not path.exists() or digest(path) != digest(source):
            growth += source.stat().st_size - (path.stat().st_size if path.exists() else 0)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(source.read_bytes())
        written.append({"path": str(path), "sha256": digest(path), "role": "tool", "retention": "canonical_tool"})
    _json(marker, {"schema": 1, "version": "0.4.0-rc.1", "files": {name: digest(p) for name, p in files.items()}})
    return {"files": written, "additional_file_bytes": growth}


def _check_artifact(artifact):
    for row in artifact.get("owned_files", []) + artifact.get("sources", []):
        path = Path(row["path"])
        if not path.is_file() or digest(path) != row["sha256"]:
            raise ValueError("Unity artifact/source changed; reassemble before reusing native evidence: " + str(path))


def _check_owned_rebuild(project, previous, req):
    if req["operation"] != "assemble" or previous.get("output_root") != req["output_root"] or previous.get("binding_digest") != req["binding_digest"]:
        raise ValueError("Owned Unity rebuild requires identical assembly parameters and output_root; use a new revision for changed art")
    _check_artifact({"owned_files": previous.get("owned_files", [])})
    if not previous.get("owned_files") or previous.get("project") != str(Path(project).resolve()):
        raise ValueError("Owned Unity rebuild requires this project's recorded artifact ownership")


def _request(project, operation, config, output):
    root = Path(project).resolve()
    plan = config.get("plan", {})
    style = config.get("style_id") or config.get("style") or "default"
    style = style.get("id") if isinstance(style, dict) else style
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", str(style)):
        raise ValueError("Unity style ID must use 1–80 ASCII letters, digits, underscore or hyphen")
    artifact = config.get("artifact", {})
    contract = plan.get("contract") or artifact.get("contract", {})
    if artifact:
        _check_artifact(artifact)
    scene = config.get("scene") or artifact.get("entry_scene") or contract.get("scene") or inspect(root).get("main_scene")
    if operation not in ("fixture", "configure", "import") and (not scene or not project_path(root, scene).is_file()):
        raise ValueError("Declare an existing Unity scene in config.scene or plan.contract.scene")
    if scene:
        scene = resource(root, scene)
    build_scenes = []
    if operation == "export":
        declared = config.get("build_scenes", [scene])
        if not isinstance(declared, list) or not declared:
            raise ValueError("Unity build_scenes must be a nonempty list of existing Assets/*.unity scenes")
        for value in declared:
            path = project_path(root, value, assets_only=True)
            if not path.is_file() or path.suffix.lower() != ".unity":
                raise ValueError("Unity build_scenes requires existing Assets/*.unity scenes: " + str(value))
            normalized = resource(root, path)
            if normalized in build_scenes:
                raise ValueError("Unity build_scenes must not contain duplicates")
            build_scenes.append(normalized)
    output_root = config.get("output_root") or artifact.get("output_root") or "Assets/Art/Greybox/" + str(style)
    output_root = resource(root, project_path(root, output_root, assets_only=True))
    bindings = []
    seen = set()
    for row in plan.get("bindings", config.get("bindings", [])):
        binding = json.loads(json.dumps(row))
        binding.update(binding.pop("styles", {}).get(style, {}))
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", str(binding.get("id", ""))) or binding["id"] in seen:
            raise ValueError("Unity bindings require unique stable IDs")
        seen.add(binding["id"])
        for value in [binding.get("owner", "")] + binding.get("hide", []):
            if not value or str(value).startswith("/") or ".." in str(value).split("/"):
                raise ValueError("Unity owner/hide paths must be explicit scene hierarchy descendants")
        source = binding.setdefault("source", {})
        if binding.get("anchor_mode", "source") not in ("source", "bottom_center"):
            raise ValueError("Unity anchor_mode supports source/bottom_center")
        normalize = binding.get("normalize", {})
        if set(normalize) - {"mode", "space", "max_extent", "target_size"} or normalize.get("mode", "none") not in ("none", "uniform_bounds") or normalize.get("space", "world") != "world":
            raise ValueError("Unity normalization supports world uniform_bounds with max_extent or target_size")
        if normalize.get("target_size") is not None and (not isinstance(normalize["target_size"], list) or len(normalize["target_size"]) != 3 or any(not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0 for v in normalize["target_size"])):
            raise ValueError("Unity normalize.target_size needs three finite positive dimensions")
        if source.get("path"):
            source["path"] = resource(root, project_path(root, source["path"], assets_only=True))
        elif source.get("route") in ("reuse", "generated", "hybrid"):
            raise ValueError("Unity reuse/generated/hybrid bindings require source.path")
        bindings.append(binding)
    style_spec = config.get("style") if isinstance(config.get("style"), dict) else next((s for s in plan.get("styles", []) if isinstance(s, dict) and s.get("id") == style), {})
    recipes = _recipes(config.get("effects") or config.get("recipes") or style_spec.get("effects") or plan.get("effects") or plan.get("lookdev", {}).get("recipes") or plan.get("recipes") or {})
    validation_steps = []
    for index, step in enumerate(contract.get("validation", {}).get("steps", [])):
        if step.get("input_action") and not step.get("hook"):
            raise ValueError("Unity input_action requires an explicit gameplay hook handling that step")
        hook = step.get("hook", {})
        expected = []
        for key, value in step.get("expect", {}).items():
            kind = "null" if value is None else "bool" if isinstance(value, bool) else "number" if isinstance(value, (int, float)) else "string" if isinstance(value, str) else "json"
            expected.append({"key": key, "kind": kind, "json": json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                             "text": value if kind == "string" else "", "number": value if kind == "number" else 0,
                             "boolean": value if kind == "bool" else False})
        validation_steps.append({"id": str(step.get("id", step.get("name", index))), "raw_json": json.dumps(step),
                                 "hook_path": hook.get("node", hook.get("path", "")),
                                 "hook_method": hook.get("method", "GreyboxProbe"), "expectations": expected})
    req = {"schema": 1, "request_id": uuid.uuid4().hex, "operation": operation,
           "scene": scene or "", "output_root": output_root,
           "report": str(output / "report.json"), "evidence_root": str(output),
           "style": style, "bindings": bindings, "recipes": recipes,
           "binding_digest": artifact.get("binding_digest") or hashlib.sha256(json.dumps({"plan": plan, "recipes": recipes, "style": style}, sort_keys=True).encode()).hexdigest(),
           "width": config.get("width", 1280), "height": config.get("height", 720),
           "warmup_frames": config.get("warmup_frames", 8), "capture_frames": max(config.get("capture_frames", 3), 1+len(validation_steps)),
           "frame_stride": config.get("frame_stride", 8), "camera_path": config.get("camera_path", ""),
           "assertions": config.get("assertions", contract.get("assertions", [])), "validation_steps": validation_steps,
           "player_output": str(config.get("player_output", config.get("output", ""))),
           "build_target": config.get("build_target", ""), "build_scenes": build_scenes, "configure_pipeline": bool(config.get("configure_pipeline", False)),
           "import_paths": config.get("import_paths", []), "fixture": config.get("fixture", False)}
    if not 16 <= req["width"] <= 8192 or not 16 <= req["height"] <= 8192:
        raise ValueError("Unity capture dimensions must be within 16–8192 pixels")
    if not 1 <= req["capture_frames"] <= 300 or not 1 <= req["frame_stride"] <= 600 or not 0 <= req["warmup_frames"] <= 3600:
        raise ValueError("Unity capture frame limits exceeded")
    return req


def run(project, operation, config=None, output=None, unity_bin=None, timeout=300):
    """Execute native bridge. Never treats exit 0, a log line or stale report as success."""
    root = Path(project).resolve()
    config = config or {}
    inspect(root, unity_bin)
    if operation not in {"inspect", "assemble", "lookdev", "capture", "validate", "play", "export", "import", "fixture", "configure"}:
        raise ValueError("Unsupported Unity operation: " + operation)
    output = Path(output).resolve() if output else root / "art/greybox-native" / (operation + "-" + uuid.uuid4().hex[:12])
    if (output / "request.json").exists() or (output / "report.json").exists():
        output = output / (operation + "-" + uuid.uuid4().hex[:12])
    output.mkdir(parents=True, exist_ok=True)
    if config.get("configure_packages"):
        configure_packages(root)
    bridge = install_bridge(root)
    req = _request(root, operation, config, output)
    if config.get("rebuild_owned"):
        _check_owned_rebuild(root, config["rebuild_owned"], req)
        req["rebuild_owned"] = True
    source_inputs = config.get("artifact", {}).get("sources", [])
    if not config.get("artifact") and operation in ("capture", "validate", "play"):
        source_inputs = dependency_snapshot(root, config.get("plan") or {"contract": {"scene": req["scene"]}})
    if operation == "export":
        export_plan = json.loads(json.dumps(config.get("plan") or {"contract": config.get("artifact", {}).get("contract", {})}))
        export_plan.setdefault("contract", {})["scene"] = req["scene"]
        export_plan["build_scenes"] = req["build_scenes"]
        export_plan["include_resources"] = True
        # Every selected scene and its asset/shader closure is frozen before the
        # build, including additional scenes outside the primary art artifact.
        source_inputs = sorted({row["path"]: row for row in source_inputs + dependency_snapshot(root, export_plan)}.values(), key=lambda row: row["path"])
        req["frozen_source_paths"] = [resource(root, row["path"]) for row in source_inputs]
    request_path = output / "request.json"
    _json(request_path, req)
    # Each invocation has a new ID. A previous receipt can never satisfy a new request.
    command = [engine(unity_bin, root), "-batchmode", "-projectPath", str(root),
               "-executeMethod", "GreyboxArt.Editor.GreyboxBridge.Execute", "-greyboxRequest", str(request_path),
               "-logFile", str(output / "unity.log")]
    # No -nographics: capture/validation must exercise real graphics and PlayMode.
    timed_out = False
    started = time.monotonic()
    try:
        proc = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        exit_code = proc.returncode
        (output / "process.log").write_text((proc.stdout or "") + (proc.stderr or ""), encoding="utf-8")
    except subprocess.TimeoutExpired:
        timed_out, exit_code = True, None
    report_path = output / "report.json"
    result = _json(report_path) if report_path.is_file() else {"ok": False, "errors": ["Unity did not produce a native report; inspect unity.log for compile/license/runtime failure"]}
    errors = list(result.get("errors", []))
    for key in ("request_id", "operation", "binding_digest"):
        if result.get(key) != req[key]:
            errors.append("Native Unity receipt mismatch: " + key)
    if timed_out:
        errors.append("Native Unity invocation timed out; report does not certify a completed run")
    elif exit_code != 0:
        errors.append("Unity exited with status " + str(exit_code))
    if operation == "export" and result.get("build_scenes") != req["build_scenes"]:
        errors.append("Native Unity Player scene coverage mismatch")
    if operation == "export":
        frozen = {row["path"] for row in source_inputs}
        generated = {}
        producer = "com.unity.test-framework.performance"
        locked_version = _json(root / "Packages/packages-lock.json").get("dependencies", {}).get(producer, {}).get("version") if (root / "Packages/packages-lock.json").is_file() else None
        allowed = {"Assets/Resources/PerformanceTestRunInfo.json", "Assets/Resources/PerformanceTestRunSettings.json"}
        for item in result.get("generated_inputs", []):
            try:
                evidence_path = Path(item.get("evidence", "")).resolve()
                if item.get("path") not in allowed or item.get("producer") != producer or item.get("producer_version") != "3.5.0" or locked_version != "3.5.0":
                    raise ValueError("unsupported generated metadata producer/path")
                if not evidence_path.is_relative_to(output) or not evidence_path.is_file() or evidence_path.stat().st_size > 65536 or digest(evidence_path) != item.get("sha256") or not isinstance(_json(evidence_path), dict):
                    raise ValueError("generated metadata evidence is missing, invalid or changed")
                generated[str(project_path(root, item["path"], assets_only=True))] = item["sha256"]
            except (ValueError, TypeError, AttributeError) as exc:
                errors.append("Invalid Unity generated build input: " + str(exc))
        for packed in result.get("packed_sources", []):
            path = packed.get("path", "")
            if path.startswith("Assets/") and str(project_path(root, path, assets_only=True)) not in frozen | generated.keys():
                errors.append("Native Unity packed an unfrozen project source: " + path)
        try:
            # Import/build hooks can add shader includes or scripts which never
            # appear as packed assets. Re-discover the same closure after build.
            for row in dependency_snapshot(root, export_plan):
                if row["path"] in generated and row["sha256"] != generated[row["path"]]:
                    errors.append("Native Unity generated metadata changed after recording: " + row["path"])
                elif row["path"] not in frozen | generated.keys():
                    errors.append("Native Unity export discovered a new source dependency: " + row["path"])
        except ValueError as exc:
            errors.append("Native Unity export dependency closure changed: " + str(exc))
    if config.get("artifact"):
        try:
            _check_artifact(config["artifact"])
        except ValueError as exc:
            errors.append(str(exc))
    if operation == "export" or (not config.get("artifact") and operation in ("capture", "validate", "play")):
        try:
            _check_artifact({"sources": source_inputs})
        except ValueError as exc:
            errors.append(str(exc))
    evidence = []
    if operation in ("capture", "validate", "play"):
        import struct
        captures = result.get("captures", [])
        if len(captures) != req["capture_frames"]:
            errors.append("Native Unity capture coverage mismatch")
        for capture in captures:
            path = Path(capture.get("path", "")).resolve()
            if not path.is_relative_to(output) or not path.is_file():
                errors.append("Native Unity capture missing or outside attempt")
                continue
            header = path.read_bytes()[:24]
            if len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or struct.unpack(">II", header[16:24]) != (req["width"], req["height"]):
                errors.append("Invalid Unity capture PNG dimensions/content")
            elif digest(path) != capture.get("sha256"):
                errors.append("Unity capture hash mismatch")
            else:
                evidence.append({"path": str(path), "sha256": digest(path)})
    result.update(ok=bool(result.get("ok")) and not errors, errors=errors,
                  command=command, exit_code=exit_code, elapsed_seconds=round(time.monotonic() - started, 3),
                  report=str(report_path), log=str(output / "unity.log"), attempt_id=req["request_id"],
                  log_path=str(output / "unity.log"), native_report_path=str(report_path),
                  native_errors=list(result.get("errors", [])), returncode=exit_code, evidence=evidence,
                  source_hashes=source_inputs,
                  artifact_hashes=config.get("artifact", {}).get("owned_files", []), bridge=bridge)
    result["passed"] = result["ok"]
    if operation in ("assemble", "lookdev") and result["ok"]:
        sources = dependency_snapshot(root, config.get("plan") or {"contract": {**config.get("artifact", {}).get("contract", {}), "scene": req["scene"]}})
        owned = list(bridge["files"])
        for p in project_path(root, req["output_root"]).rglob("*"):
            if p.is_file():
                owned.append({"path": str(p), "sha256": digest(p), "retention": "canonical_revision", "role": "runtime"})
        artifact = {"schema": 1, "engine": "unity", "style": req["style"], "project": str(root), "project_root": str(root),
                    "entry_scene": result["scene"], "output_root": req["output_root"],
                    "manifest": resource(root, project_path(root, req["output_root"]) / "assembly.json"),
                    "validator": BRIDGE_PATH + "/Editor/GreyboxBridge.cs", "owned_files": owned,
                    "sources": sources, "binding_digest": req["binding_digest"], "native_report": str(report_path),
                    "contract": config.get("plan", {}).get("contract") or config.get("artifact", {}).get("contract", {}),
                    "coverage": "native scene variant; gameplay components/colliders preserved; contract assertions separately validated"}
        _json(output / "artifact.json", artifact)
        result["artifact"] = artifact
    _json(output / "invocation.json", result)
    return result


def assemble(project, plan, style, state=None, executable=None, output=None):
    state = state or {}
    config = {"plan": plan, "style": style, **state}
    result = run(project, "assemble", config, output, executable)
    if not result["ok"]:
        raise ValueError("Unity assembly failed: " + "; ".join(result["errors"]) + " (" + result["log"] + ")")
    return result["artifact"]


def validate(project, artifact, plan=None, executable=None, output_dir=None):
    return run(project, "validate", {"artifact": artifact, "plan": plan or {}}, output_dir, executable)


def capture(project, artifact, config=None, output=None, executable=None):
    return run(project, "capture", {"artifact": artifact, **(config or {})}, output, executable)


def lookdev(project, config, output=None, executable=None):
    return run(project, "lookdev", config, output, executable)


def launch(project, artifact=None, executable=None, *, config=None, unity_bin=None):
    config = config or artifact or {}
    if "entry_scene" in config:
        _check_artifact(config)
        scene = config["entry_scene"]
    else:
        if config.get("artifact"):
            _check_artifact(config["artifact"])
        scene = config.get("scene") or config.get("artifact", {}).get("entry_scene")
    if not scene:
        raise ValueError("Unity launch requires an explicit scene or artifact")
    path = project_path(project, scene)
    command = [engine(unity_bin or executable, project), "-projectPath", str(Path(project).resolve()), "-openfile", str(path)]
    proc = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"ok": True, "state": "running_unconfirmed", "engine": "unity", "pid": proc.pid, "command": command, "entry_scene": resource(project, path), "coverage": "Editor launched; PlayMode acceptance is separate"}


def export(project, artifact, executable=None, output=None, *, build_scenes=None):
    if not output:
        raise ValueError("Unity export requires an explicit Player output path")
    config = {"artifact": artifact, "player_output": str(Path(output).resolve())}
    if build_scenes is not None:
        config["build_scenes"] = build_scenes
    return run(project, "export", config, Path(output).resolve().parent / "greybox-export-evidence", executable, timeout=900)
