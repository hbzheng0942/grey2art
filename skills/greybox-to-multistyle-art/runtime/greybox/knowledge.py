"""Local, stage-scoped reading navigation. Never executes the suggested commands."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[2]
INDEX = "schemas/knowledge-index.json"
ENGINES = ("godot", "unity", "blender")


def _path(root, relative):
    if not isinstance(relative, str) or "\\" in relative:
        raise ValueError("Knowledge paths must be package-relative POSIX paths")
    parts = PurePosixPath(relative)
    if parts.is_absolute() or ".." in parts.parts or not parts.parts or ":" in relative:
        raise ValueError("Knowledge path escapes the package: " + relative)
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("Knowledge file missing or outside the package: " + relative)
    return path


def _load(root):
    index = json.loads(_path(root, INDEX).read_text(encoding="utf-8"))
    if not isinstance(index, dict) or index.get("schema") != 1 or index.get("kind") != "greybox-knowledge-index":
        raise ValueError("Expected greybox-knowledge-index schema 1")
    if not isinstance(index.get("stages"), dict) or not isinstance(index.get("topics"), dict):
        raise ValueError("Knowledge index requires stages and topics")
    for group in ("stages", "topics"):
        for name, entry in index[group].items():
            if not isinstance(entry, dict) or not isinstance(entry.get("read", []), list):
                raise ValueError("Invalid knowledge route: " + str(name))
            for field in ("aliases", "topics", "review_questions", "command_hints"):
                if not isinstance(entry.get(field, []), list) or not all(isinstance(v, str) for v in entry.get(field, [])):
                    raise ValueError("Invalid knowledge route field: " + str(name) + "/" + field)
    if not isinstance(index.get("workflow_stages", {}), dict):
        raise ValueError("workflow_stages must map exact workflow IDs to stages")
    categories = index.get("asset_categories", {})
    if not isinstance(categories, dict):
        raise ValueError("asset_categories must map explicit categories to stage reads")
    for category, entry in categories.items():
        routes = entry.get("read_by_stage") if isinstance(entry, dict) else None
        if not isinstance(routes, dict) or any(stage not in index["stages"] or
                not isinstance(paths, list) or not all(isinstance(p, str) for p in paths)
                for stage, paths in routes.items()):
            raise ValueError("Invalid asset category route: " + str(category))
    return index


def _aliases(index):
    aliases = {}
    for stage, entry in index["stages"].items():
        for alias in [stage] + entry.get("aliases", []):
            key = alias.lower()
            if key in aliases:
                raise ValueError("Duplicate knowledge stage alias: " + alias)
            aliases[key] = stage
    return aliases


def _stage(value, index):
    aliases = _aliases(index)
    key = value.strip().lower() if isinstance(value, str) else ""
    if key in aliases:
        return aliases[key]
    # Only known workflow IDs accept a case/style scope. Arbitrary suffixes such
    # as an unknown "asset/build" must not accidentally route to greybox work.
    parts = key.split("/")
    if len(parts) == 2 and re.fullmatch(r"[a-z0-9][a-z0-9_-]*", parts[0]):
        return index.get("workflow_stages", {}).get(parts[1])
    return None


def _entries(entry, engine=None):
    return [item if isinstance(item, dict) else {"path": item}
            for item in entry.get("read", [])
            if not isinstance(item, dict) or not item.get("engines") or engine in item["engines"]]


def _files(root, entries):
    found = {}
    for entry in entries:
        relative = entry["path"]
        path = _path(root, relative)
        found.setdefault(relative, {"path": relative, "absolute_path": str(path), "bytes": path.stat().st_size})
    return list(found.values())


def navigation(stage=None, engine=None, topics=None, root=None, asset_category=None):
    """Read the index and stat only selected documents; do not load their text."""
    root = Path(root or ROOT).resolve()
    if engine is not None and engine not in ENGINES:
        raise ValueError("Unknown engine/carrier filter; select godot, unity or blender, or omit the filter")
    index = _load(root)
    selected = _stage(stage, index)
    result = {"ok": False, "status": "stage_required", "requested_stage": stage, "stage": selected,
              "engine": engine, "index_path": str(root / INDEX), "read_next": [],
              "review_questions": [], "command_hints": [], "paid_work_authorized": False,
              "limits": "Reading navigation only; current workflow, user decisions and recovery ledgers remain authoritative."}
    if selected is None:
        result.update(stage_choices=list(index["stages"]),
                      next="Select the actual current stage; no execution branch was inferred.")
        return result
    topics = list(dict.fromkeys(topics or []))
    unknown = [topic for topic in topics if topic not in index["topics"]]
    if unknown:
        result.update(status="topic_required", unknown_topics=unknown, topic_choices=list(index["topics"]))
        return result
    entry = index["stages"][selected]
    category_entries = []
    if asset_category is not None:
        categories = index.get("asset_categories", {})
        if asset_category not in categories:
            result.update(status="asset_category_required", asset_category_choices=list(categories))
            return result
        category_entries = [{"path": path} for path in
                            categories[asset_category].get("read_by_stage", {}).get(selected, [])]
    required = _files(root, _entries(entry, engine) + category_entries)
    all_entries = _entries(entry, engine)
    all_entries.extend(category_entries)
    for topic in topics:
        all_entries.extend(_entries(index["topics"][topic], engine))
    files = _files(root, all_entries)
    result.update(ok=True, status="ready", read_next=files, selected_topics=topics, asset_category=asset_category,
                  topic_choices=entry.get("topics", []), review_questions=entry.get("review_questions", []),
                  command_hints=entry.get("command_hints", []),
                  reading_bytes={"required": sum(x["bytes"] for x in required),
                                 "selected_total": sum(x["bytes"] for x in files),
                                 "unselected_topics_loaded": False},
                  next="Read only read_next; add a named topic when the current task needs it.")
    return result


def for_focus(stage, engine=None):
    """A documentation defect must not break existing case recovery or tokens."""
    try:
        return navigation(stage, engine=engine if engine in ENGINES else None)
    except (ValueError, OSError, KeyError, TypeError, AttributeError) as error:
        return {"ok": False, "status": "navigation_unavailable", "requested_stage": stage,
                "error": str(error), "read_next": [], "paid_work_authorized": False}


def audit(root=None):
    """Explicit package audit; unlike navigation, this reads document inventory."""
    root = Path(root or ROOT).resolve()
    index = _load(root)
    errors, duplicates, routed = [], [], set()
    try:
        _aliases(index)
    except ValueError as error:
        errors.append(str(error))
    for group in ("stages", "topics"):
        for key, entry in index[group].items():
            seen = set()
            for item in entry.get("read", []):
                item = item if isinstance(item, dict) else {"path": item}
                relative = item.get("path")
                if relative in seen:
                    duplicates.append({"route": group + "/" + key, "path": relative})
                seen.add(relative)
                try:
                    _path(root, relative)
                    if item.get("engines") and (not isinstance(item["engines"], list)
                            or any(e not in ENGINES for e in item["engines"])):
                        raise ValueError("Invalid engine filter: " + str(relative))
                    routed.add(relative)
                except (ValueError, OSError, TypeError) as error:
                    errors.append(str(error))
            for topic in entry.get("topics", []):
                if topic not in index["topics"]:
                    errors.append("Unknown topic in " + key + ": " + topic)
    for alias, target in index.get("workflow_stages", {}).items():
        if target not in index["stages"]:
            errors.append("Unknown workflow stage target: " + alias + " -> " + target)
    for category, entry in index.get("asset_categories", {}).items():
        for stage, paths in entry["read_by_stage"].items():
            for relative in paths:
                try:
                    _path(root, relative)
                    routed.add(relative)
                except (ValueError, OSError, TypeError) as error:
                    errors.append(str(error))
    inventory, hashes, inbound = {}, {}, set()
    references = root / "references"
    if references.is_symlink() and not references.resolve().is_relative_to(root):
        errors.append("References inventory escapes the package")
        candidates = []
    else:
        candidates = sorted(references.glob("*.md"))
    if (root / "SKILL.md").exists():
        candidates.append(root / "SKILL.md")
    broken_links = []
    for candidate in candidates:
        relative = candidate.relative_to(root).as_posix()
        try:
            path = _path(root, relative)
            data = path.read_bytes()
            inventory[relative] = len(data)
            hashes.setdefault(hashlib.sha256(data).hexdigest(), []).append(relative)
            # Static link inventory only. Never follows a link to read a file.
            for link in re.findall(r"\]\(([^)]+)\)", data.decode("utf-8")):
                target = urlsplit(link.strip().strip("<>"))
                if target.scheme or target.netloc or not target.path:
                    continue
                destination = (path.parent / unquote(target.path)).resolve()
                if not destination.is_relative_to(root):
                    broken_links.append({"source": relative, "target": link, "reason": "outside_package"})
                elif not destination.exists():
                    broken_links.append({"source": relative, "target": link, "reason": "missing"})
                else:
                    inbound.add(destination.relative_to(root).as_posix())
        except (ValueError, OSError, UnicodeError) as error:
            errors.append(str(error))
    metrics = {}
    for stage, entry in index["stages"].items():
        variants = {}
        for engine in (None,) + ENGINES:
            base = {item["path"] for item in _entries(entry, engine)}
            optional = {}
            union = set(base)
            for topic in entry.get("topics", []):
                paths = {item["path"] for item in _entries(index["topics"].get(topic, {}), engine)}
                optional[topic] = sum(inventory.get(p, 0) for p in paths - base)
                union.update(paths)
            variants[engine or "common"] = {
                "direct_read_bytes": sum(inventory.get(p, 0) for p in base),
                "optional_topic_additional_bytes": optional,
                "all_optional_additional_bytes": sum(inventory.get(p, 0) for p in union - base)}
        metrics[stage] = variants
    reference_paths = {p for p in inventory if p.startswith("references/")}
    return {"ok": not errors and not duplicates and not broken_links, "index_path": str(root / INDEX),
            "errors": errors, "duplicate_routes": duplicates, "broken_links": broken_links,
            "duplicate_content": [paths for paths in hashes.values() if len(paths) > 1],
            "unrouted_references": sorted(reference_paths - routed),
            "orphan_references": sorted(reference_paths - routed - inbound),
            "inventory": {"reference_count": len(reference_paths),
                          "reference_bytes": sum(inventory[p] for p in reference_paths),
                          "entrypoint_bytes": inventory.get("SKILL.md", 0),
                          "index_bytes": (root / INDEX).stat().st_size,
                          "total_document_bytes": sum(inventory.values())},
            "stage_reading_bytes": metrics,
            "limits": "Byte counts are reading cost indicators, not quality scores. Optional topics were read only for this explicit audit."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("next", "audit"))
    parser.add_argument("--stage", help="Exact stage, H1-H5/S0-S10, or scoped workflow stage ID")
    parser.add_argument("--engine", choices=ENGINES)
    parser.add_argument("--topic", action="append", default=[], help="Exact optional topic ID; repeat when needed")
    parser.add_argument("--asset-category", help="Known asset category; loads its required stage guidance without executing work")
    parser.add_argument("--project")
    parser.add_argument("--case", help="Use the current PLAN/FOCUS stage instead of --stage")
    args = parser.parse_args(argv)
    try:
        if args.command == "audit":
            if args.stage or args.engine or args.topic or args.project or args.case or args.asset_category:
                raise ValueError("audit inspects the package; stage/case filters belong to next")
            result = audit()
        elif args.case or args.project:
            if args.stage or not (args.project and args.case):
                raise ValueError("Use either --stage or the pair --project and --case")
            from . import continuity
            focus = continuity.derive_focus(args.project, args.case)
            case_engine = (focus.get("greybox", {}).get("engine")
                           or focus.get("learning", {}).get("engine"))
            result = navigation(focus["current_stage"], args.engine or case_engine, args.topic, asset_category=args.asset_category)
            result["case_status"] = focus["status"]
            result["case_next_action"] = focus["next_action"]
        else:
            result = navigation(args.stage, args.engine, args.topic, asset_category=args.asset_category)
    except (ValueError, OSError, KeyError, TypeError) as error:
        result = {"ok": False, "error": str(error)}
    print(json.dumps(result, indent=2, ensure_ascii=True))
    return 0 if result["ok"] else 2
