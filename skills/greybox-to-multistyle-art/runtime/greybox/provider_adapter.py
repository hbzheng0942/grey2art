"""Fixed built-in API implementations behind the open supplier registry.

No dynamic imports from project data. Capability/validation are offline;
account/status/fetch are explicit read-only network operations. Only the
workflow- and budget-aware supplier ledger should invoke submit.
"""
from __future__ import annotations

import importlib
from .core import require
from . import account_profiles

BUILTINS = {"meshy": "meshy", "tripo": "tripo", "rodin": "rodin", "hitem3d": "hitem3d"}


def dispatch(provider, method, request):
    require(provider in BUILTINS, "No dedicated adapter for this ID; register a reviewed external command")
    require(method in {"capabilities", "validate", "account", "quote", "submit", "status", "fetch"},
            "Unknown provider method")
    require(isinstance(request, dict), "Provider request must be an object")
    request = account_profiles.bind_request(provider, method, request)
    if method == "quote" and provider in {"meshy", "tripo"}:
        card = request.get("rate_card")
        if not isinstance(card, dict):
            return {"provider": provider, "method": method, "ok": False,
                    "error": {"code": "RATE_CARD_REQUIRED", "message": "Supply a reviewed official rate_card, or use the local estimate command; no API query or generation is needed."}}
        require(card.get("provider") == provider, "Rate card belongs to another supplier")
        from .suppliers import estimate_from_rate_card
        pricing = estimate_from_rate_card(card, request.get("operation"), request.get("model_version"), request.get("parameters", {}))
        return account_profiles.bind_result(provider, request, {"provider": provider, "method": method, "ok": True, "pricing": pricing, "network_calls": 0})
    module = importlib.import_module(".providers." + BUILTINS[provider], package="greybox")
    return module.dispatch(method, request)


def public_result(response):
    """Never print private recovery tokens or signed model URLs into chat."""
    private = {"recovery", "subscription_key", "access_token", "token", "api_key", "authorization",
               "headers", "raw", "raw_response", "url", "urls", "download_url"}
    if isinstance(response, dict):
        return {k: (sorted(v) if k == "recovery" and isinstance(v, dict) else public_result(v))
                for k, v in response.items() if k not in private or k == "recovery"}
    if isinstance(response, list):
        return [public_result(v) for v in response]
    return response
