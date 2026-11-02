"""Synthetic schema2 receipts for OFFLINE unit tests only.

No image generation, game execution, human decision, production approval or
artistic validation occurs here. Deliberately tiny colored PNGs exercise byte
binding only. Fixtures must never be promoted to accepted production evidence.
"""
import copy
import json
import struct
import zlib
from pathlib import Path
from greybox import core, workflow

_CONTEXTS = {}


def png(index=0):
    def chunk(kind, value):
        return struct.pack('!I', len(value)) + kind + value + struct.pack('!I', zlib.crc32(kind + value))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!IIBBBBB', 1, 1, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(bytes([0, index % 256, (index * 17) % 256, (index * 53) % 256])))
            + chunk(b'IEND', b''))


def capabilities(session='test-session'):
    result = {'schema': 2, 'session_id': session, 'checked_at': core.now(), 'capabilities': {}}
    for key in ('engine', 'native_capture', 'image_generate', 'lux'):
        result['capabilities'][key] = {
            'status': 'available', 'interface': 'offline-test-double', 'evidence': 'SYNTHETIC TEST ONLY',
            'channel': {'kind': 'bundled_openapi' if key == 'lux' else 'host_tool',
                        'target': 'greybox.lux' if key == 'lux' else 'synthetic.' + key,
                        'region': 'cn', 'supports': ['text_to_image', 'reference_image', 'screenshot']},
            'verification': {'level': 'connection_verified', 'evidence': 'SYNTHETIC TEST ONLY'}}
    return result


def evidence(project, name, role, value, image_id=None):
    p = Path(project) / 'art/workflow' / name
    p.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(value, bytes):
        p.write_bytes(value)
    else:
        core.write(p, value)
    e = {'role': role, 'path': str(p), 'sha256': core.file_hash(p)}
    if image_id:
        e.update(id=image_id, origin='user_provided', provenance_note='SYNTHETIC OFFLINE TEST ONLY')
    return e


def review_fixture(stage):
    """SYNTHETIC review only: never use for actual approval or artistic evidence."""
    from greybox.pre_handoff import CRITERIA, review_inputs
    if stage["id"] not in CRITERIA:
        return
    project = Path(stage["evidence"][0]["path"]).parents[2]
    data = _CONTEXTS[str(project)]
    stage["producer"] = {"agent_id": "synthetic-producer", "task_id": "synthetic-production-task"}
    try:
        inputs = review_inputs(data, project, stage)
    except core.WorkflowError:
        return  # Negative fixtures deliberately retain an invalid/stale review.
    artifacts = [{k: a[k] for k in ("path", "sha256")} for a in inputs["artifacts"]]
    stage["review"] = {"schema": 1, "kind": "pre-handoff-review", "input_digest": inputs["input_digest"],
        "reviewer": {"agent_id": "synthetic-reviewer", "task_id": "synthetic-review-task"},
        "source_ref": "synthetic://offline-not-a-real-review", "independence": "independent",
        "examined_images": [{k: a[k] for k in ("path", "sha256")} for a in inputs["artifacts"] if "dimensions" in a],
        "coverage": [{"id": c, "status": "satisfied", "note": "SYNTHETIC TEST ONLY", "evidence": artifacts[:1]} for c in inputs["criteria"]],
        "findings": [], "unreviewed": []}


def approve(stage):
    """Mock a new user decision for this exact fixture, never actual authority."""
    review_fixture(stage)
    stage['actor'] = 'user'
    stage['approval'] = {'actor': 'user', 'decision': 'accepted', 'source_ref': 'synthetic://test-only-user-message',
                         'scope': stage['scope'] + '/' + stage['id'], 'stage_digest': workflow.stage_digest(stage)}


def refresh_evidence(stage, role, data):
    item = next(e for e in stage['evidence'] if e['role'] == role)
    core.write(item['path'], data)
    item['sha256'] = core.file_hash(item['path'])
    return item


def synthetic_glb_bytes(identity='fixture'):
    """Structurally valid empty GLB for dependency tests, not a useful model."""
    doc = json.dumps({'asset': {'version': '2.0', 'generator': 'synthetic-offline-fixture'},
                      'scenes': [{}], 'scene': 0, 'extras': {'identity': identity}}).encode()
    doc += b' ' * (-len(doc) % 4)
    return struct.pack('<4sIII4s', b'glTF', 2, 20 + len(doc), len(doc), b'JSON') + doc


def synthetic_model_bindings(project, plan, table, inputs, prefix):
    """Tiny fake terminal ledgers for OFFLINE checks; never supplier evidence."""
    generated = [a for a in table['asset_proposals'] if a['route'] in {'generated', 'hybrid'}]
    inputs['model_task_bindings'] = []
    if not generated:
        return
    run = Path(project) / 'art/workflow' / (prefix + 'synthetic-model-run')
    run.mkdir(parents=True, exist_ok=True)
    frozen = copy.deepcopy(plan)
    portable = 'options' in plan
    if portable:
        from greybox import image_policy, suppliers
        option = plan['options'][0]
        registry = {'providers': [{'id': provider} for provider in sorted({o['provider'] for o in option['operations']})]}
        selection = {'synthetic_test_only': True}
        state = {'schema': 1, 'kind': 'supplier-job-run', 'project': str(project),
            'portfolio_digest': core.digest(plan), 'registry_digest': suppliers.registry_digest(registry),
            'selection_digest': core.digest(selection), 'selected_option': option['id'],
            'operations': {o['id']: {'state': 'pending'} for o in option['operations']},
            'inputs': {o['id']: image_policy.image_inputs(o, project) for o in option['operations']}}
        if 'workspace' in plan:
            state['workspace'] = plan['workspace']
        for name, value in [('supplier-portfolio.json', plan), ('supplier-registry.json', registry),
                            ('supplier-selection.json', selection)]:
            core.write(run / name, value)
    else:
        state = {'schema': 1, 'kind': 'greybox-art-run', 'project': str(project),
                 'planHash': core.digest(frozen), 'assets': {}}
        core.write(run / 'plan.frozen.json', frozen)
    for asset in generated:
        aid = asset['asset_id']
        model = run / (aid + '.glb')
        model.write_bytes(synthetic_glb_bytes(aid))
        record = {'path': str(model), 'sha256': core.file_hash(model)}
        binding = {'asset_id': aid, 'run_dir': str(run), 'task_id': 'synthetic-task-' + aid,
                   'source_output': record, 'realized_output': record}
        if portable:
            operation = next(o for o in option['operations'] if o['asset_id'] == aid and
                             o['operation'] in {'image_to_3d', 'multiview_to_3d'})
            state['operations'][operation['id']] = {'state': 'ready', 'task_id': binding['task_id'], 'artifacts': [record]}
            binding['operation_id'] = operation['id']
        else:
            state['assets'][aid] = {'state': 'ready', 'taskId': binding['task_id'], 'artifact': record}
        inputs['files'].append({'id': 'synthetic-model-' + aid, **record, 'category': 'asset'})
        inputs['model_task_bindings'].append(binding)
    core.write(run / ('supplier-run.json' if portable else 'run.json'), state)
    # Actual scene edges, rather than a file list, bind the synthetic GLBs to
    # this offline sample. They remain empty test models, never engine evidence.
    scene = core.resolve_input(inputs['scene'], project)
    text = scene.read_text()
    declarations, nodes = [], []
    for binding in inputs['model_task_bindings']:
        aid = binding['asset_id']
        resource = 'res://' + Path(binding['realized_output']['path']).relative_to(project).as_posix()
        declarations.append('[ext_resource type="PackedScene" path="' + resource + '" id="synthetic-model-' + aid + '"]')
        nodes.append('[node name="SyntheticModel_' + aid + '" parent="." instance=ExtResource("synthetic-model-' + aid + '")]')
    position = text.index('[node ')
    text = text[:position] + '\n'.join(declarations) + '\n' + text[position:] + '\n' + '\n'.join(nodes) + '\n'
    scene.write_text(text)
    for record in inputs['files']:
        if core.resolve_input(record['path'], project) == scene:
            record['sha256'] = core.file_hash(scene)


def make_workflow(project, plan, expansion=False, expanded_plan=None, candidate_count=8,
                  sample_space_ids=None, expansion_space_ids=None, observation_views=None, selected_styles=None,
                  initialize_control=True):
    from workspace_fixtures import attach_workspace
    attach_workspace(plan)
    if expanded_plan is not None:
        attach_workspace(expanded_plan, plan['workspace']['case_id'])
    plan = copy.deepcopy(plan)
    if plan.get('purpose') == 'technical_fixture':
        plan.pop('purpose')
    plan_hash = workflow.execution_plan_digest(plan)
    current_hash = workflow.execution_plan_digest(expanded_plan) if expanded_plan is not None else plan_hash
    styles = [s['id'] for s in plan['styles']]
    all_styles = list(selected_styles) if selected_styles is not None else styles
    assert set(styles) <= set(all_styles), 'Synthetic active styles must belong to global H1'
    data = {'schema': 2, 'kind': 'greybox-art-workflow', 'selected_styles': all_styles,
            'requires_lux': bool(any(a.get('generation') for a in plan.get('assets', []))),
            'concept_source': 'generate', 'production_policy': workflow.PRODUCTION_POLICY, 'stages': []}
    _CONTEXTS[str(Path(project))] = data
    index, digests = {}, {}

    def add(sid, scope, items, **fields):
        stage = {'id': sid, 'scope': scope, 'revision': 1, 'status': 'accepted', 'actor': 'agent',
                 'decision_note': 'SYNTHETIC TEST ONLY; not an actual user or art decision',
                 'consumes': {k: digests[k] for k in workflow.dependencies(sid, scope)},
                 'evidence': items, **fields}
        data['stages'].append(stage)
        if sid in workflow.HUMAN_STAGES:
            approve(stage)
        else:
            review_fixture(stage)
        index[(scope, sid)] = stage
        digests[scope + '/' + sid] = workflow.stage_digest(stage)
        return stage

    add('preflight', 'shared', [evidence(project, 'capabilities.json', 'capability_report', capabilities())])
    baseline = copy.deepcopy(plan['contract'])
    baseline.setdefault('spatial_scope', {'mode': 'finite', 'space_ids': ['start', 'end'],
        'transition_ids': ['connector'], 'segments': []})
    baseline['observations'] = {'views': copy.deepcopy(observation_views) if observation_views is not None else [
        {'id': 'overview', 'camera_id': 'test-camera', 'state_id': 'playing', 'framing': 'whole_composition',
         'space_ids': ['start', 'end'], 'required_layers': sorted(workflow.COMPOSITION_LAYERS)}],
        'risk_ids': ['support-clearance']}
    sample_spaces = list(sample_space_ids or ['start', 'end'])
    sample_views = [v for v in baseline['observations']['views'] if set(sample_spaces) & set(v['space_ids'])]
    add('baseline', 'shared', [evidence(project, 'baseline.json', 'spatial_contract', baseline),
                              evidence(project, 'baseline-native.json', 'native_baseline', {'synthetic_test_only': True})])
    candidates, images = [], []
    candidate_ids = all_styles + ['extra-' + str(i) for i in range(max(0, candidate_count - len(all_styles)))]
    for i, sid in enumerate(candidate_ids):
        item = evidence(project, sid + '-direction.png', 'concept_image', png(i + 1), sid + '-concept')
        images.append(item)
        candidates.append({'id': sid, 'concept_image_id': item['id'], 'concept_sha256': item['sha256'],
                           'brief': {key: f'SYNTHETIC {sid} {key}' for key in (
                               'theme', 'shape_language', 'material_language', 'spatial_composition', 'functional_identity', 'light_palette')}})
    directions = {'schema': 2, 'kind': 'direction-manifest', 'candidates': candidates}
    if not 8 <= len(candidates) <= 10:
        directions['count_override'] = {'actor': 'user', 'decision': 'accepted', 'source_ref': 'synthetic://test-only-count-override',
                                       'scope': 'shared/directions', 'candidate_set_digest': core.digest(candidates), 'reason': 'SYNTHETIC TEST ONLY'}
    add('directions', 'shared', images + [evidence(project, 'directions.json', 'directions_manifest', directions)])
    selected = [{'style_id': c['id'], 'concept_image_id': c['concept_image_id'], 'concept_sha256': c['concept_sha256']}
                for c in candidates if c['id'] in all_styles]
    add('selection', 'shared', [evidence(project, 'selection.json', 'selection_decision', {
        'schema': 2, 'kind': 'style-selection', 'directions_digest': digests['shared/directions'], 'selected': selected})])
    checks = plan['contract']['validation'].get('required_checks', [s.get('id', s.get('name'))
               for s in plan['contract']['validation']['steps'] if s.get('expect')])
    for i, sid in enumerate(styles):
        candidate = next(c for c in candidates if c['id'] == sid)
        image = evidence(project, sid + '-atlas.png', 'concept_image', png(100 + i), sid + '-atlas-image')
        atlas = {'schema': 2, 'kind': 'concept-atlas', 'style_id': sid, 'direction_concept_sha256': candidate['concept_sha256'],
                 'required_space_ids': ['start', 'end'], 'required_transition_ids': ['connector'],
                 'views': [{'id': 'connected-view', 'concept_image_id': image['id'], 'concept_sha256': image['sha256'],
                            'camera_id': 'test-camera', 'role': 'transition', 'transition_id': 'connector', 'space_ids': ['start', 'end']}]}
        add('atlas', sid, [image, evidence(project, sid + '-atlas.json', 'atlas_manifest', atlas)])
        graph = {'schema': 2, 'style_id': sid, 'atlas_digest': digests[sid + '/atlas'],
                 'space_ids': ['start', 'end'], 'transition_ids': ['connector'],
                 'space_designs': [{'space_id': space, **{key: 'SYNTHETIC ' + space + ' ' + key for key in
                     ('art_intent', 'gameplay_invariants', 'visual_freedom', 'foreground', 'midground', 'background')}}
                     for space in ['start', 'end']],
                 'boundaries': [{'id': 'connector', 'from_space_id': 'start', 'to_space_id': 'end',
                                 'continuity_rule': 'SYNTHETIC support seams and continuous material transition'}]}
        add('spatial_design', sid, [evidence(project, sid + '-graph.json', 'spatial_graph', graph),
            evidence(project, sid + '-plan.json', 'plan_view', {'synthetic_test_only': True}),
            evidence(project, sid + '-section.json', 'section_or_volume', {'synthetic_test_only': True})])
        proxy_images, proxy_captures = [], []
        for number, view in enumerate(baseline['observations']['views']):
            proxy_capture = evidence(project, sid + '-proxy-' + str(number) + '.png', 'proxy_capture',
                png(140 + i * 10 + number), sid + '-proxy-image-' + str(number))
            proxy_images.append(proxy_capture)
            proxy_captures.append({**{k: proxy_capture[k] for k in ('path', 'sha256')}, 'image_id': proxy_capture['id'],
                'view_id': view['id'], **{k: view[k] for k in ('camera_id', 'state_id', 'framing')},
                'visible_layers': view['required_layers'], 'missing_layers': []})
        proxy_manifest = {'schema': 1, 'kind': 'composition-probe', 'scope': sid, 'purpose': 'risk_and_composition_only',
            'captures': proxy_captures}
        add('art_proxy', sid, [*proxy_images, evidence(project, sid + '-proxy.json', 'native_proxy', proxy_manifest),
            evidence(project, sid + '-risks.json', 'risk_review', {'risks': [{'id': 'support-clearance', 'status': 'resolved', 'observation': 'SYNTHETIC safe envelope'}]})])
        contract = {'style_id': sid, 'baseline_scene': plan['contract']['scene'],
                    'scene': 'res://art/workflow/native-' + sid + '.tscn', 'input_digest': core.digest({'synthetic_known_h3_contract': sid}),
                    'execution_plan_digest': plan_hash, 'required_technical_checks': sorted(workflow.TECHNICAL_CHECKS),
                    'required_gameplay_checks': checks, 'required_critical_features': ['landmark-shape', 'material-language'],
                    'required_view_ids': [v['id'] for v in sample_views], 'sample_space_ids': sample_spaces, 'required_composition_layers': sorted(workflow.COMPOSITION_LAYERS)}
        proposals = [{'asset_id': a['id'], 'route': a.get('route', 'generated'),
                      'reason': 'SYNTHETIC task-specific source choice',
                      **({'generation': copy.deepcopy(a['generation'])} if a.get('generation') else {})}
                     for a in plan.get('assets', [])]
        proposals += [{'asset_id': b['id'], 'route': b.get('source', {}).get('route', 'procedural'),
                       'reason': 'SYNTHETIC existing binding source choice'} for b in plan.get('bindings', [])
                      if not b.get('source', {}).get('asset_id')]
        table = {'schema': 2, 'kind': 'production-table', 'style_id': sid, 'execution_plan_digest': plan_hash,
                 'asset_route_contract': 'asset-routes-v1',
                 'sample_contract': contract, 'asset_proposals': proposals, 'scope_mode': 'complete_sample',
                 'visual_features': [{'id': feature, 'concept_view_id': 'connected-view', 'importance': 'dominant',
                     'responsibility': 'appearance', 'feature_kind': 'form', 'target': 'SYNTHETIC rule-expressible geometric fixture',
                     'asset_ids': [a['asset_id'] for a in proposals], 'native_view_ids': contract['required_view_ids']}
                     for feature in contract['required_critical_features']]}
        for proposal in proposals:
            proposal['route_evaluation'] = {route: 'SYNTHETIC considered ' + route for route in ('generated', 'reuse', 'procedural')}
            proposal['procedural_visual_match'] = {'reason': 'SYNTHETIC approved simple geometric form',
                'evidence_image_id': sid + '-bom-image', 'observed_match': 'SYNTHETIC TEST ONLY'}
            if proposal['route'] == 'hybrid':
                proposal.update(generated_visual_role='SYNTHETIC silhouette', controlled_structure_role='SYNTHETIC support')
        generated = [a['asset_id'] for a in proposals if a.get('generation')]
        if generated:
            from modeling_ref_fixtures import write_reference_package
            package = write_reference_package(project, generated, style_id=sid,
                                               selected_concept_sha256=candidate['concept_sha256'])
            table['modeling_references'] = package
        recipe = {'schema': 2, 'kind': 'assembly-recipe', 'style_id': sid, 'execution_plan_digest': plan_hash,
                  'spatial_design_digest': digests[sid + '/spatial_design'], 'assemblies': [
                      {'id': 'assemble-' + a['asset_id'], 'asset_ids': [a['asset_id']], 'space_ids': list(sample_spaces),
                       'anchor_and_support': 'SYNTHETIC stable base support anchor',
                       'scale_and_fit': 'SYNTHETIC uniform visual fit within playable envelope',
                       'material_and_lighting': 'SYNTHETIC shared calibrated roughness and lighting',
                       'seam_integration': 'SYNTHETIC contact and seam treatment', 'depends_on': []}
                      for a in proposals]}
        table['composition_owners'] = {layer: [recipe['assemblies'][0]['id']] for layer in workflow.COMPOSITION_LAYERS}
        scope_decision = {'style_id': sid, 'execution_plan_digest': plan_hash}
        visual_items = [evidence(project, sid + '-bom.png', 'bom_board', png(160 + i), sid + '-bom-image'),
            evidence(project, sid + '-map.png', 'assembly_map', png(170 + i), sid + '-map-image'),
            evidence(project, sid + '-visual-package.json', 'visual_package', {
                'schema': 1, 'kind': 'production-visual-package', 'style_id': sid,
                'bom': [{'asset_id': a['asset_id'], 'image_id': sid + '-bom-image', 'region': [0, 0, 1, 1],
                    'reference_status': 'production_ready' if a['route'] in {'generated', 'hybrid'} else 'approved_reuse' if a['route'] == 'reuse' else 'procedural_design'} for a in proposals],
                'assembly_annotations': [{'assembly_id': a['id'], 'asset_ids': a['asset_ids'],
                    'image_id': sid + '-map-image', 'region': [0, 0, 1, 1]} for a in recipe['assemblies']]})]
        stage = add('production_plan', sid, [evidence(project, sid + '-table.json', 'production_table', table),
                    evidence(project, sid + '-recipe.json', 'assembly_recipe', recipe),
                    evidence(project, sid + '-scope.json', 'scope_decision', scope_decision)] + visual_items)
        if expansion:
            source = copy.deepcopy(stage)
            source_digest = workflow.stage_digest(source)
            source_evidence = evidence(project, sid + '-sample-source.json', 'sample_source_production', source)
            table = copy.deepcopy(table)
            table['execution_plan_digest'] = current_hash
            table['sample_contract']['source_production_digest'] = source_digest
            table['scope_mode'] = 'expansion'
            table['production_space_ids'] = list(expansion_space_ids or sample_spaces)
            table['production_view_ids'] = [v['id'] for v in baseline['observations']['views']
                if set(table['production_space_ids']) & set(v['space_ids'])]
            for feature in table['visual_features']:
                feature['native_view_ids'] = table['production_view_ids']
            for unit in recipe['assemblies']:
                unit['space_ids'] = table['production_space_ids']
            recipe['execution_plan_digest'] = current_hash
            scope_decision['execution_plan_digest'] = current_hash
            stage['revision'] += 1
            stage['evidence'] = [evidence(project, sid + '-expansion-table.json', 'production_table', table),
                                evidence(project, sid + '-expansion-recipe.json', 'assembly_recipe', recipe),
                                evidence(project, sid + '-expansion-scope.json', 'scope_decision', scope_decision)] + visual_items
            approve(stage)
            digests[sid + '/production_plan'] = workflow.stage_digest(stage)
            # Actual sample products become known only at H4; no H3 approval is
            # rewritten to predict future generated output bytes.
            asset_path = Path(project) / 'art/workflow' / ('sample-asset-' + sid + '.png')
            asset_path.write_bytes(png(240 + i))
            material_path = Path(project) / 'art/workflow' / ('sample-material-' + sid + '.tres')
            material_path.write_text('[gd_resource type="StandardMaterial3D" load_steps=2 format=3]\n'
                '[ext_resource type="Texture2D" path="res://art/workflow/' + asset_path.name + '" id="1"]\n'
                '[resource]\nalbedo_texture = ExtResource("1")\nroughness = 0.4\n')
            native_path = core.resolve_input(contract['scene'], project)
            native_path.write_text('[gd_scene load_steps=3 format=3]\n'
                '[ext_resource type="PackedScene" path="' + contract['baseline_scene'] + '" id="1"]\n'
                '[ext_resource type="Material" path="res://art/workflow/' + material_path.name + '" id="2"]\n'
                '[node name="SyntheticNativeSample" instance=ExtResource("1")]\n')
            from greybox import godot
            dependencies = godot.dependency_snapshot(project, {'contract': {'scene': contract['scene']}})
            sample_inputs = {'schema': 2, 'kind': 'sample-inputs', 'style_id': sid,
                'producer_runtime_digest': core.runtime_snapshot()['sha256'],
                'baseline_scene': contract['baseline_scene'], 'scene': contract['scene'],
                'files': [{'id': 'input-' + str(n), 'path': d['path'], 'sha256': d['sha256'],
                           'category': ('render_config' if Path(d['path']).name == 'project.godot' or Path(d['path']).suffix == '.tres'
                                        else 'asset' if Path(d['path']).suffix == '.png' else 'source')}
                          for n, d in enumerate(sorted(dependencies, key=lambda d: d['path']))]}
            synthetic_model_bindings(project, plan, table, sample_inputs, sid + '-')
            identity = {k: contract[k] for k in ('style_id', 'scene', 'input_digest', 'execution_plan_digest')}
            identity['attempt_id'] = 'synthetic-attempt-' + sid
            identity['sample_inputs_digest'] = core.digest(sample_inputs)
            capture_images, captures = [], []
            for number, view in enumerate(sample_views):
                capture = evidence(project, sid + '-native-' + str(number) + '.png', 'native_capture', png(200 + i * 10 + number),
                    'native-capture' if number == 0 else 'native-capture-' + str(number))
                capture_images.append(capture)
                captures.append({**{k: capture[k] for k in ('path', 'sha256')}, 'image_id': capture['id'],
                    'view_id': view['id'], **{k: view[k] for k in ('camera_id', 'state_id', 'framing')},
                    'visible_layers': view['required_layers'], 'missing_layers': []})
            manifest = {'schema': 2, 'kind': 'native-sample', 'identity': identity, 'captures': captures}
            technical = {'schema': 2, 'identity': identity, 'passed': True, 'passed_check_ids': contract['required_technical_checks'], 'errors': []}
            gameplay = {'schema': 2, 'identity': identity, 'passed': True, 'gameplay_verified': True, 'passed_check_ids': checks, 'errors': []}
            visual = {'schema': 2, 'identity': identity, 'visual_accepted': True, 'actor': 'user',
                      'source_ref': 'synthetic://test-only-user-message', 'passed_feature_ids': contract['required_critical_features']}
            add('representative_sample', sid, [source_evidence, *capture_images,
                evidence(project, sid + '-inputs.json', 'sample_inputs', sample_inputs),
                evidence(project, sid + '-native.json', 'native_sample', manifest),
                evidence(project, sid + '-technical.json', 'technical_report', technical),
                evidence(project, sid + '-gameplay.json', 'gameplay_report', gameplay),
                evidence(project, sid + '-visual.json', 'visual_review', visual)], identity=identity,
                consumes={sid + '/production_plan': source_digest})
    path = Path(project) / 'art/workflow/workflow.json'
    core.write(path, data)
    if initialize_control:
        from production_control_fixtures import fixture_control
        fixture_control(project, plan, path, expansion=expansion, legacy_multistyle=len(styles) > 1)
    return path, data


def add_synthetic_lead_h4(project, plan, data):
    """OFFLINE ONLY: independent tiny H4 context for legacy downstream tests.

    Keeps the caller's H3/workflow and all existing evidence immutable. This is
    deliberately synthetic game/art evidence, never a production approval.
    """
    from greybox import godot, layout
    project = Path(project)
    lead = layout.style_ids(plan)[0]
    archive = copy.deepcopy(data)
    archive['stages'] = [s for s in archive['stages'] if s['scope'] in {'shared', lead}]
    prefix = 'synthetic-lead-proof-' + lead + '-' + core.digest(archive)[:12] + '-'
    path = project / 'art/workflow' / (prefix + 'workflow.json')
    if any(s['id'] == 'representative_sample' for s in archive['stages']):
        core.write(path, archive)
        return path
    production = next(s for s in archive['stages'] if s['id'] == 'production_plan')
    source = copy.deepcopy(production)
    original_table = next(e for e in source['evidence'] if e['role'] == 'production_table')
    table = core.read(original_table['path'])
    # A separate synthetic scene must not create the caller's still-future H3
    # sample product merely to satisfy a downstream legacy scheduling test.
    table['sample_contract']['scene'] = 'res://art/workflow/' + prefix + 'native.tscn'
    source['evidence'] = [e for e in source['evidence'] if e['role'] != 'production_table']
    source['evidence'].append(evidence(project, prefix + 'source-table.json', 'production_table', table))
    previous = _CONTEXTS[str(project)]
    _CONTEXTS[str(project)] = archive
    try:
        approve(source)
    finally:
        _CONTEXTS[str(project)] = previous
    source_digest = workflow.stage_digest(source)
    source_evidence = evidence(project, prefix + 'source.json', 'sample_source_production', source)
    contract = copy.deepcopy(table['sample_contract'])
    table['sample_contract']['source_production_digest'] = source_digest
    table.update(scope_mode='expansion', production_space_ids=contract['sample_space_ids'],
                 production_view_ids=contract['required_view_ids'])
    production['revision'] += 1
    production['evidence'] = [e for e in production['evidence'] if e['role'] != 'production_table']
    production['evidence'].append(evidence(project, prefix + 'table.json', 'production_table', table))
    previous = _CONTEXTS[str(project)]
    _CONTEXTS[str(project)] = archive
    try:
        approve(production)
        # Use the declared scene; preserve an existing unique fixture resource.
        scene = core.resolve_input(contract['scene'], project)
        scene.parent.mkdir(parents=True, exist_ok=True)
        if not scene.exists():
            scene.write_text('[gd_scene load_steps=2 format=3]\n'
                '[ext_resource type="PackedScene" path="' + contract['baseline_scene'] + '" id="1"]\n'
                '[node name="SyntheticLeadProof" instance=ExtResource("1")]\n')
        dependencies = godot.dependency_snapshot(project, {'contract': {'scene': contract['scene']}})
        inputs = {'schema': 2, 'kind': 'sample-inputs', 'style_id': lead,
            'producer_runtime_digest': core.runtime_snapshot()['sha256'], 'baseline_scene': contract['baseline_scene'],
            'scene': contract['scene'], 'files': [{'id': 'input-' + str(n), 'path': d['path'], 'sha256': d['sha256'],
                'category': 'render_config' if Path(d['path']).name == 'project.godot' else 'source'}
                for n, d in enumerate(sorted(dependencies, key=lambda d: d['path']))]}
        synthetic_model_bindings(project, plan, table, inputs, prefix)
        identity = {k: contract[k] for k in ('style_id', 'scene', 'input_digest', 'execution_plan_digest')}
        identity.update(attempt_id='synthetic-lead-proof', sample_inputs_digest=core.digest(inputs))
        baseline_stage = next(s for s in archive['stages'] if s['id'] == 'baseline')
        baseline = core.read(next(e['path'] for e in baseline_stage['evidence'] if e['role'] == 'spatial_contract'))
        images, captures = [], []
        for n, view in enumerate(v for v in baseline['observations']['views'] if v['id'] in contract['required_view_ids']):
            item = evidence(project, prefix + 'capture-' + str(n) + '.png', 'native_capture', png(213 + n), 'proof-capture-' + str(n))
            images.append(item)
            captures.append({**{k: item[k] for k in ('path', 'sha256')}, 'image_id': item['id'], 'view_id': view['id'],
                **{k: view[k] for k in ('camera_id', 'state_id', 'framing')},
                'visible_layers': view['required_layers'], 'missing_layers': []})
        technical = {'schema': 2, 'identity': identity, 'passed': True,
                     'passed_check_ids': contract['required_technical_checks'], 'errors': []}
        gameplay = {'schema': 2, 'identity': identity, 'passed': True, 'gameplay_verified': True,
                    'passed_check_ids': contract['required_gameplay_checks'], 'errors': []}
        visual = {'schema': 2, 'identity': identity, 'visual_accepted': True, 'actor': 'user',
            'source_ref': 'synthetic://test-only-user-message', 'passed_feature_ids': contract['required_critical_features']}
        sample = {'id': 'representative_sample', 'scope': lead, 'revision': 1, 'status': 'accepted',
            'actor': 'agent', 'decision_note': 'SYNTHETIC OFFLINE TEST ONLY', 'identity': identity,
            'consumes': {lead + '/production_plan': source_digest}, 'evidence': [source_evidence, *images,
                evidence(project, prefix + 'inputs.json', 'sample_inputs', inputs),
                evidence(project, prefix + 'native.json', 'native_sample', {'schema': 2, 'kind': 'native-sample', 'identity': identity, 'captures': captures}),
                evidence(project, prefix + 'technical.json', 'technical_report', technical),
                evidence(project, prefix + 'gameplay.json', 'gameplay_report', gameplay),
                evidence(project, prefix + 'visual.json', 'visual_review', visual)]}
        archive['stages'].append(sample)
        approve(sample)
        core.write(path, archive)
        workflow.inspect_workflow(path, project, [lead], expansion=True, require_current_capabilities=False)
    finally:
        _CONTEXTS[str(project)] = previous
    return path
