"""Keep window assemblies on observed faces, including bent CAD blocks.

An enclosing rectangle is an orientation aid, not a glazing boundary. Native
parallel face pairs provide separate straight runs; no gaps are bridged here.
"""
import math

from shapely.geometry import Polygon, LineString
from shapely.ops import unary_union

from bf_bim.architectural_assemblies import refine_assemblies
from bf_bim.geometry import polygon_parts
from bf_bim.project_model import paired_wall_faces
from .geometry import to_local
from .schema import Registration
from .rebuild import profile_dict


def axis(poly):
    corners=list(poly.minimum_rotated_rectangle.exterior.coords)
    i=max(range(4),key=lambda i:math.dist(corners[i],corners[i+1]))
    a,b=corners[i:i+2];width=math.dist(a,b)
    u=[(b[j]-a[j])/width for j in (0,1)]
    return dict(origin=list(poly.centroid.coords[0]),direction=u,width_m=width,
                depth_m=min(math.dist(corners[j],corners[j+1]) for j in range(4)))


def native_segments(element, entities, spec):
    """Recover runs only from this member's source curves in its sheet frame."""
    refs=set(element['source']['cad_ids'])
    frame=Registration(id=spec['id']+'-window',drawing_id='A04-001~008',
                       origin_cad=tuple(spec['origin']),scale_m_per_unit=.001)
    records=[]
    for e in entities:
        if e['id'] not in refs or e.get('precision_geometry_blocked') or e.get('support')!='full':continue
        g=e['geometry']
        segments=[g] if e['type']=='LINE' else [s for s in g.get('segments',[]) if s['type']=='LINE'] if e['type']=='LWPOLYLINE' else []
        for s in segments:
            line=LineString([to_local(s['start'],frame),to_local(s['end'],frame)])
            if line.length>.05:records.append((line,e['id']))
    _,bands,_=paired_wall_faces(records)
    footprint=Polygon(element['polygon'],element.get('holes',[]))
    # Inner glazing/frame faces also form parallel pairs. They are evidence
    # inside an outer run, not eleven separate window assemblies with extra
    # jambs. Remove only fully contained pairs, retaining their native curves
    # below for the measured transverse mullions.
    distinct={p.normalize().wkb_hex:(p,a,b,d) for p,a,b,d in bands}
    kept=[]
    for poly,a,b,d in sorted(distinct.values(),key=lambda band:-band[0].area):
        if any(q.buffer(1e-7).covers(poly) for q,*_ in kept):continue
        kept.append((poly,a,b,d))
    groups=[]
    for poly,a,b,_ in kept:
        # Reject pairs outside the preserved observed candidate. A band is never
        # allowed to establish a new pane across a missing source boundary.
        if poly.difference(footprint.buffer(.002)).area>1e-7:continue
        measured=axis(poly);u=measured['direction'];center=measured['origin']
        group=next((g for g in groups if abs(sum(x*y for x,y in zip(g['axis']['direction'],u)))>1-1e-7
                    and abs((center[0]-g['axis']['origin'][0])*(-u[1])+(center[1]-g['axis']['origin'][1])*u[0])<.002),None)
        if group is None:
            group={'axis':measured,'polys':[],'cad_ids':set()};groups.append(group)
        group['polys'].append(poly);group['cad_ids'].update((a,b))
    result=[]
    for g in groups:
        for p in polygon_parts(unary_union(g['polys'])):
            measured=axis(p);u=measured['direction'];cx,cy=measured['origin'];depth=measured['depth_m'];width=measured['width_m']
            offsets={}
            for line,identifier in records:
                if not depth*.75<=line.length<=depth*1.5:continue
                a,b=line.coords;dot=abs(((b[0]-a[0])*u[0]+(b[1]-a[1])*u[1])/line.length)
                mid=line.interpolate(.5,normalized=True)
                if dot<.05 and p.buffer(.003).covers(mid):
                    s=round((mid.x-cx)*u[0]+(mid.y-cy)*u[1],6)
                    if abs(s)<width/2-.1:offsets.setdefault(s,set()).add(identifier)
            pending=sorted(offsets);divisions=[]
            while pending:
                lo=pending.pop(0);hi=lo
                if pending and pending[0]-lo<=.15 and offsets[lo]&offsets[pending[0]]:hi=pending.pop(0)
                divisions.append({'offset_m':(lo+hi)/2,'span_m':[lo,hi] if hi>lo else None,
                                  'cad_ids':sorted(offsets[lo]|offsets[hi])})
            result.append({**profile_dict(p),'axis':measured,'cad_ids':sorted(g['cad_ids']),
                           'mullion_plan_evidence':divisions,
                           'measured_mullion_offsets_m':[d['offset_m'] for d in divisions],
                           'measured_mullion_spans_m':[d['span_m'] for d in divisions if d['span_m']]})
    if len(result)<2 or footprint.difference(unary_union([Polygon(s['polygon'],s['holes']) for s in result]).buffer(.002)).area>1e-7:
        raise ValueError('Bent window lacks complete native face-pair coverage: '+element['id'])
    return result


def constrain_windows(elements, entities, specs, parameters):
    report=[]
    for e in elements:
        if e['type']!='window' or not e['components']:continue
        p=Polygon(e['polygon'],e.get('holes',[]));src=e['source']
        before=unary_union([Polygon(c['polygon'],c.get('holes',[])) for c in e['components']])
        rect=p.minimum_rotated_rectangle
        bent=p.area/rect.area<.8 and axis(p)['depth_m']>.45
        if bent:
            segments=native_segments(e,entities,specs[e['floor_id']])
            src.pop('window_plan_axis',None)
            src['window_plan_segments']=segments
            src['unknowns'].append('Bent window corner frame and segment schedule assignments')
            components=[];occupied=Polygon()
            for i,s in enumerate(segments):
                part=Polygon(s['polygon'],s['holes']).intersection(p).difference(occupied)
                occupied=unary_union([occupied,part])
                temp={'id':e['id']+'/run/'+str(i),'type':'window','floor_id':e['floor_id'],
                      'polygon':s['polygon'],'holes':s['holes'],
                      'source':{'window_plan_axis':s['axis'],
                                'measured_mullion_offsets_m':s['measured_mullion_offsets_m'],
                                'measured_mullion_spans_m':s['measured_mullion_spans_m']},'components':[]}
                refine_assemblies([temp],parameters)
                for c in temp['components']:
                    for q in polygon_parts(Polygon(c['polygon'],c.get('holes',[])).intersection(part)):
                        if q.area>1e-7:
                            components.append({**c,**profile_dict(q),'source':{**c['source'],
                                'native_segment_index':i,'cad_ids':s['cad_ids']}})
            e['components']=components
        # Also constrain ordinary windows: cached 1 mm outlines and unrounded
        # axes previously produced strips outside the recorded plan footprint.
        e['components']=[{**c,**profile_dict(q)} for c in e['components']
                         for q in polygon_parts(Polygon(c['polygon'],c.get('holes',[])).intersection(p)) if q.area>1e-7]
        after=unary_union([Polygon(c['polygon'],c.get('holes',[])) for c in e['components']])
        record={'element_id':e['id'],'floor_id':e['floor_id'],'native_segments':len(src.get('window_plan_segments',[])),
                'before_outside_footprint_m2':before.difference(p).area,
                'after_outside_footprint_m2':after.difference(p).area,
                'before_footprint_coverage_m2':before.intersection(p).area,
                'after_footprint_coverage_m2':after.intersection(p).area,
                'method':'native_face_pair_runs' if bent else 'recorded_footprint_constraint',
                'design_assignment_verified':False}
        src['plan_geometry_review']=record;report.append(record)
    return report


def audit_window_profiles(elements):
    """Check the final rounded/rendered profiles, not just intermediate cuts."""
    result=[]
    for e in elements:
        if e['type']!='window' or not e['components']:continue
        p=Polygon(e['polygon'],e.get('holes',[]))
        rendered=unary_union([Polygon(c['polygon'],c.get('holes',[])) for c in e['components']])
        outside=rendered.difference(p).area
        if outside>1e-5:raise AssertionError('Window assembly escapes its observed plan: '+e['id'])
        result.append({'element_id':e['id'],'floor_id':e['floor_id'],
                       'outside_footprint_m2':outside,'footprint_coverage_m2':rendered.intersection(p).area,
                       'status':'passed_geometry_only','design_verified':False})
    return result
