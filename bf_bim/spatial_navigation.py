"""Separate drawing-linked BF space ledger. No gap closing or inferred approvals.

python -m bf_bim.spatial_navigation --sync-web
Reviewed overrides live outside BIM; stale overrides remain on disk for re-review.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path

from shapely import constrained_delaunay_triangles
from shapely.geometry import Polygon, Point, LineString
from shapely.ops import unary_union
from shapely.strtree import STRtree

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'cad_output/bf-spatial'
VERSION = 'bf-spatial/1'


def fingerprint(model):
    """Same ordered UTF-16 FNV-1a dependency token as web/src/spatial.ts.

    A change detector, not an evidence signature or a security boundary.
    Coordinates use 0.1 micrometre precision, far below CAD tessellation.
    """
    parts = ['bf-model-dependencies/3', model['id']]
    def number(n):
        return 'null' if n is None else f'{float(n):.7f}'
    def geometry(item):
        parts.extend([str(item.get('role', '')), number(item.get('height')), number(item.get('z_offset', 0))])
        for r in [item['polygon'], *item.get('holes', [])]:
            parts.append('ring')
            parts.extend(number(v) for p in r for v in p)
        mesh = item.get('mesh')
        if mesh:
            parts.append('mesh')
            parts.extend(number(v) for p in mesh['vertices'] + mesh['triangles'] for v in p)
    for f in model['floors']:
        parts.extend([f['id'], number(f['elevation'])])
    for e in sorted(model['elements'], key=lambda e: e['id']):
        parts.extend([e['id'], e['type'], e['floor_id'], str(bool(e.get('excluded'))).lower(),
                      e.get('source', {}).get('source_sha256', '')])
        props = e.get('properties', {})
        parts.extend(number(props.get(k)) for k in ('clear_width', 'step', 'slope'))
        parts.extend(['null' if props.get('operational') is None else str(props['operational']).lower(), str(bool(e.get('verified'))).lower()])
        geometry(e)
        for c in e.get('components', []):
            geometry(c)
        source = e.get('source', {})
        for identity in sorted(source.get('host_wall_ids', [])):
            parts.extend(['host', identity])
        for cut in source.get('host_openings', []):
            parts.extend(['opening-host', cut['host_wall_id']])
            geometry({**cut, 'height': None, 'z_offset': 0})
    for t in model.get('provenance', {}).get('cad_traces', []):
        parts.extend([t['id'], t['floor_id'], t['kind']])
        parts.extend(number(v) for p in t['points'] for v in p)
    value = 2166136261
    data = '|'.join(parts).encode('utf-16-le')
    for i in range(0, len(data), 2):
        value = ((value ^ int.from_bytes(data[i:i+2], 'little')) * 16777619) & 0xffffffff
    return f'{value:08x}'


def record_fingerprint(record):
    omitted = {'id', 'name', 'status', 'review', 'evidence', 'reasons', 'boundary_audit', 'source_geometry'}
    def normalize(value):
        if isinstance(value, bool) or value is None:
            return value
        if isinstance(value, (float, int)):
            return f'{float(value):.7f}'
        if isinstance(value, list):
            return [normalize(v) for v in value]
        if isinstance(value, dict):
            return {k: normalize(v) for k, v in sorted(value.items())}
        return value
    text = json.dumps(normalize({k: v for k, v in record.items() if k not in omitted}), ensure_ascii=False, separators=(',', ':'))
    data = text.encode('utf-16-le')
    result = 2166136261
    for i in range(0, len(data), 2):
        result = ((result ^ int.from_bytes(data[i:i+2], 'little')) * 16777619) & 0xffffffff
    return f'{result:08x}'


def shape(e):
    p = Polygon(e['polygon'], e.get('holes', []))
    if not p.is_valid or p.area <= 1e-8:
        raise ValueError('Invalid boundary; automatic repair prohibited: ' + e['id'])
    return p


def polygons(g):
    if g.is_empty:
        return []
    if g.geom_type == 'Polygon':
        return [g]
    return [p for c in getattr(g, 'geoms', []) for p in polygons(c)]


def region(g):
    return [[[list(p) for p in list(poly.exterior.coords)[:-1]],
             *[[list(p) for p in list(r.coords)[:-1]] for r in poly.interiors]] for poly in polygons(g)]


def evidence(e):
    s = e.get('source', {})
    return [f"{s.get('source_sha256', 'missing-source')}:{i}" for i in s.get('cad_ids', [])]


def build_spatial(model, overrides=None):
    token = fingerprint(model)
    data = dict(version=VERSION, model_id=model['id'], model_fingerprint=token,
                spaces=[], blockers=[], portals=[], vertical=[], override_state='none')
    by_floor = {f['id']: [e for e in model['elements'] if e['floor_id'] == f['id'] and not e.get('excluded')]
                for f in model['floors']}
    from bf_bim.precision_model import COURTYARD
    for fid, es in by_floor.items():
        native = [t for t in model.get('provenance', {}).get('cad_traces', [])
                  if t['floor_id'] == fid and t['kind'] in ('wall', 'finish', 'door', 'column') and len(t['points']) > 1]
        trace_lines = [LineString(t['points']) for t in native]
        trace_tree = STRtree(trace_lines)
        buffered_traces = {}
        def boundary_audit(e):
            boundary = shape(e).boundary
            nearby = trace_tree.query(boundary.buffer(.001), predicate='intersects')
            for index in nearby:
                if index not in buffered_traces:
                    buffered_traces[index] = trace_lines[index].buffer(.001, quad_segs=2)
            covered = unary_union([buffered_traces[index] for index in nearby])
            return dict(method='inherited_contour_vs_native_lines_no_gap_repair', tolerance_m=.001,
                unsupported_source_boundary_m=boundary.difference(covered).length,
                compared_native_traces=len(native), status='observation_not_boundary_approval')
        blockers = []
        for e in es:
            if e['type'] in ('wall', 'column', 'window', 'obstacle', 'unclassified', 'elevator', 'stair'):
                blockers.append(shape(e))
                data['blockers'].append(dict(id='block-'+e['id'], element_id=e['id'], floor_id=fid,
                                             kind=e['type'], region=region(shape(e))))
                if e['type'] == 'elevator':
                    for i, c in enumerate(e.get('components', [])):
                        if 'lining' in c['role'] or 'wall' in c['role']:
                            data['blockers'].append(dict(id=f"lining-{e['id']}-{i}", element_id=e['id'],
                                floor_id=fid, kind='wall', region=region(shape({**c, 'id': e['id']}))))
        voids = [Polygon(h) for e in es if e['type'] == 'floor' for h in e.get('holes', [])]
        if fid != 'b1' and model.get('provenance', {}).get('coordination_draft'):
            voids.append(COURTYARD)
        for i, p in enumerate(voids):
            data['blockers'].append(dict(id=f'void-{fid}-{i}', element_id=None, floor_id=fid, kind='void', region=region(p)))
        blocked = unary_union(blockers + voids)
        support = unary_union([shape(e) for e in es if e['type'] == 'floor'])
        assigned = []
        for e in es:
            if e['type'] not in ('space', 'corridor'):
                continue
            # Subtraction only. Never buffer outwards, close, convex-hull or fill holes.
            free = shape(e).intersection(support).difference(blocked)
            if assigned:
                free = free.difference(unary_union(assigned))
            assigned.append(free)
            data['spaces'].append(dict(id='space-'+e['id'], element_id=e['id'], floor_id=fid, name=e['name'],
                kind='corridor' if e['type'] == 'corridor' else 'room', region=region(free), status='unresolved',
                step=None, slope=None, evidence=evidence(e), review=None,
                boundary_audit=boundary_audit(e),
                reasons=['Inherited room boundary includes unreviewed enclosure assumptions',
                         'Finished floor step/slope and drawing boundary assignment unconfirmed']))
        spaces = [s for s in data['spaces'] if s['floor_id'] == fid]
        for e in es:
            if e['type'] != 'door':
                continue
            p = shape(e)
            corners = list(p.minimum_rotated_rectangle.exterior.coords)
            a, b = max(zip(corners, corners[1:]), key=lambda pair: Point(pair[0]).distance(Point(pair[1])))
            length = Point(a).distance(Point(b))
            normal = [-(b[1]-a[1])/length, (b[0]-a[0])/length]
            center = list(p.centroid.coords[0])
            points = [[center[j]+sign*.8*normal[j] for j in range(2)] for sign in (-1, 1)]
            adjacent = []
            for point in points:
                matches = [s['id'] for s in spaces if any(Polygon(r[0], r[1:]).covers(Point(point)) for r in s['region'])]
                if len(matches) == 1:
                    adjacent.append(matches[0])
            if len(set(adjacent)) != 2:
                adjacent = []
            # A restored assembly may contain two leaves. Its old arc radius is
            # retained CAD metadata, not an actual leaf or passage measurement.
            native_axis=e['source'].get('door_plan_axis')
            data['portals'].append(dict(id='portal-'+e['id'], element_id=e['id'], floor_id=fid, kind='door',
                space_ids=adjacent, points=points, region=region(p), host_wall_ids=e['source'].get('host_wall_ids', []),
                status='unresolved', properties=dict(clear_width=None, step=None, operational=None),
                source_geometry=dict(hinge=e['source'].get('hinge'), leaf_end=e['source'].get('leaf_end'),
                    swing_end=e['source'].get('swing_end'), measured_leaf_span_m=None if native_axis else e['source'].get('leaf_radius_m'),
                    native_opening_width_m=native_axis['width_m'] if native_axis else None,
                    cad_ids=e['source'].get('cad_ids', [])),
                evidence=evidence(e), review=None, reasons=['Door swing/host-depth geometry is a candidate, not a reviewed passage',
                    'Both spaces, effective clear width, threshold and opening condition require review']))
    # A shaft PIT is a structural termination, not a serviced landing. Its
    # component role is already covered by the model dependency fingerprint.
    lifts = [e for e in model['elements'] if e['type'] == 'elevator' and not e.get('excluded')
             and not any(c.get('role')=='assumed_pit_base' for c in e.get('components',[]))]
    for a in lifts:
        higher = [b for b in lifts if next(f['elevation'] for f in model['floors'] if f['id'] == b['floor_id']) >
                  next(f['elevation'] for f in model['floors'] if f['id'] == a['floor_id']) and shape(a).intersection(shape(b)).area > .1]
        if not higher:
            continue
        b = min(higher, key=lambda e: next(f['elevation'] for f in model['floors'] if f['id'] == e['floor_id']))
        distance = next(f['elevation'] for f in model['floors'] if f['id'] == b['floor_id']) - next(f['elevation'] for f in model['floors'] if f['id'] == a['floor_id'])
        data['vertical'].append(dict(id='vertical-'+a['id']+'-'+b['id'], kind='elevator', element_ids=[a['id'], b['id']],
            space_ids=[], points=[list(shape(a).centroid.coords[0]), list(shape(b).centroid.coords[0])], distance=distance,
            status='unresolved', properties=dict(clear_width=None, step=None, operational=None, slope=None),
            evidence=evidence(a)+evidence(b), review=None, reasons=['Aligned shafts alone do not confirm serviced floors, car or landing doors']))
    if overrides:
        if overrides.get('model_id') != model['id'] or overrides.get('model_fingerprint') != token:
            data['override_state'] = 'stale_preserved'
        else:
            validate_overrides(model, overrides)
            # Full separate ledger also permits corrected walls/voids and new observed spaces.
            for key in ('spaces', 'blockers', 'portals', 'vertical'):
                data[key] = deepcopy(overrides[key])
            data['override_state'] = 'applied_requires_runtime_validation'
    return data


def validate_overrides(model, data):
    """Validate disk edits before regeneration; the browser also checks graph topology.

    Confirmations are never created here. Review records bind to current source geometry.
    """
    if data.get('version') != VERSION or data.get('model_id') != model['id'] or data.get('model_fingerprint') != fingerprint(model):
        raise ValueError('Stale or incompatible BF space overrides')
    ids = set()
    floors = {f['id'] for f in model['floors']}
    for key in ('spaces', 'blockers', 'portals', 'vertical'):
        for r in data[key]:
            if r['id'] in ids:
                raise ValueError('Duplicate BF space ID')
            ids.add(r['id'])
            if 'floor_id' in r and r['floor_id'] not in floors:
                raise ValueError('Unknown BF floor')
            for rings in r.get('region', []):
                p = Polygon(rings[0], rings[1:])
                if not p.is_valid or p.area < 1e-8:
                    raise ValueError('Invalid BF boundary; automatic repair prohibited')
            if r.get('status') == 'confirmed':
                review = r.get('review') or {}
                if (not review.get('reviewer') or not review.get('reviewed_at') or not review.get('evidence')
                        or review.get('model_fingerprint') != data['model_fingerprint']
                        or review.get('content_fingerprint') != record_fingerprint(r) or not r.get('evidence') or r.get('reasons')):
                    raise ValueError('Confirmation lacks current drawing review evidence')
                props = r.get('properties', {})
                if key == 'spaces' and (not r['region'] or r.get('step') is None or r.get('slope') is None):
                    raise ValueError('Confirmed space has unknown floor conditions')
                if key in ('portals', 'vertical') and (len(r['space_ids']) != 2 or any(props.get(k) is None for k in ('clear_width', 'step', 'operational'))):
                    raise ValueError('Confirmed connection has unknown passage conditions')
    return data


def navmesh(data, radius=.6):
    """Constrained triangles of erosion only; unresolved triangles are review-only.

    Portal and space approvals are additionally enforced by the web graph builder.
    """
    if not math.isfinite(radius) or radius <= 0:
        raise ValueError('Clearance radius must be finite and positive; boundary expansion prohibited')
    result = []
    for s in data['spaces']:
        source = unary_union([Polygon(r[0], r[1:]) for r in s['region']])
        obstacles = []
        for b in data['blockers']:
            if b['floor_id'] != s['floor_id']:
                continue
            blocked = unary_union([Polygon(r[0], r[1:]) for r in b['region']])
            if (s['kind'] == 'elevator_car' and s['status'] == 'confirmed' and s.get('review')
                    and s['review'].get('content_fingerprint') == record_fingerprint(s)
                    and (b['kind'] == 'void' or b['kind'] == 'elevator' and b['element_id'] == s['element_id'])):
                blocked = blocked.difference(source)
            obstacles.append(blocked)
        # Polygonal round-corner offsets can differ after inserting obstacle
        # vertices. Intersect with the original inward offset so new tessellation
        # never protrudes outside the source space's own clearance boundary.
        area = source.difference(unary_union(obstacles)).buffer(-radius).intersection(source.buffer(-radius))
        for poly in polygons(area):
            triangles = constrained_delaunay_triangles(poly)
            result.append(dict(space_id=s['id'], status='review_geometry_only', space_review_status=s['status'], clearance_radius_m=radius,
                triangles=[list(map(list, list(t.exterior.coords)[:-1])) for t in triangles.geoms if poly.covers(t)]))
    return result


def attach_spatial(model, overrides=None):
    model = deepcopy(model)
    model['provenance']['bf_spatial'] = build_spatial(model, overrides)
    return model


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', type=Path, default=ROOT/'cad_output/precision-rebuild/coordination-v2/preview.json')
    parser.add_argument('--overrides', type=Path, default=OUTPUT/'overrides.json')
    parser.add_argument('--sync-web', action='store_true')
    parser.add_argument('--clearance-radius', type=float, default=.6,
                        help='NavMesh inward offset in m; default is half the user-defined 1.2 m corridor clearance')
    args = parser.parse_args()
    model = json.loads(args.model.read_text(encoding='utf-8'))
    # Verify the observed plan and section against the preserved DWG inventory.
    protected = [args.model, ROOT/'cad_output/energy-center-model.json']
    expected = {model.get('provenance', {}).get('source_drawing_sha256')}
    expected.update(r.get('source_sha256') for f in model.get('provenance', {}).get('floors_evidence', []) for r in f.get('level_evidence', []))
    expected.discard(None)
    if expected:
        rows = json.loads((ROOT/'docs/bim-audit-2026-10-11/drawing-index.json').read_text(encoding='utf-8'))
        matched = [r for r in rows if r['sha256'] in expected]
        if {r['sha256'] for r in matched} != expected:
            raise ValueError('Source drawing evidence is not in the preserved inventory')
        for row in matched:
            path = ROOT / row['file']
            with path.open('rb') as source:
                digest = hashlib.file_digest(source, 'sha256').hexdigest()
            if digest != row['sha256']:
                raise ValueError('Original DWG changed; refresh drawing observations before BF regeneration')
            protected.append(path)
    def hashes():
        result = {}
        for path in protected:
            if path.exists():
                with path.open('rb') as source:
                    result[str(path.relative_to(ROOT))] = hashlib.file_digest(source, 'sha256').hexdigest()
        return result
    before = hashes()
    overrides = json.loads(args.overrides.read_text(encoding='utf-8')) if args.overrides.exists() else None
    spatial = build_spatial(model, overrides)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for name, value in [('spaces.json', spatial), ('navmesh.json', navmesh(spatial, args.clearance_radius)),
                        ('boundary-audit.json', [dict(space_id=s['id'], **s['boundary_audit']) for s in spatial['spaces'] if 'boundary_audit' in s])]:
        (OUTPUT/name).write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding='utf-8')
    if args.sync_web:
        # Update only the separate ledger in the current local web model. IFC and source BIM remain untouched.
        path = ROOT/'web/public/models/precision-rebuild.json'
        web = json.loads(path.read_text(encoding='utf-8'))
        if fingerprint(web) != spatial['model_fingerprint']:
            raise ValueError('Web/source geometry mismatch; regenerate the current BIM first')
        web['provenance']['bf_spatial'] = spatial
        temporary = path.with_name(path.name + '.bf-spatial.tmp')
        temporary.write_text(json.dumps(web, ensure_ascii=False, allow_nan=False, indent=2), encoding='utf-8', newline='\n')
        temporary.replace(path)
    after = hashes()
    if before != after:
        raise AssertionError('Protected DWG or source BIM changed during space generation')
    (OUTPUT/'preservation.json').write_text(json.dumps(dict(checked_files=len(before), changed_files=[], hashes_before=before, hashes_after=after), indent=2), encoding='utf-8')
    print(json.dumps(dict(spaces=len(spatial['spaces']), portals=len(spatial['portals']), vertical=len(spatial['vertical']),
                         confirmed=sum(s['status']=='confirmed' for s in spatial['spaces']), override_state=spatial['override_state'])))


if __name__ == '__main__':
    main()
