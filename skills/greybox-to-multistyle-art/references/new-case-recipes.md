# Space-specific recipes: select only the relevant row

These are proposed application patterns, not delivered-game evidence. Use with [spatial design](spatial-contract.md) when the project's topology/mechanic needs more than a finite-room recipe. Existing gameplay/streaming/camera rules remain authoritative; scenery work cannot invent a missing city simulation or perspective puzzle.

| Existing space/mechanic | Inspect and preserve | Useful key views and representative native unit |
|---|---|---|
| Finite room | Action/approach envelopes, doors, support, camera coverage, complete interaction loop | Whole room plus only the states/views that reveal a distinct requirement |
| Rooms, maze or hub | Room/door graph, locks/keys where present, loops/dead ends, clearance, shared ownership/lifetime and intended ambiguity | Entrance, decision point, relevant height/door transition, reveal and return. A complete loop with interaction; preserve topology rather than generate a new maze |
| Continuous route/cycling/parkour | Authoritative path and swept envelope, branches, grades, connectors, actual capture trajectories and landmark visibility | Connected sample with entry/use/exit and touching transitions. Inspect ordinary movement and reverse/branch views where relevant; do not treat segment labels as reached anchors |
| City/parcel space | Road network, frontage/access, plots, terrain grades, selection/placement bounds, entity lifecycle and allowed zoom/rotation | Neighborhood/intersection with different present plot classes, edge and landmark; check gameplay zoom and skyline. If simulation exists, exercise place→upgrade→demolish→reload. Reuse building families, not one generation per lot |
| Open/streamed terrain | Terrain/origin policy, cell lifecycle, near/distant budgets, horizon/occlusion and source uncertainty | A real streaming/origin boundary plus meaningful near/far views; large-world precision or terrain deformation needs its actual project adapter |
| Vertical/free-flight/VR | Full 3D clearance, multi-axis visibility and actual comfort/stereo requirements | Required approach/view axes in the native host; a ground-route or monocular screenshot cannot certify these |
| Destruction/deforming spaces | State graph, joints, changing collisions, attachment ownership and reset | Before/during/after transition with continuous native evidence; static bounds cannot certify deformation |
| Perspective puzzle/non-Euclidean space | Camera/FOV, pickup/scale rules, projected silhouette/alignment, occlusion and local-room/portal transforms | Pre-reveal, alignment, manipulation, solved state and transition. Probe the mechanic-critical shape faithfully; do not “fix” intended deception with realistic geometry/light |

For each chosen unit, derive measured plan/sections and a few explicit relations; then allocate visual envelopes, shared interfaces and assembly families. Add art within those constraints and inspect the meaningful native states. Camera/scale/detail settings come from the current game, never from a previous case.

Passing a unit qualifies only its covered spatial/processing types. In the next real production unit, inspect the differences before reusing the method widely. This does not require inventing a separate project or independent unseen-game experiment. Preserve the original baseline and selected-style scope while deepening a bounded sample; [workflow](workflow-vnext.md) governs focused coverage and later expansion.
