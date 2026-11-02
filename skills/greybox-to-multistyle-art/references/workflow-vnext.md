# Workflow contract — complete visual sample

## Stage dependency and output contract

S0–S3 are shared. S4 onward branches by selected style; assemblies may progress independently after their actual interfaces and scope are ready. Every artifact has stable identity, revision and real file/hash evidence. The host/tool produces the work; the checker verifies records and dependencies, not design quality.

At H1, also identify the user's high-priority style. Keep the complete selected image set unchanged in `shared/selection`; record operational priority/active/queued state in the case's `CONTROL.json`. Deepen and run that style first. Its production plan and supplier portfolio contain only the current active style; other selected styles need not complete H2/H3 before this branch starts. Reordering work must not rewrite H1 or its downstream approvals. CLI checks accept repeated `--style STYLE` and `--style-phase STYLE=representative|expansion`; phase selection validates existing evidence and grants no production authority.

The lead exits after the agreed complete native scene/interaction loop has passed H4 for a finite space, or after the agreed connected, complete key slice has passed H4 for a large/continuous space. Record project-specific interfaces, verified processing profiles, actual integration observations and unresolved limitations, then release subsequent styles through operational control. Nonblocking polish stays in the backlog and cannot postpone this transition indefinitely. Each next style retains its own H2/H3/H4 and checks structural/processing differences before reusing a pilot's evidence. All H1-selected styles remain final deliverables unless the user changes scope.

| Stage ID | Required output | Decision |
|---|---|---|
| preflight | Current host/interface capability receipt; useful invocation evidence when available | Operational readiness; no paid synthetic probe |
| baseline | Gameplay/spatial contract, logical owners/states, camera/input model and native observations | Resolve consequential uncertainty |
| directions | 8–10 actual whole-scene concepts and substantive briefs | Count changes/imported set require explicit scoped user decision |
| selection | Actual selected image IDs/hashes bound to current direction set | H1 user |
| atlas | Per-style shared language, key spatial types/transitions, consistent landmark IDs | H2 user |
| spatial_design | Map, relation graph, sections/volumes, envelopes/views/states and production interfaces | H2 user |
| art_proxy | Native composition captures at approved views/states, explicit missing layers and resolved production risks | Internal; significant design change returns to H2 |
| production_plan | Exact complete-sample table/recipe, visible BOM and assembly map, visual responsibility, reviewed scope/cost | H3 user |
| representative_sample | Complete native sample/captures plus technical, gameplay and visual reports | H4 user |
| Expansion/delivery | Dependency-ready assemblies, every promised style and version-bound final evidence | H5 actual user decision recorded against the delivery manifest |

Use [concept authoring](concept-authoring.md), [spatial contract](spatial-contract.md), [Hybrid production](hybrid-production.md) and [human decisions](human-decisions.md) for the content of these outputs. A compact finite-space board/volume may be sufficient; empty placeholders or a lone model are not. An independent asset may proceed after its own approved interface/risk work; that does not waive prerequisites for the assembly using it.

## Early workflow overview

Before direction production, show one screen with input authority, requested output/engine, stages and H1–H5, selected/unknown style count, conditional character/rig/motion branches, tools/suppliers, major unknowns and cost/time bases. Unknown estimates stay unknown. Update the same overview after material scope changes; resolve consequential unknowns before dependent work. This auxiliary artifact creates no H0, spend permission or extra approval ritual. See [capability preflight](capability-preflight.md) and [optional characters](character-pipeline.md).

## Schema 2: decision integrity

Start from `schemas/workflow-template.json`; draft/empty templates intentionally fail production. A stage has `id`, `scope`, positive `revision`, accepted status, actor/decision note, hashed `evidence`, and `consumes` mapping dependency keys such as `shared/directions` to their stage digests. Evidence has a unique identity where required plus `role`, `path` and `sha256`. Concept image evidence also needs actual `origin` (`host_generated` or `user_provided`) and `provenance_note`.

`stage_digest` includes substantive content, evidence, revision and consumed dependency digests. It excludes administrative acceptance fields (`status`, `actor`, `recorded_by`, `decision_note`, `approval`, `authorization`). A human approval is bound to `{actor:'user', decision:'accepted', source_ref, scope:'scope/id', stage_digest}`. The H1/H2/H3/H4 stages must name the actual user as decision actor; an agent can record that decision but cannot originate it. The source reference must identify actual trusted user input. This binding detects inconsistent reuse; it does not authenticate a message or prove aesthetic acceptance.

A new image, evidence file, stage revision or consumed design invalidates the affected decision binding. Preserve older checkpoints and decisions. Reuse unchanged approvals in a new checkpoint only when their substantive digest and consumed dependencies remain unchanged. Retain unrelated approved artifacts rather than regenerating or reapproving them solely because another branch changed. The execution core still snapshots project inputs conservatively; an unrelated source edit may require a new run even when those creative approvals remain valid.

Preflight is operational and excluded from creative dependency digests. Refresh capability readiness separately; do not edit a frozen creative checkpoint or re-select unchanged art because a session or capability receipt expired.

## Current policy and preserved history

`production_policy:'asset-routed-visual-sample-v3'` retains the visual/pre-handoff checks and adds explicit form route decisions and original model-task evidence. The workflow schema stays 2 and `stage_digest` retains its exact historical algorithm. Existing `image-conditioned-v1` and `complete-visual-sample-v2` checkpoints remain readable as `historical_integrity`; they do not silently acquire new compliance and cannot start a new production run. Status and known-task recovery preserve frozen records. Only an existing run with its original verified plan/checkpoint identity may use the explicit legacy continuation path. A new revision needs actual missing artifacts, review and scoped user decisions; changing the policy string cannot migrate an approval.

## Whole composition before local polish

Declare `spatial_contract.observations` before S6: stable view IDs, camera IDs, gameplay state IDs, covered spaces, framing and required layers, plus spatial/composition risk IDs. See `schemas/observation-contract-template.json`. Include a complete view with major forms, environment, functional objects, contact and lighting/materials; add important interaction states. An indoor environment does not require a sky, but still needs deliberate surrounding composition.

S6 records `composition-probe` JSON and actual `proxy_capture` pixels for every observation. `visible_layers` and `missing_layers` explicitly partition each view's required layers. Use existing greybox, reused assets and cheap representations to expose placement/composition risks. The `risk_review` covers every baseline risk; unresolved production risks block H3. Missing final visual layers can remain named work, and the probe must never be presented as H4 quality. See `schemas/composition-probe-template.json`.

For large/continuous spaces, use `atlas.scope_mode:'focused'` to separate global coarse intent from current H2 detail. Keep the complete baseline unchanged. `global_layout.spaces` gives every baseline `space_id` a coarse `intent`; `global_layout.boundaries` covers every baseline transition with its endpoints and `continuity_rule`. The atlas's `required_space_ids` is the current detailed slice; its `required_transition_ids` includes every internal and external interface touching that slice. Actual key-scene views cover each intersected baseline segment, and transition images cover its interfaces. `focus_contract` names the concrete `playable_loop` plus entry/exit `{space_id,view_id,interface}`; use distinct actual observation views and preserve clearance/support/sightline boundaries. Continuous slices must be connected. See `schemas/focused-atlas-template.json`.

The spatial graph deepens precisely those spaces and interfaces. S6 covers every baseline observation intersecting them, including views that see neighboring context; a wide view cannot be silently cropped to waive its required composition. Global risk declarations remain visible. H3 sample/production spaces must already have detailed H2 coverage. Future coarse intent cannot authorize source production. Legacy atlases without `scope_mode` still require full baseline coverage; finite scenes retain full H2 coverage.

H3 freezes one complete sample, with `scope_mode:'complete_sample'`, exact `sample_contract.sample_space_ids`, all baseline observations intersecting those spaces in `required_view_ids`, and the five `required_composition_layers`. For the initial `complete_sample`, recipe assemblies cover exactly those sample spaces; `composition_owners` maps each layer to an actual assembly. A coarse `future_backlog` does not require preparing all distant source families before the first sample. Environment, distant silhouette, ground, lighting and major forms have real owned outputs; detail tasks do not displace these gaps. Prioritize prerequisites and missing major layers, then medium form/material/joins, then local polish. See [orchestration](orchestration.md) for task selection and short active-work reassessment.

H4 binds actual captures to each required view/camera/state/framing and complete layers. A closeup, missing environment or another gameplay state cannot substitute for the approved whole composition. Image records can establish coverage and byte identity; actual pixel content remains a reviewer/human judgment.

## H3 visual package and route responsibility

In addition to the table/recipe, H3 has actual decodable `bom_board` and `assembly_map` images and `visual_package` JSON. Its `bom` maps every current source family to a real image ID and normalized region; `assembly_annotations` binds every recipe assembly and its exact asset IDs to a region in a real map. Both views derive from the same asset list. See `schemas/production-visual-package-template.json`.

Generated/hybrid entries must be `production_ready`, reuse must be `approved_reuse`, and procedural work must have an actual design reference. Related shape vocabulary or missing design can appear in the coarse backlog, never as a complete production-ready sample. Mechanical checks cannot prove that a label points to the correct object; pre-handoff review must inspect this directly.

`production_table.visual_features` maps approved concept view IDs, intended features, importance and responsibility to asset families and native observation IDs. Every critical sample feature and proposed family has an owner. Dominant procedural appearance requires `procedural_visual_match` with task-specific reason, an actual visual image ID and observed target match. Hybrid declares generated appearance and controlled structure roles. A generated label without an image-conditioned operation cannot bypass the route check. Suitable reused assets and fully rule-expressible styles remain valid; there is no AI percentage quota. Compare cost across qualified AI production combinations while preserving the visual target.

Apply [asset route decisions](asset-routes.md) before final native authoring, including direct host engine tools. The H3 table binds `asset_route_contract:asset-routes-v1` in its stage digest, so changing a copied source workflow's top-level policy cannot waive current route evidence. Each feature declares `feature_kind:form|surface|light|atmosphere|motion`; a form needs asset families even when its responsibility is environment. Its dominant source families include `route_evaluation` with short generated/reuse/procedural suitability reasons. Procedural target-match evidence applies to dominant forms regardless of responsibility labels. Both generated and hybrid routes require actual image-conditioned model operations and reviewed references. S6 proxy geometry does not silently become the production route; blocked model work remains pending while preparation and independent work continue.

## Lightweight pre-handoff review

Review `directions` before H1; `atlas` and `spatial_design` before their H2 decisions; `production_plan` before H3; and `representative_sample` before H4. Build the inputs with:

```sh
python3 "$SKILL/scripts/workflow_check.py" review-inputs --file "$WORKFLOW" --project "$PROJECT" --stage STYLE/production_plan
```

This read-only helper emits required criteria and the actual current artifacts/images, including selected concept and consumed upstream evidence. It neither records review nor passes it. A producer identifies `stage.producer:{agent_id,task_id}`. An actual reviewer examines those inputs and records `stage.review` following `schemas/pre-handoff-review-template.json`: exact `input_digest`, actual reviewer/task/source reference, examined image hashes, criterion-by-criterion observations/evidence, findings and unreviewed scope. An independent reviewer has different agent and task identities. On a host without subagents a serial fallback must explicitly state `unverified_serial` and its limitation; it is not reported as independent.

The review digest excludes its own receipt and administrative human approval fields, and excludes H4's later `visual_review` human artifact. Final `stage_digest` includes review and all human visual evidence. Changes to relevant inputs or consumed dependencies stale the review and its dependent approval; no circular hash is required. A `passed:true` field cannot replace coverage, images or unresolved blocker/repair checks. The local record cannot authenticate a reviewer or prove that they viewed pixels; the host must transcribe actual observations. One review and usually no more than two focused repairs is the default; unresolved material issues remain visible and block the relevant handoff, without inventing another user approval stage.

## Directions and selection

The direction manifest contains candidates with `id`, `concept_image_id`, `concept_sha256`, and a `brief` with `theme`, `shape_language`, `material_language`, `spatial_composition`, `functional_identity`, `light_palette`. Image IDs/hashes must match current concept evidence. Default count is 8–10; an explicit alternative requires `count_override` with `actor:'user'`, `decision:'accepted'`, `source_ref`, `scope:'shared/directions'`, `candidate_set_digest` and `reason`. This also applies to an explicitly approved imported set.

Candidates must declare at least two substantive differences excluding palette. This declaration check cannot establish that the actual images differ; inspect them. Selection evidence uses schema 2 `kind:'style-selection'`, `directions_digest`, and `selected:[{style_id,concept_image_id,concept_sha256}]`. Retaining a style ID while replacing its image does not preserve H1 approval.

## Required evidence roles

| Stage | Scope | Roles |
|---|---|---|
| preflight | shared | capability_report |
| baseline | shared | spatial_contract, native_baseline |
| directions | shared | concept_image, directions_manifest |
| selection | shared | selection_decision |
| atlas | style | concept_image, atlas_manifest |
| spatial_design | style | plan_view, spatial_graph, section_or_volume |
| art_proxy | style | native_proxy, proxy_capture, risk_review |
| production_plan | style | production_table, assembly_recipe, scope_decision, bom_board, assembly_map, visual_package |
| representative_sample | style | sample_source_production, sample_inputs, native_sample, native_capture, technical_report, gameplay_report, visual_review |

The baseline `spatial_contract` JSON includes the actual executable contract's scene and validation steps/required check IDs. Use authoring directories excluded from Godot import for non-runtime images/documents, while keeping real runtime resources importable.

## Supplier portfolios before H3

Use [supplier selection](suppliers.md) for registry, pricing and executor details. Compare qualified configured/desired vendors by asset family; documented-only operations remain setup options. Offer recommended/lower-cost/higher-quality portfolios when feasible, using the same scope and acceptance target. Otherwise identify the sole feasible route. Each choice names model/version, reference, operation chain, supported parameters, reuse and rationale. Honor the user's effective model policy; a G1-only policy cannot silently choose Turbo. G1 omits `enablePbr`. Preserve historical asset/task parameters.

Use dated official rate-card calculations by default. API quote requests are conditional; quality probes need their own authorization. Keep estimates, actual consumption, unlike credits/wallets/currencies, conversion basis, owned allowance/new cash, processing and repair reserve separate. Unknown prices are not zero and prevent a firm complete total. Lower cost does not justify silently changing quality or delivery. No numeric aesthetic score is required.

H3 binds the selected portfolio, exact operations, wallet/currency caps and permitted substitutions. Every selected source family must appear in its owning style's H3 proposal and visible BOM with the same route and image-conditioned operation; shared sources appear in each owning style. A changed fallback route requires explicit `fallback_routes:{option_id:route}`, its production-ready image reference and applicable portfolio/operation/wallet authorization. Compared but unselected alternatives do not become executable. Same-family supplier/material/rig conventions should remain consistent unless mixing is justified. Reconcile unknown submissions before retrying or switching. Legacy Lux execution and portable supplier execution below have distinct request contracts; relabeling a vendor cannot turn its request into a Lux request.

## Bind production promises to the executable plan

`execution_plan_digest` is computed from the execution plan, excluding only top-level `workflow` and `operational_receipts`. Both schema 2 production-table and assembly-recipe JSON name their `style_id` and matching `execution_plan_digest`; changing runtime asset/binding/task parameters requires updating the relevant plan and scope evidence. Renaming a descriptive table cannot approve a different executed plan.

For the portable R3 supplier path, prepare the H3 portfolio using sourced official rate-card calculations by default. An executable operation may carry no API quote ID when the provider permits direct submission. The selected estimate and reserve must fit the actual H3 cap; later consumption is recorded separately and cannot silently increase authorization. See [supplier selection](suppliers.md) for rate-card input and exact command help.

The existing **legacy Godot/Lux plan/run route** retains its stricter quote receipt contract. If choosing this route, `quote-preview` can collect optional pre-H3 API prices against a draft that already binds actual H1/H2. S6/H3 evidence is not a prerequisite for this quotation-only path, so a native proxy and quote collection can proceed independently. Current schema-2 Lux connection evidence must match each quoted asset’s region. Preview validates requests, may upload references and retrieves quotes; it submits no models and creates neither a run nor approval. This route’s quote requirement is not a global requirement for every R3 supplier proposal.

When using the legacy route, show its safe per-asset version/face-count/rationale/price summary, regional totals and `receipt_hash` alongside the selected portfolio in H3. Keep the full `0600` receipt private because requests may contain provider URLs. After actual H3, record production table/recipe/decision, freeze workflow/plan, and follow that route’s `plan` → `quote` → `approve` → `run`. A refreshed executable quote within the explicitly approved unchanged scope/credit ceiling can reuse the same response; two quote commands are not two human decisions. Expired executable quotes refresh where that route requires them; material scope or budget changes need a new decision. Source-based estimates follow their declared rate-card validity instead of inventing a quote-ID requirement.

The production table also contains `sample_contract`: `style_id`, original `baseline_scene`, actual assembled `scene`, `input_digest`, sample `execution_plan_digest`, `required_technical_checks` (including material calibration, scale fit and assembly seams), baseline `required_gameplay_checks`, and nonempty `required_critical_features` from the approved concept. H3's `input_digest` records the known production input contract; it is not a hash of future generated assets. These acceptance conditions are declared before the sample is reviewed, not lowered after failure.

## Sample semantics before expansion

A sample stage binds `identity` with `style_id`, `scene`, `attempt_id`, `input_digest`, `execution_plan_digest`, and `sample_inputs_digest`. H4 supplies `sample_inputs` evidence using `schemas/sample-inputs-template.json`: `{schema:2, kind:'sample-inputs', style_id, baseline_scene, scene, producer_runtime_digest, files:[{id, path, sha256, category}]}`, where category is `source`, `asset` or `render_config`. `sample_inputs_digest` is the canonical JSON digest of the entire manifest, computed with the runtime's `core.digest`; it differs from the evidence receipt's SHA-256 of the JSON file bytes. The native-sample JSON and technical/gameplay/visual reports repeat the full identity, and the native manifest contains the actual hashed captures.

The input manifest records actual sample sources, models/textures and render configuration after production. It must contain the baseline and assembled scenes as `source`, `project.godot` as `render_config`, the Godot adapter's discoverable dependency closure, and existing asset `.import` sidecars. Every listed current file must match its hash. Dynamic or computed resource paths must be declared by the host; discovery cannot prove that undeclared dependencies do not exist. This H4 check currently supports only files inside the project, including after symlink resolution; core `contract.dependency_roots` does not extend this manifest's support. Keep canonical sample resources project-contained for this candidate. The manifest's `producer_runtime_digest` must equal `core.runtime_snapshot()['sha256']` at H4 and again during expansion. This conservatively binds the sample to the current whole skill runtime: upgrading assembly/runtime code requires applicable new sample validation, even in a new expansion run.

Technical/gameplay reports require `passed:true`, complete `passed_check_ids`, no failed checks/errors, and `gameplay_verified:true` for gameplay. The visual review needs `visual_accepted:true`, actual user actor/source reference matching H4, and `passed_feature_ids` covering the sample contract's critical features. An accepted outer stage cannot override a failed report or missing mandatory feature. The checker validates declarations/coverage and current evidence; native execution and human judgment still have to happen.

### Preserve a valid sample when expanding the plan

For each original H3 generated/hybrid source family, `sample_inputs.model_task_bindings` references its existing supplier or legacy run, original task ID, supplier operation ID when applicable, returned source model and realized model path/hash. The check reads the original ledger and frozen operation/plan, requires ready state, approved image inputs and matching output identities, and retains source/realized models in the sample input manifest. It checks realized model reachability from the actual native scene/config and resource/assembly references; the model inventory is not used as closure roots. Inventory-only downloads and unproven computed loads remain blocked. Local processing records its actual method/source and input/output hash lineage. No new provider call or duplicate ledger is created. A preserved v2 sample referenced through its hashed original workflow keeps its original H3/H4 contract; `historical_sample_sources` identifies that un-upgraded evidence. Do not rewrite old accepted H3 bytes to add current fields. Missing or pending model tasks in a new v3 sample block H4; later expansion assets are not requirements for the original sample. Record visual use and processing quality in the existing native comparison/review rather than treating task terminality as art acceptance.

The current table/recipe binds the current expansion plan digest. Set the new table's `scope_mode` to `expansion`; `production_space_ids` names exactly the spaces covered by its current recipe, and `production_view_ids` covers every baseline observation intersecting those spaces. These may expand from the original sample into other already-approved baseline/atlas spaces. The original `sample_contract.sample_space_ids`, required sample views and other sample fields stay unchanged. The expansion route must use the H4 expansion gate; it cannot enter as representative production. See `schemas/production-expansion-scope-template.json`. The sample identity continues to bind its original sample execution plan; do not rewrite a real sample as if it ran the larger plan. The expansion `sample_contract.source_production_digest` references the archived, accepted sample-production stage supplied through `sample_source_production` evidence. The sample's `consumes` points to that original production-stage digest.

The archived stage's user approval, nested evidence and original atlas/spatial/proxy dependencies must still validate. When expanding a focused H2 to new spaces, retain a small immutable workflow JSON containing the original approved H2/H3 and its shared dependencies. The current expansion table references it as `sample_source_workflow:{path,sha256}`. Reuse the original evidence files; do not snapshot the game or assets. Baseline/directions/selection must be unchanged; current H2 must retain all original detailed spaces, exact concept-view records, space-design entries and interfaces, while adding independently approved detail for new spaces. Preserve the original `focus_contract`; if the larger slice has new entry/exit or loop coverage, retain the exact original separately as atlas `sample_focus_contract`. Original `plan_view` and `section_or_volume` evidence paths/hashes remain in the expanded spatial stage; append new region diagrams instead of replacing old layout evidence. Changing original sample design requires new applicable H4 evidence. The original H4 stage and review remain bound to their frozen source context; current H3 review uses the new H2. All nested source dependencies remain hash-checked.

The current sample contract, apart from its source-stage reference, must equal the original contract. Expansion also rechecks the actual files bound by H4's input manifest: changed sample source, asset or rendering settings invalidate that sample; an independent, unreferenced new file does not. Updating hashes alone cannot preserve H4, because its approval and reports bind the old manifest digest. Keep release/priority updates in operational control, outside frozen creative workflow bytes; a new creative revision gets a new checkpoint rather than mutating a running job's frozen input.

The shared `evidence_dependencies` walker verifies and snapshots direct evidence, recursively archived sample-production evidence (including the original production table/recipe), and sample-input files. Core status and validation use these same dependencies, so nested drift cannot disappear between those checks. This permits valid H4 evidence to survive a newly approved expansion scope without laundering a changed design or weakened sample target. An expansion missing these links remains blocked.

## Purposes and recovery

- `production`: through production_plan; `workflow.production_scope='expansion'` also requires representative_sample.
- `art_proxy`: through spatial_design; no new paid model-generation task. This avoids requiring a proxy before building the proxy.
- `technical_fixture`: explicit diagnostic only; never a fallback to bypass a production blocker.

Use `delivery_mode='single_style'` for one user-selected branch and `multistyle` for multiple. All promised branches must finish. During recovery, missing/expired capability readiness returns `next:'refresh-readiness'` and `resume:'same-run'` after recovery of known submitted work; refresh that operational receipt and continue the same run. Creative, source, asset or runtime drift instead requires a revised scoped checkpoint/run, retaining recovered immutable assets. Keep status and safe rollback available. Readiness refresh does not authorize charges or revive invalid execution/spend scope. Unknown submitted provider work must be reconciled, not resubmitted.

## H5 final delivery acceptance

Only a `production` run with `playable` validation, every promised style assembled, and passing current native technical/gameplay checks can produce an H5 manifest. Fixtures and art proxies cannot be accepted as formal playable delivery. Run `delivery-manifest` and show the actual scenes, concept comparison, remaining defects, performance observations and returned `manifestHash` to the user. After the actual user's acceptance, record it with `accept-delivery`, the real message reference, acceptance note and that exact hash. The host must faithfully transcribe the response; this CLI is not a user-authentication UI and cannot supply human art or performance judgment.

H5 binds the exact plan/runtime/inputs, assembled outputs, native attempts, captures, reports and logs. A changed file or validation attempt makes acceptance stale; re-present the current delivery for a new decision. Capability expiry or operational readiness refresh alone does not erase unchanged H5 acceptance. `status` reports final acceptance separately from technical validation and readiness.

## Real commands

```sh
python3 "$SKILL/scripts/greybox.py" doctor --project "$PROJECT" --godot "$GODOT"
python3 "$SKILL/scripts/workflow_check.py" capabilities --file "$CAPABILITIES" --session-id "$SESSION"
python3 "$SKILL/scripts/workflow_check.py" stage-digests --file "$WORKFLOW"
python3 "$SKILL/scripts/workflow_check.py" plan-digest --file "$PLAN"
python3 "$SKILL/scripts/workflow_check.py" stages --file "$WORKFLOW" --project "$PROJECT" --proxy-only --capabilities "$CAPABILITIES" --session-id "$SESSION"
# Optional API-price collection for the legacy Lux route:
python3 "$SKILL/scripts/greybox.py" quote-preview --project "$PROJECT" --file "$DRAFT_PLAN" --output "$PROJECT/art/quotes/proposal-01.json" --capabilities "$CAPABILITIES" --session-id "$SESSION"
# After the actual H3 decision, freeze the production workflow and plan:
python3 "$SKILL/scripts/workflow_check.py" plan --file "$PLAN" --project "$PROJECT" --capabilities "$CAPABILITIES" --session-id "$SESSION"
python3 "$SKILL/scripts/greybox.py" plan --project "$PROJECT" --file "$PLAN" --run-dir "$RUN" --capabilities "$CAPABILITIES" --session-id "$SESSION"
python3 "$SKILL/scripts/greybox.py" refresh-readiness --run-dir "$RUN" --file "$CAPABILITIES" --session-id "$SESSION"
python3 "$SKILL/scripts/greybox.py" delivery-manifest --run-dir "$RUN"
# Only after the actual user reviewed and accepted this manifest:
python3 "$SKILL/scripts/greybox.py" accept-delivery --run-dir "$RUN" --actor user --source-ref "ACTUAL_MESSAGE_REFERENCE" --note "ACTUAL_ART_PLAYABILITY_PERFORMANCE_DECISION" --manifest-hash HASH
```

## Portable supplier execution

After H1/H2 and the actual portfolio-bound H3, use a project-contained supplier run directory. Preparation records the operation graph; stepping can submit authorized work and is not a dry run:

```sh
python3 "$SKILL/scripts/greybox.py" supplier-jobs prepare --project "$PROJECT" --run-dir "$SUPPLIER_RUN" --registry "$REGISTRY" --portfolio "$PORTFOLIO" --selection "$H3_SELECTION" --workflow "$WORKFLOW" --capabilities "$CAPABILITIES" --session-id "$SESSION"
python3 "$SKILL/scripts/greybox.py" supplier-jobs status --run-dir "$SUPPLIER_RUN"
python3 "$SKILL/scripts/greybox.py" supplier-jobs step --run-dir "$SUPPLIER_RUN" --max-submissions 1
```

For expansion add `--expansion` to preparation; H4 then applies. Readiness refresh uses `step --registry REGISTRY --capabilities CAPABILITIES --session-id CURRENT` with unchanged approved bindings. If a submission is unknown, first recover its real task identity and record it with `supplier-jobs reconcile --run-dir RUN --operation-id OPERATION --task-id ACTUAL_TASK --note ACTUAL_RECOVERY`, then step to poll/fetch. Never invent a task ID to unblock the graph.

The bridge dispatches the selected binding: bundled Lux, supported built-in vendor API operations, or explicitly installed command adapters. Registry presence alone does not establish configured credentials, supported operation parameters or live execution evidence; inspect that binding and operation first. Fetched assets still need normalization/calibration and separate Godot/native assembly, sample and H5 evidence. Supplier-run completion is not playable or aesthetic acceptance. H3 rate estimates, optional API quotes and actual consumption remain separate records.

Use `--require-lux` on capability checks only when the planned route needs it. The above native execution commands are the bundled Godot/Lux path, not cross-engine or arbitrary-supplier dispatch. Current `--help` is the command authority. Hash utilities are read-only; they do not approve artifacts. There is no `generate-concept`, automatic checkpoint authoring or automatic assembly compilation command. The host uses actual image/engine tools and writes truthful records.

A plan's workflow reference names its immutable checkpoint `path`, `sha256` and `production_scope`. Readiness comes from the explicit capability input and current session. `status` reports readiness separately from creative approvals. Templates and receipts are not substitutes for the artifacts they describe.

## Legacy plan, assets and quote recovery

For the legacy plan/run route, keep case/shared/style outputs and run records inside the actual project, outside the installed skill. `greybox-art-plan` schema 1 binds plan/style IDs, titles, native scene/camera, validation steps and logical-owner bindings. Bindings name hidden source visuals, anchor, scale and material policy; the bundled fixture provides executable field examples. Observe the original gameplay state transitions, not merely successful hook invocation.

`normalize.space` defaults to world; owner-local normalization must use the complete parent transform. Always normalize the immutable original asset rather than accumulating transforms from a previous result; material processing remains separate. Computed resource paths belong in `contract.source_paths`. Explicit read-only `contract.dependency_roots` can extend core source checks but do not extend H4's project-contained sample-input rule. Multiple returned GLBs require an explicit selected asset in the revised reuse plan. Rollback must preserve unrelated user edits.

`allowQuoteRefresh` only reuses authorization for unchanged scope, region, parameters and approved credit ceilings. Retain submitted tasks' `submissionCredits` when calculating reserved cost plus unsubmitted work. A pending quote refresh cannot activate before all required refreshes complete; unknown cost or expanded scope needs resolution. Recover original submitted IDs even after a runtime upgrade; new runtime-bound sample/production evidence follows the current validation rules above.
