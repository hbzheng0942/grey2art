# Character production: inspect the actual body before choosing a rig

Read for a `humanoid`/`animal` asset or unresolved character need. This is conditional work: a static sculpture needs neither a neutral animation pose nor a skeleton. A moving rigid toy may use pivots; skeletal motion requires a useful rig and weights. Keep independent environment work moving while a character route is unresolved.

## Reference → actual GLB → route

1. **Reference.** Apply the character row in [modeling references](modeling-references.md): skeletal humanoid = one explicit **A or T** pose; animal = an anatomy-appropriate **natural stance**. Keep pose separate from camera/view. Open the actual image and check limb separation, readable joints, support and identity. A white background or a `pose` string is not visual evidence.
2. **Actual GLB.** Bind the exact file SHA; inspect both its structural report and rendered front/side/back or other useful actual views. Reference-image approval does not transfer to the generated mesh. Read the true mesh/skeleton/animation inventory and bounds; check limb/torso fusion, hidden intersections, disconnected pieces, clothing/accessory obstruction, orientation, support and body pose. Existing skins require checking joint references/weights and rest versus displayed pose. A `skins` entry alone is not a usable rig. Invisible features remain `unclear`.
3. **Route by that result.** Use the table below; record the actual input hash, provider/operation and its restrictions. URL suffix, supplier name, schema validity and prior success on another character do not establish compatibility. Do not remesh, rebind or regenerate a usable model automatically.
4. **First useful rig and motion.** Inspect the returned rig, then run one representative authorized action in the target engine. Capture continuous start → action → return, not only one pleasing frame. Check shoulders/hips/elbows/knees, collapsing or detached clothing, foot/contact sliding, proportions, clipping, root motion and camera occlusion. Use `pass`/`fail`/`unclear` with actual visible observations, rig/source hashes, action and capture interval in the existing asset/native ledger. Fix the specific weight, contact, transition or pose defect before multiplying compatible assets/styles; no new human checkpoint beyond H3/H4.

| Observed source and needed behavior | Production route |
|---|---|
| Static or rigid motion only | Preserve mesh; assign scale, collision and explicit pivots/sockets. No automatic skeletal rig. |
| Existing rig with compatible deformation and motion | Reuse after actual playback/contact checks. “Humanoid” alone does not prove skeleton compatibility. |
| Unrigged humanoid with clear suitable body/pose | Qualified humanoid bind service, using the inspected bytes; inspect the returned weights and first motion. Lux accepts `modelUrl`, not an invented pose-correction flag. |
| Animal/non-human anatomy | Choose an operation documenting that rig type and required motion. Tripo exposes multiple types; Lux's humanoid route does not establish quadruped support. An unsupported motion needs a separate concrete route. |
| Fused limbs, obstructed joints, unusable skin, or uncertain pose | Stop that dependent bind. Inspect another useful view or plan scoped pose/mesh/weight repair using an actually available tool. Do not pay for repeated blind binds or discard usable material/geometry without diagnosis. |

New managed Tripo rig submissions require a source-bound `rig_check`: `rig_check_from` must name its ready dependency, and the adapter checks source/report hash and rig type. Historical submitted tasks still recover without new admission. This is a Tripo service check, not a universal Lux prerequisite. Lux's published contract has no separate rig-check endpoint; local structural/visual admission cannot promise cloud acceptance. Current provider behavior and actual errors outrank assumptions.

If the same alleged GLB fails API but works on web, compare original/submitted bytes, transforms/pose actually displayed, request parameters, region and task/error records. Keep the successful web result and existing failed task IDs. Do not assert that web preprocessing, a hidden parameter or the pose caused the difference without evidence, and do not repeat paid calls to speculate.

For the first walk, inspect both feet passing and both widest-stride phases, then continuous playback. A clean rest pose and normalized weights can still hide wrong bone assignments: a hand vertex weighted to a thigh only spikes when the limbs separate. Compare deformed versus rest edges and inspect the offending vertices' influences; repair that region before replacing the whole rig. Preserve wrist motion and intended finger articulation. Simplified rigid fingers are appropriate only when the design/use permits them. Check support-foot height and sliding across the loop; a global floor offset cannot repair changing contact errors. Keep original provider output, a reproducible scoped repair and the reviewed final hash. For asset-only delivery, actual DCC/browser playback verifies the clip; target-engine integration remains a separate check when requested.

## Record and validate the actual input

From this skill directory, use new output paths; inspection does not rewrite the model:

```sh
python3 scripts/character_check.py inspect --file model.glb --output inspection.json
python3 scripts/character_check.py template --inspection inspection.json --output preflight.json
# Render/open the actual GLB views, fill observations and their file hashes, then:
python3 scripts/character_check.py validate --receipt preflight.json --provider lux3d
```

`inspect` reads GLB structure, declared local bounds, transforms, skins/joint/weight inventory and resources. It neither renders views nor decides pose, world dimensions, anatomy or useful deformation. The template starts `unclear`: supply actual front, side, back and three-quarter captures; describe visible evidence for single character, limb separation and accessory obstruction. Record the observed pose honestly, even if it differs from the requested A/T. The receipt's `category` (`humanoid`/`quadruped`/`other`) and `use` (`static`/`reuse-rig`/`rig`) classify this **actual GLB and execution route**; they are not the modeling-reference design enums. Static/reuse routes do not demand a new bind or A/T. A successful validator checks evidence integrity and the recorded review, not whether anyone really inspected the pixels.

Before a **new** managed bind, save the completed receipt at `<run-dir>/character-preflight/<operation-id>.json`, or use the operation's `character_preflight: {path, sha256}` record. Bind `submission_binding.source_sha256` to the inspected file and `parameters_sha256` to `core.digest` of the exact frozen operation parameters (stable JSON encoding, not a text-file hash). The selected local/dependency model must be that file. An HTTPS source additionally needs a hash-bound `submission_binding.source_receipt` pointing to the actual upload/download record: `kind: model-source-binding`, `method: upload|download`, `source.sha256` and exact `provider_source` URL. Obtain that binding from the real transfer; naming a URL after a local file proves nothing. Missing/unclear/changed evidence blocks new submission before spend; existing task status/fetch stays recoverable. This is an automated precondition within H3, not another human approval or a promise of cloud acceptance.

## Declare only the necessary chain

`character_graph(needs, native_engine="godot")` derives work from these declarations:

| Field | Values / evidence |
|---|---|
| `presence` | required / none / uncertain |
| `source` | new / reuse / none / uncertain; reuse needs `asset_ref` |
| `deformation` | required / none / uncertain |
| `rig` | new / existing / none / uncertain; existing refers to a reused character |
| `animation` | new / reuse / none / uncertain; reuse needs `motion_ref` |
| `retarget` | required / none / uncertain |
| `mesh_processing` | none / repair / remesh / uncertain; optional, default inspect without planned editing |

Repair/remesh needs `mesh_processing_reason` (actual defect, deformation or measured budget need). New models always derive inspection and dimension/anchor work. Necessary rigs derive deformation checks; necessary motion derives contact review/correction, export and native behavior validation. Rigid/static characters set deformation/rig/retarget to `none`. Reused motion needs retargeting unless `skeleton_compatible_verified: true` is backed by `compatibility_evidence`. Unknown needs block dependent character work; `presence: none` derives an empty graph. This overview is a plan, not another authorization gate or a claim that checks ran.

`validate_overview` regenerates the graph and rejects omitted necessary work. Bind its tool operations before dependent production. Topology/skeleton changes invalidate affected weights, sockets, contacts and fit checks; preserve/bake textures and compare materials before new binding. Do not repeatedly remesh a bound asset while retaining its old approval.

## Bind implementation and retain evidence

`validate_production_scope(brief, portfolio, base=project)` binds `portfolio.overview` to the exact brief/SHA and `character_assets` to scoped families. Every option's `character_work` covers each derived `asset_id`/`node_id`/`capabilities` using:

- `supplier`: same asset's costed `operation_id` implements the needed function.
- `local`: an exact discovered channel supporting the function, with hash-bound channel evidence.
- `manual`: named `handoff.owner`, `action`, `resume_requirement`.
- `reuse`: hash-bound existing qualification evidence.

New `character_policy: needs-driven-v2` requires `route_reason` for necessary mesh edit, rig, motion generation and retarget. Local/manual routes also explain `supplier_evaluation`; suitable installed services should be considered before custom code. This checks plan coverage, not source anatomy or completed inspection. The supplier ledger executes supplier jobs only: the integrator must schedule and retain actual local/manual outputs before dependent work. Reuse qualified results without repeating paid probes. Cost the whole needed chain inside the selected H3 option; revise H3 only for a material supplier/spend/quality-scope change.

**Blender availability is not a rigging executor.** The bundled static backend refuses armatures/shape keys and does not implement auto-rigging, pose correction, weight transfer or animation cleanup. Bind a discovered suitable implementation and a representative result, or a resumable manual route. Mixamo can be human-assisted; no assumed public API. A provider's “Mixamo-compatible” skeleton is not an Adobe invocation. Meshy/Tripo structural GLB checks and Lux task success do not establish useful weights or native playability; Rodin/Hi3D are not undeclared rig/motion services. Read the selected [Lux](lux-bridge.md) or [Meshy/Tripo](provider-meshy-tripo.md) contract only for that route.

For project-specific interactions, bind one concrete native task: existing gameplay states, actor/rig or rigid hierarchy, sockets, attachment ownership, contact/visibility criteria, real engine/DCC channel, owner and continuous capture interval. Reuse the state machine. Complete one pick-up → place → use → return loop before replication. Preset clips supply base motion, not grasp anchors, IK or gameplay timing. Thin/open tools additionally need visible thickness/backfaces, holes/normals and collisions at gameplay distance; do not assume the static Blender backend implements missing solidify/boolean repair.

An environment-only batch may declare `character_deferral: {scope: "excluded_from_this_batch", reason: "..."}` with no character assets. Report the outstanding character nodes; partial progress does not authorize full-scope H5. Preserve historical graphs and approval hashes for recovery; inspection findings become new evidence, not edits to old decisions.
