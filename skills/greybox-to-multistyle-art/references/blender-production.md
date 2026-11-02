# Bounded Blender production jobs

Use `greybox.py blender bake|scatter|render --file JOB.json --executable BLENDER` for these jobs. They run in a separate factory-startup background process; the user's live Blender document is never changed. Existing static geometry inspect/run/verify commands remain available.

Common job fields:

```json
{
  "schema": 1,
  "kind": "blender-production-job",
  "job_id": "crate-bake",
  "operation": "bake",
  "input": {"path": "/absolute/canonical/source.glb", "sha256": "EXACT_SOURCE_HASH"},
  "output_dir": "/absolute/new/task-output",
  "bake": {
    "resolution": 1024,
    "channels": ["base_color", "normal", "ao"],
    "uv": {"mode": "preserve", "name": "UVMap"},
    "normal_convention": "opengl",
    "samples": 16,
    "margin_px": 4
  }
}
```

The input is one embedded, hash-bound static GLB. Rigs and shape keys use the character workflow. For diagnostic checks only, replace `input` with `"fixture":"diagnostic_cube"`. An explicit fixture establishes tool behavior, not production art acceptance. Choose a fresh external output directory; unrelated/previous outputs are preserved. `job.json`, worker hash, Blender version, invocation log, exact input hash and output hashes bind the result. The API also supports `greybox.blender_jobs.validate(job)`, `execute(job, executable=...)` and `verify(job)`.

## Bake

Resolution is 16–4096, samples 1–256. UV mode is `preserve` (the named layer must exist) or `smart_project` (creates/updates that layer on the imported working geometry). Each mesh receives its own texture set, avoiding cross-object UV aliasing. Base color is baked without lighting and tagged sRGB; AO and tangent normals use Non-Color. Specify OpenGL +Y or DirectX -Y. The GLB always uses OpenGL normals; a requested DirectX map has a separate converted +Y texture for glTF material export.

Outputs include the texture channels, textured `asset.glb` and one compressed editable `recipe.blend`. Textures remain external to the recipe rather than being repacked. The self-contained GLB embeds maps for target-engine import. These are distinct requested production outputs; unchanged input assets are referenced by path/hash and are not snapshotted.

## Scatter

Replace `bake` with `scatter`, and set `operation` to `scatter`:

```json
{
  "count": 200,
  "seed": 17,
  "bounds_xy": [-10, -8, 10, 8],
  "height_m": 0,
  "scale": [0.8, 1.2],
  "exclude_rects": [[-2, -8, 2, 8]],
  "density_mask": {"path": "/absolute/density.png", "sha256": "EXACT_MASK_HASH"}
}
```

The optional mask maps its complete image across the declared Blender XY bounds, bottom-left image origin; luminance times alpha controls admission probability. Exclusions are applied first. Positions, uniform scales and yaw are deterministic for this seed/input. If sparse masks cannot fit the requested count within the sampling budget, the job fails explicitly.

`instances.json` references the one source GLB and exports stable instance IDs, metre translations, XYZW quaternions and scales in glTF Y-up coordinates. It contains transforms rather than cloned mesh geometry. A fixture creates one `prototype.glb`; a real input reuses its canonical path/hash. Target-engine instancing and gameplay clearances are verified in that engine.

## Render

Replace `bake` with `render`, and set `operation` to `render`:

```json
{
  "resolution": [512, 512],
  "frames": [1, 2, 3],
  "samples": 16,
  "view_transform": "Standard",
  "transparent_background": false,
  "camera": {"position": [3, -4, 2.5], "target": [0, 0, 0.5], "projection": "orthographic", "ortho_scale": 3},
  "lights": [{"type": "AREA", "position": [2, -3, 5], "target": [0, 0, 0], "energy": 500, "size": 3}],
  "environment": {"color": [0.05, 0.05, 0.05], "strength": 0.5},
  "turntable_degrees_per_frame": 10
}
```

Coordinates use Blender XYZ metres (+Z up). Camera projection is orthographic or perspective (`lens_mm`, default 50). Lights are AREA/SUN/POINT. Choose Standard or AgX explicitly; exposure is 0, gamma 1 and look None. The bounded implementation uses Cycles CPU, avoiding undeclared GPU setup. Up to 240 explicit frames produce PNGs. The replayable `job.json` references the canonical input; render reviews do not create duplicate scene snapshots. Frame rotation is optional; a static scene without declared motion remains static.

These are material/geometry/render outputs. Useful art, engine import, runtime performance and playability require separate native checks. Complex fluid simulation, hair and arbitrary compositor translation are outside this API.
