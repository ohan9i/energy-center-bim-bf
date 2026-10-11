from copy import deepcopy
import json
from pathlib import Path
import math
import pytest
from shapely.geometry import box, Polygon
from bf_bim.precise.door_authoring import native_door_groups,restore_door_assemblies,apply_door_assemblies
from bf_bim.architectural_assemblies import load_parameters
from bf_bim.precise.coordination_quality import opening_axis,host_opening


def fixture():
    def entity(identity,kind,geometry):
        return {'id':identity,'type':kind,'geometry':geometry,'support':'full','layer':'A-DOOR','insert_ancestry':['root']}
    def frame(identity,lo,hi):
        vertices=[[lo,0,0],[hi,0,0],[hi,150,0],[lo,150,0],[lo,0,0]]
        return entity(identity,'LWPOLYLINE',{'vertices':vertices,'closed':True,
            'segments':[{'type':'LINE','start':a,'end':b} for a,b in zip(vertices,vertices[1:])]})
    entities=[frame('jamb-left',0,60),frame('jamb-right',2340,2400),
              entity('bridge','LINE',{'start':[60,75,0],'end':[2340,75,0]})]
    doors=[]
    for n,side in enumerate((-1,1)):
        pivot=60 if side==-1 else 2340
        identity='arc-'+str(n)
        entities.append(entity(identity,'ARC',{'center':[pivot,75,0],'radius':1140,
            'start':[1200,75,0],'end':[pivot,1215,0]}))
        doors.append({'id':'door-'+str(n),'name':'door','type':'door','floor_id':'f1',
            'polygon':list(box(pivot*.001-.1,.075,pivot*.001+.1,1.215).exterior.coords)[:-1],'holes':[],
            'components':[],'verified':False,'height':None,'source':{'file':'plan.dwg','source_sha256':'plan',
                'cad_ids':[identity],'assumptions':{'door_height':{'value_m':2.1}},'property_status':{},
                'hinge':[pivot*.001,.075],'leaf_end':[pivot*.001,1.215]}})
    return doors,{'scene_entities':entities,'warnings':[]},{'f1':{'origin':[0,0]}}


def test_native_jambs_restore_complete_double_door_and_retain_leaf_alias():
    doors,archive,specs=fixture();r=restore_door_assemblies(doors,archive,specs)
    assert len(r)==1 and len(doors)==1
    e=doors[0];s=e['source']
    assert s['door_plan_axis']['width_m']==pytest.approx(2.4)
    assert s['door_plan_axis']['depth_m']==pytest.approx(.15)
    assert s['native_door_evidence']['superseded_leaf_ids']==['door-1']
    assert s['native_door_evidence']['original_leaf_candidates'][1]['arc_cad_id']=='arc-1'
    assert opening_axis(e)[2]==pytest.approx(2.4)
    apply_door_assemblies(doors,[],load_parameters())
    assert len([c for c in e['components'] if c['role']=='jamb'])==2
    assert len([c for c in e['components'] if c['role']=='door_leaf'])==2
    assert all(Polygon(c['polygon']).difference(Polygon(e['polygon'])).area<1e-8 for c in e['components'])
    assert host_opening(box(0,-.05,3,.2),e).bounds[2]==pytest.approx(2.4)
    assert not e['verified']


def test_no_assembly_when_native_frame_or_radius_is_incompatible():
    doors,archive,specs=fixture();archive['scene_entities'][1]['geometry']['closed']=False
    archive['scene_entities'][1]['geometry']['vertices']=archive['scene_entities'][1]['geometry']['vertices'][:-1]
    archive['scene_entities'][1]['geometry']['segments']=archive['scene_entities'][1]['geometry']['segments'][:-1]
    assert native_door_groups(doors,archive,specs)==[]


def test_shared_meeting_point_does_not_make_two_native_leaf_plans_ambiguous():
    doors,a,specs=fixture()
    for n,(lo,hi) in enumerate(((60,1200),(1200,2340))):
        vertices=[[lo,75,0],[hi,75,0],[hi,110,0],[lo,110,0],[lo,75,0]]
        a['scene_entities'].append({'id':'panel-'+str(n),'type':'LWPOLYLINE','support':'full','layer':'A-DOOR',
            'insert_ancestry':['root'],'geometry':{'vertices':vertices,'closed':True,
            'segments':[{'type':'LINE','start':p,'end':q} for p,q in zip(vertices,vertices[1:])]}})
    groups=native_door_groups(doors,a,specs)
    assert len(groups)==1
    assert groups[0]['native_leaf_plans']['door-0']['cad_id']=='panel-0'
    assert groups[0]['native_leaf_plans']['door-1']['cad_id']=='panel-1'
    restore_door_assemblies(doors,a,specs);apply_door_assemblies(doors,[],load_parameters())
    assert all(c['source']['native_leaf_plan']['thickness_m']==pytest.approx(.035)
               for c in doors[0]['components'] if c['role']=='door_leaf')
    doors,archive,specs=fixture();archive['scene_entities'][-1]['geometry']['radius']=2500
    assert native_door_groups(doors,archive,specs)==[]


def test_height_uses_unique_matching_width_and_scope_not_leaf_radius():
    doors,archive,specs=fixture();restore_door_assemblies(doors,archive,specs)
    doors[0]['source']['dimensioned_door_plan_links']=[{'mark':'SSD-3'}]
    cat=[{'mark':'SSD-3','width_m':2.4,'height_m':2.8,'floors':['f1'],'references':[],
          'elevation_lines':[{'points':[[.06,z],[2.34,z]]} for z in (2.1,2.16,2.74,2.8)],'scope_text':'f1'}]
    assert len(apply_door_assemblies(doors,cat,load_parameters()))==1
    e=doors[0]
    assert max(c['z_offset']+c['height'] for c in e['components'])==pytest.approx(2.8)
    assert max(c['height'] for c in e['components'] if c['role']=='door_leaf')==pytest.approx(2.1)
    assert e['source']['door_schedule_assignment']['leaf_head_m']==2.1
    assert any(c['role']=='glass' for c in e['components'])
    for wrong in ('width','scope','ambiguous'):
        es,a,sp=fixture();restore_door_assemblies(es,a,sp)
        es[0]['source']['dimensioned_door_plan_links']=[{'mark':'SSD-3'}]
        c=deepcopy(cat)
        if wrong=='width':c[0]['width_m']=1.2
        if wrong=='scope':c[0]['floors']=['f2']
        if wrong=='ambiguous':c+=deepcopy(c)
        assert apply_door_assemblies(es,c,load_parameters())==[]
        assert es[0]['source']['provisional_opening']['height']==2.1


@pytest.mark.skipif(not Path('cad_output/precision-rebuild/coordination-v2/preview.json').exists(),reason='Rebuild first')
def test_generated_frames_match_native_width_axis_and_bf_portals_without_approval():
    m=json.loads(Path('cad_output/precision-rebuild/coordination-v2/preview.json').read_text(encoding='utf-8'))
    if m['revision']<7:pytest.skip('Whole-building rebuild not finished')
    doors=[e for e in m['elements'] if e['source'].get('native_door_evidence')]
    assert set(e['floor_id'] for e in doors)=={'b1','f1','f2','f3','f4','roof'}
    portal_ids={p['element_id'] for p in m['provenance']['bf_spatial']['portals']}
    for e in doors:
        assert e['id'] in portal_ids and not e['verified']
        evidence=e['source']['native_door_evidence'];a=e['source']['door_plan_axis']
        assert not any(i in portal_ids for i in evidence['superseded_leaf_ids'])
        assert a['width_m']==pytest.approx(evidence['width_m'])
        assert math.hypot(*a['direction'])==pytest.approx(1)
        assert all(Polygon(c['polygon']).difference(Polygon(e['polygon'])).area<1e-6 for c in e['components'])


@pytest.mark.skipif(not Path('cad_output/precision-rebuild/coordination-v2/preview.json').exists(),reason='Rebuild first')
def test_ssd3_native_glass_and_hollow_tube_are_not_solid_leaf_or_full_frame():
    m=json.loads(Path('cad_output/precision-rebuild/coordination-v2/preview.json').read_text(encoding='utf-8'))
    e=next(e for e in m['elements'] if e['id']=='coord-48640c9874f6dd4d4424')
    a=e['source']['door_schedule_assignment'];cs=e['components']
    assert a['width_m']==pytest.approx(2.4)
    assert a['height_m']==pytest.approx(2.8,abs=1e-6)
    panes=[c for c in cs if c['role']=='door_leaf' and c['source']['material']=='glazing']
    assert len(panes)==2
    for c in panes:
        assert c['height']==pytest.approx(1.9)
        assert Polygon(c['polygon']).area==pytest.approx(1.1*.012,abs=1e-6)
        assert c['source']['native_leaf_plan']['thickness_m']==pytest.approx(.035)
    assert len({tuple(c['source']['hinge']) for c in panes})==2
    fixed=next(c for c in cs if c['role']=='glass')
    assert Polygon(fixed['polygon']).area==pytest.approx(2.28*.008,abs=1e-6)
    assert fixed['z_offset']==pytest.approx(2.16)
    assert fixed['height']==pytest.approx(.58)
    for c in cs:
        if c['role']=='jamb':
            assert len(c['holes'])==1
            p=Polygon(c['polygon'],c['holes'])
            assert p.area==pytest.approx(.15*.06-(.15-.003)*(.06-.003),abs=1e-6)
    assert a['frame_tube_applied'] and e['height'] is None and not e['verified']
