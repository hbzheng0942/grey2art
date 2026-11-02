"""Immutable plugin collection requests and local task journal. Author: yinjie."""
from __future__ import annotations

import copy
import json
import os
import sqlite3
import sys
import uuid
from pathlib import Path

JSON_FIELDS = {"context", "userInputs", "attachments", "quoteIds", "authorizations",
               "toolCalls", "coverage", "result", "execution", "consent"}
COMMON_FIELDS = {"pluginTaskId", "uniqueId", "pluginVersion", "agentName", "harnessName",
                 "modelName", "clientRegion", "startedAt", "installationTrackingId", "context"}
REVIEW_FIELDS = {"pluginTaskId", "planVersion", "plan", "userInputs", "attachments", "context"}
REPORT_FIELDS = COMMON_FIELDS | {"requestId", "reviewId", "quoteIds", "supersedesReportId",
    "authorizations", "toolCalls", "coverage", "result", "execution", "userInputs", "attachments",
    "plan", "planVersion"}
FEEDBACK_FIELDS = COMMON_FIELDS | {"requestId", "consent", "agentFeedback", "userFeedback", "summary"}


METADATA_FIELDS = (("modelName", "model", "LUX3D_MODEL_NAME"),
                   ("clientRegion", "clientRegion", "LUX3D_CLIENT_REGION"))
TASK_METADATA_FIELDS = {"model", "clientRegion", "inviteCode"}


def metadata_text(value):
    """Validate observed host metadata without inventing missing facts. Author: yinjie."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Collection metadata must be text")
    value = value.strip()
    if not value:
        return None
    if len(value) > 255 or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("Collection metadata must fit 255 characters without controls")
    return value


def invite_code_text(value):
    """Normalize collection-only invitation attribution. Author: yinjie."""
    if value is None:
        return None
    if not isinstance(value, str) or any(ord(char) < 32 or 127 <= ord(char) <= 159 for char in value):
        raise ValueError("Invite code must be text without control characters")
    value = value.strip()
    if len(value) > 255:
        raise ValueError("Invite code must fit 255 characters")
    return value or None


def installation_invite_code(skill_root):
    """Read optional attribution beside the installed Skill, never cwd. Author: yinjie."""
    path = Path(skill_root).resolve().parent / ".aholo-lux3d-installation.json"
    try:
        with path.open("rb") as stream:
            raw = stream.read(4097)
    except FileNotFoundError:
        return None
    if len(raw) > 4096:
        raise ValueError("Installation attribution configuration is too large")
    document = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(document, dict):
        raise ValueError("Installation attribution configuration must be an object")
    return invite_code_text(document.get("inviteCode"))


def command_metadata(args):
    result = {}
    for argument, field, variable in METADATA_FIELDS:
        name = "model_name" if argument == "modelName" else "client_region"
        value = metadata_text(getattr(args, name, None))
        if value is None:
            value = metadata_text(os.environ.get(variable))
        if value is not None:
            result[field] = value
    invite_code = invite_code_text(getattr(args, "installation_invite_code", None))
    if invite_code is not None:
        result["inviteCode"] = invite_code
    return result


def context_object(value, loader):
    if value is None:
        return {}
    result = loader(value) if isinstance(value, str) else value
    if not isinstance(result, dict):
        raise ValueError("Collection context must be an object")
    result = copy.deepcopy(result)
    if "inviteCode" in result:
        invite_code = invite_code_text(result["inviteCode"])
        if invite_code is None:
            result.pop("inviteCode")
        else:
            result["inviteCode"] = invite_code
    return result


def merge_metadata(request, loader, defaults=None, *, top_level=False):
    if not isinstance(request, dict):
        raise ValueError("Collection request must be an object")
    result = copy.deepcopy(request)
    context = context_object(result.get("context"), loader)
    defaults = defaults or {}
    for external, field, _ in METADATA_FIELDS:
        candidates = [result.get(external), context.get(field)]
        if external != field:
            candidates.append(context.get(external))
        values = [metadata_text(value) for value in candidates]
        selected = next((value for value in values if value is not None), None)
        if selected is None:
            selected = metadata_text(defaults.get(field))
        result.pop(external, None)
        if selected is not None:
            context[field] = selected
            if external != field and external in context:
                context[external] = selected
            if top_level:
                result[external] = selected
        else:
            context.pop(field, None)
            context.pop(external, None)
    invite_code = context.get("inviteCode") or invite_code_text(defaults.get("inviteCode"))
    if invite_code is not None:
        context["inviteCode"] = invite_code
    if context or "context" in result:
        result["context"] = context
    return result


def identifier(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 255:
        raise ValueError("Invalid collection identifier")
    return value


def dumps(value):
    return json.dumps(value, ensure_ascii=True, allow_nan=False, sort_keys=True, separators=(",", ":"))


def no_credentials(value):
    if isinstance(value, dict):
        for key, child in value.items():
            compact = ''.join(c for c in key.lower() if c.isalnum())
            if compact in {"apikey", "authorization", "accesstoken", "password", "cookie", "cookies", "xqhid", "userid"}:
                raise ValueError("Credentials are not collection content")
            no_credentials(child)
    elif isinstance(value, list):
        for child in value:
            no_credentials(child)


def wire_fields(request, allowed, loader):
    if not isinstance(request, dict) or set(request) - allowed:
        raise ValueError("Unsupported collection fields")
    result = {}
    for field, value in request.items():
        if value is None:
            continue
        if field in JSON_FIELDS:
            decoded = loader(value) if isinstance(value, str) else value
            if not isinstance(decoded, (dict, list)):
                raise ValueError("JSON content must be an object or array")
            if field in {"context", "consent"} and not isinstance(decoded, dict):
                raise ValueError("JSON content must be an object")
            if field == "context":
                # Validate without rewriting a previously frozen request. Author: yinjie.
                invite_code_text(decoded.get("inviteCode"))
            no_credentials(decoded)
            result[field] = dumps(decoded)
        elif field == "planVersion":
            if type(value) is not int or value <= 0:
                raise ValueError("Invalid plan version")
            result[field] = value
        elif not isinstance(value, str):
            raise ValueError("Text content must be a string")
        else:
            result[field] = value
    return result


def review_fields(request, loader):
    result = wire_fields(request, REVIEW_FIELDS, loader)
    identifier(result.get("pluginTaskId"))
    if "planVersion" not in result or not result.get("plan", "").strip():
        raise ValueError("Complete plan and revision are required")
    return result


def collection_fields(kind, request, loader):
    if kind not in {"report", "feedback"}:
        raise ValueError("Unsupported collection kind")
    result = wire_fields(request, REPORT_FIELDS if kind == "report" else FEEDBACK_FIELDS, loader)
    identifier(result.get("pluginTaskId"))
    identifier(result.get("requestId"))
    if kind == "feedback":
        consent = loader(result.get("consent", "{}"))
        if consent.get("granted") is not True:
            raise ValueError("Explicit consent is required")
        identifier(consent.get("feedbackVersion"))
    return result


class CollectionJournal:
    """One creative task per SQLite file; never rebind a task to another account."""

    def __init__(self, path):
        path = Path(path).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        try:
            with self.db:
                self.db.execute("BEGIN IMMEDIATE")
                self.db.execute("CREATE TABLE IF NOT EXISTS task (id INTEGER PRIMARY KEY CHECK(id=1), plugin_task_id TEXT NOT NULL, owner TEXT NOT NULL, metadata TEXT NOT NULL DEFAULT '{}')")
                if "metadata" not in {row[1] for row in self.db.execute("PRAGMA table_info(task)")}:
                    self.db.execute("ALTER TABLE task ADD COLUMN metadata TEXT NOT NULL DEFAULT '{}'")
                self.db.execute("CREATE TABLE IF NOT EXISTS submission (kind TEXT NOT NULL, request_id TEXT NOT NULL, body TEXT NOT NULL, receipt TEXT, PRIMARY KEY(kind, request_id))")
        except BaseException:
            self.db.close()
            raise

    def bind(self, owner):
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO task (id, plugin_task_id, owner) VALUES (1, ?, ?)", ("plugin_" + uuid.uuid4().hex, owner))
            task_id, original_owner = self.db.execute("SELECT plugin_task_id, owner FROM task WHERE id=1").fetchone()
            if original_owner != owner:
                raise ValueError("Collection task account or region changed")
        return task_id

    def environment(self, owner, updates=None):
        self.bind(owner)
        with self.db:
            saved = json.loads(self.db.execute("SELECT metadata FROM task WHERE id=1").fetchone()[0])
            if not isinstance(saved, dict) or set(saved) - TASK_METADATA_FIELDS:
                raise ValueError("Invalid task metadata")
            result = {field: (invite_code_text(value) if field == "inviteCode" else metadata_text(value))
                      for field, value in saved.items()}
            for field, value in (updates or {}).items():
                if field not in TASK_METADATA_FIELDS:
                    raise ValueError("Unknown task metadata")
                value = invite_code_text(value) if field == "inviteCode" else metadata_text(value)
                if value is not None:
                    result[field] = value
            result = {field: value for field, value in result.items() if value is not None}
            if result != saved:
                self.db.execute("UPDATE task SET metadata=? WHERE id=1", (dumps(result),))
        return result

    def freeze(self, kind, body, owner):
        task_id = self.bind(owner)
        if body["pluginTaskId"] != task_id:
            raise ValueError("Collection task mismatch")
        encoded = dumps(body)
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO submission(kind,request_id,body) VALUES (?,?,?)", (kind, body["requestId"], encoded))
            saved, receipt = self.db.execute("SELECT body,receipt FROM submission WHERE kind=? AND request_id=?", (kind, body["requestId"])).fetchone()
            if saved != encoded:
                raise ValueError("Frozen request changed; use a new requestId")
        if receipt is None:
            return None
        decoded = json.loads(receipt)
        if not isinstance(decoded, dict):
            raise ValueError("Invalid stored collection receipt")
        return decoded

    def acknowledge(self, kind, request_id, receipt):
        with self.db:
            self.db.execute("UPDATE submission SET receipt=? WHERE kind=? AND request_id=?", (dumps(receipt), kind, request_id))

    def request(self, kind, request_id, owner):
        self.bind(owner)
        row = self.db.execute("SELECT body FROM submission WHERE kind=? AND request_id=?", (kind, request_id)).fetchone()
        if row is None:
            raise ValueError("Unknown collection request")
        body = json.loads(row[0])
        if not isinstance(body, dict):
            raise ValueError("Invalid frozen collection request")
        # Identity is always re-injected by the authenticated client.
        body.pop("source", None)
        body.pop("agentName", None)
        return body

    def close(self):
        self.db.close()


def read_request(path, loader, limit):
    with Path(path).expanduser().open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("Collection request too large")
    return loader(raw.decode("utf-8-sig"))


def _close_journal(journal, error_type):
    # Keep the original request/network error if closing also fails.
    handling_error = sys.exc_info()[0] is not None
    try:
        journal.close()
    except (OSError, sqlite3.Error):
        if not handling_error:
            raise error_type("COLLECTION_JOURNAL_INVALID") from None


def _command_request(request, args, journal, owner, loader, error_type, *, top_level=False):
    try:
        defaults = journal.environment(owner)
    except (TypeError, ValueError, OSError, sqlite3.Error):
        raise error_type("COLLECTION_JOURNAL_INVALID") from None
    try:
        observed = command_metadata(args)
        # Attribution belongs to the task; a later installation must not relabel it. Author: yinjie.
        if defaults.get("inviteCode"):
            observed.pop("inviteCode", None)
        defaults.update(observed)
        enriched = merge_metadata(request, loader, defaults, top_level=top_level)
        context = enriched.get("context", {})
        metadata = {field: context[field] for field in TASK_METADATA_FIELDS if field in context}
    except (TypeError, ValueError, error_type):
        raise error_type("COLLECTION_REQUEST_INVALID") from None
    try:
        journal.environment(owner, metadata)
    except (TypeError, ValueError, OSError, sqlite3.Error):
        raise error_type("COLLECTION_JOURNAL_INVALID") from None
    return enriched


def execute_command(args, client, loader, limit, *, error_type=ValueError):
    try:
        journal = CollectionJournal(args.journal)
    except (ValueError, OSError, sqlite3.Error):
        raise error_type("COLLECTION_JOURNAL_INVALID") from None
    try:
        owner = client.collection_identity(region=args.region)
        try:
            task_id = journal.bind(owner)
        except (ValueError, OSError, sqlite3.Error):
            raise error_type("COLLECTION_JOURNAL_INVALID") from None
        if args.command == "init":
            metadata = _command_request({}, args, journal, owner, loader, error_type)
            return {"pluginTaskId": task_id, **metadata}
        kind = args.kind if args.command == "retry" else args.command
        if args.command == "retry":
            try:
                request = journal.request(kind, args.request_id, owner)
            except (ValueError, OSError, sqlite3.Error):
                raise error_type("COLLECTION_JOURNAL_INVALID") from None
        else:
            try:
                request = collection_fields(kind, read_request(args.request, loader, limit), loader)
            except (OSError, UnicodeError, TypeError, ValueError, error_type):
                raise error_type("COLLECTION_REQUEST_INVALID") from None
        if args.command != "retry":
            if request["pluginTaskId"] != task_id:
                raise error_type("COLLECTION_JOURNAL_INVALID")
            # Retry must retain even absent metadata from the first frozen body.
            request = _command_request(request, args, journal, owner, loader, error_type, top_level=True)
        return client.submit_collection(region=args.region, kind=kind,
                                        request=request, journal=journal)
    finally:
        _close_journal(journal, error_type)


def load_review(args, client, loader, limit, *, error_type=ValueError):
    review_path = getattr(args, "review", None)
    journal_path = getattr(args, "journal", None)
    if not review_path and not journal_path:
        return None
    if not review_path or not journal_path:
        raise error_type("COLLECTION_REQUEST_INVALID")
    try:
        review = review_fields(merge_metadata(read_request(review_path, loader, limit), loader), loader)
    except (OSError, UnicodeError, TypeError, ValueError, error_type):
        raise error_type("COLLECTION_REQUEST_INVALID") from None
    try:
        journal = CollectionJournal(journal_path)
    except (ValueError, OSError, sqlite3.Error):
        raise error_type("COLLECTION_JOURNAL_INVALID") from None
    try:
        owner = client.collection_identity(region=args.region)
        try:
            if review["pluginTaskId"] != journal.bind(owner):
                raise ValueError("Review task mismatch")
        except (ValueError, OSError, sqlite3.Error):
            raise error_type("COLLECTION_JOURNAL_INVALID") from None
        review = _command_request(review, args, journal, owner, loader, error_type)
    finally:
        _close_journal(journal, error_type)
    return review
