#!/usr/bin/env python3
"""Installed entrypoint. All imports stay inside this skill directory."""
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime"))
from greybox.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
