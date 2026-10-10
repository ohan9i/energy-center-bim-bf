import json
from pathlib import Path
import pytest
import ifcopenshell
import ifcopenshell.util.element
import ifcopenshell.validate
from shapely.geometry import Polygon
from bf_bim.schema import Model
from bf_bim.geometry import solid_parts
from bf_bim.ifc_export import export_ifc

def fixture():
    return Model.model_validate(dict(id='architectural-fixture',name='Architectural evidence test',
        floors=[dict(id='f1',name='1F',elevation=0)],places=[],links=[],elements=[
        dict(id='wall',name='Wall',type='wall',floor_id='f1',polygon=[[0,0],[6,0],[6,.2],[0,.2]],height=3,source={'geometry_status':'inferred'}),
        dict(id='door',name='Door',type='door',floor_id='f1',polygon=[[1,-.1],[2,-.1],[2,.3],[1,.3]],height=2.1),
        dict(id='window',name='Window',type='window',floor_id='f1',polygon=[[3,-.1],[5,-.1],[5,.3],[3,.3]],height=1.2,z_offset=.9),
        dict(id='stair',name='Stair',type='stair',floor_id='f1',polygon=[[0,2],[2,2],[2,4],[0,4]],height=3,components=[
            dict(role='tread',polygon=[[0,2],[1,2],[1,2.3],[0,2.3]],height=.175,z_offset=.175),
            dict(role='landing',polygon=[[0,3],[2,3],[2,4],[0,4]],height=None,z_offset=1.5)])]))

def test_architectural_openings_preserve_sill_and_lintel():
    m=fixture();wall=m.elements[0];parts=solid_parts(wall,m.elements)
    def area_at(z):return sum(p.area for p,base,depth in parts if base<=z<base+depth)
    assert area_at(.5)==pytest.approx(1.)  # Door cut only; window sill retained.
    assert area_at(1.5)==pytest.approx(.6) # Both openings.
    assert area_at(2.5)==pytest.approx(1.2) # Lintel / wall above openings.

def test_unknown_window_does_not_invent_head_or_sill_geometry():
    m=fixture();m.elements[2].height=None
    parts=solid_parts(m.elements[0],m.elements)
    assert sum(p.area for p,z,h in parts if z<=1.5<z+h)==pytest.approx(1.)
    assert solid_parts(m.elements[2],m.elements)[0][2] is None

def test_ifc_stair_parts_landings_materials_and_window_class():
    f=ifcopenshell.file.from_string(export_ifc(fixture()))
    assert len(f.by_type('IfcWindow'))==1
    assert len(f.by_type('IfcBuildingElementPart'))==2
    assert len(f.by_type('IfcMaterial'))>0
    stair=f.by_type('IfcStair')[0]
    assert len(stair.IsDecomposedBy[0].RelatedObjects)==2
    landing=next(p for p in f.by_type('IfcBuildingElementPart') if ifcopenshell.util.element.get_psets(p)['Pset_ArchitecturalEvidence']['Role']=='landing')
    assert landing.Representation.Representations[0].RepresentationType=='SurfaceModel'
    logger=ifcopenshell.validate.json_logger();ifcopenshell.validate.validate(f,logger,express_rules=True)
    assert not logger.statements

@pytest.mark.skipif(not Path('cad_output/energy-center-model.json').exists(),reason='Private CAD model unavailable')
def test_actual_model_cores_courtyard_and_unknowns():
    from bf_bim.precision_model import COURTYARD
    m=Model.model_validate_json(Path('cad_output/energy-center-model.json').read_text(encoding='utf-8'))
    assert [f.elevation for f in m.floors]==pytest.approx([-3.9,0,4.2,8.4,12.6,16.8])
    for fid in ('f1','f2','f3','f4'):
        assert sum(e.type=='stair' and e.floor_id==fid for e in m.elements)==2
        for e in m.elements:
            if e.floor_id==fid and e.type=='floor':assert Polygon(e.polygon,e.holes).intersection(COURTYARD).area<.003
    assert all(e.height is None for e in m.elements if e.type in ('door','window'))
    assert any(e.type=='space' for e in m.elements)
    assert m.links==[]


@pytest.mark.skipif(not Path('cad_output/S04-001-evidence.json').exists(),reason='Private column schedule unavailable')
def test_column_schedule_candidates_do_not_assign_ambiguous_members():
    from bf_bim.drawing_evidence import collect_evidence,annotate_columns
    source=json.loads(Path('cad_output/S04-001-evidence.json').read_text(encoding='utf-8'))
    evidence=collect_evidence([source]);rows={r['mark']:r for r in evidence['column_sections']}
    assert rows['C1']['dimensions_m']==pytest.approx([.6,.6])
    assert rows['C2']['dimensions_m']==pytest.approx([.5,.6])
    assert rows['C6']['shape']=='circular' and rows['C6']['dimensions_m']==pytest.approx([.5])
    e=dict(type='column',polygon=[[0,0],[.5,0],[.5,.5],[0,.5]],holes=[],height=None,source={'cad_id':'section'})
    annotate_columns([e],evidence,{'section':{'type':'LWPOLYLINE'}})
    assert {r['mark'] for r in e['source']['structural_section_candidates']}=={'C3','C4'}
    assert all(not r['member_assignment_verified'] for r in e['source']['structural_section_candidates'])
    assert e['height'] is None
