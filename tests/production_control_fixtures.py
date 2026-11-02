"""Synthetic operation records for offline unit tests, never production evidence.

Legacy multistyle execution tests explicitly build an archived synthetic lead H4
before releasing sibling styles. Production-control tests start with initialize
directly and exercise the actual initial gate; there is no runtime test bypass.
"""
from pathlib import Path
from greybox import core, layout, production_control as pc


def fixture_control(project, plan, workflow_path, expansion=False, legacy_multistyle=False):
    from workflow_fixtures import add_synthetic_lead_h4
    path = pc.control_path(project, plan)
    document = core.read(workflow_path)
    styles = document["selected_styles"]
    planned_styles = layout.style_ids(plan)
    owners = layout.workspace(plan)["asset_owners"]
    aids = sorted(set(owners) | set(plan.get("required_assets", [])) |
                  {a.get("id", a.get("asset_id")) for a in plan.get("assets", [])})
    families = {"synthetic-" + aid: {"profile": {"structure": "SYNTHETIC " + aid,
        "method": "SYNTHETIC OFFLINE single-asset fixture", "skeleton": "none", "engine": "godot"},
        "asset_ids": [aid], "pilot_asset_ids": [aid], "required_interactions": [], "runtime_profile": None} for aid in aids}
    combos = {"synthetic-" + sid: {"style_id": sid, "asset_ids": [aid for aid in aids
        if owners.get(aid, {}).get("scope") == "shared" or owners.get(aid, {}).get("style_id") == sid],
        "state": "queued", "required_interactions": []} for sid in styles}
    if not path.exists():
        pc.initialize(project, plan, workflow_path, lead_style=planned_styles[0], writer="synthetic-integrator", families=families, combinations=combos)
    data = core.read(path)
    # Test fixture rebinding preserves operation history. A new synthetic H4
    # below replaces the old proof only when the test explicitly asks for it.
    data.update(families=families, combinations=combos, max_open_combinations=max(1, len(styles)),
                active_styles=[data["lead_style"]], workflow_path=str(workflow_path),
                style_phases={s: "expansion" if expansion else "representative" for s in styles})
    data.pop("lead_completion", None)
    core.write(path, data)
    if legacy_multistyle and len(planned_styles) > 1:
        archived = add_synthetic_lead_h4(project, plan, document)
        pc.activate_styles(project, path, planned_styles, workflow_path=archived)
    return path
