#!/usr/bin/env python3
"""Optional stdio MCP entrypoint; the regular CLI never imports MCP packages."""
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "runtime"))
from greybox.mcp_bridge import serve

if __name__ == "__main__":
    serve()
