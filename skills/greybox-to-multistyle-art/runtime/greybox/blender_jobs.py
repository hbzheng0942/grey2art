"""Bounded production bake/scatter/render jobs in an isolated Blender process."""
from __future__ import annotations
import json
import math
import os
from pathlib import Path
import re
import subprocess
import time

from . import blender, core

WORKER = Path(__file__).resolve().parents[1] / "blender/effects_job.py"
SKILL = Path(__file__).resolve().parents[2]


def _number(value, name, low=None, high=None):
    if type(value) not in (int, float) or not math.isfinite(value) or (low is not None and value < low) or (high is not None and value > high):
        raise ValueError(name + " must be finite and within its permitted range")


def _vector(value, name, length=3):
    if not isinstance(value, list) or len(value) != length:
        raise ValueError(name + " must contain " + str(length) + " numbers")
    for item in value:
        _number(item, name)


def _integer(value, name, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(name + " must be an integer from " + str(low) + " to " + str(high))


def _reference(value, label, output, glb=False):
    if not isinstance(value, dict) or set(value) != {"path", "sha256"}:
        raise ValueError(label + " requires exact path/sha256")
    path = Path(value["path"])
    if not path.is_absolute() or not path.is_file() or core.inside(path, output):
        raise ValueError(label + " must be an existing absolute immutable input outside the output")
    if not re.fullmatch(r"[0-9a-f]{64}", str(value["sha256"])) or core.file_hash(path) != value["sha256"]:
        raise ValueError(label + " input hash changed")
    if glb:
        if path.suffix.lower() != ".glb":
            raise ValueError("Production mesh input must be an embedded GLB")
        document = blender.read_glb(path)
        if any(row.get("uri") and not row["uri"].startswith("data:") for key in ("images", "buffers") for row in document.get(key, [])):
            raise ValueError("Input GLB has external dependencies; embed and bind them first")
    else:
        from .modeling_refs import _decode
        # Masks are production data; they need valid pixels, not modeling-reference dimensions.
        _decode(path.read_bytes())


def validate(job, check_outputs=True):
    if not isinstance(job, dict) or job.get("schema") != 1 or job.get("kind") != "blender-production-job":
        raise ValueError("Expected blender-production-job schema 1")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", str(job.get("job_id", ""))):
        raise ValueError("Use a portable stable job_id")
    operation = job.get("operation")
    if operation not in {"bake", "scatter", "render"}:
        raise ValueError("Implemented production operations are bake, scatter and render")
    if set(job) - {"schema", "kind", "job_id", "operation", "output_dir", "input", "fixture", operation}:
        raise ValueError("Unsupported production job fields; use only this operation's documented settings")
    output = Path(job.get("output_dir", ""))
    if not output.is_absolute() or output.resolve() != output or core.inside(output, SKILL):
        raise ValueError("output_dir must be canonical, absolute and outside the installed skill")
    if output.exists() and (not output.is_dir() or output.is_symlink()):
        raise ValueError("Output must be a task-owned directory")
    if check_outputs and output.exists() and any(p.name not in {"job.json"} for p in output.iterdir()):
        raise ValueError("Output contains prior/unrelated files; preserve them and choose a new job directory")
    if bool(job.get("input")) == bool(job.get("fixture")):
        raise ValueError("Choose exactly one immutable GLB input or explicit diagnostic fixture")
    if job.get("input"):
        _reference(job["input"], "Mesh", output, glb=True)
    elif job.get("fixture") != "diagnostic_cube":
        raise ValueError("Only diagnostic_cube is an implemented fixture")
    settings = job.get(operation)
    if not isinstance(settings, dict):
        raise ValueError("Declare explicit " + operation + " settings")
    allowed = {"bake": {"resolution", "channels", "uv", "normal_convention", "samples", "margin_px"},
               "scatter": {"count", "seed", "bounds_xy", "scale", "height_m", "exclude_rects", "density_mask"},
               "render": {"resolution", "frames", "samples", "view_transform", "camera", "lights", "environment", "turntable_degrees_per_frame", "transparent_background"}}
    if set(settings) - allowed[operation]:
        raise ValueError("Unsupported " + operation + " settings; no parameters are silently ignored")
    if operation == "bake":
        _integer(settings.get("resolution"), "bake resolution", 16, 4096)
        channels = settings.get("channels")
        if not isinstance(channels, list) or not channels or len(set(channels)) != len(channels) or not set(channels) <= {"base_color", "normal", "ao"}:
            raise ValueError("Bake channels must select unique base_color, normal, ao")
        uv = settings.get("uv", {})
        if uv.get("mode") not in {"preserve", "smart_project"} or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", str(uv.get("name", ""))):
            raise ValueError("Bake requires an explicit UV mode and layer name")
        if settings.get("normal_convention") not in {"opengl", "directx"}:
            raise ValueError("Declare opengl (+Y) or directx (-Y) tangent normals")
        _integer(settings.get("samples", 16), "bake samples", 1, 256)
        _integer(settings.get("margin_px", 4), "bake margin", 0, 128)
    elif operation == "scatter":
        _integer(settings.get("count"), "scatter count", 0, 100000)
        _integer(settings.get("seed"), "scatter seed", 0, 2**31-1)
        _vector(settings.get("bounds_xy"), "scatter bounds", 4)
        xmin, ymin, xmax, ymax = settings["bounds_xy"]
        if xmin >= xmax or ymin >= ymax:
            raise ValueError("scatter bounds must have positive area")
        _vector(settings.get("scale", [1, 1]), "scatter scale", 2)
        low, high = settings.get("scale", [1, 1])
        if low <= 0 or low > high:
            raise ValueError("scatter uniform scale requires 0 < min <= max")
        _number(settings.get("height_m", 0), "scatter height")
        for rectangle in settings.get("exclude_rects", []):
            _vector(rectangle, "exclude rectangle", 4)
            if rectangle[0] >= rectangle[2] or rectangle[1] >= rectangle[3]:
                raise ValueError("Exclude rectangles need positive area")
        if settings.get("density_mask"):
            _reference(settings["density_mask"], "Density mask", output)
    else:
        _vector(settings.get("resolution"), "render resolution", 2)
        for n in settings["resolution"]:
            _integer(n, "render resolution", 16, 4096)
        frames = settings.get("frames")
        if not isinstance(frames, list) or not 1 <= len(frames) <= 240 or len(set(frames)) != len(frames):
            raise ValueError("Render needs 1–240 distinct explicit frame numbers")
        for frame in frames:
            _integer(frame, "frame", 0, 999999)
        _integer(settings.get("samples", 16), "render samples", 1, 256)
        if settings.get("view_transform") not in {"Standard", "AgX"}:
            raise ValueError("Choose an explicit Standard or AgX color transform")
        camera = settings.get("camera", {})
        _vector(camera.get("position"), "camera position")
        _vector(camera.get("target"), "camera target")
        if camera["position"] == camera["target"]:
            raise ValueError("Camera position and target must differ")
        if camera.get("projection") not in {"orthographic", "perspective"}:
            raise ValueError("Choose an explicit camera projection")
        _number(camera.get("ortho_scale", 3), "ortho scale", .001)
        _number(camera.get("lens_mm", 50), "lens", 1, 1000)
        if not isinstance(settings.get("lights"), list) or not settings["lights"]:
            raise ValueError("Declare the render lights explicitly")
        for light in settings["lights"]:
            if light.get("type") not in {"AREA", "SUN", "POINT"}:
                raise ValueError("Supported light types: AREA, SUN, POINT")
            _vector(light.get("position"), "light position")
            _vector(light.get("target", [0, 0, 0]), "light target")
            _number(light.get("energy"), "light energy", 0)
            _number(light.get("size", 3), "light size", .001)
        environment = settings.get("environment", {})
        _vector(environment.get("color"), "environment color")
        for value in environment["color"]:
            _number(value, "environment color", 0, 1)
        _number(environment.get("strength"), "environment strength", 0)
        _number(settings.get("turntable_degrees_per_frame", 0), "turntable speed")
        if not isinstance(settings.get("transparent_background", False), bool):
            raise ValueError("transparent_background must be boolean")
    return {"ok": True, "operation": operation, "output_dir": str(output), "job_sha256": core.digest(job)}


def execute(job, executable=None, timeout=180):
    validate(job)
    info = blender.discover(executable)
    if info["status"] != "discovered":
        raise ValueError(info["reason"])
    output = Path(job["output_dir"])
    output.mkdir(parents=True, exist_ok=True)
    lock = output / ".production.lock"
    try:
        fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise ValueError("Another Blender production job owns this output") from None
    started = time.monotonic()
    try:
        os.close(fd)
        jobfile = output / "job.json"
        if jobfile.exists() and core.read(jobfile) != job:
            raise ValueError("Preserve the previously prepared job; changed inputs need a new output")
        core.write(jobfile, job)
        argv = [info["executable"], "--background", "--factory-startup", "--python-exit-code", "1", "--python", str(WORKER), "--", str(jobfile)]
        try:
            result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
        except subprocess.TimeoutExpired:
            core.write(output / "failure.json", {"ok": False, "reason": "timeout", "job_sha256": core.digest(job)})
            raise ValueError("Blender timed out; preserve partial output and use a new job directory") from None
        (output / "invocation.log").write_text(result.stdout + "\n" + result.stderr, encoding="utf-8")
        if result.returncode:
            raise ValueError("Blender production failed; inspect task-owned invocation.log")
        verified = verify(job)
        return {**verified, "invocation_verified": True, "executable": info["executable"], "version": info["version"],
                "elapsed_seconds": round(time.monotonic()-started, 3), "log_sha256": core.file_hash(output / "invocation.log")}
    finally:
        lock.unlink()


def verify(job):
    validate(job, check_outputs=False)
    output = Path(job["output_dir"])
    report = core.read(output / "report.json")
    if (report.get("status") != "complete" or report.get("job_sha256") != core.digest(job)
            or report.get("input") != job.get("input") or report.get("worker_sha256") != core.file_hash(WORKER)):
        raise ValueError("Completed Blender production report differs from this exact job/input")
    files = report.get("outputs", [])
    if not files:
        raise ValueError("Blender job produced no artifacts")
    for row in files:
        path = output / row["path"]
        if not core.inside(path, output) or not path.is_file() or core.file_hash(path) != row.get("sha256"):
            raise ValueError("Blender output missing, outside the output, or changed: " + row["path"])
    paths = {row["path"] for row in files}
    if job["operation"] == "bake":
        if not {"recipe.blend", "asset.glb"} <= paths:
            raise ValueError("Baking must deliver editable recipe and textured GLB")
        for channel in job["bake"]["channels"]:
            if not any(path.endswith("_" + channel + ".png") for path in paths):
                raise ValueError("Bake channel output missing: " + channel)
    elif job["operation"] == "scatter":
        transforms = core.read(output / "instances.json")
        if transforms.get("count") != job["scatter"]["count"] or len(transforms.get("instances", [])) != transforms["count"]:
            raise ValueError("Scatter count differs from the requested deterministic distribution")
    else:
        if any("frames/frame-" + str(frame).zfill(6) + ".png" not in paths for frame in job["render"]["frames"]):
            raise ValueError("Render omitted a requested frame")
    return {"ok": True, "operation": job["operation"], "job_id": job["job_id"], "report_path": str(output / "report.json"),
            "report_sha256": core.file_hash(output / "report.json"), "outputs": files,
            "native_admission": "pending", "coverage": "Isolated Blender production output; import/render in target engine remains required"}
