# Concept-to-native scene comparison

Use the proposed H3 `visual_features` to compare the **whole native composition early**, before committing full production. Repeat against the current complete sample before the existing H4 human decision. A list of imported models or passed technical tests cannot substitute for this visual comparison.

Before filling the table, use [visual feature analysis](visual-feature-analysis.md) when the target is still described by broad style labels or has consequential ambiguity. Keep observable properties, evidence regions and scope distinct from implementation choices; reuse the current atlas/design note.

New production tables declare `sample_contract.scene_comparison: "feature-view-v1"`. Historical tables without it retain their existing checks; never rewrite past approvals to claim the new review happened. Each style keeps its own concept, features, native views and sample. This does not shrink a multistyle task to one style.

## Early composition probe, before H3

Prepare the proposed production table using the approved H2 atlas: name dominant and supporting visual features, their actual concept view, target appearance, responsible sources/assembly work and native observation views. Include environment, major forms, functional objects, contact and lighting/materials. Assemble an inexpensive whole scene using the assets and materials already available; do not reserve the entire comparison until paid asset production finishes.

Features implemented by native light/material/effect work may bind `assembly_ids` to declared `native_realization` owners without inventing asset families; see [production planning](hybrid-production.md). They retain the same concept target, required views and later per-feature comparison. A valid owner declaration does not prove that the effect rendered or remove a critical feature from H4 coverage.

Use this same S6 probe to resolve a high-impact rendering uncertainty before producing dependent assets. Select the mechanism through [scene effects](scene-effects.md), retain the intended renderer, and test the specific visible requirement in its actual camera context. For example, check whether water reveals the bottom before finalizing that bottom's detail budget. A small controlled comparison may diagnose a mechanism; the whole view still checks its contribution to the composition. Record partial success and unsupported parts separately. Use relevant separated frames or views for motion/view-dependent effects; a still frame cannot establish their stability or runtime cost. Ordinary proven setup does not require a second experiment or approval.

At capture time, the existing S6 `composition-probe` manifest records its actual `scene` and `source_files` (`path`, `sha256` for native scene/source/assets/render configuration and import settings). Keep its existing `proxy_capture` evidence, camera/state/view and missing-layer records. The command checks native dependency coverage and current bytes. Missing provenance requires a new capture; do not attach today's source hashes to an old screenshot.

```sh
python /absolute/path/greybox.py scene-review draft --phase proxy \
  --workflow /project/workflow.json --project /project --style city \
  --production-table /project/proposed-h3.json --output /project/proxy-comparison.json
python /absolute/path/greybox.py scene-review check --phase proxy \
  --workflow /project/workflow.json --project /project --style city \
  --production-table /project/proposed-h3.json --report /project/proxy-comparison.json
```

The draft starts `unclear`. Inspect the actual target and native images; fill each observation and next action. Missing layers are review gaps to repair, not a claim of H4 quality. This report always identifies itself as `risk_and_composition_only`; passing its evidence check does not approve H3, establish a complete sample or authorize generation. Fix high-impact discrepancies before expanding production.

## Complete sample before H4

Create the current H4 sample evidence while the stage is still a draft: original `sample_source_production`, `sample_inputs`, `native_sample`, `native_capture`, and attempt identity. The source manifest already binds source/assets/render configuration; no second project snapshot is needed.

```sh
python /absolute/path/greybox.py scene-review draft \
  --workflow /project/workflow.json --project /project --style city \
  --output /project/sample-comparison.json
python /absolute/path/greybox.py scene-review check \
  --workflow /project/workflow.json --project /project --style city \
  --report /project/sample-comparison.json
```

The paired report covers every original H3 feature in each required native view, plus a full-image comparison for each whole-composition view. Each row binds the permitted concept/native image hashes and normalized `[x, y, width, height]` regions. A shared sheet is allowed; identify the feature's actual region and observation. Copying the same image pair, region and observation cannot establish multiple feature reviews. Whole-composition rows additionally report every required visual layer.

Record `pass`, `fail` or `unclear`, a concrete observation and a next action for every unresolved item. Record the actual reviewer/task and review source. Add the finished report as H4 evidence role `scene_comparison` with its file hash. New declared contracts block H4 when coverage is missing, inputs changed, or any comparison/layer remains failed or unclear. Source changes require fresh evidence; do not alter the old report to preserve a pass.

H3 pre-handoff criteria for this contract also require their relevant local artifacts: visual responsibility cites the production table and BOM; readability cites both BOM and assembly map; complete-sample scope cites the table and assembly recipe. An unrelated image or only an examined-images list cannot satisfy these criteria.

The software checks evidence binding, freshness, coverage and declared unresolved work. It cannot prove the reviewer looked at the pixels or independently judge aesthetics. Existing independent pre-handoff review and H4 human visual acceptance remain the decision points; this adds no approval round and submits no provider calls.
