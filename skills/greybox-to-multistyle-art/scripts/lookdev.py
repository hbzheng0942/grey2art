#!/usr/bin/env python3
"""Compatibility entry for the Hole runner; mutable outputs must be outside the skill."""
from pathlib import Path
import runpy
import sys

sys.dont_write_bytecode = True
skill = Path(__file__).resolve().parents[1]
legacy = skill / 'runtime/legacy'
# Source development fallback only. Distribution always carries runtime/legacy.
if not (legacy / 'scripts/lookdev.py').is_file():
    candidate = skill.parents[1]
    if (candidate / 'scripts/lookdev.py').is_file():
        legacy = candidate
    else:
        raise SystemExit('Missing bundled legacy runtime; reinstall the complete skill package')
if len(sys.argv) > 1 and sys.argv[1] in {'run', 'replay', 'play'}:
    required = ['--overlay'] + (['--output'] if sys.argv[1] != 'play' else [])
    for flag in required:
        if flag not in sys.argv:
            raise SystemExit('Compatibility runner requires explicit ' + flag + ' outside the installed skill')
        index = sys.argv.index(flag) + 1
        if index >= len(sys.argv) or sys.argv[index].startswith('--'):
            raise SystemExit('Missing path for ' + flag)
        value = Path(sys.argv[index]).expanduser().resolve()
        if value == skill or skill in value.parents:
            raise SystemExit('Mutable output must be outside the installed skill: ' + str(value))
sys.path.insert(0, str(legacy / 'scripts'))
runpy.run_path(str(legacy / 'scripts/lookdev.py'), run_name='__main__')
