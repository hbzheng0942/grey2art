#!/usr/bin/env python3
"""Prepare an isolated, verified Python environment for the portable Skill."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import sysconfig
import time
import uuid
import venv


_identity_path = Path(__file__).with_name("host_identity.py")
_source_root = Path(__file__).resolve().parents[1]
if (not _identity_path.is_file() and _source_root.parts[-3:] == ("ecosystems", "common", "skill")
        and not (_source_root / "adapter.json").exists() and not (_source_root / "build-info.json").exists()
        and (_source_root.parents[2] / "release-manifest.json").is_file()):
    _identity_path = _source_root.parents[2] / "shared/host-identity/lux3d/scripts/host_identity.py"
_spec = importlib.util.spec_from_file_location("_lux3d_common_setup_identity", _identity_path)
identity_support = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(identity_support)
CliError = identity_support.CliError


def python_path(directory):
    return directory / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def interpreter_identity():
    return {
        "implementation": sys.implementation.name,
        "version": list(sys.version_info),
        "cacheTag": sys.implementation.cache_tag,
        "abi": sysconfig.get_config_var("SOABI"),
        "platform": sys.platform,
        "os": platform.system(),
        "architecture": platform.machine(),
        "pointerBits": 64 if sys.maxsize > 2 ** 32 else 32,
    }


def cache_identity(runtime, *, identity=None):
    digest = hashlib.sha256()
    files = sorted(path for path in runtime.rglob("*")
                   if path.is_file() and "__pycache__" not in path.parts
                   and (path.suffix == ".py" or path.name == "requirements.txt"))
    if not (runtime / "requirements.txt").is_file():
        raise CliError("CLI_RUNTIME_UNAVAILABLE", "The bundled runtime requirements are missing.")
    for path in files:
        relative = path.relative_to(runtime).as_posix().encode("utf-8")
        content = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big") + relative)
        digest.update(len(content).to_bytes(8, "big") + content)
    metadata = {
        "schema": "lux3d.common-runtime-cache/v1",
        "interpreter": interpreter_identity() if identity is None else identity,
        "requirementsDigest": hashlib.sha256((runtime / "requirements.txt").read_bytes()).hexdigest(),
        "runtimeDigest": digest.hexdigest(),
    }
    encoded = json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest(), metadata


def ready(python, runtime):
    if not python.is_file():
        return False
    # -I prevents ambient PYTHONPATH/site injection; -B keeps read-only installs
    # untouched. Every bundled module must import from the selected runtime.
    modules = sorted(path.stem for path in runtime.glob("*.py"))
    program = (
        "import importlib,sys; "
        f"sys.path.insert(0, {str(runtime)!r}); "
        "import requests; requests.Session().close(); "
        f"[importlib.import_module(name) for name in {modules!r}]"
    )
    try:
        return subprocess.run([str(python), "-I", "-B", "-c", program],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              timeout=60).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


@contextmanager
def cache_lock(path, *, timeout=60):
    """OS advisory locks release on process exit; lock files need not be deleted."""
    with path.open("a+b") as stream:
        if stream.seek(0, os.SEEK_END) == 0:
            stream.write(b"\0")
            stream.flush()
        acquired = False
        deadline = time.monotonic() + timeout
        try:
            while not acquired:
                try:
                    stream.seek(0)
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                except OSError:
                    if time.monotonic() >= deadline:
                        raise CliError("CLI_DEPENDENCY_SETUP_BUSY", "Another process is preparing this runtime; retry after it finishes.") from None
                    time.sleep(0.05)
            yield
        finally:
            if acquired:
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def install_environment(directory, requirements):
    venv.EnvBuilder(with_pip=True).create(directory)
    subprocess.run([
        str(python_path(directory)), "-I", "-m", "pip", "install",
        "--disable-pip-version-check", "--no-input", "-r", str(requirements),
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=900)


def read_ready(cache, key, runtime):
    pointer = cache / f"{key}.ready.json"
    try:
        record = identity_support.read_json(pointer)
        if not isinstance(record, dict) or record.get("cacheKey") != key:
            return None
        environment = record.get("environment")
        if not isinstance(environment, str) or not environment.startswith(key + "-"):
            return None
        if Path(environment).name != environment or "/" in environment or "\\" in environment:
            return None
        directory = cache / "environments" / environment
        if directory.resolve().parent != (cache / "environments").resolve():
            return None
        python = python_path(directory)
        return python if ready(python, runtime) else None
    except (OSError, TypeError, ValueError, UnicodeError, RecursionError):
        return None


def prepare(runtime, cache, *, check=False):
    runtime, cache = Path(runtime).resolve(), Path(cache).expanduser().resolve()
    key, metadata = cache_identity(runtime)
    existing = read_ready(cache, key, runtime)
    if existing:
        return existing
    if check:
        raise CliError("CLI_DEPENDENCY_SETUP_REQUIRED", "Run setup_runtime.py without --check to prepare this interpreter's dependencies.")
    cache.mkdir(parents=True, exist_ok=True)
    with cache_lock(cache / f"{key}.lock"):
        existing = read_ready(cache, key, runtime)
        if existing:
            return existing
        directory = cache / "environments" / f"{key}-{uuid.uuid4().hex}"
        directory.mkdir(parents=True, exist_ok=False)
        # A venv retains its final absolute path throughout installation. Failed
        # installations have no ready pointer and are never selected or reused.
        install_environment(directory, runtime / "requirements.txt")
        python = python_path(directory)
        if not ready(python, runtime):
            raise CliError("CLI_DEPENDENCY_SETUP_REQUIRED", "Installed dependencies failed runtime import validation; rerun setup.")
        record = {**metadata, "cacheKey": key, "environment": directory.name}
        temporary = cache / f".{key}.{uuid.uuid4().hex}.json"
        try:
            with temporary.open("x", encoding="utf-8") as stream:
                json.dump(record, stream, sort_keys=True)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, cache / f"{key}.ready.json")
        finally:
            if temporary.exists():
                temporary.unlink()
        return python


def default_cache():
    configured = os.environ.get("LUX3D_COMMON_ENV_DIR")
    if configured:
        return Path(configured).expanduser()
    base = Path(os.environ.get("XDG_CACHE_HOME") or (Path.home() / ".cache"))
    return base / "aholo-lux3d-common"


def main(argv=None):
    parser = identity_support.SafeArgumentParser(description=__doc__)
    parser.add_argument("--env-dir", type=Path, help="Writable cache root (not an existing virtual environment).")
    parser.add_argument("--check", action="store_true", help="Read-only readiness check; never create a cache or install dependencies.")
    try:
        args = parser.parse_args(argv)
        runtime = identity_support.find_runtime(__file__)
        python = prepare(runtime, args.env_dir or default_cache(), check=args.check)
    except CliError as exc:
        print(json.dumps({"error": exc.to_dict()}), file=sys.stderr)
        return 1
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
        error = {"code": "CLI_DEPENDENCY_SETUP_REQUIRED", "message": "Runtime preparation failed. Check the writable cache, Python venv/pip support and configured package-index connectivity, then rerun setup.", "retryable": False}
        print(json.dumps({"error": error}), file=sys.stderr)
        return 1
    print(json.dumps({"status": "ready", "python": str(python)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
