# Modeling references: design a reconstructable game asset

Use after concept/atlas selection and assembly planning. A **concept** communicates composition, mood and design; a **modeling reference** specifies one buildable asset. Do not submit a scene, action illustration, display BOM or contact sheet as that asset. Every new AI mesh uses actual reviewed image inputs; reuse and later mesh/rig processing are separate routes.

The [asset route decision](asset-routes.md) determines which source families need new models before preparing their production pages. An all-procedural proxy is not a reason to omit this decision or the references for selected AI/hybrid sources.

## Choose use before making the image

Record `modeling_contract`: `category` + `use` (`static`, `rigid_motion`, `skeletal_animation`) + `structure` (critical volume, construction and support). Read the applicable row; characters additionally require [character production](character-pipeline.md). Static sculptures can retain a fixed authored pose. Appearance does not imply animation needs.

| Category | Make explicit before generation | Choose a view that resolves |
|---|---|---|
| `humanoid` | For skeletal use choose **one A or T pose**. Straight, balanced body; readable shoulders/elbows/wrists, arms clear of torso, legs separated. No held prop or garment merging those gaps. Preserve the approved proportions, face and clothing. | A clear full-body front is the default; add a necessary side/back for hidden clothing or asymmetry. Keep **body pose unchanged** while moving the camera. A dramatic three-quarter concept is not a neutral rig reference. |
| `animal` | For skeletal use specify **natural_stance** for that anatomy: balanced support, limbs separable, tail/wings clear of body where reconstruction needs them. Do not force a quadruped, bird or fish into a human T pose. | The useful profile/three-quarter that separates limbs and exposes body depth; add front/back only for missing structure. Keep the same stance and identity across views. Read character routing before choosing a rig supplier. |
| `prop` | Real volume, support/contact surface, handle/opening and intrinsic material boundaries. Remove invented pedestals; retain real integral bases. | The view exposing the working side and depth. Add an opposite view only for an important hidden feature; avoid decorative perspective that hides the handle or hollow. |
| `architecture` | Explicit `interfaces`: module seams, base plane, portals, mounting/joining sides and occupancy from spatial design. Keep walkable openings and repeated alignment planes precise; split a shell/kit only at meaningful assembly boundaries. | Exterior mass and usable openings; complementary elevation/interior detail if needed. A facade image does not define a room, back wall or roof thickness. Use Hybrid for exact gameplay openings instead of trusting inferred geometry. |
| `vegetation` | Root/base contact, trunk/branch hierarchy, canopy volume and deliberate gaps. Decide solid mesh vs alpha foliage from the engine/use; photo-like overlapping leaves do not establish readable geometry. | A silhouette showing crown depth and branch separation; hidden-side views when asymmetry matters. Avoid a dense hedge/card that occludes the intended individual plant or gameplay view. |
| `mechanism` | Explicit `interfaces`: fixed/moving parts, pivots, contact and clearance. Produce separable rigid components when their motions differ; bind collision and sockets in-engine. | Rest configuration showing part boundaries and working clearance. Do not bake a half-open mechanism into a fused mesh and expect a character rig to recover its mechanics. |

For non-character skeletal assets, record a concrete `deformation_plan`; vegetation wind or a bending prop is not a humanoid rig request. Unsupported anatomy or invisible interfaces remain unresolved. Do not invent geometry facts or supplier support from an attractive image.

## Choose the generation route before individual calls

Assess a **generated production board** for the current asset views before submitting separate images. A board is one image-generation call containing several isolated objects; a display BOM is a local arrangement of already accepted images. Group only views that fit the observed channel's native pixel budget and can preserve their critical features. A single is a valid planned result for complex/large subjects; 3×3 requires simple-shape qualification and is not a universal default.

For new S7 production, record each asset and its views once in the [registry](board-registry.md). The program derives scope, layout, per-view descriptions and ready page jobs from that source. Bind the existing task scope when available; do not reconstruct several copies of the asset list.

```sh
python3 "$SKILL/scripts/greybox.py" boards start --file "$REGISTRY" --project "$PROJECT" --workspace "$PRODUCTION_WORKSPACE"
python3 "$SKILL/scripts/greybox.py" boards next --workspace "$PRODUCTION_WORKSPACE"
```

For WorkBuddy, use `boards workbuddy start` instead of `boards start`. It compiles the same registry, installs only this task's scoped hooks, and returns the harmless native Bash probe. After the current probe passes, `boards workbuddy bind --workspace "$PRODUCTION_WORKSPACE" --binding "$LIVE_BINDING"` binds its actual session and maps the pages. Use `boards workbuddy claim --workspace "$PRODUCTION_WORKSPACE" --page "$PAGE"` to obtain the exact one-envelope call. Supply the existing call/credit ceiling and current quoted upper cost to start; omission allows free preparation only. See the [WorkBuddy entry](../connectors/workbuddy/board-guard/README.md#normal-s7-entry).

Follow the returned jobs through actual invocation, crops and review. Existing `boards production prepare` and lower-level commands remain recovery/diagnostic interfaces for historical inputs; they are not a reason to hand-build multiple copies of a new list.

For a configured image-service profile, keep `boards prepare` and consume its exact page requests through the existing [image/executor route](execution-contract.md). Preserve its service IDs, receipts and crop provenance; the new native-host production workspace does not certify an independent service ledger. Both routes use the same planner, input descriptions and per-view image requirements.

The WorkBuddy entry registers the actual project/session scope during this structured operation. Verify real hook loading in that carrier; proposed settings and source support alone do not establish interception. A new session renews its harmless probe before binding; retain original pending calls instead of submitting them again. Use a separate actual WorkBuddy workspace for a historical regression when another chat is producing in the original project.

Inspect layout diagnostics and any single/unresolved reasons before calling a provider. A single-asset multiview page and a necessary single-view page still use this entry. Do not exempt a main asset by calling it a “single.” Do not lower modeling requirements or declare untested shapes qualified just to obtain a grid. Low-budget exploration remains exploration until the actual crops satisfy the modeling requirements.

Each page receives all approved style images plus the exact design masters for its own views. Bind an asset's accepted source view as an `identity_master` with explicit target views when deriving another direction; writing “same object” does not provide that source image. A not-yet-qualified source view leaves dependent work pending. Preparation splits pages to fit the selected channel's reference limit without dropping required inputs. Each object names its category, function, structure and distinguishing appearance; animals name their species. Preserve the category/use/pose/interfaces below. Reuse a slot only for a confirmed shared model and view, not a similar name or semantic family.

Submit each prepared page once through the chosen native-host mapping or image profile, inspect the first result before continuing, then select actual object ROIs and review every crop. Production saves inspectable original-pixel crops and records technical qualification separately. A small or truncated subject remains failed even when its crop file exists. Fixing an ROI creates a new immutable crop attempt without another ImageGen call; other slots continue and keep their accepted results. Only technically and visually qualified crops can become modeling masters. Carry their `board_crop_receipt` in the master's source review; an informal self-declared pass cannot qualify a known failed board crop.

## Make and inspect each master

1. Open the selected concept/region pixels. Name the asset/function and its few strongest recognition features: silhouette/proportion, construction/openings, material/pattern. Bind nominal dimensions and interfaces from [spatial design](spatial-contract.md), not guessed measurements from pixels.
2. Send the actual approved style images and concrete structural decisions through the prepared page or planned single route. Start with the fewest views that reveal the object. Separate views describe one object at the same scale/proportions, materials and pose; change the camera, not the design. Never label a three-quarter view `front` to satisfy an endpoint.
3. Use an **opaque white master**, complete silhouette and margin, neutral soft light, no scene/labels/floor/invented base. Keep intrinsic colors and authored marks; remove strong cast/contact shadows and baked highlights without erasing the style. No crop, mask or upscaling can recover a missing finger, branch or opening.
4. Open **each returned image and each intended crop**. Check the category-specific construction above, recognition, silhouette/support, illumination, and view agreement. Record a short visible observation and `pass`, `fail` or `unclear`; cite the actual pixel-inspection result. White borders and successful crops do not establish correct identity or construction. No viewed pixels means no pass. Test the first representative before batching; inspect every result briefly.
5. Repair the specific defect only. Re-crop a bad ROI; repair a bad view/asset without regenerating good siblings. Preserve original/master hashes. Apply transparency/masks only for a provider need and inspect pale edges afterwards; never threshold-delete white clothing, hair or ceramic.

```text
For a planned single, using the supplied approved style image, make an isolated modeling reference for
[asset ID, gameplay use and assembly]. Preserve [recognizable silhouette/proportions],
[construction/opening] and [intrinsic material/pattern]. Build [specific volume,
support and interfaces]. Show [actual view revealing the necessary working side].
[If skeletal humanoid: one full-body A OR T pose, selected explicitly; describe
arm/torso and leg separation. If animal: one anatomy-appropriate natural stance.]
[For another view: same object, proportions, materials and exact body/part pose;
only the camera moves to the specified view.]
Keep the whole object visible with margin. Pure white background, neutral soft
illumination; no scene, labels, floor, invented pedestal, strong cast shadow,
colored light or baked highlight. Keep authored colors and patterns.
```

This is the single-object skeleton; use the complete prepared page prompt for boards. Fill the alternatives; do not send literal “A OR T” or this template without the style pixels. Save the actual arguments and result in the existing generation receipt.

## Package and continue

New work uses [v2 package](../schemas/modeling-references-template.json). It binds the use/category decisions, exact views and per-image observations; [protocol](modeling-reference-protocol.md) explains conditional fields, board crops and supplier view mapping. A display BOM arranges accepted images locally and needs no new image generation.

```sh
python3 "$SKILL/scripts/greybox.py" references audit --image "$MASTER" --output "$PIXEL_REPORT"
python3 "$SKILL/scripts/greybox.py" references validate --file "$PACKAGE" --project "$PROJECT"
```

These validate bytes, provenance and recorded decisions, **not actual viewing, pose or 3D suitability**. V1 packages remain valid historical records and do not claim v2 checks. H3 binds the actual complete-sample references, scope, parameters and budget; no new reference-only human gate. After generation, inspect the actual GLB's shape/materials/interfaces; for characters, follow the bound GLB → rig → first-motion checks before replication.
