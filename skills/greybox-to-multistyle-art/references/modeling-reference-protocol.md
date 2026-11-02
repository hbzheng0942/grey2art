# Modeling-reference protocol: read only the needed operation

Start with the [method card](modeling-references.md). This page packages designed references; byte/provenance checks do not decide visual quality.

## Production boards and crops

### Production entry and bound scope

New S7 production enters through the [single asset registry](board-registry.md):
`greybox.py boards start`, or `boards workbuddy start` for WorkBuddy's scoped native
entry. The compiler derives the [production request](../schemas/reference-board-production-template.json).
Bind an independent scope source with an explicit `asset_views` list and its
SHA256; the production request's `scope.source` refers to that file and
`scope.asset_views` declares the current exact scope. The source, scope, page
plan and object descriptions must agree. A source reference records where a
decision came from; it does not create user approval or authorize a paid call.

For a new task, use `boards start` / `boards workbuddy start` above and consume
the returned jobs. The lower-level block below is for recovery or diagnosis of
an existing compiled production request; it is not a second normal entry and
does not require reconstructing the registry's scope or asset list.

```sh
python3 "$SKILL/scripts/greybox.py" boards production prepare --file "$PRODUCTION_INPUT" --project "$PROJECT" --workspace "$WORKSPACE"
python3 "$SKILL/scripts/greybox.py" boards production status --workspace "$WORKSPACE"
```

The workspace stores shared immutable scope/input identities and per-page state.
Follow its returned next action. A native binding maps each complete request;
claim a ready page once, invoke the unchanged dispatch under the existing task
authority, and record the real arguments/result and original call reference.
Pending or unknown outcomes retain their original identity. Local recording can
resume the same completed call; it does not submit another generation.

Production crops inherit the frozen asset/view identities and pixel requirements.
`boards production crop` accepts a nonempty subset of observed slots, processes
them independently and preserves content-addressed requests/outcomes. A corrected
ROI creates another attempt and current crop pointer; it does not repeat generation.
Inspection crops retain original pixels even when subject/detail or white-boundary
checks fail. `crop_available` means inspectable output, while `crop_technical_pass`
requires every frozen slot to pass. Strict crop validation and modeling references
reject technical failures. Re-cropping invalidates only affected current visual
observations; a previous cross-view review becomes stale and must be compared again.
Provide actual observed ROIs, then open each returned crop and record a specific
view observation and its pixel-reading source. A technical crop pass alone is
not visual acceptance. Status names missing views and failed/unclear views;
retain passing siblings when repairing a failed item. Changed scope, inputs or
requirements need a new explicit bound request rather than silently altering a
claimed workspace. Old low-level board commands retain their historical use.

Use `boards production bind-session --workspace "$WORKSPACE" --session-id
"$ACTUAL_SESSION_ID"` after a host-session change. Operational context/history
changes; scope, page requests and old claims do not. Old pending calls can still
be recorded from their original results, but are not new invocations in the
new session. A registered WorkBuddy guard also needs its explicit session
handoff described in the [guard guide](../connectors/workbuddy/board-guard/README.md).

An accepted asset source view can condition other views with an image role:

```json
{"role":"identity_master","asset_id":"dog","source_view_id":"rear_three_quarter","target_view_ids":["left_profile","front"],"source_review":{"path":"art/dog-source-review.json","sha256":"ACTUAL_REVIEW_SHA256"}}
```

The associated input image is sent to every named target. The source view need
not be in the current plan. Its review binds `image_sha256`, `asset_id`, the
actual source `view_id`, a passing `status` or `verdict`, a concrete `observation`
and `source_ref`. Production requires that passing review; a failed or stale
source cannot become a usable identity master by changing its role. This checks
recorded evidence, not the truth of an aesthetic judgment. Across-page views
without a qualified identity source stay blocked; first establish the source
design, then bind the dependent views. Same-page joint design still needs an
explicit comparison of construction, proportions and unchanged pose.

Final `boards production review --workspace "$WORKSPACE" --page "$PAGE_ID"
--file "$REVIEW_INPUT"` accepts per-crop `reviews` and, for a multiview asset,
`cross_view_reviews`. Each cross-view item binds `asset_id`, passing or failing
`verdict`, `observation`, inspection `source_ref` and the complete current set
`images:[{view_id,image:{path,sha256}}]`. Status supplies the owner page and exact
required images; use those paths rather than reconstructing filenames. Missing,
failed or unclear comparisons prevent completion even if every individual
view was marked pass. Recorded comparisons remain visual judgments, not a
proof of a consistent reconstructed mesh.

Projection can be supplied as
`projected_dimensions:{width,height,source_ref}`. Width divided by height defines
the aspect; a conflicting explicit `projected_aspect` is rejected. Pixel and
feature requirements keep their task basis. Ordinary two-view pages can use
horizontal or vertical two-up layouts when both views meet those requirements;
no grid size establishes generated quality.

Production boards allocate native pixels to isolated objects/views. The display BOM locally arranges accepted crops with IDs/assembly links; it needs no image-generation invocation. Each modeling master contains exactly its intended object/view, without neighboring objects or presentation labels.

Before individual generation calls, use [prepare input](../schemas/reference-board-prepare-template.json). Its `plan` follows the [board plan](../schemas/reference-board-plan-template.json): declare actual supported/observed channel size and source, projected shape, minimum subject long/short-edge pixels and any critical feature fraction/pixel minimum. These are task requirements, not universal quality thresholds. `purpose` is `modeling` (default) or `exploration`; it never changes declared requirements. Prioritize current-sample assets; do not wait for future assets to fill a board.

The planner selects single, 2×2 grid (3×3 only after simple-shape qualification), 2–4 horizontal strips or 2–4 vertical columns, with 10% per-side margin. Match long/thin shapes to strips/columns; complex openings or fragile details may need a single. Review candidate dimensions, fallback reasons and call counts before dispatch. `unresolved` means even a full canvas fails the declared pixel estimate: use a genuinely supported larger native size, useful supported views for hidden structure, or an approved modular design. Continue independent ready pages. Do not cut a unique design merely to pack it. Upscaling/padding does not add subject detail.

`images` binds the actual approved input files/hashes. Optional `image_roles` labels each as `style` or `design_master`; a design master binds its `asset_id` and `view_id`. Each page receives every style image and the exact masters for its own asset/views, including deduplicated aliases. A scene concept supplies style/design context but does not establish that an existing exact master was submitted. `objects` contains one record per planned `asset_id + view_id`, with matching `role`, `category`, `function`, `appearance`, `structure` and animal `species`. Carry `modeling_contract`, pose and interfaces into this record. Name differences that prevent similar objects being confused; never extract descriptions with sentence regexes that truncate dimensions.

An optional explicit `model_source` on the plan row and object can share a slot only when the view and all design/quality declarations agree. Different geometry, material or pose declarations remain separate even with the same family name. Retain the returned alias mapping; each original placement/asset still resolves to its intended model/view.

`capabilities` declares `edit:true`, the selected channel's `max_references` and actual capability `source_ref`. Preparation retains the declared order of each page's approved inputs, then puts the generated layout guide last. It splits pages deterministically when their required references exceed that limit; an individual view that still cannot fit is unresolved, while independent ready pages continue. Never discard a required style/master input to fit the limit. Choose explicit `layout_guide:false` for textual layout when that route is useful, or use a compatible user-selected service. Unsupported size/parameter or multi-image support is resolved before submission; a tool schema's examples are not an exhaustive supported-size list.

Inspect the first already-authorized board's actual size/subjects before extending that layout; requested size is not observed output. These local commands neither generate images nor segment objects automatically:

```sh
python3 "$SKILL/scripts/greybox.py" boards plan --file "$PLAN_INPUT" --project "$PROJECT" --output "$LAYOUT"
python3 "$SKILL/scripts/greybox.py" boards prepare --file "$BOARD_SPEC" --project "$PROJECT" --output-dir "$PREPARED"
```

Each ready page has one complete prompt, guide and standard `operation:edit` request, with input/output hashes and slots. Outputs are immutable; an identical rerun reuses them. The original single/board plan and crop commands remain available through `scripts/reference_boards.py`.

### Execute the same page across hosts

For a configured image profile, validate and submit the prepared page request directly using [image services](image-services.md#submit-and-recover). For a native Codex, WorkBuddy or Claude Code tool, map that request to the **current actual tool schema**:

```sh
python3 "$SKILL/scripts/greybox.py" boards native --file "$PAGE_REQUEST" --binding "$NATIVE_BINDING" --project "$PROJECT" --output "$DISPATCH"
```

The [native binding example](../schemas/reference-board-native-binding-template.json) illustrates a WorkBuddy wrapper; replace its tool/schema evidence with the current session's binding. A binding has `schema:1`, `kind:reference-board-native-binding`, `host` (`codex`, `workbuddy` or `claude-code`), exact `tool` and current `source_ref`. Select `input_transport:local_paths`, `https_urls` or `mixed`; map `prompt_argument` (default `prompt`) and either the array-valued `image_argument` or ordered named `image_arguments`. Declare `max_references`; `parameter_arguments` maps standard parameter names to actual tool argument names, with optional `fixed_arguments`. A wrapper can additionally use `arguments_container` and `envelope_arguments` (for example `params` and `{"toolName":"ImageGen"}`).

URL transport binds actual host-upload results in `uploads:[{path,sha256,url,source_ref}]`; `mixed` uses these only for uploaded inputs and retains local paths for the others. Local-path support needs no upload. Keep signed upload results private. Do not invent URLs or assume one host's argument names work in another. Pass only parameters the current tool actually accepts: if a Codex native tool has no size/quality arguments, use empty request `parameters` and keep `channel_size` as the observed planning estimate.

`native` validates local input hashes and writes a dispatch containing the exact tool arguments; it invokes no tool. Execute those arguments through the bound native tool once under the existing task authority, save the **actual arguments**, then record the result:

```sh
python3 "$SKILL/scripts/greybox.py" boards record-native --file "$DISPATCH" --arguments "$ACTUAL_ARGUMENTS" --image "$RETURNED_BOARD" --source-ref "$REAL_CALL_SOURCE" --job-dir "$BOARD_JOB" --project "$PROJECT"
```

Recording verifies arguments against dispatch, rechecks input bytes and records the actual returned local output through the shared image-job receipt. Native tools may return that file outside the project; recording does not require moving it first. Keep `BOARD_JOB` in the owning project so its receipt can be reused by crops. It cannot manufacture invocation evidence. Both routes keep one receipt per actual board call. Preserve an uncertain submission and reconcile its original task before any repeat; a timeout never authorizes a new call. Native-host argument tests establish mapping correctness, not live provider reliability or art quality.

### Inspect and crop

Open the returned board and locate each intended object/view. Identify objects semantically before applying any whitespace/segmentation aid; a planned cell, connected component or fixed grid is not an authoritative crop. Verify identity, construction, style, pose and requested details separately from white-border/pixel checks.

Cropping requires a project-contained board and receipt. Reuse an identical project-local canonical board when present; otherwise import the returned board once into the project's content-addressed asset store and verify the unchanged SHA256 against the shared receipt. Every crop references that same immutable board and receipt. Do not copy the board per crop or duplicate the project to accommodate an external native-tool output.

```sh
python3 "$SKILL/scripts/greybox.py" boards crop --file "$CROP_REQUEST" --project "$PROJECT"
python3 "$SKILL/scripts/greybox.py" boards validate --file "$CROP_RECEIPT" --project "$PROJECT"
```

Record **one** `reference-image-generation-receipt` per real board invocation, binding approved style-image inputs, actual board bytes and invocation source. Fill [crop request](../schemas/reference-board-crop-template.json) per asset/view:

- `roi:[left,top,right,bottom]` uses the **EXIF-oriented returned image**, with exclusive right/bottom. Select the actual object plus existing white margin, not the planned cell blindly. `padding` adds white canvas only.
- The cropper rejects out-of-bounds, undecodable/truncated, blank, boundary-touching nonwhite content, unmet declared subject pixels and overwriting different existing output. It never silently clips/resizes/deletes pale object pixels. Its threshold bbox is conservative; white foreground and semantic completeness still need pixel inspection.
- It emits PNG plus `reference-board-crop-receipt`: original/EXIF-oriented dimensions, source board/shared invocation, asset/view/role, ROI/padding, output bytes and decoded pixel hash. Validation replays that crop and compares pixels. Changed boards invalidate dependent crop provenance.
- Keep canonical boards immutable. Repair an ROI with a new crop version, regenerate only genuinely defective objects/small boards within authority, and retain good siblings. Identical reruns do not rewrite; one request handles one view.

Bind returned fields in the package:

```json
{"id":"front","role":"front","origin":"board_crop",
 "image":{"path":"assets/gate-front-v1.png","sha256":"ACTUAL_CROP_SHA256"},
 "board_crop_receipt":{"path":"assets/gate-front-v1.crop.json","sha256":"ACTUAL_RECEIPT_SHA256"}}
```

That crop is the white master when its declared modeling requirements and per-view visual review pass; no extra single-image generation is required. An exploration crop does not become a qualified master merely because it decodes or has a 256px padded canvas. Optional provider derivatives retain `master`/`derivation`; the board receipt's output remains the board, never a fictitious crop invocation. Existing `host_generated` singles and `user_provided` references remain valid. Current H3 binds exact reviewed complete-sample references; future delegated-reference acceptance is not implemented.

Planning uses Python stdlib; guide preparation and crop/replay need optional Pillow in the chosen environment. Missing dependencies fail explicitly. Paths are project-contained. Board limits: 32 million pixels / 64 MiB. Master limits: 8,388,608 pixels and minimum 256px per canvas axis. Preserve sources/hashes without copying asset/project trees.

## Supplier view mapping and optional processing

Store separate same-object view files with stable IDs and truthful roles: `front`, `back`, `left`, `right`, `three_quarter`, `top`, `bottom`. Never upload a contact sheet as one object. Reject unsupported orientations instead of relabeling them. Map the exact H3-bound endpoint/model:

| Channel | Adapter boundary |
|---|---|
| Lux pinned adapter | Actual inspected `img`/`imgs` support via local upload; explicit version/parameters |
| Meshy | Multi-image supports 1–4; this skill's multiview requires at least 2. Main image first where required |
| Tripo current v3 | Named front/left/back/right; front plus another view. Match reviewed roles/order; positional compatibility is not a separate reference mode |
| Hi3D/Hitem3D | Up to 4; explicitly map `[front,back,left,right]`/bitmap, not Tripo order |
| Rodin | Up to 5; applicable `concat` reconstructs one object. `fuse` combines features and cannot silently substitute |
| Custom | Reviewed actual model capability, count/orientation and mapping; unsupported mode blocks that asset, never falls back to text |

Offline payload checks do not establish useful cloud reconstruction. Preserve a correct neutral master first. Background removal, masking or de-lighting responds to a real defect; IC-Light/Hunyuan implementations are optional references, not installed services or proof of albedo recovery. Do not install services/weights or switch channel just because they are named here.

For supported Meshy models explicitly propose `image_enhancement:false` to preserve approved appearance. The dated single-image docs below describe `remove_lighting` as effective on Meshy6, accepted but ignored on 7.1/latest, unsupported on 6-lite/SmartTopology; multi-image differs. Check the actual endpoint/model before use. Hi3D shading/background flags and Rodin alpha handling likewise require real adapter support. A parameter value is not proof of effective de-lighting. Recheck materials under calibrated native lighting after modeling.

## Package, audit and limits

New [modeling packages](../schemas/modeling-references-template.json) use `policy: game-asset-reference-v2`. Bind asset/style, selected concept SHA, mode, actual view files, [image receipt](../schemas/reference-image-receipt-template.json) and master/derivation. Omit `master` only when `image` is the audited white master. The H3 production table and submitted operation bind the same package.

Each asset has a small `modeling_contract`:

- `category`: `humanoid`, `animal`, `prop`, `architecture`, `vegetation` or `mechanism`; `use`: `static`, `rigid_motion` or `skeletal_animation`; `structure`: concrete volume/construction/support to preserve.
- Architecture/mechanisms add `interfaces` as meaningful seam/opening/pivot/contact descriptions. Keep nominal measurements in the spatial contract.
- Skeletal humanoids add `pose: A` **or** `T`; animals add `pose: natural_stance`. Both add `pose_details` describing their actual separated limbs/joints. Each view repeats the selected `pose`; `role` changes the viewing direction only. Static sculpture may use `pose: fixed`; other static props need no pose fields.
- Other skeletal assets add `deformation_plan` explaining the real bending/skin route; a category is not proof of rig-service support.

`review` binds `images_digest: core.digest(views)` and `contract_digest: core.digest(modeling_contract)`. Record one observation per actual `view_id`: `status: pass|fail|unclear`, concrete visible `observation`, and `source_ref` of the real pixel-inspection invocation/user review. For multiview add `cross_view_observation` about the same construction, proportions and pose. Example of a useful observation: “front: both wrists clear the torso, the skirt hides knee separation; unclear for this rig reference.” A checkbox or “looks good” does not replace inspection. Failed/unclear observations block submission; fix the image or resolve visibility first.

The validator checks declarations, view coverage and stale hashes; it **cannot authenticate viewing or judge the stated visual facts**. A valid package is not proof of A/T pose or cloud riggability. Old `image-conditioned-v1` packages remain readable unchanged and report a legacy boundary, not a v2 pass. Adding a `modeling_contract` to any package invokes the new checks; never edit a frozen approval merely to silence the legacy label.

```sh
python3 "$SKILL/scripts/greybox.py" references audit --image "$MASTER" --output "$PIXEL_REPORT"
python3 "$SKILL/scripts/greybox.py" references validate --file "$PACKAGE" --project "$PROJECT"
```

Audit decodes bytes, size, PNG integrity and white-border statistics. RGB/RGBA8 noninterlaced PNG needs stdlib; other encodings need optional Pillow. Missing decoder is a concrete failure. No cloud call is made. White ratio is a background guard, not a mask, pose detector or aesthetic score.

## Primary sources, checked 2026-10-20

Historical documentation basis; verify changed model/endpoint behavior when selecting it.

- [Meshy single-image API](https://docs.meshy.ai/en/api/image-to-3d), [multi-image API](https://docs.meshy.ai/en/api/multi-image-to-3d), [image workflow](https://help.meshy.ai/en/articles/9996860-how-to-use-meshy-image-to-3d).
- [Tripo v3](https://developers.tripo3d.ai/en/docs/introduction), [multiview guidance](https://www.tripo3d.ai/help/features/how-to-use-multi-view-input-effectively).
- [Hitem3D](https://docs.hi3d.ai/en/api/api-reference/list/create-task), [Rodin](https://docs.hyper3d.ai/en/api-specification/rodin-gen1-1-5).
- Optional implementations: [Hunyuan texture pipeline](https://github.com/Tencent/Hunyuan3D-2/blob/main/hy3dgen/texgen/pipelines.py), [IC-Light](https://github.com/lllyasviel/IC-Light).
