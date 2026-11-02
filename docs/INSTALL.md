# Install and configure

[English](INSTALL.md) · [简体中文](INSTALL.zh-CN.md) · [README](../README.md)

## Get the complete package

Use [Python 3.10+](https://www.python.org/downloads/). Download the Skill ZIP and checksum from [GitHub Releases](https://github.com/hbzheng0942/grey2art/releases/latest). The ZIP is about 1 MB; games and showcase media are not needed. Extract it, then enter `greybox-to-multistyle-art/`:

```sh
python3 scripts/install.py --verify-only
python3 scripts/install.py --host auto --replace
```

## Install from source

Alternatively, clone the source. Run these commands from the repository root, `grey2art/`:

```sh
git clone https://github.com/hbzheng0942/grey2art.git
cd grey2art
python3 skills/greybox-to-multistyle-art/scripts/install.py --verify-only
python3 skills/greybox-to-multistyle-art/scripts/install.py --host auto --replace
```

On Windows replace `python3` with `py -3`. Keep the complete Skill directory; `SKILL.md` alone cannot run all tools. Verification installs nothing and submits no generation. Installing the Skill needs no engine or provider account. [Archive verification](RELEASE-PACKAGING.md)

## Select your host

Install for the host you will actually use. `--host auto` uses current-session or existing-installation evidence. An ambiguous result installs nothing; rerun with one explicit host:

```sh
python3 skills/greybox-to-multistyle-art/scripts/install.py --host codex --replace
```

Use `claude-code` or `workbuddy` for those hosts. Default locations are:

- Codex: `~/.codex/skills/greybox-to-multistyle-art`, or `CODEX_HOME/skills/greybox-to-multistyle-art` when configured.
- Claude Code: `~/.claude/skills/greybox-to-multistyle-art`.
- WorkBuddy: its existing `~/.workbuddy/skills` directory; if discovery cannot find it, provide the actual Skill directory with `--skills-dir`.

An explicit `--skills-dir` selects your host's real discovery directory. A recorded host profile can reuse a previous canonical installation; the installer always reports the actual path. Do not copy the package into every host directory.

After installation, refresh Skill discovery or start a new host session, then invoke `greybox-to-multistyle-art`. Keep the reported installed path, version and previous-install path. MCP registration and the optional WorkBuddy connector are separate choices; ordinary use runs the same Python CLI directly.

## Check before production

Give the installed path to your agent and request an offline check first. It can verify the package and inspect the current method:

```sh
python3 "$SKILL/scripts/install.py" --verify-only
python3 "$SKILL/scripts/greybox.py" --version
python3 "$SKILL/scripts/greybox.py" knowledge audit
```

Here `SKILL` is the installation path reported above. These checks need no service credentials and make no generation calls. Host setup checks readiness separately; it does not prove a useful image, native invocation or playable result. Follow the [quickstart](../skills/greybox-to-multistyle-art/references/quickstart-en.md) for the first task.

## Configure only the current operation

**Authoring and validation.** Use the existing project's engine and version. For native assembly and play checks, Godot or Unity must be installed and callable by the agent. Preparing the Skill does not download an engine or migrate the game. See [capabilities](CAPABILITIES.md) for the native routes.

**Images.** A suitable host-native image tool can produce concepts and references without a second image-service account. Local image decoding and crop operations may still require Pillow. If the current host has no usable image tool, configure one service through [image services](../skills/greybox-to-multistyle-art/references/image-services.md). Keep the reasoning model unchanged. Generation, pixel inspection and displaying the result are separate capabilities.

**Meshes.** Configure a 3D supplier only when new AI meshes are needed; reused assets and native edits may need none. New AI meshes use approved image references. The agent proposes the route, model/version, parameters, processing and costs before the first production authorization. Optional remesh, rigging and motion are separate operations and may add cost.

**Blender.** This DCC tool supports spatial greyboxes, scale, camera, geometry and offline checks. Spatial or `.blend` delivery needs no game engine. Prepare it only for selected authoring, processing or rendering work. Its presence alone does not establish support for every topology, material or animation task.

**Python packages.** The core CLI uses Python's standard library. Selected image operations prepare HTTP/decoder dependencies in a private reusable environment. Keep environments outside the Skill and project; do not use global pip or include caches in handoffs. The tested dependency set is recorded in release validation, while operation requirements may allow a broader range.

## Choose an AI 3D provider

Choose one provider and enable its API when generating new models. Installing the Skill or building a greybox needs none of these accounts.

| Provider | Sign up and API access | Skill configuration |
|---|---|---|
| Lux3D | [International](https://lux3d.aholo.ai/) / [China](https://lux3d.aholo3d.cn/) · [Key guide](https://aholo.featurebase.app/zh-CN/help/articles/6916933-dashboardji-fen-yu-api-mi-yao) | [Local setup](../skills/greybox-to-multistyle-art/references/lux-bridge.md#local-setup); select the actual account region. |
| Meshy | [Website](https://www.meshy.ai/) · [Create an API key](https://docs.meshy.ai/en/api/authentication) | [Credential setup](../skills/greybox-to-multistyle-art/references/provider-meshy-tripo.md#private-credential-setup); select `meshy`. |
| Tripo | [Website](https://www.tripo3d.ai/) · [Developer keys](https://developers.tripo3d.ai/en/keys) | [Credential setup](../skills/greybox-to-multistyle-art/references/provider-meshy-tripo.md#private-credential-setup); select `tripo`. |
| Rodin / Hyper3D | [Website](https://hyper3d.ai/) · [API dashboard](https://hyper3d.ai/workspace/api-dashboard) | [Configuration](../skills/greybox-to-multistyle-art/references/provider-rodin-hi3d.md); select `rodin`. |
| Hi3D / Hitem3D | [Website](https://www.hitem3d.ai/) · [API access guide](https://docs.hi3d.ai/en/api/getting-started/quickstart) | [Configuration](../skills/greybox-to-multistyle-art/references/provider-rodin-hi3d.md); select `hitem3d`. |

These are implemented API routes. Models, processing operations and account quotas are configured per provider. Check API access and credits separately from website subscriptions. New meshes use reviewed image references; Lux3D defaults to G1 standard.

## Accounts and credentials

Select the actual account system before configuring a provider. China and international accounts can have different keys, API hosts, wallets and entitlements; changing the website language does not migrate them. Never try a key against another region after an authentication error.

Lux setup runs in your own interactive terminal, using the actual installed path:

```sh
python3 "$SKILL/scripts/greybox.py" setup --region cn --install-dependencies --configure-key
```

Choose `--region international` for an international account. The prompt hides the key; do not paste it into the agent chat. The bridge uses its supported credential store or explicit regional environment credentials. See [Lux setup](../skills/greybox-to-multistyle-art/references/lux-bridge.md#local-setup).

For other built-in providers, [credential setup](../skills/greybox-to-multistyle-art/references/provider-meshy-tripo.md#private-credential-setup) supports hidden local input on macOS/Linux and permission-restricted plaintext storage. That file is not encrypted. Windows uses credentials supplied through the agent process environment; the POSIX file helper does not claim to enforce Windows ACLs. Keep only credential variable names in shared configuration, never values. [Account and recovery identity](../skills/greybox-to-multistyle-art/references/provider-accounts.md) explains regional profiles.

Setup and balances do not authorize paid work. Review image exploration costs and mesh/processing costs separately. Quotes, estimates and actual charges remain distinct, and wallets are not pooled. Existing production scopes have their own ceilings; multiple run approvals are not automatically one case-wide spending cap.

## Upgrade and resume

Use a new checkout of the selected fixed tag, verify it, then run the same installer with `--replace`. It preserves the old installation outside host discovery and reports the rollback path. Identical packages are reused.

For rollback, use the preserved path returned by the installer:

```sh
python3 skills/greybox-to-multistyle-art/scripts/install.py --host codex --rollback "/path/reported/by/installer"
```

Refresh host discovery afterward. Ongoing cases retain their original bound package/runtime and provider ledgers. An upgrade does not rewrite historical acceptance or automatically allow remaining submissions under changed runtime bytes. Ask the agent to use the case's existing task context and recover known provider tasks before planning new work.

## If something fails

- **Host ambiguous:** select one `--host`, or the actual `--skills-dir`.
- **Manifest mismatch:** obtain the complete same-version package; preserve edited installations and ongoing cases.
- **Missing Python/venv/pip:** select a working existing Python 3.10+; preserve old environments and follow the scoped setup diagnostic.
- **Dependency download failure:** correct connectivity or package-index configuration, then retry the same setup. Do not repeatedly create new full environments.
- **Authentication failure:** verify the declared account/region and the credential available to the agent process; do not rotate through unrelated accounts.
- **Generation timeout or unknown result:** retain the original task and recovery IDs. Status/download recovery does not require a new generation.
- **Changed or missing completed supplier output:** preserve the ledger and changed file. The agent queues `supplier-jobs recover-artifacts --run-dir RUN --operation-id ID --source-ref ACTUAL_OBSERVATION`, then resumes the original executor or `supplier-jobs step`. It re-fetches the original task and requires the original hashes, without generating a replacement.

Use [support](SUPPORT.md) for redacted reports and [security reporting](../SECURITY.md) for sensitive issues.
