# Terrain/operator catalog — cross-project design, not installed capability claims

The scope is common tasks in major engine and terrain ecosystems, not the few landforms seen in Hole or the railway. There is no measured market-share ranking in this document. The candidate does not install or implement every listed backend.

## Reference ecosystems

| Ecosystem | Reusable lesson | Integration boundary |
|---|---|---|
| UE Landscape/Edit Layers + PCG | Non-destructive base/detail/paint/spline layers; attributed points, masks and reusable graph instances | UE-native adapter; not something Godot directly executes |
| Unity Terrain/Terrain Tools | Heightfields, brush/filter/sculpt workflows, tiled terrain data | Editor APIs/operators; validate exact package and render pipeline |
| MapMagic 2 | Node-driven terrain/world-generation architecture and reusable graph organization | Unity plugin; base/add-on capabilities and licenses must be checked separately |
| Houdini HeightFields + HDA | Layered height/mask fields, projection, terracing, erosion and reusable parameterized geometry | Houdini/Engine license, executable and headless integration must be verified |
| Houdini PDG/TOPs | Work-item dependencies, scoped dirtying and executable external tasks | Production scheduling idea; not equivalent to user/art approval |
| Gaea / World Machine | Specialized landform, erosion, mask and build/export graphs | Version/OS/CLI/license-specific external adapter; never assume free commercial automation |
| Godot Terrain3D / Voxel Tools | Native heightfield or volume terrain representation, runtime integration | Choose representation by topology; third-party plugin compatibility is explicit |
| Controlled DCC geometry | Parametric sweeps, profiles, mesh joins, openings and support geometry | Backend-specific operation with stable IO; do not hand-code a new generator every run |

Sources are recorded in [research sources](research-sources.md). Design requirements below are our proposed common operator layer, not a claim that one product has all of them.

## Operator families

| Family | Typical operations | Required controls |
|---|---|---|
| 01 Source/representation | Import heightmap/DEM/mesh, coordinate conversion, resample | Units, axes, transform, extent, resolution, no invented geometry facts |
| 02 Macro form | Noise/fractal, stamp composition, ridge/valley, authored outline | Spatial domain, scale, seed, protected geometry, blend mode |
| 03 Masks | Slope/height/curvature/distance/flow/material masks | Attribute provenance, world-space sampling, predictable value ranges |
| 04 Sculpt/grade | Smooth, flatten, set height, ramp, terrace, cut/fill | Design grades, masks, no unintended gameplay collision edits |
| 05 Linear systems | Road/rail/river/corridor profile and spline sweep | Width, banking, joints, clearance, input route remains authoritative |
| 06 Erosion/weathering | Hydraulic/thermal/transport variants | Feature scale, iteration budget, frozen result, protected masks, neighbor domain |
| 07 Solid landforms | Cliffs, overhangs, arch, cave/cavity, tunnel, mesh/SDF carve | Appropriate volume representation, shell thickness, openings, manifold requirements |
| 08 Water systems | Basins, shore, channel, waterfall ribbon, flow masks | Per-basin elevation and boundary, source/receiver graph, gameplay scope |
| 09 Biome/dressing | Density, exclusion, clustered scatter, slope orientation | Stable IDs, local seeds, clearance, material/scale family |
| 10 World partitions | Tile borders, overlap/halo, LOD, export batching | Shared authoritative edges, generation vs streaming separation |
| 11 Surface integration | Material weight maps, terrain/mesh joins, contact skirts | Texel scale, edge shape, linear/color semantics, no seam concealment by fog |
| 12 Diagnostics/delivery | Bounds/clearance/support checks, native import, memory/profile | Target engine, thresholds with sources, output evidence and invalidation dependencies |

Architecture, parcels and puzzle projection are sibling operator families, not awkward terrain options. Avoid a single `generate_terrain(prompt)` hiding all production decisions.

## Shared operator contract

Input: operator ID/version; backend/version/license availability; actual spatial domain; input hashes; parameters with units; seed policy; protected masks/volumes; semantic interface and neighbor-border hashes; requested fidelity (`proxy`, `sample`, `final`); CPU/GPU/time/output budget.

Output: native geometry/heightfield/volume or asset paths; metadata/masks; bounds/pivots/sockets; ownership; source/output hashes; warnings; measured generation/import cost; support/clearance/seam results where implemented. Declare deterministic/approximate/stochastic behavior. The same seed alone does not prove determinism across backends, software versions or thread settings.

For generated AI assets cache by actual source result/hash and request, not an assumption that the same prompt is reproducible.

## Fast proxy vs final

The same spatial design and interfaces should drive both levels. In proxy mode use coarse sampling and simple materials, disable optional micro-detail and costly simulation. Some algorithms materially change form with resolution: do not assume a lower-resolution erosion run predicts the final exactly. Use higher-fidelity targeted tests where uncertainty demands it, then freeze/cache the result. Promotion preserves design intent and IDs, not necessarily identical topology.

## Terrain tiling hazards

Border equality includes positions, normals/material masks and adjacent logic, not only vertex heights. Erosion/waterflow is nonlocal: use an adequate shared context/halo or bake a broader simulation, rather than eroding each tile independently. Apply variability in world coordinates and derive local seeds from stable IDs so adding a tile does not reshuffle unrelated parts.

Natural terrain can use heightfields; overhangs and stacked traversable layers need mesh/volume support. This is a representation property, not a blanket claim that every contemporary terrain application is heightfield-only.

## Build vs borrow

Prefer wrapping an existing supported operator when it provides the needed controls. Develop thin semantic adapters, validations and IO conversions rather than reproducing proprietary algorithms. Test one suitable backend at a time on a neutral suite: rolling hills, graded road, terraces, overhang/cavity, basin/river, biome boundary and multi-tile seam. Benchmark cold/warm compute, editing and local rebuild cost. A screenshot alone proves neither automation readiness nor performance.
