import math
import numpy as np
import pytest
from shapely.geometry import Polygon
from bf_bim.precise.structural_authoring import register_grid_lines,section_matches,support_pairs,trim_wall_heads

def test_axis_registration_ignores_tangential_bubble_displacement_but_rejects_normal_error():
    source={'controls':{}};target={'controls':{}}
    shift=np.array([5.,7.])
    for i in range(12):
        normal=np.array([1.,0.]) if i<6 else np.array([0.,1.])
        tangent=np.array([-normal[1],normal[0]])
        p=np.array([i*4000.,i*7000.]);label=str(i)
        source['controls'][label]={'xy':p.tolist(),'normal':normal.tolist(),'cad_ids':['s'+label]}
        target['controls'][label]={'xy':(p+shift*1000+tangent*4000).tolist(),'normal':normal.tolist(),'cad_ids':['t'+label]}
    r=register_grid_lines(source,target,np.array([0.,0.]))
    assert r['translation_m']==pytest.approx(shift)
    assert r['max_normal_residual_m']<1e-8
    target['controls']['0']['xy'][0]+=.1*1000
    with pytest.raises(ValueError,match='mismatch'):register_grid_lines(source,target,np.array([0.,0.]))

def test_section_scope_does_not_invent_variant_or_conflicting_dimensions():
    schedule={'embedded_rows':[{'kind':'beam','mark':'2~rG1','dimensions_m':[.45,.7]}]}
    assert section_matches('2G1',schedule) and section_matches('rG1',schedule)
    assert not section_matches('1G1',schedule) and not section_matches('2G1A',schedule)
    schedule['embedded_rows'].append({'kind':'beam','mark':'2G1','dimensions_m':[.4,.8]})
    assert not section_matches('2G1',schedule)

def col(name,x,y=0):return {'id':name,'polygon':[(x-.3,y-.3),(x+.3,y-.3),(x+.3,y+.3),(x-.3,y+.3)]}

def test_girder_span_must_be_unique_adjacent_and_parallel():
    cs=[col('a',0),col('b',8)]
    assert len(support_pairs(cs,np.array([4.,.9]),0))==1
    assert not support_pairs(cs,np.array([4.,.9]),math.radians(1))
    assert not support_pairs(cs,np.array([4.,.9]),math.pi/2)
    assert not support_pairs([*cs,col('mid',4)],np.array([4.,.9]),0)
    assert len(support_pairs([*cs,col('c',0,1),col('d',8,1)],np.array([4.,.9]),0))>1

def test_wall_head_cut_removes_only_intersection_volume_preserving_plan():
    poly=[(0,0),(8,0),(8,.2),(0,.2)]
    w={'id':'w','type':'wall','floor_id':'lower','polygon':poly,'components':[{'polygon':poly,'holes':[],'height':4.2,'z_offset':0,'role':'wall','source':{}}],'source':{}}
    b={'id':'beam','floor_id':'upper','components':[{'polygon':[(2,-.2),(6,-.2),(6,.4),(2,.4)],'holes':[],'height':.5,'z_offset':-.7}]}
    before=sum(Polygon(c['polygon']).area*c['height'] for c in w['components'])
    audit=trim_wall_heads([w],[b],{'lower':{'elevation':0},'upper':{'elevation':4.2}})
    after=sum(Polygon(c['polygon']).area*c['height'] for c in w['components'])
    assert before-after==pytest.approx(4*.2*.5)
    assert audit[0]['removed_duplicate_volume_m3']==pytest.approx(before-after)
    assert w['polygon']==poly

def test_nearly_coincident_beam_levels_do_not_emit_zero_volume_wall_parts():
    poly=[(0,0),(8,0),(8,.2),(0,.2)]
    wall={'id':'w','type':'wall','floor_id':'lower','polygon':poly,'components':[{'polygon':poly,'holes':[],'height':4.2,'z_offset':0,'role':'wall','source':{}}],'source':{}}
    beams=[{'id':str(i),'floor_id':'upper','components':[{'polygon':[(i,-.2),(i+2,-.2),(i+2,.4),(i,.4)],'holes':[],'height':.5,'z_offset':-.7+i*1e-15}]} for i in range(2)]
    trim_wall_heads([wall],beams,{'lower':{'elevation':0},'upper':{'elevation':4.2}})
    assert all(c['height']>=1e-7 for c in wall['components'])

def test_generated_structural_members_keep_source_and_height_limits():
    import json
    from pathlib import Path
    from shapely.ops import unary_union
    p=Path('cad_output/precision-rebuild/coordination-v2/preview.json')
    if not p.exists():pytest.skip('Generate artifact first')
    model=json.loads(p.read_text(encoding='utf8'))
    if model['revision']<8:pytest.skip('Structural rebuild not generated')
    beams=[e for e in model['elements'] if e['type']=='beam' and not e['source'].get('user_assumed_completion')]
    assert beams and {e['floor_id'] for e in beams}=={'f1','f2','f3','f4','roof'}
    elements={e['id']:e for e in model['elements']}
    for e in beams:
        s=e['source']['structural_girder'];assert not e['verified'] and e['height'] is None
        assert s['registration']['max_normal_residual_m']<.002
        assert len(s['registration']['controls'])>=8 and s['section_references']
        assert all(r['drawing_id']=='S02-001~' and r['source_sha256']==e['source']['source_sha256'] for r in s['section_references'])
        assert not s['native_outline_recovered'] and not s['member_assignment_verified']
        assert all(elements[i]['type']=='column' for i in s['support_ids'])
        assert all(c['z_offset']+c['height']<0 for c in e['components'])
    for fid in {'f1','f2','f3','f4','roof'}:
        ps=[unary_union([Polygon(c['polygon'],c['holes']) for c in e['components']]) for e in beams if e['floor_id']==fid]
        assert sum(p.area for p in ps)-unary_union(ps).area<1e-6
    for e in model['elements']:
        if e['floor_id'] in {'f2','f3','f4','roof'} and e['type'] in {'floor','roof'} and e['components']:
            assert all(c['height']==pytest.approx(.15) for c in e['components'] if c['role']=='structural_slab')
            if not e['source'].get('user_assumed_completion'):
                assert not e['source']['structural_slab_evidence']['boundary_verified']
