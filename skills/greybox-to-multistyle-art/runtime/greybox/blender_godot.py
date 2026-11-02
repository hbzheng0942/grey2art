"""Actual static GLB admission through the native Godot GLTFDocument importer."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess
import time
import uuid

from .blender import digest, validate_native_admission, verify_result
from .godot import engine

SCRIPT = Path(__file__).resolve().parents[1] / "godot" / "asset_admission.gd"
ERROR_LINE = re.compile(r"^\s*(?:(?:SCRIPT|USER)\s+)?ERROR\b|^\s*(?:Parse|Parser|Compile)\s+Error\b|^\s*E\s+\d+:\d+", re.I)


def fatal_log_lines(log):
    return [line for line in log.splitlines() if ERROR_LINE.search(line)]


def _write(path, value):
    with Path(path).open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(value, indent=2) + "\n" if not isinstance(value, str) else value)


def _stream_digest(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for part in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(part)
    return value.hexdigest()


def native_admit(job, godot_path=None):
    verified = verify_result(job)
    source = json.loads(Path(verified["report_path"]).read_text(encoding="utf-8"))
    executable = engine(godot_path)
    version = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=20)
    if version.returncode != 0 or not version.stdout.strip().startswith("4."):
        raise ValueError("Native admission needs the installed Godot 4 executable")
    root = Path(job["output_dir"]) / "native-godot"
    if root.is_symlink() or root.resolve() != root:
        raise ValueError("Native output must remain inside the task-owned canonical directory")
    root.mkdir(exist_ok=True)
    attempt = "attempt_" + uuid.uuid4().hex
    output = root / attempt
    output.mkdir()
    project = output / "project.godot"
    _write(project, '; Task-owned import diagnostic. References the canonical GLB; no copied assets.\nconfig_version=5\n[application]\nconfig/name="Greybox GLB admission"\n[rendering]\nrenderer/rendering_method="gl_compatibility"\n[debug]\nfile_logging/enable_file_logging=false\n')
    # Blender Z-up dimensions become glTF/Godot Y-up dimensions.
    dimensions = verified["dimensions_m"]
    config = {"schema": 1, "attempt": attempt, "asset_path": verified["asset_path"],
              "asset_sha256": verified["asset_sha256"], "expected_mesh_ids": verified["mesh_stable_ids"],
              "expected_dimensions_m": [dimensions[0], dimensions[2], dimensions[1]],
              "require_base_contact": job.get("normalize", {}).get("anchor", "base_center") == "base_center",
              "source_materials": source.get("materials", []), "output_path": str(output / "probe-report.json")}
    _write(output / "probe.json", config)
    bindings = {"blender_report": {"path": verified["report_path"], "sha256": verified["report_sha256"]},
                "adapter": {"path": str(Path(__file__).resolve()), "sha256": digest(__file__)},
                "blender_verifier": {"path": str(Path(__file__).with_name("blender.py").resolve()), "sha256": digest(Path(__file__).with_name("blender.py"))},
                "runtime_script": {"path": str(SCRIPT), "sha256": digest(SCRIPT)},
                "project": {"path": str(project), "sha256": digest(project)},
                "probe_config": {"path": str(output / "probe.json"), "sha256": digest(output / "probe.json")},
                "engine_binary": {"path": executable, "sha256": _stream_digest(executable)}}
    args = [executable, "--headless", "--path", str(output), "--script", str(SCRIPT), "--", str(output / "probe.json")]
    start = time.monotonic()
    try:
        process = subprocess.run(args, capture_output=True, text=True, timeout=60)
        log = process.stdout + "\n" + process.stderr
    except subprocess.TimeoutExpired as exc:
        def decoded(value):
            return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value or ""
        _write(output / "invocation.log", decoded(exc.stdout) + "\n" + decoded(exc.stderr) + "\nNative probe killed after timeout.\n")
        _write(output / "attempt.json", {"status": "failed_timeout", "attempt": attempt, "bindings": bindings})
        raise ValueError("Godot admission timed out; preserve attempt: " + str(output)) from exc
    _write(output / "invocation.log", log)
    errors = fatal_log_lines(log)
    attempt_receipt = {"schema": 1, "attempt": attempt, "channel": "native_cli", "argv": args,
                       "returncode": process.returncode, "elapsed_seconds": round(time.monotonic() - start, 3),
                       "version": version.stdout.strip(), "bindings": bindings,
                       "log": {"path": str(output / "invocation.log"), "sha256": digest(output / "invocation.log")},
                       "fatal_log_lines": errors}
    _write(output / "attempt.json", attempt_receipt)
    probe_path = output / "probe-report.json"
    if process.returncode != 0 or errors or not probe_path.is_file():
        raise ValueError("Godot admission rejected engine error/output; inspect: " + str(output / "invocation.log"))
    probe = json.loads(probe_path.read_text(encoding="utf-8"))
    if probe.get("status") != "passed" or probe.get("asset_sha256") != verified["asset_sha256"] or probe.get("attempt") != attempt:
        raise ValueError("Godot native checks failed; inspect: " + str(probe_path))
    if digest(verified["asset_path"]) != verified["asset_sha256"]:
        raise ValueError("Source GLB changed during native admission")
    for key, item in bindings.items():
        observed = _stream_digest(item["path"]) if key == "engine_binary" else digest(item["path"])
        if observed != item["sha256"]:
            raise ValueError("Native admission input changed during execution: " + key)
    report = {**probe, "probe_report": {"path": str(probe_path), "sha256": digest(probe_path)},
              "attempt_receipt": {"path": str(output / "attempt.json"), "sha256": digest(output / "attempt.json")},
              "bindings": bindings, "log": attempt_receipt["log"], "returncode": process.returncode,
              "fatal_log_lines": errors,
              "coverage": "actual native Godot static GLB import; no gameplay or art acceptance"}
    report_path = output / "admission-report.json"
    _write(report_path, report)
    receipt = {"schema": 1, "engine": "godot", "asset_sha256": verified["asset_sha256"],
               "status": "passed", "evidence_path": str(report_path), "evidence_sha256": digest(report_path),
               "checks": probe["checks"], "attempt": attempt}
    _write(output / "admission.json", receipt)
    verify_godot_admission(job, receipt)
    return receipt


def verify_godot_admission(job, receipt):
    validated = validate_native_admission(job, receipt)
    report = json.loads(Path(receipt["evidence_path"]).read_text(encoding="utf-8"))
    if report.get("returncode") != 0 or report.get("fatal_log_lines"):
        raise ValueError("Native admission contains engine errors")
    for key in ("probe_report", "attempt_receipt", "log"):
        item = report.get(key, {})
        path = Path(item.get("path", ""))
        if not path.is_file() or digest(path) != item.get("sha256"):
            raise ValueError("Changed native admission evidence: " + key)
    if fatal_log_lines(Path(report["log"]["path"]).read_text(encoding="utf-8")):
        raise ValueError("Actual engine log contains errors despite pass report")
    for key, item in report.get("bindings", {}).items():
        path = Path(item["path"])
        if not path.is_file() or (_stream_digest(path) if key == "engine_binary" else digest(path)) != item["sha256"]:
            raise ValueError("Native source/runtime binding changed: " + key)
    if not {"adapter", "blender_verifier", "runtime_script", "project", "probe_config", "engine_binary", "blender_report"}.issubset(report.get("bindings", {})):
        raise ValueError("Native admission is missing producer bindings")
    return {**validated, "attempt": receipt.get("attempt"), "invocation_verified": True}
