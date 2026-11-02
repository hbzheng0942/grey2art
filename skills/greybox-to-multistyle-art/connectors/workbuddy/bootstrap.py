#!/usr/bin/env python3
"""Initialize only the WorkBuddy-managed Python; keep service credentials separate."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import subprocess
import sys

sys.dont_write_bytecode = True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skill-root", required=True, type=Path)
    parser.add_argument("--config-dir", type=Path)
    parser.add_argument("--skip-dependencies", action="store_true")
    parser.add_argument("--install-image-dependencies", action="store_true",
                        help="Optional API image runtime only; ordinary connector initialization needs no packages")
    args = parser.parse_args(argv)
    root = args.skill_root.expanduser().absolute()
    if sys.version_info < (3, 10):
        parser.error("Python 3.10+ is required; this connector requests WorkBuddy-managed Python 3.11")
    if not (root / "runtime/greybox/host.py").is_file():
        parser.error("Install the source skill before initializing its connector")
    if args.install_image_dependencies and not args.skip_dependencies:
        if sys.prefix == sys.base_prefix:
            parser.error("Use WorkBuddy's managed virtual environment or install.py --bootstrap with an external runtime; global pip is never used")
        # WorkBuddy supplies an isolated interpreter/venv; never use --user/global pip.
        result = subprocess.run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
                                 "-r", str(root / "connectors/workbuddy/requirements.txt")],
                                capture_output=True, text=True, check=False)
        if result.returncode:
            print(json.dumps({"ok": False, "error": "Managed Python dependency installation failed; check the WorkBuddy package index/network and retry"}))
            return 1
    sys.path.insert(0, str(root / "runtime"))
    from greybox import host
    result = host.configure("workbuddy", {"python": sys.executable}, config_dir=args.config_dir)
    result["dependencies"] = "image-installed" if args.install_image_dependencies and not args.skip_dependencies else "deferred-until-current-operation-needs-them"
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
