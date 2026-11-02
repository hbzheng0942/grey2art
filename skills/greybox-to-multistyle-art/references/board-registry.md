# One registry to production pages

Use this entry for a new S7 production revision. Preserve the case's existing
decisions, source IDs, selected style images, usable outputs and uncertain calls.
The [registry template](../schemas/reference-board-registry-template.json) records
each asset once with its function, appearance, construction, modeling contract
and explicit requested views. The program derives the other lists.

```sh
python3 "$SKILL/scripts/greybox.py" boards start --file "$REGISTRY" --project "$PROJECT" --workspace "$PRODUCTION"
python3 "$SKILL/scripts/greybox.py" boards next --workspace "$PRODUCTION"
```

`boards start` checks the real input hashes, compiles scope/plan/descriptions and
enters the existing persistent production state machine. The result contains one
job per generated page: its exact slots, request, prompt file, actual input image
references and next action. Compilation produces no image and makes no claim.
Inputs live in a small sibling directory named `<workspace>-inputs`; original
images stay at their canonical shared paths. Replaying unchanged input resumes
the same pages. Changed input needs a new explicitly named workspace revision.

Bind `source` to the existing scope/BOM JSON. Supported forms are `asset_views`,
`reference_views`, or `asset_proposals[].approved_reference_views` containing
explicit `view_id` objects. Registry coverage and orientation must match that
source exactly. For a genuinely new scope without an older machine-readable
source, explicitly use `authority:"registry"` and a concrete `source_ref`; the
registry becomes the declared source, not human approval. Do not relabel an
unconfirmed historical BOM as an approved decision.

The shared `requirements` hold the task's original subject/detail minima and
their actual source. Per-view overrides require their task basis. Requirements
cannot be reduced below the upstream source to make a page pass. Automatic
single pages remain valid when packed layouts cannot fit the required detail.
An explicit `requires_single:true` additionally needs
`single_exception:{source_ref,reason}`. Report page diagnostics before spending
the next generation budget; a frozen plan alone does not establish good policy.

The registry's default `subject_fill_ratio` is a conservative 0.65 planning
assumption. An explicit ratio needs `subject_fill_source_ref`; it never changes
the actual quality minimum. No ratio guarantees model occupancy. Inspect actual
pixels after generation and use failed-slot observations to choose a repair.

Same-asset views stay together when they fit an eligible page. If the complete
view set must span pages and lacks an identity master, `boards start` prepares
the asset's `master_view_id` first, or its first originally declared view when
no master is named. Independent assets remain in that first stage. All other
views remain visible as deferred original scope, with unchanged requirements.
An initial stage can be complete while the full task is still incomplete.

```sh
python3 "$SKILL/scripts/greybox.py" boards advance --workspace "$PRODUCTION"
```

`advance` waits for the actual source crop to pass its frozen technical checks
and a visual observation bound to that exact image. It then writes an immutable
source review and prepares only the deferred views in the returned child
workspace. It supplies the real crop as an identity-master image, preserving
all style inputs. When necessary to fit the channel, it omits only the optional
layout guide and records that adjustment. It never creates source-review passes
for unseen pixels or generates another source image to recover a missing record.

Replaying advancement returns the same child. New chats can resume the returned
child registry directly; they do not get a fresh generation budget. WorkBuddy
shares its call/credit ceiling across the verified workflow stages. Pending
original calls retain their original session and cannot be resubmitted.
Changing a currently selected source crop or its visual verdict makes its old
advancement stale before another paid call. Preserve the child, every original
call and the remaining shared budget. Automatic rebuilding of that advancement
is not supported: report the source change and recover through an explicitly
revised registry/workspace. There is no hidden revision flag, and deleting claims
is never a recovery route. Ordinary ROI repair before advancement and target-view
ROI repair in the child remain available without another image generation.

Keep body/part pose, identity and construction unchanged while changing camera
role. Complete-task multiview review includes the source and every target,
including views prepared in separate stages:

```sh
python3 "$SKILL/scripts/greybox.py" boards compare --workspace "$PRODUCTION" --file "$ACTUAL_COMPARISONS"
```

The input contains `cross_view_reviews` with each `asset_id`, `verdict`, visible
`observation`, actual `source_ref`, and the exact `images` list returned by
`workflow_cross_view_reviews[].required_images`. Inspect all those pixels before
recording the comparison. Stage passes cannot replace this complete-asset
comparison. Multiple different assets on a board do not demonstrate same-asset
multiview consistency.

WorkBuddy uses the [scoped host entry](../connectors/workbuddy/board-guard/README.md)
to register the production and bind its current native tool. Host invocation is
still an actual agent/tool action: consume the exact prepared page once, record
its original result, inspect the returned board, identify original-pixel ROIs,
and crop/review through `boards production`. A pending claim means recover the
original call; opening a new chat never authorizes a duplicate submission.

`boards next` is read-only. It distinguishes mapping, exact invocation, recovery,
crop inspection and review. A successful raw crop is inspectable evidence;
technical qualification, artistic verdict, cross-view consistency and human
acceptance retain their separate meanings. Follow the actual next action instead
of creating a parallel handwritten per-object generation loop.
