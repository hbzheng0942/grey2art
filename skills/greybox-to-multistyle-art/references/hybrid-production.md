# Produce a complete composition, then reuse what worked

Use after a concept is selected and while planning/assembling its native result. Work through **visible requirement → responsible layer and dependencies → complete assembly → native implementation → actual gameplay observation**. For a focused, already-authorized material/light revision, use [scene effects](scene-effects.md) directly; do not restart concept selection or asset production unless their accepted scope or inputs changed.

Apply [asset route decisions](asset-routes.md) before final native authoring. Classify form separately from surface/light/effects, evaluate generated/reuse/procedural choices for dominant forms, and keep selected AI/hybrid work pending until its actual model task completes. The existing H3/H4 gates cover this work; direct engine scripting does not waive them.

## Decide what must carry the image

1. Open the approved concept and identify the few properties carrying its appearance: form, surface, light/shadow, atmosphere and relevant motion. Use [visual feature analysis](visual-feature-analysis.md) for consequential ambiguity. Tie each requirement to a concept region/view and a native observation; a still image alone does not establish motion or its implementation. Do not omit a difficult feature to make coverage pass.
2. Choose a complete assembly that can be inspected: e.g. a room with its functional device and surroundings, or a bridge with both landings and the background reveal. Give environment, main forms, functional objects, contact/joins and lighting real owners. A lone hero mesh or most of an asset catalog is not the complete sample.
3. Split **appearance responsibility** from **dimensional control**, then select a route:

| Need | Useful route | Completion check |
|---|---|---|
| Precise paths, openings, support or continuity | Controlled structure with authored profile/material/joins | Actual clearance/contact and the intended visual treatment |
| Dominant organic/iconic shape or detailed identity | Qualified generated or existing authored mesh | Approved shape/detail reads at its real viewing distance |
| Variable span/fit with distinctive repeated parts | Parametric skeleton + generated/reused modules + connectors | Modules share language; sockets/returns resolve the dimensions |
| Large terrain composition | Controlled macro surface + rock/form families and masks | Continuous macroform, useful medium forms and coherent transitions |
| Minor repeated population | Instanced family variants or suitable authored rule | Enough variation where repetition is visible, without a new mesh per instance |
| Surface color, roughness, pattern or relief | Existing/native material, suitable maps or a local shader | The intended response reads on the actual object under target lighting; UVs, normals and texture interpretation are correct |
| Light hierarchy, shadow, reflections or atmospheric depth | Native lighting/environment, supported reflection/GI method and selective post-processing | Whole-view value/depth relationships and required reflected content survive the actual camera/state |
| Moving water, foliage, particles or animated surface treatment | Suitable native effect, reusable recipe or bounded extension | Motion, boundaries, contacts and gameplay readability remain useful across relevant frames/views |

These are choices, not AI percentages. Procedural appearance can be final when actual images show the intended language; low cost alone is not evidence. Do not reserve generation for tiny decorations while leaving dominant forms as a rough blockout.

Choose effort by visual identity, salience, interaction and implementation/runtime cost; projected area alone is insufficient. Ordinary native setup may be enough, while a low-impact effect may be deferred or omitted with its visible consequence recorded. Use [scene effects](scene-effects.md) to choose an existing recipe, documented native feature or bounded capability investigation. This lightweight planning decision does not require an experiment for every feature.

Feed dependencies back into the same asset/assembly plan before production: clear water may need a bottom and real depth; a displaced surface needs suitable sampling; material/lighting work may need UVs, normals, thickness, shadow casters or reflection surroundings. Record who provides each dependency and what the S6 probe must resolve. Mesh detail cannot supply missing light, and an effect cannot supply missing construction.

Teaching example: for a distinctive arch spanning an exact gameplay opening, keep the opening/support skeleton controlled, use authored/generated arch modules for visible identity, and design the feet/joins. Do not generate the entire precise interface blindly or flatten the entire arch to a box. This is a reusable decision pattern, not proof that one supplier can produce every arch.

## Make source families assemble cleanly

- Mesh families declare nominal dimensions, allowed uniform scale, front/up, pivot/support, connectors and material/runtime profile. Instances carry stable IDs, owner and transform. Record material/environment/effect ownership, inputs and compatible renderer profile in the existing design/assembly notes; do not invent mesh dimensions for these resources. One canonical source may serve many instances; justify variants where visible repetition matters.
- Design joins now: overlap, trims, returns, landings, caps/bases, UV/material transitions and neighboring occlusion. A seam is owned production work, not optional final polish.
- Preserve originals and texture buffers. Fit from immutable source with the complete owner transform. Check **achieved** dimensions, not only requested bounds: depth-limited uniform fitting can prevent a requested width. Do not stretch a complex building/character to satisfy an arbitrary AABB. Repair the skeleton/interface, approved local geometry or design conflict.
- Apply optional remesh/rig/motion only for a demonstrated need. Use [asset optimization](asset-optimization.md) for measured GLB topology/payload comparisons, supported processing routes and native rechecks; file measurements do not prove frame rate or appearance. For a required character use [character pipeline](character-pipeline.md); a static figure does not need a skeleton. Prove a family's required complete processing/interaction path on a representative before expanding it.

## H3: propose one complete sample

The current sample has exact [modeling references](modeling-references.md) for new generated meshes, readable BOM/assembly images, feature-to-source/route responsibility, assembly interfaces and native view/state coverage. Materials, environment and effects remain owned work even when they require no model generation. Reuse the same IDs in every record. Future distant families can stay coarse; they do not delay a complete useful first sample.

Bind native work in the existing [assembly recipe](../schemas/assembly-recipe-template.json): `native_realization` names its `kind` (lighting, material, shader, vfx or environment), actual `target`, implementation `method` and H3 `evidence_image_id` from the BOM/assembly images. A feature may use `asset_ids: []` with `assembly_ids` pointing to these owners; keep the existing `appearance` or `environment` responsibility. `precise_geometry` still needs real asset sources. An entirely native plan may have an empty asset catalog, but its assembly ownership, illustrated target and required native views remain. The declaration is a plan, not proof of execution; omitting an effect cannot satisfy a required feature.

For supplier work, apply the effective user supplier/model policy first. Declare version and face count explicitly; G1 omits `enablePbr`. A user requiring G1 unless explicitly requesting Turbo must receive that policy. Preserve older assets/parameters and assess reuse by actual quality. Compare qualified suppliers/models and source-family reuse at the same approved visual target; include repair/style-unification uncertainty. Keep coherent family material/rig conventions where practical.

Use [suppliers](suppliers.md) for capability evidence and [workflow](workflow-vnext.md) for sourced costs, alternatives and budgets. Unknown cost is not zero; installed is not proven useful. H3 binds exact complete-sample references, portfolio, parameters and ceilings. Reuse unchanged decisions; recover unknown submissions before retry/substitution.

## Assemble early; fix the cause that changes the picture

S6 probes the largest spatial, observation or rendering uncertainty using the intended renderer and gameplay view. Test high-impact unproven mechanisms before committing the assets that depend on them; use the existing [scene comparison](scene-comparison.md) rather than a new approval stage. During authorized production, integrate returned assets while independent environment/structure work continues. Inspect the whole gameplay view: missing major layers first, then shape/material/contact, then optional detail. Asset count is not completion.

| Observed defect | First useful action |
|---|---|
| Main feature absent / scene feels empty | Repair feature/assembly ownership and depth composition |
| Reference already lost the intended shape | Correct that reference before more modeling |
| Correct asset looks too small or floats | Inspect full transforms, limiting fit axis and actual support surface |
| Correct mesh appears white or wrong-colored | Check texture availability/material conversion under fixed lighting |
| Required reflection, depth or light response is absent | Check supported renderer capability and its actual inputs/activation, then make a targeted native comparison |
| Attractive still fails during camera or object motion | Check temporal stability, view-dependent effects, transparency and reset/time ownership |
| Harsh join or wrong neighboring proportions | Repair connector/placement/composition; preserve good sources |
| Generated geometry itself is wrong | Bounded local repair or authorized replacement of the affected source |

Use [field lessons](field-lessons.md) for a matching symptom and [visual harness](visual-harness.md) for material diagnosis. Record the few largest defects and expected visible change in existing [production control](production-control.md); changing scripts/workers does not reset repair effort. Finish the agreed complete H4 scene/core loop, then release other selected styles. Passing one spatial/processing type does not establish untested types; inspect relevant differences in the next real production unit without inventing a separate game experiment. Each promised style still needs its own native visual/interaction evidence.

The host authors these decisions and uses actual tools. The shared runtime validates declared identities/coverage and executes supported native operations; it does not automatically compile every design or judge concept fidelity.
