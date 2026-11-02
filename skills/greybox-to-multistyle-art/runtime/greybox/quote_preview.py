"""Quote an H1/H2-approved production draft without creating a production run.

A preview permits reference upload and account quotation only. It cannot submit,
poll or download models and never records approval. ``bridge`` injection is an
offline test seam; callable production routing is the pinned greybox.lux bridge.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re

from . import core, workflow


def _amount(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _quote(result, sequences):
    core.require(isinstance(result, dict) and result.get("ok", True) is not False,
                 "Provider quotation failed; no usable current price")
    nested = result.get("data") if isinstance(result.get("data"), dict) else {}
    quote = result.get("quote", nested.get("quote", {}))
    core.require(isinstance(quote, dict) and re.fullmatch(r"quote_[0-9a-f]{32}", str(quote.get("quoteId", ""))),
                 "Quote returned no valid provider quoteId")
    total, details = quote.get("estimatedCreditsTotal"), quote.get("details")
    core.require(_amount(total) and isinstance(details, dict) and set(details) == set(sequences)
                 and all(_amount(value) for value in details.values()),
                 "Quote needs explicit nonnegative total and every per-asset cost; unknown cost cannot be proposed")
    core.require(math.isclose(total, sum(details.values()), rel_tol=1e-12, abs_tol=1e-9),
                 "Quote total differs from per-asset costs")
    try:
        quoted = datetime.fromisoformat(str(quote["quotedAt"]).replace("Z", "+00:00"))
        expires = datetime.fromisoformat(str(quote["expiresAt"]).replace("Z", "+00:00"))
        current = datetime.now(timezone.utc)
        valid = quoted.utcoffset() is not None and expires.utcoffset() is not None
        valid = valid and expires > current and expires > quoted and (quoted - current).total_seconds() <= 300
    except (KeyError, TypeError, ValueError):
        valid = False
    core.require(valid, "Quote needs current timezone-aware quotedAt/expiresAt; expired prices cannot be proposed")
    return quote


def _target(output, project):
    target = core.resolve_input(output, project)
    install = Path(__file__).resolve().parents[2]
    installed_roots = (Path.home() / ".codex" / "skills", Path.home() / ".agents" / "skills")
    codex_root = os.environ.get("CODEX_HOME")
    if codex_root:
        installed_roots += (Path(codex_root) / "skills",)
    core.require(core.inside(target, project), "Quote preview output must remain inside the project")
    core.require(not core.inside(target, install) and not any(core.inside(target, root) for root in installed_roots),
                 "Quote preview must not write inside the skill installation")
    core.require(target.suffix.lower() == ".json" and target.name not in {"run.json", "plan.frozen.json", "approval.json"},
                 "Quote preview needs a separate JSON receipt, never a run or approval file")
    core.require(not target.exists(), "Quote preview output already exists; choose a new receipt path")
    return target


def _baseline(plan, checked):
    core.require(plan["contract"]["scene"] == checked["baseline_scene"],
                 "Executable scene differs from approved gameplay baseline")
    validation = plan["contract"].get("validation", {})
    steps = {step.get("id", step.get("name")): step for step in validation.get("steps", []) if step.get("expect")}
    required = set(validation.get("required_checks", steps))
    core.require(validation.get("mode", "playable") == checked["baseline_validation_mode"]
                 and set(checked["baseline_required_steps"]) <= required
                 and all(steps.get(key) == value for key, value in checked["baseline_required_steps"].items()),
                 "Executable gameplay validation differs from approved baseline required checks")


def preview(plan_file, project, output, capability_file, session_id, bridge=None):
    """Return a URL-free summary; save exact quote requests in an exclusive receipt.

    H3 production approval and native proxy are intentionally not prerequisites
    for collecting prices. H1 selection and H2 atlas/spatial decisions must be
    valid. This receipt is informational and grants no generation authority.
    """
    project = Path(project).expanduser().resolve()
    plan_path = core.resolve_input(plan_file, project)
    core.require(core.inside(plan_path, project) and plan_path.is_file(),
                 "Quote preview draft plan must be an actual project file")
    target = _target(output, project)  # Fail before upload or provider quotation.
    plan = core.read(plan_path)
    core.validate_plan(plan)
    core.require(plan.get("purpose", "production") == "production",
                 "Quote preview requires a production draft, not a technical fixture or art proxy")
    assets = [asset for asset in plan.get("assets", []) if asset.get("generation")]
    core.require(assets, "No generation tasks to quote")
    core.require(isinstance(session_id, str) and bool(session_id.strip()),
                 "Quote preview needs the actual current host session_id")
    capabilities_path = core.resolve_input(capability_file, project)
    core.require(capabilities_path.is_file(), "Current capability receipt is missing")
    capabilities = core.read(capabilities_path)
    gate = plan.get("workflow", {})
    core.require(gate.get("path") and gate.get("sha256"), "Quote preview needs approved H1/H2 workflow evidence")
    checkpoint = core.resolve_input(gate["path"], project)
    core.require(core.inside(checkpoint, project) and checkpoint.is_file()
                 and core.file_hash(checkpoint) == gate["sha256"], "Workflow receipt missing/changed")
    data = core.read(checkpoint)
    core.require(data.get("requires_lux") is True, "This draft uses Lux; preflight must require Lux")
    assessment = workflow.check_plan_capabilities(plan, project, capabilities, session_id)
    core.require(assessment["ok"], "BLOCKED_CAPABILITY: " + ",".join(
        b["capability"] + ":" + b["reason"] for b in assessment["blockers"]))
    checked = workflow.inspect_workflow(checkpoint, project, [style["id"] for style in plan["styles"]],
        expected_session=session_id, proxy_only=True, capability_report=capabilities,
        required_capabilities=sorted(set(workflow.plan_capability_requirements(plan, project)) | {"lux"}))
    _baseline(plan, checked)
    core.require(core.file_hash(checkpoint) == gate["sha256"], "Workflow receipt changed during preview validation")
    channel = capabilities["capabilities"]["lux"]["channel"]
    core.require(all(asset["generation"]["region"] == channel["region"] for asset in assets),
                 "Quote region is not covered by the current verified Lux account; split regional runs")
    if bridge is None:
        from . import lux as bridge
    # There is no user-selectable bridge/provider route in this API. The current
    # channel check above requires bundled_openapi/greybox.lux, not an MCP claim.
    core.require(all(callable(getattr(bridge, name, None)) for name in ("validate", "upload", "quote_items_for", "quote")),
                 "Pinned Lux bridge is missing a required callable quotation operation")
    original_plan_hash = core.file_hash(plan_path)
    original_capabilities_hash = core.file_hash(capabilities_path)
    inputs = core.input_snapshot(project, plan)
    groups, uploads, requests, asset_summary = {}, {}, [], []
    for asset in assets:
        generation = asset["generation"]
        parameters = dict(generation["parameters"])
        checked_reference = core._check_generation_reference(asset, project)
        references = checked_reference.get("images", [])
        reference_receipt = references[0] if len(references) == 1 else None
        if references:
            urls = []
            for reference in references:
                key = generation["region"] + ":" + reference["sha256"]
                if key not in uploads:
                    upload = bridge.upload(reference["path"], generation["region"])
                    core.require(isinstance(upload, dict), "Uploader returned no URL")
                    url = upload.get("url") or upload.get("data", {}).get("url")
                    core.require(isinstance(url, str) and bool(url), "Uploader returned no URL")
                    uploads[key] = url
                urls.append(uploads[key])
            parameters["img" if len(urls) == 1 else "imgs"] = urls[0] if len(urls) == 1 else urls
        bridge.validate(generation["operation"], parameters, generation["region"])
        row = {"asset_id": asset["id"], "route": asset["route"], "rationale": asset["reason"],
               "operation": generation["operation"], "region": generation["region"],
               "parameters": parameters, "parameters_hash": core.digest(parameters)}
        if reference_receipt:
            row["reference"] = reference_receipt
        elif references:
            row["references"] = references
        groups.setdefault(generation["region"], []).append(row)
    quotes, totals = [], {}
    for region, rows in groups.items():
        items = {}
        for sequence, row in enumerate(rows, 1):
            index = str(sequence)
            added = bridge.quote_items_for(row["operation"], row["parameters"], index)
            core.require(isinstance(added, dict) and set(added) == {index},
                         "Pinned Lux quote builder returned an unexpected item sequence")
            items.update(added)
        quote = _quote(bridge.quote(items, region), items)
        for sequence, row in enumerate(rows, 1):
            amount = quote["details"][str(sequence)]
            row.update(quote_id=quote["quoteId"], quoted_credits=amount)
            asset_summary.append({"asset_id": row["asset_id"], "route": row["route"], "operation": row["operation"],
                "region": region, "version": row["parameters"].get("version"),
                "faceCount": row["parameters"].get("faceCount"), "rationale": row["rationale"], "quoted_credits": amount})
        totals[region] = quote["estimatedCreditsTotal"]
        requests.extend(rows)
        quotes.append({"region": region, "items": items, "quote": quote})
    # Never freeze a proposal against content that changed during upload/quote.
    core.require(core.file_hash(plan_path) == original_plan_hash and core.read(plan_path) == plan
                 and core.file_hash(capabilities_path) == original_capabilities_hash and core.read(capabilities_path) == capabilities
                 and core.input_snapshot(project, plan) == inputs,
                 "Quote preview inputs changed during quotation; revise and quote the current draft")
    receipt = {"schema": 1, "kind": "greybox-quote-preview", "created_at": core.now(),
        "plan": {"path": str(plan_path), "sha256": original_plan_hash, "digest": core.digest(plan),
                 "execution_plan_digest": workflow.execution_plan_digest(plan)},
        "workflow": {"path": str(checkpoint), "sha256": gate["sha256"], "stage_digests": checked["stage_digests"]},
        "capabilities": {"path": str(capabilities_path), "sha256": original_capabilities_hash,
                         "session_id": session_id, "lux_channel": channel},
        "inputs": inputs, "requests": requests, "quotes": quotes, "assets": asset_summary,
        "regional_totals": totals, "paid_generation_authorized": False, "next": "H3",
        "note": "Current quotation only. Human plan/quote authorization is required before model submission; this receipt is never run approval."}
    receipt["receipt_hash"] = core.digest(receipt)
    payload = json.dumps(receipt, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(str(target), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        core.require(False, "Quote preview output already exists; no file was overwritten")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return {"ok": True, "receipt": str(target), "receipt_hash": receipt["receipt_hash"],
            "sha256": core.file_hash(target), "plan_hash": core.digest(plan),
            "execution_plan_digest": receipt["plan"]["execution_plan_digest"],
            "assets": asset_summary, "regional_totals": totals,
            "quotes": [{"region": item["region"], **{key: item["quote"][key] for key in ("quoteId", "quotedAt", "expiresAt")}} for item in quotes],
            "paid_generation_authorized": False, "next": "H3"}
