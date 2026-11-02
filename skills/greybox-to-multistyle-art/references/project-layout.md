# Case/shared/style workspace contract

One playable greybox is one stable `case_id`. Selectable art worlds have stable `style_id`s and readable display names. New production requires `plan.workspace` / `portfolio.workspace`; it cannot silently keep the old experiments layout. This is part of the existing plan/H3 scope, not a new approval ritual. Register the case after initial intake; add only actual selected styles after H1. Authoring tools and subagents receive the same roots and output roles.

```text
art/<case-id>/
  index.json + README.md                    # navigation and exact version pointers
  shared/
    baseline/                              # gameplay/spatial contracts, input references
    directions/                            # initial concepts and H1 records
    assets/<asset-id>/                      # explicitly shared canonical resources/manifest
    tools/godot/<content-version>/          # generic assembly/validation code, one copy
    production/plans/                      # cross-style checkpoint/portfolio/quotes
    production/runs/<run-id>/               # one cross-style ledger, recovery IDs/evidence
  styles/<style-id>/
    style.json
    concepts/                              # chosen concept + regional/segment/transition atlas
    design/                                # spatial design, recipe, assembly interfaces
    references/<asset-id>/                  # white masters, individual views, reviews
    assets/<asset-id>/                      # immutable model/texture versions + asset.json
    runtime/revisions/<content-version>/    # this style's scene/assembly/source version
    production/plans/                      # style-specific packages and prices
    production/runs/<run-id>/               # independently scoped style work only
```

Create directories only when writing actual files; `register` creates navigation metadata, not empty production trees. Multiple regions/sections remain inside their style (`concepts/regions/<region-id>`, `design/segments/<segment-id>`), not new top-level cases. A cross-style run has **one ledger under shared**; do not duplicate it in every style. Index links identify its participating owners.

## Ownership and storage

Use `workspace.asset_owners` as the explicit approved mapping: `{asset_id:{scope:"shared"}}` or `{asset_id:{scope:"style",style_id:"sunset-coast"}}`. An asset's equivalent `ownership` field may repeat it only consistently. Never infer sharing just because there are many instances or similar models. A reusable algorithm/gameplay interface is shared; sunset roads, sky, water, palette and scene scripts stay with that style. Generic tools consume style-owned data. Different styles normally have different asset IDs; deliberately reusing identical approved assets is explicit.

Asset folders are named by identity (`coastal-palm`), **not vendor** (`lux`, `meshy`). Provider, model, parameters, source image, task IDs, processing and actual content hashes belong in provenance/manifests; raw responses and private recovery tokens stay in production records. Optional rig/animation/cleanup remains the same asset's production chain, with named immutable outputs/clip roles.

Every recorded artifact has `case_id`, ownership/scope, `style_id` when relevant, `asset_id` when relevant, role, actual path and hash. Use `workspace record` for authored concepts/designs/references/plans/tools. Asset and run publishers index their actual outputs automatically. A returned path or folder name alone is not ownership proof.

Physical storage may reuse an existing hash-bound canonical source. An unchanged original source is neither moved nor recopied; `asset.json` records its canonical path/hash. New generated downloads move atomically into the declared owner's asset folder before becoming ready. A different existing target is never overwritten. The core uses content-addressed model filenames; supplier plans may reserve an explicit immutable `v1.glb`/`rigged-v1.glb` path. Changed bytes need a new version; do not modify a model consumed by an accepted scene. Original gameplay/source remains where it is.

Formal scenes cannot depend on downloads, production runs, drafts/archives or another style's resources. Explicit shared assets/tools and declared canonical reuse are allowed; a cross-style reference does not become shared by declaration after the fact. Godot checks the transitive literal TSCN/TRES, script, shader and GLB/glTF dependency closure. Computed loads need `contract.source_paths`; UID-only dependencies need an explicit resource path. Source links/read-only baselines can be declared; owned output paths cannot be redirected through symlinks, even within the same project.

## Three pointers, not one 'latest'

- `development`: exact current assembled resource revision; no validation/acceptance implied.
- `last_verified`: exact native playable result and its bound source/report/log/capture bytes; failed or incomplete checks cannot promote it.
- `user_accepted`: actual H5 receipt and exact reviewed delivery; code cannot invent this decision.

Navigation records file integrity and whether a verified/accepted version matches development separately. New development retains older verified/accepted entries. Changed source/evidence is visibly stale. Runtime revisions contain only the few changed scene/assembly files; identical revisions reuse the same files. Generic tools have their own shared content version; models/textures/engines/caches are not copied into each revision. Git remains the source-history tool. Rollback withdraws only its own development pointer and preserves shared/accepted canonical files; it does not delete milestones or another run's current pointer.

README links show each style's actual entry, concept board, spatial recipe, modeling references, asset manifest, plans/quotes and producing run. Use the index rather than guessing from timestamps. Frozen run records are operational history and do not become the directory holding formal resources.

## Commands

A draft may contain only workspace, selected styles and ownership; full gameplay/assets are completed in the production plan later. `schemas/workspace-template.json` is the workspace object to embed in that draft/plan/portfolio.

```sh
python3 "$SKILL/scripts/greybox.py" workspace register --file "$PLAN" --project "$PROJECT"
python3 "$SKILL/scripts/greybox.py" workspace paths --file "$PLAN" --project "$PROJECT" --style-id sunset-coast
python3 "$SKILL/scripts/greybox.py" workspace record --file "$PLAN" --project "$PROJECT" --style-id sunset-coast --role design --path "$SPATIAL_DESIGN"
python3 "$SKILL/scripts/greybox.py" workspace show --file "$PLAN" --project "$PROJECT"
python3 "$SKILL/scripts/greybox.py" workspace inventory --project "$EXISTING_PROJECT" --output "$INVENTORY"
```

`workspace record` validates role/owner location; it does not move a misplaced file. Fields are persisted in case/style indexes. The actual content gate and H1–H5 remain required. Keep authored documents under the returned roots; supplied canonical inputs can be referenced with declared provenance instead of duplicated.

## Existing projects and engine mapping

Existing `study`/`experiments` may contain live resources or frozen IDs. First inventory ownership, hashes, native dependencies and exact current entry. Do not rename/delete those trees or rewrite frozen approvals. Propose a changed-file mapping and new revision; explicit migration must update native references/UID/import settings, preserve recovery records, verify old/new inputs, rerun native checks and record affected user decisions. The inventory command performs **no migration**; this release does not claim a general automatic migration transaction.

The directory/ownership contract is engine-neutral. Logical documents and production records stay under `art/<case-id>`; engine code/resources use explicit independent mappings:

| Carrier | Resource root | Code / entry root | Concrete dependency check |
|---|---|---|---|
| Godot | `art/<case-id>` | same root, style `runtime/.../play.tscn` | TSCN/TRES/script/shader/glTF closure and actual native validator |
| Unity | `Assets/Art/<case-id>` | same root, style scenes/prefabs/scripts | Text scene/prefab/material/asset GUIDs resolved through actual `.meta`; ambiguous/missing references rejected |
| Three.js | `public/art/<case-id>` | `src/art/<case-id>` | Source imports, loader paths, GLB/glTF external resources; computed paths need bound explicit dependencies |
| Blender | `art/<case-id>` | style `dcc/.../*.blend` | Read-only background inspection of external images/libraries, or exact verified inspection receipt; no changes to the live scene |

`workspace.resource_root` and `workspace.code_root` expose these mappings. Shared tools follow code_root; assets follow resource_root; navigation links the actual location without copying it back into the logical tree. Unity `.meta` and GUID identity must be preserved during any later migration; a folder move is not a harmless rename. Three.js URL roots and source import paths are separate namespaces. Blender files are editor/DCC artifacts and remain `spatial_only` unless an independently validated playable host is declared.

```sh
python3 "$SKILL/scripts/greybox.py" workspace audit --file "$PLAN" --project "$PROJECT" --style-id "$STYLE" --path "$ENGINE_ENTRY" --dependencies "$EXPLICIT_DEPENDENCIES"
```

Engine audit is a real per-format dependency/ownership check, not a native compilation/playability certificate. Each result separates static audit, actual editor inspection and native verification. Unity native testing awaits the user's installation; Three.js still needs its actual host/browser build/play evidence. Don't move gameplay merely to make the tree uniform, and never label Blender output playable because the `.blend` file opens.

## Installing this revision

The verified installer supports explicit `--replace`. It preserves the old symlink itself or recognizable edited skill under sibling `skill-backups/<name>/...` **outside the host's skills discovery tree**, stages/verifies the new small source package, swaps atomically and restores on failure. It never follows a historical skill link to edit its target. A verified identical install does nothing; unrecognized ordinary directories are protected. Backups do not contain game projects or caches. Existing independent histories and local work remain intact.
