#!/usr/bin/env python3
"""Resolve the current host's attribution without install profiles or bindings."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
import unicodedata


REGIONS = ("cn", "international")
SOURCE = 100
MAX_JSON_BYTES = 16384
# Match ECMAScript String.trim used by the connector contract resolver. The
# control characters in its whitespace set are rejected before trimming.
HOST_TRIM_CHARS = " \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"


class CliError(RuntimeError):
    """Errors carry only fixed messages, never supplied credentials or paths."""

    def __init__(self, code, message):
        self.code, self.message = code, message
        super().__init__(message)

    def to_dict(self):
        return {"code": self.code, "message": self.message, "retryable": False}


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, _message):
        raise CliError("CLI_ARGUMENT_INVALID", "Invalid command arguments.")


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _constant(_value):
    raise ValueError("non-finite JSON value")


def read_json(path):
    with Path(path).open("rb") as stream:
        data = stream.read(MAX_JSON_BYTES + 1)
    if len(data) > MAX_JSON_BYTES:
        raise ValueError("JSON too large")
    return json.loads(data.decode("utf-8-sig"), object_pairs_hook=_pairs,
                      parse_constant=_constant)


def load_registry():
    root = Path(__file__).resolve().parents[1]
    path = root / "host-identity.json"
    if not path.is_file():
        repository = source_repository(root)
        if repository:
            path = repository / "shared/host-identity/lux3d/host-identity.json"
    try:
        registry = read_json(path)
        hosts = registry["knownHosts"]
        if (set(registry) != {"schema", "knownHosts", "fallback"}
                or registry.get("schema") != "lux3d.host-identity/v1"
                or registry.get("fallback") != {"source": 100, "agentName": "detected-host-name"}
                or not isinstance(hosts, dict)
                or set(hosts) != {"codex", "claude-code", "deepseek", "workbuddy"}):
            raise ValueError("registry fields")
        aliases = set()
        for name, source in (("codex", 1), ("claude-code", 2), ("deepseek", 3), ("workbuddy", 4)):
            host = hosts[name]
            if (not isinstance(host, dict) or set(host) != {"source", "agentName", "aliases"}
                    or type(host.get("source")) is not int
                    or host["source"] != source or host.get("agentName") != name
                    or not isinstance(host.get("aliases"), list) or not host["aliases"]
                    or name not in host["aliases"]):
                raise ValueError("registry host")
            for alias in host["aliases"]:
                if (not isinstance(alias, str) or len(alias) > 128
                        or not re.fullmatch(r"[a-z0-9]+(?:[ _-][a-z0-9]+)*", alias)
                        or alias in aliases):
                    raise ValueError("registry alias")
                aliases.add(alias)
        return registry
    except (OSError, KeyError, TypeError, ValueError, UnicodeError, RecursionError):
        raise CliError("CLI_CONFIGURATION_INVALID", "The packaged host identity registry is missing or invalid; reinstall this package.") from None


def identity_from_name(name, registry):
    if (not isinstance(name, str)
            or any(unicodedata.category(c) in {"Cc", "Cs"} for c in name)
            or not 1 <= len(name.strip(HOST_TRIM_CHARS)) <= 128):
        raise CliError("CLI_HOST_IDENTITY_INVALID", "The host must provide its actual nonempty application name, at most 128 characters without controls or surrogates.")
    name = name.strip(HOST_TRIM_CHARS)
    for host in registry["knownHosts"].values():
        if name.lower() in host["aliases"]:
            return {"source": host["source"], "agentName": host["agentName"]}
    return {"source": SOURCE, "agentName": name}


def resolve_host_identity(environ=None, host_name=None):
    """Use native session markers and host-supplied metadata, never model names.

    host_name and LUX3D_HOST_NAME are supplied automatically by the invoking
    agent/integration using its current host context. All present evidence must
    agree; stale inherited markers cannot silently change attribution.
    """
    environment = os.environ if environ is None else environ
    registry = load_registry()
    candidates = []
    if host_name is not None:
        candidates.append(identity_from_name(host_name, registry))
    if "LUX3D_HOST_NAME" in environment:
        candidates.append(identity_from_name(environment["LUX3D_HOST_NAME"], registry))
    if str(environment.get("CODEX_THREAD_ID", "")).strip():
        candidates.append(identity_from_name("codex", registry))
    # Official reference: https://code.claude.com/docs/en/env-vars#claudecode
    # Claude Code supplies exactly "1" to its child processes.
    if environment.get("CLAUDECODE") == "1":
        candidates.append(identity_from_name("claude-code", registry))
    if not candidates:
        raise CliError("CLI_HOST_IDENTITY_REQUIRED", "The current host agent must automatically pass its application name from host metadata with --host-name or LUX3D_HOST_NAME; do not infer it from the selected model or ask the user to create a binding.")
    if any(identity != candidates[0] for identity in candidates[1:]):
        raise CliError("CLI_HOST_IDENTITY_CONFLICT", "Host metadata and native session markers disagree. The host integration must correct the child process metadata before retrying.")
    return candidates[0]


def select_region(explicit):
    if explicit not in REGIONS:
        raise CliError("CLI_REGION_REQUIRED", "Select cn or international explicitly for this operation.")
    return explicit


def source_repository(skill_root):
    """Only an unpackaged canonical source entry may use the shared checkout."""
    root = Path(skill_root).resolve()
    if (root / "adapter.json").exists() or (root / "build-info.json").exists():
        return None
    if root.parts[-3:] != ("ecosystems", "common", "skill"):
        return None
    repository = root.parents[2]
    if ((repository / "release-manifest.json").is_file()
            and (repository / "ecosystems/common/release-design.json").is_file()):
        return repository
    return None


def find_skill_root(script_path=None):
    root = Path(script_path or __file__).resolve().parents[1]
    if not (root / "SKILL.md").is_file():
        raise CliError("CLI_CONFIGURATION_INVALID", "The Common Skill entry could not be located.")
    return root


def load_adapter(skill_root):
    if source_repository(skill_root):
        return {"schema": "lux3d.ecosystem-adapter/v1", "ecosystem": "common",
                "distribution": "skill", "identityMode": "automatic-host"}
    try:
        adapter = read_json(Path(skill_root) / "adapter.json")
        if (not isinstance(adapter, dict)
                or adapter.get("schema") != "lux3d.ecosystem-adapter/v1"
                or adapter.get("ecosystem") != "common"
                or adapter.get("distribution") != "skill"
                or adapter.get("identityMode") != "automatic-host"
                or "source" in adapter or "profileId" in adapter
                or not isinstance(adapter.get("version"), str) or not adapter["version"]
                or not isinstance(adapter.get("status"), str) or not adapter["status"]):
            raise ValueError("adapter fields")
        return adapter
    except (OSError, TypeError, ValueError, UnicodeError, RecursionError):
        raise CliError("CLI_CONFIGURATION_INVALID", "The installed Common Skill adapter is invalid.") from None


def find_runtime(script_path=None, skill_root=None):
    root = Path(skill_root) if skill_root else find_skill_root(script_path)
    load_adapter(root)
    bundled = root / "core/runtime"
    repository = source_repository(root)
    runtime = repository / "shared/core/runtime" if repository else bundled
    required = ("commerce_client.py", "lux3d_client.py", "workflow_contracts.py", "requirements.txt")
    if all((runtime / name).is_file() for name in required):
        return runtime
    raise CliError("CLI_RUNTIME_UNAVAILABLE", "The bundled Lux3D runtime is incomplete; reinstall this package.")


def main(argv=None):
    parser = SafeArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("detect",))
    parser.add_argument("--host-name", metavar="NAME", help="Actual host application name automatically supplied by the host agent.")
    try:
        args = parser.parse_args(argv)
        identity = resolve_host_identity(host_name=args.host_name)
        print(json.dumps({"status": "detected", **identity}, ensure_ascii=True))
        return 0
    except CliError as exc:
        print(json.dumps({"error": exc.to_dict()}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
