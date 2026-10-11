import math
from pathlib import Path
import json

import ezdxf
from ezdxf.math import Vec3, OCS
from fastapi.testclient import TestClient
import pytest

from cad_reader.reader import extract_document
from bf_bim.precise.geometry import sample, to_local, to_cad
from bf_bim.precise.schema import Member, Observation, Reference, Registration, Dimension
from bf_bim.precise.validation import compare_plan, compare_vertical, resolve_dimension, export_verified_ifc
from bf_bim.precise.linking import attach_evidence


def frame(confirmed=False):
    return Registration(id='frame', drawing_id='plan', origin_cad=(30000000,-5000000), scale_m_per_unit=.001,
        status='confirmed' if confirmed else 'local_view',
        control_evidence_ids=['grid-a','grid-b','grid-c'] if confirmed else [], residual_m=0 if confirmed else None)


def fact(identifier='height-a',value=3.2,status='confirmed',field='height',view='section'):
    return Observation(id=identifier,member_id='member',field=field,value=value,unit='m',status=status,interpretation='Explicit test dimension',
        reference=Reference(drawing_id='section',source_sha256='abc',drawing_number='A-021',view=view,
                            cad_ids=['dim:1'],relation='member-specific test match'))


def member():
    return Member(id='member',kind='column',references=[Reference(drawing_id='plan',source_sha256='def',view='plan',
        cad_ids=['poly:1'],relation='native profile')],cad_ids=['poly:1'],plan_polygon=[(0,0),(1,0),(1,1),(0,1)],
        plan_status='measured_geometry',plan_representation='native_linear',verification='plan_only',unknowns=['height','base_elevation'])


def test_nested_reflected_nonuniform_transform_and_curve_data_are_preserved():
    doc=ezdxf.new('R2018');doc.units=4
    inner=doc.blocks.new('inner',base_point=(2,3,0));inner.add_circle((2,3,0),10)
    inner.add_open_spline(control_points=[(0,0,0),(2,3,0),(4,-1,0),(6,0,0)])
    outer=doc.blocks.new('outer');outer.add_blockref('inner',(20,30,0),dxfattribs={'rotation':37,'xscale':-2,'yscale':3})
    doc.modelspace().add_blockref('outer',(30000000,-5000000,0),dxfattribs={'rotation':15,'xscale':.5,'yscale':.5})
    data=extract_document(doc,source=Path('fixture.dxf'),precise_identity=True)
    ellipse=next(e for e in data['scene_entities'] if e['type']=='ELLIPSE')
    assert len(ellipse['insert_ancestry'])==2
    assert ellipse['definition_handle'] is not None
    assert ellipse['geometry']['major_axis']
    inserts=[e for e in data['scene_entities'] if e['type']=='INSERT']
    assert all(len(e['geometry']['block_to_layout_matrix_rows'])==4 for e in inserts)
    points=sample('ELLIPSE',ellipse['geometry'],.05)
    assert Vec3(points[0]).distance(Vec3(points[-1]))<1e-7
    spline=next(e for e in data['scene_entities'] if e['type']=='SPLINE')
    assert len(spline['geometry']['control_points'])==4 and spline['geometry']['knots']
    assert len(sample('SPLINE',spline['geometry'],.01))>4


def test_arc_ocs_and_sagitta_tolerance():
    doc=ezdxf.new();arc=doc.modelspace().add_arc((2,3,0),10,15,270,dxfattribs={'extrusion':(0,.6,.8)})
    from cad_reader.geometry import entity_geometry
    geometry,_=entity_geometry(arc)
    points=sample('ARC',geometry,.01)
    assert Vec3(points[0]).isclose(arc.start_point)
    assert Vec3(points[-1]).isclose(arc.end_point)
    center=Vec3(geometry['center'])
    assert max(abs(Vec3(p).distance(center)-10) for p in points)<1e-9
    assert max(10-(Vec3(a)+Vec3(b)).__truediv__(2).distance(center) for a,b in zip(points,points[1:]))<=.010001


def test_no_implicit_polyline_gap_repair():
    with pytest.raises(ValueError,match='Discontinuous'):
        sample('LWPOLYLINE',{'closed':True,'segments':[
            {'type':'LINE','start':[0,0,0],'end':[1,0,0]},
            {'type':'LINE','start':[1.1,0,0],'end':[1,1,0]}]},.1)


@pytest.mark.parametrize('bulge',[1,-1])
def test_polyline_bulge_direction_follows_native_vertex_order(bulge):
    from cad_reader.geometry import entity_geometry
    from shapely.geometry import Polygon
    poly=ezdxf.new().modelspace().add_lwpolyline([(0,0,bulge),(2,0,0),(2,2,0),(0,2,0)],format='xyb',close=True)
    g,_=entity_geometry(poly)
    points=sample('LWPOLYLINE',g,.0001)
    assert points[0]==pytest.approx(g['vertices'][0])
    assert points[-1]==pytest.approx(g['vertices'][0])
    assert Polygon([(p[0],p[1]) for p in points]).area==pytest.approx(4+bulge*math.pi/2,abs=.001)


def test_nonrepresentable_nested_insert_is_reported_without_losing_raw_definition():
    doc=ezdxf.new()
    doc.blocks.new('inner').add_circle((0,0),1)
    doc.blocks.new('outer').add_blockref('inner',(0,0),dxfattribs={'rotation':45})
    doc.modelspace().add_blockref('outer',(0,0),dxfattribs={'xscale':2,'yscale':1})
    data=extract_document(doc,source=Path('shear.dxf'),precise_identity=True)
    assert any(w['code']=='BLOCK_ENTITIES_SKIPPED' for w in data['warnings'])
    assert any(block['name']=='inner' for block in data['blocks'])
    assert not data['coverage']['full_dwg_fidelity_verified']


def test_archived_transform_approximation_is_detected_and_not_used():
    from bf_bim.precise.transform_check import check_transforms
    doc=ezdxf.new()
    doc.blocks.new('inner').add_circle((0,0),1)
    doc.blocks.new('outer').add_blockref('inner',(0,0),dxfattribs={'rotation':45})
    doc.modelspace().add_blockref('outer',(0,0),dxfattribs={'xscale':2,'yscale':1})
    # Exercise the old library expansion as an archive compatibility case.
    data=extract_document(doc,source=Path('old.dxf'))
    assert check_transforms(data)
    assert any(w['code']=='BLOCK_TRANSFORM_LOSS' for w in data['warnings'])
    assert any(e.get('precision_geometry_blocked') for e in data['scene_entities'])


def test_registration_roundtrip_and_real_mismatch_detection():
    f=frame();f.rotation_rad=.43
    point=[30001734,-4999763,0]
    assert to_cad(to_local(point,f),f)==pytest.approx(point[:2],abs=1e-7)
    f=frame();m=member()
    native={'id':'poly:1','type':'LWPOLYLINE','geometry':{'closed':True,'segments':[
        {'type':'LINE','start':[30000000+a[0]*1000,-5000000+a[1]*1000,0],
         'end':[30000000+b[0]*1000,-5000000+b[1]*1000,0]}
        for a,b in zip(m.plan_polygon,m.plan_polygon[1:]+m.plan_polygon[:1])]}}
    assert compare_plan(m,native,f)['status']=='match'
    m.plan_polygon=[(x+.01,y) for x,y in m.plan_polygon]
    comparison=compare_plan(m,native,f)
    assert comparison['status']=='mismatch'
    assert comparison['boundary_distance_m']==pytest.approx(.01)
    assert comparison['symmetric_difference_m2']==pytest.approx(.02)


def test_common_registration_requires_revision_checked_noncollinear_controls():
    from bf_bim.precise.registration import register_controls
    original=frame();original.rotation_rad=.4
    points=[[30000000,-5000000],[30001000,-5000000],[30000000,-4999000]]
    controls=[]
    for i,p in enumerate(points):
        observation=fact(f'grid-{i}',field='grid_control',view='plan')
        observation.reference.drawing_id='plan'
        observation.value={'cad_xy':p,'model_xy_m':to_local(p,original)}
        controls.append(observation)
    registered=register_controls('registered','plan',.001,controls,{'plan':'abc'})
    assert registered.status=='confirmed' and registered.residual_m<1e-7
    assert registered.rotation_rad==pytest.approx(.4)
    controls[-1].value['model_xy_m'][0]+=.02
    with pytest.raises(ValueError,match='residual'):
        register_controls('bad','plan',.001,controls,{'plan':'abc'})
    with pytest.raises(ValueError,match='revision'):
        register_controls('old','plan',.001,controls,{'plan':'old'})


def test_unassigned_schedule_never_resolves_and_conflicts_never_pick_a_value():
    assert resolve_dimension('height',[fact(status='candidate')]).value is None
    conflict=resolve_dimension('height',[fact(),fact('height-b',3.4)])
    assert conflict.status=='conflict' and conflict.value is None
    with pytest.raises(ValueError): Dimension(value=4.2,status='unknown')
    with pytest.raises(ValueError):
        attach_evidence(member(),[fact()],drawing_hashes={'section':'abc'},member_match_confirmed=False)
    with pytest.raises(ValueError,match='revision'):
        attach_evidence(member(),[fact()],drawing_hashes={'section':'old'},member_match_confirmed=True)
    result=attach_evidence(member(),[fact(),fact('height-b',3.4)],drawing_hashes={'section':'abc'},member_match_confirmed=True)
    assert result.verification=='conflict' and result.dimensions['height'].value is None


def test_vertical_missing_registration_conflict_and_mismatch_are_distinct():
    m=member();m.dimensions['height']=Dimension(value=3.2,status='confirmed',evidence_ids=['height-a'])
    assert compare_vertical(m,[fact()],None)['status']=='insufficient_source'
    result=compare_vertical(m,[fact('section-height',3.25)],frame(True))
    assert result['status']=='mismatch' and result['fields']['height']['delta_m']==pytest.approx(-.05)
    result=compare_vertical(m,[fact(),fact('contradiction',3.4)],frame(True))
    assert result['status']=='source_conflict'


def test_verified_status_and_ifc_reject_plan_only_or_temporary_geometry():
    m=member()
    with pytest.raises(ValueError,match='registration'):
        export_verified_ifc([m],[],frame())
    with pytest.raises(ValueError,match='verified solid'):
        export_verified_ifc([m],[],frame(True))
    with pytest.raises(ValueError):
        Member.model_validate({**m.model_dump(),'verification':'verified'})


def test_fully_evidenced_solid_exports_without_preview_dimensions():
    import ifcopenshell
    from ifcopenshell import validate
    observations=[fact(),fact('base',0,field='base_elevation'),
                  fact('plan',status='confirmed',field='plan_geometry',view='plan'),
                  fact('kind',status='confirmed',field='member_kind',view='structure')]
    for i,point in zip(('grid-a','grid-b','grid-c'),[[30000000,-5000000],[30001000,-5000000],[30000000,-4999000]]):
        control=fact(i,field='grid_control',view='plan')
        control.member_id=None;control.reference.drawing_id='plan'
        control.value={'cad_xy':point,'model_xy_m':to_local(point,frame(True))}
        observations.append(control)
    m=member()
    observations[2].value={'native_id':'poly:1','polygon_m':m.plan_polygon,'registration_id':'frame'}
    observations[2].reference.cad_ids=['poly:1']
    observations[3].value='column'
    m.kind_status='confirmed';m.plan_status='confirmed';m.unknowns=[]
    m.dimensions['height']=resolve_dimension('height',observations)
    m.dimensions['base_elevation']=resolve_dimension('base_elevation',observations)
    m.evidence_ids=[e.id for e in observations[:4]];m.verification='verified'
    text=export_verified_ifc([m],observations,frame(True))
    f=ifcopenshell.file.from_string(text)
    assert len(f.by_type('IfcColumn'))==1
    assert {solid.Depth for solid in f.by_type('IfcExtrudedAreaSolid')}=={3.2}
    logger=validate.json_logger();validate.validate(f,logger,express_rules=True)
    assert not logger.statements
    m.plan_representation='native_curved'
    with pytest.raises(ValueError,match='Analytic curved IFC'):
        export_verified_ifc([m],observations,frame(True))
    m.plan_representation='native_linear'
    observations[0].status='candidate'
    with pytest.raises(ValueError,match='Unconfirmed'):
        export_verified_ifc([m],observations,frame(True))


def test_precision_api_is_readonly_and_does_not_accept_arbitrary_paths(tmp_path,monkeypatch):
    import bf_bim.app as api
    monkeypatch.setattr(api,'PRECISION_DIR',tmp_path)
    (tmp_path/'pilot.json').write_text('{"members":[]}',encoding='utf-8')
    client=TestClient(api.app)
    assert client.get('/api/precision/pilot').json()=={'members':[]}
    assert client.get('/api/precision/arbitrary').status_code==404
    assert client.post('/api/precision/pilot',json={}).status_code==405
    assert client.get('/api/health').status_code==200


def test_chunked_cad_archive_preserves_native_values_and_cannot_overwrite_legacy(tmp_path,monkeypatch):
    from bf_bim.precise import stage1
    folder=tmp_path/'precision'
    monkeypatch.setattr(stage1,'OUTPUT',folder)
    native={'scene_entities':[{'id':'spline','weights':[1,.7071067811865476,1],
                              'knots':[0,0,0,1,1,1],'layer':'구조벽','closed':False}],
            'blocks':[{'name':'nested','matrix':[[1,0,0,0],[0,1,0,0],[0,0,1,0],[30000000,-5000000,0,1]]}],
            'source':{'original_unchanged':True}}
    stage1.write(folder/'drawing.json.gz',native)
    assert stage1.read(folder/'drawing.json.gz')==native
    legacy=tmp_path/'legacy.dwg';legacy.write_bytes(b'original dwg bytes')
    with pytest.raises(ValueError,match='precision-stage1'):
        stage1.write(legacy,native)
    assert legacy.read_bytes()==b'original dwg bytes'


@pytest.mark.skipif(not Path('cad_output/precision-stage1/pilot.json').exists(),reason='Private CAD pilot unavailable')
def test_actual_pilot_has_evidence_and_never_invents_height():
    folder=Path('cad_output/precision-stage1')
    pilot=json.loads((folder/'pilot.json').read_text(encoding='utf-8'))
    observations={e['id']:e for e in json.loads((folder/'observations.json').read_text(encoding='utf-8'))}
    native={e['id']:e for e in pilot['native_entities']}
    assert len(pilot['members'])>0 and pilot['summary']['plan_profiles']>0
    for raw in pilot['members']:
        m=Member.model_validate(raw)
        assert m.references and all(c in native for c in m.cad_ids)
        assert all(e in observations for e in m.evidence_ids)
        assert all(d.value is None for d in m.dimensions.values())
        assert m.verification!='verified'
        if m.plan_polygon:
            assert compare_plan(m,native[m.cad_ids[0]],Registration.model_validate(pilot['registration']))['status']=='match'
    assert pilot['preview_members']==[]
    manifest=json.loads((folder/'drawings.json').read_text(encoding='utf-8'))
    assert len(manifest)==30 and all(d['hash_matches_audit'] for d in manifest)
