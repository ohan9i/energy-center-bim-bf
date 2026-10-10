"""Metre-based geometry: legacy route footprints and architectural vertical slices."""
from shapely.geometry import Polygon, MultiPolygon
from shapely.ops import unary_union

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
    return []


def solid_parts(element, elements):
    """Architectural geometry: real vertical openings, planar unknowns, assemblies.

    Each tuple is (polygon, relative Z, depth or None). Keep the legacy footprint
    operation unchanged for the preserved navigation module.
    """
    if element.components:
        return [(Polygon(c.polygon,c.holes),element.z_offset+c.z_offset,c.height) for c in element.components]
    poly=Polygon(element.polygon,element.holes)
    if element.type!='wall' or element.height is None:
        return [(poly,element.z_offset,element.height)]
    openings=[e for e in elements if e.type in ('door','window') and not e.excluded and
        e.floor_id==element.floor_id and e.height is not None and Polygon(e.polygon,e.holes).intersects(poly)]
    # Preserve original example geometry; refined CAD models require known opening heights.
    if not openings and not element.source.get('geometry_status'):
        return [(p,element.z_offset,element.height) for p in polygon_parts(footprint(element,elements))]
    start,end=element.z_offset,element.z_offset+element.height
    levels=sorted({start,end,*[max(start,min(end,z)) for e in openings for z in (e.z_offset,e.z_offset+e.height)]})
    result=[]
    for lo,hi in zip(levels,levels[1:]):
        cuts=[Polygon(e.polygon,e.holes) for e in openings if e.z_offset<=lo and e.z_offset+e.height>=hi]
        part=poly.difference(unary_union(cuts)) if cuts else poly
        result.extend((p,lo,hi-lo) for p in polygon_parts(part) if hi-lo>1e-8)
    return result
