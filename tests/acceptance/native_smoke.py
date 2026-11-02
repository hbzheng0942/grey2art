#!/usr/bin/env python3
"""Run the packaged, free Godot fixture through the public CLI.

This is a bounded native integration probe, not a production/art acceptance test.
Only six small fixture source files enter disposable scratch; retained evidence
contains reports, logs, input hashes and deduplicated captures, never a project.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone, timedelta

FIXTURE_FILES = ("README.md", "main.gd", "main.tscn", "plan.json", "project.godot", "raw_probe.tscn")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skill", type=Path, required=True, help="Verified complete source or installed package")
    parser.add_argument("--godot", type=Path, required=True, help="Existing Godot 4 executable; no download")
    parser.add_argument("--output", type=Path, required=True, help="New task-owned evidence directory")
    parser.add_argument("--reuse-captures-from", type=Path,
                        help="Existing evidence captures directory; reuse identical bytes by hash, without links or copies")
    args = parser.parse_args()
    skill, godot, output = args.skill.resolve(), args.godot.resolve(), args.output.resolve()
    fixture = skill / "fixtures" / "godot-free"
    require(not output.exists(), "Evidence output already exists; preserve the previous result")
    require(not output.is_relative_to(skill), "Evidence must stay outside the read-only Skill")
    require(godot.is_file(), "Pass an existing Godot executable")
    for name in FIXTURE_FILES:
        path = fixture / name
        require(path.is_file() and not path.is_symlink(), "Missing or linked fixture source: " + name)
    inputs = {name: {"sha256": digest(fixture / name), "bytes": (fixture / name).stat().st_size}
              for name in FIXTURE_FILES}
    source_bytes = sum(row["bytes"] for row in inputs.values())
    require(source_bytes < 1024 * 1024, "Fixture copy exceeded the one-MiB scratch limit")
    plan = json.loads((fixture / "plan.json").read_text())
    require(plan.get("purpose") == "technical_fixture", "Only the explicitly free technical fixture is allowed")
    require(not plan.get("assets"), "Fixture unexpectedly contains asset operations; inspect before running")
    require([row["id"] for row in plan["styles"]] == ["ceramic", "orbital"], "Fixture style identity changed")
    output.mkdir(parents=True)
    before_free = shutil.disk_usage(output).free
    receipt = {
        "schema": 1, "kind": "native-technical-fixture-smoke", "purpose": "technical_fixture",
        "started_at": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
        "manifest_sha256": digest(skill / "MANIFEST.json"), "acceptance_script_sha256": digest(Path(__file__)),
        "source_manifest_sha256": json.loads((skill / "MANIFEST.json").read_text())["sourceManifestSHA256"],
        "python": sys.version.split()[0], "fixture_inputs": inputs, "steps": [], "captures": [],
        "cloud_calls": 0, "production_verified": False, "art_acceptance": False,
        "human_acceptance": False, "performance_verified": False,
        "real_host_behavior": "pending: this runner executes CLI commands, not an independent agent task",
        "storage": {"scratch_fixture_source_bytes": source_bytes, "full_project_copies": False,
                    "retained_project_or_cache": False, "scratch_cleanup": "pending"},
        "ok": False,
    }
    scratch_path = None
    try:
        with tempfile.TemporaryDirectory(prefix="Grey2Art acceptance 中文 ") as temporary:
            scratch = Path(temporary).resolve()
            scratch_path = scratch
            project = scratch / "project"
            project.mkdir()
            for name in FIXTURE_FILES:
                shutil.copy2(fixture / name, project / name)
                require(digest(project / name) == inputs[name]["sha256"], "Scratch copy changed: " + name)
            run_dir = project / "art" / "experiments" / "fixture-run"
            replacements = ((str(skill), "<skill>"), (str(scratch), "<scratch>"),
                            (str(godot), "<godot>"), (sys.executable, "<python>"))

            def redact(value: object) -> object:
                if isinstance(value, str):
                    for old, new in replacements:
                        value = value.replace(old, new)
                    return value
                if isinstance(value, list):
                    return [redact(item) for item in value]
                if isinstance(value, dict):
                    return {str(redact(key)): redact(item) for key, item in value.items()}
                return value

            def command(label: str, arguments: list[str], expected: int = 0) -> dict:
                argv = [sys.executable, str(skill / "scripts" / "greybox.py"), *arguments]
                environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1",
                                   GREYBOX_IMPORT_TIMEOUT="90", GREYBOX_VALIDATE_TIMEOUT="90")
                start = time.monotonic()
                result = subprocess.run(argv, capture_output=True, text=True, env=environment, timeout=180)
                elapsed = round(time.monotonic() - start, 3)
                stdout = output / (label + ".stdout.txt")
                stderr = output / (label + ".stderr.txt")
                stdout.write_text(str(redact(result.stdout)), encoding="utf-8")
                stderr.write_text(str(redact(result.stderr)), encoding="utf-8")
                receipt["steps"].append({"name": label, "argv": redact(argv), "returncode": result.returncode,
                                         "expected_returncode": expected, "elapsed_seconds": elapsed,
                                         "stdout": stdout.name, "stderr": stderr.name})
                require(result.returncode == expected, label + " returned unexpected status; see retained logs")
                text = result.stdout if expected == 0 or result.stdout.strip() else result.stderr
                return json.loads(text)

            verify = subprocess.run([sys.executable, str(skill / "scripts" / "install.py"), "--verify-only"],
                                    capture_output=True, text=True, timeout=30)
            (output / "package-verification.stdout.txt").write_text(str(redact(verify.stdout)), encoding="utf-8")
            (output / "package-verification.stderr.txt").write_text(str(redact(verify.stderr)), encoding="utf-8")
            require(verify.returncode == 0, "Package verification failed; inspect retained verification logs")
            receipt["package_verification"] = {"returncode": verify.returncode}
            version = subprocess.run([str(godot), "--version"], capture_output=True, text=True, timeout=15)
            require(version.returncode == 0 and version.stdout.startswith("4."), "Existing executable is not Godot 4")
            receipt["engine_version"] = version.stdout.strip()

            command("01-plan", ["plan", "--file", str(project / "plan.json"), "--project", str(project),
                                "--run-dir", str(run_dir)])
            command("02-run-ceramic", ["run", "--run-dir", str(run_dir), "--godot", str(godot), "--style", "ceramic"])
            partial = command("03-validate-partial", ["validate", "--run-dir", str(run_dir), "--godot", str(godot),
                                                       "--style", "ceramic"], expected=2)
            require(partial.get("state") == "partially_validated" and partial.get("ok") is False
                    and partial["coverage"]["scope_complete"] is False,
                    "One style must not satisfy a two-style promise")
            receipt["partial_style_completion_rejected"] = True
            command("04-run-orbital", ["run", "--run-dir", str(run_dir), "--godot", str(godot), "--style", "orbital"])
            complete = command("05-validate-orbital", ["validate", "--run-dir", str(run_dir), "--godot", str(godot),
                                                        "--style", "orbital"])
            require(complete["coverage"]["scope_complete"] is True and complete["coverage"]["gameplay_passed"] is True,
                    "Both styles must pass their actual gameplay checks")
            rejected = command("06-fixture-delivery-rejected", ["delivery-manifest", "--run-dir", str(run_dir)], expected=2)
            require("only for production" in rejected.get("error", ""), "Fixture incorrectly admitted to playable H5")
            receipt["fixture_h5_rejected"] = True
            status = command("07-status", ["status", "--run-dir", str(run_dir)])
            require(status.get("delivery") == "not-accepted" and status.get("artAcceptance") == "pending-human-review",
                    "Native success must not become human art acceptance")
            receipt["version"] = status["version"]
            receipt["state"] = status["state"]
            receipt["coverage"] = status["coverage"]
            receipt["native_reports"] = []
            unique = set()
            for sid, row in complete["results"].items():
                native = row["result"]
                require(native.get("passed") is True and native.get("assertions", 0) >= 18,
                        "Missing successful native gameplay assertions for " + sid)
                report = Path(native["attempt_dir"]) / "native-report.json"
                native_report = json.loads(report.read_text())
                report_copy = output / (sid + ".native-report.json")
                write_json(report_copy, redact(native_report))
                receipt["native_reports"].append({"style": sid, "path": report_copy.name,
                                                  "sha256": digest(report_copy), "assertions": native["assertions"]})
                for capture in native_report["captures"]:
                    path = Path(capture)
                    data = path.read_bytes()
                    require(data[:8] == b"\x89PNG\r\n\x1a\n", "Native capture is not PNG")
                    width, height = struct.unpack(">II", data[16:24])
                    content_hash = hashlib.sha256(data).hexdigest()
                    target = output / "captures" / (content_hash + ".png")
                    reused = None
                    if args.reuse_captures_from is not None:
                        existing = args.reuse_captures_from.resolve() / (content_hash + ".png")
                        if existing.is_file() and digest(existing) == content_hash:
                            reused = existing
                    if content_hash not in unique:
                        if reused is None:
                            target.parent.mkdir(exist_ok=True)
                            target.write_bytes(data)
                        unique.add(content_hash)
                    receipt["captures"].append({"style": sid, "state": path.stem,
                                                "path": os.path.relpath(reused or target, output), "sha256": content_hash,
                                                "retention": "shared_existing_capture" if reused else "new_capture",
                                                "bytes": len(data), "width": width, "height": height})
            receipt["unique_capture_files"] = len(unique)
            final_verify = subprocess.run(
                [sys.executable, str(skill / "scripts" / "install.py"), "--verify-only"],
                capture_output=True, text=True, timeout=30)
            (output / "package-reverification.stdout.txt").write_text(str(redact(final_verify.stdout)), encoding="utf-8")
            (output / "package-reverification.stderr.txt").write_text(str(redact(final_verify.stderr)), encoding="utf-8")
            receipt["package_verification"]["final_returncode"] = final_verify.returncode
            receipt["source_package_unchanged"] = (
                final_verify.returncode == 0
                and receipt["manifest_sha256"] == digest(skill / "MANIFEST.json")
                and all(digest(fixture / name) == row["sha256"] for name, row in inputs.items()))
            require(receipt["source_package_unchanged"], "Read-only fixture or package identity changed during test")
            receipt["ok"] = True
        receipt["storage"]["scratch_cleanup"] = "removed" if not scratch_path.exists() else "failed"
    except (ValueError, KeyError, OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
        receipt["error"] = str(error)
        if scratch_path is not None:
            receipt["storage"]["scratch_cleanup"] = "removed" if not scratch_path.exists() else "failed"
    receipt["completed_at"] = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")
    receipt["storage"]["retained_evidence_bytes_before_receipt"] = sum(
        path.stat().st_size for path in output.rglob("*") if path.is_file())
    receipt["storage"]["volume_free_space_delta_bytes"] = shutil.disk_usage(output).free - before_free
    receipt["storage"]["measurement_note"] = "Volume free-space observation includes unrelated concurrent filesystem activity."
    write_json(output / "result.json", receipt)
    print(json.dumps({key: receipt.get(key) for key in ("ok", "kind", "version", "state", "unique_capture_files", "error")}, indent=2))
    return 0 if receipt["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
