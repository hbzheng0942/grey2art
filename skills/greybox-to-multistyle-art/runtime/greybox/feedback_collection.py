"""Bounded, offline collection of explicitly supplied feedback exports.

Sample identities and shared fingerprints are maintainer declarations. Neither
matching titles nor a case-local issue ID establishes a shared root cause.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import core, feedback

MAX_EXPORTS = 128
MAX_BYTES = 4 * 1024 * 1024
MAX_TOTAL_BYTES = 32 * 1024 * 1024
MAX_ISSUES = 500
MAX_COLLECTION_ISSUES = 5000
MAX_EVENTS = 2000
KIND = "greybox-feedback-collection"
NOTICE = ("Only submitted samples and recorded observations; sample counts are not user counts. "
          "Unknown values are not zero. Shared fingerprints are declared groupings, not verified root causes. "
          "Costs are not summed across exports or overlapping measurements.")


def _read(path, limit=MAX_BYTES):
    core.require(path.is_file() and path.stat().st_size <= limit, "Collection input is missing or too large")
    data = path.read_bytes()
    core.require(len(data) <= limit, "Collection input is too large")
    def reject_constant(value):
        raise ValueError("Non-finite JSON value: " + value)
    value = json.loads(data, parse_constant=reject_constant)
    _bounded(value)
    return value, len(data)


def _bounded(value, depth=0):
    core.require(depth <= 20, "Collection JSON nesting exceeds 20 levels")
    if isinstance(value, dict):
        core.require(len(value) <= 2000 and all(isinstance(k, str) and len(k) <= 500 for k in value), "Oversized JSON object")
        for item in value.values():
            _bounded(item, depth + 1)
    elif isinstance(value, list):
        core.require(len(value) <= 10000, "Oversized JSON list")
        for item in value:
            _bounded(item, depth + 1)
    elif isinstance(value, str):
        core.require(len(value) <= 16000, "Oversized JSON string")


def _number(value):
    return value if type(value) is int and value >= 0 else None


def _optional_text(value, limit=4000):
    core.require(value is None or isinstance(value, str) and len(value) <= limit, "Expected bounded text or null")
    return value


def _identity(value):
    if value is None:
        return {"version": None, "manifest_sha256": None}
    core.require(isinstance(value, dict), "Invalid recorder package identity")
    return {key: _optional_text(value.get(key), 500) for key in ("version", "manifest_sha256")}


def _context(value):
    core.require(value is None or isinstance(value, dict), "Invalid environment context")
    value = value or {}
    return {key: _optional_text(value.get(key), 500) for key in ("host", "model", "engine")}


def _issue(value, sample_id, case_id, overrides):
    core.require(isinstance(value, dict) and core.safe_id(value.get("issue_id")), "Invalid case-local issue identity")
    issue_id = value["issue_id"]
    mechanisms = value.get("mechanisms", [])
    core.require(isinstance(mechanisms, list) and len(mechanisms) <= 24 and all(core.safe_id(v) for v in mechanisms), "Invalid issue mechanisms")
    events = value.get("events", [])
    core.require(isinstance(events, list) and len(events) <= MAX_EVENTS and all(isinstance(e, dict) for e in events), "Invalid issue events")
    triage = value.get("triage") or {}
    core.require(isinstance(triage, dict), "Invalid issue triage")
    fingerprint = overrides.get(issue_id, triage.get("fingerprint"))
    core.require(fingerprint is None or core.safe_id(fingerprint), "Invalid declared issue fingerprint")
    category = triage.get("category", "unknown")
    severity = triage.get("severity", "unknown")
    core.require(category in {"skill_guidance", "agent_execution", "host_tool", "provider", "source_project", "unknown"}, "Invalid triage category")
    core.require(severity in {"blocker", "major", "minor", "unknown"}, "Invalid triage severity")
    project_status, skill_status = value.get("project_status"), value.get("skill_status")
    core.require(project_status is None or project_status in feedback.PROJECT_STATES, "Invalid project status")
    core.require(skill_status is None or skill_status in feedback.SKILL_STATES, "Invalid Skill status")
    if value.get("is_defect_candidate") is False and value.get("evidence_current") is not False:
        unresolved = False
    elif value.get("evidence_current") is False:
        unresolved = True
    elif project_status is None or skill_status is None:
        unresolved = None
    else:
        unresolved = project_status != "fixed" or skill_status not in {"verified", "not_applicable"}
    identities = {_json(_identity(e.get("skill"))) for e in events}
    contexts = {_json(_context(e.get("context"))) for e in events}
    contexts.add(_json(_context(value.get("context"))))
    latest_method = _optional_text(value.get("latest_method"))
    method_source = "reported_issue_summary" if latest_method is not None else None
    if "latest_method" not in value:
        for event in reversed(events):
            if event.get("method") is not None:
                latest_method = _optional_text(event["method"])
                method_source = "reported_event"
                break
    return {"sample_id": sample_id, "case_id": case_id, "issue_id": issue_id,
            "summary": _optional_text(value.get("summary")), "stage": _optional_text(value.get("stage")),
            "expected": _optional_text(value.get("expected")), "actual": _optional_text(value.get("actual")),
            "latest_method": latest_method, "latest_method_source": method_source,
            "mechanisms": sorted(set(mechanisms)), "fingerprint": fingerprint,
            "category": category, "severity": severity, "project_status": project_status,
            "skill_status": skill_status, "unresolved": unresolved,
            "event_count": len(events) if "events" in value else None,
            "attempt_count": sum(e.get("type") == "attempt" for e in events) if "events" in value else None,
            "contexts": [json.loads(v) for v in sorted(contexts)],
            "recorder_packages": [json.loads(v) for v in sorted(identities)],
            "next_test": _optional_text(value.get("next_test"))}


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sample(entry, report, digest):
    core.require(isinstance(report, dict) and type(report.get("schema")) is int and report["schema"] == 1
                 and report.get("kind") == "greybox-usage-feedback-export", "Expected a local usage feedback export")
    core.require(core.safe_id(report.get("case_id")), "Invalid exported case identity")
    revision = _number(report.get("plan_revision"))
    core.require(revision is not None, "Export needs a nonnegative plan_revision")
    issues = report.get("issues")
    core.require(isinstance(issues, list) and len(issues) <= MAX_ISSUES, "Export needs a bounded issue list")
    normalized = [_issue(v, entry["sample_id"], report["case_id"], entry.get("issue_fingerprints", {})) for v in issues]
    core.require(len({v["issue_id"] for v in normalized}) == len(normalized), "Duplicate issue IDs within one export")
    core.require(set(entry.get("issue_fingerprints", {})) <= {v["issue_id"] for v in normalized}, "Declared fingerprint references an unknown issue")
    interventions = report.get("interventions") or {}
    core.require(isinstance(interventions, dict), "Invalid exported interventions")
    coverage = report.get("coverage") or {}
    core.require(isinstance(coverage, dict), "Invalid exported coverage")
    return {"sample_id": entry["sample_id"], "case_id": report["case_id"], "plan_revision": revision,
            "canonical_export_sha256": digest, "issues": normalized,
            "recorded_rescue_episodes": _number(interventions.get("rescue")),
            "observation_count": _number(coverage.get("observation_count"))}


def build(project, manifest_path):
    """Read explicit exports only; never discover private case files recursively."""
    project = Path(project).resolve()
    manifest_path = feedback._path(project, manifest_path)
    manifest, total_bytes = _read(manifest_path, 256 * 1024)
    core.require(isinstance(manifest, dict) and set(manifest) == {"schema", "kind", "exports"}
                 and type(manifest.get("schema")) is int and manifest["schema"] == 1
                 and manifest.get("kind") == "greybox-feedback-collection-input",
                 "Expected greybox-feedback-collection-input schema 1")
    entries = manifest["exports"]
    core.require(isinstance(entries, list) and 0 < len(entries) <= MAX_EXPORTS, "Supply 1 to 128 explicit exports")
    samples, seen, input_paths = {}, {}, {manifest_path}
    duplicate_exports = superseded_exports = 0
    for entry in entries:
        core.require(isinstance(entry, dict) and {"sample_id", "path"} <= set(entry)
                     and set(entry) <= {"sample_id", "path", "issue_fingerprints"}
                     and core.safe_id(entry["sample_id"]), "Export entry needs stable anonymous sample_id and path")
        overrides = entry.get("issue_fingerprints", {})
        core.require(isinstance(overrides, dict) and len(overrides) <= MAX_ISSUES
                     and all(core.safe_id(k) and core.safe_id(v) for k, v in overrides.items()), "Invalid declared issue fingerprints")
        path = feedback._path(project, entry["path"])
        input_paths.add(path)
        raw, size = _read(path)
        total_bytes += size
        core.require(total_bytes <= MAX_TOTAL_BYTES, "Collection inputs exceed 32 MiB")
        digest = core.digest(raw)
        sample = _sample(entry, raw, digest)
        if digest in seen:
            core.require(seen[digest] == overrides, "Duplicate export has conflicting declared fingerprints")
            duplicate_exports += 1
            continue
        seen[digest] = overrides
        prior = samples.get(entry["sample_id"])
        if prior:
            core.require(prior["case_id"] == sample["case_id"], "One sample_id cannot identify different cases")
            core.require(prior["plan_revision"] != sample["plan_revision"], "Conflicting exports at one sample revision")
            superseded_exports += 1
            if prior["plan_revision"] > sample["plan_revision"]:
                continue
        samples[entry["sample_id"]] = sample
    issues = [i for key in sorted(samples) for i in samples[key]["issues"]]
    core.require(len(issues) <= MAX_COLLECTION_ISSUES, "Collection exceeds 5000 issues; split the input manifest")
    grouped, similar = {}, {}
    for issue in issues:
        if issue["fingerprint"]:
            grouped.setdefault(issue["fingerprint"], []).append(issue)
        elif issue["stage"] and issue["mechanisms"]:
            similar.setdefault(_json([issue["stage"], issue["mechanisms"]]), []).append(issue)
    groups = [{"fingerprint": key, "basis": "declared_shared_fingerprint", "sample_count": len({i["sample_id"] for i in values}),
               "issue_count": len(values), "members": [{k: i[k] for k in ("sample_id", "issue_id")} for i in values]}
              for key, values in sorted(grouped.items())]
    candidates = [{"stage": values[0]["stage"], "mechanisms": values[0]["mechanisms"],
                   "basis": "similar_stage_and_mechanisms_only", "sample_count": len({i["sample_id"] for i in values}),
                   "members": [{k: i[k] for k in ("sample_id", "issue_id")} for i in values]}
                  for key, values in sorted(similar.items()) if len({i["sample_id"] for i in values}) > 1]
    groups.sort(key=lambda group: (-group["sample_count"], -group["issue_count"], group["fingerprint"]))
    candidates.sort(key=lambda group: (-group["sample_count"], group["stage"], group["mechanisms"]))
    rescue_values = [v["recorded_rescue_episodes"] for v in samples.values()]
    report = {"schema": 1, "kind": KIND, "sample_count": len(samples), "submitted_export_count": len(entries),
              "duplicate_exports_skipped": duplicate_exports, "superseded_exports_skipped": superseded_exports,
              "issue_count": len(issues), "known_unresolved_issues": sum(i["unresolved"] is True for i in issues),
              "unknown_issue_status_count": sum(i["unresolved"] is None for i in issues),
              "known_rescue_episodes": sum(v for v in rescue_values if v is not None) if any(v is not None for v in rescue_values) else None,
              "samples_missing_rescue_measurement": sum(v is None for v in rescue_values),
              "cost_totals": None, "samples": [samples[k] for k in sorted(samples)],
              "confirmed_fingerprint_groups": groups, "similarity_candidates": candidates,
              "notice": NOTICE, "review_required": True, "uploaded": False}
    return feedback._redact(report), input_paths


def _plain(value, limit=400):
    value = feedback._plain(value)[:limit]
    for char in ("\\", "`", "*", "[", "]", "#"):
        value = value.replace(char, "\\" + char)
    return value


def markdown(report):
    lines = ["# Usage feedback collection", "", report["notice"], "",
             "Samples: " + str(report["sample_count"]) + "; issues: " + str(report["issue_count"])
             + "; known unresolved: " + str(report["known_unresolved_issues"])
             + "; unknown status: " + str(report["unknown_issue_status_count"]),
             "Known recorded rescue episodes: " + _plain(report["known_rescue_episodes"])
             + "; samples missing rescue measurement: " + str(report["samples_missing_rescue_measurement"]), "",
             "## Declared shared fingerprints", ""]
    for group in report["confirmed_fingerprint_groups"][:20]:
        lines.append("- " + _plain(group["fingerprint"]) + ": " + str(group["sample_count"]) + " samples; "
                     + ", ".join(_plain(i["sample_id"] + "/" + i["issue_id"]) for i in group["members"][:10])
                     + ("; more members in collection.json" if len(group["members"]) > 10 else ""))
    if len(report["confirmed_fingerprint_groups"]) > 20:
        lines.append("Additional fingerprint groups retained in collection.json: " + str(len(report["confirmed_fingerprint_groups"]) - 20))
    if not report["confirmed_fingerprint_groups"]:
        lines.append("No shared fingerprint declared.")
    lines += ["", "## Similarity candidates requiring triage", ""]
    for group in report["similarity_candidates"][:20]:
        lines.append("- " + _plain(group["stage"]) + "; " + ", ".join(group["mechanisms"]) + ": "
                     + str(group["sample_count"]) + " samples. Matching stage/tags do not establish a common cause.")
    if len(report["similarity_candidates"]) > 20:
        lines.append("Additional similarity candidates retained in collection.json: " + str(len(report["similarity_candidates"]) - 20))
    if not report["similarity_candidates"]:
        lines.append("No cross-sample similarity candidate.")
    lines += ["", "## Issues by submitted sample", ""]
    issues = [(sample, issue) for sample in report["samples"] for issue in sample["issues"]]
    for sample, issue in issues[:100]:
        packages = ", ".join(_plain(v["version"]) for v in issue["recorder_packages"]) or "unknown"
        contexts = "; ".join("/".join(_plain(v[k]) for k in ("host", "model", "engine")) for v in issue["contexts"])
        lines += ["- **" + _plain(sample["sample_id"]) + " / " + _plain(issue["issue_id"]) + "**: " + _plain(issue["summary"]),
                  "  Stage: " + _plain(issue["stage"]) + "; project: " + _plain(issue["project_status"])
                  + "; Skill: " + _plain(issue["skill_status"]) + "; category: " + issue["category"] + "; severity: " + issue["severity"],
                  "  Recorder package: " + packages + "; host/model/engine: " + contexts,
                  "  Expected: " + _plain(issue["expected"], 240) + " → actual: " + _plain(issue["actual"], 240),
                  "  Latest method (" + _plain(issue["latest_method_source"], 80) + "): " + _plain(issue["latest_method"], 240)
                  + "; recorded attempts: " + _plain(issue["attempt_count"], 20),
                  "  Next test: " + _plain(issue["next_test"], 240)]
    if len(issues) > 100:
        lines.append("Additional issues retained in collection.json: " + str(len(issues) - 100))
    lines += ["", "Recorder identity belongs to the recording package, including later backfills; it does not identify the failing version by itself.",
              "Local review draft; no upload or external Issue creation was performed.", ""]
    return "\n".join(lines)


def collect(project, manifest_path, output_dir):
    project = Path(project).resolve()
    report, inputs = build(project, manifest_path)
    directory = feedback._path(project, output_dir)
    skill_root = Path(__file__).resolve().parents[2]
    core.require(".git" not in directory.parts and not core.inside(directory, skill_root), "Collection destination is protected")
    json_path = feedback._path(project, directory / "collection.json")
    markdown_path = feedback._path(project, directory / "collection.md")
    core.require(json_path.parent == directory and markdown_path.parent == directory
                 and json_path not in inputs and markdown_path not in inputs, "Collection output would overwrite input or escape destination")
    marker = "# Usage feedback collection\n"
    with core.locked(directory):
        if json_path.exists():
            existing, unused_size = _read(json_path, MAX_TOTAL_BYTES)
            core.require(isinstance(existing, dict) and existing.get("kind") == KIND, "Refusing to replace unrelated collection file")
        if markdown_path.exists():
            core.require(markdown_path.read_text(encoding="utf-8").startswith(marker), "Refusing to replace unrelated collection file")
        changed_json = feedback._write_text(json_path, json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", "{")
        changed_markdown = feedback._write_text(markdown_path, markdown(report), marker)
    return {"ok": True, "json": str(json_path), "markdown": str(markdown_path),
            "sample_count": report["sample_count"], "changed": changed_json or changed_markdown,
            "review_required": True, "uploaded": False}
