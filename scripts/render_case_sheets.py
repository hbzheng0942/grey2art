#!/usr/bin/env python3
"""Render compact 2x2 README case sheets from the showcase catalog.

Source captures remain unchanged. Use --browser /path/to/chrome to export PNGs.
"""
import argparse
import hashlib
import html
import json
from pathlib import Path
from fractions import Fraction
import math
import re
import subprocess
import tempfile

from render_showcase import CATALOG, FONT, FONT_FAMILY, FRAME_ASPECTS, MEDIA, ROOT

WIDTH = 1000


def canvas_height(case):
    ratio = float(Fraction(FRAME_ASPECTS[case["id"]].replace(" ", "")))
    return math.ceil(40 + 46 + 10 + 2 * (473 / ratio + 32) + 14)


def file_record(path):
    data = path.read_bytes()
    return {"file": path.relative_to(ROOT).as_posix(), "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest()}


def case_cards(case, language="en"):
    entries = [case["input"], *case["art_versions"]]
    assert len(entries) == 4, "Case sheets require one input and three art views"
    cards, sources = [], []
    display = case.get("overview_display", {})
    for index, entry in enumerate(entries):
        path = ROOT / entry["image"]
        record = file_record(path)
        assert record["sha256"] == entry["sha256"], path
        assert record["bytes"] == entry["bytes"], path
        treatment = entry.get("overview_treatment", "fit-to-tile")
        transform = ""
        if treatment == "matched-detail":
            scale = float(display["scale"])
            origin_x, origin_y = map(float, display["transform_origin_percent"])
            transform = f"transform:scale({scale:g});transform-origin:{origin_x:g}% {origin_y:g}%"
        role = "input" if index == 0 else "art_style"
        display_label = entry["label"][language]
        if index == 0:
            display_label = re.sub(r"\s+v\d+(?:\.\d+)*(?:[a-zA-Z0-9.-]*)?$", "", display_label)
        label = html.escape(display_label)
        filename = path.relative_to(MEDIA).as_posix()
        cards.append(f'<figure class="{html.escape(treatment)}"><div class="viewport"><img src="{filename}" '
                     f'alt="{html.escape(case["name"][language])}: {label}" '
                     f'style="{transform}"></div><figcaption>'
                     f'<b>{label}</b></figcaption></figure>')
        record.update({"label": entry["label"][language], "display_label": display_label, "role": role,
                       "display_treatment": treatment})
        if transform:
            record["display_transform"] = {"scale": scale,
                                           "transform_origin_percent": [origin_x, origin_y]}
        if entry.get("camera_receipt"):
            record["camera_receipt"] = file_record(ROOT / entry["camera_receipt"])
        sources.append(record)
    return cards, sources


def build(case, cards, language="en"):
    title = html.escape(case["name"][language])
    height = canvas_height(case)
    page_title = f"{title} / Grey2Art 案例对照" if language == "zh-CN" else f"{title} / Grey2Art case comparison"
    return f'''<!doctype html><html lang="{language}"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{page_title}</title><style>
@font-face{{font-family:'{FONT_FAMILY}';src:url('{FONT}') format('woff2');font-weight:400;font-display:block}}
*{{box-sizing:border-box}}html,body{{margin:0;width:100%;background:#0d0d11;color:#f5f2eb;overflow-x:hidden}}
body{{font-family:'{FONT_FAMILY}','Noto Sans SC','PingFang SC',sans-serif;-webkit-font-smoothing:antialiased}}
main{{width:{WIDTH}px;height:{height}px;padding:20px}}
header{{height:46px;margin-bottom:10px;display:flex;align-items:baseline;justify-content:space-between}}
h1{{font-size:28px;font-weight:600;letter-spacing:-.6px;margin:0}}
.grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}}
figure{{margin:0;background:#19181f;min-width:0}}
.viewport{{aspect-ratio:{FRAME_ASPECTS[case['id']]};overflow:hidden}}
img{{display:block;height:100%;width:100%;object-fit:cover}}
figcaption{{height:32px;display:flex;align-items:center;gap:12px;padding:0 11px;white-space:nowrap}}
figcaption b{{font-size:15px;font-weight:400}}
</style><main><header><h1>{title}</h1></header>
<div class="grid">{"".join(cards)}</div></main>
<script>
function fitPreview() {{
  const scale = Math.min(1, innerWidth / {WIDTH});
  document.querySelector('main').style.zoom = scale;
  document.body.style.height = `${{{height} * scale}}px`;
  document.documentElement.dataset.previewOverflow = String(document.documentElement.scrollWidth > innerWidth);
}}
addEventListener('resize', fitPreview); fitPreview();
document.fonts.ready.then(() => {{
  document.documentElement.dataset.fontStatus = [...document.fonts].some(font => font.family === '{FONT_FAMILY}' && font.status === 'loaded') ? 'loaded' : 'error';
  document.documentElement.dataset.labelOverflow = String([...document.querySelectorAll('figcaption')].some(caption => caption.scrollWidth > caption.clientWidth));
}});
</script></html>'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", help="Chrome/Chromium executable; optional PNG export")
    parser.add_argument("--language", choices=("en", "zh-CN", "both"), default="both")
    args = parser.parse_args()
    catalog_record = file_record(CATALOG)
    catalog = json.loads(CATALOG.read_text())
    languages = ("en", "zh-CN") if args.language == "both" else (args.language,)
    cases = []
    for case in catalog["cases"]:
        variants, outputs, sources = {}, [], []
        for language in languages:
            cards, localized_sources = case_cards(case, language)
            sources = sources or localized_sources
            suffix = "" if language == "en" else ".zh-CN"
            target = MEDIA / f'grey2art-case-{case["id"]}{suffix}.html'
            target.write_text(build(case, cards, language), encoding="utf-8")
            localized_outputs = [file_record(target)]
            if args.browser:
                with tempfile.TemporaryDirectory(prefix="grey2art-case-render-") as profile:
                    png = target.with_suffix(".png")
                    result = subprocess.run([
                        args.browser, "--headless", "--disable-gpu", "--hide-scrollbars",
                        "--no-first-run", "--no-default-browser-check", f"--user-data-dir={profile}",
                        f"--window-size={WIDTH},{canvas_height(case)}", "--force-device-scale-factor=1",
                        "--virtual-time-budget=2500", f"--screenshot={png}", target.as_uri(),
                    ], capture_output=True, text=True, timeout=40)
                    if result.returncode or not png.is_file():
                        raise RuntimeError(result.stderr[-1500:])
                    localized_outputs.append(file_record(png))
            outputs.extend(localized_outputs)
            variants[language] = {"name": case["name"][language], "outputs": localized_outputs,
                                  "labels": [source["display_label"] for source in localized_sources]}
        # A concurrent catalog/capture edit must not leave a falsely bound receipt.
        for source in sources:
            current = file_record(ROOT / source["file"])
            assert current["sha256"] == source["sha256"], source["file"]
        assert file_record(CATALOG) == catalog_record, "Catalog changed during rendering; rerun"
        cases.append({"id": case["id"], "name": case["name"]["en"],
                      "canvas": {"width": WIDTH, "height": canvas_height(case), "frame_aspect": FRAME_ASPECTS[case['id']]},
                      "source_revision": case["source_revision"], "outputs": outputs,
                      "sources": sources, "languages": variants})
    receipt = {
        "brand": "Grey2Art", "layout": "one case per 2x2 comparison sheet",
        "canvas": {"width": WIDTH, "height": "per-case native aspect ratio",
                   "html_preview": "Proportional fit to viewport width; no horizontal scrolling"},
        "catalog": catalog_record, "renderer": file_record(Path(__file__).resolve()),
        "font": {**file_record(MEDIA / FONT), "family": FONT_FAMILY,
                 "weight": "Static regular 400; browser-synthesized 600 for headings",
                 "license": "OFL-1.1"},
        "image_operation": "Real frames fill equal edge-aligned viewports within each case using proportional cover. Native per-case ratios limit edge crop; no stretching or filler bars. Source capture bytes unchanged",
        "png_exported": bool(args.browser), "languages": list(languages), "cases": cases,
    }
    (MEDIA / "grey2art-case-sources.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"cases": len(cases), "native_source_images": sum(len(c["sources"]) for c in cases),
                      "png_exported": bool(args.browser)}))


if __name__ == "__main__":
    main()
