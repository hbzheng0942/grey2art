# Optional Blender geometry backend

Blender supplies geometry operations; Godot/Unity/Three.js supplies the playable host. Blender is optional when the asset recipe does not require its operations. A configured MCP, an available executable, an executed operation, and a successful runtime import are separate evidence levels.

## Implemented scope

`runtime/greybox/blender.py` provides `discover`, `validate_job`, `build_script`, `prepare_job`, `execute_cli`, `verify_result`, and `validate_native_admission`. `schemas/blender-job-template.json` is the input contract. No AI generation, installation, paid API, or live editor action occurs during validation/build-script.

Implemented jobs import an immutable, self-contained GLB or create an explicitly diagnostic cube; bake static mesh world transforms; use uniform metre/height normalization; fit a declared base/center/origin anchor; apply a declared bevel; inspect PBR channels or explicitly normalize texture color spaces; export explicit GLB with stable IDs, semantic anchor empties, operation manifest, bounds and optional diagnostic PNG. Uniform height fitting preserves proportions. It does not solve arbitrary interface fitting, terrain, retopology, UV repair, LOD, rigging, animation or full Geometry Nodes recipes. Those operations must not be advertised by this backend.

Rigged meshes and shape keys are refused by this static path. Route them to character processing instead. GLB external image/buffer references are refused until embedded and hash-bound. glTF uses metres/Y-up; `position_m` anchors in the job use Blender XYZ/Z-up before explicit glTF conversion. A height target overrides the unit factor to achieve the requested absolute height; no nonuniform box fitting is implemented.

## Portable execution

Discover `BLENDER_BIN`, `blender` on PATH, or the known macOS application paths. The executable version is recorded. Use the project's pinned Blender build; no automatic upgrade or installation.

From a host agent, load JSON and call `execute_cli(job)` in the bundled runtime. It launches an independent `--background --factory-startup` process with an explicit script argument and records its return code/log. It never loads the user's open .blend. For MCP, call `prepare_job(job)`, inspect the generated script, and invoke its exact `mcp_code` through the host-discovered Blender code tool. Then call `verify_result(job)` and retain the actual MCP invocation receipt. MCP configuration alone is not a verified capability.

The job requires a new task-owned output directory; unrelated artifacts, existing exports and changed job/script content are refused. Outputs are the changed GLB, compact report/log and optional PNG. Inputs remain at canonical paths with hashes; no project tree, assets, cache or Blender executable is copied. Completed jobs are immutable. Interrupted or failed jobs keep evidence and require a new output directory rather than overwriting an uncertain result.

## Live document preservation

The MCP worker creates a separate scene and new data IDs, exports only the active task scene/selected task objects, restores the original scene/view layer, and removes only its created IDs. It never saves or opens a .blend, changes the original camera/render settings, or uses undo as rollback. Original selection, active object, data IDs, file path, units, frame and camera/render settings are checked after cleanup. Non-object live modes are refused; use a background job instead. Shared original materials are copied before modification; color-space changes use image copies.

The exporter must use `use_active_scene=True`. A Blender 5.1.2 background probe crashed inside the native dependency graph when the exporter traversed other scenes under a temporary context. The corrected explicit-scene path passed. Render engine identifiers are discovered from the running build rather than assuming `BLENDER_EEVEE_NEXT` exists. These are executable defaults, not reminders to the user.

## Runtime admission and evidence

`verify_result` checks the input/job/output hash binding, valid GLB container, unique exported mesh `extras.stable_id`, finite positive bounds, approved envelope, preview hash and user-state restoration. The report lists observed material values and channels; it does not judge aesthetic quality or claim complete lighting calibration.

Native admission requires the exact exported asset hash and a real JSON report from the runtime import, bound by its own file hash. The report and admission receipt both carry `engine`, `asset_sha256`, `status: passed`, and successful `mesh_bounds`, `materials`, `stable_ids` checks. Use `schemas/blender-native-admission-template.json`; read evidence contents instead of trusting a nonempty evidence path. For Godot, inspect imported `MeshInstance3D` nodes/AABB/materials and retained glTF extras metadata. If the engine changes stable-ID representation, resolve through a documented sidecar and prove the mapping. Do not infer runtime admission from Blender export success.

For Godot this is executable: `greybox.blender_godot.native_admit(job, godot_path=None)` launches the native GLTFDocument importer and returns a bound admission receipt. Each invocation creates a tiny new `native-godot/attempt_<id>` directory inside the owned Blender job output. It references the original GLB and bundled GDScript; no asset/executable copies or editor import cache. It checks metre bounds, base contact when declared, unique mesh stable IDs, material presence and observed source PBR values including linear/sRGB conversion. `verify_godot_admission(job, receipt)` rechecks actual logs and input/adapter/script/engine/report hashes. Any Godot `ERROR` or `SCRIPT ERROR` rejects the attempt even when exit status is zero and the script wrote `passed`. The probe defers execution after SceneTree initialization and accumulates local matrices; it does not query unready global transforms.

Diagnostic jobs validate this integration only; they are not generated art, a production sample, gameplay evidence, H4 or H5 acceptance. Target lighting, interface clearance, motion/contact behavior, visual fidelity, performance and playable checks remain in the host engine workflow.

## Local verification (2026-10-20)

Blender 5.1.2 on macOS: background diagnostic cube → 1.2 m uniform fitting → bevel → GLB/extras → PBR report → PNG passed; immutable GLB import → fitting → bevel → GLB passed. The live MCP import/fitting/bevel/export probe also completed, and its output/report hashes, stable mesh ID and approximately 1.2 m bounds passed `verify_result`; original data/selection/active object and camera/render/unit settings were restored. These are diagnostic static-geometry checks. Native Godot admission has its own runtime receipt in the release evidence; do not infer it from either Blender path.

The reusable native Godot 4.7.2 admission then passed on that exact MCP output, with no engine errors: imported stable mesh ID and support anchor retained, approximately 1.2 m bounds/base contact, source roughness/metallic/albedo and disabled emission verified. This proves this diagnostic Blender → GLB → Godot chain; representative textured production assets and playable scene/visual acceptance remain separate tests.

Official API references: [glTF export operator](https://docs.blender.org/api/5.0/bpy.ops.export_scene.html), [context overrides](https://docs.blender.org/api/5.0/bpy.types.Context.html). Actual supported operator parameters/render enums are verified against the running executable.
