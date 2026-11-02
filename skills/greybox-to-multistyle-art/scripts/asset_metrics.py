#!/usr/bin/env python3
"""Read-only GLB inspect/compare; no processing, rendering or provider calls."""
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime"))
from greybox.asset_metrics import main

if __name__ == "__main__":
    raise SystemExit(main())
