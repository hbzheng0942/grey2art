# Scene concepts: preserve space, author the visible world

Use for direction exploration and selected-style key views. A concept must retain the supplied gameplay/space authority while making specific visual design choices. It is neither unconstrained illustration nor a material swap over every temporary box.

## Prepare one useful spatial input

1. Inspect the actual native project and a readable three-dimensional capture. Choose a representative view showing the important spaces, openings and functional locations. Start with **one 3D screenshot as spatial authority**; a plan is useful for internal measurement, not a replacement image. If a different camera is needed, capture it natively first rather than inventing camera angles in the prompt. Runtime camera behavior remains authoritative for later play checks.
2. Read the actual pixels. Separate **retain** (topology, openings, gameplay anchors, relative scale, travel/action clearance and relevant visibility) from **redesign** (temporary shells, wall/floor construction, silhouettes, characters, surfaces and lighting). A functional envelope does not automatically freeze its placeholder's outline. Record unresolved constraints; do not guess them from appearance.
3. Write concrete design actions for the main visible elements: e.g. “rounded body, rolled rim, curved tap” rather than only “cute felt style.” Let secondary details follow that construction language. Remove debug marks or distracting placeholder color only when they cause a demonstrated problem; neutral grey boxes still carry box silhouettes.
4. Bind the real screenshot to the image call. A path mentioned in text or attached only to a worker message is not image conditioning. Use [image services](image-services.md) for the actual channel and persist input/output hashes and exact prompt in its existing receipt. Keep the spatial image primary when a channel supports additional style inputs; do not add plans/collages by default or silently drop an input.

## Complete prompt template

Replace brackets with observed project facts and authored choices; do not submit placeholders. Use ordinary visual relationships, not invented numerical camera angles or a long list of contradictory prohibitions.

```text
Task
Create one complete playable-scene art concept from the supplied 3D screenshot.
Keep its viewing direction, perspective and major spatial relationships readable.

What the image controls
The screenshot supplies [spaces and their relationship], [key openings/routes],
[functional locations], and their major scale relationships.
Its temporary boxes, colors and unfinished object/character appearances are placeholders.

Retain
Keep [verified topology and important openings]. Keep [functional anchors and action space].
Preserve [needed routes/sightlines]. Decorative additions fit the available visual space.

Design this direction
World proposition: [specific setting and experience].
Construction language: [silhouette, massing, joints and material organization].
[Main element A]: [specific new form and recognizable function].
[Main element B]: [a different purposeful form using the same language].
Surroundings: [wall/floor/boundary construction, foreground and depth treatment].
Characters/creatures, if present: [proportions, face/clothing/surface design].
Light and color: [concrete choice supporting action/state readability].

Creative freedom
Redesign visible shells, architectural details and surfaces within the retained relationships.
Do not carry temporary box outlines into every final object. Do not relocate the underlying spaces.

Output
One complete scene image, no HUD, debug markings, diagram labels or presentation layout.
```

Teaching example, **not a historical successful output**: suppose native inspection confirms two adjacent work areas, their partition/pass-through, a connecting passage, and the shown workstation anchors. Replace these facts for another project.

```text
Create a complete art concept for the small workshop in this 3D screenshot, using its
viewing direction, perspective and spatial scale. The image controls the two adjacent
work areas, their partition and pass-through, the connecting passage, and workstation
anchors. Keep those relationships and the visible working/arrival spaces. Temporary
box bodies and placeholder colors are not the finished design.

Design a playful hand-built ceramic repair workshop. Use rounded fired-clay masses,
rolled rims, visible joined parts and small glazed accents. Give the washing station
a broad oval bowl, curled rim and curved copper tap; give the drying cabinet a round
belly, separate circular window and clearly exposed controls. Keep their functions
recognizable without copying their rectangular placeholder shells. Use inset tile
panels and simple timber shelves on walls, larger quiet floor tiles around working
areas, and smaller patterned strips at the edges. If figures are visible, redesign
their proportions and work clothes in the same softly rounded language. Warm local
lamps should reveal object contours and leave task states easy to distinguish.

Fit these new shells and details around the existing anchors and passage. Preserve
openings and action visibility. Output one complete scene image without HUD or labels.
```

For a selected concept entering spatial design, use [visual feature analysis](visual-feature-analysis.md) to turn its important visible properties into concrete requirements. Read that method once for the target; revisit it only for changed evidence or an unresolved interpretation.

## Small review after every image

Open the actual input and returned pixels. Record three short results in the **existing image/stage review**: `space: pass|fail|unclear`, `design: pass|fail|unclear`, `style: pass|fail|unclear`, each with one concrete visible observation. These are observations, not new workflow fields or user approvals.

| Check | Look for | If it fails |
|---|---|---|
| Space | Same important room/route relationships, openings, anchor relationships and scale hierarchy; required actions remain visible | Identify the changed relationship and correct its input/wording; do not freeze every prop outline |
| Design | Main shells/construction/characters actually change beyond color or texture | Add concrete construction actions for unchanged main elements; do not relax the spatial authority |
| Style | The proposed form/material language appears coherently in main objects and surroundings | Repair the specific inconsistent elements rather than merely repeat the style name |

Missing/ambiguous pixels mean `unclear`, never pass. Name the region and uncertainty. A screenshot can reveal spatial drift but cannot certify metric geometry. Do not call a design “excellent” or “better” without the supporting visible difference. If both image input and prompt changed, record the combination's result; it does not identify which change caused it. Use one-variable comparisons only when that attribution is needed.

Inspect an initial representative result before expanding the same method across a batch; still check each later image briefly. Reuse current authorization, cap repairs as in [human decisions](human-decisions.md), and recover uncertain submissions through their original jobs. Do not generate another paid test merely to complete this review.

## Directions → H1 → coherent key views

- Default to 8–10 real scene directions unless the user sets another count/imported set. Each brief specifies theme, shape, material, composition, functional identity and supporting light/palette. Differ at least two substantive design axes; inspect images for actual difference. One bounded duplicate repair is enough before selection.
- Present a readable contact sheet with stable IDs and linked originals. H1 binds selected image hashes and priority style; labels alone carry no approval. Preserve every selected style while deepening the priority branch first. Release later styles after the agreed complete H4 sample, without waiting for optional polish.
- For the selected style, choose key views by **uncovered spatial type, reveal, interaction state or transition**, not one image per room/tile by habit. An entry/use/exit or return view is useful only when it reveals a real requirement. Finite spaces can use a compact board.
- Before each atlas image, state **inherit / add / neighbor**: inherit shared landmark IDs, orientation, proportions and construction/material rules; add this view's needed design; identify its adjacent view/space. Supply relevant approved style imagery through supported image inputs. Use one world identity for a shared bridge/device/skyline, not a fresh design per image.
- Compare adjacent views for contradicting openings, landmarks and scale. Mark depicted, extrapolated/offscreen and unresolved content separately. Screenshots do not prove metric agreement. Resolve major conflicts in [spatial design](spatial-contract.md) before H2; do not silently omit difficult features in assembly.

H2 covers atlas **and** spatial package. Finite/full atlases retain full baseline coverage. Large/continuous `scope_mode:focused` preserves the global layout and deepens a connected slice with every touching transition, entry/exit and relevant views; future regions remain coarse and need their own H2 detail before production. Use [workflow](workflow-vnext.md) and [focused template](../schemas/focused-atlas-template.json) for records. Next build complete assemblies and their [isolated references](modeling-references.md), not independent text-to-3D prompts from the atlas.
