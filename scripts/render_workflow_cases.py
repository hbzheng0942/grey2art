#!/usr/bin/env python3
"""Render bilingual Hole and Train workflow figures from actual case images."""
from pathlib import Path
import argparse
import hashlib
import html
import json
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / 'docs' / 'demo'
WIDTH = 1800
TRAIN_INPUTS = {
    'workflow-train-clay-assembly.png': 'art/workflows/clay-pilot/production-v3/review-08/station-02.png',
    'workflow-train-clay-native.jpg': 'art/workflows/clay-pilot/production-v3/review-21/station-01.jpg',
}
HOLE_STYLES = ['amusement', 'lunar', 'coral', 'papercraft', 'saffron', 'snack']
STYLE_NAMES = {
    'en': ['Amusement park', 'Lunar base', 'Coral market', 'Paper snow town', 'Desert caravan', 'Snack town'],
    'zh-CN': ['游乐园', '月面基地', '珊瑚海集市', '纸艺雪镇', '沙漠商队', '零食店'],
}
LABELS = {
    'en': {
        'hole': 'Hole · Ceramic Town', 'train': 'Train Parkour · Clay World',
        'greybox': 'Gameplay greybox', 'concept': 'Scene concept',
        'assembly': 'Native assembly', 'styles': 'Playable art worlds',
        'recipe': 'Spatial recipe', 'assembly_plan': 'Assembly design', 'asset_board': 'Asset board', 'model': '3D asset', 'assembly_sample': 'Assembly sample', 'native': 'Playable result', 'extension': 'Style expansion',
        'suite': 'Scene concepts',
    },
    'zh-CN': {
        'hole': '黑洞 · 陶瓷小镇', 'train': '列车跑酷 · 黏土世界',
        'greybox': '玩法灰盒', 'concept': '场景概念',
        'assembly': '原生装配', 'styles': '多风格可玩原型',
        'recipe': '空间配方解析', 'assembly_plan': '场景组装设计', 'asset_board': '资产图板', 'model': '3D资产', 'assembly_sample': '组装样段', 'native': '可玩结果', 'extension': '风格拓展',
        'suite': '多场景概念',
    },
}


def identity(path):
    data = path.read_bytes()
    return {'file': path.name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}


def prepare_train_inputs(train_root):
    sources = []
    for target_name, source_relative in TRAIN_INPUTS.items():
        source, target = train_root / source_relative, MEDIA / target_name
        if not source.is_file() or source.is_symlink():
            raise ValueError('Missing regular source image: ' + source_relative)
        expected = identity(source)
        if target.exists():
            if target.is_symlink() or identity(target)['sha256'] != expected['sha256']:
                raise ValueError('Preserve existing changed input: ' + target_name)
        else:
            shutil.copy2(source, target)
        assert identity(target)['sha256'] == expected['sha256']
        row = {**identity(target), 'source_project': 'train-parkour',
               'source_path': source_relative, 'treatment': 'original bytes'}
        row['kind'] = {'workflow-train-clay-assembly.png': 'P8 actual native assembly candidate; not final art acceptance',
                       'workflow-train-clay-native.jpg': 'P21 native review frame; not human art acceptance'}[target_name]
        sources.append(row)
    return sources


def image(name, alt):
    return f'<img src="{html.escape(name)}" alt="{html.escape(alt)}">'


def source_record(train_root, relative):
    return {**identity(train_root / relative), 'source_project': 'train-parkour',
            'source_path': relative}


def svg_text(x, y, text, size=68, color='#29463a', anchor='middle'):
    return (f'<text x="{x:g}" y="{y:g}" font-size="{size}" fill="{color}" '
            f'text-anchor="{anchor}" dominant-baseline="middle">{html.escape(text)}</text>')


def svg_document(body):
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="1500" height="1000" '
            'viewBox="0 0 1500 1000"><style>text{font-family:"Noto Sans SC",'
            '"PingFang SC",Arial,sans-serif}</style><rect width="1500" height="1000" '
            'fill="#f7f8f3"/>' + body + '</svg>')


def prepare_asset_board(train_root, browser):
    """Curate actual image-conditioned asset references, not model renders."""
    base = 'art/workflows/clay-pilot/production-v3/'
    selections = {name: json.loads((train_root / base / name).read_text()) for name in
                  ['lux-enrichment/selection.json', 'hero-standard/selection.json',
                   'hero-assets/production-plan.json', 'lux-enrichment/plan.json',
                   'hero-standard/plan.json', 'hero-assets/plan.json']}
    cards = [
        ('terrace-garden-house', 'lux-enrichment/references/terrace-garden-house.png',
         'lux-enrichment/selection.json', 'Garden house · Street', '花园屋 · 街区'),
        ('station-corner-pavilion', 'hero-assets/references/station-corner-pavilion.png',
         'hero-standard/selection.json', 'Pavilion · Plaza', '观景亭 · 广场'),
        ('island-city-crown', 'hero-assets/references/island-city-crown.png',
         'hero-standard/selection.json', 'Island city · Vista', '岛城 · 远景'),
        ('clay-flower-shrub-cluster', 'hero-assets/references/clay-flower-shrub-cluster.png',
         'hero-assets/production-plan.json', 'Shrubs · Dressing', '花灌木 · 布景'),
    ]
    dependencies = []
    for asset_id, source_path, selection_path, _, _ in cards:
        selection = selections[selection_path]
        entry = next(item for item in selection.get('assets', selection.get('first_batch', []))
                     if item['id'] == asset_id)
        if 'source_review_passed' in entry:
            assert entry['source_review_passed'] is True, asset_id
        plan = next(item for plan in selections.values() for item in plan.get('assets', [])
                    if item['id'] == asset_id and item.get('reference_sha256'))
        source = train_root / base / source_path
        assert identity(source)['sha256'] == plan['reference_sha256'], asset_id
        dependencies.append({**source_record(train_root, base + source_path), 'asset': asset_id,
                             'kind': 'actual image-generation modeling reference; not a GLB render',
                             'selection': source_record(train_root, base + selection_path),
                             'recorded_use': entry.get('approved_use', entry.get('brief', '')),
                             'selection_state': entry.get('state', 'source_review_passed_scene_candidate')})
    outputs = []
    for language in ['en', 'zh-CN']:
        figures = ''.join('<figure><img src="' + (train_root / base / source).as_uri() +
                          '" alt="' + asset_id + '"><figcaption>' + html.escape(zh if language == 'zh-CN' else en) +
                          '</figcaption></figure>' for asset_id, source, _, en, zh in cards)
        body = '''<!doctype html><meta charset="utf-8"><style>
*{box-sizing:border-box}body{margin:0;background:white;color:#29463a;font-family:"Noto Sans SC","PingFang SC",Arial,sans-serif}
main{width:1500px;height:1000px;display:grid;grid-template-columns:repeat(2,1fr);grid-template-rows:repeat(2,1fr);gap:12px;padding:12px;background:#e8ece3}
figure{margin:0;min-width:0;min-height:0;background:white;display:grid;grid-template-rows:minmax(0,1fr) 80px}
img{width:100%;height:100%;min-height:0;object-fit:contain;display:block}
figcaption{font-size:62px;line-height:80px;text-align:center;white-space:nowrap}
</style><main>''' + figures + '</main><script>addEventListener("load",()=>document.documentElement.dataset.captureHeight=1000)</script>'
        with tempfile.TemporaryDirectory(prefix='grey2art-asset-board-') as temporary:
            target = Path(temporary) / 'board.html'
            target.write_text(body, encoding='utf-8')
            capture(target, browser, 1500)
            output = MEDIA / f'workflow-train-clay-assets.{language}.png'
            shutil.copy2(target.with_suffix('.png'), output)
        outputs.append({**identity(output), 'language': language})
    return {'kind': 'curated asset reference board', 'outputs': outputs, 'sources': dependencies,
            'treatment': 'Four existing modeling references and concise intended roles. Complete reference subjects are preserved on white; source bytes unchanged. No new image generation and no model render claim.',
            'scope': 'Curated from actual references and selection/production records, not an original historical board. Selected model candidates retain their recorded quality and distance limits; the reference board does not certify their rendered output.'}


def prepare_design_diagrams(train_root):
    """Reconstruct readable diagrams from actual recipe, plan and placements.

    These are editorial diagrams, not historical production screenshots or a
    replacement for the source project's metric layout and acceptance records.
    """
    base = 'art/workflows/clay-pilot/'
    plan = json.loads((train_root / base / 'scene-production-plan.json').read_text())
    recipe = json.loads((train_root / base / 'production-v1/recipe.json').read_text())
    greybox = json.loads((train_root / base / 'greybox.json').read_text())
    assembly = json.loads((train_root / base / 'production-v3/assembly.json').read_text())
    scenes = plan['scenes']
    assert len(scenes) == 7 and len(greybox['tracks']) == 37
    assert recipe['tunnel']['rib_spacing_m'] == 24
    assert recipe['tunnel']['lamp_spacing_m'] == 48
    outputs = []
    for language in ['en', 'zh-CN']:
        zh = language == 'zh-CN'
        names = (['站场', '峡谷', '立体站', '回环', '隧道', '山谷', '终点'] if zh else
                 ['Station', 'Canyon', 'Vertical', 'Loop', 'Tunnel', 'Valley', 'Finale'])
        # Seven scene beats, not a claim to reproduce the route's full topology.
        points = [(220, 210), (575, 210), (930, 210), (1285, 210),
                  (1285, 440), (930, 440), (575, 440)]
        body = svg_text(80, 77, '场景节奏' if zh else 'Scene beats', 70, anchor='start')
        for (x1, y1), (x2, y2) in zip(points, points[1:]):
            body += f'<path d="M{x1},{y1} L{x2},{y2}" stroke="#afbaad" stroke-width="14" fill="none"/>'
        for index, ((x, y), name) in enumerate(zip(points, names)):
            palette = plan['world_design']['beats'][index]['palette']
            body += f'<rect x="{x-140}" y="{y-72}" width="280" height="144" rx="24" fill="{palette[0]}"/>'
            body += svg_text(x, y, name, 64, '#fbf9f0' if index == 4 else '#203a2c')
        # A concrete, verified first-kit rule makes the recipe legible without
        # turning the figure into a screenshot of a configuration document.
        body += '<path d="M100,675 H1400" stroke="#a7a0b8" stroke-width="38"/>'
        for x in range(100, 1401, 130):
            body += f'<path d="M{x},645 V705" stroke="#c98e67" stroke-width="18"/>'
        for x in range(100, 1401, 260):
            body += f'<path d="M{x},620 V655" stroke="#477b70" stroke-width="10"/><circle cx="{x}" cy="610" r="16" fill="#ddad57"/>'
        body += svg_text(750, 785, '肋骨 24 m · 灯具 48 m' if zh else 'Ribs 24 m · Lights 48 m', 70)
        body += svg_text(750, 910, '空间验证：灰盒内粗搭' if zh else 'Validate space in the greybox', 64, '#547360')
        target = MEDIA / f'workflow-train-clay-recipe.{language}.svg'
        target.write_text(svg_document(body), encoding='utf-8')
        outputs.append({**identity(target), 'language': language, 'diagram': 'spatial_recipe',
                        'kind': 'editorial diagram reconstructed from actual recipe and world design',
                        'source_records': [source_record(train_root, base + 'scene-production-plan.json'),
                                           source_record(train_root, base + 'production-v1/recipe.json')],
                        'source_design_state': plan['world_design']['status'],
                        'scope': 'Seven proposed scene beats and actual v1 first-kit spacing. Not exact route topology, current P21 parameter certification or accepted art.'})

        # Plot actual station-area origin records. The markers show module
        # centers, not invented building footprints or reconstructed 3D meshes.
        station_tracks = [track for track in greybox['tracks']
                          if track['id'] in ['station_start', 'station_carve']]
        selected = [item for item in assembly['instances']
                    if -250 <= item['origin'][0] <= 250
                    and 1250 <= item['origin'][2] <= 2350]
        assert station_tracks and selected
        def point(origin):
            return 160 + (2350 - origin[2]) * 1.04, 190 + (origin[0] + 250) * 1.04
        colors = {'architecture': '#cf8e6f', 'nature': '#86a98c', 'props': '#d6b568'}
        counts = {key: 0 for key in colors}
        body = svg_text(80, 77, '站场布局' if zh else 'Station layout', 70, anchor='start')
        body += '<rect x="85" y="145" width="1330" height="610" rx="24" fill="#edf0e7"/>'
        for item in selected:
            name = item['id']
            group = ('architecture' if any(key in name for key in ['house', 'tower', 'arcade', 'canopy', 'pavilion', 'station']) else
                     'nature' if any(key in name for key in ['garden', 'cypress', 'cliff', 'shrub', 'tree']) else
                     'props')
            counts[group] += 1
            x, y = point(item['origin'])
            if group == 'architecture':
                body += f'<rect x="{x-7:.2f}" y="{y-5:.2f}" width="14" height="10" rx="2" fill="{colors[group]}" opacity=".82"/>'
            else:
                body += f'<circle cx="{x:.2f}" cy="{y:.2f}" r="4.5" fill="{colors[group]}" opacity=".7"/>'
        for track in station_tracks:
            coords = ' '.join(f'{point(sample["origin"])[0]:.2f},{point(sample["origin"])[1]:.2f}'
                              for sample in track['samples'])
            body += f'<polyline points="{coords}" fill="none" stroke="#6d6782" stroke-width="30" stroke-linecap="round" stroke-linejoin="round"/>'
            body += f'<polyline points="{coords}" fill="none" stroke="#e4d6c0" stroke-width="6"/>'
        labels = ['建筑', '绿化', '灯具/道具'] if zh else ['Architecture', 'Garden', 'Props / lights']
        for x, group, label in zip([270, 750, 1230], colors, labels):
            body += f'<circle cx="{x}" cy="780" r="18" fill="{colors[group]}"/>'
            body += svg_text(x, 840, label, 58)
        body += svg_text(750, 935, '结构 → 主资产 → 布置' if zh else 'Structure → Main assets → Dressing', 64, '#547360')
        target = MEDIA / f'workflow-train-clay-assembly-design.{language}.svg'
        target.write_text(svg_document(body), encoding='utf-8')
        outputs.append({**identity(target), 'language': language, 'diagram': 'assembly_design',
                        'kind': 'editorial station diagram reconstructed from actual route samples and assembly instance origins',
                        'source_records': [source_record(train_root, base + 'scene-production-plan.json'),
                                           source_record(train_root, base + 'greybox.json'),
                                           source_record(train_root, base + 'production-v3/assembly.json')],
                        'display_roi': {'x': [-250, 250], 'z': [1250, 2350]},
                        'selected_instance_origins': len(selected), 'category_counts': counts,
                        'scope': 'Simplified top-down origin markers and actual station track samples. Markers are not metric footprints, an original historical planning screenshot or an accepted construction plan.'})
    return outputs


def prepare_hole_inputs():
    rows = []
    for style in HOLE_STYLES:
        target = MEDIA / f'hole-reference-{style}.png'
        if not target.is_file() or target.is_symlink():
            raise ValueError('Missing regular fixed-camera frame: ' + target.name)
        rows.append({**identity(target), 'source_project': 'hole',
                     'source_receipt': 'docs/demo/hole-workflow-camera.json',
                     'kind': 'Godot native style frame, camera matched to selected ceramic view',
                     'treatment': 'original fixed-camera capture bytes'})
    return rows


def concept_suite(train_root, browser):
    dependencies, pictures = [], []
    for view in ['station', 'canyon', 'tunnel', 'finale-v2']:
        relative = f'art/workflows/clay-pilot/production-v1/concepts/{view}.png'
        source = train_root / relative
        dependencies.append({**identity(source), 'source_path': relative, 'kind': 'scene concept'})
        pictures.append(f'<img src="{source.as_uri()}" alt="{view}" width="1672" height="941">')
    body = '<!doctype html><meta charset="utf-8"><style>*{box-sizing:border-box}body{margin:0;background:#f2f4f0}main{width:1600px;display:grid;grid-template-columns:repeat(2,1fr);gap:8px}img{width:100%;height:100%;aspect-ratio:3/2;object-fit:cover;display:block}</style><main>' + ''.join(pictures) + '</main><script>addEventListener("load",()=>document.documentElement.dataset.captureHeight=Math.ceil(document.querySelector("main").getBoundingClientRect().height))</script>'
    with tempfile.TemporaryDirectory(prefix='grey2art-concept-suite-') as temporary:
        target = Path(temporary) / 'suite.html';target.write_text(body)
        capture(target, browser, 1600)
        shutil.copy2(target.with_suffix('.png'), MEDIA / 'workflow-train-clay-concepts.png')
    return {**identity(MEDIA / 'workflow-train-clay-concepts.png'), 'kind': 'four actual clay scene concepts',
            'dependencies': dependencies, 'treatment': 'Four actual concept sources proportionally cropped to aligned 3:2 windows; no stretching or native-frame claim',
            'temporary_html_removed': True}


def gallery(files, names, class_name):
    return f'<div class="{class_name}">' + ''.join(
        '<figure><div class="frame">' + image(file, name) + f'</div><figcaption>{html.escape(name)}</figcaption></figure>'
        for file, name in zip(files, names)) + '</div>'


def capture(target, browser, width):
    with tempfile.TemporaryDirectory(prefix='grey2art-workflow-case-') as profile:
        common = [str(browser), '--headless', '--disable-gpu', '--hide-scrollbars',
                  '--no-first-run', '--no-default-browser-check', f'--user-data-dir={profile}',
                  '--force-device-scale-factor=1', '--virtual-time-budget=2500']
        dom = subprocess.run(common + [f'--window-size={width},1000', '--dump-dom', target.as_uri()],
                             check=True, capture_output=True, text=True, timeout=45)
        match = re.search(r'data-capture-height="(\d+)"', dom.stdout)
        if not match:
            raise RuntimeError('No document-height observation: ' + target.name)
        height = int(match.group(1))
        if not 100 <= height <= 10000:
            raise ValueError('Unexpected document height')
        subprocess.run(common + [f'--window-size={width},{height}',
                       f'--screenshot={target.with_suffix(".png")}', target.as_uri()],
                       check=True, capture_output=True, timeout=45)
    return height


def document(case, language):
    words = LABELS[language]
    if case == 'hole':
        panels = [
            ('greybox', image('hole-reference-greybox.png', words['greybox'])),
            ('concept', image('ceramic-workflow-concept.png', words['concept'])),
            ('assembly', image('ceramic-workflow-assembly.png', words['assembly'])),
            ('styles', gallery([f'hole-reference-{style}.png' for style in HOLE_STYLES], STYLE_NAMES[language], 'hole-worlds')),
        ]
    else:
        panels = [
            ('greybox', image('train-greybox-native.jpg', words['greybox'])),
            ('suite', image('workflow-train-clay-concepts.png', words['suite'])),
            ('recipe', image(f'workflow-train-clay-recipe.{language}.svg', words['recipe'])),
            ('assembly_plan', image(f'workflow-train-clay-assembly-design.{language}.svg', words['assembly_plan'])),
            ('asset_board', image(f'workflow-train-clay-assets.{language}.png', words['asset_board'])),
            ('model', image('workflow-train-clay-model-preview.png', words['model'])),
            ('assembly_sample', image('workflow-train-clay-assembly.png', words['assembly_sample'])),
            ('native', image('workflow-train-clay-native.jpg', words['native'])),
            ('extension', image('train-pixel-native.jpg', words['extension'])),
        ]
    cards = ''.join(
        f'<section data-step="{key}"><h2><span>{index:02}</span>{words[key]}</h2><div class="picture">{visual}</div></section>'
        for index, (key, visual) in enumerate(panels, 1))
    return f'''<!doctype html><html lang="{language}"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{words[case]} · Grey2Art</title><style>
@font-face{{font-family:Grey2Art;src:url('fonts/NotoSansCJKsc-2.004-showcase-subset.woff2') format('woff2');font-weight:400;font-display:block}}
*{{box-sizing:border-box}}html,body{{margin:0;background:#f2f4f0;color:#1c2b25;font-family:Grey2Art,"PingFang SC","Noto Sans SC",Arial,sans-serif}}
main{{width:1800px;padding:36px 40px 40px}}header{{display:flex;align-items:baseline;justify-content:space-between;margin-bottom:32px}}
h1{{font-size:40px;line-height:1.3;font-weight:600;letter-spacing:-.8px;margin:0}}header p{{font-size:23px;color:#4e7462;margin:0}}
.steps{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:40px 32px;align-items:start}}section{{min-width:0}}
.hole .steps,.train .steps{{grid-template-columns:repeat(3,minmax(0,1fr))}}
h2{{font-size:34px;line-height:1.4;font-weight:600;margin:0 0 14px;display:flex;gap:14px;align-items:baseline}}h2 span{{font-size:24px;color:#4d8168;font-weight:400}}
.picture,.frame{{aspect-ratio:3/2;overflow:hidden}}
.picture>img,.frame img{{width:100%;height:100%;display:block;object-fit:cover;object-position:50% 50%}}
[data-step="model"] .picture>img{{object-position:50% 50%}}
.hole-worlds,.train-worlds{{display:grid;gap:20px 32px;align-items:start}}
.hole-worlds{{grid-template-columns:repeat(3,minmax(0,1fr))}}
.hole [data-step="styles"]{{grid-column:1/-1}}
[data-step="styles"] .picture{{aspect-ratio:auto;overflow:visible}}
.train-worlds{{grid-template-columns:repeat(2,minmax(0,1fr))}}
figure{{margin:0;min-width:0}}figcaption{{height:44px;font-size:24px;line-height:34px;padding-top:10px;text-align:center;color:#355241;white-space:nowrap}}
</style><main class="{case}"><header><h1>{words[case]}</h1><p>Grey2Art</p></header><div class="steps">{cards}</div></main>
<script>const fit=()=>{{document.querySelector('main').style.zoom=Math.min(1,innerWidth/1800)}};addEventListener('resize',fit);fit();addEventListener('load',()=>document.fonts.ready.then(()=>document.documentElement.dataset.captureHeight=Math.ceil(document.querySelector('main').getBoundingClientRect().height)));</script></html>'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser', required=True, type=Path)
    parser.add_argument('--train-root', required=True, type=Path)
    parser.add_argument('--case', choices=['both', 'hole', 'train'], default='both',
                        help='Render only the changed case while preserving verified outputs for the other')
    args = parser.parse_args()
    previous_path = MEDIA / 'grey2art-workflow-cases-sources.json'
    previous = json.loads(previous_path.read_text()) if previous_path.is_file() else {}
    selected_cases = ['hole', 'train'] if args.case == 'both' else [args.case]
    train_sources = prepare_train_inputs(args.train_root)
    diagram_sources = prepare_design_diagrams(args.train_root)
    asset_board = prepare_asset_board(args.train_root, args.browser)
    model_preview = MEDIA / 'workflow-train-clay-model-preview.png'
    model_receipt = MEDIA / 'workflow-train-clay-model-preview.json'
    if not model_preview.is_file() or not model_receipt.is_file():
        raise ValueError('Verified white-background selected G1 model preview and source receipt are required')
    model_sources = [{**identity(model_preview), 'source_receipt': 'docs/demo/workflow-train-clay-model-preview.json',
                      'kind': 'Actual selected G1 terrace-garden-house GLB rendered on pure white; not a concept or repaired AI image'},
                     {**identity(model_receipt), 'kind': 'Selected-model source, geometry and render identity'}]
    hole_sources = prepare_hole_inputs()
    suite = concept_suite(args.train_root, args.browser)
    sources = [identity(MEDIA / name) for name in [
        'hole-reference-greybox.png', 'ceramic-workflow-concept.png', 'ceramic-workflow-assembly.png',
        'train-greybox-native.jpg', 'train-pixel-native.jpg']]
    next(row for row in sources if row['file'] == 'train-greybox-native.jpg')['kind'] = 'Shared R2 native gameplay input view; not the historical clay greybox-comfort screenshot'
    generated = []
    for row in previous.get('outputs', []):
        if row['case'] not in selected_cases:
            assert identity(MEDIA / row['file'])['sha256'] == row['sha256']
            assert identity(MEDIA / row['html'])['sha256'] == row['html_sha256']
            row.setdefault('generator_sha256', previous.get('generator', {}).get('sha256'))
            generated.append(row)
    for case in selected_cases:
        for language in ['en', 'zh-CN']:
            target = MEDIA / f'grey2art-workflow-{case}.{language}.html'
            target.write_text(document(case, language), encoding='utf-8')
            height = capture(target, args.browser, WIDTH)
            generated.append({**identity(target.with_suffix('.png')), 'case': case, 'language': language,
                              'labels': [LABELS[language][key] for key in
                                         (['greybox','concept','assembly','styles'] if case == 'hole' else ['greybox','suite','recipe','assembly_plan','asset_board','model','assembly_sample','native','extension'])],
                              'html': target.name, 'html_sha256': identity(target)['sha256'],
                              'width': WIDTH, 'height': height,
                              'generator_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
    receipt = {'schema': 1, 'kind': 'bilingual-workflow-case-figures',
               'sources': sources + train_sources + hole_sources + model_sources, 'outputs': generated,
               'reconstructed_design_diagrams': diagram_sources, 'asset_reference_board': asset_board,
               'rendered_cases': selected_cases,
               'treatment': '1800px canvases with equal edge-aligned 3:2 image windows. Source captures and original model bytes remain unchanged; proportional CSS cover crops display edges without stretching or added filler. Hole uses three equal stage windows above six full-frame fixed-camera native styles in a 2x3 grid. Train uses nine equal windows in a 3x3 sequence: greybox, scene concepts, spatial recipe, reconstructed scene assembly design, a curated four-card asset-reference board, an actual 3D asset rendered on white, P8 assembly sample, P21 playable result and pixel style expansion. V1 spatial blockout remains bound as recipe-validation evidence rather than a separate visual stage. Spatial diagrams are editorial reconstructions from real source records, not original historical screenshots. The rejected station-main-building model and its reference are not used.',
               'train_concept_suite': suite,
               'hole_camera_receipt': {'path': 'docs/demo/hole-workflow-camera.json', **identity(MEDIA / 'hole-workflow-camera.json')},
               'train_case': {'style': 'clay', 'native_revision': 'P21', 'assembly_sample_revision': 'P8',
                              'concept_manifest': source_record(args.train_root, 'art/workflows/clay-pilot/production-v1/concepts.json'),
                              'scene_recipe': source_record(args.train_root, 'art/workflows/clay-pilot/production-v1/recipe.json'),
                              'scene_design': source_record(args.train_root, 'art/workflows/clay-pilot/scene-production-plan.json'),
                              'assembly_records': source_record(args.train_root, 'art/workflows/clay-pilot/production-v3/assembly.json'),
                              'spatial_validation': {'kind': 'actual V1 native blockout evidence, not an extra visual stage',
                                                     'frame': source_record(args.train_root, 'art/workflows/clay-pilot/production-v1/lookdev-base/station-02.png'),
                                                     'source_capture': source_record(args.train_root, 'art/workflows/clay-pilot/production-v1/lookdev-base/capture.json')},
                              'assembly_capture': source_record(args.train_root, 'art/workflows/clay-pilot/production-v3/review-08/capture.json'),
                              'native_capture': source_record(args.train_root, 'art/workflows/clay-pilot/production-v3/review-21/capture.json'),
                              'selected_model_preview': {'file': 'docs/demo/workflow-train-clay-model-preview.png', 'source_receipt': 'docs/demo/workflow-train-clay-model-preview.json'},
                              'selection_correction': 'Earlier task 3845486 station-main-building candidate was rejected and is excluded. The model stage uses the verified selected terrace-garden-house G1 asset; see its dedicated preview receipt.'},
               'scope': 'Historical case stages: concepts/references and native frames retain distinct identities. These figures illustrate the process, not current-release production qualification or human acceptance.',
               'font': 'Existing OFL Noto CJK subset with system sans-serif fallback for additional Chinese characters.'}
    receipt['generator'] = {'path': 'scripts/render_workflow_cases.py',
                            'sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (MEDIA / 'grey2art-workflow-cases-sources.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'outputs': [row['file'] for row in generated], 'referenced_train_source_bytes': sum(row['bytes'] for row in train_sources),
                      'rendered_bytes': sum(row['bytes'] for row in generated)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
