"""Drawing-constrained host cuts, evidence gates and geometric relationship checks.

Design verification is independent of the BF navigation `verified` checkbox.
No proximity/same-size match is promoted to a design assignment.
"""
from collections import Counter, defaultdict
from copy import deepcopy
import math
import hashlib
import json

from shapely.geometry import Polygon, LineString
from shapely.ops import unary_union
from bf_bim.geometry import polygon_parts


def opening_axis(portal):
    source = portal['source']
    if portal['type'] == 'door':
        a, b = source['hinge'], source['leaf_end']
        width = math.dist(a, b)
        return [(a[0]+b[0])/2, (a[1]+b[1])/2], [(b[0]-a[0])/width, (b[1]-a[1])/width], width
    axis = source.get('window_plan_axis')
    if axis:
        return axis['origin'], axis['direction'], axis['width_m']
    coords = list(Polygon(portal['polygon']).minimum_rotated_rectangle.exterior.coords)
    i = max(range(4), key=lambda i: math.dist(coords[i], coords[i+1]))
    a, b = coords[i:i+2]; width = math.dist(a, b)
    c = Polygon(portal['polygon']).centroid
    return [c.x,c.y], [(b[0]-a[0])/width,(b[1]-a[1])/width], width


def is_boolean_sliver(poly):
    """Small vertex spacing is not the same as an entirely thin solid.

    A real 30 x 15 mm corner can have a 0.096 mm CAD edge. Preserve its
    substantial interior; reject only small fragments whose whole interior is
    thin. Sub-millimetre overlap plates are numerical remainders, not walls.
    This is a numeric rendering filter, never a design verification criterion.
    """
    return poly.area<.005 and poly.minimum_clearance<.001 and poly.buffer(-.001).is_empty


def host_opening(wall, portal, max_host_distance=.2):
    """Preserve symbol span; remove the observed parallel wall's full depth.

    A short symbol footprint cannot cut a deep wall. Conversely the bounding
    rectangle of a large/branched wall must not open unrelated remote walls.
    Only a local parallel wall band touching the symbol neighbourhood qualifies.
    """
    segments=portal['source'].get('window_plan_segments',[])
    if portal['type']=='window' and segments:
        cuts=[cut for s in segments if (cut:=host_opening(wall,
            {**portal,'polygon':s['polygon'],'holes':s['holes'],
             'source':{'window_plan_axis':s['axis']}},max_host_distance)) is not None]
        return unary_union(cuts) if cuts else None
    if wall.geom_type!='Polygon':
        cuts=[cut for part in polygon_parts(wall) if (cut:=host_opening(part,portal,max_host_distance)) is not None]
        return unary_union(cuts) if cuts else None
    symbol = Polygon(portal['polygon'], portal.get('holes', []))
    if wall.distance(symbol) > max_host_distance:
        return None
    center, u, width = opening_axis(portal); nx, ny = -u[1],u[0]
    corners = list(wall.minimum_rotated_rectangle.exterior.coords)
    k = max(range(4), key=lambda i: math.dist(corners[i],corners[i+1]))
    length = math.dist(corners[k],corners[k+1])
    direction = [(corners[k+1][j]-corners[k][j])/length for j in (0,1)]
    if abs(sum(a*b for a,b in zip(direction,u))) < .95:
        return None
    ts = [(x-center[0])*nx+(y-center[1])*ny for x,y in wall.exterior.coords]
    # Long parallel bands can be positioned beside a glazing symbol. Do not
    # infer a hole through a compound wall with unrelated transverse branches.
    if max(ts)-min(ts) > 1.2:
        return None
    t0,t1 = min(ts)-.001,max(ts)+.001
    cut = Polygon([(center[0]+u[0]*s+nx*t,center[1]+u[1]*s+ny*t)
                   for s,t in [(-width/2,t0),(width/2,t0),(width/2,t1),(-width/2,t1)]])
    if cut.intersection(wall).area < 1e-7:
        return None
    return cut


def verification_decision(source, components, geometry_checks):
    """Fail-closed per-property gate; generated preview values never suffice."""
    required = source.get('verification_required_fields',('identity','position','profile','base','top','material','scope','revision'))
    evidence = source.get('property_evidence',{})
    blockers=[]
    for key in required:
        record=evidence.get(key,{})
        references=record.get('references',[])
        if (record.get('status')!='verified' or not references
                or any(not r.get('cad_ids') or len(r.get('source_sha256',''))!=64 for r in references)
                or not record.get('review',{}).get('reviewer')
                or not record.get('review',{}).get('reviewed_at')):
            blockers.append('unverified_'+key)
    if source.get('conflicts'):blockers.append('source_conflict')
    if source.get('missing_references'):blockers.append('missing_reference')
    if source.get('assumptions'):blockers.append('provisional_dimensions')
    if not components or any(c.get('height') is None or c.get('height',0)<=0 for c in components):
        blockers.append('no_complete_solid')
    if any(c.get('source',{}).get('geometry_status')!='verified' for c in components):
        blockers.append('unverified_component_geometry')
    if not geometry_checks or any(v is not True for v in geometry_checks.values()):
        blockers.append('geometry_checks_incomplete')
    return {'eligible':not blockers,'blockers':blockers,'policy':'member-evidence/1',
            'bf_navigation_verified':False}


def geometry_digest(component):
    payload={k:component.get(k) for k in ('polygon','holes','height','z_offset','mesh','role')}
    payload['material']=component.get('source',{}).get('material')
    return hashlib.sha256(json.dumps(payload,sort_keys=True,allow_nan=False,separators=(',',':')).encode()).hexdigest()


def apply_review(e,record):
    """Consume explicit reviews only when source AND every component still match.

    Review records live outside the generator. No record is synthesized by a
    rebuild. Any coordinate/height/mesh change invalidates its geometry approval.
    """
    src=e['source'];results={'review_source_matches':False,'review_geometry_matches':False,'review_checks_passed':False}
    if not record:return results
    if record.get('source_sha256')!=src['source_sha256']:return results
    results['review_source_matches']=True
    approved=record.get('components',{})
    if not e['components'] or set(approved)!=set(c['id'] for c in e['components']):return results
    if any(approved[c['id']].get('geometry_sha256')!=geometry_digest(c) for c in e['components']):return results
    results['review_geometry_matches']=True
    checks=record.get('checks',{})
    required_checks=('cad_plan','section_height','schedule_assignment','junctions','source_coverage')
    results['review_checks_passed']=all(checks.get(k,{}).get('passed') is True
        and checks[k].get('references') and checks[k].get('review',{}).get('reviewer')
        and checks[k].get('review',{}).get('reviewed_at') for k in required_checks)
    if not results['review_checks_passed']:return results
    supplied=record.get('property_evidence',{})
    if not all(supplied.get(k,{}).get('status')=='verified' and supplied[k].get('references')
               and supplied[k].get('review',{}).get('reviewer') and supplied[k].get('review',{}).get('reviewed_at')
               for k in src['verification_required_fields']):return results
    for c in e['components']:
        a=approved[c['id']]
        if not a.get('references') or not a.get('review',{}).get('reviewer') or not a.get('review',{}).get('reviewed_at'):
            results['review_geometry_matches']=False;return results
    # Resolved assumptions/unknowns must be accounted for explicitly by review.
    if set(record.get('resolved_assumptions',[]))!=set(src.get('assumptions',{})):return results
    if set(record.get('resolved_unknowns',[]))!=set(src.get('unknowns',[])):return results
    src['property_evidence'].update(deepcopy(supplied))
    src['prior_assumptions']=src.pop('assumptions',{})
    src['resolved_unknowns']=src.pop('unknowns',[])
    for c in e['components']:
        c['source'].update(geometry_status='verified',validation_status='verified',dimension_verified=True,
                           review=approved[c['id']]['review'],references=approved[c['id']]['references'])
    return results


def attach_evidence(elements, specs, missing_by_file, reviews=None):
    floors={s['id']:s for s in specs}
    decisions=[]
    for e in elements:
        src=e['source'];cad_ids=src.get('cad_ids',[])
        refs=[{'file':src['file'],'source_sha256':src['source_sha256'],'cad_ids':cad_ids,'view':'plan'}]
        profile_status='drawing_based' if src.get('precision_member_id') else 'candidate'
        level_refs=floors[e['floor_id']].get('level_evidence',[])
        src['property_evidence']={
            'identity':{'status':'unresolved','references':refs,'reason':'CAD identity is not a structural/schedule member mark'},
            'position':{'status':'drawing_based','references':refs},
            'profile':{'status':profile_status,'references':refs},
            'base':{'status':'candidate','value_m':floors[e['floor_id']]['elevation'],'references':level_refs,
                    'reason':'Section annotation located; FFL/SSL and individual member base assignment unresolved'},
            'top':{'status':'provisional','references':[]},
            'material':{'status':'provisional','references':[]},
            'scope':{'status':'candidate','value':e['floor_id'],'references':refs},
            'revision':{'status':'unresolved','references':refs},
        }
        if src.get('user_assumed_completion'):
            src.setdefault('property_status',{}).update(position='provisional',section='provisional')
            for key in ('position','profile'):
                src['property_evidence'][key]={'status':'provisional','references':refs,
                    'reason':'User-authorised assumed completion; CAD IDs are context references, not approval of this geometry.'}
            src['property_evidence']['base']['status']='provisional'
        if src.get('plan_schedule_links'):
            src['property_evidence']['member_mark']={'status':'candidate','references':src['plan_schedule_links'],
                'reason':'Registered plan callout candidates; unresolved leader/member and schedule assignment'}
        if src.get('native_frame_evidence'):
            src['property_evidence']['profile']={'status':'drawing_based','references':[src['native_frame_evidence']],
                'reason':'Native closed jamb profiles and covered outer frame boundary'}
        assignment=src.get('schedule_assignment')
        if src.get('native_door_evidence'):
            src['property_evidence']['profile']={'status':'drawing_correlated','references':[src['native_door_evidence']],
                'reason':'Native closed jamb pair; swing symbol is not the door opening axis'}
        door_assignment=src.get('door_schedule_assignment')
        if door_assignment:
            references=door_assignment['references']+src.get('dimensioned_door_plan_links',[])
            src['property_evidence']['member_mark']={'status':'drawing_correlated','value':door_assignment['mark'],
                'references':references,'reason':'Symbol centre, floor scope and native outer width correlation; independent review pending'}
            src['property_evidence']['opening_height']={'status':'drawing_correlated','value_m':door_assignment['height_m'],'references':references}
        if assignment:
            references=assignment['references']+assignment['plan_references']
            src['property_evidence']['member_mark']={'status':'drawing_correlated','references':references,
                'value':assignment['mark'],'reason':'Unique mark, stated floor scope and matching native outer width; independent review pending'}
            src['property_evidence']['sill']={'status':'drawing_correlated','value_m':assignment['sill_m'],
                'references':references,'reason':assignment['sill_reference']}
            src['property_evidence']['head']={'status':'drawing_correlated',
                'value_m':assignment['sill_m']+assignment['height_m'],'references':references}
            src['property_evidence']['opening_height']={'status':'drawing_correlated','value_m':assignment['height_m'],
                'references':references}
            src['property_evidence']['glass_specification']={'status':'drawing_correlated',
                'value_m':assignment['glass_thickness_m'],'references':assignment['references']}
        src['missing_references']=missing_by_file.get(src['file'],[])
        extra={'door':['sill','head','host'],'window':['sill','head','host'],
               'stair':['direction','risers','landing_connection'],'elevator':['entrance','pit','headroom'],
               'floor':['structural_role','openings'],'wall':['structural_role','host_openings'],
               'roof':['slope','structural_role','openings']}.get(e['type'],[])
        src['verification_required_fields']=['identity','position','profile','base','top','material','scope','revision',*extra]
        checks={'valid_profiles':all(Polygon(c['polygon'],c.get('holes',[])).is_valid for c in e['components']),
                'solid_present':bool(e['components']),**apply_review(e,(reviews or {}).get(e['id']))}
        decision=verification_decision(src,e['components'],checks)
        src['verification']=decision
        src['design_assignment_verified']=decision['eligible']
        # Deliberately do not alter Element.verified: it controls BF user review.
        if decision['eligible']:
            src['validation_status']='verified'
        decisions.append({'id':e['id'],'floor_id':e['floor_id'],'type':e['type'],**decision,
                          'properties':src['property_evidence']})
    return decisions


def audit_relationships(elements, specs, courtyard):
    by_floor=defaultdict(list)
    for e in elements:by_floor[e['floor_id']].append(e)
    reports=[];opening_checks=[];contacts=[];alignment=[]
    for fid,es in by_floor.items():
        solids=[(e,c,Polygon(c['polygon'],c.get('holes',[]))) for e in es for c in e['components'] if c['height'] is not None]
        core_void=unary_union([Polygon(e['polygon'],e.get('holes',[])) for e in es if e['type'] in ('stair','elevator')]+([courtyard] if fid!='b1' else []))
        slabs=[(e,c,p) for e,c,p in solids if e['type'] in ('floor','roof')]
        slab_overlap=sum(p.intersection(core_void).area for _,_,p in slabs)
        wall_column_overlap=0.
        columns=[(e,c,p) for e,c,p in solids if e['type']=='column']
        walls=[(e,c,p) for e,c,p in solids if e['type']=='wall']
        for w,c,p in walls:
            for col,cc,cp in columns:
                if max(c['z_offset'],cc['z_offset'])>=min(c['z_offset']+c['height'],cc['z_offset']+cc['height']):continue
                overlap=p.intersection(cp).area
                wall_column_overlap+=overlap
        for portal in [e for e in es if e['type'] in ('window','door') and e['components']]:
            op=portal['source']['provisional_opening'];lo=op['z_offset'];hi=lo+op['height']
            cuts=portal['source'].get('host_openings',[])
            for record in cuts:
                wp=Polygon(record['polygon'],record.get('holes',[]));residual=0.
                for wall,c,p in walls:
                    if wall['id']!=record['host_wall_id']:continue
                    if min(c['z_offset']+c['height'],hi)-max(c['z_offset'],lo)>1e-6:
                        residual+=p.intersection(wp).area
                opening_checks.append({'portal_id':portal['id'],'host_wall_id':record['host_wall_id'],
                    'floor_id':fid,'solid_residual_m2':residual,'status':'passed' if residual<1e-5 else 'failed',
                    'design_opening_verified':False})
        # Contacts are geometric relationships, not structural connection approvals.
        for e in es:
            if e['type'] not in ('wall','column'):continue
            p=Polygon(e['polygon'],e.get('holes',[]))
            base=min((c['z_offset'] for c in e['components'] if c['height'] is not None),default=None)
            for slab,sc,sp in slabs:
                distance=p.distance(sp)
                top=sc['z_offset']+sc['height'];gap=base-top if base is not None else None
                if distance<.002:contacts.append({'a':e['id'],'b':slab['id'],'floor_id':fid,'plan_gap_m':distance,
                    'slab_component_id':sc.get('id'),'slab_role':sc['role'],
                    'member_base_relative_z_m':base,'slab_top_relative_z_m':top,'vertical_gap_m':gap,
                    'relation':'observed_draft_z_contact' if gap is not None and abs(gap)<.002 else 'plan_contact_z_unresolved',
                    'note':'Draft FFL/SSL and finish build-up are unassigned; a structural slab gap is not automatically a defect',
                    'structural_connection_verified':False})
        reports.append({'floor_id':fid,'elements':len(es),'components':sum(len(e['components']) for e in es),
            'slab_protected_void_overlap_m2':slab_overlap,'wall_column_solid_overlap_m2':wall_column_overlap,
            'plan_only_candidates':sum(not e['components'] and e['type'] not in ('space','corridor') for e in es),
            'source_geometry_status':'CAD-derived; independent native CAD plot review outstanding'})
    elevations={s['id']:s['elevation'] for s in specs}
    for fid,es in by_floor.items():
        s=next(s for s in specs if s['id']==fid);h=s.get('height_preview')
        if h is None:continue
        upper=next((key for key,z in elevations.items() if abs(z-elevations[fid]-h)<1e-6 and key!='ph'),None)
        for e in es:
            if e['type'] not in ('column','wall','elevator','stair'):continue
            p=Polygon(e['polygon'],e.get('holes',[]))
            options=[q for q in by_floor.get(upper,[]) if q['type']==e['type']]
            if not options:continue
            closest=min(options,key=lambda q:p.centroid.distance(Polygon(q['polygon']).centroid))
            distance=p.centroid.distance(Polygon(closest['polygon']).centroid)
            alignment.append({'id':e['id'],'next_id':closest['id'],'floor_id':fid,'next_floor':upper,
                'centroid_distance_m':distance,'status':'aligned_candidate' if distance<.002 else 'changed_or_unassigned',
                'note':'Offset or changed wall layout is not automatically a defect'})
    failed=[r for r in opening_checks if r['status']=='failed']
    if failed or any(r['slab_protected_void_overlap_m2']>1e-4 or r['wall_column_solid_overlap_m2']>1e-4 for r in reports):
        bad_floors=[r for r in reports if r['slab_protected_void_overlap_m2']>1e-4 or r['wall_column_solid_overlap_m2']>1e-4]
        raise AssertionError('Coordination topology checks failed: '+json.dumps({'floors':bad_floors,'openings':failed[:5]}))
    return {'floors':reports,'host_openings':opening_checks,'contacts':contacts,'floor_alignment':alignment,
            'status':'passed_geometric_checks','design_verified':False,
            'unverified_checks':['FFL/SSL member junction','curtain-wall design detail','beam location/section assignment',
                                 'independent elevation outline','member-specific section height','PIT/roof level assignment']}


def audit_navigation_junctions(elements, specs):
    """Cover every portal and stair, including candidates with no solid/host.

    A host cut or landing contact is only a geometric observation. Neither
    proves door clear width, stair direction, FFL/SSL assignment or BF passage.
    Add inspectable results without changing any geometry or review flags.
    """
    by_id={e['id']:e for e in elements}
    floors={s['id']:s for s in specs}
    portals=[];stairs=[]
    for e in elements:
        if e['type'] not in ('door','window'):continue
        src=e['source'];hosts=set(src.get('host_wall_ids',[]))
        fragments=src.get('host_openings',[])
        fragment_hosts={r['host_wall_id'] for r in fragments}
        if hosts!=fragment_hosts:
            raise AssertionError('Portal host IDs do not match actual cut fragments: '+e['id'])
        for r in fragments:
            host=by_id.get(r['host_wall_id'])
            if not host or host['type']!='wall' or host['floor_id']!=e['floor_id']:
                raise AssertionError('Portal host type/floor mismatch: '+e['id'])
            cut=Polygon(r['polygon'],r.get('holes',[]))
            if cut.area<=0 or cut.difference(Polygon(host['polygon'],host.get('holes',[]))).area>1e-7:
                raise AssertionError('Opening fragment lies outside its host: '+e['id'])
        record={'element_id':e['id'],'floor_id':e['floor_id'],'kind':e['type'],
                'host_wall_ids':sorted(hosts),'cut_fragments':len(fragments),
                'status':'observed_host_cut' if hosts else 'unresolved_no_wall_host',
                'opening_height_status':'provisional' if src.get('provisional_opening') else 'unresolved',
                'design_connection_verified':False,'bf_passage_verified':False}
        src['connection_review']=record;portals.append(record)
    for e in elements:
        if e['type']!='stair':continue
        fid=e['floor_id'];f=floors[fid];h=f.get('height_preview')
        upper=next((s for s in specs if h is not None and s['id']!='ph'
                    and abs(s['elevation']-f['elevation']-h)<1e-6),None)
        landings=[c for c in e['components'] if c['role']=='landing' and c['height'] is not None]
        top=max((c['z_offset']+c['height'] for c in landings),default=None)
        upper_landings=unary_union([Polygon(c['polygon'],c.get('holes',[])) for c in landings
                                   if abs(c['z_offset']+c['height']-top)<1e-6])
        slabs=unary_union([Polygon(q['polygon'],q.get('holes',[])) for q in elements
                          if upper and q['floor_id']==upper['id'] and q['type'] in ('floor','roof')])
        gap=upper_landings.distance(slabs) if not upper_landings.is_empty and not slabs.is_empty else None
        dz=f['elevation']+top-upper['elevation'] if top is not None and upper else None
        record={'element_id':e['id'],'floor_id':fid,'kind':'stair',
                'next_floor_id':upper['id'] if upper else None,
                'upper_landing_elevation_m':f['elevation']+top if top is not None else None,
                'level_difference_m':dz,'plan_gap_to_upper_slab_m':gap,
                'comparison_tolerance_m':.002,
                'status':'observed_near_contact' if gap is not None and gap<=.002 and abs(dz)<=1e-6
                         else 'unresolved_connection',
                'design_connection_verified':False,'bf_passage_verified':False}
        e['source']['connection_review']=record;stairs.append(record)
    summary={'policy':'drawing-junction-observation/1','portals_checked':len(portals),
             'portals_with_wall_host':sum(bool(r['host_wall_ids']) for r in portals),
             'portals_without_wall_host':sum(not r['host_wall_ids'] for r in portals),
             'stairs_checked':len(stairs),'landing_contacts_observed':sum(r['status']=='observed_near_contact' for r in stairs),
             'design_connection_verified':False,'bf_passage_verified':False}
    return {'summary':summary,'portals':portals,'stairs':stairs}


def verified_model_dict(model):
    """Export ONLY members passing the gate, without changing BF review flags."""
    data=deepcopy(model.model_dump(mode='json'))
    data['id']='energy-center-precision-verified'
    data['name']='에너지센터 · 근거 검증 IFC'
    data['elements']=[e for e in data['elements'] if e['source'].get('verification',{}).get('eligible') is True]
    data['places']=[];data['links']=[]
    data['provenance']={'verified_solids':len(data['elements']),'verification_policy':'member-evidence/1',
                        'excluded_draft_elements':len(model.elements)-len(data['elements'])}
    data['warnings']=[] if data['elements'] else ['No members meet complete drawing evidence gate; spatial hierarchy only']
    return data
