#!/usr/bin/env python3
"""Read-only authoring checks/digests; never generate, approve, or submit work."""
import argparse, json, sys
from pathlib import Path
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'runtime'))
from greybox import core,workflow

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='cmd', required=True)
    a = sub.add_parser('capabilities')
    a.add_argument('--file', type=Path, required=True)
    a.add_argument('--require-lux', action='store_true')
    a.add_argument('--require-capability', action='append', default=[])
    a.add_argument('--session-id')
    a.add_argument('--concept-source', choices=['generate', 'approved_import'], default='generate')
    for name in ('stages', 'plan'):
        a = sub.add_parser(name)
        a.add_argument('--file', type=Path, required=True)
        a.add_argument('--project', type=Path, required=True)
        a.add_argument('--capabilities', type=Path)
        a.add_argument('--session-id')
        if name == 'stages':
            a.add_argument('--expansion', action='store_true')
            a.add_argument('--proxy-only', action='store_true')
            a.add_argument('--style', action='append', help='Inspect only this H1-selected style; repeat for a scoped group')
            a.add_argument('--style-phase', action='append', default=[], metavar='STYLE=PHASE',
                           help='Per-style representative or expansion phase; does not alter H1 or grant authority')
    for name in ('stage-digests', 'plan-digest'):
        a = sub.add_parser(name, help='Compute hashes only; no acceptance is recorded')
        a.add_argument('--file', type=Path, required=True)
    a = sub.add_parser('review-inputs', help='Build actual review inputs only; never record a passing review')
    a.add_argument('--file', type=Path, required=True)
    a.add_argument('--project', type=Path, required=True)
    a.add_argument('--stage', required=True, help='Scope/stage, for example ceramic/production_plan')
    a = p.parse_args(argv)
    try:
        if a.cmd == 'review-inputs':
            result = workflow.build_review_inputs(a.file, a.project, a.stage)
        elif a.cmd == 'capabilities':
            result = workflow.check_capabilities(core.read(a.file), a.require_lux, a.concept_source, a.session_id, a.require_capability)
        elif a.cmd == 'plan-digest':
            result = {'ok': True, 'execution_plan_digest': workflow.execution_plan_digest(core.read(a.file)),
                      'note': 'Hash only; no validity or user approval is implied'}
        elif a.cmd == 'stage-digests':
            stages = core.read(a.file).get('stages', [])
            keys = [str(s.get('scope')) + '/' + str(s.get('id')) for s in stages]
            core.require(len(keys) == len(set(keys)), 'Duplicate stage/scope')
            result = {'ok': True, 'digests': {k: workflow.stage_digest(s) for k, s in zip(keys, stages)},
                      'note': 'Hash only; approvals must reference actual user decisions'}
        else:
            report = core.read(a.capabilities) if a.capabilities else None
            if report is not None:
                core.require(a.session_id, '--capabilities requires current host --session-id')
            if a.cmd == 'stages':
                phases = {}
                for value in a.style_phase:
                    parts = value.split('=')
                    core.require(len(parts) == 2 and parts[0] not in phases, '--style-phase requires unique STYLE=PHASE values')
                    phases[parts[0]] = parts[1]
                result = workflow.inspect_workflow(a.file, a.project, selected_styles=a.style, expansion=a.expansion,
                    expected_session=a.session_id, proxy_only=a.proxy_only, capability_report=report, style_phases=phases)
            else:
                result = workflow.check_plan_gate(core.read(a.file), a.project,
                    capability_report=report, expected_session=a.session_id)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get('ok', True) else 2
    except (ValueError, OSError, KeyError, TypeError) as e:
        print(json.dumps({'ok': False, 'blocked': True, 'error': str(e)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
