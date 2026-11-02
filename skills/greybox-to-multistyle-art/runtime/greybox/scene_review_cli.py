"""Create an unresolved paired review or inspect its current evidence."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from . import core, scene_review


def main(argv=None):
    parser = argparse.ArgumentParser(description="Compare a complete native sample with its approved concept before H4")
    parser.add_argument("action", choices=["inputs", "draft", "check"])
    parser.add_argument("--workflow", type=Path, required=True)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--style", required=True)
    parser.add_argument("--phase", choices=["proxy", "sample"], default="sample")
    parser.add_argument("--production-table", type=Path, help="For early proxy comparison: proposed H3 table; this does not approve it")
    parser.add_argument("--report", type=Path, help="Review JSON to check")
    parser.add_argument("--output", type=Path, help="New project-contained output; existing files are never overwritten")
    args = parser.parse_args(argv)
    try:
        project = args.project.resolve()
        core.require(core.inside(args.workflow, project), "Workflow must remain inside project")
        data = core.read(args.workflow)
        if args.phase == "proxy":
            core.require(args.production_table is not None, "Early proxy comparison requires --production-table")
            inputs = scene_review.proxy_inputs(data, project, args.style, args.production_table)
        else:
            stages = [s for s in data.get("stages", []) if s.get("id") == "representative_sample" and s.get("scope") == args.style]
            core.require(len(stages) == 1, "Create the current native sample evidence before scene comparison")
            inputs = scene_review.inputs_for_stage(data, project, stages[0])
        if args.action == "check":
            core.require(args.report is not None, "check requires --report")
            result = scene_review.inspect_report(core.read(args.report), inputs)
        else:
            result = inputs if args.action == "inputs" else scene_review.draft(inputs)
        if args.output:
            output = args.output.resolve()
            skill = Path(__file__).resolve().parents[2]
            core.require(core.inside(output, project) and not core.inside(output, skill), "Output must be inside project and outside installed skill")
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open("x", encoding="utf-8") as stream:
                stream.write(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
        print(json.dumps(result, ensure_ascii=True, indent=2, allow_nan=False))
        return 0 if result.get("ok", True) else 2
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({"ok": False, "code": "SCENE_COMPARISON_INVALID", "error": str(exc)}, ensure_ascii=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
