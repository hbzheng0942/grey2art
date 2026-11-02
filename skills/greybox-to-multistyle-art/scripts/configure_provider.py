#!/usr/bin/env python3
"""Interactive user-terminal credential setup; never accepts a key argument."""
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime"))
from greybox.provider_credentials import configure

if __name__ == "__main__":
    raise SystemExit(configure())
