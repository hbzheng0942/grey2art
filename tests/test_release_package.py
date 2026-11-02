"""Exercise actual ZIP, hostile inputs and an offline install roundtrip."""
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('build_release', ROOT / 'scripts' / 'build_release.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleasePackage(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='greybox-package-test-')
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)

    def fixture(self):
        source = self.base / 'source'
        payloads = {
            'LICENSE': b'MIT synthetic fixture\n',
            'SKILL.md': b'---\nname: greybox-to-multistyle-art\n---\nFixture\n',
            'scripts/greybox.py': b'print("0.13.0-alpha.1")\n',
            'scripts/install.py': (release.DEFAULT_SOURCE / 'scripts' / 'install.py').read_bytes(),
            'runtime/greybox/cli.py': b'# synthetic fixture\n',
        }
        for name, payload in payloads.items():
            path = source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
        self.write_manifest(source, payloads)
        return source

    def write_manifest(self, source, payloads):
        rows = [{'path': name, 'bytes': len(payload), 'sha256': hashlib.sha256(payload).hexdigest()}
                for name, payload in sorted(payloads.items())]
        manifest = {'schema': 1, 'name': release.NAME, 'version': '0.13.0-alpha.1', 'files': rows,
                    'sourceManifestSHA256': release.digest(json.dumps(rows, sort_keys=True, separators=(',', ':')).encode())}
        (source / 'MANIFEST.json').write_text(json.dumps(manifest), encoding='utf-8')
        return manifest

    def archive(self, payloads, extra=None):
        path = self.base / 'fixture.zip'
        path.write_bytes(release.archive_bytes(payloads))
        if extra:
            with zipfile.ZipFile(path, 'a') as archive:
                for name, payload in extra.items():
                    archive.writestr(name, payload)
        return path

    def test_real_source_archive_install_and_idempotent_rebuild(self):
        result = release.build(output_dir=self.base / 'releases', verify_install=True, ref='HEAD')
        path = Path(result['output'])
        receipt, payloads = release.inspect_archive(path, result['archive_sha256'])
        self.assertTrue(result['install_roundtrip']['passed'])
        self.assertEqual(result['install_roundtrip']['repeated_install_bytes'], 0)
        self.assertEqual(receipt['source_files'] + 1, len(payloads))
        self.assertEqual(release.build(output_dir=self.base / 'releases', ref=result['source_commit'])['status'], 'reused')
        self.assertEqual(len(list(path.parent.iterdir())), 3)
        self.assertEqual(json.loads(Path(str(path) + '.release.json').read_text())['archive_sha256'], result['archive_sha256'])

    def test_git_ref_resolves_once_and_reads_only_declared_source(self):
        manifest, payloads, commit = release.source_payloads_at_ref(ROOT, 'HEAD')
        self.assertRegex(commit, r'^[0-9a-f]{40}$|^[0-9a-f]{64}$')
        self.assertEqual(set(payloads), {row['path'] for row in manifest['files']} | {'MANIFEST.json'})
        self.assertFalse(any(name.startswith(('.git/', 'docs/demo/')) for name in payloads))
        by_commit, fixed_payloads, fixed_commit = release.source_payloads_at_ref(ROOT, commit)
        self.assertEqual((by_commit, fixed_payloads, fixed_commit), (manifest, payloads, commit))
        with self.assertRaisesRegex(ValueError, 'Git source lookup'):
            release.source_payloads_at_ref(ROOT, 'refs/heads/does-not-exist-release-package-fixture')

    def test_archive_is_reproducible_across_input_order_and_mtime(self):
        source = self.fixture()
        _, first = release.source_payloads(source)
        before = release.archive_bytes(first)
        for path in source.rglob('*'):
            if path.is_file():
                os.utime(path, (1700000000, 1700000000))
        _, second = release.source_payloads(source)
        self.assertEqual(before, release.archive_bytes(dict(reversed(list(second.items())))))

    def test_missing_or_changed_source_is_rejected(self):
        source = self.fixture()
        target = source / 'runtime/greybox/cli.py'
        original = target.read_bytes()
        for payload in (None, b'changed', original[:-1] + b'X'):
            with self.subTest(payload=payload):
                if payload is None:
                    target.unlink()
                else:
                    target.write_bytes(payload)
                with self.assertRaises(ValueError):
                    release.build(source, self.base / 'out')
                target.write_bytes(original)
        self.assertFalse((self.base / 'out').exists())

    def test_unmanifested_source_is_rejected_and_cache_is_omitted(self):
        source = self.fixture()
        extra = source / 'extra.txt'
        extra.write_text('not declared')
        with self.assertRaisesRegex(ValueError, 'unmanifested'):
            release.source_payloads(source)
        extra.unlink()
        cache = source / '__pycache__' / 'fixture.pyc'
        cache.parent.mkdir()
        cache.write_bytes(b'reproducible cache')
        _, payloads = release.source_payloads(source)
        self.assertNotIn('__pycache__/fixture.pyc', payloads)

    def test_unsafe_manifest_paths_and_case_collisions_are_rejected(self):
        source = self.fixture()
        original = json.loads((source / 'MANIFEST.json').read_text())
        for path in ('../outside', '/absolute', 'C:/outside', 'a\\b', '.', 'a/./b', '.env', 'node_modules/file.js',
                     '__pycache__/x.pyc', 'file\x00.py', 'NUL.txt', 'folder./file.py', 'a?b'):
            with self.subTest(path=path):
                manifest = json.loads(json.dumps(original))
                manifest['files'][0]['path'] = path
                with self.assertRaises(ValueError):
                    release.manifest_files(json.dumps(manifest).encode())
        original['files'].append({**original['files'][0], 'path': original['files'][0]['path'].lower()})
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            release.manifest_files(json.dumps(original).encode())

    def test_source_symlink_is_rejected(self):
        source = self.fixture()
        link = source / 'extra-link'
        try:
            link.symlink_to(source / 'SKILL.md')
        except (OSError, NotImplementedError):
            self.skipTest('Creating symlinks is unavailable on this platform')
        with self.assertRaisesRegex(ValueError, 'Symlink'):
            release.source_payloads(source)

    def test_file_and_casefolded_ancestor_conflicts_fail_in_both_orders(self):
        source = self.fixture()
        _, base = release.source_payloads(source)
        for names in (('Foo', 'foo/child.txt'), ('foo/child.txt', 'Foo')):
            with self.subTest(order=names):
                payloads = {name: payload for name, payload in base.items() if name != 'MANIFEST.json'}
                payloads.update({name: b'conflict' for name in names})
                rows = [{'path': name, 'bytes': len(payload), 'sha256': release.digest(payload)}
                        for name, payload in payloads.items()]
                manifest = {'schema': 1, 'name': release.NAME, 'version': '0.13.0-alpha.1', 'files': rows,
                            'sourceManifestSHA256': release.digest(json.dumps(rows, sort_keys=True, separators=(',', ':')).encode())}
                raw_manifest = json.dumps(manifest).encode()
                with self.assertRaisesRegex(ValueError, 'conflict'):
                    release.manifest_files(raw_manifest)
                path = self.base / 'ancestor-conflict.zip'
                with zipfile.ZipFile(path, 'w') as archive:
                    # Preserve the attacker's order, instead of the builder's sort.
                    for name in names:
                        archive.writestr(release.NAME + '/' + name, payloads[name])
                    for name, payload in base.items():
                        archive.writestr(release.NAME + '/' + name,
                                         raw_manifest if name == 'MANIFEST.json' else payload)
                with self.assertRaisesRegex(ValueError, 'conflict'):
                    release.inspect_archive(path)

    def test_casefolded_directory_siblings_remain_valid(self):
        source = self.fixture()
        _, payloads = release.source_payloads(source)
        del payloads['MANIFEST.json']
        payloads.update({'Foo/first.txt': b'first', 'foo/second.txt': b'second'})
        self.write_manifest(source, payloads)
        payloads['MANIFEST.json'] = (source / 'MANIFEST.json').read_bytes()
        manifest, declarations = release.manifest_files(payloads['MANIFEST.json'])
        self.assertIn('Foo/first.txt', declarations)
        self.assertIn('foo/second.txt', declarations)
        receipt, checked = release.inspect_archive(self.archive(payloads))
        self.assertEqual(receipt['version'], manifest['version'])
        self.assertEqual(checked, payloads)

    def test_manifest_cannot_be_a_casefolded_parent_directory(self):
        source = self.fixture()
        _, payloads = release.source_payloads(source)
        del payloads['MANIFEST.json']
        payloads['manifest.JSON/child.txt'] = b'conflict'
        self.write_manifest(source, payloads)
        with self.assertRaisesRegex(ValueError, 'conflict'):
            release.manifest_files((source / 'MANIFEST.json').read_bytes())

    def test_cli_identity_and_manifest_digest_must_match(self):
        source = self.fixture()
        (source / 'scripts/greybox.py').write_text('print("9.9.9")\n')
        payloads = {p.relative_to(source).as_posix(): p.read_bytes() for p in source.rglob('*')
                    if p.is_file() and p.name != 'MANIFEST.json'}
        self.write_manifest(source, payloads)
        with self.assertRaisesRegex(ValueError, 'CLI'):
            release.build(source, self.base / 'out')
        manifest = json.loads((source / 'MANIFEST.json').read_text())
        manifest['sourceManifestSHA256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'manifest digest'):
            release.manifest_files(json.dumps(manifest).encode())

    def test_different_existing_release_is_preserved(self):
        source = self.fixture()
        output = self.base / 'out'
        output.mkdir()
        target = output / (release.NAME + '-0.13.0-alpha.1.zip')
        target.write_bytes(b'user existing archive')
        with self.assertRaisesRegex(ValueError, 'replace'):
            release.build(source, output)
        self.assertEqual(target.read_bytes(), b'user existing archive')
        self.assertEqual(list(output.iterdir()), [target])

    def test_different_receipt_does_not_replace_existing_outputs(self):
        source = self.fixture()
        result = release.build(source, self.base / 'out')
        archive = Path(result['output'])
        receipt = Path(str(archive) + '.release.json')
        receipt.write_bytes(b'user changed receipt')
        original_archive = archive.read_bytes()
        with self.assertRaisesRegex(ValueError, 'replace'):
            release.build(source, archive.parent)
        self.assertEqual(receipt.read_bytes(), b'user changed receipt')
        self.assertEqual(archive.read_bytes(), original_archive)

    def test_archive_traversal_extra_missing_and_symlink_are_rejected(self):
        source = self.fixture()
        _, payloads = release.source_payloads(source)
        for member in ('../outside', release.NAME + '/../../outside', '/outside', release.NAME + '/extra.txt'):
            with self.subTest(member=member):
                path = self.archive(payloads, {member: b'outside'})
                with self.assertRaises(ValueError):
                    release.inspect_archive(path)
        without = dict(payloads)
        del without['SKILL.md']
        with self.assertRaisesRegex(ValueError, 'missing'):
            release.inspect_archive(self.archive(without))
        path = self.archive(payloads)
        with zipfile.ZipFile(path, 'a') as archive:
            info = zipfile.ZipInfo(release.NAME + '/linked')
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, '/outside')
        with self.assertRaisesRegex(ValueError, 'linked'):
            release.inspect_archive(path)
        self.assertFalse((self.base / 'outside').exists())

    def test_archive_checksum_and_entry_hashes_are_checked(self):
        source = self.fixture()
        _, payloads = release.source_payloads(source)
        path = self.archive(payloads)
        with self.assertRaisesRegex(ValueError, 'SHA-256'):
            release.inspect_archive(path, '0' * 64)
        payloads['SKILL.md'] += b'changed'
        with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
            release.inspect_archive(self.archive(payloads))

    def test_verification_checks_sidecar_without_running_package_code(self):
        source = self.fixture()
        marker = self.base / 'should-not-exist'
        (source / 'scripts/greybox.py').write_text('from pathlib import Path\nPath(' + repr(str(marker)) + ').touch()\n')
        payloads = {p.relative_to(source).as_posix(): p.read_bytes() for p in source.rglob('*')
                    if p.is_file() and p.name != 'MANIFEST.json'}
        self.write_manifest(source, payloads)
        payloads['MANIFEST.json'] = (source / 'MANIFEST.json').read_bytes()
        path = self.archive(payloads)
        sidecar = Path(str(path) + '.sha256')
        sidecar.write_text(release.digest(path.read_bytes()) + '  ' + path.name + '\n')
        with redirect_stdout(io.StringIO()):
            self.assertEqual(release.main(['verify', str(path)]), 0)
        self.assertFalse(marker.exists())
        sidecar.write_text('0' * 64 + '  ' + path.name + '\n')
        with redirect_stderr(io.StringIO()):
            self.assertEqual(release.main(['verify', str(path)]), 1)


if __name__ == '__main__':
    unittest.main()
