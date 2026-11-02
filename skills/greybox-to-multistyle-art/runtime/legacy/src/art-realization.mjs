import {fingerprint} from './storage.mjs';
const check=(ok,msg)=>{if(!ok)throw new Error(msg);};
const triple=v=>Array.isArray(v)&&v.length===3&&v.every(x=>Number.isFinite(x)&&x>0);
export function validateRealization(c,source) {
  check(c?.schema===1 && c.styles?.length>=2,'Missing multistyle realization contract');
  if(c.sourceCanonicalSHA256)check(c.sourceCanonicalSHA256===fingerprint(source),'Source content changed');
  const instances=new Map(source.instances.map(x=>[x.id,x]));
  const roles=new Map(source.archetypes.map(x=>[x.id,x]));
  const styleIds=new Set();
  for(const style of c.styles){
    check(!styleIds.has(style.id),'Duplicate style');styleIds.add(style.id);
    check(/^[a-f0-9]{64}$/.test(style.concept?.sha256),'Missing concept hash');
    const regions=new Map();
    for(const region of style.regions){
      check(!regions.has(region.id),'Duplicate concept region');regions.set(region.id,region);
      const b=region.rect;
      check(b?.length===4&&b.every(Number.isFinite)&&b[0]>=0&&b[1]>=0&&b[2]>0&&b[3]>0&&b[0]+b[2]<=1.00001&&b[1]+b[3]<=1.00001,'Invalid concept region');
      check(region.identity&&region.requiredFeatures?.length,'Missing identity or silhouette features');
    }
    const seen=new Set(),covered=new Set();
    for(const b of c.bindings.filter(x=>x.styleId===style.id)){
      const slot=instances.get(b.slotId);check(slot&&!seen.has(b.slotId),'Unknown/duplicate slot');seen.add(b.slotId);
      check(regions.has(b.regionId),'Unmapped concept identity');covered.add(b.regionId);
      check(b.assetKey&&b.variant,'Missing asset or executable variant');
      check(['base','cap-a','cap-b','plain','planted'].includes(b.variant),'Unsupported executable variant');
      check(JSON.stringify(b.gameplayXYZ)===JSON.stringify(roles.get(slot.archetype).size_xyz),'Gameplay envelope changed');
      for(const key of ['minXYZ','maxXYZ','visualTargetXYZ'])check(triple(b[key]),'Invalid visual bounds');
      check(b.minXYZ.every((v,i)=>v<=b.visualTargetXYZ[i]&&b.visualTargetXYZ[i]<=b.maxXYZ[i]),'Infeasible visual target');
      check(b.maxXYZ.every((v,i)=>v<=b.gameplayXYZ[i] || (i===1&&b.visualEnvelopeException?.axis==='y'&&b.visualEnvelopeException.reason&&v<=b.gameplayXYZ[i]*1.625)),'Unreviewed visual envelope expansion');
    }
    check(seen.size===instances.size,'Incomplete slot coverage');
    check([...regions.keys()].every(id=>covered.has(id)),'Concept identity dropped');
  }
  check(c.bindings.every(b=>styleIds.has(b.styleId)),'Unknown binding style');
  check(c.camera?.viewport?.length===2&&c.camera.keepAspect==='height','Missing reproducible review camera');
  return {contractHash:fingerprint(c),styles:styleIds.size,bindings:c.bindings.length};
}

export function compileRepairReferences(c,source,{legacy=false}={}){
  validateRealization(c,source);
  const style=c.styles.find(s=>s.id==='ceramic');
  const specs={
    pitcher:'Extract the OPEN MILK PITCHER BUILDING in the lower middle (x 47–58%, y 63–81%). One ivory rounded pitcher, visible open milk-filled rim, one side handle, cobalt leaf motif, striped doorway awning. Preserve the open top; NO lid, coffee swirl, croissant or giant new roof ornament.',
    jug:'Extract the WIDE-MOUTH MILK JUG BUILDING at lower left (x 19.5–28.5%, y 75–89%). Bulbous ivory milk vessel with broad flared pouring lip, cobalt leaf motifs, small arched doorway. NO cup handle, lid, coffee or pastry. Preserve its distinct flared mouth silhouette.',
    barrier:'Extract one rectangular ivory FLOWER PLANTER on the middle horizontal boundary (x 47–65%, y 55–60%). Long shallow porcelain trough on small cobalt feet, recessed dark soil, dense small green leaves and tiny cream flowers. A planter, not a railing panel. Total width:height:depth approximately 1.08:0.78:0.195; keep flowers predominantly upright so the slim depth is achievable. No round massive end pillars.'
  };
  const tasks=Object.entries(specs).map(([id,description])=>{
    const bindings=c.bindings.filter(b=>b.styleId===style.id&&b.regionId===id&&(id!=='barrier'||b.variant==='planted'));
    const targets=[...new Set(bindings.map(b=>JSON.stringify(b.visualTargetXYZ)))];
    check(legacy||targets.length===1,'Reference family has incompatible visual targets; split designs');
    const xyz=JSON.parse(targets[0]);
    const sizeBrief=`Full object including handle/lip/base targets ${xyz[0]} width × ${xyz[1]} height × ${xyz[2]} depth world units. `;
    return {id:'ceramic-'+id,label:style.regions.find(r=>r.id===id).identity,
    prompt:['Create ONE isolated game-model reference, clean white background, three-quarter view, entire object visible. The attached selected scene is the art authority.',description,
      'Match the scene’s satin ivory porcelain, restrained cobalt painting, small warm doorway, crafted rounded edges and fine detail. Retain the specified object identity, do not invent a new building.',
      ...(legacy?[]:[sizeBrief]),
      id==='barrier'?'One complete integral planter; no neighboring walls.':(legacy?'Full object including handle/lip/base fits 2.35 width × 1.58 height × 2.25 depth world units; design a broad low pavilion. ':'')+'Compact thin base, no detached planters, crates, lamps or scene floor. Preserve the key silhouette within those dimensions.',
      'No labels, text, grid, additional objects or multiple views. Soft neutral studio lighting, minimal shadow.'].join('\n\n'),
    images:[style.concept],lineage:{contractHash:fingerprint(c),regionId:id,conceptSHA256:style.concept.sha256,...(legacy?{}:{visualTargetXYZ:xyz})}};});
  return {schema:1,...(legacy?{}:{compilerRevision:2}),stage:'art-repair-reference',concurrency:2,maxCalls:3,realizationContext:{contract:c,source},tasks};
}
export function validateRepairBatch(m){
  const expected=compileRepairReferences(m.realizationContext.contract,m.realizationContext.source,{legacy:m.compilerRevision===undefined});
  check(fingerprint(m.tasks)===fingerprint(expected.tasks),'Repair reference diverged from visual contract');
  check(m.maxCalls===expected.maxCalls&&m.concurrency<=2,'Repair call envelope changed');
}
