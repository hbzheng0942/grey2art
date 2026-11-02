#!/usr/bin/env python3
"""Build and verify a small, manifest-bound Skill ZIP without provider calls."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
NAME = 'greybox-to-multistyle-art'
DEFAULT_SOURCE = ROOT / 'skills' / NAME
SOURCE_PREFIX = 'skills/' + NAME
MAX_BYTES = 32 * 1024 * 1024
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
MAX_FILES = 4096
VERSION = re.compile(r'(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?:-(?:alpha|beta|rc)\.[1-9][0-9]*)?')
FORBIDDEN = {'.git', '.venv', 'venv', 'node_modules', '.godot', '__pycache__', '.DS_Store'}
WINDOWS_DEVICES = {'con', 'prn', 'aux', 'nul'} | {'com' + str(i) for i in range(1, 10)} | {'lpt' + str(i) for i in range(1, 10)}
REQUIRED = {'LICENSE', 'SKILL.md', 'scripts/install.py', 'scripts/greybox.py', 'runtime/greybox/cli.py'}


def digest(payload):
    return hashlib.sha256(payload).hexdigest()


def safe_path(name):
    if not isinstance(name, str):
        raise ValueError('Package path must be text')
    path = PurePosixPath(name)
    if (name in ('', '.', '..') or name != path.as_posix() or path.is_absolute() or '..' in path.parts
            or re.search(r'[<>:"\\|?*\x00-\x1f]', name) or any(part in FORBIDDEN for part in path.parts)
            or any(part.rstrip(' .') != part or part.split('.')[0].casefold() in WINDOWS_DEVICES for part in path.parts)
            or path.suffix in {'.pyc', '.pyo'} or any(part == '.env' or part.startswith('.env.')
                                                     and part != '.env.example' for part in path.parts)):
        raise ValueError('Unsafe or cached package path: ' + name)
    return path


def reserve_file(path, files, directories):
    """Reject file/ancestor conflicts on case-insensitive target filesystems."""
    name = path.as_posix().casefold()
    ancestors = {parent.as_posix().casefold() for parent in path.parents if parent.parts}
    if name in files:
        raise ValueError('Invalid or duplicate package path: ' + path.as_posix())
    if name in directories or ancestors & files:
        raise ValueError('File/directory conflict in package path: ' + path.as_posix())
    files.add(name)
    directories.update(ancestors)


def manifest_files(payload):
    if len(payload) > MAX_MANIFEST_BYTES:
        raise ValueError('Package manifest exceeds its size limit')
    manifest = json.loads(payload)
    if (not isinstance(manifest, dict) or manifest.get('schema') != 1 or manifest.get('name') != NAME
            or not isinstance(manifest.get('version'), str) or not VERSION.fullmatch(manifest['version'])
            or not isinstance(manifest.get('files'), list) or len(manifest['files']) > MAX_FILES):
        raise ValueError('Unsupported package identity or version')
    files, portable_names, portable_directories, total = {}, {'manifest.json'}, set(), 0
    for row in manifest['files']:
        if not isinstance(row, dict):
            raise ValueError('Invalid manifest row')
        path = safe_path(row.get('path'))
        name = path.as_posix()
        if (name == 'MANIFEST.json' or name.casefold() in portable_names
                or type(row.get('bytes')) is not int or row['bytes'] < 0
                or not isinstance(row.get('sha256'), str) or not re.fullmatch('[0-9a-f]{64}', row['sha256'])):
            raise ValueError('Invalid or duplicate manifest row: ' + name)
        reserve_file(path, portable_names, portable_directories)
        total += row['bytes']
        if total > MAX_BYTES:
            raise ValueError('Source package exceeds the small-package limit')
        files[name] = row
    if not REQUIRED <= files.keys():
        raise ValueError('Incomplete source package')
    calculated = digest(json.dumps(manifest['files'], sort_keys=True, separators=(',', ':')).encode())
    if manifest.get('sourceManifestSHA256') != calculated:
        raise ValueError('Source manifest digest differs from its file declarations')
    return manifest, files


def _check_payload(name, payload, declaration):
    if len(payload) != declaration['bytes'] or digest(payload) != declaration['sha256']:
        raise ValueError('Package checksum mismatch: ' + name)


def _cli_version(source):
    result = subprocess.run([sys.executable, '-I', '-B', str(source / 'scripts' / 'greybox.py'), '--version'],
                            cwd=source, capture_output=True, text=True, encoding='utf-8',
                            stdin=subprocess.DEVNULL, timeout=30, check=False)
    if result.returncode:
        raise ValueError('Package CLI version command failed')
    return result.stdout.strip()


def source_payloads(source):
    source = Path(source).absolute()
    if source.is_symlink() or not source.is_dir():
        raise ValueError('Source must be a regular Skill directory')
    manifest_path = source / 'MANIFEST.json'
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError('Manifest must be a regular file')
    if manifest_path.stat().st_size > MAX_MANIFEST_BYTES:
        raise ValueError('Package manifest exceeds its size limit')
    raw_manifest = manifest_path.read_bytes()
    manifest, declarations = manifest_files(raw_manifest)
    actual = set()
    for path in source.rglob('*'):
        if path.is_symlink():
            raise ValueError('Symlink not permitted in source package')
        relative = path.relative_to(source)
        if path.is_dir() and '__pycache__' not in relative.parts:
            safe_path(relative.as_posix())
        if not path.is_file():
            continue
        rel = relative.as_posix()
        # Reproducible local caches are omitted, never packed or copied.
        if '__pycache__' in relative.parts or path.name == '.DS_Store' or path.suffix in {'.pyc', '.pyo'}:
            continue
        safe_path(rel)
        actual.add(rel)
    if actual != declarations.keys() | {'MANIFEST.json'}:
        raise ValueError('Source contains missing or unmanifested files')
    payloads = {'MANIFEST.json': raw_manifest}
    for name, row in declarations.items():
        path = source.joinpath(*PurePosixPath(name).parts)
        if path.stat().st_size != row['bytes']:
            raise ValueError('Package checksum mismatch: ' + name)
        payloads[name] = path.read_bytes()
        _check_payload(name, payloads[name], row)
    if _cli_version(source) != manifest['version']:
        raise ValueError('CLI and manifest versions differ')
    # A concurrently edited input must not silently receive a new identity.
    if manifest_path.read_bytes() != raw_manifest:
        raise ValueError('Manifest changed during packaging')
    return manifest, payloads


def archive_bytes(payloads):
    result = io.BytesIO()
    with zipfile.ZipFile(result, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, payload in sorted(payloads.items()):
            info = zipfile.ZipInfo(NAME + '/' + name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, payload, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    return result.getvalue()


def _git(repo, *arguments, data=None):
    executable = shutil.which('git')
    if not executable and Path('/usr/bin/git').is_file():
        executable = '/usr/bin/git'
    if not executable:
        raise ValueError('Git is required only for --ref packaging')
    result = subprocess.run([executable, '-C', str(repo), *arguments], input=data,
                            capture_output=True, stdin=None if data is not None else subprocess.DEVNULL,
                            timeout=30, check=False)
    if result.returncode:
        raise ValueError('Git source lookup failed; verify the repository and ref')
    return result.stdout


def source_payloads_at_ref(repo, ref):
    """Read only the manifest-bound Skill blobs, never a full-tree checkout."""
    commit = _git(repo, 'rev-parse', '--verify', '--end-of-options', ref + '^{commit}').decode().strip()
    if not re.fullmatch('[0-9a-f]{40}|[0-9a-f]{64}', commit):
        raise ValueError('Git did not resolve an immutable commit')
    manifest_object = commit + ':' + SOURCE_PREFIX + '/MANIFEST.json'
    size = int(_git(repo, 'cat-file', '-s', manifest_object))
    if size > MAX_MANIFEST_BYTES:
        raise ValueError('Package manifest exceeds its size limit')
    raw_manifest = _git(repo, 'cat-file', 'blob', manifest_object)
    manifest, declarations = manifest_files(raw_manifest)
    tree = _git(repo, 'ls-tree', '-r', '-z', commit, '--', SOURCE_PREFIX + '/')
    objects = {}
    for entry in tree.split(b'\0'):
        if not entry:
            continue
        metadata, raw_path = entry.split(b'\t', 1)
        mode, kind, oid = metadata.decode('ascii').split()
        path = raw_path.decode('utf-8')
        if not path.startswith(SOURCE_PREFIX + '/'):
            raise ValueError('Git returned a path outside the Skill')
        name = path[len(SOURCE_PREFIX) + 1:]
        safe_path(name)
        if kind != 'blob' or mode not in ('100644', '100755'):
            raise ValueError('Git source contains a symlink or non-file entry')
        objects[name] = oid
    if objects.keys() != declarations.keys() | {'MANIFEST.json'}:
        raise ValueError('Git source contains missing or unmanifested files')
    names = sorted(declarations)
    request = ('\n'.join(objects[name] for name in names) + '\n').encode()
    sizes = _git(repo, 'cat-file', '--batch-check', data=request).decode('ascii').splitlines()
    if len(sizes) != len(names):
        raise ValueError('Incomplete Git object size check')
    for name, row in zip(names, sizes):
        oid, kind, size = row.split()
        if oid != objects[name] or kind != 'blob' or int(size) != declarations[name]['bytes']:
            raise ValueError('Git blob size does not match its manifest: ' + name)
    batch = _git(repo, 'cat-file', '--batch', data=request)
    cursor, payloads = 0, {'MANIFEST.json': raw_manifest}
    for name in names:
        end = batch.find(b'\n', cursor)
        if end < 0:
            raise ValueError('Incomplete Git blob stream')
        oid, kind, size = batch[cursor:end].decode('ascii').split()
        count = int(size)
        if oid != objects[name] or kind != 'blob' or count != declarations[name]['bytes']:
            raise ValueError('Git blob does not match its manifest: ' + name)
        cursor = end + 1
        payloads[name] = batch[cursor:cursor + count]
        _check_payload(name, payloads[name], declarations[name])
        cursor += count
        if batch[cursor:cursor + 1] != b'\n':
            raise ValueError('Incomplete Git blob stream')
        cursor += 1
    if cursor != len(batch):
        raise ValueError('Unexpected trailing Git blob data')
    return manifest, payloads, commit


def inspect_archive(archive_path, expected_sha256=None):
    archive_path = Path(archive_path)
    if archive_path.is_symlink() or not archive_path.is_file() or archive_path.stat().st_size > MAX_BYTES + MAX_MANIFEST_BYTES:
        raise ValueError('Archive must be a small regular file')
    raw = archive_path.read_bytes()
    actual_digest = digest(raw)
    if expected_sha256 is not None and (not re.fullmatch('[0-9a-f]{64}', expected_sha256)
                                        or expected_sha256 != actual_digest):
        raise ValueError('Archive SHA-256 does not match')
    payloads, portable_names, portable_directories, total = {}, set(), set(), 0
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        if len(archive.infolist()) > MAX_FILES + 1:
            raise ValueError('Too many archive members')
        for info in archive.infolist():
            path = safe_path(info.filename)
            if len(path.parts) < 2 or path.parts[0] != NAME or info.is_dir():
                raise ValueError('Archive must have one Skill directory with regular files')
            name = PurePosixPath(*path.parts[1:]).as_posix()
            mode = info.external_attr >> 16
            if (stat.S_IFMT(mode) not in (0, stat.S_IFREG)
                    or info.flag_bits & 1 or info.file_size < 0):
                raise ValueError('Duplicate, linked or encrypted archive member')
            reserve_file(PurePosixPath(name), portable_names, portable_directories)
            limit = MAX_MANIFEST_BYTES if name == 'MANIFEST.json' else MAX_BYTES
            total += info.file_size
            if info.file_size > limit or total > MAX_BYTES + MAX_MANIFEST_BYTES:
                raise ValueError('Archive contents exceed the small-package limit')
            payloads[name] = archive.read(info)
    if 'MANIFEST.json' not in payloads:
        raise ValueError('Archive has no package manifest')
    manifest, declarations = manifest_files(payloads['MANIFEST.json'])
    if payloads.keys() != declarations.keys() | {'MANIFEST.json'}:
        raise ValueError('Archive contains missing or unmanifested files')
    for name, row in declarations.items():
        _check_payload(name, payloads[name], row)
    receipt = {'schema': 1, 'name': NAME, 'version': manifest['version'],
               'archive': archive_path.name, 'archive_bytes': len(raw), 'archive_sha256': actual_digest,
               'manifest_sha256': digest(payloads['MANIFEST.json']),
               'source_manifest_sha256': manifest['sourceManifestSHA256'],
               'source_files': len(declarations), 'source_bytes': total,
               'format': 'zip/deflate-9', 'cloud_calls': 0}
    return receipt, payloads


def _write_payloads(source, payloads):
    source.mkdir(parents=True)
    for name, payload in payloads.items():
        target = source.joinpath(*safe_path(name).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)


def install_roundtrip(payloads, version):
    # Use this checkout's trusted installer, and only task-owned temporary paths.
    spec = importlib.util.spec_from_file_location('release_package_installer', DEFAULT_SOURCE / 'scripts' / 'install.py')
    installer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(installer)
    with tempfile.TemporaryDirectory(prefix='greybox-release-check-') as temporary:
        base = Path(temporary)
        source = base / 'source' / NAME
        _write_payloads(source, payloads)
        destination = base / 'host' / 'skills' / NAME
        first = installer.install(source, destination)
        second = installer.install(source, destination)
        checked, _ = installer.verified_files(destination)
        if (checked['version'] != version or _cli_version(destination) != version
                or second['copiedBytes'] != 0):
            raise ValueError('Offline install/version/reuse roundtrip failed')
        return {'passed': True, 'version': version, 'first_install_bytes': first['copiedBytes'],
                'repeated_install_bytes': second['copiedBytes'], 'temporary_files_removed': True}


def _publish_files(outputs):
    # Validate every existing output before creating any new one.
    for path, payload in outputs.items():
        if path.is_symlink() or path.exists() and (not path.is_file() or path.stat().st_size != len(payload)
                                                  or path.read_bytes() != payload):
            raise ValueError('Refusing to replace a different release artifact: ' + path.name)
    created = []
    try:
        for path, payload in outputs.items():
            if path.exists():
                continue
            try:
                with path.open('xb') as handle:
                    identity = os.fstat(handle.fileno())
                    created.append((path, identity.st_dev, identity.st_ino))
                    handle.write(payload)
            except FileExistsError:
                if path.is_symlink() or path.read_bytes() != payload:
                    raise ValueError('Concurrent release artifact differs: ' + path.name) from None
    except BaseException:
        for path, device, inode in created:
            if path.exists() and not path.is_symlink():
                current = path.stat()
                if (current.st_dev, current.st_ino) == (device, inode):
                    path.unlink()
        raise
    return bool(created)


def build(source=DEFAULT_SOURCE, output_dir=None, verify_install=False, ref=None, repo=ROOT):
    commit = None
    if ref is None:
        manifest, payloads = source_payloads(source)
    else:
        manifest, payloads, commit = source_payloads_at_ref(repo, ref)
        with tempfile.TemporaryDirectory(prefix='greybox-release-ref-') as temporary:
            source_for_cli = Path(temporary) / NAME
            _write_payloads(source_for_cli, payloads)
            if _cli_version(source_for_cli) != manifest['version']:
                raise ValueError('CLI and manifest versions differ')
    output_dir = Path(output_dir or ROOT / 'dist').absolute()
    if output_dir.is_symlink() or output_dir.resolve().is_relative_to(Path(source).resolve()):
        raise ValueError('Release outputs must be outside the source Skill directory')
    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / (NAME + '-' + manifest['version'] + '.zip')
    raw = archive_bytes(payloads)
    # Inspect in memory via a small task-owned file; do not extract/copy a project.
    with tempfile.TemporaryDirectory(prefix='greybox-release-archive-') as temporary:
        trial = Path(temporary) / target.name
        trial.write_bytes(raw)
        receipt, checked = inspect_archive(trial, digest(raw))
        roundtrip = install_roundtrip(checked, manifest['version']) if verify_install else None
    checksum = (receipt['archive_sha256'] + '  ' + target.name + '\n').encode()
    receipt_bytes = (json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode()
    created = _publish_files({target: raw, Path(str(target) + '.sha256'): checksum,
                              Path(str(target) + '.release.json'): receipt_bytes})
    return {**receipt, 'status': 'built' if created else 'reused', 'output': str(target), 'source_commit': commit,
            'install_roundtrip': roundtrip}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    create = commands.add_parser('build', help='Build only the verified manifest source files')
    selection = create.add_mutually_exclusive_group()
    selection.add_argument('--source', type=Path, default=DEFAULT_SOURCE)
    selection.add_argument('--ref', help='Resolve a Git ref and read only its manifest-bound Skill blobs')
    create.add_argument('--repo', type=Path, default=ROOT, help='Repository for --ref (defaults to this checkout)')
    create.add_argument('--output-dir', type=Path, default=ROOT / 'dist')
    create.add_argument('--verify-install', action='store_true', help='Run package code in an isolated temporary install')
    verify = commands.add_parser('verify', help='Verify archive members, package hashes and optional install')
    verify.add_argument('archive', type=Path)
    verify.add_argument('--sha256', help='Expected SHA-256 from a trusted release record')
    verify.add_argument('--verify-install', action='store_true', help='Run package code; use only a trusted archive')
    args = parser.parse_args(argv)
    try:
        if args.command == 'build':
            result = build(args.source, args.output_dir, args.verify_install, ref=args.ref, repo=args.repo)
        else:
            expected = args.sha256
            sidecar = Path(str(args.archive) + '.sha256')
            if expected is None and sidecar.exists():
                if sidecar.is_symlink() or not sidecar.is_file() or sidecar.stat().st_size > 1024:
                    raise ValueError('Checksum sidecar must be a small regular file')
                line = sidecar.read_text(encoding='utf-8').strip()
                match = re.fullmatch('([0-9a-f]{64})  ' + re.escape(args.archive.name), line)
                if not match:
                    raise ValueError('Invalid checksum sidecar')
                expected = match.group(1)
            result, payloads = inspect_archive(args.archive, expected)
            result['status'] = 'verified'
            result['install_roundtrip'] = install_roundtrip(payloads, result['version']) if args.verify_install else None
        print(json.dumps(result, indent=2, ensure_ascii=True))
        return 0
    except (ValueError, OSError, KeyError, TypeError, UnicodeError, zipfile.BadZipFile, subprocess.SubprocessError) as error:
        print(json.dumps({'status': 'failed', 'error': str(error)}, ensure_ascii=True), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
