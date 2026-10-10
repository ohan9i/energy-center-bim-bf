"""Evidence-led, reproducible reconstruction of the detailed architectural sheets.

Plan geometry is measured; inferred closure, heights and assembly directions are
always recorded separately. This module never creates navigation links.
"""
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
import math
from shapely import set_precision, make_valid
from shapely.geometry import Polygon, Point, LineString, MultiPoint, box
from shapely.ops import unary_union
from .project_model import xy, entity_lines, paired_wall_faces, WALL_LAYERS, GLASS_LAYERS, ORIGIN, SHEET_SPACING
from .geometry import polygon_parts
from .schema import Model
from .drawing_evidence import collect_evidence,annotate_columns

OUT=Path('cad_output')
FINISH={'A-FIN','A-STONE'}
BOUNDARY=WALL_LAYERS|GLASS_LAYERS|FINISH|{'A-AL01','무빙월','A-08-FINL','A-COL','A-DOOR','A-DOR'}
# Control points read from 1F wall/curtain-wall endpoints, in the common model frame.
# Connecting these endpoints across columns is a reviewed CAD trace candidate,
# not a claimed structural slab survey. The same courtyard is open on 2F–roof.
COURTYARD=Polygon([(34.82955,46.38950),(37.96738,49.61290),(46.07255,49.61290),
                   (46.07255,46.03595),(40.48641,40.73265)])
COURTYARD_IDS=['layout:Model/2604B/child:4','layout:Model/26C5A','layout:Model/264E2']

def select_sheet(es,n):
    offset=(n-1)*SHEET_SPACING
    return [e for e in es if e.get('bounds') and ORIGIN[0]+offset<=e['bounds']['min'][0]
        and e['bounds']['max'][0]<=ORIGIN[0]+offset+100000 and ORIGIN[1]<=e['bounds']['min'][1]
        and e['bounds']['max'][1]<=ORIGIN[1]+90000]

def ring(poly):
    return [[round(x,6),round(y,6)] for x,y in list(poly.exterior.coords)[:-1]]

def component(poly,role,height=None,z=0,**source):
    return dict(role=role,polygon=ring(poly),holes=[],height=height,z_offset=z,source=source)

def stair_components(lines,envelope,riser_evidence):
    """Use the actual parallel nosings, not an arbitrary stair box or step pitch."""
    groups=defaultdict(list)
    for line,src in lines:
        if not 2.5<line.length<3.6:continue
        a,b=list(line.coords);angle=math.atan2(b[1]-a[1],b[0]-a[0])%math.pi
        groups[round(angle,2)].append((line,src))
    if not groups:return [],{}
    treads=max(groups.values(),key=len)
    if len(treads)<8:return [],{}
    a,b=list(treads[0][0].coords);length=treads[0][0].length
    ux,uy=(b[0]-a[0])/length,(b[1]-a[1])/length;nx,ny=-uy,ux
    def st(p):return (p[0]*ux+p[1]*uy,p[0]*nx+p[1]*ny)
    def pt(s,t):return (s*ux+t*nx,s*uy+t*ny)
    s0,s1=sorted(st(p)[0] for p in (a,b));mid=(s0+s1)/2
    ts=sorted({round(st(line.coords[0])[1],4) for line,_ in treads})
    pitches=[round(y-x,4) for x,y in zip(ts,ts[1:])]
    if not pitches or max(pitches)-min(pitches)>.01:return [],{}
    pitch=sum(pitches)/len(pitches);rise=.175
    # Two flights / 12 risers per flight are supported by core section text.
    # Direction and central separation remain explicit reconstruction assumptions.
    result=[]
    for flight,(left,right) in enumerate(((s0,mid-.05),(mid+.05,s1))):
        for i,(lo,hi) in enumerate(zip(ts,ts[1:])):
            level=(i+1)*rise if flight==0 else 4.2-i*rise
            poly=Polygon([pt(left,lo),pt(right,lo),pt(right,hi),pt(left,hi)])
            result.append(component(poly,'tread',rise,level-rise,
                cad_ids=[src for _,src in treads],geometry_inferred=True,
                direction_verified=False,height_evidence=riser_evidence))
    ext=[st(p)[1] for p in envelope.exterior.coords];tmin,tmax=min(ext),max(ext)
    for lo,hi,z in ((tmin,ts[0],0),(ts[-1],tmax,2.1)):
        if hi-lo>.1:
            result.append(component(Polygon([pt(s0,lo),pt(s1,lo),pt(s1,hi),pt(s0,hi)]),'landing',None,z,
                geometry_inferred=True,slab_thickness_source='unknown'))
    return result,dict(nosing_count=len(ts),tread_pitch_m=round(pitch,4),riser_m=rise,
        risers_per_flight=12,riser_evidence=riser_evidence,flight_direction_verified=False,
        central_gap_m=.1,central_gap_source='display reconstruction assumption',
        detail_pitch_conflict=abs(pitch-.3)>.005)

def main():
    es=json.loads((OUT/'scene-compact.json').read_text(encoding='utf-8'))
    inventory=json.loads((OUT/'project-inventory.json').read_text(encoding='utf-8'))
    sections=json.loads((OUT/'section-texts.json').read_text(encoding='utf-8'))
    plan_path=next(Path('에너지-건축도면').glob('A04-001*.dwg'))
    section_path=next(Path('에너지-건축도면').glob('A04-021*.dwg'))
    if hashlib.sha256(plan_path.read_bytes()).hexdigest()!=inventory['sha256'] or hashlib.sha256(section_path.read_bytes()).hexdigest()!=sections['source']['sha256_before']:
        raise ValueError('도면 해시와 분석 캐시가 다릅니다. prepare_project로 재분석하세요.')
    evidence=[t for t in sections['texts'] if t['id'].startswith('layout:Model/8F9D/') and t['text'] in
        ('EL +37.70','EL+41.90','EL+46.10','EL+50.30','EL+54.50','EL+59.90')]
    evidence=sorted({t['text']:t for t in reversed(evidence)}.values(),key=lambda t:float(t['text'].replace('EL','').strip()))
    if len(evidence)!=6:raise ValueError('층 기준 단면 근거가 변경되었습니다. 수동 검토가 필요합니다.')
    supplements=[json.loads(p.read_text(encoding='utf-8')) for p in sorted(OUT.glob('*-evidence.json'))]
    for d in supplements:
        if hashlib.sha256((Path('에너지-건축도면')/d['file']).read_bytes()).hexdigest()!=d['source']['sha256_before']:
            raise ValueError('보조 도면 캐시가 변경된 원본과 다릅니다: '+d['file'])
    core=next((d for d in supplements if d['file'].startswith('A07-011')),None)
    risers=[dict(cad_id=e['id'],text=e['geometry']['text'],file=core['file']) for e in core['entities']
        if e['type']=='TEXT' and e['geometry']['text']=='(175 X 12EA)'] if core else []
    if not risers:raise ValueError('계단 175 × 12 단면 근거를 먼저 추출하세요.')
    elements=[];places=[];reports=[];relationships=[]
    def add(fid,kind,poly,src,name,height=None,z=0,components=None):
        poly=set_precision(make_valid(poly),.001)
        out=[]
        for p in polygon_parts(poly):
            if p.area<1e-6:continue
            identity='energy-'+hashlib.sha256((fid+'/'+kind+'/'+str(src.get('cad_ids',src.get('cad_id','')))+'/'+p.normalize().wkt).encode()).hexdigest()[:16]
            if any(e['id']==identity for e in elements):continue
            e=dict(id=identity,name=name,type=kind,floor_id=fid,polygon=ring(p),
                holes=[[[round(x,6),round(y,6)] for x,y in list(r.coords)[:-1]] for r in p.interiors],
                height=height,z_offset=z,verified=False,properties={},components=components or [],
                source=dict(origin='cad',file='A04-001~008 평면도.dwg',geometry_status='inferred' if src.get('geometry_inferred',True) else 'measured_plan',**src))
            elements.append(e);out.append(e)
        return out
    floor_polys={};core_polys={}
    for n in range(0,6):
        fid='b1' if n==0 else f'f{n}' if n<5 else 'roof';offset=(n-1)*SHEET_SPACING;use=select_sheet(es,n)
        storey_height=3.9 if n==0 else 4.2 if n<5 else 5.4
        use_by_id={e['id']:e for e in use};children=defaultdict(list)
        for e in use:children[e['root']].append(e)
        root_blocks=[e for e in es if e['type']=='INSERT' and e['id']==e['root'] and
            ORIGIN[0]+offset<e['geometry']['insert'][0]<ORIGIN[0]+offset+100000 and ORIGIN[1]<e['geometry']['insert'][1]<ORIGIN[1]+90000]
        labels=[e for e in use if e['type']=='TEXT' and e['layer']=='A-TEX2' and
            not any(w in e['geometry']['text'] for w in ('축척','평면도')) and (len(e['geometry']['text'])>1 or e['geometry']['text']=='홀')]
        records=[(l,e['id']) for e in use if e['layer'] in WALL_LAYERS for l in entity_lines(e,offset) if l.length>.01]
        structural,bands,unmatched=paired_wall_faces(records)
        seen=set()
        for p,a,b,width in bands:
            key=set_precision(p,.001).normalize().wkt
            if key in seen:continue
            seen.add(key)
            layer=use_by_id[a]['layer']
            add(fid,'wall',p,dict(cad_ids=sorted({a,b}),layer=layer,method='parallel_wall_face_pairing',
                measured_thickness_m=round(width,4),geometry_inferred=True,material='masonry' if layer=='A-BRICK' else 'concrete',
                height_source='section storey interval; wall top not verified'),f'{n}층 벽체 · {len(seen)}',storey_height)
        for i,(p,src) in enumerate(unmatched):
            add(fid,'wall',p,dict(cad_id=src,method='unpaired_wall_surface',marker_width_m=.01,geometry_inferred=True,
                height_source='storey visualization envelope'),f'{n}층 미확정 벽면 · {i+1}',storey_height)
        column_records={}
        for e in use:
            if e['layer']!='A-COL':continue
            g=e['geometry'];p=None
            if e['type']=='LWPOLYLINE' and g.get('closed') and len(g['vertices'])>=3:p=Polygon([xy(v,offset) for v in g['vertices']])
            elif e['type']=='CIRCLE':p=Point(xy(g['center'],offset)).buffer(g['radius']*.001,quad_segs=16)
            if p is not None and p.is_valid:
                key=set_precision(p,.001).normalize().wkt
                if key not in column_records:column_records[key]=(p,[])
                column_records[key][1].append(e['id'])
        for p,ids in column_records.values():
            # Distinct concentric profiles are retained for review; exact CAD copies
            # become one BIM object with all original IDs rather than double solids.
            conflicts=[other_ids[0] for other_p,other_ids in column_records.values() if other_ids!=ids and p.centroid.distance(other_p.centroid)<.002]
            add(fid,'column',p,dict(cad_id=ids[0],cad_ids=ids,layer='A-COL',method='closed CAD column section; identical copies consolidated',geometry_inferred=False,
                height_source='section storey interval; member top not verified' if not conflicts else 'concentric CAD profiles; member section unresolved',
                coincident_profile_ids=conflicts,material='concrete'),f'{n}층 기둥',storey_height if not conflicts else None)
        # Window blocks often inherit A-DOOR; their block identity is essential.
        window_roots=set();window_door_roots=set();window_shapes=[]
        for block in root_blocks:
            name=block['geometry']['block_name']
            if not name.lower().startswith(('win-','door-win-')):continue
            window_roots.add(block['id'])
            if name.lower().startswith('door-win-'):window_door_roots.add(block['id'])
            win_records=[(l,c['id']) for c in children[block['id']] if c['layer'] in GLASS_LAYERS|{'A-DOOR','A-DOR','0'} for l in entity_lines(c,offset) if l.length>.05]
            if not win_records:continue
            profiles,_,_=paired_wall_faces(win_records)
            # A mixed window/door block can contain swung leaves or several angled
            # panels. An enclosing rectangle fabricates glazing across empty space.
            parts=polygon_parts(profiles)
            if not parts:
                parts=[max(win_records,key=lambda r:r[0].length)[0].buffer(.005,cap_style=2)]
            for p in parts:
                window_shapes.append(p)
                src=dict(cad_id=block['id'],cad_ids=[src for l,src in win_records if l.distance(p)<.01],block_name=name,
                    method='paired window block faces' if not profiles.is_empty else 'unpaired window profile marker',
                    geometry_inferred=True,height_source='unknown',sill_source='unknown',material='glazing',schedule_match_status='unresolved')
                if profiles.is_empty:src['marker_width_m']=.01
                add(fid,'window',p,src,f'{n}층 창호 · {name}')
        glazing=[(l,e['id']) for e in use if e['layer'] in GLASS_LAYERS and e['root'] not in window_roots for l in entity_lines(e,offset) if l.length>.5]
        _,gbands,_=paired_wall_faces(glazing)
        gseen=set()
        for p,a,b,w in gbands:
            key=set_precision(p,.001).normalize().wkt
            if key in gseen or any(win.buffer(.01).covers(p) for win in window_shapes):continue
            gseen.add(key)
            add(fid,'window',p,dict(cad_ids=sorted({a,b}),method='paired glazing profiles',geometry_inferred=True,
                measured_profile_depth_m=round(w,4),height_source='unknown',sill_source='unknown',material='glazing'),f'{n}층 창호 경계 · {len(gseen)}')
        # Door arcs are separate leaves. Never discard a second leaf by overlap.
        arcs=[e for e in use if e['type']=='ARC' and e['layer'] in ('A-DOOR','A-DOR') and
            (e['root'] not in window_roots or e['root'] in window_door_roots) and .3<e['geometry']['radius']*.001<2]
        wall_lines=unary_union([l for l,_ in records]);closure=[];door_keys=set()
        for e in arcs:
            g=e['geometry'];hinge=xy(g['center'],offset)
            options=[LineString([hinge,xy(g[k],offset)]) for k in ('start','end')]
            leaf=min(options,key=lambda l:wall_lines.distance(Point(l.coords[-1])))
            key=(tuple(hinge),round(g['radius']*.001,3))
            if key in door_keys:continue
            door_keys.add(key);closure.extend(options)
            add(fid,'door',leaf.buffer(.15,cap_style=2),dict(cad_id=e['id'],layer=e['layer'],method='swing arc leaf and opening candidate',
                hinge=list(hinge),leaf_end=list(leaf.coords[-1]),swing_end=list(options[1 if leaf==options[0] else 0].coords[-1]),
                leaf_radius_m=g['radius']*.001,clear_width_source='unknown',height_source='unknown',geometry_inferred=True,
                closed_position_verified=False,material='door'),f'{n}층 출입문 후보 · {len(door_keys)}')
        # Identify BOTH cores from nosing layers, including anonymously named blocks.
        stair_voids=[]
        for root,cs in children.items():
            nosings=[(l,c['id']) for c in cs if c['layer']=='A-STAIR' for l in entity_lines(c,offset)]
            if len(nosings)<8:continue
            pts=[pt for l,_ in nosings for pt in l.coords]
            envelope=MultiPoint(pts).minimum_rotated_rectangle
            # Use the explicit closed core rectangle where it encloses the treads.
            candidates=[]
            for c in use:
                g=c['geometry']
                if c['type']=='LWPOLYLINE' and c['layer']=='A-CEN' and g.get('closed') and len(g['vertices'])>=3:
                    p=Polygon([xy(v,offset) for v in g['vertices']])
                    if 15<p.area<35 and p.buffer(.01).covers(envelope):candidates.append((p,c['id']))
            core_id=None
            if candidates:envelope,core_id=min(candidates,key=lambda item:item[0].area)
            parts,detail=stair_components(nosings,envelope,risers[:2])
            if not parts:continue
            if n in (0,5):
                # 3.9 / 5.4 m intervals cannot be filled with the typical 4.2 m flight.
                parts=[{**part,'height':None,'z_offset':0,'source':dict(geometry_inferred=True,height_source='non-typical flight unresolved')} for part in parts]
                detail.update(riser_m=None,risers_per_flight=None,riser_evidence=[],flight_height_status='unresolved non-typical storey')
            stair_voids.append(envelope)
            stair=add(fid,'stair',envelope,dict(cad_id=root,core_boundary_cad_id=core_id,method='CAD nosings and core section risers',
                geometry_inferred=True,connected_floors_verified=False,material='concrete',**detail),f'{n}층 계단 · 코어 {len(stair_voids)}',storey_height if n in (1,2,3,4) else None,components=parts)
            if stair:relationships.append(dict(element_id=stair[0]['id'],floor_id=fid,kind='stair_stack',
                position=list(envelope.centroid.coords)[0],review_status='flight direction and landings pending'))
        elevators=[]
        for label in labels:
            if label['geometry']['text']!='E.V':continue
            point=Point(xy(label['geometry']['insert'],offset));possible=[]
            for block in root_blocks:
                pts=[pt for c in children[block['id']] for l in entity_lines(c,offset) for pt in l.coords]
                if not pts:continue
                p=MultiPoint(pts).minimum_rotated_rectangle
                if p.geom_type=='Polygon' and 1<p.area<20 and p.covers(point):possible.append((p,block))
            if possible:
                p,b=min(possible,key=lambda item:item[0].area);elevators.append(p)
                add(fid,'elevator',p,dict(cad_id=b['id'],label_cad_id=label['id'],method='E.V labelled block envelope',
                    geometry_inferred=True,connected_floors_verified=False,height_source='shaft storey visualization',
                    car_dimensions_source='unknown',material='shaft'),f'{n}층 승강기 샤프트 후보 · {len(elevators)}',storey_height)
        core_polys[fid]=stair_voids+elevators
        # Close drawn face gaps up to 150 mm, explicitly recording this tolerance.
        boundary_records=[(l,e['id']) for e in use if e['layer'] in BOUNDARY for l in entity_lines(e,offset) if l.length>.05]
        barriers=unary_union([l.buffer(.075,cap_style=3) for l,_ in boundary_records+[(l,'door closure') for l in closure]])
        barriers=barriers.buffer(.075,join_style=2).buffer(-.075,join_style=2)
        regions=[p for p in polygon_parts(box(-1,-1,101,91).difference(barriers)) if 2<p.area<2000]
        # Remove the courtyard and both vertical cores from walkable slab coverage.
        # A 1 mm guard prevents precision-grid rounding from refilling a void edge.
        voids=unary_union([*([COURTYARD] if n>0 else []),*stair_voids,*elevators]).buffer(.001,join_style=2)
        if n<5:
            outline=unary_union([*regions,structural,*window_shapes]).buffer(.16,join_style=2).buffer(-.16,join_style=2)
            # Keep measured enclosed building regions; loose external columns are not a slab boundary.
            floor_poly=outline.difference(voids)
            floor_polys[fid]=floor_poly
            add(fid,'floor',floor_poly,dict(cad_ids=sorted({src for _,src in boundary_records}),method='enclosed CAD regions and wall bands; courtyard/core subtraction',
                geometry_inferred=True,coverage_verified=False,slab_thickness_source='unknown',closure_tolerance_m=.15,
                courtyard_evidence_ids=COURTYARD_IDS,void_guard_m=.001,material='slab'),f'{n}층 바닥 · 경계 검토 필요')
        else:
            # Roof perimeter lives on A-AL03. Polygonize its own profiles, not wall endpoint hulls.
            from shapely.ops import polygonize
            roof_lines=[l for e in use if e['layer'] in {'A-AL03','A-CON','A-FIN'} for l in entity_lines(e,offset)]
            roof_faces=[p for p in polygonize(unary_union(roof_lines)) if p.area>400]
            if roof_faces:
                roof_outline=unary_union(roof_faces)
                add(fid,'roof',roof_outline.difference(voids),dict(method='polygonized roof plan profiles',geometry_inferred=True,
                    thickness_source='unknown',material='roof'), '지붕 · 도면 경계 후보')
            else:
                # No closed roof profile: retain 4F perimeter as an explicitly unresolved projection.
                roof_outline=floor_polys['f4']
                add(fid,'roof',roof_outline,dict(method='4F perimeter projection; roof perimeter unresolved',geometry_inferred=True,
                    coverage_verified=False,thickness_source='unknown',material='roof'),'지붕 · 4층 외곽 투영 후보')
        if n>0:add(fid,'opening',COURTYARD,dict(cad_ids=COURTYARD_IDS,method='courtyard control-point trace from wall and glazing endpoints',
            geometry_inferred=True,coverage_verified=False,material='void'),f'{n}층 중정 · 바닥 제외 영역')
        # Each enclosed region has one space object, even when multiple labels share it.
        for i,region in enumerate(regions):
            for p in polygon_parts(region.difference(voids)):
                if p.area<2:continue
                matches=[e for e in labels if p.buffer(.02).covers(Point(xy(e['geometry']['insert'],offset))) and
                    e['geometry']['text'] not in ('E.V','EPS','PS','AV','TPS')]
                names=list(dict.fromkeys(e['geometry']['text'] for e in matches))
                if n==5:continue
                if not names and p.area<10:continue
                is_outdoor=any(name in ('데크','중정','하역공간') for name in names)
                kind='corridor' if any('홀' in name for name in names) else 'space'
                name=' / '.join(names) if names else f'미명명 실 {i+1}'
                src=dict(cad_ids=[e['id'] for e in matches],method='enclosed face region with door closures',geometry_inferred=True,
                    area_m2=round(p.area,3),closure_tolerance_m=.15,boundary_status='labels_share_boundary' if len(names)>1 else 'candidate',
                    constituent_labels=names,space_usage='outdoor' if is_outdoor else 'indoor_candidate',material='space')
                add(fid,kind,p,src,f'{n}층 {name} · 경계 후보')
        for e in labels:
            name=e['geometry']['text']
            if name in ('EPS','PS','AV','TPS','장비반입구','하역공간','중정','데크'):continue
            places.append(dict(id=f'{fid}-'+e['id'].replace('/','-').replace(':','-'),name=f'{n}층 {name}',floor_id=fid,
                point=xy(e['geometry']['insert'],offset)))
        # Exterior finish faces remain individual selectable elements.
        finish_records=[(l,e['id']) for e in use if e['layer'] in FINISH for l in entity_lines(e,offset) if l.length>.3]
        _,fbands,_=paired_wall_faces(finish_records);fseen=set()
        for p,a,b,w in fbands:
            key=set_precision(p,.001).normalize().wkt
            if key in fseen:continue
            fseen.add(key)
            add(fid,'wall',p,dict(cad_ids=sorted({a,b}),method='paired finish faces',geometry_inferred=True,
                material='finish',measured_thickness_m=round(w,4),height_source='storey envelope'),f'{n}층 외장 마감 · {len(fseen)}',storey_height)
        reports.append(dict(floor=fid,source_entity_count=len(use),wall_face_segments=len(records),unpaired_faces=len(unmatched),
            door_leaves=len(door_keys),stairs=len(stair_voids),elevators=len(elevators),enclosed_regions=len(regions),
            source_extent_mm=[ORIGIN[0]+offset,ORIGIN[1],ORIGIN[0]+offset+100000,ORIGIN[1]+90000]))
    # Associate hosts and spatial neighbours without declaring a traversable link.
    for e in elements:
        if e['type'] not in ('door','window'):continue
        p=Polygon(e['polygon'],e['holes'])
        e['source']['host_wall_ids']=[w['id'] for w in elements if w['type']=='wall' and w['floor_id']==e['floor_id'] and
            not w['source'].get('marker_width_m') and Polygon(w['polygon'],w['holes']).distance(p)<.2]
        if e['type']=='door':e['source']['adjacent_space_ids']=[s['id'] for s in elements if s['type'] in ('space','corridor') and
            s['floor_id']==e['floor_id'] and Polygon(s['polygon'],s['holes']).distance(p)<.35]
    source_audit=[dict(file=d['file'],sha256=d['source']['sha256_before'],original_unchanged=d['source']['original_unchanged'],
        entity_count=len(d['entities']),external_reference_count=len(d['external_references']),
        warning_counts=dict(Counter(w['code'] for w in d['warnings']))) for d in supplements]
    drawing_evidence=collect_evidence(supplements)
    annotate_columns(elements,drawing_evidence,{e['id']:e for e in es})
    for item in elements+places:
        if item['name'].startswith('0층'):item['name']=item['name'].replace('0층','지하 1층',1)
    basement_evidence=next(t for t in sections['texts'] if t['id']=='layout:Model/8F9D/child:34' and t['text']=='EL +33.80')
    evidence.insert(0,basement_evidence)
    model=Model.model_validate(dict(id='energy-center-actual-1f2f',name='에너지융복합종합지원센터 · 도면 기반 BIM',revision=1,
        floors=[dict(id='b1',name='지하 1층',elevation=-3.9)]+[dict(id=f'f{i}',name=f'지상 {i}층',elevation=(i-1)*4.2) for i in range(1,5)]+[dict(id='roof',name='지붕 / 옥탑 후보',elevation=16.8)],
        elements=elements,places=places,links=[],warnings=[
            '지하 1층·지상 1~4층과 지붕 평면을 사용했습니다. PIT층·옥탑 상부와 지하층 미폐합 영역의 전체 형상은 아직 복원하지 않았습니다.',
            '도면 개정 간 일치 여부는 미확인입니다. 누락 XREF와 변환 과정의 AEC 프록시 손실 때문에 전체 형상 확정을 보장하지 않습니다.',
            '벽 상단은 층 기준 간격으로 표시한 후보입니다. 실제 벽 높이·보·슬래브 두께는 구조도 및 상세 대조가 필요합니다.',
            '구조 평면·단면·일람표와 외벽·출입구·창호 상세·마감표를 조사했습니다. s-xref-plan 등 참조 본체가 누락됐으며 기둥 부호는 단면 호환 후보입니다. 일람표 치수를 확정 부재에 임의 적용하지 않았습니다.',
            '문·창의 XY는 도면 근거이며 높이·창대 높이와 창호 일람표의 개별 매칭은 미확인입니다. 뷰어의 선택적 높이 표시는 시각화 가정입니다.',
            '실 경계는 150 mm까지의 선 간극을 닫은 후보입니다. 여러 실명이 한 경계에 포함되는 구간은 분리 미확정으로 표시합니다.',
            '중정과 계단·승강기 영역을 바닥에서 제외했습니다. 중정은 CAD 끝점 연결 후보이고 슬래브 개구부는 구조 검토 전입니다.',
            '기준층 계단은 실제 단선 간격과 코어 상세의 175×12 높이를 사용합니다. 지하/옥탑 비기준층 계단은 높이 미확인 평면으로 보존합니다. 진행 방향·참·중앙 간격은 후보이며 280/300 mm 불일치가 있습니다.',
            '지붕 닫힌 외곽이 없으면 4층 외곽을 투영한 후보입니다. 경사지붕·파라펫·태양광·옥탑 상부를 임의로 만들지 않았습니다.',
            '계단·승강기 층간 위치 관계는 검토 후보입니다. BF links 및 경로 탐색 알고리즘은 변경하지 않았습니다.'],
        provenance=dict(modelling_version=2,floorplan_sha256=inventory['sha256'],section_sha256=sections['source']['sha256_before'],
            source_origin_mm=ORIGIN,sheet_spacing_mm=SHEET_SPACING,source_units='mm',coordinate_transform='XY=(CAD-Origin-sheet offset)*0.001; Z=EL-37.70',
            level_evidence=evidence,floor_reports=reports,source_audit=source_audit,drawing_evidence=drawing_evidence,assembly_relationships=relationships,review_status='unverified',
            missing_information=['지하층 미폐합 바닥/PIT 형상 및 옥탑 상부 모델','지붕 외곽과 파라펫 상세','개별 문·창호 높이/창대 및 일람표 매칭',
                '구조 보·슬래브 두께/슬래브 개구부: 구조 일람표와 s-xref-plan 본체·부재 위치 매칭 필요',
                '외벽 상세와 창호 상세의 24/28 mm 유리 사양 및 적용 부위 매칭',
                '계단 진행 방향/참 및 단너비 도면 불일치','식당·주방 등 공유 경계의 실 구획','도면 개정 일치와 누락 XREF'])))
    (OUT/'energy-center-model.json').write_text(model.model_dump_json(indent=2),encoding='utf-8')
    report=dict(model_elements=len(model.elements),types=dict(Counter(e.type for e in model.elements)),floor_reports=reports,
        level_evidence=evidence,source_audit=source_audit,drawing_evidence=drawing_evidence,missing_information=model.provenance['missing_information'])
    (OUT/'energy-center-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(model_elements=len(model.elements),types=report['types'],places=len(places),
        audited_drawings=len(source_audit)+1,column_section_candidates=len(drawing_evidence['column_sections']),
        detail_notes=len(drawing_evidence['note_candidates'])),ensure_ascii=False,indent=2))

if __name__=='__main__':main()
