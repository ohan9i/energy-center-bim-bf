"""Conservative overhead closures for the reviewed first and second floors.

Use only indoor room candidates outside the next storey's slab envelope.
Every existing slab hole stays open, including holes of unknown purpose.
The added caps are coordination assumptions, not ceiling-finish design.
"""
import hashlib

from shapely.geometry import Polygon
from shapely.ops import unary_union


def polygons(shape):
    if shape.geom_type == 'Polygon':
        yield shape
    elif hasattr(shape, 'geoms'):
        for part in shape.geoms:
            yield from polygons(part)


def profile(item):
    return Polygon(item['polygon'], item.get('holes', []))


def rings(poly):
    return {'polygon': [list(p) for p in poly.exterior.coords[:-1]],
            'holes': [[list(p) for p in r.coords[:-1]] for r in poly.interiors]}


def complete_ceilings(elements, floors):
    """Idempotently add caps without changing any existing member or opening."""
    elevations = {f['id']: f['elevation'] for f in floors}
    originals = [e for e in elements if not e['source'].get('ceiling_completion')]
    elements[:] = originals
    report = []
    for lower, upper in [('f1', 'f2'), ('f2', 'f3')]:
        slabs = [e for e in originals if e['floor_id'] == upper
                 and e['type'] in ('floor', 'roof') and not e.get('excluded')
                 and not e['source'].get('unresolved_plan_only') and e['components']]
        if not slabs or lower not in elevations:
            continue
        # A shell includes its holes deliberately: never cover an existing void.
        envelopes = unary_union([Polygon(e['polygon']) for e in slabs])
        protected = unary_union([profile(e) for e in originals
            if e['floor_id'] in (lower, upper) and e['type'] in ('stair', 'elevator', 'opening')
            and not e.get('excluded')])
        rooms = [e for e in originals if e['floor_id'] == lower
                 and e['type'] in ('space', 'corridor') and not e.get('excluded')
                 and e['source'].get('space_usage') == 'indoor_candidate']
        local_floors = unary_union([profile(e) for e in originals
            if e['floor_id'] == lower and e['type'] == 'floor' and not e.get('excluded')])
        region = unary_union([profile(e) for e in rooms]).intersection(local_floors)
        missing = region.difference(envelopes).difference(protected)
        top = elevations[upper] - .03
        bottom = top - .15
        # Keep walls, columns, beams and their joints intact. Slice the new cap
        # around actual solids instead of trimming existing source geometry.
        blockers = []
        for e in originals:
            if e.get('excluded') or e['type'] in ('space', 'corridor', 'opening'):
                continue
            for c in e['components']:
                if c['height'] is None:
                    continue
                lo = elevations[e['floor_id']] + e.get('z_offset', 0) + c['z_offset']
                hi = lo + c['height']
                if min(top, hi) - max(bottom, lo) > 1e-7 and profile(c).intersects(missing):
                    blockers.append((max(bottom, lo), min(top, hi), profile(c)))
        levels = sorted({bottom, top, *[v for a, b, _ in blockers for v in (a, b)]})
        components = []
        for lo, hi in zip(levels, levels[1:]):
            if hi-lo < 1e-7:
                continue
            net = missing.difference(unary_union([p for a, b, p in blockers if a < hi-1e-8 and b > lo+1e-8]))
            for poly in polygons(net):
                if poly.area < .01 or poly.buffer(-.005).is_empty:
                    continue
                components.append({**rings(poly), 'role': 'assumed_ceiling_closure',
                    'height': hi-lo, 'z_offset': lo-elevations[lower],
                    'source': {'material': 'concrete', 'geometry_status': 'provisional',
                               'dimension_verified': False}})
        added = []
        for index, c in enumerate(components):
            identity = 'ceiling-' + hashlib.sha256((lower + str(index) + profile(c).wkt).encode()).hexdigest()[:20]
            c['id'] = identity + '/component/0'
            e = {'id': identity, 'name': f'{lower[1:]}층 상부 덮개 추정 보완 {index+1}',
                 'type': 'roof', 'floor_id': lower, **rings(profile(c)), 'height': None,
                 'z_offset': 0, 'verified': False, 'excluded': False, 'properties': {},
                 'components': [c], 'source': {
                     'file': slabs[0]['source']['file'],
                     'source_sha256': slabs[0]['source']['source_sha256'],
                     'cad_ids': [],
                     'ceiling_completion': True, 'validation_status': 'provisional',
                     'geometry_status': 'inferred', 'export_status': 'coordination_draft',
                     'design_assignment_verified': False, 'material': 'concrete',
                     'user_assumed_completion': {'authorization': '1층 2층 천장쪽 보완',
                         'reason': '위층 슬래브 외곽 밖 실내 후보 영역의 상부 폐합',
                         'context_references_only': True, 'design_verified': False},
                     'context_room_ids': [r['id'] for r in rooms if profile(r).intersects(profile(c))],
                     'context_slab_ids': [s['id'] for s in slabs],
                     'assumptions': {'thickness': {'value_m': .15, 'status': 'provisional'},
                                     'top_below_upper_floor': {'value_m': .03, 'status': 'provisional'}},
                     'unknowns': ['천장·지붕 도면 대조 필요. 마감 및 설비 설계 미포함.'],
                     'method': 'Indoor candidates outside upper slab shells; preserve every slab void and subtract existing solids.'}}
            elements.append(e)
            added.append(e)
        report.append({'floor_id': lower, 'upper_floor_id': upper,
                       'added_elements': len(added),
                       'added_plan_area_m2': unary_union([profile(c) for c in components]).area,
                       'added_volume_m3': sum(profile(c).area*c['height'] for c in components),
                       'preserved_upper_voids': sum(len(s.get('holes', [])) for s in slabs)})
    return report
