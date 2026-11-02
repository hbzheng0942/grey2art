"""Bind visual form decisions and completed model tasks without choosing a vendor.

These checks validate declared evidence, not image interpretation or supplier
authenticity. They never submit, retry, migrate or copy a generation task.
"""
from pathlib import Path
from . import core

FEATURE_KINDS = {"form", "surface", "light", "atmosphere", "motion"}
MODEL_OPERATIONS = {"image_to_3d", "multiview_to_3d"}
ROUTE_CONTRACT = "asset-routes-v1"


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def validate_routes(table, image_ids):
    """A native environment label cannot satisfy a declared form requirement."""
    core.require(table.get("asset_route_contract") == ROUTE_CONTRACT,
                 "H3 needs its stage-bound asset route contract; a top-level policy label cannot replace route evidence")
    proposals = {a["asset_id"]: a for a in table["asset_proposals"]}
    for proposal in proposals.values():
        if proposal["route"] in {"generated", "hybrid"}:
            core.require(proposal.get("generation", {}).get("operation") in MODEL_OPERATIONS,
                         "AI/generated and hybrid routes need an actual image-conditioned model operation; missing work remains pending")
    for feature in table["visual_features"]:
        kind = feature.get("feature_kind")
        core.require(kind in FEATURE_KINDS,
                     "Visual route decision needs feature_kind: form, surface, light, atmosphere or motion")
        if kind != "form":
            continue
        core.require(feature.get("asset_ids"),
                     "Form requirements need actual asset sources; native material/light/environment ownership cannot replace a model route")
        if feature.get("importance") != "dominant":
            continue
        for asset_id in feature["asset_ids"]:
            proposal = proposals.get(asset_id)
            core.require(proposal is not None, "Form route references an unknown asset source")
            evaluation = proposal.get("route_evaluation", {})
            core.require(isinstance(evaluation, dict) and all(_text(evaluation.get(k)) for k in
                         ("generated", "reuse", "procedural")),
                         "Dominant form needs an explicit generated/reuse/procedural route evaluation before production")
            if proposal["route"] == "procedural":
                match = proposal.get("procedural_visual_match", {})
                core.require(_text(match.get("reason")) and match.get("evidence_image_id") in image_ids
                             and _text(match.get("observed_match")),
                             "Dominant procedural appearance/form needs actual target-match evidence even when its responsibility is environment or precise_geometry")
            elif proposal["route"] == "hybrid":
                core.require(_text(proposal.get("generated_visual_role"))
                             and _text(proposal.get("controlled_structure_role")),
                             "Hybrid form needs generated appearance and controlled structure roles")


def _record(value, project, label):
    core.require(isinstance(value, dict) and _text(value.get("path")), label + " needs a real local path/hash")
    path = core.resolve_input(value["path"], project)
    core.require(core.inside(path, project) and path.is_file()
                 and core.file_hash(path) == value.get("sha256"), label + " is missing, changed or outside project")
    return {"path": str(path), "sha256": value["sha256"]}


def _model_task(binding, proposal, table, project):
    """Read the original supported ledger; retain original IDs and inputs."""
    run = core.resolve_input(binding.get("run_dir", ""), project)
    core.require(core.inside(run, project), "Model task ledger must stay in its owning project")
    supplier = run / "supplier-run.json"
    from . import modeling_refs
    reviewed = modeling_refs.validate_operation_reference({"asset_id": proposal["asset_id"],
        "modeling_references": table["modeling_references"]}, project)
    expected_hashes = [i["sha256"] for i in reviewed["images"]]
    if supplier.is_file():
        from . import image_policy, supplier_jobs
        state, portfolio, _, _, option = supplier_jobs._load(run)
        core.require(Path(state.get("project", "")).resolve() == Path(project).resolve(),
                     "Model task ledger belongs to another project")
        core.require(table.get("supplier_portfolio_digest") == state["portfolio_digest"],
                     "Model task portfolio differs from the original H3 supplier decision")
        operations = {o["id"]: o for o in option["operations"]}
        op = operations.get(binding.get("operation_id"))
        core.require(op and op.get("asset_id") == proposal["asset_id"]
                     and op.get("operation") == proposal["generation"]["operation"],
                     "Model task must name this asset's actual image-conditioned supplier operation")
        actual = image_policy.image_inputs(op, project)
        core.require([i["sha256"] for i in actual] == expected_hashes
                     and state.get("inputs", {}).get(op["id"]) == actual,
                     "Model task input images differ from the original approved references")
        row = state["operations"][op["id"]]
        task_id, artifacts = row.get("task_id"), row.get("artifacts", [])
    else:
        core.require((run / "run.json").is_file() and (run / "plan.frozen.json").is_file(),
                     "Model route needs its original supplier or legacy task ledger; missing work remains pending")
        state = core.read(run / "run.json")
        plan = core.read(run / "plan.frozen.json")
        from .workflow import execution_plan_digest
        core.require(state.get("kind") == "greybox-art-run"
                     and Path(state.get("project", "")).resolve() == Path(project).resolve()
                     and state.get("planHash") == core.digest(plan)
                     and execution_plan_digest(plan) == table["execution_plan_digest"],
                     "Invalid original legacy model ledger or different H3 executable plan")
        asset = next((a for a in plan.get("assets", []) if a.get("id") == proposal["asset_id"]), None)
        core.require(asset and asset.get("generation") == proposal.get("generation"),
                     "Model task differs from the original H3 generation route")
        actual = core._check_generation_reference(asset, project)
        core.require([i["sha256"] for i in actual["images"]] == expected_hashes,
                     "Model task input images differ from the original approved references")
        row = state.get("assets", {}).get(proposal["asset_id"], {})
        task_id, artifacts = row.get("taskId"), [row["artifact"]] if row.get("artifact") else []
    core.require(row.get("state") == "ready" and _text(str(task_id or ""))
                 and str(binding.get("task_id", "")) == str(task_id),
                 "AI model route is pending, failed or has no matching original task ID; cannot accept a procedural substitute")
    source = _record(binding.get("source_output"), project, "Generated source output")
    core.require(any(str(core.resolve_input(a.get("path", ""), project)) == source["path"]
                     and a.get("sha256") == source["sha256"] for a in artifacts),
                 "Generated source output does not belong to the completed original task")
    return source


def validate_model_tasks(inputs, table, project):
    """H4 checks the original sample's AI routes, not future expansion tasks."""
    expected = {a["asset_id"]: a for a in table["asset_proposals"] if a["route"] in {"generated", "hybrid"}}
    bindings = inputs.get("model_task_bindings", [])
    core.require(isinstance(bindings, list) and all(isinstance(b, dict) for b in bindings),
                 "Sample model_task_bindings must be a list of original task references")
    ids = [b.get("asset_id") for b in bindings]
    core.require(all(core.safe_id(aid) for aid in ids) and len(set(ids)) == len(ids) and set(ids) == set(expected),
                 "Sample must bind every AI/generated or hybrid asset to its actual completed model task")
    resources = {(str(core.resolve_input(f["path"], project)), f["sha256"]) for f in inputs["files"]}
    consumed = set()
    if expected:
        from . import engines, godot
        core.require(_text(inputs.get("scene")), "Model consumption needs the actual sample scene")
        native = {"engine": inputs.get("engine") or engines.name(project=project),
                  "contract": {"scene": inputs["scene"]}}
        if engines.name(native, project) == "godot":
            # Root only in the real scene/config. A nonempty scene-only declaration
            # lets the scanner retain literal references around computed loaders;
            # it never seeds models from the sample's declared file inventory.
            native["contract"]["source_paths"] = [inputs["scene"]]
            roots = [*engines.configuration_files(project, native), inputs["scene"]]
            reachable = godot._native_dependencies(project, roots, native["contract"])
        else:
            reachable = engines.dependency_snapshot(project, native)
        consumed = {(str(core.resolve_input(f["path"], project)), f["sha256"]) for f in reachable}
    for binding in bindings:
        source = _model_task(binding, expected[binding["asset_id"]], table, project)
        realized = _record(binding.get("realized_output"), project, "Realized model output")
        core.require(Path(source["path"]).suffix.lower() in {".glb", ".gltf", ".fbx", ".obj", ".blend"}
                     and Path(realized["path"]).suffix.lower() in {".glb", ".gltf", ".fbx", ".obj", ".blend", ".mesh", ".res", ".tres"},
                     "Model task bindings need actual model resources, not concept images or logs")
        core.require((source["path"], source["sha256"]) in resources
                     and (realized["path"], realized["sha256"]) in resources,
                     "Sample inputs must retain generated source and realized model identities")
        core.require((realized["path"], realized["sha256"]) in consumed,
                     "Generated model consumption is unverified: realized output must be reachable from the actual native scene/assembly, not merely listed in sample inputs; dynamic loads need native binding evidence")
        if source["sha256"] != realized["sha256"]:
            processing = binding.get("processing", {})
            core.require(isinstance(processing, dict) and _text(processing.get("method"))
                         and _text(processing.get("source_ref"))
                         and processing.get("input_sha256") == source["sha256"]
                         and processing.get("output_sha256") == realized["sha256"],
                         "Changed generated model needs its actual processing method/source and input/output hash lineage")
