"""Dedicated Hi3D/Hitem3D image/multiview API with memory-only AK/SK tokens.

POST /auth/token authenticates; it never starts a generation. Only the gated
supplier runner may call submit. No generation POST is retried automatically.
"""
from __future__ import annotations

from .. import account_profiles

import base64
from decimal import Decimal, InvalidOperation
import hashlib
import os
from pathlib import Path
from urllib.parse import quote, urlsplit

from ..provider_http import (ApiClient, ProviderError, safe_id, public_url, validate_artifact, file_hash,
                             output_owner, dependency_model, bound_file)

PROVIDER = "hitem3d"
BASE = "https://api.hitem3d.ai"
CHECKED_AT = "2026-10-20"
PRICING_CHECKED_AT = "2026-10-23"
ENV = ("HITEM3D_CLIENT_ID", "HITEM3D_CLIENT_SECRET")
RESOLUTIONS = {"hitem3dv1.5": {"512", "1024", "1536", "1536pro"},
    "hitem3dv2.0": {"1536", "1536pro"}, "hitem3dv2.1": {"1536fast", "1536pro"},
    "hi3dv3.0": {"2048quality", "2048master"}, "scene-portraitv1.5": {"1536"},
    "scene-portraitv2.0": {"1536pro"}, "scene-portraitv2.1": {"1536profast", "1536pro"}}
OPERATIONS = ("image_to_3d", "multiview_to_3d", "texture")
FORMATS = {1: ".obj", 2: ".glb", 3: ".stl", 4: ".fbx", 5: ".usdz", 6: ".3mf"}
GEOMETRY_CREDITS = {"hitem3dv1.5": {"512": 5, "1024": 10, "1536": 20, "1536pro": 30},
    "hitem3dv2.0": {"1536": 20, "1536pro": 30}, "hitem3dv2.1": {"1536fast": 10, "1536pro": 30},
    "hi3dv3.0": {"2048quality": 30, "2048master": 130}, "scene-portraitv1.5": {"1536": 20},
    "scene-portraitv2.0": {"1536pro": 30}, "scene-portraitv2.1": {"1536profast": 10, "1536pro": 30}}


class _Invalid(ValueError):
    def __init__(self, code, message, *, unknown=False, task_id=None):
        self.code, self.unknown_submission, self.task_id = code, unknown, task_id
        super().__init__(message)


def _require(condition, message, code="REQUEST_INVALID", **kwargs):
    if not condition:
        raise _Invalid(code, message, **kwargs)


def _body(response, *, submitting=False):
    _require(isinstance(response, dict), "Hi3D returned an invalid response.", "RESPONSE_INVALID", unknown=submitting)
    code = response.get("code")
    if str(code) != "200":
        # Only documented client/validation failures are definite generation rejections.
        known = str(code) in {"401", "40010000", "30010000"} or str(code) in {str(10031000 + n) for n in range(1, 18)}
        raise _Invalid("PROVIDER_REJECTED" if known else "PROVIDER_UNKNOWN", "Hi3D rejected or could not resolve this request.",
                       unknown=submitting and not known)
    data = response.get("data")
    _require(isinstance(data, dict), "Hi3D response lacks its data object.", "RESPONSE_INVALID", unknown=submitting)
    return data


class _Token:
    def __init__(self, credential_envs=None, document=None):
        self.value = None
        self.credential_envs = tuple(credential_envs or ENV)
        self.document = document
        _require(len(self.credential_envs) == 2, "Hi3D auth requires client ID and secret environment names")

    def __call__(self):
        if self.value is None:
            if self.document is None:
                from ..provider_credentials import load
                ak, sk = (load(PROVIDER, "public", name) for name in self.credential_envs)
            else:
                ak, sk = (account_profiles.credential(PROVIDER, self.document, index) for index in range(2))
            _require(ak and sk and ":" not in ak and not any(c in ak + sk for c in "\r\n"),
                     "Configure Hi3D client ID and secret locally; never paste credentials into chat.", "CREDENTIAL_REQUIRED")
            encoded = base64.b64encode((ak + ":" + sk).encode()).decode()
            auth = ApiClient(BASE, allowed_hosts={"api.hitem3d.ai"}, auth_prefix="Basic ", credential_provider=lambda: encoded)
            try:
                data = _body(auth.request("POST", "/open-api/v1/auth/token", payload={}))
            except ProviderError:
                # Authentication could fail after transport; no asset was submitted.
                raise ProviderError("Hi3D authentication failed; no generation was submitted", unknown_submission=False) from None
            token = data.get("accessToken")
            _require(isinstance(token, str) and token.strip() and not any(ord(c) < 32 for c in token) and
                     data.get("tokenType", "Bearer").lower() == "bearer", "Hi3D authentication response is invalid.", "AUTH_RESPONSE_INVALID")
            self.value = token
        return self.value


def _client(request=None):
    config = account_profiles.client_config(PROVIDER, request)
    return ApiClient(config["base_url"], allowed_hosts=config["allowed_hosts"], credential_provider=_Token(config["credential_envs"], request))


def _inputs(request):
    inputs = request.get("inputs", [])
    _require(isinstance(inputs, list), "Hi3D inputs must be hash-bound local records.")
    images, meshes = [], []
    for record in inputs:
        _require(isinstance(record, dict) and isinstance(record.get("path"), str), "Invalid Hi3D input record.")
        path = Path(record["path"])
        _require(path.is_file() and path.stat().st_size > 0, "Hi3D input file is missing or empty.")
        _require(record.get("sha256") == hashlib.sha256(path.read_bytes()).hexdigest(),
                 "Hi3D input hash changed; revise the approved operation.")
        if path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
            _require(path.stat().st_size <= 20 * 1024 * 1024, "Hi3D image exceeds 20 MiB.")
            images.append(str(path))
        else:
            _require(path.suffix.lower() == ".glb" and path.stat().st_size <= 200 * 1024 * 1024,
                     "Hi3D texture input must be a GLB no larger than 200 MiB.")
            meshes.append(str(path))
    return images, meshes


def validate(request):
    _require(isinstance(request, dict) and request.get("operation") in OPERATIONS, "Unsupported Hi3D operation.")
    parameters = request.get("parameters")
    _require(isinstance(parameters, dict), "Hi3D parameters must be an object.")
    p = dict(parameters)
    mesh_dependency = p.pop("mesh_dependency", None)
    _require(set(p) <= {"request_type", "model", "resolution", "multi_images_bit", "mesh_url", "pbr", "rmbg", "shading", "face", "format"},
             "Unknown Hi3D parameter; callbacks and unbound input paths are not enabled.")
    model = p.get("model")
    _require(isinstance(model, str) and model in RESOLUTIONS and request.get("model_version") == model,
             "Select an explicit documented Hi3D model and matching model_version.")
    _require(isinstance(p.get("resolution"), str) and p["resolution"] in RESOLUTIONS[model],
             "Select an explicit resolution supported by this Hi3D model.")
    _require(type(p.get("request_type")) is int and p["request_type"] in {1, 2, 3}, "Select explicit Hi3D request_type 1, 2 or 3.")
    _require(type(p.get("format")) is int and p["format"] in FORMATS, "Select an explicit Hi3D output format.")
    images, meshes = _inputs(request)
    if mesh_dependency is not None:
        _require(not meshes and "mesh_url" not in p and request["operation"] == "texture",
                 "mesh_dependency is a texture-only alternative to a local mesh or mesh_url.")
        reference = dependency_model(request, mesh_dependency, {".glb"})
        meshes.append(str(bound_file(request, reference, {".glb"}, 200 * 1024 * 1024)))
    operation = request["operation"]
    texture = operation == "texture"
    _require((p["request_type"] == 2) == texture, "Hi3D texture must use request_type=2; generation uses 1 or 3.")
    if operation == "image_to_3d":
        _require(len(images) == 1, "Hi3D single-image generation requires exactly one image.")
    elif operation == "multiview_to_3d":
        _require(2 <= len(images) <= 4, "Hi3D multiview requires 2–4 images ordered front, back, left, right.")
    else:
        _require(1 <= len(images) <= 4, "Hi3D texture needs 1–4 reference images.")
        _require(model in {"hitem3dv1.5", "scene-portraitv1.5", "hi3dv3.0"},
                 "The documented Hi3D v2.0/v2.1 models do not support request_type=2.")
    if len(images) > 1:
        bits = p.get("multi_images_bit")
        _require(isinstance(bits, str) and len(bits) == 4 and set(bits) <= {"0", "1"} and bits[0] == "1" and bits.count("1") == len(images),
                 "Explicit multi_images_bit must map the supplied views and include the front view.")
    else:
        _require("multi_images_bit" not in p, "multi_images_bit is only applicable to multiple images.")
    if texture:
        _require(len(meshes) == 1 and "mesh_url" not in p or not meshes and isinstance(p.get("mesh_url"), str),
                 "Hi3D texture requires exactly one local GLB or HTTPS mesh_url.")
        if "mesh_url" in p:
            public_url(p["mesh_url"], resolve=False)
            _require(urlsplit(p["mesh_url"]).path.lower().endswith(".glb"), "Hi3D mesh_url must refer to GLB geometry.")
    else:
        _require(not meshes and "mesh_url" not in p, "Hi3D generation must not include a texture-only input mesh.")
    if "face" in p:
        _require(type(p["face"]) is int and 100000 <= p["face"] <= 5000000,
                 "Hi3D target face count must be 100,000–5,000,000.")
        _require(p["face"] <= 2000000 or model == "hi3dv3.0" and p["resolution"] == "2048master",
                 "Above two million faces is enabled only for Hi3D v3.0 Master.")
    for key in {"pbr", "rmbg"} & set(p):
        _require(type(p[key]) is int and p[key] in {0, 1}, "Hi3D pbr/rmbg must be integer 0 or 1.")
    if "pbr" in p or "shading" in p:
        _require(model not in {"hitem3dv1.5", "scene-portraitv1.5"}, "This Hi3D model does not support PBR/de-shading controls.")
    _require("pbr" not in p or p["request_type"] in {2, 3}, "Hi3D PBR applies only to textured output.")
    if "shading" in p:
        try:
            amount = Decimal(str(p["shading"]))
            _require(type(p["shading"]) is not bool and amount.is_finite() and 0 <= amount <= 1 and amount * 10 == (amount * 10).to_integral(),
                     "Hi3D shading must be in tenths from zero through one.")
        except (InvalidOperation, TypeError, ValueError):
            raise _Invalid("REQUEST_INVALID", "Hi3D shading must be in tenths from zero through one.") from None
    files = [("multi_images" if len(images) > 1 else "images", image) for image in images]
    files += [("mesh", mesh) for mesh in meshes]
    return {key: str(value) for key, value in p.items()}, files


def _task(request):
    task_id = safe_id(request.get("task_id"))
    recovery = request.get("recovery", {})
    _require(not recovery or isinstance(recovery, dict) and recovery.get("task_id") == task_id,
             "Hi3D recovery record belongs to another task.", "RECOVERY_MISMATCH")
    return task_id


def _status(client, request):
    task_id = _task(request)
    raw = client.request("GET", "/open-api/v1/query-task?task_id=" + quote(task_id, safe=""))
    if isinstance(raw, dict) and str(raw.get("code")) == "50010001":
        return {"ok": True, "task_id": task_id, "state": "failed", "billing_state": "refund_documented_not_receipt_verified"}, None
    data = _body(raw)
    _require(data.get("task_id") == task_id, "Hi3D returned a different task ID.", "RESPONSE_MISMATCH")
    states = {"created": "queued", "queueing": "queued", "processing": "running", "success": "succeeded", "failed": "failed"}
    _require(isinstance(data.get("state"), str) and data["state"] in states, "Hi3D returned an unknown task state.", "RESPONSE_INVALID")
    return {"ok": True, "task_id": task_id, "state": states[data["state"]]}, data


def _fetch(client, request):
    checked, data = _status(client, request)
    _require(checked["state"] == "succeeded", "Hi3D task is not complete; resume this task only.", "TASK_NOT_READY")
    url = data.get("url")
    _require(isinstance(url, str) and url, "Hi3D completed task lacks its model URL.", "RESPONSE_INCOMPLETE")
    public_url(url, resolve=False)
    accepted = request.get("accepted_request", {})
    accepted_format = accepted.get("parameters", {}).get("format")
    suffix = Path(urlsplit(url).path).suffix.lower()
    _require(suffix in set(FORMATS.values()) | {".zip"}, "Hi3D model URL has an unsupported container/format.", "ARTIFACT_INVALID")
    _require(accepted_format in FORMATS and (suffix == FORMATS[accepted_format] or suffix == ".zip"),
             "Hi3D output does not match the approved output format.", "ARTIFACT_INVALID")
    output = Path(request.get("output_dir", ""))
    _require(output.is_absolute(), "Fetch requires an absolute job output directory.")
    output = output_owner(output, PROVIDER, checked["task_id"])
    artifact = client.download(url, output, "model" + suffix)
    _require(isinstance(artifact, dict) and isinstance(artifact.get("path"), str) and
             Path(artifact["path"]).resolve() == (output / ("model" + suffix)).resolve() and
             not Path(artifact["path"]).is_symlink(), "Hi3D download is outside this job's exact output.", "ARTIFACT_INVALID")
    _require(artifact.get("sha256") == file_hash(artifact["path"]), "Hi3D artifact hash mismatch.", "ARTIFACT_INVALID")
    artifact["validation"] = validate_artifact(artifact["path"], require_geometry=suffix == ".glb")
    artifact["container"] = suffix in {".zip", ".usdz", ".3mf"}
    return {"ok": True, "task_id": checked["task_id"], "state": "succeeded", "artifacts": [artifact],
            "validation": "file/header integrity only; native material/scale/rig checks still required"}


def _dispatch(method, request, client=None):
    envelope = {"provider": PROVIDER, "method": method}
    try:
        if method == "capabilities":
            return dict(envelope, ok=True, operations=list(OPERATIONS), model_versions=sorted(RESOLUTIONS), checked_at=CHECKED_AT,
                        required_env=list(ENV), configured=all(os.environ.get(key, "").strip() for key in ENV), connection_verified=False,
                        live_verified=False, limitations=["No text-to-3D, rig or animation route in this adapter.",
                        "Texture-only excludes documented v2.0/v2.1 models; high face counts require downstream optimization."])
        if method == "validate":
            parameters, files = validate(request)
            safe_parameters = {key: value for key, value in parameters.items() if key != "mesh_url"}
            return dict(envelope, ok=True, operation=request["operation"], model_version=request["model_version"],
                        parameters=safe_parameters, input_count=len(files))
        if method == "quote":
            validate(request)
            p = request["parameters"]
            geometry = GEOMETRY_CREDITS[p["model"]][p["resolution"]] if p["request_type"] in {1, 3} else 0
            texture = 10 if p["request_type"] in {2, 3} else 0
            pbr = 5 if texture and p["model"] not in {"hitem3dv1.5", "scene-portraitv1.5"} and p.get("pbr", 1) else 0
            credits = geometry + texture + pbr
            return dict(envelope, ok=True, kind="rate_card_estimate", unit_credits=str(credits), quantity=1, network_calls=0,
                        components={"geometry": geometry, "texture": texture, "pbr": pbr},
                        list_price={"currency": "USD", "amount": str(Decimal(credits) * Decimal("0.020")),
                                    "basis": "Published API list rate; purchased resource-package discounts and tax are separate."},
                        source={"url": "https://docs.hi3d.ai/en/api/getting-started/pricing", "checked_at": PRICING_CHECKED_AT + "T00:00:00Z",
                                "sha256": "224600782588a6904a06a33757a8d6005eba6ecb6696835ae257f04fbf2cc0c8"},
                        note="Local official-rate estimate; no provider query, generation or billing receipt.")
        _require(method in {"account", "connection", "submit", "status", "fetch"},
                 "Unsupported Hi3D method; estimate prices from the official API rate card locally.")
        if method == "submit": validate(request)
        api = client or _client(request)
        if method in {"account", "connection"}:
            data = _body(api.request("GET", "/open-api/v1/balance"))
            try:
                balance = Decimal(str(data.get("totalBalance")))
                _require(balance.is_finite() and balance >= 0 and type(data.get("totalBalance")) is not bool,
                         "Hi3D account response lacks a valid balance.", "RESPONSE_INVALID")
            except (InvalidOperation, TypeError, ValueError):
                raise _Invalid("RESPONSE_INVALID", "Hi3D account response lacks a valid balance.") from None
            return dict(envelope, ok=True, connection_verified=True, balance=str(balance), spending_authorized=False)
        if method == "submit":
            parameters, files = validate(request)
            data = _body(api.request("POST", "/open-api/v1/submit-task", payload=parameters, files=files), submitting=True)
            try:
                task_id = safe_id(data.get("task_id"))
            except ProviderError:
                raise _Invalid("SUBMISSION_UNKNOWN", "Hi3D response lacks an exact task ID; reconcile before new submission.", unknown=True) from None
            result = {"ok": True, "task_id": task_id, "provider_task_id": task_id, "state": "submitted", "recovery": {"task_id": task_id}}
        elif method == "status":
            result, _ = _status(api, request)
        else:
            result = _fetch(api, request)
        return dict(envelope, **result)
    except (_Invalid, ProviderError, OSError) as exc:
        unknown = method == "submit" and bool(getattr(exc, "unknown_submission", False))
        result = dict(envelope, ok=False, state="unknown" if unknown else "rejected" if method == "submit" else "incomplete",
                      unknown_submission=unknown, error={"code": getattr(exc, "code", None) or "PROVIDER_IO_ERROR",
                      "message": str(exc) if isinstance(exc, (_Invalid, ProviderError)) else "Local provider I/O failed.",
                      "unknown_submission": unknown})
        from ..execution_errors import classify_error
        result["error"].update(classify_error(exc, method))
        if getattr(exc, "task_id", None): result["task_id"] = exc.task_id
        return result


def dispatch(method, request, client=None):
    request = account_profiles.bind_request(PROVIDER, method, request)
    return account_profiles.bind_result(PROVIDER, request, _dispatch(method, request, client))
