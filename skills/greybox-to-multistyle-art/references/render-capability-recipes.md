# Render recipe contracts and bounded lessons

Read after [scene effects](scene-effects.md) when selecting, adapting or publishing a reusable rendering capability. This is method guidance and research experience. It does not install the experimental water implementations or add new `engine lookdev` fields.

## A callable recipe

Use an existing project record or a small tool card. Include only facts needed by another caller:

- **Visible target and scope:** what phenomenon it produces, relevant distance/view/motion, and unsupported goals. State whether it is a shipped tool, project-local experiment or researched candidate.
- **Execution:** actual entry, resolved runtime and working base, input template/schema, dependency setup and preflight where implemented. Do not invent CLI flags or depend on the author's private paths.
- **Native profile:** engine/package version, pipeline, device/backend and required depth, reflections, environment or geometry. Describe units, coordinate/sun conventions and color/data interpretation.
- **Ownership:** caller-owned camera, lights, geometry and clock; what the tool creates or changes; task-owned output and how to remove or replace it. A sample scene generator is distinct from its reusable component.
- **Decision and repair:** when simpler settings suffice, diagnostic symptoms, fallbacks and unresolved limits. Missing support is a capability gap, not permission to switch the project's renderer silently.
- **Evidence and cost:** tested source/config/asset identity, actual native mode and result, transfer/repeat evidence if available, and authoring versus execution cost. Keep interface checks, a rendered first frame, useful local effect, whole-scene quality and independent transfer distinct. Unmeasured performance stays unknown.

Test a new reusable recipe through its documented entry and inputs in a changed space. For a complex or fragile interface, a caller who did not author it can expose hidden setup assumptions. A successful sample, parse or preflight alone does not prove migration, visual quality or ease of use. Use progressive evidence rather than making every local light adjustment satisfy a publishing checklist.

During Skill maintenance, use realistic requests to check whether an agent identifies the responsible layer, chooses a suitable route, obtains necessary inputs, invokes the documented operation and changes method after a useful failure. Provide the task and raw inputs without the expected answer. Add only the native calls needed to check the behavior under test; a full new scene is unnecessary when the question is an interface or routing decision.

A supported routing or diagnostic lesson can enter the method even when its source scene remains unfinished. A specific recipe earns only the scope demonstrated by its actual pixels and transfer evidence; keep untested goals experimental. Whole-scene quality remains part of the production task. Correctly rejecting an unsuitable wrapper is useful diagnosis, but completing the request still needs a feasible next route or a concrete blocking constraint.

## Water research: conditions, not engine rankings

The 2026-10-27 water capability experiment tested native output, limited space transfers, mechanism comparisons and independent selection/calling on Apple M4/Metal. Its source packages and full evidence remain in the owning research project; they are not dependencies of this installable Skill. The lessons below describe those tested recipes, not each engine's maximum quality or general performance.

| Tested route | Observed useful scope | Explicit gaps |
|---|---|---|
| Godot 4.7.2 Forward+; derived MIT GodotSSRWater | Solar glints/waves in a lake and a changed inlet; simpler distant water | Natural near clear-water optics, caustics and runtime budget unqualified. Not the bundled Compatibility recipe. |
| Unity 6000.3 / HDRP 17.3; official Water Samples and a separate component | Lake glints, visible bottom/steps and a controlled caustics-strength contribution | Runtime frame cost and broader space/interaction coverage unqualified. Not the bundled URP bridge. |
| Blender 5.1 Cycles; authored native Ocean/Sky setup | Geometric wave glints and transfer from a large lake to a small clear pool | Caustics and exact optics unqualified in this experiment; offline output does not certify a playable engine. |

| Target or symptom | Evidence-informed next action |
|---|---|
| Solar glints, with no important landmark reflection | First check sun–water–camera geometry and surface slopes. In the tested Godot scenes, removing SSR retained the principal glints; try the simpler supported route and inspect its pixels. |
| Clear near water | Resolve actual bottom, scale and observation view; check transmission, absorption, environment and reflection. A shallow/deep color gradient does not establish optical depth. |
| Working official scene becomes dark after migration | Compare color interpretation, scattering and active sky/environment. The HDRP trial required a joint repair; no individual contribution was isolated. |
| Nearshore speckle | Test the suspected mechanism. In the Godot trial, disabling SSR or refraction did not remove it; TAA reduced the soft-shadow grain. This does not make TAA a universal water fix. |
| Ocean enabled but glints missing | Check sun orientation, wave scale/sampling and foldover before increasing samples. Removing only the secondary displacement layer changed the tested glint pattern. |
| Distant, low-contribution water | A lighter surface or no special water tool may suffice; verify the intended view. |

Independent calling first failed on the Blender tool card's missing templates and execution base. Supplying those details enabled a later partial clear-water call; unsupported caustics remained unresolved. A bounded partial result must retain the missing visual goal rather than silently redefine completion.

For capability lookup, start from the installed version and package. Useful primary entry points are [Godot environment and post-processing](https://docs.godotengine.org/en/stable/tutorials/3d/environment_and_post_processing.html), [Unity HDRP documentation](https://docs.unity3d.com/Packages/com.unity.render-pipelines.high-definition@17.3/manual/index.html), and [Blender Ocean API](https://docs.blender.org/api/current/bpy.types.OceanModifier.html). The Godot research source was [GodotSSRWater at its tested commit](https://github.com/marcelb/GodotSSRWater/tree/391b2f9f9fc289c8ef0ccc2889cf53b5d3cfdaec); inspect its license and current compatibility before adopting it. `stable`/`current` links are navigation, not version pins or proof that every listed feature exists in the target project.
