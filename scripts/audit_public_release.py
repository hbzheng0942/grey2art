#!/usr/bin/env python3
"""Inventory candidate public text without printing matched credential values.

This is a bounded review aid, not a secret detector or publication approval.
It reads Git-selected files/objects and writes only a small JSON receipt.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {'.md', '.json', '.py', '.gd', '.gdshader', '.cs', '.tscn',
                 '.tres', '.txt', '.yaml', '.yml', '.mjs', '.js', '.html',
                 '.toml', '.sh', '.cmd', '.command', '.svg'}
PATTERNS = {
    'private_key_marker': re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
    'provider_token_candidate': re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|sk-(?:proj-)?[A-Za-z0-9_-]{24,})\b'),
    'credential_assignment_candidate': re.compile(r'''(?i)(?<![A-Za-z0-9_])["']?(?:api[_-]?key|access[_-]?token|secret)["']?\s*[:=]\s*["']([A-Za-z0-9_./+\-=]{24,})["']'''),
    'signed_url_candidate': re.compile(r'https?://\S+[?&](?:X-Amz-Signature|access_token|signature)=[^\s&]+', re.I),
    'local_user_path': re.compile(r'/(?:Users|home)/[^\s/]+/'),
    'internal_url': re.compile(r'https?://(?:(?:[A-Za-z0-9-]+\.)*qunhequnhe\.com|(?:[A-Za-z0-9-]+\.)+(?:internal|local|corp)|localhost)(?=[:/\s]|$)', re.I),
}
SENSITIVE = {'private_key_marker', 'provider_token_candidate',
             'credential_assignment_candidate', 'signed_url_candidate'}


def git(root: Path, *args: str) -> bytes:
    executable = shutil.which('git') or '/usr/bin/git'
    return subprocess.check_output([executable, '-C', str(root), *args], stderr=subprocess.PIPE)


def text_candidate(name: str) -> bool:
    p = Path(name)
    return p.suffix.lower() in TEXT_SUFFIXES or p.name in {
        'LICENSE', '.gitignore', '.gitattributes', '.env', '.env.example'}


def scan_text(name: str, data: bytes, object_id: str | None = None) -> list[dict]:
    try:
        source = data.decode('utf-8')
    except UnicodeDecodeError:
        return []
    findings = []
    for number, line in enumerate(source.splitlines(), 1):
        for kind, pattern in PATTERNS.items():
            if pattern.search(line):
                row = {'path': name, 'line': number, 'kind': kind,
                       'review': 'candidate_sensitive_value' if kind in SENSITIVE else 'public_content_boundary'}
                if object_id:
                    row['blob'] = object_id
                findings.append(row)
    return findings


def audit(root: Path, ref: str | None = None, history: bool = False,
          max_text_bytes: int = 2_000_000) -> dict:
    root = root.resolve()
    if max_text_bytes <= 0:
        raise ValueError('max-text-bytes must be positive')
    findings, entries, skipped = [], [], []
    def record(name: str, data: bytes, object_id: str | None = None) -> None:
        try:
            data.decode('utf-8')
        except UnicodeDecodeError:
            skipped.append({'path': name, 'reason': 'non_utf8_text_candidate'})
            return
        if b'\0' in data:
            skipped.append({'path': name, 'reason': 'binary_text_candidate'})
            return
        entry = {'path': name, 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}
        if object_id:
            entry['blob'] = object_id
        entries.append(entry)
        findings.extend(scan_text(name, data, object_id))
    source_revision = git(root, 'rev-parse', '--verify', f'{ref or "HEAD"}^{{commit}}').decode().strip()
    if history:
        # rev-list emits each reachable object once, without checking out history.
        lines = git(root, 'rev-list', '--objects', source_revision).decode().splitlines()
        candidates = [line.split(' ', 1) for line in lines if ' ' in line]
        for object_id, name in candidates:
            if not text_candidate(name):
                continue
            kind_size = git(root, 'cat-file', '-t', object_id).decode().strip()
            if kind_size != 'blob':
                continue
            size = int(git(root, 'cat-file', '-s', object_id))
            if size > max_text_bytes:
                skipped.append({'path': name, 'blob': object_id, 'reason': 'text_size_limit'})
                continue
            data = git(root, 'cat-file', 'blob', object_id)
            record(name, data, object_id)
    elif ref:
        rows = git(root, 'ls-tree', '-r', '-z', source_revision).split(b'\0')
        for row in rows:
            if not row:
                continue
            metadata, raw_name = row.split(b'\t', 1)
            mode, kind, object_id = metadata.decode().split()
            name = raw_name.decode()
            if mode == '120000' or kind != 'blob':
                skipped.append({'path': name, 'reason': 'symlink_or_gitlink'})
                continue
            if not text_candidate(name):
                continue
            size = int(git(root, 'cat-file', '-s', object_id))
            if size > max_text_bytes:
                skipped.append({'path': name, 'reason': 'text_size_limit'})
                continue
            data = git(root, 'cat-file', 'blob', object_id)
            record(name, data, object_id)
    else:
        names = sorted(set(git(root, 'ls-files', '-z', '--cached', '--others', '--exclude-standard').decode().split('\0')) - {''})
        for name in names:
            path = root / name
            if path.is_symlink() or not path.resolve().is_relative_to(root):
                skipped.append({'path': name, 'reason': 'symlink_or_outside_root'})
                continue
            if not path.is_file() or not text_candidate(name):
                continue
            if path.stat().st_size > max_text_bytes:
                skipped.append({'path': name, 'reason': 'text_size_limit'})
                continue
            data = path.read_bytes()
            record(name, data)
    kinds = {kind: sum(row['kind'] == kind for row in findings) for kind in PATTERNS}
    return {'schema': 1, 'kind': 'public-source-review-inventory',
            'scope': 'reachable_history' if history else ('git_revision' if ref else 'working_tree'),
            'source_revision': source_revision, 'reviewed_text_objects': len(entries),
            'text_bytes': sum(row['bytes'] for row in entries),
            'inventory_sha256': hashlib.sha256(json.dumps(entries, sort_keys=True).encode()).hexdigest(),
            'counts': kinds, 'findings': findings, 'skipped': skipped,
            'publication_approved': False,
            'limitations': ['Pattern candidates require human triage; synthetic fixtures may match.',
                            'No binary/media rights, arbitrary private prose, external reachability or comprehensive secret detection.',
                            'Ignored files are outside working-tree scope; history is only the selected reachable history.',
                            'Matched line contents and credential values are never included in this report.']}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--ref', help='Inspect this immutable Git revision instead of current files.')
    parser.add_argument('--history', action='store_true', help='Inspect text blobs reachable from --ref (default HEAD).')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--max-text-bytes', type=int, default=2_000_000)
    args = parser.parse_args()
    try:
        report = audit(args.root, args.ref, args.history, args.max_text_bytes)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('x', encoding='utf-8') as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        print(json.dumps({key: report[key] for key in ['scope', 'source_revision', 'reviewed_text_objects', 'counts', 'publication_approved']}))
        return 0
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f'Audit failed: {type(error).__name__}; no source text is emitted.', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
