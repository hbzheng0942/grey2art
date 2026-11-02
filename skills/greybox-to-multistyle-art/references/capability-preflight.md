# Capability checks for the current operation

Use when binding tools or a supplier, not as a prerequisite to reading/design. [Host setup](hosts-v04.md) discovers executables and reuses current tools. Verify only the active branch; missing future suppliers do not block greybox creation or concepts using a native image tool. Keep the main model; run serially when delegation is absent.

## Select the dependency

| Operation | Needed now | Conditional recovery |
|---|---|---|
| Routing, plans and local checks | Python 3.10+, project files | Reuse a verified interpreter; no global pip or engine upgrade |
| Greybox/native sample | Selected Godot/Unity, actual project/renderer and native observation | Locate real engine root/executable; preserve its version and source |
| Concepts/reference images | Generator with required reference conditioning, output pixels, inspection and display | Native tools or [image services](image-services.md); a 3D account alone proves none of these |
| Crop/format handling | Decodable source pixels | PNG audit can use stdlib; adaptive crop/JPEG/WebP handling needs Pillow in an external environment |
| Mesh/postprocessing | Selected supplier/model/operation, approved inputs and matching account | [Suppliers](suppliers.md) and [accounts](provider-accounts.md); configure only required routes |
| Geometry/bake/scatter | Required Blender operation | [Background jobs](blender-production.md) or [static backend](blender-backend.md); MCP is optional |
| Rig/motion/retarget | Operations required by gameplay | [Characters](character-pipeline.md); static/reused figures may need none |

Evidence levels stay distinct: **documented → installed/discovered → connected → useful invocation → native integration**. Record exact host, model, operation, engine/version and evidence. A balance does not prove rigging, a GLB does not prove playability, and an installed skill does not prove model vision. See [candidate status](candidate-status.md) for actual support claims. Do not download engines or weights to make an irrelevant capability green.

## Bind the host session

Use `schemas/host-template.json` with actual callable targets, current session/time and evidence. Host-report schema 1 is distinct from runtime-capability schema 2 below. Required neutral operations include file read/write, process execution, pixel inspection, image presentation and a real human-input source. Add generation/reference/editing as needed. Native tool names and session IDs stay in this binding, not creative plans.

```sh
python3 "$SKILL/scripts/greybox.py" host-check --file "$HOST_REPORT" --host-id "$HOST" --session-id "$SESSION"
```

`greybox.overview.check_host_capabilities` validates supplied evidence without invoking tools. Discovery is session-bound and expires after 24 hours; invocation references an actual current operation. Generation, conditioning, inspection and presentation are separate capabilities. A text summary cannot replace pixels. A chat response can supply human input; a local flag cannot authenticate or invent it.

Keep credentials private. [Host setup](hosts-v04.md) covers installation and optional connectors; [provider credential setup](provider-meshy-tripo.md#private-credential-setup) supports hidden user-terminal input and exact provider/region storage. A working native generation binding can satisfy the image route without a second API profile. Connection and useful output retain their own evidence. Do not spend on synthetic generation to prove readiness: the first authorized useful task supplies live evidence.

## Runtime capability receipt

The engine/Lux workflow uses `schemas/capability-template.json`. Schema 2 entries carry `channel:{kind,target,supports}` and `verification:{level,evidence}`. Channel kinds are `host_tool`, `mcp`, `api`, `cli`, `bundled_openapi`; targets identify actual callables/endpoints/executables. Levels are `discovered`, `connection_verified`, `invocation_verified`.

- Legacy `image_generate` needs `text_to_image` and `reference_image`. New plans can declare `required_image_features` for the operation. `image_edit` needs `reference_image`; `native_capture` needs `screenshot`.
- Declare additional `workflow.required_capabilities` or plan `required_capabilities` for the actual design. Pure reuse/procedural art still needs selected concepts or an explicitly accepted supplied set.
- Bundled Lux needs `kind:'bundled_openapi'`, `target:'greybox.lux'`, `region:'cn'|'international'` and connected/invoked evidence for that bridge. Another Lux MCP does not prove these credentials. `greybox.py doctor --region REGION --online` inspects connection/account without generation.
- Other suppliers use their own exact profile/operation evidence. No keys, signed URLs or recovery tokens belong in reports.

Before H3, inventory configured or user-desired suppliers, including missing ones and concrete setup actions. Adapters do not prove useful cloud output. Compare qualified options at the same target; conditional alternatives stay conditional. Prefer a readily available documented non-generation quote, including Lux's existing route. Otherwise use a current official API rate-card estimate; do not invent a quote endpoint. Show 预计费用、依据、报价方式、实际扣费 as described in [supplier prices](suppliers.md#proposals-and-prices). Keep API/consumer wallets distinct. Setup, prices and balances grant no spending authority.

## Refresh and continue

A missing/failed/expired channel blocks only dependent work. Report the operation, affected stage and exact recovery action; continue independent work. Refresh runtime schema-1 receipts to schema 2 without changing creative decisions. Validation rejects future/expired timestamps and unexpected sessions; the 24-hour window is a conservative policy, not measured reliability.

```sh
python3 "$SKILL/scripts/greybox.py" refresh-readiness --run-dir "$RUN" --file "$CAPABILITIES" --session-id "$SESSION"
```

Reconcile submitted tasks through original IDs first. Operational refresh keeps the same unchanged run/decisions; source or creative drift needs the applicable revision. `doctor.productionReady=false` separates package health from complete production. Checks cannot supply native captures or provider results.

## Initial overview

After bounded intake, use `schemas/overview-template.json` and `greybox.py overview --file INPUT --host-report HOST_REPORT --format markdown` if useful. Summarize baseline, endpoint, next stages, relevant setup and unresolved assumptions. Include H1–H5, character needs and provisional costs only for art. This formats actual observations; it neither discovers a project nor adds an approval gate. Update for material scope changes.
