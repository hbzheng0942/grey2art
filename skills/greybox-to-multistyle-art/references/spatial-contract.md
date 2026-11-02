# Spatial design: turn a visual intention into a buildable relationship

Use for greybox interpretation, atlas reconciliation and assembly. Link **GameplaySpatialContract** (facts), **ArtSpatialDesign** (appearance) and **AssemblyRecipe** (implementation) through existing IDs/ledgers; no extra ontology or approval.

## Extract the important constraints before designing

For each important opening, functional object, route or landmark, write a compact decision in the existing spatial record:

| Source fact / policy | What to retain | What can change | How to check |
|---|---|---|---|
| Measured interaction position and action clearance | Anchor, usable approach and clearance | Outer shell inside its permitted visual envelope | Native action and close/whole views |
| Required passage or transfer opening | Connectivity, opening and relevant visibility | Trim, surround and adjacent material/construction | Native passage/action plus relevant view |
| Temporary placeholder shape | Only the gameplay requirements actually established by its owner | Silhouette, construction and surface design | Concept comparison and native occupancy |
| Unresolved occluding structure | Preserve the uncertainty until inspected | Do not assume it is removable decoration | Source inspection or targeted user clarification |

These are examples, not default project facts. For each real property distinguish domain (geometry/topology/perception/mechanics/material/lifecycle/performance), edit policy (`exact`, `relational`, `bounded`, `free`, `unresolved`) and provenance (`measured`, `inferred`, `designed`). Approval and verification remain separate. A gate can have an exact collision opening, relational readability and a free outer silhouette.

## Make the smallest useful spatial package

1. **Map the native facts.** Use actual units, routes/rooms, anchors, play envelopes, protected voids and shared identities. Record source paths/IDs and measured values where available. Concept pixels do not establish metric dimensions. Derive human-readable plans from authoritative coordinates, not image-generated diagrams.
2. **Place the main visual masses.** For each space name foreground action, midground identity and background/enclosure. Start from the approved image's main features and readable negative space. Check their projected importance from the real gameplay view; a landmark that exists but is tiny may not deliver the concept. Do not impose a universal screen-percentage target.
3. **Resolve interfaces before detailing.** Record support/contact, entry, connection, adjacency, visibility/occlusion and state/lifetime relationships, with one owner for each shared structure. Include front/up, pivots, sockets and affected neighbors. When a key appearance depends on rendering, add its spatial prerequisites: bottom/depth, wall thickness, light openings, reflection surroundings or sufficiently sampled displacement geometry. Feed these into the same [production plan](hybrid-production.md). Add sections/volumes only where the relationships require them.
4. **Choose useful observations.** Bind actual camera/state IDs to whole composition, necessary interaction, transitions and reverse/branch views. A city may need zoom/rotation states; a route needs actual reached capture anchors. A cinematic view cannot replace ordinary gameplay observation.
5. **Probe the largest uncertainty natively at S6.** Use cheap masses/reused assets; check openings, access, support and major visibility from the planned states. If a high-impact visual mechanism is unproven, include a minimal [scene-effects](scene-effects.md) setup using the project's actual renderer and relevant camera/motion states. Ordinary supported setup needs no separate experiment. Record actual observations, changed dependencies and remaining final-art work in the existing [scene comparison](scene-comparison.md). Correct spatial or rendering prerequisites before dependent asset production. Numerical bounds and screenshot claims remain separate; current workflow validation does not compute all spatial relationships automatically.

Use [spatial](../schemas/spatial-design-template.json) and [observation](../schemas/observation-contract-template.json) templates with [workflow](workflow-vnext.md). H2 covers atlas/spatial package. In-envelope fitting proceeds; material layout/landmark changes revisit the affected H2.

## Preserve the project's kind of space

Keep gameplay, generated visuals, direct-edit overlays and evidence distinct. Generated subscenes/collections have an owner; hand edits stay in a separate overlay referring to the same design. Do not normalize all projects to a flat floor, one water height, linear route or fixed shelf count.

Intentional visual deception may itself be exact. For non-Euclidean spaces use local room frames and portal transforms; do not force a false global map. For dynamic spaces retain release/removal/reset ownership. Select a relevant [space-specific recipe](new-case-recipes.md) only when that topology/mechanic exists. Missing gameplay is a separately scoped implementation task, not scenery work.
