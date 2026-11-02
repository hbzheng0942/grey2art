# Production control: finish a visible result before expanding work

Use one `art/<case_id>/shared/production/CONTROL.json` per case. It controls execution order, processing pilots, unfinished combinations and cumulative repairs. It is not a second approval, asset, charge or cost ledger. PLAN/FOCUS reference it; creative decisions and paid operation scope remain in the existing workflow and supplier records. Never put mutable batch state into the frozen workflow or approved executable plan.

## Start explicitly

```sh
python3 "$SKILL/scripts/production_control.py" init --project "$PROJECT" --plan "$PLAN" --workflow "$WORKFLOW" --lead-style "$LEAD_STYLE"
python3 "$SKILL/scripts/production_control.py" inspect --project "$PROJECT" --control "$CONTROL"
python3 "$SKILL/scripts/production_control.py" configure --project "$PROJECT" --control "$CONTROL" --input "$SETTINGS" --expected-revision 1
```

Initialization is unfinished. Configure actual processing families and the minimum combinations that produce an inspectable native result, using [settings template](../schemas/production-control-settings-template.json). `configure` accepts `families`, `combinations`, `max_open_combinations`, and `style_phases`. It preserves claims, repairs and history; use the revision returned by `inspect` to avoid overwriting another coordinator's update. One integrator owns configuration. Other workers report evidence or bounded repair results.

- A family declares `profile: {structure, method, skeleton, engine}`, stable `asset_ids`, the necessary `pilot_asset_ids`, and `required_interactions`. Keep different topology/processing/skeleton risks separate. A pilot may include the few dependencies necessary to exercise a real interaction; it is not a pilot per asset and cannot be the whole unknown catalog by default.
- `runtime_profile` is either `null` or one hash-bound [runtime profile](../schemas/runtime-profile-template.json). All workers use the same profile. Null means no numeric budget has been established; it cannot produce a `budget_passed` claim. Target budgets and actual performance verification remain different facts.
- A combination names one `style_id`, all necessary `asset_ids`, its `required_interactions`, and `state: queued`. Default `max_open_combinations: 1` counts unfinished combinations, not meshes. Once a combination starts, its remaining necessary assets may still be submitted; the limit must not prevent the last required pieces from arriving. Define a new combination for changed/reopened work while keeping the previous evidence.
- Preserve all user-selected styles. Initially only the lead style produces and assembles art. Existing supplier tasks always recover; reference inspection and other independent preparation may continue. Shared assets can belong to the lead combination without making every sibling style active.

New `core.prepare` production and `supplier-jobs prepare` require configured control. Both real new-submission paths consult the same case record. New native assembly, including a pure-reuse plan, also checks the active style. Historical runs without control may query/download already submitted work, but may not issue new generation. Technical fixtures and no-paid art proxies remain separate modes.

## Pilot, integrate, then release work

Use actual native evidence from the main camera, not asset counts or a command exit code. A family pilot covers the processing path it needs: import/material/scale, plus deformation, necessary interaction and continuity where applicable. Prefer verified provider postprocessing where useful; do not remesh or rig assets that do not need it. The static Blender backend does not become a general repair pipeline by being available.

`qualify` takes `{"family_id":"...","evidence":{"path":"...","sha256":"..."}}`. Its [native composition report](../schemas/native-composition-check-template.json) binds actual exported asset hashes, engine, main camera, inspected media, reviewer, and the relevant checks. Qualification is reusable only with the same structure/method/skeleton/engine/runtime-profile signature and unchanged evidence. Other family assets then become eligible within the active combination. Qualification never grants new paid scope.

For local/reused assets, `start` takes `{"combination_id":"..."}` and opens the same bounded integration slot without an API call. New generation opens its necessary combination automatically. `integrate` takes `{"combination_id":"...","evidence":{"path":"...","sha256":"..."}}`; it verifies the whole combination's declared asset and interaction coverage, then releases the slot. This is internal evidence, not another human approval or H4.

Native report details:

- `checks.imports`, `materials`, `scale`, `visibility` must pass. Interaction families/combinations also require `interaction_continuity` and matching `covered_interactions`. A zero contact distance cannot substitute for visibility or continuous interaction.
- `assets` maps each stable asset ID to its actual exported path/hash. `media` contains project-contained main-camera image/video references with `camera_id`. Main-camera image bytes are decoded. Review the actual media; the checker cannot judge aesthetics or authenticate a claim.
- Key interactions use a continuous capture (`continuous: true` on a video/GIF item) or a timed frame sequence. For frames, every media item declares `sequence_id` and `time_seconds`; `continuous_sequence` declares `id`, `from_seconds`, `to_seconds`, `max_gap_seconds`. At least three ordered frames must cover that interval without omitted declared gaps. Record an appropriate capture cadence for the action; sparse unrelated screenshots are not continuity evidence.
- With a runtime profile, report `runtime_target` matching its target environment and `targets_by_asset: {asset_id: [{budget_id, value, ...}]}`. Each asset lists its applicable budget settings. A one-asset report may use legacy `targets`. Hard-limit violations reject the report; a changed target requires a reason and measured evidence. This validates consistency, not frame rate.

The first style is complete for release when its required representative sample has actual valid H4 acceptance, including native gameplay/technical and visual requirements. Further cosmetic polishing does not delay releasing the other selected styles. `activate` takes `{"active_styles":["style-b","style-c"]}` and optionally `--workflow` pointing to the authoritative/archived accepted lead workflow. It verifies that lead H4 without rewriting H1 or asking for another approval. Each later style still needs its own required H2/H3/H4 and risk-specific evidence; final delivery covers the complete selected set.

## A repair does not restart when the script or agent changes

Use stable asset IDs from the approved plan. Keep one defect record and its cumulative actual work, even when changing script, method, run or worker. Ordinary work still uses the 25-minute reassessment reminder; expensive repeated defects use the bounded record below. Cloud wait does not count as active repair minutes.

Reuse a registered production asset through its original `asset_id`, including when its source is now a local file. Do not replace that binding with a bare file path or invent a new asset ID to escape the repair record. The current checker follows declared identities; it does not automatically discover every arbitrary file alias or external script's lineage.

All commands use `--project`, `--control`, and an action JSON via `--input`:

| Command | Input |
| --- | --- |
| `open-repair` | `issue_id`, `asset_ids`, `defect`, `max_attempts` (default 3), `max_active_minutes` (default 30) |
| `begin-repair` | `issue_id`, changed `method`, `owner`; optional exact `submission` permit below |
| `finish-repair` | `issue_id`, actual `active_minutes`, evidence path/hash, concrete `observation` |
| `resolve-repair` | `issue_id`, `action: verified_fix\|verified_fallback\|defer`, `note`; passing native `evidence` for either verified action |
| `reconcile-claim` | `claim_id`, original run-ledger `evidence` path/hash, `note`; ready-but-defective outputs additionally need `repair_issue` and failed native `quality_evidence` |

Start the attempt before doing the work. An unfinished attempt blocks unrelated repetitions. A repair that invokes a supplier includes `submission: {asset_id, operation, run_dir, request_digest}` in `begin-repair`. This permits only that exact next submission; it does not override H3, pricing, supplier account, or unknown-task safeguards. For supplier jobs the digest is `core.digest(operation)`; for the direct Lux runner it is `core.digest({operation, parameters})` from the persisted quoted row. The normal runner still submits, queries and downloads; `finish-repair` records the observed result afterwards. Local repairs omit the submission permit.

Case claims bind stable asset/operation identity across runs. Query/download never requires a fresh claim. Only a confirmed original `failed`, `cancelled` or `rejected` run can be reconciled for another approved attempt. A `ready` result can be replaced only after a native failure report binds that exact original output, a defect is tracked, and the next request has a bounded repair permit. Unknown/inflight results cannot release their claim. Claims retain previous attempts; changing run/agent/script does not clear the repair allowance. Unchanged successful assets should be reused.

When the allowance is exhausted, apply a verified known fallback or defer that defect; continue unaffected mature families. Defer does not pass the asset or erase a required interaction. Do not invent progress, endlessly rename defects, or silently relax a hard budget. These are host-managed records and supported-entrypoint guards; they do not control arbitrary external scripts or provide automatic visual judgment.

## Scheduling and progress

The optional workgraph `production_control` field points to this file. Tasks may declare `asset_ids` and `control_action: produce|integrate|repair|prepare` (default produce). Production respects active-style, family and backlog advice; repair/integration/preparation tasks remain available to resolve the very blockage they are working on. The actual production runners independently enforce their checks even if the workgraph helper is skipped.

Report the latest complete native composition, the next inspectable result, active combinations and the few remaining blockers. `inspect` returns active/queued styles, per-style phases, qualified families, integration backlog and cumulative repair blockers. Asset counts are inventory; they do not imply H4 readiness or a delivery percentage.
