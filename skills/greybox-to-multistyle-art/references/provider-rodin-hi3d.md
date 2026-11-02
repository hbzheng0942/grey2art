# Rodin and Hi3D dedicated API adapters

Protocol sources checked **2026-10-20**; pricing rechecked **2026-10-23**. These adapters implement real provider protocols;
offline protocol tests do not establish account entitlement, paid generation
quality, or native-engine acceptance. This release made no live cloud calls for
these suppliers. Keep each provider's API wallet separate.

## Common use and boundaries

The built-in provider dispatcher exposes `capabilities`, `validate`, `quote`, `account`,
`status`, and `fetch`. `capabilities`, `validate`, and the adapters' `quote` methods
are local. `account` is an explicit read-only connection check. `submit` belongs
to the persisted supplier runner after actual H1/H2/H3 approval and reservation;
calling a Python API directly never grants authority to spend.

Inputs are local `{path, sha256}` records. The approved `model_version`, operation,
parameters, dependencies, output format, and budget must identify the actual work.
Credentials use the exact environment names or [private user credential store](provider-meshy-tripo.md#private-credential-setup), never request JSON,
portable bundles, chat, reports, or command arguments. No automatic POST retries,
provider switching, or new task after an unknown original outcome. Resume status
and fetch using the existing task. Returned signed download URLs stay ephemeral.

Downloads use HTTPS, exclude API authorization, reject private destinations and
unsafe paths, and preserve differing existing output. Models receive header and
GLB geometry checks. Archives remain unopened containers: a downloaded ZIP is
not evidence that an engine-ready model, textures, or a rig were integrated.

## Rodin / Hyper3D

- Module: `runtime/greybox/providers/rodin.py`.
- Credential: `RODIN_API_KEY`.
- Base: `https://api.hyper3d.com`.
- Operations: `image_to_3d`, `text_to_3d`. Image inputs are ordered, 1–5 files;
  text requests need a prompt and omit image files.
- Tiers: `Sketch`, `Regular`, `Detail`, `Smooth`, `Gen-2`, and explicit
  `Gen-2.5-Extreme-Low/Low/Medium/High/Extreme-High`. Set `model_version` to the
  exact tier or matching `Gen-1/1.5`, `Gen-2`, or `Gen-2.5` family. Unknown fields,
  family-specific controls on another family, and out-of-range face targets fail
  locally. Image files use an additional conservative 20 MiB adapter limit.
- Generation: authenticated multipart `POST /api/v2/rodin`; even text requests
  use multipart. Always send an explicit tier: omitting it silently selects the
  provider's older `Regular` family.
- Read-only account: authenticated `GET /api/v2/check_balance`.
- Status: authenticated query-only `POST /api/v2/status` with
  `{"subscription_key": "<original jobs.subscription_key>"}`.
- Download list: authenticated query-only `POST /api/v2/download` with
  `{"task_uuid": "<original top-level uuid>"}`. Fetch rechecks that every job is
  `Done`, requires all originally listed jobs, and downloads all returned files.

Persist **both** top-level `uuid` and `jobs.subscription_key`. Their meanings are
different. The subscription key is private recovery metadata and must not be
shown in CLI summaries or portable evidence. `jobs.uuids` are individual jobs,
not the task identifier. A valid accepted UUID without a subscription key is
preserved as `recovery_required`; never submit again to recover the key. A
missing UUID or ambiguous server/transport outcome blocks reissue.

HTTP 201 does not prove acceptance: a nonempty response `error` is checked.
Documented validation/auth/balance/concurrency errors are definite rejections;
unknown server errors remain unknown. The initial `consumed` value is preserved
as `actual_credits` when valid. An invalid billing field needs reconciliation;
it never permits a duplicate task.

No independent task-price quote endpoint was identified in the reviewed Rodin or
Hi3D public API references. Their `quote` methods make zero network calls. Present
**预计费用 / 依据 / 报价方式=费率估算 / 实际扣费**; actual consumption remains unknown
unless an actual task/settlement response supplies it.

Local Rodin `quote` uses the dated official API rate card: base generation 0.5 credits;
Gen-2.5 Extreme-High adds 0.5; extreme-high texture mode adds 2.0. It returns a
**rate-card estimate**, not a firm quote, reservation, cash conversion, or fresh
provider query. Refresh the official source before H3; account purchase terms
determine effective money conversion. T/A pose conditioning does not create a
rig. Rigging, animation, Agentic, Bang, and texture-only endpoints are not
advertised by this adapter.

Primary sources:

- [Quick start and identifier lifecycle](https://docs.hyper3d.ai/en/get-started/quick-start)
- [Gen-2.5 parameters and API pricing](https://docs.hyper3d.ai/en/api-specification/rodin-gen2-5)
- [Gen-2 parameters and API pricing](https://docs.hyper3d.ai/en/api-specification/rodin-gen2)
- [Gen-1/1.5 parameters and API pricing](https://docs.hyper3d.ai/en/api-specification/rodin-gen1-1-5)
- [Check status](https://docs.hyper3d.ai/en/api-specification/check-status)
- [Download results](https://docs.hyper3d.ai/en/api-specification/download-results)
- [Check balance](https://docs.hyper3d.ai/en/api-specification/check-balance)

## Hi3D / Hitem3D

- Module: `runtime/greybox/providers/hitem3d.py`.
- Credentials: `HITEM3D_CLIENT_ID`, `HITEM3D_CLIENT_SECRET`, corresponding to the
  account's AK/SK. The adapter creates Basic `base64(client_id:client_secret)`
  privately and calls `POST /open-api/v1/auth/token`, then keeps its Bearer token
  in memory only. Token acquisition starts no asset job. Token/auth failure
  before generation is not an unknown generation submission.
- Base: `https://api.hitem3d.ai`.
- Operations: `image_to_3d`, `multiview_to_3d`, `texture`. No text generation,
  automatic rigging, or animation is claimed.
- Explicit models: `hitem3dv1.5`, `hitem3dv2.0`, `hitem3dv2.1`, `hi3dv3.0`,
  `scene-portraitv1.5`, `scene-portraitv2.0`, `scene-portraitv2.1`.
  `model_version` must equal the `model` parameter. Resolution, request type, and
  output format are explicit, version-validated production choices.
- Generation: authenticated multipart `POST /open-api/v1/submit-task`.
  `request_type=1` is geometry, `3` is geometry+texture; texture-only uses `2`.
- Single input uses `images`; 2–4 views repeat `multi_images`. The explicit
  four-bit `multi_images_bit` maps front/back/left/right and must include front.
  Images accept PNG/JPEG/WebP up to 20 MiB each.
- Texture uses the reference images plus exactly one hash-bound local GLB
  (200 MiB guard) or explicitly approved HTTPS `mesh_url`. Current reference
  error `10031017` excludes v2.0/v2.1 texture-only despite stale contradictory
  examples; the adapter enforces that restriction. v1.5 lacks PBR controls.
  A `mesh_dependency` parameter may instead name a ready producer operation;
  its sole GLB is resolved and hash-checked at execution, and this adapter-only
  reference is omitted from the provider's multipart payload.
- Read-only account: authenticated `GET /open-api/v1/balance` after token auth.
- Status/result: authenticated `GET /open-api/v1/query-task?task_id=...`. The
  response must repeat the exact requested task. Success model URLs last one
  hour, so fetch re-queries before download. Preserve the task ID; do not rely
  on a saved expiring URL. `success` is provider completion, not visual approval.

Output format values: 1 OBJ, 2 GLB, 3 STL, 4 FBX, 5 USDZ, 6 3MF. Fetch binds the
result to the approved format or preserves a ZIP container for later controlled
processing. Targets over two million faces are enabled only for v3.0 Master;
all dense results still need a scoped game-performance/optimization route.

Local `quote` computes the official table's geometry + texture + optional PBR
components without any provider query. The published list rate is USD 0.020
per credit. The 2026-10-23 direct official API page lists v3.0 `2048quality`
geometry 30 + texture 10 + PBR 5 = 45 credits / USD 0.90; `2048master` is
130 + 10 + 5 = 145 credits / USD 2.90. The page's HTTP Last-Modified is
2026-10-22 10:02:10 GMT; HTML SHA-256 is
`224600782588a6904a06a33757a8d6005eba6ecb6696835ae257f04fbf2cc0c8`.
Older indexed pages and earlier adapter rates differ: refresh the direct official
API table for the exact model, resolution and stages before H3, and leave price
unknown if the conflict cannot be resolved. These values are a dated estimate, excluding purchased-package
discounts, tax, retries, and downstream production. Actual task consumption is
not returned by this task endpoint; the runner must not invent a billing
receipt. A documented failure refund is labelled as documentation, not as an
independently verified account credit.

Primary sources:

- [API setup / AK-SK](https://docs.hi3d.ai/en/api/getting-started/quickstart)
- [Token authentication](https://docs.hi3d.ai/en/api/api-reference/list/get-token)
- [Create task and parameter restrictions](https://docs.hi3d.ai/en/api/api-reference/list/create-task)
- [Task status and result expiry](https://docs.hi3d.ai/en/api/api-reference/list/query-task)
- [Account balance](https://docs.hi3d.ai/zh/api/api-reference/list/query-balance)
- [API component pricing and USD list rate](https://docs.hi3d.ai/en/api/getting-started/pricing)
- [FAQ, input constraints, documented refund policy](https://docs.hi3d.ai/en/api/getting-started/faq)

## Verification still required with the user's account

1. Configure credentials privately and run the explicit read-only account check.
2. Present and approve a scoped qualification asset, exact parameters, and cost.
3. Submit once through the persisted runner; verify resume, artifact contents,
   material/scale calibration, and native-engine integration for that operation.
4. Record exact model/version, task receipt, file hashes, source revision,
   accepted quality, observed cost, and time. Mark only the verified operation
   and engine ready; unrelated operations and providers remain unverified.

Same-reference artistic comparisons remain pending. These API capabilities are
not a verified ranking of supplier likeness, topology quality, animation
readiness, or accepted-asset production cost.
