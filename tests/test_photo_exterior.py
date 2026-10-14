"""Photo appearance must preserve CAD portals and never approve navigation."""
import json
from pathlib import Path
import pytest
from shapely.geometry import Polygon
from bf_bim.precise.photo_exterior import REFERENCE


def test_published_exterior_keeps_portals_voids_and_unverified_status():
    path=Path('web/public/models/precision-rebuild.json')
    m=json.loads(path.read_text(encoding='utf8'))
    if m['revision']<10:pytest.skip('Generate photo exterior first')
    photo=[e for e in m['elements'] if e['source'].get('photo_reference')]
    assert photo and all(not e['verified'] and not e['source']['design_assignment_verified'] for e in photo)
    assert m['provenance']['photo_exterior']['reference']['kind']=='site_photographs'
    assert m['provenance']['photo_exterior']['reference']['attachment_sha256']==REFERENCE['attachment_sha256']
    assert all(not c['role'].startswith(('photo_rooftop_pv','photo_outdoor_pv','photo_parking_','photo_pv_support')) for e in m['elements'] for c in e['components'])
    assert set(m['provenance']['photo_exterior']['excluded_by_user'])=={'rooftop_pv','outdoor_pv','parking_pv_canopy','pv_supports'}
    walls=[e for e in photo if e['type']=='wall']
    for portal in [e for e in m['elements'] if e['type'] in ('door','window') and e['components']]:
        op=portal['source']['provisional_opening'];mid=op['z_offset']+op['height']/2
        p=Polygon(portal['polygon'],portal['holes'])
        for e in walls:
            if e['floor_id']!=portal['floor_id']:continue
            for c in e['components']:
                if c['z_offset']<mid<c['z_offset']+c['height']:
                    assert Polygon(c['polygon'],c['holes']).intersection(p).area<1e-5
