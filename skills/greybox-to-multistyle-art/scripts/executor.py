#!/usr/bin/env python3
"""Portable executor entrypoint shared by every supported host."""
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime"))
from greybox.execution_cli import main

if __name__ == "__main__":
    raise SystemExit(main())
