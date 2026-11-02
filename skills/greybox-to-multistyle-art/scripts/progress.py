#!/usr/bin/env python3
"""Offline case continuity; no provider, engine, approval or dispatch side effects."""
import argparse
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime"))
from greybox import continuity


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("init", "update", "event", "focus", "check", "classify", "recover"))
    parser.add_argument("--project")
    parser.add_argument("--case")
    parser.add_argument("--input", help="Project-contained JSON: plan+event, changes+event, event, or resume token")
    parser.add_argument("--writer")
    parser.add_argument("--expected-revision", type=int)
    parser.add_argument("--checkpoint-sha256")
    parser.add_argument("--message")
    args = parser.parse_args()
    try:
        if args.command == "classify":
            result = continuity.classify_message(args.message)
        else:
            if not args.project or not args.case:
                raise ValueError("--project and --case required")
            source = None
            if args.command in {"init", "update", "event", "check"}:
                if not args.input:
                    raise ValueError("--input required")
                source = json.loads(continuity._path(args.input, Path(args.project).resolve()).read_text())
            if args.command == "init":
                result = continuity.initialize(args.project, args.case, source["plan"], source["event"])
            elif args.command in {"update", "event"}:
                if not args.writer or args.expected_revision is None or not args.checkpoint_sha256:
                    raise ValueError("--writer, --expected-revision and --checkpoint-sha256 required")
                result = continuity.update(args.project, args.case, args.writer, args.expected_revision,
                    args.checkpoint_sha256, source["event"] if args.command == "update" else source,
                    source["changes"] if args.command == "update" else None)
            elif args.command == "check":
                result = continuity.check_resume_token(args.project, args.case, source)
            elif args.command == "recover":
                if not args.writer:
                    raise ValueError("--writer required")
                result = continuity.recover(args.project, args.case, args.writer)
            else:
                result = continuity.derive_focus(args.project, args.case)
    except (ValueError, OSError, TypeError, KeyError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=True))
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
