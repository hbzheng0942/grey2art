"""Read-only task diagnostics and a CAS-pinned public CLI entry."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from . import core, task_context


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("inspect", "check", "pin", "run"):
        command = commands.add_parser(name)
        command.add_argument("--project", type=Path, required=True)
        command.add_argument("--engine", choices=("godot", "unity", "blender"))
        command.add_argument("--case", type=Path, required=name != "inspect")
        command.add_argument("--session-report", type=Path,
                             help="Actual host/session report with source_ref; unavailable model/schema fields stay null")
        if name == "pin":
            command.add_argument("--writer", required=True)
            command.add_argument("--expected-revision", type=int, required=True)
            command.add_argument("--checkpoint-sha256", required=True)
            command.add_argument("--source-ref", required=True, help="Current operational context source, not a new approval")
        if name == "run":
            command.add_argument("arguments", nargs=argparse.REMAINDER, help="-- followed by the original greybox command")
    args = parser.parse_args(argv)
    try:
        report = core.read(args.session_report) if args.session_report else None
        if args.command == "run":
            arguments = args.arguments[1:] if args.arguments[:1] == ["--"] else args.arguments
            return task_context.run(args.project, args.case, arguments, report, engine=args.engine)
        if args.command == "pin":
            result = task_context.pin(args.project, args.case, report, writer=args.writer,
                expected_revision=args.expected_revision, checkpoint_sha256=args.checkpoint_sha256,
                source_ref=args.source_ref, engine=args.engine)
        else:
            result = task_context.inspect(args.project, args.case, report, engine=args.engine)
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return 0 if result["ok"] else 2
    except (ValueError, OSError, TypeError, KeyError) as error:
        print(json.dumps({"ok": False, "error": str(error), "code": "TASK_CONTEXT_INVALID"}, ensure_ascii=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
