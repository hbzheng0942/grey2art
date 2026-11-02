# Extract observable art requirements

Use when a selected concept becomes a spatial/production plan, or when comparison still relies on broad labels such as “pixel”, “realistic” or “close enough”. Work with the current atlas/design note and H3 `visual_features`; this adds no stage, approval or model dependency.

## One useful pass

Inspect the actual whole image before choosing details. Separate **what is depicted** from **how it is visually constructed**. Scan form/proportion, value/color, boundaries/line, surface marks and depth/composition; retain only properties that distinguish this target and affect production. Cover the relevant views/route regions without copying every object's inventory. Separate the reference sheet's frames, labels and layout from the world being built, unless reproducing the sheet is the task. Do not infer an object's orientation or function from a familiar scene convention when visible views can check it.

Write each important requirement compactly:

**source region → visible property and scope → plausible look-alike/shortcut → distinguishing evidence or native check.**

Keep independent properties separate. A local treatment does not establish a whole-scene rule; check another relevant area before generalizing. “Not everywhere” also does not mean “absent”: retain positive local evidence when rejecting a global claim. Appearance and its implementation are separate decisions. A style label, specialist role or confident explanation is not evidence.

Ask: **“If the objects and palette stayed, which missing visual property would still make this look wrong?”** Use this to prioritize, not as proof of a measured ablation. Keep consequential unknowns visible and move resolved requirements into the plan; do not keep rewriting fluent descriptions.

For the few properties that drive this scene, assign implementation responsibility: geometry/placement, texture/material, light/environment, shader, VFX/motion, or their combination. Record dependencies and when they must be resolved in the existing design note. Clear water may need a real bottom and depth; a light shaft may depend on an opening and atmosphere. These requirements can change the asset plan before modeling starts. A static image does not establish a unique physical cause or motion behavior; label the proposed mechanism as a hypothesis until checked.

Use [scene effects](scene-effects.md) when rendering materially determines the target. Prioritize by style identity, visible contribution, gameplay importance, uncertainty and total effort, not screen area alone. Keep ordinary native settings for low-risk requirements; use the existing [scene comparison](scene-comparison.md) probe for a consequential unknown. Reuse the chosen engine/pipeline and return failed prerequisites to the responsible production task.

## Ask a discriminating question when it matters

When two interpretations would change a major production decision, ask about their observable attributes independently rather than asking “is this style X?” When boundary treatment defines the target (for example pixel/coarse or strongly graphic edges), explicitly answer the first row's two questions even if a broad style description already seems complete. Use the other rows when relevant; do not force every image through every example.

| Relevant ambiguity | Questions to answer from pixels |
|---|---|
| Pixel/coarse edge and line treatment | Is the **spatial boundary** smooth, stepped or blocky? Separately, is its **color boundary** only the meeting of adjacent faces, or a distinguishable narrow band? Both may coexist. Check a clear silhouette, an internal division and another object; record presence, absence or unclear for those regions. |
| Narrow dark band and structure/shadow | Where does the band run, and how does it behave around corners or changes in lighting? Could it be a beam, window frame, seam or shadow? Preserve the local band observation even if its cause remains unknown; do not prescribe uniform black outlines. |
| Surface pattern and reflection | Are there surface marks, directional highlights or distorted neighboring forms? They may coexist. Follow changes across curvature; a static image does not establish a physical material or shader. |
| Value blocks and geometric facets | Are there discrete value regions, angular silhouettes, or both? Do the breaks follow form edges? A flat color block alone does not prove coarse geometry. |
| Haze/negative space and missing background | What distant forms remain visible, and how do contrast/detail change with distance? Preserve intentional space without excusing absent landmarks as atmosphere. |

Revisit the source region at a useful scale only to answer a named consequential question. Use faithful source pixels and retain their whole-image context. Do not use generative enlargement, smoothing or reconstructed detail as evidence. If the host cannot expose the needed pixels, keep the claim unclear; repeated verbal review cannot recover missing evidence.

Make the follow-up an actual question to answer, not just another copy of this method. A compact form is: **“Check [named property]. Observe A and B separately; they may coexist. Locate an example and a contrasting region, state what remains uncertain, and change only the requirement supported by that evidence.”** For an orientation/function claim, use available alternate views or visible features to cross-check it; do not replace an unsupported assertion with the opposite convention. Naming the question can recover missed evidence; it does not prove the agent will autonomously discover every important question.

## Self-review or another agent

The executing VLM can ask and answer these questions itself. Do not create a subagent merely because the method says “review”, or repeat the same generic checklist in a new context by default.

Use independent review when requested, or when an unresolved high-impact interpretation merits another observation before costly commitment. If delegation is unavailable, continue with the same evidence-based questions; preserve any unresolved limit under the existing contract. Neither more agents nor agreement establishes correctness.

Give a reviewer the actual image through a supported visual channel, the scene task, compact requirements and the specific uncertainty—without an expected answer. Ask for **supported correction, source location, surviving alternative and any missed high-impact property**. A path string alone is not image access. Keep irrelevant conversation and producer/method labels out when practical. The main agent accepts corrections by evidence; do not silently replace a scoped observation with an unsupported opposite. A request for a second view is useful only if that view can distinguish the alternatives.

Stop reviewing when evidence supports the needed decision, or when a further textual pass cannot resolve it. Carry the remaining uncertainty into the existing inexpensive native comparison. Record actual extra time/token cost when measuring workflow efficiency; include reconciliation, not just the reviewer's turn. A user-chosen reviewer model belongs to the task configuration, not this reusable method.

## Use the existing handoff

Keep evidence locations and uncertainty in the atlas/design note. At H3 use `id`, `concept_view_id`, `importance`, `responsibility`, `target`, `asset_ids`, `native_view_ids`; native work can use `assembly_ids` as described in [production planning](hybrid-production.md). Put visible property and scope in `target`; bind actual assets or declared native assembly owners. If responsibility or native views are not yet known, keep a draft note rather than invent IDs or a second ledger.

Use [scene comparison](scene-comparison.md) for the early native probe and later complete sample. Inspect the supplied requirements **and omissions outside the list**; an evaluator's reference can share the producer's blind spot. Resolve consequential discrepancies against pixels, not aggregate scores or stylistic agreement. Evidence/hash/schema checks do not certify visual perception, realized beauty or human acceptance. Existing human decisions remain unchanged.
