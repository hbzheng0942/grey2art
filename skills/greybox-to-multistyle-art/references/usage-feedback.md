# Usage feedback from real tasks

Record meaningful friction by default while doing the user's task. Use current
evidence, the existing case PLAN/PROGRESS and original repair/job ledgers. The user should
not have to fill in a retrospective form. Do not start another evaluation task,
call a model per tool event, or copy transcripts, games or assets for reporting.

## Record only what changes the next action

Record a failure, user correction, repeated human rescue, significant repair
method attempt, workaround, resolution or reopening when it changes the next
action. Normal art choices and scope changes can explain a change in direction, but must not inflate rescue counts. One
intervention episode may span several messages: reuse its `episode_id`.

Start with [the observation template](../schemas/usage-feedback-template.json).
Fill actual facts; remove unused optional fields. `basis` distinguishes
`observed`, `user_reported` and `agent_inferred`. `source_ref` points to the actual
message, tool result or inspection. Never infer a model from a previous chat.
Tag relevant mechanisms such as dynamic spawning, support changes, camera
occlusion or character contact, rather than asserting support for a whole genre.

Optional `triage` records a reported category (`skill_guidance`, `agent_execution`,
`host_tool`, `provider`, `source_project` or `unknown`) and severity (`blocker`,
`major`, `minor` or `unknown`). These are sourced claims, not an automatic root-cause
judgment. Add a short `fingerprint` only when a maintainer has confirmed the same
mechanism across reports; otherwise omit it.

```sh
python3 "$SKILL/scripts/greybox.py" feedback record \
  --project "$PROJECT" --case "$CASE" --input art/usage-observation.json \
  --writer scene-integrator --expected-revision 3 \
  --checkpoint-sha256 "$CHECKPOINT_SHA256"
```

The case must already have PLAN/PROGRESS. If setup fails before a case exists,
keep a minimal project-local pending draft with the actual source, expected/actual
behavior and known environment. Once a case exists, append it through
`feedback record`; the draft alone is not a recorded observation. Do not create a
dummy task or fabricate approvals for reporting. Use the designated writer and
current revision/hash.
The command writes an immutable observation and references it through a normal
progress event. Repeating the same event ID and payload is idempotent; reuse an
`issue_id` across attempts/sessions, but assign a new event ID to new facts.
Conflicting payloads under one event ID are rejected. Unreferenced files from an
interrupted or rejected write are not counted as recorded observations.

The observation-only append preserves the whole task plan and approval state;
it can report a stale input or missing workflow without requiring production
readiness. An available checkpoint must still match the supplied hash. If it is
missing, supply the last known hash and retain the returned unavailable flag.
Normal PLAN edits, FOCUS and dispatch keep their existing source checks. This
reporting path cannot resume work or change its status.

Keep expected versus actual behavior explicit. Reference relevant project-local
files by path/hash; do not paste full logs or private recovery data. A source
label is a claim with provenance, not proof of independent observation. Each record
binds the recorder package version and manifest hash. For a late report these
identify the recorder, not necessarily the package that caused the earlier failure.

`project_status` and `skill_status` answer different questions. A project may be
`workaround` or `fixed` while the Skill issue remains `untriaged` or `candidate`.
Declaring a Skill issue `verified` requires a regression observation with distinct
before, after and holdout evidence. Those hashes establish traceability; they do
not prove image quality, a root cause, human acceptance or production approval.
Reopen a recurring issue rather than starting a fresh success record.

Costs are optional, sourced measurements with a stable `measurement_id` and
scope. Unknown values stay null. Do not sum overlapping intervals or turn cached
input tokens into a currency estimate. Use existing CONTROL repair attempts and
supplier receipts as their authorities; the recap references them without
copying their mutable state or charging an event twice.

## Recap on transition, failure or pause

```sh
python3 "$SKILL/scripts/greybox.py" feedback recap \
  --project "$PROJECT" --case "$CASE"
```

This derives `feedback/recap.json` and `feedback/recap.md` inside the case. Normal
failure/review/handoff/pause/completed progress events and stage changes also
refresh them after progress is safely committed. Once observations exist,
subsequent progress updates keep the report current. Do not wait for a successful
delivery: abandoned and interrupted work are useful evidence too. Recap failure
does not roll back the task; inspect the reported warning and rerun this command.

The recap covers sourced issues, known rescue episodes, creative changes,
attempts/results, unresolved issues, unclassified progress failures and original
CONTROL repairs. It presents known cost measurements without inventing a full
accounting total. FOCUS includes a short unresolved summary for the next session.
Absent feedback is incomplete coverage, not a claim of trouble-free execution.

The Markdown recap shows up to 12 issues, repairs, measurements and warnings,
with at most three recent events per issue and bounded text. Current issue state,
latest reported repair method, next test and attempt/event counts point to the
full JSON history. It displays the latest event's recorder version/manifest and
actual host/model/engine; unknown values stay unknown. A reported method is not
a verified fix. Do not hand-edit this derived file to preserve findings: append
new facts instead.

At failure, pause, handoff and completion, show the actual recap path alongside the
result and coverage gaps. Before closing a successful stage, check current evidence
for user rescue or rework that has not been recorded. This is a short check of the
active task, not a full transcript scan or a new user questionnaire.

FOCUS and automatic refresh verify the small observation records, but do not
rehash models or other large evidence on every resume or progress update. Artifact
freshness is explicitly not checked in both JSON and Markdown; explicit recap
or export verifies those receipts. A new failure under a previously closed issue
reopens it automatically, and each event retains its original stage and context.

At a boundary, use these facts to write a short causal recap: what blocked the
result, what intervention changed it, what remains, and the next minimal test.
Keep an explanation hypothetical until evidence distinguishes Skill guidance,
agent execution, host/tool, provider and source-project causes. The tool does not
run a language model or automatically classify all user messages.

## Turn a useful issue into a regression candidate

`next_test` should describe the smallest repeatable check: frozen inputs, expected
failure, a correct input that must pass, and a changed layout/relationship not
used to devise the fix. Reuse canonical inputs by hash. A suggested test is not
an executed regression or proof that the Skill defect is closed.

```sh
python3 "$SKILL/scripts/greybox.py" feedback export \
  --project "$PROJECT" --case "$CASE" --output art/feedback-review
```

A user can ask “export this task's usage feedback” / “导出这次使用反馈”; locate the
existing case and run this command without asking them to fill a form. It creates
`usage-feedback.md`, `usage-feedback.json` and `issue-draft.md`. The Issue draft
contains reported environment, expected/actual behavior, attempts and remaining
reproduction gaps; it does not invent missing steps. Share Markdown and JSON
together so maintainers retain the diagnostic history.

Export restricts fields and redacts common sensitive values. It omits raw ledgers,
source message text and recovery metadata. Review remaining free text before sharing; arbitrary
private content cannot be reliably anonymized by pattern matching. This command
does not upload, send messages, open external issues or modify the Skill.

For product iteration, group candidates by mechanism, stage, observed impact and
evidence quality. Keep project-specific fixes and uncertain reports separate.
Promote a method only after replaying the original failure, a valid case and an
unseen variation. Preserve actual host/model/engine coverage and retain failed
trials; no blanket multi-agent review or full production rerun is required.

## Collect reports from several users

A maintainer can collect reviewed exports locally without copying games or assets.
Keep one anonymous stable `sample_id` for the same case across updated exports:

```json
{
  "schema": 1,
  "kind": "greybox-feedback-collection-input",
  "exports": [
    {"sample_id": "user-a-case-1", "path": "inbox/user-a/usage-feedback.json"},
    {"sample_id": "user-b-case-1", "path": "inbox/user-b/usage-feedback.json"}
  ]
}
```

```sh
python3 "$SKILL/scripts/greybox.py" feedback collect \
  --project "$COLLECTION_ROOT" --input manifest.json --output review
```

Paths stay inside the collection root. `review/collection.md` and JSON show
reported occurrences, unresolved issues, known intervention episodes and actual
version/environment coverage. Identical exports are deduplicated; updated exports
of one sample are not new users. A manifest entry may supply
`"issue_fingerprints": {"case-local-issue-id": "confirmed-mechanism-id"}` after
manual triage. Only explicit fingerprints establish a confirmed grouping; shared
stages or mechanism tags produce similarity candidates. Neither establishes a
root cause by itself. Case-local issue IDs must not merge unrelated users.

These are observed reports, not a population failure rate or complete cost total.
Collection creates local analysis files; opening or linking an external Issue is
a separate action requested by the user.
