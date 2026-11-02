# Unreal Engine: knowledge and optional experiments

UE in the v0.5 local iteration is a knowledge branch and optional experimental connection. It is not a formal UE authoring, validation or greybox-to-art executor. Do not map the Unity/Godot operation result to UE, advertise an absent adapter, or silently switch the user's engine.

For a UE request, identify the intended endpoint and inspect the supplied project/version before changing it. A design-only request stops at knowledge and a concrete construction plan. An explicitly requested editor experiment may use an available native/editor/MCP connection with bounded ownership, actual invocation evidence and clear limits. Without a usable connection, deliver the applicable plan and report the exact missing operation; do not fabricate a native result.

## Select the smallest native route

| Need | Candidate route | Verify in the actual project |
|---|---|---|
| Basic blockout | Basic Shapes/static meshes and native collision | Scale, collision, object persistence and normal entry |
| Player movement/camera | Suitable installed template, Blueprint or C++ | Input mapping, possession, camera and actual Play In Editor behavior |
| Interaction/state | Blueprint/C++ runtime logic | Preconditions, feedback, repeated actions and reset |
| Complex local geometry | Modeling tools or Geometry Scripting | Plugin/version, supported functions and saved native output |
| Editor content automation | Editor Python, utilities or an inspected MCP action | Required plugins, affected objects and persistence |

[Epic's Python guide](https://dev.epicgames.com/documentation/en-us/unreal-engine/scripting-the-unreal-editor-using-python) separates editor automation from runtime gameplay. Python is not available as the gameplay scripting environment in Play In Editor or a packaged game. Build gameplay using the appropriate Blueprint/C++ route; an editor script that places actors does not prove playable behavior.

[Geometry Scripting](https://dev.epicgames.com/documentation/en-us/unreal-engine/geometry-scripting-users-guide-in-unreal-engine) provides mesh-generation/editing functions through Blueprint and Python, with plugin setup and function-specific limits. Some operations are editor-only. Choose only the functions needed by the experiment and check the installed engine's documentation. Do not assume every generated mesh supports the same render, instancing or shipping features as a static mesh.

## Optional connector discipline

An already installed UE MCP can be inspected as an optional backend. Record its repository/version, transport, operation, project and output; read the exact operation implementation or primary documentation before invoking changes. The package does not auto-install a floating connector or require Node for other branches. Installation/restart/permission needs belong to the concrete experiment, not every greybox intake.

Use a small task-owned level or explicitly owned actor set, preserving the user's project and unique work. Run an actual action, confirm the saved native result, and test the relevant interaction in UE. Editor responses, screenshots and gameplay observations are separate evidence. A successful connection proves that operation only.

## Experiment handoff

Record native project/level and engine/plugin versions, affected actor identities, scripts/Blueprint references, object roles/relationships, editable visuals versus collision/interaction boundaries, actual observations and unsupported steps. Keep small logs/source diffs and references rather than a project snapshot. Report `experimental` support even if one local operation works; formal native support requires a separate scoped implementation and acceptance effort.

This branch grants no paid model/image invocation and no automatic entry into H1–H5. The v0.5 delivery target remains the Unity/Godot semantic-greybox harness and route/continuity behavior.
