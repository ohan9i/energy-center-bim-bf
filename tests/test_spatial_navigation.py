from copy import deepcopy
import json
from pathlib import Path

import pytest
from shapely.geometry import Polygon
from shapely.ops import unary_union

from bf_bim.spatial_navigation import build_spatial, fingerprint, record_fingerprint, navmesh, validate_overrides

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def current():
    return json.loads((ROOT/'web/public/models/precision-rebuild.json').read_text(encoding='utf-8'))


def geometry(region):
    return unary_union([Polygon(r[0], r[1:]) for r in region])


def test_no_source_changes_and_no_automatic_approvals(current):
    before = deepcopy(current)
    data = build_spatial(current)
    assert current == before
    assert len(data['spaces']) == 31
    assert len(data['portals']) == len([e for e in current['elements'] if e['type'] == 'door']) == 88
    assert len(data['vertical']) == 10
    assert all(r['status'] == 'unresolved' and r['review'] is None for k in ('spaces', 'portals', 'vertical') for r in data[k])
    assert all(p['properties']['clear_width'] is None and p['properties']['operational'] is None for p in data['portals'])
    assert data['model_fingerprint'] == fingerprint(current)


def test_restored_assemblies_use_native_opening_geometry_without_approving_clear_width(current):
    data=build_spatial(current);portals={p['element_id']:p for p in data['portals']}
    for e in current['elements']:
        if not e['source'].get('door_plan_axis'):continue
        p=portals[e['id']]
        assert geometry(p['region']).symmetric_difference(Polygon(e['polygon'],e['holes'])).area<1e-8
        assert p['source_geometry']['native_opening_width_m']==pytest.approx(e['source']['door_plan_axis']['width_m'])
        assert p['source_geometry']['measured_leaf_span_m'] is None
        assert p['properties']['clear_width'] is None and p['status']=='unresolved'


def test_movement_candidates_are_subtractions_not_slab_envelopes(current):
    data = build_spatial(current)
    by_id = {e['id']: e for e in current['elements']}
    for space in data['spaces']:
        region = geometry(space['region'])
        source = by_id[space['element_id']]
        assert region.difference(Polygon(source['polygon'], source['holes'])).area < 1e-8
        blocked = unary_union([geometry(b['region']) for b in data['blockers'] if b['floor_id'] == space['floor_id']])
        assert region.intersection(blocked).area < 1e-7
        for other in data['spaces']:
            if other['id'] != space['id'] and other['floor_id'] == space['floor_id']:
                assert region.intersection(geometry(other['region'])).area < 1e-7


def test_constrained_navmesh_covers_only_eroded_floor_and_respects_holes(current):
    data = build_spatial(current)
    regions = {s['id']: geometry(s['region']).buffer(-.45) for s in data['spaces']}
    for mesh in navmesh(data, radius=.45):
        assert mesh['status'] == 'review_geometry_only'
        for triangle in mesh['triangles']:
            # Repeated Boolean subtraction can change a vertex by floating-point
            # roundoff. Measure outside area as well as maximum geometric distance.
            tri = Polygon(triangle)
            assert tri.difference(regions[mesh['space_id']]).area < 1e-9
            assert regions[mesh['space_id']].buffer(1e-7).covers(tri)


def test_overrides_survive_identical_regeneration_and_stale_edits_are_preserved(current):
    data = build_spatial(current)
    data['spaces'][0]['name'] = 'User boundary annotation'
    assert build_spatial(current, data)['spaces'][0]['name'] == 'User boundary annotation'
    changed = deepcopy(current)
    changed['elements'][0]['polygon'][0][0] += .01
    regenerated = build_spatial(changed, data)
    assert regenerated['override_state'] == 'stale_preserved'
    assert data['spaces'][0]['name'] == 'User boundary annotation'
    assert regenerated['spaces'][0]['name'] != data['spaces'][0]['name']


def test_unknown_conditions_or_fabricated_review_cannot_be_promoted(current):
    data = build_spatial(current)
    data['spaces'][0]['status'] = 'confirmed'
    with pytest.raises(ValueError, match='review evidence'):
        validate_overrides(current, data)
    s = data['spaces'][0]
    s.update(reasons=[], review=dict(reviewer='Actual reviewer', reviewed_at='2026-10-11T00:00:00Z',
        evidence=['drawing:object'], model_fingerprint=data['model_fingerprint']), evidence=['drawing:object'])
    s['review']['content_fingerprint'] = record_fingerprint(s)
    with pytest.raises(ValueError, match='unknown floor conditions'):
        validate_overrides(current, data)


def test_boundary_audit_exposes_unsupported_segments_without_closing_them(current):
    data = build_spatial(current)
    first = [s for s in data['spaces'] if s['floor_id'] == 'f1']
    assert first
    assert any(s['boundary_audit']['unsupported_source_boundary_m'] > .15 for s in first)
    assert all(s['boundary_audit']['tolerance_m'] == .001 and s['status'] == 'unresolved' for s in first)


def test_dependency_fingerprint_includes_body_of_components_and_passage_properties(current):
    for edit in (lambda m: m['elements'][0]['properties'].update(step=.01),
                 lambda m: m['elements'][0]['components'][0].update(height=.123),
                 lambda m: m['floors'][0].update(elevation=-4)):
        changed = deepcopy(current)
        edit(changed)
        assert fingerprint(changed) != fingerprint(current)


def test_navmesh_does_not_expand_for_negative_or_nan_clearance(current):
    data = build_spatial(current)
    for radius in (-.1, 0, float('nan')):
        with pytest.raises(ValueError, match='expansion prohibited'):
            navmesh(data, radius)


def test_host_metadata_changes_invalidate_bim_dependency_token(current):
    portal = next(e for e in current['elements'] if e['source'].get('host_openings'))
    for edit in (lambda s: s['host_wall_ids'].append('changed-host'),
                 lambda s: s['host_openings'][0]['polygon'][0].__setitem__(0, s['host_openings'][0]['polygon'][0][0]+.01)):
        changed=deepcopy(current)
        source=next(e['source'] for e in changed['elements'] if e['id']==portal['id'])
        edit(source)
        assert fingerprint(changed)!=fingerprint(current)


def test_current_window_boundaries_are_retained_as_non_passable_blockers(current):
    data=build_spatial(current)
    windows={e['id']:e for e in current['elements'] if e['type']=='window' and not e.get('excluded')}
    blockers={b['element_id']:b for b in data['blockers'] if b['kind']=='window'}
    assert set(windows)==set(blockers)
    for identity,e in windows.items():
        assert geometry(blockers[identity]['region']).symmetric_difference(Polygon(e['polygon'],e['holes'])).area<1e-10
