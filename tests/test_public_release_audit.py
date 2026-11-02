import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'audit_public_release.py'
spec = importlib.util.spec_from_file_location('public_audit', SCRIPT)
audit_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit_module)


class PublicReleaseAuditTests(unittest.TestCase):
    def test_findings_never_echo_sensitive_values(self):
        secret = 'ghp_' + 'x' * 32
        report = audit_module.scan_text('example.md', ('access_token = "' + secret + '"').encode())
        self.assertTrue(report)
        self.assertNotIn(secret, json.dumps(report))
        self.assertEqual(report[0]['line'], 1)

    def test_internal_url_and_local_path_are_separate_review_items(self):
        data = b'https://wiki.internal/pages/example\n/home/example/private/file\n'
        kinds = {row['kind'] for row in audit_module.scan_text('guide.md', data)}
        self.assertEqual(kinds, {'internal_url', 'local_user_path'})

    def test_quoted_json_and_yaml_credentials_remain_redacted(self):
        secret = 'opaque-' + 'x' * 30
        for source in [json.dumps({'api_key': secret}), '"access_token": "' + secret + '"', "'secret': '" + secret + "'"]:
            with self.subTest(source_kind=source.split(':')[0]):
                findings = audit_module.scan_text('config.json', source.encode())
                self.assertEqual([row['kind'] for row in findings], ['credential_assignment_candidate'])
                self.assertNotIn(secret, json.dumps(findings))

    def test_binary_content_does_not_become_a_clean_text_claim(self):
        self.assertEqual(audit_module.scan_text('invalid.md', b'\xff\xfe'), [])

    def test_working_tree_and_history_preserve_distinct_identity(self):
        executable = shutil.which('git') or '/usr/bin/git'
        with tempfile.TemporaryDirectory(prefix='grey2art-public-audit-') as temporary:
            root = Path(temporary)
            def run(*args):
                return subprocess.check_output([executable, '-C', str(root), *args], stderr=subprocess.PIPE)
            run('init', '-q')
            run('config', 'user.email', 'fixture@example.invalid')
            run('config', 'user.name', 'Synthetic fixture')
            (root / 'README.md').write_text('Old content\n')
            run('add', 'README.md')
            run('commit', '-qm', 'fixture')
            (root / 'README.md').write_text('https://git.internal/example\n')
            (root / 'invalid.md').write_bytes(b'\xff\xfe')
            current = audit_module.audit(root)
            frozen = audit_module.audit(root, 'HEAD')
            historical = audit_module.audit(root, 'HEAD', True)
            self.assertEqual(current['counts']['internal_url'], 1)
            self.assertEqual(frozen['counts']['internal_url'], 0)
            self.assertEqual(historical['counts']['internal_url'], 0)
            self.assertNotEqual(current['inventory_sha256'], frozen['inventory_sha256'])
            self.assertFalse(current['publication_approved'])
            self.assertIn({'path': 'invalid.md', 'reason': 'non_utf8_text_candidate'}, current['skipped'])

    def test_symlink_is_not_followed(self):
        executable = shutil.which('git') or '/usr/bin/git'
        with tempfile.TemporaryDirectory(prefix='grey2art-public-audit-link-') as temporary:
            root = Path(temporary) / 'repository'
            root.mkdir()
            subprocess.run([executable, '-C', str(root), 'init', '-q'], check=True)
            subprocess.run([executable, '-C', str(root), 'config', 'user.email', 'fixture@example.invalid'], check=True)
            subprocess.run([executable, '-C', str(root), 'config', 'user.name', 'Fixture'], check=True)
            (root / 'LICENSE').write_text('fixture')
            subprocess.run([executable, '-C', str(root), 'add', 'LICENSE'], check=True)
            subprocess.run([executable, '-C', str(root), 'commit', '-qm', 'fixture'], check=True)
            (Path(temporary) / 'private.md').write_text('sensitive external input')
            try:
                (root / 'linked.md').symlink_to(Path(temporary) / 'private.md')
            except OSError:
                self.skipTest('Symlink creation unavailable')
            result = audit_module.audit(root)
            self.assertIn({'path': 'linked.md', 'reason': 'symlink_or_outside_root'}, result['skipped'])
            self.assertEqual(result['reviewed_text_objects'], 1)


if __name__ == '__main__':
    unittest.main()
