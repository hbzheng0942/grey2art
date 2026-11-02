# Independent raster image services

Use this route when the active host/model lacks a usable image-generation tool.
Keep the reasoning model unchanged. These operations can run before H1 and do
not depend on H3 mesh production. Existing task scope and image-spend authority
remain necessary; configuration, credentials and balances grant no spend.

`scripts/image.py` works directly with Python 3.10+ and Pillow. The shared CLI
also exposes `greybox.py image ...`. Submission is a detached job by default;
use `status --local` for no-network inspection and `resume` for one bounded poll
and any completed download. Node and MCP are optional. Image decoding, reading
pixels in the host and displaying images to the user are separate capabilities.

For multiple images, use `image reserve` with the same request/authorization
arguments to prepare each job without invoking it, then run the [common
executor](execution-contract.md). It continuously fills confirmed account
capacity and isolates slow requests. Legacy detached `submit` completes one
invocation; an asynchronous result still needs explicit monitoring when used
outside the executor. Do not treat that worker as a multi-task scheduler.

## Configure once

`image configure --profile NAME --file profile.json` stores a non-secret profile
in the user's configuration directory. `--config-dir` selects another external
user directory. Never put credentials in that file, the project or CLI arguments.

Lux reuses its regional environment/keyring/private-config support:

```json
{"kind":"lux","region":"cn"}
```

Reference uploads use an explicit session with environment proxies disabled,
matching the image/account HTTP routes; TLS certificate verification stays on.
The pinned uploader and its secure credential provider are shared unchanged.

Standard Images-compatible endpoint (base ends at `/v1`, not `/images`):

```json
{"kind":"openai","base_url":"https://api.example.com/v1","model":"actual-image-model","credential_env":"MY_IMAGE_API_KEY","timeout":300}
```

Use the provider's actual model ID. Set `MY_IMAGE_API_KEY` locally in the host's
process environment. HTTPS base URLs may include a custom port; authenticated
redirects are rejected. Artifact download URLs use public HTTPS and never receive
API credentials. The CLI does not print saved response URLs or base64 bodies.

`capabilities --profile NAME` is offline. By default the standard adapter exposes
generation, edits with up to 16 references, PNG masks, dimensions and background
control. Narrow this declaration for a compatible service with fewer features:

```json
{"kind":"openai","base_url":"https://api.example.com/v1","model":"actual-model","credential_env":"MY_IMAGE_API_KEY","capabilities":{"max_references":1,"mask":false,"transparent_background":false,"parameters":["size","quality"]}}
```

Unsupported parameters are rejected before submission. Lux declares text-only,
one-image-only and text+one-image input; it declares no mask, size, seed,
transparency or multiple-reference controls. Raster image operations have no
G1/G1-Turbo version field. Mesh-generation policy remains separate.
`validate --profile NAME --file request.json` checks supported parameters and real
input pixels offline without credentials, uploads or job creation. It checks the
common contract; test a custom adapter's outbound HTTP dialect with its own
synthetic request/response fixture before its first authorized production call.

## Submit and recover

For modeling-reference pages, first use `greybox.py boards prepare` following the [board protocol](modeling-reference-protocol.md#production-boards-and-crops). Submit each prepared page request directly; do not replace its whole-page prompt with the single-object skeleton or split its slots into separate calls. Each page retains all style images, its own exact design masters and, when selected, the layout guide last; preparation splits pages to fit the declared reference limit. `image validate` must pass for the chosen profile before submission. A one-reference channel can use explicit guide-free preparation only when the required approved inputs still fit; never drop inputs or change an edit into text-only generation silently.

An input request uses local image paths bound to their actual SHA256:

```json
{"operation":"edit","prompt":"Create an isolated reference preserving this selected style","images":[{"path":"concept.png","sha256":"ACTUAL_SHA256"}],"parameters":{},"purpose":"modeling-reference"}
```

`generate` uses a prompt and an empty `images` list. Lux also permits an edit
without text. Standard edits send multipart `image` or repeated `image[]`, plus
an optional `mask:{path,sha256}` PNG matching the first input's dimensions.

```text
image submit --profile NAME --file request.json --project CASE --job-dir CASE/image-jobs/JOB --source-ref ACTUAL_TASK_AUTHORIZATION
image status --job-dir CASE/image-jobs/JOB --local
image resume --job-dir CASE/image-jobs/JOB
image fetch --job-dir CASE/image-jobs/JOB
```

`--authorization` accepts a local JSON object containing `source_ref` and the
existing task's budget/scope evidence instead of `--source-ref`. There is no
additional per-image approval. Every job reserves its identity before invoking a
provider and binds profile, request and input versions. Changing configuration
does not change an existing task. `--asset-dir` shares one content-addressed image
store across jobs; default is the sibling `image-assets` directory.

API failures, timeouts or worker termination after submission begins never
trigger automatic resubmission or a provider switch. `resume` only queries the
original task or downloads the saved result. If the original task identity was
lost, explicitly reconcile with the provider's actual record:

```text
image resume --job-dir JOB --task-id ORIGINAL_TASK_ID --source-ref ACTUAL_RECOVERY_EVIDENCE
image resume --job-dir JOB --response-file ORIGINAL_PRIVATE_RESPONSE.json --source-ref ACTUAL_RECOVERY_EVIDENCE
```

Synchronous Images APIs have no standard task query; recover their saved response
or reconcile provider history. A job whose detached process never started remains
`reserved`; `image start --job-dir JOB` performs its first invocation once.

Each completed image contains real decoded dimensions, format, bytes and hash.
`receipt-N.json` is compatible with the existing modeling-reference receipt
contract and records actual style-image hashes, tool, arguments and invocation.
Text-only concept receipts have no style-image hashes; they cannot satisfy a
style-conditioned modeling-reference gate. Original responses stay in the private
job directory; receipts refer to canonical images without copying them. Native
host tools can use `record-native` with actual tool arguments, output and call
source; this records provenance and does not invoke or invent a tool call.

Native board tools use `boards native` to bind the same prepared request to their actual argument schema and local-path or host-upload URL transport, then `boards record-native` to verify actual arguments and output. See the [native board mapping](modeling-reference-protocol.md#execute-the-same-page-across-hosts). Native pixel reading and user display remain separate host operations.

## Create a custom adapter from a real API manual

Read the actual provider manual first. Save a small adapter in a user extension
directory, outside the installed skill. Register its executable argv, source hash,
manual source and supported operations in a `custom` profile:

```json
{"kind":"custom","credential_env":"CUSTOM_IMAGE_KEY","base_url":"https://api.example.com","model":"actual-model","capabilities":{"generate":true,"edit":false,"max_references":0,"mask":false,"size":false,"transparent_background":false,"parameters":[]},"adapter":{"source":"/absolute/user/extensions/provider.py","sha256":"ACTUAL_ADAPTER_SHA256","argv":["/absolute/python","{adapter}"],"documentation":{"source_ref":"https://provider.example.com/api/images","path":"/absolute/user/extensions/api-manual.txt","sha256":"ACTUAL_MANUAL_SHA256"}}}
```

All paths in the registered adapter are absolute. Use the selected host runtime's
Python executable, including its Windows `.exe` path when applicable. A manual
snapshot is optional, but when supplied its hash is checked on use. Source changes
require review and registration of the new hash; saved jobs retain their binding.
The CLI runs argv directly without a shell. Credentials stay in the named local
environment variable, never stdin or argv. The adapter is user-controlled code,
not an untrusted-code sandbox; inspect it before registering.

Adapter stdin is one JSON object:

```json
{"schema":"greybox.image-adapter/v1","action":"submit","request":{"operation":"generate","prompt":"...","images":[],"parameters":{}},"task_id":null,"config":{"base_url":"https://api.example.com","model":"actual-model","credential_env":"CUSTOM_IMAGE_KEY"}}
```

For polls action is `status`, request is null and task_id is the original ID.
Stdout must contain exactly one response object, with no logs:

```json
{"state":"submitted","provider_task_id":"original-task-id"}
```

```json
{"state":"succeeded","provider_task_id":"original-task-id","items":[{"url":"https://public-cdn.example.com/result.png"}],"usage":{"images":1},"actual_cost":{"amount":1,"currency":"provider-credit"}}
```

Each item contains one of `url`, `b64_json` or an absolute local `path`. The
runtime decodes and hashes actual image bytes. Poll responses must preserve the
same task ID. Exit failure/malformed create responses are treated as unknown,
never a safe retry. Perform offline request/response tests first; the first live
test must be an already authorized actual task. No adapter registration starts a
paid call. Preserve the adapter/manual version and actual invocation evidence.

## Limits and verification

The standard adapter implements `/images/generations` and multipart
`/images/edits`; chat-completion image dialects require a custom adapter. Response
JSON is limited to 128 MiB, each decoded image/input to 64 MiB, 100 million pixels,
and combined edit inputs to 256 MiB. Image output acceptance is pixel/container
integrity; aesthetics and reference suitability still require actual visual
review. Tests use synthetic HTTP responses and no paid calls. A configured profile
or test fixture never proves production quality or native-host image delivery.
