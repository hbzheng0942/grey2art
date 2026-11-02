# Case continuity and resuming work

Keep one stable case directory inside the owning game project. `PLAN.json` is the readable structured entry: current objective, gameplay/spatial constraints, quality floor, current stage, remaining work, pending proposals and references. `PROGRESS.jsonl` appends key sourced events. Existing workflow checkpoints, workgraphs, run and supplier ledgers retain approval, budget, request IDs, unknown outcomes and execution facts. Never paste those mutable facts into another ledger or copy a game/assets tree as a checkpoint.

Use `schemas/continuity-template.json` as an intentionally unfinished input. Populate actual paths and user-message references. `references.workflow` points to the current checkpoint; `workgraph` is optional during early planning. `approved_inputs` bind exact existing path/hash pairs. `ledgers` lists existing run/supplier/claim JSON files used by the case. An empty list means no ledgers were declared, not proof that no request was submitted.

Operational production order, active styles, processing pilots, combinations and repair history live in the separate case-local `art/<case_id>/shared/production/CONTROL.json`, owned by `production_control.py`. PLAN may reference it using `references.production_control`; FOCUS otherwise discovers that canonical path. Do not duplicate its mutable facts into PLAN or rewrite H1 selection to change priority. FOCUS inspects only active styles with their individual phases, and keeps queued styles visible. Without control it conservatively follows the style in `current_stage`; another style's accepted H4 does not force this style into expansion. This fallback is navigation only, not an exception to execution's operational-control requirement.

```sh
python3 "$SKILL/scripts/progress.py" init --project "$PROJECT" --case art/continuity --input art/continuity-input.json
python3 "$SKILL/scripts/progress.py" focus --project "$PROJECT" --case art/continuity
python3 "$SKILL/scripts/progress.py" classify --message 'Meshy 会不会更好？'
```

FOCUS is generated on demand, without a third maintained state file. It includes the objective, current stage and missing evidence roles, current workflow integrity result, declared largest visual gap, recommended ready work, bounded-work reminders, authorization source references and unknown submissions in declared ledgers. It does not authenticate a user, refresh account capabilities, certify artwork or authorize dispatch. Current workflow/quote/ledger gates remain mandatory. Missing or stale files fail closed; return to their owning checkpoint to repair them.

At a new message, read FOCUS and interpret the message in context. `classify` is a conservative triage aid: `inquiry`, `proposal`, `change`, `approval_candidate`, `pause`, `replace`, `continue`, or `clarify`. It never mutates PLAN or grants approval. “Meshy 会不会更好” leaves the chosen supplier intact; “这批改 Meshy” changes that batch and requires rechecking its affected reference/quote scope. “补 BOM” repairs the current handoff. “继续” resumes only work already authorized. An actual approval must be scoped and recorded through the existing human workflow gate. Explicit new instructions take precedence over the old plan; discussion alone does not replace it.

Read FOCUS again before a stage handoff, affected execution/publication, cross-agent or session transfer, and after context compression. Preserve the returned `resume_token` in the worker's input contract. Check it before publishing or dispatching affected work:

```sh
python3 "$SKILL/scripts/progress.py" check --project "$PROJECT" --case art/continuity --input art/worker-resume-token.json
```

This compares plan revision, plan bytes, workflow checkpoint bytes and the referenced operational control bytes when present. A stale worker retains its useful outputs but must rebase/review against the new plan before publication. The token does not replace task input/dependency fingerprints, current capability checks or spend authorization.

One stable designated `writer` (normally the integrator) changes the shared PLAN. Other agents deliver bounded outputs and handoff observations to that writer. `update` takes `{"changes":{...},"event":{...}}`; `event` takes one event object. Both require the currently read revision and checkpoint hash:

```sh
python3 "$SKILL/scripts/progress.py" update --project "$PROJECT" --case art/continuity --input art/plan-update.json --writer scene-integrator --expected-revision 3 --checkpoint-sha256 "$CHECKPOINT_SHA256"
```

Every successful event advances revision, avoiding lost updates between event-only and plan-edit writers. Event types are `requirement`, `proposal`, `change`, `decision_reference`, `completed`, `failure`, `review`, `handoff`, `pause`, and `resume`. Each needs a concise summary, actual `source_ref`, affected `scope` and optional current path/hash evidence. Record milestones, meaningful decisions, changed methods, failures, review and handoff; omit polling and routine tool chatter. A `decision_reference` points to the real approval; it does not create one. Status changes require the corresponding sourced event. The host must verify completion, pause and resume intent, because editable files cannot authenticate it.

Writes reuse the runtime's cross-platform exclusive process lock, revision compare-and-swap and atomic file replacement. A small task-owned `.progress-transaction.json` repairs an interrupted PLAN/PROGRESS update without appending the same event twice. FOCUS refuses an unfinished transaction. The designated writer runs `progress.py recover --project "$PROJECT" --case art/continuity --writer scene-integrator`, then reads FOCUS again. Recovery finishes only the saved transaction; it creates no new event or authority. Rerunning an update also recovers first, then rejects a stale expected revision if the original change already committed. Unexpected changed plan/progress bytes stop recovery rather than overwriting unique work. Preserve the journal and inspect the concrete conflict; never remove a live writer lock.

Unknown/submitting/reserved/attempted/recovery-required ledger entries stay visible across proposals and checkpoint changes. Reconcile the original operation before reissuing it or changing provider; unrelated local ready work can continue. FOCUS examines only declared ledger paths and states, not the remote service. Historical PROGRESS absence is never evidence of no charge. This release provides explicit recovery commands and entry discipline, not automatic hooks for every possible host action.

## Usage feedback without a second task plan

Use [usage feedback](usage-feedback.md) for meaningful failures, user rescue and
repair-method results. Immutable observations are referenced by these existing
events; recap and FOCUS summaries are derived views, not another issue ledger.
After a committed failure/review/handoff/pause/completed event or stage change,
the tool refreshes the local recap. Reporting failure is returned as a warning
and cannot undo the committed progress event. A repeated idempotent feedback
record does not increment the plan again. Normal event CAS still applies.

FOCUS shows a bounded unresolved summary without rewriting case files. Review
those issues before continuing; a runnable command does not close a past defect.
Ordinary failures without structured observations remain visible as unclassified
events. No transcript listener is implied: record corrections from actual
messages when the current host exposes them. Keep polling and raw tool chatter
in their existing job records instead of advancing PLAN for each call.

At failure, pause, handoff and completion, include the actual `feedback/recap.md`
path and missing-coverage notice in the task update. Before closing a successful
stage, record meaningful user rescue or changed repair methods still visible in
the current evidence. A setup failure before PLAN exists can remain a minimal
project-local sourced draft until a real case exists; it grants no task authority.

The readable recap stays brief; JSON retains full event history and recorder
identity. On “导出这次使用反馈” / “export this task's usage feedback”, use the existing
case to produce the Markdown, JSON and local Issue draft described in
[usage feedback](usage-feedback.md). Review free text before sharing.
