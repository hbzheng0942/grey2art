import { prepareSpatialManifest, validateSpatialBatch } from './spatial-concept.mjs';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { fingerprint, sha256 } from './storage.mjs';
import { validateAssetReferenceBatch } from './asset-plan.mjs';
import { validateRepairBatch } from './art-realization.mjs';

function text(value, field) {
  if (typeof value !== 'string' || !value.trim()) throw new Error(`Missing art brief: ${field}`);
  return value;
}
function list(value, field, allowEmpty = false) {
  if (!Array.isArray(value) || (!allowEmpty && !value.length)) throw new Error(`Missing art brief: ${field}`);
  return value.map(v => text(v, field));
}

// Unbound exploration sees semantic constraints. It cannot certify spatial fit.
export function compileExploration(contract, directions) {
  if (contract?.schema !== 1) throw new Error('Unsupported art contract');
  const gameplay = list(contract.gameplay, 'gameplay');
  const space = list(contract.space, 'space');
  const scale = list(contract.scale, 'scale');
  const freedom = list(contract.artFreedom, 'artFreedom');
  const locks = list(contract.userArtLocks, 'userArtLocks', true);
  if (!contract.assembly || !contract.sourceEvidence) throw new Error('Assembly constraints and source evidence required');
  if (!Array.isArray(directions) || directions.length < 2) throw new Error('Style exploration requires multiple directions');
  const images = [];
  for (const ref of contract.references || []) {
    if (ref.role === 'greybox-observation') continue;
    if (ref.role !== 'user-art-reference' || !ref.userInstruction || !ref.path || !/^[a-f0-9]{64}$/.test(ref.sha256)) throw new Error('Unclassified or unauthorised art reference');
    images.push({ path: ref.path, sha256: ref.sha256, role: ref.role });
  }
  return directions.map(d => {
    if ('prompt' in d || 'images' in d) throw new Error('Use structured directions, not raw prompt/image overrides');
    const brief = [
      'Use case: stylized-concept. Create ONE whole-scene environment art-direction concept for a playable game.',
      'This is original world and asset design. Redesign architecture, landmark silhouettes and prop identities into the proposed theme. The greybox supplies gameplay, spatial occupancy and scale references only.',
      'GAMEPLAY: ' + gameplay.join(' '),
      'SPATIAL RELATIONSHIPS: ' + space.join(' '),
      'SCALE REFERENCES: ' + scale.join(' '),
      'ART FREEDOM: ' + freedom.join(' '),
      ...(locks.length ? ['EXPLICIT USER ART REQUIREMENTS: ' + locks.join(' ')] : []),
      'WORLD: ' + text(d.world, 'world'),
      'FORM LANGUAGE: ' + text(d.forms, 'forms'),
      'MATERIALS AND LIGHT: ' + text(d.materialsAndLight, 'materialsAndLight'),
      'GAMEPLAY ROLE REINTERPRETATIONS: ' + text(d.roleMapping, 'roleMapping'),
      'COMPOSITION: ' + text(d.composition, 'composition'),
      'Show a cohesive explorable environment with readable ground, multiple asset families, a focal landmark and visible size progression. Architecture and props must be large enough in frame to judge their design. Keep action lanes and interaction surfaces visually legible.',
      'Present an elevated three-quarter representative district scene with foreground, middle distance and background. A concept camera may differ from the runtime camera. Do not reduce the whole level to a tiny distant map. No asset contact sheet, labels, text, UI or watermark.',
      ...(images.length ? ['Attached user art references guide the stated art intent, not level layout or a copied camera.'] : [])
    ];
    return { id: text(d.id, 'id'), label: text(d.label, 'label'), prompt: brief.join('\n\n'), images,
      lineage: { stage: 'style-exploration', contractHash: fingerprint(contract), visualAuthority: 'unbound-art-inspiration', spatialAuthority: 'not-spatially-bound', productionReady: false } };
  });
}

export function prepareImageManifest(spec, root) {
  if (spec.lifecycle === 'rejected-by-user') throw new Error('Rejected art batch: use the corrected discovery manifest');
  if (spec.lifecycle === 'review-only-unbound') throw new Error('Unbound exploration is review-only; create a spatially verified scene brief before production');
  // Existing diagnostic runs keep their exact request identities for resume.
  if (!spec.stage) return spec;
  if (spec.stage === 'art-repair-reference') { validateRepairBatch(spec); return spec; }
  if (spec.stage === 'asset-reference') { validateAssetReferenceBatch(spec); return spec; }
  if (spec.stage === 'style-discovery') return prepareSpatialManifest(spec, root);
  if (spec.stage !== 'style-exploration') throw new Error('Spatial scene discovery is not implemented: requires a verified region, camera, neutral layout guide and slot mapping');
  if (spec.discovery) { validateArtBatch(spec); return spec; }
  if ('tasks' in spec || 'prompt' in spec || 'images' in spec) throw new Error('Discovery tasks must be compiled from the art contract');
  const path = resolve(root, text(spec.contractPath, 'contractPath'));
  const bytes = readFileSync(path), contract = JSON.parse(bytes);
  const tasks = compileExploration(contract, spec.directions);
  const { contractPath, directions, ...settings } = spec;
  return { ...settings, contractSource: { path, sha256: sha256(bytes) }, discovery: { contract, directions }, tasks };
}

export function validateArtBatch(manifest) {
  if (manifest.lifecycle === 'rejected-by-user') throw new Error('Rejected art batch');
  if (manifest.lifecycle === 'review-only-unbound') throw new Error('Unbound exploration is review-only');
  if (!manifest.stage) return;
  if (manifest.stage === 'art-repair-reference') return validateRepairBatch(manifest);
  if (manifest.stage === 'asset-reference') return validateAssetReferenceBatch(manifest);
  if (manifest.stage === 'style-discovery') return validateSpatialBatch(manifest);
  if (manifest.stage !== 'style-exploration' || !manifest.discovery) throw new Error('Uncompiled or unsupported art stage; spatial scene discovery requires verified binding');
  const expected = compileExploration(manifest.discovery.contract, manifest.discovery.directions);
  if (fingerprint(expected) !== fingerprint(manifest.tasks)) throw new Error('Art task changed outside the stage contract');
}
