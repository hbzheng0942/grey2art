# Legacy Hole look development and repeatable execution

Use the executable route below only for its supported external Hole case. General scene rendering work uses [scene effects](scene-effects.md) and [scene comparison](scene-comparison.md); Unity or another game must not be forced through this adapter. The bounded comparison and diagnosis principles can transfer, but its commands, exact styles and gameplay checks cannot. Preserve selected concept and gameplay authorities, and the user's promised styles and scope.

## Executable entry and inputs

Run `python3 <this-skill>/scripts/lookdev.py ACTION ...`. The standalone skill bundles its compatibility runtime in `runtime/legacy`; no product repository or symlink is required. Python >=3.10, Pillow and the game's Godot 4 executable are required. Node is not needed by this runner. Install Pillow into your Python environment from `runtime/legacy/requirements-lookdev.txt`.

The actual Hole case JSON, source project, contracts, adjustment files and canonical asset store remain external, explicitly supplied inputs. Historical `experiments/` and `inputs/` data are excluded from this source package. Their absence does not prevent the generic free fixture or new-project workflow. Use `--source-root`, `--asset-root` and `--godot`; never rewrite historical evidence to pretend it was produced on another machine. Mutable commands require `--overlay` and, except play, `--output`, outside the installed skill.

The runner accepts `check`, `run`, `replay`, `play`, with `--case`, `--source-root`, `--asset-root`, `--godot`, `--overlay` and `--output`. Paths in the case resolve relative to the case file. Canonical source and assets stay read-only. If another machine has different paths, supply root overrides; never edit historical evidence to pretend paths were always portable.

Three explicit input objects:

- Case: source manifest/root, spatial and realization contracts, asset manifest/root, adjustment file, targets, review camera, and budget. The Hole adapter supports exactly the existing two styles and 215 source logical objects. It must reject unsupported games before assembly.
- Adjustments: separate `assembly` and `render` objects per style. Assembly may override an existing region/asset's `target_xyz`, visual `yaw_degrees`, deformation `band`, frontage `cluster_count`, and paving gap. It cannot edit gameplay transforms, colliders or support relationships. Targets remain inside each binding's min/max. Render may change supported illumination, material roughness, floor surface detail and background detail. Unknown controls fail; do not silently ignore typos.
- Targets: selected concept hashes, identified regions, observed defects, required features and blocking/polish status. Current numeric screen boxes measure projected bounds, not perceptual silhouette similarity. Compare requested target dimensions with measured modelXYZ: uniform footprint fitting can be depth-limited, making a larger width target ineffective. A range check passing does not establish that the requested target was reached. Report that residual and route it to local geometry/asset redesign or an explicit concept/space conflict.

Example with `$SKILL` set to the installed skill and explicit external inputs:

```sh
python3 "$SKILL/scripts/lookdev.py" check --case "/path/to/local-hole-case/case.json" --source-root /path/to/hole --asset-root /path/to/sha256 --godot /path/to/Godot
python3 "$SKILL/scripts/lookdev.py" run --case "/path/to/local-hole-case/case.json" --source-root /path/to/hole --asset-root /path/to/sha256 --godot /path/to/Godot --overlay /task/hole-overlay --output /task/factorial
python3 "$SKILL/scripts/lookdev.py" replay --manifest /task/factorial/experiment.json --source-root /path/to/hole --asset-root /path/to/sha256 --godot /path/to/Godot --condition baseline --overlay /task/hole-repeat-overlay --output /task/repeat
python3 "$SKILL/scripts/lookdev.py" play --manifest /task/factorial/experiment.json --source-root /path/to/hole --asset-root /path/to/sha256 --godot /path/to/Godot --style ceramic --overlay /task/hole-play-overlay
```

Use `--mode full` for the final two-style native interaction/input checks. The ordinary-input probe injects keyboard events through the original movement/physics path at fixed steps, compares all simulation objects against the original simulation, calls the original camera occlusion path, and records four gameplay views. It is an automated smoke test; it does not establish full-round human play acceptance. The default `look` mode performs only fast structural checks and captures the concept and gameplay views. It does not prove full playability.

## Bounded experiment

This section describes the supported Hole factorial/replay experiment. For ordinary production, select the smallest comparison that resolves the current uncertainty within the existing case; four conditions and a clean-context replay are not required for every lighting adjustment.

1. Verify inputs and freeze the current baseline. Historical captures help diagnose defects but cannot certify current source. Record source/runtime/asset hashes, device, camera and frozen time. Freeze physics before the first ready/physics frame and all original shader TIME uses, including the hole interior. Repeat the material freeze after every view synchronization: restarting the game creates new materials with default time values. Freezing only the initial materials produces false determinism.
2. Declare the important mismatches before tuning. Classify assembly, rendering, asset defect, or concept/space conflict. Keep the high-fidelity target explicit; an impossible source-space relationship requires a reported conflict, not silent geometry relaxation.
3. Reuse the fixed assets to capture `baseline`, `assembly`, `render`, `combined` for every selected style. `combined` must use exactly the same assembly and render settings as the individual conditions. Capture sequentially on one device. Compare matching views and original runtime camera readability.
4. Route each remaining mismatch to its actual cause. Refit or repair only the affected asset/region. Add new generation only when it addresses a concrete blocker, within the current user's scoped allowance. Freeze a new case/asset manifest for the repair phase so it does not contaminate the fixed-asset comparison.
5. Run full native checks on the final candidates; review concept, baseline, final composition, contacts and ordinary-input captures. Preserve open defects and final human art acceptance separately from technical success.
6. Replay from a clean-context session using only this Skill and explicit manifests. No legacy `runs/`, private quote files, cached success flag, author's hidden instructions or new generation may be required to rebuild the visual result.

No automatic paid retry on an unknown outcome. Reserve attempts before dispatch and query saved task IDs after interruption. A call failure consumes the scoped attempt allowance unless authoritative evidence proves no call was dispatched; do not reset accounting across phases. New Lux generation selects G1/G1-Turbo and face count per asset's visible complexity and native budget in the user-confirmed H3 proposal. Apply explicit current user restrictions; G1 omits enablePbr. Preserve historical task parameters and reuse suitable older assets.

## Renderer diagnosis that changes decisions

Keep native material import/calibration separate from artistic look overrides. A conversion parity pass is not concept fidelity. Surface features unsupported by the converter must be reported before assembly; dimming lights cannot repair incorrect texture channels.

Godot Mobile does not support directional PCSS, so changing `sun_angular_distance` does not produce the intended soft shadows there. Use explicit supported directional PCF filter quality, constant shadow blur and measured shadow opacity; retain renderer, tone mapping and camera during the comparison. See [Godot Light3D](https://docs.godotengine.org/en/4.7/classes/class_light3d.html) and [RenderingServer](https://docs.godotengine.org/en/stable/classes/class_renderingserver.html#class-renderingserver-method-directional-soft-shadow-filter-set-quality). Revalidate actual screenshots on the installed engine/device.

## Evidence and completion

The runner binds evidence to exact runtime and input signatures. Changed source/config/assets invalidate replay; use a new output directory and capture again. Missing/changed screenshots fail before reuse. A failed image comparison retains its native captures, deltas and experiment manifest; inspect the cause and use a fresh output after correcting it. Repeated baseline captures determine the image tolerance on the same engine/device; zero variation supports exact-image replay only for that tested setup.

Report actual complete styles, elapsed/capture time, interventions, local repairs, generation attempts, quote totals and unknown settlement/image money. Historical manual-time baselines are unavailable: do not invent a speedup percentage. Fast replay measures reconstruction efficiency, not general new-style creation success.

Keep a current result and last verified result, with explicit named experiment evidence. Candidate outputs contain controls, screenshots, logs and hashes; original GLBs/textures remain canonical. Never copy the game or its caches into evidence or the source kit. The standalone skill contains the runtime and dependency declarations, but external Hole source/assets must be supplied explicitly; it is not an asset-complete game distribution.

Independent art review can be agent-authored; final human acceptance must remain pending until the user actually accepts the exact result. Do not label the pipeline portable v0 until the original Hole/new-style, second-game and colleague-project gates have passed.
