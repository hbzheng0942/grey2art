"""Dedicated Tripo v3 adapter. Explicit geometry/rig versions, no implicit paid stages."""
from __future__ import annotations

from .. import account_profiles

import copy
import math
import os
from pathlib import Path
from urllib.parse import urlsplit

from ..provider_http import (ApiClient, ProviderError, bound_file, dependency_task, dependency_model, fingerprint,
    output_owner, public_url, read_bound_file, require, safe_id, validate_artifact)

PROVIDER = "tripo"
ENV = "TRIPO_API_KEY"
BASE = "https://openapi.tripo3d.ai/v3"
ENDPOINTS = {"text_to_3d": "/generation/text-to-model", "image_to_3d": "/generation/image-to-model",
    "multiview_to_3d": "/generation/multiview-to-model", "rig": "/animations/rig", "animation": "/animations/retarget",
    "retarget": "/animations/retarget", "rig_check": "/animations/rig-check", "remesh": "/mesh/decimate"}
H_MODELS = {"v2.5-20250123", "v3.0-20250812", "v3.1-20260211"}
P_MODELS = {"P1-20260311", "P2-20260801"}
RIG_MODELS = {"v1.0-20240301", "v2.5-20260210", "v3.0-20260909"}
# Official animations-retarget table, checked 2026-10-21. These are preset
# identifiers, not arbitrary custom motion descriptions or a cross-rig library.
RIG_V1_PRESETS = {"preset:biped:" + name for name in """
afraid agree angry_01 angry_02 angry_03 basketball_shot bow box_01 box_02 box_03
cast_a_spell cheer chop clap climb complain_01 complain_02 cross_body_crunch
crossover_dribble cry dance_01 dance_02 dance_03 dance_04 dance_05 dance_06
defeat_02 defeat_03 depressed dig dive dribble fall fire flee_01 flee_02 flip fold_arms
football_catch football_save football_pass freaky frightened front_kick_01
front_kick_02 frustrated_01 frustrated_02 golf greet_01 greet_02 greet_03 greet_04
heart_pose hit_to_body_01 hit_to_body_02 hit_to_head hit_to_side hit_to_stomach
hug hurt idle jump_down jump jump_rope_01 jump_rope_02 laugh_01 laugh_02
lift_heavy look_around make_a_call_01 make_a_call_02 pitch_baseball play_mobile_game
play_video_game press-up run_upstairs run scared_01 scared_02 scratch shoot shovel
sing_01 sing_02 sing_03 sing_04 sit slash sob standing_relax surf swagger swim turn
victory_celebration volleyball wait walk warm_up wave_goodbye_01 wave_goodbye_02
""".split()}
RIG_CURRENT_PRESETS = {
    "biped": {"preset:" + name for name in "idle walk run dive climb jump slash shoot hurt fall turn".split()},
    "quadruped": {"preset:quadruped:walk"}, "hexapod": {"preset:hexapod:walk"},
    "octopod": {"preset:octopod:walk"}, "serpentine": {"preset:serpentine:march"},
    "aquatic": {"preset:aquatic:march"}, "avian": set(), "others": set(),
}
COMMON = {"model", "face_limit", "texture", "pbr", "texture_seed", "texture_quality", "texture_version", "delight",
    "model_seed", "auto_size", "quad", "export_orientation", "export_uv"}
H_EXTRA = {"geometry_quality", "smart_low_poly", "generate_parts", "compress"}
BOOLS = {"texture", "pbr", "delight", "auto_size", "quad", "export_uv", "enable_image_autofix", "smart_low_poly",
         "generate_parts", "bake", "smart_uv", "export_with_geometry", "animate_in_place"}


def _client(document=None):
    config = account_profiles.client_config(PROVIDER, document)
    return ApiClient(config["base_url"], config["allowed_hosts"], config["credential_envs"][0],
                     credential_provider=lambda: account_profiles.credential(PROVIDER, document))


def _number(value, minimum, maximum, label):
    require(type(value) is int and minimum <= value <= maximum, label + " is outside its documented range")


def _source(value, allow_task=True):
    require(isinstance(value, str) and value, "Tripo input source is required")
    if value.startswith("https://"):
        public_url(value, resolve=False)
    else:
        safe_id(value)
        # The multiview docs also show UUID-shaped upload tokens.
        require(allow_task or not value.startswith("task_"), "Tripo view input cannot be an individual task reference")
    return value


def _local(document, reference, model=False):
    suffixes = {".glb", ".gltf", ".fbx", ".obj", ".stl"} if model else {".png", ".jpg", ".jpeg"}
    path, content = read_bound_file(document, reference, suffixes, (150 if model else 20) * 1024 * 1024)
    validate_artifact(path, require_geometry=model)
    import hashlib
    return {"_bound_upload": str(path), "_sha256": hashlib.sha256(content).hexdigest()}



def _source_fingerprint(source):
    """Match rig-check to the exact provider reference or uploaded model bytes."""
    if isinstance(source, dict) and set(source) == {"_bound_upload", "_sha256"}:
        identity = {"kind": "model-bytes", "sha256": source["_sha256"]}
    else:
        require(isinstance(source, str) and source, "Tripo model source cannot be bound")
        identity = {"kind": "provider-reference", "provider": PROVIDER, "input": source}
    return fingerprint(identity)


def _rig_context(document, payload, explicit, input_from):
    """Bind preset compatibility to the actual rig task; never infer a version."""
    contexts = []
    if input_from is not None:
        dependency = document.get("dependencies", {}).get(input_from, {})
        contexts = [item["rig_context"] for item in dependency.get("artifacts", [])
                    if isinstance(item, dict) and "rig_context" in item]
    if explicit is not None:
        contexts.append(explicit)
    require(contexts, "Tripo retarget needs rig_context from the rig result or its recorded accepted request")
    context = contexts[0]
    require(isinstance(context, dict) and set(context) == {"task_id", "model_version", "rig_type"},
            "Tripo rig_context needs exact task_id, model_version and rig_type")
    require(all(item == context for item in contexts), "Tripo rig context conflicts with the source task")
    require(context["task_id"] == payload["input"], "Tripo rig context belongs to another task")
    model, rig_type = context["model_version"], context["rig_type"]
    require(isinstance(model, str) and model in RIG_MODELS and isinstance(rig_type, str)
            and rig_type in RIG_CURRENT_PRESETS, "Tripo rig context has an unsupported version or type")
    require(model != "v1.0-20240301" or rig_type == "biped", "Tripo rig v1 supports biped only")
    require(rig_type != "others" or model == "v3.0-20260909", "Tripo others rig requires v3.0")
    return RIG_V1_PRESETS if model == "v1.0-20240301" else RIG_CURRENT_PRESETS[rig_type]


def build_payload(document):
    require(isinstance(document, dict), "Tripo request must be an object")
    operation = document.get("operation")
    require(operation in ENDPOINTS, "Tripo operation is not implemented")
    parameters = document.get("parameters", {})
    require(isinstance(parameters, dict), "Tripo parameters must be an object")
    payload = copy.deepcopy(parameters)
    rig_context = payload.pop("rig_context", None)
    require(rig_context is None or operation in {"animation", "retarget"}, "rig_context applies only to Tripo retarget")
    input_from = payload.get("input_from")
    require("input" not in payload or isinstance(payload["input"], str), "Tripo input must be a URL/token or use the bound local input fields")
    if "inputs" in payload:
        require(isinstance(payload["inputs"], list) and all(isinstance(row, str) or isinstance(row, dict) and all(isinstance(value, str) for value in row.values()) for row in payload["inputs"]), "Tripo view sources must be URL/token strings or use image_paths")
    rig_check_from = payload.pop("rig_check_from", None)
    require(rig_check_from is None or operation == "rig", "Rig compatibility dependency applies only to rigging")
    if "model_from" in payload:
        require("model_path" not in payload and "input" not in payload, "Choose one Tripo model dependency route")
        payload["model_path"] = dependency_model(document, payload.pop("model_from"), {".glb", ".gltf", ".fbx", ".obj", ".stl"})
    for local, model in (("image_path", False), ("model_path", True)):
        if local in payload:
            require("input" not in payload, "Choose one Tripo local or remote source")
            payload["input"] = _local(document, payload.pop(local), model)
    if "input_from" in payload:
        require("input" not in payload, "Choose one Tripo task dependency source")
        payload["input"] = dependency_task(document, payload.pop("input_from"), PROVIDER)
    if "image_paths" in payload:
        require("inputs" not in payload and isinstance(payload["image_paths"], list), "Choose one Tripo multiview route")
        rows = payload.pop("image_paths")
        payload["inputs"] = []
        for row in rows:
            require(isinstance(row, dict) and len(row) == 1, "Local Tripo multiview inputs require named views")
            view, reference = next(iter(row.items()))
            require(view in {"front", "left", "back", "right"}, "Unknown Tripo view name")
            payload["inputs"].append({view: _local(document, reference)})
    if operation in {"text_to_3d", "image_to_3d", "multiview_to_3d"}:
        model = document.get("model_version")
        require(model in H_MODELS | P_MODELS and payload.get("model", model) == model, "Tripo needs an explicit supported geometry version")
        payload["model"] = model
        allowed = COMMON | (H_EXTRA if model in H_MODELS else set())
        if operation == "text_to_3d":
            allowed |= {"prompt", "negative_prompt", "image_seed"}
            require(isinstance(payload.get("prompt"), str) and 1 <= len(payload["prompt"]) <= 1024, "Tripo prompt must contain 1 to 1024 characters")
            require("negative_prompt" not in payload or isinstance(payload["negative_prompt"], str) and len(payload["negative_prompt"]) <= 255, "Tripo negative prompt exceeds its limit")
        elif operation == "image_to_3d":
            allowed |= {"input", "enable_image_autofix", "texture_alignment", "orientation"}
            require("input" in payload, "Tripo image generation needs an image")
        else:
            allowed |= {"inputs", "texture_alignment", "orientation"}
            values = payload.get("inputs")
            require(isinstance(values, list) and values, "Tripo multiview needs explicit views")
            if len(values) == 1 and isinstance(values[0], dict) and set(values[0]) == {"task_id"}:
                safe_id(values[0]["task_id"])
            elif all(isinstance(value, dict) and len(value) == 1 for value in values):
                views = [next(iter(value)) for value in values]
                require(2 <= len(views) <= 4 and len(set(views)) == len(views) and "front" in views and set(views) <= {"front", "left", "back", "right"}, "Tripo multiview needs front plus 1 to 3 unique views")
                for value in values:
                    source = next(iter(value.values()))
                    require(isinstance(source, str) or isinstance(source, dict) and set(source) == {"_bound_upload", "_sha256"}, "Unsupported Tripo nested view reference; use URL, file token or bound local view")
                    if isinstance(source, str):
                        _source(source, allow_task=False)
            else:
                require(len(values) == 4 and all(isinstance(v, str) for v in values) and values[0] and sum(bool(v) for v in values) >= 2,
                        "Tripo positional views need exactly front,left,back,right with front plus another view")
                for value in values:
                    if value:
                        _source(value, allow_task=False)
        if "texture_quality" in payload:
            require(payload["texture_quality"] in {"fast", "standard", "detailed", "extreme"}, "Unsupported Tripo texture quality")
        if "texture_version" in payload:
            require(payload["texture_version"] in {"v2.5-20250123", "v3.0-20250812", "v3.5-20260815"}, "Unsupported Tripo texture model")
        if payload.get("texture_quality") == "fast" or "delight" in payload:
            require(payload.get("texture_version") == "v3.5-20260815", "Tripo fast/delight requires explicit v3.5 texture model")
        if model == "v2.5-20250123":
            require(not set(payload) & {"texture_quality", "geometry_quality", "auto_size", "quad", "smart_low_poly", "generate_parts", "compress"}, "Tripo v2.5 does not support the requested advanced options")
        if model in P_MODELS:
            require(model != "P1-20260311" or "quad" not in payload, "Tripo P1 does not support quad")
        if "geometry_quality" in payload:
            require(payload["geometry_quality"] in {"standard", "detailed"}, "Unsupported Tripo geometry quality")
        if "compress" in payload:
            require(payload["compress"] == "geometry", "Unsupported Tripo compression")
        require(not payload.get("generate_parts") or payload.get("texture") is False and payload.get("pbr") is False
                and not payload.get("quad") and not payload.get("smart_low_poly"), "Tripo parts require untextured triangle generation without smart_low_poly")
        require(not (payload.get("texture") is False and payload.get("pbr", True)), "Tripo pbr would force texture=true; choose the actual intended costed output")
        if "face_limit" in payload:
            if model == "P1-20260311":
                lo, hi = 50, 20000
            elif model == "P2-20260801":
                lo, hi = 48, 25000 if payload.get("quad") else 50000
            elif payload.get("smart_low_poly"):
                lo, hi = 500, 10000 if payload.get("quad") else 20000
            elif payload.get("quad"):
                lo, hi = 1, 150000
            else:
                lo = 1
                hi = 2000000 if payload.get("geometry_quality") == "detailed" else {"v2.5-20250123": 500000, "v3.0-20250812": 1000000, "v3.1-20260211": 1500000}[model]
            _number(payload["face_limit"], lo, hi, "Tripo face_limit")
    elif operation == "rig":
        model = document.get("model_version")
        require(model in RIG_MODELS and payload.get("model", model) == model, "Tripo rig needs an explicit supported rigging model")
        payload["model"] = model
        allowed = {"input", "model", "rig_type", "spec", "out_format"}
        rig_type = payload.get("rig_type", "biped")
        if rig_check_from is not None:
            import json
            from ..provider_http import file_hash
            dependency = document.get("dependencies", {}).get(rig_check_from, {})
            reports = [a for a in dependency.get("artifacts", []) if a.get("role") == "rig-check-report"]
            require(dependency.get("state") == "ready" and dependency.get("provider") == PROVIDER and len(reports) == 1,
                    "Tripo rig requires its ready compatibility report")
            report_path = Path(reports[0]["path"])
            require(report_path.is_file() and file_hash(report_path) == reports[0].get("sha256"), "Tripo compatibility report changed")
            try:
                report = json.loads(report_path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                raise ProviderError("Tripo compatibility report is invalid") from None
            require(report.get("provider") == PROVIDER and report.get("task_id") == dependency.get("task_id"), "Tripo compatibility report task mismatch")
            require(report.get("source_digest") == _source_fingerprint(payload.get("input")),
                    "Tripo compatibility report belongs to another model source")
            compatibility = report.get("output", {})
            require(compatibility.get("riggable") is True and compatibility.get("rig_type") == rig_type,
                    "Tripo rig check rejected this model or recommended a different rig type; revise the approved route")
        require(rig_type in {"biped", "quadruped", "hexapod", "octopod", "avian", "serpentine", "aquatic", "others"}, "Unsupported Tripo rig type")
        require(model != "v1.0-20240301" or rig_type == "biped", "Tripo rig v1 supports biped only")
        require(rig_type != "others" or model == "v3.0-20260909", "Tripo others rig requires v3.0")
        spec = payload.get("spec", "tripo")
        require(spec in {"tripo", "mixamo", "actorcore", "unity", "unreal", "vrm"}, "Unsupported Tripo skeleton convention")
        require(spec in {"tripo", "mixamo"} or model == "v3.0-20260909", "This Tripo skeleton convention requires rig v3.0")
        require("spec" not in payload or rig_type == "biped", "Tripo skeleton conventions only apply to biped")
    elif operation in {"animation", "retarget"}:
        require(document.get("model_version") == "retarget-v3", "Tripo animation must pin retarget-v3 API operation")
        allowed = {"input", "animation", "animations", "out_format", "export_with_geometry", "animate_in_place"}
        require(sum(k in payload for k in ("animation", "animations")) == 1, "Choose one Tripo animation or animation list")
        values = payload.get("animations", [payload.get("animation")])
        require(isinstance(values, list) and 1 <= len(values) <= 5
                and all(isinstance(v, str) for v in values) and len(set(values)) == len(values),
                "Tripo animation needs 1 to 5 unique preset identifiers")
        require(len(values) <= 1 or payload.get("out_format", "glb") == "glb", "Batch Tripo animation requires GLB for clip completeness verification; FBX batches need an additional native validator")
        require(isinstance(payload.get("input"), str) and payload["input"].startswith("task_"), "Tripo retarget requires a completed rig task ID")
        allowed_presets = _rig_context(document, payload, rig_context, input_from)
        require(set(values) <= allowed_presets,
                "Tripo preset is not documented for this rig version/type; choose supported motion or an explicit custom-motion route")
    elif operation == "rig_check":
        require(document.get("model_version") == "rig-check-v3", "Tripo rig check must pin rig-check-v3 API operation")
        allowed = {"input"}
    else:
        model = document.get("model_version")
        require(model in {"v1.0", "v2.0", "v3.0"} and payload.get("model", model) == model, "Tripo remesh needs explicit algorithm version")
        payload["model"] = model
        allowed = {"input", "model", "face_limit", "quad", "smart_uv", "bake", "part_names"}
        require("smart_uv" not in payload or model == "v3.0", "Tripo smart_uv requires remesh v3.0")
        require(model != "v1.0" or not set(payload) & {"bake", "part_names"}, "Tripo remesh v1 rejects bake and part_names")
        require(model != "v1.0" or "face_limit" in payload, "Tripo remesh v1 needs face_limit")
        if "face_limit" in payload:
            lo = 1 if model == "v1.0" else 500
            hi = (150000 if payload.get("quad") else 2000000) if model == "v1.0" else (10000 if payload.get("quad") else 20000)
            _number(payload["face_limit"], lo, hi, "Tripo retopology face_limit")
        if "part_names" in payload:
            require(isinstance(payload["part_names"], list) and payload["part_names"] and all(isinstance(x, str) and x for x in payload["part_names"]), "Tripo part_names must be an explicit list")
    require(set(payload) <= allowed, "Tripo parameters include unsupported or deprecated fields")
    if operation != "text_to_3d" and operation != "multiview_to_3d":
        require("input" in payload, "Tripo operation needs an explicit source")
    for key in BOOLS & set(payload):
        require(type(payload[key]) is bool, "Tripo boolean parameter has an invalid type")
    if "input" in payload and not isinstance(payload["input"], dict):
        _source(payload["input"])
    if "out_format" in payload:
        require(payload["out_format"] in {"glb", "fbx"}, "Unsupported Tripo output format")
    if "texture_alignment" in payload:
        require(payload["texture_alignment"] in {"original_image", "geometry"}, "Unsupported Tripo texture alignment")
    if "orientation" in payload:
        require(payload["orientation"] in {"default", "align_image"}, "Unsupported Tripo orientation")
    if "export_orientation" in payload:
        require(payload["export_orientation"] in {"+x", "-x", "+y", "-y"}, "Unsupported Tripo export axis")
        require(not document.get("postprocess_planned"), "Leave Tripo export orientation unset until post-processing completes")
    for key in {"model_seed", "texture_seed", "image_seed"} & set(payload):
        _number(payload[key], 0, 2147483647, "Tripo random seed")
    return ENDPOINTS[operation], payload


def _unwrap(response, submitted=False):
    require(isinstance(response, dict), "Tripo response must be an object")
    if response.get("code") != 0:
        code = response.get("code")
        if type(code) is not int:
            raise ProviderError("Tripo response has no known outcome", unknown_submission=submitted)
        # Explicit vendor business rejection; never disclose its arbitrary message.
        raise ProviderError("Tripo rejected the request", unknown_submission=False, code=code)
    data = response.get("data")
    if not isinstance(data, dict):
        raise ProviderError("Tripo returned no result data", unknown_submission=submitted)
    return data


def _uploads(client, value):
    if isinstance(value, dict) and set(value) == {"_bound_upload", "_sha256"}:
        import hashlib
        import mimetypes
        path = Path(value["_bound_upload"])
        content = path.read_bytes()
        require(hashlib.sha256(content).hexdigest() == value["_sha256"], "Tripo local input changed after validation")
        data = _unwrap(client.request("POST", "/files", files={"file": (path.name, content, mimetypes.guess_type(path.name)[0] or "application/octet-stream")}))
        return safe_id(data.get("file_token"))
    if isinstance(value, dict):
        return {key: _uploads(client, child) for key, child in value.items()}
    if isinstance(value, list):
        return [_uploads(client, child) for child in value]
    return value


def _context(document):
    accepted = document.get("accepted_request") or document
    operation = accepted.get("operation")
    require(operation in ENDPOINTS, "Tripo recovery requires its exact accepted operation")
    task_id = safe_id(document.get("task_id"))
    recovery = document.get("recovery", {})
    require(not recovery or recovery.get("provider") == PROVIDER and recovery.get("task_id") == task_id
            and recovery.get("operation") == operation, "Tripo recovery binding mismatch")
    return accepted, operation, task_id


def _task(client, task_id):
    data = _unwrap(client.request("GET", "/tasks/" + task_id))
    require(data.get("task_id") == task_id, "Tripo returned another task's data")
    state = {"queued": "queued", "running": "running", "success": "succeeded", "failed": "failed", "banned": "failed", "expired": "failed", "cancelled": "cancelled"}.get(data.get("status"))
    require(state is not None, "Tripo returned an unknown task state")
    return data, state


def _fetch(client, data, document, operation, task_id, accepted):
    output = data.get("output")
    require(isinstance(output, dict), "Tripo completed without its output object")
    folder = output_owner(document["output_dir"], PROVIDER, task_id)
    parameters = accepted.get("parameters", {})
    if operation == "rig_check":
        # A report is data, never an alleged geometry artifact.
        require(type(output.get("riggable")) is bool and isinstance(output.get("rig_type"), str), "Tripo rig check returned no compatibility result")
        report = folder / (task_id + "-rig-check.json")
        import json
        from ..provider_http import file_hash
        source_digest = document.get("recovery", {}).get("source_digest")
        if source_digest is None:
            # Direct recovery of a public/provider reference remains possible. Local
            # uploads must retain the source digest returned at submission time.
            source = accepted.get("parameters", {}).get("input")
            require(isinstance(source, str) and source, "Tripo local rig-check recovery needs its original source digest")
            source_digest = _source_fingerprint(source)
        require(isinstance(source_digest, str) and len(source_digest) == 64 and all(c in "0123456789abcdef" for c in source_digest), "Tripo rig-check source digest is invalid")
        encoded = json.dumps({"provider": PROVIDER, "task_id": task_id, "source_digest": source_digest,
                              "output": {"riggable": output["riggable"], "rig_type": output["rig_type"]}}, sort_keys=True, allow_nan=False)
        if report.exists():
            require(report.read_text(encoding="utf-8") == encoded, "Existing Tripo rig report differs")
        else:
            with report.open("x", encoding="utf-8") as file:
                file.write(encoded)
        return [{"path": str(report), "sha256": file_hash(report), "bytes": report.stat().st_size, "role": "rig-check-report"}]
    candidates = []
    if output.get("model_url"):
        candidates.append(("model", output["model_url"]))
    # Some tasks return several output formats or segmented model files.
    if output.get("model_urls"):
        require(isinstance(output["model_urls"], dict), "Tripo model_urls must be keyed formats")
        for key, url in output["model_urls"].items():
            require(key in {"glb", "fbx", "obj", "stl", "gltf"} and isinstance(url, str) and url, "Invalid Tripo model format result")
            candidates.append(("model-" + key, url))
    parts = output.get("parts", [])
    require(isinstance(parts, list), "Tripo part output must be a list")
    for index, part in enumerate(parts):
        require(isinstance(part, dict) and isinstance(part.get("model_url"), str) and part["model_url"], "Tripo part output has no model URL")
        candidates.append(("part-" + str(index), part["model_url"]))
    require(candidates, "Tripo completed without model artifacts")
    expected = parameters.get("out_format")
    if expected is None and parameters.get("quad"):
        # H-series explicitly forces FBX; P2 docs only promise quad topology.
        if accepted.get("model_version") in H_MODELS:
            expected = "fbx"
    if expected:
        require(any(Path(urlsplit(url).path).suffix.lower() == "." + expected for _, url in candidates), "Tripo did not return the requested output format")
    artifacts = []
    seen = set()
    for label, url in candidates:
        require(isinstance(url, str), "Tripo artifact URL must be a string")
        if url in seen:
            continue
        seen.add(url)
        suffix = Path(urlsplit(url).path).suffix.lower()
        require(suffix in {".glb", ".fbx", ".obj", ".stl", ".gltf", ".zip"}, "Tripo returned an unsupported model artifact format")
        artifact = client.download(url, folder, task_id + "-" + label + suffix)
        artifact["validation"] = validate_artifact(artifact["path"], require_geometry=parameters.get("export_with_geometry", True),
            require_rig=operation == "rig", require_animation=operation in {"animation", "retarget"},
            min_animations=len(parameters.get("animations", [])))
        artifact["role"] = label
        if operation == "rig":
            artifact["rig_context"] = {"task_id": task_id, "model_version": accepted["model_version"],
                                       "rig_type": parameters.get("rig_type", "biped")}
        artifacts.append(artifact)
    return artifacts


def _dispatch(method, document, client=None):
    require(method in {"capabilities", "validate", "account", "submit", "status", "fetch"}, "Unsupported Tripo adapter method")
    result = {"provider": PROVIDER, "method": method, "ok": True}
    if method == "capabilities":
        return dict(result, operations=list(ENDPOINTS), required_env=[ENV], configured=bool(os.environ.get(ENV, "").strip()),
                    installed=True, documented=True, connection_verified=False, operations_verified=[],
                    models={"geometry": sorted(H_MODELS | P_MODELS), "rig": sorted(RIG_MODELS), "remesh": ["v1.0", "v2.0", "v3.0"]},
                    source="https://developers.tripo3d.ai/en/docs", checked_at="2026-10-20", quote="local sourced rate-card estimates; no generation needed", animation_scope="animation/retarget apply documented Tripo presets to a completed Tripo rig task; arbitrary uploaded motion clips are not implemented")
    if method == "validate":
        endpoint, payload = build_payload(document)
        return dict(result, operation=document["operation"], model_version=document.get("model_version"), endpoint=endpoint,
                    request_digest=fingerprint({"operation": document["operation"], "model_version": document.get("model_version"), "parameters": document.get("parameters", {})}))
    client = client or _client(document)
    if method == "account":
        account = _unwrap(client.request("GET", "/account/balance"))
        require(type(account.get("balance")) in (int, float) and math.isfinite(account["balance"]), "Tripo account response has no numeric balance")
        return dict(result, connection_verified=True, account_read="succeeded", balance_credits=account["balance"])
    if method == "submit":
        endpoint, payload = build_payload(document)
        source_digest = _source_fingerprint(payload["input"]) if document["operation"] == "rig_check" else None
        payload = _uploads(client, payload)
        response = _unwrap(client.request("POST", endpoint, payload), submitted=True)
        try:
            task_id = safe_id(response.get("task_id"))
        except ProviderError:
            raise ProviderError("Tripo submission has no usable task ID; reconcile original task", unknown_submission=True) from None
        recovery = {"provider": PROVIDER, "task_id": task_id, "operation": document["operation"]}
        if source_digest is not None:
            recovery["source_digest"] = source_digest
        return dict(result, task_id=task_id, provider_task_id=task_id, state="queued", recovery=recovery)
    accepted, operation, task_id = _context(document)
    data, state = _task(client, task_id)
    result.update(task_id=task_id, state=state, provider_state=data.get("status"))
    if data.get("credits_consumed") is not None:
        value = data["credits_consumed"]
        require(type(value) in (int, float) and math.isfinite(value) and value >= 0, "Tripo reported invalid consumed credits")
        result["consumed_credits"] = value
    if method == "fetch":
        require(state == "succeeded", "Tripo task has not succeeded; fetch cannot submit a replacement")
        result["artifacts"] = _fetch(client, data, document, operation, task_id, accepted)
    return result


def dispatch(method, request, client=None):
    request = account_profiles.bind_request(PROVIDER, method, request)
    return account_profiles.bind_result(PROVIDER, request, _dispatch(method, request, client))
