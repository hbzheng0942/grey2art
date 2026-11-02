#!/usr/bin/env python3
"""Portable raster-only entrypoint; no Node, MCP or native image tool required."""
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime"))
from greybox.image_cli import main

if __name__ == "__main__":
    raise SystemExit(main())
