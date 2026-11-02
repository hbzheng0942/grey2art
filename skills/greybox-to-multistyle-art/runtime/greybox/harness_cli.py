"""Greybox construction and contextual intake command bindings."""
from pathlib import Path

from . import core, harness, intake


def add_parser(sub):
    route = sub.add_parser("route", help="Read-only route from explicit interpreted intent, actual project and original task")
    route.add_argument("--file", type=Path, required=True)
    route.add_argument("--project", type=Path)
    route.add_argument("--output", type=Path)
    p = sub.add_parser("greybox", help="Local semantic greybox creation/iteration; no art or paid generation")
    p.add_argument("action", choices=["init", "build", "play", "validate", "handoff", "status"])
    p.add_argument("--project", type=Path)
    p.add_argument("--run-dir", type=Path, required=True)
    p.add_argument("--file", type=Path)
    p.add_argument("--output", type=Path)
    p.add_argument("--engine", choices=["godot", "unity"])
    p.add_argument("--goal", choices=["playable", "spatial"], default="playable")
    p.add_argument("--id", default="prototype")
    p.add_argument("--stop-at", choices=["greybox", "art"], default="greybox")
    p.add_argument("--source-ref")
    p.add_argument("--executable")


def handle(args):
    if args.command == "route":
        result = intake.route(core.read(args.file), args.project)
        if args.output:
            core.require(not args.output.exists(), "Preserve the previous routing decision")
            core.write(args.output, result)
        return result
    if args.project:
        args.project = args.project.resolve()
        if not args.run_dir.is_absolute():
            args.run_dir = args.project / args.run_dir
        if args.output and not args.output.is_absolute():
            args.output = args.project / args.output
    if args.project and args.action != "init":
        _, state = harness._load(args.run_dir)
        core.require(args.project.resolve() == Path(state["project"]), "Job belongs to a different project")
    if args.action == "init":
        core.require(args.project, "Initialization needs --project")
        core.require(args.file or args.engine, "Provide --file or an explicit --engine for the editable starter")
        plan = core.read(args.file) if args.file else harness.starter(args.engine, args.goal, args.id)
        return harness.initialize(args.project, args.run_dir, plan, args.stop_at, args.source_ref)
    if args.action == "build":
        return harness.build(args.run_dir, core.read(args.file) if args.file else None, args.executable)
    if args.action == "play":
        return harness.play(args.run_dir, args.executable)
    if args.action == "validate":
        return harness.validate(args.run_dir, core.read(args.file) if args.file else None, args.executable)
    if args.action == "handoff":
        core.require(args.output, "Handoff requires a fresh --output manifest")
        return harness.handoff(args.run_dir, args.output, core.read(args.file) if args.file else None)
    return harness.status(args.run_dir)
