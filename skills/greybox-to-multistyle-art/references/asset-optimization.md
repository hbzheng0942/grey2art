# Inspect, process and recheck assets

Use this when a supplied/generated asset may exceed the actual scene budget or
when a required topology operation needs a measured before/after comparison.
Inspect the source first. A usable asset that meets its current requirements
does not need remeshing, rigging or replacement.

## Measure the supplied GLB locally

The standard-library helper is read-only and makes no provider calls:

```sh
python3 "$SKILL/scripts/asset_metrics.py" inspect --input "$SOURCE_GLB" --output "$CASE/metrics/source.json"
python3 "$SKILL/scripts/asset_metrics.py" compare --before "$SOURCE_GLB" --after "$PROCESSED_GLB" --output "$CASE/metrics/comparison.json"
```

Each output must be a new path. Existing reports and inputs are never replaced.
Reports identify a source by filename, SHA-256 and bytes; they omit absolute local
paths. Keep the canonical source/resource manifest in the owning case to resolve
that identity. Review filenames and reports before public sharing.

The report measures:

- Mesh, primitive, material, texture and image definition counts.
- Triangle topology summed once per mesh definition, including unused meshes.
- Mesh-node instances and assembled triangle topology in the explicitly declared
  default scene. A missing default selection is `unknown`, not an inferred first
  scene or a zero count.
- Embedded encoded image payload bytes. Overlapping image buffer ranges count
  once; each base64 image declaration contributes its decoded payload length.
  These are compressed image-file bytes, not decoded pixel or GPU allocations.

Indexed topology validates the stored accessor range and actual unsigned index
values against POSITION count. Nonindexed triangles, triangle strips/fans and
point/line primitives use their declared topology after storage validation.
Degenerate triangles remain topology entries; no surface-area test is performed.
BIN chunks remain on disk and indices are decoded in bounded chunks.

Supported input is self-contained, uncompressed GLB 2 with stored dense accessors.
Draco, meshopt, sparse accessors, GPU instancing and external/data-URI geometry
buffers are rejected. External images need a separate resource audit. Unsupported
measurements must not become a zero-value budget pass. The helper reuses the
existing [character inspection](character-pipeline.md) container/structural checks;
its report is not an anatomy, deformation or material-quality review.

Accessor min/max values are declarations. This helper does not measure world
dimensions, camera visibility, frame time, draw calls, GPU memory or target-device
performance. Its visual, runtime-performance and processing-qualification states
remain `unverified`, including when a comparison shows fewer triangles or bytes.

## Choose an existing processing route

The shipped topology-processing routes are remote supplier operations:

- **Lux:** the pinned `remesh` / `mesh.remesh` operation accepts its documented
  static non-Draco GLB scope. Prepare the actual HTTPS model input and quote the
  exact operation/parameters. Explicitly choose texture baking and texture size
  when preserving textured appearance. Source generation and processing are
  separate task identities; see [Lux processing](lux-bridge.md).
- **Meshy / Tripo:** dedicated remesh adapters have provider-specific input,
  topology/version and baking restrictions. Follow the [provider method](provider-meshy-tripo.md)
  and qualify the required output path in the target engine before expanding.

There is no bundled local decimator. The static Blender backend provides its
documented bounded geometry operations; bake/scatter/render jobs do not become a
general retopology pipeline. A suitable host-native DCC operation may be selected
and tested for an actual project, with its own source, settings and output evidence.
Do not advertise that as an already qualified packaged optimization route.

Use an existing model already suitable for the scene when possible. For necessary
processing, bind the exact source hash, intended use, face/topology target, texture
handling, output format, route restrictions, cost and fallback in the existing H3
scope. The metrics helper grants no production or spending authorization.

Honor the task's effective model policy for new mesh generation. In a G1-restricted
task, keep `version: "G1"` explicit and omit `enablePbr`; do not select Turbo as a
silent performance workaround. A remesh operation uses its own actual processing
schema, not a mesh-generation version field. Preserve historical Turbo assets and
their provenance; processing does not turn them into G1-generated meshes.

## Complete one representative processing path

1. Measure the canonical source and record the actual scene/device budget. Keep
   target settings separate from observed values in the [shared runtime profile](production-control.md).
2. Process only the necessary representative asset through the authorized route.
   Preserve source and original provider IDs. A timeout or unknown submission is
   recovered as the original task, not replaced by another generation.
3. Measure the result and compare the same asset's recognition features, silhouette,
   surfaces, texture detail, UVs, normals and materials in actual views. Numeric
   reductions alone do not qualify it. Compare relevant deformation/contact states
   for an asset whose task requires them.
4. Import the selected output into the target engine. Recheck affected dimensions,
   anchors, materials, weights, sockets, contacts and collision when processing
   changed their inputs. Reuse unchanged valid evidence.
5. Observe the representative native scene on the actual target with the same
   camera, resolution and workload. Record measured frame time, draw calls,
   loading/memory observations and test scope where the engine provides them.
   A DCC or file report cannot substitute for that native observation.
6. Qualify the processing family only with its required actual checks and media,
   then expand through [production control](production-control.md). Retain failed
   attempts, choose an authorized fallback at the repair cap and continue unrelated
   ready work.

Keep one immutable source and changed processed versions; do not copy the complete
project for each comparison. A file-size reduction is not evidence of disk savings
after extra intermediate outputs, nor proof that the scene will run faster.

Multiple ready operations use the [common executor](execution-contract.md) and
their original authorization/fee ledgers. Shared account capacity does not create
a case-wide aggregate spending cap. Native image preparation remains agent-driven
unless an actual independent host bridge is qualified; asset metrics do not change
that execution channel.
