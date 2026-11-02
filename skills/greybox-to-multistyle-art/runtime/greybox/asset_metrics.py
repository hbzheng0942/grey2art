"""Read-only stored GLB topology and payload metrics; no renderer or optimizer.

Large BIN chunks remain on disk. Counts describe the supplied file, not visible
quality, GPU allocation, draw calls, frame time or an accepted processing result.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import struct

from . import VERSION, characters
from .core import WorkflowError, ensure_directory, file_hash, require

UNSUPPORTED_EXTENSIONS = {
    "KHR_draco_mesh_compression", "EXT_meshopt_compression",
    "KHR_meshopt_compression", "EXT_mesh_gpu_instancing",
}
COMPONENT_BYTES = {5120: 1, 5121: 1, 5122: 2, 5123: 2, 5125: 4, 5126: 4}
TYPE_WIDTH = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4,
              "MAT2": 4, "MAT3": 9, "MAT4": 16}
INDEX_FORMAT = {5121: ("<B", 255), 5123: ("<H", 65535), 5125: ("<I", 4294967295)}


def _items(doc, key):
    value = doc.get(key, [])
    require(isinstance(value, list) and all(isinstance(row, dict) for row in value),
            "Invalid GLB " + key + " collection")
    return value


def _extension_check(value):
    """Reject known topology-changing/encoded representations, including fallback data."""
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            extensions = item.get("extensions", {})
            if isinstance(extensions, dict):
                require(not UNSUPPORTED_EXTENSIONS.intersection(extensions),
                        "Compressed geometry or GPU instancing metrics are unsupported")
            for key in ("extensionsUsed", "extensionsRequired"):
                declared = item.get(key, [])
                require(isinstance(declared, list) and all(isinstance(x, str) for x in declared),
                        "Invalid GLB extension declarations")
                require(not UNSUPPORTED_EXTENSIONS.intersection(declared),
                        "Compressed geometry or GPU instancing metrics are unsupported")
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)


def _binary_offset(path):
    # characters._container has already validated all chunk boundaries.
    with path.open("rb") as handle:
        handle.seek(12)
        while handle.tell() < path.stat().st_size:
            size, kind = struct.unpack("<I4s", handle.read(8))
            if kind == b"BIN\x00":
                return handle.tell()
            handle.seek(size, 1)
    return None


def _accessor(doc, index):
    accessor = characters._index(index, _items(doc, "accessors"), "metric accessor")
    require("sparse" not in accessor, "Sparse accessor metrics are unsupported")
    view = characters._index(accessor.get("bufferView"), _items(doc, "bufferViews"),
                             "metric bufferView")
    require(view.get("buffer") == 0, "Metrics require the embedded GLB buffer")
    width = COMPONENT_BYTES.get(accessor.get("componentType"), 0)
    elements = TYPE_WIDTH.get(accessor.get("type"), 0)
    require(width and elements, "Invalid metric accessor component/type")
    count, offset = accessor.get("count"), accessor.get("byteOffset", 0)
    stride = view.get("byteStride", width * elements)
    require(type(count) is int and count > 0 and type(offset) is int and offset >= 0
            and type(stride) is int and stride >= width * elements,
            "Invalid metric accessor count/offset/stride")
    require(offset % width == 0 and (view.get("byteOffset", 0) + offset) % width == 0
            and stride % width == 0, "Misaligned metric accessor")
    require(offset + (count - 1) * stride + width * elements <= view["byteLength"],
            "Metric accessor exceeds stored bufferView")
    return accessor, view


def _validate_indices(handle, binary_offset, doc, index, vertex_count):
    accessor, view = _accessor(doc, index)
    component = accessor.get("componentType")
    require(accessor.get("type") == "SCALAR" and component in INDEX_FORMAT
            and not accessor.get("normalized", False), "Invalid primitive index accessor")
    require("byteStride" not in view, "Strided primitive indices are not supported by glTF")
    fmt, restart = INDEX_FORMAT[component]
    width, remaining = COMPONENT_BYTES[component], accessor["count"]
    require(binary_offset is not None, "Index data is missing its embedded BIN chunk")
    handle.seek(binary_offset + view.get("byteOffset", 0) + accessor.get("byteOffset", 0))
    while remaining:
        amount = min(remaining, 65536 // width)
        data = handle.read(amount * width)
        require(len(data) == amount * width, "Truncated stored index data")
        for (value,) in struct.iter_unpack(fmt, data):
            require(value < vertex_count and value != restart,
                    "Primitive index exceeds POSITION range or uses a reserved restart index")
        remaining -= amount
    return accessor["count"]


def _triangle_count(mode, count):
    require(type(mode) is int and 0 <= mode <= 6, "Invalid primitive topology mode")
    if mode == 4:
        require(count >= 3 and count % 3 == 0, "Triangle topology needs a multiple of three elements")
        return count // 3
    if mode in (5, 6):
        require(count >= 3, "Triangle strip/fan needs at least three elements")
        return count - 2
    if mode == 1:
        require(count % 2 == 0, "Line topology needs paired elements")
    if mode in (2, 3):
        require(count >= 2, "Line loop/strip needs at least two elements")
    return 0


def _scene_metrics(doc, mesh_triangles):
    nodes, scenes = _items(doc, "nodes"), _items(doc, "scenes")
    children, parents = [], {}
    for number, node in enumerate(nodes):
        values = node.get("children", [])
        require(isinstance(values, list) and all(type(i) is int for i in values)
                and len(values) == len(set(values)), "Invalid or repeated child node")
        for child in values:
            characters._index(child, nodes, "child node")
            require(child not in parents, "GLB node has multiple parents")
            parents[child] = number
        if "mesh" in node:
            characters._index(node["mesh"], mesh_triangles, "node mesh")
        children.append(values)
    visited, active = set(), set()
    for number in range(len(nodes)):
        if number in visited:
            continue
        pending = [(number, False)]
        while pending:
            index, leaving = pending.pop()
            if leaving:
                active.remove(index)
                visited.add(index)
                continue
            require(index not in active, "GLB node graph contains a cycle")
            if index in visited:
                continue
            active.add(index)
            pending.append((index, True))
            pending.extend((child, False) for child in reversed(children[index]))
    if "scene" not in doc:
        return {"status": "unknown", "reason": "No default scene is declared",
                "index": None, "mesh_instances": None, "triangles": None}
    scene = characters._index(doc["scene"], scenes, "default scene")
    roots = scene.get("nodes", [])
    require(isinstance(roots, list) and all(type(i) is int for i in roots)
            and len(roots) == len(set(roots)), "Invalid or repeated default scene root")
    pending, seen, instances, triangles = list(roots), set(), 0, 0
    while pending:
        index = pending.pop()
        node = characters._index(index, nodes, "scene node")
        require(index not in seen, "Default scene repeats a node")
        seen.add(index)
        if "mesh" in node:
            instances += 1
            triangles += mesh_triangles[node["mesh"]]
        pending.extend(children[index])
    return {"status": "measured", "index": doc["scene"], "mesh_instances": instances,
            "triangles": triangles}


def _image_payloads(doc):
    ranges, data_bytes = [], 0
    images = _items(doc, "images")
    for image in images:
        uri = image.get("uri")
        if uri is not None:
            require("bufferView" not in image, "Image storage must select either URI or bufferView")
            require(isinstance(uri, str) and uri.startswith("data:") and "," in uri,
                    "External image metrics require a separate resource audit")
            header, payload = uri.split(",", 1)
            require(header.endswith(";base64") and payload and len(payload) % 4 == 0
                    and re.fullmatch(r"[A-Za-z0-9+/]*={0,2}", payload) is not None,
                    "Only valid base64 data-URI image payloads are supported")
            data_bytes += len(payload) // 4 * 3 - (len(payload) - len(payload.rstrip("=")))
        else:
            view = characters._index(image.get("bufferView"), _items(doc, "bufferViews"),
                                     "embedded image bufferView")
            require(view.get("buffer") == 0, "Image payload must use the embedded GLB buffer")
            start = view.get("byteOffset", 0)
            ranges.append((start, start + view["byteLength"]))
    stored, end = 0, -1
    for start, stop in sorted(ranges):
        stored += max(0, stop - max(start, end))
        end = max(end, stop)
    return {"image_definitions": len(images), "payload_bytes": stored + data_bytes,
            "buffer_view_payload_bytes": stored, "data_uri_payload_bytes": data_bytes,
            "basis": "Union of embedded image byte ranges plus each base64 image declaration; encoded image bytes, not decoded pixels or GPU memory"}


def inspect_asset(source):
    """Inspect a self-contained uncompressed GLB without loading its BIN payload."""
    path = Path(source).expanduser().resolve()
    structural = characters.inspect_glb(path)
    doc, binary_bytes = characters._container(path)
    _extension_check(doc)
    for accessor in _items(doc, "accessors"):
        require("sparse" not in accessor, "Sparse accessor metrics are unsupported")
    buffers = _items(doc, "buffers")
    require(len(buffers) <= 1 and all("uri" not in row for row in buffers),
            "Metrics require a single embedded GLB buffer; external/data-URI buffers are unsupported")
    if buffers:
        require(0 <= binary_bytes - buffers[0]["byteLength"] <= 3,
                "Embedded GLB buffer length does not match its BIN payload")
    meshes = _items(doc, "meshes")
    primitives, mesh_totals = [], []
    binary_offset = _binary_offset(path)
    with path.open("rb") as handle:
        for mi, mesh in enumerate(meshes):
            total = 0
            rows = mesh.get("primitives", [])
            require(isinstance(rows, list) and rows, "Mesh has no primitives")
            for pi, primitive in enumerate(rows):
                require(isinstance(primitive, dict), "Invalid mesh primitive")
                attrs = primitive.get("attributes", {})
                require(isinstance(attrs, dict) and "POSITION" in attrs,
                        "Measured primitives require stored POSITION data")
                position, _ = _accessor(doc, attrs["POSITION"])
                require(position.get("type") == "VEC3", "POSITION must use VEC3")
                vertex_count = position["count"]
                count = (_validate_indices(handle, binary_offset, doc, primitive["indices"], vertex_count)
                         if "indices" in primitive else vertex_count)
                mode = primitive.get("mode", 4)
                triangles = _triangle_count(mode, count)
                if "material" in primitive:
                    characters._index(primitive["material"], _items(doc, "materials"), "primitive material")
                primitives.append({"mesh": mi, "primitive": pi, "mode": mode,
                                   "indexed": "indices" in primitive, "position_vertices": vertex_count,
                                   "elements": count, "triangles": triangles})
                total += triangles
            mesh_totals.append(total)
    scene = _scene_metrics(doc, mesh_totals)
    images = _image_payloads(doc)
    require(file_hash(path) == structural["source"]["sha256"], "Source changed during asset measurement")
    return {"schema_version": 1, "kind": "asset-metrics", "tool_version": VERSION,
            "source": {"filename": path.name, "sha256": structural["source"]["sha256"],
                       "bytes": structural["source"]["bytes"]},
            "counts": {"nodes": len(_items(doc, "nodes")), "meshes": len(meshes),
                       "primitives": len(primitives), "materials": len(_items(doc, "materials")),
                       "textures": len(_items(doc, "textures")), "images": len(_items(doc, "images"))},
            "geometry": {"unique_mesh_triangles": sum(mesh_totals), "default_scene": scene,
                         "primitives": primitives},
            "embedded_images": images,
            "verification": {"visual": "unverified", "runtime_performance": "unverified",
                             "processing_qualification": "unverified"},
            "limits": ["Triangle topology includes degenerate triangles; vertex area and visual quality are not measured.",
                       "Unique mesh counts include unused meshes; default-scene counts include mesh node instances, irrespective of camera visibility.",
                       "No world dimensions are inferred from accessor-declared bounds.",
                       "No frame time, draw calls, GPU memory or target-device performance is measured."]}


def compare_assets(before, after):
    first, second = inspect_asset(before), inspect_asset(after)
    def difference(a, b):
        return b - a if a is not None and b is not None else None
    return {"schema_version": 1, "kind": "asset-metrics-comparison", "tool_version": VERSION,
            "before": first, "after": second,
            "delta_after_minus_before": {
                "file_bytes": second["source"]["bytes"] - first["source"]["bytes"],
                "unique_mesh_triangles": second["geometry"]["unique_mesh_triangles"] - first["geometry"]["unique_mesh_triangles"],
                "default_scene_triangles": difference(first["geometry"]["default_scene"]["triangles"], second["geometry"]["default_scene"]["triangles"]),
                "embedded_image_payload_bytes": second["embedded_images"]["payload_bytes"] - first["embedded_images"]["payload_bytes"]},
            "verification": {"same_asset_identity": "unverified", "visual": "unverified",
                             "runtime_performance": "unverified", "processing_qualification": "unverified"}}


def write_report(report, output):
    """Create a private new report; never replace an existing report or input."""
    path = Path(output).expanduser().absolute()
    ensure_directory(path.parent)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    identity = os.fstat(descriptor)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
    except BaseException:
        current = path.lstat()
        if (current.st_dev, current.st_ino) == (identity.st_dev, identity.st_ino):
            path.unlink()
        raise
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inspect", help="Measure one stored self-contained GLB")
    inspect.add_argument("--input", required=True)
    compare = commands.add_parser("compare", help="Compare stored metrics; does not qualify optimization")
    compare.add_argument("--before", required=True)
    compare.add_argument("--after", required=True)
    for command in (inspect, compare):
        command.add_argument("--output", help="Create a new JSON report; existing paths are never replaced")
    args = parser.parse_args(argv)
    try:
        result = inspect_asset(args.input) if args.command == "inspect" else compare_assets(args.before, args.after)
        if args.output:
            write_report(result, args.output)
    except OSError:
        print(json.dumps({"ok": False, "error": "File operation failed; inspect local paths, permissions and existing output reports."}))
        return 2
    except WorkflowError as error:
        print(json.dumps({"ok": False, "error": str(error)}))
        return 2
    except (ValueError, TypeError, KeyError, AttributeError, IndexError, struct.error):
        # Error details remain local; do not echo arbitrary source metadata or paths.
        print(json.dumps({"ok": False, "error": "Unsupported or invalid GLB metrics input; use a self-contained uncompressed GLB with valid stored accessors and indices."}))
        return 2
    print(json.dumps(result, ensure_ascii=True, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
