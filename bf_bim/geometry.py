"""Metre-based geometry: legacy route footprints and architectural vertical slices."""
from shapely.geometry import Polygon, MultiPolygon,GeometryCollection
from shapely.ops import unary_union

def opening_footprint(element):
    rings=element.source.get('architectural_opening_polygons')
    return unary_union([Polygon(r) for r in rings]) if rings else Polygon(element.polygon,element.holes)

def architectural_footprint(element):
    profiles=element.source.get('architectural_wall_profiles')
    return unary_union([Polygon(p[0],p[1:]) for p in profiles]) if profiles is not None else Polygon(element.polygon,element.holes)

def footprint(element, elements):
    poly=Polygon(element.polygon, element.holes)
    if element.type == 'wall':
        openings=[Polygon(e.polygon,e.holes) for e in elements
                  if e.type=='door' and e.floor_id==element.floor_id and not e.excluded]
        if openings:
            poly=poly.difference(unary_union(openings))
    return poly

def polygon_parts(geom):
    if isinstance(geom, Polygon):
        return [geom] if not geom.is_empty else []
    if isinstance(geom, MultiPolygon):
        return list(geom.geoms)
    if isinstance(geom,GeometryCollection):
        return [p for g in geom.geoms for p in polygon_parts(g)]
    return []


def solid_parts(element, elements):
    """Architectural geometry: real vertical openings, planar unknowns, assemblies.

    Each tuple is (polygon, relative Z, depth or None). Keep the legacy footprint
    operation unchanged for the preserved navigation module.
    """
    if element.components:
        return [(Polygon(c.polygon,c.holes),element.z_offset+c.z_offset,c.height) for c in element.components]
    poly=architectural_footprint(element)
    if element.type!='wall' or element.height is None:
        return [(p,element.z_offset,element.height) for p in polygon_parts(poly)]
    openings=[]
    for e in elements:
        if e.type not in ('door','window') or e.excluded or e.floor_id!=element.floor_id:continue
        if not opening_footprint(e).intersects(poly):continue
        provisional=e.source.get('provisional_opening',{})
        height=e.height if e.height is not None else provisional.get('height')
        z=e.z_offset+(0 if e.height is not None else provisional.get('z_offset',0))
        if height is not None:openings.append((e,z,height))
    # Preserve original example geometry; refined CAD models require known opening heights.
    if not openings and not element.source.get('geometry_status'):
        return [(p,element.z_offset,element.height) for p in polygon_parts(footprint(element,elements))]
    start,end=element.z_offset,element.z_offset+element.height
    levels=sorted({start,end,*[max(start,min(end,v)) for e,z,h in openings for v in (z,z+h)]})
    result=[]
    for lo,hi in zip(levels,levels[1:]):
        cuts=[opening_footprint(e) for e,z,h in openings if z<=lo and z+h>=hi]
        part=poly.difference(unary_union(cuts)) if cuts else poly
        result.extend((p,lo,hi-lo) for p in polygon_parts(part) if hi-lo>1e-8)
    return result
