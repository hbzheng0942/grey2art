"""Dedicated Hyper3D Rodin API v2 adapter. No call grants spending authority.

Generation is multipart; status and download are query-only POST operations.
The generation UUID and private jobs.subscription_key are NOT interchangeable.
"""
from __future__ import annotations

from .. import account_profiles

from decimal import Decimal, InvalidOperation
import hashlib
import os
from pathlib import Path
import re

from ..provider_http import ApiClient, ProviderError, safe_id, validate_artifact, file_hash, output_owner

PROVIDER = "rodin"
BASE = "https://api.hyper3d.com"
CHECKED_AT = "2026-10-20"
TIERS = {"Sketch", "Regular", "Detail", "Smooth", "Gen-2"} | {
    "Gen-2.5-" + level for level in ("Extreme-Low", "Low", "Medium", "High", "Extreme-High")}
OPERATIONS = ("image_to_3d", "text_to_3d")
COMMON = {"tier", "prompt", "mesh_mode", "geometry_file_format", "material", "quality",
          "quality_override", "seed", "bbox_condition", "addons", "TAPose", "use_original_alpha",
          "preview_render"}
GEN2 = {"soft", "detail_level", "quad_normal", "is_symmetric", "hd_texture"}
GEN25 = {"texture_mode", "image_label", "uhd_texture", "is_micro", "geometry_instruct_mode", "texture_delight"}
GEN1 = {"condition_mode", "mesh_simplify", "mesh_smooth"}
BOOLS = {"TAPose", "use_original_alpha", "preview_render", "soft", "quad_normal", "hd_texture",
         "uhd_texture", "is_micro", "texture_delight", "mesh_simplify", "mesh_smooth"}
MODELS = {".glb", ".obj", ".fbx", ".usdz", ".stl", ".zip"}


class _Invalid(ValueError):
    def __init__(self, code, message, *, unknown=False, task_id=None, recovery=None):
        self.code, self.unknown_submission = code, unknown
        self.task_id, self.recovery = task_id, recovery
        super().__init__(message)


def _require(condition, message, code="REQUEST_INVALID", **kwargs):
    if not condition:
        raise _Invalid(code, message, **kwargs)


def _client(request=None):
    config = account_profiles.client_config(PROVIDER, request)
    return ApiClient(config["base_url"], allowed_hosts=config["allowed_hosts"], credential_env=config["credential_envs"][0],
                     credential_provider=lambda: account_profiles.credential(PROVIDER, request))


def _task(value):
    _require(isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", value),
             "Rodin needs the generation response's top-level UUID.")
    return safe_id(value)


def _images(request):
    records = request.get("inputs", [])
    _require(isinstance(records, list), "Rodin inputs must be hash-bound local image records.")
    result = []
    for record in records:
        _require(isinstance(record, dict) and isinstance(record.get("path"), str), "Invalid Rodin image input.")
        path = Path(record["path"])
        _require(path.is_file() and 0 < path.stat().st_size <= 20 * 1024 * 1024,
                 "Rodin image must be a nonempty local file no larger than 20 MiB.")
        _require(path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}, "Use PNG, JPEG or WebP images.")
        _require(record.get("sha256") == hashlib.sha256(path.read_bytes()).hexdigest(),
                 "Rodin input hash changed; revise the approved operation.")
        result.append(("images", str(path)))
    return result


def validate(request):
    _require(isinstance(request, dict) and request.get("operation") in OPERATIONS, "Unsupported Rodin operation.")
    parameters = request.get("parameters")
    _require(isinstance(parameters, dict), "Rodin parameters must be an object.")
    p = dict(parameters)
    tier = p.get("tier")
    _require(isinstance(tier, str) and tier in TIERS, "Select an explicit documented Rodin tier; no implicit Regular fallback.")
    family = "Gen-2.5" if tier.startswith("Gen-2.5-") else "Gen-2" if tier == "Gen-2" else "Gen-1/1.5"
    _require(isinstance(request.get("model_version"), str) and request["model_version"] in {tier, family},
             "Rodin model_version must match the explicit tier/family.")
    allowed = COMMON | (GEN2 | GEN25 if family == "Gen-2.5" else GEN2 if family == "Gen-2" else GEN1)
    _require(set(p) <= allowed, "Unknown or unsupported Rodin parameter for this generation family.")
    files = _images(request)
    if request["operation"] == "image_to_3d":
        _require(1 <= len(files) <= 5, "Rodin image generation needs 1–5 ordered input images.")
    else:
        _require(not files and isinstance(p.get("prompt"), str) and bool(p["prompt"].strip()),
                 "Rodin text generation needs a prompt and no images.")
    if "prompt" in p:
        _require(isinstance(p["prompt"], str) and 0 < len(p["prompt"]) <= 1024, "Rodin prompt length must be 1–1024.")
    enums = {"mesh_mode": {"Raw", "Quad"}, "geometry_file_format": {"glb", "fbx", "obj", "usdz", "stl"},
             "material": {"PBR", "Shaded", "All", "None"} | ({"Hybrid"} if family == "Gen-1/1.5" else set()),
             "quality": {"high", "medium", "low", "extra-low"}, "condition_mode": {"fuse", "concat"},
             "is_symmetric": {"symmetric", "balanced", "asymmetric", "unknown"},
             "texture_mode": {"legacy", "extreme-low", "low", "medium", "high", "extreme-high"},
             "geometry_instruct_mode": {"creative", "faithful"}}
    for key, values in enums.items():
        if key in p:
            _require(isinstance(p[key], str) and p[key] in values, "Invalid Rodin " + key + ".")
    for key in BOOLS & set(p):
        _require(type(p[key]) is bool, "Rodin boolean parameters must be actual booleans.")
    for key, low, high in (("seed", 0, 65535), ("detail_level", 1, 3)):
        if key in p:
            _require(type(p[key]) is int and low <= p[key] <= high, "Invalid Rodin " + key + ".")
    if "quality_override" in p:
        high = 200000 if family == "Gen-1/1.5" else 2000000 if tier in {"Gen-2.5-High", "Gen-2.5-Extreme-High"} else 1000000
        if p.get("mesh_mode", "Raw" if family == "Gen-2.5" else "Quad") == "Quad":
            high = min(high, 200000)
        _require(type(p["quality_override"]) is int and 500 <= p["quality_override"] <= high,
                 "Rodin target faces exceed the selected tier/topology limit.")
    if "bbox_condition" in p:
        _require(isinstance(p["bbox_condition"], list) and len(p["bbox_condition"]) == 3 and
                 all(type(v) is int and v > 0 for v in p["bbox_condition"]), "Rodin bbox needs three positive integers.")
    if "addons" in p:
        _require(isinstance(p["addons"], list) and p["addons"] in ([], ["HighPack"]), "Unsupported Rodin add-on.")
    if "image_label" in p:
        _require(isinstance(p["image_label"], list) and len(p["image_label"]) <= len(files) and
                 all(isinstance(v, str) and v in {"F", "FL", "FR", "B", "BL", "BR", "L", "R", "U", "D", "?"} for v in p["image_label"]),
                 "Rodin labels must match the ordered input images.")
    _require(not p.get("is_micro") or tier == "Gen-2.5-Extreme-High", "Rodin micro detail requires Extreme-High tier.")
    _require("mesh_simplify" not in p or p.get("mesh_mode", "Quad") == "Raw", "mesh_simplify requires Raw mode.")
    _require("mesh_smooth" not in p or p.get("mesh_mode", "Quad") == "Quad", "mesh_smooth requires Quad mode.")
    _require("geometry_instruct_mode" not in p or tier in {"Gen-2.5-Medium", "Gen-2.5-High", "Gen-2.5-Extreme-High"},
             "Geometry instruction mode is unavailable for this tier.")
    # The form always declares its output format; keeping GLB explicit makes handoff reproducible.
    p.setdefault("geometry_file_format", "glb")
    return p, files


def _form(parameters):
    import json
    return {key: ("true" if value else "false") if type(value) is bool else
            json.dumps(value, separators=(",", ":")) if isinstance(value, list) else str(value)
            for key, value in parameters.items()}


def _body(response, *, submitting=False):
    _require(isinstance(response, dict), "Rodin returned an invalid response.", "RESPONSE_INVALID", unknown=submitting)
    error = response.get("error")
    if error:
        definitive = isinstance(error, str) and error in {"API_NO_ACTIVE_SUBSCRIPTION", "API_SUBSCRIPTION_PLAN_TOO_LOW", "API_PARALLELISM_LIMIT_REACHED",
            "API_INSUFFICIENT_FUNDS", "API_OBJECT_NOT_FOUND_ON_IMAGE", "INVALID_REQUEST", "IMAGE_LABEL_LENGTH_TOO_LONG",
            "IMAGE_CONTENT_VIOLATION", "PERMISSION_DENIED", "NO_SUCH_TASK", "ASSET_NOT_AVAILABLE"}
        raise _Invalid("PROVIDER_REJECTED" if definitive else "PROVIDER_UNKNOWN", "Rodin rejected or could not resolve this request.",
                       unknown=submitting and not definitive)
    return response


def _recovery(request):
    task_id = _task(request.get("task_id"))
    recovery = request.get("recovery", {})
    _require(isinstance(recovery, dict) and recovery.get("task_uuid") == task_id,
             "Rodin recovery must bind this exact generation UUID.", "RECOVERY_REQUIRED")
    subscription = recovery.get("subscription_key")
    _require(isinstance(subscription, str) and bool(subscription.strip()) and len(subscription) <= 4096 and
             not any(ord(c) < 32 for c in subscription), "Restore the original Rodin jobs.subscription_key; never regenerate.",
             "RECOVERY_REQUIRED", task_id=task_id, recovery=recovery)
    return task_id, recovery


def _status(client, request):
    task_id, recovery = _recovery(request)
    data = _body(client.request("POST", "/api/v2/status", payload={"subscription_key": recovery["subscription_key"]}))
    jobs = data.get("jobs")
    _require(isinstance(jobs, list) and jobs and all(isinstance(job, dict) and isinstance(job.get("status"), str) and job["status"] in
             {"Waiting", "Generating", "Done", "Failed"} and isinstance(job.get("uuid"), str) for job in jobs),
             "Rodin status lacks a complete valid job list.", "RESPONSE_INVALID")
    uuids = [job["uuid"] for job in jobs]
    _require(len(uuids) == len(set(uuids)), "Rodin status contains duplicate jobs.", "RESPONSE_INVALID")
    expected = recovery.get("job_uuids", [])
    _require(isinstance(expected, list) and all(isinstance(v, str) and v for v in expected),
             "Rodin recovery job identifiers are invalid.", "RECOVERY_REQUIRED")
    _require(not expected or set(expected) <= set(uuids), "Rodin status omits submitted jobs; keep polling this task.", "RESPONSE_INCOMPLETE")
    state = "failed" if any(job["status"] == "Failed" for job in jobs) else "succeeded" if all(
        job["status"] == "Done" for job in jobs) else "running" if any(job["status"] == "Generating" for job in jobs) else "queued"
    return {"ok": True, "task_id": task_id, "state": state, "job_states": [job["status"] for job in jobs], "poll_after_seconds": 5}


def _submit(client, request):
    parameters, files = validate(request)
    data = _body(client.request("POST", "/api/v2/rodin", payload=_form(parameters), files=files), submitting=True)
    raw_task = data.get("uuid")
    try:
        task_id = _task(raw_task)
    except _Invalid:
        raise _Invalid("SUBMISSION_UNKNOWN", "Rodin submission lacks a valid generation UUID; reconcile before any new submission.", unknown=True) from None
    recovery = {"task_uuid": task_id}
    jobs = data.get("jobs")
    if isinstance(jobs, dict) and isinstance(jobs.get("subscription_key"), str) and jobs["subscription_key"].strip():
        recovery["subscription_key"] = jobs["subscription_key"]
    if isinstance(jobs, dict) and isinstance(jobs.get("uuids"), list) and jobs["uuids"] and all(
            isinstance(v, str) and v for v in jobs["uuids"]):
        recovery["job_uuids"] = jobs["uuids"]
    result = {"ok": True, "task_id": task_id, "provider_task_id": task_id,
              "state": "submitted" if recovery.get("subscription_key") else "recovery_required", "recovery": recovery}
    if "consumed" in data:
        try:
            consumed = Decimal(str(data["consumed"]))
            _require(consumed.is_finite() and consumed >= 0 and type(data["consumed"]) is not bool,
                     "Invalid Rodin consumed credits.", "BILLING_INVALID", task_id=task_id, recovery=recovery)
            result["actual_credits"] = str(consumed)
        except (InvalidOperation, TypeError, ValueError):
            result["billing_state"] = "needs_reconciliation"
    return result


def _fetch(client, request):
    checked = _status(client, request)
    _require(checked["state"] == "succeeded", "Rodin files are available only after every job is Done.", "TASK_NOT_READY")
    task_id = checked["task_id"]
    data = _body(client.request("POST", "/api/v2/download", payload={"task_uuid": task_id}))
    items = data.get("list")
    _require(isinstance(items, list) and items, "Rodin download list is empty; recover this task only.", "RESPONSE_INCOMPLETE")
    names, urls = set(), set()
    for item in items:
        _require(isinstance(item, dict) and isinstance(item.get("name"), str) and item["name"] not in {"", ".", ".."}
                 and Path(item["name"]).name == item["name"] and "\\" not in item["name"]
                 and not any(ord(c) < 32 for c in item["name"]), "Unsafe Rodin artifact name.", "ARTIFACT_INVALID")
        _require(item["name"] not in names and isinstance(item.get("url"), str) and item["url"] not in urls,
                 "Duplicate or invalid Rodin artifact.", "ARTIFACT_INVALID")
        names.add(item["name"]); urls.add(item["url"])
    _require(any(Path(name).suffix.lower() in MODELS for name in names), "Rodin returned no model artifact.", "ARTIFACT_INVALID")
    output = Path(request.get("output_dir", ""))
    _require(output.is_absolute(), "Fetch requires an absolute job output directory.")
    output = output_owner(output, PROVIDER, task_id)
    artifacts = []
    for item in items:
        result = client.download(item["url"], output, item["name"])
        _require(isinstance(result, dict) and isinstance(result.get("path"), str) and
                 Path(result["path"]).resolve() == (output / item["name"]).resolve() and
                 not Path(result["path"]).is_symlink(), "Rodin download is outside this job's exact output.", "ARTIFACT_INVALID")
        _require(result.get("sha256") == file_hash(result["path"]), "Rodin artifact hash mismatch.", "ARTIFACT_INVALID")
        result["validation"] = validate_artifact(result["path"], require_geometry=Path(item["name"]).suffix.lower() == ".glb")
        result["container"] = Path(item["name"]).suffix.lower() in {".zip", ".usdz"}
        artifacts.append(result)
    return {"ok": True, "task_id": task_id, "state": "succeeded", "artifacts": artifacts,
            "validation": "file-integrity-only; native material/scale/rig checks still required"}


def _dispatch(method, request, client=None):
    envelope = {"provider": PROVIDER, "method": method}
    try:
        if method == "capabilities":
            return dict(envelope, ok=True, operations=list(OPERATIONS), model_versions=sorted(TIERS), checked_at=CHECKED_AT,
                        connection_operation="GET /api/v2/check_balance", required_env=["RODIN_API_KEY"],
                        configured=bool(os.environ.get("RODIN_API_KEY", "").strip()), connection_verified=False, live_verified=False,
                        limitations=["No rigging/animation adapter; T/A pose conditioning does not produce a rig.",
                                     "Recovery needs both generation UUID and private jobs.subscription_key."])
        if method == "validate":
            parameters, files = validate(request)
            return dict(envelope, ok=True, operation=request["operation"], model_version=request["model_version"],
                        parameters=parameters, input_count=len(files))
        if method == "quote":
            parameters, _ = validate(request)
            credits = Decimal("0.5")
            if parameters["tier"] == "Gen-2.5-Extreme-High": credits += Decimal("0.5")
            if parameters.get("texture_mode") == "extreme-high": credits += Decimal("2.0")
            return dict(envelope, ok=True, kind="rate_card_estimate", unit_credits=str(credits), quantity=1, network_calls=0,
                        source={"url": "https://docs.hyper3d.ai/en/api-specification/rodin-gen2-5" if
                                parameters["tier"].startswith("Gen-2.5-") else
                                "https://docs.hyper3d.ai/en/api-specification/rodin-gen2" if parameters["tier"] == "Gen-2" else
                                "https://docs.hyper3d.ai/en/api-specification/rodin-gen1-1-5", "checked_at": CHECKED_AT + "T00:00:00Z"},
                        note="Local official-rate estimate; no provider quote call or money conversion.")
        _require(method in {"account", "connection", "submit", "status", "fetch"}, "Unsupported Rodin adapter method.")
        if method == "submit": validate(request)  # Reject locally before requesting credentials.
        api = client or _client(request)
        if method in {"account", "connection"}:
            data = _body(api.request("GET", "/api/v2/check_balance"))
            balance = data.get("balance")
            _require(type(balance) in {int, float} and Decimal(str(balance)).is_finite() and balance >= 0,
                     "Rodin connection response lacks a valid balance.", "RESPONSE_INVALID")
            return dict(envelope, ok=True, connection_verified=True, balance=balance, spending_authorized=False)
        result = _submit(api, request) if method == "submit" else _status(api, request) if method == "status" else _fetch(api, request)
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
        if getattr(exc, "recovery", None): result["recovery"] = exc.recovery
        return result


def dispatch(method, request, client=None):
    request = account_profiles.bind_request(PROVIDER, method, request)
    return account_profiles.bind_result(PROVIDER, request, _dispatch(method, request, client))
