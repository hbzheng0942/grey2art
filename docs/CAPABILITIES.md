# Capabilities, tools and tested scope

[English](CAPABILITIES.md) · [简体中文](CAPABILITIES.zh-CN.md) · [Homepage](../README.md) · [Install](INSTALL.md)

**Grey2Art turns one gameplay greybox into playable prototypes in multiple art styles.** Start with the existing game, select the delivery styles, complete the priority style's whole playable sample, then expand the remaining styles. Outputs stay editable in the native project.

The tables below list production routes, tool entry points and tested scope. [Release notes](../CHANGELOG.md)

## What you can make

| Task | Concrete output | Method and current boundary |
|---|---|---|
| Build a greybox from a brief or reference | A small native playable level, editable gameplay code and check records | [Greybox authoring](../skills/greybox-to-multistyle-art/references/greybox-authoring.md). Implement the defined core loop; clarify rules and dimensions not shown by the reference. Continue into one or more art styles when requested. |
| Explore multiple art worlds | Numbered scene concepts, selected styles and a priority style | [Concepts](../skills/greybox-to-multistyle-art/references/concept-authoring.md). Actual images need visual review; exploration count and delivered style count are separate choices. |
| Turn a selected concept into a buildable scene | Key views, spatial design, asset responsibilities, interfaces and an early native composition probe | [Spatial design](../skills/greybox-to-multistyle-art/references/spatial-contract.md) and [scene comparison](../skills/greybox-to-multistyle-art/references/scene-comparison.md). A concept image alone does not prove metric geometry or a working scene. |
| Prepare and produce assets | Isolated references, necessary views, generated/reused/authored models and an assembly plan | [References](../skills/greybox-to-multistyle-art/references/modeling-references.md) and [production](../skills/greybox-to-multistyle-art/references/hybrid-production.md). New AI meshes use approved image inputs; each major visual feature needs a suitable route. |
| Assemble playable art styles | Style-owned native scenes/resources, actual captures and relevant gameplay checks | [Engine adapters](../skills/greybox-to-multistyle-art/references/engine-adapters.md). Godot and Unity have native routes; complete art, gameplay and performance acceptance remain task-specific. |
| Revise an existing result | Scoped source changes, comparable views and checks of affected interactions | [Visual diagnosis](../skills/greybox-to-multistyle-art/references/visual-harness.md) and [scene effects](../skills/greybox-to-multistyle-art/references/scene-effects.md). An accepted direction can be retained for local changes. |
| Resume interrupted work | Current focus, preserved references, original supplier jobs and outstanding work | [Continuity](../skills/greybox-to-multistyle-art/references/continuity.md). Unknown submissions are reconciled before retrying; an upgrade does not rewrite historical acceptance. |

Greybox creation/revision and editable Blender spaces are additional scoped routes. They can end at the requested native baseline or `.blend`; they do not automatically start a multistyle art project. See [native authoring](../skills/greybox-to-multistyle-art/references/greybox-authoring.md).

## Choose a host and native endpoint

| Area | Available work | Setup |
|---|---|---|
| Codex, Claude Code, WorkBuddy | Shared Python CLI; optional wrappers/connectors | Local command execution and suitable image tools. [Host setup](../skills/greybox-to-multistyle-art/references/hosts-v04.md) |
| Godot | Native inspection, art assembly, capture, gameplay checks and export | Use the project's existing Godot installation and version. |
| Unity | Editor/PlayMode assembly, materials/effects, capture, gameplay hooks and Player export | Use the project's Editor and render pipeline. [Unity route](../skills/greybox-to-multistyle-art/references/unity-runtime.md) |
| Blender | Editable spatial authoring/review, static GLB processing, baking, scattering and rendering | Prepare for selected operations. General retopology, UV repair, LOD, rigging and animation cleanup use a suitable separate tool or provider. [Blender operations](../skills/greybox-to-multistyle-art/references/blender-backend.md) |

Keep the project's existing engine and version. Check visuals, interactions and performance in the intended player build and device.

## Functional tool entry points

These are entries into the existing workflow, not extra installation requirements. `$SKILL` is the actual path returned by the installer; use the Python command prefix returned by setup.

| Need | Entry | Check before using the result |
|---|---|---|
| Inspect or compare GLB resources | `scripts/asset_metrics.py inspect` / `compare`; [asset inspection](../skills/greybox-to-multistyle-art/references/asset-optimization.md#measure-the-supplied-glb-locally) | Measures topology, definitions/instances and encoded image bytes. Compressed/sparse/external geometry has explicit limits; this does not measure draw calls, GPU memory or FPS. |
| Reduce or repair a necessary asset | [Processing routes](../skills/greybox-to-multistyle-art/references/asset-optimization.md#choose-an-existing-processing-route) for Lux/Meshy/Tripo remesh or a suitable native DCC operation | No local decimator is bundled. Preserve the source, compare silhouette/materials and recheck the actual native scene. Fewer triangles alone do not prove a useful optimization. |
| Inspect a character and choose rig/motion work | `scripts/character_check.py inspect`; [character route](../skills/greybox-to-multistyle-art/references/character-pipeline.md) | Structural inspection does not judge anatomy or deformation. Check the actual model, provider restrictions, first motion and contact in the required endpoint. |
| Assemble, capture or inspect native output | `scripts/greybox.py engine`; [engine methods](../skills/greybox-to-multistyle-art/references/engine-adapters.md) and [effects](../skills/greybox-to-multistyle-art/references/scene-effects.md) | Use the selected engine's plan/config and task-owned output. A successful command or screenshot is not complete gameplay, art or performance acceptance. |
| Recover a task or missing download | `scripts/progress.py focus`, `scripts/greybox.py task-context inspect`, or [original-artifact recovery](../skills/greybox-to-multistyle-art/references/suppliers.md#restore-a-completed-local-artifact) | Follow the actual ledger type and original job/account identity. Do not create a replacement generation to repair a download. |

For a local asset inspection, for example:

```sh
python3 "$SKILL/scripts/asset_metrics.py" inspect --input "$SOURCE_GLB" --output "$CASE/metrics/source.json"
```

Use a new report path. The input remains unchanged. Read the linked method before processing; it names the supported inputs, output handling, recovery and native checks.

## Suppliers, images and cost

- Concepts/references can use a suitable native image tool or a configured [image service](../skills/greybox-to-multistyle-art/references/image-services.md). Generation, seeing pixels and displaying results are verified separately.
- Bundled supplier implementations cover Lux and dedicated Meshy, Tripo, Rodin and Hi3D routes, plus reviewed custom command adapters. Dedicated API contracts have offline tests; account readiness, each operation's useful output and native integration need separate evidence. [Supplier routes](../skills/greybox-to-multistyle-art/references/suppliers.md)
- New Lux generations default to **G1 standard**, explicitly `version: "G1"`, with no Turbo-only `enablePbr`. Use G1-Turbo only when explicitly requested for the current task. Existing Turbo assets keep their provenance and may be reused. Remesh, material transfer, rigging and motion retain their separate operation/version contracts.
- Configure only the chosen operation. The concrete production plan names references, supplier/model/version, parameters, postprocessing and the cost basis before paid work. Setup and account balance do not authorize production. Quotes, estimates and actual charges remain distinct; unknown charges stay unknown.

[Installation and account setup](INSTALL.md) · [Support](SUPPORT.md) · [Near-term roadmap](ROADMAP.md)
