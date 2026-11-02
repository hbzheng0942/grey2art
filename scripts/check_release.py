#!/usr/bin/env python3
"""Verify the distributable skill and public-source boundaries without cloud calls."""
from pathlib import Path
from html import unescape
from html.parser import HTMLParser
import hashlib
import importlib.util
import json
import re
import sys
import unicodedata
from urllib.parse import unquote, urlsplit

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / 'skills' / 'greybox-to-multistyle-art'


class DocumentHTML(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.references = []
        self.anchors = set()
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        for name in ('src', 'href', 'poster'):
            if attrs.get(name):
                self.references.append(attrs[name])
        if attrs.get('id'):
            self.anchors.add(attrs['id'])
        if tag == 'a' and attrs.get('name'):
            self.anchors.add(attrs['name'])


def without_fenced_code(text):
    lines, fence = [], None
    for line in text.splitlines():
        marker = re.match(r'^ {0,3}(`{3,}|~{3,})', line)
        if marker:
            value = marker.group(1)
            if fence is None:
                fence = value
            elif value[0] == fence[0] and len(value) >= len(fence):
                fence = None
            lines.append('')
        else:
            lines.append(line if fence is None else '')
    return '\n'.join(lines)


def document_anchors(path):
    text = path.read_text(encoding='utf-8')
    if path.suffix == '.md':
        text = without_fenced_code(text)
    anchors = DocumentHTML(text).anchors
    used = set(anchors)
    if path.suffix == '.md':
        for heading in re.findall(r'^ {0,3}#{1,6}\s+(.+?)\s*#*\s*$', text, re.M):
            heading = re.sub(r'<[^>]*>', '', unescape(heading)).lower()
            heading = re.sub(r'\[([^]]+)\]\([^)]*\)', r'\1', heading)
            slug = ''.join(c for c in heading if c in '-_ ' or unicodedata.category(c)[0] in 'LMN')
            slug = slug.replace(' ', '-')
            candidate, suffix = slug, 0
            while candidate in used:
                suffix += 1
                candidate = slug + '-' + str(suffix)
            used.add(candidate)
            anchors.add(candidate)
    return anchors


def check_document_links(path, root, check_fragments=False):
    """Check local resources; strict fragment checks apply to the two homepages."""
    text = path.read_text(encoding='utf-8')
    references = []
    if path.suffix == '.md':
        text = without_fenced_code(text)
        text = re.sub(r'(`+).*?\1', '', text)
        references.extend(re.findall(r'\]\(\s*(<[^>]+>|[^\s)]+)(?:\s+["\'][^)]*)?\)', text))
    references.extend(DocumentHTML(text).references)
    count = 0
    for reference in references:
        reference = unescape(reference.strip('<>'))
        if reference.startswith('$'):
            continue
        parsed = urlsplit(reference)
        if parsed.netloc or parsed.scheme:
            assert parsed.scheme != 'file', 'Local file URL in ' + str(path.relative_to(root))
            continue
        relative = unquote(parsed.path)
        target = (root / relative.lstrip('/') if relative.startswith('/') else path.parent / relative) if relative else path
        assert target.exists(), 'Broken relative link in ' + str(path.relative_to(root)) + ': ' + reference
        if check_fragments and parsed.fragment and target.suffix in {'.md', '.html'}:
            fragment = unquote(parsed.fragment)
            assert fragment in document_anchors(target), 'Broken anchor in ' + str(path.relative_to(root)) + ': ' + reference
        count += 1
    return count


def main():
    spec = importlib.util.spec_from_file_location('release_installer', SKILL / 'scripts' / 'install.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    manifest, files = module.verified_files(SKILL)
    assert manifest['name'] == 'greybox-to-multistyle-art'
    assert re.search(r'^name: greybox-to-multistyle-art$', (SKILL / 'SKILL.md').read_text(encoding='utf-8'), re.M)
    sys.path.insert(0, str(SKILL / 'runtime'))
    from greybox import VERSION
    assert VERSION == manifest['version'], 'Code and package versions differ'
    assert (ROOT / 'LICENSE').read_bytes() == (SKILL / 'LICENSE').read_bytes(), 'Installable license differs'
    expected = {str(rel) for rel, path in files} | {'MANIFEST.json'}
    actual = {p.relative_to(SKILL).as_posix() for p in SKILL.rglob('*') if p.is_file()
              and '__pycache__' not in p.parts and p.name != '.DS_Store' and p.suffix not in {'.pyc', '.pyo'}}
    assert actual == expected, 'Unmanifested or missing source files'
    for forbidden in ['runtime/legacy/experiments', 'runtime/legacy/inputs']:
        assert not (SKILL / forbidden).exists(), 'Private legacy case data must not ship'
    vendor = SKILL / 'runtime' / 'vendor'
    for row in json.loads((vendor / 'manifest.json').read_text(encoding='utf-8'))['files']:
        data = (vendor / row['path']).read_bytes()
        assert len(data) == row['bytes'] and hashlib.sha256(data).hexdigest() == row['sha256'], row['path']
    for p in [*SKILL.rglob('*'), *ROOT.glob('*.md'), *ROOT.joinpath('docs').rglob('*'),
              *ROOT.joinpath('.github').rglob('*')]:
        if not p.is_file() or '__pycache__' in p.parts:
            continue
        if p.suffix in {'.md', '.html', '.json', '.py', '.gd', '.cs', '.tscn', '.txt', '.yml', '.yaml', '.mjs', '.js'}:
            text = p.read_text(encoding='utf-8')
            assert not re.search(r'/Users/[^\s]+|/home/[^\s]+', text), 'Local user path in ' + str(p.relative_to(ROOT))
            if p.suffix in {'.md', '.html'}:
                check_document_links(p, ROOT, check_fragments=p in {ROOT / 'README.md', ROOT / 'README.zh-CN.md'})
    print(json.dumps({'ok': True, 'name': manifest['name'], 'version': VERSION,
                      'source_files': len(files), 'vendor_hashes': 'passed',
                      'private_case_data': 'excluded', 'cloud_calls': 0}, indent=2))


if __name__ == '__main__':
    main()
