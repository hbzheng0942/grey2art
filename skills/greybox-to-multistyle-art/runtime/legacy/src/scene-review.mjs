import { fingerprint } from './storage.mjs';
export const sceneChecks = ['majorAnchors','relativeScale','routesAndBoundary','artRedesign','assetMappingPlausible'];
export function evaluateSceneReview({ task, artifact, review }) {
  if (!task.lineage?.cameraHash || review.artifactSHA256!==artifact.sha256 || review.guideSHA256!==task.lineage.guideHash || review.cameraHash!==task.lineage.cameraHash || review.sourceConfigSHA256!==task.lineage.sourceConfigSHA256) throw new Error('Review does not match generated scene and spatial binding');
  if (!review.reviewer || !review.method) throw new Error('Review provenance required');
  const checks=sceneChecks.map(id=>({id,...review.checks?.[id]}));
  for(const c of checks) if(!['pass','fail','unverified'].includes(c.status) || typeof c.evidence!=='string' || !c.evidence.trim()) throw new Error('Missing scene review evidence: '+c.id);
  return {reviewHash:fingerprint(review),status:checks.some(c=>c.status==='fail')?'needs-correction':checks.some(c=>c.status==='unverified')?'needs-review':'ready-for-user-selection',productionReady:false,modelAndEngineFeasibility:'unverified',checks};
}

// A human may choose an art direction despite advisory visual concerns. This
// records that choice without rewriting the review or approving production.
export function selectScene({ task, artifact, review, decision }) {
  const diagnostic = evaluateSceneReview({task, artifact, review});
  if (decision?.actor !== 'user' || decision.scope !== 'art-direction' ||
      decision.artifactSHA256 !== artifact.sha256 || !decision.evidence?.trim() ||
      !decision.recordedAt || !decision.styleId) throw new Error('Explicit user selection of this artifact required');
  return {schema:1, styleId:decision.styleId, status:'selected', artifact,
    sourceConfigSHA256:task.lineage.sourceConfigSHA256,
    guideSHA256:task.lineage.guideHash, cameraHash:task.lineage.cameraHash,
    diagnostic, decision, productionReady:false, spendAuthorized:false,
    planningConcerns:diagnostic.checks.filter(c=>c.status!=='pass')};
}
