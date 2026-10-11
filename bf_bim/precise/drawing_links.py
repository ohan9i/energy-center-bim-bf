"""Link drawing observations without equating geometric proximity with approval."""
from collections import defaultdict
import math
import re

from shapely.geometry import Point, Polygon

from .rebuild import select, safe, native_profile, layer
from .schema import Registration


def plan_callouts(plan_archive, schedule_archive, row, specs, elements):
    """Register A10 plan sheets against A04 grid annotations before querying tags.

    Type/number symbols are kept as candidate links: no leader, floor scope or
    schedule dimensions are silently inferred from nearest-text distance.
    """
    report=[]
    clipped={w.get('entity_id') for w in schedule_archive['warnings'] if w['code']=='XCLIP_NOT_APPLIED'}
    for s in specs:
        def texts(archive):
            clipped={w.get('entity_id') for w in archive['warnings'] if w['code']=='XCLIP_NOT_APPLIED'}
            return [e for e in select(archive['scene_entities'],s) if e['type'] in ('TEXT','MTEXT','ATTRIB')
                    and e['geometry'].get('insert') and safe(e,clipped)]
        original=texts(plan_archive);current=texts(schedule_archive)
        controls=[]
        frame=Registration(id=s['id']+'-A10-controls',drawing_id='A10-001~',origin_cad=tuple(s['origin']),scale_m_per_unit=.001)
        columns=[e for e in elements if e['floor_id']==s['id'] and e['type']=='column' and not e['source'].get('section_candidate_suppressed')]
        used=set()
        for e in select(schedule_archive['scene_entities'],s):
            if layer(e)!='A-COL' or e['type'] not in ('CIRCLE','LWPOLYLINE','POLYLINE') or not safe(e,clipped):continue
            try:_,p=native_profile(e,frame)
            except (ValueError,KeyError):continue
            if p is None:continue
            matches=[q for q in columns if Polygon(q['polygon'],q.get('holes',[])).boundary.hausdorff_distance(p.boundary)<.002]
            if len(matches)!=1 or matches[0]['id'] in used:continue
            q=matches[0];used.add(q['id'])
            controls.append({'cad_ids':[q['source']['cad_ids'][0],e['id']],'position':list(p.centroid.coords)[0],
                'residual_m':Polygon(q['polygon'],q.get('holes',[])).boundary.hausdorff_distance(p.boundary),
                'method':'native column boundary control, not displaced grid label text'})
        # A10 omits column geometry with its unavailable plan XREF, but retains
        # native grid DIMENSION endpoints. Match these exact coordinates without
        # shifting drawings to displaced text labels or presumed building sizes.
        if len(controls)<3:
            originals=[e for e in select(plan_archive['scene_entities'],s) if e['type']=='DIMENSION' and safe(e,set())]
            matched_points=set()
            for e in select(schedule_archive['scene_entities'],s):
                if e['type']!='DIMENSION' or not safe(e,clipped):continue
                for key,point in e['geometry'].get('definition_points_raw',{}).items():
                    if key not in ('defpoint2','defpoint3') or not point:continue
                    identity=tuple(round(v*.001,5) for v in point[:2])
                    if identity in matched_points:continue
                    matches=[(q,pt) for q in originals for k,pt in q['geometry'].get('definition_points_raw',{}).items()
                        if k in ('defpoint2','defpoint3') and pt and math.dist(pt[:2],point[:2])*.001<.002
                        and abs(q['geometry'].get('measurement',0)-e['geometry'].get('measurement',0))*.001<.002]
                    if not matches:continue
                    q,pt=matches[0];matched_points.add(identity)
                    controls.append({'cad_ids':[q['id'],e['id']],
                        'position':[(point[j]-s['origin'][j])*.001 for j in (0,1)],
                        'residual_m':math.dist(pt[:2],point[:2])*.001,'method':'matched native dimension definition point and measured span'})
        noncollinear=any(abs((b['position'][0]-a['position'][0])*(c['position'][1]-a['position'][1])
                            -(b['position'][1]-a['position'][1])*(c['position'][0]-a['position'][0]))>.001
                         for a in controls[:1] for b in controls for c in controls)
        registered=len(controls)>=3 and noncollinear
        linked=0
        if registered:
            for e in current:
                label=e['geometry'].get('text','').strip()
                if label not in ('AW','AD','SSD','SD','FSD','SW','FSSD'):continue
                x,y=e['geometry']['insert'][:2]
                numbers=[q for q in current if re.fullmatch(r'\d+',q['geometry'].get('text','').strip())
                         and abs(q['geometry']['insert'][0]-x)<400 and 150<q['geometry']['insert'][1]-y<800]
                if len(numbers)!=1:continue
                point=Point((x-s['origin'][0])*.001,(y-s['origin'][1])*.001)
                kind='window' if label.endswith('W') else 'door'
                choices=sorted([(Polygon(q['polygon'],q.get('holes',[])).distance(point),q)
                    for q in elements if q['floor_id']==s['id'] and q['type']==kind],key=lambda q:q[0])
                if not choices or choices[0][0]>1.2 or len(choices)>1 and choices[1][0]-choices[0][0]<.15:continue
                target=choices[0][1]
                target['source'].setdefault('plan_schedule_links',[]).append({
                    'drawing_id':'A10-001~','file':row['file'],'source_sha256':row['sha256'],
                    'cad_ids':[e['id'],numbers[0]['id']],'mark':label+'-'+numbers[0]['geometry']['text'].strip(),
                    'distance_m':choices[0][0],'status':'registered_plan_callout_candidate',
                    'assignment_verified':False,'floor_id':s['id']})
                linked+=1
        report.append({'floor_id':s['id'],'registration_status':'control_geometry_match' if registered else 'insufficient_controls',
                       'controls':controls,'linked_callouts':linked,'member_assignment_verified':False})
    return report


def schedule_catalog(schedule):
    """Deduplicate repeated embedded tables; preserve every original reference."""
    grouped=defaultdict(list)
    for r in schedule['embedded_rows']:
        grouped[(r['kind'],r['mark'],tuple(r['dimensions_m']))].append(r)
    return [{'kind':kind,'mark':mark,'dimensions_m':list(dimensions),
             'references':[{'drawing_id':r['drawing_id'],'source_sha256':r['source_sha256'],'cad_ids':r['cad_ids']} for r in rows],
             'assignment_status':'unassigned_location_scope_revision'}
            for (kind,mark,dimensions),rows in sorted(grouped.items())]


def stair_section_observations(archive,row):
    records=[]
    for e in archive['scene_entities']:
        if e['type'] not in ('TEXT','MTEXT') or e.get('precision_geometry_blocked'):continue
        text=e['geometry'].get('text','')
        match=re.fullmatch(r'\s*\((\d+(?:\.\d+)?)\s*[xX×]\s*(\d+)EA\)\s*',text)
        if match:
            records.append({'value_m':float(match[1])*.001,'count':int(match[2]),'text':text,
                'cad_id':e['id'],'cad_ids':[e['id']],'file':row['file'],'source_sha256':row['sha256'],
                'position_cad':e['geometry']['insert'][:2],'assignment_verified':False})
    return records
