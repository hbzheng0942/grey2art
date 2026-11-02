"""Explicit-input Hole look development. No provider calls or legacy run dependencies."""
from __future__ import annotations
import copy
import hashlib
import html
import json
import math
import os
import re
from pathlib import Path
import shutil
import subprocess
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
CONDITIONS = {"baseline": (False, False), "assembly": (True, False),
              "render": (False, True), "combined": (True, True)}


def read(path):
    return json.loads(Path(path).read_text())


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    os.replace(tmp, path)


def require(ok, message):
    if not ok:
        raise ValueError(message)


def resolve(base, value):
    p = Path(value).expanduser()
    return (base / p).resolve() if not p.is_absolute() else p.resolve()


def checked(path, expected):
    require(Path(path).is_file(), "Missing input: " + str(path))
    require(file_hash(path) == expected, "Input hash changed: " + str(path))


def number(value, lo, hi, label):
    require(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and lo <= value <= hi,
            "Out-of-range " + label)


def keys(value, allowed, label):
    require(isinstance(value, dict), "Expected object: " + label)
    require(not set(value) - set(allowed), "Unknown fields in " + label + ": " + str(set(value) - set(allowed)))


def controls_for(adjustments, style, condition):
    assembly, render = CONDITIONS[condition]
    s = adjustments["styles"][style]
    return {"schema": 1, "assembly": copy.deepcopy(s.get("assembly", {})) if assembly else {},
            "render": copy.deepcopy(s.get("render", {})) if render else {}}


def validate_controls(controls, skin):
    keys(controls, ["schema", "assembly", "render"], "controls")
    require(controls.get("schema") == 1, "Unsupported controls schema")
    assembly, render = controls.get("assembly", {}), controls.get("render", {})
    keys(assembly, ["regions", "assets", "paving_gap_multiplier"], "assembly")
    if "paving_gap_multiplier" in assembly:
        number(assembly["paving_gap_multiplier"], .05, 2, "paving gap")
    for group, field in [("regions", "regionId"), ("assets", "assetKey")]:
        for name, values in assembly.get(group, {}).items():
            matches = [s for s in skin.values() if s[field] == name]
            require(matches, "Unknown assembly target: " + name)
            keys(values, ["target_xyz", "yaw_degrees", "band", "cluster_count"], name)
            if "cluster_count" in values:
                number(values["cluster_count"], 0, 6, "cluster count")
                require(isinstance(values["cluster_count"], int), "Cluster count must be an integer")
                require(all(s["gameplayXYZ"][0] >= 1.5 and s["gameplayXYZ"][2] >= 1.5 for s in matches), "Clusters require a building footprint")
            if "yaw_degrees" in values:
                number(values["yaw_degrees"], -180, 180, "visual yaw")
            if "band" in values:
                b = values["band"]
                require(isinstance(b, list) and len(b) == 2, "Invalid fit band")
                number(b[0], 0, .9, "band lower")
                number(b[1], .1, 1, "band upper")
                require(b[1] - b[0] >= .05, "Fit band too narrow")
            if "target_xyz" in values:
                xyz = values["target_xyz"]
                require(isinstance(xyz, list) and len(xyz) == 3, "Invalid visual target")
                for spec in matches:
                    for i, v in enumerate(xyz):
                        number(v, spec["minXYZ"][i], spec["maxXYZ"][i], name + " visual target")
    keys(render, ["ambient_energy", "exposure", "sun_energy", "sun_angular_distance", "ambient_color",
                  "sun_color", "sun_rotation_degrees", "floor", "background_detail", "materials", "shadow_filter_quality", "shadow_blur", "shadow_opacity"], "render")
    for name, lo, hi in [("ambient_energy", 0, 1.5), ("exposure", .5, 1.5), ("sun_energy", .1, 2),
                         ("sun_angular_distance", 0, 10), ("background_detail", 0, 1), ("shadow_blur", .1, 10), ("shadow_opacity", 0, 1)]:
        if name in render:
            number(render[name], lo, hi, name)
    if "shadow_filter_quality" in render:
        require(isinstance(render["shadow_filter_quality"], int), "Shadow filter must be an integer")
        number(render["shadow_filter_quality"], 0, 5, "shadow filter")
    for name in ["ambient_color", "sun_color"]:
        if name in render:
            v = render[name]
            require(isinstance(v, str) and len(v) == 6 and all(c in "0123456789abcdefABCDEF" for c in v), "Invalid color")
    if "sun_rotation_degrees" in render:
        a = render["sun_rotation_degrees"]
        require(isinstance(a, list) and len(a) == 3, "Invalid sun rotation")
        for v in a:
            number(v, -180, 180, "sun rotation")
    floor = render.get("floor", {})
    keys(floor, ["seam_strength", "grain_strength", "variation_strength", "lane_mark_strength", "roughness_multiplier"], "floor")
    for name, v in floor.items():
        number(v, 0 if name != "roughness_multiplier" else .2, 2, name)
    for region, v in render.get("materials", {}).items():
        require(any(s["regionId"] == region for s in skin.values()), "Unknown material region")
        keys(v, ["roughness_multiplier"], "material look")
        if "roughness_multiplier" in v:
            number(v["roughness_multiplier"], .2, 2, "material roughness")


def runtime_files():
    return [*sorted((ROOT / "adapters/godot").glob("*")), ROOT / "scripts/lookdev.py",
            ROOT / "scripts/lookdev_core.py", ROOT / "scripts/render_contract.py"]


def load_case(path, source_root=None, asset_root=None):
    path = Path(path).resolve()
    c = read(path)
    require(c.get("schema") == 1 and c.get("engine") == "godot-hole", "Unsupported case/engine; implement an adapter first")
    base = path.parent
    source = resolve(base, source_root or c["sourceRoot"])
    store = resolve(base, asset_root or c["assetRoot"])
    paths = {k: resolve(base, c[k]) for k in ["sourceManifest", "spatialContract", "realizationContract", "assetManifest", "adjustments", "targets"]}
    docs = {k: read(p) for k, p in paths.items()}
    expected = {f["path"]: f["sha256"] for f in docs["sourceManifest"]["files"]}
    for name, sha in expected.items():
        checked(source / name, sha)
    assets = docs["assetManifest"]
    require(assets.get("schema") == 1, "Unsupported asset manifest")
    require(set(assets["styles"]) == {"ceramic", "orbital"}, "Both Hole styles are required")
    for sha, asset in assets["assets"].items():
        p = resolve(store, asset["file"])
        require(p.is_relative_to(store), "Asset escapes canonical store")
        checked(p, sha)
        require(p.stat().st_size == asset["bytes"], "Asset size changed")
    spatial = docs["spatialContract"]
    ids = {s["id"] for s in spatial["slots"]}
    spatial_slots = {s["id"]: s for s in spatial["slots"]}
    require(len(ids) == 215, "Hole adapter expects 215 source slots")
    contract = docs["realizationContract"]
    contract_bindings = {(b["styleId"], b["slotId"]): b for b in contract["bindings"]}
    require(len(contract_bindings) == 430, "Incomplete realization contract")
    skin = copy.deepcopy(assets["styles"])
    for style, bindings in skin.items():
        require(set(bindings) == ids, "Incomplete/unknown slots: " + style)
        for slot, spec in bindings.items():
            b = contract_bindings[(style, slot)]
            require(b["gameplayXYZ"] == spatial_slots[slot]["gameplay_size_xyz"], "Gameplay bounds changed: " + slot)
            for axis in range(3):
                require(0 < b["minXYZ"][axis] <= b["visualTargetXYZ"][axis] <= b["maxXYZ"][axis], "Invalid visual envelope")
                if b["maxXYZ"][axis] > b["gameplayXYZ"][axis]:
                    require(axis == 1 and b.get("visualEnvelopeException", {}).get("reason") and
                            b["maxXYZ"][axis] <= b["gameplayXYZ"][axis] * 1.625, "Unreviewed visual envelope expansion")
            for key in ["styleId", "slotId", "regionId", "assetKey", "variant", "gameplayXYZ", "minXYZ", "maxXYZ", "visualTargetXYZ"]:
                require(spec[key] == b[key], "Binding differs from realization contract: " + slot + "/" + key)
            sha = spec["sha256"]
            require(sha in assets["assets"], "Unmapped model hash")
            spec["path"] = str(resolve(store, assets["assets"][sha]["file"]))
    coffee = assets["coffee"]
    require(coffee in assets["assets"], "Coffee texture missing")
    for s in docs["targets"]["styles"].values():
        concept = s["conceptSHA256"]
        require(concept in assets["assets"], "Concept image missing")
        require(s["defects"], "Missing declared art targets")
    require(set(docs["adjustments"]["styles"]) == set(skin), "Adjustments must cover both styles")
    for style in skin:
        for condition in CONDITIONS:
            validate_controls(controls_for(docs["adjustments"], style, condition), skin[style])
    cam = c["camera"]
    require(cam == {"position": [-12, 16, 6], "target": [-12, 0, -8], "size": 19, "viewport": [1536, 1024]}, "Unsupported review camera")
    # Structural GLB inspection is independent of native material/render acceptance.
    from render_contract import validate_materials
    glbs = {s["sha256"]: s["path"] for bindings in skin.values() for s in bindings.values()}
    materials = {sha: validate_materials(p) for sha, p in glbs.items()}
    files = {str(p.relative_to(ROOT)): file_hash(p) for p in runtime_files() if p.is_file()}
    signature = digest({"case": c, "documents": docs, "sourceFiles": expected, "runtime": files})
    return {"path": path, "case": c, "source": source, "store": store, "paths": paths, "docs": docs,
            "expected": expected, "skin": skin, "runtime": files, "signature": signature,
            "materials": materials}


def patch_once(text, old, new):
    require(text.count(old) == 1, "Source adapter pattern changed: " + old)
    return text.replace(old, new, 1)


def assemble(case, overlay, godot):
    """All validation precedes staging; only task-owned, small source overlays are written."""
    overlay = Path(overlay).resolve()
    marker = overlay / "lookdev-overlay.json"
    if marker.exists() and read(marker).get("signature") == case["signature"]:
        rec = read(marker)
        if all((overlay / p).is_file() and file_hash(overlay / p) == sha for p, sha in rec["files"].items()):
            return overlay
    require(not overlay.exists() or marker.exists(), "Refusing to replace an unowned overlay")
    stage = overlay.with_name(overlay.name + ".staging")
    require(not stage.exists(), "Unfinished staging exists; inspect before removing: " + str(stage))
    stage.mkdir(parents=True)
    source, root = case["source"], ROOT
    files = {}
    def put(name, value):
        p = stage / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(value.encode() if isinstance(value, str) else value)
        files[name] = file_hash(p)
    try:
        names = ["project.godot", "scenes/Main.tscn"]
        names += [str(p.relative_to(source)) for p in sorted((source / "scripts").glob("*.gd"))]
        names += [str(p.relative_to(source)) for p in sorted((source / "shaders").glob("*.gdshader"))]
        for name in names:
            text = (source / name).read_text()
            if name.endswith(".gdshader") and re.search(r"\bTIME\b", text):
                # Preserve live animation; native review freezes every original TIME shader.
                text = re.sub(r"\bTIME\b", "(review_time >= 0.0 ? review_time : TIME)", text)
                text = text.replace("shader_type spatial;", "shader_type spatial;\nuniform float review_time = -1.0;", 1)
            if name == "project.godot":
                text = text.replace("Hole Waterfront Lab v0.3", "Hole Look Development")
                text = text.replace("gl_compatibility", "mobile").replace("GL Compatibility", "Mobile")
                if "anti_aliasing/quality/msaa_3d=1" in text:
                    text = text.replace("anti_aliasing/quality/msaa_3d=1", "anti_aliasing/quality/msaa_3d=2")
                elif "anti_aliasing/quality/msaa_3d" not in text:
                    text += "\n[rendering]\nanti_aliasing/quality/msaa_3d=2\n"
            if name == "scripts/main.gd":
                text = patch_once(text, 'factory.build(o["definition"], str(o["asset_id"]))', 'factory.build(o["definition"], str(o["asset_id"]), str(o["id"]))')
                text += "\nfunc _exit_tree() -> void:\n\tif factory != null: factory.release_templates()\n"
            if name == "scripts/visual_factory.gd":
                text = patch_once(text, 'asset_id: String = "") -> Node3D:', 'asset_id: String = "", logical_id: String = "") -> Node3D:')
                put("scripts/baseline_visual_factory.gd", text)
                text = (root / "adapters/godot/pilot_visual_factory.gd").read_text()
            if name == "scripts/waterfront_stage.gd":
                put("scripts/baseline_waterfront_stage.gd", text)
                text = (root / "adapters/godot/art_stage.gd").read_text()
            put(name, text)
        for p in sorted((root / "adapters/godot").glob("*")):
            if p.name in ["pilot_visual_factory.gd", "art_stage.gd"] or not p.is_file():
                continue
            folder = "shaders" if p.suffix == ".gdshader" else ("tests" if p.name in ["capture_pilot.gd", "material_probe.gd"] else "scripts")
            put(folder + "/" + p.name, p.read_bytes())
        links = ["data/graybox_config.json", "data/visual_proxies.json", "data/scenery.json", "data/default_tuning.tres"]
        links += [str(p.relative_to(source)) for p in sorted((source / "assets/audio").glob("*.wav"))]
        # Small immutable configs/audio are copied, so Windows requires no symlink privilege.
        # Model and texture buffers remain canonical external references.
        copy_bytes = sum((source / name).stat().st_size for name in links)
        require(copy_bytes <= 32 * 1024 * 1024, "Legacy small-resource overlay exceeds 32 MiB; inspect before copying")
        for name in links:
            original = source / name
            require(original.is_file(), "Missing source resource: " + str(original))
            p = stage / name
            p.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(original, p)
            require(file_hash(p) == file_hash(original), "Overlay resource copy mismatch: " + name)
            files[name] = file_hash(p)
        put("data/art_realization.json", json.dumps(case["docs"]["realizationContract"]))
        put("data/pilot_skin.json", json.dumps(case["skin"]))
        sha = case["docs"]["assetManifest"]["coffee"]
        put("data/coffee-texture.json", json.dumps({"path": str(case["store"] / case["docs"]["assetManifest"]["assets"][sha]["file"]), "sha256": sha}))
        put("data/look_camera.json", json.dumps(case["case"]["camera"]))
        result = subprocess.run([str(godot), "--headless", "--path", str(stage), "--editor", "--import"], capture_output=True, text=True, timeout=180)
        (stage / "import.log").write_text(result.stdout + result.stderr)
        require(result.returncode == 0 and "SCRIPT ERROR" not in result.stdout + result.stderr and "Parse Error" not in result.stdout + result.stderr,
                "Overlay import failed; inspect " + str(stage / "import.log"))
        write(stage / "lookdev-overlay.json", {"signature": case["signature"], "files": files, "assetsCopied": 0})
        previous = overlay.with_name(overlay.name + ".previous")
        require(not previous.exists(), "Previous task overlay still exists")
        if overlay.exists():
            overlay.rename(previous)
        try:
            stage.rename(overlay)
        except BaseException:
            if previous.exists():
                previous.rename(overlay)
            raise
        # Retain the previous task-owned runtime until the first real native capture passes.
        return overlay
    except BaseException:
        # Preserve failed staged source/log for diagnosis, with explicit task ownership.
        write(stage / "lookdev-failed.json", {"taskOwned": True, "signature": case["signature"]})
        raise


def settle_overlay(overlay, success):
    overlay = Path(overlay)
    previous = overlay.with_name(overlay.name + ".previous")
    if success:
        if previous.exists():
            require((previous / "lookdev-overlay.json").exists(), "Unowned previous overlay")
            shutil.rmtree(previous)
    elif previous.exists():
        require((overlay / "lookdev-overlay.json").exists(), "Unowned candidate overlay")
        shutil.rmtree(overlay)
        previous.rename(overlay)


def native_capture(case, overlay, controls, style, directory, godot, mode="look"):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    control_path = directory / "controls.json"
    write(control_path, controls)
    env = dict(os.environ, HOLE_ART_STYLE=style, HOLE_ART_CONTROLS=str(control_path.resolve()),
               HOLE_ART_EVIDENCE=str(directory.resolve()), HOLE_ART_EXPECTED="215", HOLE_CAPTURE_MODE=mode)
    started = time.time()
    try:
        result = subprocess.run([str(godot), "--path", str(overlay), "--script", "res://tests/capture_pilot.gd"],
                                env=env, capture_output=True, text=True, timeout=240)
    except subprocess.SubprocessError:
        settle_overlay(overlay, False)
        raise
    (directory / "native.log").write_text(result.stdout + result.stderr)
    if result.returncode != 0 or "SCRIPT ERROR" in result.stdout + result.stderr:
        settle_overlay(overlay, False)
        raise ValueError("Native capture failed: " + str(directory / "native.log"))
    native_path = directory / (style + "-native.json")
    try:
        native = read(native_path)
        require(native["controlsFileSHA256"] == file_hash(control_path), "Native controls mismatch")
        require(native["logicalObjects"] == native["loadedGeneratedInstances"] == 215 and
                not native["boundsFailures"] and not native["artContractFailures"], "Native structural failure")
        captures = {Path(p).name: {"path": str(Path(p).resolve()), "sha256": file_hash(p)} for p in native["captures"]}
    except (ValueError, OSError, KeyError):
        settle_overlay(overlay, False)
        raise
    settle_overlay(overlay, True)
    return {"style": style, "mode": mode, "startedAt": started, "finishedAt": time.time(),
            "seconds": time.time() - started, "controls": controls, "controlsSHA256": file_hash(control_path),
            "native": {"path": str(native_path.resolve()), "sha256": file_hash(native_path)}, "captures": captures}


def image_delta(a, b):
    from PIL import Image, ImageChops, ImageStat
    with Image.open(a) as im_a, Image.open(b) as im_b:
        require(im_a.size == im_b.size, "Capture viewport differs")
        d = ImageChops.difference(im_a.convert("RGB"), im_b.convert("RGB"))
        stat = ImageStat.Stat(d)
        return {"meanAbsolute255": sum(stat.mean) / 3, "maxChannel255": max(v[1] for v in stat.extrema)}


def verify_record(rec):
    checked(rec["native"]["path"], rec["native"]["sha256"])
    for value in rec["captures"].values():
        checked(value["path"], value["sha256"])
    cp = Path(rec["native"]["path"]).parent / "controls.json"
    checked(cp, rec["controlsSHA256"])


def reserve_call(path, kind, request_hash, quoted_credits=None):
    """Reserve before dispatch. Unknown outcomes consume allowance and cannot be reissued."""
    path = Path(path)
    lock = path.with_suffix(".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    try:
        ledger = read(path) if path.exists() else {"limits": {"images": 6, "models": 3, "credits": 60}, "attempts": []}
        require(kind in ["images", "models"], "Unknown paid operation")
        require(not any(a["requestHash"] == request_hash for a in ledger["attempts"]), "Reconcile existing attempt before reissue")
        require(sum(a["kind"] == kind for a in ledger["attempts"]) < ledger["limits"][kind], "Call budget exhausted")
        if kind == "models":
            number(quoted_credits, 0, ledger["limits"]["credits"], "quoted credits")
            require(sum(a.get("quotedCredits", 0) for a in ledger["attempts"]) + quoted_credits <= ledger["limits"]["credits"], "Credit budget exhausted")
        ledger["attempts"].append({"kind": kind, "requestHash": request_hash, "status": "submission-unknown",
                                   "quotedCredits": quoted_credits or 0, "reservedAt": time.time()})
        write(path, ledger)
        return ledger
    finally:
        lock.unlink()


def report(case, experiment, output):
    def url(p):
        try:
            value = os.path.relpath(p, output)
        except ValueError:  # Windows cross-drive canonical assets.
            value = Path(p).resolve().as_uri()
        return html.escape(value.replace("\\", "/"), quote=True)
    parts = ['<!doctype html><meta charset="utf-8"><title>Hole 双风格还原实验</title>',
             '<style>body{background:#15191f;color:#e5e8ed;font:15px/1.6 system-ui;margin:28px}img{width:100%}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px}figure{margin:0}code{word-break:break-all}a{color:#9bd0ff}</style>',
             '<h1>Hole · 双风格组装与渲染对照</h1><p>技术检查与原概念还原分别评审。人类最终美术验收待确认；本页不推断历史提效。</p>']
    for style, target in case["docs"]["targets"]["styles"].items():
        concept = case["store"] / case["docs"]["assetManifest"]["assets"][target["conceptSHA256"]]["file"]
        parts += ["<h2>" + html.escape(style) + "</h2><div class=grid><figure><img src='" + url(concept) + "'><figcaption>原选定概念</figcaption></figure><div><h3>冻结验收目标</h3><ul>"]
        parts += ["<li>" + html.escape(d["observation"] + "；目标：" + d["target"]) + "</li>" for d in target["defects"]]
        parts += ["</ul></div></div><div class=grid>"]
        for key, rec in experiment["results"].items():
            if rec["style"] != style:
                continue
            p = rec["captures"][style + "-zone-b.png"]["path"]
            runtime = rec["captures"][style + "-runtime-b.png"]["path"]
            parts += ["<figure><img src='" + url(p) + "'><figcaption>" + html.escape(key) + " · " + str(round(rec["seconds"], 2)) + " 秒 · <a href='" + url(runtime) + "'>玩法镜头</a> · <a href='" + url(rec["native"]["path"]) + "'>原生收据</a></figcaption></figure>"]
        parts += ["</div>"]
    parts += ["<p>源码/输入签名：<code>" + experiment["signature"] + "</code></p>"]
    (output / "report.html").write_text("\n".join(parts))
