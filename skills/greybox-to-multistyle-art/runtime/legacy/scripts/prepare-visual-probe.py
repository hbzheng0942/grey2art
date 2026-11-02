"""Bind a completed native Godot probe to current source and immutable assets."""
import argparse,json
from pathlib import Path
from visual_harness import sha
p=argparse.ArgumentParser();p.add_argument('probe',type=Path);p.add_argument('overlay',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
r=json.loads(a.probe.read_text());overlay=a.overlay.resolve()
if not r.get('runtimeRejectionChecks') or not all(x['rejectedWithoutMutation'] for x in r['runtimeRejectionChecks']):raise SystemExit('Missing native feature rejection checks')
def ref(path):
 path=Path(path).resolve();return {'path':str(path),'sha256':sha(path)}
provenance=[ref(a.probe)]
for path,digest in r['runtimeHashes'].items():
 record=ref(overlay/path)
 if record['sha256']!=digest:raise SystemExit('Probe is stale: '+path)
 provenance.append(record)
# Audit all mapped assets, even though representative parity samples cover only a subset.
skin=json.loads((overlay/'data/pilot_skin.json').read_text());assets={v['sha256']:v for style in skin.values() for v in style.values()}
asset_refs=[]
for digest,spec in assets.items():
 record=ref(spec['path'])
 if record['sha256']!=digest:raise SystemExit('Asset content changed')
 asset_refs.append(record)
provenance+=asset_refs
pairs=[{'id':pair['id'],**{k:ref(pair[k]) for k in ['imported','converted','background']}} for pair in r['pairs']]
for pair in pairs:provenance.extend(pair[k] for k in ['imported','converted','background'])
m={'schema':1,'provenance':provenance,'assets':asset_refs,'profile':{'engine':'Godot','engineVersion':r['engineVersion'],'renderer':r['renderer'],'device':r['device'],'native':r['native'],'displayTransform':'ACES exposure 1','viewport':r['viewport'],'camera':{'position':[2.6,2.2,4.8],'lookAt':[0,1,0],'orthographicSize':3.4},'lighting':'render_profile.gd exact bytes in provenance; ceramic/orbital pairs and ceramic sentinels'},'pairs':pairs,'parityLimits':{'meanAbsoluteError255':3,'p95AbsoluteError255':12,'clipIncrease':.01},'sceneReview':None,'scope':'Hole opaque PBR calibration; 2 generated samples + 6 analytic sentinels; other material classes and engines unvalidated'}
a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(m,indent=2)+'\n');print(a.output)
