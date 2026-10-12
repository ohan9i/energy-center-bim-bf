import json
from pathlib import Path

import pytest
from shapely.geometry import box
from shapely.ops import unary_union

from bf_bim.precise.completion import profile, parts, trim_solid_junctions, complete_slabs, complete_paired_shafts


def element(identity, kind, fid, p, cs):
    return {'id': identity, 'type': kind, 'floor_id': fid,
            'polygon': list(p.exterior.coords)[:-1], 'holes': [], 'components': cs,
            'source': {'cad_ids': [identity], 'assumptions': {}}}


def test_slab_junction_cuts_only_intersecting_xyz_and_keeps_wall_plan():
    wall=element('w','wall','low',box(0,0,8,.2),parts(box(0,0,8,.2),'wall',4.2))
    slab=element('s','floor','high',box(2,-1,6,1),parts(box(2,-1,6,1),'structural_slab',.2,-.23))
    far=element('far','wall','low',box(9,0,10,.2),parts(box(9,0,10,.2),'wall',4.2))
    old=wall['polygon'][:]
    r=trim_solid_junctions([wall,slab,far],{'low':{'elevation':0},'high':{'elevation':4.2}})
    assert len(r)==1 and r[0]['removed_duplicate_volume_m3']==pytest.approx(4*.2*.2)
    assert wall['polygon']==old and len(far['components'])==1
    assert sum(profile(c).area*c['height'] for c in wall['components'])==pytest.approx(8*.2*4.2-4*.2*.2)


def test_inferred_panel_partition_uses_s4_section_and_preserves_unknown_hole():
    p=box(0,0,10,10).difference(box(4,4,6,6))
    floor=element('floor','floor','f1',box(0,0,10,10),parts(p,'structural_slab',.2,-.23))
    floor['holes']=[list(r.coords)[:-1] for r in p.interiors]
    tags={'scene_entities':[{'id':'s1','type':'TEXT','geometry':{'text':'1S1','insert':[2000,-670000]}},
                             {'id':'s4','type':'TEXT','geometry':{'text':'1S4','insert':[8000,-670000]}}]}
    reg={'f1':{'translation_m':[0,675]}}
    schedule={'embedded_rows':[{'mark':'1S1','kind':'slab','dimensions_m':[.15]},
                                {'mark':'1S4','kind':'slab','dimensions_m':[.2]}]}
    r=complete_slabs([floor],{'f1':{}},tags,reg,schedule)
    concrete=[c for c in floor['components'] if c['role']=='structural_slab']
    assert {c['height'] for c in concrete}=={.15,.2}
    assert sum(profile(c).area for c in concrete)==pytest.approx(96)
    assert unary_union([profile(c) for c in concrete]).intersection(box(4,4,6,6)).area==0
    assert all(not c['source']['inferred_panel']['boundary_verified'] for c in concrete)
    assert r[0]['added_support_area_m2']==pytest.approx(0,abs=1e-8)


def test_touching_hole_is_opened_with_recorded_clearance_never_sealed():
    from shapely.geometry import Polygon
    from bf_bim.precise.wall_recovery import exact_prism_mesh
    hole=Polygon([(0,5),(2,4),(2,6)])
    p=box(0,0,10,10).difference(hole)
    cs=parts(p,'slab',.2)
    assert cs and cs[0]['source']['numeric_hole_clearance_m']==.0001
    assert unary_union([profile(c) for c in cs]).intersection(hole).area<1e-9
    assert 0<p.area-sum(profile(c).area for c in cs)<.01
    for c in cs:assert exact_prism_mesh(profile(c),c['height'])


def test_overlapping_shaft_candidates_keep_union_void_with_disjoint_compartments():
    shafts=[element('a','elevator','f1',box(0,0,3,3),[]),element('b','elevator','f1',box(2,0,5,3),[])]
    old=unary_union([profile(e) for e in shafts])
    r=complete_paired_shafts(shafts,{'f1':{'height_preview':4.2}})
    assert r[0]['before_parent_overlap_m2']==pytest.approx(3)
    assert r[0]['after_parent_overlap_m2']==pytest.approx(0,abs=1e-10)
    assert unary_union([profile(e) for e in shafts]).symmetric_difference(old).area<1e-10
    pa=unary_union([profile(c) for c in shafts[0]['components']]);pb=unary_union([profile(c) for c in shafts[1]['components']])
    assert pa.intersection(pb).area<1e-9
    assert all(e['source']['user_assumed_completion']['design_verified'] is False for e in shafts)


def test_generated_assumptions_are_visible_and_never_design_approved():
    path=Path('cad_output/precision-rebuild/coordination-v2/preview.json')
    if not path.exists():pytest.skip('Generate model first')
    m=json.loads(path.read_text(encoding='utf8'))
    if m['revision']<9:pytest.skip('Generate completion first')
    assumed=[e for e in m['elements'] if e['source'].get('user_assumed_completion')]
    assert assumed and {'b1','f1','f2','f3','f4','roof','phroof','pit'} <= {e['floor_id'] for e in assumed}
    assert not m['provenance']['assumed_completion']['route_calculated']
    for e in assumed:
        assert not e['verified'] and not e['source']['design_assignment_verified']
        assert e['source']['property_evidence']['position']['status']=='provisional'
        assert e['source']['property_evidence']['profile']['status']=='provisional'
        assert e['source']['user_assumed_completion']['authorization']
    beams=[e for e in assumed if e['type']=='beam']
    assert beams and {'f1','f2','f3','f4','roof'} <= {e['floor_id'] for e in beams}
    known={e['id'] for e in m['elements']}
    for e in beams:
        b=e['source']['assumed_beam']
        assert len(b['support_ids'])==2 and set(b['support_ids'])<=known
        assert b['section_references'] or b['section_defaulted']
        assert b['registration']['max_normal_residual_m']<.002
    f1=[c for e in m['elements'] if e['floor_id']=='f1' and e['type']=='floor' for c in e['components'] if c['role']=='structural_slab']
    assert {round(c['height'],2) for c in f1}=={.15,.2}
    assert any(c['source']['inferred_panel'].get('mark')=='1S4' for c in f1)
    pit_ids={e['id'] for e in m['elements'] if e['floor_id']=='pit'}
    assert pit_ids and not any(pit_ids.intersection(v['element_ids']) for v in m['provenance']['bf_spatial']['vertical'])
