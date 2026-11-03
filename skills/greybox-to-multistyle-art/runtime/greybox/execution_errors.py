"""Safe action errors shared by hosts, transports and the durable dispatcher.

An action being retryable never grants permission to repeat an uncertain POST.
Messages below are local constants; remote bodies and credentials stay private.
"""
from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import math
import re
import time


ACCEPTANCE = {"not_accepted", "accepted", "unknown"}
CATEGORIES = {"capacity", "rate_limit", "network", "timeout", "permanent", "capability", "protocol", "local"}
MESSAGES = {
    "capacity": "The account generation pool is full; wait for capacity.",
    "rate_limit": "The request rate is limited; retain the task and respect its cooldown.",
    "network": "The transport did not finish; preserve the original attempt.",
    "timeout": "The action exceeded its deadline; preserve the original attempt.",
    "permanent": "The operation was rejected; inspect the bound request before continuing.",
    "capability": "The selected execution route does not support this action.",
    "protocol": "The operation did not return a valid receipt; preserve its original attempt.",
    "local": "A local operation is temporarily unavailable; preserve the attempt and retry when ready.",
}


def retry_after(value, now=None):
    """Accept HTTP delay seconds or an HTTP-date without exposing header text."""
    if value is None or isinstance(value, bool):
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        try:
            stamp = parsedate_to_datetime(str(value))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            seconds = stamp.timestamp() - (time.time() if now is None else now)
        except (TypeError, ValueError, OverflowError):
            return None
    return max(0.0, seconds) if math.isfinite(seconds) and seconds <= 31_536_000 else None


def safe_code(value, default="EXECUTION_ACTION_FAILED"):
    text = str(value) if value is not None else default
    return text if re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", text) else default


def classify_error(error, action):
    """Preserve explicit rejection semantics, fail closed on unknown creation."""
    code = safe_code(getattr(error, "code", None))
    provider_code = safe_code(getattr(error, "provider_code", None), code)
    category = getattr(error, "category", None)
    combined = (code + " " + provider_code).upper()
    if category not in CATEGORIES:
        if "CONCURRENCY" in combined or "CAPACITY" in combined:
            category = "capacity"
        elif code in {"429", "IMAGE_HTTP_429"} or "RATE_LIMIT" in combined:
            category = "rate_limit"
        elif isinstance(error, TimeoutError) or "TIMEOUT" in combined or "DEADLINE" in combined:
            category = "timeout"
        elif "UNSUPPORTED" in combined or "CAPABILITY" in combined:
            category = "capability"
        elif isinstance(error, OSError) or "TRANSPORT" in combined or "QUERY_FAILED" in combined:
            category = "network"
        elif code == "LIVE_QUOTE_FAILED" and getattr(error, "retryable", False):
            category = "network"
        elif getattr(error, "unknown_submission", None) is True:
            category = "protocol"
        else:
            category = "permanent"
    acceptance = getattr(error, "acceptance", None)
    if acceptance not in ACCEPTANCE:
        if action != "submit":
            acceptance = "accepted"
        elif getattr(error, "unknown_submission", None) is False:
            acceptance = "not_accepted"
        else:
            acceptance = "unknown"
    result = {"code": code, "provider_code": provider_code, "category": category,
              "acceptance": acceptance, "message": MESSAGES[category]}
    delay = retry_after(getattr(error, "retry_after", None))
    if delay is not None:
        result["retry_after"] = delay
    return result


def response_error(response, action):
    """Normalize a failed adapter receipt using only explicit acceptance facts."""
    if not isinstance(response, dict):
        response = {}
    detail = response.get("error", {})
    detail = detail if isinstance(detail, dict) else {}
    error = RuntimeError("Adapter returned a failed receipt")
    error.code = detail.get("code", response.get("code", "ADAPTER_RECEIPT_FAILED"))
    error.provider_code = detail.get("provider_code")
    error.category = detail.get("category")
    error.acceptance = detail.get("acceptance", response.get("acceptance"))
    error.retry_after = detail.get("retry_after", response.get("retry_after"))
    unknown = detail.get("unknown_submission", detail.get("unknownSubmission",
              response.get("unknown_submission", response.get("unknownSubmission"))))
    if type(unknown) is bool:
        error.unknown_submission = unknown
    return classify_error(error, action)
