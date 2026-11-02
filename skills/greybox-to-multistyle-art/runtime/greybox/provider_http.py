"""Small guarded HTTP transport shared by dedicated supplier adapters.

Credentials come from explicit environment names or a caller-bound private loader. No POST is
retried; exceptions never include remote bodies, headers, URLs or credentials.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import mimetypes
import os
from pathlib import Path
import re
import socket
import struct
import tempfile
from urllib import error, parse, request
import uuid
import zipfile


class ProviderError(ValueError):
    def __init__(self, message, unknown_submission=False, code=None, *, category=None,
                 acceptance=None, retry_after=None, provider_code=None):
        super().__init__(message)
        self.unknown_submission = bool(unknown_submission)
        self.code = code
        self.category, self.acceptance = category, acceptance
        self.retry_after, self.provider_code = retry_after, provider_code


def require(condition, message):
    if not condition:
        raise ProviderError(message)


def safe_id(value):
    require(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,159}", value),
            "Invalid supplier task identifier")
    return value


def _https(url):
    require(isinstance(url, str) and 0 < len(url) <= 16384, "Invalid supplier URL")
    parsed = parse.urlsplit(url)
    try:
        port = parsed.port
    except ValueError:
        raise ProviderError("Invalid supplier URL") from None
    require(parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password
            and port in (None, 443) and not parsed.fragment, "Supplier URLs must use HTTPS without credentials or custom ports")
    return parsed


def public_url(url, resolve=True):
    """Validate every download hop; provider API credentials never accompany it."""
    parsed = _https(url)
    host = parsed.hostname.lower().rstrip(".")
    require(host not in {"localhost", "localhost.localdomain"} and not host.endswith((".localhost", ".local", ".internal")),
            "Local supplier artifact URLs are prohibited")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        require(literal.is_global, "Private supplier artifact addresses are prohibited")
    elif resolve:
        try:
            records = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        except OSError:
            raise ProviderError("Supplier artifact hostname could not be resolved") from None
        require(records and all(ipaddress.ip_address(row[4][0]).is_global for row in records),
                "Private supplier artifact addresses are prohibited")
    return url


class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ProviderError("Authenticated supplier redirects are prohibited", unknown_submission=req.get_method() == "POST")


class _PublicRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        public_url(newurl)
        # This opener is used solely for unauthenticated artifact GETs.
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _part_name(value):
    require(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", value), "Unsafe multipart name")
    return value


def multipart(payload, files):
    boundary = "greybox-" + uuid.uuid4().hex
    body = bytearray()
    for key, value in (payload or {}).items():
        _part_name(key)
        values = value if isinstance(value, list) else [value]
        for entry in values:
            encoded = (json.dumps(entry) if isinstance(entry, (dict, list, bool)) else str(entry)).encode()
            body.extend(("--" + boundary + "\r\nContent-Disposition: form-data; name=\"" + key + "\"\r\n\r\n").encode())
            body.extend(encoded + b"\r\n")
    entries = files.items() if isinstance(files, dict) else files
    for key, source in entries:
        _part_name(key)
        if isinstance(source, tuple):
            filename, content, mime = source
            require(isinstance(content, bytes), "Multipart content must be bytes")
        else:
            path = Path(source)
            require(path.is_file() and path.stat().st_size <= 400 * 1024 * 1024, "Multipart input missing or too large")
            filename, content, mime = path.name, path.read_bytes(), mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        require(isinstance(filename, str) and filename and not any(c in filename for c in '\r\n\"\\/'), "Unsafe multipart filename")
        require(re.fullmatch(r"[a-zA-Z0-9.+-]+/[a-zA-Z0-9.+-]+", mime) is not None, "Invalid multipart MIME type")
        body.extend(("--" + boundary + "\r\nContent-Disposition: form-data; name=\"" + key + "\"; filename=\"" + filename + "\"\r\nContent-Type: " + mime + "\r\n\r\n").encode())
        body.extend(content + b"\r\n")
    body.extend(("--" + boundary + "--\r\n").encode())
    return bytes(body), "multipart/form-data; boundary=" + boundary


class ApiClient:
    def __init__(self, base_url, allowed_hosts, credential_env=None, auth_header="Authorization", auth_prefix="Bearer ",
                 timeout=30, credential_provider=None):
        parsed = _https(base_url)
        require(parsed.hostname in set(allowed_hosts), "Supplier API host is outside the exact allowlist")
        require(auth_header in {"Authorization", "X-API-Key", "x-api-key"}, "Unsupported supplier authentication header")
        self.base_url = base_url.rstrip("/")
        self.allowed_hosts = frozenset(allowed_hosts)
        self.credential_env = credential_env
        self.auth_header, self.auth_prefix = auth_header, auth_prefix
        self.timeout, self.credential_provider = timeout, credential_provider

    def configured(self):
        return bool(self.credential_provider or self.credential_env and os.environ.get(self.credential_env, "").strip())

    def request(self, method, path, payload=None, files=None):
        method = method.upper()
        require(method in {"GET", "POST"}, "Only documented supplier GET/POST operations are supported")
        require(isinstance(path, str) and path.startswith("/") and not path.startswith("//") and "#" not in path,
                "Supplier endpoint must be an absolute API path")
        url = self.base_url + path
        parsed = _https(url)
        require(parsed.hostname in self.allowed_hosts, "Supplier API host is outside the exact allowlist")
        require(not any(segment in {".", ".."} for segment in parse.unquote(parsed.path).split("/")), "Unsafe supplier endpoint path")
        try:
            token = self.credential_provider() if self.credential_provider else os.environ.get(self.credential_env or "", "")
        except Exception:
            raise ProviderError("Supplier authentication could not be loaded") from None
        require(isinstance(token, str) and token.strip() and not any(c in token for c in "\r\n"), "Supplier credential is missing or invalid; configure the exact provider/account region locally")
        headers = {self.auth_header: self.auth_prefix + token.strip(), "Accept": "application/json", "User-Agent": "greybox-art-refinement/3.1"}
        data = None
        if files is not None:
            require(method == "POST", "Multipart requires POST")
            data, headers["Content-Type"] = multipart(payload, files)
        elif payload is not None:
            require(method == "POST", "JSON bodies require POST")
            try:
                data = json.dumps(payload, allow_nan=False, separators=(",", ":")).encode()
            except (TypeError, ValueError):
                raise ProviderError("Supplier payload must be finite JSON") from None
            headers["Content-Type"] = "application/json"
        opener = request.build_opener(request.ProxyHandler({}), _NoRedirect())
        try:
            with opener.open(request.Request(url, data=data, headers=headers, method=method), timeout=self.timeout) as response:
                raw = response.read(16 * 1024 * 1024 + 1)
                if len(raw) > 16 * 1024 * 1024:
                    raise ProviderError("Supplier JSON response exceeds the supported limit", unknown_submission=method == "POST")
                try:
                    result = json.loads(raw)
                except (UnicodeError, ValueError):
                    raise ProviderError("Supplier returned malformed JSON", unknown_submission=method == "POST") from None
                if not isinstance(result, dict):
                    raise ProviderError("Supplier returned an invalid JSON object", unknown_submission=method == "POST")
                return result
        except ProviderError:
            raise
        except error.HTTPError as exc:
            status = exc.code
            from .execution_errors import retry_after
            ambiguous = status == 408 or status >= 500
            raise ProviderError("Supplier HTTP request rejected" if 400 <= status < 500 and status != 408 else "Supplier HTTP outcome needs reconciliation",
                unknown_submission=method == "POST" and ambiguous, code=status,
                category="rate_limit" if status == 429 else ("network" if ambiguous else "permanent"),
                acceptance=("unknown" if ambiguous else "not_accepted") if method == "POST" else "accepted",
                retry_after=retry_after(exc.headers.get("Retry-After") if exc.headers else None)) from None
        except (OSError, error.URLError, TimeoutError):
            raise ProviderError("Supplier transport failed; reconcile the original submission" if method == "POST" else "Supplier read request failed",
                                unknown_submission=method == "POST") from None

    def download(self, url, output_dir, filename):
        public_url(url)
        require(isinstance(filename, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,220}", filename), "Unsafe supplier artifact filename")
        output = Path(output_dir).resolve()
        output.mkdir(parents=True, exist_ok=True)
        target = output / filename
        require(not target.is_symlink(), "Supplier artifact target cannot be a symbolic link")
        temporary = None
        try:
            opener = request.build_opener(request.ProxyHandler({}), _PublicRedirect())
            with opener.open(request.Request(url, headers={"User-Agent": "greybox-art-refinement/3.1"}), timeout=self.timeout) as response:
                public_url(response.geturl())
                with tempfile.NamedTemporaryFile(prefix=".supplier-", suffix=".part", dir=output, delete=False) as file:
                    temporary = Path(file.name)
                    digest, total = hashlib.sha256(), 0
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        total += len(chunk)
                        require(total <= 2 * 1024 * 1024 * 1024, "Supplier artifact exceeds the 2 GiB limit")
                        digest.update(chunk)
                        file.write(chunk)
            require(total > 0, "Supplier artifact is empty")
            if target.exists():
                require(target.is_file() and file_hash(target) == digest.hexdigest(), "Existing supplier output differs; preserve it and select a fresh job directory")
            else:
                # Exclusive link avoids replacing a file created after the existence check.
                try:
                    os.link(temporary, target)
                except FileExistsError:
                    require(target.is_file() and not target.is_symlink() and file_hash(target) == digest.hexdigest(), "Supplier output collision")
            return {"path": str(target), "sha256": digest.hexdigest(), "bytes": total}
        except ProviderError:
            raise
        except (OSError, error.URLError, TimeoutError):
            raise ProviderError("Supplier artifact download failed; resume fetch without generation") from None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_artifact(path, require_geometry=False, require_rig=False, require_animation=False, min_animations=0):
    """Check format and GLB structural demands; target-engine validation remains required."""
    path = Path(path)
    require(path.is_file() and path.stat().st_size > 0, "Supplier artifact missing or empty")
    with path.open("rb") as file:
        header = file.read(28)
        if path.suffix.lower() == ".glb":
            require(len(header) >= 20 and header[:4] == b"glTF", "Supplier GLB header is invalid")
            version, size, json_size, kind = struct.unpack("<IIII", header[4:20])
            require(version == 2 and size == path.stat().st_size and kind == 0x4E4F534A and 0 < json_size <= min(size - 20, 32 * 1024 * 1024), "Supplier GLB structure is invalid")
            file.seek(20)
            try:
                doc = json.loads(file.read(json_size))
            except (ValueError, UnicodeError):
                raise ProviderError("Supplier GLB JSON is invalid") from None
            require(isinstance(doc, dict) and doc.get("asset", {}).get("version") == "2.0", "Supplier GLB asset version is invalid")
            if require_geometry:
                require(any(p.get("attributes", {}).get("POSITION") is not None for mesh in doc.get("meshes", []) for p in mesh.get("primitives", [])), "Supplier GLB has no mesh geometry")
            if require_rig:
                require(any(s.get("joints") for s in doc.get("skins", [])), "Supplier GLB has no skin joints")
            if require_animation:
                require(sum(bool(a.get("channels") and a.get("samplers")) for a in doc.get("animations", [])) >= max(1, min_animations), "Supplier GLB is missing required animation clips/channels")
            return {"format": "glb", "geometry_checked": require_geometry, "rig_checked": require_rig, "animation_checked": require_animation}
        suffix = path.suffix.lower()
        if suffix == ".fbx":
            require(header.startswith(b"Kaydara FBX Binary") or header.lstrip().startswith((b"; FBX", b"FBXHeaderExtension")), "Supplier FBX header is invalid")
        elif suffix in {".zip", ".usdz", ".3mf"}:
            require(zipfile.is_zipfile(path), "Supplier archive structure is invalid")
        elif suffix == ".png":
            require(header.startswith(b"\x89PNG\r\n\x1a\n"), "Supplier PNG header is invalid")
        elif suffix in {".jpg", ".jpeg"}:
            require(header.startswith(b"\xff\xd8"), "Supplier JPEG header is invalid")
        elif suffix == ".webp":
            require(header.startswith(b"RIFF") and header[8:12] == b"WEBP", "Supplier WebP header is invalid")
        else:
            require(suffix in {".obj", ".stl", ".gltf", ".mtl", ".bin", ".exr"}, "Unsupported supplier artifact format")
    return {"format": suffix[1:], "validation": "header/file integrity only; native geometry/rig/animation validation required"}


def bound_file(document, reference, extensions, limit):
    """Resolve only approved hash-bound inputs, including completed dependency outputs."""
    records = list(document.get("inputs", []))
    for dependency in document.get("dependencies", {}).values():
        if dependency.get("state") == "ready":
            records.extend(dependency.get("artifacts", []))
    if type(reference) is int:
        require(0 <= reference < len(document.get("inputs", [])), "Supplier input index is invalid")
        record = document["inputs"][reference]
    else:
        require(isinstance(reference, str), "Supplier local input must name a bound path or index")
        path = Path(reference).resolve()
        matches = [r for r in records if Path(r.get("path", "")).resolve() == path]
        require(len(matches) == 1, "Supplier local input must match one approved input record")
        record = matches[0]
    path = Path(record.get("path", "")).resolve()
    require(path.is_file() and path.suffix.lower() in extensions and 0 < path.stat().st_size <= limit,
            "Supplier local input format or size is unsupported")
    require(isinstance(record.get("sha256"), str) and file_hash(path) == record["sha256"], "Supplier local input changed or is not hash-bound")
    return path


def dependency_task(document, reference, provider):
    record = document.get("dependencies", {}).get(reference)
    require(isinstance(record, dict) and record.get("state") == "ready" and record.get("provider") == provider,
            "Supplier task dependency must be a ready task from the same provider")
    return safe_id(record.get("provider_task_id") or record.get("task_id"))


def fingerprint(document):
    return hashlib.sha256(json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def output_owner(output_dir, provider, task_id):
    """Persist ownership before downloading; a different job cannot reuse the directory."""
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    marker = output / ".supplier-owner.json"
    expected = {"provider": provider, "task_id": task_id}
    require(not marker.is_symlink(), "Supplier output ownership marker cannot be a symlink")
    if marker.exists():
        try:
            existing = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise ProviderError("Invalid supplier output ownership record") from None
        require(existing == expected, "Supplier output directory belongs to another task")
    else:
        require(not any(output.iterdir()), "A fresh supplier output directory or matching ownership record is required")
        try:
            with marker.open("x", encoding="utf-8") as handle:
                json.dump(expected, handle, sort_keys=True)
        except FileExistsError:
            raise ProviderError("Supplier output directory ownership changed concurrently") from None
    return output


def dependency_model(document, reference, extensions):
    record = document.get("dependencies", {}).get(reference)
    require(isinstance(record, dict) and record.get("state") == "ready", "Supplier model dependency must be ready")
    records = [r for r in record.get("artifacts", []) if Path(r.get("path", "")).suffix.lower() in extensions]
    # Prefer a single primary model, rather than animation examples or previews.
    primary = [r for r in records if r.get("role", "").startswith(("model", "rigged_character"))]
    records = primary or records
    glbs = [r for r in records if Path(r.get("path", "")).suffix.lower() == ".glb"]
    if len(glbs) == 1:
        records = glbs
    require(len(records) == 1, "Supplier model dependency needs exactly one primary model; choose an explicit bound path otherwise")
    return records[0]["path"]


def read_bound_file(document, reference, extensions, limit):
    """Bind the bytes actually sent, even if a local producer edits after inspection."""
    path = bound_file(document, reference, extensions, limit)
    if type(reference) is int:
        expected = document["inputs"][reference]["sha256"]
    else:
        records = list(document.get("inputs", []))
        for dependency in document.get("dependencies", {}).values():
            if dependency.get("state") == "ready":
                records.extend(dependency.get("artifacts", []))
        matches = [r for r in records if Path(r.get("path", "")).resolve() == path]
        require(len(matches) == 1, "Supplier local input binding changed")
        expected = matches[0].get("sha256")
    content = path.read_bytes()
    require(0 < len(content) <= limit and hashlib.sha256(content).hexdigest() == expected,
            "Supplier local input bytes changed after inspection")
    return path, content
