# Grey2Art user guide

[Homepage](../README.md) · [Install and configure](INSTALL.md) · [Capabilities and tools](CAPABILITIES.md) · [Documentation](README.md)

**Use one gameplay greybox to build editable, playable prototypes in one or more art styles.** Grey2Art is an Agent Skill for Codex, Claude Code and WorkBuddy. You describe the task; the agent inspects the project, develops the art direction, plans the scene and assets, then assembles and checks the result in the selected native tool.

You can also start with a gameplay brief or reference and build a greybox first. A Blender task can finish with an editable spatial scene; playable delivery uses the game's runtime, such as Godot or Unity.

## 1. Prepare your workspace

| Prepare | When you need it |
|---|---|
| Codex, Claude Code or WorkBuddy with local command execution | Every task. |
| [Python 3.10+](https://www.python.org/downloads/) | Installation and the shared CLI. |
| An existing project, or a new project directory | Keep the original gameplay, assets and project instructions available to the agent. |
| [Godot](https://godotengine.org/download/) or [Unity](https://unity.com/download) | Native playable assembly and interaction checks. Retain an existing project's engine version. |
| [Blender](https://www.blender.org/download/) | Spatial greyboxes, scale/camera/geometry work, or selected asset processing and rendering. Blender is a DCC tool; an editable `.blend` endpoint needs no game engine. |
| A suitable image tool | Concepts and modeling references. Use the host's image tool or configure an [image service](../skills/greybox-to-multistyle-art/references/image-services.md). Image decoding and cropping may need Pillow. |
| One AI 3D provider | Only when new generated models are needed. Existing assets and native geometry may need no provider account. |

Installing the Skill and building a primitive greybox need no image or 3D account. Prepare additional dependencies for the current operation when the agent identifies them.

### Install the complete Skill

Download the Skill ZIP and checksum from [GitHub Releases](https://github.com/hbzheng0942/grey2art/releases/latest). Extract the archive and enter its `greybox-to-multistyle-art/` directory:

```sh
python3 scripts/install.py --verify-only
python3 scripts/install.py --host auto --replace
```

On Windows use `py -3` instead of `python3`. If host selection is ambiguous, rerun with `--host codex`, `--host claude-code` or `--host workbuddy`. The installer reports the actual installation and rollback paths. Refresh Skill discovery or start a new session afterward.

Keep the complete directory: `SKILL.md` alone does not contain the runtime and methods. [Source installation, custom paths and rollback](INSTALL.md)

### Choose a provider when needed

| Provider | Account and API | Configuration |
|---|---|---|
| Lux3D | [International](https://lux3d.aholo.ai/) / [China](https://lux3d.aholo3d.cn/) | [Lux setup](../skills/greybox-to-multistyle-art/references/lux-bridge.md#local-setup) |
| Meshy | [Website](https://www.meshy.ai/) · [API keys](https://docs.meshy.ai/en/api/authentication) | [Meshy configuration](../skills/greybox-to-multistyle-art/references/provider-meshy-tripo.md#private-credential-setup) |
| Tripo | [Website](https://www.tripo3d.ai/) · [Developer keys](https://developers.tripo3d.ai/en/keys) | [Tripo configuration](../skills/greybox-to-multistyle-art/references/provider-meshy-tripo.md#private-credential-setup) |
| Rodin / Hyper3D | [Website](https://hyper3d.ai/) · [API dashboard](https://hyper3d.ai/workspace/api-dashboard) | [Rodin configuration](../skills/greybox-to-multistyle-art/references/provider-rodin-hi3d.md) |
| Hi3D / Hitem3D | [Website](https://www.hitem3d.ai/) · [API access](https://docs.hi3d.ai/en/api/getting-started/quickstart) | [Hi3D configuration](../skills/greybox-to-multistyle-art/references/provider-rodin-hi3d.md) |

Choose the actual account region and check API access and credits separately from a website subscription. These are implemented API routes; useful output and integration still depend on the selected model, operation and project. New Lux3D mesh generation defaults to **G1 standard**. New AI meshes use approved image references.

Configure keys through the linked local setup, outside the chat and repository. For Lux, the hidden key prompt runs in your own terminal. Other providers support process-environment credentials; the POSIX local-file helper stores permission-restricted plaintext. [Accounts and credential handling](INSTALL.md#accounts-and-credentials)

## 2. Start with a concrete request

Include the project path, desired result, style goals, target device and what must remain unchanged. Replace the placeholders below. You can ask the agent to propose art directions if you have not chosen them.

### Existing greybox, one style

```text
Use greybox-to-multistyle-art to turn <project path> into a clay-style playable art prototype.
Target: <engine and device>. Preserve the existing controls, rules, collisions and camera.
Keep the result editable. Inspect the project first, then show the scene direction,
assembly design, asset references and costs before new asset production.
```

### One greybox, multiple styles

```text
Use greybox-to-multistyle-art to make paper, pixel and clay playable versions of <project path>.
Target: <device>. Preserve the same gameplay across all three styles.
Complete a whole paper-style sample first, then develop the other two styles.
Show references, production scope and costs before generating new assets.
```

The number of exploration directions and the number of delivered styles are separate choices. New concept exploration normally proposes 8–10 directions, or your requested count. Selecting two delivery styles does not mean exactly two image-generation calls.

### Build a greybox, then develop the art

```text
Use greybox-to-multistyle-art to create a top-down collection game in Godot at <new directory>.
First build a small playable greybox with movement, collection, level completion and reset.
Check that core loop, then develop a toy-style playable art prototype.
Target: <device>.
```

### Start from a game reference

```text
Use greybox-to-multistyle-art to explore <core gameplay> from <game link, screenshots or recording>.
Describe the controls, camera, rules and uncertainties. Build one small original greybox level
in <engine> at <new directory>, check the core loop, then make a <style> playable art prototype.
Target: <device>. Use my own or reusable assets.
```

A reference supplies observable behavior and appearance. Hidden rules, dimensions and interactions remain questions to resolve. Give the agent accessible screenshots or a recording when it cannot inspect the game directly.

### Start with a Blender space

```text
Use greybox-to-multistyle-art to create <scene description> in Blender at <directory>.
Check scale, circulation, clearances and the selected camera views. Deliver an editable .blend
with the relevant views and open issues. Stop at spatial validation.
```

To continue into gameplay, add the target Godot/Unity project and request a playable sample. A `.blend` file and its offline renders establish the spatial work; runtime interaction gets a separate check in the game.

## 3. Check the starting state

The agent should identify the real project entry, current controls/camera, existing assets, instructions and task records. An already usable greybox can enter art work directly; a missing new-format manifest does not require rebuilding the game.

Ask for this first report:

```text
Inspect the installed Skill and project without submitting generation.
Report the actual package version, project entry, available authoring tools,
missing setup for this task, protected gameplay relationships and proposed next step.
Reuse the current project and existing task records.
```

Setup and offline checks make no generation request. When needed, the agent uses the installation path reported earlier and the command prefix returned by host setup. For manual verification, replace `$SKILL` with that actual path:

```sh
python3 "$SKILL/scripts/install.py" --verify-only
python3 "$SKILL/scripts/greybox.py" --version
python3 "$SKILL/scripts/greybox.py" knowledge audit
```

## 4. Follow the scene, then the assets

The intermediate work depends on the scene. A compact level may need one concept and a short assembly plan; a longer route benefits from several key views and an explicit spatial recipe.

| Step | What you should see |
|---|---|
| Gameplay baseline | The actual entry and camera, object roles, important dimensions and relationships, and relevant gameplay observations. |
| Art direction | Actual scene concepts with meaningfully different forms, materials and atmosphere; chosen delivery styles and a priority style. |
| Spatial recipe and scene design | A buildable interpretation of massing, route rhythm, landmarks, scale, clearances, camera constraints and transitions. A cheap spatial probe checks the uncertain relationships. |
| Assembly plan and asset board | Which forms use generated models, existing assets or native geometry; asset responsibilities, connections, placement and build order; actual isolated modeling references. |
| 3D assets and assembled sample | Necessary models and processing, then a connected native composition including the environment, materials, light, contact and gameplay objects. |
| Playable result and expansion | The priority style's complete agreed sample, actual gameplay and visual review, then the remaining selected styles and final delivery. |

[Colorful Clay Train Parkour workflow](demo/grey2art-workflow-train.en.png) shows this progression. A good individual model does not replace the whole-scene sample.

You review selected directions, design, concrete production, the complete sample and final delivery. The methods call these H1–H5. The agent reuses your existing decisions while their scope remains valid; routine commands, status checks and repairs within that scope need no repeated approval. [Review details](../skills/greybox-to-multistyle-art/references/human-decisions.md)

### Agree on paid work before submission

The proposal should identify the actual reference images, assets, provider/model/version, parameters, necessary processing, cost basis and spending limits. Image exploration and 3D production have separate workloads. Estimates, supplier quotes and actual charges are different records; unknown charges remain unknown.

Installation, an available tool and an account balance authorize no paid generation. Existing authorized work can continue within its recorded scope. A timeout should first recover the original job rather than create a replacement charge.

## 5. Review and revise a result

Compare the approved target and native output using the same camera and gameplay state. Name the largest visible problem and the expected change:

```text
Keep the selected style and current gameplay. From <camera/state>, the station facade
blocks the route and the entrance is hard to read. Adjust that area, preserve the rest,
then capture the same view and recheck traversal and visibility.
```

The agent should repair the responsible design, asset, assembly or rendering layer and recheck affected results. Unchanged good assets can be reused. A local revision does not need a new full concept search.

For a heavy model, ask the agent to measure it before choosing processing:

```text
Inspect <GLB path> and its actual use in this scene. Report topology, instances and
embedded image bytes. If processing is needed, propose the route, cost and a before/after
native check. Preserve the source model.
```

The bundled read-only tool is `scripts/asset_metrics.py inspect` / `compare`. It does not measure FPS, draw calls or GPU memory, and no local decimator is bundled. Remeshing routes and native DCC work have their own input limits and checks. [Asset inspection and processing](../skills/greybox-to-multistyle-art/references/asset-optimization.md)

## 6. Find the deliverables

Ask the agent for an index of actual paths and entries. A case normally uses `art/<case-id>/` for navigation and design records, with `shared/` and `styles/<style-id>/`. Native resources follow the engine mapping: for example, Unity resources use `Assets/Art/<case-id>/`. Existing canonical inputs can stay in their original locations. [Workspace layout](../skills/greybox-to-multistyle-art/references/project-layout.md)

The handoff should identify:

- Each selected style's editable native scene and how to launch it.
- Selected concepts, spatial recipe, assembly design, asset board and source identities.
- Models, textures and required dependencies used by that scene.
- Current gameplay captures, relevant native checks, remaining defects and target-device performance observations when requested.
- The exact delivered version, current task records and next action.

The latest development result, last native-verified result and your accepted result may be different revisions. A concept image, downloaded GLB, successful command or headless check does not establish the complete playable experience. Review the actual intended build and device for the claims that matter to your task.

## 7. Resume or recover

```text
Resume <project and case path> with greybox-to-multistyle-art.
Read the existing PLAN/PROGRESS and current focus. Identify the bound package and native entry,
recover the original pending supplier jobs, and report the next authorized action.
Preserve completed assets and existing decisions.
```

| Problem | Next action |
|---|---|
| The host cannot find the Skill | Refresh discovery; select the actual host or its `--skills-dir`. |
| Package verification fails | Obtain the complete same-version package and preserve local edits. |
| A tool or dependency is missing | Prepare only that operation's environment using the setup diagnostic. |
| Authentication fails | Check the actual account, region and credentials visible to the agent process. |
| Generation times out or its result is unknown | Preserve the original task and recovery IDs; query and recover that operation before resubmission. |
| A completed download is missing or changed | Recover the original supplier artifact using its ledger and hashes. A new generation is a different operation. |
| The host or installed Skill changed | Inspect the existing task context; keep its bound version or explicitly revalidate affected work. |

[Continuity](../skills/greybox-to-multistyle-art/references/continuity.md) and [supplier recovery](../skills/greybox-to-multistyle-art/references/suppliers.md#restore-a-completed-local-artifact) describe the exact paths for the agent. Preserve one canonical copy of unchanged large assets; source diffs and small evidence records are sufficient for iteration.

For a useful report, ask **“export this task's usage feedback.”** Review the local Markdown, JSON and Issue draft before sharing them. Include the version, host/OS/engine, stage, small reproduction and redacted error. Keep keys, signed URLs, private recovery records and full game assets out of public reports. [Support](SUPPORT.md)

## Agent reference entry

Agents start with [SKILL.md](../skills/greybox-to-multistyle-art/SKILL.md), then read the methods for the current stage. The user guide explains the task and review points; the installed methods define the actual command and record contracts.

[First-task method](../skills/greybox-to-multistyle-art/references/quickstart-en.md) · [Greybox authoring](../skills/greybox-to-multistyle-art/references/greybox-authoring.md) · [Spatial design](../skills/greybox-to-multistyle-art/references/spatial-contract.md) · [Assembly](../skills/greybox-to-multistyle-art/references/hybrid-production.md) · [Native adapters](../skills/greybox-to-multistyle-art/references/engine-adapters.md)
