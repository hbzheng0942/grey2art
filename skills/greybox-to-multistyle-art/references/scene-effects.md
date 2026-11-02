# Native scene effects

Read this during design when a key appearance depends on material response, light/shadow, reflections, transparency, atmosphere or motion, and again when native output exposes a related gap. The agent identifies the visible requirement; `knowledge next` only routes reading. Keep the source project's renderer and package versions. Shared visual intent can require different native implementations.

## Select the amount and route of work

In the existing feature/production record, connect the desired visible phenomenon to its responsible layers, necessary scene inputs and observation view/state. Choose the work and intervention stage together: shape or construction may need modeling/reused assets, surface response may need material authoring or baking, and view-dependent light may need a native rendering feature. For clear water this may involve bottom geometry, depth, absorption and reflection. Resolve inputs affecting asset construction before producing that asset. Prioritize style identity, visibility and gameplay value against authoring and runtime cost; a small but distinctive feature can matter more than its screen area. A short decision in the existing plan is enough; no separate effects form is required.

| Current situation | Action |
|---|---|
| A project or packaged recipe fits the target and installed profile | Reuse it; check its input contract and actual result in this space. |
| A normal engine feature can deliver the requirement | Use the installed-version official manual/API and existing project settings directly. A new wrapper is optional. |
| A selected wrapper rejects an input or lacks the effect | Keep the visual target; inspect a suitable native operation, importer or existing implementation. Report the wrapper gap separately from engine support. Do not strip source features merely to pass its gate. |
| An important requirement is unfamiliar or repeatedly fails | Inspect a matching official sample or sourced implementation, then isolate the largest uncertainty in the existing S6/native probe. Record the result before expanding its use. |
| A heavy effect contributes little to the requested view or interaction | Keep a simpler native material/lighting route or skip that effect. Preserve the appearance requirement. |
| A necessary input is unknown | Inspect the project first; request only information that cannot be recovered. Continue unrelated work. |

Official lookup starts with a concrete question and the actual engine/version/pipeline/device: what supports this phenomenon, what inputs it needs, and how to observe its contribution. Prefer installed package documentation and samples, then matching official web documentation. Use the result to operate the native editor, CLI/API or available MCP directly; package a helper only when repetition or fragility justifies it. A sourced existing implementation is also a candidate after checking license and compatibility. Check API availability against the installed runtime when versions differ. Links and successful compilation do not establish the target appearance. Do not silently convert URP to HDRP, change a Godot renderer, or use an offline result as a runtime substitute.

Use a small native probe when a high-impact uncertainty could change geometry, assets, the chosen route or its cost. State the one question, competing actions, necessary view/state and repair budget before running it. Stop when that decision is supported or the budget is spent; retain the unresolved goal and choose the next feasible route. Do not default to a full-scene rebuild or a matrix of engines. Routine light/material tuning can proceed in the current scene. Reuse [scene comparison](scene-comparison.md), original authorization and repair allowance; no new stage or approval is introduced. Successful recurring fragile operations can become a recipe with the [calling contract and bounded lessons](render-capability-recipes.md).

An unresolved critical effect blocks completion of its affected sample or delivery, while unrelated ready work can continue. Identifying a gap is diagnosis; continue toward a feasible implementation or name the concrete input/deployment constraint that prevents one. General routing lessons can be retained from failed probes; promoting a specific recipe still needs evidence for its declared visual scope.

## Apply a recipe

Use `python3 scripts/greybox.py engine lookdev --project PROJECT --file effects.json --output OWNED_OUTPUT --engine godot|unity`. The JSON contains an existing native `scene` and `effects` object. Godot writes an inherited scene with owned scripts; Unity writes a serialized scene variant and native materials. This entry exposes the bounded families below, not every native rendering feature. The shipped Godot route supports Compatibility; the shipped Unity bridge targets URP 17.3. Forward+ SSR water, HDRP Water and Cycles research recipes are separate implementations and are not bundled options of this command.

For Godot, `OWNED_OUTPUT` is a task-owned directory inside the project and staging reports `native_verified:false`; launch/capture the generated entry scene to establish native evidence. For Unity use the bridge's style-owned `Assets/...` output root and evidence path described in [Unity runtime](unity-runtime.md). Inspect/capture the actual resulting scene before expanding it. Output is small source and resource files, never a cloned project.

Per-style production plans may include `styles[].effects`. They enter the ordinary assembly manifest and source/runtime identity; differing styles do not share mutable effect data. Local recipe extensions are allowed when a selected concept requires them, with explicit parameters, owned source and native evidence. Record target/device budgets before choosing high density or expensive reflections.

## Common recipe families

| Family | Main parameters and intent |
|---|---|
| lighting | sun_energy, sun_rotation, color, ambient_energy/color, fog_density, exposure, bloom. Optional light_path configures an existing directional light in the scene variant, avoiding a second sun. Exposure is a positive brightness multiplier; engine adapters implement their native control. Rotation uses the declared native engine coordinate convention. |
| water | position, size, color, speed, amplitude. Keep a bounded surface, place it below the actual bank and check minimum wave clearance against bottom geometry. |
| grass | bounds=[xmin,zmin,xmax,zmax], count, seed, height, color, wind, cull_distance, exclude_rects. Keep travel paths and interaction spaces clear. |
| ground | position, size, color, secondary_color, tile_scale, texture, secondary_texture, blend_mask. Texture scale is world-based; base color images use color interpretation, masks use data interpretation. |

Example:

```json
{"scene":"res://Main.tscn","effects":{
  "lighting":{"sun_energy":1.2,"ambient_energy":0.5,"exposure":1.0},
  "water":{"position":[3,0.2,0],"size":[5,10],"speed":0.5,"amplitude":0.04},
  "grass":{"bounds":[-5,-5,0,5],"count":600,"seed":42,"exclude_rects":[[-1,-1,1,1]]},
  "ground":{"position":[0,-0.02,0],"size":[12,12],"tile_scale":1.5}
}}
```

For Unity use an `Assets/...unity` scene. Its documented native recipe extensions include depth-based shore/deep color, normal maps, density masks and quality/chunk controls; see [Unity runtime](unity-runtime.md). Unsupported fields must be rejected rather than silently ignored.

## Godot implementation

`effects.py` validates supported fields, finite ranges and referenced project textures. Common raster inputs are decoded before staging; dependency records bind hashes and color/data interpretation. `runtime/godot/effects.gd` creates owned environment/light, surface meshes and spatially chunked MultiMesh grass. It never creates gameplay collision.

Water additionally accepts `deep_color` (RGB/RGBA), `normal_texture` (tangent-space normal map), `roughness` (0..1), `shore_width` and `depth_distance` (positive world units). Its normal texture flows in two directions; omitting it retains procedural ripple normals. With an explicit `deep_color`, `color` is the shallow color and `deep_color` is reached at `depth_distance` inland. Omitting `deep_color` keeps legacy color inland with a brighter edge. A red-channel `shore_mask` encodes inland distance divided by `depth_distance`; absent a mask, distance to the rectangular surface boundary supplies the fallback. `shore_width` controls edge opacity fade. This Compatibility implementation describes authored shore/depth appearance, not sampled physical bathymetry or scene-depth intersection. Supply a mask for irregular banks. Reflection uses the configured native sky/environment; roughness controls the reflection lobe.

Grass additionally accepts `density_mask`, `mask_threshold` (0..1), `width`, `chunk_size` and `ground_y`. Mask UV covers the declared bounds: black rejects, values at or below the threshold reject, and remaining red values supply deterministic acceptance probability. `count` is the requested population; at most `30 * count` candidates are tested, so sparse masks can produce fewer cards. The native node exposes `grass_report` with accepted count and chunk count. Exclusions always reject candidates. Height, width, chunk size and cull distance use world units; width defaults to `0.35 * height` for legacy appearance. `ground_y` aliases legacy `y`; conflicting values are rejected. Cards are grouped around actual chunk centers so distance culling applies spatially, with a wind margin. `cull_distance=0` disables distance culling. Ground accepts optional tileable color textures and a data blend mask. Albedo uses `source_color`; normal maps and masks use data sampling without sRGB conversion.

The default Godot implementation supports Compatibility. Bloom requires a supported renderer; a request on Compatibility is reported, never used as a reason to switch the project. SSR/volumetric effects require a separate explicitly supported native extension. Grass `ground_y`/`y` supplies a flat base; arbitrary terrain projection is not implicit. Use a DCC-produced scatter layout or an owned terrain extension where needed. Signed flow speed is allowed; amplitude/wind must be nonnegative. Exposure, surface dimensions, tile scale, grass height/width and chunk size must be positive. Unknown fields fail before staging.

## Native review and troubleshooting

Check the selected route's installed capability and required scene inputs, then inspect material channels, color spaces, normals, alpha/culling and import settings under stable camera/light. When an import or conversion is suspect, use a small affected-channel comparison before compensating with lighting; do not run every calibration fixture for a routine correction. For transparent/reflective effects also inspect depth, off-screen data, ordering, geometry or masks and active environment/camera overrides. Then tune the authored style. Avoid compensating a material decoding error with brighter lights. See [visual diagnosis](visual-harness.md) for symptom routing.

Capture a complete gameplay view and necessary close views. Record version, pipeline/renderer, camera, time and source/asset/shader hashes. Measure frame costs on the target runtime before claiming budget compliance; capture duration or video playback rate is not FPS. Dynamic water/wind requires at least two separated frames; inspect a sequence and moving view when the target depends on motion or screen-space behavior. Different hashes alone do not establish desirable motion. Check shore intersections, alpha ordering, grass density/exclusions, shadows, ground scale, contact and action readability. For a playable deliverable, a Blender render cannot replace this target-engine check; for an explicitly offline deliverable, evaluate its actual requested output.
