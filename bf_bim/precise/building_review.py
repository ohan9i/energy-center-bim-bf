"""Whole-building XYZ coordination checks and unresolved contact records.

Prismatic checks exclude sloped stair meshes. Landing plates are prismatic;
stair flight geometry is inspected separately in actual mesh sections.
No check in this module grants design or navigation approval.
"""
from collections import Counter
from shapely.geometry import Polygon
from shapely.ops import unary_union
from shapely.strtree import STRtree
from bf_bim.geometry import polygon_parts
from bf_bim.precision_model import COURTYARD
from .envelope import opening_projection, parapet_band


def profile(c):
    return Polygon(c['polygon'], c.get('holes', []))


def audit_building(elements, specs):
    elevations = {s['id']: s['elevation'] for s in specs}
    solids = [(e, c, profile(c), elevations[e['floor_id']]+e.get('z_offset', 0)+c['z_offset'])
              for e in elements for c in e['components'] if c.get('height')]
    slabs = [(e, c, p, z) for e, c, p, z in solids if e['type'] in ('floor', 'roof')]
    slab_tree = STRtree([p for _, _, p, _ in slabs])
    clashes = []
    for e, c, p, z in solids:
        if e['type'] not in ('wall', 'column', 'beam', 'elevator') or e['floor_id'] == 'pit':
            continue
        for i in slab_tree.query(p):
            slab, sc, sp, sz = slabs[i]
            rise = min(z+c['height'], sz+sc['height'])-max(z, sz)
            if rise <= 1e-7:
                continue
            volume = p.intersection(sp).area*rise
            if volume > 1e-8:
                clashes.append({'element_id': e['id'], 'component_id': c.get('id'),
                                'slab_id': slab['id'], 'volume_m3': volume,
                                'role': c['role'], 'floor_id': e['floor_id']})

    openings = []
    boundaries={fid:unary_union([Polygon(p.exterior) for p in polygon_parts(unary_union(
        [p for e, _, p, _ in slabs if e['floor_id']==fid]))]).boundary for fid in elevations}
    opaque = [(e, c, p, z) for e, c, p, z in solids
              if c['role'].startswith('photo_') and e['type'] == 'wall']
    tree = STRtree([p for _, _, p, _ in opaque])
    for portal in elements:
        if portal['type'] not in ('door', 'window') or not portal['components']:
            continue
        # An interior door 0.64m behind the facade must not create an external
        # opening simply because its normal projection extends across that face.
        if profile(portal).distance(boundaries[portal['floor_id']])>.55:
            continue
        cut = opening_projection(portal)
        op = portal['source']['provisional_opening']
        lo = elevations[portal['floor_id']]+op['z_offset']
        hi = lo+op['height']
        residual = 0.
        for i in tree.query(cut):
            e, c, p, z = opaque[i]
            if e['floor_id'] != portal['floor_id']:
                continue
            h = min(hi, z+c['height'])-max(lo, z)
            if h > 1e-7:
                residual += cut.intersection(p).area*h
        openings.append({'id': portal['id'], 'floor_id': portal['floor_id'],
                         'opaque_residual_volume_m3': residual})

    # Missing skin outside measured opening spans. A local consistency check;
    # this does not establish that the architectural slab outline is the facade.
    skin_gaps = []
    for fid in ('f1', 'f2', 'f3', 'f4'):
        floor = unary_union([p for e, c, p, _ in slabs if e['floor_id'] == fid])
        outer = unary_union([Polygon(p.exterior) for p in polygon_parts(floor)])
        skin = outer.buffer(.06, join_style=2).difference(outer.buffer(.002, join_style=2))
        columns = unary_union([p.buffer(.001, join_style=2) for e, c, p, _ in solids
                               if e['floor_id'] == fid and e['type'] == 'column'])
        skin = skin.difference(columns)
        portals = [e for e in elements if e['floor_id'] == fid and e['type'] in ('door', 'window')
                   and e['components'] and profile(e).distance(outer.boundary) <= .55]
        cuts = [(e['source']['provisional_opening']['z_offset'],
                 e['source']['provisional_opening']['z_offset']+e['source']['provisional_opening']['height'],
                 opening_projection(e)) for e in portals]
        actual = [(c, p) for e, c, p, _ in opaque if e['floor_id'] == fid and c['role'] == 'photo_exterior_cladding']
        h = next(s['height_preview'] for s in specs if s['id'] == fid)
        levels = sorted({0., h, *[max(0., min(h, v)) for a, b, _ in cuts for v in (a, b)],
                         *[max(0., min(h, v)) for c, _ in actual for v in (c['z_offset'], c['z_offset']+c['height'])],
                         *[max(0., min(h, v-elevations[fid])) for _, sc, _, sz in slabs for v in (sz, sz+sc['height'])]})
        missing = 0.
        for a, b in zip(levels, levels[1:]):
            if b-a < 1e-7:
                continue
            mid = (a+b)/2
            desired = skin.difference(unary_union([p for x, y, p in cuts if x < mid < y]))
            desired = desired.difference(unary_union([p for _, c, p, z in slabs
                if z < elevations[fid]+mid < z+c['height']]))
            shown = unary_union([p for c, p in actual if c['z_offset'] < mid < c['z_offset']+c['height']])
            missing += desired.difference(shown.buffer(.000002, join_style=2)).area*(b-a)
        skin_gaps.append({'floor_id': fid, 'unexplained_missing_skin_volume_m3': missing,
                          'interpretation': 'current perimeter consistency; not a measured facade volume'})

    roof = unary_union([p for e, c, p, _ in slabs if e['floor_id'] == 'roof'])
    target = parapet_band(roof, COURTYARD)
    paras = [(e, c, p, z) for e, c, p, z in solids if c['role'] == 'assumed_parapet']
    misplaced = sum(p.difference(target.buffer(.000002, join_style=2)).area*c['height'] for _, c, p, _ in paras)

    stairs = []
    for e in elements:
        if e['type'] != 'stair' or not e['components']:
            continue
        fz = elevations[e['floor_id']]
        h = next(s.get('height_preview') for s in specs if s['id'] == e['floor_id'])
        upper = next((s for s in specs if h and abs(s['elevation']-fz-h) < .001 and s['id'] != 'ph'), None)
        landings = [c for c in e['components'] if c['role'] == 'landing']
        if not landings or not upper:
            continue
        top = max(c['z_offset']+c['height'] for c in landings)
        p = unary_union([profile(c) for c in landings if abs(c['z_offset']+c['height']-top) < .001])
        floor = unary_union([sp for se, _, sp, _ in slabs if se['floor_id'] == upper['id']])
        gap = p.distance(floor) if not floor.is_empty else None
        stairs.append({'id': e['id'], 'from_floor': e['floor_id'], 'to_floor': upper['id'],
                       'landing_level_gap_m': fz+top-upper['elevation'], 'landing_plan_gap_m': gap,
                       'geometric_contact': gap is not None and gap < .002 and abs(fz+top-upper['elevation']) < .002,
                       'direction_verified': False, 'navigation_approved': False})
    return {'policy': 'building-xyz-review/1', 'design_verified': False,
            'slab_clashes': clashes, 'portal_checks': openings, 'facade_gaps': skin_gaps,
            'parapet_outside_boundary_volume_m3': misplaced, 'stair_contacts': stairs,
            'summary': {'slab_duplicate_volume_m3': sum(r['volume_m3'] for r in clashes),
                        'maximum_slab_pair_volume_m3': max((r['volume_m3'] for r in clashes), default=0.),
                        'slab_clashes_by_role': dict(Counter(r['role'] for r in clashes)),
                        'maximum_opaque_opening_residual_m3': max((r['opaque_residual_volume_m3'] for r in openings), default=0.),
                        'facade_missing_volume_m3': sum(r['unexplained_missing_skin_volume_m3'] for r in skin_gaps),
                        'parapet_outside_boundary_volume_m3': misplaced,
                        'stair_contacts': len(stairs), 'unresolved_stair_contacts': sum(not r['geometric_contact'] for r in stairs)},
            'outstanding': ['Independent native elevation/section member assignment',
                            'FFL/SSL recesses and finish build-up', 'Missing structural XREF outlines',
                            '600 mm penthouse datum conflict', 'Stair ascent direction and landing opening geometry']}
