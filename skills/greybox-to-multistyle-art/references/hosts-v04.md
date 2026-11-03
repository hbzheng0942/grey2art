# Portable host setup

Use the complete canonical Skill package through its Python CLI. For the normal task, inspect the existing gameplay greybox and prepare its multistyle art path. [English quickstart](quickstart-en.md) and [中文快速开始](quickstart-zh.md) describe the user-facing sequence. MCP, a WorkBuddy connector and delegation are optional; keep the selected main model and run serially when needed. The Skill link must resolve the package containing its relative references/scripts, not an isolated Markdown file.

## Install once; preserve the selected version

From the verified extracted package, use Python 3.10+:

```sh
python3 scripts/install.py --host auto --replace
```

Use `py -3` or the actual interpreter on Windows. The installer selects one host from current-session evidence, `GREYBOX_HOST`, or one existing host installation. When evidence is ambiguous it reports candidates and performs no install; supply `--host workbuddy`, `codex` or `claude-code`. An explicit `--skills-dir` always wins. Existing WorkBuddy `~/.workbuddy/skills` can be reused; if absent, supply the actual host import/discovery directory. Never install into every detected host. `--config-dir` lets the installer reuse a recorded canonical install outside the discovery directory.

Only manifest-listed source files are installed. Identical content is reused; `--replace` preserves the old directory or link outside host discovery and swaps atomically. Save the returned version, manifest hash, installed path and previous path. Use `--host HOST [--skills-dir DIR] --rollback BACKUP_PATH` to restore a preserved install. Existing cases keep their original approvals, artifact hashes, task/recovery IDs and historical version bindings; an upgrade does not rewrite them. Do not assume a moved previous install remains at its former path.

## One setup command for the current operation

Install, rollback and dependency setup retain a separate `.guard` file after release.
The legacy PID sentinel is removed on normal exit so older installers can run after rollback.
Guard file existence alone does not mean another operation is running. Process exit
releases ownership, so a crashed setup can be retried without deleting locks.
Stop older installer/bootstrap and credential-configuration processes before upgrading a shared installation;
live or unrecognized legacy lock owners are not silently replaced.

Multiple image/model jobs use the [common executor](execution-contract.md),
independently of delegation. Process execution and a verified native tool do not
prove that the host can dispatch autonomously. Native claim/record explicitly
reports agent-driven execution unless a real independent bridge is available;
the model's network connection cannot be the autonomous queue's heartbeat.

Use the installed `scripts/greybox.py` as the prefix:

```text
host setup --host auto --scope art --project PROJECT --capability-report REPORT --session-id CURRENT_SESSION
host setup --host auto --scope runtime --runtime lux
host setup --host auto --scope greybox --project PROJECT
host setup --host auto --scope spatial --engine blender --operation review --project SOURCE.blend
```

Use `greybox` for the bundled Godot/Unity starter, `spatial` for native Blender work, `art` for concepts/art, and `runtime lux` only when that operation needs Lux. Setup returns the actual project/workspace root, verified package identity and `command_prefix`; use that exact Python/prefix in subsequent commands. Game-project discovery checks the supplied root and at most two child levels, skips links/caches and reports ambiguity. Specify an exact root when a folder contains multiple games. It does not launch the engine or claim native acceptance.

Blender spatial setup accepts an existing `.blend` or workspace directory, including an empty directory for `--operation create`; `edit` and `review` select the other scoped operations. It needs no game-project marker, future runtime receipt, image profile or supplier. `host verify --host HOST --scope spatial --engine blender --operation review` checks the corresponding bindings without requiring source-write capability. Setup/verification establish package, Python and Blender executable readiness only: `project.native_invocation_verified` and `production_ready` remain false. Continue with the actual scoped native operation from [authoring](greybox-authoring.md); neither setup nor the bundled application-level `blender inspect` command reviews `.blend` scene content.

Core greybox work installs no image or supplier dependencies. For art, a suitable native image tool with actual `invocation_verified` evidence in the current session satisfies generation readiness without an API profile. Use `schemas/host-template.json`; generation, reading pixels and displaying the result remain separate bindings. A tool listing is only discovery. Use evidence from an already authorized real task, not an extra paid capability probe. Missing invocation evidence does not instruct the agent to switch providers: continue ready planning/setup and record the first authorized native result.

If no suitable native tool exists, configure the chosen service with `image configure`, bind its non-secret name using `host configure --host HOST --image-profile NAME`, then rerun setup. During art setup, the configured image route prepares requests/Pillow in a private reusable runtime; a native-only art setup does not automatically install them. `--scope runtime --runtime image` explicitly prepares the same runtime. Setup never logs in, queries all suppliers, creates a quote or submits generation. Credentials and actual service capability remain separate; see [image services](image-services.md).

Native generation also needs Pillow when actual board cropping begins. Prepare
only the reusable image-processing runtime with
`host setup --host auto --scope runtime --runtime image`; this needs no image
profile or API credentials and submits no image request. Use its returned Python
prefix for the crop commands. An already suitable environment can be reused.

Python selection invokes existing interpreters rather than trusting PATH. When dependency creation is needed, an offline temporary venv/pip probe detects failures such as WorkBuddy ensurepip aborts; setup can select another existing compatible interpreter and reports the attempts. An explicit `--python PATH` is never silently replaced. No global pip, Python/engine downloads, project copies or copied caches are used. Network/index failures retain a scoped diagnostic; retry the same operation after correction. Configuration defaults to the private greybox-art directory; `--config-dir` or `GREYBOX_CONFIG_HOME` overrides it.

`host discover`, `host configure` and `host verify` remain available for focused diagnosis. Configuration success is not current-session proof, playable evidence or production approval. Keep all three distinct.

## One board workflow, current host bindings

For new S7 native reference tasks, record the asset/view registry once and use `boards start`; WorkBuddy uses `boards workbuddy start` to register the same task's actual native scope. Follow the [reference method](modeling-references.md#choose-the-generation-route-before-individual-calls) and consume the returned jobs. Preserve pending calls, map the actual current tool schema and reference-count/transport limits, then invoke the exact claimed page arguments once and record its actual result. WorkBuddy additionally completes its harmless native probe and current-session binding. Lower-level `boards production prepare` remains for existing inputs/recovery, not a second normal entry.

For a configured image-service profile, retain `boards prepare` and consume its exact page requests through the existing [image/executor route](execution-contract.md). Its service IDs and receipts remain authoritative; new native-host production records do not replace that ledger. Legacy `boards native` / `boards record-native` mapping and recording remain applicable to their original prepared requests; see the [protocol](modeling-reference-protocol.md#execute-the-same-page-across-hosts).

Use local paths when supported; bind any required upload to its actual source hash, preserve image order and never invent a cross-host argument schema. Planning/preparation, mapping tests and successful receipts do not prove visual quality. Open the board and each original-pixel crop, preserve modeling requirements, and repair only failed objects/views. Actual cropping needs Pillow even when generation uses a native tool. Use the first already-authorized board as the current host's real invocation evidence; do not spend on an extra capability probe.

## Optional host wrappers

WorkBuddy can execute the full Skill through Bash without a connector. If its managed runtime or connector UI is useful, generate a local CLI wrapper with:

```sh
python3 scripts/install.py --host workbuddy --skills-dir EXISTING_SKILLS_DIR --connector-dir NEW_CONNECTOR_DIR --replace
```

Import/register that wrapper through WorkBuddy only when needed. It follows the official [CLI connector schema](https://open.workbuddy.cn/docs/connector), uses `type: cli` and requests managed Python 3.11 on WorkBuddy 5.0+. Initialization configures the CLI and defers optional dependencies. The wrapper points at the installed package; regenerate it if that path changes. It is not a published marketplace package or an MCP requirement. Host UI refresh/registration may still require the user; do not claim universal zero-interaction installation.

Claude Code and Codex may optionally register a stdio MCP bridge using the selected Python and absolute `scripts/greybox_mcp.py` argument. It wraps the same CLI and can return local image bytes. Persisted submit/status/fetch/resume handles long jobs; never repeat an unknown submission after timeout. See the [WorkBuddy Skill structure](https://open.workbuddy.cn/docs/skill) for direct scripts through Bash.
