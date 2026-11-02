# One task, one explicit execution entry

Use `task-context` when starting a case or resuming it after a host, model, tool or installed-skill change. It stores one `execution_context` inside the existing `PLAN.json`, using its designated writer and revision/checkpoint CAS. It creates no new approval or execution ledger.

The current process inspects its actual skill root, CLI path, manifest and source bytes, Python launcher/environment, and actual Godot/Unity root. It lists known alternative installations without invoking or changing them. A different installed version is a possible competing entry, not proof that either package is corrupt.

Supply the current host report as a small local JSON document. Values must come from the actual current host/tool metadata. Omit unavailable fields or use `null`; never infer the model from a previous conversation, an environment variable or an assistant's assertion.

```json
{
  "host": "workbuddy",
  "session_id": "ACTUAL_CURRENT_SESSION_ID",
  "model": null,
  "tool_schema_sha256": null,
  "source_ref": "ACTUAL_HOST_METADATA_REFERENCE"
}
```

If the host exposes the actual available tool schema, fingerprint that schema's canonical JSON and report the SHA-256. This is reported context, not authentication, invocation qualification or paid-work approval. Unknown model/schema fields remain visible as unverified even when all observed identity fields are unchanged.

Run through the selected package's explicit Python and `scripts/greybox.py` path:

```bash
python /SELECTED_SKILL/scripts/greybox.py task-context inspect \
  --project /ENGINE_PROJECT --case art/CASE --session-report /LOCAL/session.json

python /SELECTED_SKILL/scripts/greybox.py task-context pin \
  --project /ENGINE_PROJECT --case art/CASE --session-report /LOCAL/session.json \
  --writer DESIGNATED_WRITER --expected-revision CURRENT_PLAN_REVISION \
  --checkpoint-sha256 CURRENT_WORKFLOW_SHA256 --source-ref CURRENT_CONTEXT_REFERENCE

python /SELECTED_SKILL/scripts/greybox.py task-context run \
  --project /ENGINE_PROJECT --case art/CASE --session-report /LOCAL/session.json \
  -- image status --local --job-dir /ORIGINAL_IMAGE_JOB
```

`inspect` returns the current identity, competing entries, PLAN revision/checkpoint hash and routes for declared ledgers. `check` performs the same inspection with a required case and exits nonzero when unpinned or changed. `pin` records an operational choice through the existing CAS; it needs actual host/session values, while unavailable model/schema values may stay unknown. It does not add a human-approval step. A source package with a stale manifest cannot be pinned.

`run` checks the pin before starting the fixed Python launcher and fixed package CLI. Source, entry, interpreter, engine root, host/session, reported model or reported tool-schema drift stops this invocation before the forwarded command starts. A known identity becoming unknown is also drift. Arguments are executed with the engine project as working directory; use absolute paths for existing ledgers and files. A forwarded `--project` must match the pinned root. Existing workflow, capability, quote and job gates still run in the selected CLI.

On drift, inspect the changed fields, refresh the affected current capabilities/bindings, then repin with the current PLAN revision. Retain creative approvals, references, task IDs and costs in their owning ledgers. Repinning never makes old source/runtime evidence current and does not disable a legacy run's own drift gates. Do not switch versions solely to bypass a failed gate. `FOCUS` displays the pin but does not claim to have checked the current host session.

## Resume by actual ledger type

| Existing ledger | Correct continuation |
| --- | --- |
| `kind: greybox-art-run` (`run.json`) | Original legacy status/resume/recovery commands and original run directory. It is not a supplier executor source. |
| `kind: supplier-job-run` (`supplier-run.json`) | Existing directory as executor `supplier` source; original supplier ledger retains authority. |
| `schema: greybox.image-job/v1` | Existing job directory as executor `image` source. Reconcile unknown original attempts before resubmission. |
| `schema: greybox.native-job/v1` | Existing `native` source with claim/record/settle. Actual native tool invocation remains agent driven. |
| `kind: greybox-execution-queue` | Inspect/status the existing queue and its original source ledgers. |
| Unknown or unreadable schema | Inspect the owning implementation; filename alone does not authorize routing or migration. |

This is an explicit guarded entry, not a sandbox around the host. Direct commands, old copies, arbitrary scripts and tools invoked outside `task-context run` are not intercepted. Only PLAN-declared ledgers are classified. No automatic old-run conversion, background-native bridge, provider call, asset copy or new submission is performed by inspection or pinning.
