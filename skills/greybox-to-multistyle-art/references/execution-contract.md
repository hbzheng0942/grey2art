# Common rolling executor

Use the common executor for multiple generation tasks. Prepare an authorized
queue once; its coordinator then runs without further model replies. Original
project ledgers retain task, approval, provider ID and cost facts. The shared
local store owns capacity reservations referencing those ledgers.

## Six invariants

1. Queue authorized, input-ready work and refill available capacity after each
   completion. Independent tasks never wait for a whole batch.
2. Bind operations to confirmed account pools. Local projects, hosts, connectors
   and keys using the same account share the supplier's applicable limit.
3. Release generation capacity on a confirmed remote terminal state. Download,
   checks and import use separate capacity and do not supply art acceptance.
4. Persist an attempt and reservation before invocation. Lost responses, process
   exit and expired local leases never prove remote failure. Retain unknown
   occupancy and reconcile the original attempt before any repeat.
5. Use the shipped scheduler and reviewed adapters; extend an adapter instead of
   creating another batch/retry loop or untracked background job.
6. Autonomous scheduling cannot depend on another model reply or stalled
   request. Every action has an absolute wall deadline and a mechanism that
   terminates underlying I/O and reclaims execution capacity.

Preserve real dependencies, pilots, human decisions and cumulative budgets.
Query/download retries recover the original task. A generic retryable flag
never authorizes another uncertain or newly charged create.

## Queue actual prepared tasks

Supplier sources are existing H3-bound supplier-run directories. Reserve exact
image requests without invoking them:

```text
image reserve --profile NAME --file request.json --project CASE --job-dir CASE/image-jobs/JOB --source-ref ACTUAL_AUTHORIZATION
```

Populate [the queue template](../schemas/execution-queue-template.json). Each
source has `kind:image|supplier|native`, absolute `path` to its original ledger
directory, and `pools:{PROFILE_OR_PROVIDER_OR_TOOL:POOL_ID}`. All providers in a
supplier source need bindings. Do not copy a project into the queue.

Each `pools` entry declares `capacity` and the actual current `source_ref`.
Confirm the account/region/operation group; a template value or historical
membership table is not a live quota. Multiple API keys do not establish
different accounts. Optional `rate_limits:{submit:5,status:10,fetch:2}` declares
actual requests per second, independently of in-flight capacity. Those numbers
illustrate syntax, not supplier limits. Server capacity/rate refusals remain
authoritative when manual jobs or other machines share the account.

Explicit frozen portfolio run limits remain effective. A current user-authorized
operational change can be recorded in a source as
`execution_limits:{source_ref:"ACTUAL_DECISION",max_inflight_per_provider:{lux3d:3}}`.
This never changes asset parameters, suppliers, quotes or paid scope.

Queue `limits` accepts total wall-second `submit_timeout`, `status_timeout`,
`fetch_timeout`; `poll_interval`, `retry_interval`, `tick_interval`; and separate
action counts `max_submit`, `max_status`, `max_fetch`. Allow sufficient time for
the actual operation: synchronous image generation needs a different create
deadline from asynchronous task submission. Socket inactivity timeout cannot
bound a response that keeps slowly sending bytes.

## Start, inspect and resume

Use `greybox.py executor` or `scripts/executor.py`:

```text
executor validate --file queue.json
executor run --file queue.json
executor start --file queue.json
executor status --file queue.json
```

Validation is offline. `run` owns the coordinator; `start` detaches it. The
default shared state directory is the user's greybox configuration directory
under `execution/`. Different local hosts must use the same `--state-dir` to
share capacity. This is a local SQLite store, not a multi-machine/network-share
coordination service.

Workflow ownership uses a stable `.workflow.lock` file with an OS lock. The file
remains after release; its existence or recorded PID alone does not mean the run
is busy. Never delete or replace it to recover a current worker. Process exit
releases the lock, including when metadata is empty or incomplete. Stop workers
using older PID-file locking before upgrading a shared workspace; a live legacy
PID is conservatively refused. Temporary lock contention leaves unsubmitted
supplier operations pending, separate from a confirmed conflicting claim.

`run --once` and `run --max-seconds N` bound the coordinator. Started action
supervisors retain original deadlines and durable receipts. Resume the same
queue to import them instead of creating new tasks. Inspect phase, process
liveness, heartbeat age, pools, task deferred reasons and capability gaps.

Changing a running queue pauses new submissions until a reviewed restart.
Unavailable ledgers never free capacity. Reconcile original provider IDs using
the existing image/supplier recovery commands, then resume the same queue.
Proven-unsubmitted supplier preparation may stop at a review/input gate with
`preflight_blocked`. After correcting its evidence, use
`executor retry-preflight --file queue.json --source-ref ACTUAL_CORRECTION`
and run the same queue. Accepted, unknown and permanent provider rejections
cannot be reset by this command; the full original production gate runs again.
Legacy `image submit`, `supplier-jobs step` and low-level bridges remain bounded
single-operation/recovery interfaces; do not loop them into another dispatcher.

If a supplier's completed local artifacts are missing or changed, status names
`artifact_recovery_required`. Use `supplier-jobs recover-artifacts --run-dir RUN
--operation-id ID --source-ref ACTUAL_OBSERVATION`, then resume this same queue.
The queued action only fetches the original remote task; it uses download capacity,
not a new generation slot or quote. Exact original hashes/roles must be restored
before dependent work becomes ready. Damaged originals remain preserved. This
does not relax later new-submission checks or supply art acceptance.

## Execution and host adapters

Invocation channel (HTTP/command/native tool) and completion mode (synchronous
result/asynchronous task) are independent. Explicitly declare unsupported query,
cancel and recovery actions. Tool availability does not prove independence.

Fixed shipped backends implement `scan/prepare/invoke/commit`. Brief locks protect
ledger changes; isolated workers perform provider calls and heavy artifact I/O.
An independent supervisor enforces total deadlines and saves action receipts
even if the coordinator/model connection stops. Custom suppliers use the existing
reviewed hash-bound command adapter; queue data cannot import arbitrary modules.

Errors retain provider code, category, `acceptance:not_accepted|accepted|unknown`
and `retry_after`. Proven-unaccepted capacity/rate refusals can wait and retry;
accepted/unknown outcomes never authorize another create. Query failure retains
the original ID. Success/failure/cancellation are remote terminality, separate
from local download, artifact validity and review readiness.

Native tools are called by their actual host. Current native support is
**agent-driven** claim/record, not an unattended ImageGen/MCP connection:

```text
executor native-reserve --file native-request.json --job-dir CASE/native-jobs/JOB --tool ACTUAL_TOOL --source-ref ACTUAL_AUTHORIZATION
executor claim --file queue.json --action submit
executor record --ticket ACTUAL_TICKET_PATH --file actual-receipt.json
```

Native request: `tool_arguments` plus actual `images:[{path,sha256}]`. Local
references must appear in tool arguments. URL channels bind the existing
`boards native` dispatch as `native_dispatch:{path,sha256}`. Receipts bind actual
action ID, attempt ID, request hash, exact arguments and invocation source. A
successful receipt also identifies the real local output. Async acceptance saves
the real provider task ID; `native-settle` records actual terminal evidence for
that same ID without inventing a query interface. A late synchronous result can
also settle its exact original unknown action without inventing a task ID.

An autonomous native bridge must demonstrate dispatch of the next ready action
without another model turn. Capability declarations alone cannot certify this.
Do not silently switch to a paid external route or claim autonomous progress on
an agent-driven channel.

## Behavioral acceptance

Use fake services first: fast/slow task permutations, shared independent ledgers,
controller inactivity, slow query/download, all workers occupied by slow-drip
responses, capacity refusal/429, lost POST response, restart before ID persistence,
failed/cancelled terminality and exact native receipts. Qualify real host/provider
routes using already authorized work. Offline fixtures never certify live output,
real host independence or human acceptance.
