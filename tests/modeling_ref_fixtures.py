"""Small real PNG fixtures for image-conditioned control tests; no generated-art claim."""
from pathlib import Path
import struct,zlib
from greybox import core, modeling_refs

def png_bytes(width=512,height=512,color=(60,120,180),background=(255,255,255),alpha=False):
    channels=4 if alpha else 3
    rows=[]
    for y in range(height):
        row=bytearray()
        for x in range(width):
            rgb=color if width//4<=x<width*3//4 and height//4<=y<height*3//4 else background
            row.extend((*rgb,255) if alpha else rgb)
        rows.append(b'\0'+bytes(row))
    def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,6 if alpha else 2,0,0,0))+chunk(b'IDAT',zlib.compress(b''.join(rows)))+chunk(b'IEND',b'')

def write_reference_package(project,asset_ids,style_id='fixture-style',selected_concept_sha256=None,mode='single'):
    project=Path(project);folder=project/'art/modeling-references'/style_id;folder.mkdir(parents=True,exist_ok=True)
    rows=[]
    for aid in asset_ids:
        views=[]
        for i,role in enumerate(['front'] if mode=='single' else ['front','back']):
            image=folder/(aid+'-'+role+'.png');image.write_bytes(png_bytes(color=(60+i*20,120,180)))
            receipt=folder/(aid+'-'+role+'-receipt.json')
            core.write(receipt,{'schema':1,'source_ref':'synthetic-control-fixture-only','kind':'reference-image-generation-receipt','tool':'synthetic-fixture-only','output_sha256':core.file_hash(image),'actual_input_image_sha256':[selected_concept_sha256 or 'a'*64],'invocation_recorded':True})
            views.append({'id':aid+'-'+role,'role':role,'origin':'host_generated','image':{'path':str(image.relative_to(project)),'sha256':core.file_hash(image)},'generation_receipt':{'path':str(receipt.relative_to(project)),'sha256':core.file_hash(receipt)}})
        rows.append({'asset_id':aid,'mode':mode,'views':views,'review':{'actor':'agent','note':'Synthetic geometric fixture for control tests; not a real art-quality review.','images_digest':core.digest(views),'criteria':{k:True for k in [*modeling_refs.CRITERIA,*(['multiview_consistent'] if mode=='multiview' else[])]}}})
    path=folder/'package.json';core.write(path,{'schema':1,'kind':'modeling-reference-package','policy':modeling_refs.POLICY,'style_id':style_id,'selected_concept_sha256':selected_concept_sha256 or 'a'*64,'assets':rows})
    return {'path':str(path.relative_to(project)),'sha256':core.file_hash(path)}
