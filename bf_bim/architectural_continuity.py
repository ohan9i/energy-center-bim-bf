"""Explicit, reversible architectural closure; CAD/BF footprints stay untouched.

These are review assumptions requested by the user, not recovered design data.
Unlike a screen overlay, the same independently identified parts go to IFC.
"""
from collections import Counter, defaultdict
from shapely import set_precision
from shapely.geometry import Polygon, LineString
from shapely.ops import unary_union
from .geometry import polygon_parts, solid_parts
from .schema import Element


def shape(e):
    return Polygon(e['polygon'], e.get('holes', []))


def rings(p):
    return [list(p.exterior.coords)[:-1], *[list(r.coords)[:-1] for r in p.interiors]]


def browser_profile_valid(p):
    """Check the existing BF/browser segment tolerance without changing it."""
    eps=1e-8
    def cross(a,b,c):return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
    for ring in rings(p):
        edges=list(zip(ring,ring[1:]+ring[:1]))
        for i,(a,b) in enumerate(edges):
            for j in range(i+2,len(edges)):
                if i==0 and j==len(edges)-1:continue
                c,d=edges[j]
                if max(a[0],b[0])+eps<min(c[0],d[0]) or max(c[0],d[0])+eps<min(a[0],b[0]) or max(a[1],b[1])+eps<min(c[1],d[1]) or max(c[1],d[1])+eps<min(a[1],b[1]):continue
                if cross(a,b,c)*cross(a,b,d)<=eps and cross(c,d,a)*cross(c,d,b)<=eps:return False
    return True


def clean_profile(p):
    for tolerance in (.002,.005,.008,.012,.02):
        candidate=p.simplify(tolerance,preserve_topology=True)
        if browser_profile_valid(candidate):return candidate
    return None  # A numerical face sliver is not a new construction component.


def kernel_profiles(p):
    # OCC heals near-coincident edges and can silently drop a long, micrometre
    # wide spur. Remove those spurs in the shared model before either renderer
    # sees them, rather than accepting an IFC/WebGL disagreement.
    if p.minimum_clearance<.0015:
        p=p.buffer(-.0015,join_style=2).buffer(.0015,join_style=2).intersection(p)
    return [clean for part in polygon_parts(p) if (clean:=clean_profile(part)) is not None]


def repair_part(e, poly, role, z, height, material='finish', **evidence):
    for p in [p for part in polygon_parts(poly) for p in kernel_profiles(part)]:
        # Boolean host intersections can create sub-mm slivers. They are neither
        # useful construction detail nor robust browser/IFC profiles.
        if p.area < 2e-5 or 2*p.area/max(p.length,1e-9) < .004 or height <= 1e-6:
            continue
        e['components'].append(dict(role=role, polygon=list(p.exterior.coords)[:-1],
            holes=[list(r.coords)[:-1] for r in p.interiors], z_offset=z, height=height,
            source=dict(geometry_status='provisional', dimension_verified=False,
                material=material, parent_element_id=e['id'],
                method='user-authorized architectural continuity reconstruction',
                repair_verified=False, **evidence)))


def assign_ids(elements):
    for e in elements:
        roles = Counter()
        for c in e['components']:
            c['id'] = f"{e['id']}/component/{c['role']}/{roles[c['role']]}"
            roles[c['role']] += 1


def repair_slabs(elements, parameters):
    groups = defaultdict(list)
    for e in elements:
        groups[e['floor_id']].append(e)
    reports = []
    for fid, es in groups.items():
        owners = [e for e in es if e['type'] in ('floor', 'roof')]
        if not owners:
            continue
        original = unary_union([shape(e) for e in owners])
        voids = unary_union([shape(e) for e in es if e['type'] in ('opening', 'stair', 'elevator')]).buffer(.002, join_style=2)
        # Only near slab faces enter closure. Piloti columns far outside lower
        # storey coverage do not turn into invented rooms or a filled podium.
        near = [shape(e) for e in es if e['type'] in ('wall', 'window', 'column')
            and not e['source'].get('marker_width_m') and shape(e).distance(original) < .85]
        joined = unary_union([original, *near]).buffer(.4, join_style=2).buffer(-.4, join_style=2)
        parts = sorted(polygon_parts(joined), key=lambda p: p.area, reverse=True)
        # Detached face strips are extraction debris, not separate floating slabs.
        candidates = [p for i, p in enumerate(parts) if i == 0 or p.area > 25]
        filled = []
        for p in candidates:
            holes = [r for r in p.interiors if Polygon(r).area > 4 or Polygon(r).intersects(voids)]
            filled.append(Polygon(p.exterior, holes))
        rebuilt = set_precision(unary_union(filled).simplify(.008, preserve_topology=True), .001).difference(voids.buffer(.008,join_style=2))
        final_parts=sorted(polygon_parts(rebuilt),key=lambda p:p.area,reverse=True)
        rebuilt=unary_union([p for i,p in enumerate(final_parts) if i==0 or p.area>25])
        # The disconnected extracted regions are not separate designed slabs.
        # One original owner carries the continuous body; the other CAD/BF IDs
        # stay inspectable with empty architectural coverage, without thin seams.
        ordered = sorted(owners, key=lambda e: shape(e).area, reverse=True)
        allocations = {}
        for e in ordered[1:]:allocations[e['id']]=Polygon()
        allocations[ordered[0]['id']] = rebuilt
        for e in owners:
            profile = allocations[e['id']]
            e['source']['architectural_slab_profiles'] = [rings(p) for p in polygon_parts(profile)]
            e['source']['continuity_repair_status'] = 'provisional closure; original BF footprint retained'
            e['source']['slab_closure_radius_m'] = .4
            e['source']['slab_added_plan_area_m2'] = profile.difference(shape(e)).area
            e['source']['slab_removed_plan_area_m2'] = shape(e).difference(profile).area
            e['components'] = []
            finish, depth = parameters['finish_thickness'], parameters['slab_thickness']
            repair_part(e, profile, 'structural_slab', -depth-finish, depth, 'concrete')
            repair_part(e, profile, 'roof_finish' if e['type'] == 'roof' else 'floor_finish', -finish, finish)
            e['source']['architectural_slab_profiles']=[rings(Polygon(c['polygon'],c['holes'])) for c in e['components'] if c['role']=='structural_slab']
        rebuilt=unary_union([Polygon(p[0],p[1:]) for e in owners for p in e['source']['architectural_slab_profiles']])
        reports.append(dict(floor_id=fid, original_area_m2=original.area, rebuilt_area_m2=rebuilt.area,
            original_parts=len(polygon_parts(original)), rebuilt_parts=len(polygon_parts(rebuilt)),
            protected_void_overlap_m2=rebuilt.intersection(voids).area))
    return reports


def repair_windows(elements, parameters):
    groups = defaultdict(list)
    for e in elements:
        groups[e['floor_id']].append(e)
    repaired = 0
    for fid, es in groups.items():
        walls = [e for e in es if e['type'] == 'wall' and not e['source'].get('marker_width_m')]
        validated = [Element.model_validate(x) for x in es]
        by_id = {x.id:x for x in validated}
        wall_solids = [(p, z, h) for e in walls for p, z, h in solid_parts(by_id[e['id']], validated) if h]
        # Shared occupied levels prevent two neighbouring repairs owning one solid.
        occupied = list(wall_solids)
        floor_shapes = unary_union([Polygon(p[0], p[1:]) for e in es if e['type'] in ('floor', 'roof')
            for p in e['source'].get('architectural_slab_profiles', [])])
        columns = unary_union([shape(e) for e in es if e['type'] == 'column'])
        protected_voids=unary_union([shape(e) for e in es if e['type'] in ('opening','stair','elevator')]).buffer(-.002,join_style=2)
        doors=[(shape(e),e['z_offset'],parameters['door_height']) for e in es if e['type']=='door']
        windows = [e for e in es if e['type'] == 'window' and e['components']]
        for e in windows:
            # Keep actual glazed bays without a nearby wall (curtain walls), but
            # do not manufacture a room under an isolated opened-leaf fragment.
            if shape(e).distance(floor_shapes) > .85:
                e['source']['continuity_review_issue'] = 'isolated CAD window candidate; host/closed position unresolved'
                continue
            axis = e['source'].get('window_plan_axis')
            if axis:
                cx, cy = axis['origin']; ux, uy = axis['direction']; width = axis['width_m']; depth = min(.2, axis['depth_m'])
            else:
                corners = list(shape(e).minimum_rotated_rectangle.exterior.coords)
                i = max(range(4), key=lambda k: LineString([corners[k], corners[k+1]]).length)
                width = LineString([corners[i], corners[i+1]]).length
                ux, uy = (corners[i+1][0]-corners[i][0])/width, (corners[i+1][1]-corners[i][1])/width
                cx, cy = shape(e).centroid.coords[0]
                depth = min(.2, shape(e).area/width)
            nx, ny = -uy, ux
            left, right = -width/2, width/2
            def rectangle(lo, hi, t0, t1):
                return Polygon([(cx+ux*s+nx*t, cy+uy*s+ny*t) for s,t in [(lo,t0),(hi,t0),(hi,t1),(lo,t1)]])
            # A collar reaches parallel host faces, including offsets beyond the
            # old 200 mm host search; limit normal reach to 900 mm, not a room.
            t0, t1 = -max(depth/2, .1), max(depth/2, .1)
            hosts = []
            probe = rectangle(left-.12, right+.12, -.9, .9)
            for w in walls:
                wp = shape(w)
                if not probe.intersects(wp): continue
                c = list(wp.minimum_rotated_rectangle.exterior.coords)
                i = max(range(4), key=lambda k: LineString([c[k],c[k+1]]).length)
                length = LineString([c[i],c[i+1]]).length
                if not length or abs(((c[i+1][0]-c[i][0])*ux+(c[i+1][1]-c[i][1])*uy)/length) < .96: continue
                pts = list(wp.intersection(probe).exterior.coords) if wp.intersection(probe).geom_type == 'Polygon' else []
                ts = [(x-cx)*nx+(y-cy)*ny for x,y in pts]
                if ts:
                    t0=min(t0,min(ts)); t1=max(t1,max(ts)); hosts.append(w['id'])
            full = rectangle(left-.08, right+.08, t0, t1).difference(columns)
            opening = rectangle(left, right, t0-.002, t1+.002)
            if hosts:
                e['source']['architectural_opening_polygons']=[list(opening.exterior.coords)[:-1]]
            frame = rectangle(left, right, -depth/2, depth/2)
            sill = e['source']['provisional_opening']['z_offset']
            head = sill+e['source']['provisional_opening']['height']
            storey = max((w['height'] or 0 for w in walls), default=4.2)
            top = max(head, storey-parameters['slab_thickness']-parameters['finish_thickness'])
            zones = [(0.,sill,'sill_infill',full),(sill,head,'window_reveal',full.difference(opening)),
                (head,top,'head_infill',full)]
            # Side reveals line the opening depth behind/in front of the frame.
            jambs = rectangle(left,left+.045,t0,t1).union(rectangle(right-.045,right,t0,t1)).difference(frame)
            zones.append((sill,head,'depth_reveal',jambs))
            added = 0
            for lo,hi,role,profile in zones:
                if hi-lo < 1e-7: continue
                levels = sorted({lo,hi,*[max(lo,min(hi,v)) for p,z,h in occupied+doors for v in (z,z+h)]})
                for a,b in zip(levels,levels[1:]):
                    taken=unary_union([p for p,z,h in occupied if z <= a+1e-8 and z+h >= b-1e-8])
                    forbidden=unary_union([protected_voids,*[p for p,z,h in doors if z <= a+1e-8 and z+h >= b-1e-8]])
                    patch=set_precision(profile.difference(taken).difference(forbidden),.0001)
                    for piece in polygon_parts(patch):
                        if piece.area<1e-5: continue
                        repair_part(e,piece,role,a,b-a,host_wall_ids=hosts,normal_reach_m=[t0,t1])
                        occupied.append((piece,a,b-a));added+=1
            if added:
                repaired+=1
                e['source']['continuity_repair_status']='window sill/head/depth closure; provisional user-authorized infill'
                e['source']['continuity_host_wall_ids']=hosts
    return repaired


def repair_roof(elements, parameters):
    roofs = [e for e in elements if e['type']=='roof']
    if not roofs: return {}
    primary=max(roofs,key=lambda e:shape(e).area)
    coverage=unary_union([Polygon(p[0],p[1:]) for e in roofs for p in e['source'].get('architectural_slab_profiles',[])])
    shell=coverage.difference(coverage.buffer(-.15,join_style=2))
    repair_part(primary,shell,'parapet',0,.9,assumed_thickness_m=.15,assumed_height_m=.9)
    walls=[e for e in elements if e['floor_id']==primary['floor_id'] and e['type']=='wall' and not e['source'].get('marker_width_m')]
    if not walls:return dict(parapet=True)
    # The measured roof-storey walls enclose one rotated penthouse. A bounding
    # roof cover is explicitly provisional, with no guessed PV/structure layout.
    core=unary_union([shape(w) for w in walls]).convex_hull
    top=max(w['height'] or 0 for w in walls)
    thickness=parameters['slab_thickness']
    repair_part(primary,core,'penthouse_roof',top-thickness,thickness,'concrete',
        host_wall_ids=[w['id'] for w in walls],outline_status='inferred from roof-storey wall envelope')
    for w in walls:
        profiles=w['source'].get('architectural_wall_profiles')
        ps=[Polygon(p[0],p[1:]) for p in profiles] if profiles is not None else [shape(w)]
        w['source']['architectural_vertical_profiles']=[dict(polygon=list(p.exterior.coords)[:-1],
            holes=[list(r.coords)[:-1] for r in p.interiors],z_offset=w['z_offset'],
            height=min(w['height'],top-thickness),geometry_status='provisional') for p in ps]
        w['source']['continuity_repair_status']='provisional penthouse cover underside'
    return dict(parapet=True,penthouse_cover_area_m2=core.area,cover_top_m=top)


def finish_continuity(elements, parameters):
    repair_roles={'sill_infill','head_infill','window_reveal','depth_reveal','parapet','penthouse_roof','glass_middle','glass_upper','transom'}
    for e in elements:
        e['components']=[c for c in e['components'] if c['role'] not in repair_roles]
        for c in e['components']:
            original=c['source'].get('unsplit_glass_range')
            if original:c['z_offset'],c['height']=original
    windows=repair_windows(elements,parameters)
    roof=repair_roof(elements,parameters)
    transoms=refine_window_transoms(elements)
    repair_spaces(elements)
    assign_ids(elements)
    return dict(repaired_window_assemblies=windows,roof=roof,provisional_transoms=transoms,
        status='provisional user-authorized reconstruction; BF footprints unchanged')


def refine_window_transoms(elements):
    count=0
    for e in elements:
        if e['type']!='window' or not e['source'].get('block_name'):continue
        axis=e['source'].get('window_plan_axis')
        if not axis:continue
        ux,uy=axis['direction'];nx,ny=-uy,ux;depth=min(.2,axis['depth_m']);bar=.024
        for glass in list(e['components']):
            if glass['role']!='glass' or not glass['height'] or glass['height']<1.2:continue
            poly=Polygon(glass['polygon'],glass['holes']);cx,cy=poly.centroid.coords[0]
            ss=[(x-cx)*ux+(y-cy)*uy for x,y in poly.exterior.coords];left,right=min(ss),max(ss)
            frame=Polygon([(cx+ux*s+nx*t,cy+uy*s+ny*t) for s,t in [(left,-depth/2),(right,-depth/2),(right,depth/2),(left,depth/2)]])
            z,height=glass['z_offset'],glass['height'];pitch=height/3
            glass['source']['unsplit_glass_range']=[z,height]
            glass['height']=pitch-bar/2
            evidence=dict(detail_reference='에너지융복합커뮤니티센터_조감도_1117.jpg',
                detail_assignment_verified=False,note='Three-row glazing is a visual review assumption; no window schedule dimensions confirmed.')
            repair_part(e,poly,'glass_middle',z+pitch+bar/2,pitch-bar,'glazing',**evidence)
            repair_part(e,poly,'glass_upper',z+2*pitch+bar/2,pitch-bar/2,'glazing',**evidence)
            for at in (z+pitch-bar/2,z+2*pitch-bar/2):
                repair_part(e,frame,'transom',at,bar,'metal',assumed_bar_height_m=bar,**evidence);count+=1
        e['source']['transom_status']='provisional glazing divisions from supplied CG; schedule assignment unverified'
    return count


def repair_spaces(elements):
    for fid in {e['floor_id'] for e in elements}:
        coverage=unary_union([Polygon(p[0],p[1:]) for e in elements if e['floor_id']==fid and e['type'] in ('floor','roof')
            for p in e['source'].get('architectural_slab_profiles',[])])
        for e in elements:
            if e['floor_id']==fid and e['type'] in ('space','corridor'):
                e['source']['architectural_space_profiles']=[rings(p) for p in polygon_parts(shape(e).intersection(coverage))]
                e['source']['space_display_status']='clipped to reconstructed slab surface; BF boundary unchanged'


def main():
    """Reapply closures without reparsing the large DWG cache."""
    import json
    from pathlib import Path
    from .schema import Model
    from .architectural_joints import resolve_joints
    path=Path('cad_output/energy-center-model.json')
    data=json.loads(path.read_text(encoding='utf-8'))
    elements=data['elements'];parameters=data['provenance']['assembly_parameters']
    slabs=repair_slabs(elements,parameters)
    data['provenance']['joint_report']=resolve_joints(elements,parameters)
    report=finish_continuity(elements,parameters);report['slabs']=slabs
    data['provenance']['continuity_report']=report
    data['provenance']['assembly_report']['assemblies']=dict(Counter(e['type'] for e in elements if e['components']))
    data['provenance']['assembly_report']['component_count']=sum(len(e['components']) for e in elements)
    data['provenance']['modelling_version']=5;data['revision']=4
    model=Model.model_validate(data)
    path.write_text(model.model_dump_json(indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
