#!/usr/bin/env python3
"""Local stage/topic reading navigation and explicit static knowledge audit."""
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime"))
from greybox.knowledge import main

if __name__ == "__main__":
    raise SystemExit(main())
