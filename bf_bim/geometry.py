"""XY in metres, Z in metres; door footprints cut the wall footprint at all heights.
This simplified open-top geometry matches the browser. No lintel is modelled.
"""
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
