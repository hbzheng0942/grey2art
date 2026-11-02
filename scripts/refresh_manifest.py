#!/usr/bin/env python3
"""Refresh source hashes without changing a version or publishing a package."""
from pathlib import Path
import hashlib
import json
import os
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills/greybox-to-multistyle-art'


def main():
    target = SKILL / 'MANIFEST.json'
    manifest = json.loads(target.read_text())
    rows = []
    for path in sorted(SKILL.rglob('*')):
        if not path.is_file() or path == target or '__pycache__' in path.parts or path.name == '.DS_Store' or path.suffix in {'.pyc', '.pyo'}:
            continue
        if path.is_symlink():
            raise ValueError('Installable source cannot contain symbolic file links')
        data = path.read_bytes()
        rows.append({'path': path.relative_to(SKILL).as_posix(), 'bytes': len(data),
                     'sha256': hashlib.sha256(data).hexdigest()})
    manifest['files'] = rows
    manifest['sourceManifestSHA256'] = hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    descriptor, temporary = tempfile.mkstemp(prefix='.manifest-', dir=target.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
            handle.write(json.dumps(manifest, indent=2, ensure_ascii=False) + '\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    print(json.dumps({'files': len(rows), 'version': manifest['version'],
                      'sourceManifestSHA256': manifest['sourceManifestSHA256']}))


if __name__ == '__main__':
    main()
