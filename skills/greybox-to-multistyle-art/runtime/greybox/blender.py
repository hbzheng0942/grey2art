"""Optional static-geometry backend: explicit GLB jobs, no live-document saves."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import time

WORKER = Path(__file__).resolve().parents[1] / "blender" / "backend_job.py"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def discover(executable=None):
    """Known paths only. Discovery/version success is not invocation evidence."""
    candidates = [executable, os.environ.get("BLENDER_BIN"), shutil.which("blender"),
                  "/Applications/Blender.app/Contents/MacOS/Blender",
                  str(Path.home() / "Applications/Blender.app/Contents/MacOS/Blender")]
    for value in candidates:
        if value and Path(value).is_file():
            path = str(Path(value).resolve())
            proc = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=20)
            if proc.returncode == 0 and proc.stdout.startswith("Blender "):
                return {"status": "discovered", "executable": path,
                        "version": proc.stdout.splitlines()[0], "invocation_verified": False}
    return {"status": "unavailable", "invocation_verified": False,
            "reason": "Set BLENDER_BIN; this adapter never installs Blender."}


def _number(value, label, minimum=0, strict=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(label + " must be a finite number")
    if value < minimum or (strict and value == minimum):
        raise ValueError(label + " is out of range")


def validate_job(job, *, check_outputs=True):
    if job.get("schema") != 1 or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", str(job.get("job_id", ""))):
        raise ValueError("Expected schema 1 and a portable job_id")
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,120}", str(job.get("asset_id", ""))):
        raise ValueError("asset_id is required for stable exported identities")
    if job.get("kind") not in ("static_glb", "diagnostic_cube"):
        raise ValueError("Only static_glb and diagnostic_cube are implemented; rigs need a separate path")
    output = Path(job.get("output_dir", ""))
    if not output.is_absolute() or output.resolve() != output:
        raise ValueError("output_dir must be absolute, canonical, and task-owned")
    if output.exists() and (not output.is_dir() or output.is_symlink()):
        raise ValueError("output_dir must be an owned directory")
    if check_outputs and output.is_dir() and any(p.name not in ("job.json", "run.py") for p in output.iterdir()):
        raise ValueError("Output directory contains unrelated or prior artifacts; use a new task directory")
    if check_outputs and any((output / n).exists() for n in ("asset.glb", "report.json", "preview.png")):
        raise ValueError("Refusing to overwrite an existing output; use a new job directory")
    source = job.get("input")
    if job["kind"] == "static_glb":
        if not isinstance(source, dict):
            raise ValueError("static_glb requires immutable input.path and input.sha256")
        path = Path(source.get("path", ""))
        if not path.is_absolute() or path.suffix.lower() != ".glb" or not path.is_file():
            raise ValueError("Only an existing absolute GLB input is admitted")
        if not re.fullmatch(r"[0-9a-f]{64}", str(source.get("sha256", ""))) or digest(path) != source["sha256"]:
            raise ValueError("Input hash differs from the approved immutable input")
        if path.resolve().is_relative_to(output):
            raise ValueError("Input cannot be inside the writable output directory")
        document = read_glb(path)
        if any(item.get("uri") and not item["uri"].startswith("data:")
               for key in ("images", "buffers") for item in document.get(key, [])):
            raise ValueError("GLB external dependencies are not hash-bound; embed them before admission")
    elif source:
        raise ValueError("diagnostic_cube takes no source input")
    normalize = job.get("normalize", {})
    if set(normalize) - {"unit_scale", "anchor", "target_height_m"}:
        raise ValueError("Only uniform unit scaling/height fitting is implemented; do not box-fit geometry")
    _number(normalize.get("unit_scale", 1.0), "unit_scale", strict=True)
    if normalize.get("anchor", "base_center") not in ("base_center", "origin", "center"):
        raise ValueError("Unknown semantic fitting anchor")
    if "target_height_m" in normalize:
        _number(normalize["target_height_m"], "target_height_m", strict=True)
    envelope = job.get("max_dimensions_m")
    if envelope is not None:
        if not isinstance(envelope, list) or len(envelope) != 3:
            raise ValueError("max_dimensions_m needs three positive values")
        for n in envelope:
            _number(n, "max_dimensions_m", strict=True)
    for operation in job.get("operations", []):
        if operation.get("type") != "bevel":
            raise ValueError("Only the declared bevel operation is implemented")
        _number(operation.get("width_m", 0), "bevel width", strict=True)
        segments = operation.get("segments", 2)
        if isinstance(segments, bool) or not isinstance(segments, int) or not 1 <= segments <= 8:
            raise ValueError("bevel segments must be 1–8")
    anchors = job.get("semantic_anchors", [])
    ids = set()
    for anchor in anchors:
        name = anchor.get("id", "")
        if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,120}", name) or name in ids:
            raise ValueError("semantic anchors require unique portable ids")
        ids.add(name)
        xyz = anchor.get("position_m")
        if not isinstance(xyz, list) or len(xyz) != 3:
            raise ValueError("anchor position_m must use Blender XYZ metres after normalization")
        for value in xyz:
            _number(value, "anchor position", minimum=-1e12)
    if job.get("material_policy", "inspect") not in ("inspect", "normalize_pbr"):
        raise ValueError("Unknown material policy")
    if not isinstance(job.get("render", False), bool):
        raise ValueError("render must be boolean")
    return {"ok": True, "kind": job["kind"], "output_dir": str(output),
            "coverage": "static_geometry_only; no rig/animation or gameplay proof"}


def build_script(job):
    validate_job(job)
    # repr(json) is Python source escaping, never shell interpolation.
    return "JOB = __import__('json').loads(" + repr(json.dumps(job, sort_keys=True)) + ")\n" + WORKER.read_text(encoding="utf-8")


def prepare_job(job):
    script = build_script(job)
    output = Path(job["output_dir"])
    output.mkdir(parents=True, exist_ok=True)
    for name, content in (("job.json", json.dumps(job, indent=2) + "\n"), ("run.py", script)):
        path = output / name
        if path.exists() and path.read_text(encoding="utf-8") != content:
            raise ValueError("Refusing changed job/script overwrite: " + str(path))
        if not path.exists():
            with path.open("x", encoding="utf-8") as handle:
                handle.write(content)
    return {"script_path": str(output / "run.py"), "script_sha256": digest(output / "run.py"),
            "job_sha256": digest(output / "job.json"),
            "mcp_code": "exec(compile(open(" + repr(str(output / "run.py")) + ", encoding='utf-8').read(), " + repr(str(output / "run.py")) + ", 'exec'))"}


def execute_cli(job, executable=None, timeout=180):
    info = discover(executable)
    if info["status"] != "discovered":
        raise ValueError(info["reason"])
    prepared = prepare_job(job)
    start = time.monotonic()
    args = [info["executable"], "--background", "--factory-startup", "--python-exit-code", "1", "--python", prepared["script_path"]]
    log = Path(job["output_dir"]) / "invocation.log"
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        def decoded(value):
            return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value or ""
        with log.open("x", encoding="utf-8") as handle:
            handle.write(decoded(exc.stdout) + "\n" + decoded(exc.stderr) + "\nBlender process killed after timeout; partial outputs are not reusable.\n")
        raise ValueError("Blender timed out; preserve evidence and use a new job directory: " + str(log)) from exc
    with log.open("x", encoding="utf-8") as handle:
        handle.write(proc.stdout + "\n" + proc.stderr)
    try:
        result = verify_result(job)
    except (ValueError, OSError) as exc:
        raise ValueError("Blender invocation failed; inspect task-owned log: " + str(log)) from exc
    result.update(channel="cli", executable=info["executable"], version=info["version"],
                  returncode=proc.returncode, elapsed_seconds=round(time.monotonic() - start, 3),
                  invocation_verified=proc.returncode == 0 and result["ok"], log_sha256=digest(log))
    if not result["invocation_verified"]:
        raise ValueError("Blender invocation failed; inspect task-owned log: " + str(log))
    return result


def read_glb(path):
    data = Path(path).read_bytes()
    if len(data) < 20:
        raise ValueError("Truncated GLB")
    magic, version, length = struct.unpack_from("<4sII", data)
    size, chunk = struct.unpack_from("<I4s", data, 12)
    if magic != b"glTF" or version != 2 or length != len(data) or chunk != b"JSON" or 20 + size > len(data):
        raise ValueError("Invalid GLB 2 container")
    return json.loads(data[20:20 + size])


def verify_result(job, report=None):
    validate_job(job, check_outputs=False)
    output = Path(job["output_dir"])
    report = report or json.loads((output / "report.json").read_text(encoding="utf-8"))
    expected = hashlib.sha256(json.dumps(job, sort_keys=True).encode()).hexdigest()
    if report.get("job_sha256") != expected or report.get("status") != "complete":
        raise ValueError("Blender report does not match this completed job")
    if report.get("input") != job.get("input"):
        raise ValueError("Blender report source binding differs")
    target = output / "asset.glb"
    if report.get("output", {}).get("sha256") != digest(target):
        raise ValueError("Blender output changed after execution")
    document = read_glb(target)
    ids = [n.get("extras", {}).get("stable_id") for n in document.get("nodes", []) if "mesh" in n]
    if not ids or any(not isinstance(x, str) or not x for x in ids) or len(ids) != len(set(ids)):
        raise ValueError("Export lost unique stable mesh IDs")
    dimensions = report.get("dimensions_m", [])
    if len(dimensions) != 3 or any(not math.isfinite(v) or v <= 0 for v in dimensions):
        raise ValueError("Invalid geometry bounds")
    if job.get("max_dimensions_m") and any(a > b + 1e-5 for a, b in zip(dimensions, job["max_dimensions_m"])):
        raise ValueError("Export exceeds approved visual envelope")
    if not report.get("user_state_restored"):
        raise ValueError("Blender user document state was not restored")
    if job.get("render"):
        preview = output / "preview.png"
        if not preview.is_file() or report.get("preview_sha256") != digest(preview):
            raise ValueError("Missing or changed diagnostic preview")
    return {"ok": True, "job_id": job["job_id"], "asset_path": str(target),
            "asset_sha256": digest(target), "report_path": str(output / "report.json"),
            "report_sha256": digest(output / "report.json"), "mesh_stable_ids": ids,
            "dimensions_m": dimensions, "blender_version": report.get("blender_version"),
            "coverage": "Blender static GLB execution verified; target-engine admission still required",
            "invocation_verified": True, "native_admission": "pending"}


def validate_native_admission(job, admission):
    """Check a caller-owned engine receipt, never infer import success from GLB export."""
    result = verify_result(job)
    if admission.get("asset_sha256") != result["asset_sha256"]:
        raise ValueError("Native admission must bind the exact exported GLB hash")
    if admission.get("engine") not in ("godot", "unity", "threejs"):
        raise ValueError("Native admission requires a runtime engine")
    if admission.get("status") != "passed" or not admission.get("evidence_path"):
        raise ValueError("Native admission needs actual successful engine evidence")
    path = Path(admission["evidence_path"])
    if not path.is_absolute() or not path.is_file() or digest(path) != admission.get("evidence_sha256"):
        raise ValueError("Native evidence is missing or changed")
    try:
        actual = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise ValueError("Native admission evidence must be a readable JSON engine report") from exc
    if actual.get("engine") != admission["engine"] or actual.get("asset_sha256") != result["asset_sha256"] or actual.get("status") != "passed":
        raise ValueError("Native evidence contents do not bind this successful engine import")
    for name in ("mesh_bounds", "materials", "stable_ids"):
        if admission.get("checks", {}).get(name) is not True or actual.get("checks", {}).get(name) is not True:
            raise ValueError("Native admission check missing: " + name)
    return {"ok": True, "engine": admission["engine"], "asset_sha256": result["asset_sha256"],
            "coverage": "static import admission only; gameplay and art acceptance remain separate"}
