"""Independent persisted image jobs, usable before H1 and outside H3 mesh jobs.

The host supplies the existing task's actual authorization reference. Reserving a
job is not approval. Every network submission has one durable local identity;
resume only queries or downloads and never repeats generation.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager, ExitStack
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import uuid
from urllib import error, request

from . import VERSION, image_adapters as adapters, provider_http
from .execution_process import LockBusyError, exclusive, replace_file

SKILL = Path(__file__).resolve().parents[2]
ImageError = adapters.ImageError
require = adapters.require


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def config_directory(config_dir=None):
    if config_dir:
        return Path(config_dir).expanduser().resolve()
    base = Path(os.environ.get("APPDATA") or Path.home() / "AppData/Roaming") if os.name == "nt" else Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "greybox-to-multistyle-art/images"


def _external(path):
    path = Path(path).expanduser().resolve()
    require(not path.is_relative_to(SKILL), "Image configuration and jobs must be outside the installed skill")
    return path


def _read(path):
    try:
        require(Path(path).stat().st_size <= adapters.MAX_JSON_BYTES, "Image document exceeds the supported limit")
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        require(isinstance(doc, dict), "Image document must be an object")
        return doc
    except ImageError:
        raise
    except (OSError, ValueError):
        raise ImageError("Image document is missing or invalid") from None


def _write(path, value):
    path = _external(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, prefix=".image-", delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        replace_file(temporary, path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def _id(value):
    require(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,100}", value), "Image profile identifier is invalid")
    return value


def _profile_path(name, config_dir=None):
    return _external(config_directory(config_dir)) / (_id(name) + ".json")


def _validate_profile(profile):
    require(isinstance(profile, dict), "Image profile must be an object")
    profile = dict(profile)
    allowed = {"schema", "kind", "base_url", "model", "credential_env", "timeout", "region", "capabilities", "adapter", "auth"}
    require(not set(profile) - allowed, "Image profile contains unknown fields; store only environment credential references")
    require(profile.get("kind") in {"lux", "openai", "custom"}, "Image profile kind must be lux, openai or custom")
    require(type(profile.get("timeout", 300)) in {int, float} and 1 <= profile.get("timeout", 300) <= 900, "Image timeout must be 1–900 seconds")
    require(profile.get("auth", "bearer") in {"raw", "bearer"}, "Image authentication must be raw or bearer")
    if profile["kind"] == "lux":
        from . import lux
        profile["region"] = lux._region(profile.get("region"))
        require(not set(profile) & {"base_url", "model", "credential_env", "auth", "adapter", "capabilities"}, "Lux images reuse the regional Lux endpoint and secure credential configuration")
    else:
        if profile["kind"] == "openai" or "base_url" in profile:
            profile["base_url"] = adapters.validate_base(profile.get("base_url"))
        if profile["kind"] == "openai":
            require(isinstance(profile.get("model"), str) and profile["model"].strip(), "Images API profile needs its actual model")
        env = profile.get("credential_env")
        require(isinstance(env, str) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", env), "Image credential must reference a local environment variable")
        require("key" not in profile and "api_key" not in profile, "Do not store image credentials in a profile")
    if "capabilities" in profile:
        cap = profile["capabilities"]
        require(isinstance(cap, dict) and set(cap) <= {"generate", "edit", "max_references", "mask", "size", "transparent_background", "parameters"}, "Image capability declaration is invalid")
        require(all(type(cap[k]) is bool for k in ("generate", "edit", "mask", "size", "transparent_background") if k in cap), "Image capabilities need boolean operation declarations")
        require(type(cap.get("max_references", 16)) is int and 0 <= cap.get("max_references", 16) <= 32, "Image reference limit must be 0–32")
        require(isinstance(cap.get("parameters", []), list) and all(isinstance(p, str) for p in cap.get("parameters", [])), "Image parameter capabilities must be a string list")
        if profile["kind"] == "openai":
            require(set(cap.get("parameters", [])) <= set(adapters.OPENAI_CAPABILITIES["parameters"]), "Extra Images API dialect parameters require a custom adapter; model/prompt/image inputs cannot be overridden")
    if profile["kind"] == "custom":
        require("capabilities" in profile and "adapter" in profile, "Custom profile needs explicit capabilities and a registered adapter")
        adapters.validate_custom(profile)
    profile["schema"] = "greybox.image-profile/v1"
    return profile


def configure(name, profile, config_dir=None):
    value = _validate_profile(profile)
    _write(_profile_path(name, config_dir), value)
    return profile_report(name, config_dir)


def load_profile(name, config_dir=None):
    return _validate_profile(_read(_profile_path(name, config_dir)))


def profile_report(name, config_dir=None):
    profile = load_profile(name, config_dir)
    if profile["kind"] == "lux":
        from . import lux
        key, source = lux._credential(profile["region"], use_keyring=False)
        configured = bool(key)
        if not configured:
            source = "missing-or-system-keyring-checked-on-explicit-use"
    else:
        configured = bool(os.environ.get(profile["credential_env"], "").strip())
        source = "environment-reference"
    return {"ok": True, "profile": name, "kind": profile["kind"], "profile_sha256": adapters.fingerprint(profile),
            "capabilities": adapters.capabilities(profile), "credentials": {"configured": configured, "source": source},
            "offline_only": True, "operation_verified": False}


@contextmanager
def _lock(folder):
    """Advisory OS lock is released on process death, including detached workers."""
    path = Path(folder) / ".image.lock"
    require(not path.is_symlink(), "Image job lock cannot be a symbolic link")
    with ExitStack() as stack:
        try:
            stack.enter_context(exclusive(path))
        except LockBusyError:
            raise ImageError("Another image operation owns this job",
                             code="IMAGE_JOB_BUSY", category="local") from None
        yield


def _record_input(value, base):
    require(isinstance(value, dict) and set(value) <= {"path", "sha256"} and isinstance(value.get("path"), str), "Image references need local path and exact sha256")
    path = Path(value["path"]).expanduser()
    require(not value["path"].startswith(("http:", "https:", "data:")), "Image inputs must be local hash-bound files")
    path = (path if path.is_absolute() else Path(base) / path).resolve()
    info = adapters.image_info(path)
    require(info["sha256"] == value.get("sha256"), "Image input is missing or changed")
    return dict(info, path=str(path))


def _bind_request(profile, document, base):
    checked = adapters.validate_request(profile, document)
    checked["images"] = [_record_input(row, base) for row in checked["images"]]
    require(len({row["sha256"] for row in checked["images"]}) == len(checked["images"]), "Reference images must have distinct bytes")
    if checked.get("mask"):
        checked["mask"] = _record_input(checked["mask"], base)
        require(checked["mask"]["format"] == "png", "Image edit mask must be a PNG")
        require((checked["mask"]["width"], checked["mask"]["height"]) == (checked["images"][0]["width"], checked["images"][0]["height"]), "Image edit mask dimensions differ from the first reference")
    return checked


def validate(name, document, *, config_dir=None, base=None):
    """Offline operation/input check; never uploads, installs or submits."""
    profile = load_profile(name, config_dir)
    checked = _bind_request(profile, document, base or Path.cwd())
    return {"ok": True, "profile": name, "operation": checked["operation"],
            "profile_sha256": adapters.fingerprint(profile), "request_sha256": adapters.fingerprint(checked),
            "input_image_sha256": [row["sha256"] for row in checked["images"]],
            "network": False, "submission": False,
            "validation": "declared operation, parameters and actual input pixels; custom outbound HTTP dialect needs its adapter fixture"}


def _job(folder):
    folder = _external(folder)
    data = _read(folder / "job.json")
    require(data.get("schema") == "greybox.image-job/v1", "Unsupported image job schema")
    require(adapters.fingerprint(data["profile"]) == data["profile_sha256"], "Saved image profile binding changed")
    require(adapters.fingerprint(data["request"]) == data["request_sha256"], "Saved image request binding changed")
    return folder, data


def _save(folder, data):
    data["updated_at"] = now()
    _write(folder / "job.json", data)


def _summary(folder, data):
    usage = data.get("usage")
    usage = {key: value for key, value in usage.items() if isinstance(key, str) and re.fullmatch(r"[a-zA-Z0-9_]{1,80}", key) and type(value) in {int, float}} if isinstance(usage, dict) else None
    actual = data.get("actual_cost")
    actual = {"amount": actual["amount"], "currency": actual["currency"]} if isinstance(actual, dict) and type(actual.get("amount")) in {int, float} and isinstance(actual.get("currency"), str) and re.fullmatch(r"[A-Za-z0-9_-]{1,40}", actual["currency"]) else None
    task_id = data.get("provider_task_id")
    if task_id and ("?" in task_id or task_id.startswith(("http://", "https://"))):
        task_id = "private-id-sha256:" + hashlib.sha256(task_id.encode()).hexdigest()[:16]
    return {"ok": data["state"] not in {"failed", "rejected", "unknown", "cancelled"}, "job_id": data["job_id"],
            "job_dir": str(folder), "state": data["state"], "provider": data["profile"]["kind"],
            "provider_task_id": task_id, "request_sha256": data["request_sha256"],
            "outputs": data.get("outputs", []), "error": data.get("error"),
            "authorization_source_ref": data["authorization"]["source_ref"],
            "cost": {"usage": usage, "budget": data["authorization"].get("budget"), "actual": actual}}


def submit(name, document, job_dir, *, authorization, config_dir=None, base=None, background=True, asset_dir=None, reserve_only=False):
    profile = load_profile(name, config_dir)
    request_doc = _bind_request(profile, document, base or Path.cwd())
    require(isinstance(authorization, dict) and isinstance(authorization.get("source_ref"), str) and authorization["source_ref"].strip(), "Bind the existing task's actual image-spend authorization source_ref before submitting")
    require(not authorization.get("request_sha256") or authorization["request_sha256"] == adapters.fingerprint(request_doc), "Image authorization binds a different request")
    # Check local credentials before creating a submission reservation.
    if profile["kind"] == "lux":
        from . import lux
        lux.credential_provider(profile["region"])
    else:
        require(bool(os.environ.get(profile["credential_env"], "").strip()), "Configure the image credential environment locally before submitting")
    folder = _external(job_dir)
    require(not folder.exists(), "Image job already exists; use status/resume/fetch, never submit it again")
    folder.mkdir(parents=True, mode=0o700)
    canonical = _external(asset_dir) if asset_dir else folder.parent / "image-assets"
    data = {"schema": "greybox.image-job/v1", "job_id": uuid.uuid4().hex, "state": "reserved", "created_at": now(),
            "profile_name": name, "profile": profile, "profile_sha256": adapters.fingerprint(profile),
            "request": request_doc, "request_sha256": adapters.fingerprint(request_doc),
            "authorization": authorization, "asset_dir": str(canonical), "outputs": []}
    data["runtime_binding"] = {"version": VERSION, "image_jobs_sha256": provider_http.file_hash(__file__),
                               "image_adapters_sha256": provider_http.file_hash(adapters.__file__)}
    if profile["kind"] == "lux":
        from . import lux
        manifest = lux._verify_vendor()
        data["runtime_binding"]["lux_vendor"] = {key: manifest.get(key) for key in ("version", "commit")}
    _save(folder, data)
    if reserve_only:
        return _summary(folder, data)
    if not background:
        return execute(folder)
    command = [sys.executable, "-B", str(SKILL / "scripts/image.py"), "_worker", "--job-dir", str(folder)]
    kwargs = {"stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL, "close_fds": True}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    else:
        kwargs["start_new_session"] = True
    try:
        process = subprocess.Popen(command, **kwargs)
    except OSError:
        data["state"], data["error"] = "reserved", {"code": "IMAGE_WORKER_START_FAILED", "message": "Worker did not start; use image start on this reserved job"}
        _save(folder, data)
        return _summary(folder, data)
    # Reap children while an embedding host process remains alive. A short-lived
    # CLI can exit immediately; the detached child keeps its durable job state.
    threading.Thread(target=process.wait, daemon=True).start()
    result = _summary(folder, data)
    result["worker_pid"] = process.pid
    return result


def reserve(name, document, job_dir, *, authorization, config_dir=None, base=None, asset_dir=None):
    """Bind one authorized image request without starting any generation call."""
    return submit(name, document, job_dir, authorization=authorization,
                  config_dir=config_dir, base=base, asset_dir=asset_dir, reserve_only=True)


def _response_fields(response, response_saved=False):
    state = response.get("state")
    require(state in {"submitted", "running", "succeeded", "failed", "cancelled"},
            "Image adapter returned an invalid state")
    identity = response.get("provider_task_id")
    if state in {"submitted", "running"}:
        require(identity is not None, "Async image response needs its original task ID")
    if state == "succeeded":
        items = response.get("items")
        staged_count = response.get("items_count")
        require((isinstance(items, list) and bool(items)) or
                (response_saved and type(staged_count) is int and staged_count > 0),
                "Succeeded image response has no outputs")
    task_id = str(identity) if identity is not None else None
    if task_id is not None:
        require(0 < len(task_id) <= 2048 and task_id.strip() == task_id
                and not any(ord(c) < 32 or ord(c) == 127 for c in task_id), "Image provider task ID is invalid")
    return state, task_id


def _accept_response(folder, data, response, *, response_saved=False, expected_task_id=None):
    require(isinstance(response, dict), "Image adapter response must be an object")
    known = data.get("provider_task_id")
    incoming = response.get("provider_task_id")
    require(known is None or incoming is None or str(incoming) == str(known),
            "Image response belongs to a different original task")
    if expected_task_id is not None:
        require(incoming is not None and str(incoming) == str(expected_task_id),
                "Image poll must identify its original task")
        _response_fields(response, response_saved)
    # Save the full original response first, including recovery URLs; stdout only
    # receives a sanitized summary and canonical output records.
    if not response_saved:
        _write(folder / "provider-response.json", response)
    state, task_id = _response_fields(response, response_saved)
    data["state"] = state
    if task_id is not None:
        data["provider_task_id"] = task_id
    if "usage" in response:
        data["usage"] = response["usage"]
    if "actual_cost" in response:
        data["actual_cost"] = response["actual_cost"]
    data.pop("error", None)
    _save(folder, data)


def execute(job_dir):
    folder, data = _job(job_dir)
    with _lock(folder):
        folder, data = _job(folder)
        require(not data.get("execution_lease"), "Image job belongs to the shared executor; recover its action before manual execution")
        require(data["state"] == "reserved", "Generation was already reserved/invoked; use resume to reconcile its original task")
        # Recheck input bytes and extension source immediately before invocation.
        for row in data["request"]["images"] + ([data["request"]["mask"]] if data["request"].get("mask") else []):
            require(provider_http.file_hash(row["path"]) == row["sha256"], "Image inputs changed before invocation; create a separately authorized revised job")
        profile = _validate_profile(data["profile"])
        data["state"], data["worker_pid"], data["invocation_started_at"] = "submitting", os.getpid(), now()
        _save(folder, data)
        submission_returned = False
        try:
            response = adapters.submit(profile, data["request"])
            submission_returned = True
            _accept_response(folder, data, response)
        except Exception as exc:
            unknown = submission_returned or not isinstance(exc, ImageError) or exc.unknown_submission
            data["state"] = "unknown" if unknown else "rejected"
            data["error"] = {"code": getattr(exc, "code", "IMAGE_ADAPTER_FAILED"),
                             "message": "Submission outcome is unknown; reconcile the original invocation" if unknown else "Image submission was rejected; inspect configuration and original task"}
            _save(folder, data)
            return _summary(folder, data)
    if data["state"] == "succeeded":
        return fetch(folder)
    return _summary(folder, data)


def status(job_dir, *, remote=True):
    folder, data = _job(job_dir)
    if remote and data["state"] in {"submitted", "running"}:
        with _lock(folder):
            folder, data = _job(folder)
            require(not data.get("execution_lease"), "Image job belongs to the shared executor; recover its action before manual polling")
            if data["state"] in {"submitted", "running"}:
                response = adapters.status(_validate_profile(data["profile"]), data["provider_task_id"])
                _accept_response(folder, data, response, expected_task_id=data["provider_task_id"])
    return _summary(folder, data)


def _download_item(item, temporary):
    require(isinstance(item, dict), "Image artifact entry is invalid")
    sources = [key for key in ("b64_json", "url", "path") if item.get(key)]
    require(len(sources) == 1, "Image artifact needs exactly one base64, URL or local path source")
    key = sources[0]
    if key == "b64_json":
        encoded = item[key]
        require(isinstance(encoded, str) and len(encoded) <= adapters.MAX_IMAGE_BYTES * 4 // 3 + 8, "Base64 image exceeds 64 MiB")
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError):
            raise ImageError("Image service returned invalid base64") from None
        temporary.write_bytes(raw)
    elif key == "path":
        require(isinstance(item[key], str) and Path(item[key]).is_absolute(), "Custom image output path must be absolute")
        source = Path(item[key]).resolve()
        require(source.is_file() and source.stat().st_size <= adapters.MAX_IMAGE_BYTES, "Custom image output is missing or exceeds 64 MiB")
        with source.open("rb") as incoming, temporary.open("wb") as outgoing:
            shutil.copyfileobj(incoming, outgoing, 1024 * 1024)
    else:
        # Share URL/redirect validation, with a raster-sized streaming limit.
        # API credentials never accompany an artifact request.
        try:
            provider_http.public_url(item[key])
            opener = request.build_opener(request.ProxyHandler({}), provider_http._PublicRedirect())
            with opener.open(request.Request(item[key], headers={"User-Agent": "greybox-art/0.4-images"}), timeout=60) as response:
                provider_http.public_url(response.geturl())
                total = 0
                with temporary.open("xb") as outgoing:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        total += len(chunk)
                        require(total <= adapters.MAX_IMAGE_BYTES, "Downloaded image exceeds 64 MiB")
                        outgoing.write(chunk)
        except ImageError:
            raise
        except Exception:
            raise ImageError("Image artifact download failed; resume the existing fetch") from None
    return adapters.image_info(temporary)


def _fetch_outputs(folder, data):
    """Fetch a leased snapshot without holding the job lock or saving job.json.

    Canonical bytes and receipts are installed atomically. The caller commits
    the returned snapshot under its own checked lease after all I/O finishes.
    """
    require(data["state"] == "succeeded", "Fetch needs an existing succeeded invocation; query or reconcile the original task")
    response = _read(folder / "provider-response.json")
    items = response.get("items", [])
    require(isinstance(items, list) and items, "Succeeded image task has no saved artifact sources")
    canonical = _external(data["asset_dir"])
    canonical.mkdir(parents=True, exist_ok=True, mode=0o700)
    scratch_prefix = ".image-fetch-" + hashlib.sha256((str(folder) + ":" + data["job_id"]).encode()).hexdigest()[:20] + "-"
    # A terminated action cannot run its finally block. A later exclusively
    # leased fetch may remove only this exact job's abandoned partial bytes.
    for abandoned in canonical.glob(scratch_prefix + "*"):
        if abandoned.is_dir() and not abandoned.is_symlink():
            shutil.rmtree(abandoned)
    outputs = []
    previous_outputs = data.get("outputs", [])
    try:
        for index, item in enumerate(items):
            if index < len(previous_outputs):
                record = previous_outputs[index]
                require(Path(record["path"]).is_file() and provider_http.file_hash(record["path"]) == record["sha256"],
                        "Previously fetched canonical image changed; restore its original bytes")
                receipt = record.get("receipt", {})
                require(Path(receipt.get("path", "")).is_file() and provider_http.file_hash(receipt["path"]) == receipt.get("sha256"),
                        "Previously fetched image receipt changed; preserve its original evidence")
                outputs.append(record)
                continue
            scratch_dir = Path(tempfile.mkdtemp(prefix=scratch_prefix, dir=canonical))
            try:
                # API downloader requires a target that does not exist.
                temporary = scratch_dir / "download.image"
                info = _download_item(item, temporary)
                destination = canonical / (info["sha256"] + "." + info["format"])
                require(not destination.is_symlink(), "Canonical image cannot be a symbolic link")
                if destination.exists():
                    require(provider_http.file_hash(destination) == info["sha256"], "Canonical image hash collision or changed bytes")
                else:
                    # These outputs become immutable canonical assets. os.link
                    # only atomically installs our disposable temporary bytes;
                    # no writable project source is hard-linked.
                    try:
                        os.link(temporary, destination)
                    except FileExistsError:
                        require(provider_http.file_hash(destination) == info["sha256"], "Concurrent canonical image collision")
                receipt = {"schema": 1, "kind": "reference-image-generation-receipt",
                           "tool": "greybox.image/" + data.get("runtime_binding", {}).get("version", VERSION) + ":" + data["profile"]["kind"],
                           "actual_input_image_sha256": [row["sha256"] for row in data["request"]["images"]],
                           "output_sha256": info["sha256"], "invocation_recorded": True,
                           "actual_tool_arguments": data["request"],
                           "source_ref": str(folder / "job.json") + "#" + data["job_id"],
                           "profile_sha256": data["profile_sha256"], "request_sha256": data["request_sha256"],
                           "provider_task_id": data.get("provider_task_id"),
                           "runtime_binding": data.get("runtime_binding"),
                           "invocation_started_at": data.get("invocation_started_at")}
                receipt_path = folder / ("receipt-" + str(index) + ".json")
                _write(receipt_path, receipt)
                outputs.append(dict(info, path=str(destination), receipt={"path": str(receipt_path), "sha256": provider_http.file_hash(receipt_path)}))
            finally:
                shutil.rmtree(scratch_dir)
        data["outputs"], data["state"] = outputs, "downloaded"
        # Base64 responses are temporary transport containers, not a second
        # permanent copy of every image. Preserve the response fingerprint
        # and metadata, then point its artifacts at the canonical bytes.
        data["provider_response_sha256"] = provider_http.file_hash(folder / "provider-response.json")
        response["items"] = [{"path": row["path"], "sha256": row["sha256"]} for row in outputs]
        response["transport_payload_replaced_by_verified_canonical_images"] = True
        _write(folder / "provider-response.json", response)
        data.pop("error", None)
    except Exception:
        data["outputs"] = outputs
        data["error"] = {"code": "IMAGE_FETCH_INCOMPLETE", "message": "Image download or pixel validation failed; resume fetch without generating again"}
        raise
    return data


def fetch(job_dir):
    folder, data = _job(job_dir)
    with _lock(folder):
        folder, data = _job(folder)
        require(not data.get("execution_lease"), "Image job belongs to the shared executor; recover its action before manual fetch")
        if data["state"] == "downloaded":
            for record in data["outputs"]:
                require(provider_http.file_hash(record["path"]) == record["sha256"], "Canonical image output changed; preserve evidence and restore the original bytes")
            return _summary(folder, data)
        try:
            _fetch_outputs(folder, data)
        finally:
            _save(folder, data)
    return _summary(folder, data)


def resume(job_dir, *, task_id=None, response_file=None, source_ref=None):
    """Reconcile known remote identity or import the original saved response.

    Never calls a generation endpoint, even after a killed synchronous worker.
    """
    folder, data = _job(job_dir)
    if task_id is not None or response_file is not None:
        require(bool(task_id) != bool(response_file), "Reconcile with a task ID or saved response, not both")
        require(isinstance(source_ref, str) and source_ref.strip(), "Reconciliation needs the actual original-task evidence source_ref")
        with _lock(folder):
            folder, data = _job(folder)
            require(not data.get("execution_lease"), "Image job belongs to the shared executor; reconcile its action before changing task identity")
            require(data["state"] in {"unknown", "submitting", "submitted", "running"}, "Only unresolved original invocations need reconciliation")
            if task_id:
                require(data["profile"]["kind"] in {"lux", "custom"}, "Synchronous Images API needs its original response, not an invented task endpoint")
                require(not data.get("provider_task_id") or data["provider_task_id"] == task_id, "Reconciliation cannot replace an already known original task")
                data["provider_task_id"], data["state"] = str(task_id), "submitted"
                data["reconciliation"] = {"source_ref": source_ref, "task_id": str(task_id), "at": now()}
                _save(folder, data)
            else:
                response = _read(response_file)
                if "data" in response:
                    response = {"state": "succeeded", "items": response["data"], "usage": response.get("usage")}
                require(response.get("state") == "succeeded" and response.get("items"), "Original response does not contain succeeded image artifacts")
                data["reconciliation"] = {"source_ref": source_ref, "response_sha256": provider_http.file_hash(response_file), "at": now()}
                _accept_response(folder, data, response)
    result = status(folder)
    if result["state"] == "succeeded":
        return fetch(folder)
    if result["state"] in {"submitting", "unknown"}:
        result["reconciliation_required"] = True
        result["note"] = "Preserve the original invocation; supply its known task ID or original response. Resume never resubmits."
    return result


def record_native(output, job_dir, *, tool, source_ref, actual_arguments, images=None, base=None):
    """Record a host's actual image call under the same provenance contract."""
    require(isinstance(tool, str) and tool.strip() and isinstance(source_ref, str) and source_ref.strip(), "Native image record needs the actual tool and invocation source")
    info = adapters.image_info(output)
    inputs = [_record_input(value, base or Path.cwd()) for value in (images or [])]
    folder = _external(job_dir)
    require(not folder.exists(), "Native image invocation record already exists")
    folder.mkdir(parents=True, mode=0o700)
    receipt = {"schema": 1, "kind": "reference-image-generation-receipt", "tool": tool,
               "actual_input_image_sha256": [value["sha256"] for value in inputs], "output_sha256": info["sha256"],
               "invocation_recorded": True, "actual_tool_arguments": actual_arguments, "source_ref": source_ref}
    path = folder / "receipt-0.json"
    _write(path, receipt)
    return {"ok": True, "output": dict(info, path=str(Path(output).resolve())), "receipt": {"path": str(path), "sha256": provider_http.file_hash(path)}}
