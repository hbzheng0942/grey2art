"""Version-bound human final acceptance; never executes engines or providers.

Technical validation only makes a run reviewable. H5 records a user decision
against the exact delivery manifest returned to the host for review.
"""
from pathlib import Path
import copy
import re

from . import core


_FILE_KEYS = {"report_path", "native_report_path", "validation_path", "log_path"}


def _file(reference, project, expected=None):
    core.require(isinstance(reference, str) and reference.strip(), "Delivery file needs an explicit path")
    path = core.resolve_input(reference, project)
    core.require(path.is_file(), "Delivery file is missing: " + str(path))
    value = core.file_hash(path)
    core.require(expected is None or value == expected, "Delivery file changed: " + str(path))
    return {"path": str(path), "sha256": value}


def _receipts(items, project, label):
    core.require(isinstance(items, list) and items, "Delivery needs " + label)
    found = {}
    for item in items:
        core.require(isinstance(item, dict) and isinstance(item.get("sha256"), str)
                     and re.fullmatch(r"[0-9a-f]{64}", item["sha256"]), "Invalid " + label + " receipt")
        record = _file(item.get("path"), project, item["sha256"])
        core.require(record["path"] not in found or found[record["path"]] == record, "Conflicting " + label + " receipts")
        found[record["path"]] = record
    return [found[key] for key in sorted(found)]


def _auxiliary(result, project):
    """Bind native report/log files, including explicit adapter result paths."""
    files = {}
    attempt = result.get("attempt_dir")
    if attempt is not None:
        core.require(isinstance(attempt, str) and attempt.strip(), "Invalid native attempt directory")
        root = core.resolve_input(attempt, project)
        core.require(root.is_dir() and root.name == result["attempt_id"], "Native attempt directory does not match attempt_id")
        native_log = result.get("log_path") or str(root / ("unity.log" if result.get("engine") == "unity" else "godot.log"))
        for name in ("native-report.json", "validation.json"):
            record = _file(str(root / name), project)
            files[record["path"]] = record
        record = _file(native_log, project)
        files[record["path"]] = record
        core.require(core.read(root / "validation.json") == result,
                     "Persisted native validation report differs from the journal result")
        native = core.read(root / "native-report.json")
        core.require(isinstance(native, dict), "Native report must be an object")
        for key in ("attempt_id", "scene", "binding_digest"):
            core.require(native.get(key) == result[key], "Native report identity mismatch: " + key)
        core.require(native.get("passed") is True, "Native report did not pass")
    # Adapters may expose separate report paths without using Godot's layout.
    def visit(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in _FILE_KEYS:
                    record = _file(item, project)
                    files[record["path"]] = record
                elif key in ("report", "native_report", "log") and isinstance(item, str):
                    # Treat these ambiguous keys as paths only when explicitly
                    # path-shaped; free-form diagnostic text is not a filename.
                    if item.startswith(("res://", "/", "./", "../")):
                        record = _file(item, project)
                        files[record["path"]] = record
                elif isinstance(item, (dict, list)):
                    visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
    visit(result)
    return [files[key] for key in sorted(files)]


def _manifest(run_dir):
    state, plan = core.load_run(run_dir)
    core.validate_plan(plan)
    core.require(plan.get("purpose", "production") == "production",
                 "H5 is available only for production; fixtures and art proxies are not playable delivery")
    coverage = core.validation_coverage(state, plan)
    core.require(coverage["validation_mode"] == "playable", "H5 requires playable validation")
    core.require(state.get("state") == "validated", "H5 requires a currently validated production run")
    core.require(coverage["scope_complete"], "H5 requires every promised style assembled and validated")
    core.require(coverage["technical_passed"] and coverage["gameplay_passed"],
                 "H5 requires technical and gameplay checks to pass")
    styles = []
    for style in plan["styles"]:
        sid = style["id"]
        artifact = state["artifacts"][sid]
        row = state["validation"][sid]
        result = row["result"]
        core.require(row.get("planHash") == state["planHash"] and row.get("inputHash") == state["inputs"]["sha256"],
                     "Validation belongs to another plan or input version")
        core.require(isinstance(result.get("attempt_id"), str) and result["attempt_id"].strip(),
                     "H5 requires an identified native validation attempt")
        core.require(result.get("scene") == artifact.get("entry_scene")
                     and result.get("binding_digest") == artifact.get("binding_digest")
                     and bool(artifact.get("binding_digest")), "Validation does not match assembled style")
        core.require(not result.get("errors") and not result.get("native_errors")
                     and not result.get("failed_check_ids") and result.get("returncode", 0) == 0,
                     "Native validation contains failures")
        owned = _receipts(artifact.get("owned_files"), state["project"], "owned files")
        sources = _receipts(artifact.get("sources"), state["project"], "source files")
        core.require(_receipts(result.get("artifact_hashes"), state["project"], "validated artifact files") == owned
                     and _receipts(result.get("source_hashes"), state["project"], "validated source files") == sources,
                     "Native validation belongs to another artifact/source version")
        evidence = _receipts(result.get("evidence"), state["project"], "native evidence")
        referenced = [_file(artifact.get(key), state["project"]) for key in ("entry_scene", "manifest", "validator")]
        owned_paths = {item["path"] for item in owned}
        core.require(all(item["path"] in owned_paths for item in referenced),
                     "Assembled scene, manifest and validator must be versioned owned files")
        styles.append({"id": sid, "entry_scene": artifact["entry_scene"],
                       "artifact": copy.deepcopy(artifact), "owned_files": owned, "sources": sources,
                       "validation": copy.deepcopy(row), "native_evidence": evidence,
                       "native_reports": _auxiliary(result, state["project"])})
    return {"schema": 1, "kind": "greybox-playable-art-delivery", "purpose": "production",
            "delivery_mode": plan.get("delivery_mode", "multistyle"),
            "runDir": str(Path(run_dir).resolve()), "project": state["project"],
            "planHash": state["planHash"], "runtimeHash": state["runtime"]["sha256"],
            "inputHash": state["inputs"]["sha256"], "state": state["state"],
            "coverage": coverage, "styles": styles}


def promised_scope(run_dir, manifest=None):
    """A scoped production run never narrows the user's H1/global space promise."""
    manifest = manifest or _manifest(run_dir)
    state, plan = core.load_run(run_dir)
    reference = plan.get('workflow', {})
    checkpoint = _file(reference.get('path'), state['project'], reference.get('sha256'))
    data = core.read(checkpoint['path'])
    selected = set(data.get('selected_styles', []))
    delivered = {style['id'] for style in manifest['styles']}
    core.require(selected and delivered <= selected, 'Delivery styles differ from the approved H1 selection')
    stages = data.get('stages', [])
    missing_spaces = {}
    baseline = next((s for s in stages if s['id'] == 'baseline' and s['scope'] == 'shared'), None)
    if baseline:
        item = next(e for e in baseline['evidence'] if e['role'] == 'spatial_contract')
        path = _file(item['path'], state['project'], item['sha256'])
        spaces = set(core.read(path['path']).get('spatial_scope', {}).get('space_ids', []))
        for sid in delivered:
            stage = next(s for s in stages if s['id'] == 'production_plan' and s['scope'] == sid)
            ref = next(e for e in stage['evidence'] if e['role'] == 'production_table')
            table = core.read(_file(ref['path'], state['project'], ref['sha256'])['path'])
            scope = table.get('production_space_ids') if table.get('scope_mode') == 'expansion' else table.get('sample_contract', {}).get('sample_space_ids')
            # Historical tables did not have a partial-space production scope.
            if scope is not None and spaces - set(scope):
                missing_spaces[sid] = sorted(spaces - set(scope))
    return {'complete': delivered == selected and not missing_spaces,
            'selected_styles': sorted(selected), 'delivered_styles': sorted(delivered),
            'missing_styles': sorted(selected - delivered), 'missing_spaces': missing_spaces,
            'next': 'Complete outstanding styles/spaces and validate a final run using existing canonical assets; do not regenerate them merely to consolidate delivery.'}


def propose_manifest(run_dir):
    """Read-only proposal; callers display it before obtaining actual H5 input."""
    manifest = _manifest(run_dir)
    review = review_status(run_dir, manifest)
    scope = promised_scope(run_dir, manifest)
    return {"ok": True, "manifest": manifest, "manifestHash": core.digest(manifest),
            "handoff_review": review, "delivery_scope": scope,
            "human_reviewable": scope['complete'] and (not review['required'] or review['current']),
            "acceptance": acceptance_status(run_dir)}


def review_inputs(run_dir, manifest=None):
    """Exact final delivery + approved visual targets, without circular review data."""
    from . import workflow, pre_handoff
    manifest = manifest or _manifest(run_dir)
    state, plan = core.load_run(run_dir)
    reference = plan.get('workflow', {})
    path = core.resolve_input(reference.get('path', ''), state['project'])
    core.require(path.is_file() and core.file_hash(path) == reference.get('sha256'),
                 'H5 needs the exact approved workflow checkpoint')
    data = core.read(path)
    required = data.get('production_policy') == workflow.PRODUCTION_POLICY
    artifacts, accepted_samples = {}, {}
    for style in manifest['styles']:
        for record in style['owned_files'] + style['sources'] + style['native_reports'] + style['native_evidence']:
            item = dict(record, role='delivery_file', stage=style['id'])
            if record in style['native_evidence']:
                from .modeling_refs import _decode
                w, h, _, _ = _decode(Path(record['path']).read_bytes())
                item.update(role='native_capture', dimensions=[w, h])
            artifacts[(item['path'], item['sha256'])] = item
        if required:
            # Include actual accepted concepts and spatial/BOM targets for visual comparison.
            target = next(s for s in data['stages'] if s['scope'] == style['id'] and s['id'] == 'production_plan')
            for item in pre_handoff.review_inputs(data, state['project'], target)['artifacts']:
                artifacts[(item['path'], item['sha256'])] = item
            sample = next((s for s in data['stages'] if s['scope'] == style['id']
                           and s['id'] == 'representative_sample' and s.get('status') == 'accepted'), None)
            core.require(sample is not None or reference.get('production_scope') != 'expansion',
                         'Expansion delivery review needs its accepted H4 sample')
            if sample is not None:
                workflow._approval(sample)
                accepted_samples[style['id']] = workflow.stage_digest(sample)
                for item in pre_handoff.review_inputs(data, state['project'], sample)['artifacts']:
                    artifacts[(item['path'], item['sha256'])] = item
                for evidence in sample['evidence']:
                    if evidence['role'] == 'visual_review':
                        item = dict(_file(evidence['path'], state['project'], evidence['sha256']),
                                    role='accepted_sample_judgment', stage=style['id'] + '/representative_sample')
                        artifacts[(item['path'], item['sha256'])] = item
    result = {'schema': 1, 'kind': 'pre-handoff-review-inputs', 'stage': 'delivery',
              'manifestHash': core.digest(manifest), 'workflow_sha256': reference['sha256'],
              'accepted_sample_digests': accepted_samples,
              'required': required, 'criteria': ['promised_scope_and_style', 'whole_native_composition',
                  'gameplay_and_performance_evidence', 'remaining_defects_and_delivery'],
              'artifacts': sorted(artifacts.values(), key=lambda a: (a['stage'], a['role'], a['path']))}
    result['input_digest'] = core.digest(result)
    return result


def record_review(run_dir, document):
    """Record a real reviewer result; this never supplies a human acceptance."""
    from .pre_handoff import validate_review_receipt
    core.require(isinstance(document, dict), 'Delivery review must be an object')
    with core.locked(run_dir):
        inputs = review_inputs(run_dir)
        validate_review_receipt(document.get('receipt'), inputs, document.get('producer'))
        state, _ = core.load_run(run_dir)
        state['deliveryReview'] = copy.deepcopy(document)
        core.save_run(run_dir, state)
    return {'ok': True, **review_status(run_dir)}


def review_status(run_dir, manifest=None):
    from .pre_handoff import validate_review_receipt
    inputs = review_inputs(run_dir, manifest)
    if not inputs['required']:
        return {'required': False, 'current': False, 'mode': 'historical-policy'}
    try:
        state, _ = core.load_run(run_dir)
        document = state.get('deliveryReview', {})
        checked = validate_review_receipt(document.get('receipt'), inputs, document.get('producer'))
        return {'required': True, 'current': True, 'review_digest': core.digest(document), **checked}
    except (core.WorkflowError, ValueError, TypeError, KeyError) as error:
        return {'required': True, 'current': False, 'reason': str(error)}


def accept(run_dir, actor, source_ref, note, manifest_hash):
    """Persist an actual user decision for the exact manifest they reviewed."""
    core.require(actor == "user", "H5 requires the actual user's decision")
    core.require(isinstance(source_ref, str) and source_ref.strip(), "H5 requires the actual user message/source reference")
    core.require(isinstance(note, str) and note.strip(), "H5 requires the user's art/playability/performance acceptance note")
    core.require(isinstance(manifest_hash, str) and re.fullmatch(r"[0-9a-f]{64}", manifest_hash),
                 "H5 needs the reviewed manifestHash")
    with core.locked(run_dir):
        manifest = _manifest(run_dir)
        scope = promised_scope(run_dir, manifest)
        core.require(scope['complete'], 'H5 requires all H1-selected styles and promised spaces; this run is a partial production result')
        core.require(core.digest(manifest) == manifest_hash, "Delivery changed since review; present the current manifest for H5")
        reviewed = review_status(run_dir, manifest)
        core.require(not reviewed['required'] or reviewed['current'], 'Complete the current independent delivery review before H5')
        state, plan = core.load_run(run_dir)
        state["deliveryAcceptance"] = {"schema": 1, "kind": "human-delivery-acceptance",
            "actor": actor, "decision": "accepted", "source_ref": source_ref,
            "note": note, "recordedAt": core.now(), "manifestHash": manifest_hash,
            "manifest": manifest, "review_digest": reviewed.get('review_digest')}
        core.save_run(run_dir, state)
        if plan.get("workspace"):
            from . import layout
            receipt = state["deliveryAcceptance"]
            receipt_path = Path(run_dir) / "navigation-receipts" / ("h5-" + manifest_hash + ".json")
            if not receipt_path.exists():
                core.write(receipt_path, receipt)
            else:
                core.require(core.read(receipt_path).get("manifestHash") == manifest_hash,
                             "Existing H5 navigation proof conflicts with accepted version")
            for style in manifest["styles"]:
                files = style["owned_files"] + style["sources"] + style["native_evidence"] + style["native_reports"]
                layout.update_pointer(state["project"], plan, style["id"], "user_accepted", style["entry_scene"],
                                      files, state["planHash"], proof={"path": str(receipt_path), "sha256": core.file_hash(receipt_path)})
    return {"ok": True, **acceptance_status(run_dir)}


def acceptance_status(run_dir, state=None, plan=None):
    """Read-only H5 state; never calls core.status or refreshes capabilities."""
    try:
        if state is None:
            state, _ = core.load_run(run_dir, check_inputs=False)
        receipt = state.get("deliveryAcceptance")
        if not receipt:
            try:
                manifest = _manifest(run_dir)
                scope = promised_scope(run_dir, manifest)
                return {"status": "pending", "accepted": False, "manifestHash": core.digest(manifest),
                        "scope_complete": scope['complete'],
                        "reason": "Awaiting actual user H5 review" if scope['complete'] else "Complete remaining H1 styles/spaces before final H5"}
            except (core.WorkflowError, OSError, ValueError, KeyError, TypeError) as error:
                return {"status": "pending", "accepted": False, "reviewable": False, "reason": str(error)}
        core.require(isinstance(receipt, dict) and receipt.get("kind") == "human-delivery-acceptance"
                     and receipt.get("actor") == "user" and receipt.get("decision") == "accepted"
                     and isinstance(receipt.get("source_ref"), str) and receipt["source_ref"].strip()
                     and isinstance(receipt.get("note"), str) and receipt["note"].strip(),
                     "Stored H5 is not an actual version-bound user decision")
        core.require(isinstance(receipt.get("manifest"), dict)
                     and core.digest(receipt["manifest"]) == receipt.get("manifestHash"), "Stored H5 manifest is corrupt")
        manifest = _manifest(run_dir)
        core.require(promised_scope(run_dir, manifest)['complete'], 'H5 no longer covers all promised styles/spaces')
        current_hash = core.digest(manifest)
        core.require(current_hash == receipt["manifestHash"], "Delivery changed after H5; a new user decision is required")
        reviewed = review_status(run_dir, manifest)
        core.require(not reviewed['required'] or reviewed['current'] and
                     receipt.get('review_digest') == reviewed.get('review_digest'), 'Delivery review changed after H5')
        return {"status": "current", "accepted": True, "manifestHash": current_hash,
                "actor": receipt["actor"], "source_ref": receipt["source_ref"], "note": receipt["note"],
                "recordedAt": receipt.get("recordedAt")}
    except (core.WorkflowError, OSError, ValueError, KeyError, TypeError) as error:
        return {"status": "stale", "accepted": False, "reason": str(error)}
