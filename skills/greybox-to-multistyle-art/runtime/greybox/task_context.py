"""Pin the actual CLI entry in PLAN; never infer host/model identity or migrate jobs."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys

from . import core, host, host_setup

SKILL = Path(__file__).resolve().parents[2]
SESSION_FIELDS = {"host", "session_id", "model", "tool_schema_sha256"}


def _package(root, *, verify=False):
    root = Path(root).expanduser().resolve()
    manifest_path = root / "MANIFEST.json"
    manifest = core.read(manifest_path)
    core.require(isinstance(manifest, dict) and manifest.get("name") == "greybox-to-multistyle-art",
                 "Not a greybox skill package")
    result = {"root": str(root), "entry": str(root / "scripts/greybox.py"),
              "version": manifest.get("version"), "manifest_sha256": core.file_hash(manifest_path),
              "source_sha256": manifest.get("sourceManifestSHA256")}
    if verify:
        rows = []
        for path in sorted(root.rglob("*")):
            if (not path.is_file() or path == manifest_path or "__pycache__" in path.parts
                    or path.name == ".DS_Store" or path.suffix in {".pyc", ".pyo"}):
                continue
            core.require(not path.is_symlink() and core.inside(path, root), "Skill source contains a symbolic file link")
            rows.append({"path": path.relative_to(root).as_posix(), "bytes": path.stat().st_size,
                         "sha256": core.file_hash(path)})
        actual = hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        result.update({"actual_source_sha256": actual,
                       "integrity_ok": rows == manifest.get("files") and actual == result["source_sha256"]
                       and (root / "scripts/greybox.py").is_file()})
    return result


def _session(report=None):
    report = report or {}
    core.require(isinstance(report, dict) and set(report) <= SESSION_FIELDS | {"source_ref"},
                 "Session report accepts host/session_id/model/tool_schema_sha256/source_ref only")
    if any(report.get(key) is not None for key in SESSION_FIELDS):
        core.require(isinstance(report.get("source_ref"), str) and report["source_ref"].strip(),
                     "Explicit session identity needs its actual source_ref")
    for key in SESSION_FIELDS:
        core.require(report.get(key) is None or isinstance(report[key], str) and bool(report[key].strip()),
                     "Session values must be nonempty text or null: " + key)
    core.require(report.get("host") is None or report["host"] in host.HOSTS, "Unsupported reported host")
    sha = report.get("tool_schema_sha256")
    core.require(sha is None or len(sha) == 64 and all(c in "0123456789abcdef" for c in sha),
                 "Tool schema fingerprint must be a SHA-256 of the actual available schema")
    return {**{key: report.get(key) for key in sorted(SESSION_FIELDS)}, "source_ref": report.get("source_ref"),
            "evidence": "explicit_report" if report else "unavailable"}


def validate_context(value):
    core.require(isinstance(value, dict) and set(value) == {"schema", "kind", "package", "python", "project", "session"}
                 and value.get("schema") == 1 and value.get("kind") == "greybox-task-context", "Invalid task execution context")
    package = value.get("package", {})
    core.require(isinstance(package, dict) and set(package) == {"root", "entry", "version", "manifest_sha256",
                 "source_sha256", "actual_source_sha256", "integrity_ok"}, "Task context needs actual package identity")
    core.require(package.get("integrity_ok") is True, "Refresh the source manifest before pinning this skill entry")
    core.require(isinstance(package["version"], str) and bool(package["version"]), "Skill version required")
    for key in ("manifest_sha256", "source_sha256", "actual_source_sha256"):
        core.require(isinstance(package[key], str) and len(package[key]) == 64
                     and all(c in "0123456789abcdef" for c in package[key]), "Invalid package hash")
    core.require(package["source_sha256"] == package["actual_source_sha256"], "Pinned package source differs from manifest")
    for key in ("root", "entry"):
        core.require(isinstance(package.get(key), str) and Path(package[key]).is_absolute(), "Absolute skill entry required")
    core.require(Path(package["entry"]) == Path(package["root"]) / "scripts/greybox.py", "Pinned entry must be the package CLI")
    python = value.get("python", {})
    core.require(isinstance(python, dict) and set(python) == {"executable", "prefix", "version", "implementation"}
                 and all(isinstance(x, str) and x for x in python.values())
                 and Path(python["executable"]).is_absolute() and Path(python["prefix"]).is_absolute(),
                 "Task context needs actual Python identity")
    project = value.get("project", {})
    core.require(isinstance(project, dict) and set(project) == {"root", "engine"}
                 and project.get("engine") in {"godot", "unity", "blender"}
                 and isinstance(project.get("root"), str) and Path(project["root"]).is_absolute(),
                 "Task context needs a game or native spatial project root")
    session = value.get("session", {})
    core.require(isinstance(session, dict) and set(session) == SESSION_FIELDS | {"source_ref", "evidence"},
                 "Task context needs explicit or unknown session identity")
    normalized = _session({k: v for k, v in session.items() if k != "evidence"})
    core.require(all(normalized[k] == session[k] for k in SESSION_FIELDS | {"source_ref"}), "Invalid session identity")
    core.require(session["evidence"] in {"explicit_report", "unavailable"}, "Invalid session evidence type")
    return value


def capture(project, session_report=None, *, engine=None):
    path = Path(project).expanduser()
    resolved = (host_setup.spatial_root(project) if engine == "blender" or path.suffix.lower() == ".blend"
                else host_setup.project_root(project, engine))
    return {"schema": 1, "kind": "greybox-task-context", "package": _package(SKILL, verify=True),
            # Resolving a venv launcher symlink would select the base interpreter
            # and silently lose that environment on the next guarded invocation.
            "python": {"executable": str(Path(sys.executable).absolute()), "prefix": str(Path(sys.prefix).absolute()),
                       "version": platform.python_version(),
                       "implementation": platform.python_implementation()},
            "project": {"root": str(Path(resolved["path"]).resolve()), "engine": resolved["engine"]},
            "session": _session(session_report)}


def installed_entries(*, home=None, config_dir=None):
    """Bounded known locations only; do not run or recursively search another installation."""
    home = Path(home or Path.home())
    roots = [home / folder / "skills/greybox-to-multistyle-art"
             for folder in (".agents", ".codex", ".workbuddy", ".claude")]
    config = Path(config_dir) if config_dir else home / ".config/greybox-art"
    roots.extend(config / "host-packages" / name / "skills/greybox-to-multistyle-art" for name in host.HOSTS)
    result, seen = [], set()
    for root in roots:
        if not (root / "MANIFEST.json").is_file() or root.resolve() in seen:
            continue
        seen.add(root.resolve())
        try:
            result.append({**_package(root), "integrity": "not_checked", "invoked": False})
        except (OSError, ValueError, TypeError) as error:
            result.append({"root": str(root), "error": str(error), "invoked": False})
    return result


def ledger_route(path):
    """Classify observed ledger bytes, not a promising filename; do not mutate them."""
    path = Path(path).resolve()
    try:
        data = core.read(path)
        core.require(isinstance(data, dict), "Ledger must be an object")
        route, backend, next_action = "unknown", None, "Inspect this ledger's owning implementation before any action"
        if data.get("schema") == 1 and data.get("kind") == "greybox-art-run":
            route, next_action = "legacy_core", "Use the original run directory and legacy status/resume/recovery commands; never enqueue as supplier"
        elif data.get("schema") == 1 and data.get("kind") == "supplier-job-run":
            route, backend, next_action = "executor", "supplier", "Reference this existing run directory in the executor supplier source; retain original IDs and approvals"
        elif data.get("schema") in {"greybox.image-job/v1", "greybox.native-job/v1"}:
            backend = "image" if data["schema"] == "greybox.image-job/v1" else "native"
            route = "executor"
            next_action = ("Reference this existing job directory in the executor image source; reconcile unknown original attempts first"
                           if backend == "image" else "Use executor claim/record/settle for the original native attempt; native invocation remains agent driven")
        elif data.get("schema") == 1 and data.get("kind") == "greybox-execution-queue":
            route, next_action = "executor_queue", "Inspect/status this existing queue; original source ledgers retain execution authority"
        expected_name = ("supplier-run.json" if backend == "supplier" else "job.json" if backend else
                         "run.json" if route == "legacy_core" else None)
        if expected_name and path.name != expected_name:
            route, backend, next_action = "unsupported_location", None, (
                "Recognized schema outside its expected " + expected_name + " location; inspect the original owner instead of renaming or recreating it")
        return {"ledger": str(path), "route": route, "backend": backend, "source_dir": str(path.parent),
                "next_action": next_action, "migration_performed": False, "new_submission_authorized": False}
    except (OSError, ValueError, TypeError) as error:
        return {"ledger": str(path), "route": "unreadable", "error": str(error), "migration_performed": False}


def compare(pinned, current):
    validate_context(pinned)
    changed = []
    for group, fields in (("package", ("root", "entry", "version", "manifest_sha256", "actual_source_sha256")),
                          ("python", ("executable", "prefix", "version", "implementation")),
                          ("project", ("root", "engine")), ("session", tuple(sorted(SESSION_FIELDS)))):
        changed.extend(group + "." + key for key in fields if pinned[group].get(key) != current[group].get(key))
    if not current["package"]["integrity_ok"]:
        changed.append("package.integrity")
    scopes = []
    if any(field.startswith("package.") for field in changed):
        scopes.append("Verify selected package and its compatibility with each original run; existing runtime/input gates still apply")
    if any(field.startswith(("python.", "project.")) for field in changed):
        scopes.append("Recheck local dependencies and actual engine project; do not reset prior creative decisions")
    if any(field.startswith("session.") for field in changed):
        scopes.append("Refresh current-session host capabilities and affected native tool bindings; preserve approved artifacts and original attempts")
    unknown = sorted(key for key in SESSION_FIELDS if current["session"].get(key) is None)
    return {"ok": not changed, "status": "drift" if changed else "unchanged",
            "changed": changed, "revalidate": scopes, "unknown_session_fields": unknown,
            "session_identity_fully_observed": not unknown, "paid_work_authorized": False,
            "limits": "Explicit host reports are not authentication or invocation proof; unchanged unknown fields do not establish model/tool continuity"}


def inspect(project, case_dir=None, session_report=None, *, engine=None, home=None, config_dir=None):
    from . import continuity
    current = capture(project, session_report, engine=engine)
    entries = installed_entries(home=home, config_dir=config_dir)
    result = {"ok": current["package"]["integrity_ok"], "current": current, "installed_entries": entries,
              "competing_entries": [row for row in entries if row.get("root") != current["package"]["root"]],
              "provider_calls": 0}
    if case_dir is not None:
        root = Path(current["project"]["root"])
        case = continuity._path(case_dir, root)
        plan = core.read(case / "PLAN.json")
        continuity._validate(plan, root)
        continuity._verify_progress(case, plan)
        core.require(not (case / ".progress-transaction.json").exists(), "Recover interrupted PLAN update first")
        pinned = plan.get("execution_context")
        check = compare(pinned, current) if pinned else {"ok": False, "status": "unpinned", "paid_work_authorized": False}
        result.update({"ok": result["ok"] and check["ok"], "check": check,
                       "routes": [ledger_route(continuity._path(ref, root)) for ref in plan["references"].get("ledgers", [])],
                       "plan_revision": plan["revision"], "checkpoint_sha256": continuity._checkpoint(plan, root)[1]})
    return result


def pin(project, case_dir, session_report, *, writer, expected_revision, checkpoint_sha256, source_ref, engine=None):
    from . import continuity
    context = capture(project, session_report, engine=engine)
    validate_context(context)
    core.require(context["session"]["host"] and context["session"]["session_id"],
                 "Pin needs the current host and session ID; leave unavailable model/schema as null")
    result = continuity.update(Path(context["project"]["root"]), case_dir, writer, expected_revision,
        checkpoint_sha256, {"type": "change", "summary": "Pin actual skill execution context; approvals and task IDs remain in their owning ledgers",
        "source_ref": source_ref, "scope": "execution_context", "evidence": []}, {"execution_context": context})
    return {**result, "execution_context": context, "paid_work_authorized": False}


def run(project, case_dir, arguments, session_report=None, *, engine=None):
    """Explicit guarded entry; no shell, arbitrary executable, migration, or replacement job."""
    checked = inspect(project, case_dir, session_report, engine=engine)
    core.require(checked["ok"], "Task context is unpinned or changed; inspect, refresh affected capabilities and explicitly repin before dispatch")
    core.require(arguments and arguments[0] != "task-context", "Provide a greybox command other than task-context")
    context = checked["current"]
    arguments = list(arguments)
    # Do not silently change the engine root in the forwarded public command.
    for index, argument in enumerate(arguments):
        option = argument.split("=", 1)[0]
        core.require(not (option.startswith("--") and option != "--project" and "--project".startswith(option)),
                     "Use the full --project option inside the task guard; abbreviated project overrides are not allowed")
        value = argument.split("=", 1)[1] if argument.startswith("--project=") else (
            arguments[index + 1] if argument == "--project" and index + 1 < len(arguments) else None)
        if value is not None:
            core.require(str(Path(value).expanduser().resolve()) == context["project"]["root"],
                         "Forwarded --project differs from the pinned engine root")
            if argument.startswith("--project="):
                arguments[index] = "--project=" + context["project"]["root"]
            else:
                arguments[index + 1] = context["project"]["root"]
    completed = subprocess.run([context["python"]["executable"], context["package"]["entry"], *arguments],
                               cwd=context["project"]["root"], check=False)
    return completed.returncode
