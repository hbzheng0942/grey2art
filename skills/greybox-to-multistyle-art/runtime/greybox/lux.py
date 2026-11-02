"""Thin, credential-safe bridge to the pinned official Lux3D OpenAPI runtime.

These low-level calls do not grant spending authority. The caller owns persisted
quotes, authorization, pre-submit reservation and unknown-outcome reconciliation.
No call in this module submits REPORT/feedback or starts the upstream workflow.
"""
from __future__ import annotations

import getpass
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit
import zipfile

VENDOR_ROOT = Path(__file__).resolve().parents[1] / "vendor"
VENDOR = VENDOR_ROOT / "aholo-lux3d"
RUNTIME = VENDOR / "core/runtime"
SERVICE = "greybox-art-prototype.lux3d"
ENV_KEYS = {"cn": "LUX3D_CN_API_KEY", "international": "LUX3D_GLOBAL_API_KEY"}
BASES = {"cn": "https://api.aholo3d.cn", "international": "https://api.aholo.ai/global"}
OPERATIONS = {
    "image_to_3d": ("build_image_to_3d_payload", "/lux3d/v1/generate/img-to-3d/task/create"),
    "text_to_3d": ("build_text_to_3d_payload", "/lux3d/v1/generate/text-to-3d/task/create"),
    "remesh": ("build_mesh_retopology_payload", "/lux3d/v1/mesh-retopology/task/create"),
    "articulate": ("build_articulation_animation_payload", "/lux3d/v1/articulation-animation/task/create"),
    "rig": ("build_auto_rig_payload", "/lux3d/v1/animations/rig/task/create"),
    "retarget": ("build_animation_retarget_payload", "/lux3d/v1/animations/retarget/task/create"),
    "material_transfer": ("build_material_transfer_payload", "/lux3d/v1/generate/material-transfer/task/create"),
    "export": ("build_multi_format_export_payload", "/lux3d/v1/multi-format-export/task/create"),
}
ALIASES = {"image-to-3d": "image_to_3d", "text-to-3d": "text_to_3d", "mesh.remesh": "remesh",
           "mesh-retopology": "remesh", "articulation-animation": "articulate", "auto-rig": "rig",
           "rig.bind": "rig", "animation-retarget": "retarget", "motion.apply_preset": "retarget",
           "material-transfer": "material_transfer"}
DEPENDENCY_ERRORS = {
    "DEPENDENCY_CERTIFICATE_FAILED": "Package installation could not verify TLS certificates. Check the configured package index, proxy and trusted CA configuration; do not disable certificate verification.",
    "DEPENDENCY_NETWORK_FAILED": "Package installation could not reach its configured index. Check network, proxy and package-index access, then rerun explicit setup.",
    "DEPENDENCY_INDEX_UNAVAILABLE": "The configured package index did not provide the required packages. Check its access permissions and Python-version compatibility.",
    "DEPENDENCY_PERMISSION_DENIED": "Dependency setup cannot write to its selected private cache. Check the cache directory permissions and security software.",
    "DEPENDENCY_DISK_FULL": "Dependency setup ran out of storage. Free space in the selected private cache volume and rerun setup.",
    "DEPENDENCY_BOOTSTRAP_FAILED": "Python could not create a private environment with pip. Install a complete Python 3.10+ distribution with venv and ensurepip support.",
    "DEPENDENCY_INSTALL_FAILED": "Package installation failed. Check Python, the writable private cache and package-index configuration; raw installer output is omitted to protect credentials.",
    "DEPENDENCY_SETUP_REQUIRED": "Run setup with dependency installation to prepare the private Lux Python runtime.",
    "DEPENDENCY_SETUP_BUSY": "Another process is preparing the private Lux runtime; retry after it finishes.",
}


class LuxError(RuntimeError):
    def __init__(self, code, message, retryable=False, unknown_submission=False, *, category=None,
                 acceptance=None, retry_after=None, provider_code=None):
        self.code, self.message = code, message
        self.retryable, self.unknown_submission = retryable, unknown_submission
        self.category, self.acceptance = category, acceptance
        self.retry_after, self.provider_code = retry_after, provider_code
        super().__init__(message)

    def to_dict(self):
        return {"code": self.code, "message": self.message, "retryable": self.retryable,
                "unknownSubmission": self.unknown_submission,
                **{k: getattr(self, k) for k in ("category", "acceptance", "retry_after", "provider_code")
                   if getattr(self, k) is not None}}


def _error(code, message, **kwargs):
    raise LuxError(code, message, **kwargs) from None


def _region(value=None):
    value = value or os.environ.get("LUX3D_REGION") or _profile().get("region") or _private_config().get("region") or "cn"
    aliases = {"cn": "cn", "china": "cn", "domestic": "cn", "international": "international",
               "global": "international", "intl": "international"}
    if not isinstance(value, str) or value.lower().strip() not in aliases:
        _error("REGION_INVALID", "Select cn or international explicitly.")
    return aliases[value.lower().strip()]


def _profile_path():
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData/Roaming")
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "greybox-art-prototype/lux.json"


def _profile():
    path = _profile_path()
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or value.get("schema") != "greybox.lux-profile/v1" or value.get("region") not in ENV_KEYS or set(value) != {"schema", "region"}:
            raise ValueError()
        return value
    except (OSError, ValueError):
        _error("REGION_PROFILE_INVALID", "The non-secret Lux region profile is invalid; configure the region again locally.")


def _save_region(region):
    path = _profile_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, prefix=".lux-region-", delete=False, encoding="utf-8") as stream:
            temporary = Path(stream.name)
            json.dump({"schema": "greybox.lux-profile/v1", "region": region}, stream)
            stream.write("\n")
        os.replace(temporary, path)
    except OSError:
        _error("REGION_PROFILE_WRITE_FAILED", "The selected Lux region could not be stored in user configuration.")
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _private_config():
    configured = os.environ.get("GREYBOX_LUX3D_CREDENTIALS_FILE")
    candidates = [Path(configured).expanduser()] if configured else [
        Path.home() / ".config/lux3d/credentials.json",
        Path(os.environ.get("APPDATA", str(Path.home() / ".config"))) / "lux3d/credentials.json"]
    for path in candidates:
        if not path.is_file():
            continue
        try:
            if os.name != "nt" and stat.S_IMODE(path.stat().st_mode) & 0o077:
                _error("CREDENTIAL_CONFIG_PERMISSIONS", "Existing Lux credentials must be private (chmod 600).")
            if path.stat().st_size > 65536:
                raise ValueError()
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError()
            return value
        except LuxError:
            raise
        except (OSError, ValueError):
            _error("CREDENTIAL_CONFIG_INVALID", "The existing private Lux credential configuration is invalid.")
    return {}


def _keyring():
    try:
        keyring = importlib.import_module("keyring")
        backend = keyring.get_keyring()
        module = type(backend).__module__
        # Never accept plaintext/file backends or a chain that can fall back to one.
        if module not in {"keyring.backends.macOS", "keyring.backends.Windows", "keyring.backends.SecretService"}:
            _error("SECURE_KEYRING_UNAVAILABLE", "A supported system keyring is required; use regional environment credentials instead.")
        return keyring
    except LuxError:
        raise
    except Exception:
        _error("SECURE_KEYRING_UNAVAILABLE", "Install keyring in the private runtime or use regional environment credentials.")


def _credential(region, *, use_keyring=True):
    region = _region(region)
    dedicated = os.environ.get(ENV_KEYS[region], "").strip()
    if dedicated:
        return dedicated, "regional-environment"
    legacy = os.environ.get("LUX3D_API_KEY", "").strip()
    if legacy:
        bound = os.environ.get("LUX3D_API_KEY_REGION", "").strip()
        if not bound or _region(bound) != region:
            _error("CREDENTIAL_REGION_MISMATCH", "Legacy Lux API key must be explicitly bound to the selected region.")
        return legacy, "bound-legacy-environment"
    keys = _private_config().get("apiKeys", {})
    if isinstance(keys, dict) and isinstance(keys.get(region), str) and keys[region].strip():
        return keys[region].strip(), "existing-private-config"
    if use_keyring:
        try:
            key = _keyring().get_password(SERVICE, region)
            if key:
                return key, "system-keyring"
        except LuxError:
            pass
        except Exception:
            _error("SECURE_KEYRING_LOCKED", "The system keyring could not be read; unlock it locally or supply regional environment credentials.")
    return "", "missing"


def credential_provider(region):
    key, _ = _credential(region)
    if not key or key in {"your_lux3d_api_key", "your_api_key"}:
        _error("CREDENTIAL_REQUIRED", "Configure the regional Lux API key locally; do not paste it into chat.")
    return key


def _verify_vendor():
    try:
        manifest = json.loads((VENDOR_ROOT / "manifest.json").read_text(encoding="utf-8"))
        for record in manifest["files"]:
            path = (VENDOR_ROOT / record["path"]).resolve()
            if not path.is_relative_to(VENDOR.resolve()):
                raise ValueError()
            if hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
                raise ValueError()
        return manifest
    except (OSError, ValueError, KeyError, TypeError):
        _error("VENDOR_INTEGRITY_FAILED", "The pinned Lux runtime differs from its manifest; reinstall this skill package.")


def _module(name):
    _verify_vendor()
    sys.dont_write_bytecode = True
    if str(RUNTIME) not in sys.path:
        sys.path.insert(0, str(RUNTIME))
    try:
        module = importlib.import_module(name)
        if Path(module.__file__).resolve().parent != RUNTIME.resolve():
            _error("RUNTIME_CONFLICT", "Another Lux runtime was imported in this process; use a fresh skill process.")
        return module
    except ImportError:
        _error("DEPENDENCY_SETUP_REQUIRED", "Run setup with dependency installation to prepare the private Lux Python runtime.")


def _dependency_error(output, *, bootstrap=False):
    """Classify locally; never return installer text, URLs, paths or credentials."""
    text = output.decode("utf-8", errors="replace") if isinstance(output, bytes) else str(output or "")
    text = text.lower()
    rules = [
        ("DEPENDENCY_DISK_FULL", ("no space left", "disk full", "not enough space")),
        ("DEPENDENCY_PERMISSION_DENIED", ("permission denied", "access is denied", "operation not permitted", "read-only file system")),
        ("DEPENDENCY_CERTIFICATE_FAILED", ("certificate verify failed", "certificate_verify_failed", "sslcertverificationerror", "unable to get local issuer certificate")),
        ("DEPENDENCY_NETWORK_FAILED", ("connection refused", "connection reset", "network is unreachable", "name or service not known", "nodename nor servname", "temporary failure in name resolution", "read timed out", "connecttimeout", "proxyerror", "failed to establish a new connection")),
        ("DEPENDENCY_INDEX_UNAVAILABLE", ("no matching distribution found", "could not find a version", "401 client error", "403 client error", "404 client error")),
    ]
    code = next((code for code, markers in rules if any(marker in text for marker in markers)),
                "DEPENDENCY_BOOTSTRAP_FAILED" if bootstrap else "DEPENDENCY_INSTALL_FAILED")
    return LuxError(code, DEPENDENCY_ERRORS[code], retryable=code == "DEPENDENCY_NETWORK_FAILED")


def _install_environment_with_diagnostics(module, directory, requirements):
    """Same upstream installation command, with private in-memory diagnostics."""
    try:
        module.venv.EnvBuilder(with_pip=True).create(directory)
    except (OSError, subprocess.SubprocessError) as exc:
        raise _dependency_error(getattr(exc, "output", None) or str(exc), bootstrap=True) from None
    try:
        result = subprocess.run([
            str(module.python_path(directory)), "-I", "-m", "pip", "install",
            "--disable-pip-version-check", "--no-input", "-r", str(requirements),
        ], capture_output=True, text=True, timeout=900)
    except subprocess.TimeoutExpired:
        raise _dependency_error("read timed out") from None
    except OSError as exc:
        raise _dependency_error(str(exc)) from None
    if result.returncode:
        raise _dependency_error((result.stdout or "") + "\n" + (result.stderr or "")) from None


def _prepare_runtime_worker(install=False):
    _verify_vendor()
    specification = importlib.util.spec_from_file_location("_greybox_lux_setup", VENDOR / "scripts/setup_runtime.py")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    created = []
    if install:
        def install_with_diagnostics(directory, requirements):
            created.append(Path(directory))
            _install_environment_with_diagnostics(module, directory, requirements)
        # Scope the diagnostic hook to this dedicated setup process. The pinned
        # source remains byte-for-byte unchanged, including cache and lock rules.
        module.install_environment = install_with_diagnostics
    try:
        python = module.prepare(RUNTIME, module.default_cache(), check=not install)
        return {"ok": True, "python": str(python)}
    except Exception as exc:
        # Only a new UUID directory passed to this invocation's installer is
        # disposable. Never remove an existing ready environment or cache root.
        for directory in created:
            shutil.rmtree(directory, ignore_errors=True)
        if isinstance(exc, LuxError):
            raise
        if isinstance(exc, module.CliError):
            code = "DEPENDENCY_SETUP_BUSY" if exc.code == "CLI_DEPENDENCY_SETUP_BUSY" else "DEPENDENCY_SETUP_REQUIRED"
            raise LuxError(code, DEPENDENCY_ERRORS[code]) from None
        raise _dependency_error(str(exc), bootstrap=True) from None


def _runtime_python(*, install=False):
    _verify_vendor()
    if sys.version_info < (3, 10):
        _error("PYTHON_VERSION", "Lux requires Python 3.10 or newer.")
    command = [sys.executable, "-B", str(Path(__file__).resolve()), "--prepare-runtime", "install" if install else "check"]
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=960 if install else 60)
        result = json.loads(completed.stdout)
        if completed.returncode:
            code = result.get("error", {}).get("code")
            if code in DEPENDENCY_ERRORS:
                raise LuxError(code, DEPENDENCY_ERRORS[code], retryable=code == "DEPENDENCY_NETWORK_FAILED")
            raise ValueError()
        if not result or not Path(result.get("python", "")).is_file():
            raise ValueError()
        return result["python"]
    except (OSError, ValueError, subprocess.SubprocessError):
        _error("DEPENDENCY_SETUP_REQUIRED", "Run setup with dependency installation; check Python venv/pip, cache permissions and package-index access.")


def _call(name, arguments):
    if importlib.util.find_spec("requests") is None:
        python = _runtime_python()
        try:
            process = subprocess.run([python, "-B", str(Path(__file__).resolve()), "--worker"],
                                     input=json.dumps({"method": name, "arguments": arguments}),
                                     text=True, capture_output=True, timeout=600)
            result = json.loads(process.stdout)
            if not result.get("ok") and result.get("state") != "partial":
                error = result.get("error", {})
                raise LuxError(error.get("code", "BRIDGE_FAILED"), error.get("message", "Lux bridge failed."),
                               error.get("retryable", False), error.get("unknownSubmission", False),
                               **{k: error[k] for k in ("category", "acceptance", "retry_after", "provider_code") if k in error})
            return result
        except LuxError:
            raise
        except (OSError, ValueError, subprocess.SubprocessError):
            _error("BRIDGE_FAILED", "Private Lux runtime did not return a valid result; preserve the task record before retrying.",
                   unknown_submission=name == "submit")
    return _HANDLERS[name](**arguments)


def _base(region):
    upstream = _module("lux3d_client")
    try:
        base = upstream.get_base_url(region)
        if base not in {BASES[region], "https://api.aholo3d.com/global" if region == "international" else BASES[region]}:
            raise ValueError()
        return base
    except ValueError:
        _error("ENDPOINT_REGION_MISMATCH", "Lux endpoint override must match the selected public regional endpoint.")


def capabilities():
    manifest = _verify_vendor()
    contract = json.loads((VENDOR / "core/contracts/lux3d-generation.v1.json").read_text(encoding="utf-8"))
    return {"ok": True, "provider": "lux3d", "version": manifest["version"], "commit": manifest["commit"],
            "operations": list(OPERATIONS), "generationVersions": ["G1", "G1-Turbo"],
            "generationFaceCount": {"min": 10000, "max": 300000},
            "animationIds": contract["sharedFields"]["animationId"]["values"],
            "rigInput": "public HTTPS GLB; human binding", "retargetInput": "rigged public HTTPS GLB and 1–10 public action IDs",
            "automaticReport": False, "evidence": "pinned-runtime; network and Godot acceptance must be recorded per run"}


def doctor(region=None, online=False):
    selected = region or os.environ.get("LUX3D_REGION") or _profile().get("region") or _private_config().get("region")
    if online and not selected:
        _error("REGION_REQUIRED", "Choose cn or international with setup before checking the online account.")
    region = _region(selected)
    manifest = _verify_vendor()
    key, source = _credential(region, use_keyring=False)
    try:
        python = _runtime_python()
        runtime = "ready"
    except LuxError:
        python = None
        runtime = "setup-required"
    result = {"ok": True, "provider": "lux3d", "region": region, "version": manifest["version"],
              "commit": manifest["commit"], "runtime": runtime, "python": python,
              "credentials": {"configured": bool(key), "source": source, "keyring": "checked-on-explicit-use"},
              "selectedRegion": region if selected else None,
              "onlineChecked": False, "automaticReport": False}
    if online:
        result.update(_call("account", {"region": region}))
        result["onlineChecked"] = True
    return result


def setup(region, configure_key=False, install_dependencies=False):
    region = _region(region)
    python = _runtime_python(install=install_dependencies)
    if configure_key:
        try:
            check = subprocess.run([python, "-B", "-c", "import keyring"], capture_output=True, timeout=30)
            if check.returncode:
                if not install_dependencies:
                    _error("DEPENDENCY_SETUP_REQUIRED", "Use setup with dependency installation before configuring the system keyring.")
                subprocess.run([python, "-m", "pip", "install", "--disable-pip-version-check", "--no-input", "keyring>=25,<26"],
                               check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300)
            # Interactive subprocess receives the terminal directly; the key is never an argument or JSON field.
            configured = subprocess.run([python, "-B", str(Path(__file__).resolve()), "--configure-key", region], timeout=300)
            if configured.returncode:
                _error("SECURE_KEYRING_UNAVAILABLE", "The API key was not stored; configure the regional environment variable locally.")
        except LuxError:
            raise
        except (OSError, subprocess.SubprocessError):
            _error("SECURE_KEYRING_UNAVAILABLE", "System keyring setup did not complete; no plaintext fallback was used.")
    _save_region(region)
    return {"ok": True, "provider": "lux3d", "region": region, "python": python,
            "runtime": "ready", "keyConfigured": bool(configure_key), "onlineChecked": False}


def _validate(operation, parameters, region=None):
    operation = ALIASES.get(operation, operation)
    if operation not in OPERATIONS or not isinstance(parameters, dict):
        _error("PARAMETERS_INVALID", "Unsupported Lux operation or invalid parameter object.")
    if any(key in parameters for key in {"region", "base_url", "api_key", "credential_provider", "content_id", "quoteId", "source"}):
        _error("PARAMETERS_INVALID", "Credentials, routing and quote metadata must not appear in operation parameters.")
    try:
        json.dumps(parameters, allow_nan=False)
        payload = getattr(_module("lux3d_client"), OPERATIONS[operation][0])(**parameters, region=_region(region))
    except (TypeError, ValueError):
        _error("PARAMETERS_INVALID", "Parameters do not match the pinned Lux contract; inspect capabilities and the operation reference.")
    return {"ok": True, "provider": "lux3d", "operation": operation, "parameters": payload,
            "endpoint": {"method": "POST", "path": OPERATIONS[operation][1]}}


def validate(operation, parameters, region=None):
    return _call("validate", {"operation": operation, "parameters": parameters, "region": region})


def quote_items_for(operation, parameters, sequence="1"):
    checked = validate(operation, parameters)
    if not re.fullmatch(r"[1-9][0-9]{0,5}", str(sequence)):
        _error("PARAMETERS_INVALID", "Quote sequence must be a positive numeric string.")
    return {str(sequence): {"endpoint": checked["endpoint"],
                           "parameters": {"body": checked["parameters"], "pathParameters": {}, "queryParameters": {}}}}


def _commerce(region, items=None):
    region = _region(region)
    _base(region)
    credential_provider(region)  # Preserve a precise safe credential error before upstream masks it.
    module = _module("commerce_client")
    client = module.CommerceClient(source=1, credential_provider=credential_provider)
    try:
        normalized = None
        if items is not None:
            normalized = module.normalize_items(items)
            # Rebuild each billable body through the exact creation validator.
            for item in normalized.values():
                paths = {value[1]: key for key, value in OPERATIONS.items()}
                op = paths.get(item["endpoint"]["path"])
                if op is None:
                    _error("PARAMETERS_INVALID", "The quote contains an operation outside this bridge.")
                checked = _validate(op, item["parameters"].get("body", {}), region)
                item["parameters"]["body"] = checked["parameters"]
        account = client.get_account(region=region)
        result = {"ok": True, "provider": "lux3d", "region": region, "account": account}
        if normalized is not None:
            result["quote"] = client.create_quote(region=region, unique_id=account["uniqueId"], items=normalized)
            result["items"] = normalized
        return result
    except LuxError:
        raise
    except module.CommerceError as exc:
        raise LuxError(exc.code, exc.message, exc.retryable) from None
    except Exception:
        _error("PROVIDER_RESPONSE_INVALID", "Lux account or quotation did not return a valid response.")
    finally:
        client.close()


def quote(items, region):
    return _call("quote", {"items": items, "region": region})


def _submit(operation, parameters, region, quote_id=None):
    region = _region(region)
    checked = _validate(operation, parameters, region)
    if quote_id is not None and not re.fullmatch(r"quote_[0-9a-f]{32}", quote_id):
        _error("QUOTE_ID_INVALID", "Use the unmodified quote ID returned by Lux commerce.")
    base = _base(region)
    credential_provider(region)
    module = _module("lux3d_client")
    try:
        task_id = module.submit_task(checked["endpoint"]["path"], checked["parameters"], base_url=base,
                                     region=region, credential_provider=credential_provider,
                                     content_id=quote_id)
    except module.ApiBusinessRejection as exc:
        from .execution_errors import safe_code
        provider_code = safe_code(getattr(exc, "code", None), "SUBMISSION_REJECTED")
        capacity = provider_code == "GENERATION_CONCURRENCY_LIMIT_EXCEEDED"
        limited = provider_code in {"RATE_LIMITED", "RATE_LIMIT_EXCEEDED"}
        _error(provider_code if capacity or limited else "SUBMISSION_REJECTED",
               "Lux explicitly rejected the submission; inspect account limits and the approved plan.",
               retryable=capacity or limited, category="capacity" if capacity else ("rate_limit" if limited else "permanent"),
               acceptance="not_accepted", provider_code=provider_code)
    except Exception:
        _error("SUBMISSION_UNKNOWN", "Lux submission outcome is unknown. Reconcile task history; do not blindly resubmit.",
               unknown_submission=True)
    return {"ok": True, "provider": "lux3d", "region": region, "operation": checked["operation"],
            "taskId": task_id, "quoteId": quote_id, "state": "submitted"}


def submit(operation, parameters, region, quote_id=None):
    return _call("submit", {"operation": operation, "parameters": parameters, "region": region, "quote_id": quote_id})


def _task(task_id, region):
    region = _region(region)
    if not str(task_id).isdigit() or int(task_id) <= 0:
        _error("TASK_ID_INVALID", "Use the positive task ID returned by the original submission.")
    base = _base(region)
    credential_provider(region)
    try:
        return _module("lux3d_client").get_task(str(task_id), base_url=base, region=region, credential_provider=credential_provider)
    except Exception:
        _error("TASK_QUERY_FAILED", "Lux task query failed; preserve and resume the existing task ID.", retryable=True)


def _status(task_id, region):
    region = _region(region)
    task = _task(task_id, region)
    labels = {0: "queued", 1: "running", 2: "running", 3: "succeeded", 4: "failed", 5: "failed", 6: "cancelled"}
    return {"ok": True, "provider": "lux3d", "taskId": str(task_id), "region": region,
            "providerStatus": task["status"], "state": labels[task["status"]],
            "providerState": {0: "initialized", 1: "running", 2: "waiting_for_result", 3: "succeeded", 4: "failed", 5: "dispatch_failed", 6: "cancelled"}[task["status"]],
            "data": {"taskId": str(task_id), "status": task["status"]}}


def status(task_id, region):
    return _call("status", {"task_id": task_id, "region": region})


def _upload(path, region):
    region = _region(region)
    _base(region)
    credential_provider(region)
    try:
        result = _module("asset_uploader").upload_file(path, region=region, credential_provider=credential_provider)
    except Exception:
        _error("UPLOAD_FAILED", "Lux input upload failed; preserve the local file and retry the upload separately from generation.", retryable=True)
    return {"ok": True, "provider": "lux3d", "region": region, "data": result}


def upload(path, region):
    return _call("upload", {"path": str(path), "region": region})


def _artifact_urls(outputs):
    if isinstance(outputs, str):
        return [("artifact", outputs)]
    if isinstance(outputs, list):
        return [(str(index), value) for index, value in enumerate(outputs) if isinstance(value, str)]
    if isinstance(outputs, dict) and "actions" in outputs:
        records = []
        for index, action in enumerate(outputs["actions"]):
            if action.get("status") == "success":
                for field in ("animationGlbUrl", "fbxUrl"):
                    if action.get(field):
                        records.append((f"action:{action['animation_id']}", action[field]))
        return records
    if isinstance(outputs, dict):
        return [(str(name), value) for name, value in outputs.items() if isinstance(value, str) and value.startswith(("https://", "http://"))]
    return []


def _inspect_download(path, extension, operation=None):
    size = path.stat().st_size
    if size == 0:
        raise ValueError()
    if extension == ".glb":
        with path.open("rb") as stream:
            header = stream.read(20)
            if len(header) != 20 or header[:4] != b"glTF" or struct.unpack_from("<I", header, 4)[0] != 2 or struct.unpack_from("<I", header, 8)[0] != size or header[16:20] != b"JSON":
                raise ValueError()
            length = struct.unpack_from("<I", header, 12)[0]
            if length > min(size - 20, 64 * 1024 * 1024):
                raise ValueError()
            document = json.loads(stream.read(length))
            if not document.get("meshes"):
                raise ValueError()
            if operation in {"rig", "retarget"} and not any(skin.get("joints") for skin in document.get("skins", [])):
                raise ValueError()
            if operation == "retarget" and not document.get("animations"):
                raise ValueError()
    elif extension in {".zip", ".usdz", ".3mf"}:
        with zipfile.ZipFile(path) as archive:
            if not archive.namelist() or archive.testzip() is not None:
                raise ValueError()
    return size


def _fetch(task_id, region, output_dir, accepted_request=None):
    region = _region(region)
    task = _task(task_id, region)
    if task["status"] != 3:
        _error("TASK_NOT_SUCCEEDED", "Fetch requires a succeeded task. Resume its status instead of creating another task.")
    module = _module("lux3d_client")
    checked = None
    if accepted_request is not None:
        if not isinstance(accepted_request, dict):
            _error("PARAMETERS_INVALID", "Accepted request must contain the original operation and parameters.")
        checked = _validate(accepted_request.get("operation"), accepted_request.get("parameters"), region)
    try:
        operation = checked["operation"] if checked else None
        if operation == "remesh":
            outputs = module.parse_mesh_retopology_output(task)
        elif operation == "articulate":
            outputs = module.parse_articulation_animation_output(task)
        elif operation == "material_transfer":
            outputs = module.parse_fixed_output_slots(task, module.MATERIAL_OUTPUT_SLOTS)
        elif operation == "export":
            outputs = module.parse_fixed_output_slots(task, module.EXPORT_OUTPUT_SLOTS)
        else:
            outputs = module.parse_task_outputs(task)
        if operation == "retarget":
            parameters = checked["parameters"]
            actions = module.validate_animation_results(outputs, parameters["animationIds"],
                        outFormat=parameters["outFormat"], animationOutputMode=parameters["animationOutputMode"])
            outputs = {"actions": actions}
        elif isinstance(outputs, dict) and "actions" in outputs:
            # Without the accepted request, preserve semantics but never claim
            # request coverage. IDs still must belong to the public contract.
            identifiers = [action.get("animation_id") for action in outputs["actions"]]
            if len(identifiers) != len(set(identifiers)) or any(item not in module.ANIMATION_IDS for item in identifiers):
                raise ValueError()
        urls = _artifact_urls(outputs)
        if not urls:
            raise ValueError()
    except Exception:
        _error("OUTPUT_INVALID", "The succeeded Lux task has no usable artifacts; preserve its task ID.")
    target = Path(output_dir).expanduser().resolve()
    if target.is_relative_to(Path(__file__).resolve().parents[2]):
        _error("OUTPUT_INSIDE_INSTALL", "Write downloads to the project or an external cache, not the skill installation.")
    target.mkdir(parents=True, exist_ok=True)
    downloads, failures = [], []
    for label, url in urls:
        temporary = None
        try:
            parsed = urlsplit(module.validate_http_url(url, "artifact"))
            extension = Path(parsed.path).suffix.lower()
            if not re.fullmatch(r"\.[a-z0-9]{1,10}", extension):
                extension = ".bin"
            with tempfile.NamedTemporaryFile(dir=target, prefix=".lux-download-", delete=False) as stream:
                temporary = Path(stream.name)
            module.download_model(url, str(temporary))
            size = _inspect_download(temporary, extension, operation)
            digest = hashlib.sha256(temporary.read_bytes()).hexdigest()
            destination = target / (digest + extension)
            if destination.exists():
                if hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
                    raise ValueError()
            else:
                os.replace(temporary, destination)
            record = {"slot": label, "path": str(destination), "sha256": digest, "bytes": size,
                      "format": extension[1:], "validation": "container-only; Godot and art validation pending"}
            if label.startswith("action:"):
                record["animationId"] = label.removeprefix("action:")
            downloads.append(record)
        except Exception:
            failures.append({"slot": label, "code": "DOWNLOAD_OR_CONTAINER_INVALID"})
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
    failed_actions = sum(action.get("status") != "success" for action in outputs.get("actions", [])) if isinstance(outputs, dict) else 0
    return {"ok": not failures and not failed_actions, "provider": "lux3d", "region": region,
            "taskId": str(task_id), "state": "downloaded" if not failures and not failed_actions else "partial",
            "downloads": downloads, "failures": failures, "failedActions": failed_actions,
            "requestBound": checked is not None,
            "actions": [{"animationId": action["animation_id"], "status": action["status"]} for action in outputs.get("actions", [])] if isinstance(outputs, dict) else [],
            "error": {"code": "FETCH_PARTIAL", "message": "Some artifacts could not be downloaded or actions failed; successful files are preserved.", "retryable": True} if failures or failed_actions else None}


def fetch(task_id, region, output_dir, accepted_request=None):
    return _call("fetch", {"task_id": task_id, "region": region, "output_dir": str(output_dir), "accepted_request": accepted_request})


_HANDLERS = {"validate": _validate, "account": _commerce, "quote": _commerce, "submit": _submit,
             "status": _status, "fetch": _fetch, "upload": _upload}


def _main():
    try:
        if len(sys.argv) == 3 and sys.argv[1] == "--prepare-runtime" and sys.argv[2] in {"install", "check"}:
            print(json.dumps(_prepare_runtime_worker(install=sys.argv[2] == "install")))
            return 0
        if len(sys.argv) == 3 and sys.argv[1] == "--configure-key":
            region = _region(sys.argv[2])
            if not sys.stdin.isatty():
                _error("SECURE_INPUT_REQUIRES_TERMINAL", "Configure the API key from a local interactive terminal; piped input is not accepted.")
            ring = _keyring()
            key = getpass.getpass("Lux3D API key (local secure input): ").strip()
            if not key:
                _error("CREDENTIAL_REQUIRED", "An empty key was not stored.")
            ring.set_password(SERVICE, region, key)
            return 0
        if sys.argv[1:] != ["--worker"]:
            _error("BRIDGE_ARGUMENT_INVALID", "Use the skill CLI to invoke this bridge.")
        request = json.load(sys.stdin)
        method = request["method"]
        if method not in _HANDLERS:
            raise ValueError()
        result = _HANDLERS[method](**request["arguments"])
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except LuxError as exc:
        print(json.dumps({"ok": False, "error": exc.to_dict()}))
        return 1
    except Exception:
        print(json.dumps({"ok": False, "error": {"code": "BRIDGE_FAILED", "message": "Lux bridge failed; diagnostic bodies are omitted to protect credentials."}}))
        return 1


if __name__ == "__main__":
    raise SystemExit(_main())
