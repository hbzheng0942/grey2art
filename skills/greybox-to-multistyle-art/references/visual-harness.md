# Visual harness: reusable semantics, engine calibration, scene review

Use for new imports, renderer/material changes, stubborn visual failures, or another gameplay case. The generic entry and bundled legacy comparison scripts have distinct scopes; portability is reported per tested capability.

## Boundary

| Layer | Reuse | Evidence / repair |
|---|---|---|
| Asset semantics | GLB material inventory, texture roles, factors, UVs, alpha/culling, file hashes | `render_contract.py` supports a narrow opaque metallic/roughness UV0 profile. Unsupported input returns a capability gap; do not silently strip it. |
| Engine adapter | Import/material conversion, normal conventions, culling, display transform, gameplay shader integration | Native imported-vs-converted paired renders under the same camera/light. Revalidate on engine/renderer/shader/profile change. |
| Geometry adaptation | Bounds/pivots/contact measurements, declared fitting recipes | Inspect full node transforms, negative scale, normals/tangents, protected silhouettes. Model-specific deformation is not a universal converter. |
| Rendering mechanism | Version/pipeline support, active environment/camera state, depth/transparent/reflection inputs and motion ownership | Use the selected native feature's probe; the opaque Hole material comparator does not validate water, volumetrics or VFX. |
| Scene art | Review schema and defect routing | Author target composition, density, scale hierarchy, surface scale, ground/boundary design, lighting and readability for each concept. |

Preserve native imported materials when gameplay does not require replacement. Conversion should implement only the semantic bridge required by that engine/gameplay. Hole's clipping shader is not a general material for other games. Do not switch another project's renderer to Mobile, copy Hole light values, add gamma correction, or flatten PBR features as a universal fix.

For each affected material, choose preservation, supported-channel baking or target-native reconstruction. Inspect linked inputs and view-dependent nodes before export; a constant fallback is a loss to report, not a successful transfer. Keep distinct optical materials distinct. Use the installed native importer or another suitable operation when a bundled helper lacks support, while preserving required source features and the requested deployment target.

## Implemented commands

For the bundled Hole compatibility runtime, after an explicit native probe (set `$LEGACY` to `<skill>/runtime/legacy`):

```sh
python3 "$LEGACY/scripts/prepare-visual-probe.py" RUN/native-probe/probe.json .local/hole-pilot RUN/visual-manifest.json
python3 "$LEGACY/scripts/visual_harness.py" RUN/visual-manifest.json --output RUN/visual-result.json
```

The comparison command needs Pillow. Manifest paths resolve relative to the manifest. The current Hole native probe is `adapters/godot/material_probe.gd`, staged by the Hole lookdev runner; run Godot with `HOLE_RENDER_EVIDENCE` and `--script tests/material_probe.gd`. Never use headless rendering as native visual evidence.

The manifest binds current runtime/probe/assets and screenshot bytes. It records engine version, renderer/device, viewport/camera/display/light profile, explicit parity limits, all mapped GLB audits and matched imported/converted/background captures. Background subtraction uses the union of both foregrounds. Changed files or mismatched viewport reject stale evidence. Probes currently cover two real tower materials and six analytic color/roughness/metallic/packed-channel/normal sentinels, not all material features. Numeric limits are local regression tolerances, not universal perceptual quality thresholds.

`visual_harness.py` returns technical status separately from art acceptance. Conversion parity can pass when both images are overexposed. Missing scene review returns `needs-scene-review`, never full pass. A scene review binds input signature and native captures and includes actor, observations for identity, silhouette, relative scale, composition, contacts, readability, exposure and playability. A machine-checkable record is not an independent vision oracle; do not fabricate its observations.

Defects need ID, affected region, observation, severity (`blocking` or `polish`), route and status. Blocking failures cannot be waived by a generic pass flag. User-accepted design changes update the contract and trigger affected checks; retain the original observation. Nonblocking polish stays visible without triggering endless paid retries.

## Diagnosis order and routing

1. **Evidence/setup:** exact region, viewport, camera, source/model/adapter hashes. Camera mismatch goes to capture setup, not geometry scaling. Establish an actual rendered first frame before a long capture. On timeout retain the failed stage, version, native mode and available timing; an older version's image cannot certify a new one. Freeze known shader time, random seeds and gameplay for static comparisons; record what was frozen. Test motion separately. The Hole review adapter freezes its coffee shader through a review-only uniform; normal gameplay keeps animation.
2. **Asset availability:** missing textures, unsupported extensions/UV/samplers, import warnings. Go to import/adapter; never default to white material and mark success. Count mesh instances separately from helper/camera/light nodes and retain their transform/dependency roles. A narrow helper's rejection is not an engine-wide limitation.
3. **Conversion parity:** native material vs custom gameplay shader with identical light/display. Wrong color/channel/culling/normal goes to adapter. When factor and texture routes disagree, compare equivalent inputs under that profile before changing light. Check data/color interpretation, normal convention and whether a source strength was already baked before applying it again. Use only the affected channel probe. Near-clip fraction is a diagnostic; intentional white/specular highlights are not automatically defects.
4. **Rendering mechanism, when relevant:** check the installed profile, active settings and required inputs. Transparent/reflection failures may concern scene depth, unavailable off-screen content, render ordering, bottom/boundary geometry or masks. A missing shader/API path calls for a supported native route or bounded extension; unrelated light changes do not supply it. Skip the opaque parity comparator for features outside its stated scope.
5. **Scene exposure:** native and converted both too bright/dark -> scene light/sky/environment/exposure/tone mapping. Check highlight detail, midtone separation and actual runtime view. Do not compensate channel errors with dimmer lights.
6. **Geometry/contact:** transformed bounds, body-vs-accessory proportions, silhouette, penetrations, hovering, support release. Repair placement/pivot or approved local geometry; protect circles and details. Animation/skinning and nonuniform deformation require a dedicated adapter probe.
7. **Composition:** landmarks, secondary identities, density, negative space, ground scale, boundary and background layers. Go to art/assembly recipe; do not regenerate a correct single model to fix layout.
8. **Gameplay:** native camera readability, occlusion, motion, collisions and interaction dependencies. Run case-specific tests; Hole swallow tests do not validate another game.

Use this as diagnostic ordering, not a mandatory pass through every layer. For an ambiguous symptom, state the expected visible change and compare a relevant mechanism under matching camera, time, warm-up and exposure. If the artifact persists, retain that failed hypothesis and inspect the next plausible cause or choose another suitable native route. Keep the critical gap unresolved while unrelated ready work proceeds. Joint fixes may solve a problem but cannot establish each component's isolated contribution. [Bounded water lessons](render-capability-recipes.md) illustrate this without making them universal engine rules.

## Capabilities and limitations

The Hole-specific static gate rejects alpha blend/mask, effective emission, AO textures, vertex colors, material extensions, required glTF extensions, non-UV0 texture mappings/transforms and unsupported sampler modes. Current runtime converter rejects effective unsupported StandardMaterial features and nonstandard material classes. Some importers enable emission with a zero color: test effective contribution rather than the flag alone. Do not reject unused vertex-color flags when no color attribute exists.

Adding support means implementing the feature and adding a native fixture that would fail without it. Priority is features encountered in the next case; do not prebuild speculative Unity/UE/Three converters. Unimplemented: complete glTF structural validation, HDR display certification, automatic composition perception, animation/skinning fit verification, and general cross-engine parity.

## New gameplay intake

`python3 <skill>/scripts/greybox.py intake --project PATH --output OUTPUT.json` performs a read-only, bounded source inventory. It does not copy assets or launch the project. Supply a real entrypoint, engine version, representative region/camera and relevant transition states, gameplay invariants and native baseline before style exploration. Inventory classification is not runtime validation.

Apply relevant checks to the current production case, its input hashes, user-selected styles, whole-scene scope, existing budget and original gameplay checks. A small scene/feature probe needed to resolve an authorized production uncertainty belongs to that case; it does not require a new project or approval round. Separate benchmark campaigns remain a distinct requested scope. Reuse the harness and canonical assets where appropriate, not Hole identity names, exact dimensions, rendering profile or gameplay shader. Preserve actual style/scope authorization; an earlier case's repair budget does not authorize this case.

## Technical references

Material channel semantics: [glTF 2.0 specification](https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html#materials). Godot color-texture hints: [shading language](https://docs.godotengine.org/en/stable/tutorials/shaders/shader_reference/shading_language.html). Local runtime evidence remains authoritative for the installed engine/device combination.
