"""Raster service adapters. No submit retry, no credentials in job documents.

This transport is deliberately separate from the 3D transport: image responses
can contain large base64 bodies and the standard edits API uses image[].
"""
from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import mimetypes
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib import error, parse, request
import uuid

from . import provider_http

MAX_IMAGE_BYTES = 64 * 1024 * 1024
MAX_JSON_BYTES = 128 * 1024 * 1024


class ImageError(ValueError):
    def __init__(self, message, *, unknown_submission=False, code="IMAGE_ERROR", category=None,
                 acceptance=None, retry_after=None, provider_code=None):
        super().__init__(message)
        self.unknown_submission = unknown_submission
        self.code = code
        self.category, self.acceptance = category, acceptance
        self.retry_after, self.provider_code = retry_after, provider_code


def require(value, message):
    if not value:
        raise ImageError(message)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def image_info(path):
    """Decode pixels, not just file headers; reject truncated/oversized outputs."""
    path = Path(path)
    require(path.is_file() and 0 < path.stat().st_size <= MAX_IMAGE_BYTES, "Image is missing, empty or exceeds 64 MiB")
    try:
        from PIL import Image
    except ImportError:
        raise ImageError("Image validation needs Pillow in this Python runtime; install the host image dependencies", code="IMAGE_DEPENDENCY_REQUIRED") from None
    try:
        with Image.open(path) as image:
            require(image.format in {"PNG", "JPEG", "WEBP"}, "Image must decode as PNG, JPEG or WebP")
            require(0 < image.width * image.height <= 100_000_000, "Image pixel count exceeds the supported limit")
            image.load()
            return {"format": image.format.lower(), "width": image.width, "height": image.height,
                    "bytes": path.stat().st_size, "sha256": provider_http.file_hash(path)}
    except ImageError:
        raise
    except Exception:
        raise ImageError("Image pixels could not be decoded; preserve the task and fetch again") from None


def validate_base(url):
    require(isinstance(url, str), "Image API base URL is required")
    parsed = parse.urlsplit(url)
    try:
        parsed.port
    except ValueError:
        raise ImageError("Invalid image API port") from None
    require(parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password
            and not parsed.query and not parsed.fragment, "Image API base URL must use HTTPS without credentials, query or fragment")
    require(not any(p in {".", ".."} for p in parse.unquote(parsed.path).split("/")), "Unsafe image API path")
    return url.rstrip("/")


def multipart(payload, files):
    """Encode repeated image[] fields, with bounded hash-checked local bytes."""
    boundary = "greybox-image-" + uuid.uuid4().hex
    result = bytearray()
    for name, value in payload.items():
        require(re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", name), "Unsafe multipart field")
        encoded = (json.dumps(value) if isinstance(value, (dict, list, bool)) else str(value)).encode()
        result.extend(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        result.extend(encoded + b"\r\n")
    total = 0
    for name, record in files:
        require(name in {"image", "image[]", "mask"}, "Unsupported image multipart field")
        source = Path(record["path"])
        raw = source.read_bytes()
        require(0 < len(raw) <= MAX_IMAGE_BYTES and hashlib.sha256(raw).hexdigest() == record["sha256"], "Image input changed before transmission")
        total += len(raw)
        require(total <= 256 * 1024 * 1024, "Combined multipart image inputs exceed 256 MiB")
        # Use generated names; local filenames never become HTTP header text.
        mime = {"png": "image/png", "jpeg": "image/jpeg", "webp": "image/webp"}[record["format"]]
        filename = record["sha256"] + "." + record["format"]
        result.extend(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\nContent-Type: {mime}\r\n\r\n'.encode())
        result.extend(raw + b"\r\n")
    result.extend(f"--{boundary}--\r\n".encode())
    return bytes(result), "multipart/form-data; boundary=" + boundary


class ImageHttp:
    def __init__(self, profile, credential_provider=None):
        self.profile = profile
        self.base = validate_base(profile["base_url"])
        self.credential_provider = credential_provider

    def token(self):
        try:
            token = self.credential_provider() if self.credential_provider else os.environ.get(self.profile.get("credential_env", ""), "")
        except Exception:
            raise ImageError("Image API credential could not be loaded", code="IMAGE_CREDENTIAL_REQUIRED") from None
        require(isinstance(token, str) and token.strip() and not any(c in token for c in "\r\n"), "Configure the image API credential environment locally")
        return token.strip()

    def call(self, method, path, payload=None, files=None):
        require(method in {"GET", "POST"} and path.startswith("/") and not path.startswith("//")
                and "#" not in path and not any(p in {".", ".."} for p in parse.unquote(parse.urlsplit(path).path).split("/")), "Invalid image API operation path")
        token = self.token()
        headers = {"Authorization": ("" if self.profile.get("auth") == "raw" else "Bearer ") + token,
                   "Accept": "application/json", "User-Agent": "greybox-art/0.4-images"}
        data = None
        if files is not None:
            data, headers["Content-Type"] = multipart(payload, files)
        elif payload is not None:
            data = json.dumps(payload, allow_nan=False).encode()
            headers["Content-Type"] = "application/json"
        opener = request.build_opener(request.ProxyHandler({}), provider_http._NoRedirect())
        try:
            with opener.open(request.Request(self.base + path, data=data, method=method, headers=headers),
                             timeout=self.profile.get("timeout", 300)) as response:
                raw = response.read(MAX_JSON_BYTES + 1)
            if len(raw) > MAX_JSON_BYTES:
                raise ImageError("Image API response exceeds 128 MiB; recover the existing task", unknown_submission=method == "POST")
            try:
                value = json.loads(raw)
            except (UnicodeError, ValueError):
                raise ImageError("Image API returned malformed JSON", unknown_submission=method == "POST") from None
            if not isinstance(value, dict):
                raise ImageError("Image API response must be an object", unknown_submission=method == "POST")
            return value
        except ImageError:
            raise
        except provider_http.ProviderError:
            raise ImageError("Image API redirected; reconcile the original task", unknown_submission=method == "POST") from None
        except error.HTTPError as exc:
            from .execution_errors import retry_after
            ambiguous = exc.code in {408} or exc.code >= 500
            raise ImageError("Image API rejected the request" if not ambiguous else "Image API outcome needs reconciliation",
                             unknown_submission=method == "POST" and ambiguous, code="IMAGE_HTTP_" + str(exc.code),
                             category="rate_limit" if exc.code == 429 else ("network" if ambiguous else "permanent"),
                             acceptance=("unknown" if ambiguous else "not_accepted") if method == "POST" else "accepted",
                             retry_after=retry_after(exc.headers.get("Retry-After") if exc.headers else None)) from None
        except (OSError, error.URLError, TimeoutError):
            raise ImageError("Image transport failed; recover the existing task", unknown_submission=method == "POST", code="IMAGE_TRANSPORT_FAILED") from None


OPENAI_CAPABILITIES = {"generate": True, "edit": True, "max_references": 16, "mask": True,
                       "size": True, "transparent_background": True,
                       "parameters": ["size", "quality", "background", "output_format", "output_compression", "response_format", "n", "user", "moderation", "input_fidelity", "style"]}
LUX_CAPABILITIES = {"generate": True, "edit": True, "max_references": 1, "mask": False,
                    "size": False, "transparent_background": False, "parameters": []}


def capabilities(profile):
    defaults = LUX_CAPABILITIES if profile["kind"] == "lux" else OPENAI_CAPABILITIES
    return dict(defaults, **profile.get("capabilities", {})) if profile["kind"] != "custom" else dict(profile["capabilities"])


def validate_request(profile, document):
    require(isinstance(document, dict), "Image request must be a JSON object")
    allowed = {"operation", "prompt", "images", "mask", "parameters", "purpose", "source_ref"}
    require(not set(document) - allowed, "Image request contains unknown fields")
    cap = capabilities(profile)
    operation = document.get("operation", "edit" if document.get("images") else "generate")
    require(operation in {"generate", "edit"} and cap.get(operation) is True, "Image service does not support this operation")
    images = document.get("images", [])
    require(isinstance(images, list) and len(images) <= cap.get("max_references", 0), "Image service does not support this reference count")
    require((operation == "edit") == bool(images), "Use edit for reference images and generate for text-only input")
    prompt = document.get("prompt")
    require(prompt is None or isinstance(prompt, str) and prompt.strip() and len(prompt) <= 100_000, "Image prompt must be a nonempty string")
    require(bool(prompt) or profile["kind"] == "lux" and bool(images), "This image service needs a prompt")
    require(not document.get("mask") or cap.get("mask") is True and operation == "edit", "Image service does not support a mask for this operation")
    parameters = document.get("parameters", {})
    require(isinstance(parameters, dict) and set(parameters) <= set(cap.get("parameters", [])), "Image service does not support one or more request parameters")
    require("size" not in parameters or cap.get("size") is True, "Image service cannot control output size")
    require(parameters.get("background") != "transparent" or cap.get("transparent_background") is True, "Image service cannot produce transparent backgrounds")
    # Validate finite JSON before any upload/submission reservation.
    try:
        fingerprint(parameters)
    except (TypeError, ValueError):
        raise ImageError("Image parameters must be finite JSON") from None
    return dict(document, operation=operation, images=images, parameters=parameters)


def openai_submit(profile, document):
    payload = {"model": profile["model"], "prompt": document["prompt"], **document["parameters"]}
    client = ImageHttp(profile)
    if document["operation"] == "generate":
        raw = client.call("POST", "/images/generations", payload)
    else:
        field = "image[]" if len(document["images"]) > 1 else "image"
        files = [(field, record) for record in document["images"]]
        if document.get("mask"):
            files.append(("mask", document["mask"]))
        raw = client.call("POST", "/images/edits", payload, files)
    if not isinstance(raw.get("data"), list) or not raw["data"]:
        raise ImageError("Image create response has no image data; reconcile the original invocation", unknown_submission=True)
    return {"state": "succeeded", "items": raw["data"], "usage": raw.get("usage"),
            "provider_task_id": raw.get("id"), "provider_created": raw.get("created")}


def _lux_upload_direct(path, region):
    """Pinned uploader with the same explicit proxy isolation as other APIs."""
    from . import lux
    import requests
    session = requests.Session()
    session.trust_env = False
    try:
        return lux._module("asset_uploader").upload_file(path, region=region,
                   credential_provider=lux.credential_provider, session=session)
    except Exception:
        raise ImageError("Lux image input upload failed; retry the upload without generating", code="IMAGE_INPUT_UPLOAD_FAILED") from None
    finally:
        session.close()


def _lux_upload_worker():
    # Private child stdout is captured by the calling adapter, never forwarded to
    # the host transcript. It can contain the provider's recovery/upload URL.
    try:
        value = json.load(sys.stdin)
        result = _lux_upload_direct(value["path"], value["region"])
        print(json.dumps({"ok": True, "data": result}))
        return 0
    except Exception:
        print(json.dumps({"ok": False, "error": "Lux image input upload failed"}))
        return 2


def _lux_upload_image(path, region):
    from . import lux
    if importlib.util.find_spec("requests") is not None:
        return _lux_upload_direct(path, region)
    python = lux._runtime_python()
    runtime = str(Path(__file__).resolve().parents[1])
    script = "import sys; sys.path.insert(0," + repr(runtime) + "); from greybox.image_adapters import _lux_upload_worker; raise SystemExit(_lux_upload_worker())"
    try:
        completed = subprocess.run([python, "-B", "-c", script], input=json.dumps({"path": str(path), "region": region}),
                                   text=True, capture_output=True, timeout=600)
        value = json.loads(completed.stdout)
        require(completed.returncode == 0 and value.get("ok") is True and isinstance(value.get("data"), dict), "Lux image upload worker failed")
        return value["data"]
    except Exception:
        raise ImageError("Lux image input upload failed; retry the upload without generating", code="IMAGE_INPUT_UPLOAD_FAILED") from None


def lux_call(profile, document=None, task_id=None):
    from . import lux
    # Credential/upload/routing validation is shared with the pinned bridge; its
    # source and original task parameters are never modified by image support.
    lux._verify_vendor()
    region = lux._region(profile.get("region"))
    routed = dict(profile, base_url=lux.BASES[region], auth="raw")
    client = ImageHttp(routed, credential_provider=lambda: lux.credential_provider(region))
    if document is not None:
        payload = {}
        if document.get("prompt"):
            payload["prompt"] = document["prompt"]
        if document["images"]:
            source = document["images"][0]
            raw_image = Path(source["path"]).read_bytes()
            require(hashlib.sha256(raw_image).hexdigest() == source["sha256"], "Lux image input changed before upload")
            # The pinned uploader reads the exact verified snapshot, even if an
            # upstream editor changes the original while its upload is running.
            with tempfile.TemporaryDirectory(prefix="greybox-image-upload-") as scratch:
                snapshot = Path(scratch) / (source["sha256"] + "." + source["format"])
                snapshot.write_bytes(raw_image)
                if importlib.util.find_spec("requests") is None:
                    try:
                        lux._runtime_python()
                    except lux.LuxError as exc:
                        if exc.code != "DEPENDENCY_SETUP_REQUIRED":
                            raise
                        # Explicit image execution may repair its missing private
                        # upload runtime. Configuration/doctor never installs.
                        lux.setup(region, install_dependencies=True)
                uploaded = _lux_upload_image(snapshot, region)
            require(isinstance(uploaded, dict) and isinstance(uploaded.get("url"), str), "Lux upload did not return an image URL")
            payload["img"] = uploaded["url"]
        raw = client.call("POST", "/lux3d/v1/generate/multimodal-to-image/task/create", payload)
        if isinstance(raw.get("c"), str) and raw["c"] != "0":
            from .execution_errors import safe_code
            code = safe_code(raw["c"], "IMAGE_SUBMISSION_REJECTED")
            capacity = code == "GENERATION_CONCURRENCY_LIMIT_EXCEEDED"
            limited = code in {"RATE_LIMITED", "RATE_LIMIT_EXCEEDED"}
            raise ImageError("Lux image API rejected the request", code=code,
                             category="capacity" if capacity else ("rate_limit" if limited else "permanent"),
                             acceptance="not_accepted", provider_code=code)
        if not {"f", "c", "m", "d"} <= set(raw) or raw["c"] != "0" or raw["f"] is not None or raw["m"] != "":
            raise ImageError("Lux create envelope is malformed; reconcile the original invocation", unknown_submission=True)
        value = raw.get("d")
        if type(value) is not int or value <= 0:
            raise ImageError("Lux create response lacks a valid task ID", unknown_submission=True)
        return {"state": "submitted", "provider_task_id": str(value), "actual_parameters": payload}
    require(str(task_id).isdigit() and int(task_id) > 0, "Lux recovery needs the original positive task ID")
    raw = client.call("GET", "/lux3d/v1/generate/task/get?taskid=" + str(task_id))
    require({"f", "c", "m", "d"} <= set(raw) and raw["c"] == "0" and raw["f"] is None and raw["m"] == "", "Lux task query envelope is invalid")
    task = raw.get("d", {})
    require(isinstance(task, dict) and task.get("bizId") == "LUX_3D" and str(task.get("taskId")) == str(task_id)
            and type(task.get("status")) is int and task["status"] in range(7), "Lux task query returned an invalid or different task")
    state = {0: "submitted", 1: "running", 2: "running", 3: "succeeded", 4: "failed", 5: "failed", 6: "cancelled"}[task["status"]]
    items = []
    if state == "succeeded":
        outputs = task.get("outputs", [])
        require(isinstance(outputs, list), "Lux image outputs are malformed")
        for output in outputs:
            content = output.get("content") if isinstance(output, dict) else None
            if isinstance(content, str) and content.startswith("https://"):
                items.append({"url": content})
        require(len(items) == 1, "Lux single-image task must return exactly one image")
    return {"state": state, "provider_task_id": str(task_id), "items": items}


def validate_custom(profile):
    spec = profile["adapter"]
    require(isinstance(spec.get("source"), str) and Path(spec["source"]).expanduser().is_absolute(), "Custom adapter source must be an absolute path")
    source = Path(spec["source"]).expanduser().resolve()
    require(source.is_file() and provider_http.file_hash(source) == spec["sha256"], "Custom image adapter source changed; review and register its new hash")
    argv = spec.get("argv")
    require(isinstance(argv, list) and argv and all(isinstance(v, str) and v for v in argv), "Custom adapter needs an argv array")
    require(Path(argv[0]).is_absolute() and Path(argv[0]).is_file(), "Custom adapter executable must be an existing absolute path")
    # Merely mentioning the bound source as an unused trailing argument would
    # permit execution of a different, unbound script. Bind the actual entrypoint.
    if Path(argv[0]).resolve() != source:
        position = 1
        while position < len(argv) and argv[position] in {"-B", "-u", "-I", "-E", "-s"}:
            position += 1
        require(position < len(argv) and argv[position] in {"{adapter}", str(source)}, "Custom argv must execute the hash-bound source as its entrypoint")
    require(all(not any(c in part for c in "\r\n") for part in argv), "Custom adapter argv contains unsafe line breaks")
    doc = spec.get("documentation", {})
    require(isinstance(doc.get("source_ref"), str) and doc["source_ref"].strip(), "Custom adapter must register the actual API manual source")
    if doc.get("path"):
        path = Path(doc["path"])
        require(path.is_absolute(), "Custom adapter documentation snapshot must use an absolute path")
        require(path.is_file() and provider_http.file_hash(path) == doc.get("sha256"), "Custom adapter documentation snapshot changed")
    return [part.replace("{adapter}", str(source)) for part in argv]


def custom_call(profile, *, document=None, task_id=None):
    argv = validate_custom(profile)
    action = "submit" if document is not None else "status"
    request_doc = {"schema": "greybox.image-adapter/v1", "action": action,
                   "request": document, "task_id": task_id,
                   "config": {k: profile[k] for k in ("base_url", "model", "credential_env") if k in profile}}
    try:
        completed = subprocess.run(argv, input=json.dumps(request_doc), capture_output=True, text=True,
                                   timeout=profile.get("timeout", 300), shell=False)
    except (OSError, subprocess.TimeoutExpired):
        raise ImageError("Custom image adapter did not complete; recover its original invocation", unknown_submission=action == "submit") from None
    if completed.returncode:
        # An extension failure cannot prove that its HTTP submission was rejected.
        raise ImageError("Custom image adapter failed; diagnostic output remains private", unknown_submission=action == "submit")
    try:
        require(len(completed.stdout) <= MAX_JSON_BYTES, "Custom adapter output exceeds the supported limit")
        result = json.loads(completed.stdout)
        require(isinstance(result, dict) and result.get("state") in {"submitted", "running", "succeeded", "failed", "cancelled"}, "Custom adapter returned an invalid state")
        if result["state"] in {"submitted", "running"}:
            require(isinstance(result.get("provider_task_id"), str) and result["provider_task_id"], "Async custom adapter needs the original provider task ID")
        if result["state"] == "succeeded":
            require(isinstance(result.get("items"), list) and result["items"], "Custom adapter succeeded without image artifacts")
        if task_id is not None:
            require(str(result.get("provider_task_id")) == str(task_id), "Custom adapter returned a different task")
        return result
    except (ImageError, ValueError, TypeError):
        raise ImageError("Custom image adapter response is malformed; recover the original invocation", unknown_submission=action == "submit") from None


def submit(profile, document):
    if profile["kind"] == "lux":
        return lux_call(profile, document=document)
    if profile["kind"] == "openai":
        return openai_submit(profile, document)
    return custom_call(profile, document=document)


def status(profile, task_id):
    if profile["kind"] == "lux":
        return lux_call(profile, task_id=task_id)
    require(profile["kind"] == "custom", "Synchronous Images API has no task-status endpoint; import its saved response to recover")
    return custom_call(profile, task_id=task_id)
