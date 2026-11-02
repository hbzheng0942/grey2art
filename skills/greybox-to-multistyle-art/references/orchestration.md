# Delegation, readiness and incremental production

## Ownership and dispatch

One host owns scope and critical-path decisions; one integrator publishes shared scenes, IDs and interfaces. Delegate only ready, nonoverlapping producers: asset families, controlled geometry, materials or review. Without subagents, keep the same dependencies; provider concurrency uses the [common executor](execution-contract.md) and does not require multiple agents. See [capabilities](capability-preflight.md).

Each task binds approved input hashes, owned IDs/writable paths, read-only neighbors and interfaces, camera/state/material context, completion evidence, blockers, time/call/spend caps and recovery rules. Workers preserve others' edits and return actual outputs/hashes/unresolved issues. Persistent task/provider records remain authoritative across sessions and hosts. No worker supplies user acceptance.

Use three compact views of the same IDs: semantic space/gameplay constraints, art design/assembly ownership, and executable task dependencies. Art regions, assemblies and runtime streaming cells can differ; explicitly map their IDs and preserve interfaces rather than assuming one-to-one partitioning.

After H3, ready tasks within the authorized complete-sample scope can stream: returned models enter essential import/calibration while other generation runs; environment and interfaces progress independently. An unrelated wait does not stop ready work, but an assembly cannot finish with a missing mandatory dependency. Placeholder structure never satisfies concept-feature acceptance. [Production control](production-control.md) governs lead style, pilots, unfinished combinations and cumulative repair allowance. Its operational file does not authorize charges.

## Complete composition before local polish

After input/scope/resource checks, prioritize:

1. `blocker`: gameplay, import, spatial or verification failures, including view-wide material/exposure faults.
2. `composition`: principal forms, environment and complete-sample dependencies.
3. `style`: medium-scale forms, materials and joins.
4. `polish`: minor decoration/seams or optimization without an observed performance problem.

Use concrete rationale; a small functional cue can be critical and sky can be inapplicable indoors. Each required environment/contact/lighting layer needs an owner and visible output. S6 uses existing greybox/reuse/cheap geometry to answer production questions; stop once those are resolved. H4 uses actual art and gameplay states together. Integrate returned assets early after essential unit/axis/material/contact checks; detailed cleanup waits for a demonstrated defect or explicit requirement. See [assembly method](hybrid-production.md).

`visual-completeness-v1` requires per-task `visual_priority:{tier,rationale}` and `work_unit:{observable_result,stop_condition,active_minutes_budget}`. Prerequisites inherit a higher-priority consumer's tier but cannot bypass readiness. Legacy graphs report `unclassified_tasks`; classify them before new full production.

Keep changing observations at graph level, outside immutable task specifications:

```json
{"largest_visual_gap":"environment","observations":{
  "environment":{"active_minutes":25,"external_wait_minutes":0,"no_progress_rounds":2,"ready_wait_rounds":0},
  "hero":{"submission_state":"unknown","external_wait_minutes":30}}}
```

`largest_visual_gap` is an image-grounded host assessment, not machine vision. Within a tier, two no-progress rounds yield to a ready alternative; longer ready waits then break ties before critical-path estimates. Waiting cannot promote polish over missing composition. `submission_state:submitting|unknown|recovery_required` blocks repeated recommendation of that task: reconcile its original ledger.

Around 25 active minutes or two no-progress rounds triggers `reassess_at_safe_boundary`; external waits are separate. Check whether the largest gap decreased. Change method/rotate on stagnation; continue a necessary progressing blocker with a reason and a new bounded work unit. This reminder kills no process, waives no blocker and grants no paid retry. Preserve prior evidence. Repeated defects use cumulative repair commands; a new worker/run/script/issue label cannot reset the allowance.

## Capacity and shared publication

Use the common executor for continuous multi-task submission and polling. The
workgraph below remains a read-only planning helper. Reserve exact requests in
their owning ledgers, bind confirmed account pools, then run/start the queue.
Slow network actions have killable total deadlines; downloads use separate
capacity. Native claim/record remains agent-driven until an actual independent
host bridge is implemented and verified.

Track image quota, each supplier wallet/account's submit rate and in-flight work, local CPU/GPU, geometry jobs, import/publication lock and review capacity separately. Multiple connectors can share one wallet; more agents do not increase its quota. Reserve allowances before dispatch, keep job IDs and reconcile unknown results. External waiting need not occupy every worker.

Optional cleanup/rig/motion/native subgraphs use only necessary operations. A manual handoff has saved input/output contracts and `waiting_human`, not a failed-generation label. Switching suppliers needs the approved fallback/budget. Only the integrator publishes shared native changes. Reuse canonical resources; isolate writable work with supported clones/reflinks when necessary, never whole-project copies per worker.

## Workgraph helper boundary

Start from `schemas/workgraph-template.json`:

```sh
python3 "$SKILL/scripts/workgraph.py" inspect --project "$PROJECT" --file "$WORKGRAPH"
python3 "$SKILL/scripts/workgraph.py" review --project "$PROJECT" --file "$REVIEW_ROUNDS"
```

`inspect` validates declared dependencies, hashes, owned writes, capacities and publication ownership, then recommends a nonconflicting wave. Completion binds `spec_sha256` from inspection, direct `dependency_sha256`, hashed `outputs`/`evidence` and every required `criteria_passed` ID. Changed specs/dependencies stale completion. Fairness/time observations do not change these fingerprints. Running tasks need owner leases, reserving declared resources/locks in recommendations. Paths remain project-contained after symlink resolution.

The helper does not launch agents, query suppliers, acquire real distributed locks, verify process liveness or schedule per-assembly engine calls. The executor can release ready style branches; actual host dispatch and reconciliation remain necessary. Declared upstream output not yet produced means wait; a changed/missing external input is stale.

`review` consumes schema 1 `kind:'greybox-review-budget'`, limits `max_rounds/max_minutes/max_calls/max_no_progress_rounds`, blocking/polish issues and actual rounds. `max_calls:0` allows local review. Measured progress names an issue, `direction:increase|decrease`, metrics and hashed before/after evidence. Qualitative progress uses `mode:'observed'`, actual `reviewer`, criterion, concrete observation and hashed before/after files. Both must be current and different. This records judgment, not automated aesthetic proof.

While blockers remain, polish improvements cannot reset their stagnation count. Repeating a hypothesis is not a new method; hypotheses never reset no-progress. Exhausted budgets do not pass blockers. The report always keeps `accepted:false` and `paid_retry_authorized:false`; use [review and decisions](human-decisions.md) to repair or present a concrete unresolved tradeoff.

## Local invalidation and continuity

A family change invalidates dependent instances/assemblies/views; interface edits affect their neighbors; material edits affect look evidence and dependent perceptual mechanics; gameplay edits need affected baseline checks. Preserve unaffected assets/decisions. This planning policy does not remove the execution core's conservative source snapshot, which can still require a new run after unrelated source drift.

Retain current, last verified and named milestone outputs plus small diffs/evidence. Record source revision, changed files, hashes and native observations. Respect ownership before cleanup. [PLAN/PROGRESS/FOCUS](continuity.md) references existing tasks/ledgers for steering and handoff without adding approvals or budgets.
