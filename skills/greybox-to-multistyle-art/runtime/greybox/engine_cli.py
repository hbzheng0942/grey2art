"""Native engine operations shared by local CLI and host wrappers."""
from pathlib import Path
import subprocess

from . import core, engines


def add_parser(sub):
    p = sub.add_parser("engine", help="Native Unity/Godot inspection, assembly, effects and runtime operations")
    p.add_argument("action", choices=["inspect", "configure", "assemble", "lookdev", "capture", "validate", "play", "export"])
    p.add_argument("--project", type=Path, required=True)
    p.add_argument("--engine", choices=["godot", "unity"])
    p.add_argument("--file", type=Path, help="Operation JSON; a native plan or explicit bridge configuration")
    p.add_argument("--output", type=Path)
    p.add_argument("--run-dir", type=Path)
    p.add_argument("--executable")
    p.add_argument("--style")
    p.add_argument("--native", action="store_true", help="Run the native editor for inspection")


def handle(args):
    project = args.project.resolve()
    config = core.read(args.file) if args.file else {}
    selected = engines.name({"engine": args.engine} if args.engine else config, project)
    if selected == "unity":
        from . import unity
        if config.get("kind") == "greybox-art-plan" or ("contract" in config and "bindings" in config):
            config = {"plan": config}
        elif "entry_scene" in config and "binding_digest" in config:
            config = {"artifact": config}
        if args.action == "inspect" and not args.native:
            return unity.inspect(project)
        if args.style:
            config["style_id"] = args.style
        if args.action == "play":
            return unity.launch(project, config, unity_bin=args.executable)
        return unity.run(project, args.action, config=config, output=args.output,
                         unity_bin=args.executable)
    from . import godot
    core.require(args.action != "configure", "Godot keeps its project configuration; use explicit lookdev recipes")
    if args.action == "inspect":
        return godot.inspect(project, godot_path=args.executable)
    if args.action == "lookdev":
        from . import effects
        core.require(args.output, "lookdev requires a task-owned --output directory")
        return effects.apply_godot(project, config, args.output)
    if args.action == "assemble":
        core.require(args.run_dir and args.style, "assemble requires --run-dir and --style")
        return godot.assemble(project, args.run_dir, config, args.style, godot_path=args.executable)
    if args.action in {"validate", "capture"}:
        core.require(args.output, "Native evidence requires --output")
        return godot.validate(project, config.get("artifact", config), args.output, godot_path=args.executable)
    if args.action == "play":
        return godot.launch(project, config.get("artifact", config), godot_path=args.executable)
    core.require(args.output and config.get("preset"), "export needs --output and a configured export preset")
    core.require(not args.output.exists(), "Export target already exists; preserve it and select a fresh target")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run([godot.engine(args.executable), "--headless", "--path", str(project),
                             "--export-release", config["preset"], str(args.output.resolve())],
                            capture_output=True, text=True, timeout=config.get("timeout", 600))
    log = args.output.parent / (args.output.name + ".export.log")
    log.write_text(result.stdout + result.stderr, encoding="utf-8")
    return {"ok": result.returncode == 0 and args.output.is_file(), "engine": "godot",
            "returncode": result.returncode, "output": str(args.output), "log_path": str(log)}
