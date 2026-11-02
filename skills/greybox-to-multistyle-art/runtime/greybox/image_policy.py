"""Production image conditioning policy, separate from suppliers' raw API abilities.

Only canonical image operations create new geometry in this skill. References
must be local hash-bound inputs; URLs, provider upload tokens and task IDs cannot
stand in for the image bytes the user approved. Non-generation operations and
historical source/reuse records keep their existing semantics.
"""
from __future__ import annotations

from pathlib import Path
from .core import require, resolve_input, file_hash

IMAGE_OPERATIONS = {"image_to_3d", "multiview_to_3d"}
PROCESS_OPERATIONS = {"remesh", "articulate", "rig", "retarget", "material_transfer", "export",
                      "texture_refine", "texture", "animation", "rig_check"}
TEXT_OPERATIONS = {"text_to_3d", "text-to-3d", "text_to_model", "text-to-model", "text_preview"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def _record(reference, records, base):
    if type(reference) is int:
        require(0 <= reference < len(records), "Image conditioning input index is outside the approved records")
        return records[reference]
    require(isinstance(reference, str) and reference and not reference.startswith(("https://", "http://", "data:")),
            "Production generation needs a bound local image, not an unverified URL/token")
    path = resolve_input(reference, base or Path.cwd())
    matches = [row for row in records if resolve_input(row.get("path", ""), base or Path.cwd()) == path]
    require(len(matches) == 1, "Every conditioning image must resolve to exactly one approved input record")
    return matches[0]


def image_inputs(operation, base=None, check_files=True):
    """Return ordered local image records actually consumed by a production call.

    Lux keeps its actual image_to_3d operation for both img and imgs. Its local
    image_path(s) are translated to a content-bound upload immediately before
    submission. Raw generic provider API calls remain outside this policy.
    """
    name = operation.get("operation")
    require(name not in TEXT_OPERATIONS, "This skill requires approved image-to-3D; text-to-3D production is prohibited")
    require(name in IMAGE_OPERATIONS | PROCESS_OPERATIONS,
            "Unknown production operation: suppliers must map generation to canonical image operations or reviewed processing operations")
    if name not in IMAGE_OPERATIONS:
        return []
    parameters = operation.get("parameters", {})
    require(isinstance(parameters, dict), "Image-conditioned production parameters must be an object")
    records = operation.get("inputs", [])
    require(isinstance(records, list) and records, "Image-to-3D needs the approved hash-bound local image inputs")
    for row in records:
        require(isinstance(row, dict) and isinstance(row.get("path"), str), "Image inputs need local path/hash records")
    provider = operation.get("provider")
    forbidden = {"img", "imgs", "image_url", "image_urls", "input", "input_task_id", "input_from", "inputs"}
    require(not (set(parameters) & forbidden), "Production image conditioning cannot use remote URLs, upload tokens or opaque source tasks")
    require(not (set(parameters) & {"prompt", "text", "negative_prompt", "texture_prompt"}) or provider == "rodin",
            "Geometry text prompts cannot replace or redirect the approved image-conditioned production route")
    require("texture_prompt" not in parameters, "New generated assets must retain their approved image style; textual texture overrides require a revised image package")
    if provider == "meshy" and operation.get("model_version") not in {"meshy-6-lite", "meshy-t2", "meshy-t2.5"}:
        require(parameters.get("image_enhancement") is False,
                "Meshy production must explicitly disable image_enhancement to preserve the approved reference style")
    ordered = []
    if provider in {"rodin", "hitem3d"}:
        require(not (set(parameters) & {"image_path", "image_paths"}), "This supplier consumes its ordered top-level image inputs")
        ordered = list(records)
    elif "image_path" in parameters:
        require("image_paths" not in parameters, "Choose a single image or ordered multiple views")
        ordered = [_record(parameters["image_path"], records, base)]
    elif "image_paths" in parameters:
        refs = parameters["image_paths"]
        require(isinstance(refs, list) and refs, "Multiview needs ordered local image references")
        if provider == "tripo":
            require(all(isinstance(row, dict) and len(row) == 1 for row in refs), "Tripo multiview needs named local views")
            views = [next(iter(row)) for row in refs]
            require(2 <= len(views) <= 4 and len(set(views)) == len(views) and "front" in views and
                    set(views) <= {"front", "left", "back", "right"}, "Tripo supports front plus 1–3 distinct named views")
            refs = [next(iter(row.values())) for row in refs]
        ordered = [_record(ref, records, base) for ref in refs]
    else:
        require(False, "Image-to-3D parameters must consume their bound image_path or image_paths")
    resolved = []
    for row in ordered:
        path = resolve_input(row["path"], base or Path.cwd())
        require(path.suffix.lower() in IMAGE_SUFFIXES, "Conditioning inputs must be PNG, JPEG or WebP images")
        expected = row.get("sha256")
        require(isinstance(expected, str) and len(expected) == 64 and all(c in "0123456789abcdef" for c in expected),
                "Image inputs require exact SHA-256 hashes")
        if check_files:
            require(path.is_file() and file_hash(path) == expected, "Approved conditioning image is missing or changed")
        resolved.append({"path": str(path), "sha256": expected})
    require(len({r["sha256"] for r in resolved}) == len(resolved), "Multiview requires distinct views, not repeated copies of one image")
    require(len({str(resolve_input(r["path"], base or Path.cwd())) for r in records}) == len(records), "Duplicate conditioning input records")
    require(len(resolved) == len(records), "No unused or hidden input images may accompany a generation call")
    count = len(resolved)
    if provider == "lux3d":
        require(name == "image_to_3d" and 1 <= count <= 32, "Lux uses image_to_3d with one image or 2–32 ordered views")
    elif provider == "rodin":
        require(name == "image_to_3d" and 1 <= count <= 5, "Rodin image_to_3d supports 1–5 ordered images")
        if count > 1:
            tier = parameters.get("tier", operation.get("model_version", ""))
            if str(tier).startswith("Gen-2.5"):
                labels = parameters.get("image_label")
                require(isinstance(labels, list) and len(labels) == count and len(set(labels)) == count and "?" not in labels,
                        "Rodin 2.5 multiview must label every distinct approved view explicitly")
            elif tier != "Gen-2":
                require(parameters.get("condition_mode") == "concat", "Rodin Gen1/1.5 multiview requires concat; fuse combines different objects")
    else:
        limit = 4 if provider in {"meshy", "tripo", "hitem3d"} else 32
        require(count == 1 if name == "image_to_3d" else 2 <= count <= limit,
                "Single-image and multiview operations must match the actual supplied view count")
    return resolved


def validate_operation(operation, base, provider=None):
    """Bind consumed upload bytes to the approved, reviewed modeling package."""
    images = image_inputs(operation, base)
    if operation.get("operation") not in IMAGE_OPERATIONS:
        return {"ok": True, "images": []}
    from . import modeling_refs
    reviewed = modeling_refs.validate_operation_reference(operation, base, provider=provider)
    expected = [{"path": str(resolve_input(row["path"], base)), "sha256": row["sha256"]} for row in reviewed["images"]]
    require(images == expected, "Submitted conditioning images/order differ from the reviewed modeling-reference package")
    require(reviewed["mode"] == ("single" if len(images) == 1 else "multiview"),
            "Submitted single/multiview mode differs from the approved modeling-reference package")
    if len(images) > 1:
        roles = [row["role"] for row in reviewed["images"]]
        parameters = operation["parameters"]
        if operation.get("provider") == "tripo":
            require([next(iter(row)) for row in parameters["image_paths"]] == roles,
                    "Tripo view labels differ from the reviewed image orientations")
        elif operation.get("provider") == "hitem3d":
            order = ["front", "back", "left", "right"]
            bits = parameters.get("multi_images_bit")
            require(isinstance(bits, str) and len(bits) == 4 and set(bits) <= {"0", "1"} and bits[0] == "1" and
                    [role for role, present in zip(order, bits) if present == "1"] == roles,
                    "Hi3D multiview bitmask/order differs from the reviewed image orientations")
        elif operation.get("provider") == "rodin" and str(parameters.get("tier", "")).startswith("Gen-2.5"):
            labels = {"front": "F", "back": "B", "left": "L", "right": "R", "top": "U", "bottom": "D",
                      "front_left": "FL", "front_right": "FR", "back_left": "BL", "back_right": "BR"}
            require(all(role in labels for role in roles) and parameters.get("image_label") == [labels[role] for role in roles],
                    "Rodin view labels differ from the reviewed image orientations")
    return dict(reviewed, images=images)
