"""CLI parser shared by greybox.py and the standalone raster-only entrypoint."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from . import image_jobs as jobs


def add_parser(subparsers):
    parser = subparsers.add_parser("image", help="Independent raster profiles and recoverable jobs; no H3 mesh dependency")
    _arguments(parser)
    return parser


def _arguments(parser):
    parser.add_argument("action", choices=["configure", "capabilities", "validate", "reserve", "submit", "status", "fetch", "resume", "start", "record-native", "_worker"])
    parser.add_argument("--profile", help="Non-secret user image profile name")
    parser.add_argument("--config-dir", type=Path, help="User image profiles directory, outside the skill installation")
    parser.add_argument("--file", type=Path, help="Profile JSON for configure; request JSON for submit")
    parser.add_argument("--job-dir", type=Path, help="One persistent image invocation, outside the installation")
    parser.add_argument("--asset-dir", type=Path, help="Canonical content-hash image directory shared across jobs")
    parser.add_argument("--project", type=Path, help="Base for hash-bound request inputs")
    parser.add_argument("--authorization", type=Path, help="Existing task authorization JSON; source_ref is required")
    parser.add_argument("--source-ref", help="Actual image-call authorization, reconciliation or native invocation source")
    parser.add_argument("--wait", action="store_true", help="Run synchronously; default submit uses a detached worker")
    parser.add_argument("--local", action="store_true", help="Read persisted status without contacting the provider")
    parser.add_argument("--task-id", help="Original provider task ID for explicit reconciliation")
    parser.add_argument("--response-file", type=Path, help="Private original provider response for synchronous recovery")
    parser.add_argument("--image", type=Path, help="Actual native-tool image output")
    parser.add_argument("--tool", help="Actual native image tool and version")
    parser.add_argument("--arguments", type=Path, help="Actual native tool argument object")
    parser.add_argument("--inputs", type=Path, help="JSON object with images:[{path,sha256}] actually passed to native tool")


def handle(args):
    action = args.action
    if action in {"configure", "capabilities", "validate", "reserve", "submit"}:
        jobs.require(args.profile, "This image operation needs --profile")
    if action == "configure":
        jobs.require(args.file, "Image configure needs --file profile.json")
        return jobs.configure(args.profile, jobs._read(args.file), args.config_dir)
    if action == "capabilities":
        return jobs.profile_report(args.profile, args.config_dir)
    if action == "validate":
        jobs.require(args.file, "Image validate needs --file request.json")
        return jobs.validate(args.profile, jobs._read(args.file), config_dir=args.config_dir,
                             base=args.project or args.file.resolve().parent)
    jobs.require(args.job_dir, "This image operation needs --job-dir")
    if action in {"submit", "reserve"}:
        jobs.require(args.file, "Image submit needs --file request.json")
        authorization = jobs._read(args.authorization) if args.authorization else {"source_ref": args.source_ref}
        if action == "reserve":
            return jobs.reserve(args.profile, jobs._read(args.file), args.job_dir, authorization=authorization,
                                config_dir=args.config_dir, base=args.project or args.file.resolve().parent,
                                asset_dir=args.asset_dir)
        return jobs.submit(args.profile, jobs._read(args.file), args.job_dir, authorization=authorization,
                           config_dir=args.config_dir, base=args.project or args.file.resolve().parent,
                           background=not args.wait, asset_dir=args.asset_dir)
    if action == "status":
        return jobs.status(args.job_dir, remote=not args.local)
    if action == "fetch":
        return jobs.fetch(args.job_dir)
    if action == "resume":
        return jobs.resume(args.job_dir, task_id=args.task_id, response_file=args.response_file, source_ref=args.source_ref)
    if action in {"start", "_worker"}:
        return jobs.execute(args.job_dir)
    jobs.require(args.image and args.tool and args.arguments, "Native recording needs --image, --tool and --arguments")
    inputs = jobs._read(args.inputs).get("images", []) if args.inputs else []
    return jobs.record_native(args.image, args.job_dir, tool=args.tool, source_ref=args.source_ref,
                              actual_arguments=jobs._read(args.arguments), images=inputs, base=args.project)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Greybox raster execution, profiles and recovery")
    _arguments(parser)
    args = parser.parse_args(argv)
    try:
        result = handle(args)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok", True) else 2
    except jobs.ImageError as exc:
        print(json.dumps({"ok": False, "error": str(exc), "code": exc.code,
                          "unknown_submission": exc.unknown_submission}), file=sys.stderr)
        return 2
    except Exception:
        # Third-party adapter bodies, signed URLs and credential details never
        # enter the host transcript through unhandled exception strings.
        print(json.dumps({"ok": False, "error": "Image operation failed; preserve the job and inspect its local state", "code": "IMAGE_OPERATION_FAILED"}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
