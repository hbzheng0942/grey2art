#!/bin/sh
set -eu
TASK_SKILL_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
if command -v python3 >/dev/null 2>&1; then
  exec python3 "$TASK_SKILL_DIR/scripts/install.py" "$@"
fi
printf '%s\n' 'Python 3.10+ is required. Install Python, then run scripts/install.py with that interpreter.' >&2
exit 1
