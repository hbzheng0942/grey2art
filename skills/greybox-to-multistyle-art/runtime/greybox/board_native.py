"""Offline native-tool mapping for the same hash-bound board edit request.

Bindings describe an observed host tool; this module never discovers, uploads or
invokes one. Recording still requires the real call's arguments and source.
"""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlsplit

from . import core, image_jobs, reference_boards as boards

HOSTS = {"codex", "workbuddy", "claude-code"}


def _field(value):
    core.require(isinstance(value, str) and value.strip() and len(value) <= 100,
                 "Native argument names must be nonempty strings")
    return value


def _text(value, message):
    core.require(isinstance(value, str) and value.strip(), message)
    return value


def _arguments(document, binding, project):
    core.require(isinstance(document, dict) and document.get("operation") == "edit"
                 and not document.get("mask"), "Board native mapping needs an unmasked edit request")
    core.require(not set(document) - {"operation", "prompt", "images", "parameters", "purpose", "source_ref"},
                 "Unexpected board request fields")
    prompt = _text(document.get("prompt"), "Board request needs its complete prompt")
    core.require(isinstance(binding, dict) and binding.get("schema") == 1
                 and binding.get("kind") == "reference-board-native-binding"
                 and binding.get("host") in HOSTS, "Expected current native board binding for a supported host")
    _text(binding.get("tool"), "Bind the actual native tool name")
    _text(binding.get("source_ref"), "Bind the current tool schema or observed capability source")
    images = document.get("images")
    capacity = binding.get("max_references")
    core.require(isinstance(images, list) and images and type(capacity) is int
                 and 0 < len(images) <= capacity, "Native tool reference capacity is insufficient; preserve all art inputs")
    bound = []
    for row in images:
        boards._file(row, project, {})
        bound.append(image_jobs._record_input(row, project))
    core.require(len({x["sha256"] for x in bound}) == len(bound), "Board inputs must have distinct bytes")
    transport = binding.get("input_transport")
    core.require(transport in {"local_paths", "https_urls", "mixed"}, "Declare the native tool's actual input transport")
    uploads = binding.get("uploads", [])
    core.require(isinstance(uploads, list), "Native uploads must be explicit hash-bound records")
    uploaded = {}
    for row in uploads:
        core.require(isinstance(row, dict) and boards._hash(row.get("sha256"))
                     and row["sha256"] not in uploaded, "Duplicate or invalid native upload identity")
        path, _ = boards._file({k: row.get(k) for k in ("path", "sha256")}, project, {})
        core.require(any(x["sha256"] == row["sha256"] and Path(x["path"]) == path for x in bound),
                     "Upload does not bind an actual ordered request input")
        _text(row.get("source_ref"), "Upload needs its actual host upload result source")
        url = _text(row.get("url"), "Upload needs an actual HTTPS URL")
        parsed = urlsplit(url)
        core.require(parsed.scheme == "https" and parsed.hostname and not parsed.username and not parsed.password,
                     "Native upload URL must be HTTPS without embedded credentials")
        uploaded[row["sha256"]] = url
    core.require(transport != "local_paths" or not uploaded, "Local-path transport must not silently use upload URLs")
    core.require(transport != "https_urls" or all(x["sha256"] in uploaded for x in bound),
                 "HTTPS transport needs a real upload mapping for every reference")
    values = [uploaded.get(x["sha256"], x["path"]) for x in bound]
    args = {}

    def put(key, value):
        key = _field(key)
        core.require(key not in args, "Native argument mapping collides; do not replace prompt or image inputs")
        args[key] = value

    put(binding.get("prompt_argument", "prompt"), prompt)
    array = binding.get("image_argument")
    named = binding.get("image_arguments")
    core.require((array is None) != (named is None), "Choose either an image array argument or ordered named image arguments")
    if array is not None:
        put(array, values)
    else:
        core.require(isinstance(named, list) and len(named) >= len(values)
                     and all(isinstance(x, str) for x in named) and len(set(named)) == len(named),
                     "Ordered native image argument slots are insufficient or duplicated")
        for key, value in zip(named, values):
            put(key, value)
    parameters = document.get("parameters", {})
    mapping = binding.get("parameter_arguments", {})
    core.require(isinstance(parameters, dict) and isinstance(mapping, dict)
                 and set(parameters) <= set(mapping), "Native tool does not map every requested parameter; revise the request explicitly")
    core.require(parameters.get("background", "opaque") in ("opaque", "white", "auto"),
                 "Modeling boards require opaque white output; transparent background is incompatible")
    core.require("n" not in parameters or type(parameters["n"]) is int and parameters["n"] == 1,
                 "One board request must produce one image")
    for key, value in parameters.items():
        put(mapping[key], value)
    fixed = binding.get("fixed_arguments", {})
    core.require(isinstance(fixed, dict), "Native fixed arguments must be an object")
    core.require(fixed.get("transparent_background", False) is False
                 and fixed.get("background", "opaque") in ("opaque", "white", "auto")
                 and ("n" not in fixed or type(fixed["n"]) is int and fixed["n"] == 1),
                 "Native fixed arguments must preserve one opaque white board")
    for key, value in fixed.items():
        put(key, value)
    envelope = binding.get("envelope_arguments", {})
    container = binding.get("arguments_container")
    core.require(isinstance(envelope, dict), "Native envelope arguments must be an object")
    if container is not None:
        core.require(_field(container) not in envelope, "Native envelope would overwrite the mapped call")
        args = {**envelope, container: args}
    else:
        core.require(not envelope, "Envelope arguments require an explicit arguments_container")
    core.digest(args)  # finite JSON, including fixed and mapped parameters
    return args, [{"path": x["path"], "sha256": x["sha256"]} for x in bound]


def prepare(document, binding, project, output, *, request_path, binding_path, host=None):
    """Freeze exact arguments without invoking the native tool or uploading."""
    project = Path(project).resolve()
    core.require(isinstance(binding, dict), "Native binding must be an object")
    core.require(host is None or host == binding.get("host"), "Requested host differs from its native binding")
    args, images = _arguments(document, binding, project)
    dependencies = {}
    source_request = boards._path(str(request_path), project)
    source_binding = boards._path(str(binding_path), project)
    for path, expected in ((source_request, document), (source_binding, binding)):
        core.require(path.is_file() and core.read(path) == expected, "Native mapping source differs from saved request or binding")
        dependencies[str(path)] = {"path": str(path.relative_to(project)), "sha256": core.file_hash(path)}
    dispatch = {"schema": 1, "kind": "reference-board-native-dispatch", "host": binding["host"],
                "tool": binding["tool"], "request": dependencies[str(source_request)],
                "binding": dependencies[str(source_binding)], "tool_arguments": args,
                "images": images, "invocation_recorded": False,
                "boundary": "Prepared arguments only. Invoke once under existing authority; reconcile unknown outcomes before any repeat."}
    path = boards._path(str(output), project)
    core.require(not core.inside(path, Path(__file__).resolve().parents[2]), "Installed skill is read-only")
    raw = (json.dumps(dispatch, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
    forbidden = {Path(p) for p in dependencies} | {Path(x["path"]) for x in images}
    boards._same_or_new(path, raw, forbidden)
    if not path.exists():
        core.ensure_directory(path.parent)
        with path.open("xb") as stream:
            stream.write(raw)
    return {"ok": True, "host": binding["host"], "tool": binding["tool"],
            "dispatch": {"path": str(path.relative_to(project)), "sha256": boards._sha(raw)},
            "input_count": len(images), "invocation_recorded": False,
            "network": False, "submission": False}


def record(dispatch, actual_arguments, image, job_dir, project, *, source_ref):
    """Verify the unchanged dispatch against a real call, then share its receipt."""
    project = Path(project).resolve()
    core.require(isinstance(dispatch, dict) and dispatch.get("schema") == 1
                 and dispatch.get("kind") == "reference-board-native-dispatch"
                 and dispatch.get("invocation_recorded") is False, "Expected a prepared native board dispatch")
    dependencies = {}
    _, request_raw = boards._file(dispatch.get("request"), project, dependencies)
    _, binding_raw = boards._file(dispatch.get("binding"), project, dependencies)
    binding = json.loads(binding_raw)
    args, images = _arguments(json.loads(request_raw), binding, project)
    core.require(dispatch.get("host") == binding["host"] and dispatch.get("tool") == binding["tool"]
                 and dispatch.get("tool_arguments") == args and dispatch.get("images") == images,
                 "Native dispatch changed or no longer matches its sources")
    core.require(isinstance(actual_arguments, dict) and actual_arguments == args,
                 "Actual native arguments differ: preserve full prompt and every ordered reference")
    folder = boards._path(str(job_dir), project)
    core.require(not core.inside(folder, Path(__file__).resolve().parents[2]), "Installed skill is read-only")
    return image_jobs.record_native(image, folder, tool=dispatch["tool"], source_ref=source_ref,
                                    actual_arguments=actual_arguments, images=images, base=project)


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description="Map or record a board's actual native image call; no invocation")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("native", "record-native"):
        item = sub.add_parser(name)
        item.add_argument("--file", required=True)
        item.add_argument("--project", required=True)
        if name == "native":
            item.add_argument("--binding", required=True)
            item.add_argument("--host", choices=sorted(HOSTS))
            item.add_argument("--output", required=True)
        else:
            item.add_argument("--arguments", required=True)
            item.add_argument("--image", required=True)
            item.add_argument("--job-dir", required=True)
            item.add_argument("--source-ref", required=True)
    args = parser.parse_args(argv)
    try:
        project = Path(args.project).resolve()
        document = core.read(boards._path(args.file, project))
        if args.command == "native":
            binding = core.read(boards._path(args.binding, project))
            result = prepare(document, binding, project, args.output, request_path=args.file,
                             binding_path=args.binding, host=args.host)
        else:
            actual = core.read(boards._path(args.arguments, project))
            result = record(document, actual, args.image, args.job_dir, project, source_ref=args.source_ref)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False), file=__import__("sys").stderr)
        return 2
