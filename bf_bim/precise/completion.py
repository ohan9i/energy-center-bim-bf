"""Reproducible, explicitly assumed completion authorised by the user.

Native observations remain intact. Inferred panel boundaries, beam placements,
wall widths and terminal core details are never promoted to drawing approval.
All lengths are model metres; registrations come from the native labelled axes.
"""
from collections import defaultdict
from copy import deepcopy
import hashlib
import math
import re
import statistics

from shapely import voronoi_polygons, set_precision
from shapely.geometry import Polygon, LineString, Point, MultiPoint, box
from shapely.ops import unary_union
from shapely.strtree import STRtree

from bf_bim.geometry import polygon_parts
from bf_bim.precision_model import COURTYARD
from .rebuild import profile_dict
from .structural_authoring import section_matches

AUTHORIZATION = '확인되지 않는 부분은 임의로 정합하게 메워주라'


def profile(item):
    return Polygon(item['polygon'], item.get('holes', []))


def regularized_profiles(poly):
    cleaned=[]
    for p in polygon_parts(set_precision(poly,1e-6)):
        rings=list(p.interiors)
        touching=[Polygon(r) for i,r in enumerate(rings) if LineString(r.coords).distance(p.exterior)<1e-7
                  or any(LineString(r.coords).distance(LineString(s.coords))<1e-7 for j,s in enumerate(rings) if i!=j)]
        if touching:
            # A hole tangent to the shell at one vertex extrudes into a
            # non-manifold vertical edge. Open a recorded 0.1 mm clearance;
            # never seal an unknown opening to make a mesh pass.
            p=set_precision(p.difference(unary_union([h.buffer(.0001,join_style=2) for h in touching])),1e-6)
        cleaned.extend((q,bool(touching)) for q in polygon_parts(p))
    return cleaned


def parts(poly, role, height, z=0, **source):
    cleaned=regularized_profiles(poly)
    return [{**profile_dict(p), 'role': role, 'height': height, 'z_offset': z,
             'source': {'material': 'concrete', 'geometry_status': 'provisional',
                        'dimension_verified': False, 'assumed_completion': True,
                        **({'numeric_hole_clearance_m':.0001} if touching else {}), **source}}
            for p,touching in cleaned if p.area > 1e-5 and not p.buffer(-.0005).is_empty]


def assumed_source(context, reason, **dimensions):
    return {'file': context['file'], 'source_sha256': context['source_sha256'],
            'cad_ids': context.get('cad_ids', []), 'validation_status': 'provisional',
            'geometry_status': 'user_authorised_assumption', 'material': 'concrete',
            'design_assignment_verified': False, 'export_status': 'coordination_draft',
            'user_assumed_completion': {'authorization': AUTHORIZATION, 'reason': reason,
                'context_references_only': True, 'design_verified': False},
            'property_status': {'position': 'provisional', 'section': 'provisional',
                                'height': 'provisional', 'material': 'provisional'},
            'assumptions': {k: {'value_m': v, 'status': 'provisional', 'reason': reason}
                            for k, v in dimensions.items()},
            'unknowns': ['Assumed completion requires drawing or designer review.']}


def new_element(fid, kind, poly, source, name, components):
    poly=set_precision(poly,1e-6).simplify(.00001,preserve_topology=True)
    poly=max(polygon_parts(poly),key=lambda p:p.area)
    identity = 'fill-' + hashlib.sha256((fid + kind + name + poly.normalize().wkt).encode()).hexdigest()[:20]
    return {'id': identity, 'name': name, 'type': kind, 'floor_id': fid,
            **profile_dict(poly), 'height': None, 'z_offset': 0, 'verified': False,
            'excluded': False, 'properties': {}, 'source': source, 'components': components}


def located_tags(structure, registration, fid, family):
    prefix = {'f1': '1', 'f2': '2', 'f3': '3', 'f4': '4', 'roof': 'r'}.get(fid)
    if not prefix:
        return []
    shift = registration['translation_m']
    # The registered footprint provides a sheet-local filter, avoiding schedules
    # and the repeated floor marks on neighbouring sheets.
    return [(e, Point(e['geometry']['insert'][0]*.001+shift[0],
                      e['geometry']['insert'][1]*.001+shift[1]))
            for e in structure['scene_entities'] if e['type'] == 'TEXT'
            and not e.get('precision_geometry_blocked')
            and re.fullmatch(prefix + family + r'\d+[A-Z]?', e['geometry']['text'].strip())
            and -677000 < e['geometry']['insert'][1] < -622000]


def complete_paired_shafts(elements,specs):
    """Split overlapping candidate envelopes without changing their union void.

    The old envelope includes block equipment strokes and is not an assigned
    shaft rectangle. Preserve it as context; use a shared 200 mm partition.
    """
    report=[]
    for fid in ['b1','f1','f2','f3','f4','roof']:
        shafts=sorted([e for e in elements if e['floor_id']==fid and e['type']=='elevator'],key=lambda e:e['id'])
        if len(shafts)!=2:continue
        old=[profile(e) for e in shafts];overlap=old[0].intersection(old[1]).area
        if overlap<1e-6:continue
        union=unary_union(old);centers=[p.centroid for p in old]
        vx=centers[1].x-centers[0].x;vy=centers[1].y-centers[0].y;length=math.hypot(vx,vy)
        vx/=length;vy/=length;nx,ny=-vy,vx;mx=(centers[0].x+centers[1].x)/2;my=(centers[0].y+centers[1].y)/2
        divider=LineString([(mx-nx*100,my-ny*100),(mx+nx*100,my+ny*100)]).buffer(.1,cap_style=2).intersection(union)
        shell=unary_union([union.difference(union.buffer(-.15,join_style=2)),divider])
        blockers=unary_union([profile(e) for e in elements if e['floor_id']==fid and e['type'] in ('wall','column')])
        portals=[e for e in elements if e['floor_id']==fid and e['type'] in ('door','window') and e['components']]
        cells=[]
        for i,e in enumerate(shafts):
            sign=-1 if i==0 else 1
            half=Polygon([(mx+nx*s+vx*t,my+ny*s+vy*t) for s,t in [(-100,0),(100,0),(100,sign*100),(-100,sign*100)]])
            cell=max(polygon_parts(set_precision(union.intersection(half),1e-6)),key=lambda p:p.area).simplify(.00001,preserve_topology=True);cells.append(cell)
            full_lining=shell.intersection(cell)
            lining=full_lining.difference(blockers.buffer(.00001))
            cuts=[];height=specs[fid]['height_preview']
            for p in portals:
                q=profile(p).buffer(.15,join_style=2);op=p['source']['provisional_opening']
                if q.intersection(lining).area>1e-7:cuts.append((q,op['z_offset'],op['z_offset']+op['height']))
            levels=sorted({0,height,*[max(0,min(height,v)) for _,a,b in cuts for v in (a,b)]});cs=[]
            for a,b in zip(levels,levels[1:]):
                if b-a<1e-7:continue
                cs+=parts(lining.difference(unary_union([q for q,x,y in cuts if x<b-1e-8 and y>a+1e-8])), 'shaft_lining',b-a,a)
            e.update(profile_dict(cell));e['components']=cs
            src=e['source'];src['original_block_envelope']=profile_dict(old[i])
            src['user_assumed_completion']={'authorization':AUTHORIZATION,
                'reason':'Overlapping block envelopes split at centre bisector; preserve combined core void and assumed shared wall.',
                'design_verified':False,'context_references_only':True}
            src['assumptions']['shaft_partition']={'value_m':.2,'status':'provisional',
                'reason':'Assumed shared partition; original block envelope is not a shaft wall boundary.'}
            src['assumed_pit_lining_profiles']=[profile_dict(q) for q in polygon_parts(full_lining)]
        report.append({'floor_id':fid,'shaft_ids':[e['id'] for e in shafts],
            'before_parent_overlap_m2':overlap,'after_parent_overlap_m2':cells[0].intersection(cells[1]).area,
            'combined_void_difference_m2':union.symmetric_difference(unary_union(cells)).area,
            'partition_thickness_m':.2,'native_boundary_verified':False})
    return report


def complete_slabs(elements, specs, structure, registrations, schedule):
    report = []
    for fid in ['b1', 'f1', 'f2', 'f3', 'f4', 'roof']:
        slabs = [e for e in elements if e['floor_id'] == fid and e['type'] in ('floor', 'roof') and e['components']]
        if not slabs:
            continue
        original = unary_union([profile(e) for e in slabs])
        supports = unary_union([profile(e) for e in elements if e['floor_id'] == fid
            and e['type'] in ('wall', 'column', 'window') and e['components']
            and profile(e).distance(original) < .3])
        core = unary_union([profile(e) for e in elements if e['floor_id'] == fid
                            and e['type'] in ('stair', 'elevator')] + ([] if fid == 'b1' else [COURTYARD]))
        # Retain every existing hole except a pocket almost entirely occupied by
        # an existing support. This preserves unidentified openings, not just cores.
        holes = unary_union([Polygon(r) for e in slabs for r in profile(e).interiors
                             if Polygon(r).difference(supports).area > Polygon(r).area*.1])
        protected = unary_union([core, holes])
        expanded = unary_union([original, supports.intersection(original.buffer(.3, join_style=2))])
        expanded = expanded.buffer(.12, join_style=2).buffer(-.12, join_style=2).difference(protected)
        added = expanded.difference(original)
        tags = located_tags(structure, registrations[fid], fid, 'S') if fid in registrations else []
        # 1S4 is annotated 1.734 m outside the retained architectural region.
        # Keep that nearby mark as an assumed assignment, with its offset recorded.
        tags = [(e, p) for e, p in tags if original.buffer(3).covers(p)]
        unique = {(round(p.x, 4), round(p.y, 4)): (e, p) for e, p in tags}
        tags = list(unique.values())
        cells = list(voronoi_polygons(MultiPoint([p for _, p in tags]),
            extend_to=box(*expanded.buffer(10).bounds)).geoms) if len(tags) > 1 else [expanded]
        panels = []
        for cell in cells:
            if tags:
                tag, point = min(tags, key=lambda pair: cell.distance(pair[1]))
                mark = tag['geometry']['text'].strip()
                refs = section_matches(mark, schedule, 'slab')
                thickness = refs[0]['dimensions_m'][0] if refs else .2
                evidence = {'mark': mark, 'cad_id': tag['id'], 'tag_xy_m': list(point.coords)[0],
                    'section_references': refs, 'tag_to_original_region_m':original.distance(point),
                    'boundary_method': 'nearest native slab tag Voronoi partition',
                    'boundary_verified': False, 'assignment_verified': False}
            else:
                thickness = .2
                evidence = {'boundary_method': 'existing architectural region',
                            'boundary_verified': False, 'assignment_verified': False}
            p = cell.intersection(expanded)
            if not p.is_empty:
                panels.append((p, thickness, evidence))
        used = Polygon()
        for e in sorted(slabs, key=lambda e: e['id']):
            p = profile(e)
            extension = added.intersection(p.buffer(.3, join_style=2)).difference(used)
            p = unary_union([p, extension]).intersection(expanded)
            used = unary_union([used, extension])
            # Keep a stable parent identity, update both parent and solid profiles.
            # Disconnected extensions are retained as components under this slab.
            parent_parts = polygon_parts(p)
            if not parent_parts:
                continue
            p = max(parent_parts, key=lambda q: q.area)
            p=set_precision(p,1e-6).simplify(.00001,preserve_topology=True)
            e.update(profile_dict(p))
            before = sum(c['height']*profile(c).area for c in e['components'] if c['role'] == 'structural_slab')
            cs = []
            for panel, thickness, evidence in panels:
                cs += parts(panel.intersection(p), 'structural_slab', thickness, -.03-thickness,
                    inferred_panel=evidence)
            cs += parts(p, 'floor_finish', .03, -.03, material='finish')
            e['components'] = cs
            e['source']['user_assumed_completion'] = {'authorization': AUTHORIZATION,
                'reason': 'Support-face seam closure and assumed panel boundaries; native slab perimeter missing.',
                'position_modified': True, 'design_verified': False}
            e['source']['assumptions']['panel_boundaries'] = {'status': 'provisional',
                'reason': 'Voronoi regions of located S marks are assumed boundaries, not recovered beam/panel edges.'}
            e['source']['assumptions']['support_seam_closure'] = {'value_m': .12, 'maximum_extension_m': .3,
                'reason': 'Close small seams toward existing supports while retaining unknown holes and all cores.'}
            report.append({'id': e['id'], 'floor_id': fid, 'added_support_area_m2': p.difference(original).area,
                'original_concrete_volume_m3': before,
                'completed_concrete_volume_m3': sum(profile(c).area*c['height'] for c in cs if c['role']=='structural_slab'),
                'panels': [{'area_m2': profile(c).area, 'thickness_m': c['height'], **c['source']['inferred_panel']}
                           for c in cs if c['role'] == 'structural_slab']})
    return report


def complete_beams(elements, specs, structure, registrations, row, schedule, structural_report):
    new, report, skipped = [], [], []
    for e in elements:
        if e['type']=='beam' and e['source'].get('structural_girder'):
            # Rebuild the section top before subtracting the newly partitioned
            # slab. Otherwise 150 mm panels would leave a 50 mm head gap on 1F.
            for c in e['components']:
                c['height']=-.03-c['z_offset']
            e['source']['assumptions']['slab_underside']={'status':'provisional',
                'reason':'Beam section rebuilt to FL-30, then clipped by current local slab panel solids.'}
    ordered = ['b1', 'f1', 'f2', 'f3', 'f4', 'roof']
    by_cad = {e['id']: e for e in structure['scene_entities']}
    for index, fid in enumerate(ordered[1:], 1):
        if fid not in registrations:
            continue
        base = unary_union([profile(e) for e in elements if e['floor_id']==fid and e['type'] in ('floor','roof')])
        columns = [e for e in elements if e['floor_id']==ordered[index-1] and e['type']=='column' and e['components']]
        col_union = unary_union([profile(e) for e in columns])
        girders = [e for e in elements if e['floor_id']==fid and e['type']=='beam']
        occupied = unary_union([profile(c) for e in girders for c in e['components']])
        core = unary_union([profile(e) for e in elements if e['floor_id']==fid and e['type'] in ('stair','elevator')]+[COURTYARD])
        offsets = defaultdict(list)
        axes = []
        for e in girders:
            g = e['source']['structural_girder']; axis = LineString(g['axis']); axes.append((e['id'], axis))
            tag = by_cad[e['source']['cad_ids'][0]]
            a = math.radians(tag['geometry'].get('rotation_deg', 0)); u = (math.cos(a),math.sin(a))
            shift=registrations[fid]['translation_m']; xy=[tag['geometry']['insert'][k]*.001+shift[k] for k in (0,1)]
            offsets[round(a % math.pi,3)].append((xy[0]-g['axis'][0][0])*(-u[1])+(xy[1]-g['axis'][0][1])*u[0])
        candidates=[]
        # Ambiguous G support pairs may be selected for an assumed model, but
        # remain explicitly different from the 155 uniquely interpreted girders.
        for r in structural_report['unresolved']:
            if r.get('floor_id')!=fid or not r.get('support_candidates') or not r.get('mark','').startswith(('1G','2G','3G','4G','rG')):
                continue
            tag=by_cad[r['cad_id']]; match=min(r['support_candidates'],key=lambda q:q['annotation_offset_m'])
            candidates.append((tag,LineString(match['axis']),match['support_ids'],'nearest candidate column span'))
        for tag, pos in located_tags(structure, registrations[fid], fid, 'B'):
            if not base.buffer(.5).covers(pos):continue
            a=math.radians(tag['geometry'].get('rotation_deg',0));u=(math.cos(a),math.sin(a))
            obs=offsets.get(round(a % math.pi,3),[])
            offset=statistics.median(obs) if obs else .75
            center=Point(pos.x+u[1]*offset,pos.y-u[0]*offset)
            line=LineString([(center.x-u[0]*20,center.y-u[1]*20),(center.x+u[0]*20,center.y+u[1]*20)])
            hits=[]
            for identity,axis in axes:
                hit=line.intersection(axis)
                if hit.geom_type=='Point':hits.append(((hit.x-center.x)*u[0]+(hit.y-center.y)*u[1],hit,identity))
            left=[h for h in hits if h[0]<-.5];right=[h for h in hits if h[0]>.5]
            if not left or not right:
                skipped.append({'floor_id':fid,'cad_id':tag['id'],'reason':'No bracketing modelled girder supports'});continue
            l=max(left,key=lambda h:h[0]);r=min(right,key=lambda h:h[0])
            candidates.append((tag,LineString([l[1],r[1]]),[l[2],r[2]],
                'annotation-offset assumption from same-sheet G tags; bracketing girder intersections'))
        for tag, axis, support_ids, method in candidates:
            mark=tag['geometry']['text'].strip();refs=section_matches(mark,schedule)
            width,depth=refs[0]['dimensions_m'] if refs else [.4,.7]
            if not 2<axis.length<15 or not base.buffer(.35).covers(axis) or axis.intersection(core.buffer(.02)).length>.05:
                skipped.append({'floor_id':fid,'cad_id':tag['id'],'reason':'Span crosses protected void or exceeds support envelope'});continue
            full=axis.buffer(width/2,cap_style=2)
            net=full.difference(unary_union([occupied,col_union,core]))
            if net.area<full.area*.35:continue
            src=assumed_source({'file':row['file'],'source_sha256':row['sha256'],'cad_ids':[tag['id']]},
                method,beam_width=width,beam_depth=depth,concrete_top=-.03)
            src['assumed_beam']={'mark':mark,'axis':list(axis.coords),'support_ids':support_ids,
                'section_references':refs,'section_defaulted':not bool(refs),'span_m':axis.length,
                'registration':registrations[fid],'native_outline_recovered':False}
            cs=parts(net,'assumed_structural_beam',depth,-.03-depth)
            e=new_element(fid,'beam',full,src,specs[fid]['name']+' 추정 보 '+mark,cs)
            new.append(e);occupied=unary_union([occupied,net])
            report.append({'id':e['id'],'floor_id':fid,**src['assumed_beam']})
    elements.extend(new)
    return {'added':report,'skipped':skipped}


def complete_wall_traces(elements, specs, traces):
    report=[]
    for fid in ['b1','f1','f2','f3','f4']:
        es=[e for e in elements if e['floor_id']==fid]
        floor=unary_union([profile(e) for e in es if e['type']=='floor'])
        walls=[e for e in es if e['type']=='wall']
        occupied=unary_union([profile(e) for e in es if e['type'] in ('wall','column','door','window','stair','elevator')])
        clearance=unary_union([profile(e).buffer(.2,join_style=2) for e in es if e['type'] in ('door','window')])
        context=walls[0]['source'] if walls else None
        if not context:continue
        curves=[t for t in traces if t['floor_id']==fid and t['kind']=='wall']
        for t in curves:
            line=LineString(t['points']).difference(occupied.buffer(.025))
            p=line.buffer(.075,cap_style=2,join_style=2).intersection(floor.buffer(.15,join_style=2)).difference(unary_union([occupied,clearance,COURTYARD if fid!='b1' else Polygon()]))
            for q in polygon_parts(p):
                if q.area<.015 or q.buffer(-.015).is_empty:continue
                src=assumed_source({**context,'cad_ids':[t['id']]},
                    'Uncovered native wall-face trace; assumed 150 mm wall band, trimmed around every existing opening/support.',wall_thickness=.15,height=specs[fid]['height_preview'])
                e=new_element(fid,'wall',q,src,specs[fid]['name']+' 추정 벽체 보완',parts(q,'assumed_wall_infill',specs[fid]['height_preview']))
                elements.append(e);occupied=unary_union([occupied,q])
                report.append({'id':e['id'],'floor_id':fid,'area_m2':q.area,'trace_id':t['id']})
    return report


def complete_terminals(elements,specs):
    report=[]
    roof_es=[e for e in elements if e['floor_id']=='roof']
    cores=[e for e in roof_es if e['type'] in ('stair','elevator')]
    if cores:
        core=unary_union([profile(e) for e in cores])
        neighbouring=[profile(e) for e in roof_es if e['type']=='wall' and profile(e).distance(core)<.5]
        cap=unary_union([core,*neighbouring]).convex_hull.buffer(.15,join_style=2).difference(COURTYARD.buffer(.00001))
        cap=max(polygon_parts(cap),key=lambda p:p.area)
        src=assumed_source(cores[0]['source'],
            'Assumed cap aligned to located roof core, using existing 22.2 m upper datum; 600 mm structural/architectural datum conflict unresolved.',slab_thickness=.15,finish_thickness=.03)
        src['roof_source_floor']='phroof';src['context_source_floor']='roof'
        e=new_element('phroof','roof',cap,src,'옥탑 코어 추정 지붕',parts(cap,'structural_slab',.15,-.18)+parts(cap,'roof_finish',.03,-.03,material='roof'))
        elements.append(e);report.append({'id':e['id'],'kind':'roof_core_cap','area_m2':cap.area,'top_m':specs['phroof']['elevation']})
    report.extend(complete_parapets(elements,specs))
    for shaft in [e for e in elements if e['floor_id']=='b1' and e['type']=='elevator']:
        p=profile(shaft)
        lining_profiles=shaft['source'].get('assumed_pit_lining_profiles')
        shell=unary_union([profile(q) for q in lining_profiles]) if lining_profiles else p.difference(p.buffer(-.15,join_style=2))
        rise=specs['b1']['elevation']-specs['pit']['elevation']
        src=assumed_source(shaft['source'],'Assumed PIT termination aligned to basement shaft; depth follows existing PIT datum, equipment/drainage/detail unassigned.',pit_depth=rise,lining_thickness=.15,base_thickness=.2)
        cs=parts(shell,'assumed_pit_lining',rise)+parts(p,'assumed_pit_base',.2,-.2)
        e=new_element('pit','elevator',p,src,'승강기 추정 PIT',cs)
        elements.append(e);report.append({'id':e['id'],'kind':'pit','depth_m':rise,'area_m2':p.area})
    return report


def complete_parapets(elements,specs):
    """Connect the external roof/courtyard edge; internal holes stay unassigned."""
    from .envelope import parapet_band
    roofs=[e for e in elements if e['floor_id']=='roof' and e['type']=='roof' and e['components']]
    if not roofs:return []
    ring=parapet_band(unary_union([profile(e) for e in roofs]),COURTYARD)
    z=specs['roof']['elevation'];height=.9
    # Full parent footprints of stairs/shafts are voids, not opaque obstacles.
    # A 10mm buffer around every parent formerly opened visible parapet seams.
    blockers=[]
    for e in elements:
        if e['type'] not in ('wall','column','elevator'):continue
        for c in e['components']:
            a=specs[e['floor_id']]['elevation']+c['z_offset']
            if a<=z+1e-7 and a+c['height']>=z+height-1e-7:
                blockers.append(profile(c))
    ring=ring.difference(unary_union(blockers))
    report=[]
    for q in polygon_parts(ring):
        cs=parts(q,'assumed_parapet',height)
        if not cs:continue
        src=assumed_source(roofs[0]['source'],
            'Assumed parapet on exterior roof/courtyard boundary only; mosaic holes are not parapet design lines.',
            parapet_height=height,parapet_thickness=.15)
        src['parapet_boundary_policy']='exterior_and_explicit_courtyard'
        e=new_element('roof','wall',q,src,'옥상 추정 파라펫',cs)
        elements.append(e);report.append({'id':e['id'],'kind':'parapet','area_m2':q.area})
    return report


def complete_portal_hosts(elements,specs):
    """Opaque sill/head bands around located windows; never seal the opening."""
    from .coordination_quality import opening_axis
    report=[]
    for fid in ['b1','f1','f2','f3','f4','roof']:
        es=[e for e in elements if e['floor_id']==fid]
        floor=unary_union([profile(e) for e in es if e['type'] in ('floor','roof')])
        blockers=[(profile(c),c['z_offset'],c['z_offset']+c['height'])
            for e in es if e['type'] in ('wall','column','elevator') for c in e['components']]
        portals=[e for e in es if e['type'] in ('window','door') and e['components']]
        # All portal voids also protect against an adjacent band with a different
        # sill/head level. Host masks are deeper than the assembly symbol.
        for e in portals:
            op=e['source']['provisional_opening']
            blockers.append((profile(e).buffer(.2,join_style=2),op['z_offset'],op['z_offset']+op['height']))
        tree=STRtree([p for p,_,_ in blockers]);accepted=[]
        for portal in portals:
            op=portal['source']['provisional_opening'];low=op['z_offset'];high=low+op['height']
            if portal['type']=='door':band=profile(portal)
            else:
                runs=portal['source'].get('window_plan_segments') or [portal]
                bands=[]
                for run in runs:
                    target=portal if run is portal else {'type':'window',**run,'source':{'window_plan_axis':run['axis']}}
                    center,u,width=opening_axis(target)
                    axis=LineString([(center[0]-u[0]*width/2,center[1]-u[1]*width/2),
                                     (center[0]+u[0]*width/2,center[1]+u[1]*width/2)])
                    bands.append(axis.buffer(.075,cap_style=2))
                band=unary_union(bands)
            band=band.intersection(floor.buffer(.3,join_style=2))
            cs=[]
            for bottom,top,role in [(0,low,'assumed_window_sill'),(high,specs[fid]['height_preview'],'assumed_opening_head')]:
                if top-bottom<.001:continue
                cuts=[blockers[i] for i in tree.query(band) if blockers[i][1]<top and blockers[i][2]>bottom]
                cuts.extend((p,a,b) for p,a,b in accepted if a<top and b>bottom and p.intersects(band))
                levels=sorted({bottom,top,*[max(bottom,min(top,v)) for _,a,b in cuts for v in (a,b)]})
                for a,b in zip(levels,levels[1:]):
                    if b-a<1e-7:continue
                    net=band.difference(unary_union([p for p,x,y in cuts if x<b-1e-8 and y>a+1e-8]))
                    for c in parts(net,role,b-a,a):
                        cs.append(c);accepted.append((profile(c),a,b))
            if not cs:continue
            for q in polygon_parts(band):
                qcs=[{**c,**profile_dict(p)} for c in cs for p in polygon_parts(profile(c).intersection(q)) if p.area>1e-5]
                if not qcs:continue
                src=assumed_source(portal['source'],'Assumed opaque sill/head infill around the existing opening; retain original portal geometry and opening levels.',host_thickness=.15)
                src['context_portal_id']=portal['id']
                e=new_element(fid,'wall',q,src,specs[fid]['name']+' 창호 상하부 추정 보완',qcs)
                elements.append(e);report.append({'id':e['id'],'floor_id':fid,'portal_id':portal['id'],
                    'volume_m3':sum(profile(c).area*c['height'] for c in qcs)})
    return report


def trim_solid_junctions(elements,specs, selected_ids=None):
    """Give slabs priority at actual 3D intersections; do not alter plan walls."""
    slabs=[(e,c,profile(c)) for e in elements if e['type'] in ('floor','roof') for c in e['components']]
    tree=STRtree([p for _,_,p in slabs]);report=[]
    for e in elements:
        if selected_ids is not None and e['id'] not in selected_ids:continue
        if e['type'] not in ('wall','column','beam','elevator'):continue
        if e['floor_id']=='pit':continue
        base=specs[e['floor_id']]['elevation'];result=[];volume=0.
        for c in e['components']:
            p=profile(c);lo=base+c['z_offset'];hi=lo+c['height'];cuts=[]
            for i in tree.query(p):
                slab,sc,sp=slabs[i];bottom=specs[slab['floor_id']]['elevation']+sc['z_offset'];top=bottom+sc['height']
                if min(hi,top)-max(lo,bottom)>1e-7 and p.intersection(sp).area>1e-7:
                    cuts.append((max(lo,bottom),min(hi,top),sp,slab['id']))
            if not cuts:result.append(c);continue
            c={k:v for k,v in c.items() if k!='mesh'}
            levels=sorted({lo,hi,*[v for a,b,_,_ in cuts for v in (a,b)]})
            for a,b in zip(levels,levels[1:]):
                if b-a<1e-7:continue
                active=[p for x,y,p,_ in cuts if x<b-1e-8 and y>a+1e-8]
                net=p.difference(unary_union(active));volume+=(p.area-net.area)*(b-a)
                for q in polygon_parts(net):
                    if q.area>1e-7 and b-a>1e-7:
                        result.append({**c,**profile_dict(q),'height':b-a,'z_offset':a-base,
                            'source':{**c['source'],'slab_joint_cuts':sorted({i for x,y,_,i in cuts if x<b and y>a})}})
        if volume>1e-8:
            e['components']=result;e['source']['slab_joint_removed_volume_m3']=volume
            report.append({'id':e['id'],'type':e['type'],'floor_id':e['floor_id'],'removed_duplicate_volume_m3':volume})
    return report


def complete(elements,specs,traces,structure,row,schedule,structural_report):
    registrations={r['floor_id']:r for r in structural_report['registrations']}
    report={'policy':'user-authorised assumed completion/1','authorization':AUTHORIZATION,
            'design_verified':False,'route_calculated':False}
    print('Separating overlapping candidate shaft compartments',flush=True)
    report['shafts']=complete_paired_shafts(elements,specs)
    print('Completing provisional slab panels and support seams',flush=True)
    report['slabs']=complete_slabs(elements,specs,structure,registrations,schedule)
    print('Completing supported provisional beam placements',flush=True)
    report['beams']=complete_beams(elements,specs,structure,registrations,row,schedule,structural_report)
    print('Completing uncovered native wall traces',flush=True)
    report['walls']=complete_wall_traces(elements,specs,traces)
    print('Completing opaque sill/head bands outside portal voids',flush=True)
    report['portal_hosts']=complete_portal_hosts(elements,specs)
    print('Completing provisional roof and PIT terminals',flush=True)
    report['terminals']=complete_terminals(elements,specs)
    print('Subtracting duplicate slab junction volumes',flush=True)
    report['slab_junctions']=trim_solid_junctions(elements,specs)
    from .ceiling_completion import complete_ceilings
    report['ceilings']=complete_ceilings(elements,list(specs.values()))
    return report
