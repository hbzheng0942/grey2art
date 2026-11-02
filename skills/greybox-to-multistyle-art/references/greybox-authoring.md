# Lightweight native greybox authoring

Use this branch to create a native greybox or editable space from a brief, or revise an existing game's controls, interaction or space. It can finish independently. Unity and Godot have the bundled game starter; Blender has the native spatial authoring route below. Read [UE experimental knowledge](ue-greybox-experimental.md) for Unreal requests and [intake routing](intake-routing.md) first.

The game starter supplies a small repeatable starting point and native execution loop. The host agent implements the requested mechanics in project-owned C#/GDScript. Use the [build-plan starter](../schemas/greybox-build-plan-template.json) as a small editable example. It is not an arbitrary game-code translator or a claim that one template can produce every game.

## Start with the experience

Record the authoring carrier, requested endpoint, viewpoint and spatial intent; add the target runtime/device, player actions and visible response when relevant. For playable work add only the goals, failure/recovery and state transitions the brief needs. For a walkthrough, prioritize navigation, viewpoints and spatial legibility; do not invent rewards, hazards or a victory screen.

Choose one bounded first scene or loop. Reuse a sound existing native project and controller when needed. From an empty start create only the scene/camera and the inputs, collision or feedback the endpoint requires. Expose the parameters likely to change. A throwaway mechanic experiment should be identified as such; a requested editable baseline should retain stable structure and IDs from the start.

## Blender spatial route

For an editable `.blend` or offline spatial review, use Blender as the authoring/review carrier with no required game runtime. Inspect an existing source before rebuilding it. Create or revise the requested scene with a task-owned `bpy` script, installed CLI or available MCP, consulting the installed-version API/manual for unfamiliar operations. Bind the actual scene, relevant cameras/collections, units, object identities and external dependencies in the existing project record.

Deliver the editable native source and the views or renders needed to judge the requested space. Read-only inspection/render/export keeps source bytes unchanged; authorized revisions retain ownership and source identity without copying the whole project. Blender rendering establishes its stated offline result. A later Godot/Unity integration preserves that runtime's controls/constraints and gets its own material, view and interaction checks. The packaged `greybox init/build/play/validate` starter below remains Godot/Unity; do not invent Blender support in those commands.

## Operations

For the Godot/Unity starter, all host packages call the same Python entry; MCP is optional. Run only dependencies needed by this branch. Use a task-owned run directory; source and native resources remain in the project, while logs, observations and manifests remain small.

```sh
python3 "$SKILL/scripts/greybox.py" greybox init --project "$PROJECT" --file "$BUILD_PLAN" --run-dir "$RUN" --source-ref "$USER_SOURCE"
python3 "$SKILL/scripts/greybox.py" greybox build --project "$PROJECT" --file "$BUILD_PLAN" --run-dir "$RUN"
python3 "$SKILL/scripts/greybox.py" greybox play --project "$PROJECT" --run-dir "$RUN" --executable "$ENGINE"
python3 "$SKILL/scripts/greybox.py" greybox validate --project "$PROJECT" --run-dir "$RUN" --executable "$ENGINE"
python3 "$SKILL/scripts/greybox.py" greybox handoff --project "$PROJECT" --run-dir "$RUN" --output "$HANDOFF"
python3 "$SKILL/scripts/greybox.py" greybox status --project "$PROJECT" --run-dir "$RUN"
```

Inspect `--help` for operation-specific required arguments. Initialization does not overwrite an unrelated project. A generated scene or successful build is not runtime completion. `play` and `validate` evidence must describe the actual launched version and mode; headless logic checks alone cannot establish visible spatial experience.

`init` writes the small job/build-plan records inside the run directory; it does not create a second task PLAN. Link its `job.json` from the existing continuity workflow/ledgers using the continuity commands and revision checks. On a fresh case the host creates the normal PLAN/PROGRESS; on an existing case append the reference through the designated writer. `validate --file "$STEPS"` may provide a bounded native action configuration; it is not a build-plan argument.

Job phases are `initialized`, `building`, `built`, `validating`, `validated`, `handoff` and `failed`. `status` additionally derives stale state when bound sources change. Restore from the same job and repair the concrete failure; do not create an apparently fresh task to hide a failed native run.

## Small build-plan surface

The common starter uses `schema: 1`, `kind: "greybox-build-plan"`, a stable `id`, selected `engine`, and `goal: "playable"` or `"spatial"`. It describes:

- `player`: position, movement speed, height/radius and `view` (`top_down` or `first_person`).
- `camera`: offset, interpreted by the selected native controller.
- `entities`: stable `id`, semantic `role`, `shape` (`box`, `sphere`, `cylinder`), position, size, color, collider and starter `behavior` (`none`, `collectible`, `goal`, `hazard`, `interactable`).
- `objective`: required object IDs and goal ID when the playable brief needs them.

Semantic roles describe the authored object and are open vocabulary. They are not limited to the starter behavior enum. All dimensions are explicit world units with a declared native coordinate interpretation; do not assume a screenshot supplies dimensions. Engine-specific controllers, physics and scripts stay native and editable. Implement mechanics beyond this starter in project-owned code and preserve that code on rebuild.

The harness owns its generated resources; an agent must not apply a broad regeneration that overwrites unrelated scripts or a previously customized scene. Inspect ownership and changed inputs first, update plan data for parameter edits, and make native code revisions when the mechanics change. Keep canonical assets and exact IDs; a title or hierarchy rename is not an identity change.

## Build, experience and revise

1. Establish the controls, camera and collision scale on a small test patch. Measure relevant movement/reach rather than sizing the full level by eye.
2. Build the useful route, interaction sequence or viewing sequence with simple shapes. Give important spaces distinct silhouettes or diagnostic colors without beginning an art-production branch.
3. Run from the normal entry. Use real input when available; log deterministic action sequences for repeatable checks. Observe feedback, collision, occlusion and state changes as well as numbers.
4. Check the likely bad states: invalid interaction, blocked path, repeated action, leaving the allowed area and reset after a changed state. Only add failure checks relevant to the brief.
5. Repair the largest experience problem locally; rerun the affected loop. Keep last verified output and small failure evidence instead of copying the entire project per attempt.

The first playable path should teach or expose the interaction before demanding precision. Judge corridor width with the moving controller and camera; judge interaction distance from the actual player position. See [greybox knowledge](greybox-knowledge.md) for focused spatial and state lessons.

## Semantics bind real objects

The handoff must identify the actual native scene and object for each semantic entity. Include stable entity ID, role, native node/object identity, native transform/bounds, visual replacement target, collision/trigger ownership, interaction anchors where applicable, relevant relationships and protected gameplay/spatial constraints. A separate list of labels with no native binding is insufficient.

Maintain a clear boundary between visual replacement and behavior. A door may permit a new visible frame but still require a clear opening and trigger; a pickup's decorative geometry may change while its capture volume and stable reward identity remain fixed. Avoid freezing an entire cube mesh merely to preserve its interaction. Record relationships such as required-before, supports, contains and connects only when they exist in this prototype.

Native metadata/components or a source-bound sidecar must resolve to existing objects and match the current source version. `handoff` checks this binding and records the common baseline; it does not certify every intended spatial relationship or authorize art. New mechanics or layout revisions must refresh affected bindings and observations.

The exported `greybox-baseline-manifest` binds the semantic map, source/evidence hashes, goal and a descriptive `next_workflow` hint. That hint is an interface recommendation, not a dispatch instruction. A later art request reads this manifest through the common intake; a greybox-only request stops here.

## Completion boundary

Deliver an editable native entry, source/configuration, semantically bound objects, requested controls or spatial views, actual observations and open issues, and the exact source/runtime version. Apply the following claims only where that endpoint requires them:

| Claim | Required basis |
|---|---|
| Structure exists | Native files and resolved object bindings |
| Runtime works | Actual launch, input/state observations and relevant reset behavior |
| Space is usable | Actual views/traversal with scale, reach, visibility and collision observations |
| User accepts it | The user's actual response, if one was requested or given |

An automated route can establish bounded movement/objective behavior. It cannot establish enjoyment or all possible navigation paths. Report the actual limits without adding a new universal human approval gate. Stop at this greybox endpoint unless the user explicitly requested further art work. H1–H5, image configuration and supplier spending do not gate primitive greybox delivery.

The run directory uses `build-plan.json` alongside `job.json`; this avoids collisions with continuity `PLAN.json` on case-insensitive filesystems. Native probe steps use `id`, `actions`, `frames`, and `expect`; check names come from the selected adapter. Bind `validation.required_checks` and `validation.coverage` (`input`, plus `loop` and `reset` for playable work) to those actual names. A successful smoke run can remain short of a complete playable handoff.

When `--project` is supplied, relative `--run-dir` and greybox `--output` paths resolve inside that project. The greybox job directory must belong to the project; `--file` remains a normal host filesystem input path. Store original user-source references with `init --source-ref`. Native validation re-reads semantic bindings from the actual scene; scene renames and transform edits must update those bindings before handoff.

Verify the active host branch with `host verify --host HOST --scope greybox --engine godot` (or `unity`). For Blender spatial setup use `host verify --host HOST --scope spatial --engine blender --operation create` (or `edit` / `review`). These check the selected executable and common host bindings without requiring unrelated image/supplier configuration. They do not execute a Blender scene operation; actual session, output and pixel evidence remain separate.
