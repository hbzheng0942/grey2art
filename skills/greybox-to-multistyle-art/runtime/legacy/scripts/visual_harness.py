"""Read-only visual gate. No asset rewriting, rendering, paid calls or implicit acceptance.
Paths in manifests resolve against the manifest directory. Pillow is needed only for pairs.
"""
import argparse, hashlib, json, math
from pathlib import Path
from render_contract import validate_materials

def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()

def compare_pair(imported, converted, background, limits):
    from PIL import Image
    images=[Image.open(p).convert('RGB') for p in [imported,converted,background]]
    if len({i.size for i in images})!=1:raise ValueError('Viewport mismatch')
    # Union mask detects geometry present only in one image. Background is a separate capture.
    a,b,bg=[list(i.get_flattened_data() if hasattr(i,"get_flattened_data") else i.getdata()) for i in images]
    rows=[(x,y) for x,y,z in zip(a,b,bg) if max(abs(x[k]-z[k]) for k in range(3))>8 or max(abs(y[k]-z[k]) for k in range(3))>8]
    if len(rows)<100:raise ValueError('Empty/insufficient foreground')
    errors=sorted(sum(abs(x[k]-y[k]) for k in range(3))/3 for x,y in rows)
    clip=lambda side:sum(max(row[side])>=250 for row in rows)/len(rows)
    metrics={'foregroundPixels':len(rows),'meanAbsoluteError255':sum(errors)/len(errors),'p95AbsoluteError255':errors[int((len(errors)-1)*.95)],'importedNearClipFraction':clip(0),'convertedNearClipFraction':clip(1),'viewport':list(images[0].size)}
    metrics['clipIncrease']=max(0,clip(1)-clip(0))
    required=['meanAbsoluteError255','p95AbsoluteError255','clipIncrease']
    if any(k not in limits or not isinstance(limits[k],(float,int)) or not math.isfinite(limits[k]) or limits[k]<0 for k in required):raise ValueError('Explicit finite comparison limits required')
    return {'status':'pass' if all(metrics[k]<=limits[k] for k in required) else 'fail','metrics':metrics,'limits':limits,'scope':'conversion parity only; identical overexposure can pass'}

def evaluate(manifest, base):
    result={'schema':1,'failures':[],'assetChecks':[],'pairChecks':[],'artAcceptance':False}
    fail=lambda kind,msg:result['failures'].append({'kind':kind,'message':msg})
    def ref(record):
        path=(base/record['path']).resolve()
        if sha(path)!=record['sha256']:raise ValueError('Stale evidence: '+str(path))
        return path
    try:
        if manifest.get('schema')!=1:raise ValueError('Unsupported visual manifest')
        provenance=manifest['provenance']
        if not provenance:raise ValueError('Empty provenance')
        for record in provenance:ref(record)
        signature=hashlib.sha256(json.dumps({k:v for k,v in manifest.items() if k!='sceneReview'},sort_keys=True,separators=(',',':')).encode()).hexdigest()
        result['inputSignature']=signature
        profile=manifest['profile']
        for key in ['engine','engineVersion','renderer','device','displayTransform','viewport','camera','lighting']:
            if not profile.get(key):raise ValueError('Missing profile '+key)
        if profile.get('native') is not True:raise ValueError('Native capture required for render parity')
        if not manifest.get('assets') or not manifest.get('pairs'):raise ValueError('Assets and probe pairs required')
        for asset in manifest['assets']:
            path=ref(asset)
            try:result['assetChecks'].append({'sha256':asset['sha256'],'status':'pass','contract':validate_materials(path)})
            except (AssertionError,ValueError) as e:fail('unsupported-material',str(e))
        seen=set()
        for pair in manifest['pairs']:
            if pair['id'] in seen:raise ValueError('Duplicate probe ID')
            seen.add(pair['id'])
            paths=[ref(pair[k]) for k in ['imported','converted','background']]
            outcome=compare_pair(*paths,manifest['parityLimits'])
            if outcome['metrics']['viewport']!=profile['viewport']:raise ValueError('Profile viewport differs from pixels')
            result['pairChecks'].append({'id':pair['id'],**outcome})
            if outcome['status']!='pass':fail('conversion-parity',pair['id'])
        # Reviews bind exact input + screenshots, not just an author-written pass flag.
        review=manifest.get('sceneReview')
        required={'identity','silhouette','relative-scale','composition','contacts','readability','exposure','playability'}
        if not review:
            result['sceneStatus']='pending-review'
        else:
            if review.get('inputSignature')!=signature:raise ValueError('Stale scene review')
            if review.get('actor') not in ['agent','user'] or not review.get('captures'):raise ValueError('Missing visual reviewer/evidence')
            for capture in review['captures']:ref(capture)
            checks=review.get('checks',{})
            if not required.issubset(checks):raise ValueError('Incomplete scene review dimensions')
            for key,check in checks.items():
                if check.get('status') not in ['pass','fail','unverified'] or not check.get('observation'):raise ValueError('Invalid review '+key)
                if check['status']!='pass':fail('scene-'+key,check['observation'])
            for defect in review.get('defects',[]):
                if defect.get('severity') not in ['blocking','polish']:raise ValueError('Invalid defect severity')
                if not all(defect.get(k) for k in ['id','region','observation','route']):raise ValueError('Unroutable defect')
                if defect.get('severity')=='blocking' and defect.get('status')!='resolved':fail('blocking-defect',defect['id'])
            result['sceneStatus']='reviewed'
            result['artAcceptance']=not result['failures']
    except (KeyError,ValueError,OSError,TypeError) as e:fail('manifest-or-provenance',str(e))
    result['technicalStatus']='fail' if any(f['kind'] not in ['blocking-defect'] and not f['kind'].startswith('scene-') for f in result['failures']) else 'pass'
    result['status']='fail' if result['failures'] else ('pass' if result['artAcceptance'] else 'needs-scene-review')
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('manifest',type=Path);parser.add_argument('--output',type=Path)
    a=parser.parse_args();r=evaluate(json.loads(a.manifest.read_text()),a.manifest.parent)
    text=json.dumps(r,indent=2,ensure_ascii=False)+'\n'
    if a.output:a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(text)
    print(text);raise SystemExit(1 if r['status']=='fail' else 0)
