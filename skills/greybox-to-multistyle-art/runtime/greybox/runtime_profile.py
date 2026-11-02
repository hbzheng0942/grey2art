"""Hash-bound runtime budget targets, not a second performance/approval ledger."""
from __future__ import annotations

import math

from . import core


def _number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _evidence(reference, project):
    core.require(isinstance(reference, dict) and _text(reference.get('path')),
                 'Runtime budget evidence needs a path/hash reference')
    path = core.resolve_input(reference['path'], project)
    core.require(core.inside(path, project) and path.is_file()
                 and core.file_hash(path) == reference.get('sha256'),
                 'Runtime budget evidence missing, outside project or changed')
    return path


def validate_profile(reference, project):
    path = _evidence(reference, project)
    data = core.read(path)
    core.require(isinstance(data, dict) and data.get('schema') == 1
                 and data.get('kind') == 'runtime-profile', 'Invalid runtime profile')
    core.require(_text(data.get('engine')) and _text(data.get('target')),
                 'Runtime profile needs the actual engine and target context')
    rows = data.get('budgets')
    core.require(isinstance(rows, list), 'Runtime profile budgets must be a list; empty means unspecified')
    seen = set()
    for row in rows:
        core.require(isinstance(row, dict) and core.safe_id(row.get('id'))
                     and row['id'] not in seen, 'Runtime budget IDs must be unique')
        seen.add(row['id'])
        core.require(_text(row.get('metric')) and _text(row.get('unit'))
                     and _number(row.get('limit')) and row.get('classification') in {'hard', 'target'}
                     and _text(row.get('source_ref')), 'Runtime budget needs metric/unit/limit/type and its source')
        if 'asset_ids' in row:
            ids = row['asset_ids']
            core.require(isinstance(ids, list) and ids and all(core.safe_id(i) for i in ids)
                         and len(ids) == len(set(ids)), 'Invalid asset scope for runtime budget')
    return data


def validate_targets(reference, targets, project, asset_id=None):
    """Check declared processing targets against the one bound budget profile.

    Targets are settings, not observed polygon counts. Actual quality, frame time,
    memory and native measurements retain their separate engine receipts.
    """
    profile = validate_profile(reference, project)
    core.require(isinstance(targets, list), 'Processing report must declare runtime budget targets')
    budgets = {b['id']: b for b in profile['budgets']}
    applicable = {key for key, row in budgets.items()
                  if 'asset_ids' not in row or asset_id in row['asset_ids']}
    checked = set()
    for target in targets:
        core.require(isinstance(target, dict) and target.get('budget_id') in budgets,
                     'Processing target names an unknown runtime budget')
        key = target['budget_id']
        core.require(key in applicable and key not in checked,
                     'Processing target duplicates a budget or belongs to another asset')
        checked.add(key)
        row, value = budgets[key], target.get('value')
        core.require(_number(value), 'Runtime target must be a finite nonnegative number')
        core.require(target.get('unit', row['unit']) == row['unit'],
                     'Runtime target unit differs from the shared profile')
        if row['classification'] == 'hard':
            core.require(value <= row['limit'], 'Processing target exceeds a hard runtime limit: ' + key)
        elif value != row['limit']:
            core.require(_text(target.get('reason')) and isinstance(target.get('evidence'), list)
                         and target['evidence'],
                         'Changed provisional runtime target needs a reason and measured evidence: ' + key)
            for item in target['evidence']:
                _evidence(item, project)
    core.require(checked == applicable, 'Processing report omits applicable shared runtime budget targets')
    return {'ok': True, 'profile_sha256': reference['sha256'], 'asset_id': asset_id,
            'target_ids': sorted(checked), 'performance_verified': False}
