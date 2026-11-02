"""Explicit organization choices for synthetic tests, not production sharing inference."""
from greybox import layout

def attach_workspace(plan, case_id="fixture-case"):
    if "workspace" not in plan:
        plan["workspace"]={"schema":1,"case_id":case_id,"root":"art/"+case_id,"engine":"godot","asset_owners":{a["id"]:{"scope":"shared"} for a in plan.get("assets",[])}}
    return plan
