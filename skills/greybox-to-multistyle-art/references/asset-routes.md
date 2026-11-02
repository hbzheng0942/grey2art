# Decide asset routes before turning a proxy into final art

Use after selecting a concept and before producing final scene art, including
when the host can write native engine code directly. Keep this decision in the
existing design/production table and PLAN/FOCUS; do not create another approval
ledger. Greybox-only work and an explicitly local material/light correction keep
their narrower endpoint.

## Make the decision visible

Identify the concept's important **form, surface, light, atmosphere and motion**
requirements. A bridge silhouette, boat hull or character body is form even when
it belongs to the environment. Native environment/material ownership does not
provide that geometry.

For each source family choose `generated`, `reuse`, `procedural` or `hybrid` and
show it on the asset/BOM board and assembly map. For a dominant form record a
short `route_evaluation` of generated, reused and procedural options: suitability,
available evidence and the reason for the selected route. An unavailable account
or missing paid authorization is a pending dependency, not evidence that a code
approximation meets the visual target. Recommend qualified vendors by the actual
asset requirements; the user need not name a service to activate this work.

- Distinctive organic/iconic form or detailed identity normally needs a qualified
  image-conditioned model or suitable existing authored model.
- Exact openings, paths, supports and joins can keep controlled geometry. A
  mixed assembly uses generated or reused appearance modules around that structure.
  Reused modules stay `reuse`, with controlled structure recorded separately as
  `procedural`; that assembly needs no new AI task. Reserve source-family
  `route:hybrid` for a family that actually includes new generated geometry.
- Procedural final appearance is valid for a rule-expressible target **after
  actual target/native image comparison demonstrates the match**. Record the
  task-specific reason, image ID and observed match. A cheap proxy, elapsed time
  or an earlier decision to write code is not that evidence.
- Surface, light, atmosphere and motion may use native systems and empty mesh
  catalogs where appropriate. Keep the whole composition and its dependencies.

S6's cheap masses and provisional rendering remain a proxy. Before replacing or
refining them as final art, return to this route decision, prepare the actual
modeling references and complete assembly, and obtain the existing H3 decision.
Do not silently carry every proxy mesh into final production.

## Follow the selected routes

`feature_kind` is `form`, `surface`, `light`, `atmosphere` or `motion` in the
existing production table. Form features need actual asset families regardless
of whether their responsibility is appearance, precise geometry or environment.
The H3 table also carries `asset_route_contract:asset-routes-v1`, bound by its
stage digest. Changing a copied workflow's top-level policy cannot downgrade
that contract. The [workflow](workflow-vnext.md) checks this and dominant-form route evaluation.
It checks declarations and evidence bindings; the reviewer still examines pixels.

Generated/hybrid new meshes bind an actual `image_to_3d` or `multiview_to_3d`
operation and reviewed isolated image inputs. A name, scene concept, material
transfer or text prompt is not a model task. H3 authorizes the concrete operations,
parameters, references and cost ceilings; preparation is possible before paid
submission. Preserve pending/unknown tasks and original IDs. If a route cannot
run, continue independent work and report that asset as pending. A switch to
procedural/reuse requires the affected design, visual evidence and scoped user
decision; “continue” does not silently select a different route.

Before H4, each generated/hybrid source family must have a real completed
original task and retained source model. Add its small `model_task_bindings`
entry to the existing [sample input manifest](../schemas/sample-inputs-template.json):
asset ID, original run directory, supplier operation ID when applicable, original
task ID, source output and realized output path/hash. Use the existing
`supplier-run.json` or legacy `run.json`; do not copy it into a new ledger or
regenerate the model. The source and realized model remain sample dependencies.
For local processing, record its actual method/source and input/output hash
lineage in the same binding. This records processing, not a new generation claim.

The H4 check reopens the original ledger, verifies completed state, original ID,
approved image inputs and returned source model identity. It also checks that
the realized model is reachable from the actual native scene/config and its
resource/assembly references, without using the full file inventory as roots.
A downloaded model merely listed in the manifest cannot pass. An unresolved
computed loader remains unverified until its actual native/assembly binding is
expressed in inspectable evidence; listing a file does not resolve that gap. Missing, failed,
unknown or still-pending model work blocks the affected sample. Future expansion
tasks are not required to finish before the original sample's H4.

Use these methods through the selected package. Direct host commands are not
globally sandboxed by this Skill; the agent must not bypass the route checkpoint
by writing engine code outside it. Never report a skipped production path as a
completed Skill workflow or count technical checks as visual acceptance.
