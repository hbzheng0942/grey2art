"""Local usage feedback and derived recap; no generation, upload or approval."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import core, feedback, feedback_collection


def main(argv=None):
    parser = argparse.ArgumentParser(prog="greybox.py feedback", description=__doc__)
    parser.add_argument("command", choices=("record", "recap", "export", "collect"))
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--case", help="Existing case; required except for collect")
    parser.add_argument("--input", help="Project-contained observation or collection manifest JSON")
    parser.add_argument("--writer")
    parser.add_argument("--expected-revision", type=int)
    parser.add_argument("--checkpoint-sha256")
    parser.add_argument("--output", help="Project-contained local export directory")
    args = parser.parse_args(argv)
    try:
        if args.command == "collect":
            if not args.input or not args.output:
                raise ValueError("collect needs --input and --output")
            result = feedback_collection.collect(args.project, args.input, args.output)
        elif not args.case:
            raise ValueError(args.command + " needs --case")
        elif args.command == "record":
            if not args.input or not args.writer or args.expected_revision is None or not args.checkpoint_sha256:
                raise ValueError("record needs --input, --writer, --expected-revision and --checkpoint-sha256")
            path = feedback._path(args.project.resolve(), args.input)
            result = feedback.record(args.project, args.case, core.read(path), args.writer,
                                     args.expected_revision, args.checkpoint_sha256)
        elif args.command == "export":
            if not args.output:
                raise ValueError("export needs --output")
            result = feedback.export_report(args.project, args.case, args.output)
        else:
            result = feedback.refresh(args.project, args.case)
    except (ValueError, OSError, TypeError, KeyError, RecursionError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0
