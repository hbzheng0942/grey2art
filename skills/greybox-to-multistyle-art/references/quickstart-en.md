# Start with one gameplay greybox

[中文](quickstart-zh.md) · [Host installation and setup](hosts-v04.md) · [Current scope and limits](candidate-status.md)

The main task is to **batch-transform one gameplay greybox into playable prototypes in multiple art styles**. Keep gameplay and every selected style, validate a complete priority-style sample, then expand the remaining styles.

## 1. Install the complete Skill

Obtain a fixed-version complete directory or package from the repository homepage. Python 3.10+ is required; use `python3` on macOS/Linux, or `py -3` / the actual interpreter path on Windows. Run inside the extracted **Skill directory**:

```sh
python3 scripts/install.py --host auto --replace
```

On Windows replace the prefix with `py -3`. If host detection is ambiguous, specify `--host codex`, `--host claude-code` or `--host workbuddy`; use `--skills-dir PATH` for a custom discovery directory. The installer verifies the manifest, reuses identical files, preserves the previous version for rollback and returns the actual installation path. Refresh the host's Skill list if needed. An isolated `SKILL.md` cannot run the complete workflow. See [host setup](hosts-v04.md#install-once-preserve-the-selected-version) for upgrades and rollback.

## 2. Give the agent a concrete task

```text
Use greybox-to-multistyle-art to make playable prototypes in two art styles from this same playable greybox.
Project: <actual project path>
Styles: <chosen styles, or ask the agent to propose directions>
Target device: <desktop/Web/other actual target>
Preserve existing gameplay, controls, collisions and critical spatial relationships.
Inspect the project and its current records, then propose multiple styles and a complete priority sample.
Show references, parameters and costs before concrete asset production; keep every selected style in the delivery scope.
```

Change the request to three or more styles when needed; an explicitly single-style task keeps that scope. **Concept exploration count and delivery style count are separate**: new exploration defaults to 8–10 directions, or the user's count. An existing selected direction or local revision does not restart exploration. Explain the applicable image workload and cost scope before execution; requesting two delivered styles does not determine a fixed exploration call count.

## 3. Let the agent check the current environment

The agent reads `SKILL.md`, project instructions and PLAN/PROGRESS/FOCUS, then reuses the existing installation and project. A usable greybox enters art directly; missing new-format manifests do not require rebuilding gameplay.

Use the actual `$SKILL` directory returned by installation:

```sh
python3 "$SKILL/scripts/greybox.py" host setup --host auto --scope art --project "$PROJECT"
python3 "$SKILL/scripts/greybox.py" knowledge next --stage intake
```

Setup returns the actual project root, selected Python/command prefix, readiness and missing items. Use that returned prefix afterwards. Record only known current-session tool bindings; users need not invent unknown model/tool-schema facts. Supply an existing capability report and current session ID when applicable; see [host setup](hosts-v04.md).

Prepare only needed dependencies: reuse a suitable native image tool; configure an [image service](image-services.md) only when no suitable tool exists. Actual cropping needs Pillow. If the current environment lacks it, prepare only the reusable private image-processing runtime below, then use its returned Python prefix. This needs no image profile or API credentials and submits no image request:

```sh
python3 "$SKILL/scripts/greybox.py" host setup --host auto --scope runtime --runtime image
```

Configure a supplier when asset generation needs it, and prepare Blender only for the required processing. Retain the project's engine version. Setup, checks and balances do not authorize paid production. The first already-authorized real call can provide host invocation evidence; no extra paid capability probe is required.

## 4. Follow the same main workflow

1. **Gameplay baseline:** inspect the actual entry, camera, controls, space and object bindings; record protected relationships. Use the [art intake example](../schemas/intake-art-request-template.json) for structured routing and replace source_ref with the real request. Style count belongs in overview/plan, not unsupported intake fields.
2. **Select multiple styles:** inspect actual outputs using the [concept method](concept-authoring.md); the user chooses delivery styles and priority (H1).
3. **Design and production preparation:** use the [spatial method](spatial-contract.md) and [assembly method](hybrid-production.md) to allocate major forms, functional objects, environment, materials/light and interfaces. After a cheap native probe, confirm design (H2) and the complete sample's actual references/assets/parameters/costs (H3). These can share a presentation; unchanged scoped decisions are reused.
4. **Complete the priority sample:** new native modeling-reference work uses `boards start`, or `boards workbuddy start` in WorkBuddy. Configured image services retain their prepared-request route. Follow the [reference method](modeling-references.md) for exact arguments and per-image review. Every new AI mesh uses approved actual reference images.
5. **Batch expansion and delivery:** after the priority sample passes native gameplay/whole-scene review and actual H4 acceptance, release the other selected styles. Dependencies and account capacity determine concurrency. Local failures retain successful work and original tasks. Present the exact version, remaining defects and H5 delivery object only after every promised style is complete.

At each stage read only the current methods returned by `knowledge next`. Users review actual directions, design, production scope, complete sample and final delivery. Ordinary commands, polling and in-scope repairs add no approval gate.

## 5. Find outputs and recover failures

The agent records the actual case, shared resources, per-style native entries, latest views and next action in PLAN/FOCUS. Workspaces normally use `art/<case>/shared/` and `art/<case>/styles/<style>/`; resource roots follow the engine mapping in [project layout](project-layout.md). Completion means every selected style runs in the agreed native target with gameplay preserved. An image or downloaded model alone is not complete delivery.

On failure preserve the current version and original ledgers. Report version/manifest, host/engine, stage, error and small redacted evidence. [Resume the original task](continuity.md); reconcile an unknown submission's original ID before any repeat. Revalidate affected results only; do not copy whole projects or silently replace the task's package version. Report technical, visual, performance and human-acceptance status separately.

The agent keeps a [usage-feedback recap](usage-feedback.md) during meaningful
failures, user corrections and rework, and shows its path at pause, handoff or
completion. You do not need a separate retrospective form. Ask **“export this
task's usage feedback”** to get a concise Markdown report, full JSON and a local
Issue draft. Review the text, then share the Markdown and JSON with maintainers;
exporting does not submit an Issue or upload the project. Missing records remain
unknown rather than a claim of no problems.

## Other supported scenarios

[Greybox creation/revision and Blender spaces](greybox-authoring.md) may finish at a native baseline or editable `.blend`. [Local visual revisions](visual-harness.md) reuse accepted direction. Discussion ends with the requested proposal; existing work first restores its original records. The user's actual request determines these endpoints rather than automatically expanding them into multistyle production.
