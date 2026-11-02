"""Image-conditioned modeling references, deterministic pixel checks and bound visual review.

PNG RGB/RGBA8 is supported with stdlib; optional Pillow enables other encodings.
Pixel checks never claim style, silhouette semantics or successful de-lighting.
"""
from __future__ import annotations
import hashlib
import io
from pathlib import Path
import struct
import zlib
from collections import OrderedDict, namedtuple
from threading import RLock
from . import core

POLICY = "image-conditioned-v1"  # Historical packages remain recoverable unchanged.
CURRENT_POLICY = "game-asset-reference-v2"
CATEGORIES = {"humanoid", "animal", "prop", "architecture", "vegetation", "mechanism"}
USES = {"static", "rigid_motion", "skeletal_animation"}
CRITERIA = ("isolated_subject", "complete_silhouette", "style_consistent", "neutral_lighting",
            "no_baked_shadows", "no_baked_highlights", "no_text_or_layout")
MAX_PIXELS = 8_388_608
MAX_IMAGE_BYTES = 32*1024*1024
# Bump when decoding or pixel-audit rules change. No approval or visual review
# state enters this process-local cache, and no cache file is trusted or written.
PIXEL_AUDIT_VERSION = "rgb-rgba-thresholds-v1"
AUDIT_CACHE_MAXSIZE = 256
_PixelAudit = namedtuple("PixelAudit", "width height opaque border_white_fraction nonwhite_fraction visible_fraction nonwhite_bbox")
_CacheInfo = namedtuple("CacheInfo", "hits misses maxsize currsize")
_audit_cache = OrderedDict()
_audit_lock = RLock()
_audit_hits = _audit_misses = 0


def _png(raw):
    core.require(raw.startswith(b"\x89PNG\r\n\x1a\n"), "Not PNG")
    pos, chunks, header, ended, data_ended = 8, [], None, False, False
    while pos + 12 <= len(raw):
        size = struct.unpack_from(">I", raw, pos)[0]
        core.require(pos + size + 12 <= len(raw), "Truncated PNG chunk")
        kind, data = raw[pos+4:pos+8], raw[pos+8:pos+8+size]
        crc = struct.unpack_from(">I", raw, pos+8+size)[0]
        core.require(zlib.crc32(kind+data) & 0xffffffff == crc, "PNG checksum failed")
        core.require(header is not None or kind == b"IHDR", "PNG IHDR must be first")
        if chunks and kind != b"IDAT": data_ended = True
        if kind == b"IHDR":
            core.require(header is None and pos == 8 and size == 13, "Invalid PNG header")
            header = struct.unpack(">IIBBBBB", data)
        elif kind == b"IDAT":
            core.require(not data_ended, "PNG IDAT chunks must be contiguous")
            chunks.append(data)
        elif kind == b"IEND":
            core.require(size == 0 and bool(chunks), "Invalid PNG end")
            ended = True; pos += size+12; break
        elif kind == b"PLTE":
            core.require(not chunks and size > 0 and size % 3 == 0 and size <= 768, "Invalid PNG palette")
        else:
            core.require(bool(kind[0] & 32), "Unsupported PNG critical chunk")
        pos += size+12
    core.require(header is not None and ended and pos == len(raw), "Incomplete PNG")
    w, h, bits, color, compression, filters, interlace = header
    core.require(w > 0 and h > 0 and w*h <= MAX_PIXELS, "Reference dimensions exceed safe pixel limit")
    if (bits, color, compression, filters, interlace) not in ((8, 2, 0, 0, 0), (8, 6, 0, 0, 0)):
        return None
    channels = 3 if color == 2 else 4
    stride, expected = w*channels, (w*channels+1)*h
    decoder = zlib.decompressobj()
    decoded = decoder.decompress(b"".join(chunks), expected+1)
    core.require(len(decoded) == expected and decoder.eof and not decoder.unused_data,
                 "Invalid or oversized PNG pixel payload")
    previous = bytearray(stride); rows = []
    for y in range(h):
        start = y*(stride+1); filter_id = decoded[start]
        core.require(filter_id in range(5), "Unsupported PNG filter")
        row = bytearray(decoded[start+1:start+1+stride])
        if filter_id:
            for x in range(stride):
                a = row[x-channels] if x >= channels else 0
                b = previous[x]; c = previous[x-channels] if x >= channels else 0
                if filter_id == 1: predictor = a
                elif filter_id == 2: predictor = b
                elif filter_id == 3: predictor = (a+b)//2
                else:
                    value=a+b-c; pa,pb,pc=abs(value-a),abs(value-b),abs(value-c)
                    predictor=a if pa <= pb and pa <= pc else b if pb <= pc else c
                row[x]=(row[x]+predictor)&255
        rows.append(bytes(row)); previous=row
    return w,h,channels,b"".join(rows)


def _decode(raw):
    core.require(len(raw) <= MAX_IMAGE_BYTES, "Reference image exceeds32MiB")
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        result = _png(raw)
        if result is not None: return result
    try:
        from PIL import Image
    except ImportError as error:
        raise ValueError("Pixel audit needs RGB/RGBA8 noninterlaced PNG, or install optional Pillow for JPEG/WebP/other PNG encodings") from error
    with Image.open(io.BytesIO(raw)) as im:
        core.require(im.width*im.height <= MAX_PIXELS, "Reference dimensions exceed safe pixel limit")
        im.load(); im=im.convert("RGBA")
        return im.width,im.height,4,im.tobytes()


def _audit_pixels(raw):
    w,h,c,pixels=_decode(raw)
    core.require(w >= 256 and h >= 256, "Modeling reference must be at least256px on each axis; prefer1024px or provider requirement")
    opaque=True; border=white=subject=visible=0; minx,miny,maxx,maxy=w,h,-1,-1
    for y in range(h):
        for x in range(w):
            i=(y*w+x)*c; r,g,b=pixels[i:i+3]; a=pixels[i+3] if c==4 else 255
            opaque=opaque and a==255
            visible += a>8
            is_white=min(r,g,b)>=245 and a==255
            if x in (0,w-1) or y in (0,h-1): border+=1; white+=is_white
            if a>8 and not is_white:
                subject+=1; minx=min(minx,x);miny=min(miny,y);maxx=max(maxx,x);maxy=max(maxy,y)
    return _PixelAudit(w,h,opaque,white/border,subject/(w*h),visible/(w*h),
                       (minx,miny,maxx,maxy) if subject else None)


def _audit(raw):
    """Cache only immutable measurements, never encoded/decoded images or passes."""
    global _audit_hits, _audit_misses
    core.require(isinstance(raw, bytes), "Reference audit requires immutable image bytes")
    core.require(len(raw) <= MAX_IMAGE_BYTES, "Reference image exceeds32MiB")
    key = (PIXEL_AUDIT_VERSION, MAX_PIXELS, MAX_IMAGE_BYTES, hashlib.sha256(raw).digest())
    # Serialize misses so simultaneous validations cannot multiply decode memory.
    with _audit_lock:
        if key in _audit_cache:
            _audit_hits += 1
            stats = _audit_cache.pop(key)
        else:
            _audit_misses += 1
            stats = _audit_pixels(raw)  # Exceptions leave no cached result.
        _audit_cache[key] = stats
        while len(_audit_cache) > AUDIT_CACHE_MAXSIZE:
            _audit_cache.popitem(last=False)
    result = stats._asdict()
    result["nonwhite_bbox"] = list(stats.nonwhite_bbox) if stats.nonwhite_bbox is not None else None
    result["semantic_checks"] = "visual review required; white/light subject extent is not inferred from thresholding"
    return result


def _audit_cache_clear():
    global _audit_hits, _audit_misses
    with _audit_lock:
        _audit_cache.clear()
        _audit_hits = _audit_misses = 0


def _audit_cache_info():
    with _audit_lock:
        return _CacheInfo(_audit_hits, _audit_misses, AUDIT_CACHE_MAXSIZE, len(_audit_cache))


# Preserve the diagnostics/reset interface of the former functools cache.
_audit.cache_clear = _audit_cache_clear
_audit.cache_info = _audit_cache_info


def audit_image(path):
    path=Path(path); raw=path.read_bytes()
    return {"path":str(path.resolve()),"sha256":hashlib.sha256(raw).hexdigest(),**_audit(raw)}


def _file(ref, project, dependencies):
    core.require(isinstance(ref,dict) and isinstance(ref.get("path"),str) and isinstance(ref.get("sha256"),str),
                 "Reference file needs path and SHA256")
    path=core.resolve_input(ref["path"],project)
    core.require(core.inside(path,project) and path.is_file(),"Modeling reference must be a real project-contained file")
    raw=path.read_bytes();actual=hashlib.sha256(raw).hexdigest()
    core.require(actual==ref["sha256"],"Modeling reference changed; re-review the affected approved package")
    dependencies[str(path)]={"path":str(path),"sha256":actual}
    return path,raw


def _text(value):
    return isinstance(value, str) and bool(value.strip()) and not value.strip().startswith("REPLACE_")


def _modeling_contract(asset):
    """Validate design declarations, never infer anatomy or pose from image pixels."""
    contract = asset.get("modeling_contract")
    core.require(isinstance(contract, dict), "Current references need a modeling_contract with category and use")
    category, use = contract.get("category"), contract.get("use")
    core.require(isinstance(category, str) and category in CATEGORIES and isinstance(use, str) and use in USES,
                 "Choose a supported reference category and use")
    core.require(_text(contract.get("structure")), "Describe the intended volume and critical construction, not only a style label")
    if category in {"architecture", "mechanism"}:
        interfaces = contract.get("interfaces")
        core.require(isinstance(interfaces, list) and bool(interfaces) and all(_text(v) for v in interfaces),
                     "Architecture/mechanisms need explicit assembly or working interfaces")
    pose = contract.get("pose")
    if use == "skeletal_animation" and category in {"humanoid", "animal"}:
        allowed = {"A", "T"} if category == "humanoid" else {"natural_stance"}
        core.require(isinstance(pose, str) and pose in allowed, "Animated humanoids need one A or T pose; animals need natural_stance")
        core.require(_text(contract.get("pose_details")), "Describe readable limb/joint separation for this character")
    elif pose is not None:
        core.require(category in {"humanoid", "animal"} and isinstance(pose, str) and pose in {"A", "T", "natural_stance", "fixed"},
                     "Pose applies only to character references; static sculptures may use fixed")
    if use == "skeletal_animation" and category not in {"humanoid", "animal"}:
        core.require(_text(contract.get("deformation_plan")),
                     "Non-character skeletal assets need an explicit deformation plan, not an assumed humanoid rig")
    return contract


def _review_v2(asset, contract):
    review, views = asset.get("review", {}), asset["views"]
    core.require(review.get("contract_digest") == core.digest(contract),
                 "Reference review is stale for this modeling contract")
    observations = review.get("observations")
    core.require(isinstance(observations, list) and len(observations) == len(views),
                 "Current reference review needs one actual pixel observation per view, not boolean criteria")
    core.require(all(isinstance(view, dict) and core.safe_id(view.get("id")) for view in views),
                 "Reference observations need valid view identities")
    expected = {view["id"]: view for view in views}
    core.require(len(expected) == len(views), "Reference observations need unique view identities")
    seen = set()
    for item in observations:
        core.require(isinstance(item, dict), "Reference observation must be an object")
        view_id = item.get("view_id")
        core.require(isinstance(view_id, str) and view_id in expected and view_id not in seen,
                     "Reference observations must cover the exact unique view IDs")
        seen.add(view_id)
        core.require(isinstance(item.get("status"), str) and item["status"] in {"pass", "fail", "unclear"}, "Record pass, fail or unclear for each observed image")
        core.require(_text(item.get("observation")) and _text(item.get("source_ref")),
                     "Record visible findings and the actual pixel-inspection invocation/source")
        core.require(item.get("status") == "pass", "Failed or unclear reference observations cannot enter model production")
    if len(views) > 1:
        core.require(_text(review.get("cross_view_observation")),
                     "Multiview review needs a concrete same-object/pose observation")
    pose = contract.get("pose")
    if pose is not None:
        core.require(all(view.get("pose") == pose for view in views),
                     "Every character view must declare the same selected body pose; view role changes the camera only")


def validate_package(package, project, style_id=None, expected_asset_ids=None, selected_concept_sha256=None):
    core.require(isinstance(package,dict) and package.get("schema")==1 and package.get("kind")=="modeling-reference-package"
                 and isinstance(package.get("policy"), str) and package["policy"] in {POLICY, CURRENT_POLICY},"Require a supported image-conditioned modeling-reference package")
    current = package["policy"] == CURRENT_POLICY
    core.require(core.safe_id(package.get("style_id")),"Modeling references need a stable style identity")
    if style_id is not None:core.require(package["style_id"]==style_id,"Modeling reference style differs from approved production")
    concept=package.get("selected_concept_sha256","")
    core.require(len(concept)==64 and all(x in "0123456789abcdef" for x in concept),"Bind references to selected concept SHA256")
    if selected_concept_sha256 is not None:core.require(concept==selected_concept_sha256,"References bind a different selected concept")
    rows=package.get("assets");core.require(isinstance(rows,list) and rows,"Modeling reference package needs actual assets")
    assets={};dependencies={};boards={}
    for asset in rows:
        core.require(isinstance(asset,dict),"Reference asset must be an object")
        aid=asset.get("asset_id");core.require(core.safe_id(aid) and aid not in assets,"Duplicate or missing reference asset identity")
        mode=asset.get("mode");views=asset.get("views")
        core.require(mode in {"single","multiview"} and isinstance(views,list) and (len(views)==1 if mode=="single" else 2<=len(views)<=32),"Choose one image or2..32 actual separate views; provider caps apply separately")
        review=asset.get("review",{});core.require(isinstance(review,dict),"Reference review must be an object")
        criteria=review.get("criteria",{});core.require(isinstance(criteria,dict),"Reference review criteria must be an object")
        core.require(review.get("actor") in {"agent","user"}, "Reference visual review needs an actual reviewer")
        core.require(review.get("images_digest")==core.digest(views),"Reference review is stale for these exact view versions")
        contract = _modeling_contract(asset) if current or "modeling_contract" in asset else None
        if contract is not None:
            _review_v2(asset, contract)
        else:
            core.require(isinstance(review.get("note"), str) and review["note"].strip(), "Reference visual review needs an actual observation")
            required=CRITERIA+(("multiview_consistent",) if mode=="multiview" else ())
            core.require(all(criteria.get(k) is True for k in required),"Reference visual checks are incomplete or failed")
        images=[];ids=set();roles=set();hashes=set()
        for view in views:
            core.require(isinstance(view,dict),"Reference view must be an object")
            vid,role=view.get("id"),view.get("role")
            core.require(core.safe_id(vid) and vid not in ids and role in {"front","back","left","right","three_quarter","top","bottom"},"Each reference needs unique view identity and explicit orientation")
            ids.add(vid);roles.add(role)
            path,raw=_file(view.get("image"),project,dependencies);submitted=_audit(raw)
            core.require(submitted["nonwhite_fraction"] > .001 or
                         (not submitted["opaque"] and .001 < submitted["visible_fraction"] < .999),
                         "Blank or empty submitted image cannot represent an asset")
            master_ref=view.get("master",view["image"]);master,mraw=_file(master_ref,project,dependencies);stats=_audit(mraw)
            origin=view.get("origin")
            core.require(origin in {"host_generated","user_provided","board_crop"},"Record reference image origin, not an untraceable prompt output")
            if origin=="host_generated":
                receipt_path,_=_file(view.get("generation_receipt"),project,dependencies)
                receipt=core.read(receipt_path)
                hashes_in=receipt.get("actual_input_image_sha256")
                core.require(isinstance(hashes_in,list) and bool(hashes_in) and all(isinstance(h,str) and len(h)==64
                             and all(c in "0123456789abcdef" for c in h) for h in hashes_in),
                             "Actual style image inputs must be a nonempty SHA256 list")
                core.require(receipt.get("schema")==1 and isinstance(receipt.get("source_ref"),str) and receipt["source_ref"].strip(),
                             "Reference image receipt needs schema1 and actual invocation source")
                core.require(receipt.get("kind")=="reference-image-generation-receipt" and receipt.get("output_sha256")==master_ref["sha256"]
                             and concept in receipt.get("actual_input_image_sha256",[]) and receipt.get("invocation_recorded") is True
                             and isinstance(receipt.get("tool"),str) and receipt["tool"].strip(),
                             "Generated reference must record the actual style-conditioned image invocation and exact output")
            elif origin=="board_crop":
                from . import reference_boards
                crop_result=reference_boards.validate_crop_receipt(view.get("board_crop_receipt"), project,
                    asset_id=aid, view_id=vid, role=role, concept=concept)
                boards[crop_result['board']['path']]=crop_result['board']
                core.require(crop_result["output"]["sha256"]==master_ref["sha256"]
                             and core.resolve_input(crop_result["output"]["path"],project)==master,
                             "Board crop output must be the exact reviewed white master")
                for dependency in crop_result["dependencies"]:
                    dependencies[dependency["path"]]=dependency
            else:
                provenance=view.get("provenance",{})
                core.require(isinstance(provenance.get("source_ref"),str) and provenance["source_ref"].strip(),
                             "Supplied modeling reference needs its actual source provenance")
            core.require(stats["opaque"] and stats["border_white_fraction"]>=.95,"Master reference needs a clean opaque white background; keep light edges via visual review/mask, never threshold-delete")
            core.require(stats["nonwhite_fraction"]>.001,"Blank white image cannot represent an asset")
            if master_ref["sha256"] != view["image"]["sha256"]:
                derived=view.get("derivation",{})
                core.require(derived.get("source_sha256")==master_ref["sha256"] and isinstance(derived.get("method"),str) and derived["method"].strip() and isinstance(derived.get("tool"),str) and derived["tool"].strip(),"Derived provider input needs master lineage, method and tool/version")
            core.require(view["image"]["sha256"] not in hashes,"Duplicate image bytes are not additional views")
            hashes.add(view["image"]["sha256"])
            images.append({"path":str(path),"sha256":view["image"]["sha256"],"view_id":vid,"role":role})
        core.require(mode=="single" or len(roles)==len(views),"Multiview orientations must be distinct, not duplicate angle labels")
        assets[aid]={"mode":mode,"images":images}
        if contract is not None:
            assets[aid]["modeling_contract"] = contract
        assets[aid]["contract_review"] = "reviewer-declared-v2" if contract is not None else "legacy-v1; category/pose review not established"
    if expected_asset_ids is not None:core.require(set(expected_asset_ids)<=set(assets),"Generated families lack approved modeling references")
    return {"ok":True,"policy":package["policy"],"legacy":not current,"assets":assets,"dependencies":list(dependencies.values()),"boards":list(boards.values()),"review_boundary":"Validates bytes and recorded observations, not actual image viewing, anatomy, pose, geometry, riggability or aesthetic quality. Legacy packages do not establish v2 checks."}


def validate_operation_reference(operation, project, provider=None):
    ref=operation.get("modeling_references");dependencies={}
    path,raw=_file(ref,project,dependencies)
    package=core.read(path);result=validate_package(package,project)
    aid=operation.get("asset_id");core.require(aid in result["assets"],"Submitted asset lacks its exact modeling-reference entry")
    return {"ok":True,**result["assets"][aid],"style_id":package["style_id"],"selected_concept_sha256":package["selected_concept_sha256"],"dependencies":[*dependencies.values(),*result["dependencies"]]}
