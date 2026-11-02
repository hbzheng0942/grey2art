"""Open supplier inventory and comparable, hash-bound production portfolios.

These contracts do not discover credentials, call networks, or grant spending
authority. Local command bridges are opt-in and never loaded from the knowledge
catalog. The existing Lux runner remains the only bundled submission runner.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import copy
import json
from pathlib import Path
import re
import subprocess

from .core import WorkflowError, digest, file_hash, require, safe_id, resolve_input
from . import account_profiles

CATALOG = Path(__file__).resolve().parents[2] / "references" / "supplier-catalog.json"
READ_ONLY = {"capabilities", "quote", "status"}
BRIDGE_METHODS = READ_ONLY | {"submit", "fetch"}


def _no_secrets(value):
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).lower().replace("_", "").replace("-", "")
            require(normalized not in {"apikey", "token", "accesstoken", "refreshtoken", "password", "credentials", "authorization", "secret"},
                    "Contracts must contain no credentials; use inherited local environment/keyring")
            _no_secrets(child)
    elif isinstance(value, list):
        for child in value:
            _no_secrets(child)


def _time(value):
    require(isinstance(value, str), "A timezone-aware ISO timestamp is required")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise WorkflowError("Invalid ISO timestamp") from None
    require(result.tzinfo is not None, "Timestamp must include a timezone")
    return result.astimezone(timezone.utc)


def _now(value=None):
    return _time(value) if isinstance(value, str) else value or datetime.now(timezone.utc)


def _number(value, label):
    require(not isinstance(value, bool), label + " must be a finite nonnegative number")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise WorkflowError(label + " must be a finite nonnegative number") from None
    require(result.is_finite() and result >= 0, label + " must be a finite nonnegative number")
    return result


def _text(value, label):
    require(isinstance(value, str) and bool(value.strip()), label + " is required")
    return value


def _evidence(record, base=None):
    require(isinstance(record, dict), "Evidence must be a hash-bound local file")
    path = Path(_text(record.get("path"), "Evidence path"))
    require(path.is_absolute() or base is not None, "Relative evidence requires an explicit base directory")
    path = path if path.is_absolute() else Path(base) / path
    require(path.is_file() and re.fullmatch(r"[0-9a-f]{64}", str(record.get("sha256", ""))) is not None,
            "Evidence must exist with a SHA-256")
    require(file_hash(path) == record["sha256"], "Evidence changed; refresh the corresponding verification or decision")
    return record


def _source(record, base=None):
    require(isinstance(record, dict), "A dated pricing/knowledge source is required")
    _time(record.get("checked_at"))
    if "path" in record:
        _evidence(record, base)
    else:
        require(isinstance(record.get("url"), str) and record["url"].startswith("https://"),
                "Source needs a HTTPS primary URL or hash-bound local evidence")


def _verification(record, base=None, now=None, account_profile_sha256=None):
    if record is None:
        return False
    require(isinstance(record, dict) and record.get("state") in {"unverified", "verified", "failed"},
            "Verification state must be unverified, verified or failed")
    if record["state"] != "verified":
        return False
    checked = _time(record.get("checked_at"))
    require(checked <= _now(now), "Verification cannot be dated in the future")
    _evidence(record.get("evidence"), base)
    expires = _time(record["expires_at"]) if record.get("expires_at") else None
    require(expires is None or expires > checked, "Verification expiry must follow its check")
    return (expires is None or expires > _now(now)) and (account_profile_sha256 is None or record.get("account_profile_sha256") == account_profile_sha256)


def validate_registry(document, base=None, now=None):
    require(isinstance(document, dict) and document.get("schema") == 1 and document.get("kind") == "supplier-registry",
            "Expected supplier-registry schema 1")
    _no_secrets(document)
    providers = document.get("providers")
    require(isinstance(providers, list), "providers must list every configured or desired supplier")
    seen = set()
    for provider in providers:
        require(isinstance(provider, dict) and safe_id(provider.get("id")) and provider["id"] not in seen,
                "Suppliers need unique open IDs")
        seen.add(provider["id"])
        _text(provider.get("label"), "Supplier label")
        require(type(provider.get("desired")) is bool and type(provider.get("configured")) is bool,
                "Record desired and configured independently")
        operations = provider.get("operations", [])
        require(isinstance(operations, list) and len(set(operations)) == len(operations) and all(safe_id(o) for o in operations),
                "Supplier operations need unique IDs; unsupported operations must remain absent")
        binding = provider.get("binding", {"kind": "catalog_only"})
        require(isinstance(binding, dict) and binding.get("kind") in {"catalog_only", "builtin_lux", "builtin_api", "command"},
                "Unknown supplier binding; use an explicitly reviewed local command adapter")
        require(binding.get("kind") != "builtin_lux" or provider["id"] == "lux3d", "The built-in binding is Lux only")
        if binding.get("kind") == "builtin_api":
            from .provider_adapter import BUILTINS
            require(provider["id"] in BUILTINS, "This built-in API ID is unsupported; custom suppliers use reviewed command adapters")
        if binding["kind"] == "command":
            argv = binding.get("argv")
            require(isinstance(argv, list) and 1 <= len(argv) <= 32 and all(isinstance(a, str) and a and "\x00" not in a for a in argv),
                    "Adapter argv must be an explicit argument list without shell expansion")
            require(Path(argv[0]).is_absolute() and Path(argv[0]).is_file(), "Adapter executable must be an existing absolute local file")
            adapter = Path(_text(binding.get("adapter_path"), "Adapter source path"))
            require(adapter.is_absolute() and adapter.is_file() and str(adapter) in argv,
                    "Adapter source must be an explicit absolute argv entry")
            require(file_hash(adapter) == binding.get("sha256"), "Local adapter changed; review and rebind its hash")
            require(binding.get("reviewed_local") is True, "External adapter requires explicit local review")
        profile = provider.get("account_profile")
        if profile is not None:
            require(binding.get("kind") == "builtin_api", "Account profiles currently bind dedicated built-in APIs; Lux keeps its regional bridge")
            account_profiles.validate(provider["id"], profile)
        verify = provider.get("verification", {})
        require(isinstance(verify, dict), "Invalid supplier verification inventory")
        _verification(verify.get("discovery"), base, now)
        _verification(verify.get("connection"), base, now)
        for section in ("operations", "native"):
            records = verify.get(section, {})
            require(isinstance(records, dict), "Operation/native verification must be keyed records")
            for operation, record in records.items():
                require(safe_id(operation), "Verification key must be a stable ID")
                require(section != "operations" or operation in operations, "Verified operation must be declared by the supplier")
                _verification(record, base, now)
        if provider.get("knowledge"):
            _source(provider["knowledge"], base)
        # Never accept credentials/endpoints in a distributable inventory.
        json.dumps(provider, allow_nan=False)
    return document


def inventory(document, base=None, now=None):
    validate_registry(document, base, now)
    rows = []
    for provider in document["providers"]:
        verify = provider.get("verification", {})
        profile_sha = account_profiles.profile_digest(provider["id"], provider["account_profile"]) if provider.get("account_profile") is not None else None
        connected = _verification(verify.get("connection"), base, now, profile_sha)
        operation_ready = [operation for operation in provider.get("operations", [])
                           if _verification(verify.get("operations", {}).get(operation), base, now, profile_sha)]
        binding = provider.get("binding", {}).get("kind", "catalog_only")
        rows.append({"id": provider["id"], "label": provider["label"], "desired": provider["desired"],
                     "configured": provider["configured"], "discovered": _verification(verify.get("discovery"), base, now),
                     "connection_verified": connected, "operations_verified": operation_ready,
                     "native_verified": [key for key, value in verify.get("native", {}).items() if _verification(value, base, now, profile_sha)],
                     "account_profile_sha256": profile_sha,
                     "binding": binding, "execution_ready": provider["configured"] and connected and binding != "catalog_only" and bool(operation_ready)})
    return {"ok": True, "registry_sha256": registry_digest(document), "inventory_sha256": digest(document), "suppliers": rows,
            "note": "Inventory is evidence inspection only; no credential discovery, provider calls or spending authorization."}


def portfolio_digest(document):
    return digest(document)


def registry_digest(document):
    """Bind routing identity without turning readiness renewal into new consent."""
    mutable = {"verification", "configured", "desired", "knowledge", "label", "notes"}
    providers = [{key: value for key, value in provider.items() if key not in mutable}
                 for provider in document.get("providers", [])]
    providers.sort(key=lambda provider: provider.get("id", ""))
    return digest({"schema": document.get("schema"), "kind": document.get("kind"), "providers": providers})


def _price(pricing, base=None, now=None):
    require(isinstance(pricing, dict) and pricing.get("kind") in {"firm_quote", "rate_card_estimate", "user_estimate"},
            "Label firm quotes separately from rate-card and user estimates")
    _source(pricing.get("source"), base)
    quoted = _time(pricing.get("quoted_at"))
    require(quoted <= _now(now), "Price cannot be dated in the future")
    expires = _time(pricing["expires_at"]) if pricing.get("expires_at") else None
    require(pricing["kind"] != "firm_quote" or expires is not None, "Firm quotes require an explicit expiry")
    require(expires is None or expires > quoted, "Price expiry must follow its quote")
    quantity = _number(pricing.get("quantity", 1), "Price quantity")
    require(quantity > 0, "Price quantity must be positive")
    credits = _number(pricing.get("unit_credits", 0), "Unit credits") * quantity
    wallet = pricing.get("wallet")
    require(not credits or safe_id(wallet), "Credit costs require a named wallet; never pool supplier credits")
    money = None
    currency = None
    if pricing.get("conversion"):
        conversion = pricing["conversion"]
        require(isinstance(conversion, dict), "Credit conversion must be a sourced object")
        _source(conversion.get("source"), base)
        amount = _number(conversion.get("amount_paid"), "Purchase amount")
        received = _number(conversion.get("credits_received"), "Usable credits received")
        require(received > 0, "Usable credits received must be positive")
        currency = conversion.get("currency")
        require(isinstance(currency, str) and re.fullmatch(r"[A-Z]{3}", currency), "Use an explicit ISO currency code")
        _text(conversion.get("basis"), "Conversion purchase SKU/allocation basis")
        money = credits * amount / received
    if "direct_money" in pricing:
        require(not credits, "Use direct money only for charges outside a credit wallet")
        direct = pricing["direct_money"]
        require(isinstance(direct, dict) and re.fullmatch(r"[A-Z]{3}", str(direct.get("currency", ""))), "Direct cost needs currency")
        money, currency = _number(direct.get("unit_amount"), "Direct money") * quantity, direct["currency"]
    cash_due = pricing.get("cash_due")
    if cash_due is not None:
        require(isinstance(cash_due, dict) and re.fullmatch(r"[A-Z]{3}", str(cash_due.get("currency", ""))), "Cash due needs currency")
        _number(cash_due.get("amount"), "Cash due")
        _text(cash_due.get("basis"), "Cash due basis")
    require(credits > 0 or money is not None or pricing.get("zero_cost_reason"), "Zero cost must be explicit; unknown is not free")
    return {"credits": credits, "wallet": wallet, "money": money, "currency": currency,
            "expired": expires is not None and expires <= _now(now), "cash_due": cash_due,
            "kind": pricing["kind"]}


def validate_portfolio(document, registry, base=None, now=None, for_execution=False, allow_qualification_probes=None, enforce_image_policy=True):
    validate_registry(registry, base, now)
    require(isinstance(document, dict) and document.get("schema") == 1 and document.get("kind") == "supplier-portfolio",
            "Expected supplier-portfolio schema 1")
    _no_secrets(document)
    require(document.get("registry_sha256") == registry_digest(registry), "Portfolio must bind the exact supplier routing identities")
    _text(document.get("recommendation_rationale"), "Recommended combination rationale")
    assets = document.get("required_assets")
    require(isinstance(assets, list) and assets and all(safe_id(a) for a in assets) and len(set(assets)) == len(assets),
            "Portfolio needs the unique complete asset scope")
    requirements = document.get("required_operations", {})
    require(isinstance(requirements, dict) and set(requirements).issubset(set(assets)), "Operation requirements must refer to scoped assets")
    require(all(isinstance(ops, list) and all(safe_id(op) for op in ops) for ops in requirements.values()), "Invalid required operation chain")
    options = document.get("options")
    require(isinstance(options, list) and options, "Present at least one feasible option; do not fabricate supplier alternatives")
    ids = [option.get("id") for option in options]
    require(all(safe_id(i) for i in ids) and len(set(ids)) == len(ids), "Portfolio option IDs must be unique")
    require(document.get("recommended_option") in ids, "Choose a recommended option explicitly")
    require(for_execution in (False, True) or for_execution in ids, "Execution must select a known option")
    allowed_probes = set(allow_qualification_probes or [])
    providers = {p["id"]: p for p in registry["providers"]}
    summaries = []
    wallet_owners = {}
    for option in options:
        _text(option.get("rationale"), "Option tradeoff rationale")
        entries = option.get("assets")
        require(isinstance(entries, list) and len(entries) == len(assets) and {a.get("asset_id") for a in entries} == set(assets),
                "Every option must cover the same complete asset scope exactly once")
        operations = option.get("operations", [])
        require(isinstance(operations, list), "Operation chain must be a list")
        operation_ids = [op.get("id") for op in operations]
        require(all(safe_id(i) for i in operation_ids) and len(set(operation_ids)) == len(operation_ids), "Unique operation IDs required")
        wallets, money, cash, unknown, expired, blocked, probes = {}, {}, {}, [], [], [], []
        claimed = []
        for entry in entries:
            require(entry.get("route") in {"reuse", "procedural", "generated", "hybrid"}, "Invalid asset route")
            _text(entry.get("rationale"), "Asset route rationale")
            references = entry.get("operation_ids", [])
            require(isinstance(references, list) and len(set(references)) == len(references) and set(references).issubset(set(operation_ids)), "Asset chain references unknown or duplicate operations")
            require(entry["route"] not in {"generated", "hybrid"} or references, "Generated/hybrid route needs a costed operation chain")
            require(entry["route"] not in {"reuse", "procedural"} or not references, "Reuse/procedural route cannot hide paid operations")
            claimed += references
        require(sorted(claimed) == sorted(operation_ids), "Every cost operation must belong to exactly one scoped asset")
        completed = set()
        for op in operations:
            require(op.get("asset_id") in assets and op["id"] in next(e for e in entries if e["asset_id"] == op["asset_id"])["operation_ids"], "Operation asset binding mismatch")
            provider = providers.get(op.get("provider"))
            require(provider is not None, "Operation supplier must be in the open registry")
            require(op.get("operation") in provider.get("operations", []), "Supplier does not declare this operation")
            _text(op.get("model_version"), "Explicit supplier model/version")
            _text(op.get("rationale"), "Task-based supplier/model rationale")
            require(isinstance(op.get("parameters"), dict), "Record the exact proposed parameters")
            if enforce_image_policy:
                from . import image_policy
                image_policy.validate_operation(op, base or Path.cwd(), provider=provider)
            require(isinstance(op.get("depends_on", []), list) and set(op.get("depends_on", [])).issubset(completed), "Operations must follow their complete dependency chain")
            completed.add(op["id"])
            if provider["id"] == "lux3d" and op["operation"] in {"image_to_3d", "text_to_3d"}:
                parameters = op["parameters"]
                require(parameters.get("version") in {"G1", "G1-Turbo"} and parameters["version"] == op["model_version"], "Choose Lux G1/G1-Turbo explicitly per task, without a global default")
                require(type(parameters.get("faceCount")) is int and 10000 <= parameters["faceCount"] <= 300000, "Lux needs an explicit supported face count")
                require(parameters["version"] != "G1" or "enablePbr" not in parameters, "G1 must omit Turbo-only enablePbr")
                require(parameters["version"] != "G1-Turbo" or "customSize" not in parameters, "G1-Turbo must omit unsupported customSize")
                allowed = document.get("effective_policy", {}).get("lux_allowed_versions", ["G1", "G1-Turbo"])
                require(parameters["version"] in allowed, "Lux version conflicts with this task's explicit user policy")
            pricing = _price(op.get("pricing"), base, now)
            if provider.get("account_profile") is not None and (pricing["credits"] or pricing["wallet"] is not None):
                require(pricing["wallet"] == provider["account_profile"]["wallet"], "Operation pricing wallet differs from the selected account profile")
            if pricing["credits"]:
                owner = wallet_owners.setdefault(pricing["wallet"], provider["id"])
                require(owner == provider["id"], "A wallet ID belongs to one supplier; never combine unrelated supplier credits")
                wallets[pricing["wallet"]] = wallets.get(pricing["wallet"], Decimal(0)) + pricing["credits"]
                if pricing["money"] is None:
                    unknown.append(op["id"])
            if pricing["money"] is not None:
                money[pricing["currency"]] = money.get(pricing["currency"], Decimal(0)) + pricing["money"]
            if pricing["cash_due"] is not None:
                due = pricing["cash_due"]
                cash[due["currency"]] = cash.get(due["currency"], Decimal(0)) + _number(due["amount"], "Cash due")
            if pricing["expired"]:
                expired.append(op["id"])
            verify = provider.get("verification", {})
            profile_sha = account_profiles.profile_digest(provider["id"], provider["account_profile"]) if provider.get("account_profile") is not None else None
            connected = provider["configured"] and provider.get("binding", {}).get("kind", "catalog_only") != "catalog_only" and _verification(verify.get("connection"), base, now, profile_sha)
            verified = _verification(verify.get("operations", {}).get(op["operation"]), base, now, profile_sha)
            require(type(op.get("qualification_probe", False)) is bool, "qualification_probe must be boolean")
            probe = connected and not verified and op.get("qualification_probe") is True
            if probe:
                probes.append(op["id"])
            if not connected or not verified and not (probe and op["id"] in allowed_probes):
                blocked.append(op["id"])
        for asset_id, required in requirements.items():
            present = {op["operation"] for op in operations if op["asset_id"] == asset_id}
            require(set(required).issubset(present), "Option omits a required character/postprocessing operation")
        for_execution_option = for_execution is True or for_execution == option["id"]
        require(not for_execution_option or not (blocked or expired), "Selected option has unverified supplier operations or expired prices")
        summaries.append({"id": option["id"], "wallet_credits": {k: str(v) for k, v in wallets.items()},
                          "allocated_money": {k: str(v) for k, v in money.items()}, "cash_due": {k: str(v) for k, v in cash.items()},
                          "money_conversion_missing": unknown, "expired_prices": expired, "blocked_operations": blocked,
                          "qualification_pending": probes,
                          "price_kinds": sorted({op["pricing"]["kind"] for op in operations}),
                          "execution_ready": not (blocked or expired)})
    return {"ok": True, "portfolio_sha256": digest(document), "registry_sha256": registry_digest(registry),
            "recommended_option": document["recommended_option"], "options": summaries,
            "authorization": "none; requires actual H3 selection and the submission runner's spend reservation"}


def validate_selection(selection, portfolio, registry, base=None, now=None, require_current=True):
    require(isinstance(selection, dict) and selection.get("schema") == 1 and selection.get("kind") == "supplier-selection",
            "Expected supplier-selection schema 1")
    require(selection.get("gate") == "H3" and selection.get("actor") == "user" and selection.get("decision") == "approved",
            "Portfolio selection requires the actual user's H3 decision")
    require(selection.get("portfolio_sha256") == digest(portfolio) and selection.get("registry_sha256") == registry_digest(registry),
            "Selection is stale after a supplier, scope, route, parameter or price change")
    _text(selection.get("source_ref"), "Actual human decision source reference")
    _evidence(selection.get("evidence"), base)
    _time(selection.get("decided_at"))
    option_id = selection.get("selected_option")
    options = {o["id"]: o for o in portfolio.get("options", [])}
    require(option_id in options, "User selection must name an exact proposed option")
    probes = selection.get("allow_qualification_probes", [])
    require(isinstance(probes, list) and len(probes) == len(set(probes)) and all(safe_id(p) for p in probes), "Qualification authorization must list exact operation IDs")
    require(set(probes).issubset({op["id"] for op in options[option_id]["operations"] if op.get("qualification_probe") is True}), "Qualification authorization must refer to declared probes in the selected option")
    report = validate_portfolio(portfolio, registry, base, now, for_execution=option_id if require_current else False, allow_qualification_probes=probes, enforce_image_policy=require_current)
    fallback_ids = set()
    for fallback in selection.get("allowed_fallbacks", []):
        require(isinstance(fallback, dict) and fallback.get("option_id") in options and fallback["option_id"] != option_id and fallback["option_id"] not in fallback_ids,
                "Fallbacks must name distinct, fully proposed alternatives")
        fallback_ids.add(fallback["option_id"])
        alternative = next(row for row in report["options"] if row["id"] == fallback["option_id"])
        caps = fallback.get("wallet_caps")
        require(isinstance(caps, dict) and set(caps) == set(alternative["wallet_credits"]), "Fallback must cap each supplier wallet explicitly")
        require(all(_number(caps[k], "Fallback wallet cap") >= Decimal(v) for k, v in alternative["wallet_credits"].items()), "Fallback wallet cap is below its proposed complete cost")
        operation_ids = fallback.get("operation_ids")
        require(isinstance(operation_ids, list) and operation_ids and set(operation_ids).issubset({op["id"] for op in options[fallback["option_id"]]["operations"]}), "Fallback must scope the exact operations authorized")
    return {"ok": True, "selection_sha256": digest(selection), "selected_option": option_id,
            "portfolio_sha256": digest(portfolio), "registry_sha256": registry_digest(registry), "allowed_fallbacks": sorted(fallback_ids),
            "note": "Evidence binding does not authenticate a human or authorize duplicate submissions after an unknown outcome."}


def invoke_adapter(registry, provider_id, method, request, *, base=None, timeout=60, authorization=None):
    """Invoke an explicitly reviewed local command adapter without a shell.

    Submission/fetch additionally bind the exact selected operation. The caller
    MUST enforce the actual workflow H3 decision, reserve spending before submit,
    and persist/reconcile unknown outcomes. A portable contract cannot
    authenticate a human or replace that runner ledger.
    """
    validate_registry(registry, base)
    require(method in BRIDGE_METHODS, "Unknown adapter method")
    require(isinstance(request, dict), "Adapter request must be an object")
    provider = next((p for p in registry["providers"] if p["id"] == provider_id), None)
    require(provider is not None and provider.get("binding", {}).get("kind") in {"command", "builtin_api"},
            "Choose an explicitly registered dedicated API or reviewed local command adapter")
    if method not in READ_ONLY:
        require(isinstance(authorization, dict), "Submission/fetch requires an exact selected portfolio operation")
        selection, portfolio = authorization.get("selection"), authorization.get("portfolio")
        validate_selection(selection, portfolio, registry, base, require_current=method == "submit")
        option_id = authorization.get("option_id", selection["selected_option"])
        option = next((o for o in portfolio["options"] if o["id"] == option_id), None)
        operation = next((o for o in (option or {}).get("operations", []) if o["id"] == authorization.get("operation_id")), None)
        require(operation is not None and operation["provider"] == provider_id, "Adapter operation is outside the selected supplier scope")
        if option_id != selection["selected_option"]:
            fallback = next((f for f in selection.get("allowed_fallbacks", []) if f["option_id"] == option_id), None)
            require(fallback is not None and operation["id"] in fallback["operation_ids"], "Fallback supplier/operation lacks explicit H3 authorization")
            validate_portfolio(portfolio, registry, base, for_execution=option_id if method == "submit" else False,
                               enforce_image_policy=method == "submit")
        if method == "submit":
            from . import image_policy
            image_policy.validate_operation(operation, base or Path.cwd(), provider=provider)
            expected = {"operation": operation["operation"], "model_version": operation["model_version"], "parameters": operation["parameters"]}
            require(all(request.get(key) == value for key, value in expected.items()) and
                    set(request).issubset(set(expected) | {"inputs", "dependencies", "quote", "output_dir", "account_profile", "account_profile_sha256"}),
                    "Adapter submission parameters differ from the exact approved operation")
            expected_inputs = [{"path": str(resolve_input(record["path"], base or Path.cwd())),
                                "sha256": record["sha256"]} for record in operation.get("inputs", [])]
            actual_inputs = [{"path": str(Path(record.get("path", "")).resolve()), "sha256": record.get("sha256")} for record in request.get("inputs", [])]
            require(actual_inputs == [{"path": str(Path(row["path"]).resolve()), "sha256": row["sha256"]} for row in expected_inputs],
                    "Adapter input payload differs from the approved hash-bound image/model records")
        else:
            _text(request.get("task_id"), "Fetch needs the original persisted supplier task ID")
    require(type(timeout) is int and 1 <= timeout <= 60, "Adapter calls must yield within 60 seconds")
    if provider["binding"]["kind"] == "builtin_api":
        from .provider_adapter import dispatch
        request = account_profiles.inject_registry(provider_id, method, request, provider.get("account_profile"))
        return dispatch(provider_id, method, request)
    envelope = {"schema": 1, "provider": provider_id, "method": method, "request": request}
    try:
        result = subprocess.run(provider["binding"]["argv"], input=json.dumps(envelope, allow_nan=False),
                                text=True, capture_output=True, timeout=timeout, shell=False)
        require(result.returncode == 0, "Local adapter failed; raw output is omitted to protect credentials")
        require(len(result.stdout.encode()) <= 1024 * 1024, "Adapter output exceeds 1 MiB")
        response = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        raise WorkflowError("Local adapter failed or returned invalid JSON; raw output is omitted to protect credentials") from None
    require(isinstance(response, dict) and response.get("provider") == provider_id and response.get("method") == method and type(response.get("ok")) is bool,
            "Adapter response must bind provider/method and declare ok")
    return response


def load_catalog():
    """Knowledge is descriptive and must never install or invoke its URLs."""
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def _domain(value, domain):
    require(isinstance(domain, dict), "Billing parameter domain must be explicit")
    if "values" in domain:
        require(isinstance(domain["values"], list) and domain["values"], "Billing values must be a nonempty list")
        return any(digest(value) == digest(candidate) for candidate in domain["values"])
    require("minimum" in domain and "maximum" in domain, "Billing domain needs values or a bounded numeric range")
    minimum = _number(domain["minimum"], "Domain minimum")
    maximum = _number(domain["maximum"], "Domain maximum")
    require(minimum <= maximum, "Billing domain minimum exceeds maximum")
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    number = _number(value, "Billing parameter")
    return minimum <= number <= maximum and (not domain.get("integer") or type(value) is int)


def estimate_from_rate_card(card, operation, model_version, parameters, *, base=None, now=None):
    """Calculate a sourced manual/rate-card estimate without an API quote call.

    Each rate describes a supported parameter combination. Undeclared inputs,
    missing billable parameters and overlapping rates are unknown, never free.
    The official manual must be normalized/reviewed by the host; this calculator
    cannot establish that an arbitrary supplied rate matches a vendor's terms.
    """
    require(isinstance(card, dict) and card.get("schema") == 1 and card.get("kind") == "supplier-rate-card",
            "Expected supplier-rate-card schema 1")
    _no_secrets(card)
    require(safe_id(card.get("id")) and safe_id(card.get("provider")), "Rate card needs versioned ID and supplier")
    _source(card.get("source"), base)
    require(isinstance(parameters, dict), "Pricing parameters must be an object")
    rates = card.get("rates")
    require(isinstance(rates, list) and rates, "Rate card must contain explicit rates")
    ids = [rate.get("id") for rate in rates]
    require(all(safe_id(i) for i in ids) and len(set(ids)) == len(ids), "Rate IDs must be unique")
    matches = []
    for rate in rates:
        if rate.get("operation") != operation or rate.get("model_version") != model_version:
            continue
        domains = rate.get("parameter_domains", {})
        nonbillable = rate.get("nonbillable_parameters", [])
        require(isinstance(domains, dict) and isinstance(nonbillable, list) and all(isinstance(v, str) for v in nonbillable),
                "Declare billing domains and manual-confirmed nonbillable parameters")
        require(not set(domains).intersection(nonbillable), "A parameter cannot be both billable and nonbillable")
        if not set(parameters).issubset(set(domains) | set(nonbillable)):
            continue
        effective, supported = {}, True
        for name, domain in domains.items():
            require(isinstance(domain, dict), "Billing domain must be an object")
            if name not in parameters and "default" not in domain:
                supported = False
                break
            value = parameters[name] if name in parameters else domain["default"]
            if not _domain(value, domain):
                supported = False
                break
            effective[name] = value
        if supported:
            matches.append((rate, effective))
    require(len(matches) == 1, "No unambiguous documented rate matches all billable parameters; price is unknown")
    rate, effective = matches[0]
    costs = [(rate["id"], rate.get("base"))]
    addons = rate.get("addons", [])
    require(isinstance(addons, list), "Rate add-ons must be an explicit list")
    addon_ids = [addon.get("id") for addon in addons]
    require(all(safe_id(i) for i in addon_ids) and len(set(addon_ids)) == len(addon_ids), "Add-on IDs must be unique")
    for addon in addons:
        when = addon.get("when")
        require(isinstance(when, dict) and when and set(when).issubset(effective), "Add-on conditions must name declared billing parameters")
        if all(digest(effective[key]) == digest(value) for key, value in when.items()):
            costs.append((addon["id"], addon))
    credits, direct, currency, mode = Decimal(0), Decimal(0), None, None
    for rule_id, cost in costs:
        require(isinstance(cost, dict) and (("unit_credits" in cost) != ("direct_money" in cost)),
                "Every matched rate/add-on needs explicit credits or direct money")
        current_mode = "credits" if "unit_credits" in cost else "money"
        require(mode in (None, current_mode), "Do not mix cash and wallet charges in one operation; use separate cost lines")
        mode = current_mode
        if mode == "credits":
            credits += _number(cost["unit_credits"], "Documented unit credits")
        else:
            value = cost["direct_money"]
            require(isinstance(value, dict) and re.fullmatch(r"[A-Z]{3}", str(value.get("currency", ""))), "Documented money needs currency")
            require(currency in (None, value["currency"]), "Add-on currency differs from base rate")
            currency = value["currency"]
            direct += _number(value.get("unit_amount"), "Documented unit money")
    result = {"kind": "rate_card_estimate", "source": copy.deepcopy(card["source"]),
              "quoted_at": _now(now).isoformat(), "quantity": 1,
              "rate_card_audit": {"id": card["id"], "sha256": digest(card), "provider": card["provider"],
                                  "operation": operation, "model_version": model_version,
                                  "rule_ids": [rule_id for rule_id, _ in costs], "effective_billing_parameters": effective}}
    if card.get("expires_at"):
        result["expires_at"] = card["expires_at"]
    if mode == "credits":
        require(safe_id(card.get("wallet")), "Credit rate card requires a named supplier wallet")
        result.update(wallet=card["wallet"], unit_credits=str(credits))
        if card.get("conversion"):
            result["conversion"] = copy.deepcopy(card["conversion"])
    else:
        result["direct_money"] = {"unit_amount": str(direct), "currency": currency}
    if credits == 0 and direct == 0:
        result["zero_cost_reason"] = _text(rate.get("zero_cost_reason"), "Documented zero-cost reason")
    _price(result, base, now)
    return result
