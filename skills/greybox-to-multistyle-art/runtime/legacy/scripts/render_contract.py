"""Fail before assembly if imported PBR features exceed the tested clipping adapter."""
import json,struct
from pathlib import Path

def validate_materials(path):
    with Path(path).open('rb') as f:
        magic,version,total=struct.unpack('<III',f.read(12))
        assert magic==0x46546c67 and version==2, f'Not GLB 2: {path}'
        assert total==Path(path).stat().st_size, 'GLB length mismatch'
        size,kind=struct.unpack('<II',f.read(8))
        assert size%4==0 and size<=total-20, 'Invalid JSON chunk length'
        assert kind==0x4e4f534a, 'First GLB chunk must be JSON'
        gltf=json.loads(f.read(size))
    assert not gltf.get('extensionsRequired'), 'Required glTF extensions need adapter capability validation'
    materials=gltf.get('materials',[])
    assert materials, f'No PBR materials: {path}'
    for i,m in enumerate(materials):
        prefix=f'{path} material {i}: '
        assert m.get('alphaMode','OPAQUE')=='OPAQUE', prefix+'alpha mode needs adapter support'
        assert not m.get('extensions'), prefix+'material extensions need adapter support'
        assert not m.get('occlusionTexture'), prefix+'AO texture needs adapter support'
        assert not m.get('emissiveTexture') and not any(m.get('emissiveFactor',[0,0,0])), prefix+'emission needs adapter support'
        pbr=m.get('pbrMetallicRoughness',{})
        assert not pbr.get('extensions'), prefix+'PBR extensions need adapter support'
        for key in ['metallicFactor','roughnessFactor']:
            value=pbr.get(key,1)
            assert isinstance(value,(int,float)) and 0<=value<=1, prefix+'invalid '+key
        color=pbr.get('baseColorFactor',[1,1,1,1])
        assert len(color)==4 and all(isinstance(v,(int,float)) and 0<=v<=1 for v in color), prefix+'invalid baseColorFactor'
        for texture in [pbr.get('baseColorTexture'),pbr.get('metallicRoughnessTexture'),m.get('normalTexture')]:
            if texture:
                assert texture.get('texCoord',0)==0 and not texture.get('extensions'), prefix+'UV set/transform needs adapter support'
    for mesh in gltf.get('meshes',[]):
        for primitive in mesh.get('primitives',[]):
            assert primitive.get('mode',4)==4, f'{path}: non-triangle primitive needs adapter support'
            assert 'COLOR_0' not in primitive.get('attributes',{}), f'{path}: vertex colors need adapter support'
    for sampler in gltf.get('samplers',[]):
        assert sampler.get('wrapS',10497)==10497 and sampler.get('wrapT',10497)==10497, f'{path}: non-repeat sampler needs adapter support'
        assert sampler.get('magFilter',9729)==9729 and sampler.get('minFilter',9987) in [9729,9987], f'{path}: nearest/mixed sampler filtering needs adapter support'
    return {'path':str(path),'materials':len(materials),'profile':'opaque-metallic-roughness-uv0','albedo':'sRGB','roughness':'linear G','metallic':'linear B','doubleSided':[m.get('doubleSided',False) for m in materials]}
