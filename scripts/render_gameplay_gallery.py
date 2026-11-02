#!/usr/bin/env python3
"""Render the bilingual nine-case gallery from verified native game frames.

This only composes retained media. It does not run games or alter source images.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
MEDIA = ROOT / "docs/demo"
CATALOG = ROOT / "docs/showcase/gallery.json"
WIDTH, HEIGHT = 1800, 1342
FONT = "fonts/NotoSansCJKsc-2.004-showcase-subset.woff2"


def identity(path: Path) -> dict:
    data = path.read_bytes()
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def read_cases() -> list[dict]:
    catalog = json.loads(CATALOG.read_text())
    cases = catalog["cases"]
    assert len(cases) == 9, "The gallery requires exactly nine native frames"
    assert len({(case["game"], case["style"]) for case in cases}) == 9
    assert len({case["game"] for case in cases}) == catalog["unique_games"]
    assert len({case["image"] for case in cases}) == 9
    for case in cases:
        source = ROOT / case["image"]
        assert source.is_file(), f"Missing approved native frame: {case['image']}"
        assert identity(source) == {key: case[key] for key in ("bytes", "sha256")}, case["id"]
        assert source.resolve().is_relative_to(MEDIA.resolve()), "Only curated demo media is embedded"
        assert case["source"]["kind"] != "concept"
    return cases


CSS = """
@font-face{font-family:'Grey2Art Sans';src:url('fonts/NotoSansCJKsc-2.004-showcase-subset.woff2') format('woff2');font-weight:400;font-display:block}
*{box-sizing:border-box}html,body{margin:0;background:#0d0d11;color:#f5f2eb;width:100%;overflow-x:hidden}
body{font-family:'Grey2Art Sans','Noto Sans SC','PingFang SC',sans-serif;-webkit-font-smoothing:antialiased}
main{width:1800px;height:1342px;padding:24px;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;align-content:start}
figure{margin:0;min-width:0;background:#19181f}a{color:inherit;text-decoration:none}
.viewport{display:block;width:100%;aspect-ratio:8 / 5;overflow:hidden}
img{display:block;width:100%;height:100%;object-fit:cover;object-position:center}
figcaption{height:62px;padding:15px 18px;font-size:27px;line-height:32px;letter-spacing:-.25px;white-space:nowrap}
a:focus-visible{outline:3px solid #aff38a;outline-offset:-3px}figure:hover figcaption{color:#aff38a}
"""


def build(language: str, cases: list[dict]) -> str:
    tiles = []
    for case in cases:
        source = case["source"]
        # A linked native recording is preferred; otherwise open the source project.
        link = source.get("clip")
        if link:
            link = "../" + Path(link).relative_to("docs").as_posix()
        else:
            link = source.get("play")
        if not link:
            revision = source.get("revision", "main")
            link = source["repository"] + "/blob/" + revision + "/" + source["path"]
        image = (ROOT / case["image"]).relative_to(MEDIA).as_posix()
        title = case["title"][language]
        tiles.append(f'<figure data-case="{case["id"]}"><a class="viewport" href="{html.escape(link, quote=True)}"><img src="{image}" alt="{html.escape(title, quote=True)}" width="{case["width"]}" height="{case["height"]}"></a><figcaption>{html.escape(title)}</figcaption></figure>')
    title = "Grey2Art · 游戏与美术世界" if language == "zh-CN" else "Grey2Art · Games and Art Worlds"
    return f'''<!doctype html>
<html lang="{language}"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title><style>{CSS}</style>
<main aria-label="{title}">{"".join(tiles)}</main>
<script>
function fitPreview(){{const scale=Math.min(1,innerWidth/{WIDTH});document.querySelector('main').style.zoom=scale;document.body.style.height=`${{{HEIGHT}*scale}}px`;}}
addEventListener('resize',fitPreview);fitPreview();
</script></html>
'''


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser", help="Chrome/Chromium executable; exports PNGs with disposable profiles")
    args = parser.parse_args()
    cases = read_cases()
    outputs = []
    for language, suffix in [("en", ""), ("zh-CN", ".zh-CN")]:
        path = MEDIA / f"grey2art-gallery{suffix}.html"
        path.write_text(build(language, cases))
        outputs.append({"file": path.relative_to(ROOT).as_posix(), **identity(path)})
        if args.browser:
            with tempfile.TemporaryDirectory(prefix="grey2art-gallery-") as profile:
                png = path.with_suffix(".png")
                result = subprocess.run([args.browser, "--headless", "--disable-gpu", "--hide-scrollbars", "--no-first-run", "--no-default-browser-check", f"--user-data-dir={profile}", f"--window-size={WIDTH},{HEIGHT}", "--force-device-scale-factor=1", "--virtual-time-budget=2000", f"--screenshot={png}", path.as_uri()], capture_output=True, text=True, timeout=35)
                if result.returncode or not png.is_file():
                    raise RuntimeError(result.stderr[-1500:])
                outputs.append({"file": png.relative_to(ROOT).as_posix(), **identity(png)})
    receipt = {"schema": 1, "catalog": {"file": CATALOG.relative_to(ROOT).as_posix(), **identity(CATALOG)},
               "renderer": {"file": Path(__file__).relative_to(ROOT).as_posix(), **identity(Path(__file__))},
               "canvas": {"width": WIDTH, "height": HEIGHT}, "outputs": outputs,
               "font": {"file": FONT, **identity(MEDIA / FONT),
                        "fallback_families": ["Noto Sans SC", "PingFang SC", "sans-serif"],
                        "coverage": "Shared existing subset; additional Chinese title glyphs use browser CJK fallback. The exported PNG fixes the rendered glyph appearance."},
               "source_count": len(cases), "unique_games": len({case["game"] for case in cases}),
               "source_operation": "Verified source bytes unchanged. CSS proportional cover in 8:5 tiles; edge crop depends on native aspect. No added filler bars or stretching.",
               "scope": "Native art showcase only; no claim of current release end-to-end qualification or measured runtime performance."}
    (MEDIA / "grey2art-gallery-sources.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"native_frames": len(cases), "unique_games": receipt["unique_games"], "outputs": outputs}))


if __name__ == "__main__":
    main()
