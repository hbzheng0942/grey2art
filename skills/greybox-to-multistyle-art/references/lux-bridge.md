# Lux3D bridge and optional postprocessing

The standalone skill vendors a minimal, unmodified official Lux3D 1.2.0 runtime, pinned to commit `81c495ad0f01784b3d86f8d5b4a97558e80a78ca`, with its MIT license and per-file hashes in `runtime/vendor/manifest.json`. It calls OpenAPI methods through `runtime/greybox/lux.py`; it neither upgrades the global plugin nor starts the upstream workflow or automatic REPORT.

## Local setup

Run `python3 <skill>/scripts/greybox.py setup --region cn --install-dependencies --configure-key` in a local terminal. Choose `international` for an international account. The key is entered without echo and stored in a supported system credential store. Dependency setup creates a private runtime cache outside the skill; it does not install packages globally. Setup flags are explicit: ordinary `setup`/`doctor` do not install dependencies or submit generation.

The bridge can reuse regional environment credentials (`LUX3D_CN_API_KEY` or `LUX3D_GLOBAL_API_KEY`) and an existing private Lux configuration. A generic `LUX3D_API_KEY` must also have `LUX3D_API_KEY_REGION` bound to the intended region. Do not ask users to paste keys into chat or write them in a plan, shell history or shared report. Do not infer international credentials from a China account. If the secure keyring is unavailable, explain the available regional-environment option; do not silently save plaintext.

- `doctor --region cn` checks local installation and configuration without network generation.
- `doctor --region cn --online` performs non-generation connection/account checks.
- `lux capabilities` reports the exact pinned operation and parameter capabilities.
- `lux status --region cn --task-id ID` inspects a known task.
- `lux fetch --region cn --task-id ID --output DIR` fetches a completed known task into task-owned storage.

Use `setup --help` and action help for the current interface. Credentials and signed download URLs must not appear in public output.

## Production lifecycle

Public pricing references: [Lux3D 定价 (China)](https://lux3d.aholo3d.cn/lux3d/home?view=pricing&lang=zh_CN)
and [Lux3D Pricing (international)](https://lux3d.aholo.ai/lux3d/home?view=pricing).
The international URL is linked by the China page's official language alternate
and was checked on 2026-10-23. These pages cover membership, credit packs and
generation costs; do not assume a Web allowance equals an API account price.
[Dashboard、积分与 API 密钥](https://aholo.featurebase.app/zh-CN/help/articles/6916933-dashboardji-fen-yu-api-mi-yao)
explains the public account/usage workflow. Public pages supplement, rather than
replace, the exact request's live quote from `POST /lux3d/v1/pricing/openapi-quotes`.
The bridge does not read internal documentation at runtime. Retained upstream
contract provenance is not a requirement for users to access internal documents.

Present **预计费用 / 依据 / 报价方式 / 实际扣费** consistently with
[supplier prices](suppliers.md#proposals-and-prices). For Lux, label the successful
quote `实时报价`, retain its region, request, quote ID and expiry, and distinguish
its stated account-benefit scope from actual settlement. No verified live quote
means no claim of one; a failed quote does not become zero cost.

The generic supplier runner enforces this for every new `builtin_lux` operation,
including portfolios originally priced from a rate card: quote the final uploaded
input parameters, persist the full private receipt before creation, and require
the live total to fit that operation's approved `unit_credits * quantity` ceiling.
Quote/receipt failure or excess cost means no model submission; an estimate cannot
bypass this check. Only the new live quote ID is passed into creation. Historical
task status/fetch does not requote or generate a replacement.

New operations belong to explicit draft-plan assets, with `generation.operation`, `region` and version-appropriate `parameters`. Obtain a current proposal quote before asking for H3 approval:

```sh
python3 "$SKILL/scripts/greybox.py" quote-preview --project "$PROJECT" --file "$DRAFT_PLAN" --output "$PROJECT/art/quotes/proposal-01.json" --capabilities "$CAPABILITIES" --session-id "$SESSION"
```

The draft binds a workflow path/hash with actual H1/H2 decisions. S6 proxy evidence and H3 approval need not exist yet; proxy construction and quote collection may proceed independently. Preview requires a current schema-2 capability report with the bundled Lux connection verified and matching every quoted asset's account region. It validates requests, may upload the explicit approved local reference and fetches quotes; it submits no models and creates no run or approval. Tell the user which reference is uploaded.

Preview returns safe per-asset version/face-count/rationale/quoted-credit information, regional totals and a `receipt_hash`. Keep the complete receipt at its private `0600` output path; do not publish request URLs or copy that private file into the shared review bundle. Show safe quoted values and the receipt hash in the H3 package.

For H3, propose a concrete asset package before model submission. Each asset/family includes intended use and approved reference, route (reuse/procedural/generated/Hybrid), explicit G1/G1-Turbo choice, generation face count, delivery/LOD budget, optional postprocessing, selection reason and current provider quote. Show the selected package total by account region, retry/call allowance and credit ceiling; distinguish optional alternatives from committed totals. A cached estimate or an account balance is not a current quote or spending authorization.

Choose the route/version/face count together from silhouette and topology difficulty, visible fine detail, material requirements, camera importance, repetition/instancing, repair risk and target-platform budgets. Compare candidate outcomes or run an authorized representative probe when the choice is uncertain; do not assume a version guarantees better art or impose one version on every asset. High generation face counts do not automatically improve visible fidelity. G1 and G1-Turbo are ordinary proposal alternatives; H3 approval of the explicit request authorizes the chosen version, without a separate Turbo-only opt-in. Apply the current user's explicit restrictions through `effective_policy.allowed_versions`; do not carry the author's local preference into a colleague's plan. G1 omits `enablePbr`. Preserve and assess historical assets by actual quality and lineage.

Show modeling references and the completed native proxy with the H3 package before model submission. If references will be produced later, obtain explicit scoped authority for agent intermediate review; otherwise return with those actual references before model production. After the actual H3 response, record its production table/recipe and approval, freeze the workflow/plan, then use the normal `plan` → `quote` → `approve` → `run` commands. Record `approve` with the actual user decision and current quote hash; the second command does not require a second human approval for the same authorized request and budget. Agent-created approval text cannot substitute for the user's decision. Unchanged approved parameters and remaining budget continue autonomously; material scope, quality or credit changes return to H3.

The executor persists intent before submission and acknowledgement/task ID after it. `resume` queries known work and continues completed independent items. A submission with an unknown outcome must be reconciled using an authoritative task ID; never create a duplicate merely because a timeout occurred. Changed request parameters or scope require renewed quotes/authorization as appropriate. Partial downloads remain inspectable and retryable without a new generation.

Record initial permission with `approve --run-dir RUN --actor user --note "actual user decision" --quote-hash HASH`. Add `--allow-quote-refresh` only if the actual H3 decision permits requoting the same scope within its existing credit ceiling. Proposal and executable quotes can expire; refresh with normal `quote` and faithfully reuse the actual H3 response only inside its explicit scope/budget, without asking twice solely because there are two quote commands. The runtime retains explicit refresh permission only for the unchanged plan/policy and operation/region/parameter scope, with submitted tasks reserved at their committed `submissionCredits` plus the new unsubmitted quote staying within each original regional credit ceiling. An interrupted refresh invalidates active authorization before network work and retains only narrowly scoped pending refresh permission; a complete within-budget refresh can restore it. Pending permission cannot submit work. Unknown committed costs, exceeding the existing ceiling or changed scope require a new decision. Sufficient account credits never authorize retries.

For optional processing, create another explicit asset task and quote it. Supply its generated `operation` and `parameters` as `accepted_request` when calling the thin Python `fetch` adapter; workflow `resume` does this automatically. Action IDs, requested formats, skins and animation containers are checked, but deform quality remains a native test. A separate output per action is retained for explicit selection, not silently assembled as one model. Low-level wrappers remain library mechanisms; the host must not bypass the workflow's confirmation record.

## Functional operations

| Operation | Bridge entry | Constraints to preserve |
|---|---|---|
| Image/text generation | `image_to_3d`, `text_to_3d` | Per-task explicit `G1`/`G1-Turbo` and face count from the installed capability schema and H3-approved package; G1 omits `enablePbr` |
| Topology processing | `remesh` / `mesh.remesh` | Current pinned route accepts static, non-Draco GLB; explicitly plan texture baking when needed and invalidate dependent fit/material/rig evidence |
| Mechanical articulation | `articulate` | Do not assume arbitrary requested joint semantics are preserved; inspect returned hierarchy |
| Human binding | `rig` / `rig.bind` | Provider-readable HTTPS humanoid GLB; native rig validation is separate; do not assume quadruped support |
| Public action transfer | `retarget` / `motion.apply_preset` | Rigged provider-readable GLB and supported public action IDs, not arbitrary source-clip retargeting |
| Material transfer | `material_transfer` | Separate operation/version, not a change in original mesh generation provenance |
| Format export | `export` | Inspect exported contents and actual Godot import before acceptance |

Consult `lux capabilities` and the vendored contracts before constructing a task; aliases do not broaden upstream support. Remesh generally precedes binding and motion. If a later operation changes topology, UVs, transforms or skeletons, recheck affected textures, weights, sockets, contacts and collision. Root motion, loop closure, IK and gameplay event mapping need native game checks. Rigid train wheels and door pivots usually stay under deterministic game control instead of a character binding pipeline.

Processing is conditional: an inspected source that already meets the actual scene
requirements need not be remeshed or rigged. For a necessary operation, assess the
installed suitable supplier route before writing custom processing code. The pinned
Lux remesh default is `bakeTextures: false`; when preserving a textured asset, choose
the required baking setting and texture size explicitly in H3, then compare actual
materials and silhouette. Do not use topology changes on a bound asset as a shortcut
around revalidating weights and contacts. Public action transfer provides base
motions, not automatic project-specific grasping, wiping or gameplay timing.

## Other tools

Additional providers are optional, not required for Lux users to start. Installed
API implementations, account connectivity and useful native results are separate
evidence levels. Cross-provider processing can use hash-bound source artifacts;
the destination's input restrictions and separately approved operation still apply.

| Provider | Potential integration | Release state |
|---|---|---|
| Meshy | Remesh, humanoid rigging, animation | Installed dedicated REST adapter; explicit cn/international account profile; offline contracts tested, useful live results require qualification |
| Tripo | Topology, rig preflight, rigging and preset actions | Installed dedicated v3 REST adapter; explicit cn/international account profile; rig type/version and preset restrictions checked |
| Tencent Hunyuan cloud | Topology, binding, motion generation | Interface mapping only; distinguish cloud API from open-source models |
| Mixamo | Web rigging, action selection and download | Manual handoff; no assumed supported public API |

Official references: [Lux3D source](https://github.com/manycore-research/Aholo-Lux3D), [Meshy Remesh](https://docs.meshy.ai/en/api/remesh), [Meshy rigging](https://docs.meshy.ai/en/api/rigging), [Tripo rigging](https://developers.tripo3d.ai/en/docs/animations-rig), [Tripo retargeting](https://developers.tripo3d.ai/en/docs/animations-retarget), [Hunyuan topology](https://cloud.tencent.cn/document/api/1804/126293), [Hunyuan binding](https://cloud.tencent.cn/document/api/1804/131618), [Mixamo workflow](https://helpx.adobe.com/creative-cloud/help/mixamo-rigging-animation.html). Check these when adding a live provider adapter; capabilities change.
