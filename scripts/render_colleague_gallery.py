#!/usr/bin/env python3
"""Record selected Gallery PCKs with existing Godot, then make compact README GIFs."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess

ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "scripts/capture_colleague_gallery.gd"
REVISION = "3ed4658b1a8e61df961c9d2a36ca3662827e33af"
REPOSITORY = "https://github.com/shencaiyiyi11-byte/playable-game-gallery"
GAMES = {
    "halloween-racing": {"title": "万圣夜竞速", "start": 192, "events": [
        {"frame": 32, "type": "key", "key": "Enter", "pressed": True},
        {"frame": 34, "type": "key", "key": "Enter", "pressed": False},
        {"frame": 64, "type": "key", "key": "W", "pressed": True},
        {"frame": 385, "type": "key", "key": "W", "pressed": False},
    ], "input": "Enter starts; W accelerates along the first road. No camera, speed, route or scene edits."},
    "no-signal-halloween": {"title": "失联航次 · 手绘哥特", "start": 192, "events": [
        {"frame": 32, "type": "key", "key": "Enter", "pressed": True},
        {"frame": 34, "type": "key", "key": "Enter", "pressed": False},
        {"frame": 96, "type": "key", "key": "W", "pressed": True},
        {"frame": 166, "type": "look", "x": -482.0, "y": 0},
        {"frame": 385, "type": "key", "key": "W", "pressed": False},
    ], "input": "Enter starts; W exits the starting cabin, mouse motion turns toward the decorated central corridor, W continues walking. No teleport or camera-state edits."},
}


def identity(path: Path) -> dict:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1048576), b""): digest.update(block)
    return {"bytes": path.stat().st_size, "sha256": digest.hexdigest()}


def run(command: list[str], **kwargs) -> str:
    return subprocess.run(command, check=True, text=True, capture_output=True, **kwargs).stdout


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--godot", required=True)
    parser.add_argument("--game", choices=GAMES, action="append")
    parser.add_argument("--ffmpeg", default=shutil.which("ffmpeg") or "ffmpeg")
    parser.add_argument("--ffprobe", default=shutil.which("ffprobe") or "ffprobe")
    args = parser.parse_args()
    source_root = args.source_root.resolve()
    revision = run(["/usr/bin/git", "rev-parse", "HEAD"], cwd=source_root).strip()
    if revision != REVISION: raise SystemExit("Use the pinned Gallery revision")
    manifest = json.loads((source_root / "release-manifest.json").read_text())
    entries = {entry["path"]: entry for entry in manifest}
    media = ROOT / "docs/demo"
    receipt_path = media / "colleague-gallery-sources.json"
    receipt = json.loads(receipt_path.read_text()) if receipt_path.exists() else {"schema": 1, "files": []}
    for game in args.game or GAMES:
        options = GAMES[game]
        entry = entries[f"{game}/game.pck"]
        pck = source_root / ".local-capture" / (entry["sha256"] + ".pck")
        if not pck.exists() or identity(pck) != {"bytes": entry["size"], "sha256": entry["sha256"]}:
            raise SystemExit(f"Assemble and verify the selected manifest PCK first: {game}")
        target = media / f"colleague-{game}.gif"
        if target.exists(): raise SystemExit(f"Preserve existing reviewed output: {target.name}")
        folder = source_root / ".local-capture" / "recordings" / game
        folder.mkdir(parents=True, exist_ok=False)
        frames = folder / "frames"
        plan = {"output": str(frames), "capture_start": options["start"],
                "capture_frames": 192, "events": options["events"]}
        plan_path = folder / "plan.json"
        plan_path.write_text(json.dumps(plan, indent=2) + "\n")
        command = [args.godot, "--main-pack", str(pck), "--script", str(DRIVER),
                   "--rendering-method", "gl_compatibility", "--resolution", "960x540",
                   "--fixed-fps", "32", "--log-file", str(folder / "godot.log"), "--", "--plan=" + str(plan_path)]
        with (folder / "native.stdout.log").open("w") as log:
            subprocess.run(command, check=True, stdout=log, stderr=subprocess.STDOUT, timeout=120)
        native = json.loads((frames / "native.json").read_text())
        native.pop("user_data_dir", None)
        images = sorted(frames.glob("*.png"))
        if len(images) != 192 or native["captured_frames"] != 192: raise SystemExit("Native frame count mismatch")
        dimensions = set()
        for image in images:
            with image.open("rb") as stream: dimensions.add(struct.unpack(">II", stream.read(24)[16:24]))
        if dimensions != {(960, 540)}: raise SystemExit(f"Native viewport changed during capture: {dimensions}")
        native["captured_image_size"] = [960, 540]
        frame_ids = [{"file": p.name, **identity(p)} for p in images]
        run([args.ffmpeg, "-n", "-hide_banner", "-loglevel", "error", "-framerate", "32",
             "-i", str(frames / "%04d.png"), "-t", "6", "-filter_complex",
             "fps=8,scale=480:-1:flags=lanczos,split[a][b];"
             "[a]palettegen=max_colors=128:stats_mode=diff[p];"
             "[b][p]paletteuse=dither=none:diff_mode=rectangle",
             "-an", "-map_metadata", "-1", "-loop", "0", str(target)])
        probe = json.loads(run([args.ffprobe, "-v", "error", "-count_frames", "-show_entries",
                              "stream=width,height,nb_read_frames,duration:format=duration,size", "-of", "json", str(target)]))
        run([args.ffmpeg, "-v", "error", "-i", str(target), "-f", "null", "-"])
        log = run([args.ffmpeg, "-v", "error", "-i", str(target), "-f", "framemd5", "-"])
        decoded = [line.rsplit(",", 1)[1].strip() for line in log.splitlines() if not line.startswith("#")]
        if len(decoded) != 48 or len(set(decoded)) != 48: raise SystemExit("GIF frame continuity check failed")
        item = {"game": game, "title": options["title"], "output": str(target.relative_to(ROOT)),
                **identity(target), "repository": REPOSITORY, "revision": REVISION,
                "play": f"https://shencaiyiyi11-byte.github.io/playable-game-gallery/play.html?game={game}",
                "source": entry, "native": native, "driver": identity(DRIVER), "renderer": identity(Path(__file__)),
                "input": options["input"], "events": options["events"], "native_start_frame": options["start"],
                "native_fixed_fps": 32, "native_frame_hashes": frame_ids, "gif": probe,
                "unique_decoded_frames": 48, "full_decode_passed": True,
                "treatment": "Actual native PCK scene and input replay. Full frames downscaled preserving aspect ratio; 128-color silent GIF. No repaint, interpolation, teleport, scene, lighting or material changes.",
                "boundary": "Offline native rendering from the published Web PCK using the existing Godot engine. Encoded frame rates are not measured runtime FPS or human gameplay acceptance."}
        receipt["files"] = [old for old in receipt["files"] if old["game"] != game] + [item]
        receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps({"game": game, **identity(target)}, ensure_ascii=False), flush=True)


if __name__ == "__main__": main()
