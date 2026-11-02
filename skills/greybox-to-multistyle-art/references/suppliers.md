# Open suppliers and comparable asset portfolios

The registry has open supplier IDs. Lux, Tripo, Meshy, Hi3D/Hitem3D and Rodin are
knowledge seeds, not an exclusive list. Keep every configured or desired vendor
in the inventory. Do not silently select the first configured vendor. No key,
token or password belongs in these files; credentials stay in the user's local
environment or explicitly configured private store. See the [provider setup](provider-meshy-tripo.md#private-credential-setup) for hidden terminal input; never copy credential files into a project or package.

## Availability and knowledge are different

`schemas/suppliers-template.json` is an offline inventory starter. `catalog_only`
means no executable bridge is installed. `builtin_lux` uses the bundled Lux
runtime. `builtin_api` selects the fixed packaged Meshy/Tripo/Rodin/Hi3D implementation; it does not accept arbitrary module imports or prove account readiness. `command` means the user has explicitly reviewed a local adapter and
bound its absolute argv/source path/hash. A catalog URL never installs or invokes
anything. A third-party MCP being documented does not establish local readiness.

Record discovery, configuration, connection, each operation and native-engine
integration independently. A verified receipt has `state: "verified"`, a
timezone-aware `checked_at`, optional `expires_at`, and `evidence: {path, sha256}`.
The file must actually exist and match its hash. This binds evidence; it does not
authenticate the writer or prove visual quality. Failed/unverified receipts do
not turn into success because an account has credits.

`references/supplier-catalog.json` separates official documented capabilities,
project observations and unknowns. Refresh facts per model/version/task. Record
same-reference trials for props, characters, terrain pieces and other relevant
families rather than using an unsupported universal vendor ranking. Compare
shape, texture, topology, rig suitability, scale/material repair, accepted cost
and time. Keep coherent families on one route unless a useful exception is
demonstrated. The Hi3D/Hitem3D API documentation is identified; a different product using a
similar name needs its own registry identity. Unknown API operations and prices
stay unknown.

## Proposals and prices

`schemas/portfolio-template.json` demonstrates multiple Lux G1/G1-Turbo options;
its placeholders intentionally cannot pass validation. Replace them using real
references, supported parameters and current dated prices. Prefer a current
provider quote when the selected API has a documented, non-generation quote route
and it is readily available. Lux has this route: use it for the concrete request;
every new bundled Lux submission requires a valid live quote. For comparison before request
inputs are ready, label a sourced official API rate-card calculation as an estimate.
Do not invent quote endpoints or require one from suppliers that do not document one.
There is no blanket
Lux version default. Choose version and face count for each task and explain the
choice. G1 omits `enablePbr`; Turbo omits `customSize`. An explicit current user
restriction can narrow `effective_policy.lux_allowed_versions`.

A portfolio has:

- `registry_sha256`: `suppliers.registry_digest(registry)`.
- `required_assets`: the complete asset scope shared by every option.
- `required_operations`: asset ID to required operation names. Include all needed
  texture, remesh, rig, motion, retarget and export stages. Characters expand this
  chain only when the approved greybox scope needs them.
- `options`: asset route/operation mappings and complete dependency-ordered
  operation cost lines. Each operation belongs to exactly one asset.
- `recommended_option` and `recommendation_rationale`: the proposed best mix and
  its quality/cost/schedule reasoning. Present economy/quality alternatives when
  feasible; never fabricate diversity or quote an unsupported operation.

Each cost line identifies supplier, exact model/version, parameters, rationale,
dependencies and `pricing`. Price kinds are `firm_quote`, `rate_card_estimate`
and `user_estimate`. Every price has a dated HTTPS source or hash-bound local
receipt, `quoted_at`, `quantity`, and either named-wallet `unit_credits` or
`direct_money: {unit_amount, currency}`. Firm quotes need an actual expiry. A zero
cost needs `zero_cost_reason`; unknown is not zero.

Use the same four fields in user-facing proposals and reports: **预计费用**
(credits and wallet, plus evidenced currency conversion if available), **依据**
(exact operation/model/options, source URL and check time or quote ID/expiry),
**报价方式** (`实时报价` / `费率估算` / explicit user estimate), and **实际扣费**
(provider task/settlement receipt, otherwise `尚未产生` or `未知`). A current quote
is still a pre-execution price, not an actual charge or spending authorization.
Quote API failure must stay visible; a fallback estimate cannot authorize a
quote-required execution. Balance checks and differences between two balances
are not per-task billing receipts.

For `builtin_lux`, the supplier runner resolves/uploads the approved references,
quotes those exact final API parameters, and saves a private mode-0600 receipt
before generation. Even an older approved rate-card estimate is checked against
the live total: it must be no greater than that operation's approved
`unit_credits * quantity`. Quote/receipt failure or an overrun stops before model
submission and is recorded as definitely unsubmitted. A successful check sends
the new quote ID with the creation request. Existing task status/fetch retains
its original recovery path and does not request a new generation quote.

Public API review on 2026-10-23: Lux exposes an account-bound quote endpoint.
Meshy, Tripo, Rodin and Hi3D publish official API rates; no independent task-price
quote endpoint was identified in their reviewed public references. Their current
`provider quote` command computes a local estimate, with zero network requests.
Refresh official rates for the exact model/options before H3. This is a documented
capability difference, not a reason to invent a live-quote claim. See the linked
provider references for sources and actual-charge fields.

Normalize reviewed official prices into `schemas/rate-card-template.json` and use
`estimate_from_rate_card(card, operation, model_version, parameters)`. Each rate
specifies supported `parameter_domains`, explicitly manual-confirmed
`nonbillable_parameters`, a base credit/money cost, and priced conditional add-ons.
The calculator requires exactly one matching supported rate and records the
card hash, matched rule IDs and effective billing parameters. Unsupported inputs,
missing required billing choices and overlapping rates produce unknown-price
errors. The example contains no actual vendor rates. The host must verify the
normalized rules against the official source; calculation does not authenticate
an arbitrary supplied price document. Do not use Web subscription allowances as
API prices or silently supply an unpriced option with zero cost.

Credits stay separated by wallet. A wallet ID may not refer to unrelated
suppliers. Optional `conversion` records `amount_paid`, `credits_received`,
`currency`, purchase/allocation `basis` and dated `source`. This yields allocated
asset cost, not necessarily cash due. `cash_due: {amount,currency,basis}` records
incremental cash separately. Missing conversion is reported as unknown; different
currencies are not added without a separately evidenced conversion. List retry
reserves and necessary paid postprocessing as explicit lines; include estimated
human repair/assembly effort in option rationale rather than hiding it behind a
cheap generation price. Quote quantity is the supplier's billed units for that
operation, not permission to submit it repeatedly.

`registry_digest` binds supplier IDs, declared operations and executable routing
identity. Renewal of discovery/connection/operation receipts or configured/
desired flags does not erase a creative/spend decision. Fresh readiness is still
checked before new submissions. A binding, operation, parameter, scope or price
change requires the corresponding proposal revision and human decision.

## H3 selection and first use

`supplier-selection` schema 1 contains `gate: "H3"`, `actor: "user"`,
`decision: "approved"`, exact `portfolio_sha256` and `registry_sha256`,
`selected_option`, `source_ref`, hash-bound decision `evidence`, `decided_at`, and
optional `allowed_fallbacks`.

Each fallback names `option_id`, exact `operation_ids`, and per-wallet
`wallet_caps`. It does not authorize the agent to spend both primary and fallback
budgets without the runner's aggregate cost control. Unknown submissions must be
reconciled before any alternative is issued. Silence and account balance are not
approval. The runner also checks that the source matches the actual workflow H3
approval and that the production table binds this exact portfolio.

A provider's first authorized pilot cannot require prior successful generation.
An operation can declare `qualification_probe: true`; actual H3 selection must
list its exact ID in `allow_qualification_probes`. This allows a configured,
connection-verified, explicitly bound adapter to run that limited probe. It does
not mark the operation or native integration tested. Expansion still needs the
real sample/native evidence and normal H4 gate.

## Portable local adapter protocol

The adapter receives one JSON object on stdin and returns one JSON object on
stdout. No shell, dynamic module import or credential interpolation is used.

```json
{"schema":1,"provider":"user-vendor","method":"capabilities","request":{}}
```

The response binds `provider`, `method` and boolean `ok`. Methods are
`capabilities`, `quote`, `submit`, `status`, `fetch`. Do not invent a provider
quote endpoint: `quote` can return a clearly sourced estimate or an explicit
unsupported result. Errors must omit raw headers, keys and provider bodies.
Adapters must implement the intended operation and enforce its input restrictions.

Submit requests bind `operation`, `model_version`, and `parameters` exactly to
the selected cost line. A spend-aware runner may add `inputs`, `dependencies`,
`quote`, `output_dir` context; these do not permit parameter drift. Original task
IDs and multiple provider-specific recovery IDs belong in the runner ledger.
Status/fetch recover the existing task. Fetch writes only task-owned outputs and
returns local artifact paths/hashes. A receipt is not engine or art acceptance.

`invoke_adapter` checks registered command integrity and selection binding for
submit/fetch. Its caller must additionally enforce actual H3 workflow provenance,
persist spend reservations before submission, retain ambiguous outcomes, and
verify output ownership. The R3 supplier runner provides that ledger; direct
low-level calls do not grant authority. Fetch can recover an already submitted
task after prices/readiness expire; new submissions remain blocked.

The bundled implementation includes Lux and dedicated Meshy/Tripo/Rodin/Hi3D APIs, plus the open command-adapter interface. See [Meshy/Tripo](provider-meshy-tripo.md) and [Rodin/Hi3D](provider-rodin-hi3d.md). Dedicated modules are offline tested; credentials and actual useful production remain separately unverified. Custom suppliers continue through reviewed command adapters.

## R3.1 execution additions

The public `provider` command exposes offline capabilities/validation/local quotes
and explicit account/status/fetch only; paid submit is reached through the gated
supplier-job runner. Supply keys through the named local environment variables.
`account` is an opt-in read-only check, not spending permission.

`execution_limits.max_inflight_per_provider` in the approved portfolio caps each
provider across repeated steps. Claims in project/art/.supplier-claims protect H3
operations across runs; unresolved asset/operation claims also survive new H3
metadata. Do not remove those records to retry. Accepted provider IDs and private
recovery are retained separately. Settlement observed during polling updates the
same cost record rather than counting it as another charge.

For a model consumed by a predeclared native source, set operation.publish to an
explicit project art GLB path and optional exact primary role. This is part of the
approved operation digest. The runner moves the verified owned file, preserves
role/hash/validation, and refuses missing or ambiguous primaries and different
existing content. Final native checks still follow.

## Restore a completed local artifact

`supplier-jobs status` reports missing or changed bytes separately from remote
task completion. Do not mark the row ready, delete its ledger or generate a
replacement to repair a local download. Queue restoration from that exact task:

```sh
python3 "$SKILL/scripts/greybox.py" supplier-jobs recover-artifacts --run-dir "$RUN" --operation-id "$OPERATION_ID" --source-ref "$ACTUAL_OBSERVATION"
```

This command is offline. Resume the original executor, or run `supplier-jobs step`
on the same run to fetch. Restoration retains the original task/account/request,
expected artifact roles and hashes, and cost reservations. Changed originals are
preserved before a verified exact replacement is published; dependent operations
remain blocked until restoration completes. A missing provider copy or different
bytes leaves recovery unresolved and never authorizes another create. Existing
workflow/runtime submission checks still apply to later new production.

## Image-conditioned production policy

New mesh production must use approved single-image/multiview conditioning and the actual H3 reference package; raw text API capabilities do not authorize text production. Custom supplier IDs remain open, but operations map to reviewed canonical image or processing operations. Unknown aliases such as generate_mesh cannot bypass this policy. Optional remesh, rig, motion, texture processing and historical task recovery retain their declared source contracts. See [modeling references](modeling-references.md).
