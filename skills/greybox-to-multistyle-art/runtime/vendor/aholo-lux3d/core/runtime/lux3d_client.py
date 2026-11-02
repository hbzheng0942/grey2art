"""Public Lux3D API client.

The client accepts accessible HTTP(S) URLs. Upload local files with the Asset
upload API before calling a Lux3D task endpoint.
"""

import argparse
import json
import os
import pathlib
import math
import struct
import tempfile
import zipfile
import sys
import time
import urllib.parse

import requests


CN_BASE_URL = "https://api.aholo3d.cn"
INTERNATIONAL_BASE_URL = "https://api.aholo.ai/global"
REGION_BASE_URLS = {
    "cn": CN_BASE_URL,
    "international": INTERNATIONAL_BASE_URL,
}
REGION_API_KEY_ENV = {
    "cn": "LUX3D_CN_API_KEY",
    "international": "LUX3D_GLOBAL_API_KEY",
}
ASSET_UPLOAD_DOCS = {
    "cn": "https://labs.aholo3d.cn/api-docs/api-reference#tag/asset",
    "international": "https://labs.aholo.ai/api-docs/en/api-reference#tag/asset",
}

DEFAULT_REGION = "cn"
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_DELAY = 2
DEFAULT_POLL_ATTEMPTS = 60
DEFAULT_POLL_INTERVAL = 15
DOWNLOAD_CHUNK_SIZE = 1024 * 1024

SUPPORTED_STYLES = {
    "photorealistic",
    "cartoon",
    "anime",
    "hand_painted",
    "cyberpunk",
    "fantasy",
    "glass",
}
GENERATION_VERSIONS = {"G1", "G1-Turbo"}
MATERIAL_VERSION = "v3.0-standard"
GENERATION_FORMATS = {"zip", "glb", "ply"}
MATERIAL_FORMATS = {"zip", "glb", "usdz", "obj_zip", "fbx_zip"}
EXPORT_FORMATS = {"usdz", "obj_zip", "fbx_zip", "stl", "3mf"}
DOWNLOAD_FORMATS = GENERATION_FORMATS | MATERIAL_FORMATS | EXPORT_FORMATS | {"obj"}
ANIMATION_FORMATS = {"glb", "fbx"}
ANIMATION_OUTPUT_MODES = {"separate", "combined"}
with (pathlib.Path(__file__).resolve().parents[1] / "contracts/lux3d-generation.v1.json").open(encoding="utf-8") as _contract_file:
    ANIMATION_IDS = tuple(json.load(_contract_file)["sharedFields"]["animationId"]["values"])
SUPPORTED_TASK_STATUSES = {0, 1, 2, 3, 4, 5, 6}
TASK_LIST_FILTER_STATUSES = {0, 1, 3, 4}
FACE_COUNT_MIN = 10000
FACE_COUNT_MAX = 300000
ARTIFACT_TTL_SECONDS = 2 * 60 * 60
MATERIAL_OUTPUT_SLOTS = ("zip", "glb", "usdz", "obj_zip", "fbx_zip")
EXPORT_OUTPUT_SLOTS = (
    "zip",
    "glb",
    "usdz",
    "obj_zip",
    "fbx_zip",
    "stl",
    "3mf",
)


class ApiBusinessRejection(RuntimeError):
    """A complete API envelope that explicitly rejected the request."""

    def __init__(self, code, message, payload=None):
        self.code = code
        self.payload = payload
        # Provider messages can echo credentials or request data. Keep them only
        # in the diagnostic payload; user-visible errors use trusted local text.
        description = (
            "The account task concurrency limit has been reached"
            if code == "GENERATION_CONCURRENCY_LIMIT_EXCEEDED"
            else "The API rejected this request"
        )
        super().__init__(description)


class ApiProtocolError(RuntimeError):
    """An API response that does not satisfy the documented response contract."""


class TaskQueryError(RuntimeError):
    """A query failure carrying the last provider status observed, if any."""

    def __init__(self, message, last_provider_status=None):
        self.last_provider_status = last_provider_status
        super().__init__(message)


class TaskTerminalError(RuntimeError):
    """A provider failure or cancellation retaining its actual status.

    @author yinjie
    """

    def __init__(self, provider_status, task_data=None):
        self.last_provider_status = provider_status
        self.task_data = task_data
        prefix = "Task was cancelled" if provider_status == 6 else "Task failed"
        super().__init__(f"{prefix}: provider status={provider_status}")


class TaskOutputError(RuntimeError):
    """A succeeded provider task whose output violates the output contract."""

    def __init__(self, message, task_data=None):
        self.last_provider_status = 3
        self.task_data = task_data
        super().__init__(message)


class TaskPollingTimeout(TimeoutError):
    """A polling limit that carries the last provider status observed."""

    def __init__(self, message, last_provider_status=None):
        self.last_provider_status = last_provider_status
        super().__init__(message)


def get_api_key(region):
    """Read only the API key explicitly bound to the selected region."""
    selected_region = normalize_region(region)
    dedicated_name = REGION_API_KEY_ENV[selected_region]
    dedicated_key = os.environ.get(dedicated_name, "").strip()
    if dedicated_key:
        return dedicated_key

    legacy_key = os.environ.get("LUX3D_API_KEY", "").strip()
    if not legacy_key:
        return ""
    legacy_region = os.environ.get("LUX3D_API_KEY_REGION", "").strip()
    if not legacy_region:
        raise ValueError(
            "Legacy LUX3D_API_KEY is not region-bound. Set "
            f"{dedicated_name}, or set LUX3D_API_KEY_REGION={selected_region}."
        )
    bound_region = normalize_region(legacy_region)
    if bound_region != selected_region:
        raise ValueError(
            "Legacy LUX3D_API_KEY is bound to region "
            f"'{bound_region}' and cannot be used for '{selected_region}'."
        )
    return legacy_key


def resolve_api_key(region, *, api_key=None, credential_provider=None):
    """Resolve one request credential without mutating process environment.

    Explicit credentials are intended for server adapters that handle multiple
    callers in one process. The environment fallback preserves the existing CLI
    behavior when neither explicit input is supplied.
    """
    selected_region = normalize_region(region)
    if api_key is not None and credential_provider is not None:
        raise ValueError("Pass either api_key or credential_provider, not both")
    if credential_provider is not None:
        if not callable(credential_provider):
            raise ValueError("credential_provider must be callable")
        provider_failed = False
        try:
            api_key = credential_provider(selected_region)
        except Exception:
            api_key = None
            provider_failed = True
        if provider_failed:
            raise ValueError(
                f"Credential provider failed for region '{selected_region}'."
            )
    elif api_key is None:
        api_key = get_api_key(selected_region)
    if not isinstance(api_key, str):
        return ""
    return api_key.strip()


def validate_api_key(region, *, api_key=None, credential_provider=None):
    """Return a request or environment API key, or raise a useful error."""
    selected_region = normalize_region(region)
    resolved_key = resolve_api_key(
        selected_region,
        api_key=api_key,
        credential_provider=credential_provider,
    )
    if not resolved_key or resolved_key in {"your_lux3d_api_key", "your_api_key"}:
        dedicated_name = REGION_API_KEY_ENV[selected_region]
        raise ValueError(
            f"API key not configured for region '{selected_region}'. Set "
            f"{dedicated_name}, or bind legacy LUX3D_API_KEY with "
            f"LUX3D_API_KEY_REGION={selected_region}."
        )
    return resolved_key


def normalize_region(region=None):
    """Normalize supported region aliases and reject unknown values."""
    value = region
    if value is None:
        value = os.environ.get("LUX3D_REGION", DEFAULT_REGION)
    value = str(value).strip().lower()
    aliases = {
        "cn": "cn",
        "china": "cn",
        "domestic": "cn",
        "international": "international",
        "global": "international",
        "intl": "international",
    }
    if value not in aliases:
        raise ValueError("region must be 'cn' or 'international'")
    return aliases[value]


def get_base_url(region=None):
    """Return the configured Lux3D API root."""
    configured = os.environ.get("LUX3D_BASE_URL", "").strip()
    if configured:
        return normalize_base_url(configured, region)
    return REGION_BASE_URLS[normalize_region(region)]


def normalize_base_url(base_url=None, region=None):
    """Normalize a custom base URL to the documented Lux3D API root."""
    if not base_url:
        base_url = os.environ.get("LUX3D_BASE_URL", "").strip()
        if not base_url:
            return REGION_BASE_URLS[normalize_region(region)]
    normalized = str(base_url).strip().rstrip("/")
    if normalized == "https://api.aholo3d.com":
        normalized += "/global"
    if normalized == "https://api.aholo.ai":
        normalized = INTERNATIONAL_BASE_URL

    explicit_region = region
    if explicit_region is None:
        explicit_region = os.environ.get("LUX3D_REGION", "").strip() or None
    public_url_regions = {
        CN_BASE_URL: "cn",
        INTERNATIONAL_BASE_URL: "international",
        "https://api.aholo3d.com/global": "international",
    }
    if normalized in public_url_regions and explicit_region is not None:
        selected_region = normalize_region(explicit_region)
        actual_region = public_url_regions[normalized]
        if selected_region != actual_region:
            raise ValueError(
                f"base_url belongs to region '{actual_region}', not "
                f"'{selected_region}'; China and Global credentials/endpoints "
                "must remain isolated"
            )
    return normalized


def resolve_request_region(base_url=None, region=None):
    """Resolve the credential region from an explicit region or public API root."""
    normalized_base_url = normalize_base_url(base_url, region)
    public_url_regions = {
        CN_BASE_URL: "cn",
        INTERNATIONAL_BASE_URL: "international",
        "https://api.aholo3d.com/global": "international",
    }
    if normalized_base_url in public_url_regions:
        return public_url_regions[normalized_base_url]
    return normalize_region(region)


def get_asset_upload_docs(region=None):
    """Return the Asset upload documentation for a region."""
    return ASSET_UPLOAD_DOCS[normalize_region(region)]


def validate_http_url(value, field_name, region=None):
    """Validate a public HTTP(S) URL used by an API file field."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty HTTP(S) URL")
    normalized = value.strip()
    parsed = urllib.parse.urlparse(normalized)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        docs = get_asset_upload_docs(region)
        raise ValueError(
            f"{field_name} must be an accessible HTTP(S) URL. "
            f"Upload local files first: {docs}"
        )
    return normalized


def validate_url_suffix(value, field_name, suffixes, region=None):
    """Validate a URL and its decoded path suffix."""
    normalized = validate_http_url(value, field_name, region)
    path = urllib.parse.unquote(urllib.parse.urlparse(normalized).path).lower()
    if not any(path.endswith(suffix) for suffix in suffixes):
        expected = " or ".join(suffixes)
        raise ValueError(f"{field_name} URL path must end with {expected}")
    return normalized


def validate_output_path(output_path):
    """Validate that an output path can be written."""
    output_dir = os.path.dirname(os.path.abspath(output_path)) or "."
    if not os.path.isdir(output_dir):
        raise ValueError(f"Output directory does not exist: {output_dir}")


def validate_prompt(prompt):
    """Validate a text-to-3D prompt."""
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("prompt must be non-empty text")
    return prompt.strip()


def validate_style(style):
    """Validate an optional text-to-3D style."""
    if style is None:
        return None
    if style not in SUPPORTED_STYLES:
        supported = ", ".join(sorted(SUPPORTED_STYLES))
        raise ValueError(f"Unsupported style '{style}'. Supported styles: {supported}")
    return style


def validate_boolean(value, name):
    """Validate an optional boolean field."""
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be a boolean")
    return value


def validate_version(version):
    """Validate the required image/text generation version."""
    if version not in GENERATION_VERSIONS:
        raise ValueError("version is required and must be 'G1' or 'G1-Turbo'")
    return version


def validate_material_version(version):
    """Validate the required material-transfer version."""
    if version != MATERIAL_VERSION:
        raise ValueError(f"version is required and must be '{MATERIAL_VERSION}'")
    return version


def validate_face_count(faceCount):
    """Validate the target Mesh face count."""
    if faceCount is None:
        return None
    if not isinstance(faceCount, int) or isinstance(faceCount, bool):
        raise ValueError("faceCount must be an integer")
    if not FACE_COUNT_MIN <= faceCount <= FACE_COUNT_MAX:
        raise ValueError(
            f"faceCount must be in [{FACE_COUNT_MIN}, {FACE_COUNT_MAX}]"
        )
    return faceCount


def normalize_output_formats(outputFormat):
    """Normalize outputFormat while preserving order and rejecting duplicates."""
    if outputFormat is None:
        return None
    if isinstance(outputFormat, str):
        formats = [outputFormat]
    elif isinstance(outputFormat, (list, tuple)):
        formats = list(outputFormat)
    else:
        raise ValueError("outputFormat must be a string or an ordered list of strings")
    if any(not isinstance(item, str) for item in formats):
        raise ValueError("outputFormat values must be strings")
    if len(formats) != len(set(formats)):
        raise ValueError("outputFormat must not contain duplicate values")
    return formats


def validate_allowed_formats(outputFormat, allowed, label):
    """Validate outputFormat against one endpoint's public values."""
    formats = normalize_output_formats(outputFormat)
    invalid = [item for item in formats or [] if item not in allowed]
    if invalid:
        supported = ", ".join(sorted(allowed))
        raise ValueError(f"{label} supports only: {supported}")
    return formats


def validate_generation_options(
    version, outputFormat=None, enablePbr=None, customSize=None
):
    """Validate version-specific image/text generation fields."""
    version = validate_version(version)
    formats = validate_allowed_formats(
        outputFormat, GENERATION_FORMATS, f"{version} generation"
    )
    validate_boolean(enablePbr, "enablePbr")
    validate_custom_size(customSize)
    if version == "G1" and enablePbr is not None:
        raise ValueError("enablePbr is not a G1 field; omit it for G1")
    if version == "G1-Turbo" and customSize is not None:
        raise ValueError("customSize is not a G1-Turbo field; omit it for G1-Turbo")
    if (
        version == "G1-Turbo"
        and formats == ["ply"]
        and enablePbr is not None
    ):
        raise ValueError("enablePbr must be omitted for a G1-Turbo PLY-only request")
    return formats


def validate_custom_size(customSize):
    """Validate a model height in millimetres."""
    if customSize is None:
        return None
    if isinstance(customSize, bool) or not isinstance(customSize, (int, float)):
        raise ValueError("customSize must be a number greater than 0")
    if customSize <= 0:
        raise ValueError("customSize must be a number greater than 0")
    return customSize


def validate_material_options(
    version, outputFormat=None, aiPredictSize=None, customSize=None
):
    """Validate material-transfer fields for v3.0-standard."""
    validate_material_version(version)
    formats = validate_allowed_formats(
        outputFormat, MATERIAL_FORMATS, "Material transfer"
    )
    validate_boolean(aiPredictSize, "aiPredictSize")
    validate_custom_size(customSize)
    if aiPredictSize is True and customSize is not None:
        raise ValueError("customSize must be omitted when aiPredictSize is true")
    return formats


def validate_export_options(modelUrl, outputFormat=None, region=None):
    """Validate multi-format export input and requested formats."""
    model_url = validate_url_suffix(
        modelUrl, "modelUrl", (".zip", ".glb"), region
    )
    formats = validate_allowed_formats(
        outputFormat, EXPORT_FORMATS, "Multi-format export"
    )
    path = urllib.parse.unquote(urllib.parse.urlparse(model_url).path).lower()
    if path.endswith(".glb") and not formats:
        raise ValueError(
            "outputFormat is required for GLB input and must include at least "
            "one of: usdz, obj_zip, fbx_zip, stl, 3mf"
        )
    return model_url, formats


def add_optional(payload, name, value):
    """Add a field only when the caller supplied it."""
    if value is not None:
        payload[name] = value


def build_multimodal_payload(img=None, prompt=None, region=None):
    """Build a payload that requires at least one image or text input."""
    if img is None and prompt is None:
        raise ValueError("Pass at least one of img or prompt")
    payload = {}
    if img is not None:
        payload["img"] = validate_http_url(img, "img", region)
    if prompt is not None:
        payload["prompt"] = validate_prompt(prompt)
    return payload


def build_image_to_four_view_payload(img=None, *, prompt=None, region=None):
    """Build the exact validated body sent by four-view creation."""
    return build_multimodal_payload(img, prompt, region)


def build_image_to_3d_payload(
    img=None,
    *,
    imgs=None,
    version,
    faceCount=None,
    outputFormat=None,
    enablePbr=None,
    aiPredictSize=None,
    customSize=None,
    region=None,
):
    """Build the exact validated body sent by image-to-3D creation."""
    if (img is None) == (imgs is None):
        raise ValueError("Pass exactly one of img or imgs")
    payload = {}
    if img is not None:
        payload["img"] = validate_http_url(img, "img", region)
    else:
        if not isinstance(imgs, (list, tuple)):
            raise ValueError("imgs must be an ordered list of 1-32 image URLs")
        if not 1 <= len(imgs) <= 32:
            raise ValueError("imgs must contain 1-32 image URLs")
        payload["imgs"] = [
            validate_http_url(item, f"imgs[{index}]", region)
            for index, item in enumerate(imgs)
        ]

    payload["version"] = validate_version(version)
    formats = validate_generation_options(
        version, outputFormat, enablePbr, customSize
    )
    add_optional(payload, "faceCount", validate_face_count(faceCount))
    if outputFormat is not None:
        payload["outputFormat"] = formats
    add_optional(payload, "enablePbr", enablePbr)
    add_optional(
        payload, "aiPredictSize", validate_boolean(aiPredictSize, "aiPredictSize")
    )
    add_optional(payload, "customSize", validate_custom_size(customSize))
    return payload


def build_text_to_3d_payload(
    prompt,
    *,
    version,
    style=None,
    img=None,
    faceCount=None,
    outputFormat=None,
    enablePbr=None,
    aiPredictSize=None,
    customSize=None,
    region=None,
):
    """Build the exact validated body sent by text-to-3D creation."""
    payload = {
        "prompt": validate_prompt(prompt),
        "version": validate_version(version),
    }
    add_optional(payload, "style", validate_style(style))
    if img is not None:
        payload["img"] = validate_http_url(img, "img", region)
    formats = validate_generation_options(
        version, outputFormat, enablePbr, customSize
    )
    add_optional(payload, "faceCount", validate_face_count(faceCount))
    if outputFormat is not None:
        payload["outputFormat"] = formats
    add_optional(payload, "enablePbr", enablePbr)
    add_optional(
        payload, "aiPredictSize", validate_boolean(aiPredictSize, "aiPredictSize")
    )
    add_optional(payload, "customSize", validate_custom_size(customSize))
    return payload


def build_material_transfer_payload(
    img,
    meshUrl,
    *,
    version,
    outputFormat=None,
    aiPredictSize=None,
    customSize=None,
    region=None,
):
    """Build the exact validated body sent by material-transfer creation."""
    formats = validate_material_options(
        version, outputFormat, aiPredictSize, customSize
    )
    payload = {
        "img": validate_http_url(img, "img", region),
        "meshUrl": validate_url_suffix(meshUrl, "meshUrl", (".glb",), region),
        "version": validate_material_version(version),
    }
    if outputFormat is not None:
        payload["outputFormat"] = formats
    add_optional(
        payload, "aiPredictSize", validate_boolean(aiPredictSize, "aiPredictSize")
    )
    add_optional(payload, "customSize", validate_custom_size(customSize))
    return payload


def build_multi_format_export_payload(
    modelUrl,
    *,
    outputFormat=None,
    region=None,
):
    """Build the exact validated body sent by multi-format export creation."""
    model_url, formats = validate_export_options(modelUrl, outputFormat, region)
    payload = {"modelUrl": model_url}
    if outputFormat is not None:
        payload["outputFormat"] = formats
    return payload


def validate_digital_human_model_url(value, field_name, region=None):
    """Validate the digital-human endpoint's public HTTPS GLB input."""
    model_url = validate_url_suffix(value, field_name, (".glb",), region)
    parsed = urllib.parse.urlsplit(model_url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username is not None or parsed.password is not None or parsed.fragment:
        raise ValueError(f"{field_name} must be a public HTTPS GLB URL without credentials or a fragment")
    return model_url


def build_auto_rig_payload(modelUrl, *, region=None):
    """Build the exact body used for auto-rig quotation and creation."""
    model_url = validate_digital_human_model_url(modelUrl, "modelUrl", region)
    return {"modelUrl": model_url}


def build_animation_retarget_payload(
    rigModelUrl,
    animationIds,
    *,
    animationOutputMode=None,
    outFormat=None,
    animateInPlace=None,
    region=None,
):
    """Build one normalized call, independent of quote correlation metadata."""
    model_url = validate_digital_human_model_url(rigModelUrl, "rigModelUrl", region)
    if not isinstance(animationIds, (list, tuple)) or not 1 <= len(animationIds) <= 10:
        raise ValueError("animationIds must contain 1-10 distinct public animation IDs")
    if any(not isinstance(item, str) or not item.strip() or item != item.strip() or item not in ANIMATION_IDS for item in animationIds):
        raise ValueError("animationIds must use the exact public animation IDs")
    if len(set(animationIds)) != len(animationIds):
        raise ValueError("animationIds must not contain duplicates")
    mode = "separate" if animationOutputMode is None else animationOutputMode
    output_format = "glb" if outFormat is None else outFormat
    if not isinstance(mode, str) or not isinstance(output_format, str) or mode not in ANIMATION_OUTPUT_MODES or output_format not in ANIMATION_FORMATS:
        raise ValueError("animationOutputMode must be separate/combined and outFormat must be glb/fbx")
    in_place = False if animateInPlace is None else validate_boolean(animateInPlace, "animateInPlace")
    return {"rigModelUrl": model_url, "animationIds": list(animationIds), "animationOutputMode": mode, "outFormat": output_format, "animateInPlace": in_place}


def generation_result_formats(version, outputFormat=None):
    """Return the documented output order for a generation request."""
    formats = normalize_output_formats(outputFormat)
    if version == "G1":
        result = ["zip", "glb"]
        if formats and "ply" in formats:
            result.append("ply")
        return result
    return formats or ["zip"]


def material_result_formats(outputFormat=None):
    """Return the documented material-transfer output order."""
    formats = normalize_output_formats(outputFormat) or []
    return ["zip", "glb"] + [
        item for item in MATERIAL_OUTPUT_SLOTS[2:] if item in formats
    ]


def export_result_formats(modelUrl, outputFormat=None):
    """Return expected output formats for a multi-format export request."""
    formats = normalize_output_formats(outputFormat) or []
    result = [item for item in EXPORT_OUTPUT_SLOTS[2:] if item in formats]
    path = urllib.parse.unquote(urllib.parse.urlparse(modelUrl).path).lower()
    if path.endswith(".zip"):
        result.insert(0, "glb")
    return result


def output_extension(output_format):
    """Return the file extension for a public output format."""
    if output_format in {"obj_zip", "fbx_zip", "zip"}:
        return "zip"
    return output_format


def get_auth_headers(region, *, api_key=None, credential_provider=None):
    """Build the Lux3D authentication headers."""
    return {
        "Content-Type": "application/json",
        "Authorization": validate_api_key(
            region,
            api_key=api_key,
            credential_provider=credential_provider,
        ),
    }


def secure_request(
    method,
    url,
    headers=None,
    data=None,
    timeout=None,
    retries=None,
    stream=False,
):
    """Perform an HTTP request with bounded retries."""
    method = method.upper()
    request_headers = {"Content-Type": "application/json"} if headers is None else headers
    timeout = REQUEST_TIMEOUT if timeout is None else timeout
    retries = (1 if method == "POST" else MAX_RETRIES) if retries is None else retries
    if not isinstance(retries, int) or isinstance(retries, bool) or retries < 1:
        raise ValueError("retries must be a positive integer")
    last_error = None
    for attempt in range(retries):
        try:
            response = requests.request(
                method=method,
                url=url,
                headers=request_headers,
                json=data,
                timeout=timeout,
                stream=stream,
            )
            response.raise_for_status()
            return response
        except requests.exceptions.Timeout:
            last_error = f"Request timeout (attempt {attempt + 1}/{retries})"
        except requests.exceptions.RequestException as exc:
            last_error = f"Request failed: {exc}"
        if attempt < retries - 1:
            time.sleep(RETRY_DELAY)
    raise RuntimeError(f"Request failed after {retries} attempts: {last_error}")


def ensure_success(result):
    """Validate create, query, and list response envelopes."""
    if not isinstance(result, dict):
        raise ApiProtocolError("API response must be a JSON object")
    required = {"f", "c", "m", "d"}
    missing = sorted(required - set(result))
    if missing:
        raise ApiProtocolError(
            "API response is missing envelope fields: " + ", ".join(missing)
        )
    code = result["c"]
    if code == "0":
        if result["f"] is not None:
            raise ApiProtocolError("Successful API response f must be null")
        if result["m"] != "":
            raise ApiProtocolError("Successful API response m must be an empty string")
        return result
    if isinstance(code, str) and code:
        raise ApiBusinessRejection(code, result.get("m"), result)
    raise ApiProtocolError(
        f"API response must contain string success code '0'; got {code!r}"
    )


def submit_task(
    path,
    payload,
    base_url=None,
    region=None,
    *,
    api_key=None,
    credential_provider=None,
    content_id=None,
):
    """Submit an asynchronous task and return its task ID."""
    if content_id is not None:
        if not isinstance(content_id, str) or not content_id.strip() or len(content_id) > 255:
            raise ValueError("content_id must be a non-empty string of at most 255 characters")
        payload = dict(payload)
        payload["contentId"] = content_id
    request_region = resolve_request_region(base_url, region)
    url = normalize_base_url(base_url, request_region) + path
    response = secure_request(
        "POST",
        url,
        headers=get_auth_headers(
            request_region,
            api_key=api_key,
            credential_provider=credential_provider,
        ),
        data=payload,
    )
    try:
        result = response.json()
    except ValueError as exc:
        raise ApiProtocolError("API returned a non-JSON response; response body omitted") from exc
    ensure_success(result)
    task_id = result["d"]
    if not isinstance(task_id, int) or isinstance(task_id, bool) or task_id <= 0:
        raise ApiProtocolError(
            "Create response d must be a positive long task ID"
        )
    return str(task_id)


def create_auto_rig_task(
    modelUrl,
    *,
    base_url=None,
    region=None,
    api_key=None,
    credential_provider=None,
    content_id=None,
):
    """Create one auto-rig task; content_id is the bound quoteId."""
    return submit_task(
        "/lux3d/v1/animations/rig/task/create",
        build_auto_rig_payload(modelUrl, region=region),
        base_url=base_url,
        region=region,
        api_key=api_key,
        credential_provider=credential_provider,
        content_id=content_id,
    )


def create_animation_retarget_task(
    rigModelUrl,
    animationIds,
    *,
    animationOutputMode=None,
    outFormat=None,
    animateInPlace=None,
    base_url=None,
    region=None,
    api_key=None,
    credential_provider=None,
    content_id=None,
):
    """Create one task for 1-10 actions with the current bound quoteId."""
    payload = build_animation_retarget_payload(rigModelUrl, animationIds, animationOutputMode=animationOutputMode, outFormat=outFormat, animateInPlace=animateInPlace, region=region)
    return submit_task(
        "/lux3d/v1/animations/retarget/task/create",
        payload,
        base_url=base_url,
        region=region,
        api_key=api_key,
        credential_provider=credential_provider,
        content_id=content_id,
    )


def create_image_to_3d_task(
    img=None,
    *,
    imgs=None,
    version,
    faceCount=None,
    outputFormat=None,
    enablePbr=None,
    aiPredictSize=None,
    customSize=None,
    base_url=None,
    region=None,
    api_key=None,
    credential_provider=None,
    content_id=None,
):
    """Create an image-to-3D task from one URL or 1-32 URL inputs."""
    payload = build_image_to_3d_payload(
        img,
        imgs=imgs,
        version=version,
        faceCount=faceCount,
        outputFormat=outputFormat,
        enablePbr=enablePbr,
        aiPredictSize=aiPredictSize,
        customSize=customSize,
        region=region,
    )
    return submit_task(
        "/lux3d/v1/generate/img-to-3d/task/create",
        payload,
        base_url=base_url,
        region=region,
        api_key=api_key,
        credential_provider=credential_provider,
        content_id=content_id,
    )


def create_task(img=None, **kwargs):
    """Backward-compatible name for create_image_to_3d_task."""
    return create_image_to_3d_task(img, **kwargs)


def create_text_to_3d_task(
    prompt,
    *,
    version,
    style=None,
    img=None,
    faceCount=None,
    outputFormat=None,
    enablePbr=None,
    aiPredictSize=None,
    customSize=None,
    base_url=None,
    region=None,
    api_key=None,
    credential_provider=None,
    content_id=None,
):
    """Create a text-to-3D task with one optional reference-image URL."""
    payload = build_text_to_3d_payload(
        prompt,
        version=version,
        style=style,
        img=img,
        faceCount=faceCount,
        outputFormat=outputFormat,
        enablePbr=enablePbr,
        aiPredictSize=aiPredictSize,
        customSize=customSize,
        region=region,
    )
    return submit_task(
        "/lux3d/v1/generate/text-to-3d/task/create",
        payload,
        base_url=base_url,
        region=region,
        api_key=api_key,
        credential_provider=credential_provider,
        content_id=content_id,
    )


def create_material_transfer_task(
    img,
    meshUrl,
    *,
    version,
    outputFormat=None,
    aiPredictSize=None,
    customSize=None,
    base_url=None,
    region=None,
    api_key=None,
    credential_provider=None,
    content_id=None,
):
    """Create a v3.0-standard material-transfer task."""
    payload = build_material_transfer_payload(
        img,
        meshUrl,
        version=version,
        outputFormat=outputFormat,
        aiPredictSize=aiPredictSize,
        customSize=customSize,
        region=region,
    )
    return submit_task(
        "/lux3d/v1/generate/material-transfer/task/create",
        payload,
        base_url=base_url,
        region=region,
        api_key=api_key,
        credential_provider=credential_provider,
        content_id=content_id,
    )


def create_multimodal_to_image_task(
    img=None,
    *,
    prompt=None,
    base_url=None,
    region=None,
    api_key=None,
    credential_provider=None,
    content_id=None,
):
    """Create one image from an image URL, text, or both."""
    payload = build_multimodal_payload(img, prompt, region)
    return submit_task(
        "/lux3d/v1/generate/multimodal-to-image/task/create",
        payload,
        base_url=base_url,
        region=region,
        api_key=api_key,
        credential_provider=credential_provider,
        content_id=content_id,
    )


def create_image_to_four_view_task(
    img=None,
    *,
    prompt=None,
    base_url=None,
    region=None,
    api_key=None,
    credential_provider=None,
    content_id=None,
):
    """Create a four-view task from an image URL, text, or both."""
    payload = build_image_to_four_view_payload(img, prompt=prompt, region=region)
    return submit_task(
        "/lux3d/v1/generate/image-to-four-view/task/create",
        payload,
        base_url=base_url,
        region=region,
        api_key=api_key,
        credential_provider=credential_provider,
        content_id=content_id,
    )


def create_multi_format_export_task(
    modelUrl,
    *,
    outputFormat=None,
    base_url=None,
    region=None,
    api_key=None,
    credential_provider=None,
    content_id=None,
):
    """Create a multi-format export task for a Lux3D ZIP or GLB URL."""
    payload = build_multi_format_export_payload(
        modelUrl,
        outputFormat=outputFormat,
        region=region,
    )
    return submit_task(
        "/lux3d/v1/multi-format-export/task/create",
        payload,
        base_url=base_url,
        region=region,
        api_key=api_key,
        credential_provider=credential_provider,
        content_id=content_id,
    )


def get_task(
    task_id,
    base_url=None,
    region=None,
    *,
    api_key=None,
    credential_provider=None,
):
    """Query one Lux3D task once and return the public task object."""
    if isinstance(task_id, int) and not isinstance(task_id, bool):
        requested_task_id = task_id
    elif isinstance(task_id, str) and task_id.strip().isdigit():
        requested_task_id = int(task_id.strip())
    else:
        raise ValueError("task_id must be a positive long")
    if requested_task_id <= 0:
        raise ValueError("task_id must be a positive long")
    request_region = resolve_request_region(base_url, region)
    url = (
        normalize_base_url(base_url, request_region)
        + "/lux3d/v1/generate/task/get?taskid="
        + urllib.parse.quote(str(requested_task_id))
    )
    response = secure_request(
        "GET",
        url,
        headers=get_auth_headers(
            request_region,
            api_key=api_key,
            credential_provider=credential_provider,
        ),
    )
    try:
        result = response.json()
    except ValueError as exc:
        raise ApiProtocolError("API returned a non-JSON response; response body omitted") from exc
    ensure_success(result)
    task_data = result["d"]
    if not isinstance(task_data, dict):
        raise ApiProtocolError("Task response d must be a JSON object")
    required = {"bizId", "taskId", "status"}
    missing = sorted(required - set(task_data))
    if missing:
        raise ApiProtocolError(
            "Task response d is missing fields: " + ", ".join(missing)
        )
    if task_data["bizId"] != "LUX_3D":
        raise ApiProtocolError("Task response bizId must be LUX_3D")
    response_task_id = task_data["taskId"]
    if (
        not isinstance(response_task_id, int)
        or isinstance(response_task_id, bool)
        or response_task_id <= 0
    ):
        raise ApiProtocolError("Task response taskId must be a positive long")
    if response_task_id != requested_task_id:
        raise ApiProtocolError(
            "Task response taskId does not match the requested task_id"
        )
    status = task_data["status"]
    if (
        not isinstance(status, int)
        or isinstance(status, bool)
        or status not in SUPPORTED_TASK_STATUSES
    ):
        raise ApiProtocolError("Task response status must be an integer from 0 through 6")
    return task_data


def infer_artifact_format(url):
    """Infer a public artifact format from a result URL when possible."""
    path = urllib.parse.unquote(urllib.parse.urlparse(url).path).lower()
    filename = path.rsplit("/", 1)[-1]
    if filename.endswith(("_obj.zip", ".obj.zip", "obj.zip")):
        return "obj_zip"
    if filename.endswith(("_fbx.zip", ".fbx.zip", "fbx.zip")):
        return "fbx_zip"
    if filename.endswith(".usdz"):
        return "usdz"
    if filename.endswith(".stl"):
        return "stl"
    if filename.endswith(".3mf"):
        return "3mf"
    if filename.endswith(".glb"):
        return "glb"
    if filename.endswith(".ply"):
        return "ply"
    if filename.endswith(".zip"):
        return "zip"
    return None


def normalize_output_content(output):
    """Return one usable output value, or None for a documented empty slot."""
    if not isinstance(output, dict):
        raise RuntimeError("Task output item must be a JSON object")
    if "content" not in output:
        return None
    content = output["content"]
    if not isinstance(content, str):
        raise RuntimeError("Task output content must be a string when present")
    content = content.strip()
    if not content or content.lower() in {"not_requested", "null"}:
        return None
    return content


def task_output_items(task_data):
    """Validate the output container before examining individual slots."""
    outputs = task_data.get("outputs")
    if outputs is None:
        return []
    if not isinstance(outputs, list):
        raise RuntimeError("Task outputs must be a JSON array")
    return outputs


def parse_fixed_output_slots(task_data, output_slots):
    """Map fixed-position task outputs without guessing from URL suffixes."""
    if tuple(output_slots) == ARTICULATION_OUTPUT_SLOTS:
        return parse_articulation_animation_output(task_data)
    if tuple(output_slots) == RETOPOLOGY_OUTPUT_SLOTS:
        return parse_mesh_retopology_output(task_data)
    outputs = task_output_items(task_data)
    slots = tuple(output_slots)
    if len(outputs) != len(slots):
        raise RuntimeError(
            f"Expected {len(slots)} fixed output slots, got {len(outputs)}"
        )
    artifacts = {}
    for slot, output in zip(slots, outputs):
        content = normalize_output_content(output)
        if content is not None:
            artifacts[slot] = content
    if not artifacts:
        raise RuntimeError("Task succeeded without output content")
    return artifacts


def parse_task_outputs(task_data):
    """Parse result URLs without discarding their documented order."""
    contents = []
    for output in task_output_items(task_data):
        content = normalize_output_content(output)
        if content is not None:
            contents.append(content)
    if not contents:
        raise RuntimeError("Task succeeded without output content")

    if len(contents) == 1 and isinstance(contents[0], str):
        try:
            view_urls = json.loads(contents[0])
        except (TypeError, ValueError):
            view_urls = None
        if isinstance(view_urls, dict) and "error" in view_urls:
            return view_urls
        if isinstance(view_urls, dict) and "actions" in view_urls:
            if not isinstance(view_urls["actions"], list) or not view_urls["actions"]:
                raise RuntimeError("Animation result actions must be a non-empty array")
            return view_urls
        if (
            isinstance(view_urls, list)
            and len(view_urls) == 4
            and all(isinstance(item, str) for item in view_urls)
        ):
            return [
                validate_http_url(item, f"fourView[{index}]")
                for index, item in enumerate(view_urls)
            ]

    artifacts = {}
    for content in contents:
        if not isinstance(content, str):
            break
        output_format = infer_artifact_format(content)
        if output_format is None or output_format in artifacts:
            break
        artifacts[output_format] = content
    else:
        return artifacts
    return contents[0] if len(contents) == 1 else contents


def validate_animation_results(outputs, animationIds, *, outFormat="glb", animationOutputMode="separate"):
    """Validate every action against the accepted request without guessing file order."""
    if not isinstance(outputs, dict) or not isinstance(outputs.get("actions"), list):
        raise ValueError("Animation output must contain an actions array")
    actions = outputs["actions"]
    if len(actions) != len(animationIds):
        raise ValueError("Animation output is missing or has extra requested actions")
    url_key = {"glb": "animationGlbUrl", "fbx": "fbxUrl"}.get(outFormat)
    if url_key is None or animationOutputMode not in ANIMATION_OUTPUT_MODES:
        raise ValueError("Accepted animation format or output mode is invalid")
    results = {}
    for action in actions:
        if not isinstance(action, dict):
            raise ValueError("Animation action must be an object")
        action_id = action.get("animation_id")
        if not isinstance(action_id, str) or action_id not in animationIds or action_id in results:
            raise ValueError("Animation output has an unknown or duplicate action")
        status = action.get("status")
        result = {"animation_id": action_id, "status": status}
        if status == "success":
            other_key = "fbxUrl" if outFormat == "glb" else "animationGlbUrl"
            if action.get(other_key) is not None:
                raise ValueError("Animation success has a result in the wrong requested format")
            result[url_key] = validate_http_url(action.get(url_key), url_key)
        elif status == "failed":
            error = action.get("error")
            if not isinstance(error, dict) or any(not isinstance(error.get(key), str) or not error[key].strip() for key in ("code", "message")):
                raise ValueError("Failed animation must have an error code and message")
            result["error"] = {"code": error["code"], "message": error["message"]}
        else:
            raise ValueError("Animation action must have terminal success or failed status")
        results[action_id] = result
    urls = [action[url_key] for action in results.values() if action["status"] == "success"]
    if animationOutputMode == "combined" and len(set(urls)) > 1:
        raise ValueError("Combined actions must reference the same returned file")
    if animationOutputMode == "separate" and len(set(urls)) != len(urls):
        raise ValueError("Separate actions must reference independent returned files")
    return [results[action_id] for action_id in animationIds]


def query_task_status(
    task_id,
    base_url=None,
    region=None,
    max_attempts=DEFAULT_POLL_ATTEMPTS,
    interval=DEFAULT_POLL_INTERVAL,
    output_slots=None,
    *,
    api_key=None,
    credential_provider=None,
):
    """Poll a task until it succeeds, fails, or is cancelled."""
    if not isinstance(max_attempts, int) or max_attempts < 1:
        raise ValueError("max_attempts must be a positive integer")
    if not isinstance(interval, (int, float)) or interval < 0:
        raise ValueError("interval must be a non-negative number")
    last_provider_status = None
    for attempt in range(max_attempts):
        try:
            task_data = get_task(
                task_id,
                base_url=base_url,
                region=region,
                api_key=api_key,
                credential_provider=credential_provider,
            )
        except RuntimeError as exc:
            raise TaskQueryError(
                f"Task query failed: {exc}",
                last_provider_status=last_provider_status,
            ) from exc
        status = task_data.get("status")
        if status == 3:
            try:
                if output_slots is not None:
                    return parse_fixed_output_slots(task_data, output_slots)
                return parse_task_outputs(task_data)
            except (RuntimeError, ValueError) as exc:
                raise TaskOutputError(
                    f"Task succeeded but output contract validation failed: {exc}",
                    task_data=task_data,
                ) from exc
        if status in {4, 5, 6}:
            raise TaskTerminalError(status, task_data=task_data)
        if status not in {0, 1, 2}:
            raise TaskQueryError(
                f"Unknown task status: {status}",
                last_provider_status=last_provider_status,
            )
        last_provider_status = status
        if attempt < max_attempts - 1:
            time.sleep(interval)
    raise TaskPollingTimeout(
        "Task did not finish before the polling limit",
        last_provider_status=last_provider_status,
    )


def validate_task_list_data(data):
    """Validate the documented list response instead of synthesizing history."""
    if not isinstance(data, dict):
        raise ApiProtocolError("Task list response d must be a JSON object")
    required = {"items", "total", "page", "pageSize"}
    missing = sorted(required - set(data))
    if missing:
        raise ApiProtocolError(
            "Task list response d is missing fields: " + ", ".join(missing)
        )
    items = data["items"]
    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        raise ApiProtocolError("Task list response items must be a list of objects")
    for name, minimum, maximum in (
        ("total", 0, None),
        ("page", 1, None),
        ("pageSize", 1, 100),
    ):
        value = data[name]
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or value < minimum
            or (maximum is not None and value > maximum)
        ):
            expected = f">= {minimum}" if maximum is None else f"in [{minimum}, {maximum}]"
            raise ApiProtocolError(f"Task list response {name} must be an integer {expected}")
    if data["total"] < len(items):
        raise ApiProtocolError("Task list response total cannot be smaller than items")
    for index, item in enumerate(items):
        missing_item_fields = {
            "taskId",
            "status",
            "created",
            "lastModified",
        } - set(item)
        if missing_item_fields:
            raise ApiProtocolError(
                f"Task list item {index} is missing fields: "
                + ", ".join(sorted(missing_item_fields))
            )
        if (
            not isinstance(item["status"], int)
            or isinstance(item["status"], bool)
            or item["status"] not in SUPPORTED_TASK_STATUSES
        ):
            raise ApiProtocolError(
                f"Task list item {index} has unsupported status: {item['status']!r}"
            )
        for name in ("taskId", "created", "lastModified"):
            value = item[name]
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ApiProtocolError(
                    f"Task list item {index} {name} must be a non-negative integer"
                )
    return data


def list_tasks(
    page=1,
    pagesize=20,
    status=None,
    starttime=None,
    endtime=None,
    base_url=None,
    region=None,
    *,
    api_key=None,
    credential_provider=None,
):
    """List tasks for the current API-key account."""
    if not isinstance(page, int) or isinstance(page, bool) or page < 1:
        raise ValueError("page must be a positive integer")
    if (
        not isinstance(pagesize, int)
        or isinstance(pagesize, bool)
        or not 1 <= pagesize <= 100
    ):
        raise ValueError("pagesize must be an integer between 1 and 100")
    if (
        status is not None
        and (
            not isinstance(status, int)
            or isinstance(status, bool)
            or status not in TASK_LIST_FILTER_STATUSES
        )
    ):
        raise ValueError("status filter must be one of 0, 1, 3, or 4")
    for name, value in (("starttime", starttime), ("endtime", endtime)):
        if (
            value is not None
            and (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < 0
            )
        ):
            raise ValueError(
                f"{name} must be a non-negative Unix timestamp in milliseconds"
            )
    if starttime is not None and endtime is not None and starttime >= endtime:
        raise ValueError("starttime must be earlier than endtime")

    params = {"page": page, "pagesize": pagesize}
    for name, value in (
        ("status", status),
        ("starttime", starttime),
        ("endtime", endtime),
    ):
        if value is not None:
            params[name] = value
    request_region = resolve_request_region(base_url, region)
    url = (
        normalize_base_url(base_url, request_region)
        + "/lux3d/v1/generate/task/list?"
        + urllib.parse.urlencode(params)
    )
    response = secure_request(
        "GET",
        url,
        headers=get_auth_headers(
            request_region,
            api_key=api_key,
            credential_provider=credential_provider,
        ),
    )
    try:
        result = response.json()
    except ValueError as exc:
        raise ApiProtocolError("API returned a non-JSON response; response body omitted") from exc
    ensure_success(result)
    return validate_task_list_data(result.get("d"))


def download_model(model_url, output_path):
    """Download one result URL and return the number of bytes written."""
    model_url = validate_http_url(model_url, "model_url")
    validate_output_path(output_path)
    response = secure_request("GET", model_url, headers={}, stream=True)
    total_size = 0
    with open(output_path, "wb") as file_obj:
        for chunk in response.iter_content(chunk_size=DOWNLOAD_CHUNK_SIZE):
            if chunk:
                file_obj.write(chunk)
                total_size += len(chunk)
    response.close()
    return total_size


def map_artifact_urls(outputs, expected_formats):
    """Map ordered or named task outputs to expected formats."""
    if isinstance(outputs, dict):
        missing = [item for item in expected_formats if item not in outputs]
        if missing:
            raise ValueError(
                "Missing expected result formats: " + ", ".join(missing)
            )
        return {item: outputs[item] for item in expected_formats}
    if isinstance(outputs, str) and len(expected_formats) == 1:
        return {expected_formats[0]: outputs}
    if (
        isinstance(outputs, list)
        and len(outputs) == len(expected_formats)
        and all(isinstance(item, str) for item in outputs)
    ):
        return dict(zip(expected_formats, outputs))
    raise ValueError("Task outputs do not match the expected result formats")


def download_requested_models(outputs, output_path, expected_formats):
    """Download all expected model artifacts in documented output order."""
    artifact_urls = map_artifact_urls(outputs, expected_formats)
    if len(expected_formats) == 1:
        output_format = expected_formats[0]
        path = output_path
        if not os.path.splitext(path)[1]:
            path = f"{path}.{output_extension(output_format)}"
        return [(path, download_model(artifact_urls[output_format], path))]

    output_base, _ = os.path.splitext(output_path)
    downloads = []
    for output_format in expected_formats:
        path = f"{output_base}_{output_format}.{output_extension(output_format)}"
        size = download_model(artifact_urls[output_format], path)
        downloads.append((path, size))
    return downloads


def complete_task(
    task_id,
    *,
    output_path=None,
    expected_formats=None,
    base_url=None,
    region=None,
    max_attempts=DEFAULT_POLL_ATTEMPTS,
    interval=DEFAULT_POLL_INTERVAL,
    output_slots=None,
    api_key=None,
    credential_provider=None,
):
    """Wait for a task, optionally downloading all expected artifacts."""
    outputs = query_task_status(
        task_id,
        base_url=base_url,
        region=region,
        max_attempts=max_attempts,
        interval=interval,
        output_slots=output_slots,
        api_key=api_key,
        credential_provider=credential_provider,
    )
    if output_path is None:
        return outputs
    if not expected_formats:
        raise ValueError("expected_formats are required when downloading results")
    return download_requested_models(outputs, output_path, expected_formats)


def generate_3d_model(
    img=None,
    output_path=None,
    *,
    imgs=None,
    version,
    faceCount=None,
    outputFormat=None,
    enablePbr=None,
    aiPredictSize=None,
    customSize=None,
    base_url=None,
    region=None,
    max_attempts=DEFAULT_POLL_ATTEMPTS,
    interval=DEFAULT_POLL_INTERVAL,
    api_key=None,
    credential_provider=None,
    content_id=None,
):
    """Run the image-to-3D create, poll, and optional download workflow."""
    task_id = create_image_to_3d_task(
        img,
        imgs=imgs,
        version=version,
        faceCount=faceCount,
        outputFormat=outputFormat,
        enablePbr=enablePbr,
        aiPredictSize=aiPredictSize,
        customSize=customSize,
        base_url=base_url,
        region=region,
        api_key=api_key,
        credential_provider=credential_provider,
        content_id=content_id,
    )
    return complete_task(
        task_id,
        output_path=output_path,
        expected_formats=generation_result_formats(version, outputFormat),
        base_url=base_url,
        region=region,
        max_attempts=max_attempts,
        interval=interval,
        api_key=api_key,
        credential_provider=credential_provider,
    )


def generate_text_to_3d(
    prompt,
    output_path=None,
    *,
    version,
    style=None,
    img=None,
    faceCount=None,
    outputFormat=None,
    enablePbr=None,
    aiPredictSize=None,
    customSize=None,
    base_url=None,
    region=None,
    max_attempts=DEFAULT_POLL_ATTEMPTS,
    interval=DEFAULT_POLL_INTERVAL,
    api_key=None,
    credential_provider=None,
    content_id=None,
):
    """Run the text-to-3D create, poll, and optional download workflow."""
    task_id = create_text_to_3d_task(
        prompt,
        version=version,
        style=style,
        img=img,
        faceCount=faceCount,
        outputFormat=outputFormat,
        enablePbr=enablePbr,
        aiPredictSize=aiPredictSize,
        customSize=customSize,
        base_url=base_url,
        region=region,
        api_key=api_key,
        credential_provider=credential_provider,
        content_id=content_id,
    )
    return complete_task(
        task_id,
        output_path=output_path,
        expected_formats=generation_result_formats(version, outputFormat),
        base_url=base_url,
        region=region,
        max_attempts=max_attempts,
        interval=interval,
        api_key=api_key,
        credential_provider=credential_provider,
    )


def generate_material_transfer(
    img,
    meshUrl,
    output_path=None,
    *,
    version,
    outputFormat=None,
    aiPredictSize=None,
    customSize=None,
    base_url=None,
    region=None,
    max_attempts=DEFAULT_POLL_ATTEMPTS,
    interval=DEFAULT_POLL_INTERVAL,
    api_key=None,
    credential_provider=None,
    content_id=None,
):
    """Run the material-transfer create, poll, and optional download workflow."""
    task_id = create_material_transfer_task(
        img,
        meshUrl,
        version=version,
        outputFormat=outputFormat,
        aiPredictSize=aiPredictSize,
        customSize=customSize,
        base_url=base_url,
        region=region,
        api_key=api_key,
        credential_provider=credential_provider,
        content_id=content_id,
    )
    return complete_task(
        task_id,
        output_path=output_path,
        expected_formats=material_result_formats(outputFormat),
        base_url=base_url,
        region=region,
        max_attempts=max_attempts,
        interval=interval,
        output_slots=MATERIAL_OUTPUT_SLOTS,
        api_key=api_key,
        credential_provider=credential_provider,
    )


def generate_multimodal_image(
    img=None,
    output_path=None,
    *,
    prompt=None,
    base_url=None,
    region=None,
    max_attempts=DEFAULT_POLL_ATTEMPTS,
    interval=DEFAULT_POLL_INTERVAL,
    api_key=None,
    credential_provider=None,
    content_id=None,
):
    """Run the multimodal single-image create and poll workflow."""
    task_id = create_multimodal_to_image_task(
        img,
        prompt=prompt,
        base_url=base_url,
        region=region,
        api_key=api_key,
        credential_provider=credential_provider,
        content_id=content_id,
    )
    result = complete_task(
        task_id,
        base_url=base_url,
        region=region,
        max_attempts=max_attempts,
        interval=interval,
        api_key=api_key,
        credential_provider=credential_provider,
    )
    if not isinstance(result, str):
        raise RuntimeError("The multimodal image task did not return one image URL")
    image_url = validate_http_url(result, "image result", region)
    if output_path is None:
        return image_url
    return [(output_path, download_model(image_url, output_path))]


def generate_four_views(
    img=None,
    *,
    prompt=None,
    base_url=None,
    region=None,
    max_attempts=DEFAULT_POLL_ATTEMPTS,
    interval=DEFAULT_POLL_INTERVAL,
    api_key=None,
    credential_provider=None,
    content_id=None,
):
    """Run the multimodal viewpoint-completion workflow and return four URLs."""
    task_id = create_image_to_four_view_task(
        img,
        prompt=prompt,
        base_url=base_url,
        region=region,
        api_key=api_key,
        credential_provider=credential_provider,
        content_id=content_id,
    )
    result = complete_task(
        task_id,
        base_url=base_url,
        region=region,
        max_attempts=max_attempts,
        interval=interval,
        api_key=api_key,
        credential_provider=credential_provider,
    )
    if not (
        isinstance(result, list)
        and len(result) == 4
        and all(isinstance(item, str) for item in result)
    ):
        raise RuntimeError("The four-view task did not return four image URLs")
    return result



ARTICULATION_OUTPUT_SLOTS = ("articulation-artifact",)


def build_articulation_animation_payload(glbUrl, prompt, *, region=None):
    """The public endpoint accepts exactly these two fields."""
    return {"glbUrl": validate_http_url(glbUrl, "glbUrl", region),
            "prompt": validate_prompt(prompt)}


def create_articulation_animation_task(
    glbUrl, prompt, *, base_url=None, region=None, api_key=None, credential_provider=None,
):
    request_region = resolve_request_region(base_url, region)
    return submit_task(
        "/lux3d/v1/articulation-animation/task/create",
        build_articulation_animation_payload(glbUrl, prompt, region=request_region),
        base_url=base_url, region=request_region,
        api_key=api_key, credential_provider=credential_provider,
    )


def parse_articulation_animation_output(task_data):
    outputs = task_output_items(task_data)
    if len(outputs) != 1 or not isinstance(outputs[0], dict):
        raise ValueError("Articulation requires exactly one result URL")
    return validate_http_url(outputs[0].get("content"), "articulation result")


def articulation_result_extension(url):
    path = urllib.parse.unquote(urllib.parse.urlparse(validate_http_url(url, "result")).path)
    extension = os.path.splitext(path)[1].lower()
    if not extension[1:].isascii() or not extension[1:].isalnum() or len(extension) > 12:
        return ".bin"
    return extension


def resume_articulation_animation(
    task_id, output_path=None, *, base_url=None, region=None,
    max_attempts=DEFAULT_POLL_ATTEMPTS, interval=DEFAULT_POLL_INTERVAL,
    api_key=None, credential_provider=None,
):
    if output_path is not None:
        validate_output_path(output_path)
    url = query_task_status(
        task_id, base_url=base_url, region=region, max_attempts=max_attempts,
        interval=interval, output_slots=ARTICULATION_OUTPUT_SLOTS,
        api_key=api_key, credential_provider=credential_provider,
    )
    result = {"taskId": str(task_id), "artifactUrl": url}
    if output_path is not None:
        from artifact_delivery import inspect_articulation_artifact
        target = os.path.splitext(os.fspath(output_path))[0] + articulation_result_extension(url)
        with tempfile.NamedTemporaryFile(dir=os.path.dirname(os.path.abspath(target)),
                                         prefix=".articulation-", delete=False) as stream:
            temporary = stream.name
        try:
            download_model(url, temporary)
            inspected = inspect_articulation_artifact(temporary, articulation_result_extension(url))
            os.replace(temporary, target)
            result["downloads"] = [{"path": target, "format": inspected["format"],
                                    "size": inspected["size"], "validation": inspected["validation"]}]
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return result


def generate_articulation_animation(
    glbUrl, prompt, output_path=None, *, base_url=None, region=None,
    max_attempts=DEFAULT_POLL_ATTEMPTS, interval=DEFAULT_POLL_INTERVAL,
    api_key=None, credential_provider=None,
):
    if output_path is not None:
        validate_output_path(output_path)
    if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or max_attempts < 1:
        raise ValueError("max_attempts must be a positive integer")
    if isinstance(interval, bool) or not isinstance(interval, (int, float)) or not 0 <= interval < float("inf"):
        raise ValueError("interval must be finite and non-negative")
    task_id = create_articulation_animation_task(
        glbUrl, prompt, base_url=base_url, region=region,
        api_key=api_key, credential_provider=credential_provider,
    )
    print(f"Task created: {task_id}", file=sys.stderr)
    return resume_articulation_animation(
        task_id, output_path, base_url=base_url, region=region,
        max_attempts=max_attempts, interval=interval,
        api_key=api_key, credential_provider=credential_provider,
    )


RETOPOLOGY_OUTPUT_SLOTS = ("glb", "obj", "obj_zip")


def build_mesh_retopology_payload(
    modelUrl, faceLimit, *, quad=True, bakeTextures=False, textureSize=2048,
    region=None,
):
    """Validate public retopology fields before any paid submission."""
    model_url = validate_url_suffix(modelUrl, "modelUrl", (".glb",), region)
    if not isinstance(quad, bool) or not isinstance(bakeTextures, bool):
        raise ValueError("quad and bakeTextures must be booleans")
    minimum, maximum = (1000, 500000) if quad else (2000, 1000000)
    if (isinstance(faceLimit, bool) or not isinstance(faceLimit, int)
            or not minimum <= faceLimit <= maximum):
        raise ValueError(f"faceLimit must be an integer between {minimum} and {maximum}")
    if (isinstance(textureSize, bool) or not isinstance(textureSize, int)
            or textureSize not in {512, 1024, 2048, 4096}):
        raise ValueError("textureSize must be one of 512, 1024, 2048 or 4096")
    return {"modelUrl": model_url, "faceLimit": faceLimit, "quad": quad,
            "bakeTextures": bakeTextures, "textureSize": textureSize}


def parse_mesh_retopology_output(task_data):
    """Preserve three provider slots, accepting only the documented empty ZIP."""
    outputs = task_data.get("outputs")
    if not isinstance(outputs, list) or len(outputs) != 3:
        raise RuntimeError("Retopology requires exactly three output slots")
    artifacts = {}
    for index, name in enumerate(RETOPOLOGY_OUTPUT_SLOTS):
        item = outputs[index]
        if not isinstance(item, dict) or not isinstance(item.get("content"), str):
            raise RuntimeError(f"Invalid retopology output slot: {name}")
        content = item["content"]
        if index == 2 and content == "":
            continue
        try:
            artifacts[name] = validate_http_url(content, name)
        except ValueError as exc:
            raise RuntimeError(f"Invalid retopology output URL: {name}") from exc
    return artifacts


def retopology_result(task_id, artifacts, bake_textures):
    return {
        "taskId": str(task_id), "artifacts": artifacts,
        "texturePackageAvailable": "obj_zip" in artifacts,
        "warnings": ["TEXTURE_PACKAGE_NOT_GENERATED"]
        if bake_textures and "obj_zip" not in artifacts else [],
    }


def create_mesh_retopology_task(
    modelUrl, faceLimit, *, quad=True, bakeTextures=False, textureSize=2048,
    base_url=None, region=None, content_id=None, api_key=None, credential_provider=None,
):
    payload = build_mesh_retopology_payload(
        modelUrl, faceLimit, quad=quad, bakeTextures=bakeTextures,
        textureSize=textureSize, region=region,
    )

    return submit_task(
        "/lux3d/v1/mesh-retopology/task/create", payload,
        base_url=base_url, region=region,
        content_id=content_id, api_key=api_key, credential_provider=credential_provider,
    )



def validate_retopology_download(file_path, kind):
    """Check downloaded model structure before replacing a previous result."""
    size = os.path.getsize(file_path)
    if size == 0:
        raise ValueError("Retopology artifact is empty")
    if kind == "glb":
        with open(file_path, "rb") as stream:
            header = stream.read(20)
            if (len(header) != 20 or header[:4] != b"glTF"
                    or struct.unpack_from("<I", header, 4)[0] != 2
                    or struct.unpack_from("<I", header, 8)[0] != size
                    or header[16:20] != b"JSON"):
                raise ValueError("Invalid retopology GLB")
            length = struct.unpack_from("<I", header, 12)[0]
            if length > size - 20:
                raise ValueError("Invalid GLB JSON chunk")
            document = json.loads(stream.read(length).decode("utf-8"))
            if not isinstance(document, dict) or not document.get("meshes"):
                raise ValueError("Retopology GLB has no meshes")
    elif kind == "obj":
        counts = [0, 0, 0]
        faces = 0
        with open(file_path, encoding="utf-8-sig") as stream:
            for line in stream:
                parts = line.split("#", 1)[0].split()
                if not parts:
                    continue
                if parts[0] in ("v", "vt", "vn"):
                    slot = ("v", "vt", "vn").index(parts[0])
                    minimum = 1 if slot == 1 else 3
                    if len(parts) <= minimum or not all(math.isfinite(float(v)) for v in parts[1:]):
                        raise ValueError("Invalid OBJ coordinate")
                    counts[slot] += 1
                elif parts[0] == "f":
                    if len(parts) < 4:
                        raise ValueError("Invalid OBJ face")
                    for token in parts[1:]:
                        refs = token.split("/")
                        if len(refs) > 3 or not refs[0]:
                            raise ValueError("Invalid OBJ face reference")
                        for slot, value in enumerate(refs):
                            if not value:
                                if slot == 1 and len(refs) == 3 and refs[2]:
                                    continue
                                raise ValueError("Empty OBJ face reference")
                            index = int(value)
                            if index == 0 or abs(index) > counts[slot]:
                                raise ValueError("OBJ face index out of bounds")
                    faces += 1
        if not counts[0] or not faces:
            raise ValueError("OBJ has no geometry")
    elif kind == "obj_zip":
        with zipfile.ZipFile(file_path) as archive:
            names = [n.lower() for n in archive.namelist()]
            if (archive.testzip() is not None or
                    not any(n.endswith(".obj") for n in names) or
                    not any(n.endswith(".mtl") for n in names) or
                    sum(n.endswith(".png") for n in names) < 3):
                raise ValueError("Invalid retopology OBJ texture package")
    return size


def download_retopology_artifacts(artifacts, output_path):
    """Keep prior downloads intact if a resumed transfer fails."""
    base, _ = os.path.splitext(os.fspath(output_path))
    downloads = []
    for kind in RETOPOLOGY_OUTPUT_SLOTS:
        if kind not in artifacts:
            continue
        target = f"{base}_{kind}.{output_extension(kind)}"
        directory = os.path.dirname(os.path.abspath(target))
        with tempfile.NamedTemporaryFile(dir=directory, prefix=".retopology-", delete=False) as stream:
            temporary = stream.name
        try:
            download_model(artifacts[kind], temporary)
            size = validate_retopology_download(temporary, kind)
            os.replace(temporary, target)
            downloads.append((target, size))
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return downloads


def resume_mesh_retopology(
    task_id, output_path=None, *, bakeTextures=False, base_url=None, region=None,
    max_attempts=DEFAULT_POLL_ATTEMPTS, interval=DEFAULT_POLL_INTERVAL,
    api_key=None, credential_provider=None,
):
    """Resume the original task; never create another task on query/download failure."""
    if not isinstance(bakeTextures, bool):
        raise ValueError("bakeTextures must be a boolean")
    artifacts = query_task_status(
        task_id, base_url=base_url, region=region, max_attempts=max_attempts,
        interval=interval, output_slots=RETOPOLOGY_OUTPUT_SLOTS,
        api_key=api_key, credential_provider=credential_provider,
    )
    result = retopology_result(task_id, artifacts, bakeTextures)
    if output_path is not None:
        result["downloads"] = download_retopology_artifacts(artifacts, output_path)
    return result


def generate_mesh_retopology(
    modelUrl, faceLimit, output_path=None, *, quad=True, bakeTextures=False,
    textureSize=2048, base_url=None, region=None, content_id=None,
    max_attempts=DEFAULT_POLL_ATTEMPTS, interval=DEFAULT_POLL_INTERVAL,
    api_key=None, credential_provider=None,
):
    if output_path is not None:
        validate_output_path(output_path)
    task_id = create_mesh_retopology_task(
        modelUrl, faceLimit, quad=quad, bakeTextures=bakeTextures,
        textureSize=textureSize, base_url=base_url, region=region,
        content_id=content_id,
        api_key=api_key, credential_provider=credential_provider,
    )
    # Persist this ID in the caller's task record before polling; CLI also emits it.
    print(json.dumps({"taskId": str(task_id)}), file=sys.stderr, flush=True)
    return resume_mesh_retopology(
        task_id, output_path, bakeTextures=bakeTextures, base_url=base_url,
        region=region, max_attempts=max_attempts, interval=interval,
        api_key=api_key, credential_provider=credential_provider,
    )


def generate_multi_format_export(
    modelUrl,
    output_path=None,
    *,
    outputFormat=None,
    base_url=None,
    region=None,
    max_attempts=DEFAULT_POLL_ATTEMPTS,
    interval=DEFAULT_POLL_INTERVAL,
    api_key=None,
    credential_provider=None,
    content_id=None,
):
    """Run the multi-format export create, poll, and optional download workflow."""
    task_id = create_multi_format_export_task(
        modelUrl,
        outputFormat=outputFormat,
        base_url=base_url,
        region=region,
        api_key=api_key,
        credential_provider=credential_provider,
        content_id=content_id,
    )
    return complete_task(
        task_id,
        output_path=output_path,
        expected_formats=export_result_formats(modelUrl, outputFormat),
        base_url=base_url,
        region=region,
        max_attempts=max_attempts,
        interval=interval,
        output_slots=EXPORT_OUTPUT_SLOTS,
        api_key=api_key,
        credential_provider=credential_provider,
    )


def add_poll_arguments(parser):
    """Add shared polling controls to a CLI subcommand."""
    parser.add_argument(
        "--max-attempts", type=int, default=DEFAULT_POLL_ATTEMPTS
    )
    parser.add_argument(
        "--interval", type=float, default=DEFAULT_POLL_INTERVAL
    )


def add_generation_arguments(parser):
    """Add shared version-specific image/text generation options."""
    parser.add_argument(
        "--version", required=True, choices=sorted(GENERATION_VERSIONS)
    )
    parser.add_argument(
        "--face-count",
        dest="faceCount",
        type=int,
        default=None,
        help=f"Mesh face count in [{FACE_COUNT_MIN}, {FACE_COUNT_MAX}]",
    )
    parser.add_argument(
        "--format",
        dest="outputFormat",
        action="append",
        choices=sorted(GENERATION_FORMATS),
        default=None,
        help="Repeat to request multiple formats.",
    )
    pbr_group = parser.add_mutually_exclusive_group()
    pbr_group.add_argument(
        "--enable-pbr", dest="enablePbr", action="store_true"
    )
    pbr_group.add_argument(
        "--no-pbr", dest="enablePbr", action="store_false"
    )
    parser.set_defaults(enablePbr=None)
    size_group = parser.add_mutually_exclusive_group()
    size_group.add_argument(
        "--ai-predict-size", dest="aiPredictSize", action="store_true"
    )
    size_group.add_argument(
        "--no-ai-predict-size", dest="aiPredictSize", action="store_false"
    )
    parser.set_defaults(aiPredictSize=None)
    parser.add_argument(
        "--custom-size",
        dest="customSize",
        type=float,
        help="G1 target height in millimetres; omit for G1-Turbo.",
    )
    add_poll_arguments(parser)


def build_parser():
    """Build the public command-line interface."""
    parser = argparse.ArgumentParser(
        description="Lux3D client using accessible URL inputs."
    )
    parser.add_argument(
        "--region",
        "-r",
        choices=["cn", "international"],
        default=None,
        help="API region. Default for this package: cn",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="Override the API root; LUX3D_BASE_URL is also supported.",
    )
    subparsers = parser.add_subparsers(dest="command")

    image_parser = subparsers.add_parser(
        "image", help="Generate 3D from one or more accessible image URLs."
    )
    image_parser.add_argument("img", help="Primary accessible image URL")
    image_parser.add_argument(
        "output_path", nargs="?", help="Optional output path or filename base"
    )
    image_parser.add_argument(
        "--image-view",
        dest="imageViews",
        action="append",
        default=None,
        help="Additional accessible image URL; repeat up to 31 times.",
    )
    add_generation_arguments(image_parser)

    text_parser = subparsers.add_parser(
        "text", help="Generate 3D from text and an optional image URL."
    )
    text_parser.add_argument("prompt")
    text_parser.add_argument(
        "output_path", nargs="?", help="Optional output path or filename base"
    )
    text_parser.add_argument("--style", choices=sorted(SUPPORTED_STYLES))
    text_parser.add_argument(
        "--image", dest="img", help="Optional accessible reference-image URL"
    )
    add_generation_arguments(text_parser)

    material_parser = subparsers.add_parser(
        "material", help="Transfer materials using accessible image and GLB URLs."
    )
    material_parser.add_argument("img", help="Material reference image URL")
    material_parser.add_argument(
        "output_path", nargs="?", help="Optional output path or filename base"
    )
    material_parser.add_argument(
        "--mesh-url", dest="meshUrl", required=True, help="Accessible GLB URL"
    )
    material_parser.add_argument(
        "--version", required=True, choices=[MATERIAL_VERSION]
    )
    material_parser.add_argument(
        "--format",
        dest="outputFormat",
        action="append",
        choices=sorted(MATERIAL_FORMATS),
        default=None,
    )
    material_size_group = material_parser.add_mutually_exclusive_group()
    material_size_group.add_argument(
        "--ai-predict-size", dest="aiPredictSize", action="store_true"
    )
    material_size_group.add_argument(
        "--no-ai-predict-size", dest="aiPredictSize", action="store_false"
    )
    material_parser.set_defaults(aiPredictSize=None)
    material_parser.add_argument("--custom-size", dest="customSize", type=float)
    add_poll_arguments(material_parser)

    four_view_parser = subparsers.add_parser(
        "four-view", help="Generate four viewpoints from an image URL, text, or both."
    )
    four_view_parser.add_argument(
        "img", nargs="?", help="Optional accessible object image URL"
    )
    four_view_parser.add_argument(
        "--prompt", help="Optional non-empty object or viewpoint prompt"
    )
    add_poll_arguments(four_view_parser)

    retopology_parser = subparsers.add_parser(
        "retopology", help="Retopologize a static GLB; face budget is required."
    )
    retopology_parser.add_argument("modelUrl")
    retopology_parser.add_argument("output_path", nargs="?")
    retopology_parser.add_argument("--face-limit", type=int, required=True, dest="faceLimit")
    retopology_parser.add_argument("--triangle", action="store_true")
    retopology_parser.add_argument("--bake-textures", action="store_true", dest="bakeTextures")
    retopology_parser.add_argument("--texture-size", type=int, default=2048, dest="textureSize")
    retopology_parser.add_argument("--content-id", dest="content_id")
    add_poll_arguments(retopology_parser)
    resume_retopology_parser = subparsers.add_parser(
        "retopology-result", help="Resume polling/downloading an existing retopology task."
    )
    resume_retopology_parser.add_argument("task_id")
    resume_retopology_parser.add_argument("output_path", nargs="?")
    resume_retopology_parser.add_argument("--bake-textures", action="store_true", dest="bakeTextures")
    add_poll_arguments(resume_retopology_parser)

    articulation_parser = subparsers.add_parser("articulation", help="Add joints and motion to a GLB model.")
    articulation_parser.add_argument("glbUrl")
    articulation_parser.add_argument("output_path", nargs="?")
    articulation_parser.add_argument("--prompt", required=True)
    articulation_parser.add_argument("--submit-only", action="store_true")
    add_poll_arguments(articulation_parser)
    articulation_result_parser = subparsers.add_parser("articulation-result", help="Resume an articulation task without creating it again.")
    articulation_result_parser.add_argument("task_id")
    articulation_result_parser.add_argument("output_path", nargs="?")
    add_poll_arguments(articulation_result_parser)

    export_parser = subparsers.add_parser(
        "export", help="Export a Lux3D ZIP or GLB URL to other formats."
    )
    export_parser.add_argument("modelUrl", help="Accessible .zip or .glb URL")
    export_parser.add_argument(
        "output_path", nargs="?", help="Optional output path or filename base"
    )
    export_parser.add_argument(
        "--format",
        dest="outputFormat",
        action="append",
        choices=sorted(EXPORT_FORMATS),
        default=None,
    )
    add_poll_arguments(export_parser)

    rig_parser = subparsers.add_parser("auto-rig", help="Create auto-rig and return its task ID before querying or delivery.")
    rig_parser.add_argument("modelUrl", help="Public HTTPS character GLB URL")
    retarget_parser = subparsers.add_parser("retarget", help="Create one animation task and return its task ID before querying or delivery.")
    retarget_parser.add_argument("rigModelUrl", help="Public HTTPS rigged character GLB URL")
    retarget_parser.add_argument("--animation-id", dest="animationIds", action="append", required=True, choices=ANIMATION_IDS)
    retarget_parser.add_argument("--output-mode", dest="animationOutputMode", choices=sorted(ANIMATION_OUTPUT_MODES), default="separate")
    retarget_parser.add_argument("--format", dest="outFormat", choices=sorted(ANIMATION_FORMATS), default="glb")
    retarget_parser.add_argument("--animate-in-place", dest="animateInPlace", action="store_true")

    for create_parser in (image_parser, text_parser, material_parser, four_view_parser, export_parser, rig_parser, retarget_parser):
        create_parser.add_argument(
            "--content-id", dest="content_id",
            help="Current quoteId for generation correlation; not spending authorization",
        )

    query_parser = subparsers.add_parser("query", help="Query one task once.")
    query_parser.add_argument("task_id")

    list_parser = subparsers.add_parser(
        "list", help="List generation tasks for the current account."
    )
    list_parser.add_argument("--page", type=int, default=1)
    list_parser.add_argument("--pagesize", type=int, default=20)
    list_parser.add_argument(
        "--status",
        type=int,
        choices=sorted(TASK_LIST_FILTER_STATUSES),
        default=None,
    )
    list_parser.add_argument("--starttime", type=int, default=None)
    list_parser.add_argument("--endtime", type=int, default=None)
    return parser


def print_result(result):
    """Print a CLI result without Python representation noise."""
    if isinstance(result, (dict, list, tuple)):
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(result)


def main():
    """Command-line entry point."""
    parser = build_parser()
    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        raise SystemExit(1)

    common = {"base_url": args.base_url, "region": args.region}
    if args.command in {"image", "text", "material", "four-view", "export", "auto-rig", "retarget"}:
        common["content_id"] = args.content_id
    if args.command == "image":
        image_urls = [args.img] + list(args.imageViews or [])
        image_input = (
            {"img": image_urls[0]} if len(image_urls) == 1 else {"imgs": image_urls}
        )
        result = generate_3d_model(
            output_path=args.output_path,
            version=args.version,
            faceCount=args.faceCount,
            outputFormat=args.outputFormat,
            enablePbr=args.enablePbr,
            aiPredictSize=args.aiPredictSize,
            customSize=args.customSize,
            max_attempts=args.max_attempts,
            interval=args.interval,
            **image_input,
            **common,
        )
    elif args.command == "text":
        result = generate_text_to_3d(
            args.prompt,
            output_path=args.output_path,
            version=args.version,
            style=args.style,
            img=args.img,
            faceCount=args.faceCount,
            outputFormat=args.outputFormat,
            enablePbr=args.enablePbr,
            aiPredictSize=args.aiPredictSize,
            customSize=args.customSize,
            max_attempts=args.max_attempts,
            interval=args.interval,
            **common,
        )
    elif args.command == "material":
        result = generate_material_transfer(
            args.img,
            args.meshUrl,
            output_path=args.output_path,
            version=args.version,
            outputFormat=args.outputFormat,
            aiPredictSize=args.aiPredictSize,
            customSize=args.customSize,
            max_attempts=args.max_attempts,
            interval=args.interval,
            **common,
        )
    elif args.command == "four-view":
        result = generate_four_views(
            args.img,
            prompt=args.prompt,
            max_attempts=args.max_attempts,
            interval=args.interval,
            **common,
        )
    elif args.command == "articulation":
        if args.submit_only:
            if args.output_path is not None:
                parser.error("--submit-only cannot be used with output_path")
            result = create_articulation_animation_task(args.glbUrl, args.prompt, **common)
        else:
            result = generate_articulation_animation(
                args.glbUrl, args.prompt, args.output_path,
                max_attempts=args.max_attempts, interval=args.interval, **common,
            )
    elif args.command == "articulation-result":
        result = resume_articulation_animation(
            args.task_id, args.output_path,
            max_attempts=args.max_attempts, interval=args.interval, **common,
        )
    elif args.command == "retopology":
        result = generate_mesh_retopology(
            args.modelUrl, args.faceLimit, args.output_path, quad=not args.triangle,
            bakeTextures=args.bakeTextures, textureSize=args.textureSize,
            base_url=args.base_url, region=args.region, content_id=args.content_id,
            max_attempts=args.max_attempts, interval=args.interval,
        )
    elif args.command == "retopology-result":
        result = resume_mesh_retopology(
            args.task_id, args.output_path, bakeTextures=args.bakeTextures,
            base_url=args.base_url, region=args.region,
            max_attempts=args.max_attempts, interval=args.interval,
        )
    elif args.command == "export":
        result = generate_multi_format_export(
            args.modelUrl,
            output_path=args.output_path,
            outputFormat=args.outputFormat,
            max_attempts=args.max_attempts,
            interval=args.interval,
            **common,
        )
    elif args.command == "auto-rig":
        result = {"taskId": create_auto_rig_task(args.modelUrl, **common)}
    elif args.command == "retarget":
        result = {"taskId": create_animation_retarget_task(args.rigModelUrl, args.animationIds, animationOutputMode=args.animationOutputMode, outFormat=args.outFormat, animateInPlace=args.animateInPlace, **common)}
    elif args.command == "query":
        result = get_task(args.task_id, **common)
    elif args.command == "list":
        result = list_tasks(
            page=args.page,
            pagesize=args.pagesize,
            status=args.status,
            starttime=args.starttime,
            endtime=args.endtime,
            **common,
        )
    else:
        parser.error(f"Unknown command: {args.command}")
        return
    print_result(result)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, TimeoutError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise SystemExit(1)
