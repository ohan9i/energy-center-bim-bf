import io
import json
from pathlib import Path
import pytest
import ezdxf
import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.element
import ifcopenshell.validate
from fastapi.testclient import TestClient
from shapely.geometry import Polygon
from bf_bim.app import app
from bf_bim.example import example_model
from bf_bim.ifc_export import export_ifc
from bf_bim.geometry import footprint
from bf_bim.schema import Model
from bf_bim.cad import build_model
from cad_reader import analyze_drawing

def dxf_file(path,units=6):
    d=ezdxf.new('R2018');d.units=units
    for name in ('A-FLOOR','A-WALL','A-DOOR','A-ROOM'):d.layers.new(name)
    ms=d.modelspace()
    ms.add_lwpolyline([(0,0),(10,0),(10,8),(0,8)],close=True,dxfattribs={'layer':'A-FLOOR'})
    ms.add_lwpolyline([(4,0),(4.2,0),(4.2,8),(4,8)],close=True,dxfattribs={'layer':'A-WALL'})
    ms.add_line((3.8,3),(4.4,3),dxfattribs={'layer':'A-DOOR'})
    d.saveas(path)

def test_cad_pipeline_units_ids_and_unknowns(tmp_path):
    path=tmp_path/'test.dxf';dxf_file(path)
    raw=analyze_drawing(path);m=build_model(raw,{},None,3,.2)
    assert raw['source']['original_unchanged']
    assert {e.type for e in m.elements}=={'floor','wall','door'}
    assert all(not e.verified for e in m.elements)
    assert next(e for e in m.elements if e.type=='door').properties.clear_width is None
    assert [e.id for e in m.elements]==[e.id for e in build_model(raw,{},None,3,.2).elements]

def test_unknown_units_require_input(tmp_path):
    path=tmp_path/'test.dxf';dxf_file(path,0);d=analyze_drawing(path)
    with pytest.raises(ValueError,match='단위'):build_model(d,{},None,3,.2)
    assert build_model(d,{},.001,3,.2).elements

def test_api_upload_build_ifc_and_errors(tmp_path):
    client=TestClient(app)
    assert client.get('/api/health').status_code==200
    assert client.post('/api/cad/analyze',files={'file':('bad.txt',b'hello')}).status_code==415
    assert client.post('/api/cad/analyze',files={'file':('bad.dwg',b'not a dwg')}).status_code==422
    path=tmp_path/'fixture.dxf';dxf_file(path)
    r=client.post('/api/cad/analyze',files={'file':('fixture.dxf',path.read_bytes())});assert r.status_code==200
    token=r.json()['token'];result=client.post('/api/cad/build',json={'token':token,'mapping':{},'height':3,'thickness':.2})
    assert result.status_code==200
    assert client.post('/api/ifc',json=result.json()).status_code==200
    assert client.get(f'/api/cad/{token}/report').status_code==200
    assert client.post('/api/cad/build',json={'token':'missing','mapping':{},'height':3,'thickness':.2}).status_code==410

def test_ifc_world_coordinates_and_geometry_consistency():
    model=example_model();f=ifcopenshell.file.from_string(export_ifc(model))
    assert f.schema=='IFC4'
    assert f.by_type('IfcSIUnit')[0].Prefix is None
    settings=ifcopenshell.geom.settings();settings.set(settings.USE_WORLD_COORDS,True)
    floor_elev={x.id:x.elevation for x in model.floors}
    for e in model.elements:
        if e.height is None:continue
        obj=next(x for x in f.by_type('IfcProduct') if ifcopenshell.util.element.get_psets(x).get('Pset_BFNavigation',{}).get('ModelElementId')==e.id)
        s=ifcopenshell.geom.create_shape(settings,obj)
        vertices=list(zip(*[iter(s.geometry.verts)]*3));g=footprint(e,model.elements)
        assert min(p[0] for p in vertices)==pytest.approx(g.bounds[0])
        assert min(p[1] for p in vertices)==pytest.approx(g.bounds[1])
        assert max(p[0] for p in vertices)==pytest.approx(g.bounds[2])
        assert max(p[1] for p in vertices)==pytest.approx(g.bounds[3])
        assert min(p[2] for p in vertices)==pytest.approx(floor_elev[e.floor_id]+e.z_offset)
        assert max(p[2] for p in vertices)==pytest.approx(floor_elev[e.floor_id]+e.z_offset+e.height)
    second=ifcopenshell.file.from_string(export_ifc(model))
    assert sorted(x.GlobalId for x in f.by_type('IfcRoot'))==sorted(x.GlobalId for x in second.by_type('IfcRoot')) or sorted(x.GlobalId for x in f.by_type('IfcProduct'))==sorted(x.GlobalId for x in second.by_type('IfcProduct'))

def test_validation():
    m=example_model().model_dump();m['elements'][0]['polygon']=[(0,0),(2,2),(0,2),(2,0)]
    with pytest.raises(ValueError):Model.model_validate(m)

def test_wall_opening_geometry():
    m=example_model();wall=next(e for e in m.elements if e.id=='f1-wall-강의실 칸막이')
    door=next(e for e in m.elements if e.id=='f1-door-class')
    assert footprint(wall,m.elements).intersection(Polygon(door.polygon)).area==0

def test_ifc_express_schema():
    logger=ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(ifcopenshell.file.from_string(export_ifc(example_model())),logger,express_rules=True)
    assert not logger.statements

def test_unknown_height_exports_footprint_without_invented_thickness():
    model=example_model()
    e=next(e for e in model.elements if e.id=='f2-floor');e.height=None
    f=ifcopenshell.file.from_string(export_ifc(model))
    logger=ifcopenshell.validate.json_logger();ifcopenshell.validate.validate(f,logger,express_rules=True)
    assert not logger.statements
    obj=next(x for x in f.by_type('IfcSlab') if ifcopenshell.util.element.get_psets(x)['Pset_BFNavigation']['ModelElementId']==e.id)
    settings=ifcopenshell.geom.settings();settings.set(settings.USE_WORLD_COORDS,True)
    vertices=list(zip(*[iter(ifcopenshell.geom.create_shape(settings,obj).geometry.verts)]*3))
    assert vertices
    assert all(p[2]==pytest.approx(3.3+e.z_offset) for p in vertices)
