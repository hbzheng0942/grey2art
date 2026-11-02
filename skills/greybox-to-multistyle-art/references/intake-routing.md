# Intent, observed state and endpoint

Read this at task intake, meaningful user steering and session resumption. The main use case is an existing gameplay greybox becoming playable prototypes in multiple art styles. Start there when that is the user's request; load authoring only when creation/revision or the observed baseline actually requires it. The agent interprets the request in context; the CLI records and checks structured choices. No natural-language keyword list can replace that interpretation.

## Three separate questions

1. **Intent:** discuss, create, revise gameplay/space, review existing content, author art, or continue existing work? A mention of a greybox or an engine is not itself an instruction to modify it.
2. **State:** no native project, empty project, static layout, partial interaction, usable native baseline, or unknown/stale? These are observations to substantiate, not labels inferred from a file extension.
3. **Endpoint:** proposal, spatial greybox, playable greybox, art deliverable, or the explicitly requested full chain? “Make a greybox” ends at the greybox. “Continue” inherits the current endpoint rather than expanding it.

Use a concise task brief in ordinary language, then record the decision with the actual source request and project observations:

```sh
python3 "$SKILL/scripts/greybox.py" route --file "$INTAKE" --project "$PROJECT" --output "$ROUTE"
```

`$INTAKE` is structured agent interpretation, not an arbitrary prompt sent to a keyword classifier. The returned route is navigation; it grants no paid authorization, creative approval or proof of playability. Keep small route artifacts in the owning case and reference them from its existing PLAN/PROGRESS.

The default tutorial uses the [art request example](../schemas/intake-art-request-template.json). A [greybox-creation example](../schemas/intake-request-template.json) remains available for that explicit task. The request uses `schema: 1`, `kind: "greybox-intake-request"`, `intent` and an actual user-message `source_ref`. Supported intents are `discuss`, `create_greybox`, `edit_greybox`, `review`, `art`, `end_to_end`, `resume` and `pause`. Optional `stop_at` is `discussion`, `greybox` or `art`; legacy `engine` remains `godot`, `unity` or `unreal`. Optional `baseline`, `run_dir` and `case_dir` identify project-contained manifests or current task records.

```json
{
  "schema": 1,
  "kind": "greybox-intake-request",
  "intent": "art",
  "source_ref": "user:current-multistyle-request",
  "stop_at": "art"
}
```

Replace the source reference with the real request. Derive the engine from the existing project or explicit user choice. Delivery mode, selected styles and style count belong in the overview/workflow/plan, not extra intake fields. Defaults are multistyle with at least two delivery styles; an explicitly single-style request uses the supported single-style mode rather than inventing a second style. Concept exploration count is separate from delivery style count.

For native spatial work, optional `authoring_carrier` selects `blender`, `godot`, `unity` or `unreal`; `endpoint` is `spatial` or `playable`, and `runtime` is a game engine or `null`. An existing `.blend` supplied to `--project` also identifies Blender as its authoring carrier. A new empty Blender workspace needs that explicit choice. Use the [Blender spatial example](../schemas/native-spatial-intake-template.json); keep `runtime: null` for an editable space with no requested game host. Blender is not a playable runtime.

Defaults are discuss → discussion, create/edit/review → greybox, art/end-to-end → art. Resume inherits the existing task; it does not default to art. The source reference must resolve to the real instruction in the owning host/task, not the example string. Carrier/runtime selection follows the user/current project; a choice in structured input does not authorize migration.

## Routing decisions

| Intent and state | Next work | Normal stopping point |
|---|---|---|
| Discussion, any state | Research/design against known facts | Requested answer or proposal |
| Art, usable baseline | Existing baseline intake and H1–H5; complete the priority sample, then expand all selected styles | Requested art stage/delivery |
| Greybox creation, absent or empty project | Create a bounded Unity/Godot native greybox | Greybox handoff |
| Greybox/gameplay/space revision, existing content | Inspect and edit only the affected native content | Revised greybox handoff |
| Blender spatial creation/edit, explicit carrier or existing source | `native_spatial_create` / `native_spatial_edit`, using host-native Blender operations | Requested editable space |
| Review, existing Blender source | `native_spatial_review`, with no source-write requirement | Requested observations/views |
| Art, static or partial baseline | Establish only the capabilities needed by the requested endpoint | Continue only if the art endpoint is explicit |
| Any execution request, uncertain state | Inspect entry, dependencies, runtime and current records | Re-evaluate after the observation |
| Continue, existing task | Restore current stage, input version and original ledgers | Inherited endpoint |
| UE greybox | Knowledge and explicitly scoped optional experiment | Experiment findings, without formal engine support claim |

Do not rebuild a viable greybox because its art is rough. Do not start image configuration when the required result is primitive geometry. Conversely, a “greybox” folder containing only meshes does not establish the requested interactions. Preserve supplied scenes, controls, gameplay scripts and existing IDs unless the scoped change requires an explicit revision.

The Blender route returns `execution_route: host_native_blender` and `native_verification: unverified`. It directs the agent to the actual `bpy`/CLI/MCP operation; it does not inspect scene contents or execute authoring itself. `--project` accepts an existing `.blend` or workspace directory without a Godot/Unity marker. For file-based recovery ledgers, supply their project directory. A future playable endpoint requires its declared runtime and later gameplay evidence; it does not make that evidence a prerequisite for Blender authoring.

An existing art project without the new v0.5 baseline manifest still uses the legacy art intake to establish its baseline. Absence of a harness manifest is not a reason to force authoring, recreate scenes or revoke historical decisions.

## Observe proportionately

Inspect only enough to resolve the next decision: engine/version and entry; existing controls, camera and interactions; scene/physics scale; current source and runtime evidence; semantic object bindings; task and provider ledgers. If the project is already working, run a bounded check of the relevant loop instead of recreating it. If only screenshots are provided, spatial dimensions and hidden gameplay remain unknown.

Treat stale source-bound evidence as stale evidence, not automatic failure of every subsystem. A palette change does not require rebuilding a controller. A controller/collision change does require revisiting affected movement, reach and layout. Preserve useful output and identify the affected checks.

Reversible details such as primitive colors, provisional object spacing or an exposed movement speed can use stated assumptions. Clarify when ambiguity changes the core mechanic, engine, endpoint, destructive migration or paid scope. Do not add a universal intake approval gate.

## State and continuity

PLAN owns the current objective, endpoint and references. PROGRESS records meaningful route changes and their user source; FOCUS derives the next work. The existing workgraph, checkpoints and original service ledgers remain authoritative for execution, approvals and recovery. A greybox run manifest describes its files and observations; it must not duplicate mutable approval or spending facts.

On resume, first read these records and inspect unfinished native/background jobs. Recover a known job through its original identity. A missing progress event never proves that no paid request was submitted. Refresh capabilities only for the affected operation. A changed host or model does not discard valid task scope or creative decisions.

Mid-task steering takes precedence within its scope. “First fix movement” suspends the affected art work and activates a bounded greybox revision; “keep the layout” protects that layout while other work continues. Record the new endpoint or temporary subtask, preserved work and affected baseline version. Do not erase prior approvals or use an exploratory question as an instruction to switch routes.

## Merge through a common baseline

Externally supplied and newly authored playable greyboxes converge on one baseline contract: native entry, exact source/dependency version, usable controls, object-bound semantics, protected gameplay/spatial constraints, replaceable visuals and actual runtime observations. Spatial-only work retains the applicable source, identity, dependency and view evidence without inventing controls or a game baseline. No copied project or separate business workflow is needed.

`greybox handoff` exports that descriptive contract. It is a valid endpoint on its own and does not launch H1. The existing art intake may consume it later. Starting concepts, meshes or art production requires the corresponding user scope and the existing authorization/approval rules; no handoff flag can create either.

Greybox-only work ends at a usable semantic greybox plus readability of this common contract. Multistyle art work continues through its requested art endpoint. Historical H1–H5 decisions remain historical and are not relabeled by a new route.

For a full-scene art endpoint, carry the selected concept through [asset route decisions](asset-routes.md) before final native authoring. A proxy made with code is a spatial/composition probe, not an implicit all-procedural production choice. Keep needed AI/model work pending when setup or paid authorization is missing, and still prepare its route, references and cost proposal.
