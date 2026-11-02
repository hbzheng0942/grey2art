"""Common executor CLI; source ledgers retain authority for every paid action."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from . import execution


def main(argv=None):
    parser = argparse.ArgumentParser(description="Durable rolling execution across approved image and supplier jobs")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "run", "start", "status", "claim"):
        command = commands.add_parser(name)
        command.add_argument("--file", type=Path, required=True, help="Queue JSON referencing existing authorized jobs")
        command.add_argument("--state-dir", type=Path, help="Shared account capacity directory; use the same path across hosts")
        if name == "run":
            command.add_argument("--max-seconds", type=float)
            command.add_argument("--once", action="store_true", help="One bounded scheduling turn; this does not promise background tracking")
        if name == "claim":
            command.add_argument("--action", choices=["submit", "status", "fetch"], default="submit")
    command = commands.add_parser("record", help="Record one real action receipt, including a host-native tool receipt")
    command.add_argument("--ticket", type=Path, required=True)
    command.add_argument("--file", type=Path, required=True, help="Private action outcome JSON; no fabricated invocation")
    command.add_argument("--state-dir", type=Path)
    command = commands.add_parser("native-reserve", help="Bind an authorized native tool request without invoking the tool")
    command.add_argument("--file", type=Path, required=True)
    command.add_argument("--job-dir", type=Path, required=True)
    command.add_argument("--tool", required=True)
    command.add_argument("--authorization", type=Path)
    command.add_argument("--source-ref")
    command.add_argument("--binding", type=Path)
    command.add_argument("--project", type=Path)
    command = commands.add_parser("native-settle", help="Record actual terminal evidence for an accepted native task")
    command.add_argument("--job-dir", type=Path, required=True)
    command.add_argument("--task-id", help="Original accepted ID; required for an asynchronous native task")
    command.add_argument("--file", type=Path, required=True)
    command = commands.add_parser("retry-preflight", help="Recheck corrected, proven-unsubmitted supplier preparation")
    command.add_argument("--file", type=Path, required=True)
    command.add_argument("--source-ref", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "retry-preflight":
            from . import supplier_execution
            queue = execution.validate_queue(json.loads(args.file.read_text(encoding="utf-8")))
            count = sum(supplier_execution.retry_preflight(source, args.source_ref)
                        for source in queue['sources'] if source['kind'] == 'supplier')
            result = {'ok': True, 'recheck_preparations': count, 'provider_calls': 0}
        elif args.command == "validate":
            data = json.loads(args.file.read_text(encoding="utf-8"))
            checked = execution.validate_queue(data)
            result = {"ok": True, "queue_valid": True, "network_calls": 0,
                      "sources": len(checked["sources"]), "pools": len(checked["pools"])}
        elif args.command == "record":
            result = execution.record(args.ticket, json.loads(args.file.read_text(encoding="utf-8")), state_dir=args.state_dir)
        elif args.command == "native-settle":
            from . import host_execution
            result = host_execution.settle(args.job_dir, args.task_id, json.loads(args.file.read_text(encoding="utf-8")))
            _, data = host_execution._job(args.job_dir)
            if data.get("submission_ticket_path"):
                result["capacity"] = execution.refresh_ticket(data["submission_ticket_path"])
        elif args.command == "native-reserve":
            from . import host_execution
            authorization = json.loads(args.authorization.read_text(encoding="utf-8")) if args.authorization else {"source_ref": args.source_ref}
            result = host_execution.reserve(json.loads(args.file.read_text(encoding="utf-8")), args.job_dir,
                authorization=authorization, tool=args.tool,
                binding=json.loads(args.binding.read_text(encoding="utf-8")) if args.binding else None,
                base=args.project or args.file.resolve().parent)
        elif args.command == "run":
            result = execution.run(args.file, state_dir=args.state_dir, max_seconds=args.max_seconds, once=args.once)
        elif args.command == "claim":
            result = execution.claim(args.file, state_dir=args.state_dir, action=args.action)
        else:
            result = getattr(execution, args.command)(args.file, state_dir=args.state_dir)
        print(json.dumps(result, indent=2, ensure_ascii=True))
        if args.command == 'run' and result.get('phase') == 'blocked':
            return 2
        if args.command == 'start' and result.get('code') == 'EXECUTOR_START_FAILED':
            return 2
        return 0 if result.get("ok", True) else 2
    except (ValueError, OSError) as exc:
        # Validation errors come from local contracts, not raw provider bodies.
        print(json.dumps({"ok": False, "error": str(exc), "code": "EXECUTION_CONTRACT_INVALID"}), file=sys.stderr)
        return 2
    except Exception:
        print(json.dumps({"ok": False, "error": "Execution interrupted; preserve the queue, original job ledgers and action receipts.",
                          "code": "EXECUTION_FAILED"}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
