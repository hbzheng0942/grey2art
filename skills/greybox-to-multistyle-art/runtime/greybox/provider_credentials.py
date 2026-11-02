"""Explicit local provider credentials; never infer regions or inspect other apps.

Environment values take precedence. The optional POSIX file is private plaintext,
not a keychain; its provider, region and environment-name binding must all match.
"""
from __future__ import annotations

from contextlib import ExitStack
import json
import os
from pathlib import Path
import stat
import tempfile

from .core import require
from .execution_process import LockBusyError, exclusive


def store_path():
    if os.environ.get("GREYBOX_CONFIG_HOME"):
        base = Path(os.environ["GREYBOX_CONFIG_HOME"]).expanduser().absolute()
    elif os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local"))) / "greybox-art"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "greybox-art"
    return base / "credentials" / "providers.json"


def _private(path, directory=False):
    require(os.name == "posix", "Private credential files require POSIX permissions; use provider environment variables on this host")
    info = path.lstat()
    require(not stat.S_ISLNK(info.st_mode) and (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)),
            "Credential storage must be an ordinary private directory/file, never a symlink")
    require(info.st_uid == os.getuid() and stat.S_IMODE(info.st_mode) == (0o700 if directory else 0o600),
            "Credential storage must be owned by this user with directory mode 0700 and file mode 0600")
    require(directory or info.st_nlink == 1, "Credential storage cannot be hard-linked")


def _secret(value):
    require(isinstance(value, str) and 0 < len(value.strip()) <= 8192 and not any(ord(c) < 32 or ord(c) == 127 for c in value),
            "Provider credential is empty or contains invalid characters")
    return value.strip()


def _read(path):
    if not path.parent.exists() and not path.parent.is_symlink():
        return {"schema": 1, "credentials": {}}
    _private(path.parent, directory=True)
    if not path.exists() and not path.is_symlink():
        return {"schema": 1, "credentials": {}}
    _private(path)
    require(path.stat().st_size <= 128 * 1024, "Credential storage exceeds its supported size")
    try:
        with path.open(encoding="utf-8") as stream:
            value = json.load(stream)
        require(isinstance(value, dict) and set(value) == {"schema", "credentials"} and value["schema"] == 1
                and isinstance(value["credentials"], dict), "Credential storage has an unsupported schema")
        from .account_profiles import ENDPOINTS
        for provider, regions in value["credentials"].items():
            require(provider in ENDPOINTS and isinstance(regions, dict), "Credential storage has an invalid provider")
            for region, entries in regions.items():
                require(region in ENDPOINTS[provider] and isinstance(entries, dict), "Credential storage has an invalid region")
                for name, secret in entries.items():
                    _binding(provider, region, name)
                    _secret(secret)
        return value
    except (UnicodeError, json.JSONDecodeError):
        raise ValueError("Credential storage is malformed; repair the private file before continuing") from None


def _binding(provider, region, name):
    from .account_profiles import ENDPOINTS
    import re
    require(provider in ENDPOINTS and region in ENDPOINTS[provider], "Unsupported provider/account region")
    require(isinstance(name, str) and re.fullmatch(provider.upper() + r"_[A-Z0-9_]{1,90}", name),
            "Credential environment name must have the exact provider prefix")


def load(provider, region, name):
    _binding(provider, region, name)
    # An explicitly set invalid/empty value must not silently switch accounts.
    if name in os.environ:
        return _secret(os.environ[name])
    values = _read(store_path())["credentials"].get(provider, {}).get(region, {})
    return _secret(values[name]) if name in values else ""


def save(provider, region, values):
    require(isinstance(values, dict) and values, "Supply at least one provider credential")
    for name, secret in values.items():
        _binding(provider, region, name)
        _secret(secret)
    require(os.name == "posix", "Private credential files require POSIX permissions; use provider environment variables on this host")
    path = store_path()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    _private(path.parent, directory=True)
    lock = path.parent / ".providers.lock"
    with ExitStack() as stack:
        try:
            stack.enter_context(exclusive(lock))
        except LockBusyError:
            raise ValueError("Credential setup is already locked; finish the other setup before retrying") from None
        return _save_locked(path, provider, region, values)


def _save_locked(path, provider, region, values):
    temporary = None
    try:
        data = _read(path)
        data["credentials"].setdefault(provider, {}).setdefault(region, {}).update({name: _secret(value) for name, value in values.items()})
        descriptor, temporary = tempfile.mkstemp(prefix=".providers-", dir=path.parent)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(data, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
        _private(path)
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)
    return path


def configure(argv=None):
    import argparse
    import getpass
    import sys
    import warnings
    from .account_profiles import ENDPOINTS, LEGACY
    parser = argparse.ArgumentParser(description="Save private provider credentials locally; no API calls")
    parser.add_argument("--provider", choices=sorted(ENDPOINTS), required=True)
    parser.add_argument("--region", choices=["cn", "international", "public"], required=True)
    parser.add_argument("--credential-env", action="append", help="Exact profile environment name; repeat twice for Hi3D ID and secret")
    args = parser.parse_args(argv)
    try:
        require(sys.stdin.isatty(), "Run credential setup in your own interactive terminal; piped/chat credentials are not accepted")
        names = args.credential_env or LEGACY[args.provider][1]
        require(len(names) == (2 if args.provider == "hitem3d" else 1) and len(set(names)) == len(names), "Wrong number of credential environment names")
        for name in names:
            _binding(args.provider, args.region, name)
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            values = {name: getpass.getpass(name + " (hidden): ") for name in names}
        path = save(args.provider, args.region, values)
        print(json.dumps({"ok": True, "provider": args.provider, "region": args.region,
                          "credential_envs": names, "path": str(path), "connection_verified": False}))
        return 0
    except ValueError as error:
        print("Credential setup failed: " + str(error), file=sys.stderr)
        return 1
    except (OSError, EOFError, getpass.GetPassWarning):
        print("Credential setup failed. Use an interactive terminal and private user-owned storage; no credential value was printed.", file=sys.stderr)
        return 1
