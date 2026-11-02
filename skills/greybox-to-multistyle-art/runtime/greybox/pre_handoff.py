"""Small, read-only review input/receipt checks; never manufacture a review.

Hashes establish scope and freshness, not that an actor actually inspected pixels.
The host is responsible for truthful actor IDs, observations and user decisions.
"""
from __future__ import annotations
from .core import require, digest, read, file_hash, resolve_input, inside, safe_id

CRITERIA = {
    'directions': ('actual_concepts', 'substantive_differences', 'gameplay_space_constraints'),
    'atlas': ('key_spaces_transitions', 'style_and_landmark_consistency', 'gameplay_space_constraints'),
    'spatial_design': ('spatial_relationships_interfaces', 'whole_composition', 'gameplay_space_constraints'),
    'production_plan': ('visual_route_responsibility', 'bom_and_assembly_readable', 'complete_sample_scope', 'references_and_budget'),
    'representative_sample': ('concept_shape_material_depth', 'whole_native_composition', 'contact_and_gameplay_states'),
}
IMAGE_ROLES = {'concept_image', 'native_capture', 'bom_board', 'assembly_map', 'proxy_capture'}
ADMIN_FIELDS = {'status', 'actor', 'recorded_by', 'decision_note', 'approval', 'authorization', 'review'}


def review_stage_content(stage):
    value = {k: v for k, v in stage.items() if k not in ADMIN_FIELDS}
    # The H4 human judgment is recorded after independent review. It remains in
    # stage_digest and is validated separately; it cannot circularly bind review.
    value['evidence'] = [e for e in stage.get('evidence', []) if e.get('role') != 'visual_review']
    return value


def review_inputs(data, project, stage):
    """Build exact current review inputs, without writing an acceptance receipt."""
    from .workflow import stage_digest, sample_context
    require(stage.get('id') in CRITERIA, 'Stage does not have a pre-handoff review')
    if stage['id'] == 'representative_sample':
        # A later, separately approved H2 may add regions. Keep the accepted
        # sample's review bound to its original small frozen context; current
        # production_plan review continues to consume the current H2 instead.
        data = sample_context(data, project, stage['scope'])
    index = {s['scope'] + '/' + s['id']: s for s in data.get('stages', [])}
    if stage['id'] == 'representative_sample':
        sources = [e for e in stage.get('evidence', []) if e.get('role') == 'sample_source_production']
        require(len(sources) == 1, 'H4 review needs original sample production evidence')
        source_path = resolve_input(sources[0]['path'], project)
        require(inside(source_path, project) and source_path.is_file()
                and file_hash(source_path) == sources[0]['sha256'], 'Archived sample review input changed')
        source = read(source_path)
        index[source['scope'] + '/' + source['id']] = source
    artifacts, seen = {}, set()

    def visit(value, current=False):
        key = value['scope'] + '/' + value['id']
        require(key not in seen, 'Cyclic review dependency')
        seen.add(key)
        for dependency, expected in value.get('consumes', {}).items():
            parent = index.get(dependency)
            require(parent is not None and stage_digest(parent) == expected, 'Review has stale upstream dependency: ' + dependency)
            if dependency not in seen:
                visit(parent)
        selected_hash = None
        if value['id'] == 'directions' and stage['scope'] != 'shared':
            manifests = [e for e in value['evidence'] if e['role'] == 'directions_manifest']
            require(len(manifests) == 1, 'Review needs directions manifest')
            candidates = read(resolve_input(manifests[0]['path'], project)).get('candidates', [])
            selected_hash = next((c.get('concept_sha256') for c in candidates if c.get('id') == stage['scope']), None)
            require(selected_hash, 'Review scope has no selected direction')
        for item in value.get('evidence', []):
            if item['role'] == 'visual_review':
                continue
            if selected_hash and item['role'] == 'concept_image' and item['sha256'] != selected_hash:
                continue
            path = resolve_input(item['path'], project)
            require(inside(path, project) and path.is_file() and file_hash(path) == item['sha256'],
                    'Review artifact missing/changed/outside project')
            record = {'path': str(path), 'sha256': item['sha256'], 'role': item['role'], 'stage': key}
            if item['role'] in IMAGE_ROLES:
                from .modeling_refs import _decode
                w, h, _, _ = _decode(path.read_bytes())
                record['dimensions'] = [w, h]
            artifacts[(str(path), item['sha256'])] = record
            if item['role'] == 'production_table':
                reference = read(path).get('modeling_references')
                if reference:
                    package_path = resolve_input(reference.get('path', ''), project)
                    require(inside(package_path, project) and package_path.is_file()
                            and file_hash(package_path) == reference.get('sha256'), 'Review modeling-reference package changed')
                    from .modeling_refs import validate_package, _decode
                    from .workflow import _image
                    validated = validate_package(read(package_path), project)
                    # Crop validation already decoded the immutable board under
                    # its separate 32MP limit. Do not apply the 8MP master limit
                    # to the source board or repeatedly decode it for dimensions.
                    boards = {(b['path'], b['sha256']): b['dimensions'] for b in validated.get('boards', [])}
                    for dependency in [{'path': str(package_path), 'sha256': reference['sha256']}, *validated['dependencies']]:
                        dep_path = resolve_input(dependency['path'], project)
                        dep = dict(dependency, role='modeling_reference_dependency', stage=key)
                        board_size = boards.get((str(dep_path), dependency['sha256']))
                        if board_size is not None:
                            dep.update(role='modeling_reference_board', dimensions=board_size)
                        elif _image(dep_path):
                            w, h, _, _ = _decode(dep_path.read_bytes())
                            dep.update(role='modeling_reference', dimensions=[w, h])
                        artifacts[(str(dep_path), dependency['sha256'])] = dep
    visit(stage, True)
    result = {'schema': 1, 'kind': 'pre-handoff-review-inputs', 'stage': stage['scope'] + '/' + stage['id'],
              'stage_content': review_stage_content(stage), 'criteria': list(CRITERIA[stage['id']]),
              'artifacts': sorted(artifacts.values(), key=lambda a: (a['stage'], a['role'], a['path']))}
    if stage['id'] == 'production_plan':
        tables = [a for a in result['artifacts'] if a['stage'] == result['stage'] and a['role'] == 'production_table']
        if len(tables) == 1:
            declaration = read(tables[0]['path']).get('sample_contract', {}).get('scene_comparison')
            if declaration is not None:
                result['scene_comparison_contract'] = declaration
    result['input_digest'] = digest(result)
    result['note'] = 'Inputs only; inspect actual images and record a separate truthful review. No approval or successful review is implied.'
    return result


def validate_review_receipt(receipt, inputs, producer):
    require(isinstance(producer, dict) and safe_id(producer.get('agent_id')) and safe_id(producer.get('task_id')),
            'Review target needs producer agent_id/task_id')
    require(isinstance(receipt, dict) and receipt.get('schema') == 1 and receipt.get('kind') == 'pre-handoff-review',
            'Missing pre-handoff review receipt')
    require(receipt.get('input_digest') == inputs['input_digest'], 'Pre-handoff review is stale for current inputs')
    reviewer = receipt.get('reviewer', {})
    require(isinstance(reviewer, dict) and safe_id(reviewer.get('agent_id')) and safe_id(reviewer.get('task_id'))
            and isinstance(receipt.get('source_ref'), str) and receipt['source_ref'].strip(),
            'Review needs actual reviewer/task identity and source_ref')
    mode = receipt.get('independence')
    require(mode in {'independent', 'unverified_serial'}, 'Review must declare its actual independence')
    if mode == 'independent':
        require(reviewer['agent_id'] != producer['agent_id'] and reviewer['task_id'] != producer['task_id'],
                'Producer cannot claim an independent review of its own output')
    else:
        require(isinstance(receipt.get('limitation'), str) and receipt['limitation'].strip(),
                'Serial fallback must expose unavailable independent reviewer and its limitation')
    artifacts = {(a['path'], a['sha256']) for a in inputs['artifacts']}
    required_images = {(a['path'], a['sha256']) for a in inputs['artifacts'] if 'dimensions' in a}
    examined = receipt.get('examined_images')
    require(isinstance(examined, list) and all(isinstance(e, dict) for e in examined), 'Review needs actual examined image hashes')
    examined_set = {(e.get('path'), e.get('sha256')) for e in examined}
    require(required_images and required_images <= examined_set and examined_set <= artifacts,
            'Review must cover the actual required images, not just a producer summary')
    coverage = receipt.get('coverage')
    require(isinstance(coverage, list) and all(isinstance(c, dict) for c in coverage), 'Review needs criterion coverage')
    require(len(coverage) == len(inputs['criteria']) and {c.get('id') for c in coverage} == set(inputs['criteria']),
            'Review is missing required criterion coverage')
    for check in coverage:
        require(check.get('status') == 'satisfied' and isinstance(check.get('note'), str) and check['note'].strip(),
                'Pre-handoff criterion is unresolved: ' + str(check.get('id')))
        links = check.get('evidence')
        require(isinstance(links, list) and links and all(isinstance(e, dict) and
                (e.get('path'), e.get('sha256')) in artifacts for e in links), 'Review criterion needs bound evidence')
    from .scene_review import validate_criterion_roles
    validate_criterion_roles(receipt, inputs)
    findings = receipt.get('findings')
    require(isinstance(findings, list) and all(isinstance(f, dict) for f in findings), 'Review findings must be explicit')
    for finding in findings:
        require(safe_id(finding.get('id')) and finding.get('severity') in {'blocker', 'repair', 'preference'}
                and finding.get('status') in {'resolved', 'open', 'deferred'} and isinstance(finding.get('note'), str)
                and finding['note'].strip(), 'Review finding needs identity, severity, status and note')
        require(finding['severity'] == 'preference' or finding['status'] == 'resolved',
                'Pre-handoff review has an unresolved blocker/repair')
    unreviewed = receipt.get('unreviewed')
    require(isinstance(unreviewed, list) and all(isinstance(item, dict)
            and item.get('outside_required_scope') is True and isinstance(item.get('scope'), str)
            and item['scope'].strip() and isinstance(item.get('reason'), str) and item['reason'].strip()
            for item in unreviewed), 'Unreviewed areas must be explicit and outside required pre-handoff scope')
    return {'independence': mode, 'input_digest': inputs['input_digest']}
