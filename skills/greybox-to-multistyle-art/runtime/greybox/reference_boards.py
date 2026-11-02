"""Offline reference-board planning and immutable, replay-verified crops.

One actual board generation receipt is shared by its crops. This module neither
calls image services nor substitutes pixel checks for per-asset visual review.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
from pathlib import Path
import re
from string import Template
import sys

from . import core

MAX_BOARD_PIXELS = 32_000_000
MAX_CROP_PIXELS = 8_388_608
ROLES = {"front", "back", "left", "right", "three_quarter", "top", "bottom"}


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _hash(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _path(value, project):
    core.require(isinstance(value, str) and value.strip(), "A project-contained path is required")
    path = core.resolve_input(value, project)
    core.require(core.inside(path, project), "Reference-board path escapes project")
    return path


def _file(ref, project, dependencies):
    core.require(isinstance(ref, dict) and _hash(ref.get("sha256")), "Reference-board input needs path and SHA256")
    path = _path(ref.get("path"), project)
    core.require(path.is_file(), "Reference-board input file is missing")
    raw = path.read_bytes()
    core.require(_sha(raw) == ref["sha256"], "Reference-board input changed or hash is wrong; affected crops need review")
    dependencies[str(path)] = {"path": str(path), "sha256": ref["sha256"]}
    return path, raw


def _pillow():
    try:
        from PIL import Image, ImageOps, __version__
    except ImportError as error:
        raise core.WorkflowError("Reference-board preparation/crop/replay needs optional Pillow; install Pillow in the selected Python environment. Planning uses stdlib only.") from error
    return Image, ImageOps, __version__


def _board(raw):
    Image, ImageOps, version = _pillow()
    core.require(len(raw) <= 64 * 1024 * 1024, "Reference board exceeds 64MiB")
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        core.require(raw.endswith(b"\x00\x00\x00\x00IEND\xaeB`\x82"), "Reference board PNG is truncated or has trailing data")
    try:
        with Image.open(io.BytesIO(raw)) as check:
            core.require(check.width * check.height <= MAX_BOARD_PIXELS, "Reference board exceeds safe pixel limit")
            check.verify()
        with Image.open(io.BytesIO(raw)) as source:
            core.require(source.width * source.height <= MAX_BOARD_PIXELS, "Reference board exceeds safe pixel limit")
            core.require(getattr(source, "n_frames", 1) == 1, "Reference board must be a single still image")
            original = list(source.size)
            orientation = source.getexif().get(274, 1)
            source.load()  # fail on truncated payloads; never enable LOAD_TRUNCATED_IMAGES
            oriented = ImageOps.exif_transpose(source).convert("RGBA")
            core.require(oriented.getchannel("A").getextrema() == (255, 255), "Reference board needs opaque white background, not transparent pixels")
            return oriented.convert("RGB"), {"original_size": original, "oriented_size": list(oriented.size),
                                            "exif_orientation": orientation}, version
    except (OSError, SyntaxError) as error:
        raise core.WorkflowError("Reference board cannot be decoded completely") from error


def _generation(ref, board_ref, concept, project, dependencies):
    _, raw = _file(ref, project, dependencies)
    receipt = json.loads(raw)
    core.require(isinstance(receipt, dict), "Board invocation receipt must be an object")
    inputs = receipt.get("actual_input_image_sha256")
    core.require(receipt.get("schema") == 1 and receipt.get("kind") == "reference-image-generation-receipt"
                 and receipt.get("output_sha256") == board_ref["sha256"]
                 and receipt.get("invocation_recorded") is True
                 and isinstance(receipt.get("source_ref"), str) and receipt["source_ref"].strip()
                 and isinstance(receipt.get("tool"), str) and receipt["tool"].strip()
                 and isinstance(inputs, list) and inputs and all(_hash(x) for x in inputs)
                 and concept in inputs,
                 "Board needs its one actual style-conditioned invocation receipt and exact output hash")
    return receipt


def _identity(row):
    core.require(isinstance(row, dict) and core.safe_id(row.get("asset_id")) and core.safe_id(row.get("view_id")),
                 "Each board slot/crop needs stable asset_id and view_id")
    core.require(row.get("role") in ROLES, "Each board view needs an explicit orientation")
    return row["asset_id"], row["view_id"]


def _requirements(row):
    long_edge = row.get("min_subject_long_edge_px", 512)
    short_edge = row.get("min_subject_short_edge_px", 128)
    core.require(type(long_edge) is int and type(short_edge) is int and long_edge >= short_edge > 0,
                 "Subject pixel requirements must be positive integers, long >= short")
    fraction, minimum = row.get("critical_feature_fraction_of_short_edge"), row.get("min_feature_px")
    core.require((fraction is None) == (minimum is None), "Critical feature fraction and pixel minimum must be supplied together")
    if fraction is not None:
        core.require(type(fraction) in (int, float) and math.isfinite(fraction) and 0 < fraction <= 1
                     and type(minimum) is int and minimum > 0, "Invalid critical-feature pixel requirement")
    return {"min_subject_long_edge_px": long_edge, "min_subject_short_edge_px": short_edge,
            **({"critical_feature_fraction_of_short_edge": fraction, "min_feature_px": minimum} if fraction is not None else {})}


def _projected_aspect(row):
    """Use evidenced width/height when supplied; retain legacy ratio-only inputs."""
    dimensions = row.get("projected_dimensions")
    aspect = row.get("projected_aspect")
    if dimensions is not None:
        core.require(isinstance(dimensions, dict), "projected_dimensions must contain width, height and source_ref")
        width, height = dimensions.get("width"), dimensions.get("height")
        core.require(all(type(value) in (int, float) and math.isfinite(value) and value > 0
                         for value in (width, height)), "Projected width and height must be positive finite numbers")
        core.require(isinstance(dimensions.get("source_ref"), str) and dimensions["source_ref"].strip(),
                     "Projected dimensions need their actual source_ref")
        derived = width / height
        core.require(math.isfinite(derived) and derived > 0, "Projected width/height ratio must be finite and positive")
        if aspect is not None:
            core.require(type(aspect) in (int, float) and math.isfinite(aspect) and aspect > 0,
                         "projected_aspect must be positive width/height")
            core.require(math.isclose(aspect, derived, rel_tol=.01, abs_tol=1e-9),
                         "projected_aspect contradicts projected width/height (1% rounding tolerance)")
        return derived
    core.require(type(aspect) in (int, float) and math.isfinite(aspect) and aspect > 0,
                 "projected_aspect must be positive width/height, or supply evidenced projected_dimensions")
    return aspect


def _layout_candidates(row, aspect):
    if row.get("requires_single", False):
        return [("single", 1, 1)]
    if aspect >= 2.5:
        return [("horizontal_strips", 1, n) for n in (4, 3, 2)] + [("single", 1, 1)]
    if aspect <= .4:
        return [("vertical_columns", n, 1) for n in (4, 3, 2)] + [("single", 1, 1)]
    return (([("grid", 3, 3)] if row.get("simple_shape_validated") is True else [])
            + [("grid", 2, 2), ("vertical_columns", 2, 1), ("horizontal_strips", 1, 2), ("single", 1, 1)])


def _passes(width, height, requirements):
    longer, shorter = max(width, height), min(width, height)
    return (longer >= requirements["min_subject_long_edge_px"] and shorter >= requirements["min_subject_short_edge_px"]
            and shorter * requirements.get("critical_feature_fraction_of_short_edge", 1) >= requirements.get("min_feature_px", 0))


def _estimate(size, aspect, columns, lines, fill_ratio=.8):
    """Reserve native subject margin and legal master padding without upscaling."""
    cw, ch = size[0] // columns, size[1] // lines
    pw = min(cw * fill_ratio, ch * fill_ratio * aspect)
    ph = pw / aspect
    border = 50
    if (pw + border) * (ph + border) > MAX_CROP_PIXELS:
        factor = (-border * (pw + ph) + math.sqrt(border ** 2 * (pw - ph) ** 2
                  + 4 * pw * ph * MAX_CROP_PIXELS)) / (2 * pw * ph)
        pw, ph = pw * factor, ph * factor
    return math.floor(pw), math.floor(ph)


def plan(spec):
    """Choose controlled templates using declared projection/quality and real channel size."""
    core.require(isinstance(spec, dict) and spec.get("schema") == 1 and spec.get("kind") == "reference-board-plan-input", "Expected reference-board-plan-input schema 1")
    size = spec.get("channel_size")
    core.require(isinstance(size, list) and len(size) == 2 and all(type(x) is int and x >= 256 for x in size)
                 and size[0] * size[1] <= MAX_BOARD_PIXELS, "Declare actual supported channel_size within safe pixel limit")
    core.require(isinstance(spec.get("size_source_ref"), str) and spec["size_source_ref"].strip(), "Record observed output or documented channel size source; never assume arbitrary 4K support")
    rows = spec.get("views")
    core.require(isinstance(rows, list) and rows, "Reference-board plan requires actual asset views")
    fill_ratio = spec.get("subject_fill_ratio", .8)
    core.require(type(fill_ratio) in (int, float) and math.isfinite(fill_ratio) and .3 <= fill_ratio <= .9,
                 "subject_fill_ratio must be a finite estimate in 0.3..0.9, never an output guarantee")
    coherent = spec.get("coherent_asset_groups", False)
    core.require(type(coherent) is bool, "coherent_asset_groups must be boolean")
    groups, group_layouts, group_pages = {}, {}, {}
    if coherent:
        for row in rows:
            groups.setdefault(_identity(row)[0], []).append(row)
        rows = [row for group in groups.values() for row in group]
        for asset, group in groups.items():
            if len(group) < 2:
                continue
            common = None
            for view in group:
                aspect = _projected_aspect(view)
                requirements = _requirements(view)
                fits = {(template, columns, lines) for template, columns, lines in _layout_candidates(view, aspect)
                        if columns * lines >= len(group)
                        and _passes(*_estimate(size, aspect, columns, lines, fill_ratio), requirements)}
                common = fits if common is None else common & fits
            if common:
                group_layouts[asset] = common
    boards, unavailable, seen, diagnostics = [], [], set(), []
    for row in rows:
        identity = _identity(row)
        core.require(identity not in seen, "Duplicate board asset/view identity")
        seen.add(identity)
        aspect = _projected_aspect(row)
        requirements = _requirements(row)
        candidates = _layout_candidates(row, aspect)
        choice, estimates, feasible = None, [], {}
        if not row.get("requires_single", False) and .4 < aspect < 2.5 and row.get("simple_shape_validated") is not True:
            estimates.append({"template": "grid", "grid": [3, 3], "eligible": False,
                              "reason": "simple_shape_validated is not true; no nine-object qualification is inferred"})
        for template, columns, lines in candidates:
            pw, ph = _estimate(size, aspect, columns, lines, fill_ratio)
            failures = []
            if max(pw, ph) < requirements["min_subject_long_edge_px"]: failures.append("subject_long_edge")
            if min(pw, ph) < requirements["min_subject_short_edge_px"]: failures.append("subject_short_edge")
            if min(pw, ph) * requirements.get("critical_feature_fraction_of_short_edge", 1) < requirements.get("min_feature_px", 0): failures.append("critical_feature")
            if identity[0] in group_layouts and (template, columns, lines) not in group_layouts[identity[0]]:
                failures.append("coherent_asset_group")
            estimates.append({"template": template, "grid": [columns, lines], "eligible": True,
                              "estimated_subject_size": [pw, ph], "passes": not failures, "failures": failures})
            if not failures:
                feasible[(template, columns, lines)] = template, columns, lines, pw, ph
                if choice is None:
                    choice = feasible[(template, columns, lines)]
        # Fill the earliest compatible page without waiting for later assets or
        # weakening this view's requirements to make it fit a preferred grid.
        group = identity[0] in group_layouts
        needed = len(groups[identity[0]]) if group else 1
        board = group_pages.get(identity[0]) if group else None
        if board is None:
            board = next((candidate for candidate in boards
                          if (candidate["template"], *candidate["grid"]) in feasible
                          and len(candidate["slots"]) + needed <= math.prod(candidate["grid"])), None)
        if board is not None:
            choice = feasible[(board["template"], *board["grid"])]
        diagnostic = {"asset_id": identity[0], "view_id": identity[1], "requirements": requirements,
                      "projected_aspect": aspect, "candidates": estimates,
                      "selected": list(choice[1:3]) if choice else None}
        if row.get("projected_dimensions") is not None:
            diagnostic["projection_source_ref"] = row["projected_dimensions"]["source_ref"]
        if choice and choice[0] == "single":
            diagnostic["reason"] = "requires_single was explicitly requested" if row.get("requires_single") else "Packed layouts do not meet the declared subject/detail pixels; check their task basis before authorizing a batch"
        diagnostics.append(diagnostic)
        if choice is None:
            unavailable.append({"asset_id": identity[0], "view_id": identity[1], "requirements": requirements,
                                "reason": "No layout meets subject/detail pixels within the channel and modeling-master pixel limits (including white boundary/padding). Use a compatible supported reference route, coherent views, or an approved modular decomposition; upscaling is not detail."})
            continue
        template, columns, lines, pw, ph = choice
        if board is None:
            board = {"id": f"board-{len(boards)+1:03d}", "template": template, "grid": [columns, lines], "canvas_size": size, "slots": []}
            boards.append(board)
        if group:
            group_pages[identity[0]] = board
        index = len(board["slots"])
        x, y = index % columns, index // columns
        board["slots"].append({"asset_id": identity[0], "view_id": identity[1], "role": row["role"],
                               "planned_region": [x * size[0] // columns, y * size[1] // lines, (x+1) * size[0] // columns, (y+1) * size[1] // lines],
                               "estimated_subject_size": [pw, ph], "recommended_padding": 24,
                               "max_master_pixels": MAX_CROP_PIXELS, "requirements": requirements})
    return {"schema": 1, "kind": "reference-board-layout", "input_digest": core.digest(spec), "channel_size": size,
            "size_source_ref": spec["size_source_ref"], "subject_fill_ratio": fill_ratio,
            "coherent_asset_groups": coherent, "boards": boards, "unresolved": unavailable,
            "diagnostics": diagnostics,
            "summary": {"view_count": len(rows), "ready_view_count": sum(len(b["slots"]) for b in boards),
                        "unresolved_view_count": len(unavailable), "estimated_generation_calls": len(boards),
                        "single_boards": sum(b["template"] == "single" for b in boards),
                        "packed_boards": sum(b["template"] != "single" for b in boards)},
            "boundary": "Geometric estimates only. Observe the returned image, record actual EXIF-oriented ROIs, inspect critical features and perform per-view visual review. Layout is not generation authority."}


def _json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()


def _description(row, planned):
    """Normalize semantic inputs without guessing identity, pose or construction."""
    core.require(isinstance(row, dict), "Board objects must be structured objects")
    result = dict(row)
    result.setdefault("role", planned["role"])
    core.require(_identity(result) == _identity(planned) and result["role"] == planned["role"],
                 "Board object identity/orientation differs from its planned view")
    contract = result.get("modeling_contract", {})
    core.require(isinstance(contract, dict), "modeling_contract must be an object")
    for key in ("category", "structure"):
        if key not in result and key in contract:
            result[key] = contract[key]
    core.require(result.get("category") in {"humanoid", "animal", "prop", "architecture", "vegetation", "mechanism"},
                 "Every board object needs its actual modeling category")
    for key in ("function", "appearance", "structure"):
        core.require(isinstance(result.get(key), str) and result[key].strip(),
                     f"Every board object needs a concrete {key}")
        core.require(not _placeholder(result[key]), f"Board {key} is a placeholder; provide the actual object design")
    if isinstance(contract.get("structure"), str):
        core.require(not _placeholder(contract["structure"]), "Board modeling_contract structure is a placeholder")
    core.require(not contract.get("category") or contract["category"] == result["category"],
                 "Object category contradicts modeling_contract")
    if result["category"] == "animal":
        core.require(isinstance(result.get("species"), str) and result["species"].strip(),
                     "Animal board objects need an explicit species, not only a family ID")
    use = contract.get("use", result.get("use"))
    core.require(use is None or use in {"static", "rigid_motion", "skeletal_animation"}, "Unsupported modeling use")
    if use == "skeletal_animation":
        pose = contract.get("pose", result.get("pose"))
        details = contract.get("pose_details", result.get("pose_details"))
        if result["category"] in {"humanoid", "animal"}:
            allowed = {"A", "T"} if result["category"] == "humanoid" else {"natural_stance"}
            core.require(pose in allowed and isinstance(details, str) and details.strip(),
                         "Skeletal board references need an anatomy-appropriate explicit pose and pose_details")
        else:
            deformation = contract.get("deformation_plan", result.get("deformation_plan"))
            core.require(isinstance(deformation, str) and deformation.strip(), "Other skeletal assets need a deformation_plan")
    return result


def _placeholder(value):
    """Reject explicit unfinished fields, not prose that discusses placeholders."""
    return value.strip() in {"占位", "待补", "待填写"} or bool(re.fullmatch(
        r"\s*[\[(<]?(?:placeholder|todo|tbd)[\])>]?(?:\s*[:：-]\s*.*)?[.!。]?\s*", value, re.I | re.S))


def _identity_master_review(role, image, project, dependencies):
    """Check an optional recorded review, without authenticating visual judgment."""
    if "source_review" not in role:
        return
    _, raw = _file(role["source_review"], project, dependencies)
    review = json.loads(raw)
    core.require(isinstance(review, dict) and review.get("image_sha256") == image["sha256"]
                 and review.get("asset_id") == role["asset_id"] and review.get("view_id") == role["source_view_id"],
                 "Identity master source review must bind its exact image, asset and actual source view")
    verdicts = [review[key] for key in ("status", "verdict") if key in review]
    core.require(verdicts and all(verdict == "pass" for verdict in verdicts),
                 "Identity master source review must pass; fail/unclear sources cannot become production masters")
    core.require(all(isinstance(review.get(key), str) and review[key].strip() for key in ("observation", "source_ref")),
                 "Identity master source review needs its visible observation and actual inspection source_ref")
    if "board_crop_receipt" in review:
        checked = validate_crop_receipt(review["board_crop_receipt"], project,
                                        asset_id=role["asset_id"], view_id=role["source_view_id"])
        core.require(checked["output"]["sha256"] == image["sha256"],
                     "Identity master crop receipt must bind this exact source image")
        for dependency in checked["dependencies"]:
            dependencies[str(_path(dependency["path"], project))] = dependency


def _deduplicate(plan_spec, descriptions):
    """Only explicit identical reusable designs share a generated view."""
    source_seen, rows, aliases, conflicts = {}, [], [], []
    for row in plan_spec["views"]:
        identity = _identity(row)
        description = descriptions[identity]
        source = row.get("model_source", description.get("model_source"))
        core.require(source is None or isinstance(source, str) and source.strip(), "model_source must be an explicit nonempty model identity")
        core.require(not (row.get("model_source") and description.get("model_source")) or row["model_source"] == description["model_source"],
                     "Planned and described model_source identities differ")
        if source is not None:
            key = source, row["view_id"], row["role"]
            signature = core.digest({"view": {k: v for k, v in row.items() if k not in {"asset_id", "model_source"}},
                                     "design": {k: v for k, v in description.items() if k not in {"asset_id", "model_source"}}})
            existing = source_seen.get(key, [])
            match = next((previous for previous_signature, previous in existing if previous_signature == signature), None)
            if match:
                aliases.append({"asset_id": row["asset_id"], "view_id": row["view_id"],
                                "source_asset_id": match["asset_id"], "source_view_id": match["view_id"], "model_source": source})
                continue
            if existing:
                conflicts.append({"asset_id": row["asset_id"], "view_id": row["view_id"], "model_source": source,
                                  "reason": "Shared model_source has different design, view or quality declarations; kept separate"})
            source_seen.setdefault(key, []).append((signature, row))
        rows.append(row)
    return dict(plan_spec, views=rows), aliases, conflicts


def _compact_board(source, slots, rows, board_id):
    """Compact an actual chunk only where every unchanged requirement still fits."""
    count = len(slots)
    if count == 1:
        candidates = [("single", 1, 1)]
    elif count == 2:
        candidates = [("vertical_columns", 2, 1), ("horizontal_strips", 1, 2), ("grid", 2, 2)]
    elif source["template"] == "horizontal_strips":
        candidates = [("horizontal_strips", 1, count)]
    elif source["template"] == "vertical_columns":
        candidates = [("vertical_columns", count, 1)]
    else:
        columns = lines = 2 if count <= 4 else 3
        candidates = [("grid", columns, lines)]
    size = source["canvas_size"]
    feasible = []
    for candidate in candidates:
        estimates = [_estimate(size, _projected_aspect(rows[_identity(slot)]), *candidate[1:]) for slot in slots]
        if all(_passes(*estimate, slot["requirements"]) for slot, estimate in zip(slots, estimates)):
            feasible.append((sum(width * height for width, height in estimates), candidate, estimates))
    core.require(feasible, "Reference-budget re-planning cannot reduce declared subject/detail pixels")
    # Stable ties keep the deterministic candidate order; larger usable subject
    # area selects columns for tall/round pairs and strips for wide pairs.
    _, (template, columns, lines), estimates = max(feasible, key=lambda item: item[0])
    result = {"id": board_id, "template": template, "grid": [columns, lines], "canvas_size": size, "slots": []}
    for index, (slot, (pw, ph)) in enumerate(zip(slots, estimates)):
        x, y = index % columns, index // columns
        result["slots"].append(dict(slot, planned_region=[x * size[0] // columns, y * size[1] // lines,
                                                        (x + 1) * size[0] // columns, (y + 1) * size[1] // lines],
                                    estimated_subject_size=[pw, ph]))
    return result


def _reference_budget_layout(layout, rows, aliases, roles, maximum, guide_enabled):
    """Keep global style and page-specific masters; split before dropping any input."""
    style_indexes = {i for i, role in enumerate(roles) if role["role"] == "style"}
    core.require(len(style_indexes) + int(guide_enabled) <= maximum,
                 "Reference capacity exceeded even before one object's masters; preserve style inputs, explicitly choose layout_guide:false or use a capable channel")
    canonical = {_identity(row): _identity(row) for row in rows.values()}
    canonical.update({(alias["asset_id"], alias["view_id"]): (alias["source_asset_id"], alias["source_view_id"]) for alias in aliases})
    masters = {}
    for index, role in enumerate(roles):
        if role["role"] == "design_master":
            identity = canonical[(role["asset_id"], role["view_id"])]
            masters.setdefault(identity, set()).add(index)
        elif role["role"] == "identity_master":
            for view_id in role["target_view_ids"]:
                identity = canonical[(role["asset_id"], view_id)]
                masters.setdefault(identity, set()).add(index)
    boards, page_indexes, adjustments = [], {}, []
    diagnostics = {(row["asset_id"], row["view_id"]): row for row in layout["diagnostics"]}
    for source in layout["boards"]:
        chunks, current, current_indexes, rejected = [], [], set(style_indexes), []
        for slot in source["slots"]:
            identity = _identity(slot)
            required = style_indexes | masters.get(identity, set())
            reason = None
            if not required:
                reason = "This view has no approved style or bound design-master image; a layout guide cannot supply appearance"
            elif len(required) + int(guide_enabled) > maximum:
                reason = "This view's required style/master images plus layout guide exceed the actual reference capacity; preserve them and select an explicit compatible input route"
            if reason:
                layout["unresolved"].append({"asset_id": identity[0], "view_id": identity[1], "requirements": slot["requirements"],
                                             "reason": reason, "required_references": len(required) + int(guide_enabled), "max_references": maximum})
                rejected.append(identity)
                diagnostics[identity]["planned_selection"] = diagnostics[identity]["selected"]
                diagnostics[identity]["selected"] = None
                diagnostics[identity]["reference_capacity_reason"] = reason
                continue
            if current and len(current_indexes | required) + int(guide_enabled) > maximum:
                chunks.append((current, sorted(current_indexes)))
                current, current_indexes = [], set(style_indexes)
            current.append(slot)
            current_indexes |= required
        if current:
            chunks.append((current, sorted(current_indexes)))
        new_ids = []
        split = len(chunks) > 1 or bool(rejected)
        for slots, indexes in chunks:
            board_id = f"board-{len(boards) + 1:03d}"
            board = _compact_board(source, slots, rows, board_id)
            boards.append(board)
            new_ids.append(board_id)
            page_indexes[board_id] = indexes
            for slot in board["slots"]:
                diagnostic = diagnostics[_identity(slot)]
                diagnostic["planned_selection"] = diagnostic["selected"]
                diagnostic["selected"] = board["grid"]
                diagnostic["selected_page"] = board_id
                diagnostic["required_references"] = len(indexes) + int(guide_enabled)
                if split:
                    diagnostic["reference_capacity_reason"] = "Page split to preserve every required style/master input within the actual reference capacity"
        if split:
            adjustments.append({"source_board_id": source["id"], "prepared_board_ids": new_ids,
                                "reason": "Per-page reference capacity", "max_references": maximum})
    layout["boards"] = boards
    layout["reference_capacity_adjustments"] = adjustments
    layout["summary"].update(ready_view_count=sum(len(board["slots"]) for board in boards),
                             unresolved_view_count=len(layout["unresolved"]), estimated_generation_calls=len(boards),
                             single_boards=sum(board["template"] == "single" for board in boards),
                             packed_boards=sum(board["template"] != "single" for board in boards))
    return page_indexes, canonical


def _guide(board):
    Image, _, _ = _pillow()
    from PIL import ImageDraw
    image = Image.new("RGB", tuple(board["canvas_size"]), "white")
    draw = ImageDraw.Draw(image)
    for number, slot in enumerate(board["slots"], 1):
        left, top, right, bottom = slot["planned_region"]
        draw.rectangle((left + 3, top + 3, right - 4, bottom - 4), outline=(210, 210, 210), width=1)
        draw.text((left + 12, top + 12), str(number), fill=(130, 130, 130))
    output = io.BytesIO()
    image.save(output, format="PNG", compress_level=9)
    return output.getvalue()


def _prompt_subject(description, planned, slot):
    """Carry frozen view/layout constraints into the submitted subject JSON."""
    reserved = {"projected_aspect", "projected_dimensions", "projection_source_ref", "pixel_requirements",
                "requirements", "estimated_subject_size", "min_subject_long_edge_px", "min_subject_short_edge_px",
                "critical_feature_fraction_of_short_edge", "min_feature_px"}
    subject = {key: value for key, value in description.items() if key not in reserved}
    subject.update(projected_aspect=_projected_aspect(planned),
                   pixel_requirements=dict(slot["requirements"]),
                   estimated_subject_size=list(slot["estimated_subject_size"]))
    if planned.get("projected_dimensions") is not None:
        subject["projected_dimensions"] = dict(planned["projected_dimensions"])
    return subject


def prepare(spec, project, output_dir, request_path=None):
    """Prepare immutable one-page edit requests; never invoke a host or supplier."""
    core.require(isinstance(spec, dict) and spec.get("schema") == 1 and spec.get("kind") == "reference-board-prepare-input",
                 "Expected reference-board-prepare-input schema 1")
    project = Path(project).resolve()
    output_dir = _path(str(output_dir), project)
    skill = Path(__file__).resolve().parents[2]
    core.require(not core.inside(output_dir, skill), "Installed skill is read-only; choose an external project output")
    # Validate the original input before any deduplication changes its view list.
    plan(spec.get("plan"))
    rows = spec["plan"]["views"]
    planned = {_identity(row): row for row in rows}
    supplied = spec.get("objects")
    core.require(isinstance(supplied, list) and supplied, "Prepare needs structured objects for every planned view")
    descriptions = {}
    for row in supplied:
        core.require(isinstance(row, dict), "Board objects must be structured objects")
        core.require(core.safe_id(row.get("asset_id")) and core.safe_id(row.get("view_id")),
                     "Every object needs stable asset_id and view_id")
        identity = row.get("asset_id"), row.get("view_id")
        core.require(identity in planned and identity not in descriptions, "Object description is duplicated or not a planned asset/view")
        descriptions[identity] = _description(row, planned[identity])
    core.require(set(descriptions) == set(planned), "Every planned asset/view needs its own complete object description")
    capabilities = spec.get("capabilities", {})
    core.require(isinstance(capabilities, dict) and capabilities.get("edit") is True,
                 "Board generation needs an actual image-conditioned edit capability")
    core.require(type(capabilities.get("max_references")) is int and capabilities["max_references"] > 0,
                 "Declare the current channel's actual max_references")
    core.require(isinstance(capabilities.get("source_ref"), str) and capabilities["source_ref"].strip(),
                 "Record the actual capability source, not an assumed host default")
    guide_enabled = capabilities.get("layout_guide", True)
    core.require(type(guide_enabled) is bool, "layout_guide must be true or explicit false")
    purpose = spec.get("purpose", "modeling")
    core.require(purpose in {"modeling", "exploration"}, "Board purpose must be modeling or exploration")
    parameters = spec.get("parameters", {})
    core.require(isinstance(parameters, dict) and type(parameters.get("n", 1)) is int and parameters.get("n", 1) == 1,
                 "Each board request must generate exactly one image")
    core.require(parameters.get("background") != "transparent", "Reference boards need an opaque white background")
    _json_bytes(parameters)  # reject nonfinite/non-JSON values before writing
    requested_size = parameters.get("size")
    core.require(requested_size is None or requested_size == "auto" or requested_size == "x".join(map(str, spec["plan"]["channel_size"])),
                 "Requested image size contradicts the planned channel_size")
    images, dependencies = [], {}
    references = spec.get("images")
    core.require(isinstance(references, list) and references, "Board generation needs actual approved style/design image inputs")
    from . import image_adapters
    for ref in references:
        path, _ = _file(ref, project, dependencies)
        info = image_adapters.image_info(path)
        images.append({"path": str(path.relative_to(project)), "sha256": info["sha256"]})
    core.require(len({ref["sha256"] for ref in images}) == len(images), "Board input images must have distinct bytes")
    roles = spec.get("image_roles", [{"role": "style"} for _ in images])
    core.require(isinstance(roles, list) and len(roles) == len(images), "image_roles must match the ordered images")
    for image, role in zip(images, roles):
        core.require(isinstance(role, dict) and role.get("role") in {"style", "design_master", "identity_master"},
                     "Image roles must be style, design_master or identity_master")
        if role["role"] == "design_master":
            core.require(core.safe_id(role.get("asset_id")) and core.safe_id(role.get("view_id")),
                         "A design_master image must bind its planned asset/view")
            identity = role.get("asset_id"), role.get("view_id")
            core.require(identity in planned, "A design_master image must bind its planned asset/view")
        elif role["role"] == "identity_master":
            core.require(core.safe_id(role.get("asset_id")) and core.safe_id(role.get("source_view_id")),
                         "An identity_master needs its asset_id and actual source_view_id")
            targets = role.get("target_view_ids")
            core.require(isinstance(targets, list) and targets and all(core.safe_id(view) for view in targets)
                         and len(set(targets)) == len(targets), "An identity_master needs distinct explicit target_view_ids")
            core.require(all((role["asset_id"], view) in planned for view in targets),
                         "Every identity_master target must bind its own asset's planned view")
            _identity_master_review(role, image, project, dependencies)
    effective_plan, aliases, conflicts = _deduplicate(spec["plan"], descriptions)
    layout = plan(effective_plan)
    planned_views = {_identity(row): row for row in effective_plan["views"]}
    page_indexes, canonical = _reference_budget_layout(layout, planned_views,
                                                       aliases, roles, capabilities["max_references"], guide_enabled)
    layout_raw = _json_bytes(layout)
    writes = {output_dir / "layout.json": layout_raw}
    layout_ref = {"path": str((output_dir / "layout.json").relative_to(project)), "sha256": _sha(layout_raw)}
    template = Template((Path(__file__).parent / "prompt_templates" / "board.txt").read_text(encoding="utf-8"))
    prepared = []
    for board in layout["boards"]:
        prefix = output_dir / board["id"]
        indexes = page_indexes[board["id"]]
        page_images, page_roles, guide_ref = [images[i] for i in indexes], [roles[i] for i in indexes], None
        input_lines = []
        for number, role in enumerate(page_roles, 1):
            if role["role"] == "design_master":
                identity = role["asset_id"], role["view_id"]
                source = canonical[identity]
                alias_note = f" This approved alias shares the exact model with {source[0]} / {source[1]}." if source != identity else ""
                input_lines.append(f"Image {number}: exact design master for {identity[0]} / {identity[1]}; preserve its identity and construction.{alias_note}")
            elif role["role"] == "identity_master":
                targets = [view for view in role["target_view_ids"] if canonical[(role["asset_id"], view)]
                           in {_identity(slot) for slot in board["slots"]}]
                input_lines.append(f"Image {number}: identity master for {role['asset_id']} from actual source view "
                                   f"{role['source_view_id']}; preserve that same object's proportions, construction, "
                                   f"materials and pose for target views {', '.join(targets)}. Move only the camera; "
                                   "the source view is not a label for the requested output view.")
            else:
                input_lines.append(f"Image {number}: approved style reference; retain its intended colors, materials and authored patterns.")
        layout_text = f"Use a loose {board['grid'][0]} column by {board['grid'][1]} row arrangement; slot order is left to right, then top to bottom."
        if guide_enabled:
            guide_raw = _guide(board)
            guide_path = prefix.with_suffix(".guide.png")
            guide_ref = {"path": str(guide_path.relative_to(project)), "sha256": _sha(guide_raw)}
            core.require(guide_ref["sha256"] not in {ref["sha256"] for ref in page_images}, "Layout guide duplicates an approved input image")
            writes[guide_path] = guide_raw
            page_images.append(guide_ref)
            layout_text += f" Image {len(page_images)} is ONLY the layout guide; ignore its frames, numbers and colors when rendering."
        object_lines = []
        for number, slot in enumerate(board["slots"], 1):
            identity = _identity(slot)
            subject = _prompt_subject(descriptions[identity], planned_views[identity], slot)
            object_lines.append(f"Slot {number}: " + json.dumps(subject, ensure_ascii=False, sort_keys=True, allow_nan=False))
        text = template.substitute(size="x".join(map(str, board["canvas_size"])), layout=layout_text,
                                   inputs="\n".join(input_lines), objects="\n".join(object_lines))
        core.require(len(text) <= 100_000, "Board prompt exceeds the shared image-request limit; shorten concrete descriptions")
        prompt_path = prefix.with_suffix(".prompt.txt")
        prompt_raw = text.encode()
        writes[prompt_path] = prompt_raw
        request = {"operation": "edit", "prompt": text, "images": page_images, "parameters": parameters,
                   "purpose": "modeling-reference" if purpose == "modeling" else "reference-exploration"}
        request_path_out = prefix.with_suffix(".request.json")
        request_raw = _json_bytes(request)
        writes[request_path_out] = request_raw
        page = {"id": board["id"], "request": {"path": str(request_path_out.relative_to(project)), "sha256": _sha(request_raw)},
                "prompt": {"path": str(prompt_path.relative_to(project)), "sha256": _sha(prompt_raw)},
                "slots": board["slots"], "input_roles": page_roles + ([{"role": "layout_guide"}] if guide_enabled else []),
                "layout_sha256": layout_ref["sha256"]}
        if guide_ref:
            page["guide"] = guide_ref
        prepared.append(page)
    result = {"ok": True, "schema": 1, "kind": "reference-board-preparation", "purpose": purpose,
              "input_digest": core.digest(spec), "layout": layout_ref, "prepared": prepared,
              "aliases": aliases, "model_source_conflicts": conflicts, "unresolved": layout["unresolved"],
              "diagnostics": layout["diagnostics"], "summary": dict(layout["summary"], original_view_count=len(rows), reused_views=len(aliases)),
              "capability_source_ref": capabilities["source_ref"],
              "boundary": "Prepared requests only; no submission, image-call authorization or visual acceptance. Inspect actual output size and every object before extending a layout."}
    manifest_path = output_dir / "preparation.json"
    manifest_raw = _json_bytes(result)
    writes[manifest_path] = manifest_raw
    forbidden = {Path(path) for path in dependencies}
    if request_path is not None:
        forbidden.add(_path(str(request_path), project))
    # Check every destination before the first write; changed reruns never partly overwrite a preparation.
    for path, raw in writes.items():
        _same_or_new(path, raw, forbidden)
    for path, raw in writes.items():
        if not path.exists():
            core.ensure_directory(path.parent)
            with path.open("xb") as stream:
                stream.write(raw)
    return dict(result, manifest={"path": str(manifest_path.relative_to(project)), "sha256": _sha(manifest_raw)})


def _render(image, crop, *, inspect=False):
    """Preserve source pixels; inspection mode records qualification failures.

    Strict callers retain their historical reject-before-write behavior. A
    production inspection crop is evidence to inspect, not a qualified master.
    """
    _identity(crop)
    roi, padding = crop.get("roi"), crop.get("padding", 24)
    core.require(isinstance(roi, list) and len(roi) == 4 and all(type(x) is int for x in roi), "ROI requires integer [left,top,right,bottom] in EXIF-oriented pixels")
    left, top, right, bottom = roi
    core.require(0 <= left < right <= image.width and 0 <= top < bottom <= image.height, "ROI is empty or out of bounds; automatic clipping is forbidden")
    core.require(type(padding) is int and 0 <= padding <= 1024, "Padding must be an integer in 0..1024")
    width, height = right - left + 2*padding, bottom - top + 2*padding
    core.require(width * height <= MAX_CROP_PIXELS, "Crop exceeds modeling-reference safe pixel limit")
    checks = []
    def check(condition, code, message):
        if not condition:
            if not inspect:
                raise core.WorkflowError(message)
            checks.append({"code": code, "observation": message})
    check(width >= 256 and height >= 256, "small_canvas", "Crop canvas must be >=256px each axis; add white padding without claiming added subject detail")
    region = image.crop(tuple(roi))
    pixels = region.load()
    boundary = [pixels[x, y] for x in range(region.width) for y in (0, region.height-1)] + [pixels[x, y] for y in range(region.height) for x in (0, region.width-1)]
    check(all(min(p) >= 245 for p in boundary), "nonwhite_boundary", "ROI touches nonwhite pixels: possible truncated silhouette or adjacent object; inspect and widen/reselect the ROI before padding")
    minx, miny, maxx, maxy = region.width, region.height, -1, -1
    for y in range(region.height):
        for x in range(region.width):
            if min(pixels[x, y]) < 245:
                minx, miny, maxx, maxy = min(minx, x), min(miny, y), max(maxx, x), max(maxy, y)
    check(maxx >= 0, "blank_subject", "Crop is blank white; it cannot represent an asset")
    bbox = [minx, miny, maxx+1, maxy+1] if maxx >= 0 else None
    subject_size = [bbox[2]-bbox[0], bbox[3]-bbox[1]] if bbox else [0, 0]
    requirements = _requirements(crop)
    check(_passes(*subject_size, requirements), "subject_pixels", "Actual nonwhite subject fails declared pixel requirements; padding/upscaling cannot satisfy missing detail")
    Image, _, _ = _pillow()
    output = Image.new("RGB", (width, height), "white")
    output.paste(region, (padding, padding))
    observed = {"subject_bbox_in_roi": bbox, "subject_size": subject_size, "output_size": [width, height],
                "pixels_sha256": _sha(output.tobytes())}
    if inspect:
        observed.update(technical_pass=not checks, qualification_failures=checks,
                        qualification_boundary="Pixel and white-boundary checks only; not visual or multiview acceptance.")
    return output, observed, requirements


def _same_or_new(path, raw, forbidden):
    core.require(path not in forbidden and not any(path.exists() and p.exists() and path.samefile(p) for p in forbidden),
                 "Cannot overwrite canonical board, invocation receipt, request or another crop input")
    core.require(not path.exists() or (path.is_file() and path.read_bytes() == raw), "Output already exists with different content; use a new versioned output path")


def crop(request, project, request_path=None):
    """Write one asset view only; repairing one view never rewrites sibling crops."""
    core.require(isinstance(request, dict) and request.get("schema") == 1 and request.get("kind") == "reference-board-crop-request", "Expected reference-board-crop-request schema 1")
    concept = request.get("selected_concept_sha256")
    core.require(_hash(concept), "Crop must bind selected concept SHA256")
    dependencies = {}
    board_path, raw = _file(request.get("board"), project, dependencies)
    _generation(request.get("generation_receipt"), request["board"], concept, project, dependencies)
    image, source_info, version = _board(raw)
    mode = request.get("qualification_mode", "strict")
    core.require(mode in {"strict", "inspection"}, "Crop qualification_mode must be strict or inspection")
    output, crop_info, requirements = _render(image, request, inspect=mode == "inspection")
    recipe = {"asset_id": request["asset_id"], "view_id": request["view_id"], "role": request["role"],
              "roi": request["roi"], "padding": request.get("padding", 24), **requirements,
              "coordinate_space": "exif-oriented-pixels", "resize": "none", "background": "white"}
    if mode == "inspection":
        recipe["qualification_mode"] = mode
    buffer = io.BytesIO()
    output.save(buffer, format="PNG", compress_level=9)
    output_raw = buffer.getvalue()
    output_path = _path(request.get("output"), project)
    receipt_path = _path(request.get("receipt_output"), project)
    core.require(output_path.suffix.lower() == ".png", "Crop output must use .png so provider MIME and actual bytes agree")
    core.require(output_path != receipt_path, "Image and receipt outputs must differ")
    receipt = {"schema": 1, "kind": "reference-board-crop-receipt", "board": request["board"],
               "generation_receipt": request["generation_receipt"], "selected_concept_sha256": concept,
               "source": source_info, "recipe": recipe, "recipe_digest": core.digest(recipe),
               "output": {"path": str(output_path.relative_to(Path(project).resolve())), "sha256": _sha(output_raw)},
               "observed": crop_info, "tool": f"greybox-reference-boards-v1/Pillow-{version}",
               "boundary": "Derived crop, not a new image-generation invocation. Complete silhouette/style/lighting and view consistency require visual review."}
    receipt_raw = (json.dumps(receipt, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
    forbidden = {Path(p) for p in dependencies}
    if request_path is not None:
        forbidden.add(_path(str(request_path), project))
    _same_or_new(output_path, output_raw, forbidden)
    _same_or_new(receipt_path, receipt_raw, forbidden)
    for path, content in ((output_path, output_raw), (receipt_path, receipt_raw)):
        if not path.exists():
            core.ensure_directory(path.parent)
            # Exclusive creation protects existing files even if another worker wins a race.
            with path.open("xb") as stream:
                stream.write(content)
    return {"ok": True, "image": receipt["output"], "board_crop_receipt": {
        "path": str(receipt_path.relative_to(Path(project).resolve())), "sha256": _sha(receipt_raw)},
        "origin": "board_crop", "technical_pass": crop_info.get("technical_pass", True)}


def validate_crop_receipt(ref, project, asset_id=None, view_id=None, role=None, concept=None, *, require_qualified=True):
    dependencies = {}
    _, raw = _file(ref, project, dependencies)
    receipt = json.loads(raw)
    core.require(isinstance(receipt, dict) and receipt.get("schema") == 1 and receipt.get("kind") == "reference-board-crop-receipt", "Expected reference-board-crop-receipt schema 1")
    selected = receipt.get("selected_concept_sha256")
    core.require(_hash(selected) and (concept is None or concept == selected), "Crop selected concept differs from approved package")
    _, source_raw = _file(receipt.get("board"), project, dependencies)
    _generation(receipt.get("generation_receipt"), receipt["board"], selected, project, dependencies)
    image, source_info, _ = _board(source_raw)
    core.require(receipt.get("source") == source_info, "Crop source dimensions/orientation changed")
    recipe = receipt.get("recipe", {})
    core.require(receipt.get("recipe_digest") == core.digest(recipe)
                 and recipe.get("coordinate_space") == "exif-oriented-pixels"
                 and recipe.get("resize") == "none" and recipe.get("background") == "white", "Crop recipe is stale or unsupported")
    for key, value in (("asset_id", asset_id), ("view_id", view_id), ("role", role)):
        core.require(value is None or recipe.get(key) == value, "Crop identity/orientation differs from modeling reference")
    mode = recipe.get("qualification_mode", "strict")
    core.require(mode in {"strict", "inspection"}, "Unsupported crop qualification mode")
    expected, observed, _ = _render(image, recipe, inspect=mode == "inspection")
    core.require(receipt.get("observed") == observed, "Crop measurements no longer match source and recipe")
    _, crop_raw = _file(receipt.get("output"), project, dependencies)
    actual, actual_info, _ = _board(crop_raw)
    core.require(actual_info["exif_orientation"] == 1 and actual.size == expected.size and actual.tobytes() == expected.tobytes(),
                 "Crop bytes do not reproduce the bound source ROI and padding")
    technical = observed.get("technical_pass", True)
    core.require(not require_qualified or technical,
                 "Crop is inspection evidence only: technical qualification failed; repair the named ROI or subject detail before using it as a modeling master")
    return {"ok": True, "output": receipt["output"], "dependencies": list(dependencies.values()),
            "technical_pass": technical, "qualification_failures": observed.get("qualification_failures", []),
            "board": {"path": str(_path(receipt['board']['path'], project)),
                      "sha256": receipt['board']['sha256'], "dimensions": source_info['oriented_size']}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("plan", "prepare", "crop", "validate"):
        item = sub.add_parser(command)
        item.add_argument("--file", required=True)
        item.add_argument("--project", required=True)
        if command == "plan": item.add_argument("--output", required=True)
        if command == "prepare": item.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    try:
        project = Path(args.project).resolve()
        source = _path(args.file, project)
        if args.command == "plan":
            result = plan(core.read(source))
            output = _path(args.output, project)
            raw = (json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
            _same_or_new(output, raw, {source})
            if not output.exists():
                core.ensure_directory(output.parent)
                with output.open("xb") as stream: stream.write(raw)
        elif args.command == "prepare":
            result = prepare(core.read(source), project, args.output_dir, request_path=source)
        elif args.command == "crop":
            result = crop(core.read(source), project, request_path=source)
        else:
            result = validate_crop_receipt({"path": str(source), "sha256": core.file_hash(source)}, project)
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return 0
    except (ValueError, OSError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=True), file=sys.stderr)
        return 2
