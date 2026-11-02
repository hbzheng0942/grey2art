"""M03 account and quote ports over authenticated public Aholo OpenAPI.

Only server facts are cached, in this process, for submission verification.
No local ID issuance, pricing, spending authorization or COS persistence.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import unicodedata
from typing import Mapping

import requests

import collection_support

from lux3d_client import REGION_BASE_URLS, normalize_region, validate_api_key
from workflow_contracts import (
    CALL_CONTEXT_ID_PATTERN,
    CREATE_PATHS,
    QUOTE_ID_PATTERN,
    SubmissionVerification,
    canonical_digest,
    normalize_quote_call,
    parse_datetime,
    utc_now,
)


ACCOUNT_PATH = "/lux3d/v1/account/balance"
QUOTE_PATH = "/lux3d/v1/pricing/openapi-quotes"
MAX_REQUEST_BYTES = 1024 * 1024
PARAMETER_FIELDS = ("pathParameters", "queryParameters", "body")
AGENT_PLACEHOLDER_CLIENT_SOURCE = 100
MAX_AGENT_NAME_LENGTH = 128
DEDICATED_AGENT_NAMES = {
    1: "codex",
    2: "claude-code",
    3: "deepseek",
    4: "workbuddy",
}
SUPPORTED_CLIENT_SOURCES = frozenset({1, 2, 3, 4, 100})
ACCOUNT_FIELDS = (
    "availableCredits", "trialCountMap", "member", "memberType", "snapshotAt",
    "uniqueId", "uniqueIdExpiresAt",
)
QUOTE_FIELDS = (
    "uniqueId", "quoteId", "source", "pricingScope", "quotedAt", "expiresAt",
    "estimatedCreditsTotal", "details",
)
ERROR_MESSAGES = {
    "COLLECTION_REQUEST_INVALID": "Invalid collection request or missing explicit feedback consent.",
    "COLLECTION_EVENT_CONFLICT": "This request ID already refers to different content.",
    "COLLECTION_JOURNAL_INVALID": "Collection journal unavailable, changed content, or task ownership mismatch.",
    "API_KEY_REQUIRED": "Configure the API key for the selected region.",
    "UNAUTHORIZED": "API key authentication failed; check the selected region and key.",
    "ACCOUNT_CONTEXT_REQUIRED": "Refresh the account balance before requesting a quote.",
    "ACCOUNT_MISMATCH": "Account credentials changed; refresh the balance and quote.",
    "GOAL_CONTEXT_INVALID": "Call context expired or changed; refresh the balance and quote.",
    "PRICING_REQUEST_INVALID": "Invalid quote plan; check item indices, endpoints and JSON parameters.",
    "PRICING_CONTEXT_UNTRUSTED": "Account, region or source context was rejected.",
    "PRICING_ITEM_NOT_QUOTABLE": "A requested operation cannot be priced; revise the plan.",
    "PRICING_UPSTREAM_UNAVAILABLE": "Pricing upstream is unavailable; try again later.",
    "PRICING_SERVICE_UNAVAILABLE": "Pricing service is unavailable; try again later.",
    "UPSTREAM_REQUEST_FAILED": "Account upstream is unavailable; try again later.",
    "INTERNAL_ERROR": "The OpenAPI service failed; try again later.",
    "RATE_LIMITED": "OpenAPI rate limit reached; try again later.",
    "NETWORK_UNAVAILABLE": "OpenAPI request did not complete; no automatic retry was made.",
    "OPENAPI_UNAVAILABLE": "The public OpenAPI route is unavailable.",
    "OPENAPI_REJECTED": "The public OpenAPI rejected the request.",
    "RESPONSE_INVALID": "OpenAPI response does not satisfy the account or quote contract.",
}
RETRYABLE_CODES = {
    "PRICING_UPSTREAM_UNAVAILABLE", "PRICING_SERVICE_UNAVAILABLE",
    "UPSTREAM_REQUEST_FAILED", "INTERNAL_ERROR", "RATE_LIMITED",
    "NETWORK_UNAVAILABLE", "OPENAPI_UNAVAILABLE",
}


class CommerceError(RuntimeError):
    """Safe error view: never echo API bodies, request parameters or credentials."""

    def __init__(self, code, *, details=None):
        self.code = code if code in ERROR_MESSAGES else "OPENAPI_REJECTED"
        self.message = ERROR_MESSAGES[self.code]
        self.retryable = self.code in RETRYABLE_CODES
        self.details = details or {}
        super().__init__(self.message)

    def to_dict(self):
        result = {"code": self.code, "message": self.message, "retryable": self.retryable}
        if self.details:
            result["details"] = copy.deepcopy(self.details)
        return result


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError("non-finite JSON number")


def load_items_json(text):
    """Parse CLI input without silently overwriting duplicate item/parameter keys."""
    try:
        if len(text.encode("utf-8")) > MAX_REQUEST_BYTES:
            raise ValueError("request size limit")
        return json.loads(text, object_pairs_hook=_unique_pairs, parse_constant=_reject_constant)
    except (TypeError, ValueError, RecursionError):
        raise CommerceError("PRICING_REQUEST_INVALID") from None


def _check_parameter_secrets(value):
    # Authentication belongs exclusively to the HTTP client, never the quote plan.
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str) or re.sub(r"[^A-Za-z0-9]", "", key).lower() in {
                "headers", "authorization", "apikey", "cookie", "cookies",
                "xqhid", "userid", "source", "uniqueid", "quoteid",
                "skucode", "pipelineid", "agentname",
            }:
                raise ValueError("untrusted parameter field")
            _check_parameter_secrets(child)
    elif isinstance(value, list):
        for child in value:
            _check_parameter_secrets(child)


def normalize_items(items):
    """Keep M01's object-based plan; accept wire JSON Strings at the input edge."""
    try:
        if not isinstance(items, Mapping) or any(not isinstance(key, str) for key in items):
            raise ValueError("invalid items")
        # JSON round-trip detaches caller data and rejects NaN before transmission.
        encoded = json.dumps(items, ensure_ascii=False, allow_nan=False)
        if len(encoded.encode("utf-8")) > MAX_REQUEST_BYTES:
            raise ValueError("request size limit")
        detached = json.loads(encoded)
        if not isinstance(detached, dict) or not 1 <= len(detached) <= 50:
            raise ValueError("invalid items")
        normalized = {}
        for sequence, call in detached.items():
            if not re.fullmatch(r"[1-9][0-9]{0,5}", sequence) or not isinstance(call, dict):
                raise ValueError("invalid item")
            parameters = call.get("parameters")
            if isinstance(parameters, dict):
                for field in PARAMETER_FIELDS:
                    if isinstance(parameters.get(field), str):
                        parameters[field] = load_items_json(parameters[field])
                _check_parameter_secrets(parameters)
            normalized[sequence] = normalize_quote_call(call)
        return dict(sorted(normalized.items(), key=lambda item: int(item[0])))
    except (TypeError, ValueError, RecursionError):
        raise CommerceError("PRICING_REQUEST_INVALID") from None


def serialize_items(items):
    return {
        sequence: {
            "endpoint": call["endpoint"],
            "parameters": {
                field: json.dumps(call["parameters"][field], ensure_ascii=False,
                                  allow_nan=False, separators=(",", ":"))
                for field in PARAMETER_FIELDS
            },
        }
        for sequence, call in items.items()
    }


def _credits(value):
    if type(value) is not int or value < 0:
        raise ValueError("invalid credits")


def _identifier(value, pattern):
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ValueError("invalid identifier")


def _collection_receipt(kind, data, error_code="RESPONSE_INVALID"):
    id_field = "reportId" if kind == "report" else "feedbackId"
    status_field = "receiptStatus" if kind == "report" else "submissionStatus"
    if (not isinstance(data, dict)
            or not re.fullmatch(kind + r"_[0-9a-f]{64}", str(data.get(id_field, "")))
            or data.get(status_field) != "ACCEPTED"
            or (kind == "report" and data.get("checkResult") != "OK")):
        raise CommerceError(error_code)
    receipt = {id_field: data[id_field], status_field: data[status_field]}
    if kind == "report":
        receipt["checkResult"] = data["checkResult"]
    return receipt


class CommerceClient:
    """One ecosystem's AccountPort, QuotePort and process-local QuoteVerificationPort.

    source is supplied by the ecosystem adapter, not by a user request.
    An accountRef is a local credential fingerprint, never a server userId.
    """

    def __init__(
        self,
        *,
        source,
        session=None,
        now=None,
        api_key=None,
        credential_provider=None,
        agent_name=None,
    ):
        if type(source) is not int or source not in SUPPORTED_CLIENT_SOURCES:
            raise ValueError("source must be one of 1, 2, 3, 4 or 100")
        if source == AGENT_PLACEHOLDER_CLIENT_SOURCE:
            if not isinstance(agent_name, str):
                raise ValueError("agent_name is required for Agent placeholder source 100")
            agent_name = agent_name.strip()
            if (
                not agent_name
                or len(agent_name) > MAX_AGENT_NAME_LENGTH
                or any(unicodedata.category(character) in {"Cc", "Cs"} for character in agent_name)
            ):
                raise ValueError(
                    "agent_name must be 1 to 128 characters after trimming and contain no controls or surrogates"
                )
        elif agent_name is not None:
            raise ValueError("agent_name cannot override a dedicated source mapping")
        if api_key is not None and credential_provider is not None:
            raise ValueError("Pass either api_key or credential_provider, not both")
        if credential_provider is not None and not callable(credential_provider):
            raise ValueError("credential_provider must be callable")
        self._source = source
        self._session = session or requests.Session()
        # Do not let .netrc replace the explicitly selected API key.
        self._session.trust_env = False
        self._now = now or utc_now
        self._api_key = api_key
        self._credential_provider = credential_provider
        self._agent_name = (
            agent_name
            if source == AGENT_PLACEHOLDER_CLIENT_SOURCE
            else DEDICATED_AGENT_NAMES[source]
        )
        self._accounts = {}
        self._quotes = {}

    @property
    def source(self):
        return self._source

    @property
    def agent_name(self):
        return self._agent_name

    def _credentials(self, region):
        try:
            key = validate_api_key(
                region,
                api_key=self._api_key,
                credential_provider=self._credential_provider,
            )
        except ValueError:
            raise CommerceError("API_KEY_REQUIRED") from None
        fingerprint = hashlib.sha256((region + "\0" + key).encode("utf-8")).hexdigest()
        return key, "account_" + fingerprint

    def _forget(self, region):
        self._accounts.pop(region, None)
        self._quotes = {key: value for key, value in self._quotes.items()
                        if value["region"] != region}

    def _request(self, method, region, path, key, *, params=None, body=None):
        try:
            # Region changes the public URL only. The international base owns
            # /global; body.items[*].endpoint.path remains /lux3d/v1/... .
            response = self._session.request(
                method, REGION_BASE_URLS[region] + path,
                headers={"Authorization": key, "Accept": "application/json",
                         "Content-Type": "application/json"},
                params=params, json=body, timeout=(10, 30), allow_redirects=False,
            )
        except requests.RequestException:
            raise CommerceError("NETWORK_UNAVAILABLE") from None
        try:
            if 300 <= response.status_code < 400:
                raise CommerceError("OPENAPI_REJECTED")
            try:
                envelope = response.json()
            except ValueError:
                envelope = None
            code = envelope.get("c") if isinstance(envelope, dict) else None
            if type(code) is str and code != "0" and code in ERROR_MESSAGES:
                errors = {}
                data = envelope.get("d")
                raw_errors = data.get("errors") if isinstance(data, dict) else None
                if isinstance(raw_errors, dict):
                    for index, error in raw_errors.items():
                        if (isinstance(index, str) and re.fullmatch(r"[1-9][0-9]{0,5}", index)
                                and isinstance(error, dict)):
                            item_code = error.get("code")
                            safe = CommerceError(item_code if isinstance(item_code, str) else "OPENAPI_REJECTED")
                            errors[index] = safe.to_dict()
                raise CommerceError(code, details=errors)
            if response.status_code in (401, 403):
                raise CommerceError("UNAUTHORIZED")
            if response.status_code == 429:
                raise CommerceError("RATE_LIMITED")
            if response.status_code == 404 or response.status_code >= 500:
                raise CommerceError("OPENAPI_UNAVAILABLE")
            if not 200 <= response.status_code < 300 or code != "0":
                raise CommerceError("OPENAPI_REJECTED" if code is not None else "RESPONSE_INVALID")
            if not isinstance(envelope.get("d"), dict):
                raise CommerceError("RESPONSE_INVALID")
            return envelope["d"]
        finally:
            response.close()

    def get_account(self, *, region, account_ref=None):
        region = normalize_region(region)
        try:
            key, actual_ref = self._credentials(region)
            if account_ref is not None and account_ref != actual_ref:
                raise CommerceError("ACCOUNT_MISMATCH")
            account_params = {"source": self.source}
            if self.source == AGENT_PLACEHOLDER_CLIENT_SOURCE:
                account_params["agentName"] = self.agent_name
            data = self._request("GET", region, ACCOUNT_PATH, key, params=account_params)
            account = {field: data[field] for field in ACCOUNT_FIELDS}
            _credits(account["availableCredits"])
            if type(account["member"]) is not bool or type(account["memberType"]) is not int:
                raise ValueError("invalid membership")
            trials = account["trialCountMap"]
            if trials is not None:
                if not isinstance(trials, dict):
                    raise ValueError("invalid trials")
                for name, amount in trials.items():
                    if not isinstance(name, str):
                        raise ValueError("invalid trial name")
                    _credits(amount)
            _identifier(account["uniqueId"], CALL_CONTEXT_ID_PATTERN)
            snapshot = parse_datetime(account["snapshotAt"], "snapshotAt")
            expiry = parse_datetime(account["uniqueIdExpiresAt"], "uniqueIdExpiresAt")
            if expiry <= self._now() or expiry <= snapshot:
                raise CommerceError("GOAL_CONTEXT_INVALID")
            account.update(accountRef=actual_ref, source=self.source, region=region)
        except (KeyError, TypeError, ValueError):
            self._forget(region)
            raise CommerceError("RESPONSE_INVALID") from None
        except CommerceError:
            self._forget(region)
            raise
        previous = self._accounts.get(region)
        if previous and (previous["uniqueId"] != account["uniqueId"]
                         or previous["accountRef"] != actual_ref):
            self._forget(region)
        self._accounts[region] = copy.deepcopy(account)
        self._prune_quotes()
        return copy.deepcopy(account)

    def create_quote(self, *, region, unique_id, items, review=None, context=None):
        region = normalize_region(region)
        normalized = normalize_items(items)
        try:
            review_body = {}
            if review is not None or context is not None:
                request = copy.deepcopy(review) if review is not None else {}
                if not isinstance(request, dict):
                    raise ValueError("Collection review must be an object")
                combined = collection_support.context_object(context, load_items_json)
                combined.update(collection_support.context_object(request.get("context"), load_items_json))
                if combined or "context" in request:
                    request["context"] = combined
                request = collection_support.merge_metadata(request, load_items_json)
                review_body = (collection_support.review_fields(request, load_items_json) if review is not None
                               else collection_support.wire_fields(request, {"context"}, load_items_json))
        except (TypeError, ValueError, CommerceError):
            raise CommerceError("COLLECTION_REQUEST_INVALID") from None
        try:
            key, account_ref = self._credentials(region)
            account = self._accounts.get(region)
            if account is None:
                raise CommerceError("ACCOUNT_CONTEXT_REQUIRED")
            if account["accountRef"] != account_ref:
                raise CommerceError("ACCOUNT_MISMATCH")
            if (unique_id != account["uniqueId"]
                    or parse_datetime(account["uniqueIdExpiresAt"], "uniqueIdExpiresAt") <= self._now()):
                raise CommerceError("GOAL_CONTEXT_INVALID")
            body = {"source": self.source, "uniqueId": unique_id, "items": serialize_items(normalized)}
            body["agentName"] = self.agent_name
            body.update(review_body)
            # requests' json= transport escapes Unicode by default.
            if len(json.dumps(body).encode("utf-8")) > MAX_REQUEST_BYTES:
                raise CommerceError("PRICING_REQUEST_INVALID")
            data = self._request("POST", region, QUOTE_PATH, key, body=body)
            quote = {field: data[field] for field in QUOTE_FIELDS}
            if review is not None:
                receipt = data.get("review")
                if (not isinstance(receipt, dict) or receipt.get("status") != "OK"
                        or not re.fullmatch(r"review_[0-9a-f]{32}", str(receipt.get("reviewId", "")))
                        or not isinstance(receipt.get("reason"), str)):
                    raise ValueError("Missing plan review receipt")
                quote["review"] = copy.deepcopy(receipt)
            _identifier(quote["quoteId"], QUOTE_ID_PATTERN)
            if (type(quote["source"]) is not int or quote["source"] != self.source
                    or quote["uniqueId"] != unique_id
                    or quote["pricingScope"] != "BEFORE_ACCOUNT_BENEFITS"):
                raise ValueError("quote context mismatch")
            _credits(quote["estimatedCreditsTotal"])
            details = quote["details"]
            if not isinstance(details, dict) or set(details) != set(normalized):
                raise ValueError("quote item mismatch")
            for amount in details.values():
                _credits(amount)
            if quote["estimatedCreditsTotal"] != sum(details.values()):
                raise ValueError("quote total mismatch")
            quoted_at = parse_datetime(quote["quotedAt"], "quotedAt")
            expires_at = parse_datetime(quote["expiresAt"], "expiresAt")
            if expires_at <= self._now() or expires_at <= quoted_at:
                raise ValueError("expired quote")
            if parse_datetime(account["uniqueIdExpiresAt"], "uniqueIdExpiresAt") <= self._now():
                raise CommerceError("GOAL_CONTEXT_INVALID")
        except (KeyError, TypeError, ValueError):
            raise CommerceError("RESPONSE_INVALID") from None
        except CommerceError as exc:
            if exc.code in {"API_KEY_REQUIRED", "ACCOUNT_MISMATCH", "GOAL_CONTEXT_INVALID",
                            "UNAUTHORIZED", "PRICING_CONTEXT_UNTRUSTED"}:
                self._forget(region)
            raise
        self._prune_quotes()
        self._quotes[quote["quoteId"]] = {
            "quote": copy.deepcopy(quote), "accountRef": account_ref, "region": region,
            "items": {sequence: {"digest": canonical_digest(call), "path": call["endpoint"]["path"]}
                      for sequence, call in normalized.items()},
        }
        return copy.deepcopy(quote)

    def collection_identity(self, *, region):
        region = normalize_region(region)
        _, account_ref = self._credentials(region)
        return region + ":" + str(self.source) + ":" + self.agent_name + ":" + account_ref

    def submit_collection(self, *, region, kind, request, journal):
        region = normalize_region(region)
        try:
            body = collection_support.collection_fields(kind, request, load_items_json)
            body["source"] = self.source
            body["agentName"] = self.agent_name
            if len(json.dumps(body).encode("utf-8")) > MAX_REQUEST_BYTES:
                raise ValueError("Request too large")
        except (TypeError, ValueError, CommerceError):
            raise CommerceError("COLLECTION_REQUEST_INVALID") from None
        key, account_ref = self._credentials(region)
        owner = region + ":" + str(self.source) + ":" + self.agent_name + ":" + account_ref
        try:
            receipt = journal.freeze(kind, body, owner)
        except (ValueError, OSError, collection_support.sqlite3.Error):
            raise CommerceError("COLLECTION_JOURNAL_INVALID") from None
        if receipt is not None:
            return _collection_receipt(kind, receipt, "COLLECTION_JOURNAL_INVALID")
        path = "/lux3d/v1/tasks/report" if kind == "report" else "/lux3d/v1/feedback/experience"
        data = self._request("POST", region, path, key, body=body)
        receipt = _collection_receipt(kind, data)
        try:
            journal.acknowledge(kind, body["requestId"], receipt)
        except (OSError, collection_support.sqlite3.Error):
            raise CommerceError("COLLECTION_JOURNAL_INVALID") from None
        return receipt

    def _prune_quotes(self):
        self._quotes = {
            quote_id: record for quote_id, record in self._quotes.items()
            if parse_datetime(record["quote"]["expiresAt"], "expiresAt") > self._now()
        }

    def verify_submission(self, intent):
        """Verify an observed quote, not user confirmation or a final debit price."""
        self._prune_quotes()
        record = self._quotes.get(intent.quote_id)
        if record is None:
            return SubmissionVerification(False, "quote was not observed or has expired; requote required")
        try:
            region = normalize_region(intent.region)
            _, actual_ref = self._credentials(region)
            account = self._accounts.get(region)
            quote = record["quote"]
            valid = (
                type(intent.source) is int and intent.source == self.source
                and region == record["region"] and account is not None
                and intent.account_ref == actual_ref == record["accountRef"]
                and intent.unique_id == quote["uniqueId"] == account["uniqueId"]
                and parse_datetime(account["uniqueIdExpiresAt"], "uniqueIdExpiresAt") > self._now()
                and type(intent.estimated_credits) is int
                and any(item["digest"] == intent.request_digest
                        and item["path"] == CREATE_PATHS.get(intent.operation)
                        and quote["details"][sequence] == intent.estimated_credits
                        for sequence, item in record["items"].items())
            )
        except (ValueError, CommerceError):
            valid = False
        return SubmissionVerification(bool(valid), "quote verified" if valid else "quote context or detail mismatch")

    def close(self):
        self._accounts.clear()
        self._quotes.clear()
        self._session.close()
