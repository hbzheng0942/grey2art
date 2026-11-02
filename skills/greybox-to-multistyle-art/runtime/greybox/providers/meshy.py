"""Dedicated Meshy REST adapter, pinned to documented API operations (2026-10-20).

Text preview/refine are separate costed operations. No operation is silently
submitted to refine, remesh, rig, or animate a completed task.
"""
from __future__ import annotations

from .. import account_profiles

import base64
import copy
import math
import mimetypes
import os
from pathlib import Path
from urllib.parse import urlsplit

from ..provider_http import (ApiClient, ProviderError, bound_file, dependency_task, dependency_model, fingerprint,
    output_owner, public_url, read_bound_file, require, safe_id, validate_artifact)

PROVIDER = "meshy"
ENV = "MESHY_API_KEY"
BASE = "https://api.meshy.ai"
ENDPOINTS = {"image_to_3d": "/openapi/v1/image-to-3d", "multiview_to_3d": "/openapi/v1/multi-image-to-3d",
    "text_to_3d": "/openapi/v2/text-to-3d", "texture_refine": "/openapi/v2/text-to-3d",
    "rig": "/openapi/v1/rigging", "animation": "/openapi/v1/animations", "remesh": "/openapi/v1/remesh"}
MODELS = {"meshy-6-lite", "meshy-6", "meshy-7.1", "meshy-t2", "meshy-t2.5"}
FORMATS = {"glb", "fbx", "obj", "stl", "usdz", "3mf"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
IMAGE_LIMIT = 20 * 1024 * 1024
COMMON = {"ai_model", "target_formats", "alpha_thumbnail", "auto_size", "origin_at"}
SHAPE = {"model_type", "geometry_resolution", "should_remesh", "topology", "target_polycount", "decimation_mode",
         "save_pre_remeshed_model", "pose_mode", "moderation"}
TEXTURE = {"enable_pbr", "texture_resolution", "texture_prompt", "texture_image_url", "remove_lighting"}
BOOLS = {"alpha_thumbnail", "auto_size", "should_remesh", "save_pre_remeshed_model", "moderation", "enable_pbr",
         "remove_lighting", "should_texture", "image_enhancement", "multi_view_thumbnails"}


def _client(document=None):
    config = account_profiles.client_config(PROVIDER, document)
    return ApiClient(config["base_url"], config["allowed_hosts"], config["credential_envs"][0],
                     credential_provider=lambda: account_profiles.credential(PROVIDER, document))


def _int(value, lo, hi, label):
    require(type(value) is int and lo <= value <= hi, label + " is outside its documented range")


def _uri(value, extensions, limit):
    require(isinstance(value, str) and value, "Supplier input URL is required")
    if value.startswith("data:"):
        try:
            header, encoded = value.split(",", 1)
            require(header.endswith(";base64"), "Supplier data URI must be base64")
            data = base64.b64decode(encoded, validate=True)
        except (ValueError, TypeError):
            raise ProviderError("Invalid supplier data URI") from None
        require(0 < len(data) <= limit, "Supplier data URI exceeds its documented limit")
    else:
        public_url(value, resolve=False)
        suffix = Path(urlsplit(value).path).suffix.lower()
        require(not suffix or suffix in extensions, "Unsupported supplier input URL format")
    return value


def _local_uri(document, reference, image=True, glb_only=False):
    extensions = IMAGE_EXTENSIONS if image else {".glb"} if glb_only else {".glb", ".gltf", ".obj", ".fbx", ".stl"}
    limit = IMAGE_LIMIT if image else 100 * 1024 * 1024
    path, content = read_bound_file(document, reference, extensions, limit)
    validate_artifact(path, require_geometry=not image)
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if not image:
        mime = "application/octet-stream"
    return "data:" + mime + ";base64," + base64.b64encode(content).decode()


def build_payload(document):
    """Validate a frozen approved request before any network request."""
    require(isinstance(document, dict), "Meshy request must be an object")
    operation = document.get("operation")
    require(operation in ENDPOINTS, "Meshy operation is not implemented")
    parameters = document.get("parameters", {})
    require(isinstance(parameters, dict), "Meshy parameters must be an object")
    payload = copy.deepcopy(parameters)
    if "model_from" in payload:
        require("model_path" not in payload and "model_url" not in payload, "Choose one Meshy model dependency route")
        payload["model_path"] = dependency_model(document, payload.pop("model_from"), {".glb"} if operation == "rig" else {".glb", ".gltf", ".fbx", ".obj", ".stl"})
    # Local path/task-dependency conveniences are consumed by this adapter only.
    for local, remote, image in (("image_path", "image_url", True), ("model_path", "model_url", False)):
        if local in payload:
            require(remote not in payload, "Choose exactly one supplier local or remote input")
            payload[remote] = _local_uri(document, payload.pop(local), image, glb_only=operation == "rig")
    if "image_paths" in payload:
        require("image_urls" not in payload and isinstance(payload["image_paths"], list), "Choose one multiview input route")
        payload["image_urls"] = [_local_uri(document, p) for p in payload.pop("image_paths")]
    for local, remote in (("input_task_from", "input_task_id"), ("preview_task_from", "preview_task_id"), ("rig_task_from", "rig_task_id")):
        if local in payload:
            require(remote not in payload, "Choose one task dependency route")
            payload[remote] = dependency_task(document, payload.pop(local), PROVIDER)
    if operation in {"image_to_3d", "multiview_to_3d", "text_to_3d", "texture_refine"}:
        model = document.get("model_version")
        require(model in MODELS and payload.get("ai_model", model) == model, "Meshy requires an explicit supported model version")
        payload["ai_model"] = model
        if operation in {"multiview_to_3d", "texture_refine"}:
            require(model not in {"meshy-t2", "meshy-t2.5"}, "This Meshy endpoint does not accept an explicit Smart Topology model")
    if operation == "image_to_3d":
        allowed = COMMON | SHAPE | TEXTURE | {"image_url", "input_task_id", "should_texture", "image_enhancement", "multi_view_thumbnails"}
        require(("image_url" in payload) != ("input_task_id" in payload), "Meshy image generation needs exactly one image or source task")
    elif operation == "multiview_to_3d":
        allowed = COMMON | (SHAPE - {"model_type"}) | TEXTURE | {"image_urls", "input_task_id", "should_texture", "image_enhancement", "multi_view_thumbnails"}
        require(("image_urls" in payload) != ("input_task_id" in payload), "Meshy multiview needs exactly one image list or source task")
        if "image_urls" in payload:
            require(isinstance(payload["image_urls"], list) and 1 <= len(payload["image_urls"]) <= 4, "Meshy supports 1 to 4 multiview images")
            for value in payload["image_urls"]:
                _uri(value, IMAGE_EXTENSIONS, IMAGE_LIMIT)
        require(payload.get("geometry_resolution", "standard") in {"standard", "2k"}, "Meshy multiview does not support 4k geometry")
    elif operation == "text_to_3d":
        allowed = COMMON | SHAPE | {"prompt", "mode"}
        require(payload.get("mode", "preview") == "preview", "Text preview and texture_refine must be separately approved operations")
        payload["mode"] = "preview"
        require(isinstance(payload.get("prompt"), str) and 1 <= len(payload["prompt"]) <= 800, "Meshy prompt must contain 1 to 800 characters")
    elif operation == "texture_refine":
        allowed = COMMON | TEXTURE | {"mode", "preview_task_id", "moderation"}
        require(payload.get("mode", "refine") == "refine", "Meshy texture_refine requires refine mode")
        payload["mode"] = "refine"
        safe_id(payload.get("preview_task_id"))
    elif operation == "rig":
        require(document.get("model_version") == "rigging-v1", "Meshy rig must pin rigging-v1 API operation")
        allowed = {"input_task_id", "model_url", "height_meters", "texture_image_url"}
        require(("input_task_id" in payload) != ("model_url" in payload), "Meshy rig needs exactly one source task or GLB")
        if "height_meters" in payload:
            value = payload["height_meters"]
            require(type(value) in (int, float) and math.isfinite(value) and value > 0, "Meshy rig height must be a positive finite number")
        if "model_url" in payload:
            _uri(payload["model_url"], {".glb"}, 100 * 1024 * 1024)
    elif operation == "animation":
        require(document.get("model_version") == "animations-v1", "Meshy animation must pin animations-v1 API operation")
        allowed = {"rig_task_id", "action_id", "action_ids", "motion_task_id", "post_process"}
        safe_id(payload.get("rig_task_id"))
        require(sum(k in payload for k in ("action_id", "action_ids", "motion_task_id")) == 1, "Meshy animation needs exactly one motion source")
        if "action_id" in payload:
            _int(payload["action_id"], 0, 2147483647, "Meshy action ID")
        if "action_ids" in payload:
            values = payload["action_ids"]
            require(isinstance(values, list) and 1 <= len(values) <= 10 and len(set(values)) == len(values), "Meshy needs 1 to 10 unique animation action IDs")
            for value in values:
                _int(value, 0, 2147483647, "Meshy action ID")
        if "motion_task_id" in payload:
            safe_id(payload["motion_task_id"])
        if "post_process" in payload:
            post = payload["post_process"]
            require(isinstance(post, dict) and set(post) <= {"operation_type", "fps"}, "Invalid Meshy animation post-process")
            require(post.get("operation_type") in {"change_fps", "fbx2usdz", "extract_armature"}, "Unsupported Meshy animation post-process")
            require("fps" not in post or post.get("operation_type") == "change_fps" and post["fps"] in {24, 25, 30, 60}, "Invalid Meshy animation FPS")
    else:
        require(document.get("model_version") == "remesh-v1", "Meshy remesh must pin remesh-v1 API operation")
        allowed = {"input_task_id", "model_url", "target_formats", "topology", "target_polycount", "decimation_mode", "alpha_thumbnail"}
        require(("input_task_id" in payload) != ("model_url" in payload), "Meshy remesh needs exactly one model or source task")
        if "model_url" in payload:
            _uri(payload["model_url"], {".glb", ".gltf", ".obj", ".fbx", ".stl"}, 100 * 1024 * 1024)
    require(set(payload) <= allowed, "Meshy parameters include unsupported or deprecated fields")
    for key in BOOLS & set(payload):
        require(type(payload[key]) is bool, "Meshy boolean parameter has an invalid type")
    for key in ("image_url", "texture_image_url"):
        if key in payload:
            _uri(payload[key], IMAGE_EXTENSIONS, IMAGE_LIMIT)
    for key in ("input_task_id", "preview_task_id", "rig_task_id"):
        if key in payload:
            safe_id(payload[key])
    if "target_formats" in payload:
        formats = payload["target_formats"]
        require(isinstance(formats, list) and formats and all(f in FORMATS for f in formats) and len(set(formats)) == len(formats), "Unsupported Meshy output formats")
    if "topology" in payload:
        require(payload["topology"] in {"triangle", "quad"}, "Unsupported Meshy topology")
    if "target_polycount" in payload:
        upper = 15000 if payload.get("ai_model") == "meshy-t2" else 30000 if payload.get("ai_model") == "meshy-t2.5" else 300000
        _int(payload["target_polycount"], 100, upper, "Meshy target_polycount")
    if "decimation_mode" in payload:
        _int(payload["decimation_mode"], 1, 4, "Meshy decimation_mode")
        require("target_polycount" not in payload, "Choose Meshy adaptive decimation or target_polycount explicitly")
    if "geometry_resolution" in payload:
        require(payload["geometry_resolution"] in {"standard", "2k", "4k"}, "Unsupported Meshy geometry resolution")
        require(payload.get("ai_model") == "meshy-7.1", "Meshy geometry_resolution requires meshy-7.1")
    if payload.get("ai_model") in {"meshy-t2", "meshy-t2.5"}:
        require(payload.get("model_type") == "smart-topology" and payload.get("topology", "triangle") == "triangle", "Meshy Smart Topology requires smart-topology and triangle output")
        require(not set(payload) & {"should_remesh", "save_pre_remeshed_model", "decimation_mode", "image_enhancement", "remove_lighting"}, "Meshy Smart Topology rejects or ignores these parameters")
    elif "model_type" in payload:
        require(payload["model_type"] == "standard", "Meshy standard models require standard model_type; retired lowpoly is disabled")
    if payload.get("ai_model") == "meshy-6-lite":
        require(not set(payload) & {"image_enhancement", "remove_lighting"} and payload.get("texture_resolution", "2k") == "2k", "Meshy 6 Lite does not support requested image/texture options")
    if "texture_resolution" in payload:
        require(payload["texture_resolution"] in {"2k", "4k", "8k"}, "Unsupported Meshy texture resolution")
    if "pose_mode" in payload:
        require(payload["pose_mode"] in {"", "a-pose", "t-pose"}, "Unsupported Meshy pose mode")
    if "origin_at" in payload:
        require(payload["origin_at"] in {"bottom", "center"} and payload.get("auto_size") is True, "Meshy origin_at requires auto_size")
    require(not payload.get("enable_pbr") or payload.get("should_texture", True), "Meshy PBR requires textured output")
    require(not ("texture_prompt" in payload and "texture_image_url" in payload), "Choose one Meshy texture reference route")
    if "texture_prompt" in payload:
        require(isinstance(payload["texture_prompt"], str) and 1 <= len(payload["texture_prompt"]) <= 800, "Meshy texture prompt exceeds its limit")
    return ENDPOINTS[operation], payload


def _context(document):
    accepted = document.get("accepted_request") or document
    operation = accepted.get("operation")
    require(operation in ENDPOINTS, "Meshy recovery requires its exact accepted operation")
    task_id = safe_id(document.get("task_id"))
    recovery = document.get("recovery", {})
    require(not recovery or recovery.get("provider") == PROVIDER and recovery.get("task_id") == task_id
            and recovery.get("endpoint") == ENDPOINTS[operation], "Meshy recovery binding mismatch")
    return accepted, operation, task_id


def _task(client, operation, task_id):
    response = client.request("GET", ENDPOINTS[operation] + "/" + task_id)
    require(response.get("id") == task_id, "Meshy returned another task's data")
    status = {"PENDING": "queued", "IN_PROGRESS": "running", "SUCCEEDED": "succeeded", "FAILED": "failed", "CANCELED": "cancelled", "CANCELLED": "cancelled"}.get(response.get("status"))
    require(status is not None, "Meshy returned an unknown task state")
    return response, status


def _artifacts(client, response, document, operation, task_id, accepted):
    parameters = accepted.get("parameters", {})
    output = output_owner(document["output_dir"], PROVIDER, task_id)
    candidates = []
    if operation in {"rig", "animation"}:
        result = response.get("result", {})
        require(isinstance(result, dict), "Meshy completed without its result object")
        # Preserve every provided rig/motion format, not just the first GLB.
        def visit(value, label=""):
            if isinstance(value, dict):
                for key, child in value.items():
                    visit(child, (label + "-" + key).strip("-"))
            elif isinstance(value, str) and value and label.endswith("_url"):
                suffix = Path(urlsplit(value).path).suffix.lower()
                require(suffix in {".glb", ".fbx", ".usdz"}, "Meshy returned an unsupported rig/motion artifact format")
                candidates.append((label, value, suffix))
        visit(result)
        required_key = "rigged_character_glb_url" if operation == "rig" else "animation_glb_url"
        if operation == "animation" and len(parameters.get("action_ids", [])) > 1:
            require(any(label == "animation_glb_url" for label, _, _ in candidates), "Multi-action Meshy output requires GLB for clip completeness verification")
        require(any(label == required_key or operation == "animation" and label == "animation_fbx_url" for label, _, _ in candidates), "Meshy completed without its primary rig/animation artifact")
    else:
        models = response.get("model_urls", {})
        require(isinstance(models, dict), "Meshy completed without model outputs")
        formats = parameters.get("target_formats", ["glb"])
        require(all(models.get(fmt) for fmt in formats), "Meshy completed without every requested model format")
        for fmt in formats:
            candidates.append(("model-" + fmt, models[fmt], "." + fmt))
        for index, textures in enumerate(response.get("texture_urls", [])):
            require(isinstance(textures, dict), "Meshy texture output is invalid")
            for semantic, url in textures.items():
                if url:
                    require(semantic in {"base_color", "metallic", "roughness", "normal", "emission"}, "Unknown Meshy texture channel")
                    suffix = Path(urlsplit(url).path).suffix.lower()
                    require(suffix in {".png", ".jpg", ".jpeg", ".webp"}, "Unsupported Meshy texture format")
                    candidates.append(("texture-" + str(index) + "-" + semantic, url, suffix))
    require(candidates, "Meshy completed without downloadable artifacts")
    artifacts = []
    for label, url, suffix in candidates:
        artifact = client.download(url, output, task_id + "-" + label + suffix)
        is_primary = label.startswith("model-") or label.startswith("rigged_character_") or label.startswith("animation_")
        artifact["validation"] = validate_artifact(artifact["path"], require_geometry=is_primary,
            require_rig=operation == "rig" and label.startswith("rigged_character_"),
            require_animation=operation == "animation" and label.startswith("animation_"),
            min_animations=len(parameters.get("action_ids", [])))
        artifact["role"] = label
        artifacts.append(artifact)
    return artifacts


def _dispatch(method, document, client=None):
    require(method in {"capabilities", "validate", "account", "submit", "status", "fetch"}, "Unsupported Meshy adapter method")
    result = {"provider": PROVIDER, "method": method, "ok": True}
    if method == "capabilities":
        return dict(result, operations=list(ENDPOINTS), required_env=[ENV], configured=bool(os.environ.get(ENV, "").strip()),
                    installed=True, documented=True, connection_verified=False, operations_verified=[],
                    source="https://docs.meshy.ai/en/api/image-to-3d", checked_at="2026-10-20", quote="local sourced rate-card estimates; no generation needed")
    if method == "validate":
        endpoint, payload = build_payload(document)
        return dict(result, operation=document["operation"], model_version=document.get("model_version"), endpoint=endpoint,
                    request_digest=fingerprint({"operation": document["operation"], "model_version": document.get("model_version"), "parameters": document.get("parameters", {})}))
    client = client or _client(document)
    if method == "account":
        account = client.request("GET", "/openapi/v1/balance")
        require(type(account.get("balance")) in (int, float) and math.isfinite(account["balance"]), "Meshy account response has no numeric balance")
        return dict(result, connection_verified=True, balance_credits=account["balance"])
    if method == "submit":
        endpoint, payload = build_payload(document)
        response = client.request("POST", endpoint, payload)
        task_id = response.get("result")
        try:
            safe_id(task_id)
        except ProviderError:
            raise ProviderError("Meshy submission did not return a usable task ID; reconcile original task", unknown_submission=True) from None
        recovery = {"provider": PROVIDER, "task_id": task_id, "endpoint": endpoint, "operation": document["operation"]}
        return dict(result, task_id=task_id, provider_task_id=task_id, state="queued", recovery=recovery)
    accepted, operation, task_id = _context(document)
    response, state = _task(client, operation, task_id)
    result.update(task_id=task_id, state=state)
    if response.get("consumed_credits") is not None:
        value = response["consumed_credits"]
        require(type(value) in (int, float) and math.isfinite(value) and value >= 0, "Meshy reported invalid consumed credits")
        result["consumed_credits"] = value
    if method == "fetch":
        require(state == "succeeded", "Meshy task has not succeeded; fetch cannot submit a replacement")
        result["artifacts"] = _artifacts(client, response, document, operation, task_id, accepted)
    return result


def dispatch(method, request, client=None):
    request = account_profiles.bind_request(PROVIDER, method, request)
    return account_profiles.bind_result(PROVIDER, request, _dispatch(method, request, client))
