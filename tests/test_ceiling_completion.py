import json
from copy import deepcopy
from pathlib import Path

from shapely.geometry import Polygon
from shapely.ops import unary_union

from bf_bim.precise.ceiling_completion import complete_ceilings, profile
from bf_bim.precise.coordination_quality import attach_evidence

MODEL = Path(__file__).resolve().parents[1]/'web/public/models/precision-rebuild.json'


def test_closures_preserve_source_members_voids_and_are_repeatable():
    data = json.loads(MODEL.read_text(encoding='utf-8'))
    original = [e for e in data['elements'] if not e['source'].get('ceiling_completion')]
    elements = deepcopy(original)
    report = complete_ceilings(elements, data['floors'])
    assert elements[:len(original)] == original
    caps = elements[len(original):]
    assert report[0]['added_plan_area_m2'] > 48
    assert report[1]['added_elements'] == 0
    assert len(caps) == 2
    upper = next(e for e in original if e['floor_id'] == 'f2' and e['type'] == 'floor')
    for e in caps:
        assert not e['verified'] and e['height'] is None
        assert profile(e).intersection(Polygon(upper['polygon'])).area < 1e-8
        assert all(profile(e).intersection(Polygon(h)).area < 1e-8 for h in upper['holes'])
    saved = deepcopy(elements)
    assert complete_ceilings(elements, data['floors']) == report
    assert elements == saved
    # New caps must survive the full rebuild's evidence step as assumptions.
    attach_evidence(caps, data['floors'], {})
    assert all(e['source']['property_evidence']['position']['status'] == 'provisional' for e in caps)
    assert all(not e['source']['verification']['eligible'] for e in caps)


def test_closures_do_not_overlap_existing_solids_or_outdoor_rooms():
    data = json.loads(MODEL.read_text(encoding='utf-8'))
    complete_ceilings(data['elements'], data['floors'])
    elevations = {f['id']: f['elevation'] for f in data['floors']}
    caps = [e for e in data['elements'] if e['source'].get('ceiling_completion')]
    for cap in caps:
        for c in cap['components']:
            low = elevations[cap['floor_id']] + c['z_offset']
            high = low+c['height']
            for e in data['elements']:
                if e in caps or e['excluded'] or e['type'] in ('space', 'corridor', 'opening'):
                    continue
                for other in e['components']:
                    if other['height'] is None:
                        continue
                    bottom = elevations[e['floor_id']] + e['z_offset'] + other['z_offset']
                    overlap = min(high, bottom+other['height'])-max(low, bottom)
                    if overlap > 1e-7:
                        assert profile(c).intersection(profile(other)).area*overlap < 1e-7
        outdoors = unary_union([profile(e) for e in data['elements'] if e['floor_id'] == cap['floor_id']
                               and e['source'].get('space_usage') == 'outdoor'])
        assert profile(cap).intersection(outdoors).area < 1e-8
