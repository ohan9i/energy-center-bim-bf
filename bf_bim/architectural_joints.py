"""Disjoint structural junction solids, retaining original CAD/route footprints."""
from collections import defaultdict
from shapely.geometry import Polygon
from shapely.ops import unary_union
from shapely import set_precision
from .geometry import polygon_parts


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
    count=0;removed=0.;trimmed=0
    for fid,es in groups.items():
        occupied={}
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
        slabs=unary_union([Polygon(e['polygon'],e.get('holes',[])) for e in groups[target] if e['type'] in ('floor','roof')])
        for e in groups[fid]:
            if e['type'] not in ('wall','column') or e['height'] is None:continue
            p=Polygon(e['polygon'],e.get('holes',[]))
            # Trim only when the next slab covers the entire member section.
            if slabs.buffer(.002).covers(p):
                e['source']['untrimmed_storey_height_m']=e['height']
                e['height']-=parameters['slab_thickness']+parameters['finish_thickness']
                e['source']['height_source']='provisional upper-slab underside; original storey interval retained separately'
                trimmed+=1
    return dict(resolved_wall_junctions=count,removed_duplicate_plan_area_m2=removed,
        members_trimmed_to_provisional_slab=trimmed,original_route_footprints_preserved=True,
        limitation='Finish interfaces and partially covered upper-slab intersections still need detailed section review.')
