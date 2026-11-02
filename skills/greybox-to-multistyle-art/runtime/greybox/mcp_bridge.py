"""Optional stdio MCP facade over the same installed CLI. No Node/MCP dependency."""
from __future__ import annotations
import base64
import json
from pathlib import Path
import subprocess
import sys

from . import VERSION, host

TOOLS = [
    {"name": "greybox_cli", "description": "Invoke the common Greybox Art CLI with exact argv, without a shell. For long image calls use submit/status/fetch/resume; do not repeat uncertain submissions.",
     "inputSchema": {"type": "object", "properties": {"argv": {"type": "array", "items": {"type": "string"}, "minItems": 1}}, "required": ["argv"], "additionalProperties": False}},
    {"name": "greybox_image", "description": "Return actual local PNG/JPEG/WebP pixels as an MCP image. A successful response must still be inspected by the host model.",
     "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"], "additionalProperties": False}},
]


def call_tool(name, arguments):
    if name == "greybox_image":
        path = Path(arguments["path"]).expanduser().absolute()
        if not path.is_file() or path.stat().st_size > 10 * 1024 * 1024:
            raise ValueError("Image must be a local file up to 10 MiB")
        payload = path.read_bytes()
        if payload.startswith(b"\x89PNG\r\n\x1a\n"):
            mime = "image/png"
        elif payload.startswith(b"\xff\xd8\xff"):
            mime = "image/jpeg"
        elif payload.startswith(b"RIFF") and payload[8:12] == b"WEBP":
            mime = "image/webp"
        else:
            raise ValueError("Use a PNG, JPEG or WebP image; no text or other binary payloads")
        from .modeling_refs import _decode
        _decode(payload)
        return {"content": [{"type": "image", "mimeType": mime, "data": base64.b64encode(payload).decode("ascii")}], "isError": False}
    if name != "greybox_cli":
        raise ValueError("Unknown Greybox tool")
    argv = arguments.get("argv")
    if not isinstance(argv, list) or not argv or not all(isinstance(v, str) and "\0" not in v for v in argv):
        raise ValueError("argv must be a nonempty list of strings")
    try:
        result = subprocess.run([sys.executable, str(host.SKILL / "scripts/greybox.py"), *argv],
                                capture_output=True, text=True, timeout=55, check=False)
    except subprocess.TimeoutExpired:
        # Never retry; image submission records own the task's recovery identity.
        return {"content": [{"type": "text", "text": json.dumps({"ok": False, "error": "CLI exceeded the tool window. Inspect persisted task status before any new submission."})}], "isError": True}
    return {"content": [{"type": "text", "text": result.stdout if result.returncode == 0 else result.stderr or result.stdout}],
            "isError": result.returncode != 0}


def serve(instream=None, outstream=None):
    """MCP newline-delimited JSON-RPC; stdout is reserved for protocol messages."""
    instream, outstream = instream or sys.stdin, outstream or sys.stdout
    for line in instream:
        request = None
        try:
            request = json.loads(line)
            if "id" not in request:
                continue
            method = request.get("method")
            if method == "initialize":
                result = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                          "serverInfo": {"name": "greybox-art", "version": VERSION}}
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": TOOLS}
            elif method == "tools/call":
                params = request.get("params", {})
                result = call_tool(params.get("name"), params.get("arguments", {}))
            else:
                outstream.write(json.dumps({"jsonrpc": "2.0", "id": request["id"], "error": {"code": -32601, "message": "Method not found"}}) + "\n")
                outstream.flush()
                continue
            response = {"jsonrpc": "2.0", "id": request["id"], "result": result}
        except Exception:
            # Avoid logging arbitrary request values, API keys or local transport details.
            response = {"jsonrpc": "2.0", "id": request.get("id") if isinstance(request, dict) else None,
                        "error": {"code": -32602, "message": "Invalid request or local operation failed; inspect the selected CLI operation locally"}}
        outstream.write(json.dumps(response, ensure_ascii=False) + "\n")
        outstream.flush()


if __name__ == "__main__":
    serve()
