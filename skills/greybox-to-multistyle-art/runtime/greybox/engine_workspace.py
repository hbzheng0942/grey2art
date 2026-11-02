"""Read-only, format-specific dependency audits; static closure is not native play validation.

Unity metadata: https://docs.unity.com/en-us/engine/7000.0/manual/assets-and-media/import-assets/asset-metadata
Three loaders: https://threejs.org/docs/pages/GLTFLoader
Blender external paths are read with the installed bpy.utils.blend_paths API.
"""
from __future__ import annotations

import ast
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote, urlsplit

from . import core, layout

UNITY_SERIALIZED = {".unity", ".prefab", ".mat", ".asset", ".controller", ".overridecontroller", ".anim",
                    ".physicmaterial", ".rendertexture", ".playable", ".terrainlayer", ".mask", ".lighting"}
JS = {".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx"}
BUILTIN_GUIDS = {"0" * 32, "0" * 16 + "e" + "0" * 15, "0" * 16 + "f" + "0" * 15}
BLENDER_MARKER = "GREYBOX_EXTERNAL_PATHS="
BLENDER_SCRIPT = """import bpy,json,hashlib
p=bpy.data.filepath
h=hashlib.sha256()
with open(p,'rb') as f:
 for chunk in iter(lambda:f.read(1048576),b''): h.update(chunk)
print('GREYBOX_EXTERNAL_PATHS='+json.dumps({'source':{'path':p,'sha256':h.hexdigest()},'dependencies':sorted(set(bpy.utils.blend_paths(absolute=True,packed=False,local=False))),'version':bpy.app.version_string,'engine_resource_root':bpy.utils.resource_path('LOCAL')},sort_keys=True))
"""
BLENDER_SCRIPT_SHA256 = hashlib.sha256(BLENDER_SCRIPT.encode()).hexdigest()


def _records(project, explicitdeps):
    core.require(explicitdeps is None or isinstance(explicitdeps, list), "Explicit dependencies must be hash-bound file records")
    result = []
    for row in explicitdeps or []:
        core.require(isinstance(row, dict) and row.get("path") and re.fullmatch(r"[0-9a-f]{64}", str(row.get("sha256", ""))),
                     "Each explicit dependency needs path and sha256")
        path = core.resolve_input(row["path"], project)
        core.require(path.is_file() and core.file_hash(path) == row["sha256"], "Explicit dependency is missing or changed")
        result.append({**row, "path": str(path), "role": row.get("role", "art")})
    return result


def _tokens(text, yaml=False):
    """Separate literals and comments before matching dependency syntax."""
    comment = r"\#[^\n]*" if yaml else r"/\*[\s\S]*?\*/|//[^\n]*"
    pattern = r"(?P<comment>" + comment + r")|(?P<string>\"(?:\\.|[^\"\\])*\"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`)"
    code, literals, end = [], {}, 0
    for match in re.finditer(pattern, text):
        code.append(text[end:match.start()])
        if match.lastgroup == "string":
            raw = match.group(); marker = "__GB_S%d__" % len(literals)
            try:
                value = ast.literal_eval(raw) if raw[0] != "`" else raw[1:-1]
            except (ValueError, SyntaxError):
                value = raw[1:-1].replace("\\/", "/")
            literals[marker] = {"value": value, "computed": raw[0] == "`" and "${" in raw}
            code.append(marker)
        else:
            code.append("\n" * match.group().count("\n"))
        end = match.end()
    code.append(text[end:])
    return "".join(code), literals


def _dynamic(source, explicit, project):
    matches = [r for r in explicit if r.get("for_source") and core.resolve_input(r["for_source"], project) == source]
    core.require(matches, "Computed or symbolic loads need hash-bound explicit dependencies with for_source: " + str(source))
    return [Path(r["path"]) for r in matches]


def _reference_file(project, value, allowed_roots, allowed_files):
    path = core.resolve_input(value, project)
    core.require(any(core.inside(path, root) for root in allowed_roots) or str(path) in allowed_files,
                 "External dependency needs an explicit read-only contract root or approved reuse source: " + str(path))
    core.require(path.is_file(), "Dependency is missing: " + str(path))
    return path


def _gltf_refs(path):
    from . import godot
    return [Path(value) for value in godot._native_references(path, {})]


def _unity_index(project, extra_roots=()):
    found = {}
    scanned, seen_meta = set(), set()
    for root in (project / "Assets", project / "Packages", *extra_roots):
        root = Path(root).resolve()
        if str(root) in scanned: continue
        scanned.add(str(root))
        if not root.is_dir():
            continue
        for directory, dirs, files in os.walk(root, followlinks=False):
            dirs[:] = [d for d in dirs if not (Path(directory) / d).is_symlink()]
            for name in files:
                meta = Path(directory) / name
                if not name.endswith(".meta") or meta.is_symlink() or str(meta.resolve()) in seen_meta:
                    continue
                seen_meta.add(str(meta.resolve()))
                match = re.search(r"(?m)^guid:\s*([0-9a-fA-F]{32})\s*$", meta.read_text(encoding="utf-8"))
                if match:
                    found.setdefault(match.group(1).lower(), []).append(meta.with_suffix(""))
    return found


def _unity_refs(path, index, project, explicit):
    refs = []
    if path.suffix.lower() in UNITY_SERIALIZED or path.suffix.lower() == ".meta":
        text = path.read_text(encoding="utf-8")
        if path.suffix.lower() != ".meta":
            core.require(text.lstrip().startswith(("%YAML", "--- !u!")),
                         "Unity serialized dependencies require Force Text YAML: " + str(path))
        else:
            text = re.sub(r"(?m)^guid:[^\n]*", "", text)  # Own GUID is identity, not another resource.
        code, literals = _tokens(text, yaml=True)
        for match in re.finditer(r"\bguid\s*:\s*([0-9a-fA-F]{32}|__GB_S\d+__)", code):
            guid = literals.get(match.group(1), {}).get("value", match.group(1)).lower()
            core.require(re.fullmatch(r"[0-9a-f]{32}", guid), "Malformed Unity GUID")
            if guid in BUILTIN_GUIDS:
                continue
            choices = index.get(guid, [])
            core.require(len(choices) == 1, "Unity GUID is missing or ambiguous: " + guid)
            refs.append(choices[0])
    elif path.suffix.lower() == ".cs":
        code, literals = _tokens(path.read_text(encoding="utf-8"))
        for match in re.finditer(r"\b(?:Resources\.Load(?:Async)?(?:<[^>]+>)?|Addressables\.LoadAssetAsync(?:<[^>]+>)?|AssetDatabase\.LoadAssetAtPath(?:<[^>]+>)?)\s*\(\s*([^,)]*)", code):
            expression = match.group(1).strip(); item = literals.get(expression)
            if item and not item["computed"] and item["value"].startswith("Assets/"):
                refs.append(project / item["value"])
            else:
                refs.extend(_dynamic(path, explicit, project))
    return refs


def _module_file(path):
    if path.is_file():
        return path
    candidates = [Path(str(path) + ext) for ext in (".js", ".mjs", ".ts", ".tsx", ".jsx", ".json")]
    candidates += [path / ("index" + ext) for ext in (".js", ".ts", ".tsx", ".jsx")]
    present = [p for p in candidates if p.is_file()]
    core.require(len(present) == 1, "Module dependency is missing or ambiguous: " + str(path))
    return present[0]


def _web_path(project, source, value, kind, public_root):
    core.require(isinstance(value, str) and value.strip(), "Empty web dependency")
    if value.startswith("data:"):
        return None
    parts = urlsplit(value)
    core.require(not parts.scheme and not parts.netloc, "Formal web dependencies must be local: " + value)
    name = unquote(parts.path)
    core.require(name and "\\" not in name, "Invalid web dependency URL")
    if kind == "module":
        if name.startswith("."):
            return _module_file(source.parent / name)
        if name.startswith("/"):
            choices = []
            for base in (project, public_root):
                candidate = base / name.lstrip("/")
                try: resolved = _module_file(candidate)
                except core.WorkflowError: continue
                if resolved.resolve() not in [p.resolve() for p in choices]: choices.append(resolved)
            core.require(len(choices) == 1, "Absolute web source URL is missing or ambiguous between project/public roots: " + value)
            return choices[0]
        return None  # Bare packages are bound by package.json and its lockfile.
    if kind == "document-asset" and not name.startswith("/"):
        return source.parent / name
    if kind == "module-url":
        return source.parent / name if not name.startswith("/") else public_root / name.lstrip("/")
    return public_root / name.lstrip("/")


def _package(project, value, modules):
    package = value.split("/")[0] if not value.startswith("@") else "/".join(value.split("/")[:2])
    core.require(re.fullmatch(r"(?:@[A-Za-z0-9_.-]+/)?[A-Za-z0-9_.-]+", package),
                 "Module aliases need explicit dependency mappings")
    manifest = project / "package.json"
    core.require(manifest.is_file(), "Bare web package needs package.json: " + value)
    doc = core.read(manifest)
    core.require(package in {**doc.get("dependencies", {}), **doc.get("devDependencies", {})},
                 "Bare web import is not declared in package.json: " + value)
    locks = [project / name for name in ("package-lock.json", "pnpm-lock.yaml", "yarn.lock", "bun.lock", "bun.lockb") if (project / name).is_file()]
    core.require(locks, "Web packages require a dependency lockfile before handoff")
    modules.add(value)
    return [manifest, *locks]


def _js_refs(path, text, project, public_root, explicit, modules):
    code, literals = _tokens(text); refs, imported, prefixes = [], {}, {}
    def literal(expression, kind):
        item = literals.get(expression.strip())
        if item is None or item["computed"]:
            return _dynamic(path, explicit, project)
        value = item["value"]
        result = _web_path(project, path, value, kind, public_root)
        if kind == "module" and result is None:
            return _package(project, value, modules)
        return [result] if result is not None else []
    for match in re.finditer(r"\b(?:import|export)\s+(?!\s*\()(?:[^;]*?\bfrom\s+)?(__GB_S\d+__)", code):
        refs.extend(literal(match.group(1), "module"))
    for match in re.finditer(r"\bimport\s+(\w+)\s+from\s+(__GB_S\d+__)", code):
        value = literals[match.group(2)]["value"]
        resolved = _web_path(project, path, value, "module", public_root)
        if resolved is not None:
            imported[match.group(1)] = resolved
    for match in re.finditer(r"\bimport\s*\(\s*([^)]*)", code):
        refs.extend(literal(match.group(1).split(",", 1)[0], "module"))
    for match in re.finditer(r"\b(\w+)\.setPath\s*\(\s*([^)]*)", code):
        item = literals.get(match.group(2).strip())
        if item is None or item["computed"]:
            refs.extend(_dynamic(path, explicit, project))
        else:
            prefixes.setdefault(match.group(1), []).append((match.start(), item["value"]))
    for match in re.finditer(r"\b(?:\w+\.setResourcePath|\w+\.setURLModifier)\s*\(", code):
        refs.extend(_dynamic(path, explicit, project))
    for match in re.finditer(r"(?:(\w+)\s*)?\.(?:load|loadAsync)\s*\(\s*([^,)]*)|\b(?:useGLTF(?:\.preload)?|useTexture|fetch)\s*\(\s*([^,)]*)|\buseLoader\s*\(\s*[^,]+,\s*([^,)]*)", code):
        expression = next((part for part in match.groups()[1:] if part is not None), "").strip()
        if expression.startswith("new URL("):
            continue  # The dedicated module-relative URL parser follows it below.
        if expression in imported:
            refs.append(imported[expression]); continue
        item = literals.get(expression)
        if item is not None and not item["computed"]:
            prior = [value for offset, value in prefixes.get(match.group(1), []) if offset < match.start()]
            if match.group(1) is None and ".setPath(" in code[max(0, match.start()-200):match.start()]:
                refs.extend(_dynamic(path, explicit, project)); continue
            value = (prior[-1] if prior else "") + item["value"]
            resolved = _web_path(project, path, value, "asset", public_root)
            if resolved is not None: refs.append(resolved)
        else:
            refs.extend(_dynamic(path, explicit, project))
    for match in re.finditer(r"\bnew\s+URL\s*\(\s*([^,]+),\s*import\.meta\.url\s*\)", code):
        refs.extend(literal(match.group(1), "module-url"))
    return refs


class _HTML(HTMLParser):
    def __init__(self):
        super().__init__(); self.urls = []; self.scripts = []; self.script = False
    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag in ("script", "img", "source", "video", "audio", "iframe") and values.get("src"):
            self.urls.append((values["src"], "module" if tag == "script" else "document-asset"))
        if tag == "link" and values.get("href") and values.get("rel") in ("stylesheet", "preload", "modulepreload"):
            self.urls.append((values["href"], "document-asset"))
        self.script = tag == "script" and not values.get("src")
    def handle_endtag(self, tag):
        if tag == "script": self.script = False
    def handle_data(self, data):
        if self.script: self.scripts.append(data)


def _web_refs(path, project, public_root, explicit, modules):
    if path.suffix.lower() in JS:
        return _js_refs(path, path.read_text(encoding="utf-8"), project, public_root, explicit, modules)
    if path.suffix.lower() in (".html", ".htm"):
        parsed = _HTML(); parsed.feed(path.read_text(encoding="utf-8")); refs = []
        for value, kind in parsed.urls:
            resolved = _web_path(project, path, value, kind, public_root)
            if resolved is not None: refs.append(resolved)
        for script in parsed.scripts:
            refs.extend(_js_refs(path, script, project, public_root, explicit, modules))
        return refs
    if path.suffix.lower() == ".css":
        text = re.sub(r"/\*[\s\S]*?\*/", "", path.read_text(encoding="utf-8"))
        refs = []
        for value in re.findall(r"url\(\s*['\"]?([^)'\"\s]+)", text):
            resolved = _web_path(project, path, value, "module-url", public_root)
            if resolved is not None: refs.append(resolved)
        return refs
    return []


def _parse_blender_stdout(stdout, path):
    values = [line[len(BLENDER_MARKER):] for line in stdout.splitlines() if line.startswith(BLENDER_MARKER)]
    core.require(len(values) == 1, "Blender inspection did not produce one complete external-path report")
    value = json.loads(values[0]); source = value.get("source", {})
    core.require(Path(source.get("path", "")).resolve() == path and source.get("sha256") == core.file_hash(path),
                 "Blender inspected a different source version")
    core.require(isinstance(value.get("dependencies"), list) and all(isinstance(p, str) for p in value["dependencies"]),
                 "Blender external-path report is malformed")
    return value


def _blend_refs(path, project, plan):
    config = plan["workspace"]
    reports = config.get("blender_dependency_reports", [])
    if config.get("blender_dependency_report"):
        reports = [*reports, config["blender_dependency_report"]]
    for reference in reports:
        report_path = core.resolve_input(reference.get("path", ""), project)
        core.require(report_path.is_file() and core.file_hash(report_path) == reference.get("sha256"), "Blender inspection receipt changed")
        report = core.read(report_path)
        if report.get("source", {}).get("path") != str(path): continue
        core.require(report.get("kind") == "blender-dependency-inspection" and report.get("schema") == 1
                     and report.get("source", {}).get("sha256") == core.file_hash(path)
                     and report.get("inspector", {}).get("script_sha256") == BLENDER_SCRIPT_SHA256
                     and report.get("inspector", {}).get("returncode") == 0
                     and re.fullmatch(r"[0-9a-f]{64}", str(report.get("inspector", {}).get("sha256", "")))
                     and hashlib.sha256(report.get("stdout", "").encode()).hexdigest() == report.get("stdout_sha256"),
                     "Blender inspection receipt does not bind the reviewed inspector/source/log")
        observed = _parse_blender_stdout(report["stdout"], path)
        expected = {str(Path(r["path"]).resolve()): r["sha256"] for r in report.get("dependencies", [])}
        for value in observed["dependencies"]:
            candidate = Path(value).resolve()
            core.require(str(candidate) in expected and candidate.is_file() and core.file_hash(candidate) == expected[str(candidate)],
                         "Recorded Blender dependency is missing or changed")
        return observed["dependencies"], {"mode": "verified-recorded-inspection", "actual_blender_inspection": False,
            "recorded_blender_inspection": True, "engine_resource_root": observed.get("engine_resource_root"), "report": {"path": str(report_path), "sha256": reference["sha256"]}}
    from . import blender
    found = blender.discover(config.get("blender_executable"))
    core.require(found["status"] == "discovered", "Blender dependency audit needs Blender CLI or a verified inspection receipt")
    executable = Path(found["executable"])
    before = core.file_hash(path)
    proc = subprocess.run([str(executable), "--background", "--factory-startup", "--disable-autoexec", str(path),
                           "--python-expr", BLENDER_SCRIPT], capture_output=True, text=True, timeout=60, cwd=project)
    core.require(proc.returncode == 0 and core.file_hash(path) == before, "Blender read-only inspection failed or changed the input")
    observed = _parse_blender_stdout(proc.stdout, path)
    dependencies = []
    for value in observed["dependencies"]:
        candidate = Path(value).resolve()
        core.require(candidate.is_file(), "Blender external dependency is missing: " + value)
        dependencies.append({"path": str(candidate), "sha256": core.file_hash(candidate)})
    receipt = {"schema": 1, "kind": "blender-dependency-inspection", "source": {"path": str(path), "sha256": before},
        "inspector": {"executable": str(executable), "sha256": core.file_hash(executable), "version": found["version"],
                      "script_sha256": BLENDER_SCRIPT_SHA256, "returncode": proc.returncode},
        "stdout": proc.stdout, "stdout_sha256": hashlib.sha256(proc.stdout.encode()).hexdigest(), "dependencies": dependencies}
    return observed["dependencies"], {"mode": "actual-read-only-inspection", "actual_blender_inspection": True,
        "engine_resource_root": observed.get("engine_resource_root"), "receipt": receipt}


def audit(project, plan, style_id, entry, explicitdeps=None):
    """Audit actual serialized dependencies; optional dynamics are explicit scoped evidence."""
    project = Path(project).resolve(); config = layout.workspace(plan, project); engine = config["engine"]
    entry = core.resolve_input(entry, project)
    layout.validate_output(project, plan, entry, "dcc" if engine == "blender" else "runtime", style_id=style_id)
    explicit = _records(project, explicitdeps)
    declared = {r["path"]: r for r in explicit}
    roots = [project] + [core.resolve_input(root, project) for root in plan.get("contract", {}).get("dependency_roots", [])]
    allowed_files = {str(core.resolve_input(a["source"]["path"], project)) for a in plan.get("assets", [])
                     if a.get("source", {}).get("path") and a.get("source", {}).get("sha256")}
    found, pending, modules, inspections = {}, [entry, *[Path(r["path"]) for r in explicit]], set(), []
    engine_roots = []
    index = _unity_index(project, roots[1:]) if engine == "unity" else None
    public_root = project / config.get("public_root", "public")
    core.require(core.inside(public_root, project), "Web public root must stay inside the project")
    while pending:
        path = _reference_file(project, pending.pop(), roots, allowed_files)
        if str(path) in found: continue
        core.require(len(found) < 4096, "Dependency audit exceeded its bounded source scope")
        default_role = "baseline" if not core.inside(path, project) and any(core.inside(path, root) for root in roots[1:]) else "art"
        row = {"path": str(path), "sha256": core.file_hash(path), "role": declared.get(str(path), {}).get("role", default_role)}
        found[str(path)] = row
        suffix = path.suffix.lower()
        refs = []
        if engine == "godot":
            from . import godot
            refs.extend(godot._native_references(path, {**plan.get("contract", {}), "source_paths": [r["path"] for r in explicit]}))
        elif engine == "unity":
            refs.extend(_unity_refs(path, index, project, explicit))
            if suffix != ".meta" and (core.inside(path, project / "Assets") or core.inside(path, project / "Packages")
                                      or any(core.inside(path, root) for root in roots[1:])):
                sidecar = Path(str(path) + ".meta")
                core.require(sidecar.is_file(), "Unity resource needs its original .meta sidecar: " + str(path))
                refs.append(sidecar)
        elif engine == "threejs":
            refs.extend(_web_refs(path, project, public_root, explicit, modules))
        elif engine == "blender" and suffix == ".blend" and not any(core.inside(path, root) for root in engine_roots):
            refs, inspection = _blend_refs(path, project, plan); inspections.append(inspection)
            if inspection.get("engine_resource_root"):
                engine_root = Path(inspection["engine_resource_root"]).resolve()
                core.require(engine_root.is_dir() and not core.inside(project, engine_root), "Invalid Blender system resource root")
                roots.append(engine_root); engine_roots.append(engine_root)
        if suffix in (".gltf", ".glb") and engine != "godot": refs.extend(_gltf_refs(path))
        for reference in refs:
            value = str(reference)
            if value.startswith("res://"): value = str(project / value[6:])
            elif not Path(value).is_absolute(): value = str(path.parent / value)
            pending.append(value)
    rows = [found[key] for key in sorted(found)]
    ownership = layout.audit_dependencies(project, plan, style_id, rows,
        dependency_roots=roots[1:])
    return {"ok": ownership["ok"], "static_audit_passed": ownership["ok"], "native_verified": False,
        "engine": engine, "mode": "spatial_only" if engine == "blender" else "static_dependency_audit",
        "case_id": config["case_id"], "style_id": style_id, "entry": str(entry), "artifacts": rows,
        "dependencies": ownership["dependencies"], "issues": ownership["issues"], "external_modules": sorted(modules),
        "inspections": inspections, "actual_blender_inspection": any(i.get("actual_blender_inspection") for i in inspections),
        "limitations": ["Static dependency closure does not verify engine compilation, rendering, playability or H4/H5 acceptance.",
                        "Computed loader coverage relies on reviewed explicit for_source declarations; no static audit proves all runtime branches."]}
