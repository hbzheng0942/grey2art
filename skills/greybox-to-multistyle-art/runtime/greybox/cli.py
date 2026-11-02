"""Portable command surface; no submission or network during ordinary doctor."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

from . import VERSION, core

SKILL = Path(__file__).resolve().parents[2]


def doctor(project=None, godot=None, region=None, online=False, engine_name=None):
    from . import lux
    from . import godot as adapter
    files = []
    manifest = SKILL / "MANIFEST.json"
    if manifest.exists():
        m = core.read(manifest)
        for item in m.get("files", []):
            p = SKILL / item["path"]
            if not core.inside(p, SKILL) or not p.is_file() or core.file_hash(p) != item["sha256"]:
                files.append(item["path"])
    data = {"ok": not files, "version": VERSION, "python": sys.version.split()[0],
            "pythonExecutable": sys.executable, "node": shutil.which("node"),
            "package": "verified" if manifest.exists() and not files else ("changed" if files else "source-checkout"),
            "changedFiles": files, "imageGeneration": "native host or configured image service; use host discover/configure and image capabilities",
            "platform": sys.platform, "windowsNativeValidation": "pending-colleague-first-test"}
    from . import engines
    selected = engines.name({"engine": engine_name} if engine_name else {}, project)
    if selected == "unity":
        from . import unity
        try:
            core.require(project, "Unity diagnostics need its actual project")
            data["unity"] = unity.inspect(project, godot)
        except Exception as e:
            data["unity"] = {"ok": False, "error": str(e)}
            data["ok"] = False
    elif project:
        try:
            data["godot"] = adapter.inspect(project, godot_path=godot)
            if data["godot"].get("engine_error"):
                data["ok"] = False
        except Exception as e:
            data["godot"] = {"ok": False, "error": str(e)}
            data["ok"] = False
    else:
        try:
            executable = adapter.engine(godot)
            result = subprocess.run([executable, "--version"], capture_output=True, text=True, timeout=15)
            version = result.stdout.strip()
            core.require(result.returncode == 0 and version.startswith("4."), "This adapter requires the project's Godot 4 executable")
            data["godot"] = {"path": executable, "version": version, "projectCompatibility": "requires-intake"}
        except Exception as e:
            data["godot"] = {"ok": False, "error": str(e)}
            data["ok"] = False
    data["productionReady"] = False
    data["readinessScope"] = "Local package/engine diagnostics only; host image capability and authoring checkpoints require workflow_check.py. No paid call is made."
    data["nodeRequirement"] = "optional for generic Godot runtime; required by legacy JS tooling"
    data["dependencyGuide"] = str(SKILL / "references" / "capability-preflight.md")
    try:
        data["lux"] = lux.doctor(region=region, online=online)
    except Exception as e:
        data["lux"] = {"ok": False, "error": str(e)}
    if online and not data["lux"].get("ok", False):
        data["ok"] = False
    return data


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "feedback":
        from . import feedback_cli
        return feedback_cli.main(argv[1:])
    if argv and argv[0] == "task-context":
        from . import task_context_cli
        return task_context_cli.main(argv[1:])
    if argv and argv[0] == "scene-review":
        from . import scene_review_cli
        return scene_review_cli.main(argv[1:])
    if argv and argv[0] == "executor":
        from . import execution_cli
        return execution_cli.main(argv[1:])
    if argv and argv[0] == "knowledge":
        from . import knowledge
        return knowledge.main(argv[1:])
    if argv and argv[0] == "boards":
        if len(argv) > 1 and argv[1] == "workbuddy":
            from . import board_workbuddy
            return board_workbuddy.main(argv[2:])
        if len(argv) > 1 and argv[1] in {"start", "next", "status", "advance", "compare"}:
            from . import board_registry
            return board_registry.main(argv[1:])
        if len(argv) > 1 and argv[1] == "production":
            from . import board_production
            return board_production.main(argv[2:])
        if len(argv) == 1 or argv[1] in {"--help", "-h"}:
            helper = argparse.ArgumentParser(prog="greybox.py boards", description="Whole-page reference preparation and strict output provenance; no generation")
            commands = helper.add_subparsers(dest="command", required=True)
            for name, help_text in [("plan", "Estimate pixels, layouts and invocation counts"),
                                    ("start", "Compile one asset/view registry into persistent page jobs"),
                                    ("next", "Read the next registry page action without submitting"),
                                    ("status", "Read registry page jobs and current production status"),
                                    ("advance", "Prepare deferred views from qualified identity masters"),
                                    ("compare", "Record a complete original asset multiview comparison"),
                                    ("workbuddy", "Bind WorkBuddy scoped guard and registry production"),
                                    ("production", "Persistent scope-bound board prepare, claim, record, crop and review"),
                                    ("prepare", "Write guides, complete prompts and one edit request per ready page"),
                                    ("native", "Map a page request to the actual native tool arguments"),
                                    ("record-native", "Verify actual native arguments and record the shared board receipt"),
                                    ("crop", "Crop an observed object ROI without resizing"),
                                    ("validate", "Replay and verify one crop receipt")]:
                commands.add_parser(name, help=help_text)
            helper.parse_args(argv[1:])
        if len(argv) > 1 and argv[1] in {"native", "record-native"}:
            from . import board_native
            return board_native.main(argv[1:])
        from . import reference_boards
        return reference_boards.main(argv[1:])
    p = argparse.ArgumentParser(description="Multistyle art workflow and native engine runtime " + VERSION)
    p.add_argument("--version", action="version", version=VERSION)
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("feedback", help="Record sourced usage observations and derive local recaps/regression candidates; no network")
    sub.add_parser("task-context", help="Inspect/pin the actual task entry or guard continuation against context drift")
    sub.add_parser("scene-review", help="Prepare/check concept-to-native comparisons; no visual acceptance authority")
    sub.add_parser("knowledge", help="Current-stage methods, optional topics and reference audit; no execution")
    sub.add_parser("executor", help="Durable rolling submission, shared account capacity and bounded action workers")
    sub.add_parser("boards", help="Prepare whole-page image requests, map native tools or crop/verify actual boards; no generation")
    from . import engine_cli, image_cli, host_cli, harness_cli
    engine_cli.add_parser(sub)
    image_cli.add_parser(sub)
    host_cli.add_parser(sub)
    harness_cli.add_parser(sub)
    s = sub.add_parser("workspace", help="Case/shared/style ownership, navigation and read-only migration inventory")
    s.add_argument("action", choices=["register", "paths", "show", "inventory", "record", "audit"])
    s.add_argument("--file", type=Path, help="Current plan or draft with workspace/styles/asset ownership")
    s.add_argument("--project", type=Path, required=True)
    s.add_argument("--style-id")
    s.add_argument("--asset-id")
    s.add_argument("--path", help="Actual resource path, including engine-native res:// where supported")
    s.add_argument("--dependencies", type=Path, help="Hash-bound explicit dependencies for computed loads")
    s.add_argument("--role")
    s.add_argument("--provenance", type=Path)
    s.add_argument("--output", type=Path)
    s = sub.add_parser("references", help="Audit real modeling images or validate a style-bound single/multiview package; no image generation")
    s.add_argument("action", choices=["audit", "validate"])
    s.add_argument("--image", type=Path)
    s.add_argument("--file", type=Path)
    s.add_argument("--project", type=Path)
    s.add_argument("--output", type=Path)
    s = sub.add_parser("provider", help="Dedicated APIs: offline capabilities/validation or explicit read-only account/task operations")
    s.add_argument("action", choices=["capabilities", "validate", "quote", "account", "status", "fetch"])
    s.add_argument("--provider", required=True)
    s.add_argument("--request", type=Path, help="Private JSON input; recovery metadata is never printed")
    s.add_argument("--output", type=Path, help="Write a sanitized report outside the installed skill")
    s = sub.add_parser("blender", help="Optional static geometry backend; MCP script, background CLI and result verification")
    s.add_argument("action", choices=["inspect", "script", "run", "verify", "admit-godot", "bake", "scatter", "render"])
    s.add_argument("--file", type=Path)
    s.add_argument("--executable")
    s.add_argument("--godot")
    s.add_argument("--output", type=Path)
    s = sub.add_parser("estimate", help="Calculate a sourced official rate card locally; no API request")
    s.add_argument("--rate-card", type=Path, required=True)
    s.add_argument("--operation", required=True)
    s.add_argument("--model-version", required=True)
    s.add_argument("--parameters", type=Path, required=True)
    s.add_argument("--project", type=Path)
    s.add_argument("--output", type=Path)
    s = sub.add_parser("suppliers", help="Inspect every configured/desired supplier; no network or generation")
    s.add_argument("--file", type=Path, required=True)
    s.add_argument("--project", type=Path)
    s.add_argument("--output", type=Path)
    s = sub.add_parser("portfolio", help="Compare complete supplier portfolios; optional exact H3 selection check")
    s.add_argument("--file", type=Path, required=True)
    s.add_argument("--registry", type=Path, required=True)
    s.add_argument("--selection", type=Path)
    s.add_argument("--project", type=Path)
    s.add_argument("--output", type=Path)
    s = sub.add_parser("overview", help="Generate the early workflow brief; never grants approval")
    s.add_argument("--file", type=Path, required=True)
    s.add_argument("--host-report", type=Path)
    s.add_argument("--output", type=Path)
    s.add_argument("--format", choices=["json", "markdown"], default="json")
    s = sub.add_parser("host-check", help="Check exact host operations; profiles alone prove no capability")
    s.add_argument("--file", type=Path, required=True)
    s.add_argument("--require-operation", action="append", default=[])
    s.add_argument("--host-id")
    s.add_argument("--session-id")
    s = sub.add_parser("supplier-jobs", help="Resume exact approved asset operations; native acceptance is separate")
    jobs = s.add_subparsers(dest="job_action", required=True)
    for action in ("prepare", "step", "status", "reconcile", "recover-artifacts"):
        j = jobs.add_parser(action)
        j.add_argument("--run-dir", type=Path, required=True)
        if action == "prepare":
            j.add_argument("--project", type=Path, required=True)
            j.add_argument("--registry", type=Path, required=True)
            j.add_argument("--portfolio", type=Path, required=True)
            j.add_argument("--selection", type=Path, required=True)
            j.add_argument("--workflow", type=Path, required=True)
            j.add_argument("--capabilities", type=Path, required=True)
            j.add_argument("--session-id", required=True)
            j.add_argument("--expansion", action="store_true")
        elif action == "step":
            j.add_argument("--registry", type=Path, help="Refresh readiness only; approved bindings must remain identical")
            j.add_argument("--capabilities", type=Path)
            j.add_argument("--session-id")
            j.add_argument("--max-submissions", type=int, default=1)
        elif action == "reconcile":
            j.add_argument("--operation-id", required=True)
            j.add_argument("--task-id", required=True)
            j.add_argument("--note", required=True)
            j.add_argument("--recovery", type=Path, help="Private provider recovery identifiers; never paste them in chat")
        elif action == "recover-artifacts":
            j.add_argument("--operation-id", required=True)
            j.add_argument("--source-ref", required=True, help="Actual missing/damaged artifact observation; no generation authorization")
    for name in ("setup", "doctor"):
        s = sub.add_parser(name)
        s.add_argument("--project", type=Path)
        s.add_argument("--godot")
        s.add_argument("--executable")
        s.add_argument("--engine", choices=["godot", "unity"])
        s.add_argument("--region", choices=["cn", "international"])
        if name == "doctor":
            s.add_argument("--online", action="store_true")
        else:
            s.add_argument("--configure-key", action="store_true")
            s.add_argument("--install-dependencies", action="store_true")
            s.add_argument("--install-fixture", type=Path)
    s = sub.add_parser("intake")
    s.add_argument("--project", type=Path, required=True)
    s.add_argument("--godot")
    s.add_argument("--executable")
    s.add_argument("--engine", choices=["godot", "unity"])
    s.add_argument("--output", type=Path)
    s = sub.add_parser("plan")
    s.add_argument("--file", "--plan", dest="file", type=Path, required=True)
    s.add_argument("--project", type=Path, required=True)
    s.add_argument("--run-dir", type=Path, required=True)
    s.add_argument("--capabilities", type=Path, help="Fresh host capability report, separate from creative checkpoint")
    s.add_argument("--session-id", help="Current host session for --capabilities")
    s = sub.add_parser("quote-preview", help="Current prices after H1/H2, before H3; never submit generation")
    s.add_argument("--file", type=Path, required=True)
    s.add_argument("--project", type=Path, required=True)
    s.add_argument("--output", type=Path, required=True)
    s.add_argument("--capabilities", type=Path, required=True)
    s.add_argument("--session-id", required=True)
    for name in ("run", "resume", "status", "quote", "approve", "reconcile", "validate", "play", "rollback", "refresh-readiness", "delivery-manifest", "accept-delivery", "delivery-review-inputs", "record-delivery-review"):
        s = sub.add_parser(name)
        s.add_argument("--run-dir", type=Path, required=True)
        if name == 'record-delivery-review':
            s.add_argument('--file', type=Path, required=True)
        if name in ("run", "resume", "validate", "play"):
            s.add_argument("--godot")
            s.add_argument("--executable", help="Selected engine executable; --godot remains a compatibility alias")
            s.add_argument("--style", required=name == "play")
        if name == "refresh-readiness":
            s.add_argument("--file", type=Path, required=True)
            s.add_argument("--session-id", required=True)
        if name == "accept-delivery":
            s.add_argument("--actor", choices=["user"], required=True)
            s.add_argument("--source-ref", required=True)
            s.add_argument("--note", required=True)
            s.add_argument("--manifest-hash", required=True)
        if name == "approve":
            s.add_argument("--actor", choices=["user"], required=True)
            s.add_argument("--note", required=True)
            s.add_argument("--quote-hash")
            s.add_argument("--allow-quote-refresh", action="store_true", help="Only when user authorized same scope within quoted ceiling")
        if name == "reconcile":
            s.add_argument("--asset", required=True)
            s.add_argument("--task-id", type=int, required=True)
            s.add_argument("--note", required=True)
    s = sub.add_parser("lux", help="Configuration/capabilities and existing-task inspection only")
    s.add_argument("action", choices=["capabilities", "status", "fetch"])
    s.add_argument("--region", choices=["cn", "international"])
    s.add_argument("--task-id", type=int)
    s.add_argument("--output", type=Path)
    args = p.parse_args(argv)
    try:
        for attr in ("output", "run_dir", "install_fixture"):
            value = getattr(args, attr, None)
            if value:
                core.require(not core.inside(value, SKILL), "Installed skill is read-only; choose an external output")
        if args.command in ("plan", "run", "resume", "validate", "play", "rollback") and getattr(args, "project", None):
            core.require(not core.inside(args.project, SKILL), "Copy the fixture outside the installed skill before using it")
        if args.command == "workspace" and args.action in ("register", "record"):
            core.require(not core.inside(args.project, SKILL), "Installed skill is read-only; choose an external project")
        if args.command in {"route", "greybox"}:
            result = harness_cli.handle(args)
        elif args.command == "engine":
            result = engine_cli.handle(args)
        elif args.command == "image":
            result = image_cli.handle(args)
        elif args.command == "host":
            result = host_cli.handle(args)
        elif args.command == "workspace":
            from . import layout
            plan = core.read(args.file) if args.file else None
            if args.action == "inventory":
                result = layout.inventory(args.project, plan)
            else:
                core.require(plan is not None, "Workspace command needs --file identifying its current case and styles")
                if args.action == "register":
                    result = layout.register(args.project, plan)
                elif args.action == "paths":
                    result = {"ok": True, "paths": layout.roots(args.project, plan, args.style_id)}
                elif args.action == "show":
                    result = layout.read_navigation(args.project, plan)
                elif args.action == "audit":
                    from . import engine_workspace
                    core.require(args.path and args.style_id, "Engine audit needs --path and --style-id")
                    result = engine_workspace.audit(args.project, plan, args.style_id, args.path,
                        explicitdeps=core.read(args.dependencies) if args.dependencies else None)
                else:
                    core.require(args.path is not None and args.role, "Record needs --path and --role")
                    result = layout.record_artifact(args.project, plan, args.path, args.role, args.style_id, args.asset_id,
                        provenance=core.read(args.provenance) if args.provenance else None,
                        write_manifest=args.role in {"asset", "model", "texture"})
            if args.output:
                core.write(args.output, result)
        elif args.command == "references":
            from . import modeling_refs
            if args.action == "audit":
                core.require(args.image is not None, "Reference audit needs --image")
                result = {"ok": True, **modeling_refs.audit_image(args.image)}
            else:
                core.require(args.file is not None and args.project is not None, "Reference validate needs --file and --project")
                result = modeling_refs.validate_package(core.read(args.file), args.project)
            if args.output:
                core.write(args.output, result)
        elif args.command == "provider":
            from . import provider_adapter
            request = core.read(args.request) if args.request else {}
            result = provider_adapter.public_result(provider_adapter.dispatch(args.provider, args.action, request))
            if args.output:
                core.require(not args.output.exists(), "Preserve the previous provider diagnostic report")
                core.write(args.output, result)
        elif args.command == "blender":
            from . import blender
            if args.action == "inspect":
                result = blender.discover(args.executable)
            else:
                core.require(args.file, "Blender job action requires --file")
                job = core.read(args.file)
                if args.action in {"bake", "scatter", "render"}:
                    from . import blender_jobs
                    core.require(job.get("operation") == args.action, "Blender operation differs from its job")
                    core.require(not core.inside(job.get("output_dir", SKILL), SKILL), "Blender output must be outside the installed skill")
                    result = blender_jobs.execute(job, executable=args.executable)
                elif args.action == "run":
                    result = blender.execute_cli(job, executable=args.executable)
                elif args.action == "admit-godot":
                    from . import blender_godot
                    result = blender_godot.native_admit(job, godot_path=args.godot)
                elif args.action == "verify":
                    result = blender.verify_result(job)
                else:
                    core.require(args.output and not args.output.exists(), "Choose a new external script --output")
                    script = blender.build_script(job)
                    args.output.parent.mkdir(parents=True, exist_ok=True)
                    args.output.write_text(script, encoding="utf-8")
                    result = {"ok": True, "script": str(args.output), "sha256": core.file_hash(args.output),
                              "note": "Prepared only. Invoke with the discovered Blender MCP or background CLI."}
        elif args.command == "supplier-jobs":
            from . import supplier_jobs
            if args.job_action == "prepare":
                result = supplier_jobs.prepare(args.project, args.run_dir, core.read(args.registry),
                    core.read(args.portfolio), core.read(args.selection), args.workflow,
                    core.read(args.capabilities), args.session_id, args.expansion)
            elif args.job_action == "step":
                result = supplier_jobs.step(args.run_dir,
                    registry_refresh=core.read(args.registry) if args.registry else None,
                    capabilities=core.read(args.capabilities) if args.capabilities else None,
                    session_id=args.session_id, max_submissions=args.max_submissions)
            elif args.job_action == "reconcile":
                result = supplier_jobs.reconcile(args.run_dir, args.operation_id, args.task_id, args.note,
                    recovery=core.read(args.recovery) if args.recovery else None)
            elif args.job_action == "recover-artifacts":
                result = supplier_jobs.recover_artifacts(args.run_dir, args.operation_id, args.source_ref)
            else:
                result = supplier_jobs.status(args.run_dir)
        elif args.command == "estimate":
            from . import suppliers
            result = suppliers.estimate_from_rate_card(core.read(args.rate_card), args.operation, args.model_version,
                core.read(args.parameters), base=args.project or args.rate_card.resolve().parent)
            if args.output:
                core.require(not args.output.exists(), "Estimate output already exists; preserve prior pricing evidence")
                core.write(args.output, result)
        elif args.command in ("suppliers", "portfolio"):
            from . import suppliers
            base = args.project or args.file.resolve().parent
            if args.command == "suppliers":
                result = suppliers.inventory(core.read(args.file), base=base)
            else:
                registry = core.read(args.registry)
                document = core.read(args.file)
                result = suppliers.validate_portfolio(document, registry, base=base)
                if args.selection:
                    result["selection"] = suppliers.validate_selection(core.read(args.selection), document, registry, base=base)
            if args.output:
                core.require(not args.output.exists(), "Output already exists; preserve the prior report")
                core.write(args.output, result)
        elif args.command == "overview":
            from . import overview
            brief = overview.generate_overview(core.read(args.file), core.read(args.host_report) if args.host_report else None)
            result = brief if args.format == "json" else overview.render_overview(brief)
            if args.output:
                core.require(not args.output.exists(), "Overview output already exists; use an explicit revision")
                if args.format == "json":
                    core.write(args.output, result)
                else:
                    args.output.parent.mkdir(parents=True, exist_ok=True)
                    args.output.write_text(result, encoding="utf-8")
        elif args.command == "host-check":
            from . import overview
            result = overview.check_host_capabilities(core.read(args.file), args.require_operation or None,
                                                     args.host_id, args.session_id)
        elif args.command == "doctor":
            result = doctor(args.project, args.executable or args.godot, args.region, args.online, args.engine)
        elif args.command == "setup":
            from . import lux
            result = {"ok": True, "version": VERSION}
            if args.install_fixture:
                src = SKILL / "fixtures" / "tiny-godot"
                if not src.is_dir():
                    choices = list((SKILL / "fixtures").glob("*/project.godot"))
                    core.require(len(choices) == 1, "Specify the fixture directory from the package")
                    src = choices[0].parent
                core.require(not args.install_fixture.exists(), "Fixture destination already exists; preserve its work")
                shutil.copytree(src, args.install_fixture, ignore=shutil.ignore_patterns(".godot", "__pycache__", "art"))
                result["fixture"] = str(args.install_fixture.resolve())
            if args.region:
                result["lux"] = lux.setup(args.region, configure_key=args.configure_key,
                                           install_dependencies=args.install_dependencies)
                result["ok"] = result["lux"].get("ok", True)
            elif args.configure_key or args.install_dependencies:
                raise core.WorkflowError("Choose --region cn or international for Lux setup")
            result["diagnostics"] = doctor(args.project, args.executable or args.godot, args.region, engine_name=args.engine)
            result["installationCompleted"] = bool(result.get("fixture"))
            result["ready"] = bool(result["diagnostics"].get("ok"))
            result["ok"] = result["ok"] and result["ready"]
        elif args.command == "intake":
            from . import engines
            selected = engines.name({"engine": args.engine} if args.engine else {}, args.project)
            if selected == "unity":
                from . import unity
                result = unity.inspect(args.project, args.executable or args.godot)
            else:
                from . import godot
                result = godot.inspect(str(args.project), godot_path=args.executable or args.godot)
            if args.output:
                core.write(args.output, result)
        elif args.command == "quote-preview":
            from . import quote_preview
            result = quote_preview.preview(args.file, args.project, args.output, args.capabilities, args.session_id)
        elif args.command == "plan":
            result = core.prepare(args.file, args.project, args.run_dir, args.capabilities, args.session_id)
        elif args.command in ("run", "resume"):
            result = core.run(args.run_dir, godot_path=args.executable or args.godot, style=args.style, recovery=args.command == "resume")
        elif args.command == "quote":
            result = core.quote_run(args.run_dir)
        elif args.command == "approve":
            result = core.approve(args.run_dir, args.actor, args.note, args.quote_hash, args.allow_quote_refresh)
        elif args.command == "reconcile":
            result = core.reconcile(args.run_dir, args.asset, args.task_id, args.note)
        elif args.command == "validate":
            result = core.validate(args.run_dir, godot_path=args.executable or args.godot, style=args.style)
        elif args.command == "play":
            result = core.play(args.run_dir, args.style, godot_path=args.executable or args.godot)
        elif args.command == "rollback":
            result = core.rollback(args.run_dir)
        elif args.command == "status":
            result = core.status(args.run_dir)
        elif args.command == "delivery-manifest":
            from . import delivery
            result = delivery.propose_manifest(args.run_dir)
        elif args.command == 'delivery-review-inputs':
            from . import delivery
            result = delivery.review_inputs(args.run_dir)
        elif args.command == 'record-delivery-review':
            from . import delivery
            result = delivery.record_review(args.run_dir, core.read(args.file))
        elif args.command == "accept-delivery":
            from . import delivery
            result = delivery.accept(args.run_dir, args.actor, args.source_ref, args.note, args.manifest_hash)
        elif args.command == "refresh-readiness":
            result = core.refresh_readiness(args.run_dir, args.file, args.session_id)
        elif args.command == "lux":
            from . import lux
            if args.action == "capabilities":
                result = lux.capabilities()
            else:
                core.require(args.region and args.task_id, "Existing-task operations need --region and --task-id")
                if args.action == "status":
                    raw = lux.status(args.task_id, args.region)
                    data = raw.get("data", raw)
                    result = {"ok": True, "taskId": args.task_id, "region": args.region, "status": data.get("status"),
                              "note": "Output URLs are kept in task files, not printed"}
                else:
                    core.require(args.output, "fetch needs --output")
                    raw = lux.fetch(args.task_id, args.region, str(args.output))
                    result = {"ok": raw.get("ok", True), "taskId": args.task_id, "output": str(args.output),
                              "glbFiles": core._fetch_paths(raw)}
        else:
            raise core.WorkflowError("Unknown command")
        if isinstance(result, str) and hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8')
        print(result if isinstance(result, str) else json.dumps(result, ensure_ascii=True, indent=2, default=str))
        return 0 if not isinstance(result, dict) or result.get("ok", True) else 2
    except Exception as e:
        # Bridge errors redact credentials and signed URLs at the provider boundary.
        print(json.dumps({"ok": False, "error": str(e), "type": type(e).__name__}, ensure_ascii=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
