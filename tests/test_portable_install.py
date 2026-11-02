"""Exercise the real offline installer in a Unicode/space path on every CI OS."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills/greybox-to-multistyle-art'


class PortableInstall(unittest.TestCase):
    def command(self, *args):
        environment = os.environ.copy()
        environment['PYTHONIOENCODING'] = 'cp1252'
        result = subprocess.run([sys.executable, '-B', str(SKILL / 'scripts/install.py'), *map(str, args)],
                                capture_output=True, text=True, encoding='utf-8', env=environment, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_real_manifest_install_reuse_and_private_configuration(self):
        with tempfile.TemporaryDirectory(prefix='greybox-portable-') as temporary:
            base = Path(temporary) / '中文 with spaces'
            destination = base / 'skills'
            value = self.command('--skills-dir', destination, '--config-dir', base / 'config')
            installed = Path(value['path'])
            self.assertEqual(installed, destination / 'greybox-to-multistyle-art')
            self.assertTrue((installed / 'LICENSE').is_file())
            before = hashlib.sha256((installed / 'MANIFEST.json').read_bytes()).hexdigest()
            second = self.command('--skills-dir', destination, '--config-dir', base / 'config')
            self.assertEqual(second['copiedBytes'], 0)
            self.assertEqual(hashlib.sha256((installed / 'MANIFEST.json').read_bytes()).hexdigest(), before)
            for name in ['.venv', '.godot', 'node_modules', 'docs/demo']:
                self.assertFalse((installed / name).exists())
            version = subprocess.run([sys.executable, '-B', str(installed / 'scripts/greybox.py'), '--version'],
                                     capture_output=True, text=True, timeout=15)
            self.assertEqual(version.returncode, 0, version.stderr)
            self.assertIn(json.loads((installed / 'MANIFEST.json').read_text(encoding='utf-8'))['version'], version.stdout)

    def test_unicode_cli_error_works_with_non_utf8_stdio(self):
        environment = os.environ.copy()
        environment['PYTHONIOENCODING'] = 'cp1252'
        # Argparse errors are plain text; use a valid command that reports an absent Unicode path.
        with tempfile.TemporaryDirectory(prefix='greybox-portable-error-') as temporary:
            path = Path(temporary) / '\u4e2d\u6587-missing.json'
            run = subprocess.run([sys.executable, '-B', str(SKILL / 'scripts/greybox.py'),
                                  'plan', '--file', str(path), '--project', temporary,
                                  '--run-dir', str(Path(temporary) / 'run')],
                                 capture_output=True, encoding='utf-8', env=environment, timeout=30)
            self.assertNotEqual(run.returncode, 0)
            value = json.loads(run.stderr or run.stdout)
            self.assertEqual(value['type'], 'FileNotFoundError')
            self.assertIn(repr(str(path)), value['error'])

    def test_mcp_preserves_non_ascii_argparse_diagnostic(self):
        environment = os.environ.copy()
        environment.update(PYTHONIOENCODING='cp1252', PYTHONPATH=str(SKILL / 'runtime'))
        code = ("import json; from greybox.mcp_bridge import call_tool; "
                "print(json.dumps(call_tool('greybox_cli', {'argv': ['caf\u00e9']}), ensure_ascii=True))")
        run = subprocess.run([sys.executable, '-B', '-c', code], capture_output=True,
                             encoding='utf-8', env=environment, timeout=30)
        self.assertEqual(run.returncode, 0, run.stderr)
        response = json.loads(run.stdout)
        self.assertTrue(response['isError'])
        self.assertIn('caf\u00e9', response['content'][0]['text'])
        self.assertIn('invalid choice', response['content'][0]['text'])

    def test_mcp_roundtrips_raw_utf8_id_under_non_utf8_locale(self):
        environment = os.environ.copy()
        environment.update(PYTHONIOENCODING='cp1252', PYTHONPATH=str(SKILL / 'runtime'))
        request = {'jsonrpc': '2.0', 'id': '\u4e2d\u6587-identifier', 'method': 'unknown-method'}
        run = subprocess.run([sys.executable, '-B', '-c',
                              'from greybox.mcp_bridge import serve; serve()'],
                             input=(json.dumps(request, ensure_ascii=False) + '\n').encode('utf-8'),
                             capture_output=True, env=environment, timeout=30)
        self.assertEqual(run.returncode, 0, run.stderr.decode('utf-8'))
        response = json.loads(run.stdout.decode('utf-8'))
        self.assertEqual(response['id'], request['id'])
        self.assertEqual(response['error']['code'], -32601)


if __name__ == '__main__':
    unittest.main()
