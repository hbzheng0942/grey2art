import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'check_release.py'
spec = importlib.util.spec_from_file_location('document_release_check', SCRIPT)
release_check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release_check)


class PublicDocumentLinksTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='grey2art-document-links-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        return path

    def check(self, document, strict=True):
        return release_check.check_document_links(document, self.root, check_fragments=strict)

    def test_missing_html_image_or_link_fails(self):
        for content in ('<img src="missing.png">', '<a href="missing.md">Read more</a>'):
            with self.subTest(content=content):
                document = self.write('README.md', content)
                with self.assertRaisesRegex(AssertionError, 'Broken relative link'):
                    self.check(document)

    def test_external_and_embedded_urls_need_no_local_files(self):
        document = self.write('README.md', '''
[Docs](https://example.invalid/docs#install)
<a href="mailto:maintainer@example.invalid">Email</a>
<img src="//example.invalid/preview.png">
<img src="data:image/png;base64,AA==">
''')
        self.assertEqual(self.check(document), 0)

    def test_local_html_media_and_markdown_links_are_checked(self):
        self.write('media/clip.mp4', 'fixture')
        self.write('media/frame.png', 'fixture')
        self.write('docs/My Guide.md', '# Guide\n')
        document = self.write('README.md', '''
<video poster="media/frame.png"><source src="media/clip.mp4"></video>
[Guide](docs/My%20Guide.md?raw=1#guide)
''')
        self.assertEqual(self.check(document), 3)
        (self.root / 'media/frame.png').unlink()
        with self.assertRaisesRegex(AssertionError, 'media/frame.png'):
            self.check(document)

    def test_homepage_fragment_checks_english_chinese_and_duplicate_headings(self):
        document = self.write('README.md', '''
[Start](#quickstart) · [中文](#%E5%BF%AB%E9%80%9F%E5%BC%80%E5%A7%8B) · [Again](#quickstart-1)
## Quickstart
## 快速开始
## Quickstart
''')
        self.assertEqual(self.check(document), 3)

    def test_missing_anchor_fails_only_when_requested(self):
        document = self.write('README.md', '[Start](#missing)\n## Quickstart\n')
        with self.assertRaisesRegex(AssertionError, 'Broken anchor'):
            self.check(document)
        self.assertEqual(self.check(document, strict=False), 1)

    def test_cross_document_and_explicit_html_anchors(self):
        self.write('docs/guide.md', '## Use the `CLI`\n<a id="native-sample"></a>\n')
        self.write('docs/player.html', '<section id="player"></section>')
        document = self.write('README.md', '''
[CLI](/docs/guide.md#use-the-cli)
<a href="docs/guide.md#native-sample">Native</a>
[Play](docs/player.html#player)
''')
        self.assertEqual(self.check(document), 3)

    def test_code_examples_are_not_published_links(self):
        document = self.write('README.md', '''
```html
<img src="example-only.png">
[Example](missing.md)
```
`<a href="also-example.md">example</a>`
''')
        self.assertEqual(self.check(document), 0)

    def test_machine_file_urls_do_not_count_as_external_links(self):
        document = self.write('README.md', '<img src="file:///private/example.png">')
        with self.assertRaisesRegex(AssertionError, 'Local file URL'):
            self.check(document)

    def test_release_check_does_not_depend_on_locale_encoding(self):
        environment = os.environ.copy()
        environment.update(LC_ALL='C', PYTHONUTF8='0',
                           PYTHONCOERCECLOCALE='0', PYTHONIOENCODING='utf-8')
        result = subprocess.run(
            [sys.executable, '-X', 'utf8=0', str(SCRIPT)],
            cwd=SCRIPT.parent.parent, env=environment,
            capture_output=True, encoding='utf-8', timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
