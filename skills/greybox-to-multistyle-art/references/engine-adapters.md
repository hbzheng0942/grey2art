# Input, geometry and runtime adapters

The bundled runtime execution core dispatches production, sample identity and H5 dependencies to Godot or Unity. Blender can be the authoring carrier and spatial delivery/review endpoint through its native route. Choose authoring carrier, review renderer and runtime separately; a spatial Blender request needs no future game project. Read [Unity runtime](unity-runtime.md) for its concrete Editor/PlayMode bridge. Documentation, installed programs and GLB support do not establish a tested adapter.

## Separate four responsibilities

| Responsibility | Contract |
|---|---|
| Input adapter | Read the native project/space, identities, coordinate/unit conventions, logical owners/states, cameras, protected relationships and dependency manifest |
| Authoring / geometry backend | Produce an editable native space or owned geometry/material/export outputs; Blender can author the scene as well as prepare individual assets |
| Asset supplier | Generate/process approved asset families with its own model/operation/quote/task semantics |
| Runtime/output adapter | Assemble an incremental native art layer, retain gameplay, calibrate target rendering and provide native evidence |

The shared authority remains GameplaySpatialContract → ArtSpatialDesign → AssemblyRecipe, with stable IDs and actual human decisions. Do not turn each new engine into a separate art workflow. Native gameplay, renderer and validation differ and must stay in their adapters.

## Input and output promises

- An existing Godot/Unity/web game should receive an incremental native art layer plus required resources/manifests, preserving its playable baseline and existing version.
- A `.blend`, GLB or FBX space alone is `spatial_only`. This is a valid spatial analysis, authoring or art delivery route. It cannot prove controls, state changes, collisions or playability without a game host and measured baseline.
- Keep editable `.blend` as source where used. Exchange explicit GLB/glTF or appropriate FBX plus a sidecar contract, rather than assuming round-trip losslessness.
- The sidecar carries stable source/instance IDs, units/axes/front, anchors/interfaces, material intent, dependency hashes, collision ownership, optional rig/animation conventions and runtime bindings. Node names alone are not unique identities; use stable metadata and an explicit mapping.

GLB does not carry arbitrary game scripts, shader graphs, gameplay semantics or editor behavior. Inspect imported scripts, cameras, lights and collision ownership before art-only integration. Native material calibration and gameplay probes are required after export/import.

## Blender scene and asset authoring

Use Blender for editable spaces and greyboxes, modeling/Geometry Nodes, mesh/UV editing, materials, lighting, offline review, baking and export when those operations suit the requested endpoint. Pure spatial work can finish with the `.blend` and the necessary views/dependencies. For later playable integration, gameplay authority still comes from the host contract; keep runtime collision/clearance and interactions observable in that engine.

Operate through task-owned `bpy` scripts, the installed Blender CLI or an available Blender MCP; no new wrapper is required for ordinary native authoring. Prefer deterministic batch Python/CLI for repeatable owned jobs. A live MCP can affect the user's open scene, so bind its session and owned objects/collections before writing. Read-only inspection/render/export does not save the source; an authorized revision changes only the owned scene/content and records the changed source. Record Blender version, export settings and actual output; a successful file save is not target-runtime acceptance.

Use the [native authoring method](greybox-authoring.md) for the spatial route. Choose each operation by the required editability, interaction, visual goal and cost. Engine tools provide native gameplay and runtime lighting/performance feedback; Blender can remain the endpoint when those are not requested. Do not export the entire game or duplicate large assets on each iteration.

## Unity adapter and project setup

For a new test project, start with **Unity 6.3 LTS latest available patch, Universal 3D/URP**; lock the actual editor, render pipeline and package versions after setup. Existing projects retain their chosen versions/pipelines. Install through Unity Hub with only needed build modules. Official references: [6.x support](https://unity.com/releases/unity-6/support), [URP project template](https://docs.unity3d.com/6000.3/Documentation/Manual/urp/creating-a-new-project-with-urp.html).

The native adapter binds stable GameObject/prefab identities, art-layer ownership, colliders/nav/animation separation, material conversion for the chosen pipeline, cameras/exposure, native capture, gameplay probes and performance budgets. ProBuilder is an available in-editor geometry option, not a required Blender replacement. `.blend` import depends on Blender/FBX conversion; prefer explicit exports/settings for reproducible team handoff. The implemented Editor/PlayMode bridge and its limitations are detailed in [Unity runtime](unity-runtime.md); installing glTFast alone does not establish native invocation evidence.

## Three.js first adapter target

Choose one pinned game host with renderer/color management, GLTFLoader, animation mixer, input/camera, physics, resource loading and test hooks. Define native/browser captures and state probes there. Three.js is a rendering/runtime library; loading GLB and displaying a scene does not establish a playable baseline or preserve gameplay.

Keep browser mesh/texture/download budgets explicit and validate compression/animation paths in the actual browser. A browser-host adapter is separate from the generic supplier/geometry backend and from the Godot H5 implementation.

## Adapter evidence and validation

For each adapter report documented → installed → connection/local invocation → useful round trip → target-native acceptance, with exact versions and evidence. Before claiming a new runtime supported, test a real source greybox, import/render calibration, identities/scale/interfaces, representative states, two selected styles, actual H1–H5 and interruption recovery. Where a branch remains unimplemented or untested, show it in the overview/preflight instead of substituting the Godot fixture as proof.

Qualify Blender spatial operations against their declared files, scene/camera/collection, native views and source/dependency behavior. Selecting a future game runtime does not require its completed receipt before authoring or export can begin. Keep that future runtime unverified until it has its own evidence; Blender review does not supply it.

R3.1 implements the limited static Blender backend and native Godot GLB admission;
see [Blender backend](blender-backend.md). Real MCP and background CLI diagnostics
passed, including preservation of the open scene. This does not implement every
Blender geometry operator or certify character/terrain/complex material production.
Unity now has actual macOS native invocation and GLB round-trip evidence; Windows and human art acceptance remain separately pending.

## R3.3 organization adapters

Shared case/style/asset ownership now maps separately to logical, code and resource roots. Godot, Unity, Three.js and Blender each have a concrete `workspace audit` dependency inspector; Unity uses GUID/.meta resolution, Three.js source/loader resources, Blender read-only external-file inspection. See [project layout](project-layout.md). These format adapters do not claim an unimplemented native gameplay compiler. Godot and Unity native execution are tested by their own operation receipts; browser and DCC results remain separately reported.
