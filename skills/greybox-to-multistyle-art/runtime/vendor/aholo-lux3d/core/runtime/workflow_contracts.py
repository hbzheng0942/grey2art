"""Platform-neutral M01 workflow contracts and validation helpers."""

from __future__ import annotations

import dataclasses
import datetime
import hashlib
import json
import re
from typing import Any, Mapping


WORKFLOW_CONTRACT = "lux3d-workflow/v2"
CREATE_PATHS = {
    "articulation-animation": "/lux3d/v1/articulation-animation/task/create",
    "mesh-retopology": "/lux3d/v1/mesh-retopology/task/create",
    "image-to-3d": "/lux3d/v1/generate/img-to-3d/task/create",
    "text-to-3d": "/lux3d/v1/generate/text-to-3d/task/create",
    "material-transfer": "/lux3d/v1/generate/material-transfer/task/create",
    "four-view": "/lux3d/v1/generate/image-to-four-view/task/create",
    "export": "/lux3d/v1/multi-format-export/task/create",
    "auto-rig": "/lux3d/v1/animations/rig/task/create",
    "animation-retarget": "/lux3d/v1/animations/retarget/task/create",
}
SUBMISSION_CONTEXT_FIELDS = {
    "accountRef",
    "source",
    "stepId",
    "attemptId",
    "requestKey",
    "uniqueId",
    "uniqueIdExpiresAt",
    "quoteId",
    "quoteExpiresAt",
    "estimatedCredits",
    "requestDigest",
    "retryCount",
}
LOCAL_ID_PATTERN = re.compile(r"[A-Za-z0-9._:-]{1,200}")
CALL_CONTEXT_ID_PATTERN = re.compile(r"ctx_[0-9a-f]{32}")
QUOTE_ID_PATTERN = re.compile(r"quote_[0-9a-f]{32}")


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc)


def parse_datetime(value, field_name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be an ISO-8601 date-time")
    text = value.strip().replace("Z", "+00:00")
    # Java timestamps can contain nanoseconds; older Python accepts only
    # 3 or 6 fractional digits. Normalize a parsing copy, preserving the offset.
    fraction = re.search(
        r"[Tt ][0-9]{2}:[0-9]{2}:[0-9]{2}\.([0-9]+)(?=[+-][0-9]{2}:[0-9]{2}$)",
        text,
    )
    if fraction:
        digits = fraction.group(1)
        if len(digits) > 9:
            raise ValueError(f"{field_name} must be an ISO-8601 date-time")
        # Truncate rather than round, so an expiry is never extended.
        micros = digits[:6].ljust(6, "0")
        text = text[:fraction.start(1)] + micros + text[fraction.end(1):]
    try:
        parsed = datetime.datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO-8601 date-time") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field_name} must include a timezone")
    try:
        return parsed.astimezone(datetime.timezone.utc)
    except OverflowError as exc:
        raise ValueError(f"{field_name} is outside the supported UTC date-time range") from exc


def canonical_digest(value):
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def billable_request(request):
    operation = request.get("operation")
    if operation not in CREATE_PATHS:
        raise ValueError("request operation has no billable create path")
    excluded = {
        "submission",
        "outputBasename",
        "target",
        "operation",
        "region",
    }
    return {
        "endpoint": {
            "method": "POST",
            "path": CREATE_PATHS[operation],
        },
        "parameters": {
            "pathParameters": {},
            "queryParameters": {},
            "body": {
                key: value
                for key, value in request.items()
                if key not in excluded and value is not None
            },
        },
    }


def request_digest(request):
    return canonical_digest(billable_request(request))


def generation_port_request(request):
    """Build M02 input with the quote event ID as generation contentId."""
    context = request.get("submission")
    if not isinstance(context, Mapping):
        raise ValueError("submission context is required")
    result = {
        key: value
        for key, value in request.items()
        if key not in {"submission", "outputBasename", "target"}
    }
    result["uniqueId"] = context["uniqueId"]
    if request["operation"] != "articulation-animation":
        result["contentId"] = context["quoteId"]
    result["workflowContext"] = {
        "accountRef": context["accountRef"],
        "source": context["source"],
        "stepId": context["stepId"],
        "attemptId": context["attemptId"],
        "requestKey": context["requestKey"],
        "quoteId": context["quoteId"],
        "requestDigest": context["requestDigest"],
        "retryCount": context["retryCount"],
    }
    return result


def validate_submission_context(request, now=None):
    context = request.get("submission")
    if not isinstance(context, dict):
        raise ValueError("submission context is required for a paid create request")
    unknown = set(context) - SUBMISSION_CONTEXT_FIELDS
    missing = SUBMISSION_CONTEXT_FIELDS - set(context)
    if unknown:
        raise ValueError(
            "Unsupported submission fields: " + ", ".join(sorted(unknown))
        )
    if missing:
        raise ValueError(
            "Missing submission fields: " + ", ".join(sorted(missing))
        )
    for field in (
        "accountRef",
        "stepId",
        "attemptId",
        "requestKey",
        "uniqueId",
        "quoteId",
        "requestDigest",
    ):
        if not isinstance(context[field], str) or not context[field].strip():
            raise ValueError(f"submission.{field} must be a non-empty string")
    for field in ("accountRef", "stepId", "attemptId", "requestKey"):
        if not LOCAL_ID_PATTERN.fullmatch(context[field]):
            raise ValueError(
                f"submission.{field} must be an opaque identifier"
            )
    if not CALL_CONTEXT_ID_PATTERN.fullmatch(context["uniqueId"]):
        raise ValueError("submission.uniqueId must be a valid ctx_ identifier")
    if not QUOTE_ID_PATTERN.fullmatch(context["quoteId"]):
        raise ValueError("submission.quoteId must be a valid quote_ identifier")
    source = context["source"]
    if (
        not isinstance(source, int)
        or isinstance(source, bool)
        or source not in (1, 2, 3, 4, 100)
    ):
        raise ValueError("submission.source must be one of 1, 2, 3, 4, or 100")
    if not isinstance(context["estimatedCredits"], int) or isinstance(
        context["estimatedCredits"], bool
    ):
        raise ValueError("submission.estimatedCredits must be a non-negative integer")
    if context["estimatedCredits"] < 0:
        raise ValueError("submission.estimatedCredits must be a non-negative integer")
    retry_count = context["retryCount"]
    if not isinstance(retry_count, int) or isinstance(retry_count, bool):
        raise ValueError("submission.retryCount must be 0 or 1")
    if retry_count not in (0, 1):
        raise ValueError("submission.retryCount must be 0 or 1")

    current = now or utc_now()
    unique_expiry = parse_datetime(
        context["uniqueIdExpiresAt"], "submission.uniqueIdExpiresAt"
    )
    quote_expiry = parse_datetime(
        context["quoteExpiresAt"], "submission.quoteExpiresAt"
    )
    if unique_expiry <= current:
        raise ValueError("submission uniqueId has expired")
    if quote_expiry <= current:
        raise ValueError("submission quote has expired")
    actual_digest = request_digest(request)
    if context["requestDigest"] != actual_digest:
        raise ValueError("submission quote does not match the normalized request")
    return context


@dataclasses.dataclass(frozen=True)
class SubmissionIntent:
    account_ref: str
    source: int
    step_id: str
    attempt_id: str
    request_key: str
    operation: str
    region: str
    unique_id: str
    quote_id: str
    request_digest: str
    estimated_credits: int
    retry_count: int


@dataclasses.dataclass(frozen=True)
class SubmissionDecision:
    allowed: bool
    reason: str
    user_event_ref: str | None = None


@dataclasses.dataclass(frozen=True)
class SubmissionVerification:
    verified: bool
    reason: str


@dataclasses.dataclass(frozen=True)
class SubmissionReservation:
    reserved: bool
    reason: str


def build_submission_intent(request):
    context = request["submission"]
    return SubmissionIntent(
        account_ref=context["accountRef"],
        source=context["source"],
        step_id=context["stepId"],
        attempt_id=context["attemptId"],
        request_key=context["requestKey"],
        operation=request["operation"],
        region=request["region"],
        unique_id=context["uniqueId"],
        quote_id=context["quoteId"],
        request_digest=context["requestDigest"],
        estimated_credits=context["estimatedCredits"],
        retry_count=context["retryCount"],
    )


def persistable_submission_context(context):
    return {
        "accountRef": context["accountRef"],
        "source": context["source"],
        "stepId": context["stepId"],
        "attemptId": context["attemptId"],
        "requestKey": context["requestKey"],
        "uniqueId": context["uniqueId"],
        "uniqueIdExpiresAt": context["uniqueIdExpiresAt"],
        "quoteId": context["quoteId"],
        "quoteExpiresAt": context["quoteExpiresAt"],
        "estimatedCredits": context["estimatedCredits"],
        "requestDigest": context["requestDigest"],
        "retryCount": context["retryCount"],
    }


def quote_call_plan_digest(calls: Mapping[str, Mapping[str, Any]]):
    if not isinstance(calls, Mapping) or not calls:
        raise ValueError("quote call plan must be a non-empty map")
    if len(calls) > 50:
        raise ValueError("quote call plan must contain no more than 50 items")
    validated_entries = []
    for sequence, call in calls.items():
        if (
            not isinstance(sequence, str)
            or not re.fullmatch(r"[1-9][0-9]{0,5}", sequence)
            or not isinstance(call, Mapping)
        ):
            raise ValueError(
                "quote call plan entries must use 1-6 digit positive numeric string keys"
            )
        validated_entries.append((sequence, call))
    normalized = {}
    for sequence, call in sorted(validated_entries, key=lambda item: int(item[0])):
        normalized[str(sequence)] = normalize_quote_call(call)
    return canonical_digest(normalized)


def normalize_quote_call(call):
    unknown = set(call) - {"endpoint", "parameters"}
    if unknown:
        raise ValueError(
            "Unsupported quote call fields: " + ", ".join(sorted(unknown))
        )
    endpoint = call.get("endpoint")
    parameters = call.get("parameters")
    if not isinstance(endpoint, Mapping):
        raise ValueError("quote call endpoint must be an object")
    endpoint_unknown = set(endpoint) - {"method", "path"}
    if endpoint_unknown:
        raise ValueError(
            "Unsupported quote endpoint fields: "
            + ", ".join(sorted(endpoint_unknown))
        )
    method = str(endpoint.get("method") or "").strip().upper()
    path = endpoint.get("path")
    if method != "POST":
        raise ValueError("quote call method must be POST")
    if (
        not isinstance(path, str)
        or not path.startswith("/lux3d/v1/")
        or path.endswith("/")
        or any(token in path for token in ("://", "?", "#", "..", "\\", "//"))
    ):
        raise ValueError("quote call path must be a canonical /lux3d/v1/ path")
    if not isinstance(parameters, Mapping):
        raise ValueError("quote call parameters must be an object")
    parameter_unknown = set(parameters) - {
        "pathParameters",
        "queryParameters",
        "body",
    }
    if parameter_unknown:
        raise ValueError(
            "Unsupported quote parameter fields: "
            + ", ".join(sorted(parameter_unknown))
        )
    path_parameters = parameters.get("pathParameters", {})
    query_parameters = parameters.get("queryParameters", {})
    body = parameters.get("body", {})
    if not isinstance(path_parameters, Mapping):
        raise ValueError("quote pathParameters must be an object")
    if not isinstance(query_parameters, Mapping):
        raise ValueError("quote queryParameters must be an object")
    if not isinstance(body, Mapping):
        raise ValueError("quote body must be an object")
    return {
        "endpoint": {"method": method, "path": path},
        "parameters": {
            "pathParameters": dict(path_parameters),
            "queryParameters": dict(query_parameters),
            "body": dict(body),
        },
    }


def validate_assembly_request(request):
    if not isinstance(request, Mapping):
        raise ValueError("assembly request must be an object")
    for field in ("objects", "instances"):
        if not isinstance(request.get(field), list) or not request[field]:
            raise ValueError(f"assembly.{field} must be a non-empty list")
    for field in ("coordinateSystem", "unit", "targetFormat"):
        if not isinstance(request.get(field), str) or not request[field].strip():
            raise ValueError(f"assembly.{field} must be a non-empty string")

    asset_refs = set()
    object_ids = set()
    for index, item in enumerate(request["objects"]):
        if not isinstance(item, Mapping):
            raise ValueError(f"assembly.objects[{index}] must be an object")
        object_id = item.get("objectId")
        asset_ref = item.get("assetRef")
        if not isinstance(object_id, str) or not object_id:
            raise ValueError(f"assembly.objects[{index}].objectId is required")
        if object_id in object_ids:
            raise ValueError(f"duplicate assembly objectId: {object_id}")
        object_ids.add(object_id)
        if not isinstance(asset_ref, str) or not asset_ref:
            raise ValueError(f"assembly.objects[{index}].assetRef is required")
        asset_refs.add(asset_ref)

    instance_ids = set()
    parents = {}
    for index, item in enumerate(request["instances"]):
        if not isinstance(item, Mapping):
            raise ValueError(f"assembly.instances[{index}] must be an object")
        instance_id = item.get("instanceId")
        asset_ref = item.get("assetRef")
        if not isinstance(instance_id, str) or not instance_id:
            raise ValueError(f"assembly.instances[{index}].instanceId is required")
        if instance_id in instance_ids:
            raise ValueError(f"duplicate assembly instanceId: {instance_id}")
        instance_ids.add(instance_id)
        parent_id = item.get("parentInstanceId")
        if parent_id is not None and (
            not isinstance(parent_id, str) or not parent_id
        ):
            raise ValueError(
                f"assembly.instances[{index}].parentInstanceId must be a string"
            )
        parents[instance_id] = parent_id
        if asset_ref not in asset_refs:
            raise ValueError(
                f"assembly.instances[{index}].assetRef does not reference an object asset"
            )
        transform = item.get("transform")
        if not isinstance(transform, Mapping):
            raise ValueError(f"assembly.instances[{index}].transform is required")
        for field in ("translation", "rotation", "scale"):
            values = transform.get(field)
            if (
                not isinstance(values, list)
                or len(values) != 3
                or any(
                    not isinstance(value, (int, float))
                    or isinstance(value, bool)
                    for value in values
                )
            ):
                raise ValueError(
                    f"assembly.instances[{index}].transform.{field} must contain three numbers"
                )
        if any(value <= 0 for value in transform["scale"]):
            raise ValueError(
                f"assembly.instances[{index}].transform.scale must be positive"
            )
        if transform.get("rotationUnit") not in {"degree", "radian"}:
            raise ValueError(
                f"assembly.instances[{index}].transform.rotationUnit must be degree or radian"
            )
    for instance_id, parent_id in parents.items():
        if parent_id is None:
            continue
        if parent_id not in instance_ids:
            raise ValueError(
                f"assembly parent instance does not exist: {parent_id}"
            )
        if parent_id == instance_id:
            raise ValueError("assembly instance cannot be its own parent")
        seen = {instance_id}
        cursor = parent_id
        while cursor is not None:
            if cursor in seen:
                raise ValueError("assembly instance hierarchy must be acyclic")
            seen.add(cursor)
            cursor = parents[cursor]
    return request
