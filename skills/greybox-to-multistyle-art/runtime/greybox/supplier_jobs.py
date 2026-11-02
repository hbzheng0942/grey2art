"""Persisted, engine-independent supplier jobs after actual H1/H2/H3 decisions.

Adapters translate the neutral protocol; they do not grant spending authority.
Every submission is reserved before invocation. Unknown outcomes block reissue
and vendor switching; existing tasks can still recover after source drift.
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path
import copy
import os
import uuid

from . import core, suppliers, workflow

_ARTIFACT_CHECKS = {}  # Process-local polling cache; production gates never use it.


class DuplicateOperationError(core.WorkflowError):
    """An actual persisted operation/asset claim conflicts with this attempt."""


def _inputs(operation, project):
    records = operation.get("inputs", [])
    core.require(isinstance(records, list), "Operation inputs must be hash-bound records")
    result = []
    for record in records:
        path = core.resolve_input(record["path"], project)
        core.require(path.is_file() and core.file_hash(path) == record.get("sha256"),
                     "Supplier input missing or changed; revise the affected operation")
        result.append({"path": str(path), "sha256": record["sha256"]})
    return result


def _gate(portfolio, selection, checkpoint, project, capabilities=None, session_id=None,
          expansion=False, current=True):
    """The complete production gate stays authoritative, including atlas/spatial/H4."""
    data = core.read(checkpoint)
    core.require(data.get("production_policy") == workflow.PRODUCTION_POLICY or
                 (not current and data.get("production_policy") in workflow.HISTORICAL_PRODUCTION_POLICIES),
                 "New production requires asset-routed-visual-sample-v3 workflow gates; preserve existing tasks for recovery")
    from . import overview
    brief_ref = portfolio.get("overview", {})
    brief_path = core.resolve_input(brief_ref.get("path", ""), project)
    core.require(brief_path.is_file() and core.file_hash(brief_path) == brief_ref.get("sha256"),
                 "R3 supplier production needs its exact early workflow overview")
    overview.validate_production_scope(core.read(brief_path), portfolio, base=project)
    styles = portfolio.get("selected_styles")
    core.require(isinstance(styles, list) and styles, "Supplier portfolio must name its actual selected_styles")
    report = workflow.inspect_workflow(checkpoint, project, selected_styles=styles, expansion=expansion,
        expected_session=session_id, capability_report=capabilities, require_current_capabilities=current)
    tables = {}
    for style in styles:
        stage = next(s for s in data["stages"] if s["id"] == "production_plan" and s["scope"] == style)
        item = next(e for e in stage["evidence"] if e["role"] == "production_table")
        table = core.read(core.resolve_input(item["path"], project))
        tables[style] = table
        core.require(table.get("supplier_portfolio_digest") == suppliers.portfolio_digest(portfolio),
                     "H3 production table must bind this exact supplier portfolio")
        core.require(stage["approval"]["source_ref"] == selection.get("source_ref"),
                     "Supplier selection must refer to the actual H3 production decision")
    if current and data.get("production_policy") == workflow.PRODUCTION_POLICY:
        from . import layout
        # A portfolio digest alone cannot put its sources in a visual BOM. Bind
        # the actual selected/allowed paid scope to each owning style's H3.
        scoped_options = {selection["selected_option"]: None}
        scoped_options.update({f["option_id"]: set(f["operation_ids"]) for f in selection.get("allowed_fallbacks", [])})
        for option in portfolio["options"]:
            if option["id"] not in scoped_options:
                continue
            allowed = scoped_options[option["id"]]
            for entry in option["assets"]:
                if allowed is not None and not (set(entry.get("operation_ids", [])) & allowed):
                    continue
                asset_id = entry["asset_id"]
                owner = layout.asset_owner(portfolio, asset_id)
                owning_styles = styles if owner["scope"] == "shared" else [owner["style_id"]]
                for style in owning_styles:
                    approved = next((a for a in tables.get(style, {}).get("asset_proposals", []) if a["asset_id"] == asset_id), None)
                    core.require(approved is not None,
                                 "H3 visual BOM omits supplier asset in its owning style: " + style + "/" + asset_id)
                    permitted_route = approved.get("route")
                    if allowed is not None:
                        permitted_route = approved.get("fallback_routes", {}).get(option["id"], permitted_route)
                    core.require(entry.get("route") == permitted_route,
                                 "Selected supplier visual route differs from H3 BOM responsibility: " + style + "/" + asset_id)
                    mesh_ops = [op for op in option["operations"] if op["id"] in entry.get("operation_ids", [])
                                and (allowed is None or op["id"] in allowed)
                                and op["operation"] in {"image_to_3d", "multiview_to_3d"}]
                    core.require(all(op["operation"] == approved.get("generation", {}).get("operation") for op in mesh_ops),
                                 "Supplier mesh operation differs from H3 asset proposal: " + style + "/" + asset_id)
                    if entry.get("route") in {"generated", "hybrid"}:
                        stage = next(s for s in data["stages"] if s["id"] == "production_plan" and s["scope"] == style)
                        visual = core.read(core.resolve_input(next(e for e in stage["evidence"] if e["role"] == "visual_package")["path"], project))
                        displayed = next(b for b in visual["bom"] if b["asset_id"] == asset_id)
                        core.require(displayed.get("reference_status") == "production_ready",
                                     "Paid selected/fallback source needs production-ready visual BOM reference: " + asset_id)
    approved_packages = []
    for style in styles:
        stage = next(s for s in data["stages"] if s["id"] == "production_plan" and s["scope"] == style)
        table = core.read(core.resolve_input(next(e for e in stage["evidence"] if e["role"] == "production_table")["path"], project))
        reference = table.get("modeling_references")
        if reference:
            package = core.read(core.resolve_input(reference["path"], project))
            core.require(package.get("style_id") == style, "Modeling-reference package style differs from its H3 production table")
            approved_packages.append((reference, package))
    from . import image_policy, modeling_refs
    for option in portfolio["options"]:
        for operation in option.get("operations", []):
            if operation.get("operation") not in image_policy.IMAGE_OPERATIONS:
                continue
            checked = image_policy.validate_operation(operation, project)
            core.require(any(operation.get("modeling_references") == reference for reference, _ in approved_packages),
                         "Supplier image operation must bind an H3-approved modeling-reference package")
            # A global asset may be explicitly reused across styles. Every H3
            # package that includes it must approve identical ordered view bytes.
            for reference, package in approved_packages:
                if any(asset.get("asset_id") == operation["asset_id"] for asset in package.get("assets", [])):
                    other = modeling_refs.validate_operation_reference({**operation, "modeling_references": reference}, project)
                    core.require(other["mode"] == checked["mode"] and
                                 [i["sha256"] for i in other["images"]] == [i["sha256"] for i in checked["images"]],
                                 "A shared asset's submitted views differ from another style's H3-approved images")
    return report


def prepare(project, run_dir, registry, portfolio, selection, checkpoint, capabilities, session_id, expansion=False):
    project_alias, run_alias = Path(project).absolute(), Path(run_dir).absolute()
    project, checkpoint = project_alias.resolve(), Path(checkpoint).resolve()
    run_dir = project / run_alias.relative_to(project_alias) if run_alias.is_relative_to(project_alias) else run_alias
    core.require(portfolio.get("workspace") is not None,
                 "New supplier production requires an approved workspace directory contract; existing tasks may only recover")
    _validate_run_path(portfolio, project, run_dir)
    run_dir = run_dir.resolve()
    core.require(session_id, "Current capability discovery needs a host session ID")
    checked = suppliers.validate_selection(selection, portfolio, registry, base=project)
    for option in portfolio["options"]:
        _validate_publish_paths(option, project, portfolio)
    _gate(portfolio, selection, checkpoint, project, capabilities, session_id, expansion)
    from .production_control import ensure_prepared
    ensure_prepared(project, portfolio, workflow_path=checkpoint)
    option = next(o for o in portfolio["options"] if o["id"] == checked["selected_option"])
    for operation in option['operations']:
        provider = next(p for p in registry['providers'] if p['id'] == operation['provider'])
        if provider.get('binding', {}).get('kind') == 'builtin_api':
            core.require(provider.get('account_profile'), 'New built-in API production needs an explicit account profile')
    inputs = {op["id"]: _inputs(op, project) for op in option["operations"]}
    with core.locked(run_dir):
        core.require(not (run_dir / "supplier-run.json").exists(), "Supplier run already exists; resume it")
        for name, document in (("supplier-registry.json", registry), ("supplier-portfolio.json", portfolio),
                               ("supplier-selection.json", selection), ("supplier-readiness.json", capabilities)):
            core.write(run_dir / name, document)
        state = {"schema": 1, "kind": "supplier-job-run", "project": str(project), "created_at": core.now(),
            "portfolio_digest": suppliers.portfolio_digest(portfolio), "registry_digest": suppliers.registry_digest(registry),
            "selection_digest": core.digest(selection), "selected_option": option["id"], "expansion": bool(expansion),
            "workflow": {"path": str(checkpoint), "sha256": core.file_hash(checkpoint)},
            "readiness": {"sha256": core.digest(capabilities), "session_id": session_id},
            "runtime_digest": core.runtime_snapshot()["sha256"], "inputs": inputs,
            "operations": {op["id"]: {"state": "pending"} for op in option["operations"]},
            "reservations": {}, "events": [], "state": "prepared"}
        if portfolio.get("workspace") is not None:
            state["workspace"] = portfolio["workspace"]
            state["run_id"] = run_dir.name
        core.write(run_dir / "supplier-run.json", state)
    _register_run(project, portfolio, run_dir)
    return status(run_dir)


def _load(run_dir):
    run_dir = Path(run_dir).resolve()
    state = core.read(run_dir / "supplier-run.json")
    core.require(state.get("schema") == 1 and state.get("kind") == "supplier-job-run", "Invalid supplier run")
    portfolio = core.read(run_dir / "supplier-portfolio.json")
    registry = core.read(run_dir / "supplier-registry.json")
    selection = core.read(run_dir / "supplier-selection.json")
    core.require(core.digest(portfolio) == state["portfolio_digest"] and core.digest(selection) == state["selection_digest"],
                 "Frozen portfolio/selection changed; preserve submitted jobs and restore the exact records")
    core.require(suppliers.registry_digest(registry) == state["registry_digest"], "Supplier binding changed; preserve original task provenance")
    core.require(state.get("workspace") == portfolio.get("workspace"),
                 "Supplier run workspace differs from its frozen approved portfolio")
    option = next(o for o in portfolio["options"] if o["id"] == state["selected_option"])
    core.require(set(state["operations"]) == {o["id"] for o in option["operations"]}, "Supplier job scope changed")
    return state, portfolio, registry, selection, option


def _lux_parameters(operation, request, project, region):
    """Upload only reviewed source bytes; persist URL/hash receipts without copying images."""
    from . import image_policy, lux
    checked = image_policy.validate_operation(operation, project)
    parameters = dict(request["parameters"])
    if operation["operation"] not in image_policy.IMAGE_OPERATIONS:
        return parameters
    images = checked["images"]
    core.require(request.get("inputs") == images, "Lux upload bytes differ from approved modeling inputs")
    output = Path(request["output_dir"]).resolve()
    cache_path = output.parent.parent / ("lux-upload-" + operation["id"] + ".json")
    cache = core.read(cache_path) if cache_path.is_file() else {"schema": 1, "uploads": {}}
    urls = []
    for image in images:
        key = region + ":" + image["sha256"]
        receipt = cache["uploads"].get(key)
        if receipt is None:
            uploaded = lux.upload(image["path"], region)
            url = uploaded.get("url") or uploaded.get("data", {}).get("url")
            core.require(isinstance(url, str) and url.startswith("https://"), "Lux upload returned no HTTPS source URL")
            receipt = {"region": region, "source": image, "url": url}
            cache["uploads"][key] = receipt
            core.write(cache_path, cache)
        core.require(receipt.get("region") == region and receipt.get("source") == image,
                     "Lux upload cache source binding changed")
        core.require(core.file_hash(image["path"]) == image["sha256"], "Image source changed during upload; no generation may proceed")
        urls.append(receipt["url"])
    parameters.pop("image_path", None)
    parameters.pop("image_paths", None)
    parameters["img" if len(urls) == 1 else "imgs"] = urls[0] if len(urls) == 1 else urls
    request["_submitted_parameters"] = parameters
    request["_upload_receipt"] = {"path": str(cache_path), "sha256": core.file_hash(cache_path)}
    return parameters


def _prepare_lux_submission(operation, request, project):
    """Quote before claiming/reserving; the returned closure alone crosses POST.

    This closure exists only within this invocation. No serialized request flag
    or user-supplied receipt can bypass the exact live quotation and budget check.
    """
    from . import lux
    region = operation.get("region") or operation["parameters"].get("region")
    core.require(region in {"cn", "international"}, "Lux operation needs its explicit account region")
    pricing = operation["pricing"]
    try:
        import re
        ceiling = Decimal(str(pricing["unit_credits"])) * Decimal(str(pricing.get("quantity", 1)))
        core.require(ceiling.is_finite() and ceiling >= 0, "Lux needs an explicit approved credit ceiling")
        parameters = _lux_parameters(operation, request, project, region)
        items = lux.quote_items_for(operation["operation"], parameters)
        receipt = lux.quote(items, region)
        core.require(isinstance(receipt, dict) and receipt.get("ok") is True and receipt.get("region") == region,
                     "Lux live quote did not return the selected account region")
        quote = receipt["quote"]
        quote_id = quote["quoteId"]
        core.require(isinstance(quote_id, str) and re.fullmatch(r"quote_[0-9a-f]{32}", quote_id), "Lux live quote ID is invalid")
        total = quote["estimatedCreditsTotal"]
        core.require(type(total) in (int, float), "Lux live quote needs its actual credit total")
        estimated = Decimal(str(total))
        core.require(estimated.is_finite() and estimated >= 0, "Lux live quote credit total is invalid")
        output = Path(request["output_dir"]).resolve()
        receipt_path = output.parent.parent / ("lux-quote-" + operation["id"] + "-" + quote_id + ".json")
        core.write(receipt_path, {"schema": 1, "kind": "supplier-lux-live-quote", "region": region,
            "operation_id": operation["id"], "operation_sha256": core.digest(operation),
            "parameters": parameters, "quoted_at": core.now(), "approved_credit_ceiling": str(ceiling),
            "receipt": receipt})
        request["_live_quote_receipt"] = {"path": str(receipt_path), "sha256": core.file_hash(receipt_path),
            "quote_id": quote_id, "estimated_credits": str(estimated), "approved_credit_ceiling": str(ceiling)}
    except Exception as error:
        raise lux.LuxError("LIVE_QUOTE_FAILED", "Lux live quotation or its private receipt failed; no model was submitted. Check the approved credit ceiling, account connection and quote inputs.",
                           retryable=bool(getattr(error, "retryable", False)), unknown_submission=False) from None
    if estimated > ceiling:
        raise lux.LuxError("QUOTE_EXCEEDS_APPROVED_BUDGET",
                           "Lux live quote requires " + str(estimated) + " credits; the approved operation allows " + str(ceiling) + ". No model was submitted; revise the approved budget before continuing.",
                           unknown_submission=False)

    def submit():
        result = lux.submit(operation["operation"], parameters, region, quote_id=quote_id)
        return {"ok": result.get("ok", False), "task_id": str(result["taskId"])}
    return submit


def _submission_receipts(row, request):
    if request.get("_live_quote_receipt"):
        row["live_quote_receipt"] = request["_live_quote_receipt"]
    if request.get("_submitted_parameters"):
        row["submitted_parameters"] = request["_submitted_parameters"]
        row["upload_receipt"] = request["_upload_receipt"]


def _invoke(registry, operation, method, request, authorization, project):
    provider = next(p for p in registry["providers"] if p["id"] == operation["provider"])
    if provider.get("binding", {}).get("kind") != "builtin_lux":
        return suppliers.invoke_adapter(registry, provider["id"], method, request, base=project, authorization=authorization)
    from . import lux
    if method == "submit":
        return _prepare_lux_submission(operation, request, project)()
    region = operation.get("region") or operation["parameters"].get("region")
    core.require(region in {"cn", "international"}, "Lux operation needs its explicit account region")
    if method == "status":
        result = lux.status(request["task_id"], region)
        return {"ok": result.get("ok", False), "state": result.get("state"), "task_id": request["task_id"]}
    result = lux.fetch(request["task_id"], region, request["output_dir"], accepted_request={
        "operation": operation["operation"], "parameters": request.get("accepted_request", {}).get("parameters", operation["parameters"])})
    return {"ok": result.get("ok", False), "artifacts": result.get("downloads", []), "state": result.get("state")}


def _artifacts(response, output):
    core.require(response.get("ok") is True, "Provider output incomplete; preserve task and retry fetch only")
    artifacts = response.get("artifacts")
    core.require(isinstance(artifacts, list) and artifacts, "Fetch must return nonempty local artifacts")
    result, seen = [], set()
    for item in artifacts:
        path = Path(item["path"]).resolve()
        core.require(core.inside(path, output) and path.is_file() and path.stat().st_size > 0,
                     "Fetch artifact must be a nonempty file inside this job's output directory")
        digest = core.file_hash(path)
        core.require(not item.get("sha256") or item["sha256"] == digest, "Downloaded artifact hash mismatch")
        core.require(str(path) not in seen, "Duplicate fetch artifact")
        seen.add(str(path))
        result.append({"path": str(path), "sha256": digest, "bytes": path.stat().st_size,
                       "validation": item.get("validation", "file-integrity-only; material/scale/rig/native/art checks still required"),
                       **{k: item[k] for k in ("role", "format", "animation_id") if k in item}})
    return result


def _artifact_problems(row, *, cached=False):
    """Describe missing/changed bytes without treating recorded ready as proof."""
    artifacts = row.get("artifacts", [])
    if not artifacts:
        return [{"problem": "missing_artifact_records"}]
    result = []
    for item in artifacts:
        path = Path(item["path"])
        try:
            intact = False
            if not path.is_symlink() and path.is_file():
                before = path.stat()
                signature = (str(path), item["sha256"], before.st_dev, before.st_ino, before.st_size,
                             before.st_mtime_ns, before.st_ctime_ns)
                if cached and signature in _ARTIFACT_CHECKS:
                    intact = _ARTIFACT_CHECKS[signature]
                else:
                    matches = core.file_hash(path) == item["sha256"]
                    after = path.stat()
                    intact = matches and (after.st_dev, after.st_ino, after.st_size,
                        after.st_mtime_ns, after.st_ctime_ns) == signature[2:]
                    if cached:
                        if len(_ARTIFACT_CHECKS) >= 1024:
                            _ARTIFACT_CHECKS.clear()
                        _ARTIFACT_CHECKS[signature] = intact
        except OSError:
            intact = False
        if not intact:
            result.append({"path": str(path), "problem": "missing" if not path.exists() else "changed"})
    return result


def _recovery_artifacts(run, state, portfolio, operation, row):
    """Bind a re-download to the original accepted identity and owned paths."""
    recovery = row.get("artifact_recovery")
    core.require(isinstance(recovery, dict) and row.get("task_id")
                 and recovery.get("task_id") == row["task_id"]
                 and recovery.get("operation_digest") == core.digest(operation)
                 and recovery.get("context_digest") == core.digest(_context(operation, row))
                 and recovery.get("expected_artifacts") == row.get("artifacts"),
                 "Artifact recovery must retain the original task, operation and artifact identity")
    output = Path(recovery["output_dir"])
    core.require(core.inside(output, run / "artifact-recovery" / operation["id"])
                 and not output.is_symlink(), "Artifact recovery output must belong to this operation")
    published = {_publish_target(d, state["project"], portfolio, operation)
                 for d in _publish_declarations(operation["publish"])} if operation.get("publish") else set()
    for artifact in recovery["expected_artifacts"]:
        path = Path(artifact["path"])
        core.require(path.is_absolute() and path.absolute() == path.resolve() and
                     (path in published or core.inside(path, run / "outputs" / operation["id"])),
                     "Artifact recovery cannot change original ownership or follow redirected paths")
        core.require(not path.exists() or path.is_file(), "Artifact recovery will not replace a directory")
    return recovery


def _fetch_request(run, state, portfolio, operation, row, action_id=None):
    # Each invocation owns its staging location, so a retry cannot overwrite a
    # different result retained from a failed or interrupted original re-fetch.
    action_id = action_id or uuid.uuid4().hex
    core.require(core.safe_id(action_id), "Artifact fetch action needs a stable owned staging ID")
    output = (str(Path(_recovery_artifacts(run, state, portfolio, operation, row)["output_dir"])
                  / action_id)
              if row.get("artifact_recovery") else str(run / "outputs" / operation["id"]))
    if row.get("artifact_recovery"):
        core.require(Path(output).absolute() == Path(output).resolve(), "Artifact recovery staging was redirected")
    return {**_context(operation, row), "output_dir": output}


def _restore_artifacts(run, state, portfolio, operation, row, artifacts):
    """Restore exact original bytes, preserving damaged files without copying."""
    recovery = _recovery_artifacts(run, state, portfolio, operation, row)
    expected = recovery["expected_artifacts"]
    core.require(len(artifacts) == len(expected), "Recovered task returned a different artifact set")
    core.require(len({item["path"] for item in expected}) == len(expected),
                 "Original artifact recovery paths must be distinct")
    selected, used = [], set()
    for previous in expected:
        matches = [index for index, artifact in enumerate(artifacts) if index not in used
                   and artifact["sha256"] == previous["sha256"]
                   and all(artifact.get(k) == previous.get(k) for k in ("role", "format", "animation_id"))]
        core.require(matches,
                     "Recovered task bytes or artifact roles differ from the original; no files were replaced")
        used.add(matches[0])
        selected.append((artifacts[matches[0]], Path(previous["path"])))
    preserved = []
    with core.locked(Path(state["project"]) / "art" / ".supplier-publish"):
        # Validate the entire set before replacing even one canonical resource.
        _recovery_artifacts(run, state, portfolio, operation, row)
        for item, target in selected:
            core.require(core.file_hash(item["path"]) == item["sha256"], "Recovery download changed before restoration")
        for index, (item, target) in enumerate(selected):
            source = Path(item["path"])
            if target.exists() and core.file_hash(target) != item["sha256"]:
                digest = core.file_hash(target)
                backup = Path(recovery["output_dir"]).parent / "preserved" / (str(index) + "-" + digest + target.suffix)
                core.require(backup.absolute() == backup.resolve(), "Recovery preservation directory was redirected")
                backup.parent.mkdir(parents=True, exist_ok=True)
                if backup.exists():
                    core.require(backup.is_file() and core.file_hash(backup) == digest,
                                 "Preserved recovery file has conflicting content")
                    target.unlink()  # An identical task-owned duplicate already exists.
                else:
                    os.rename(target, backup)
                preserved.append({"path": str(backup), "sha256": digest, "original_path": str(target)})
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                source.unlink()  # Exact original bytes already restored by an interrupted action.
            else:
                os.rename(source, target)
            core.require(core.file_hash(target) == item["sha256"], "Restored artifact changed")
        # A previous isolated action may have moved damaged bytes before its
        # receipt was lost. Its task-owned content hashes remain discoverable.
        preservation_root = Path(recovery["output_dir"]).parent / "preserved"
        if preservation_root.is_dir():
            known = {item["path"] for item in preserved}
            for path in preservation_root.iterdir():
                index, separator, digest = path.stem.partition("-")
                core.require(path.absolute() == path.resolve() and path.is_file() and separator
                             and index.isdigit() and int(index) < len(expected)
                             and core.file_hash(path) == digest, "Preserved recovery evidence changed")
                if str(path) not in known:
                    preserved.append({"path": str(path), "sha256": digest,
                                      "original_path": expected[int(index)]["path"]})
    return {"artifacts": copy.deepcopy(expected), "preserved": preserved}


def _accept_fetch(run, state, portfolio, operation, row, response, output):
    core.require(not response.get("task_id") or str(response["task_id"]) == row["task_id"],
                 "Fetch returned another provider task identity")
    artifacts = _artifacts(response, output)
    if row.get("artifact_recovery"):
        return _restore_artifacts(run, state, portfolio, operation, row, artifacts)
    return {"artifacts": _publish(operation, artifacts, state["project"], portfolio,
        provenance={"run_id": run.name, "run_ledger": str(run / "supplier-run.json"),
                    "task_id": row["task_id"], "selection_digest": state["selection_digest"]})}


def _finish_artifact_recovery(row, response):
    if row.get("artifact_recovery"):
        row.setdefault("artifact_recovery_history", []).append({**row.pop("artifact_recovery"),
            "completed_at": core.now(), "preserved": response.get("preserved", [])})


def recover_artifacts(run_dir, operation_id, source_ref):
    """Queue only an exact re-fetch of an already completed original task."""
    core.require(isinstance(source_ref, str) and source_ref.strip(), "Artifact recovery needs its actual observation source")
    run = Path(run_dir).resolve()
    with core.locked(run):
        state, portfolio, registry, _, option = _load(run)
        operation = next((o for o in option["operations"] if o["id"] == operation_id), None)
        core.require(operation is not None, "Unknown supplier operation")
        row = state["operations"][operation_id]
        core.require(row.get("state") == "ready" and row.get("task_id") and not row.get("execution"),
                     "Only an unleased completed original task can recover artifacts")
        problems = _artifact_problems(row)
        core.require(problems and row.get("artifacts"), "Original artifacts are intact or have no recoverable identity")
        provider = next(p for p in registry["providers"] if p["id"] == operation["provider"])
        _freeze_account_profile(row, provider)
        attempt = len(row.get("artifact_recovery_history", [])) + 1
        row["artifact_recovery"] = {"task_id": row["task_id"], "operation_digest": core.digest(operation),
            "context_digest": core.digest(_context(operation, row)),
            "expected_artifacts": copy.deepcopy(row["artifacts"]), "source_ref": source_ref,
            "requested_at": core.now(), "problems": problems,
            "output_dir": str(run / "artifact-recovery" / operation_id / ("attempt-" + str(attempt)) / "downloads")}
        _recovery_artifacts(run, state, portfolio, operation, row)
        row.update(state="artifact_recovery", execution_next_at=0)
        state["state"] = "waiting"
        state["events"].append({"at": core.now(), "operation_id": operation_id, "artifact_recovery": "requested",
                                "source_ref": source_ref})
        core.write(run / "supplier-run.json", state)
    return status(run)


def _reserve(state, operation):
    pricing = operation["pricing"]
    credits = Decimal(str(pricing.get("unit_credits", 0))) * Decimal(str(pricing.get("quantity", 1)))
    direct = pricing.get("direct_money", {})
    money = ({direct["currency"]: str(Decimal(str(direct["unit_amount"])) * Decimal(str(pricing.get("quantity", 1))))}
             if direct else {})
    state["reservations"][operation["id"]] = {"wallet": pricing.get("wallet"), "credits": str(credits),
        "direct_money": money,
        "provider": operation["provider"], "operation_digest": core.digest(operation), "at": core.now()}


def _claim(state, run_dir, operation):
    """An H3 operation may be submitted by only one project run, even concurrently."""
    directory = Path(state["project"]) / "art" / ".supplier-claims"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (state["selection_digest"] + "-" + operation["id"] + ".json")
    claim = {"selection_digest": state["selection_digest"], "operation_digest": core.digest(operation),
             "run_dir": str(run_dir), "operation_id": operation["id"], "created_at": core.now(), "phase": "reserved"}
    guard_dir = directory / "unresolved"
    with core.locked(guard_dir):
        # Serialize the complete claim/guard publication. Atomic JSON writes
        # cannot leave an empty claim if a process dies before publishing it.
        if path.exists():
            previous = core.read(path)
            if not (previous.get("run_dir") == str(run_dir) and
                    previous.get("operation_digest") == core.digest(operation) and
                    previous.get("phase") == "reserved"):
                raise DuplicateOperationError(
                    "This H3 operation is already claimed by another run; recover the original, never duplicate it")
        guard_paths = _guard_paths(state, operation)
        guard_path = guard_paths[0]
        for candidate in guard_paths:
            previous = core.read(candidate) if candidate.exists() else {}
            unresolved = previous.get("phase") in {"reserved", "attempted", "unknown", "recovery_required"}
            if unresolved and not (previous.get("claim_path") == str(path) and previous.get("phase") == "reserved"):
                raise DuplicateOperationError(
                    "An unresolved original asset task exists, including under a previous H3 or legacy run; reconcile it before any replacement")
        if not path.exists():
            core.write(path, claim)
        core.write(guard_path, {"claim_path": str(path), "phase": "reserved", "provider": operation["provider"],
                               "asset_id": operation["asset_id"], "operation": operation["operation"]})
    return str(path)


def _guard_paths(state, operation):
    directory = Path(state["project"]) / "art" / ".supplier-claims" / "unresolved"
    legacy = directory / (core.digest([operation["asset_id"], operation["operation"]]) + ".json")
    if state.get("workspace") is None:
        return [legacy]
    owner = state["workspace"]["asset_owners"][operation["asset_id"]]
    scoped = directory / (core.digest([state["workspace"]["case_id"], owner,
                                      operation["asset_id"], operation["operation"]]) + ".json")
    return [scoped, legacy]  # A new directory contract cannot erase an old unknown charge.


def _guard_update(state, operation, row, phase):
    directory = Path(state["project"]) / "art" / ".supplier-claims" / "unresolved"
    with core.locked(directory):
        for path in _guard_paths(state, operation):
            previous = core.read(path) if path.exists() else {}
            if previous.get("claim_path") == row.get("claim_path"):
                core.write(path, {**previous, "phase": phase, "task_id": row.get("task_id"), "updated_at": core.now()})


def _workspace_owner(portfolio, asset_id, operation=None):
    """Ownership is approved portfolio data, never an instance-count heuristic."""
    from . import layout
    workspace = portfolio.get("workspace", {})
    owners = workspace.get("asset_owners", {})
    core.require(isinstance(owners, dict) and asset_id in owners,
                 "Workspace supplier assets need an explicit workspace.asset_owners entry")
    declared = layout.owner(owners[asset_id], allow_shared=True)
    if declared["scope"] == "style":
        core.require(declared["style_id"] in portfolio.get("selected_styles", []),
                     "Supplier asset owner must be one of the approved selected_styles")
    else:
        core.require(asset_id in workspace.get("shared_asset_ids", []),
                     "Shared supplier assets must be explicitly listed in workspace.shared_asset_ids")
    if operation is not None and "ownership" in operation:
        core.require(layout.owner(operation["ownership"], allow_shared=True) == declared,
                     "Operation ownership conflicts with the approved workspace asset owner")
    return declared


def _validate_run_path(portfolio, project, run_dir):
    if portfolio.get("workspace") is None:
        core.require(core.inside(run_dir, Path(project) / "art" / "experiments"),
                     "Supplier run must be inside project/art/experiments")
        return
    from . import layout
    layout.roots(project, portfolio)  # Validate the case/root/engine declaration first.
    core.require(core.safe_id(run_dir.name), "Supplier run needs a stable run ID")
    owners = {_workspace_owner(portfolio, aid).get("style_id") for aid in portfolio.get("required_assets", [])}
    allowed = {layout.run_root(project, portfolio, run_dir.name)}
    if len(owners) == 1 and None not in owners:
        allowed.add(layout.run_root(project, portfolio, run_dir.name, style_id=next(iter(owners))))
    core.require(run_dir in allowed,
                 "Supplier run must use the case shared production/runs path, or its sole owning style's production/runs path")
    scoped_style = None if run_dir == layout.run_root(project, portfolio, run_dir.name) else next(iter(owners))
    layout.validate_output(project, portfolio, run_dir, "supplier-run", style_id=scoped_style)


def _register_run(project, portfolio, run_dir):
    if portfolio.get("workspace") is None:
        return
    from . import layout
    layout.register(project, portfolio)
    # Only the public run location/identity enters the navigation. Private task
    # recovery data stays in its original supplier-run ledger.
    style_id = next((sid for sid in portfolio.get("selected_styles", [])
                     if core.inside(run_dir, layout.roots(project, portfolio, style_id=sid)["runs"])), None)
    layout.record_artifact(project, portfolio, run_dir / "supplier-portfolio.json", "supplier-run", style_id=style_id,
                           provenance={"run_id": run_dir.name, "ledger": str(run_dir / "supplier-run.json")})


def _publish_declarations(declaration):
    core.require(isinstance(declaration, dict) and set(declaration) <= {"path", "role", "animation_id", "additional"},
                 "Publish needs an approved primary path and optional additional artifact selectors")
    additional = declaration.get("additional", [])
    core.require(isinstance(additional, list), "Additional publish outputs must be a list")
    primary = {key: value for key, value in declaration.items() if key != "additional"}
    result = [primary] + additional
    for item in result:
        core.require(isinstance(item, dict) and set(item) <= {"path", "role", "animation_id"} and
                     isinstance(item.get("path"), str) and item["path"].strip(),
                     "Publish needs an explicit approved output path and optional primary role/animation ID")
        core.require(all(key not in item or core.safe_id(item[key]) for key in ("role", "animation_id")),
                     "Publish role and animation ID must be stable IDs")
    return result


def _publish_target(declaration, project, portfolio=None, operation=None):
    # Individual declarations have no nested 'additional' key.
    declaration = _publish_declarations(declaration)[0]
    target = core.resolve_input(declaration["path"], project)
    core.require(target.suffix.lower() == ".glb", "Publish a self-contained GLB")
    if portfolio is None or portfolio.get("workspace") is None:
        core.require(core.inside(target, Path(project) / "art"), "Publish a self-contained GLB inside the project's art directory")
    else:
        from . import layout
        core.require(operation is not None, "Workspace publication needs the exact approved asset operation")
        owned = _workspace_owner(portfolio, operation["asset_id"], operation)
        layout.validate_output(project, portfolio, declaration["path"], "asset", style_id=owned.get("style_id"),
                               asset_id=operation["asset_id"])
    return target


def _validate_publish_paths(option, project, portfolio=None):
    """Reject conflicting or ownerless stable sources before any provider charge."""
    targets = set()
    for operation in option["operations"]:
        if portfolio is not None and portfolio.get("workspace") is not None:
            _workspace_owner(portfolio, operation["asset_id"], operation)
            core.require(operation.get("operation") == "rig_check" or operation.get("publish"),
                         "Workspace asset-producing operations require an approved stable publish path; run outputs are production evidence")
        if "publish" not in operation:
            continue
        for declaration in _publish_declarations(operation["publish"]):
            target = _publish_target(declaration, project, portfolio, operation)
            core.require(target not in targets, "Each operation needs a unique publish path within its supplier option")
            targets.add(target)


def _publish(operation, artifacts, project, portfolio=None, provenance=None):
    """Move approved runtime GLBs into canonical asset ownership; retain raw evidence."""
    declaration = operation.get("publish")
    if not declaration:
        return artifacts
    selected, seen, target_paths = [], set(), set()
    for item in _publish_declarations(declaration):
        target = _publish_target(item, project, portfolio, operation)
        core.require(target not in target_paths, "Each published artifact needs a unique stable target")
        target_paths.add(target)
        candidates = [a for a in artifacts if Path(a["path"]).suffix.lower() == ".glb" and
                      all(key not in item or a.get(key) == item[key] for key in ("role", "animation_id"))]
        core.require(len(candidates) == 1, "Select exactly one primary GLB role for each approved publish path")
        artifact = candidates[0]
        core.require(id(artifact) not in seen, "Each published artifact needs one distinct approved target")
        seen.add(id(artifact))
        selected.append((artifact, Path(artifact["path"]), target))
    # A busy publication lock leaves this task's downloaded files intact. Check
    # all collisions before moving any file, preserving repairable task output.
    with core.locked(Path(project) / "art" / ".supplier-publish"):
        for item, source, target in selected:
            if target.exists():
                core.require(target.is_file() and core.file_hash(target) == item["sha256"],
                             "Publish would overwrite a different asset version")
        for item, source, target in selected:
            if target != source:
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    source.unlink()  # An identical task-owned duplicate; retain canonical bytes.
                else:
                    os.rename(source, target)  # No hidden physical-copy fallback.
                core.require(core.file_hash(target) == item["sha256"], "Published asset hash changed")
                item["path"] = str(target)
            item["published"] = True
            if portfolio is not None and portfolio.get("workspace") is not None:
                from . import layout
                owned = _workspace_owner(portfolio, operation["asset_id"], operation)
                item.update(case_id=portfolio["workspace"]["case_id"], asset_id=operation["asset_id"], ownership=owned)
                layout.record_artifact(project, portfolio, target, "asset", style_id=owned.get("style_id"),
                    asset_id=operation["asset_id"], provenance={"provider": operation["provider"],
                    "operation_id": operation["id"], "model_version": operation["model_version"],
                    "operation_digest": core.digest(operation), **(provenance or {})}, write_manifest=True)
    return artifacts


def _freeze_account_profile(row, provider):
    """Persist routing from the hash-bound registry, never from a provider reply."""
    profile = provider.get("account_profile") if provider.get("binding", {}).get("kind") == "builtin_api" else None
    if profile is None:
        return  # Historical unprofiled tasks retain their original adapter route.
    from . import account_profiles
    binding = {"account_profile": profile,
               "account_profile_sha256": account_profiles.profile_digest(provider["id"], profile)}
    for recorded in (row, row.get("recovery", {})):
        core.require(isinstance(recorded, dict), "Recovery metadata must be a private JSON object")
        for key, value in binding.items():
            core.require(key not in recorded or recorded[key] == value,
                         "Persisted task account differs from its frozen supplier registry")
    row.update(copy.deepcopy(binding))


def _context(operation, row):
    accepted = {k: operation[k] for k in ("operation", "model_version", "parameters")}
    if row.get("submitted_parameters"):
        accepted["parameters"] = row["submitted_parameters"]
    recovery = copy.deepcopy(row.get("recovery", {}))
    core.require(isinstance(recovery, dict), "Recovery metadata must be a private JSON object")
    for key in ("account_profile", "account_profile_sha256"):
        if key in row:
            core.require(key not in recovery or recovery[key] == row[key],
                         "Recovery cannot switch the frozen task account")
            accepted[key] = copy.deepcopy(row[key])
            if recovery:
                recovery[key] = copy.deepcopy(row[key])
        elif key in recovery:  # Preserve recovery from pre-freeze profiled runs.
            accepted[key] = copy.deepcopy(recovery[key])
    return {"task_id": row["task_id"], "recovery": recovery, "accepted_request": accepted}


def _record_cost(state, oid, row, response, blocked):
    """Settlement may arrive during polling, not only in the POST response."""
    actual = response.get("consumed_credits", response.get("actual_credits"))
    if actual is not None:
        consumed = suppliers._number(actual, "Actual consumed credits")
        if row.get("consumed_credits") != str(consumed):
            row.setdefault("cost_observations", []).append({"at": core.now(), "credits": str(consumed)})
        row["consumed_credits"] = str(consumed)
        if consumed > Decimal(state["reservations"][oid]["credits"]):
            blocked.append("Actual supplier charge exceeded the approved reservation; stop new submissions")
            state["cost_overrun"] = oid
    if response.get("consumed_money") is not None:
        actual = response["consumed_money"]
        amount = suppliers._number(actual["amount"], "Actual consumed money")
        row["consumed_money"] = {"currency": actual["currency"], "amount": str(amount)}
        ceiling = state["reservations"][oid]["direct_money"].get(actual["currency"])
        if ceiling is None or amount > Decimal(ceiling):
            blocked.append("Actual cash charge exceeded the approved reservation; stop new submissions")
            state["cost_overrun"] = oid


def step(run_dir, registry_refresh=None, capabilities=None, session_id=None, invoker=None, max_submissions=1):
    """Advance independent ready jobs once; never sleep, retry POST, or substitute a vendor."""
    core.require(type(max_submissions) is int and 1 <= max_submissions <= 16, "Bound submissions per step to 1..16")
    run_dir = Path(run_dir).resolve()
    call = invoker or _invoke
    with core.locked(run_dir):
        state, portfolio, registry, selection, option = _load(run_dir)
        if registry_refresh is not None:
            core.require(suppliers.registry_digest(registry_refresh) == state["registry_digest"],
                         "Readiness refresh cannot change the approved supplier bindings")
            suppliers.validate_registry(registry_refresh, base=state["project"])
            registry = registry_refresh
            core.write(run_dir / "supplier-registry.json", registry)
        if capabilities is not None:
            core.require(session_id, "Readiness refresh requires current host session")
            core.write(run_dir / "supplier-readiness.json", capabilities)
            state["readiness"] = {"sha256": core.digest(capabilities), "session_id": session_id}
        blocked = (["Actual supplier charge exceeded its approved reservation; resolve the cost overrun before new submissions"]
                   if state.get("cost_overrun") else [])
        if portfolio.get("workspace") is None:
            blocked.append("Historical run has no approved workspace contract; existing task recovery only")
        try:
            suppliers.validate_selection(selection, portfolio, registry, base=state["project"])
            if portfolio.get("workspace") is not None:
                _validate_run_path(portfolio, Path(state["project"]), run_dir)
                _validate_publish_paths(option, state["project"], portfolio)
            if state["expansion"]:
                for operation in option["operations"]:
                    provider = next(p for p in registry["providers"] if p["id"] == operation["provider"])
                    verify = provider.get("verification", {})
                    from . import account_profiles
                    profile = provider.get("account_profile")
                    profile_sha = account_profiles.profile_digest(provider["id"], profile) if profile is not None else None
                    core.require(suppliers._verification(verify.get("operations", {}).get(operation["operation"]),
                                 state["project"], account_profile_sha256=profile_sha),
                                 "Qualification-only operation cannot enter expansion before actual verification")
            checkpoint = Path(state["workflow"]["path"])
            core.require(core.file_hash(checkpoint) == state["workflow"]["sha256"], "Workflow changed")
            core.require(core.runtime_snapshot()["sha256"] == state["runtime_digest"], "Producer runtime changed")
            readiness = core.read(run_dir / "supplier-readiness.json")
            core.require(core.digest(readiness) == state["readiness"]["sha256"], "Readiness receipt changed")
            _gate(portfolio, selection, checkpoint, state["project"], readiness,
                  state["readiness"]["session_id"], state["expansion"])
            for operation in option["operations"]:
                core.require(_inputs(operation, state["project"]) == state["inputs"][operation["id"]], "Operation inputs changed")
            for oid, row in state["operations"].items():
                if row.get("state") == "ready":
                    core.require(not _artifact_problems(row),
                                 "Completed artifacts missing or changed for " + oid + "; use supplier-jobs recover-artifacts")
        except (ValueError, OSError, KeyError, TypeError):
            blocked.append("Approved inputs, current capability, quote or verification changed; existing task recovery only")
        for oid, row in state["operations"].items():
            if row.get("state") == "ready" and _artifact_problems(row):
                blocked.append("Completed artifacts missing or changed for " + oid + "; use supplier-jobs recover-artifacts")
        submitted, accepted, attempted = 0, 0, 0
        control_blocked = []
        limits = portfolio.get("execution_limits", {}).get("max_inflight_per_provider", {})
        core.require(isinstance(limits, dict) and all(core.safe_id(k) and type(v) is int and 1 <= v <= 32
                     for k, v in limits.items()), "Provider concurrency caps must be explicit integers 1..32")
        for operation in option["operations"]:
            oid = operation["id"]
            row = state["operations"][oid]
            if row.get("state") == "artifact_recovery":
                # Re-fetch only the accepted task; no production/readiness gate,
                # new reservation, provider quote, query or create is involved.
                authorization = {"selection": selection, "portfolio": portfolio, "operation_id": oid}
                try:
                    core.require(not row.get("execution"), "Recover the leased executor action before manual recovery")
                    request = _fetch_request(run_dir, state, portfolio, operation, row)
                    response = call(registry, operation, "fetch", request, authorization, state["project"])
                    accepted_fetch = _accept_fetch(run_dir, state, portfolio, operation, row, response, request["output_dir"])
                    _record_cost(state, oid, row, response, blocked)
                    _finish_artifact_recovery(row, accepted_fetch)
                    row.update(state="ready", artifacts=accepted_fetch["artifacts"], execution_next_at=0)
                    row.pop("last_error", None)
                except Exception:
                    row["last_error"] = "Original artifact recovery incomplete; no generation was submitted"
                    blocked.append("Original artifact recovery incomplete for " + oid + "; retain the original task")
                core.write(run_dir / "supplier-run.json", state)
                continue
            if row["state"] in {"unknown", "submitting", "failed", "cancelled", "rejected", "ready", "budget_exceeded", "blocked_duplicate", "recovery_required"}:
                continue
            authorization = {"selection": selection, "portfolio": portfolio, "operation_id": oid}
            if not row.get("task_id"):
                if blocked or attempted >= max_submissions:
                    continue
                if not all(state["operations"][d]["state"] == "ready" for d in operation.get("depends_on", [])):
                    continue
                inflight = sum(value.get("provider") == operation["provider"] and value.get("state") in
                    {"submitting", "submitted", "queued", "running", "unknown", "recovery_required"}
                    for value in state["operations"].values())
                if inflight >= limits.get(operation["provider"], 1):
                    continue
                from . import character_gate
                try:
                    preflight = character_gate.for_supplier(operation, state, run_dir, registry)
                    if preflight is not None:
                        row["character_preflight"] = preflight
                except (ValueError, OSError, KeyError, TypeError) as error:
                    row["operational_blocker"] = str(error)
                    control_blocked.append(oid + ": " + str(error))
                    continue
                from .production_control import guard_submission
                provider = next(p for p in registry["providers"] if p["id"] == operation["provider"])
                request = {k: operation[k] for k in ("operation", "model_version", "parameters")}
                request.update(inputs=state["inputs"][oid], dependencies={d: {k: v for k, v in state["operations"][d].items()
                    if k in {"provider", "task_id", "artifacts", "state"}}
                    for d in operation.get("depends_on", [])}, quote=operation["pricing"],
                    output_dir=str(run_dir / "outputs" / oid))
                prepared_submit = None
                if invoker is None and provider.get("binding", {}).get("kind") == "builtin_lux":
                    from . import lux
                    try:
                        guard_submission(state["project"], portfolio, operation["asset_id"], operation["operation"],
                                         run_dir, core.digest(operation), dry_run=True)
                    except (ValueError, OSError, KeyError, TypeError) as error:
                        row["operational_blocker"] = str(error)
                        control_blocked.append(oid + ": " + str(error))
                        continue
                    try:
                        attempted += 1  # Bound failed preparations as well as actual POSTs per step.
                        prepared_submit = _prepare_lux_submission(operation, request, state["project"])
                    except (lux.LuxError, ValueError, OSError, KeyError, TypeError) as error:
                        _submission_receipts(row, request)
                        row["operational_blocker"] = str(error)
                        row["pre_submit_error"] = {"code": getattr(error, "code", "PREPARE_FAILED"),
                            "model_submitted": False, "at": core.now()}
                        control_blocked.append(oid + ": " + str(error))
                        continue  # No claim, reservation or POST; original run can resume.
                    _submission_receipts(row, request)
                    row.pop("pre_submit_error", None)
                try:
                    # Recheck after quotation: another run may have claimed or
                    # exhausted this family while the read-only request ran.
                    guard_submission(state["project"], portfolio, operation["asset_id"], operation["operation"],
                                     run_dir, core.digest(operation))
                    row.pop("operational_blocker", None)
                except (ValueError, OSError, KeyError, TypeError) as error:
                    row["operational_blocker"] = str(error)
                    if "already belongs to another attempt" in str(error):
                        row["state"] = "blocked_duplicate"
                    control_blocked.append(oid + ": " + str(error))
                    continue
                try:
                    row["claim_path"] = _claim(state, run_dir, operation)
                except DuplicateOperationError:
                    row["state"] = "blocked_duplicate"
                    core.write(run_dir / "supplier-run.json", state)
                    from .production_control import release_unsubmitted
                    release_unsubmitted(state["project"], portfolio, operation["asset_id"], operation["operation"],
                                        run_dir, core.digest(operation))
                    blocked.append("Operation already belongs to another run: " + oid)
                    continue
                except (ValueError, OSError) as error:
                    # Local contention/I/O is not evidence of another paid
                    # attempt. Keep the original pending operation recoverable.
                    row["operational_blocker"] = str(error)
                    control_blocked.append(oid + ": " + str(error))
                    continue
                # One reservation per operation is persisted BEFORE crossing the adapter boundary.
                _reserve(state, operation)
                _freeze_account_profile(row, provider)
                row.update(state="submitting", provider=operation["provider"], request_digest=core.digest(operation))
                core.write(run_dir / "supplier-run.json", state)
                response = None
                try:
                    claim = core.read(row["claim_path"])
                    core.write(row["claim_path"], {**claim, "phase": "attempted", "attempted_at": core.now()})
                    _guard_update(state, operation, row, "attempted")
                    submitted += 1  # Count attempts, including uncertain/rejected results.
                    if prepared_submit is None:
                        attempted += 1
                    response = prepared_submit() if prepared_submit is not None else call(
                        registry, operation, "submit", request, authorization, state["project"])
                    _submission_receipts(row, request)
                    if response.get("task_id"):
                        row["task_id"] = str(response["task_id"])
                    if isinstance(response.get("recovery"), dict):
                        row["recovery"] = response["recovery"]
                    if row.get("task_id"):
                        accepted += 1
                        core.write(row["claim_path"], {**claim, "phase": "accepted", "task_id": row["task_id"],
                                   "recovery": row.get("recovery", {}), "accepted_at": core.now()})
                        _record_cost(state, oid, row, response, blocked)
                    if response.get("state") == "recovery_required" and row.get("task_id"):
                        row.update(state="recovery_required", submitted_at=core.now())
                        _guard_update(state, operation, row, "recovery_required")
                        core.write(run_dir / "supplier-run.json", state)
                        blocked.append("Accepted task needs original recovery identifiers: " + oid)
                        continue
                    core.require(response.get("ok") is True and isinstance(response.get("task_id"), str)
                                 and bool(response["task_id"].strip()), "Submission did not return an exact task ID")
                    row.update(state="submitted", task_id=response["task_id"], submitted_at=core.now())
                    _guard_update(state, operation, row, "accepted")
                except Exception as error:
                    _submission_receipts(row, request)
                    definite = getattr(error, "unknown_submission", None) is False
                    if isinstance(response, dict) and response.get("unknown_submission") is False and not row.get("task_id"):
                        definite = True
                    row["state"] = "rejected" if definite else "unknown"
                    _guard_update(state, operation, row, row["state"])
                    row["next"] = ("Inspect the definite rejection and revise the affected request" if row["state"] == "rejected" else
                                   "Reconcile the original provider task; never issue another submission or vendor fallback")
                    core.write(run_dir / "supplier-run.json", state)
                    blocked.append("Submission needs inspection: " + oid)
                    continue
                core.write(run_dir / "supplier-run.json", state)
            # Expired production approval never prevents recovering the original task.
            try:
                provider = next(p for p in registry["providers"] if p["id"] == operation["provider"])
                _freeze_account_profile(row, provider)
                response = call(registry, operation, "status", _context(operation, row), authorization, state["project"])
                core.require(response.get("ok") is True, "Task query failed")
                core.require(not response.get("task_id") or str(response["task_id"]) == row["task_id"],
                             "Provider query returned another task identity")
                observed = response.get("state")
                core.require(observed in {"queued", "running", "succeeded", "failed", "cancelled"}, "Unknown task state")
                _record_cost(state, oid, row, response, blocked)
                row.update(state=observed, checked_at=core.now())
                if observed == "succeeded":
                    output = run_dir / "outputs" / oid
                    output.mkdir(parents=True, exist_ok=True)
                    response = call(registry, operation, "fetch", {**_context(operation, row), "output_dir": str(output)}, authorization, state["project"])
                    accepted_fetch = _accept_fetch(run_dir, state, portfolio, operation, row, response, output)
                    _record_cost(state, oid, row, response, blocked)
                    row.update(artifacts=accepted_fetch["artifacts"], state="ready")
            except Exception:
                row["last_error"] = "Query/download incomplete; preserve the task ID and resume without generation"
            core.write(run_dir / "supplier-run.json", state)
        blocked.extend(control_blocked)
        states = {v["state"] for v in state["operations"].values()}
        state["state"] = ("blocked" if blocked or states & {"unknown", "submitting", "failed", "cancelled", "rejected", "budget_exceeded", "blocked_duplicate", "recovery_required"}
                          else "assets_ready" if states <= {"ready"} else "waiting")
        state["blockers"] = blocked
        state["events"].append({"at": core.now(), "submission_attempts": submitted, "accepted_tasks": accepted, "state": state["state"]})
        core.write(run_dir / "supplier-run.json", state)
    return status(run_dir)


def reconcile(run_dir, operation_id, task_id, note, recovery=None):
    core.require(isinstance(task_id, str) and task_id.strip() and isinstance(note, str) and note.strip(),
                 "Reconciliation needs the original task ID and inspection evidence")
    run_dir = Path(run_dir).resolve()
    with core.locked(run_dir):
        state, _, registry, _, option = _load(run_dir)
        row = state["operations"].get(operation_id, {})
        core.require(row.get("state") in {"unknown", "submitting", "recovery_required"}, "Only the original ambiguous submission can be reconciled")
        core.require(not row.get("task_id") or row["task_id"] == task_id, "Cannot replace the original known provider task ID")
        operation = next(o for o in option["operations"] if o["id"] == operation_id)
        provider = next(p for p in registry["providers"] if p["id"] == operation["provider"])
        _freeze_account_profile(row, provider)
        if recovery is not None:
            core.require(isinstance(recovery, dict), "Recovery metadata must be a private JSON object")
            previous = row.get("recovery", {})
            core.require(isinstance(previous, dict), "Recovery metadata must be a private JSON object")
            core.require(all(key not in previous or previous[key] == value for key, value in recovery.items()),
                         "Reconciliation cannot replace persisted recovery identity")
            merged = {**previous, **copy.deepcopy(recovery)}
            for key in ("task_id", "task_uuid"):
                core.require(key not in merged or merged[key] == task_id,
                             "Recovery metadata belongs to another supplier task")
            core.require("provider" not in merged or merged["provider"] == operation["provider"],
                         "Recovery metadata belongs to another supplier")
            row["recovery"] = merged
            _freeze_account_profile(row, provider)
        row.update(state="submitted", task_id=task_id, reconciliation={"note": note, "at": core.now()})
        if row.get("claim_path"):
            _guard_update(state, operation, row, "accepted")
        core.write(run_dir / "supplier-run.json", state)
    return status(run_dir)


def status(run_dir):
    state, _, _, _, _ = _load(run_dir)
    totals = {}
    money = {}
    for reservation in state["reservations"].values():
        if reservation.get("wallet"):
            key = reservation["wallet"]
            totals[key] = totals.get(key, Decimal(0)) + Decimal(reservation["credits"])
        for currency, amount in reservation.get("direct_money", {}).items():
            money[currency] = money.get(currency, Decimal(0)) + Decimal(amount)
    problems = {oid: _artifact_problems(row, cached=True) for oid, row in state["operations"].items() if row.get("state") == "ready"}
    problems = {oid: issues for oid, issues in problems.items() if issues}
    return {"ok": state["state"] not in {"blocked"} and not problems,
        "state": "artifact_recovery_required" if problems else state["state"], "artifact_problems": problems,
        "selected_option": state["selected_option"], "portfolio_digest": state["portfolio_digest"],
        "operations": {oid: {k: v for k, v in row.items() if k != "recovery"} |
                       ({"recovery_fields": sorted(row["recovery"])} if row.get("recovery") else {})
                       for oid, row in state["operations"].items()}, "wallet_reservations": {k: str(v) for k, v in totals.items()},
        "money_reservations": {k: str(v) for k, v in money.items()},
        "blockers": state.get("blockers", []), "cost_overrun": state.get("cost_overrun"),
        "delivery": "asset production only; native assembly and H4/H5 acceptance remain required"}
