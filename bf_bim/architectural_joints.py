"""Disjoint structural junction solids, retaining original CAD/route footprints."""
from collections import defaultdict
from shapely.geometry import Polygon
from shapely.ops import unary_union
from shapely import set_precision
from .geometry import polygon_parts,slab_shape


def close_column_face_gaps(slab,columns,protected_voids):
    """Remove small artificial column-surround holes from face-line region closure.

    Never close a courtyard/core void or a hole without an enclosed CAD column.
    This is an explicitly inferred junction repair, not a structural slab survey.
    """
    repairs=[]
    for part in polygon_parts(slab):
        for ring in part.interiors:
            hole=Polygon(ring)
            if hole.area>=2 or hole.intersection(protected_voids).area>1e-6:continue
            if any(hole.buffer(.001).covers(column) for column in columns):repairs.append(hole)
    return unary_union([slab,*repairs]),len(repairs)


def resolve_joints(elements,parameters):
    groups=defaultdict(list)
    for e in elements:groups[e['floor_id']].append(e)
    count=0;removed=0.;trimmed=0;partial=0
    for fid,es in groups.items():
        occupied={}
        slabs_here=unary_union([slab_shape(e) for e in es if e['type'] in ('floor','roof')])
        outline=unary_union([Polygon(g.exterior) for g in polygon_parts(slabs_here)])
        courts=unary_union([Polygon(e['polygon'],e.get('holes',[])) for e in es if e['type']=='opening'])
        perimeter=unary_union([g.boundary for g in polygon_parts(outline)+polygon_parts(courts)])
        for e in es:
            if e['type']=='wall' and not e['source'].get('marker_width_m'):
                p=Polygon(e['polygon'],e.get('holes',[]))
                exterior=e['source'].get('material')=='finish' or not perimeter.is_empty and p.distance(perimeter)<.3
                e['source']['envelope_role']='exterior_candidate' if exterior else 'interior_candidate'
                e['source']['envelope_classification_verified']=False
        columns=[Polygon(e['polygon'],e.get('holes',[])) for e in es if e['type']=='column' and e['height'] is not None]
        column_union=unary_union(columns)
        # Resolve larger measured wall bands first; position markers do not own solids.
        walls=sorted((e for e in es if e['type']=='wall' and not e['source'].get('marker_width_m')),
            key=lambda e:Polygon(e['polygon'],e.get('holes',[])).area,reverse=True)
        for e in walls:
            p=Polygon(e['polygon'],e.get('holes',[]));material=e['source'].get('material','unknown')
            prior=occupied.get(material,Polygon());resolved=p.difference(prior)
            if material!='finish':resolved=resolved.difference(column_union)
            # Boolean intersections can leave sub-mm knife edges in diagonal
            # finish bands. Snap to the same 1 mm CAD reconstruction grid before
            # handing profiles to browser triangulation and the IFC solid kernel.
            resolved=set_precision(resolved,.001)
            occupied[material]=prior.union(p)
            difference=p.area-resolved.area
            if difference>1e-7:
                e['source']['architectural_wall_profiles']=[
                    [list(g.exterior.coords)[:-1],*[list(r.coords)[:-1] for r in g.interiors]] for g in polygon_parts(resolved)]
                e['source']['joint_resolution']='same-material wall overlap removed; known-height columns take precedence; original footprint retained'
                e['source']['joint_removed_plan_area_m2']=difference
                e['source']['joint_precision_grid_m']=.001
                count+=1;removed+=difference
    # Avoid running walls and columns into the next level's provisional slab.
    next_floor={'b1':'f1','f1':'f2','f2':'f3','f3':'f4','f4':'roof'}
    for fid,target in next_floor.items():
        slabs=unary_union([slab_shape(e) for e in groups[target] if e['type'] in ('floor','roof')])
        for e in groups[fid]:
            if e['type'] not in ('wall','column') or e['height'] is None:continue
            p=Polygon(e['polygon'],e.get('holes',[]))
            profiles=e['source'].get('architectural_wall_profiles')
            shape=unary_union([Polygon(q[0],q[1:]) for q in profiles]) if profiles is not None else p
            # A 1 mm guard prevents snapping an outside fragment back into the
            # slab. This is a display boolean tolerance, not a measured width.
            protected=slabs.buffer(.001,join_style=2)
            covered=set_precision(shape.intersection(protected),.001);uncovered=set_precision(shape.difference(protected),.001)
            depth=parameters['slab_thickness']+parameters['finish_thickness']
            if covered.area>1e-8 and e['height']>depth:
                # Separate display / IFC envelopes. Original height and route
                # footprint are never overwritten by a provisional slab depth.
                e['source']['architectural_vertical_profiles']=[
                    dict(polygon=list(g.exterior.coords)[:-1],holes=[list(r.coords)[:-1] for r in g.interiors],
                        z_offset=e.get('z_offset',0),height=height,geometry_status='provisional' if clipped else 'inferred')
                    for geometry,height,clipped in ((covered,e['height']-depth,True),(uncovered,e['height'],False))
                    for g in polygon_parts(geometry) if g.area>1e-8]
                e['source']['joint_vertical_status']='upper slab underside candidate; original element height preserved'
                e['source']['joint_vertical_guard_m']=.001
                trimmed+=1;partial+=int(uncovered.area>1e-8)
    return dict(resolved_wall_junctions=count,removed_duplicate_plan_area_m2=removed,
        members_trimmed_to_provisional_slab=trimmed,partially_covered_members=partial,original_route_footprints_preserved=True,
        original_heights_preserved=True,limitation='Slab depths, finish interfaces and member tops still require detailed section review.')
