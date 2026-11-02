"""Small, non-secret host bindings. Configuration is not tool/session proof."""
from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
import plistlib
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

from . import core

HOSTS = ("workbuddy", "claude-code", "codex")
PROGRAMS = ("python", "godot", "unity", "blender", "workbuddy", "claude-code", "codex")
SKILL = Path(__file__).resolve().parents[2]


def config_root(config_dir=None):
    if config_dir:
        return Path(config_dir).expanduser().absolute()
    if os.environ.get("GREYBOX_CONFIG_HOME"):
        return Path(os.environ["GREYBOX_CONFIG_HOME"]).expanduser().absolute()
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local"))) / "greybox-art"
    return Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "greybox-art"


@contextlib.contextmanager
def _locked(root):
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = root / ".host.lock"
    try:
        fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise ValueError("Another host configuration owns the lock; inspect its process before retrying") from None
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(str(os.getpid()))
        yield
    finally:
        lock.unlink()


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix="." + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            json.dump(data, out, indent=2, ensure_ascii=False)
            out.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _load(host, config_dir=None):
    if host not in HOSTS:
        raise ValueError("Supported host names: " + ", ".join(HOSTS))
    path = config_root(config_dir) / "hosts" / (host + ".json")
    if not path.exists():
        return {}, path
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema") != 1 or data.get("kind") != "greybox-host-profile" or data.get("host") != host:
        raise ValueError("Unsupported host configuration; preserve and migrate the existing file")
    return data, path


def _candidates(name, platform, home, environ):
    """Known app locations supplement PATH; never launch an application here."""
    if platform == "darwin":
        applications = (Path("/Applications"), home / "Applications")
        apps = {"godot": ["Godot.app"], "blender": ["Blender.app"],
                "workbuddy": ["WorkBuddy.app"], "codex": ["Codex.app"],
                "claude-code": ["Claude Code.app"], "unity": ["Unity/Hub/Editor/*/Unity.app"]}
        for root in applications:
            for pattern in apps.get(name, []):
                for bundle in sorted(root.glob(pattern), reverse=True):
                    yield from _bundle_executables(bundle, name)
        if name == "godot":
            # Godot's official macOS download is a directly runnable .app bundle.
            yield from _bundle_executables(home / "Downloads/Godot.app", name)
    elif platform == "win32":
        roots = [Path(environ.get("ProgramFiles", "C:/Program Files")),
                 Path(environ.get("LOCALAPPDATA", str(home / "AppData/Local")))]
        apps = {"unity": ["Unity/Hub/Editor/*/Editor/Unity.exe"],
                "blender": ["Blender Foundation/Blender */blender.exe"],
                "godot": ["Godot/Godot*.exe"],
                "workbuddy": ["Programs/WorkBuddy/WorkBuddy.exe", "WorkBuddy/WorkBuddy.exe"],
                "codex": ["Programs/Codex/Codex.exe"]}
        for root in roots:
            for pattern in apps.get(name, []):
                yield from sorted(root.glob(pattern), reverse=True)
    if name == "claude-code":
        yield home / ".local/bin" / ("claude.exe" if platform == "win32" else "claude")
    if name == "codex":
        yield home / ".local/bin" / ("codex.exe" if platform == "win32" else "codex")


def _bundle_executables(bundle, fallback):
    metadata = bundle / "Contents/Info.plist"
    try:
        with metadata.open("rb") as handle:
            executable = plistlib.load(handle).get("CFBundleExecutable")
        if isinstance(executable, str) and executable and Path(executable).name == executable:
            yield bundle / "Contents/MacOS" / executable
    except (OSError, ValueError, plistlib.InvalidFileException):
        pass
    yield bundle / "Contents/MacOS" / {"godot": "Godot", "blender": "Blender", "unity": "Unity", "codex": "Codex", "workbuddy": "WorkBuddy"}.get(fallback, fallback)


def _resolve(name, explicit, platform, home, environ):
    if explicit:
        path = Path(explicit).expanduser().absolute()
        # Explicit bindings must never silently select a different executable.
        return {"path": str(path), "source": "configured", "available": path.is_file()}
    aliases = {"python": ["python3", "python"], "godot": ["godot", "godot4"],
               "claude-code": ["claude"], "unity": ["Unity", "unity"]}
    found = []
    if name == "python" and platform == sys.platform:
        found.append((Path(sys.executable).absolute(), "current-interpreter"))
    for alias in aliases.get(name, [name]):
        match = shutil.which(alias, path=environ.get("PATH", ""))
        if match:
            found.append((Path(match).absolute(), "PATH"))
    found.extend((path, "application-directory") for path in _candidates(name, platform, home, environ))
    available = [(path, source) for path, source in found if path.is_file()]
    if not available:
        return {"path": None, "source": None, "available": False}
    path, source = available[0]
    return {"path": str(path), "source": source, "available": True,
            "alternatives": list(dict.fromkeys(str(p) for p, _ in available[1:] if p != path))}


def discover(host="workbuddy", executables=None, config_dir=None, platform=None, home=None, environ=None):
    profile, path = _load(host, config_dir)
    bindings = dict(profile.get("executables", {}))
    bindings.update(executables or {})
    unknown = set(bindings) - set(PROGRAMS)
    if unknown:
        raise ValueError("Unknown executable binding: " + ", ".join(sorted(unknown)))
    platform, home, environ = platform or sys.platform, Path(home or Path.home()), environ or os.environ
    programs = {name: _resolve(name, bindings.get(name), platform, home, environ) for name in PROGRAMS}
    remediation = []
    if not programs["python"]["available"]:
        remediation.append({"capability": "process_execute", "action": "Provide a Python 3.10+ executable with host configure --python PATH"})
    if not profile.get("image_profile"):
        remediation.append({"capability": "image_generate", "action": "Bind an actually invoked native image tool in the current session report, or configure and bind an image profile if the host has no suitable tool"})
    for operation in ("image_inspect", "image_present", "human_input"):
        remediation.append({"capability": operation, "action": "Bind the current host tool and actual invocation evidence in the session capability report"})
    return {"ok": programs["python"]["available"], "kind": "host-discovery", "host": host,
            "platform": platform, "profile_path": str(path), "configured": bool(profile),
            "programs": programs, "image_profile": profile.get("image_profile"),
            "execution": "cli", "delegation": "serial-unless-session-tool-verified",
            "session_verified": False, "remediation": remediation}


def configure(host="workbuddy", executables=None, image_profile=None, config_dir=None,
              image_config_dir=None, connector_dir=None, skill_root=None):
    root = config_root(config_dir)
    with _locked(root):
        old, path = _load(host, config_dir)
        report = discover(host, executables, config_dir)
        # Only installed applications are persisted; explicit missing paths are rejected.
        for name in (executables or {}):
            if not report["programs"][name]["available"]:
                raise ValueError("Configured executable does not exist: " + name)
        data = {**old, "schema": 1, "kind": "greybox-host-profile", "host": host,
                "executables": {name: row["path"] for name, row in report["programs"].items() if row["available"]},
                "execution": "cli", "updated_at": core.now()}
        if image_profile is not None:
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}", image_profile):
                raise ValueError("image_profile must be a non-secret profile name")
            data["image_profile"] = image_profile
        if image_config_dir is not None:
            data["image_config_dir"] = str(Path(image_config_dir).expanduser().absolute())
        connector = None
        if connector_dir is not None:
            if host != "workbuddy":
                raise ValueError("--connector-dir is only used by WorkBuddy")
            connector = render_workbuddy_connector(connector_dir, skill_root or SKILL, root)
            data["connector_dir"] = connector["path"]
        _write(path, data)
    return {"ok": True, "kind": "host-configuration", "host": host, "profile_path": str(path),
            "image_profile": data.get("image_profile"), "executables": data["executables"],
            "connector": connector, "next": "Run host verify; session pixel/display tools still need actual invocation evidence"}


def verify(host="workbuddy", config_dir=None, capability_report=None, session_id=None, scope="art", engine=None, operation=None):
    core.require(scope in {"art", "greybox", "runtime", "spatial"}, "Choose art, greybox, spatial or runtime host verification scope")
    core.require(engine in {None, "godot", "unity", "blender"}, "Unknown native engine")
    core.require(operation in {None, "create", "edit", "review"}, "Unknown spatial operation")
    core.require(scope == "spatial" or operation is None, "Operation applies only to spatial verification")
    core.require(scope == "spatial" or engine != "blender", "Blender is an authoring carrier; use spatial verification scope")
    core.require(scope != "spatial" or engine == "blender", "Spatial verification needs the selected Blender authoring carrier")
    core.require(scope != "greybox" or engine, "Greybox verification needs the selected --engine")
    data, _ = _load(host, config_dir)
    report = discover(host, config_dir=config_dir)
    row = report["programs"]["python"]
    checks = {}
    if row["available"]:
        try:
            probe = subprocess.run([row["path"], "-c", "import json,sys; print(json.dumps({'version':list(sys.version_info[:3])}))"],
                                   capture_output=True, text=True, timeout=15, check=False)
            version = json.loads(probe.stdout)["version"] if probe.returncode == 0 else []
            checks["python"] = {"ok": tuple(version) >= (3, 10), "version": version, "path": row["path"]}
        except (OSError, ValueError, subprocess.TimeoutExpired, KeyError):
            checks["python"] = {"ok": False, "path": row["path"], "error": "Python probe failed; refresh this executable binding"}
    else:
        checks["python"] = {"ok": False, "error": "Configured Python is missing; rerun host configure --python PATH"}
    # An explicitly configured missing engine must remain visible after restarts.
    configured = {key: value for key, value in data.get("executables", {}).items()
                  if key in ({"python"} if scope == "runtime" else {"python", engine})}
    checks["configured_paths"] = {"ok": all(Path(value).is_file() for value in configured.values()),
                                  "missing": [key for key, value in configured.items() if not Path(value).is_file()]}
    if scope in {"greybox", "spatial"}:
        checks["engine"] = {"ok": report["programs"][engine]["available"], "path": report["programs"][engine]["path"],
                            "scope": "discovered executable only; the actual scoped native operation remains unverified"}
        if not checks["engine"]["ok"]:
            report["remediation"].append({"capability": engine, "action": "Configure the selected engine using host configure --" + engine + " PATH"})
    session = {"ok": False, "status": "unverified", "reason": "No current session capability report supplied"}
    if capability_report is not None:
        from .overview import check_host_capabilities
        from .overview import BASE_HOST_OPERATIONS
        operations = ["file_read", "file_write", "process_execute"] if scope == "runtime" else [*BASE_HOST_OPERATIONS, *(["image_generate"] if scope == "art" else [])]
        if scope == "spatial" and operation == "review":
            operations = [name for name in operations if name != "file_write"]
        session = check_host_capabilities(capability_report, required_operations=operations,
                                          expected_host=host, expected_session=session_id)
    native_image = session.get("bindings", {}).get("image_generate", {})
    if (scope == "art" and session_id and native_image.get("kind") in {"host_tool", "mcp"}
            and native_image.get("verification") == "invocation_verified"):
        checks["image_route"] = {"ok": True, "status": "native_invocation_verified",
                                 "binding": native_image, "session_id": session_id,
                                 "report_digest": session["report_digest"], "generation_invoked": False}
        report["remediation"] = [item for item in report["remediation"] if item.get("capability") != "image_generate"]
    else:
        checks["image_route"] = _image_route(data) if scope == "art" else {"ok": True, "status": "not_required_for_" + scope}
    ready = bool(data) and all(item.get("ok") for item in checks.values())
    invocation_ready = session.get("ok", False) and all(row.get("verification") == "invocation_verified"
                                                       for row in session.get("bindings", {}).values())
    relevant = {"python", "process_execute"} if scope == "runtime" else {"python", "process_execute", engine, "image_inspect", "image_present", "human_input"}
    refreshed = ["python", "configured_paths"] + (["image_route"] if scope == "art" else ([engine] if engine and scope in {"greybox", "spatial"} else []))
    return {"ok": ready, "kind": "host-verification", "host": host, "scope": scope, "configuration_verified": ready,
            "checks": checks, "session": session, "host_session_ready": ready and invocation_ready,
            "production_ready": False, "readiness_scope": "Host bindings only; workflow approvals and native engine production are checked separately",
            "refreshed_capabilities": refreshed,
            "remediation": report["remediation"] if scope == "art" else [item for item in report["remediation"] if item.get("capability") in relevant]}


def _image_route(data):
    if not data.get("image_profile"):
        return {"ok": False, "status": "missing", "action": "image configure, then host configure --image-profile NAME"}
    from . import image_jobs
    try:
        capabilities = image_jobs.profile_report(data["image_profile"], config_dir=data.get("image_config_dir"))
        return {"ok": capabilities.get("ok", False) and capabilities.get("credentials", {}).get("configured", False), "profile": data["image_profile"],
                "capabilities": capabilities, "generation_invoked": False}
    except (ValueError, OSError, core.WorkflowError) as error:
        # Provider errors may contain private transport details; never echo them here.
        return {"ok": False, "profile": data["image_profile"], "status": "unavailable",
                "action": "Check image capabilities --profile NAME and repair that image configuration"}


def render_workbuddy_connector(destination, skill_root, config_dir=None):
    destination, skill_root = Path(destination).expanduser().absolute(), Path(skill_root).expanduser().absolute()
    if destination.exists():
        raise ValueError("Choose a new connector directory; preserve the previous connector until the replacement is tested")
    template = SKILL / "connectors/workbuddy"
    if not (skill_root / "scripts/greybox.py").is_file():
        raise ValueError("Connector must reference an installed skill with scripts/greybox.py")
    cli = json.loads((template / "cli.template.json").read_text(encoding="utf-8"))
    script = str(skill_root / "connectors/workbuddy/bootstrap.py")
    for platform in ("darwin", "linux", "win32"):
        quote = subprocess.list2cmdline if platform == "win32" else shlex.join
        cli["init"][platform] = quote(["python", script, "--skill-root", str(skill_root), "--config-dir", str(config_root(config_dir))])
        # Connector installation is usable before provider credentials are supplied.
        # Service readiness remains an explicit host verify/image capabilities step.
        cli["status"][platform] = quote(["python", str(skill_root / "scripts/greybox.py"), "host", "discover", "--host", "workbuddy", "--config-dir", str(config_root(config_dir))])
    destination.mkdir(parents=True, mode=0o700)
    for name in ("connector-meta.json", "icon.svg"):
        shutil.copy2(template / name, destination / name)
    _write(destination / "cli.json", cli)
    skilldir = destination / "skills/greybox-host-bridge"
    skilldir.mkdir(parents=True)
    text = (template / "skills/greybox-host-bridge/SKILL.md").read_text(encoding="utf-8")
    (skilldir / "SKILL.md").write_text(text.replace("{{SKILL_ROOT}}", str(skill_root)), encoding="utf-8")
    return {"path": str(destination), "skill_root": str(skill_root), "runtime": {"type": "python", "version": "3.11"},
            "registration": "Import/register this local connector through WorkBuddy; automatic registration and marketplace publication were not performed"}
