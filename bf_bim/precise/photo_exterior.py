"""Photo-informed exterior, registered to CAD; never an as-built survey.

Primary evidence: Gwangju TP 2026-0041, demand attachment pp. 4-5.
The four site photographs establish appearance, not measured dimensions.
"""
from copy import deepcopy
import math
from shapely.geometry import Polygon, LineString, box
from shapely.ops import unary_union
from bf_bim.geometry import polygon_parts
from .completion import profile, parts, new_element
from .envelope import opening_projection

REFERENCE = {
    'title': '광주테크노파크 2026 창업기업제품 실증지원사업 혁신기술수요조사서',
    'url': 'https://www.iplexgj.com/board/B0002.cs?act=read&bwrId=723',
    'attachment_url': 'https://www.iplexgj.com/board/B0002.cs?act=download&bwrId=723&bfiNo=1',
    'pages': [4, 5], 'photo_count': 4, 'kind': 'site_photographs',
    'attachment_sha256': 'd6439b9a6bd1c2c2832df4ed318c9487d2161762140210297a28302e329340a7',
    'building_address': '광주 남구 도시첨단산업6로 2',
    'observed': ['밝은 상부 외벽', '짙은 회색 하부 외벽', '남색 외벽 BIPV와 밝은 격자', '옥외 경사 PV와 주차 캐노피'],
    'limits': '사진 촬영일과 측량 치수 미제공. 옥상 배치는 조감도 및 CAD 지붕 경계로 추정.',
}
MATERIALS = {'white': 'photo_white_cladding', 'dark': 'photo_charcoal_cladding',
             'bipv': 'photo_bipv'}


def photo_source(context, reason):
    return {'file': context['file'], 'source_sha256': context['source_sha256'],
            # Link the context once, not hundreds of floor trace IDs on every
            # module and again on every property-evidence record in the IFC.
            'cad_ids': context['cad_ids'][:1], 'context_cad_reference_count': len(context['cad_ids']),
            'context_reference_scope': 'Floor boundary context only; individual panel layout is assumed.',
            'validation_status': 'provisional',
            'geometry_status': 'photo_informed_assumption', 'material': MATERIALS['white'],
            'envelope_role': 'exterior_candidate', 'design_assignment_verified': False,
            'photo_reference': deepcopy(REFERENCE),
            'user_assumed_completion': {'authorization': '사진들을 찾아보고 외관이 비슷하게 만들어줘',
                'reason': reason, 'context_references_only': True, 'design_verified': False},
            'property_status': {k: 'provisional' for k in ('position', 'section', 'height', 'material')},
            'assumptions': {'photo_registration': {'status': 'provisional', 'reason': reason}},
            'unknowns': ['현장 실측 치수, 외장 제품, 고정 상세, 사진과 도면의 개정 관계 미확인']}


def apply_photo_exterior(elements, specs):
    report={'reference': deepcopy(REFERENCE), 'design_verified': False, 'route_verified': False,
            'appearance_changes': [], 'added': [], 'dimensions_status': 'CAD registration + assumed exterior depths and layouts'}
    original=list(elements)
    footprints={}
    contexts={}
    for fid in ('f1','f2','f3','f4','roof'):
        es=[e for e in original if e['floor_id']==fid and e['type'] in ('floor','roof') and e['components']]
        footprints[fid]=unary_union([profile(e) for e in es])
        contexts[fid]=es[0]['source']
    boundaries={fid:unary_union([Polygon(p.exterior) for p in polygon_parts(polygon)]).boundary
                for fid,polygon in footprints.items()}

    # Use the actual opening Z range, including fixed transoms. Sweep only in
    # the depth direction so facade jambs and bent-window corners survive.
    portal_cuts={fid: [(e['source']['provisional_opening']['z_offset'],
                       e['source']['provisional_opening']['z_offset']+e['source']['provisional_opening']['height'],
                       opening_projection(e), e['id'])
        for e in original if e['floor_id']==fid and e['type'] in ('door','window') and e['components']
        and profile(e).distance(boundaries[fid])<=.55]
        for fid in footprints}

    def add(fid, name, poly, cs, reason, kind='wall'):
        if kind=='wall':
            # Structural columns already occupy some slab-edge bands. Never
            # add a finish prism through them just to produce a closed facade.
            occupied=column_masks[fid]
            clipped=[]
            for c in cs:
                base=profile(c).difference(occupied)
                lo=c['z_offset'];hi=lo+c['height']
                nearby=[(a,b,p,i) for a,b,p,i in portal_cuts[fid]
                        if min(hi,b)-max(lo,a)>1e-7 and p.intersection(base).area>1e-7]
                levels=sorted({lo,hi,*[max(lo,min(hi,z)) for a,b,_,_ in nearby for z in (a,b)]})
                for a,b in zip(levels,levels[1:]):
                    if b-a<1e-7:continue
                    active=[p for x,y,p,_ in nearby if x<b-1e-7 and y>a+1e-7]
                    q=base.difference(unary_union(active))
                    clipped+=parts(q,c['role'],b-a,a,material=c['source']['material'],
                        opening_cut_method='measured_span_normal_projection',
                        portal_ids=[i for x,y,_,i in nearby if x<b-1e-7 and y>a+1e-7])
            cs=clipped
        if not cs: return
        src=photo_source(contexts[fid],reason)
        for c in cs: c['source']['photo_informed']=True
        e=new_element(fid,kind,poly,src,name,cs)
        elements.append(e)
        report['added'].append({'id':e['id'],'floor_id':fid,'role':cs[0]['role'],'components':len(cs)})

    column_masks={fid:unary_union([profile(c).buffer(.001,join_style=2) for e in original
        if e['floor_id']==fid and e['type']=='column' for c in e['components']])
        for fid in footprints}

    for fid in ('f1','f2','f3','f4'):
        outer=unary_union([Polygon(p.exterior) for p in polygon_parts(footprints[fid])])
        boundary=outer.boundary
        for e in [e for e in original if e['floor_id']==fid and e['type'] in ('wall','column','beam')]:
            if boundary.distance(profile(e))>.38: continue
            changed=[]
            for c in e['components']:
                if profile(c).distance(boundary)>.38: continue
                if c['source'].get('material') in ('glazing','metal'): continue
                c['source']['pre_photo_material']=c['source'].get('material',e['source'].get('material'))
                c['source']['material']=MATERIALS['dark' if fid in ('f1','f2') else 'white']
                changed.append(c.get('id'))
            if changed:
                e['source']['photo_appearance']={'reference':deepcopy(REFERENCE),'geometry_changed':False,
                    'material_product_verified':False,'assignment':'외곽 경계에 인접한 부재의 사진 기반 표현 색상'}
                report['appearance_changes'].append({'id':e['id'],'components':len(changed)})

        # A thin OUTSIDE skin completes discontinuous extraction, with CAD doors
        # and windows cut at their actual model Z ranges, not a flat full wall.
        skin=outer.buffer(.06,join_style=2).difference(outer.buffer(.002,join_style=2))
        exterior_portals={e['id'] for e in original if e['floor_id']==fid and e['type'] in ('window','door')
                          and e['components'] and profile(e).distance(boundary)<=.55}
        openings=[(lo,hi,p) for lo,hi,p,i in portal_cuts[fid] if i in exterior_portals]
        height=specs[fid]['height_preview']
        levels=sorted({0.,height,*[max(0.,min(height,z)) for lo,hi,_ in openings for z in (lo,hi)]})
        for lo,hi in zip(levels,levels[1:]):
            if hi-lo<.002:continue
            cuts=unary_union([p for a,b,p in openings if a<hi-1e-6 and b>lo+1e-6])
            for i,p in enumerate(polygon_parts(skin.difference(cuts))):
                cs=parts(p,'photo_exterior_cladding',hi-lo,lo,material=MATERIALS['dark' if fid in ('f1','f2') else 'white'])
                add(fid,f'{specs[fid]["name"]} 사진 기반 외장 보완 {lo:.2f}-{i}',p,cs,
                    '외장 색상은 현장 사진. 경계는 CAD 바닥 외곽, 58mm 깊이는 추정. 개구부 폭을 유지하고 깊이 방향으로만 절단.')

    # Large blind BIPV bay on the cantilever wing, registered to its CAD north
    # face. Modules are a visual grid, not a counted equipment schedule.
    for fid in ('f3','f4'):
        for i in range(6):
            p=box(8.65+i*2.1,59.07,10.67+i*2.1,59.12)
            cs=[]
            for j in range(4):cs+=parts(p,'photo_bipv_module',.81,.35+j*.88,material=MATERIALS['bipv'])
            add(fid,f'{specs[fid]["name"]} 돌출부 BIPV {i+1}',p,cs,'사진의 큰 불투명 태양광 격자. CAD 돌출부 외곽에 배치하며 격자 치수는 추정.')

    # Repeated BIPV spandrels on the long facades. Clip away every native
    # opening so photovoltaic panels cannot replace operable windows or doors.
    for fid in ('f3','f4'):
        outer=unary_union([Polygon(p.exterior) for p in polygon_parts(footprints[fid])])
        coords=list(max(polygon_parts(outer),key=lambda p:p.area).exterior.coords)
        for k,(a,b) in enumerate(zip(coords,coords[1:])):
            length=math.dist(a,b)
            if length<3:continue
            ux,uy=(b[0]-a[0])/length,(b[1]-a[1])/length
            # exterior ring is clockwise/CCW dependent; use geometric outside.
            line=LineString([a,b]);strip=line.buffer(.10,cap_style=2).difference(outer.buffer(.065,join_style=2))
            if strip.is_empty:continue
            count=max(1,int(length/1.05))
            for i in range(count):
                start=i*length/count+.035;end=(i+1)*length/count-.035
                tile=LineString([(a[0]+ux*start,a[1]+uy*start),(a[0]+ux*end,a[1]+uy*end)]).buffer(.11,cap_style=2)
                # Vertical clipping happens in add(): retain opaque spandrels
                # above/below the opening instead of erasing a full-height bay.
                poly=tile.intersection(strip)
                for q in polygon_parts(poly):
                    cs=[]
                    for z in (1.0,1.83,2.66):cs+=parts(q,'photo_bipv_spandrel',.76,z,material=MATERIALS['bipv'])
                    add(fid,f'{specs[fid]["name"]} 외벽 BIPV {k}-{i}',q,cs,'사진에서 보이는 창 사이 BIPV. 창 위치 유지, 패널 분할과 적용 범위는 추정.')

    report['excluded_by_user']=['rooftop_pv','outdoor_pv','parking_pv_canopy','pv_supports']
    report['opening_policy']='Measured along-wall span, independent bent runs, normal projection and full opening Z interval; no radial width buffer.'
    return report
