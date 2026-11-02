"""Host parser hooks shared by the CLI entrypoint and optional MCP wrapper."""
from pathlib import Path

from . import core, host


def add_parser(subparsers):
    parser = subparsers.add_parser("host", help="Discover, configure and verify portable host bindings; no paid calls")
    parser.add_argument("action", choices=["discover", "configure", "verify", "setup"])
    parser.add_argument("--host", choices=(*host.HOSTS, "auto"), help="Setup auto-detects one host; older actions default to workbuddy")
    parser.add_argument("--config-dir", type=Path)
    for name in host.PROGRAMS:
        parser.add_argument("--" + name, dest="executable_" + name.replace("-", "_"))
    parser.add_argument("--image-profile")
    parser.add_argument("--image-config-dir", type=Path)
    parser.add_argument("--connector-dir", type=Path)
    parser.add_argument("--capability-report", type=Path)
    parser.add_argument("--session-id")
    parser.add_argument("--scope", choices=["art", "greybox", "runtime", "spatial"], default="art", help="Prepare/check only the active branch; spatial binds native Blender authoring/review")
    parser.add_argument("--engine", choices=["godot", "unity", "blender"], help="Selected game engine, or Blender with spatial scope")
    parser.add_argument("--operation", choices=["create", "edit", "review"], help="Spatial operation; review does not require source write capability")
    parser.add_argument("--project", type=Path, help="Engine directory, or an existing .blend/workspace with spatial scope")
    parser.add_argument("--runtime", choices=["image", "lux"], help="Setup only: explicitly prepare this private runtime, without provider calls")
    parser.add_argument("--output", type=Path)
    return parser


def handle(args):
    bindings = {name: getattr(args, "executable_" + name.replace("-", "_"), None) for name in host.PROGRAMS}
    bindings = {key: value for key, value in bindings.items() if value is not None}
    selected_host = args.host or ("auto" if args.action == "setup" else "workbuddy")
    if selected_host == "auto" and args.action != "setup":
        from . import host_setup
        selected_host = host_setup.installer_module().resolve_host("auto", config_dir=host.config_root(args.config_dir))
    if args.output and core.inside(args.output, host.SKILL):
        raise ValueError("Choose an output outside the installed skill")
    if args.action == "setup":
        from . import host_setup
        result = host_setup.setup(selected_host, args.config_dir, args.project, args.engine, args.scope,
                                  bindings, args.image_profile, args.image_config_dir,
                                  core.read(args.capability_report) if args.capability_report else None,
                                  args.session_id, args.runtime, args.connector_dir, operation=args.operation)
    elif args.action == "discover":
        result = host.discover(selected_host, bindings, args.config_dir)
    elif args.action == "configure":
        result = host.configure(selected_host, bindings, args.image_profile, args.config_dir,
                                args.image_config_dir, args.connector_dir)
    else:
        result = host.verify(selected_host, args.config_dir,
                             core.read(args.capability_report) if args.capability_report else None,
                             args.session_id, args.scope, args.engine, operation=args.operation)
    if args.output:
        core.write(args.output, result)
    return result
