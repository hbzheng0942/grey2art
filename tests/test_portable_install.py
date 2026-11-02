"""Exercise the real offline installer in a Unicode/space path on every CI OS."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills/greybox-to-multistyle-art'


class PortableInstall(unittest.TestCase):
    def command(self, *args):
        result = subprocess.run([sys.executable, '-B', str(SKILL / 'scripts/install.py'), *map(str, args)],
                                capture_output=True, text=True, encoding='utf-8', timeout=30)
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
            self.assertIn(json.loads((installed / 'MANIFEST.json').read_text())['version'], version.stdout)


if __name__ == '__main__':
    unittest.main()
