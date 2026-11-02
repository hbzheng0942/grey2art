import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { fingerprint, readJSON, sha256, verifyArtifact } from './storage.mjs';

const requiredText = (x, name) => { if (typeof x !== 'string' || !x.trim()) throw new Error('Missing '+name); return x; };
const near = (a,b) => Array.isArray(a) && Array.isArray(b) && a.length===b.length && a.every((v,i)=>Number.isFinite(v)&&Math.abs(v-b[i])<0.0001);
export function validateSpatialSnapshot(scene) {
  const { spatial, capture, binding } = scene;
  if (!spatial || !capture || !binding) throw new Error('Spatial binding required');
  if (capture.kind!=='source-derived-neutral-spatial-scaffold' || capture.display==='headless') throw new Error('Native spatial scaffold required');
  if (capture.sourceConfigSHA256 !== spatial.sourceConfigSHA256) throw new Error('Scaffold source mismatch');
  if (binding.sourceManifestSHA256 !== spatial.sourceManifestSHA256) throw new Error('Source manifest mismatch');
  if (fingerprint(capture.camera)!==fingerprint(binding.camera)) throw new Error('Camera binding mismatch');
  if (!near(capture.viewport,[binding.guide.width,binding.guide.height])) throw new Error('Guide viewport mismatch');
  if (binding.zone!==capture.zone || !spatial.map.zones.some(z=>z.id===binding.zone)) throw new Error('Unknown bound region');
  const slots = new Map(spatial.slots.map(s=>[s.id,s]));
  const seen=new Set();
  if(capture.allSlots.length!==slots.size) throw new Error('Scaffold omits source slots');
  for(const s of capture.allSlots){
    const o=slots.get(s.id);
    if(!o || seen.has(s.id) || !near(o.position_xyz,s.position_xyz) || !near(o.gameplay_size_xyz,s.size_xyz) || Math.abs(o.yaw_degrees-s.yaw_degrees)>0.0001 || o.support_id!==s.support_id) throw new Error('Source slot mismatch: '+s.id);
    seen.add(s.id);
  }
  const anchors=capture.allSlots.filter(s=>s.anchor);
  if(!anchors.length || new Set(anchors.map(a=>a.anchor)).size!==anchors.length) throw new Error('Unique spatial anchors required');
  for(const a of anchors) if(a.zone!==binding.zone || !near(a.base_px,a.base_px) || a.base_px.length!==2 || a.base_px[0]<0 || a.base_px[0]>capture.viewport[0] || a.base_px[1]<0 || a.base_px[1]>capture.viewport[1]) throw new Error('Anchor outside bound view');
  if(anchors.length!==capture.majorAnchorCount) throw new Error('Anchor count mismatch');
  return anchors;
}

export function compileSpatialScene(scene) {
  const anchors=validateSpatialSnapshot(scene);
  const { artContract, spatial, capture, binding, directions }=scene;
  if(!Array.isArray(directions)||!directions.length) throw new Error('Scene direction required');
  const [width,height]=capture.viewport;
  return directions.map(d=>{
    if('prompt' in d || 'images' in d) throw new Error('Raw scene overrides are not allowed');
    const mapping=anchors.map(a=>{
      const role=a.id.replace(/_\d+$/,'');
      return {anchor:a.anchor,slotId:a.id,role,design:requiredText(d.roles?.[role],role),position_xyz:a.position_xyz,size_xyz:a.size_xyz,basePercent:a.base_px.map((n,i)=>+(100*n/(i?height:width)).toFixed(2))};
    });
    const prompt=[
      'Use case: stylized-concept. Generate ONE production-oriented game environment concept using the attached spatial scaffold. It is a measured crop of an existing playable level, NOT a picture of the old art. Output landscape 3:2.',
      'REFERENCE ROLE: the attached neutral block diagram defines camera, ground-contact positions, scale and open routes. Labels S01..S10 identify slots, not signs to reproduce. Replace its boxes with newly designed objects. Box corners, flat roofs and rectangular silhouettes are NOT design requirements.',
      'SPATIAL CONTRACT: keep the same orthographic viewpoint, projection, framing, land edge, road connections and ground height. Keep the ten labeled objects at their projected ground-contact centers, in the same count and relative size hierarchy. Keep the six tall narrow slots as two rows of three distinct units. Do not merge neighboring slots, add new buildings, insert stairs/raised terraces, or widen footprints into the open lanes. Unlabeled surrounding masses and small-prop clusters remain at their shown positions.',
      'DESIGN FREEDOM: invent curved, sculptural, radial, organic or modular shapes inside each spatial allocation. A bounding box is an allowance, not a mesh to recolor. Use the full height/width category without making distant megastructures. Retain narrow gaps between the repeated tall units. Remove all S labels and guide marks in the final artwork.',
      'GAMEPLAY: '+artContract.gameplay.join(' '),
      'WORLD: '+requiredText(d.world,'world'),
      'FORMS: '+requiredText(d.forms,'forms'),
      'MATERIALS/LIGHT: '+requiredText(d.materialsAndLight,'materialsAndLight'),
      'SLOT DESIGN MAP (dimensions are world units, centers are percentages of the attached image):\n'+mapping.map(m=>`${m.anchor} / ${m.slotId}: ${m.design}; allocation width-height-depth ${m.size_xyz.join(' x ')}; ground-contact center ${m.basePercent.join(', ')}%.`).join('\n'),
      'SMALL PROPS AND SURFACES: '+requiredText(d.smallProps,'smallProps'),
      'PRODUCTION LIMIT: simple closed or thick-walled individual 3D assets, one coherent asset per logical slot; economical repeated modules. Clear broad forms and restrained texture detail. Avoid thin lace, elaborate transparent shells, complex interiors and pasted scenery. Keep existing empty ground readable. Ground treatment and light may change; do not invent surrounding districts.',
      'Present a cohesive finished art environment, not white-box geometry, a contact sheet or an illustrated map. The frame must be directly comparable to the supplied scaffold. No text, UI, watermarks or dimension lines.'
    ].join('\n\n');
    return {id:requiredText(d.id,'id'),label:requiredText(d.label,'label'),prompt,images:[{...binding.guide,role:'spatial-scaffold-only'}],slotMapping:mapping,
      lineage:{stage:'style-discovery',sceneHash:fingerprint(scene),sourceConfigSHA256:spatial.sourceConfigSHA256,cameraHash:fingerprint(capture.camera),guideHash:binding.guide.sha256,spatialReview:'pending',feasibility:'unverified',productionReady:false}};
  });
}

export function prepareSpatialManifest(spec,root){
  if(spec.scene){validateSpatialBatch(spec);return spec;}
  if('tasks' in spec) throw new Error('Compile spatial tasks from source binding');
  const binding=readJSON(resolve(root,requiredText(spec.bindingPath,'bindingPath')));
  const readBound=ref=>{
    const bytes=readFileSync(resolve(root,ref.path));
    if(sha256(bytes)!==ref.sha256) throw new Error('Bound input changed: '+ref.path);
    return JSON.parse(bytes);
  };
  const spatial=readBound(binding.spatialContract),capture=readBound(binding.capture);
  if(sha256(readFileSync(spatial.sourceConfig))!==spatial.sourceConfigSHA256) throw new Error('Canonical greybox changed');
  verifyArtifact(binding.guide);
  const artContract=readJSON(resolve(root,requiredText(spec.contractPath,'contractPath')));
  if (artContract.sourceEvidence?.sha256 !== spatial.sourceManifestSHA256) throw new Error('Art brief belongs to a different source greybox');
  const scene={binding,spatial,capture,artContract,directions:structuredClone(spec.directions)};
  const {bindingPath,contractPath,directions,...settings}=spec;
  return {...settings,scene,tasks:compileSpatialScene(scene)};
}

export function validateSpatialBatch(manifest){
  if(!manifest.scene) throw new Error('Spatial binding required');
  const tasks=compileSpatialScene(manifest.scene);
  if(fingerprint(tasks)!==fingerprint(manifest.tasks)) throw new Error('Spatial task changed outside source binding');
}
