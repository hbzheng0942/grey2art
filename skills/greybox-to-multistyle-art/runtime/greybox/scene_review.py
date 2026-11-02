"""Paired concept/native review inputs and coverage, never an aesthetic judge.

This is evidence inside H3/H4, not a new approval or production ledger. Images
stay in their owning project; the report only references their current bytes.
"""
from __future__ import annotations

import copy
import math
from pathlib import Path

from . import core

CONTRACT = "feature-view-v1"
H3_CRITERION_ROLES = {
    "visual_route_responsibility": {"production_table", "bom_board"},
    "bom_and_assembly_readable": {"bom_board", "assembly_map"},
    "complete_sample_scope": {"production_table", "assembly_recipe"},
}


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _one(stage, role, project):
    items = [e for e in stage.get("evidence", []) if e.get("role") == role]
    core.require(len(items) == 1, "Scene comparison needs exactly one " + role)
    item = items[0]
    path = core.resolve_input(item.get("path", ""), project)
    core.require(core.inside(path, project) and path.is_file()
                 and core.file_hash(path) == item.get("sha256"), "Scene comparison evidence missing or stale: " + role)
    return core.read(path), {"path": str(path), "sha256": item["sha256"]}


def _image(item, project):
    path = core.resolve_input(item.get("path", ""), project)
    core.require(core.inside(path, project) and path.is_file()
                 and core.file_hash(path) == item.get("sha256"), "Scene comparison image missing or stale")
    from .modeling_refs import _decode
    width, height, _, _ = _decode(path.read_bytes())
    return {"path": str(path), "sha256": item["sha256"], "dimensions": [width, height]}


def _comparisons(table, atlas_stage, atlas, manifest, views, project):
    from . import workflow
    contract = table["sample_contract"]
    target_images = {e.get("id"): _image(e, project) for e in atlas_stage.get("evidence", []) if e.get("role") == "concept_image"}
    targets = {}
    for view in atlas.get("views", []):
        image = target_images.get(view.get("concept_image_id"))
        core.require(image and image["sha256"] == view.get("concept_sha256"), "Scene comparison concept view is unbound")
        targets[view["id"]] = image
    captures = {}
    for capture in manifest["captures"]:
        captures.setdefault(capture["view_id"], []).append(_image(capture, project))
    features = table.get("visual_features")
    core.require(isinstance(features, list) and features, "Scene comparison needs H3 visual features")
    feature_ids = workflow._ids([f.get("id") for f in features], "Scene comparison feature IDs")
    core.require(set(contract["required_critical_features"]) <= feature_ids, "Scene comparison omits critical features")
    comparisons = []
    for feature in features:
        core.require(feature.get("concept_view_id") in targets and _text(feature.get("target")),
                     "Scene comparison feature needs its concept view and target")
        native_views = workflow._ids(feature.get("native_view_ids"), "Scene comparison feature views")
        core.require(native_views <= set(contract["required_view_ids"]), "Scene comparison feature names unknown native views")
        for view_id in sorted(native_views):
            comparisons.append({"id": "feature/" + feature["id"] + "/" + view_id, "kind": "feature",
                "feature_id": feature["id"], "native_view_id": view_id,
                "importance": feature.get("importance"), "target_description": feature["target"],
                "targets": [targets[feature["concept_view_id"]]], "actuals": captures[view_id]})
    for view in views:
        if view["framing"] != "whole_composition":
            continue
        choices = [row["targets"][0] for row in comparisons if row["native_view_id"] == view["id"]]
        core.require(choices, "Whole-composition view needs a mapped concept target")
        unique = {core.digest(image): image for image in choices}
        comparisons.append({"id": "composition/" + view["id"], "kind": "whole_composition",
            "native_view_id": view["id"], "required_layers": sorted(view["required_layers"]),
            "target_description": "Compare the complete scene, including environment, major forms, functional objects, contact and lighting/materials",
            "capture_gaps": [{"path": str(core.resolve_input(c["path"], project)), "sha256": c["sha256"],
                "missing_layers": sorted(c.get("missing_layers", []))} for c in manifest["captures"] if c["view_id"] == view["id"]],
            "targets": list(unique.values()), "actuals": captures[view["id"]]})
    core.require(any(row["kind"] == "whole_composition" for row in comparisons), "Scene comparison needs a whole-composition view")
    return comparisons


def proxy_inputs(data, project, scope, production_table):
    """Early S6 review against a proposed H3 table, before production approval.

    ``native_proxy`` records scene/source_files when it captures the probe. This
    read path verifies those bytes; it must never backfill old capture provenance.
    """
    from . import engines, workflow
    project = Path(project).resolve()
    index = {(s.get("id"), s.get("scope")): s for s in data.get("stages", [])}
    atlas_stage, proxy_stage = index.get(("atlas", scope)), index.get(("art_proxy", scope))
    spatial_stage, baseline_stage = index.get(("spatial_design", scope)), index.get(("baseline", "shared"))
    core.require(all((atlas_stage, proxy_stage, spatial_stage, baseline_stage)), "Early comparison needs H2 atlas, spatial design, baseline and S6 probe")
    core.require(proxy_stage.get("consumes", {}).get(scope + "/spatial_design") == workflow.stage_digest(spatial_stage)
        and spatial_stage.get("consumes", {}).get(scope + "/atlas") == workflow.stage_digest(atlas_stage),
        "Early comparison probe has stale spatial/concept inputs")
    path = core.resolve_input(production_table, project)
    core.require(core.inside(path, project) and path.is_file(), "Proposed production table must remain inside project")
    table = core.read(path)
    core.require(table.get("style_id") == scope and table.get("sample_contract", {}).get("scene_comparison") == CONTRACT,
                 "Proposed H3 must declare this style and scene comparison contract")
    atlas, atlas_ref = _one(atlas_stage, "atlas_manifest", project)
    baseline, baseline_ref = _one(baseline_stage, "spatial_contract", project)
    manifest, native_ref = _one(proxy_stage, "native_proxy", project)
    core.require(manifest.get("schema") == 1 and manifest.get("kind") == "composition-probe"
        and manifest.get("scope") == scope and manifest.get("purpose") == "risk_and_composition_only",
        "Early comparison needs an S6 composition probe, not a completed sample")
    core.require(_text(manifest.get("scene")), "Capture the early probe with its actual scene and source_files")
    source_files = manifest.get("source_files")
    core.require(isinstance(source_files, list) and source_files, "Capture the early probe with current source_files hashes; do not backfill provenance")
    files = {}
    for entry in source_files:
        core.require(isinstance(entry, dict), "Probe source file needs path/hash")
        source = core.resolve_input(entry.get("path", ""), project)
        core.require(core.inside(source, project) and source.is_file() and str(source) not in files
            and core.file_hash(source) == entry.get("sha256"), "Probe source missing, changed or duplicated; capture again")
        files[str(source)] = entry["sha256"]
    plan = {"engine": manifest.get("engine") or engines.name(project=project), "contract": {"scene": manifest["scene"], "source_paths": list(files)}}
    discovered = engines.dependency_snapshot(project, plan)
    required = {str(Path(d["path"]).resolve()) for d in discovered}
    required.update(str(p.resolve()) for p in engines.configuration_files(project, plan))
    required.add(str(core.resolve_input(manifest["scene"], project)))
    for entry in discovered:
        sidecar = engines.import_sidecar(entry["path"], engines.name(plan, project))
        if sidecar.is_file():
            required.add(str(sidecar.resolve()))
    core.require(required <= set(files), "Probe source_files omit native dependencies or render configuration")
    observations = workflow._observations(baseline)
    probe_views = [v for v in observations["views"] if set(v["space_ids"]) & set(atlas["required_space_ids"])]
    required_views = workflow._ids(table["sample_contract"].get("required_view_ids"), "Proposed sample observation views")
    core.require(required_views <= {v["id"] for v in probe_views}, "Proposed sample names unknown probe views")
    views = [v for v in probe_views if v["id"] in required_views]
    workflow._capture_coverage(manifest, proxy_stage, probe_views, "proxy_capture", project, proxy=True)
    comparisons = _comparisons(table, atlas_stage, atlas, manifest, views, project)
    result = {"schema": 1, "kind": "scene-comparison-inputs", "contract": CONTRACT, "style_id": scope,
        "purpose": "risk_and_composition_only", "production_table_approved": False,
        "identity": {"scope": scope, "native_probe_sha256": native_ref["sha256"], "source_files_digest": core.digest(files)},
        "sources": {"proposed_production_table": {"path": str(path), "sha256": core.file_hash(path)},
                    "atlas": atlas_ref, "baseline": baseline_ref, "native_proxy": native_ref}, "comparisons": comparisons}
    result["input_digest"] = core.digest(result)
    return result


def inputs_for_stage(data, project, stage):
    """Derive review scope from the original H3 and current native attempt.

    The H4 stage may still be a draft. No human acceptance is required to expose
    its gaps early; the existing workflow remains responsible for H1-H4 gates.
    """
    from . import workflow
    project = Path(project).resolve()
    core.require(stage.get("id") == "representative_sample", "Scene comparison requires an H4 sample stage")
    scope = stage.get("scope")
    source, source_ref = _one(stage, "sample_source_production", project)
    core.require(source.get("id") == "production_plan" and source.get("scope") == scope,
                 "Scene comparison source must be the original H3 for this style")
    core.require(stage.get("consumes") == {scope + "/production_plan": workflow.stage_digest(source)},
                 "Scene comparison sample consumes a different original H3")
    table, table_ref = _one(source, "production_table", project)
    contract = table.get("sample_contract", {})
    core.require(contract.get("scene_comparison") == CONTRACT, "H3 has not declared " + CONTRACT)
    context = workflow.sample_context(data, project, scope)
    atlas_stages = [s for s in context.get("stages", []) if s.get("id") == "atlas" and s.get("scope") == scope]
    core.require(len(atlas_stages) == 1, "Scene comparison needs its original concept atlas")
    atlas_stage = atlas_stages[0]
    core.require(source.get("consumes", {}).get(scope + "/atlas") == workflow.stage_digest(atlas_stage),
                 "Scene comparison atlas differs from the original H3")
    atlas, atlas_ref = _one(atlas_stage, "atlas_manifest", project)
    baseline_stages = [s for s in context.get("stages", []) if s.get("id") == "baseline" and s.get("scope") == "shared"]
    core.require(len(baseline_stages) == 1, "Scene comparison needs observation views")
    baseline, baseline_ref = _one(baseline_stages[0], "spatial_contract", project)
    observations = workflow._observations(baseline)
    sample_inputs, input_ref = _one(stage, "sample_inputs", project)
    workflow._sample_input_dependencies(sample_inputs, project)
    identity = stage.get("identity", {})
    expected = {k: contract[k] for k in ("style_id", "scene", "input_digest", "execution_plan_digest")}
    expected.update(attempt_id=identity.get("attempt_id"), sample_inputs_digest=core.digest(sample_inputs))
    core.require(core.safe_id(identity.get("attempt_id")) and identity == expected,
                 "Scene comparison belongs to another source/scene/attempt/input")
    manifest, native_ref = _one(stage, "native_sample", project)
    workflow._identity_equal(manifest, identity, "Scene comparison native sample")
    views = [v for v in observations["views"] if v["id"] in contract["required_view_ids"]]
    workflow._capture_coverage(manifest, stage, views, "native_capture", project)
    comparisons = _comparisons(table, atlas_stage, atlas, manifest, views, project)
    result = {"schema": 1, "kind": "scene-comparison-inputs", "contract": CONTRACT, "style_id": scope,
        "identity": identity, "sources": {"h3": source_ref, "production_table": table_ref, "atlas": atlas_ref,
            "baseline": baseline_ref, "sample_inputs": input_ref, "native_sample": native_ref}, "comparisons": comparisons}
    result["input_digest"] = core.digest(result)
    return result


def draft(inputs):
    """Make an explicitly unresolved review, never a fabricated pass."""
    rows = []
    for row in inputs["comparisons"]:
        rows.append({"id": row["id"], "target": {**row["targets"][0], "region": [0, 0, 1, 1]},
            "actual": {**row["actuals"][0], "region": [0, 0, 1, 1]},
            "status": "unclear", "observation": "Pending visual comparison", "next_action": "Inspect both images and record the observed difference",
            **({"layers": [{"id": layer, "status": "unclear", "observation": "Pending visual comparison",
                            "next_action": "Inspect this layer in the whole native scene"} for layer in row["required_layers"]]}
               if row["kind"] == "whole_composition" else {})})
    return {"schema": 1, "kind": "scene-comparison", "contract": CONTRACT, "input_digest": inputs["input_digest"],
        "purpose": inputs.get("purpose", "h4_comparison"),
        "identity": copy.deepcopy(inputs["identity"]), "reviewer": None, "source_ref": None, "comparisons": rows,
        "note": "Unreviewed draft. Coverage and freshness checks do not judge aesthetics or constitute H4 acceptance."}


def _region(record, choices, whole=False):
    core.require(isinstance(record, dict), "Scene comparison needs an image and region")
    image = {k: record.get(k) for k in ("path", "sha256", "dimensions")}
    core.require(image in choices, "Scene comparison image does not match the required concept/native view")
    box = record.get("region")
    core.require(isinstance(box, list) and len(box) == 4 and all(type(v) in {int, float} and math.isfinite(v) for v in box)
        and 0 <= box[0] < 1 and 0 <= box[1] < 1 and box[2] > 0 and box[3] > 0
        and box[0] + box[2] <= 1 and box[1] + box[3] <= 1, "Scene comparison needs a bounded normalized image region")
    core.require(not whole or box == [0, 0, 1, 1], "Whole-composition comparison must inspect the full image")


def inspect_report(report, inputs):
    """Check traceability and reported gaps; pass means coverage, not beauty."""
    core.require(isinstance(report, dict) and report.get("schema") == 1 and report.get("kind") == "scene-comparison"
                 and report.get("contract") == CONTRACT, "Expected scene-comparison schema 1")
    core.require(report.get("input_digest") == inputs["input_digest"] and report.get("identity") == inputs["identity"],
                 "Scene comparison is stale for the current source/images/native attempt")
    core.require(report.get("purpose") == inputs.get("purpose", "h4_comparison"), "Probe review cannot stand in for H4 comparison")
    rows = report.get("comparisons")
    expected = {row["id"]: row for row in inputs["comparisons"]}
    core.require(isinstance(rows, list) and all(isinstance(row, dict) for row in rows)
                 and len(rows) == len(expected) and {row.get("id") for row in rows} == set(expected),
                 "Scene comparison omits required feature/view or whole-composition coverage")
    blockers, seen = [], set()

    def check_status(record, key):
        core.require(record.get("status") in {"pass", "fail", "unclear"} and _text(record.get("observation")),
                     "Scene comparison needs pass/fail/unclear and a concrete observation: " + key)
        if record["status"] != "pass":
            core.require(_text(record.get("next_action")), "Unresolved scene comparison needs a next action: " + key)
            blockers.append({"id": key, "status": record["status"], "observation": record["observation"], "next_action": record["next_action"]})

    for row in rows:
        wanted = expected[row["id"]]
        whole = wanted["kind"] == "whole_composition"
        _region(row.get("target"), wanted["targets"], whole)
        _region(row.get("actual"), wanted["actuals"], whole)
        check_status(row, row["id"])
        if not whole and row["status"] == "pass":
            fingerprint = core.digest({"target": row["target"], "actual": row["actual"], "observation": row["observation"].strip()})
            core.require(fingerprint not in seen, "Scene comparison repeats the same image regions and observation for different features; identify each feature's actual evidence")
            seen.add(fingerprint)
        if whole:
            layers = row.get("layers")
            core.require(isinstance(layers, list) and all(isinstance(layer, dict) for layer in layers)
                and len(layers) == len(wanted["required_layers"])
                and {layer.get("id") for layer in layers} == set(wanted["required_layers"]),
                "Whole-composition comparison must account for every required visual layer")
            for layer in layers:
                check_status(layer, row["id"] + "/" + layer["id"])
                known_missing = {name for gap in wanted.get("capture_gaps", [])
                    if (gap["path"], gap["sha256"]) == (row["actual"]["path"], row["actual"]["sha256"])
                    for name in gap["missing_layers"]}
                core.require(layer["id"] not in known_missing or layer["status"] != "pass",
                             "Probe manifest declares this layer missing; repair and capture again: " + layer["id"])
    reviewer = report.get("reviewer")
    if not (isinstance(reviewer, dict) and core.safe_id(reviewer.get("agent_id"))
            and core.safe_id(reviewer.get("task_id")) and _text(report.get("source_ref"))):
        blockers.append({"id": "reviewer", "status": "unclear", "observation": "Actual reviewer and source reference are missing",
                         "next_action": "Record the actual visual review identity and source"})
    return {"ok": not blockers, "kind": "scene-comparison-assessment", "input_digest": inputs["input_digest"],
        "purpose": inputs.get("purpose", "h4_comparison"),
        "comparisons": len(rows), "blockers": blockers, "human_visual_acceptance": False,
        "limitation": "Validates declared comparison evidence and freshness; does not authenticate inspection or judge aesthetics. Existing H4 human acceptance remains required."}


def validate_stage(data, project, stage):
    """H4 hook for a newly declared contract; existing contracts stay readable."""
    source, _ = _one(stage, "sample_source_production", project)
    table, _ = _one(source, "production_table", project)
    declaration = table.get("sample_contract", {}).get("scene_comparison")
    if declaration is None:
        return {"required": False}
    core.require(declaration == CONTRACT, "Unknown scene comparison contract")
    inputs = inputs_for_stage(data, project, stage)
    report, _ = _one(stage, "scene_comparison", project)
    result = inspect_report(report, inputs)
    core.require(result["ok"], "Scene comparison has unresolved items: " + ", ".join(item["id"] for item in result["blockers"]))
    return {**result, "required": True}


def validate_criterion_roles(receipt, inputs):
    """New H3 contracts must cite the relevant artifact roles per criterion."""
    declaration = inputs.get("scene_comparison_contract")
    if declaration is None:
        return
    core.require(declaration == CONTRACT, "Unknown scene comparison contract")
    artifacts = {(a["path"], a["sha256"]): a for a in inputs["artifacts"] if a["stage"] == inputs["stage"]}
    for check in receipt["coverage"]:
        needed = H3_CRITERION_ROLES.get(check["id"], set())
        roles = {artifacts[(e["path"], e["sha256"])]["role"] for e in check["evidence"]
                 if (e["path"], e["sha256"]) in artifacts}
        core.require(needed <= roles, "H3 review criterion needs relevant evidence roles: " + check["id"] + ": " + ", ".join(sorted(needed - roles)))
