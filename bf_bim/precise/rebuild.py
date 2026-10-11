"""Drawing-first whole-building reconstruction; run python -m bf_bim.precise.rebuild.

No legacy generator, slab repair, wall pairing or global window dimensions.
Metric native profiles and topological cycles are retained as observations.
Unconfirmed vertical surfaces exist ONLY in preview.json. IFC is fail-closed.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

from shapely import set_precision
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import polygonize, unary_union

from .stage1 import ROOT, OUTPUT as ARCHIVE, AUDIT, read, sha256, drawing_id
from .geometry import sample, to_local, to_cad, closed_native
from .schema import Registration
from bf_bim.schema import Model
from bf_bim.ifc_export import export_ifc

OUTPUT=ROOT/'cad_output/precision-rebuild'
TOLERANCE=.0005
NUMERIC_GRID=.0000001  # 0.1 micrometre, numerical noding only; no CAD gap repair.
SPACING=126150.00007091
WALL_LAYERS={'A-CON','A-WAL','A-WALL','A-BRICK'}
FINISH_LAYERS={'A-FIN','A-STONE','A-INSUL'}
GLASS_LAYERS={'A-WIN'}
CURVES={'LINE','LWPOLYLINE','POLYLINE','ARC','CIRCLE','ELLIPSE','SPLINE'}
PLAN_ID='A04-001~008'


def write(name,value):
    path=OUTPUT/name
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,allow_nan=False,indent=2),encoding='utf-8')
    temp.replace(path)


def load_archive(identifier,rows):
    row=next(r for r in rows if drawing_id(r)==identifier)
    data=read(ARCHIVE/'extractions'/f'{identifier}.json.gz')
    if (data['source']['sha256_before']!=row['sha256']
            or sha256(ROOT/row['file'])!=row['sha256']):
        raise ValueError(f'{identifier}: stale source/archive')
    if data['coverage']['scene_truncated']:
        raise ValueError(f'{identifier}: truncated geometry cannot generate members')
    if data.get('precision_identity_version')!=1:
        raise ValueError(f'{identifier}: archive lacks original block identities')
    return data,row


def layer(e):
    return e.get('effective_layer',e.get('layer','')).split('$')[-1].upper()


def safe(e,clipped):
    return (e.get('support')=='full' and not e.get('precision_geometry_blocked')
            and not set(e.get('insert_ancestry',[])).intersection(clipped))


def native_profile(e,frame,tolerance=TOLERANCE):
    points=sample(e['type'],e['geometry'],tolerance/frame.scale_m_per_unit)
    if max(p[2] for p in points)-min(p[2] for p in points)>1e-7:
        raise ValueError('Nonplanar native profile')
    local=[to_local(p,frame) for p in points]
    poly=None
    if closed_native(e['type'],e['geometry']):
        if math.dist(points[0],points[-1])>1e-6:
            raise ValueError('Native closed flag disagrees with endpoints')
        candidate=Polygon(local)
        if candidate.is_valid and candidate.area>1e-8: poly=candidate
    return LineString(local),poly


def topological_profiles(records,max_area=40,max_half_width=.251):
    """Actual noded closed cycles. Never join gaps, offset faces or fill holes.

    Thinness is only a candidate filter; it does not certify a wall identity.
    Each accepted boundary must be covered by its own source curves.
    """
    if not records:return []
    network=unary_union([set_precision(line,NUMERIC_GRID) for line,_ in records])
    result=[]
    for poly in polygonize(network):
        # Noding computes intersection vertices between already rounded
        # curves. Quantise those computed vertices to the same numerical grid
        # so microscopic duplicate corners do not reach either renderer.
        poly=set_precision(poly,NUMERIC_GRID)
        if poly.geom_type!='Polygon' or poly.is_empty or not poly.is_valid:continue
        if not .0001<poly.area<max_area or not poly.buffer(-max_half_width).is_empty:continue
        ids=[identifier for line,identifier in records
             if line.intersection(poly.boundary.buffer(NUMERIC_GRID*2)).length>NUMERIC_GRID*3]
        source=unary_union([line for line,identifier in records if identifier in ids])
        residual=poly.boundary.hausdorff_distance(source.intersection(poly.boundary.buffer(NUMERIC_GRID*3)))
        if residual>NUMERIC_GRID*4:continue
        result.append((poly,sorted(set(ids)),residual))
    return result


def ring(coords):return [[float(x),float(y)] for x,y in list(coords)[:-1]]


def profile_dict(poly):
    return {'polygon':ring(poly.exterior.coords),'holes':[ring(r.coords) for r in poly.interiors]}


def measured_sizes(poly,e=None):
    if e and e['type']=='CIRCLE':return {'shape':'circular','diameter_m':2*e['geometry']['radius']*.001}
    corners=list(poly.minimum_rotated_rectangle.exterior.coords)
    return {'shape':'polygonal','bounding_section_m':sorted([math.dist(corners[0],corners[1]),math.dist(corners[1],corners[2])]),
            'area_m2':poly.area,'perimeter_m':poly.length}


def column_alignment(reference,current,tolerance=.002):
    """Check seed sheet transform against column centres, with one-to-one matches.

    No transform is silently moved to improve the score. No centre proximity
    establishes that two columns have the same structural member mark.
    """
    pairs=[];used=set()
    for b in current:
        candidates=[a for a in reference if a['id'] not in used and math.dist(a['center'],b['center'])<=tolerance]
        if len(candidates)==1:
            a=candidates[0];used.add(a['id']);pairs.append({'reference_id':a['id'],'member_id':b['id'],
                'residual_m':math.dist(a['center'],b['center']), 'section_matches':a['sizes']==b['sizes']})
    matched=[b for b in current if b['id'] in {p['member_id'] for p in pairs}]
    noncollinear=any(abs((b['center'][0]-a['center'][0])*(c['center'][1]-a['center'][1])
                         -(b['center'][1]-a['center'][1])*(c['center'][0]-a['center'][0]))>1e-5
                    for a in matched for b in matched for c in matched) if len(pairs)>=3 else False
    return {'status':'geometry_controls_match' if len(pairs)>=3 and noncollinear else 'insufficient_controls',
            'matched_centers':len(pairs),'unmatched_centers':len(current)-len(pairs),
            'max_residual_m':max((p['residual_m'] for p in pairs),default=None),
            'tolerance_m':tolerance,'pairs':pairs,
            'limitation':'Centre constellation validates relative geometry only; grid identity and revision remain unconfirmed'}


def level_records(rows):
    data,row=load_archive('A04-021~026',rows)
    texts=[e for e in data['scene_entities'] if e['id'].startswith('layout:Model/8F9D/') and e['type'] in ('TEXT','MTEXT')]
    levels={}
    for e in texts:
        text=e['geometry']['text'].replace(' ','')
        if text.startswith('EL+'):
            try:value=float(text[3:])
            except ValueError:continue
            levels.setdefault(round(value,2),[]).append({'drawing_id':'A04-021~026','cad_id':e['id'],
                'text':e['geometry']['text'],'source_sha256':row['sha256']})
    expected=[33.8,37.7,41.9,46.1,50.3,54.5,59.9]
    if any(v not in levels for v in expected):raise ValueError('Section level annotation changed')
    return levels


def sheet_specs(levels):
    specs=[]
    for n,fid,name,el in [(0,'b1','지하 1층',33.8),(1,'f1','지상 1층',37.7),(2,'f2','지상 2층',41.9),
                          (3,'f3','지상 3층',46.1),(4,'f4','지상 4층',50.3),(5,'roof','옥상 / 지붕 평면',54.5),
                          (6,'phroof','옥탑지붕',59.9)]:
        specs.append({'id':fid,'name':name,'origin':[32920000+(n-1)*SPACING,-5730000],
                      'elevation':round(el-37.7,6),'level_evidence':levels[el],
                      'height_preview':3.9 if n==0 else 4.2 if n<5 else 5.4 if n==5 else None,
                      'level_assignment':'section_level_candidate','sheet_group':'primary'})
    # The second sheet group is translated as a whole, from the two 1F title
    # positions. Column controls verify (or reject) this seed independently.
    delta=[33404077.36864104-33017620.23931913,-4925351.805333163-(-5703270.086600297)]
    for n,fid,name,el in [(-1,'pit','PIT 평면',32.2),(5,'ph','옥탑 평면 · 별도 도면군',54.5)]:
        specs.append({'id':fid,'name':name,'origin':[32920000+(n-1)*SPACING+delta[0],-5730000+delta[1]],
                      'elevation':round(el-37.7,6),'level_evidence':levels.get(el,[]),
                      'height_preview':None,'level_assignment':'unconfirmed_PIT_level' if fid=='pit' else 'alternative_sheet_group',
                      'sheet_group':'alternative','preview_withheld':fid=='ph'})
    return specs


def select(entities,spec):
    ox,oy=spec['origin']
    result=[]
    for e in entities:
        if e.get('layout')!='Model':continue
        b=e.get('bounds')
        if b and ox<=b['min'][0] and b['max'][0]<=ox+100000 and oy<=b['min'][1] and b['max'][1]<=oy+90000:
            result.append(e)
        elif e['type'] in ('INSERT','DIMENSION'):
            p=e['geometry'].get('insert') or e['geometry'].get('definition_points_raw',{}).get('defpoint')
            if p and ox<=p[0]<=ox+100000 and oy<=p[1]<=oy+90000:result.append(e)
    return result


def build_sheet(data,row,spec):
    frame=Registration(id=spec['id']+'-local',drawing_id=PLAN_ID,origin_cad=tuple(spec['origin']),scale_m_per_unit=.001,status='candidate')
    entities=select(data['scene_entities'],spec)
    clipped={w.get('entity_id') for w in data['warnings'] if w['code']=='XCLIP_NOT_APPLIED'}
    by_id={e['id']:e for e in entities}
    members=[];traces=[];issues=[];comparisons=[];profiles_seen={};records=defaultdict(list)

    def add(kind,poly,ids,method,status='measured_geometry',boundary_error=0,native=None):
        key=(kind,set_precision(poly,NUMERIC_GRID).normalize().wkb_hex)
        if key in profiles_seen:
            previous=profiles_seen[key]
            previous['cad_ids']=sorted(set(previous['cad_ids']+ids))
            previous['evidence'][0]['cad_ids']=previous['cad_ids']
            return previous
        # CAD instances can differ below floating point noise after a nested
        # insertion. Consolidate geometrically identical boundaries only.
        for previous in members:
            if previous['kind']!=kind or math.dist(previous['center'],list(poly.centroid.coords[0]))>NUMERIC_GRID:continue
            old=Polygon(previous['polygon'],previous['holes'])
            if old.boundary.hausdorff_distance(poly.boundary)<=NUMERIC_GRID and abs(old.area-poly.area)<NUMERIC_GRID:
                previous['cad_ids']=sorted(set(previous['cad_ids']+ids))
                previous['evidence'][0]['cad_ids']=previous['cad_ids']
                profiles_seen[key]=previous
                return previous
        identity='pr-'+hashlib.sha256((spec['id']+'/'+kind+'/'+','.join(sorted(ids))+'/'+poly.normalize().wkb_hex).encode()).hexdigest()[:24]
        sizes=measured_sizes(poly,native)
        unknowns=['member_identity','material','member_bottom','member_top','design_revision','structural_assignment']
        if kind in ('window','door'):unknowns+=['schedule_mark','opening_host','sill','head','frame_section']
        if kind in ('floor','roof'):unknowns+=['slab_thickness','structural_boundary','opening_assignment']
        m={'id':identity,'kind':kind,'floor_id':spec['id'],**profile_dict(poly),
           'center':list(poly.centroid.coords[0]),'cad_ids':ids,'plan_status':status,'verified':False,
           'geometry_validation':{'plan':'match','vertical':'insufficient_source','boundary_tolerance_m':TOLERANCE},
           'dimension_validation':{'cad_geometry':'measured','design_assignment':'unconfirmed'},
           'dimensions':{'measured_plan':sizes,'height':None,'base_elevation':None},'material':None,'member_mark':None,
           'method':method,'unknowns':unknowns,'conflicts':[],
           'evidence':[{'drawing_id':PLAN_ID,'file':row['file'],'source_sha256':row['sha256'],'cad_ids':ids,
                        'definition_handles':[by_id[i].get('definition_handle') or by_id[i].get('handle') for i in ids],
                        'registration_id':frame.id,'relation':method}],
           'curve_approximation':{'method':'adaptive_or_sagitta','tolerance_m':TOLERANCE,'native_archive':f'precision-stage1/extractions/{PLAN_ID}.json.gz'}}
        m['numeric_noding_grid_m']=NUMERIC_GRID if method.startswith('closed source curve network') else None
        members.append(m);profiles_seen[key]=m
        comparisons.append({'member_id':identity,'floor_id':spec['id'],'status':'match','scope':'native_plan_geometry_only',
                            'boundary_distance_m':boundary_error,'tolerance_m':.002,'cad_ids':ids,
                            'vertical_status':'insufficient_source','semantic_status':'unconfirmed'})
        return m

    for e in entities:
        if e['type'] not in CURVES:continue
        kind=('column' if layer(e)=='A-COL' else 'wall' if layer(e) in WALL_LAYERS else 'finish' if layer(e) in FINISH_LAYERS
              else 'window' if layer(e) in GLASS_LAYERS else 'door' if layer(e) in {'A-DOOR','A-DOR'}
              else 'stair' if layer(e).startswith('A-STAIR') else 'roof_trace' if layer(e) in {'A-AL01','A-AL03','A-ELEV2','A-ELEV3','A-ELEV4','A-ELEV5','A-ELEV6'} and spec['id'] in ('roof','phroof','ph') else None)
        if kind is None:continue
        if not safe(e,clipped):
            issues.append({'cad_id':e['id'],'floor_id':spec['id'],'reason':'partial, transformed or XCLIP geometry blocked'});continue
        try:line,poly=native_profile(e,frame)
        except (ValueError,KeyError,ZeroDivisionError) as exc:
            issues.append({'cad_id':e['id'],'floor_id':spec['id'],'reason':str(exc)});continue
        if line.length<1e-7:continue
        traces.append({'id':e['id'],'floor_id':spec['id'],'kind':kind,'points':[list(p) for p in line.coords],
                       'native_type':e['type'],'tolerance_m':TOLERANCE})
        records[(kind,layer(e))].append((line,e['id']))
        if kind=='column' and poly is not None:
            fresh_points=sample(e['type'],e['geometry'],.00025/frame.scale_m_per_unit)
            expected=Polygon([to_local(p,frame) for p in fresh_points])
            add('column',poly,[e['id']],'closed native column outline',native=e,
                boundary_error=expected.boundary.hausdorff_distance(poly.boundary))
    for (kind,material_layer),lines in records.items():
        if kind not in ('wall','finish','window'):continue
        for poly,ids,residual in topological_profiles(lines):
            add('wall' if kind=='finish' else kind,poly,ids,'closed source curve network: '+material_layer,
                status='measured_boundary_candidate',boundary_error=residual)
    # Do not make slabs from architectural floor outlines or roof projections.
    # All open wall curves remain visible as explicitly unresolved surfaces.
    titles=[{'cad_id':e['id'],'text':e['geometry']['text']} for e in entities if e['type'] in ('TEXT','MTEXT') and '평면도' in e['geometry'].get('text','')]
    spec={**spec,'registration':frame.model_dump(),'titles':titles,'cad_entity_count':len(entities),
          'counts':dict(Counter(m['kind'] for m in members)), 'trace_counts':dict(Counter(t['kind'] for t in traces))}
    return members,traces,issues,comparisons,spec


def build_preview(members,traces,specs,row):
    elements=[];lookup={s['id']:s for s in specs}
    covered=defaultdict(list)
    for m in members:
        s=lookup[m['floor_id']]
        if s.get('preview_withheld'):continue
        source={'file':row['file'],'cad_ids':m['cad_ids'],'precision_member_id':m['id'],
                'geometry_status':'measured_plan','height_source':'미확정 · 단면 층간 구간을 미리보기 외피로 사용',
                'material':'unknown','evidence':m['evidence'],'unknowns':m['unknowns'],
                'dimension_validation':m['dimension_validation'],'member_mark':m.get('member_mark'),
                'design_assignment_verified':False,'geometry_validation':m['geometry_validation'],
                'conflicts':m['conflicts'],'structural_section_candidates':m.get('schedule_candidates',[])}
        height=s['height_preview'] if m['kind'] in ('wall','column') and not m['conflicts'] else None
        components=[]
        if height:
            components=[{'id':m['id']+'/preview','role':'unconfirmed_storey_envelope',**{k:m[k] for k in ('polygon','holes')},
                         'height':height,'z_offset':0,'source':{'geometry_status':'provisional','dimension_verified':False,
                          'material':'unknown','height_is_member_dimension':False,'section_level_evidence':s['level_evidence']}}]
        elements.append({'id':m['id'],'name':s['name']+' · '+{'column':'기둥 경계','wall':'벽 경계','window':'창호 평면 경계'}[m['kind']],
                         'type':m['kind'],'floor_id':s['id'],**{k:m[k] for k in ('polygon','holes')},
                         'height':None,'verified':False,'source':source,'components':components})
        if m['kind']=='wall':covered[s['id']].append(Polygon(m['polygon'],m['holes']))
    # Surfaces give spatial context where the drawing has no closed wall solid.
    # A 1 mm marker is a rendering width, never a measured wall thickness.
    networks={fid:unary_union(polys).boundary for fid,polys in covered.items()}
    for t in traces:
        s=lookup[t['floor_id']]
        if t['kind']!='wall' or not s['height_preview'] or s.get('preview_withheld'):continue
        line=LineString(t['points'])
        if line.length<.02:continue
        network=networks.get(s['id'])
        if network is not None and line.difference(network.buffer(.000001)).length<.000002:continue
        p=line.buffer(.0005,cap_style=2,join_style=2)
        if p.geom_type!='Polygon' or not p.is_valid or len(p.exterior.coords)>2000:continue
        identity='surface-'+hashlib.sha256((s['id']+t['id']).encode()).hexdigest()[:22]
        elements.append({'id':identity,'name':s['name']+' · 미확정 벽면','type':'wall','floor_id':s['id'],
                         **profile_dict(p),'height':None,'source':{'file':row['file'],'cad_ids':[t['id']],
                         'geometry_status':'preview_only','marker_width_m':.001,'height_source':'층간 시각화 구간 · 부재 높이 미확인',
                         'unknowns':['wall_thickness','wall_top','wall_material','structural_role'],
                         'preview_only':True,'design_assignment_verified':False},
                         'components':[{'id':identity+'/preview','role':'unconfirmed_wall_surface',**profile_dict(p),
                          'height':s['height_preview'],'source':{'geometry_status':'provisional','dimension_verified':False}}]})
    # Native door swings, stairs, glazing and roof lines retain their actual CAD
    # paths instead of rectangular proxy volumes with guessed dimensions.
    return Model.model_validate({'id':'energy-center-precision-rebuild','name':'에너지융복합종합지원센터 · 도면 기반 재구축',
          'revision':1,'floors':[{'id':s['id'],'name':s['name'],'elevation':s['elevation']} for s in specs],
          'elements':elements,'places':[],'links':[],
          'warnings':['평면 경계와 미확정 3D 외피를 함께 표시합니다. 실제 부재의 높이·재료·구조 배치는 검증 전입니다.',
                      '구조 슬래브·보·창호 높이·계단 방향은 배치 근거가 부족하여 확정 입체로 생성하지 않았습니다.',
                      '옥탑은 별도 도면군의 개정·좌표 대응이 미확정이므로 중복 입체를 표시하지 않습니다.'],
          'provenance':{'precision_rebuild':True,'modelling_version':6,'source_drawing_sha256':row['sha256'],
                        'floors_evidence':specs,'cad_traces':[t for t in traces if not lookup[t['floor_id']].get('preview_withheld')],
                        'missing_information':['누락 XREF의 구조 평면·단면·입면','부재 상하단 및 구조 슬래브 경계','창호 일람표와 평면 부호 대응','PIT 및 옥탑 레벨 대응'],
                        'verified_solids':0,'preview_policy':'Provisional components and marker widths excluded from precise IFC; original native traces retained'}})


def validate_model(members,comparisons,specs,preview):
    errors=[];conflicts=[];relationships=[]
    grouped=defaultdict(list)
    for m in members:grouped[m['floor_id']].append(m)
    for fid,items in grouped.items():
        for i,a in enumerate(items):
            pa=Polygon(a['polygon'],a['holes'])
            for b in items[i+1:]:
                pb=Polygon(b['polygon'],b['holes'])
                if not pa.intersects(pb):continue
                overlap=pa.intersection(pb).area
                if a['kind']==b['kind'] and overlap>1e-6:
                    item={'type':'overlapping_native_profiles','a':a['id'],'b':b['id'],'overlap_m2':overlap,'floor_id':fid}
                    conflicts.append(item);a['conflicts'].append(item);b['conflicts'].append(item)
                elif {a['kind'],b['kind']}=={'column','wall'}:
                    relationships.append({'type':'column_wall_geometric_contact','a':a['id'],'b':b['id'],
                                          'status':'geometric_only','structural_connection_verified':False})
    for c in comparisons:
        if c['boundary_distance_m']>.002:errors.append({'type':'plan_mismatch',**c})
    for e in preview.elements:
        if e.height is not None or e.verified:errors.append({'type':'preview_dimension_leak','id':e.id})
        for c in e.components:
            if c.source.get('geometry_status')!='provisional':errors.append({'type':'preview_status_missing','id':c.id})
    for m in members:
        if not m['evidence'] or not m['cad_ids']:errors.append({'type':'missing_geometry_evidence','id':m['id']})
    return {'status':'passed_with_unresolved_design' if not errors else 'failed','errors':errors,
            'native_profile_conflicts':conflicts,'contacts':relationships,'plan_comparisons':comparisons,
            'vertical_comparisons':'insufficient_member_specific_source','registration':[{'floor_id':s['id'],**s['alignment']} for s in specs],
            'checks':{'duplicates':'identical profiles consolidated with CAD references; overlapping distinct profiles reported',
                      'slab_openings':'not_verifiable: no assigned structural slab boundaries',
                      'door_window_host':'not_verifiable: native symbols are not assigned openings',
                      'beams':'not_verifiable: no located beam boundaries',
                      'coordinate_roundtrip':'checked against native source','unsupported_geometry':'blocked before member generation'}}


def build(sync_web=False):
    rows=read(AUDIT/'drawing-index.json')
    protected=[ROOT/r['file'] for r in rows]
    protected += [p for p in (ROOT/'cad_output').rglob('*') if p.is_file() and not p.is_relative_to(OUTPUT)]
    own_web_files={ROOT/'web/public/models/precision-rebuild.json',ROOT/'web/public/models/precision-rebuild-verified.ifc'}
    protected += [p for p in (ROOT/'web/public').rglob('*') if p not in own_web_files]
    before={str(p.relative_to(ROOT)).replace('\\','/'):sha256(p) for p in protected if p.is_file()}
    OUTPUT.mkdir(parents=True,exist_ok=True)
    levels=level_records(rows)
    data,row=load_archive(PLAN_ID,rows)
    members=[];traces=[];issues=[];comparisons=[];specs=[]
    for seed in sheet_specs(levels):
        ms,ts,es,cs,s=build_sheet(data,row,seed)
        members+=ms;traces+=ts;issues+=es;comparisons+=cs;specs.append(s)
        print(s['id'],s['counts'],'traces',len(ts),flush=True)
    reference=[{'id':m['id'],'center':m['center'],'sizes':m['dimensions']['measured_plan']} for m in members if m['kind']=='column' and m['floor_id']=='f1']
    for s in specs:
        columns=[{'id':m['id'],'center':m['center'],'sizes':m['dimensions']['measured_plan']} for m in members if m['kind']=='column' and m['floor_id']==s['id']]
        s['alignment']=column_alignment(reference,columns)
    preview=build_preview(members,traces,specs,row)
    from .evidence import collect_schedule_observations,attach_column_candidates
    archives=[]
    for identifier in ('S04-001','S04-018','S02-001~','S03-001~'):
        archive,source_row=load_archive(identifier,rows)
        archives.append((identifier,archive,source_row))
    schedule=collect_schedule_observations(archives)
    attach_column_candidates(members,schedule)
    del archives
    write('schedule-observations.json',schedule)
    preview.provenance['drawing_evidence']=schedule['survey']
    validation=validate_model(members,comparisons,specs,preview)
    # Conflicting sections remain visible in plan, but never receive preview
    # extrusion. Regenerate after the clash audit has populated each record.
    preview=build_preview(members,traces,specs,row)
    preview.provenance['drawing_evidence']=schedule['survey']
    # A valid IFC spatial hierarchy is still produced when no solids meet the
    # evidence gate. It deliberately contains ZERO building element products.
    precise_model=Model(id='energy-center-precision-verified',name='에너지센터 · 검증 형상 IFC (미확정 부재 제외)',
                        floors=preview.floors,elements=[],places=[],links=[],
                        warnings=['No verified member solids; spatial hierarchy only'],
                        provenance={'verified_solids':0,'excluded_preview_elements':len(preview.elements)})
    (OUTPUT/'verified.ifc').write_text(export_ifc(precise_model),encoding='utf-8')
    from bf_bim.validate_ifc import validate_file
    ifc_check=validate_file(precise_model,OUTPUT/'verified.ifc')
    ifc_check['solid_geometry_validation']='not_run_no_verified_solids'
    validation['ifc']=ifc_check
    validation['ifc_web_parity']={'status':'not_verifiable_no_verified_solids','verified_web_members':0,'ifc_products':ifc_check['products'],
                                   'excluded_preview_elements':len(preview.elements),'not_full_preview_parity':True}
    unresolved=[{'floor_id':s['id'],'kind':kind,'status':'unresolved','reason':reason}
                for s in specs for kind,reason in [('beam','Structural outline/span/mark not jointly available; schedule alone is insufficient'),
                ('slab','No located, revision-matched structural slab boundary/thickness/opening assignment'),
                ('opening','Door/window symbols not connected to schedule heights and host wall'),
                ('stair','Native nosings retained; direction, landings and per-floor vertical assignment unconfirmed'),
                ('elevator','Shaft boundary, PIT and upper clearance not jointly confirmed')]]
    write('bim.json',{'schema_version':'precision-rebuild/1','created_at':datetime.now(timezone.utc).isoformat(),
                    'members':members,'floors':specs,'verified_solids':0,'preview_model':'preview.json',
                    'source_geometry_archive':f'../precision-stage1/extractions/{PLAN_ID}.json.gz'})
    write('preview.json',preview.model_dump(mode='json'))
    write('verified-model.json',precise_model.model_dump(mode='json'))
    write('validation.json',validation)
    write('unresolved.json',{'members':[{'id':m['id'],'floor_id':m['floor_id'],'unknowns':m['unknowns'],'conflicts':m['conflicts']} for m in members],
                             'unimplemented':unresolved,'extraction_issues':issues,
                             'missing_xrefs':read(ARCHIVE/'build-summary.json')['missing_xrefs']})
    summary={'status':validation['status'],'floors':[{'id':s['id'],'name':s['name'],'counts':s['counts'],'traces':s['trace_counts'],
                                                   'alignment':s['alignment']['status'],'level_assignment':s['level_assignment']} for s in specs],
             'member_counts':dict(Counter(m['kind'] for m in members)),'preview_elements':len(preview.elements),
             'preview_solids':sum(c.height is not None for e in preview.elements for c in e.components),
             'verified_solids':0,'plan_matches':len(comparisons),'conflicts':len(validation['native_profile_conflicts']),
             'extraction_issues':len(issues),'ifc':ifc_check,
             'completion':'partial reconstruction; design-verified full-building BIM not achieved'}
    write('summary.json',summary)
    render_comparisons(members,traces,specs)
    after={p:sha256(ROOT/p) for p in before}
    preservation={'checked_files':len(before),'changed_files':[p for p in before if before[p]!=after[p]],'hashes_before':before,'hashes_after':after}
    write('preservation.json',preservation)
    if preservation['changed_files']:raise RuntimeError('Protected original/legacy files changed')
    if validation['errors']:raise RuntimeError('Generated geometry validation failed')
    if sync_web:
        import shutil
        # Local asset preparation only; no publishing, git push or deployment.
        shutil.copyfile(OUTPUT/'preview.json',ROOT/'web/public/models/precision-rebuild.json')
        shutil.copyfile(OUTPUT/'verified.ifc',ROOT/'web/public/models/precision-rebuild-verified.ifc')
    print(json.dumps({k:v for k,v in summary.items() if k!='floors'},ensure_ascii=True),flush=True)


def render_comparisons(members,traces,specs):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection
    for s in specs:
        fig,ax=plt.subplots(figsize=(11,9))
        paths=[t['points'] for t in traces if t['floor_id']==s['id']]
        if paths:ax.add_collection(LineCollection(paths,colors='#a3abb1',linewidths=.5,label='Native CAD traces (same sheet frame)'))
        for kind,color in [('column','#b74040'),('wall','#277d55'),('window','#2876b0')]:
            paths=[]
            for m in members:
                if m['floor_id']==s['id'] and m['kind']==kind:
                    paths.append(m['polygon']+[m['polygon'][0]])
                    paths += [r+[r[0]] for r in m['holes']]
            if paths:ax.add_collection(LineCollection(paths,colors=color,linewidths=1.2,label=f'{kind}: measured boundary candidates'))
        ax.autoscale();ax.set_aspect('equal');ax.grid(alpha=.15)
        ax.set_title(f"{s['id']} CAD / reconstructed plan comparison\nPlan geometry only; member height, identity and revision UNCONFIRMED")
        ax.set_xlabel('Building candidate X (m)');ax.set_ylabel('Building candidate Y (m)')
        if ax.get_legend_handles_labels()[0]:ax.legend(loc='upper left',fontsize=8)
        fig.tight_layout();fig.savefig(OUTPUT/f'comparison-{s["id"]}.png',dpi=150);plt.close(fig)


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sync-web',action='store_true',help='Copy new local preview assets only; no remote publishing')
    parser.add_argument('--coordination',action='store_true',help='Extend preserved native results with explicit provisional 3D assemblies')
    parser.add_argument('--reviews',type=Path,help='Explicit reviewed member evidence ledger; no automatic approval')
    args=parser.parse_args()
    if args.coordination:
        from .coordination import build as build_coordination
        build_coordination(sync_web=args.sync_web,reviews_path=args.reviews)
    else:build(sync_web=args.sync_web)
