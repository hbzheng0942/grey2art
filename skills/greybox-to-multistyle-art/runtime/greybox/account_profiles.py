"""Non-secret account routing identity; fixed hosts, no credential probing/fallback.

A profile binds one configured account alias and wallet, not a verified account
identity. Credentials come from the chosen environment variable(s), or the exact
provider/region/name entry in the user's private credential file.
"""
from __future__ import annotations

import copy
import os
import re
from urllib.parse import urlsplit

from . import core

ENDPOINTS = {
    "meshy": {"cn": "https://api.meshy.cn", "international": "https://api.meshy.ai"},
    "tripo": {"cn": "https://openapi.tripo3d.com/v3", "international": "https://openapi.tripo3d.ai/v3"},
    "rodin": {"public": "https://api.hyper3d.com"},
    "hitem3d": {"public": "https://api.hitem3d.ai"},
}
LEGACY = {"meshy": ("international", ["MESHY_API_KEY"]), "tripo": ("international", ["TRIPO_API_KEY"]),
          "rodin": ("public", ["RODIN_API_KEY"]), "hitem3d": ("public", ["HITEM3D_CLIENT_ID", "HITEM3D_CLIENT_SECRET"])}


def validate(provider, profile):
    core.require(provider in ENDPOINTS and isinstance(profile, dict), "Built-in account profile must name a supported provider")
    credential_key = "credential_envs" if provider == "hitem3d" else "credential_env"
    core.require(set(profile) == {"account_system", "account_ref", "wallet", credential_key},
                 "Account profile accepts only account_system, account_ref, wallet and dedicated credential env name(s); no host overrides or secrets")
    core.require(profile.get("account_system") in ENDPOINTS[provider], "Unsupported account system; do not infer a regional API from website language")
    core.require(core.safe_id(profile.get("account_ref")) and core.safe_id(profile.get("wallet")), "Account alias and wallet must be non-secret stable IDs")
    names = profile[credential_key] if provider == "hitem3d" else [profile[credential_key]]
    core.require(isinstance(names, list) and len(names) == (2 if provider == "hitem3d" else 1)
                 and all(isinstance(name, str) and re.fullmatch(provider.upper() + r"_[A-Z0-9_]{1,90}", name) for name in names)
                 and len(set(names)) == len(names), "Declare dedicated provider-prefixed credential env names; Hi3D needs ordered client ID and secret names")
    return profile


def profile_digest(provider, profile):
    validate(provider, profile)
    return core.digest({"provider": provider, "profile": profile, "api_base": ENDPOINTS[provider][profile["account_system"]]})


def bind_request(provider, method, request):
    core.require(isinstance(request, dict), "Provider request must be an object")
    result = copy.deepcopy(request)
    profile = result.get("account_profile")
    if method in {"status", "fetch"}:
        accepted = result.get("accepted_request", {})
        core.require(isinstance(accepted, dict), "Recovery needs accepted_request as an object")
        frozen = accepted.get("account_profile")
        if profile is not None or frozen is not None:
            core.require(frozen is not None, "Profiled recovery needs the original accepted_request account profile; never guess or switch accounts")
            core.require(profile is None or profile == frozen, "Recovery cannot switch the accepted account profile")
            profile = frozen
            expected = profile_digest(provider, profile)
            core.require(accepted.get("account_profile_sha256", expected) == expected, "Accepted account profile digest changed")
        recovery = result.get("recovery", {})
        core.require(isinstance(recovery, dict), "Recovery must be an object")
        if profile is not None and recovery:
            core.require(recovery.get("account_profile_sha256") == profile_digest(provider, profile), "Profiled recovery must retain its original account binding")
        if recovery.get("account_profile_sha256") is not None:
            core.require(profile is not None and recovery["account_profile_sha256"] == profile_digest(provider, profile), "Task recovery account profile mismatch")
        if recovery.get("account_profile") is not None:
            core.require(recovery["account_profile"] == profile, "Task recovery account identity mismatch")
    if profile is not None:
        expected = profile_digest(provider, profile)
        core.require(result.get("account_profile_sha256", expected) == expected, "Request account profile digest changed")
        result.update(account_profile=copy.deepcopy(profile), account_profile_sha256=expected)
    else:
        core.require("account_profile_sha256" not in result, "Account profile digest requires its actual profile")
    return result


def inject_registry(provider, method, request, profile):
    """Call only after exact operation/authorization comparison in suppliers."""
    if profile is None:
        core.require("account_profile" not in request and "account_profile_sha256" not in request,
                     "Request cannot introduce an account profile absent from the approved registry")
        return request
    validate(provider, profile)
    core.require(request.get("account_profile", profile) == profile, "Request account differs from the approved registry profile")
    return bind_request(provider, method, {**request, "account_profile": copy.deepcopy(profile)})


def client_config(provider, request=None):
    profile = (request or {}).get("account_profile")
    if profile is None:
        system, names = LEGACY[provider]
    else:
        validate(provider, profile)
        system = profile["account_system"]
        names = profile["credential_envs"] if provider == "hitem3d" else [profile["credential_env"]]
    base = ENDPOINTS[provider][system]
    return {"base_url": base, "allowed_hosts": {urlsplit(base).hostname}, "credential_envs": list(names), "region": system}


def credential(provider, request=None, index=0):
    from .provider_credentials import load
    config = client_config(provider, request)
    return load(provider, config["region"], config["credential_envs"][index])


def bind_result(provider, request, response):
    if response.get("method") == "capabilities":
        names = client_config(provider, request)["credential_envs"]
        try:
            configured = all(credential(provider, request, index) for index in range(len(names)))
            response = {**response, "required_env": names, "configured": bool(configured)}
        except (ValueError, OSError):
            response = {**response, "required_env": names, "configured": False,
                        "credential_error": "Private credential configuration is invalid; repair permissions/schema or set the exact profile environment variables."}
    profile = request.get("account_profile")
    if profile is None:
        return response
    result = dict(response)
    expected = profile_digest(provider, profile)
    result.update(account_profile=copy.deepcopy(profile), account_profile_sha256=expected,
                  api_base=ENDPOINTS[provider][profile["account_system"]], wallet=profile["wallet"])
    if isinstance(result.get("recovery"), dict):
        result["recovery"] = {**result["recovery"], "account_profile": copy.deepcopy(profile), "account_profile_sha256": expected}
    if "request_digest" in result:
        result["request_digest"] = core.digest({"operation": request.get("operation"), "model_version": request.get("model_version"),
                                               "parameters": request.get("parameters", {}), "account_profile_sha256": expected})
    if isinstance(result.get("pricing"), dict):
        core.require(result["pricing"].get("wallet") == profile["wallet"], "Quote wallet differs from the selected account profile")
    return result
