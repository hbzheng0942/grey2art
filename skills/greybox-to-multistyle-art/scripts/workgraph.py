#!/usr/bin/env python3
"""Offline scheduling and review-budget inspection; never dispatches work."""
from pathlib import Path
import argparse
import json
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime"))
from greybox.workgraph import WorkgraphError, inspect_review, inspect_workgraph


def main():
    parser = argparse.ArgumentParser(description="Read-only host scheduling aid, not an engine integration or paid-task dispatcher. Recorded leases are not verified live remote jobs.")
    parser.add_argument("command", choices=("inspect", "review"))
    parser.add_argument("--project", required=True, help="Project root; every referenced file must stay inside it")
    parser.add_argument("--file", required=True, help="JSON path within project (absolute or project-relative)")
    args = parser.parse_args()
    try:
        result = (inspect_workgraph if args.command == "inspect" else inspect_review)(args.file, args.project)
    except (WorkgraphError, OSError, ValueError, TypeError, KeyError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
