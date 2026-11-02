#!/usr/bin/env python3
"""check / run / replay / play for explicit-input, two-style Hole look development."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import importlib.util
from lookdev_core import *


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["check", "run", "replay", "play"])
    parser.add_argument("--case", type=Path)
    parser.add_argument("--source-root")
    parser.add_argument("--asset-root")
    parser.add_argument("--godot")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--overlay", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--style", choices=["ceramic", "orbital"])
    parser.add_argument("--conditions", nargs="+", choices=list(CONDITIONS), default=list(CONDITIONS))
    parser.add_argument("--condition", choices=list(CONDITIONS), default="combined")
    parser.add_argument("--mode", choices=["look", "full"], default="look")
    args = parser.parse_args()
    started = time.time()
    old = None
    if args.action in ["replay", "play"] and args.manifest:
        old = read(args.manifest)
        if old.get("kind") == "lookdev-selection":
            p = resolve(args.manifest.resolve().parent, old["experiment"]["path"])
            checked(p, old["experiment"]["sha256"])
            args.condition = old["condition"]
            old = read(p)
        if args.case is None:
            args.case = Path(old["casePath"])
    require(args.case is not None, "Explicit --case is required; local case data is not bundled")
    case_path = args.case
    case = load_case(case_path, args.source_root, args.asset_root)
    require(importlib.util.find_spec("PIL") is not None, "Pillow missing; install requirements-lookdev.txt")
    if old:
        require(old["signature"] == case["signature"], "Stale evidence: source, configuration or adapter changed")
    candidates = [args.godot, shutil.which("godot"), str(Path.home() / "Downloads/Godot.app/Contents/MacOS/Godot"), "/Applications/Godot.app/Contents/MacOS/Godot"]
    godot = next((Path(p).resolve() for p in candidates if p and Path(p).is_file()), None)
    require(godot is not None, "Godot missing; pass --godot")
    version = subprocess.check_output([str(godot), "--version"], text=True).strip()
    require(version.startswith("4."), "This adapter requires Godot 4")
    if args.action == "check":
        print(json.dumps({"status": "ready", "signature": case["signature"], "godot": str(godot), "version": version,
                          "styles": {s: len(v) for s, v in case["skin"].items()}, "uniqueModels": len(case["materials"]),
                          "generationCalls": 0, "seconds": time.time() - started}))
        return
    output = (args.output or ROOT / "runs/hole-lookdev").resolve()
    overlay = (args.overlay or ROOT / ".local/hole-lookdev").resolve()
    overlay = assemble(case, overlay, godot)
    styles = [args.style] if args.style else list(case["skin"])
    if args.action == "play":
        require(args.style is not None, "play requires --style")
        require(old is not None, "play requires a verified --manifest")
        key = args.style + "/" + args.condition
        require(key in old["results"], "Selected style/condition has no evidence")
        verify_record(old["results"][key])
        controls = old["results"][key]["controls"]
        p = overlay / "data/play-controls.json"
        write(p, controls)
        env = dict(os.environ, HOLE_ART_STYLE=args.style, HOLE_ART_CONTROLS=str(p))
        raise SystemExit(subprocess.call([str(godot), "--path", str(overlay)], env=env))
    output.mkdir(parents=True, exist_ok=True)
    manifest = output / "experiment.json"
    experiment = read(manifest) if manifest.exists() else {"schema": 1, "casePath": str(case["path"]), "signature": case["signature"],
        "runtimeFiles": case["runtime"], "godotVersion": version, "results": {}, "startedAt": started,
        "artAcceptance": "pending-human-review", "humanInterventions": [], "generation": {"imageCalls": 0, "modelCalls": 0, "quotedCredits": 0, "settledCredits": None, "imageMoney": None}}
    require(experiment["signature"] == case["signature"], "Output belongs to another input version; use a new output directory")
    conditions = [args.condition] if args.action == "replay" else args.conditions
    for style in styles:
        for condition in conditions:
            key = style + "/" + condition
            if key in experiment["results"]:
                verify_record(experiment["results"][key])
                require(experiment["results"][key]["mode"] == args.mode, "Output mode differs; use a new directory")
                require(experiment["results"][key].get("replayStatus") != "failed", "Previous replay failed; inspect its persisted deltas and use a new output after fixing the cause")
                continue
            if old:
                require(key in old["results"], "Missing original replay evidence")
                verify_record(old["results"][key])
                controls = old["results"][key]["controls"]
            else:
                controls = controls_for(case["docs"]["adjustments"], style, condition)
            record = native_capture(case, overlay, controls, style, output / style / condition, godot, args.mode)
            if old:
                record["replayDeltas"] = {name: image_delta(old["results"][key]["captures"][name]["path"], value["path"])
                    for name, value in record["captures"].items() if name in old["results"][key]["captures"]}
                tolerance = old.get("repeatTolerance", {"meanAbsolute255": 0, "maxChannel255": 0})
                record["replayStatus"] = "pass" if all(v["meanAbsolute255"] <= tolerance["meanAbsolute255"] and v["maxChannel255"] <= tolerance["maxChannel255"]
                            for v in record["replayDeltas"].values()) else "failed"
            experiment["results"][key] = record
            experiment["finishedAt"] = time.time()
            experiment["captureSeconds"] = sum(v["seconds"] for v in experiment["results"].values())
            write(manifest, experiment)
            report(case, experiment, output)
            require(record.get("replayStatus") != "failed", "Replay image exceeds measured repeat tolerance; evidence saved in " + str(manifest))
            print(json.dumps({"completed": key, "mode": args.mode, "seconds": round(record["seconds"], 2)}), flush=True)
    print(json.dumps({"manifest": str(manifest), "report": str(output / "report.html"), "observedConditions": len(experiment["results"]),
                      "artAcceptance": experiment["artAcceptance"], "seconds": round(time.time() - started, 2)}))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as error:
        print(json.dumps({"status": "failed", "error": str(error), "newPaidCalls": 0}, ensure_ascii=True), file=sys.stderr)
        raise SystemExit(1)
