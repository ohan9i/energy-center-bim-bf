"""Regressions for facade width, bent openings and roof mosaic boundaries."""
import math
import json
from pathlib import Path
import pytest
from shapely.affinity import rotate
from shapely.geometry import box
from bf_bim.precise.envelope import opening_projection, parapet_band


@pytest.mark.parametrize('angle', [0, 37, 90, 135])
def test_projection_reaches_outside_skin_without_removing_jamb_width(angle):
    p = rotate(box(1, -.05, 3, .05), angle, origin=(0, 0))
    a = math.radians(angle)
    e = {'type': 'window', 'polygon': list(p.exterior.coords)[:-1], 'source': {
        'window_plan_axis': {'origin': [2*math.cos(a), 2*math.sin(a)],
                             'direction': [math.cos(a), math.sin(a)], 'width_m': 2.}}}
    projected = opening_projection(e)
    skin = rotate(box(0, .20, 4, .258), angle, origin=(0, 0))
    expected = rotate(box(1, .20, 3, .258), angle, origin=(0, 0))
    assert projected.intersection(skin).symmetric_difference(expected).area < 1e-9
    assert projected.intersection(rotate(box(.8, .20, .99, .258), angle, origin=(0, 0))).is_empty


def test_bent_window_projects_runs_without_erasing_the_corner():
    runs = [(box(1, -.05, 3, .05), [2, 0], [1, 0]),
            (box(2.95, 0, 3.05, 2), [3, 1], [0, 1])]
    segments = [{'polygon': list(p.exterior.coords)[:-1], 'holes': [],
                 'axis': {'origin': o, 'direction': u, 'width_m': 2}} for p, o, u in runs]
    e = {'type': 'window', 'polygon': list(box(1, 0, 3, 2).exterior.coords)[:-1],
         'source': {'window_plan_segments': segments}}
    cut = opening_projection(e)
    assert cut.covers(box(1.1, -.5, 2.9, -.2))
    assert cut.covers(box(3.2, .1, 3.5, 1.9))
    assert cut.intersection(box(1.1, 1.2, 2.1, 1.8)).is_empty


def test_native_axis_and_retained_rounded_symbol_do_not_leave_opaque_sliver():
    p=box(1, -.15, 3.00046, .15)
    e={'type':'window','polygon':list(p.exterior.coords)[:-1], 'source':{
        'window_plan_axis':{'origin':[2,0],'direction':[1,0],'width_m':2.}}}
    cut=opening_projection(e)
    assert p.difference(cut).area < 1e-10
    assert cut.intersection(box(3.01,.05,3.2,.1)).is_empty


def test_parapet_ignores_unassigned_mosaic_hole_but_keeps_courtyard_edge():
    courtyard = box(4, 4, 6, 6)
    roof = box(0, 0, 10, 10).difference(courtyard).difference(box(1, 1, 2, 2))
    band = parapet_band(roof, courtyard)
    assert band.intersection(box(.9, .9, 2.1, 2.1)).is_empty
    assert band.covers(box(4.1, 3.86, 5.9, 3.99))
    assert band.covers(box(.01, .2, .14, 9.8))
    assert band.difference(roof).area < 1e-9


def test_published_model_has_no_facade_obstruction_or_slab_duplicate():
    model = json.loads(Path('web/public/models/precision-rebuild.json').read_text(encoding='utf8'))
    if model['revision'] < 11:
        pytest.skip('Generate building 3D revision first')
    # Recompute from the actual solids; do not trust the saved summary.
    from bf_bim.precise.building_review import audit_building
    report = audit_building(model['elements'], model['provenance']['floors_evidence'])
    assert report['summary']['maximum_slab_pair_volume_m3'] < 1e-5
    assert report['summary']['maximum_opaque_opening_residual_m3'] < 1e-5
    assert report['summary']['parapet_outside_boundary_volume_m3'] < 1e-5
    assert report['summary']['facade_missing_volume_m3'] < .001
    assert not model['provenance']['verified_solids']
    assert all(not e['verified'] for e in model['elements'])
