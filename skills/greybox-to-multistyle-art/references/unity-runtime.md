# Unity 6 URP native runtime

Read this for Unity inspection, scene assembly, effects, PlayMode evidence or Player export. The bundled bridge targets Unity 6000.3 and URP 17.3; it never substitutes Godot receipts for Unity results.

## Entry points

`greybox.unity.run(project, operation, config, output, unity_bin=None, timeout=300)` implements `inspect`, `import`, `assemble`, `lookdev`, `capture`, `validate`, `play`, `export`, `configure` and the small `fixture` probe. `inspect(project)` and `dependency_snapshot(project, plan)` are read-only static inventories. `UNITY_BIN`, the explicit path and the project-version Hub install are discovery inputs on Windows/macOS.

Pass `scene` as an existing `Assets/...unity` path, `output_root` as a new style-owned `Assets/...` revision and an external-to-Assets `output` evidence directory. `assemble` accepts the common `plan`, `style_id`, `bindings` and `effects` configuration. It returns `artifact` with entry scene, ownership hashes, native source hashes and binding digest. `validate`/`capture` accept that artifact. Changed source or artifact hashes require reassembly.

`configure_packages(project)` adds absent `com.unity.render-pipelines.universal: 17.3.0` and official `com.unity.cloud.gltfast: 6.20.0`. Existing versions are preserved for deliberate compatibility review. Package Manager resolves the lock file; retain the actual `Packages/packages-lock.json`. glTFast owns glTF axis conversion and material import. Calibrate imported PBR/normal/alpha conventions before look development. A project with another pipeline is not silently converted.

The bridge is a small managed copy under `Assets/GreyboxArtRuntime`. Upgrade checks its previous hashes and refuses to overwrite local edits. Unity serializes a new scene variant while assets/prefabs/scripts remain references. No source project, engine, Library cache or game asset copy is created. Save/reopen and full dependency inventory are part of assembly.

External canonical GLBs can enter the project through `admit_asset(project,source,destination)`: APFS clonefile is preferred, otherwise only bounded small copies are allowed (64 MiB/file, 256 MiB/project by default). `require_clone:true` prohibits fallback. Admission verifies content/metadata and independent file identity, preserves an existing changed destination, and records original canonical path/hash/transfer method in `art/asset-admission.json`. No project snapshots, mutable hard links or unsupported external symlinks are created. Configure measured transfers explicitly when the limits cannot be met.

For a deliberate rebuild after source/deployment changes, pass `rebuild_owned:<previous artifact>` with identical binding digest and output root. Every prior owned file must still match its recorded hash. The Editor reassembles the scene against current source while reusing unchanged canonical resources; changed art parameters require a new revision. Source hashes are collected from that actual new assembly, never manually refreshed. BuildSettings is itself hashed without treating every other selectable scene as a dependency of the selected scene.

## Assembly and recipes

Each binding has a distinct `id`, explicit `owner` hierarchy path, optional `owner_global_id`, optional `hide` paths, `source`, anchors, Euler rotation and positive uniform scale. Imported art must be visual-only: qualify scripts, colliders, cameras and lights separately. Hiding changes Renderer.enabled, preserving GameObjects, colliders and scripts. Primitive sources are explicit technical/procedural choices, never an implicit replacement for missing generated art. Static uniform-bounds normalization is supported; skinned content requires units and explicit anchors.

`normalize:{mode:"uniform_bounds",target_size:[x,y,z]}` uniformly fits static renderer bounds inside the declared world-space gameplay envelope using the smallest nonzero-axis ratio; proportions are preserved. `max_extent` remains available when no target envelope is supplied. `anchor_mode:"bottom_center"` aligns the final scaled/rotated renderer bottom center to the owner's declared `anchor`; default `source` uses explicit `source_anchor`. Owner-space bounds normalization is not silently substituted for world-space fitting.

The `effects` object accepts these optional keys:

| Key | Inputs and native implementation |
|---|---|
| `lighting` | `sun_energy`, `sun_rotation`, `color`, `ambient_color`, `ambient_energy`, `fog_density`, `fog_color`, `exposure`, `bloom`; directional light, Unity fog, URP Volume with ACES/exposure/Bloom |
| `water` | `position:[x,y,z]`, `size:[w,d]`, shallow `color`, `deep_color`, `normal_texture`, `shore_mask`, `speed`, `amplitude`, `shore_width`, `depth_distance`, `roughness`; bounded mesh, masked shoreline, depth contact, flowing normals, animated waves and reflection probes/environment |
| `grass` | `bounds:[xmin,zmin,xmax,zmax]`, `count`, `seed`, `exclude_rects`, `density_mask`, `mask_threshold`, `ground_y`, `height`, `width`, `wind`, `chunk_size`, `cull_distance`, `color`; deterministic chunked instancing with frustum/distance culling and vertex wind |
| `ground` | `position`, `size`, `color`, `secondary_color`, `texture`, `secondary_texture`, `blend_mask`, `tile_scale`, `blend_scale`; world-scale tiling, mask/procedural blending and main-light shadows |

Colors are `[r,g,b,a]` floats. Common `exposure` is a positive brightness multiplier (1 neutral), converted to Unity post-exposure stops. `bloom` accepts numeric intensity or boolean (`true` maps to .25). Grass `y` aliases `ground_y`. Unknown recipe keys fail instead of being silently ignored. Color textures require sRGB; masks/normals require linear import. Grass density masks must already have Read/Write enabled. The bridge reports unsuitable imports rather than rewriting shared canonical inputs. New project URP setup requires explicit `configure_pipeline:true`; existing lighting/renderer configurations are otherwise respected.

Use native `lighting.light_path` to configure an existing visual Light in the new scene variant, avoiding duplicate directional lights. Omit it only when a new owned light is intended; a declared missing light fails.

Recipes create style-owned editable Materials/Meshes/VolumeProfiles. Grass excludes declared route rectangles; gameplay heightfields or arbitrary shoreline meshes require a project-specific extension. Water uses URP depth and reflection probes, not a fluid simulator. Set camera depth texture on the target URP asset/camera for water contact.

## Native evidence and limitations

`capture` and `validate` enter actual PlayMode, wait `warmup_frames`, then sample `capture_frames` at `frame_stride`. They use a real graphics device and URP render requests; `-nographics` is never used. Configure `camera_path`, `width`, `height`. Receipts include PNG hashes, frame/time, graphics API/device, memory and sampled frame times. Editor timings are diagnostics, not target-device performance certification.

Contract assertions support `exists`, `active`, `component` and named-object `count`; unknown assertion types fail explicitly. Missing scripts, shader errors and runtime errors fail. Project-specific gameplay assertions remain necessary for full mechanics/rig/interaction coverage.

Gameplay uses the existing `contract.validation.steps` with `hook:{path,method}` and `expect:{key:value}`. Implement one public MonoBehaviour hook returning `Dictionary<string,object>`, accepting either no argument or the original step as a JSON string. The bridge executes each step during actual PlayMode, compares its returned observations, captures the resulting frame, and records exact step IDs and state. A hook may consume `step.hook.args` to drive project-specific input or fixed simulation steps. An `input_action` without an explicit handling hook fails. Structural checks alone leave `gameplay_verified:false`; only nonempty successful expected gameplay observations set it true. Native errors still fail either result.

`export` requires an explicit `player_output`, optionally a Unity `build_target`; the platform module must be installed. `build_scenes` selects an ordered, nonempty list of unique existing `Assets/*.unity` paths; its first scene starts the Player. Omission preserves the single `scene` default. Every included scene and its GUID/shader closure is hashed before and after export. Unity’s automatic `Assets/**/Resources` content is also frozen; declare other computed Addressables/dynamic inputs in `plan.contract.source_paths`. Every actual packed project source must appear in that pre-build snapshot. The native receipt records included scenes, output files and packed source sizes. Two transient JSON metadata resources produced by pinned Unity performance-testing 3.5.0 are recorded by a final pre-build callback with exact bytes/hashes and producer identity; arbitrary new game inputs remain rejected. Build success is separate from actually running the Player and human H5 acceptance. A nonzero Editor exit, timeout, missing/stale/mismatched receipt fails even if some output files exist. Keep reports and logs together, tied to their source and artifact hashes.

Run native `configure` during preflight before freezing a new project's baseline: Unity 6 requires complete global default Volume overrides and otherwise repairs that asset at build time. The configure operation uses the same public VolumeProfile utility as the build preprocessor. Both capture and export recheck artifact/source bytes after native execution; a successful engine build with changed source inputs still requires reassembly, and cannot silently certify the previous revision.

Official references: [URP 17.3](https://docs.unity3d.com/Packages/com.unity.render-pipelines.universal@17.3/manual/index.html), [Unity glTFast](https://docs.unity3d.com/Packages/com.unity.cloud.gltfast@6.20/manual/index.html), [URP render requests](https://docs.unity.com/en-us/engine/6000.0/manual/cameras/urp/multiple/user-render-requests).
