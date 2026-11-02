# Executable art constraints

Use this contract when converting an approved scene concept into assets or correcting assembly drift. The current implementation is local to this repository; other engines need equivalent measurement and capture adapters.

## Required data

- Source configuration hash and selected concept hashes.
- Concept identity inventory: stable region ID, normalized `[x,y,width,height]`, identity, required silhouette features. Regions are visual references, not inferred exact 3D measurements. Label extrapolated/offscreen designs explicitly. Do not omit hard-to-build objects from the inventory to make coverage pass.
- Slot bindings: concept region, model asset key, executable variant, immutable gameplay bounds, authored visual target, minimum/maximum bounds and ground/support anchor. Distinct concepts may share a gameplay role without sharing a model.
- Any deviation from the original visual envelope: specific axis/extent, reason, collision and occlusion implications, required native check. Changing the art envelope must not silently edit gameplay data.
- Exact model hash and local-fitting provenance; variant ID must select actual geometry/material/detail behavior, not only a label.
- Review evidence: contract hash, source/adapter revision or changed-file hashes, asset manifest, camera/viewport and screenshots, explicit checks and unresolved defects.

## Deterministic and visual gates

`runtime/legacy/src/art-realization.mjs` validates identity coverage, unique complete slot bindings, immutable gameplay bounds, feasible visual ranges, bounded declared height exceptions and exact reference compilation. The reference compiler's three repair designs are Hole-specific; do not reuse those designs for unrelated concepts.

The legacy realization validator checks model hashes, slot/identity/variant correspondence and numeric ranges. `pilot_visual_factory.gd` measures the actual GLB after its explicit transform; it fails undersized or oversized realizations instead of silently shrinking them. `capture_pilot.gd` records native bounds and interaction results. These are structural checks, not automated perception of images.

Agent visual review must compare a complete scene composition against the selected concept: missing objects, wrong silhouettes, relative scale, surrounding composition and readability. A `pass` needs specific observations tied to current screenshots. Unverified proportions or pending local-fit notes cannot become accepted merely because the next stage ran. Keep technical checks and art review separate. Do not claim portability, v0 or human acceptance from the Hole test alone.

## Correction and cost control

Route the failure to its source: omitted identity → repair plan; wrong reference → correct reference; wrong mesh → local repair or bounded new model; correct asset placed/scaled wrongly → repair assembly. Reuse verified assets. Keep local edits content-addressed and texture buffers shared; preserve originals. Do not regenerate an entire family to repair one attachment or copy the project for each review.

Persist every dispatched call and reconcile unknown results. Record actual host call intervals: configured parallelism is not observed provider concurrency. Stream ready references into modeling within the authorized scope, and continue environment/assembly work while tasks run. Stop at the scoped call cap, no unlimited retries.

## Compatibility evidence

Historical Hole identity contracts are external local case data; they are not bundled in this repository. Supply an explicit current contract and its source/asset manifests to reproduce that case. The legacy implementation and model-specific exceptions are case fixtures, not new-project defaults. Earlier repair batches had specific G1 budgets; they authorize no new calls. New plans select G1/G1-Turbo, generation and delivery face budgets, and production routes per task; present reasons and current quotes in H3. G1 omits enablePbr. Apply explicit current user restrictions and obtain the first production-scope confirmation. Use [Hybrid production](hybrid-production.md) for generic complete-assembly planning.

The generic runtime consumes explicit logical owners and style bindings. Before expanding a new scene, provide current native evidence and an art review for identity, silhouette, relative scale and composition. Completed historical requests remain immutable; do not change their lineage when resuming.
