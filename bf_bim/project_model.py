"""Project-specific reconstruction of the approved detailed 1F / 2F drawing set.

Coordinates and wall face spacing are derived from CAD. Unmatched faces, floor
coverage, door openings and room topology retain explicit inference flags.
This adapter deliberately does not certify incomplete drawings for navigation.
"""
import hashlib
import json
import math
import re
from pathlib import Path
from collections import Counter
from shapely.geometry import Polygon, LineString, Point, MultiPoint, box
from shapely.ops import unary_union, polygonize
from shapely import concave_hull, set_precision
from .schema import Model
from .geometry import polygon_parts

OUT=Path('cad_output')
WALL_LAYERS={'A-CON','A-BRICK','A-WAL','A-WALL'}
GLASS_LAYERS={'A-WIN','A-AL03','A-WID','XREF-평면도$0$A-WIN'}
ORIGIN=(32920000.,-5730000.)
SHEET_SPACING=126150.00007091

def xy(p,offset):
    return (round((p[0]-ORIGIN[0]-offset)*.001,5),round((p[1]-ORIGIN[1])*.001,5))

def entity_lines(e,offset):
    g=e['geometry']
    if e['type']=='LINE':
        return [LineString([xy(g['start'],offset),xy(g['end'],offset)])]
    if e['type']=='LWPOLYLINE':
        return [LineString([xy(s['start'],offset),xy(s['end'],offset)]) for s in g.get('segments',[]) if s['type']=='LINE']
    return []

def paired_wall_faces(records):
    solids=[];used=set()
    # Opposing parallel faces establish a measured thickness; only overlap is filled.
    for i,(line,src) in enumerate(records):
        a,b=list(line.coords);length=line.length
        if length<.2:continue
        ux,uy=(b[0]-a[0])/length,(b[1]-a[1])/length
        best=None
        for j,(other,_) in enumerate(records):
            if j==i or other.length<.2:continue
            c,d=list(other.coords);vx,vy=(d[0]-c[0])/other.length,(d[1]-c[1])/other.length
            if abs(ux*vy-uy*vx)>.001:continue
            signed=-(c[0]-a[0])*uy+(c[1]-a[1])*ux
            gap=abs(signed)
            if not .075<=gap<=.45:continue
            t1=(c[0]-a[0])*ux+(c[1]-a[1])*uy;t2=(d[0]-a[0])*ux+(d[1]-a[1])*uy
            lo=max(0,min(t1,t2));hi=min(length,max(t1,t2))
            if hi-lo<.25:continue
            if best is None or gap<best[0]:best=(gap,j,lo,hi,signed)
        if best:
            gap,j,lo,hi,signed=best
            coords=[(a[0]+ux*lo,a[1]+uy*lo),(a[0]+ux*hi,a[1]+uy*hi),
                    (a[0]+ux*hi-uy*signed,a[1]+uy*hi+ux*signed),
                    (a[0]+ux*lo-uy*signed,a[1]+uy*lo+ux*signed)]
            solids.append((Polygon(coords),src,records[j][1],gap));used.add(i);used.add(j)
    # Union removes duplicate bands from reciprocal face pairing.
    paired=unary_union([p for p,*_ in solids]) if solids else Polygon()
    unmatched=[]
    for i,(line,src) in enumerate(records):
        if i not in used and line.length>.15:
            # 1 cm envelope is an explicitly uncertain surface marker, not wall thickness.
            unmatched.append((line.buffer(.005,cap_style=2),src))
    return paired,solids,unmatched

def main():
    es=json.loads((OUT/'scene-compact.json').read_text(encoding='utf-8'))
    inventory=json.loads((OUT/'project-inventory.json').read_text(encoding='utf-8'))
    sections=json.loads((OUT/'section-texts.json').read_text(encoding='utf-8'))
    levels={t['text']:t for t in sections['texts'] if t['id'].startswith('layout:Model/8F9D/')}
    level1=next(t for text,t in levels.items() if text=='EL +37.70')
    level2=next(t for text,t in levels.items() if text=='EL+41.90')
    delta=41.90-37.70
    elements=[];places=[];floor_report=[]
    def add(fid,kind,poly,src,name=None,height=None,**props):
        if not poly.is_valid or poly.area<1e-7:return None
        poly=set_precision(poly,.001)
        if poly.geom_type=='MultiPolygon':
            for part in poly.geoms:add(fid,kind,part,src,name,height,**props)
            return None
        if poly.is_empty or not poly.is_valid:return None
        identity='energy-'+hashlib.sha256((fid+'/'+kind+'/'+str(src.get('cad_ids',src.get('cad_id','')))+'/'+poly.wkt).encode()).hexdigest()[:16]
        e=dict(id=identity,name=name or f'{kind} · {identity[-5:]}',type=kind,floor_id=fid,
            polygon=[[round(x,6),round(y,6)] for x,y in list(poly.exterior.coords)[:-1]],
            holes=[[[round(x,6),round(y,6)] for x,y in list(r.coords)[:-1]] for r in poly.interiors],
            height=height,verified=False,properties=props,source={'origin':'cad','file':'A04-001~008 평면도.dwg',**src})
        elements.append(e);return e
    for number in (1,2):
        fid=f'f{number}';offset=(number-1)*SHEET_SPACING
        x1,x2=32920000+offset,33020000+offset;y1,y2=-5730000,-5640000
        use=[e for e in es if e.get('bounds') and x1<=e['bounds']['min'][0] and e['bounds']['max'][0]<=x2 and y1<=e['bounds']['min'][1] and e['bounds']['max'][1]<=y2]
        records=[(line,e['id']) for e in use if e['layer'] in WALL_LAYERS for line in entity_lines(e,offset) if line.length>.01]
        structural,paired,unmatched=paired_wall_faces(records)
        for index,p in enumerate(polygon_parts(structural)):
            sources=[(s,t,w) for poly,s,t,w in paired if poly.intersects(p)]
            add(fid,'wall',p,{'cad_ids':sorted({id for s,t,_ in sources for id in (s,t)}),
                'method':'parallel_wall_face_pairing','thickness_candidates_m':sorted({round(w,4) for _,_,w in sources}),
                'geometry_inferred':True,'height_source':'storey interval from section; simplified extrusion'},f'{number}층 벽체 {index+1}',delta)
        for index,(p,src) in enumerate(unmatched):
            add(fid,'wall',p,{'cad_id':src,'method':'unpaired_wall_surface','marker_width_m':.01,'geometry_inferred':True},f'{number}층 미확정 벽면 {index+1}',delta)
        for e in use:
            if e['layer']!='A-COL':continue
            g=e['geometry'];p=None
            if e['type']=='LWPOLYLINE' and g.get('closed'):p=Polygon([xy(v,offset) for v in g['vertices']])
            if e['type']=='CIRCLE':p=Point(xy(g['center'],offset)).buffer(g['radius']*.001,quad_segs=16)
            if p is not None:add(fid,'column',p,{'cad_id':e['id'],'layer':e['layer'],'geometry_inferred':False,'height_source':'section storey interval'},f'{number}층 기둥',delta)
        # Swing arcs locate doors. Nominal leaf radius is stored as evidence, never clear width.
        arcs=[e for e in use if e['type']=='ARC' and e['layer'] in ('A-DOOR','A-DOR') and .3<e['geometry']['radius']*.001<2]
        doors=[]
        wall_lines=unary_union([l for l,_ in records])
        for e in arcs:
            g=e['geometry'];hinge=xy(g['center'],offset);ends=[xy(g['start'],offset),xy(g['end'],offset)]
            choices=[LineString([hinge,end]) for end in ends]
            # Closed position is the endpoint nearest a wall face, pending designer verification.
            leaf=min(choices,key=lambda line:wall_lines.distance(Point(list(line.coords)[-1])))
            p=leaf.buffer(.3,cap_style=3)
            if any(old.distance(p)<.05 for old in doors):continue
            doors.append(p)
            add(fid,'door',p,{'cad_id':e['id'],'layer':e['layer'],'leaf_radius_m':g['radius']*.001,
                'geometry_inferred':True,'method':'swing arc opening candidate','clear_width_source':'unknown'},f'{number}층 출입문 후보 {len(doors)}',None)
        # Paired window profiles are modelled as unverified barriers, preventing false open edges.
        glazing_records=[(line,e['id']) for e in use if e['layer'] in GLASS_LAYERS for line in entity_lines(e,offset) if line.length>.5]
        glass,_,_=paired_wall_faces(glazing_records)
        for index,p in enumerate(polygon_parts(glass)):
            add(fid,'wall',p,{'method':'glazing profile barrier','geometry_inferred':True,'cad_ids':[src for line,src in glazing_records if line.distance(p)<.01]},f'{number}층 창호 경계 {index+1}',delta)
        # Polygonized face network captures rooms without inventing centre-to-centre links.
        close_lines=[l for l,_ in records]+[l for l,_ in glazing_records]+[LineString(p.exterior.coords) for p in doors]
        network=set_precision(unary_union(close_lines),.001)
        faces=[p for p in polygonize(network) if p.area>2 and p.area<1500]
        floor_area=unary_union(faces)
        floor_area=concave_hull(MultiPoint([pt for line,_ in records for pt in line.coords]),ratio=.9,allow_holes=False)
        floor_method='concave hull of wall face endpoints; floor boundary unverified; courtyard not subtracted'
        for index,p in enumerate(polygon_parts(floor_area)):
            add(fid,'floor',p,{'method':floor_method,'geometry_inferred':True,'coverage_verified':False,
                'slab_thickness_source':'unknown'},f'{number}층 바닥 영역 후보 {index+1}',None)
        # Finish-line faces complete the visible exterior in this drawing convention.
        finish_records=[(line,e['id']) for e in use if e['layer'] in ('A-FIN','A-STONE') for line in entity_lines(e,offset)
                        if line.length>.3 and floor_area.buffer(.5).covers(line)]
        finish,_,finish_unpaired=paired_wall_faces(finish_records)
        for index,p in enumerate(polygon_parts(finish)):
            add(fid,'wall',p,{'method':'paired finish faces','cad_ids':[src for line,src in finish_records if line.distance(p)<.01],'geometry_inferred':True},f'{number}층 외장 경계 {index+1}',delta)
        for index,(p,src) in enumerate(finish_unpaired):
            add(fid,'wall',p,{'cad_id':src,'method':'unpaired finish face marker','marker_width_m':.01,'geometry_inferred':True},f'{number}층 외장 미확정 면 {index+1}',delta)
        room_labels=[e for e in use if e['type']=='TEXT' and e['layer']=='A-TEX2' and any(w in e['geometry']['text'] for w in ('홀','사무','관리','통신','세미나','주방','식당','E.V','센터','회의'))]
        root_blocks=[e for e in es if e['type']=='INSERT' and e['id']==e['root'] and x1<e['geometry']['insert'][0]<x2 and y1<e['geometry']['insert'][1]<y2]
        for block in root_blocks:
            if '계단' not in block['geometry']['block_name']:continue
            children=[e for e in use if e['root']==block['root'] and e['type'] in ('LINE','LWPOLYLINE')]
            pts=[pt for child in children for line in entity_lines(child,offset) for pt in line.coords]
            if pts:add(fid,'stair',MultiPoint(pts).minimum_rotated_rectangle,{'cad_id':block['id'],'block_name':block['geometry']['block_name'],'method':'stair block envelope','geometry_inferred':True,'connected_floors_verified':False},f'{number}층 계단 후보',delta)
        for e in room_labels:
            name=e['geometry']['text'];point=Point(xy(e['geometry']['insert'],offset))
            candidates=[p for p in faces if p.covers(point)]
            poly=min(candidates,key=lambda p:p.area) if candidates else None
            if poly is not None:
                kind='corridor' if '홀' in name else 'space'
                add(fid,kind,poly,{'cad_id':e['id'],'method':'room label within polygonized region','geometry_inferred':True},f'{number}층 {name}',None)
            places.append(dict(id=f'{fid}-'+e['id'].replace('/','-').replace(':','-'),name=f'{number}층 {name}',floor_id=fid,point=list(point.coords)[0]))
            if name=='E.V':
                possible=[]
                for block in root_blocks:
                    children=[c for c in use if c['root']==block['root'] and c['type'] in ('LINE','LWPOLYLINE')]
                    pts=[pt for child in children for line in entity_lines(child,offset) for pt in line.coords]
                    if not pts:continue
                    envelope=MultiPoint(pts).minimum_rotated_rectangle
                    if 1<envelope.area<20 and envelope.covers(point):possible.append((envelope,block))
                if possible:
                    envelope,block=min(possible,key=lambda item:item[0].area)
                    add(fid,'elevator',envelope,{'cad_id':block['id'],'label_cad_id':e['id'],'block_name':block['geometry']['block_name'],'method':'E.V label within CAD block envelope','geometry_inferred':True,'connected_floors_verified':False},f'{number}층 승강기 후보',None)
        floor_report.append(dict(floor=fid,source_extent_mm=[x1,y1,x2,y2],source_entity_count=len(use),
            wall_face_segments=len(records),paired_wall_area_m2=structural.area,unpaired_faces=len(unmatched),
            floor_candidate_area_m2=floor_area.area,door_candidates=len(doors),room_labels=len(room_labels)))
    model=Model.model_validate(dict(id='energy-center-actual-1f2f',name='에너지융복합종합지원센터 · 실제 도면 1·2층',
        floors=[dict(id='f1',name='지상 1층',elevation=0),dict(id='f2',name='지상 2층',elevation=delta)],elements=elements,places=places,links=[],
        warnings=['상세 형상이 남아 있는 도면 묶음의 지상 1·2층을 사용했습니다. 다른 도면 묶음과 개정 일치 여부는 미확인입니다.',
            '외부 참조 xref-plan.dwg와 에너지 융복합단지-FORM.dwg가 없어 내용 누락 가능성이 있습니다.',
            '벽체 평행면을 연결한 형상, 바닥 영역, 문 개구부 후보는 자동 추정이며 검토 전입니다.',
            '바닥 후보는 벽면 끝점의 오목 외곽으로 추정했습니다. 중정·외부공간·슬래브 개구부를 직접 구분해야 합니다.',
            '문 유효폭, 단차, 승강기 가동 상태·층간 연결이 미확인입니다. 실제 건물의 BF 경로를 검증 완료로 안내하지 않습니다.',
            '벽·기둥은 단면도에서 확인한 층간 높이 4.20 m로 단순 압출했습니다. 천장고·슬래브 두께를 뜻하지 않습니다.',
            '출입문 후보는 높이가 미확인되어 평면 표시만 제공합니다. 상부 인방과 창 유리 상세는 모델링하지 않았습니다.'],
        provenance={'floorplan_sha256':inventory['sha256'],'section_sha256':sections['source']['sha256_before'],
            'original_unchanged':sections['source']['original_unchanged'],'source_origin_mm':ORIGIN,
            'sheet_spacing_mm':SHEET_SPACING,'source_units':'mm','coordinate_transform':'XY=(CAD-Origin-sheet offset)*0.001; Z=EL-37.70',
            'level_evidence':[level1,level2],'floor_reports':floor_report,'review_status':'unverified'}))
    (OUT/'energy-center-model.json').write_text(model.model_dump_json(indent=2),encoding='utf-8')
    report={'model_elements':len(model.elements),'types':dict(Counter(e.type for e in model.elements)),
        'floor_reports':floor_report,'places':[p.model_dump() for p in model.places], 'level_evidence':[level1,level2]}
    (OUT/'energy-center-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
