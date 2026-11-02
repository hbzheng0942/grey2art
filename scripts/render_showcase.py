#!/usr/bin/env python3
"""Build the README's reproducible HTML composition from retained game captures.

This is a documentation renderer. It does not run games or alter source images.
Use --browser /path/to/chrome to also export the PNGs with a temporary profile.
"""
from pathlib import Path
import argparse
import hashlib
import html
import json
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "docs" / "demo"
WIDTH, HEIGHT = 1800, 1226
FRAME_ASPECTS = {"hole": "3 / 2", "train-parkour": "16 / 9", "wander-garden": "8 / 5"}
FONT = "fonts/NotoSansCJKsc-2.004-showcase-subset.woff2"
FONT_FAMILY = "Grey2Art Sans"
CATALOG = ROOT / "docs" / "showcase" / "catalog.json"
GENRES = {
    "hole": ("Top-down collection", "俯视吞噬玩法"),
    "train-parkour": ("Continuous 3D action", "连续三维动作"),
    "wander-garden": ("Third-person farming", "第三人称种植"),
}


def read_rows(language="en"):
    catalog = json.loads(CATALOG.read_text())
    rows = []
    for case in catalog["cases"]:
        assert len(case["art_versions"]) == 3, "Overview needs three art views per row"
        cells = []
        for entry in [case["input"], *case["art_versions"]]:
            image = entry.get("image")
            if image:
                source = ROOT / image
                data = source.read_bytes()
                assert hashlib.sha256(data).hexdigest() == entry["sha256"], image
                assert len(data) == entry["bytes"], image
                filename = source.relative_to(MEDIA).as_posix()
            else:
                assert entry["kind"] == "placeholder", "Missing image must be explicit"
                filename = None
            cells.append((entry["label"]["en"], entry["label"]["zh-CN"], filename,
                          entry.get("overview_treatment", "placeholder" if image is None else "")))
        en, zh = GENRES[case["id"]]
        rows.append((case["id"], case["name"][language], en, zh, cells))
    return rows


CSS = """
@font-face{font-family:'Grey2Art Sans';src:url('fonts/NotoSansCJKsc-2.004-showcase-subset.woff2') format('woff2');font-weight:400;font-display:block}
*{box-sizing:border-box}html,body{margin:0;width:100%;background:#0d0d11;color:#f5f2eb;overflow-x:hidden}
body{font-family:'Grey2Art Sans','Noto Sans SC',sans-serif;-webkit-font-smoothing:antialiased}main{width:1800px;height:1226px;padding:28px 40px 20px}
.masthead{height:110px;display:flex;align-items:flex-start;gap:34px;border-bottom:1px solid #32313a;margin-bottom:16px}
.identity{white-space:nowrap;display:flex;align-items:center;gap:18px;padding-top:7px}
.mark{display:grid;grid-template-columns:repeat(3,11px);grid-template-rows:repeat(3,11px);gap:3px;transform:translateY(1px)}
.mark i{display:block;background:#575661}.mark i:nth-child(3){background:#fc70bb}.mark i:nth-child(5){background:#aff38a}.mark i:nth-child(6){background:#7bc8ff}.mark i:nth-child(8){background:#ffcc66}.mark i:nth-child(9){background:#e8e4dc}
.brand{font-size:64px;font-weight:600;line-height:1;letter-spacing:-3px;margin:0}.brand span{color:#fc70bb}
.pitch{padding-top:1px;margin-left:12px}.pitch h1{font-weight:600;font-size:30px;line-height:1.24;margin:0 0 9px;letter-spacing:-.7px}
.pitch p{font-size:15px;line-height:1.4;color:#a5a0b0;margin:0}.meta{margin-left:auto;font-size:12px;line-height:1.9;color:#a5a0b0;text-align:right;padding-top:8px}.meta b{color:#fc70bb;font-weight:600}
.columns{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;height:24px;margin-bottom:10px;font-size:13px;letter-spacing:1px;color:#c8c1d2}.columns span:first-child{color:#b8b4c1}.columns span:not(:first-child){color:#fc70bb}
.row{margin-bottom:14px}.rowhead{display:flex;align-items:center;height:28px;margin-bottom:6px;gap:13px}.rowhead b{font-size:12px;font-weight:400;color:#fc70bb}.rowhead h2{font-weight:600;font-size:21px;margin:0}.rowhead p{font-size:13px;color:#9691a2;margin:0 0 0 auto}
.grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px}.tile{margin:0;background:#19181f;min-width:0}.viewport{aspect-ratio:var(--frame-aspect);overflow:hidden;position:relative}.viewport img{display:block;height:100%;width:100%;object-fit:cover}

figcaption{height:32px;padding:7px 11px;font-size:14px;color:#e6e1ec;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.placeholder .viewport{background:repeating-conic-gradient(#15141c 0% 25%,#1c1a23 0% 50%) 50%/40px 40px;display:flex;flex-direction:column;align-items:center;justify-content:center;border:1px dashed #777080}
.pendingmark{font-size:58px;color:#81778d;line-height:1;margin-bottom:20px}.pendingtext{font-size:18px;color:#e0c9e9;text-align:center;line-height:1.6}.placeholder figcaption{color:#c8a2d5}
footer{display:flex;justify-content:space-between;gap:20px;border-top:1px solid #32313a;padding-top:14px;margin-top:14px;color:#aaa3b6;font-size:12px;line-height:1.5}
"""

# Scale the complete composition in HTML previews; PNG export uses its native size.
PREVIEW_SCRIPT = f"""<script>
function fitPreview() {{
  const scale = Math.min(1, innerWidth / {WIDTH});
  document.querySelector('main').style.zoom = scale;
  document.body.style.height = `${{{HEIGHT} * scale}}px`;
  document.documentElement.dataset.previewOverflow = String(document.documentElement.scrollWidth > innerWidth);
}}
addEventListener('resize', fitPreview); fitPreview();
document.fonts.ready.then(() => {{
  document.documentElement.dataset.fontStatus =
    [...document.fonts].some(font => font.family === '{FONT_FAMILY}' && font.status === 'loaded')
      ? 'loaded' : 'error';
}});
</script>"""


def build(language):
    zh = language == "zh-CN"
    sections = []
    for index, (case_id, name, genre_en, genre_zh, cells) in enumerate(read_rows(language), 1):
        cards = []
        for en, cn, filename, treatment in cells:
            label = cn if zh else en
            if filename:
                assert (MEDIA / filename).is_file(), filename
                content = f'<img src="{filename}" alt="{html.escape(name + ": " + label)}">'
            else:
                content = '<div class="pendingmark">[ ... ]</div><div class="pendingtext">' + ("灰盒截图待补<br>占位示意" if zh else "GREYBOX CAPTURE<br>TO BE ADDED") + '</div>'
            cards.append(f'<figure class="tile {treatment}"><div class="viewport">{content}</div><figcaption>{label}</figcaption></figure>')
        sections.append(f'<section class="row" id="{case_id}" style="--frame-aspect:{FRAME_ASPECTS[case_id]}"><div class="rowhead"><b>0{index}</b><h2>{name}</h2><p>{genre_zh if zh else genre_en}</p></div><div class="grid">{"".join(cards)}</div></section>')
    columns = ["玩法灰盒 / 输入", "美术世界 01", "美术世界 02", "美术世界 03"] if zh else ["GREYBOX / INPUT", "ART WORLD 01", "ART WORLD 02", "ART WORLD 03"]
    headline = "同一玩法灰盒，<br>多种美术世界。" if zh else "From one greybox<br>to multistyle art."
    explanation = "批量制作可编辑、可玩的多风格原型。" if zh else "Batch-create editable, playable art prototypes."
    title = "Grey2Art · 从同一灰盒到多风格美术" if zh else "Grey2Art · From One Greybox to Multistyle Art"
    return f'''<!doctype html><html lang="{language}"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{title}</title><style>{CSS}</style><main><header class="masthead"><div class="identity"><div class="mark" aria-hidden="true">{"<i></i>" * 9}</div><p class="brand">Grey2Art<span>.</span></p></div><div class="pitch"><h1>{headline}</h1><p>{explanation}</p></div></header><div class="columns">{"".join(f"<span>{c}</span>" for c in columns)}</div>{"".join(sections)}</main>{PREVIEW_SCRIPT}</html>'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", help="Chrome/Chromium executable; optional PNG export")
    args = parser.parse_args()
    outputs = []
    for language, suffix in [("en", ""), ("zh-CN", ".zh-CN")]:
        target = MEDIA / f"grey2art-overview{suffix}.html"
        target.write_text(build(language), encoding="utf-8")
        if args.browser:
            with tempfile.TemporaryDirectory(prefix="grey2art-doc-render-") as profile:
                png = target.with_suffix(".png")
                result = subprocess.run([args.browser, "--headless", "--disable-gpu", "--hide-scrollbars", "--no-first-run", "--no-default-browser-check", f"--user-data-dir={profile}", f"--window-size={WIDTH},{HEIGHT}", "--force-device-scale-factor=1", "--virtual-time-budget=2500", f"--screenshot={png}", target.as_uri()], capture_output=True, text=True, timeout=40)
                if result.returncode or not png.is_file():
                    raise RuntimeError(result.stderr[-1500:])
        outputs.append(target.relative_to(ROOT).as_posix())
    sources = []
    for case_id, _, _, _, cells in read_rows():
        for _, _, filename, treatment in cells:
            if filename:
                data = (MEDIA / filename).read_bytes()
                sources.append({"case": case_id, "file": filename, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data), "display_treatment": treatment or "fit-to-tile"})
    placeholders = [{"case": row[0], "label": cell[0]} for row in read_rows() for cell in row[4] if cell[2] is None]
    font = MEDIA / FONT
    receipt = {"brand": "Grey2Art", "layout": "three game rows by four columns", "canvas": {"width": WIDTH, "height": HEIGHT, "html_preview": "Proportional fit to viewport width; no horizontal scrolling"}, "frame_aspects": FRAME_ASPECTS, "font": {"family": FONT_FAMILY, "source_family": "Noto Sans CJK SC 2.004", "file": FONT, "sha256": hashlib.sha256(font.read_bytes()).hexdigest(), "bytes": font.stat().st_size, "weight": "Static regular 400; browser-synthesized 600 for headings", "license": "OFL-1.1"}, "image_operation": "Real frames fill equal edge-aligned viewports within each game row using proportional cover. Native per-case ratios limit edge crop; no stretching or filler bars. Source bytes unchanged", "catalog_sha256": hashlib.sha256(CATALOG.read_bytes()).hexdigest(), "placeholders": placeholders, "sources": sources}
    receipt["renderer"] = {"file": "scripts/render_showcase.py", "bytes": Path(__file__).stat().st_size, "sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    receipt["outputs"] = []
    for relative in outputs:
        for target in [ROOT / relative, (ROOT / relative).with_suffix(".png")]:
            if target.is_file() and (target.suffix != ".png" or args.browser):
                data = target.read_bytes()
                receipt["outputs"].append({"file": target.relative_to(ROOT).as_posix(), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    (MEDIA / "grey2art-overview-sources.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"html": outputs, "native_source_images": len(sources), "png_exported": bool(args.browser)}))


if __name__ == "__main__":
    main()
