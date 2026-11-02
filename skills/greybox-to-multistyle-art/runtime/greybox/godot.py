"""Additive Godot 4 adapter. No project copies, source rewrites, or rig flattening."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import struct
from urllib.parse import unquote, urlparse
import time
import uuid

RUNTIME = Path(__file__).resolve().parents[1] / "godot"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def engine(godot_path=None):
    candidates = [godot_path, os.environ.get("GODOT_BIN"), shutil.which("godot"),
                  shutil.which("godot4"), "/Applications/Godot.app/Contents/MacOS/Godot",
                  str(Path.home() / "Downloads/Godot.app/Contents/MacOS/Godot")]
    for value in candidates:
        if value and Path(value).is_file():
            return str(Path(value).resolve())
    raise ValueError("Godot 4 executable unavailable. Set GODOT_BIN or pass godot_path; the adapter never installs or upgrades the engine.")


def project_path(project, value):
    root = Path(project).resolve()
    value = str(value)
    candidate = root / value[6:] if value.startswith("res://") else Path(value)
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = candidate.resolve()
    if not candidate.is_relative_to(root):
        raise ValueError("Resource must be inside the Godot project: " + value)
    return candidate


def resource(project, path):
    return "res://" + project_path(project, path).relative_to(Path(project).resolve()).as_posix()


def _write_owned(path, content, owned, retention=None, role=None):
    from .core import read, write
    lexical = Path(os.path.abspath(path))
    path = lexical.resolve()
    if path != lexical:
        raise ValueError("Owned outputs must use canonical paths without symlink redirection: " + str(lexical))
    data = content.encode("utf-8") if isinstance(content, str) else content
    if path.exists() and path.read_bytes() != data:
        raise ValueError("Refusing to overwrite a changed artifact; create a new run: " + str(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    journal = path.parent / "ownership.json"
    if journal.is_symlink():
        raise ValueError("Ownership journal cannot be redirected by a symlink")
    receipt = {"path": str(path), "sha256": hashlib.sha256(data).hexdigest()}
    if retention:
        receipt["retention"] = retention
    if role:
        receipt["role"] = role
    rows = read(journal).get("files", []) if journal.exists() else []
    by_path = {r["path"]: r for r in rows}
    by_path[str(path)] = {**receipt, "state": "intent"}
    write(journal, {"schema": 1, "files": list(by_path.values())})
    if not path.exists():
        temporary = path.with_name(path.name + ".assembling")
        if temporary.is_symlink():
            raise ValueError("Owned output staging cannot be redirected by a symlink")
        temporary.write_bytes(data)
        os.replace(temporary, path)
    by_path[str(path)] = {**receipt, "state": "written"}
    write(journal, {"schema": 1, "files": list(by_path.values())})
    owned.append(receipt)


def inspect(project, godot_path=None):
    root = Path(project).resolve()
    config = root / "project.godot"
    if not config.is_file():
        raise ValueError("Expected an existing playable Godot project with project.godot")
    text = config.read_text(encoding="utf-8")
    match = re.search(r'^run/main_scene="([^"]+)"', text, re.M)
    renderer = re.search(r'^renderer/rendering_method="([^"]+)"', text, re.M)
    result = {"engine": "godot", "project": str(root), "project_sha256": digest(config),
              "main_scene": match.group(1) if match else None,
              "renderer": renderer.group(1) if renderer else "project default",
              "coverage": "inventory-only; node paths and gameplay hooks must be declared",
              "csharp": any(root.glob("*.csproj"))}
    try:
        executable = engine(godot_path)
        version = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=15)
        if version.returncode != 0 or not version.stdout.strip().startswith("4."):
            raise ValueError("Expected the project Godot 4 executable with a successful --version result")
        result.update(godot_path=executable, version=version.stdout.strip())
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        result["engine_error"] = str(exc)
    return result


def _scene_name(path):
    text = Path(path).read_text(encoding="utf-8")
    match = re.search(r'^\[node name="([^"]+)"[^\n]*\]', text, re.M)
    if not match:
        raise ValueError("Source scene must be a text .tscn with a named root")
    return match.group(1)


def _dependency_roots(project, contract):
    root = Path(project).resolve()
    roots = [root]
    for value in contract.get("dependency_roots", []):
        candidate = Path(value)
        if not candidate.is_absolute():
            candidate = root / candidate
        candidate = candidate.resolve()
        if not candidate.is_dir():
            raise ValueError("Declared read-only dependency root does not exist: " + str(candidate))
        roots.append(candidate)
    return roots


def _read_path(project, value, roots):
    root = Path(project).resolve()
    value = str(value)
    candidate = root / value[6:] if value.startswith("res://") else Path(value)
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = candidate.resolve()
    if not any(candidate.is_relative_to(boundary) for boundary in roots):
        raise ValueError("External read-only dependency needs an explicit contract.dependency_roots entry: " + value)
    return candidate


def _read_resource(project, value, contract):
    """Keep an existing Godot resource alias; resolve it only for provenance hashing."""
    root = Path(project).resolve()
    value = str(value)
    roots = _dependency_roots(root, contract)
    canonical = _read_path(root, value, roots)
    lexical = root / value[6:] if value.startswith("res://") else Path(value)
    if not lexical.is_absolute():
        lexical = root / lexical
    lexical = Path(os.path.abspath(lexical))
    try:
        reference = "res://" + Path(os.path.relpath(lexical, root)).as_posix()
    except ValueError as exc:
        raise ValueError("Cross-drive resources need one canonical import inside the project") from exc
    return canonical, reference


def _dependencies(project, initial, contract=None):
    """Hash direct native resource dependencies, plus caller-declared dynamic inputs."""
    pending = list(initial)
    found = {}
    roots = _dependency_roots(project, contract or {})
    text_extensions = {".gd", ".tscn", ".tres", ".gdshader", ".gdshaderinc", ".godot", ".json"}
    while pending:
        path = _read_path(project, pending.pop(), roots)
        if str(path) in found or not path.is_file():
            continue
        found[str(path)] = {"path": str(path), "sha256": digest(path)}
        if path.suffix in text_extensions:
            text = path.read_text(encoding="utf-8")
            if path.suffix in {".tscn", ".tres"}:
                for line in text.splitlines():
                    if not line.lstrip().startswith("[ext_resource"):
                        continue
                    match = re.search(r'\bpath\s*=\s*("(?:\\.|[^"\\])*")', line)
                    if match:
                        reference = json.loads(match.group(1))
                        if not reference.startswith("res://") and not Path(reference).is_absolute():
                            reference = str(path.parent / reference)
                        candidate = _read_path(project, reference, roots)
                        if not candidate.is_file():
                            raise ValueError("Native resource dependency is missing: " + str(candidate))
                        pending.append(candidate)
            for match in re.findall(r'["\'](res://[^"\'\n]+)["\']', text):
                candidate = _read_path(project, match, roots)
                if candidate.is_file():
                    pending.append(candidate)
    return list(found.values())


def _gd_tokens(text):
    """Lex literals and code separately; comments cannot become dependencies."""
    pattern = r'(?P<comment>\#[^\n]*)|(?P<string>"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\')'
    code, literals, last = [], {}, 0
    for match in re.finditer(pattern, text):
        code.append(text[last:match.start()])
        if match.lastgroup == "string":
            marker = "__GB_LITERAL_%d__" % len(literals)
            raw = match.group()
            quote = 3 if raw.startswith(('"""', "\'\'\'")) else 1
            literals[marker] = raw[quote:-quote].replace('\\"', '"').replace("\\'", "'")
            code.append(marker)
        else:
            code.append("\n" * match.group().count("\n"))
        last = match.end()
    code.append(text[last:])
    return "".join(code), literals


def _native_references(path, contract):
    """Read native dependency fields, never arbitrary res:// substrings in comments.

    A glTF image/buffer URI is relative to the model, not the project. JSON is
    traversed for declared resource/path fields used by assembly manifests.
    Computed gameplay loads require explicit read-only source_paths.
    """
    path = Path(path)
    suffix = path.suffix.lower()
    refs = []
    if suffix == ".gd":
        code, literals = _gd_tokens(path.read_text(encoding="utf-8"))
        for match in re.finditer(r'\b(?:preload|load|load_threaded_request)\s*\(\s*([^)]*)', code):
            value = literals.get(match.group(1).split(",", 1)[0].strip())
            if value is None:
                if not contract.get("source_paths"):
                    raise ValueError("Computed Godot resource loads need contract.source_paths: " + str(path))
            elif value.startswith("res://"):
                refs.append(value)
            elif value.startswith("uid://"):
                raise ValueError("UID-only native dependency needs an explicit res:// path before formal assembly: " + str(path))
    elif suffix in (".tscn", ".tres"):
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.lstrip()
            if stripped.startswith("[ext_resource"):
                found = re.search(r'\bpath\s*=\s*("(?:\\.|[^"\\])*")', stripped)
                if found:
                    refs.append(json.loads(found.group(1)))
                elif "uid=" in stripped:
                    raise ValueError("UID-only native dependency needs an explicit res:// path before formal assembly: " + str(path))
            elif re.match(r'(?:manifest_path|resource_path)\s*=', stripped):
                found = re.search(r'=\s*("(?:\\.|[^"\\])*")', stripped)
                if found:
                    refs.append(json.loads(found.group(1)))
    elif suffix == ".godot":
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.lstrip().startswith((";", "#")):
                continue
            found = re.search(r'=\s*("(?:\\.|[^"\\])*")', line)
            if found:
                value = json.loads(found.group(1))
                if value.startswith(("res://", "*res://")):
                    refs.append(value.lstrip("*"))
    elif suffix in (".gltf", ".glb"):
        if suffix == ".gltf":
            doc = json.loads(path.read_text(encoding="utf-8"))
        else:
            with path.open("rb") as stream:
                header = stream.read(20)
                if len(header) < 20 or header[:4] != b"glTF":
                    raise ValueError("Formal GLB dependency is not a GLB: " + str(path))
                magic, version, total, size, chunk = struct.unpack("<4sIIII", header)
                if version != 2 or chunk != 0x4E4F534A or total != path.stat().st_size or size > total - 20:
                    raise ValueError("Malformed GLB dependency: " + str(path))
                doc = json.loads(stream.read(size).decode("utf-8"))
        for row in doc.get("buffers", []) + doc.get("images", []):
            uri = row.get("uri")
            if not uri or uri.startswith("data:"):
                continue
            if urlparse(uri).scheme:
                raise ValueError("Formal model cannot depend on an external URL: " + uri)
            refs.append(str(path.parent / unquote(uri)))
    elif suffix == ".json":
        doc = json.loads(path.read_text(encoding="utf-8"))
        def walk(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if key in ("path", "resource", "resource_path", "scene", "manifest_path") and isinstance(item, str) and item.startswith("res://"):
                        refs.append(item)
                    else:
                        walk(item)
            elif isinstance(value, list):
                for item in value:
                    walk(item)
        walk(doc)
    elif suffix in (".gdshader", ".gdshaderinc"):
        text = re.sub(r'("(?:\\.|[^"\\])*")|/\*[\s\S]*?\*/|//[^\n]*',
                      lambda match: match.group(1) or "", path.read_text(encoding="utf-8"))
        refs.extend(re.findall(r'^\s*#include\s+"([^"\n]+)"', text, re.M))
    return refs


def _native_dependencies(project, initial, contract):
    pending, found = list(initial), {}
    roots = _dependency_roots(project, contract)
    while pending:
        path = _read_path(project, pending.pop(), roots)
        if str(path) in found:
            continue
        if not path.is_file():
            raise ValueError("Native resource dependency is missing: " + str(path))
        found[str(path)] = {"path": str(path), "sha256": digest(path)}
        for reference in _native_references(path, contract):
            reference = str(reference)
            if not reference.startswith("res://") and not Path(reference).is_absolute():
                reference = str(path.parent / reference)
            pending.append(reference)
    return list(found.values())


def dependency_snapshot(project, plan):
    """Public read-only source manifest, including explicitly permitted external roots.

    Dynamic loaders whose resource paths are computed must declare source_paths.
    No write destination is relaxed by dependency_roots.
    """
    contract = plan.get("contract", {})
    scene = contract.get("scene") or inspect(project).get("main_scene")
    initial = [Path(project).resolve() / "project.godot"] + contract.get("source_paths", [])
    if scene:
        initial.append(scene)
    for binding in plan.get("bindings", []):
        if binding.get("source", {}).get("path"):
            initial.append(binding["source"]["path"])
        for variant in binding.get("styles", {}).values():
            if variant.get("source", {}).get("path"):
                initial.append(variant["source"]["path"])
    roots = _dependency_roots(project, contract)
    for item in initial:
        if not _read_path(project, item, roots).is_file():
            raise ValueError("Declared source dependency is missing: " + str(item))
    return (_native_dependencies(project, initial, contract) if plan.get("workspace")
            else _dependencies(project, initial, contract))


def assemble(project, run_dir, plan, style, godot_path=None):
    root = Path(project).resolve()
    scene = plan.get("contract", {}).get("scene") or inspect(root).get("main_scene")
    if not scene or not str(scene).startswith("res://"):
        raise ValueError("Declare contract.scene as res://path.tscn (UID main scenes need an explicit resource path)")
    source = project_path(root, scene)
    if source.suffix != ".tscn" or not source.is_file():
        raise ValueError("Declared source scene must exist and use .tscn")
    style_id = style.get("id") if isinstance(style, dict) else str(style)
    run_id = plan.get("run_id") or Path(run_dir).name
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", str(run_id)) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", style_id):
        raise ValueError("Run and style IDs use 1–80 ASCII letters, digits, underscore or hyphen")
    run_path = project_path(root, run_dir)
    workspace = plan.get("workspace")
    layout_roots = None
    if workspace:
        from . import layout
        layout_roots = layout.roots(root, plan, style_id)
        allowed_runs = [layout.roots(root, plan)["runs"], layout_roots["runs"]]
        if not any(run_path.is_relative_to(path) and run_path != path for path in allowed_runs):
            raise ValueError("Workspace run directory must be under shared/style production/runs")
        # Formal source revisions are content addressed; logs and task ledgers stay in runs.
        target = None
    else:
        # Legacy recovery preserves recorded experiment paths; never silently migrate.
        if not run_path.is_relative_to(root / "art" / "experiments"):
            raise ValueError("Run directory must be within project/art/experiments for task-owned reversible output")
        target = run_path / style_id
    bindings = []
    baseline_plan = {"contract": plan.get("contract", {})}
    if workspace:
        baseline_plan["workspace"] = workspace
    sources = dependency_snapshot(root, baseline_plan)
    baseline_sources = list(sources)
    art_sources = []
    seen = set()
    for original in plan.get("bindings", []):
        binding = json.loads(json.dumps(original))
        binding.update(binding.pop("styles", {}).get(style_id, {}))
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", str(binding.get("id", ""))) or binding["id"] in seen or not binding.get("owner"):
            raise ValueError("Bindings require distinct IDs and explicit logical owner node paths")
        seen.add(binding["id"])
        if any(part == ".." for part in binding["owner"].split("/")) or binding["owner"].startswith("/"):
            raise ValueError("Owner paths must be relative descendants of the gameplay root")
        if any(path.startswith("/") or ".." in path.split("/") for path in binding.get("hide", [])):
            raise ValueError("Hidden visuals must be relative descendants of the gameplay root")
        source_spec = binding.get("source")
        if not isinstance(source_spec, dict) or not source_spec:
            raise ValueError("Missing binding source; no implicit placeholder substitution")
        if source_spec.get("units", "m") not in ("m", "cm", "mm"):
            raise ValueError("source.units supports m/cm/mm; declare measured source units explicitly")
        if source_spec.get("basis", "godot") not in ("godot", "gltf", "z_up"):
            raise ValueError("source.basis supports godot/gltf/z_up; imported glTF already uses Godot coordinates")
        if source_spec.get("route", "procedural") not in ("procedural", "reuse", "generated", "hybrid"):
            raise ValueError("Unsupported production route")
        if source_spec.get("route") in ("reuse", "generated", "hybrid") and not source_spec.get("path"):
            raise ValueError("Reuse/generated/hybrid bindings require an imported source.path")
        if not source_spec.get("path") and source_spec.get("primitive", "box") not in ("box", "sphere", "cylinder"):
            raise ValueError("Procedural primitive supports box/sphere/cylinder; extend the assembly recipe for other geometry")
        size = source_spec.get("size", [1, 1, 1])
        if not isinstance(size, list) or len(size) != 3 or any(type(x) not in (int, float) or not math.isfinite(x) or not 0 < x <= 100000 for x in size):
            raise ValueError("source.size must contain three finite positive dimensions")
        if not source_spec.get("path") and source_spec.get("primitive") == "sphere" and size[0] != size[2]:
            raise ValueError("Sphere size X and Z must match; use an explicit geometry recipe for ellipsoids")
        for vector_name in ("anchor", "source_anchor", "rotation_degrees"):
            vector = binding.get(vector_name, [0, 0, 0])
            if not isinstance(vector, list) or len(vector) != 3 or any(type(x) not in (int, float) or not math.isfinite(x) or abs(x) > 1e9 for x in vector):
                raise ValueError(vector_name + " must contain three finite coordinates")
        if source_spec.get("path"):
            asset, asset_reference = _read_resource(root, source_spec["path"], plan.get("contract", {}))
            if not asset.is_file():
                raise ValueError("Asset does not exist: " + str(asset))
            source_spec["path"] = asset_reference
            dependencies = (_native_dependencies(root, [asset], plan.get("contract", {})) if workspace
                            else _dependencies(root, [asset], plan.get("contract", {})))
            sources.extend(dependencies)
            art_sources.extend(dependencies)
        scale = binding.get("uniform_scale", 1.0)
        if not isinstance(scale, (int, float)) or not 0 < scale <= 10000:
            raise ValueError("uniform_scale must be a positive scalar, never XYZ stretching")
        if binding.get("normalize", {}).get("mode") not in (None, "none", "uniform_bounds"):
            raise ValueError("Normalization supports none or uniform_bounds; rigs are never flattened")
        if binding.get("normalize", {}).get("space", "world") not in ("world", "owner"):
            raise ValueError("normalize.space must be world or owner")
        extent = binding.get("normalize", {}).get("max_extent", 1.0)
        if not isinstance(extent, (int, float)) or not 0 < extent <= 10000:
            raise ValueError("normalize.max_extent must be a positive number in metres")
        if binding.get("kind") in ("skinned", "articulated") and binding.get("normalize", {}).get("mode") == "uniform_bounds":
            raise ValueError("Dynamic assets require declared uniform_scale and anchors; do not normalize posed bounds")
        bindings.append(binding)
    style_config = next((item for item in plan.get("styles", []) if item.get("id") == style_id), {})
    effect_config = style_config.get("effects", plan.get("effects", {}))
    tool_names = ["art_layer.gd", "validate.gd"]
    if effect_config:
        from . import effects
        effect_config = effects.validate(effect_config)
        tool_names += ["effects.gd", "water.gdshader", "grass.gdshader", "ground.gdshader"]
        effect_sources = effects.dependencies(effect_config, root)
        sources.extend(effect_sources)
        art_sources.extend(effect_sources)
    manifest = {"schema": 1, "style": style_id, "source_scene": resource(root, source),
                "contract": plan.get("contract", {}), "bindings": bindings,
                **({"effects": effect_config} if effect_config else {})}
    sources = list({item["path"]: item for item in sources}.values())
    dependency_audit = None
    retention = "canonical_revision" if workspace else None
    revision_digest = None
    if workspace:
        baseline_audit = layout.audit_dependencies(root, plan, style_id, baseline_sources,
                                                   source_role="baseline",
                                                   dependency_roots=plan.get("contract", {}).get("dependency_roots", []))
        art_audit = layout.audit_dependencies(root, plan, style_id, art_sources)
        dependency_audit = {"ok": baseline_audit["ok"] and art_audit["ok"],
                            "issues": baseline_audit["issues"] + art_audit["issues"],
                            "dependencies": baseline_audit["dependencies"] + art_audit["dependencies"]}
        if not dependency_audit["ok"]:
            raise ValueError("Formal runtime dependency ownership audit failed: " + json.dumps(dependency_audit["issues"], ensure_ascii=False))
        revision_identity = {"manifest": manifest, "sources": sorted(sources, key=lambda item: item["path"]),
                             "producer": digest(__file__),
                             "runtime": {name: digest(RUNTIME / name) for name in tool_names}}
        revision_digest = hashlib.sha256(json.dumps(revision_identity, sort_keys=True).encode()).hexdigest()
        target = layout_roots["runtime"] / "revisions" / revision_digest[:20]
        layout.validate_output(root, plan, target / "play.tscn", "runtime", style_id=style_id)
    owned = []
    tools_target = target
    if workspace:
        _write_owned(target / "revision.json", json.dumps({"schema": 1, "revision_sha256": revision_digest,
                     "case_id": workspace["case_id"], "style_id": style_id,
                     "identity": revision_identity}, indent=2, ensure_ascii=False) + "\n", owned, retention, "runtime")
        tool_identity = {name: digest(RUNTIME / name) for name in tool_names}
        tool_digest = hashlib.sha256(json.dumps(tool_identity, sort_keys=True).encode()).hexdigest()
        tools_target = layout.roots(root, plan)["tools"] / "godot" / tool_digest[:20]
        for filename in tool_names + ["tools.json"]:
            layout.validate_output(root, plan, tools_target / filename, "tool")
        _write_owned(tools_target / "tools.json", json.dumps({"schema": 1, "case_id": workspace["case_id"],
                     "tool_sha256": tool_digest, "files": tool_identity}, indent=2, ensure_ascii=False) + "\n",
                     owned, "canonical_tool", "tool")
    _write_owned(target / "assembly.json", json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", owned, retention,
                 "runtime" if workspace else None)
    for filename in tool_names:
        _write_owned(tools_target / filename, (RUNTIME / filename).read_bytes(), owned,
                     "canonical_tool" if workspace else None, "tool" if workspace else None)
    adapter = resource(root, tools_target / "art_layer.gd")
    assembly = resource(root, target / "assembly.json")
    root_name = _scene_name(source)
    effect_resources, effect_properties = [], []
    if effect_config:
        effect_resources, effect_properties = effects._godot_bindings(root, tools_target, effect_config)
        effect_resources.insert(0, f'[ext_resource type="Script" path={json.dumps(resource(root, tools_target / "effects.gd"))} id="effect_script"]')
        effect_properties.insert(0, 'effect_script = ExtResource("effect_script")')
    effect_resource_text = '\n'.join(effect_resources) + ('\n' if effect_resources else '')
    effect_property_text = '\n'.join(effect_properties) + ('\n' if effect_properties else '')
    scene_text = (f'[gd_scene load_steps={3 + len(effect_resources)} format=3]\n\n'
                  f'[ext_resource type="PackedScene" path={json.dumps(resource(root, source))} id="1"]\n'
                  f'[ext_resource type="Script" path={json.dumps(adapter)} id="2"]\n'
                  f'{effect_resource_text}\n'
                  f'[node name={json.dumps(root_name)} instance=ExtResource("1")]\n\n'
                  '[node name="_GreyboxArtLayer" type="Node" parent="."]\n'
                  'script = ExtResource("2")\n'
                  f'manifest_path = {json.dumps(assembly)}\n'
                  f'{effect_property_text}')
    _write_owned(target / "play.tscn", scene_text, owned, retention, "runtime" if workspace else None)
    return {"schema": 1, "style": style_id, "project": str(root), "project_root": str(root),
            **({"case_id": workspace["case_id"], "style_id": style_id,
                "revision_sha256": revision_digest, "dependency_audit": dependency_audit,
                "evidence_root": str(run_path / "evidence" / style_id),
                "layout": "case-style-v1"} if workspace else {}),
            "entry_scene": resource(root, target / "play.tscn"), "manifest": assembly,
            "validator": resource(root, tools_target / "validate.gd"), "owned_files": owned,
            "sources": sources, "binding_digest": hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest(),
            "coverage": "additive Node3D visuals; gameplay verified only by declared hooks/assertions",
            "dependency_scope": ("native field/load/glTF URI closure plus contract.source_paths; declare computed dynamic resource paths explicitly"
                                 if workspace else "literal res:// dependencies plus contract.source_paths; declare computed dynamic resource paths explicitly")}


def _check_artifact(artifact):
    for item in artifact.get("owned_files", []) + artifact.get("sources", []):
        if not Path(item["path"]).is_file() or digest(item["path"]) != item["sha256"]:
            raise ValueError("Artifact or source changed; reassemble/revalidate before using old evidence: " + item["path"])


def launch(project, artifact, godot_path=None):
    _check_artifact(artifact)
    args = [engine(godot_path), "--path", str(Path(project).resolve()), artifact["entry_scene"]]
    log_dir = (project_path(project, artifact["evidence_root"]) / "launch-logs" if artifact.get("evidence_root")
               else project_path(project, artifact["manifest"]).parent / "launch-logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / (uuid.uuid4().hex + ".log")
    with log_path.open("wb") as log:
        process = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT)
    deadline = time.monotonic() + 0.75
    while process.poll() is None and time.monotonic() < deadline:
        time.sleep(0.05)
    code = process.poll()
    status = "running_unconfirmed" if code is None else ("exited" if code == 0 else "failed")
    return {"ok": code is None, "state": status, "pid": process.pid, "returncode": code,
            "entry_scene": artifact["entry_scene"], "command": args, "log": str(log_path),
            "note": "Process observation only, not proof of a ready window or playability"}


def import_resources(project, godot_path=None):
    """Native import with configurable timeout and retained diagnostics; no engine upgrades."""
    args = [engine(godot_path), "--headless", "--path", str(Path(project).resolve()), "--editor", "--import"]
    timeout = max(1, int(os.environ.get("GREYBOX_IMPORT_TIMEOUT", "120")))
    try:
        completed = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        log, code = completed.stdout + completed.stderr, completed.returncode
    except subprocess.TimeoutExpired as exc:
        def text(x):
            return x.decode("utf-8", errors="replace") if isinstance(x, bytes) else (x or "")
        log, code = text(exc.stdout) + text(exc.stderr) + "\nIMPORT TIMEOUT", -1
    errors = [line for line in log.splitlines() if "SCRIPT ERROR" in line or "Parse Error" in line or "ERROR:" in line]
    return {"passed": code == 0 and not errors, "returncode": code, "timed_out": code == -1,
            "errors": errors, "command": args, "log": log, "timeout_seconds": timeout}


def validate(project, artifact, output_dir, godot_path=None):
    _check_artifact(artifact)
    attempt_id = uuid.uuid4().hex
    output = Path(output_dir).resolve() / attempt_id
    output.mkdir(parents=True, exist_ok=False)
    args = [engine(godot_path), "--path", str(Path(project).resolve()),
            "--resolution", "960x540", "--position", "80,80", "--script", artifact["validator"],
            "--", "--scene", artifact["entry_scene"], "--output", str(output), "--attempt-id", attempt_id,
            "--binding-digest", artifact["binding_digest"]]
    start = time.monotonic()
    try:
        completed = subprocess.run(args, capture_output=True, text=True,
                                   timeout=max(1, int(os.environ.get("GREYBOX_VALIDATE_TIMEOUT", "120"))))
        log, code = completed.stdout + completed.stderr, completed.returncode
    except subprocess.TimeoutExpired as exc:
        def text(x):
            return x.decode("utf-8", errors="replace") if isinstance(x, bytes) else (x or "")
        log, code = text(exc.stdout) + text(exc.stderr) + "\nVALIDATION TIMEOUT", -1
    (output / "godot.log").write_text(log, encoding="utf-8")
    report_path = output / "native-report.json"
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if not isinstance(report, dict):
            raise ValueError("Report must be an object")
    except (OSError, ValueError):
        report = {"passed": False, "errors": ["This attempt produced no valid native report"]}
    report.setdefault("errors", [])
    for key, expected in (("attempt_id", attempt_id), ("binding_digest", artifact["binding_digest"]), ("scene", artifact["entry_scene"])):
        if report.get(key) != expected:
            report["errors"].append("Native report mismatch: " + key)
    evidence = []
    claimed = report.get("captures", [])
    manifest = json.loads(project_path(project, artifact["manifest"]).read_text(encoding="utf-8"))
    expected_count = 1 + len(manifest.get("contract", {}).get("validation", {}).get("steps", []))
    if not isinstance(claimed, list) or len(claimed) != expected_count or len(set(map(str, claimed))) != len(claimed):
        report["errors"].append("Missing/duplicate native capture coverage")
        claimed = claimed if isinstance(claimed, list) else []
    for name in claimed:
        p = Path(str(name))
        p = p.resolve() if p.is_absolute() else (output / p).resolve()
        if not p.is_relative_to(output) or not p.is_file() or p.suffix.lower() != ".png":
            report["errors"].append("Capture is missing or outside this attempt")
        elif p.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
            report["errors"].append("Capture does not contain PNG bytes")
        else:
            evidence.append({"path": str(p), "sha256": digest(p)})
    native_errors = [line for line in log.splitlines() if "SCRIPT ERROR" in line or "Parse Error" in line or "ERROR:" in line]
    report.update(returncode=code, elapsed_seconds=round(time.monotonic() - start, 3),
        source_hashes=artifact["sources"], artifact_hashes=artifact["owned_files"], native_errors=native_errors,
        evidence=evidence, attempt_dir=str(output))
    report["passed"] = report.get("passed") is True and code == 0 and not native_errors and not report["errors"]
    report["ok"] = report["passed"]
    (output / "validation.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def rollback(artifact):
    removed, conflicts, retained = [], [], []
    for item in reversed(artifact.get("owned_files", [])):
        path = Path(item["path"])
        if item.get("retention") in ("canonical_revision", "canonical_tool"):
            retained.append(str(path))
            continue
        if not path.exists():
            continue
        if digest(path) != item["sha256"]:
            conflicts.append(str(path))
        else:
            path.unlink()
            removed.append(str(path))
    return {"removed": removed, "conflicts": conflicts, "retained": retained, "passed": not conflicts}
