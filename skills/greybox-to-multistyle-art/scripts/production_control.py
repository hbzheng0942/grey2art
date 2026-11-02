#!/usr/bin/env python3
"""Manage one case's operational control; no cloud calls or new user approvals."""
import argparse
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime"))
from greybox import core, production_control as pc


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=("init", "inspect", "configure", "qualify", "start", "integrate", "activate", "reconcile-claim",
                                      "open-repair", "begin-repair", "finish-repair", "resolve-repair"))
    p.add_argument("--project", required=True)
    p.add_argument("--control")
    p.add_argument("--plan")
    p.add_argument("--workflow")
    p.add_argument("--lead-style")
    p.add_argument("--writer", default="integrator")
    p.add_argument("--input", help="Project-contained settings/action JSON; see production-control.md")
    p.add_argument("--expected-revision", type=int)
    args = p.parse_args()
    try:
        source = core.read(pc._path(args.project, args.input)) if args.input else {}
        if args.command == "init":
            core.require(args.plan and args.workflow, "init requires --plan and --workflow")
            result = pc.initialize(args.project, core.read(pc._path(args.project, args.plan)), args.workflow,
                                   args.lead_style, args.writer)
        else:
            core.require(args.control, "--control is required")
            common = (args.project, args.control)
            if args.command == "inspect":
                result = pc.assess(*common, workflow_path=args.workflow)
            elif args.command == "configure":
                core.require(args.expected_revision is not None, "configure requires --expected-revision from inspect")
                result = pc.configure(*common, source, args.expected_revision)
            elif args.command == "qualify":
                result = pc.qualify(*common, source["family_id"], source["evidence"])
            elif args.command == "start":
                result = pc.start_combination(*common, source["combination_id"])
            elif args.command == "reconcile-claim":
                result = pc.reconcile_claim(*common, **source)
            elif args.command == "integrate":
                result = pc.integrate(*common, source["combination_id"], source["evidence"])
            elif args.command == "activate":
                result = pc.activate_styles(*common, source["active_styles"], args.workflow)
            elif args.command == "open-repair":
                result = pc.open_repair(*common, **source)
            elif args.command == "begin-repair":
                result = pc.begin_repair(*common, **source)
            elif args.command == "finish-repair":
                result = pc.finish_repair(*common, **source)
            else:
                result = pc.resolve_repair(*common, **source)
    except (ValueError, OSError, TypeError, KeyError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
