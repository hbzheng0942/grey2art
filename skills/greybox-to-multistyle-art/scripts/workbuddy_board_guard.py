#!/usr/bin/env python3
"""Scoped WorkBuddy hooks; settings change only through explicit install/uninstall."""
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime"))
from greybox.workbuddy_board_guard import main

if __name__ == "__main__":
    raise SystemExit(main())
