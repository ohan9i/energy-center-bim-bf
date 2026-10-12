"""Recover missing wall returns from closed native wall/column line networks.

No snapping beyond the rebuild's numeric grid, buffering of open lines, or
joining gaps. Only leftover faces with a real interior survive the gate.
"""
from collections import defaultdict, Counter
from shapely.geometry import LineString,Polygon
from shapely.geometry.polygon import orient
from shapely import constrained_delaunay_triangles
from shapely.ops import unary_union
from bf_bim.geometry import polygon_parts
from .rebuild import topological_profiles,profile_dict

def exact_prism_mesh(poly,height):
    """Triangulate the same profile, including holes, without contour repair.

    IFC profile sweeps can drop tiny concave edges at Boolean junctions.
    Explicit shared triangles preserve the final validated polygon in both viewers.
    """
    from bf_bim.schema import SolidMesh
    poly=orient(poly,sign=1)
    vertices=[];lookup={};faces=[]
    boundary_edges=Counter()
    def vertex(x,y,z):
        key=(x,y,z)
        if key not in lookup:lookup[key]=len(vertices);vertices.append(key)
        return lookup[key]
    for triangle in constrained_delaunay_triangles(poly).geoms:
        if not poly.covers(triangle):continue
        coords=list(orient(triangle,sign=1).exterior.coords)[:-1]
        for p,q in zip(coords,coords[1:]+coords[:1]):boundary_edges[(p,q)]+=1
        a,b,c=[vertex(x,y,0.) for x,y in coords];faces.append((a,c,b))
        a,b,c=[vertex(x,y,height) for x,y in coords];faces.append((a,b,c))
    # CDT can omit a redundant collinear ring vertex. Side faces must use
    # exactly the cap's edges, otherwise the cap/side meet in a T junction.
    # This changes tessellation only, never the polygon or its dimensions.
    for ((x,y),(u,v)),count in boundary_edges.items():
        if boundary_edges[((u,v),(x,y))]:continue
        if count!=1:raise ValueError('Non-manifold constrained cap boundary')
        a=vertex(x,y,0.);b=vertex(u,v,0.);c=vertex(u,v,height);d=vertex(x,y,height)
        faces.extend(((a,b,c),(a,c,d)))
    return SolidMesh(vertices=vertices,triangles=faces).model_dump()

def recover_wall_gaps(traces,wall_candidates,columns,portals):
    records=defaultdict(list);wall_ids=defaultdict(set);occupied=defaultdict(list)
    for t in traces:
        if t['kind'] not in ('wall','column'):continue
        records[t['floor_id']].append((LineString(t['points']),t['id']))
        if t['kind']=='wall':wall_ids[t['floor_id']].add(t['id'])
    for fid,p,source,name in wall_candidates:occupied[fid].append(p)
    for fid,ps in columns.items():occupied[fid].extend(ps)
    for e in portals:
        if e['type'] in ('door','window'):occupied[e['floor_id']].append(Polygon(e['polygon'],e['holes']))
    added=[];audit=[]
    for fid,lines in records.items():
        mask=unary_union(occupied[fid])
        for cycle,ids,residual in topological_profiles(lines):
            if not wall_ids[fid].intersection(ids):continue
            gap=cycle.difference(mask)
            for p in polygon_parts(gap):
                if p.area<1e-5:continue
                # Reject numerical slivers. Do not offset the actual accepted
                # profile; the buffer is used only as an interior test.
                if p.buffer(-.01).is_empty:continue
                evidence={'cad_ids':ids,'method':'closed native wall/column network minus existing envelopes',
                    'plan_status':'drawing_correlated','material':'concrete',
                    'native_wall_closure':{'cycle':profile_dict(cycle),'boundary_residual_m':residual,
                        'recovered_area_m2':p.area,'interior_test_m':.01,
                        'design_verified':False,'structural_role':'unresolved'}}
                added.append((fid,p,evidence,'CAD 폐합 접합부 벽체'))
                audit.append({'floor_id':fid,'cad_ids':ids,'area_m2':p.area,'boundary_residual_m':residual,**profile_dict(p)})
    return added,audit
