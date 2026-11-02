# Meshy / Tripo dedicated API adapters

Updated from primary API documentation on **2026-10-21**. These are installed
standard-library adapters with offline HTTP contract tests. No live generation,
account authentication, provider quality, or native-engine success is implied.

## Readiness and execution

- Meshy: `runtime/greybox/providers/meshy.py`, credential environment
  `MESHY_API_KEY` by default; international host `api.meshy.ai`, China `api.meshy.cn`.
- Tripo: `runtime/greybox/providers/tripo.py`, credential environment
  `TRIPO_API_KEY` by default; v3 international host `openapi.tripo3d.ai`, China `openapi.tripo3d.com`.
- `dispatch("capabilities", {})` is offline: reports documented/installed operations,
  key presence only, `connection_verified: false`, and no verified operations.
- `dispatch("validate", request)` is local validation. It checks model-dependent
  fields and local input hashes; it makes no upload, quote or generation call.
- `account` is an explicitly requested, read-only balance GET. Passing account
  authentication verifies the connection only, not generation or engine integration.
- `submit` is called only by the H3-gated supplier job runner after a persistent
  spend reservation. It is intentionally absent from the user-facing provider CLI.
- `status` and `fetch` recover the original task. Both need the original accepted
  request context; Meshy has different query endpoints for different operations.
- A response returns the actual `task_id` plus provider-specific `recovery` fields;
  the runner must persist them before attempting any further validation or polling.
  These adapters never create a second stage or retry a generation automatically.

Never place keys in an inventory, portfolio, skill, command argument, evidence
bundle, exception log, screenshot or Git. This adapter does not scan other tools'
private configuration for credentials. The installed REST adapters route the two
account systems through an explicit frozen `account_profile`, including credential
environment and wallet identity; see [provider accounts](provider-accounts.md).
Keys, balances and operation evidence do not transfer between profiles. Alternate
proxies, CLI device authentication and provider MCP authentication are separate
bindings, not silently interchangeable routes.

## Private credential setup

For Meshy's international account, the user runs this in their own interactive
terminal, using the actual installed skill directory:

```sh
python3 "$SKILL/scripts/configure_provider.py" --provider meshy --region international
```

The script prompts with hidden input; it accepts no key argument and makes no
network request. On macOS/Linux it atomically stores private plaintext in
`~/.config/greybox-art/credentials/providers.json` (directory `0700`, file `0600`).
`GREYBOX_CONFIG_HOME` overrides the base; otherwise `XDG_CONFIG_HOME/greybox-art`
is respected. Never paste the key into chat or copy this file into a project,
evidence, package or Git. This is file permission protection, not encryption or
an OS keychain. Windows uses explicitly configured environment credentials;
this file setup refuses to claim POSIX modes enforce Windows ACLs.

Subsequent built-in calls automatically load the exact provider, region and
credential environment name. Existing environment values take precedence; an
explicit invalid/empty value fails instead of selecting another account.
The default Meshy name is `MESHY_API_KEY`; production `account_profile` must name
`account_system: "international"` and `credential_env: "MESHY_API_KEY"` with its
own account/wallet aliases. For a dedicated alias, configure
`--credential-env MESHY_TEAM_API_KEY` and use that same name in the profile.
Other saved providers/regions/names remain intact; there is no regional fallback.

Use `--provider tripo --region international` (or `cn`), `--provider rodin --region public`,
or `--provider hitem3d --region public` for those accounts. Hi3D prompts separately
for client ID and secret. A custom Hi3D profile supplies `--credential-env` twice,
in that order. `provider capabilities` checks local configuration without network;
`provider account` is a separate explicit balance check. Configuration is not
connection verification or spending authority. Invalid storage stops credential
loading; repair its schema/ownership/modes locally rather than trying another key.

## Supported Meshy operations

| Neutral operation | Actual endpoint | Explicit `model_version` |
|---|---|---|
| `image_to_3d` | `POST /openapi/v1/image-to-3d` | `meshy-6-lite`, `meshy-6`, `meshy-7.1`, `meshy-t2`, `meshy-t2.5` |
| `multiview_to_3d` | `POST /openapi/v1/multi-image-to-3d` | `meshy-6-lite`, `meshy-6`, `meshy-7.1` |
| `text_to_3d` | `POST /openapi/v2/text-to-3d`, `mode: preview` | Same explicit geometry versions as image generation |
| `texture_refine` | `POST /openapi/v2/text-to-3d`, `mode: refine` | `meshy-6-lite`, `meshy-6`, `meshy-7.1` |
| `remesh` | `POST /openapi/v1/remesh` | `remesh-v1` API operation label |
| `rig` | `POST /openapi/v1/rigging` | `rigging-v1` API operation label |
| `animation` | `POST /openapi/v1/animations` | `animations-v1` API operation label |

The final three labels pin the implemented API operation; they are not vendor
neural-model identifiers and are not sent as an invented model parameter.

**Text preview has no finished texture.** A textured text-to-3D plan needs two
separately costed and approved operations: preview, then `texture_refine` using
`preview_task_from` or `preview_task_id`. A preview task cannot silently count as
finished character/scene art.

Smart Topology requires `model_type: "smart-topology"`, triangle topology, and an
explicit T2/T2.5 version. T2 target faces: 100–15,000; T2.5: 100–30,000. Normal remesh:
100–300,000. Ignored Smart Topology remesh/image parameters are rejected locally.
The deprecated `lowpoly` route and floating `latest` model are intentionally absent;
Meshy documents `lowpoly` retirement on 2026-10-30.

Multi-image accepts 1–4 images, with the first as front/primary. Its geometry
resolution is `standard` or `2k`; `4k` is rejected. Single-image supports `4k` with
Meshy 7.1. Unsupported model/image/texture combinations are rejected before POST.

Rigging supports textured, well-defined humanoid GLB sources, facing +Z. Uploaded
non-humanoid rigs are not advertised. `animation` applies Meshy preset action IDs or
a Meshy text-to-motion task to a Meshy rig task. It does not claim arbitrary external
FBX motion retargeting. Text-to-motion generation is not implemented by this adapter.
The optional character subgraph should reuse an existing suitable rig or invoke
rigging only when character deformation is actually required.

Primary references:
[image](https://docs.meshy.ai/en/api/image-to-3d),
[multi-image](https://docs.meshy.ai/en/api/multi-image-to-3d),
[text preview/refine](https://docs.meshy.ai/en/api/text-to-3d),
[remesh](https://docs.meshy.ai/en/api/remesh),
[rigging](https://docs.meshy.ai/en/api/rigging),
[animation](https://docs.meshy.ai/en/api/animation),
[balance](https://docs.meshy.ai/en/api/balance).

## Supported Tripo operations

| Neutral operation | Actual v3 endpoint | Explicit `model_version` |
|---|---|---|
| `text_to_3d` | `/generation/text-to-model` | H or P geometry versions below |
| `image_to_3d` | `/generation/image-to-model` | H or P geometry versions below |
| `multiview_to_3d` | `/generation/multiview-to-model` | H or P geometry versions below |
| `remesh` | `/mesh/decimate` | `v1.0`, `v2.0`, `v3.0` |
| `rig_check` | `/animations/rig-check` | `rig-check-v3` API operation label |
| `rig` | `/animations/rig` | `v1.0-20240301`, `v2.5-20260210`, `v3.0-20260909` |
| `retarget` (`animation` compatibility alias) | `/animations/retarget` | `retarget-v3` API operation label |

Pinned geometry choices: H `v2.5-20250123`, `v3.0-20250812`, `v3.1-20260211`; P
`P1-20260311`, `P2-20260801`. P2 is documented as preview. It supports up to 50,000
triangle faces or 25,000 quad faces. P1 does not support quad. H v2.5 rejects newer
advanced options. Versions are explicit to preserve an approved route and price.

H quad generation forces FBX upstream; do not assume a GLB will be returned. P2 quad
documentation does not make that same guarantee. Native axis, material and scale
normalization remain required after download. Explicit texture `fast`/`delight`
requires `texture_version: "v3.5-20260815"`; conflicting PBR/texture or segmented
parts options fail locally instead of silently changing the paid output.

Multiview accepts named front/left/back/right views with front plus at least one
other unique view, or four positional slots in that exact order with empty skipped
slots, or a previous multiview task. The adapter supports URL/token strings and
bound local inputs, not arbitrary bucket/object credentials.

Rig v1 is biped only. Rig v3 adds the actorcore/unity/unreal/vrm conventions and
`others` rig type. `spec: "mixamo"` means a skeleton convention, not an Adobe Mixamo
call. Retarget accepts documented **Tripo animation presets** on a completed Tripo
rig task; arbitrary user FBX animation uploads are not implemented by this endpoint.
V2.5 supports quadrupeds and other documented creature types; v3 improves humanoids
while retaining v2.5 quality/speed for the other types. Do not infer rig suitability
from the supplier name or an unrelated humanoid success.
Every new managed Tripo rig submission needs a completed rig-check dependency;
set `rig_check_from` on the rig operation to that dependency ID. Historical submitted
tasks still recover without adding a new check. This rechecks the report hash and its exact model-source
fingerprint (provider reference or uploaded file SHA-256), and rejects
`riggable: false` or a rig type different from the approved choice. A green report
for model A cannot enable model B. Local check recovery must preserve the returned
`source_digest`; remote URL identity does not independently prove immutable remote
content, so use hash-bound local files for that guarantee. A downloaded report can say
`false`; download success alone must not enable rigging.

New retarget submissions accept **1–5 unique presets** and require the actual rig
version/type. With `input_from`, a fetched rig's artifact `rig_context` supplies
`task_id`, `model_version` and `rig_type`. For an existing external task, supply that
same `rig_context` object in the approved parameters from its recorded rig request;
do not guess a version from today's default. This local metadata is not sent to
Tripo. Conflicts with dependency metadata or a different task ID are rejected.
The adapter checks the documented preset table: v1 uses `preset:biped:*`; v2.5/v3
bipeds use the documented `preset:walk`-style IDs, while quadrupeds currently have
`preset:quadruped:walk`. No listed preset for avian/others is invented. A rig type
being supported does not establish a preset or a project-specific care interaction.
Existing accepted tasks remain recoverable without adding this new-submit metadata.

Batch retarget requests use GLB so the adapter can check that every requested clip
exists structurally. Batch FBX requires an additional native clip validator and is
rejected before paid submission by this adapter. Single FBX output receives header
and file-integrity checks, followed by Blender/engine validation.

## Choose only necessary processing

Inspect a useful source model first. When actual defects, a deformation requirement
or measured runtime limits require processing, assess the installed supplier
remesh/rig/motion operations before custom DCC code. A source already suitable for
the scene can proceed directly to assembly. Reuse compatible qualification evidence
instead of repeating paid probes; evidence must cover the processing structure,
skeleton and intended visible behavior, not only the provider name.

For a textured model requiring new topology, plan remesh with texture baking and
material comparison before new binding and motion. Tripo v2/v3 `bake` defaults true;
v1 does not support that field. Inspect the returned textures and silhouette rather
than assuming face count establishes success. A topology change invalidates affected
weights, sockets and previous contact evidence. Meshy/Tripo API success and structural
GLB checks do not prove useful deformations or target-engine performance.

Supplier presets or generated motion supply base clips. Engine/DCC work still binds
project-specific grip/contact anchors, IK, root motion, transitions and gameplay
events, and checks them in the actual main camera. Meshy Text-to-Motion is documented
but not generated by this adapter; applying an existing `motion_task_id` does not
claim that capability is installed. Do not silently expand a case into developing
a general rigging or animation system. See [character production](character-pipeline.md).

Primary references:
[introduction](https://developers.tripo3d.ai/en/docs/introduction),
[H image](https://developers.tripo3d.ai/en/docs/generation-image-to-model/standard),
[P image](https://developers.tripo3d.ai/en/docs/generation-image-to-model/p),
[multiview](https://developers.tripo3d.ai/en/docs/generation-multiview-to-model/standard),
[retopology](https://developers.tripo3d.ai/en/docs/mesh-decimate),
[rig check](https://developers.tripo3d.ai/en/docs/animations-rig-check),
[rig](https://developers.tripo3d.ai/en/docs/animations-rig),
[retarget](https://developers.tripo3d.ai/en/docs/animations-retarget),
[files](https://developers.tripo3d.ai/en/docs/files),
[account](https://developers.tripo3d.ai/en/docs/account).

## Hash-bound local inputs and dependent jobs

An adapter request contains `operation`, `model_version`, `parameters`, plus the
runner's frozen `inputs` and completed `dependencies` records.

- `image_path` / `model_path`: absolute approved local path, or zero-based index in
  the request's `inputs`. Each record must match its existing file's SHA-256; encoded/uploaded bytes are
  checked again against that binding immediately before submission.
- Meshy `image_paths`: a list of those path/index references, encoded as image data
  URIs. Tripo `image_paths`: named records such as `[{"front": 0}, {"back": 1}]`.
- Meshy local images use documented data URIs, limited to 20 MiB each. Local models
  use the documented octet-stream data URI and are limited to 100 MiB. Larger models
  need a separately approved public upload route.
- Tripo local images (PNG/JPEG, ≤20 MiB) and models (≤150 MiB) use the actual multipart
  `/files` endpoint before generation. A WebP public URL is accepted upstream, while
  this documented multipart route only advertises PNG/JPEG. No paid generation is
  submitted before all local uploads return usable file tokens.
- `model_from: "operation-id"`: transfer one ready primary model from any provider (prefer a unique GLB);
  recheck the local artifact hash and use the destination provider's upload route.
- Meshy `input_task_from`, `preview_task_from`, `rig_task_from`, or Tripo `input_from`:
  use a ready same-provider task directly. A task ID from another supplier is never
  misinterpreted as a task owned by the destination provider.

Status/fetch requests carry `task_id`, exact `accepted_request`, private `recovery`,
and `output_dir`. Returned task IDs must equal the requested task. Each destination
is marked with provider/task ownership before any download. A different task or
pre-existing unowned output directory is rejected, and existing differing assets
are never replaced. Expired download URLs are refreshed by querying the original
completed task, never by generating again.

## Quotes, failure handling and acceptance

The public API references reviewed on 2026-10-23 provide pricing tables and
balance/usage operations; no separate task-price quote endpoint was identified.
`provider quote` uses a reviewed local rate card and performs zero network calls.
Show **预计费用 / 依据 / 报价方式=费率估算 / 实际扣费** using exact model/options,
wallet and current source check time. Use [Meshy API pricing](https://docs.meshy.ai/en/api/pricing)
and [Tripo API pricing](https://developers.tripo3d.ai/en/pricing). Do not invent a
provider quote endpoint, submit a sample generation to obtain a price, mix web and
API wallets, or use sample task-response credits as a price table.

The shared transport performs no POST retry. HTTP 408/5xx, network failures,
malformed successful submission responses and missing task IDs are unknown outcomes:
reconcile the original task before another submission. Explicit authentication,
parameter, credit and rate-limit rejections are recorded separately. Arbitrary
remote error text, headers, URLs and credentials are excluded from exceptions.

API credentials are sent only to the exact official API host, with authenticated
redirects disabled. Artifact downloads use separate unauthenticated requests;
HTTPS, public DNS/address checks and the same checks after redirects prevent local
or private network targets. Signed artifact URLs are not copied into public output.

Fetch requires a successful task plus every requested model format and a nonempty
primary model/rig/motion result. GLB checks cover version/length/JSON, demanded mesh,
skin joints, animation channels, and the minimum requested animation clip count.
They are structural checks, not a complete glTF validator or an aesthetic score.
FBX/OBJ and other non-GLB outputs still need native geometry/rig/clip inspection.
Archive integrity is checked without extracting or executing its contents.

The asset job becoming ready is not scene acceptance. Preserve H4/H5 checks for
material calibration, spatial fit, rig/clip meaning, contacts, performance,
playability and the selected concept atlas. A supplier report or file-integrity
pass cannot replace those checks.
