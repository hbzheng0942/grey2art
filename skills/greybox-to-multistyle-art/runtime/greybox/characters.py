"""Offline character evidence checks. No pose recognition, render or provider call.

Hashes establish freshness, not truthful visual review or provider acceptance.
Accessor bounds are declarations in mesh-local coordinates, not measured dimensions.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
import math
from pathlib import Path
import struct

from .core import file_hash, read, require

VIEWS = ("front", "side", "back", "three-quarter")
CHECKS = ("single-character", "limbs-separated", "accessories-clear")
STATUSES = ("pass", "fail", "unclear")


def _vector(value, size, label):
    require(isinstance(value, list) and len(value) == size and all(
        not isinstance(v, bool) and isinstance(v, (int, float)) and math.isfinite(v)
        for v in value), label + " must contain finite numbers")
    return value


def _index(value, items, label):
    require(type(value) is int and 0 <= value < len(items), "Invalid " + label + " index")
    return items[value]


def _container(path):
    """Read only JSON and chunk headers; never load or unpack a large BIN chunk."""
    length = path.stat().st_size
    with path.open("rb") as handle:
        header = handle.read(12)
        require(len(header) == 12, "Truncated GLB header")
        magic, version, declared = struct.unpack("<4sII", header)
        require(magic == b"glTF" and version == 2 and declared == length, "Invalid GLB 2 container")
        document, binary_bytes, first = None, 0, True
        while handle.tell() < length:
            chunk_header = handle.read(8)
            require(len(chunk_header) == 8, "Truncated GLB chunk")
            size, kind = struct.unpack("<I4s", chunk_header)
            require(size % 4 == 0 and handle.tell() + size <= length, "Invalid GLB chunk length")
            require(not first or kind == b"JSON", "First GLB chunk must be JSON")
            if kind == b"JSON":
                require(document is None, "Duplicate GLB JSON chunk")
                document = json.loads(handle.read(size))
            else:
                require(kind != b"BIN\x00" or binary_bytes == 0, "Duplicate GLB BIN chunk")
                if kind == b"BIN\x00":
                    binary_bytes = size
                handle.seek(size, 1)
            first = False
    require(isinstance(document, dict) and document.get("asset", {}).get("version") == "2.0", "Expected glTF 2.0 asset")
    return document, binary_bytes


def inspect_glb(path):
    """Return reproducible structural facts, without inferring anatomy or orientation."""
    path = Path(path).resolve()
    require(path.is_file() and path.suffix.lower() == ".glb", "Expected an existing GLB file")
    source = {"path": str(path), "sha256": file_hash(path), "bytes": path.stat().st_size}
    doc, binary_bytes = _container(path)
    nodes, meshes, accessors = (doc.get(k, []) for k in ("nodes", "meshes", "accessors"))
    resources, transforms, positions = [], [], []
    for view in doc.get("bufferViews", []):
        buffer = _index(view.get("buffer"), doc.get("buffers", []), "bufferView buffer")
        offset, length = view.get("byteOffset", 0), view.get("byteLength")
        require(type(offset) is int and type(length) is int and offset >= 0 and length > 0
                and offset + length <= buffer.get("byteLength", 0), "Invalid bufferView range")
    for accessor in accessors:
        count = accessor.get("count")
        require(type(count) is int and count >= 0, "Invalid accessor count")
        require("bufferView" in accessor or "sparse" in accessor, "Accessor has no stored data")
        if "bufferView" in accessor:
            view = _index(accessor["bufferView"], doc.get("bufferViews", []), "accessor bufferView")
            widths = {5120: 1, 5121: 1, 5122: 2, 5123: 2, 5125: 4, 5126: 4}
            components = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT2": 4, "MAT3": 9, "MAT4": 16}
            width = widths.get(accessor.get("componentType"), 0) * components.get(accessor.get("type"), 0)
            offset, stride = accessor.get("byteOffset", 0), view.get("byteStride", width)
            require(width > 0 and type(offset) is int and offset >= 0 and type(stride) is int and stride >= width
                    and offset + max(0, count - 1) * stride + (width if count else 0) <= view["byteLength"],
                    "Accessor exceeds stored bufferView")
    for kind in ("buffers", "images"):
        for i, item in enumerate(doc.get(kind, [])):
            uri = item.get("uri")
            storage = ("data-uri" if uri.startswith("data:") else "external") if uri else "bin"
            if kind == "buffers" and storage == "bin":
                require(type(item.get("byteLength")) is int and 0 <= item["byteLength"] <= binary_bytes,
                        "Buffer exceeds embedded BIN chunk")
            if kind == "images" and storage == "bin":
                _index(item.get("bufferView"), doc.get("bufferViews", []), "image bufferView")
            resources.append({"kind": kind, "index": i, "storage": storage,
                              "mime_type": item.get("mimeType"), "uri": uri if storage == "external" else None})
    primitives = joint_attributes = weight_attributes = vertices = 0
    for mi, mesh in enumerate(meshes):
        for pi, primitive in enumerate(mesh.get("primitives", [])):
            primitives += 1
            attrs = primitive.get("attributes", {})
            joint_attributes += int("JOINTS_0" in attrs)
            weight_attributes += int("WEIGHTS_0" in attrs)
            for index in attrs.values():
                _index(index, accessors, "attribute accessor")
            if "POSITION" not in attrs:
                continue
            accessor = accessors[attrs["POSITION"]]
            count = accessor.get("count")
            require(type(count) is int and count >= 0, "Invalid POSITION count")
            vertices += count
            bounds = None
            if "min" in accessor and "max" in accessor:
                low = _vector(accessor["min"], 3, "POSITION min")
                high = _vector(accessor["max"], 3, "POSITION max")
                require(all(a <= b for a, b in zip(low, high)), "Reversed POSITION bounds")
                bounds = {"min": low, "max": high}
            positions.append({"mesh": mi, "primitive": pi, "count": count, "declared_local_bounds": bounds})
    skins = doc.get("skins", [])
    for i, node in enumerate(nodes):
        for key, items in (("mesh", meshes), ("skin", skins)):
            if key in node:
                _index(node[key], items, key)
        transform = {key: _vector(node[key], size, "node " + key)
                     for key, size in (("translation", 3), ("rotation", 4), ("scale", 3), ("matrix", 16)) if key in node}
        transforms.append({"node": i, "name": node.get("name"), "mesh": node.get("mesh"),
                           "skin": node.get("skin"), "transform": transform,
                           "default_identity": not transform})
    joints = []
    for skin in skins:
        for joint in skin.get("joints", []):
            _index(joint, nodes, "joint node")
            joints.append(joint)
    animations = [{"index": i, "name": a.get("name"), "channels": len(a.get("channels", [])),
                   "samplers": len(a.get("samplers", []))} for i, a in enumerate(doc.get("animations", []))]
    require(file_hash(path) == source["sha256"], "Source changed during inspection")
    return {"schema_version": 1, "kind": "character-inspection", "source": source,
            "generator": doc["asset"].get("generator"), "embedded_bin_bytes": binary_bytes,
            "resources": resources, "all_resources_embedded": all(r["storage"] != "external" for r in resources),
            "counts": {"nodes": len(nodes), "meshes": len(meshes), "primitives": primitives,
                       "position_vertices": vertices, "skins": len(skins), "unique_joints": len(set(joints)),
                       "joint_attributes": joint_attributes, "weight_attributes": weight_attributes,
                       "animations": len(animations)},
            "node_transforms": transforms, "positions": positions, "animations": animations,
            "limits": ["No anatomy, category, pose, orientation or separation inference from JSON.",
                       "Bounds are accessor declarations; no vertex decoding or world-space measurement.",
                       "Skin and weight presence does not prove usable deformation or animation."]}


def _write_new(path, value):
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")


def write_inspection(source, output):
    result = inspect_glb(source)
    _write_new(output, result)
    return result


def make_template(inspection_path):
    """Produce blanks only; the caller must actually view the model and fill observations."""
    path = Path(inspection_path).resolve()
    report = read(path)
    require(report.get("kind") == "character-inspection", "Expected character inspection report")
    return {"schema_version": 1, "kind": "character-preflight", "source": report["source"],
            "inspection": {"path": str(path), "sha256": file_hash(path)}, "reviewer": "",
            "category": "unknown", "use": "unknown",
            "pose": {"label": "unknown", "status": "unclear", "observation": ""},
            "views": [{"view": view, "path": "", "sha256": ""} for view in VIEWS],
            "checks": [{"id": key, "status": "unclear", "observation": "", "views": []} for key in CHECKS]}


def _evidence(record, base, label):
    require(isinstance(record, dict) and isinstance(record.get("path"), str) and record["path"].strip(), label + " path required")
    path = (base / record["path"]).resolve()
    require(path.is_file(), label + " file missing")
    require(file_hash(path) == record.get("sha256"), label + " hash changed or missing")
    return path


def validate_preflight(receipt, source_path=None, provider=None):
    """Validate fresh evidence and explicit review. Returns errors; never authorizes spend.

    A receipt path resolves relative evidence paths beside itself; dict paths use cwd.
    Provider-specific checks (including Tripo rig_check) remain executor obligations.
    """
    result = {"ok": False, "errors": [], "coverage": "Evidence integrity and recorded review only; no provider or animation acceptance."}
    try:
        base = Path.cwd()
        if isinstance(receipt, (str, Path)):
            path = Path(receipt).resolve()
            base, receipt = path.parent, read(path)
        require(isinstance(receipt, dict) and receipt.get("schema_version") == 1 and receipt.get("kind") == "character-preflight",
                "Expected character-preflight schema_version 1")
        source = receipt["source"]
        actual_path = Path(source_path).resolve() if source_path is not None else _evidence(source, base, "source")
        actual = inspect_glb(actual_path)
        require(all(actual["source"][k] == source.get(k) for k in ("sha256", "bytes")), "Source GLB hash/bytes differ")
        report = read(_evidence(receipt["inspection"], base, "inspection"))
        expected = deepcopy(actual)
        expected["source"]["path"] = report.get("source", {}).get("path")
        require(report == expected, "Inspection contents differ from actual GLB")
        require(actual["all_resources_embedded"], "External GLB resources are not hash-bound; embed before preflight")
        require(actual["counts"]["position_vertices"] > 0, "GLB has no declared POSITION geometry")
        category, use = receipt.get("category"), receipt.get("use")
        result.update(source_sha256=source["sha256"], category=category, use=use, provider=provider)
        require(category in ("humanoid", "quadruped", "other"), "Explicit reviewed category required")
        require(use in ("static", "reuse-rig", "rig"), "Explicit static/reuse-rig/rig use required")
        require(isinstance(receipt.get("reviewer"), str) and receipt["reviewer"].strip(), "Reviewer identity required")
        views, hashes = set(), set()
        require(isinstance(receipt.get("views"), list), "Views must be a list")
        for view in receipt["views"]:
            name = view.get("view")
            require(name in VIEWS and name not in views, "Invalid or duplicate view name")
            path = _evidence(view, base, "view " + name)
            with path.open("rb") as handle:
                header = handle.read(32)
            require(header.startswith(b"\x89PNG\r\n\x1a\n") or header.startswith(b"\xff\xd8\xff") or
                    (header.startswith(b"RIFF") and header[8:12] == b"WEBP"), "View must be a PNG, JPEG or WebP image")
            require(view["sha256"] not in hashes, "Distinct views cannot reuse the same image hash")
            views.add(name)
            hashes.add(view["sha256"])
        require(views == set(VIEWS), "Actual front, side, back and three-quarter views required")
        pose = receipt.get("pose", {})
        require(pose.get("status") in STATUSES and isinstance(pose.get("label"), str) and pose["label"].strip()
                and isinstance(pose.get("observation"), str) and pose["observation"].strip(), "Pose needs status, label and observation")
        seen = set()
        for check in receipt.get("checks", []):
            key = check.get("id")
            require(key in CHECKS and key not in seen, "Invalid or duplicate review check")
            require(check.get("status") in STATUSES and isinstance(check.get("observation"), str)
                    and check["observation"].strip(), "Check needs pass/fail/unclear and observation: " + key)
            refs = check.get("views")
            require(isinstance(refs, list) and refs and all(v in views for v in refs), "Check must reference actual views: " + key)
            require(use != "rig" or check["status"] == "pass", "Rig review is not pass: " + key)
            seen.add(key)
        require(seen == set(CHECKS), "Missing required review checks")
        if use == "rig":
            require(pose["status"] == "pass" and pose["label"] != "unknown", "Rig pose review must pass")
            require(isinstance(provider, str) and provider.strip(), "Explicit rig provider required")
            require(provider not in ("lux3d", "lux", "meshy") or category == "humanoid", "Lux/Meshy rig route requires humanoid")
        if use == "reuse-rig":
            counts = actual["counts"]
            require(all(counts[k] > 0 for k in ("skins", "unique_joints", "joint_attributes", "weight_attributes"))
                    and any(n["skin"] is not None for n in actual["node_transforms"]), "Reuse-rig requires an existing skin, joints and weights")
        result["ok"] = True
    except (ValueError, OSError, TypeError, KeyError, IndexError, AttributeError, struct.error) as exc:
        result["errors"].append(str(exc))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inspect", help="Write structural facts from an actual GLB")
    inspect.add_argument("--file", required=True)
    inspect.add_argument("--output", required=True, help="New JSON report path")
    template = commands.add_parser("template", help="Write an unreviewed receipt with unclear checks")
    template.add_argument("--inspection", required=True)
    template.add_argument("--output", required=True)
    validate = commands.add_parser("validate", help="Verify existing review evidence without calls or writes")
    validate.add_argument("--receipt", required=True)
    validate.add_argument("--file")
    validate.add_argument("--provider", choices=("lux3d", "lux", "meshy", "tripo"))
    args = parser.parse_args(argv)
    try:
        if args.command == "inspect":
            result = write_inspection(args.file, args.output)
        elif args.command == "template":
            result = make_template(args.inspection)
            _write_new(args.output, result)
        else:
            result = validate_preflight(args.receipt, args.file, args.provider)
        print(json.dumps(result, ensure_ascii=True, indent=2, allow_nan=False))
        return 0 if result.get("ok", True) else 1
    except (ValueError, OSError, TypeError, KeyError, AttributeError, struct.error) as exc:
        print(json.dumps({"ok": False, "errors": [str(exc)]}, ensure_ascii=True))
        return 1
