import {readFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {fingerprint, sha256, verifyArtifact} from './storage.mjs';
import {validateRealization} from './art-realization.mjs';

const requireThat=(ok,message)=>{if(!ok) throw new Error(message);};
const same=(a,b)=>fingerprint(a)===fingerprint(b);
const named=x=>typeof x==='string' && x.trim().length>0;
const safeID=x=>/^[a-z0-9][a-z0-9-]{0,79}$/.test(x||'');

export function validateAssetPlan(plan, source, selections) {
  requireThat(plan?.schema===1 && safeID(plan.id), 'Invalid asset plan');
  requireThat(plan.source.configSHA256===fingerprint(source), 'Plan source content changed');
  requireThat(plan.selectionHash===fingerprint(selections), 'Selected directions changed');
  requireThat(plan.styles.length>=2, 'This experiment requires multiple playable styles');
  const styleIDs=new Set(), allRows=[];
  const sourceIDs=new Map(source.instances.map(i=>[i.id,i]));
  const archetypes=new Map(source.archetypes.map(a=>[a.id,a]));
  requireThat(sourceIDs.size===source.instances.length, 'Duplicate source slot');
  for(const style of plan.styles) {
    requireThat(safeID(style.id) && !styleIDs.has(style.id), 'Duplicate or invalid style'); styleIDs.add(style.id);
    const selected=selections.find(s=>s.styleId===style.id);
    requireThat(selected?.status==='selected' && selected.decision?.actor==='user' &&
      selected.decision.scope==='art-direction' && named(selected.decision.evidence) &&
      selected.decision.artifactSHA256===selected.artifact.sha256 &&
      selected.artifact.sha256===style.conceptSHA256 &&
      selected.sourceConfigSHA256===plan.source.fileSHA256, 'Style lacks matching user selection');
    requireThat(style.environment && ['ground','boundary','lighting','hole'].every(k=>named(style.environment[k])), 'Incomplete environment plan');
    const seen=new Set(), familyIDs=new Set();
    for(const family of style.families) {
      requireThat(safeID(family.id) && !familyIDs.has(family.id), 'Duplicate or invalid family'); familyIDs.add(family.id);
      requireThat(named(family.design) && named(family.variants) && named(family.localFit), 'Missing family design or fit plan');
      requireThat(['pilot','expand'].includes(family.wave) && family.slotIds?.length>0, 'Missing family stage or slots');
      const p=family.generation;
      requireThat(p && ['G1','G1-Turbo'].includes(p.version), 'Missing generation tier');
      if(p.version==='G1-Turbo') {
        requireThat(plan.turboAuthorization?.actor==='user' &&
          plan.turboAuthorization.scope===plan.id && named(plan.turboAuthorization.evidence), 'Turbo requires explicit authorization for this experiment');
        requireThat(p.enablePbr===true, 'This art prototype requires textured Turbo assets');
      }
      else requireThat(!('enablePbr' in p), 'G1 must omit enablePbr');
      requireThat(Number.isInteger(p.faceCount) && p.faceCount>=10000 && p.faceCount<=300000 &&
        same(p.outputFormat,['glb']) && p.aiPredictSize===false, 'Invalid model parameters');
      requireThat(family.reference?.kind==='isolated-white-background' && family.reference.imageCalls===1 &&
        family.reference.fourView===false, 'Unexpected reference route or call count');
      requireThat(family.crossSlotConnections===false, 'Independent gameplay objects cannot be fused');
      for(const id of family.slotIds) {
        const slot=sourceIDs.get(id), a=archetypes.get(slot?.archetype);
        requireThat(slot && !seen.has(id), 'Missing or duplicate logical slot: '+id); seen.add(id);
        requireThat(family.roles.includes(slot.archetype), 'Family role does not match slot: '+id);
        if(slot.support_id) requireThat(sourceIDs.has(slot.support_id), 'Unknown support');
        if(a.support_surface_height_from_base!==undefined) requireThat(
          family.supportSurfaceHeightFromBase===a.support_surface_height_from_base,
          'Support height must match source: '+id);
        allRows.push({styleId:style.id, familyId:family.id, ...slot,
          gameplay_size_xyz:a.size_xyz, fit_span:a.proxy_flat_span,
          min_tier:a.min_tier, score:a.score, growth:a.growth,
          support_surface_height_from_base:a.support_surface_height_from_base??null});
      }
    }
    requireThat(seen.size===sourceIDs.size, 'Incomplete style coverage: '+style.id);
    for(const concern of selected.planningConcerns||[]) requireThat(
      named(style.concernResolutions?.[concern.id]), 'Unaddressed review concern: '+concern.id);
  }
  requireThat(same([...styleIDs].sort(),selections.map(s=>s.styleId).sort()), 'All selected styles must be delivered');
  const families=plan.styles.flatMap(s=>s.families);
  requireThat(plan.budget.imageCalls===families.length && plan.budget.modelCalls===families.length,
    'Call budget must match family plan');
  requireThat(plan.budget.automaticRetries===0, 'Revisions need an explicit scope and cost decision');
  return {planHash:fingerprint(plan), styles:plan.styles.length,
    logicalInstancesPerStyle:source.instances.length, bindings:allRows,
    families:families.length, pilotFamilies:families.filter(f=>f.wave==='pilot').length,
    byTier:Object.fromEntries(['G1','G1-Turbo'].map(v=>[v,families.filter(f=>f.generation.version===v).length])),
    productionReady:false};
}

export function loadPlanContext(root, planPath) {
  const plan=JSON.parse(readFileSync(resolve(root,planPath),'utf8'));
  const bytes=readFileSync(resolve(root,plan.source.path));
  requireThat(sha256(bytes)===plan.source.fileSHA256,'Source file changed');
  const source=JSON.parse(bytes);
  const selections=JSON.parse(readFileSync(resolve(root,plan.selectionsPath),'utf8'));
  for(const selected of selections) verifyArtifact({...selected.artifact,path:resolve(root,selected.artifact.path)});
  const validation=validateAssetPlan(plan,source,selections);
  return {plan,source,selections,validation};
}

export function validatePlanApproval(plan, approval) {
  requireThat(approval?.actor==='user' && approval.scope==='asset-plan-and-references' &&
    approval.planHash===fingerprint(plan) && named(approval.evidence) && approval.recordedAt,
    'Asset plan and reference production need matching user confirmation');
  // This confirmation releases image references only. It cannot authorize Lux
  // charges or certify the still-unseen modeling inputs.
  return {referencesApproved:true,modelReferencesApproved:false,luxSpendApproved:false};
}

export function compileAssetReferences({plan,source,selections,approval,wave='pilot',pilotReview=null,realization=null}) {
  validateAssetPlan(plan,source,selections); validatePlanApproval(plan,approval);
  if(realization){
    validateRealization(realization,source);
    requireThat(realization.styles.every(s=>plan.styles.find(p=>p.id===s.id)?.conceptSHA256===s.concept.sha256),'Realization concepts changed');
    if(wave==='expand')requireThat(pilotReview?.artReview?.contractHash===fingerprint(realization)&&pilotReview.artReview.status==='pass'&&
      ['identity-coverage','silhouette','relative-scale','composition'].every(k=>pilotReview.artReview.checks?.[k]==='pass')&&named(pilotReview.artReview.evidencePath),'Expansion requires closed art review, not only technical pilot pass');
  }
  requireThat(['pilot','expand'].includes(wave), 'Unknown wave');
  if(wave==='expand') requireThat(pilotReview?.planHash===fingerprint(plan) &&
    pilotReview.status==='pass' && pilotReview.engine===plan.source.engine &&
    named(pilotReview.sourceRevision) && named(pilotReview.evidencePath) &&
    pilotReview.styles?.length===plan.styles.length &&
    plan.styles.every(s=>pilotReview.styles.includes(s.id)), 'Expansion needs reviewed native pilot evidence for both styles');
  const tasks=[];
  for(const style of plan.styles) {
    const selection=selections.find(s=>s.styleId===style.id);
    for(const family of style.families.filter(f=>f.wave===wave)) {
      const roles=family.roles.map(id=>source.archetypes.find(a=>a.id===id));
      const sizes=roles.map(a=>`${a.id}: ${a.size_xyz.join(' × ')} world units${a.support_surface_height_from_base!==undefined?`; load-bearing surface exactly ${a.support_surface_height_from_base} above base`:''}`);
      const bindings=realization?.bindings.filter(b=>b.styleId===style.id&&family.slotIds.includes(b.slotId));
      if(bindings)requireThat(bindings.length===family.slotIds.length&&bindings.every(b=>b.assetKey===style.id+'-'+family.id),'Family would merge different concept identities');
      const identities=bindings?[...new Set(bindings.map(b=>b.regionId))].map(id=>realization.styles.find(s=>s.id===style.id).regions.find(r=>r.id===id)):[];
      const prompt=[
        'Create ONE isolated game-model reference on a clean white background, three-quarter view, entire object visible with margin. One asset only, no labels, grid, scene floor, neighboring objects or multiple views.',
        'The attached USER-SELECTED SCENE defines the art. Extract and develop ONLY the object described below; do not reproduce the entire scene. Preserve its recognizable silhouette, material language, large motifs and level of finish.',
        `STYLE: ${style.label}. ${style.materials}`,
        `ASSET: ${family.label}. ${family.design}`,
        ...(realization?[`CONCEPT IDENTITIES: ${JSON.stringify(identities)}. Preserve every listed silhouette feature.`,
          `VISUAL TARGETS AND LIMITS: ${JSON.stringify(bindings.map(b=>({slot:b.slotId,target:b.visualTargetXYZ,min:b.minXYZ,max:b.maxXYZ,variant:b.variant,exception:b.visualEnvelopeException??null})))}. Gameplay sizes below are collision constraints, not substitute silhouettes.`]:[]),
        `${realization?'GAMEPLAY':'TARGET'} DIMENSIONS: ${sizes.join('; ')}. These describe the bounding envelope and contact relationships, not a box-shaped design.`,
        `INDEPENDENCE AND FIT: ${family.localFit}`,
        'Do not include separately swallowable cargo, tables, plants, neighboring buildings, shared pipes or scenery. Details integral to this one object may stay inside its envelope. Keep a clear base and readable silhouette; do not flatten the design into a graybox or substitute generic low-detail primitives.',
        'Use opaque materials except where explicitly specified, soft neutral studio illumination and minimal contact shadow. The source scene may show an oversized landmark or connected pipes: those are resolved by the stated dimensions and independence requirements.'
      ].join('\n\n');
      tasks.push({id:`${style.id}-${family.id}`,label:`${style.label} · ${family.label}`,prompt,
        images:[selection.artifact],lineage:{stage:'asset-reference',planHash:fingerprint(plan),styleId:style.id,
          conceptSHA256:style.conceptSHA256,familyId:family.id,wave,productionReady:false}});
    }
  }
  requireThat(tasks.length>0,'No reference jobs in wave');
  return {schema:1,stage:'asset-reference',route:'host-direct',concurrency:2,maxCalls:tasks.length,
    assetContext:{plan,source,selections,approval,wave,pilotReview,...(realization?{realization}:{})},tasks};
}

export function validateAssetReferenceBatch(manifest) {
  requireThat(manifest.assetContext, 'Asset references must come from an approved plan');
  const expected=compileAssetReferences(manifest.assetContext);
  requireThat(same(expected,manifest), 'Asset-reference manifest changed outside the approved plan');
}
