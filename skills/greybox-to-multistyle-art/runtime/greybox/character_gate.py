"""Artifact-bound rig review at the managed submission boundary, never recovery."""
from pathlib import Path
import base64
import hashlib
from . import core
from .provider_http import bound_file, dependency_model, dependency_task, public_url, safe_id

RIG_OPERATIONS = {"rig", "rig.bind", "auto-rig", "rigging"}
SOURCE_FIELDS = {"model_from", "model_path", "modelUrl", "model_url", "input_from",
                 "input_task_from", "input_task_id", "input"}


def _selected_source(provider, parameters, sources, dependencies):
    """Resolve the same selector as the adapter; unrelated inputs prove nothing."""
    fields = SOURCE_FIELDS.intersection(parameters)
    allowed = {"lux3d": {"modelUrl"}, "lux": {"modelUrl"},
               "meshy": {"model_from", "model_path", "model_url", "input_task_from", "input_task_id"},
               "tripo": {"model_from", "model_path", "input_from", "input"}}.get(provider, SOURCE_FIELDS)
    core.require(len(fields) == 1 and fields <= allowed,
                 "Rig needs one explicit supported model source, without conflicting selectors")
    field = next(iter(fields))
    value = parameters[field]
    document = {"inputs": list(sources), "dependencies": dependencies or {}}
    limit = (150 if provider == "tripo" else 100) * 1024 * 1024
    if field == "model_from":
        value = dependency_model(document, value, {".glb"})
    elif field in {"input_from", "input_task_from", "input_task_id"} or (
            field == "input" and isinstance(value, str) and not value.startswith("https://")):
        if field in {"input_from", "input_task_from"}:
            dependency_task(document, value, provider)
            reference = value
        else:
            task_id = safe_id(value)
            matches = [key for key, row in document["dependencies"].items()
                       if row.get("state") == "ready" and row.get("provider") == provider
                       and (row.get("provider_task_id") or row.get("task_id")) == task_id]
            core.require(len(matches) == 1,
                         "Rig task source needs one ready same-provider dependency with its actual GLB")
            reference = matches[0]
            dependency_task(document, reference, provider)
        value = dependency_model(document, reference, {".glb"})
    elif field in {"modelUrl", "model_url", "input"}:
        if provider == "meshy" and isinstance(value, str) and value.startswith("data:"):
            header, separator, encoded = value.partition(",")
            core.require(separator and header.endswith(";base64") and len(encoded) <= (limit + 2) // 3 * 4,
                         "Rig data URI must contain bounded base64 model bytes")
            try:
                content = base64.b64decode(encoded, validate=True)
            except (ValueError, TypeError):
                raise core.WorkflowError("Rig data URI has invalid base64 model bytes") from None
            core.require(0 < len(content) <= limit, "Rig data URI model size is unsupported")
            return {"sha256": hashlib.sha256(content).hexdigest()}
        core.require(isinstance(value, str) and value.startswith("https://"), "Rig remote model source must be HTTPS")
        public_url(value, resolve=False)
        return {"remote": value}
    path = bound_file(document, value, {".glb"}, limit)
    return {"sha256": core.file_hash(path)}


def require_preflight(provider, operation, parameters, run_dir, operation_id,
                      sources=(), preflight=None, base=None, dependencies=None):
    if operation not in RIG_OPERATIONS:
        return None
    from . import characters
    base = Path(base or run_dir).resolve()
    if preflight is not None:
        core.require(isinstance(preflight, dict), "Character preflight must be a path/hash record")
        path = core.resolve_input(preflight.get("path", ""), base)
        core.require(path.is_file() and core.file_hash(path) == preflight.get("sha256"),
                     "Character preflight missing or changed")
    else:
        core.require(core.safe_id(operation_id), "Invalid rig operation ID")
        path = Path(run_dir) / "character-preflight" / (operation_id + ".json")
    core.require(path.is_file(), "Rig submission needs completed GLB review: " + str(path))
    receipt = core.read(path)
    check = characters.validate_preflight(path, provider=provider)
    core.require(check.get("ok") is True, "Rig preflight failed: " + "; ".join(check.get("errors", [])))
    core.require(receipt.get("use") == "rig", "New rig submission needs a rig review, not a static/reuse review")
    source = receipt["source"]
    binding = receipt.get("submission_binding", {})
    core.require(isinstance(parameters, dict) and isinstance(binding, dict), "Rig parameters and submission binding must be objects")
    core.require(binding.get("parameters_sha256") == core.digest(parameters)
                 and binding.get("source_sha256") == source["sha256"],
                 "Rig review must bind the exact operation parameters and source GLB")
    selected = _selected_source(provider, parameters, sources, dependencies)
    remote = selected.get("remote")
    if remote is not None:
        ref = binding.get("source_receipt", {})
        core.require(isinstance(ref, dict) and ref.get("path"), "Remote rig input needs its model-source binding receipt")
        linked = core.resolve_input(ref["path"], path.parent)
        core.require(linked.is_file() and core.file_hash(linked) == ref.get("sha256"), "Model-source receipt changed")
        recorded = core.read(linked)
        core.require(isinstance(recorded, dict) and recorded.get("kind") == "model-source-binding"
                     and isinstance(recorded.get("source"), dict) and recorded["source"].get("sha256") == source["sha256"]
                     and recorded.get("provider_source") == remote
                     and recorded.get("method") in {"upload", "download"},
                     "Remote rig source differs from reviewed upload/download bytes")
    else:
        core.require(selected["sha256"] == source["sha256"],
                     "Rig review belongs to another selected model")
    return {"path": str(path.resolve()), "sha256": core.file_hash(path), "source_sha256": source["sha256"]}


def for_supplier(operation, state, run_dir, registry=None):
    """Run before claiming/reserving a new operation; never before status/fetch."""
    if operation.get("operation") not in RIG_OPERATIONS:
        return None
    parameters = operation.get("parameters", {})
    dependencies = {key: state["operations"][key] for key in operation.get("depends_on", [])}
    if operation.get("provider") == "tripo":
        ref = parameters.get("rig_check_from")
        core.require(ref and ref in operation.get("depends_on", []),
                     "Tripo rig requires a source-bound rig_check dependency before submission")
        row = state["operations"][ref]
        core.require(row.get("state") == "ready" and row.get("provider") == "tripo"
                     and any(a.get("role") == "rig-check-report" for a in row.get("artifacts", [])),
                     "Tripo rig_check dependency is not ready")
    sources = list(state.get("inputs", {}).get(operation["id"], []))
    provider = operation["provider"]
    entry = next((p for p in (registry or {}).get("providers", []) if p["id"] == provider), {})
    if entry.get("binding", {}).get("kind") == "builtin_lux":
        provider = "lux3d"
    elif provider not in {"lux3d", "lux", "meshy", "tripo"}:
        core.require(entry.get("binding", {}).get("kind") == "command" and
                     operation["operation"] in entry.get("operations", []),
                     "Custom rig route needs an explicitly registered command operation")
    return require_preflight(provider, operation["operation"], parameters, run_dir,
                             operation["id"], sources=sources, preflight=operation.get("character_preflight"),
                             base=state["project"], dependencies=dependencies)
