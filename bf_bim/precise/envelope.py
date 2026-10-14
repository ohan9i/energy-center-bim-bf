"""Local facade opening projection, preserving the measured along-wall span.

These are coordination operations, not new opening dimensions or approvals.
"""
from shapely.geometry import Polygon
from shapely.ops import unary_union
from .coordination_quality import opening_axis


def opening_projection(portal, depth=.8):
    """Sweep each opening only across wall depth, never along its width.

    A radial buffer increases width by twice its radius and removes the jambs.
    Separate runs are essential for L-shaped glazing: its bounding rectangle
    would erase the corner and a large unrelated section of facade.
    """
    segments = portal['source'].get('window_plan_segments', []) if portal['type'] == 'window' else []
    targets = [{**portal, 'polygon': s['polygon'], 'holes': s.get('holes', []),
                'source': {'window_plan_axis': s['axis']}} for s in segments] or [portal]
    cuts = []
    for target in targets:
        center, u, width = opening_axis(target)
        n = (-u[1], u[0])
        symbol = Polygon(target['polygon'], target.get('holes', []))
        offsets = [(x-center[0])*n[0] + (y-center[1])*n[1] for x, y in symbol.exterior.coords]
        # Older CAD symbol footprints were rounded to 1mm, while the recovered
        # frame axis retains native floats. Keep that symbol too: a sub-mm edge
        # must not leave an opaque sliver inside the retained portal footprint.
        cuts.append(symbol)
        cuts.append(Polygon([(center[0]+u[0]*s+n[0]*t, center[1]+u[1]*s+n[1]*t)
                             for s, t in [(-width/2, min(offsets)-depth),
                                          (width/2, min(offsets)-depth),
                                          (width/2, max(offsets)+depth),
                                          (-width/2, max(offsets)+depth)]]))
    return unary_union(cuts)


def parapet_band(roof, courtyard, thickness=.15):
    """Use outside roof rings and the explicit courtyard, not mosaic holes."""
    from bf_bim.geometry import polygon_parts
    outer = unary_union([Polygon(p.exterior) for p in polygon_parts(roof)])
    edge = outer.difference(outer.buffer(-thickness, join_style=2))
    court_edge = courtyard.buffer(thickness, join_style=2).difference(courtyard)
    return unary_union([edge, court_edge]).intersection(roof)
