"""Evidence-labelled coordination assemblies built on the preserved native rebuild.

Run: python -m bf_bim.precise.rebuild --coordination --sync-web
Never modifies strict-stage results, original drawings, or legacy models.
"""
from collections import Counter, defaultdict
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import math

from shapely import set_precision
from shapely.geometry import Polygon, LineString
from shapely.ops import unary_union, polygonize

from bf_bim.schema import Model
from bf_bim.geometry import polygon_parts
from bf_bim.architectural_assemblies import refine_assemblies, load_parameters
from bf_bim.precision_model import COURTYARD, stair_components
from bf_bim.ifc_export import export_ifc
from bf_bim.validate_ifc import validate_file
from .rebuild import ROOT, OUTPUT as BASE, read, sha256, profile_dict, load_archive, PLAN_ID, AUDIT
from .coordination_quality import host_opening, attach_evidence, audit_relationships, audit_navigation_junctions, verified_model_dict, is_boolean_sliver
from .drawing_links import plan_callouts, schedule_catalog, stair_section_observations
from .window_geometry import constrain_windows, audit_window_profiles
from .window_authoring import recover_plan_frames, window_catalog, apply_window_schedules
from .door_authoring import restore_door_assemblies, door_catalog, apply_door_assemblies, correlate_door_tags
from .wall_recovery import recover_wall_gaps,exact_prism_mesh

OUT=BASE/'coordination-v2'
REASONS={
 'slab_thickness':'Structural slab thickness is not assigned to this plan; coordination depth only.',
 'finish_thickness':'Finish build-up is not assigned; finished-floor reference display only.',
 'door_height':'Door schedule mark is not located; generic opening height.',
 'window_height':'Window schedule/elevation assignment is unresolved; generic glazing height.',
 'window_sill':'Individual sill level is unresolved; generic sill.',
 'frame_width':'Profile specification is not assigned; generic frame and mullion width.',
 'door_leaf_thickness':'Leaf construction is unconfirmed; generic leaf thickness.',
 'glass_thickness':'Glass detail specifications are candidates, not assigned products.',
 'shaft_lining_thickness':'E.V block envelope does not specify shaft lining thickness.',
 'landing_thickness':'Landing section assignment unconfirmed.',
 'stair_support_thickness':'Stair waist/support thickness assignment unconfirmed.',
 'handrail_height':'Rail placement/detail assignment unconfirmed; visual rail only.',
 'handrail_diameter':'Detail assignment unconfirmed; visual rail only.',
 'railing_post_diameter':'Detail assignment unconfirmed; visual rail only.',
 'railing_post_spacing':'Detail assignment unconfirmed; visual rail only.',
}

def save(name,data):
    (OUT/name).write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')

def ids(e):
    s=e.get('source',{})
    return sorted(set(s.get('cad_ids',[])+([s['cad_id']] if s.get('cad_id') else [])))

def solid(poly,role,height,z=0,material='concrete',**source):
    return [{**profile_dict(p),'role':role,'height':height,'z_offset':z,
             'source':{'geometry_status':'provisional','validation_status':'provisional',
                       'dimension_verified':False,'material':material,**source}}
            for p in polygon_parts(set_precision(poly,1e-6)) if p.area>1e-7]

def build(sync_web=False,reviews_path=None):
    OUT.mkdir(parents=True,exist_ok=True)
    protected=[p for folder in [ROOT/'에너지-건축도면',ROOT/'cad_output'] for p in folder.rglob('*')
               if p.is_file() and not p.is_relative_to(OUT)]
    hashes={str(p.relative_to(ROOT)):sha256(p) for p in protected}
    native=read(BASE/'bim.json');preview=read(BASE/'preview.json')
    legacy=read(ROOT/'cad_output/energy-center-model.json')
    cache_hash=sha256(ROOT/'cad_output/energy-center-model.json')
    rows=read(AUDIT/'drawing-index.json')
    archive,row=load_archive(PLAN_ID,rows)
    native_ids={e['id'] for e in archive['scene_entities'] if not e.get('precision_geometry_blocked')}
    native_layers={e['id']:e.get('effective_layer',e.get('layer','')) for e in archive['scene_entities']}
    if legacy['provenance']['floorplan_sha256']!=row['sha256']:
        raise ValueError('Legacy candidate cache belongs to another drawing revision')
    specs={s['id']:s for s in native['floors']};parameters=load_parameters()
    assumptions={k:{'value_m':v,'status':'provisional','reason':REASONS[k]}
                 for k,v in parameters.items() if isinstance(v,(float,int))}
    rejected=[];elements=[];native_member_map={}
    remnant_path=BASE/'wall-remnant-observations.json'
    remnants=read(remnant_path) if remnant_path.exists() else {'elements':[]}
    empty_baseline={e['id']:e for e in remnants['elements']}
    schedule=read(BASE/'schedule-observations.json')
    catalog=schedule_catalog(schedule)
    core_archive,core_row=load_archive('A07-011~',rows)
    section_steps=stair_section_observations(core_archive,core_row)
    del core_archive

    def add(fid,kind,poly,source,name,components=None,status='provisional'):
        if poly.is_empty:return []
        result=[]
        for p in polygon_parts(set_precision(poly,.000001)):
            if p.area<1e-6:continue
            identity='coord-'+hashlib.sha256((fid+kind+str(source.get('cad_ids',[]))+p.normalize().wkt).encode()).hexdigest()[:20]
            part_components=deepcopy(components or [])
            if kind=='wall':
                part_components=[{**c,**profile_dict(q)} for c in part_components
                    for q in polygon_parts(Polygon(c['polygon'],c.get('holes',[])).intersection(p)) if q.area>1e-7]
            e={'id':identity,'name':name,'type':kind,'floor_id':fid,**profile_dict(p),
               'height':None,'verified':False,'z_offset':0,'properties':{},'components':part_components,
               'source':{'file':row['file'],'source_sha256':row['sha256'],'validation_status':status,
                         'geometry_status':'measured_plan' if status=='drawing_based' else 'provisional',
                         'export_status':'coordination_draft','design_assignment_verified':False,**source}}
            elements.append(e);result.append(e)
        return result

    # Keep all 211 observed profiles, render one of each concentric conflicting
    # pair. Selection does not assign a column schedule mark or prove its section.
    col_polys=defaultdict(list);retained_cols=defaultdict(list)
    for m in sorted([m for m in native['members'] if m['kind']=='column'],key=lambda m:-Polygon(m['polygon']).area):
        poly=Polygon(m['polygon'],m['holes']);fid=m['floor_id']
        conflict=any(poly.centroid.distance(p.centroid)<.002 for p in retained_cols[fid])
        height=specs[fid]['height_preview']
        cs=[] if conflict or not height else solid(poly,'column',height,assumption_keys=['storey_envelope'])
        es=add(fid,'column',poly,{'cad_ids':m['cad_ids'],'precision_member_id':m['id'],
             'evidence':m['evidence'],'unknowns':m['unknowns'],
             'property_status':{'position':'drawing_based','section':'unresolved' if conflict else 'drawing_based',
                                'height':'provisional','material':'provisional','member_mark':'unresolved'},
             'material':'concrete','conflicts':m['conflicts'],'section_candidate_suppressed':conflict,
             'assumptions':{'height':{'value_m':height,'reason':'Section storey interval; individual column ends unknown.'}},
             'schedule_candidates':m.get('schedule_candidates',[])},specs[fid]['name']+' · CAD 기둥',cs,'unresolved' if conflict else 'provisional')
        native_member_map[m['id']]=es[0]['id']
        if not conflict:retained_cols[fid].append(poly);col_polys[fid].append(poly)

    # Existing block-based candidates are accepted only with current native CAD
    # identities. Discard prior continuity infill, expanded slabs and roof copies.
    candidates=[]
    for e in legacy['elements']:
        kind=e['type'];src=deepcopy(e['source']);refs=ids(e)
        if kind not in ('wall','window','door','stair','elevator','floor','space','corridor'):continue
        if src.get('marker_width_m'):continue
        if not refs or any(i not in native_ids for i in refs):
            rejected.append({'id':e['id'],'reason':'Missing native CAD identity'});continue
        poly=Polygon(e['polygon'],e.get('holes',[]))
        if not poly.is_valid:raise ValueError('Invalid cached footprint '+e['id'])
        if kind=='floor' and poly.area<5:continue
        for key in list(src):
            if key.startswith(('architectural_','continuity_')) or key in ('host_wall_ids','adjacent_space_ids','provisional_opening'):
                src.pop(key)
        src.update(cad_ids=refs,candidate_cache_id=e['id'],candidate_cache_sha256=cache_hash,
                   material=src.get('material','unknown'),
                   property_status={'position':'drawing_based','section':'provisional','height':'provisional',
                                    'material':'provisional','member_mark':'unresolved'},
                   unknowns=['individual_detail_assignment','material_specification'],
                   assumptions={})
        candidates.append((e,poly,src))

    # Resolve windows and doors first; generic assemblers preserve actual plan
    # axes and measured transverse mullions, with explicit assumed dimensions.
    for old,poly,src in candidates:
        if old['type'] not in ('window','door'):continue
        src['assumptions']={k:v for k,v in assumptions.items() if k in
            (['window_height','window_sill','frame_width','glass_thickness'] if old['type']=='window' else ['door_height','frame_width','door_leaf_thickness'])}
        if old['type']=='window':
            corners=list(poly.minimum_rotated_rectangle.exterior.coords)
            lengths=[LineString([corners[i],corners[i+1]]).length for i in range(4)]
            # Thin or tiny symbol regions cannot represent an assembly.
            if min(lengths)<.012 or max(lengths)<.15:continue
        add(old['floor_id'],old['type'],poly,src,old['name'])
    window_archive,window_row=load_archive('A10-001~',rows)
    frame_geometry=recover_plan_frames(elements,archive,specs)
    door_geometry=restore_door_assemblies(elements,archive,specs)
    callout_report=plan_callouts(archive,window_archive,window_row,list(specs.values()),elements)
    refine_assemblies(elements,parameters)
    window_geometry=constrain_windows(elements,archive['scene_entities'],specs,parameters)
    window_specs=window_catalog(window_archive,window_row)
    window_assignments=apply_window_schedules(elements,window_specs)
    door_specs=door_catalog(window_archive,window_row)
    door_links=correlate_door_tags(elements,window_archive,window_row,specs,door_specs,callout_report)
    door_assignments=apply_door_assemblies(elements,door_specs,parameters)
    del window_archive
    # Retain raw native curves for individual classification of the 44 prior
    # Boolean remainders, not just a comparison against derived model geometry.
    from .rebuild import native_profile
    from .schema import Registration
    empty_refs={i for e in empty_baseline.values() for i in ids(e)}
    raw_wall_evidence={}
    for observed in archive['scene_entities']:
        if observed['id'] not in empty_refs:continue
        for fid,spec in specs.items():
            if any(e['floor_id']==fid and observed['id'] in ids(e) for e in empty_baseline.values()):
                frame=Registration(id=fid+'-remnant',drawing_id=PLAN_ID,origin_cad=tuple(spec['origin']),scale_m_per_unit=.001)
                try:
                    line,_=native_profile(observed,frame)
                    raw_wall_evidence[(fid,observed['id'])]={'cad_id':observed['id'],'points':list(line.coords),
                        'layer':native_layers[observed['id']],'length_m':line.length}
                except (ValueError,KeyError):pass
    portals=defaultdict(list)
    for e in elements:
        if e['type'] not in ('door','window') or not e['components']:continue
        p=Polygon(e['polygon'],e['holes']);op=e['source']['provisional_opening']
        portals[e['floor_id']].append((p,op['z_offset'],op['z_offset']+op['height'],e))

    # Native closed wall loops take priority over inferred face-pair candidates.
    wall_candidates=[]
    for m in native['members']:
        if m['kind']!='wall':continue
        wall_candidates.append((m['floor_id'],Polygon(m['polygon'],m['holes']),
            {'cad_ids':m['cad_ids'],'evidence':m['evidence'],'precision_member_id':m['id'],
             'method':'native closed wall profile','plan_status':'drawing_based','material':'concrete'},'CAD 폐합 벽체'))
    for old,p,src in candidates:
        if old['type']=='wall':wall_candidates.append((old['floor_id'],p,src,old['name']))
    recovered_walls,wall_recovery= recover_wall_gaps(preview['provenance']['cad_traces'],wall_candidates,col_polys,elements)
    wall_candidates.extend(recovered_walls)
    occupied=defaultdict(list);wall_audit=[]
    for fid,p,src,name in wall_candidates:
        h=specs[fid].get('height_preview')
        if not h:continue
        original=p
        cuts=unary_union(col_polys[fid]+occupied[fid])
        p=p.difference(cuts)
        if p.is_empty:continue
        occupied[fid].append(p)
        source={**src,'property_status':{'position':'drawing_based','section':src.get('plan_status','provisional'),
                    'height':'provisional','material':'provisional','structural_role':'unresolved'},
                'wall_class':'exterior_finish' if src.get('material')=='finish' else src.get('envelope_role','wall_role_unresolved'),
                'assumptions':{'height':{'value_m':h,'reason':'Section storey interval; wall top not assigned.'},
                    'face_pairing':{'status':'provisional','reason':'Opposing CAD faces identify candidate wall bands; individual wall semantics unresolved.'}},
                'unknowns':['wall_top','structural_role','finish_assignment'],'assembly_plan_trim_m2':original.area-p.area}
        relevant=[]
        for _,lo,hi,portal in portals[fid]:
            cut=host_opening(p,portal)
            symbol=Polygon(portal['polygon'],portal['holes'])
            if cut is None:
                if symbol.intersection(p).area>1e-7:
                    # Preserve the baseline symbol-only cut where host direction
                    # is unassigned. Never expand it into perpendicular walls.
                    cut=symbol
            elif symbol.intersects(p):
                # Cached symbol rings were rounded to 1 mm while their measured
                # axes retain native floats. Retain both, so a sub-mm jamb edge
                # cannot leave wall behind an already represented opening.
                cut=unary_union([cut,symbol])
            if cut is not None:relevant.append((cut,lo,hi,portal))
        levels=sorted({0,h,*[max(0,min(h,v)) for _,a,b,_ in relevant for v in (a,b)]})
        cs=[]
        for lo,hi in zip(levels,levels[1:]):
            if hi-lo<1e-6:continue
            openings=unary_union([q for q,a,b,_ in relevant if a<(lo+hi)/2<b])
            cs+=solid(p.difference(openings),'wall_body',hi-lo,lo,src.get('material','concrete'),assumption_keys=['storey_envelope'])
        es=add(fid,'wall',p,source,name,cs)
        for cut,_,_,portal in relevant:
            for e in es:
                part=cut.intersection(Polygon(e['polygon'],e['holes']))
                fragments=polygon_parts(part)
                if fragments:
                    hosts=portal['source'].setdefault('host_wall_ids',[])
                    if e['id'] not in hosts:hosts.append(e['id'])
                for fragment in fragments:
                    portal['source'].setdefault('host_openings',[]).append({**profile_dict(fragment),
                        'host_wall_id':e['id'],'method':'parallel_host_depth' if host_opening(Polygon(e['polygon'],e['holes']),portal) is not None else 'baseline_symbol_intersection',
                        'height_assignment':'provisional','design_assignment_verified':False})
        wall_audit.append({'floor':fid,'trim_m2':original.area-p.area,'opening_count':len(relevant)})

    # Stair placement comes from nosings/core outline. Typical CAD/section
    # assemblies retained; non-typical rise rescaled explicitly to section levels.
    voids=defaultdict(list);stairs=[];elevators=[]
    traces=preview['provenance']['cad_traces']
    for old,p,src in candidates:
        fid=old['floor_id'];kind=old['type']
        if kind not in ('stair','elevator'):continue
        h=specs[fid].get('height_preview')
        if not h:continue
        voids[fid].append(p)
        if kind=='stair':
            if fid=='roof':
                src.update(validation_status='unresolved',unresolved_plan_only=True)
                src['property_status']['height']='unresolved'
                src['unknowns'].append('Roof plan may show the downward flight; no upward stair to EL59.90 is located. Do not stretch 24 risers across 5.4 m.')
                es=add(fid,kind,p,src,old['name'],status='unresolved');stairs+=es
                continue
            if old['height'] is not None:
                cs=deepcopy(old['components'])
            else:
                nosings=[]
                for t in traces:
                    if t['floor_id']!=fid or t['kind']!='stair':continue
                    for a,b in zip(t['points'],t['points'][1:]):
                        line=LineString([a,b])
                        if p.buffer(.02).covers(line):nosings.append((line,t['id']))
                # Core outlines/diagonals share A-STAIR. Select the repeated
                # measured nosing length before testing uniform pitch.
                lengths=Counter(round(l.length,2) for l,_ in nosings if 2.5<l.length<3.6)
                if lengths:
                    mode=lengths.most_common(1)[0][0]
                    nosings=[(l,i) for l,i in nosings if abs(l.length-mode)<.01]
                basement_evidence=[r for r in section_steps if r['count']==11 and abs(r['value_m']*22-h)<.002]
                if fid=='b1' and basement_evidence:
                    parts,detail=stair_components(nosings,p,basement_evidence,riser_m=h/22,
                                                 risers_per_flight=11,storey_interval_m=h)
                else:
                    parts,detail=stair_components(nosings,p,[])
                src.update(detail)
                temp={'id':old['id'],'type':'stair','polygon':old['polygon'],'holes':old.get('holes',[]),
                      'height':h if basement_evidence else 4.2,'source':{**src,**detail},'components':parts}
                refine_assemblies([temp],parameters);cs=temp['components']
                factor=1. if basement_evidence else h/4.2
                for c in cs:
                    c['z_offset']*=factor
                    if c['height'] is not None:c['height']*=factor
                    if c.get('mesh'):
                        c['mesh']['vertices']=[[x,y,z*factor] for x,y,z in c['mesh']['vertices']]
                if basement_evidence:
                    src['section_dimension_link']={'status':'plan_count_section_interval_compatible',
                        'references':basement_evidence,'riser_m':h/22,'risers_per_flight':11,
                        'rounded_section_interval_error_m':abs(basement_evidence[0]['value_m']*22-h),
                        'assignment_verified':False,'reason':'11 plan nosings and 177.27 x 11 section candidates agree with 3.9 m interval; core identity/direction unreviewed'}
                    src['assumptions']['flight_section_assignment']={'status':'candidate','reason':'Basement section/plan count compatible; individual section-core identity unresolved.'}
                    src['property_status']['riser']='drawing_compatible_candidate'
                else:
                    src['assumptions']['non_typical_rise']={'value_m':h/24,'reason':'24 riser arrangement is provisional; scale to section interval, not a confirmed basement detail.'}
                    src['assumptions']['vertical_scale']={'factor':factor,'reason':'Prototype vertical scale; unassigned section.',
                        'effective_handrail_height_m':parameters['handrail_height']*factor,'effective_support_thickness_m':parameters['stair_support_thickness']*factor}
            if not cs:
                rejected.append({'id':old['id'],'reason':'No continuous CAD nosing arrangement'});continue
            src['assumptions'].update({k:v for k,v in assumptions.items() if k.startswith(('stair','landing','handrail','railing'))})
            src['assumptions']['flight_direction']={'status':'provisional','reason':'Two opposing CAD flights; ascent direction not confirmed.'}
            es=add(fid,kind,p,src,old['name'],cs);stairs+=es
        else:
            # Empty shaft lining, without an invented cabin or equipment.
            shell=p.difference(p.buffer(-parameters['shaft_lining_thickness'],join_style=2)).difference(unary_union(occupied[fid]+col_polys[fid]))
            relevant=[]
            edges=[LineString([a,b]).buffer(parameters['shaft_lining_thickness'],cap_style=2).intersection(shell)
                   for a,b in zip(p.exterior.coords,list(p.exterior.coords)[1:])]
            for _,lo,hi,portal in portals[fid]:
                cuts=[cut for band in edges for part in polygon_parts(band)
                      if (cut:=host_opening(part,portal)) is not None]
                if cuts:relevant.append((unary_union(cuts),lo,hi,portal))
            levels=sorted({0,h,*[max(0,min(h,v)) for _,a,b,_ in relevant for v in (a,b)]})
            cs=[]
            for lo,hi in zip(levels,levels[1:]):
                openings=unary_union([q for q,a,b,_ in relevant if a<(lo+hi)/2<b])
                cs+=solid(shell.difference(openings),'shaft_lining',hi-lo,lo,
                          assumption_keys=['shaft_lining_thickness','storey_envelope'])
            src['assumptions'].update(shaft_lining_thickness=assumptions['shaft_lining_thickness'],
               height={'value_m':h,'reason':'Section storey interval, upper clearance/PIT unknown.'})
            src['unknowns']+=['entrance_assignment','car','equipment','pit_depth','headroom']
            es=add(fid,kind,p,src,old['name'],cs);elevators+=es

    # Slabs use preserved enclosed-region footprints, never the legacy expanded
    # render components. Re-subtract all protected core and courtyard candidates.
    slabs=[]
    for old,p,src in candidates:
        fid=old['floor_id']
        if old['type'] not in ('floor','space','corridor'):continue
        protected_voids=unary_union(voids[fid]+([COURTYARD] if fid!='b1' else []))
        p=p.difference(protected_voids)
        if old['type']=='floor':
            src['assumptions'].update({k:assumptions[k] for k in ['slab_thickness','finish_thickness']})
            src['assumptions']['boundary_closure']={'value_m':.15,'reason':'Inherited enclosed architectural regions, closure tolerance 150 mm; structural perimeter unconfirmed.'}
            src['property_status']['section']='provisional'
            es=add(fid,'floor',p,src,old['name'])
            refine_assemblies(es,parameters);slabs+=es
        else:add(fid,old['type'],p,src,old['name'],status='provisional')

    roof_report=[]
    for fid in ['roof','phroof']:
        ts=[t for t in traces if t['floor_id']==fid and t['kind']=='roof_trace']
        if fid=='phroof':
            # The full-building lines in the upper plan are lower-roof reference
            # outlines. Never elevate that large mosaic into a whole penthouse.
            ts=[t for t in ts if native_layers.get(t['id'])=='A-ELEV4']
        network=unary_union([set_precision(LineString(t['points']),1e-7) for t in ts])
        all_faces=list(polygonize(network))
        faces=[p for p in all_faces if (10<p.area<100 if fid=='phroof' else p.area>2)]
        if not faces:
            rejected.append({'floor_id':fid,'reason':'No closed roof drawing contour; no 4F copy'});continue
        outline=unary_union(faces).difference(unary_union([COURTYARD,*voids[fid]]))
        src={'cad_ids':sorted({t['id'] for t in ts}),'method':'polygonized own native roof plan traces',
             'material':'roof','property_status':{'position':'drawing_based','section':'provisional','height':'provisional','material':'provisional'},
             'assumptions':{k:assumptions[k] for k in ['slab_thickness','finish_thickness']},
             'unknowns':['individual_roof_level_assignment','slope','penthouse_wall_assignment','parapet_height'],
             'level_assignment_status':'provisional','roof_source_floor':fid}
        if fid=='phroof':
            src['unknowns'].append('A-ELEV4 closed outline function; penthouse versus equipment canopy unresolved')
            src['excluded_reference_outline_areas_m2']=[p.area for p in all_faces if p.area>=100]
        src['assumptions']['roof_level']={'value_m':specs[fid]['elevation'],
            'reason':'Plan title and section EL association; roof slope and split levels unresolved. Upper outline may include canopy, not a confirmed penthouse box.'}
        if fid=='phroof':
            src.update(unresolved_plan_only=True,validation_status='unresolved',
                       geometry_status='measured_plan')
            src['unknowns'].append('Upper candidates do not align with the located roof cores; not extruded.')
        es=add(fid,'roof',outline,src,specs[fid]['name']+' · 자체 도면 경계',status='unresolved' if fid=='phroof' else 'provisional')
        if fid!='phroof':refine_assemblies(es,parameters)
        slabs+=es
        roof_report.append({'floor':fid,'area_m2':outline.area,'source_traces':len(ts),'copied_4f':False})

    # Interpret only uniquely supported, schedule-sized structural girders.
    from .structural_authoring import build_girders, trim_wall_heads
    structural_archive,structural_row=load_archive('S02-001~',rows)
    beams,structural_report=build_girders(elements,specs,archive,structural_archive,structural_row,schedule)
    del archive,structural_archive
    structural_report['wall_head_cuts']=trim_wall_heads(elements,beams,specs)
    elements.extend(beams)

    # Stable component identities and inspectable dimensions/assumptions.
    for e in elements:
        cleaned=[]
        for c in e['components']:
            if c.get('mesh'):
                cleaned.append(c);continue
            geometry=set_precision(Polygon(c['polygon'],c.get('holes',[])),1e-6).simplify(.00001,preserve_topology=True)
            if e['type']=='wall' and geometry.minimum_clearance<.0001:
                original_geometry=geometry
                geometry=geometry.buffer(-.0001,join_style=2).buffer(.0001,join_style=2)
                geometry=set_precision(geometry,1e-6).simplify(.00001,preserve_topology=True)
                removed=original_geometry.difference(geometry)
                if not removed.is_empty:
                    e['source'].setdefault('omitted_boolean_slivers',[]).extend({**profile_dict(q),
                        'area_m2':q.area,'status':'unresolved','reason':'0.1 mm numerical opening removes sub-tolerance neck/spur in overlapping candidate wall bands.'}
                        for q in polygon_parts(removed) if q.area>1e-9)
            for q in polygon_parts(geometry):
                rect=list(q.minimum_rotated_rectangle.exterior.coords)
                width=min(math.dist(rect[i],rect[i+1]) for i in range(4))
                sliver=is_boolean_sliver(q)
                if sliver:
                    e['source'].setdefault('omitted_boolean_slivers',[]).append({**profile_dict(q),
                        'area_m2':q.area,'minimum_clearance_m':q.minimum_clearance,'status':'unresolved',
                        'reason':'Sub-0.1 mm neck left by candidate-band Boolean assembly; OCCT does not preserve this numerical remnant.'})
                if q.area>1e-7 and width>=.0001 and not sliver:
                    cleaned.append({**c,**profile_dict(q)})
        e['components']=cleaned
        if e['source'].get('native_wall_closure'):
            # Use the same final numerical-cleanup profile as every wall. A
            # tessellation must not bypass cleanup or become stale afterwards.
            for c in cleaned:
                c['mesh']=exact_prism_mesh(Polygon(c['polygon'],c['holes']),c['height'])
                c['source']['representation']='exact final-profile prism tessellation; no additional contour smoothing'
        if e['type']=='wall' and not cleaned:
            e['source'].update(validation_status='unresolved',unresolved_plan_only=True,
                unresolved_no_representation=True)
            e['source']['unknowns']=e['source'].get('unknowns',[])+['No renderable wall solid after Boolean sliver cleanup; native traces retained.']
        e['source']['numeric_cleanup']={'grid_m':1e-6,'simplification_m':.00001,'minimum_fragment_width_m':.0001,
            'wall_neck_opening_radius_m':.0001,
            'reason':'Remove sub-OCCT tolerance Boolean slivers; source observation retained in strict stage.'}
        for i,c in enumerate(e['components']):
            c['id']=e['id']+'/component/'+str(i)
            c['source'].update(validation_status='provisional',dimension_verified=False,parent_element_id=e['id'])
        e['source']['applied_dimensions']={'component_height_ranges_m':sorted({round(c['height'],6) for c in e['components'] if c['height'] is not None}),
                                          'storey_interval_m':specs[e['floor_id']].get('height_preview')}
    remnant_audit=[]
    current_by_id={e['id']:e for e in elements}
    legacy_by_id={e['id']:e for e in legacy['elements']}
    for identity,old in empty_baseline.items():
        e=current_by_id.get(identity);footprint=Polygon(old['polygon'],old['holes'])
        parent=legacy_by_id.get(old['source'].get('candidate_cache_id'))
        parent_area=Polygon(parent['polygon'],parent.get('holes',[])).area if parent else None
        effective_width=2*footprint.area/footprint.length
        curves=[raw_wall_evidence[(old['floor_id'],i)] for i in ids(old) if (old['floor_id'],i) in raw_wall_evidence]
        trace_coverage=unary_union([LineString(c['points']) for c in curves])
        source_distance=footprint.distance(trace_coverage) if curves else None
        # These are after priority subtraction, not the original full wall bands.
        # Never expand a tiny remainder back into a wall/column/another wall.
        numerical=bool(parent_area and curves and footprint.area/parent_area<.01 and effective_width<.0002
                       and source_distance<.002)
        classification='overlap_boolean_remnant' if numerical else 'small_source_band_restored' if e and e['components'] else 'unresolved_source_candidate'
        if e:
            e['source']['candidate_classification']=classification
            e['source']['classification_reason']='Sub-0.2 mm residual of source-referenced parent band after column/wall priority subtraction' if numerical else 'Source-referenced corner has a substantial interior despite short CAD edge; retain Draft solid, finish assignment unreviewed' if e['components'] else 'Requires member-specific drawing review'
        remnant_audit.append({'id':identity,'floor_id':old['floor_id'],'cad_ids':ids(old),
            'source_sha256':old['source']['source_sha256'],'classification':classification,
            'residual_area_m2':footprint.area,'effective_width_m':effective_width,'parent_candidate_area_m2':parent_area,
            'source_curve_distance_m':source_distance,'native_curves':curves,
            'solid_restored':bool(e and e['components']),'action':'retain source observation; no fabricated expansion',
            'design_classification_verified':False})
    missing_refs=[{k:r.get(k) for k in ('kind','id','stored_path','exists','contents_extracted')}
                  for r in read(AUDIT/'A04-001~008-audit.json')['external_references'] if not r.get('contents_extracted')]
    missing_by_file={key:missing_refs for key in (row['file'],Path(row['file']).name)}
    review_file=Path(reviews_path) if reviews_path else BASE/'member-reviews.json'
    ledger=read(review_file) if review_file.exists() else {}
    if reviews_path and not review_file.exists():raise FileNotFoundError(review_file)
    if ledger and ledger.get('policy')!='member-evidence/1':raise ValueError('Unknown member review policy')
    reviews=ledger.get('members',{})
    decisions=attach_evidence(elements,list(specs.values()),missing_by_file,reviews)
    relationships=audit_relationships(elements,list(specs.values()),COURTYARD)
    junctions=audit_navigation_junctions(elements,list(specs.values()))
    verified_count=sum(d['eligible'] for d in decisions)
    continuity=[]
    for e in stairs+elevators:
        p=Polygon(e['polygon'],e['holes']);fid=e['floor_id'];h=specs[fid]['height_preview']
        next_floor=next((s for s in specs.values() if abs(s['elevation']-specs[fid]['elevation']-h)<.001 and s['id']!='ph'),None)
        matches=[q for q in stairs+elevators if next_floor and q['type']==e['type'] and q['floor_id']==next_floor['id']
                 and Polygon(q['polygon'],q['holes']).centroid.distance(p.centroid)<.1]
        continuity.append({'id':e['id'],'type':e['type'],'next_floor':next_floor['id'] if next_floor else None,
            'aligned_candidates':[q['id'] for q in matches],'position_status':'aligned' if matches else 'unresolved',
            'expected_storey_top_m':specs[fid]['elevation']+h,
            'landing_top_m':max((specs[fid]['elevation']+c['z_offset']+c['height'] for c in e['components']
                                if c['role']=='landing' and c['height'] is not None),default=None),
            'height_assignment_status':e['source']['property_status']['height'],'direction_verified':False})

    model=Model.model_validate({'id':preview['id'],'name':'에너지융복합종합지원센터 · 통합 3D 검토 Draft',
        'revision':8,'floors':preview['floors'],'elements':elements,'places':legacy['places'],'links':[],
        'warnings':['Coordination Draft: 검증 완료 설계 BIM이 아닙니다. 부재와 속성별 가정을 확인하세요.',
                    '구조 보는 주열·G 부호·기둥 지지점·단면표를 연결한 해석 모델이며 원본 보 외곽·개별 SL 레벨은 미확정입니다. 작은보·미연결 부호는 생성하지 않았습니다.',
                    'PIT·옥탑 외벽·파라펫 상세는 본체/높이 근거 부족으로 미구현입니다.',
                    '상부 지붕은 자체 도면의 경계 후보이며 평지붕 레벨·두께는 가정입니다.',
                    '실·복도 경계 미분류 영역이 남아 전체 내부 공간 분할과 실제 BF 통행 검증은 미완료입니다.'],
        'provenance':{**preview['provenance'],'modelling_version':11,'export_status':'coordination_draft',
             'coordination_draft':True,'assumption_parameters':assumptions,'verified_solids':verified_count,
             'verification_policy':'member-evidence/1',
             'junction_audit':junctions['summary'],
             'ifc_assets':{'draft':'precision-rebuild-coordination-draft.ifc','verified':'precision-rebuild-verified.ifc'},
             'improvements':{'host_openings':len(relationships['host_openings']),
                  'plan_schedule_callouts':sum(r['linked_callouts'] for r in callout_report),
                  'basement_stair_section_link':sum(bool(e['source'].get('section_dimension_link')) for e in elements),
                  'boolean_remnant_review':len(remnant_audit),
                  'bent_window_runs':sum(r['native_segments']>1 for r in window_geometry),
                  'native_window_frames':len(frame_geometry),
                  'dimensioned_window_assignments':len(window_assignments),
                  'native_door_assemblies':len(door_geometry),
                  'merged_duplicate_door_leaves':sum(len(q['superseded_leaf_ids']) for q in door_geometry),
                  'dimensioned_door_assignments':len(door_assignments),
                  'native_wall_gap_profiles':len(wall_recovery),
                  'native_wall_gap_area_m2':sum(r['area_m2'] for r in wall_recovery),
                  'interpreted_structural_girders':len(beams),
                  'structural_wall_head_cuts':len(structural_report['wall_head_cuts'])},
             'candidate_cache_sha256':sha256(ROOT/'cad_output/energy-center-model.json'),
             'strict_stage_sha256':sha256(BASE/'bim.json'),'roof_report':roof_report,
             'preview_policy':'Drawing positions and provisional architectural assemblies; separate verified and Draft IFC.'}})
    from bf_bim.spatial_navigation import build_spatial, OUTPUT as SPATIAL_OUTPUT
    spatial_overrides = SPATIAL_OUTPUT / 'overrides.json'
    model.provenance['bf_spatial'] = build_spatial(model.model_dump(mode='json'),
        read(spatial_overrides) if spatial_overrides.exists() else None)
    save('preview.json',model.model_dump(mode='json'))
    verified=Model.model_validate(verified_model_dict(model))
    save('verified-model.json',verified.model_dump(mode='json'))
    (OUT/'energy-center-Verified.ifc').write_text(export_ifc(verified),encoding='utf-8')
    print('Exporting explicit Coordination Draft IFC',len(elements),'objects',flush=True)
    (OUT/'energy-center-Coordination-Draft.ifc').write_text(export_ifc(model,coordination_draft=True),encoding='utf-8')
    print('Validating Draft IFC EXPRESS / every solid / volume / world coordinates',flush=True)
    checks={'draft_ifc':validate_file(model,OUT/'energy-center-Coordination-Draft.ifc'),
            'verified_ifc':validate_file(verified,OUT/'energy-center-Verified.ifc')}
    void_checks=[]
    for e in slabs:
        p=Polygon(e['polygon'],e['holes']);fid=e['floor_id']
        v=unary_union(voids[fid]+([COURTYARD] if fid!='b1' else []))
        area=p.intersection(v).area
        if area>1e-4:raise AssertionError('Slab fills a protected core/courtyard '+e['id'])
        void_checks.append({'id':e['id'],'protected_void_overlap_m2':area})
    checks.update(slab_openings=void_checks,vertical_candidates=continuity,wall_assembly=wall_audit,
                  certified_design=False,rejected_candidates=rejected,
                  architectural_relationships=relationships,navigation_junctions=junctions,boolean_remnant_review=remnant_audit)
    save('member-validation.json',{'policy':'member-evidence/1','verified_solids':verified_count,'members':decisions})
    save('drawing-links.json',{'schedule_catalog':catalog,'plan_callouts':callout_report,
        'window_catalog':window_specs,'window_assignments':window_assignments,
        'door_catalog':door_specs,'door_assignments':door_assignments,'door_tag_correlations':door_links,
        'stair_section_observations':section_steps,'missing_references':missing_refs,
        'unassigned_reason':'No unambiguous member mark, structural plan position, floor/revision scope combination; no invented beams/slab specification'})
    save('validation.json',checks)
    save('window-geometry-validation.json',{'windows':window_geometry,
        'native_frames':frame_geometry,'schedule_assignments':window_assignments,
        'final_profiles':audit_window_profiles(elements),'design_verified':False})
    save('door-geometry-validation.json',{'native_assemblies':door_geometry,'schedule_assignments':door_assignments,'design_verified':False})
    save('wall-recovery-validation.json',{'recovered':wall_recovery,'design_verified':False})
    save('structural-authoring-validation.json',structural_report)
    summary={'status':'coordination_draft','elements':len(elements),'components':sum(len(e['components']) for e in elements),
        'types':dict(Counter(e['type'] for e in elements)),'floors':dict(Counter(e['floor_id'] for e in elements)),
        'statuses':dict(Counter(e['source']['validation_status'] for e in elements)),'verified_solids':verified_count,
        'improvements':model.provenance['improvements'],
        'boolean_remnant_classifications':dict(Counter(r['classification'] for r in remnant_audit)),
        'native_column_profiles':len(native_member_map),'suppressed_concentric_columns':sum(e['source'].get('section_candidate_suppressed',False) for e in elements),
        'roof_report':roof_report,'ifc':{k:v for k,v in checks.items() if k.endswith('_ifc')},
        'unimplemented':model.warnings[1:],'candidate_source':'Current native identities + preserved enclosed-region/block candidates; no legacy render infill.'}
    save('summary.json',summary)
    changed=[p for p,h in hashes.items() if sha256(ROOT/p)!=h]
    save('preservation.json',{'checked_files':len(hashes),'changed_files':changed,'hashes_before':hashes})
    if changed:raise AssertionError('Protected source changed: '+str(changed))
    if sync_web:
        for src,dst in [('preview.json','precision-rebuild.json'),('energy-center-Verified.ifc','precision-rebuild-verified.ifc'),
                        ('energy-center-Coordination-Draft.ifc','precision-rebuild-coordination-draft.ifc')]:
            shutil.copyfile(OUT/src,ROOT/'web/public/models'/dst)
    print(json.dumps(summary,ensure_ascii=True),flush=True)
    return model
