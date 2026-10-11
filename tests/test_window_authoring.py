import json
from pathlib import Path

import ifcopenshell
import pytest
from shapely.geometry import Polygon, box

from bf_bim.precise.window_authoring import recover_plan_frames, window_catalog, apply_window_schedules
from bf_bim.schema import Model
from bf_bim.ifc_export import export_ifc


def entity(identity,kind,geometry,layer='A-DOOR',ancestry=None):
    return dict(id=identity,type=kind,geometry=geometry,effective_layer=layer,support='full',insert_ancestry=ancestry or [])


def line(identity,a,b,ancestry=None):
    return entity(identity,'LINE',{'start':[*a,0],'end':[*b,0]},ancestry=ancestry)


def rectangle(identity,x0,y0,x1,y1,ancestry=None,closed=True):
    points=[(x0,y0),(x1,y0),(x1,y1),(x0,y1),(x0,y0)]
    return entity(identity,'LWPOLYLINE',{'closed':closed,'vertices':[[*p,0] for p in points],
        'segments':[{'type':'LINE','start':[*a,0],'end':[*b,0]} for a,b in zip(points,points[1:])]},ancestry=ancestry)


def test_plan_frame_restores_omitted_jambs_without_using_a_block_name_size():
    e={'id':'w','type':'window','floor_id':'f1','polygon':list(box(.06,0,1.74,.15).exterior.coords)[:-1],
       'source':{'cad_ids':['block'],'file':'plan','source_sha256':'hash','window_plan_axis':
                 {'origin':[.9,.075],'direction':[1,0],'width_m':1.68,'depth_m':.15}}}
    curves=[entity('block','INSERT',{'block_name':'untrusted-name-9999'}),
            rectangle('j1',0,0,60,150,['block'],closed=False),rectangle('j2',1740,0,1800,150,['block']),
            line('bottom',(0,0),(1800,0),['block']),line('top',(0,150),(1800,150),['block'])]
    report=recover_plan_frames([e],{'scene_entities':curves,'warnings':[]},{'f1':{'id':'f1','origin':[0,0]}})
    assert len(report)==1
    assert e['source']['window_plan_axis']['width_m']==pytest.approx(1.8)
    assert Polygon(e['polygon']).area==pytest.approx(.27)
    assert report[0]['jamb_width_m']==pytest.approx(.06)
    # Missing a native outside face must not be replaced by guessed geometry.
    e['source']['cad_ids']=['block'];curves=curves[:2]
    assert not recover_plan_frames([e],{'scene_entities':curves,'warnings':[]},{'f1':{'id':'f1','origin':[0,0]}})


def schedule_fixture():
    es=[entity('tag','TEXT',{'text':'AW','insert':[0,0,0]}),entity('number','TEXT',{'text':'6','insert':[150,330,0]}),
        entity('scope','TEXT',{'text':'1F : 사무실','insert':[900,-825,0]}),
        entity('glass','TEXT',{'text':'THK24 복층유리','insert':[900,-425,0]}),
        rectangle('outer',2300,3250,3200,4850),line('jleft',(2360,3250),(2360,4850)),
        line('jright',(3140,3250),(3140,4850)),line('sill',(2360,3310),(3140,3310)),
        line('head',(2360,4790),(3140,4790)),line('rail-low',(2360,3890),(3140,3890)),
        line('rail-high',(2360,3950),(3140,3950))]
    for identity,a,b in [('width',(2300,5550),(3200,5550)),('height',(1700,2050),(1700,4850))]:
        es.append(entity(identity,'DIMENSION',{'definition_points_raw':{'defpoint2':[*a,0],'defpoint3':[*b,0]},
            'measurement':max(abs(a[0]-b[0]),abs(a[1]-b[1])),'text_override':''}))
    return {'scene_entities':es,'warnings':[]},{'file':'A10.dwg','sha256':'hash'}


def test_catalog_distinguishes_overall_datum_height_from_window_height_and_sill():
    archive,row=schedule_fixture();catalog=window_catalog(archive,row)
    assert len(catalog)==1
    c=catalog[0]
    assert c['datum_to_head_m']==pytest.approx(2.8)
    assert c['height_m']==pytest.approx(1.6)
    assert c['sill_m']==pytest.approx(1.2)
    assert c['glass_thickness_m']==pytest.approx(.024)
    assert len([r for r in c['regions'] if r['role']=='glass'])==2
    archive['scene_entities'][-1]['geometry']['text_override']='3000'
    assert not window_catalog(archive,row)


def test_schedule_requires_unique_mark_floor_scope_and_matching_native_frame_width():
    archive,row=schedule_fixture();catalog=window_catalog(archive,row)
    def window(width=.9,floor='f1'):
        return {'id':'w','type':'window','floor_id':floor,'polygon':list(box(0,0,width,.15).exterior.coords)[:-1],
            'source':{'window_plan_axis':{'origin':[width/2,.075],'direction':[1,0],'width_m':width,'depth_m':.15},
            'native_frame_evidence':{'width_m':width},'plan_schedule_links':[{'mark':'AW-6'}],
            'property_status':{},'assumptions':{'window_height':{'value_m':2.4}}},'components':[]}
    for e,c in [(window(.8),catalog),(window(floor='f4'),catalog),(window(),catalog*2)]:
        assert not apply_window_schedules([e],c)
        assert not e['components']
    e=window();assert apply_window_schedules([e],catalog)
    assert min(c['z_offset'] for c in e['components'])==pytest.approx(1.2)
    assert max(c['z_offset']+c['height'] for c in e['components'])==pytest.approx(2.8)
    assert 'window_height' not in e['source']['assumptions']
    assert not e['source']['provisional_opening']['dimension_verified']


def test_double_glazing_models_only_documented_panes_and_leaves_the_argon_gap_empty():
    archive,row=schedule_fixture()
    archive['scene_entities'][3]['geometry']['text']='THK24 로이복층유리 5LE(더블로이)+14AR+5CL'
    catalog=window_catalog(archive,row)
    assert catalog[0]['glazing_build_up_m']==[.005,.014,.005]
    e={'id':'w','type':'window','floor_id':'f1','source':{
        'window_plan_axis':{'origin':[.45,.075],'direction':[1,0],'width_m':.9,'depth_m':.15},
        'native_frame_evidence':{},'plan_schedule_links':[{'mark':'AW-6'}],'property_status':{}},'components':[]}
    e['source']['native_frame_evidence']={'width_m':.9,'parallel_faces':[
        {'offset_m':.051,'cad_ids':['inside']},{'offset_m':.075,'cad_ids':['outside']}]}
    assert apply_window_schedules([e],catalog)
    panes=[c for c in e['components'] if c['role']=='glass']
    assert len(panes)==4
    assert all(Polygon(c['polygon']).bounds[3]-Polygon(c['polygon']).bounds[1]==pytest.approx(.005) for c in panes)
    first,second=panes[:2]
    assert Polygon(second['polygon']).bounds[1]-Polygon(first['polygon']).bounds[3]==pytest.approx(.014)
    assert Polygon(first['polygon']).bounds[1]==pytest.approx(.126)
    assert Polygon(second['polygon']).bounds[3]==pytest.approx(.15)


def test_ifc_keeps_component_wall_geometry_and_exports_semantic_host_void_and_type():
    wall={'id':'wall','name':'wall','type':'wall','floor_id':'f1','polygon':list(box(0,0,3,.2).exterior.coords)[:-1],
          'source':{'assumptions':{'height':{'value_m':4.2}}},'components':[
            {'id':'body','role':'wall_body','polygon':list(box(0,0,3,.2).exterior.coords)[:-1],
             'height':1.4,'z_offset':2.8}]}
    window={'id':'window','name':'window','type':'window','floor_id':'f1','polygon':list(box(1,0,2,.2).exterior.coords)[:-1],
        'source':{'provisional_opening':{'height':2.8,'z_offset':0},'host_openings':[
          {'host_wall_id':'wall','polygon':list(box(1,0,2,.2).exterior.coords)[:-1]}],
          'type_definition':{'kind':'window','mark':'AW-1','width_m':1,'height_m':2.8,
                             'glass_thickness_m':.024,'status':'drawing_correlated_not_design_approved'}},
        'components':[{'id':'glass','role':'glass','polygon':list(box(1,.088,2,.112).exterior.coords)[:-1],
                       'height':2.8}]}
    m=Model(id='m',name='m',floors=[{'id':'f1','name':'f1','elevation':0}],elements=[wall,window],places=[],links=[],
            provenance={'export_status':'coordination_draft'})
    f=ifcopenshell.file.from_string(export_ifc(m,coordination_draft=True))
    assert len(f.by_type('IfcOpeningElement'))==1
    assert len(f.by_type('IfcRelVoidsElement'))==1
    assert len(f.by_type('IfcRelFillsElement'))==1
    assert len(f.by_type('IfcWindowType'))==1
    assert len(f.by_type('IfcRelDefinesByType'))==1
    assert f.by_type('IfcWall')[0].Representation is None
    assert len(f.by_type('IfcBuildingElementPart'))==2


@pytest.mark.skipif(not Path('cad_output/precision-rebuild/coordination-v2/preview.json').exists(),reason='Generate model first')
def test_generated_schedule_assignment_has_independent_native_plan_and_elevation_evidence():
    m=json.loads(Path('cad_output/precision-rebuild/coordination-v2/preview.json').read_text(encoding='utf-8'))
    if m['revision']<6:pytest.skip('Authoring rebuild not finished')
    assigned=[e for e in m['elements'] if e['source'].get('schedule_assignment')]
    assert len(assigned)>=4 and {'f1','f2'}<=set(e['floor_id'] for e in assigned)
    for e in assigned:
        s=e['source'];a=s['schedule_assignment']
        assert a['width_residual_m']<.002 and e['floor_id'] in a['floors']
        assert s['native_frame_evidence']['source_sha256']!=a['references'][0]['source_sha256']
        assert not e['verified'] and not s['design_assignment_verified']
        assert not any(k in s['assumptions'] for k in ['window_height','window_sill','glass_thickness'])
        placement=a['glazing_plan_placement']
        assert placement['status']=='drawing_correlated'
        lo,hi=placement['normal_bounds_m']
        assert hi-lo==pytest.approx(a['glass_thickness_m'])
        axis=s['window_plan_axis'];cx,cy=axis['origin'];ux,uy=axis['direction']
        panes=[c for c in e['components'] if c['role']=='glass']
        offsets=[-(x-cx)*uy+(y-cy)*ux for c in panes for x,y in c['polygon']]
        # Published polygons use micrometre precision, including rotated faces.
        assert min(offsets)==pytest.approx(lo,abs=1e-6)
        assert max(offsets)==pytest.approx(hi,abs=1e-6)
