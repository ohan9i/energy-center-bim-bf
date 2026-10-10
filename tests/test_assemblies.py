import pytest
from shapely.geometry import Polygon, LineString, box
from bf_bim.architectural_assemblies import load_parameters,refine_assemblies
from bf_bim.schema import Model
from bf_bim.geometry import solid_parts
from bf_bim.precision_model import stair_components
from bf_bim.ifc_export import export_ifc
import ifcopenshell
import ifcopenshell.util.element


def test_slab_finish_preserve_holes_and_finished_floor_level():
    e=dict(id='slab',name='Slab',type='floor',floor_id='f1',polygon=[[0,0],[6,0],[6,6],[0,6]],
        holes=[[[2,2],[4,2],[4,4],[2,4]]],height=None,z_offset=0,components=[],source={})
    p=load_parameters();refine_assemblies([e],p)
    structure,finish=e['components']
    assert structure['z_offset']+structure['height']==pytest.approx(finish['z_offset'])
    assert finish['z_offset']+finish['height']==pytest.approx(0)
    for c in e['components']:
        assert Polygon(c['polygon'],c['holes']).area==pytest.approx(32)
        assert not c['source']['dimension_verified']


def test_door_assembly_and_ifc_preserve_provisional_opening_semantics():
    elements=[dict(id='wall',name='Wall',type='wall',floor_id='f1',polygon=[[0,0],[5,0],[5,.2],[0,.2]],
        height=3,source={'geometry_status':'inferred'},components=[]),
        dict(id='door',name='Door',type='door',floor_id='f1',polygon=[[1,-.15],[2,-.15],[2,.15],[1,.15]],
        height=None,source={'hinge':[1,0],'leaf_end':[2,0]},components=[])]
    p=load_parameters();refine_assemblies(elements,p)
    m=Model.model_validate(dict(id='assembly',name='Assembly',floors=[dict(id='f1',name='1F',elevation=0)],elements=elements,places=[],links=[]))
    assert m.elements[1].height is None
    assert {c.role for c in m.elements[1].components}=={'jamb','head_frame','door_leaf'}
    def area(z):return sum(poly.area for poly,base,depth in solid_parts(m.elements[0],m.elements) if base<=z<base+depth)
    assert area(1)==pytest.approx(.8)
    assert area(2.5)==pytest.approx(1)
    f=ifcopenshell.file.from_string(export_ifc(m))
    assert len(f.by_type('IfcRelVoidsElement'))==1
    assert len(f.by_type('IfcRelFillsElement'))==1
    assert not ifcopenshell.util.element.get_psets(f.by_type('IfcOpeningElement')[0])['Pset_OpeningEvidence']['DimensionVerified']


def test_twelve_riser_stair_meets_intermediate_and_upper_landings():
    nosings=[(LineString([(0,i*.3),(3,i*.3)]),str(i)) for i in range(12)]
    parts,detail=stair_components(nosings,box(0,-1,3,4.3),[{'text':'175 X 12EA'}])
    tops=[c['z_offset']+c['height'] for c in parts if c['role']=='tread']
    assert max(tops)==pytest.approx(4.2-.175)
    assert min(tops)==pytest.approx(.175)
    assert sorted(c['z_offset'] for c in parts if c['role']=='landing')==pytest.approx([0,2.1,4.2])
    assert detail['risers_per_flight']==12


def test_joints_remove_duplicate_solids_without_changing_navigation_footprints():
    from bf_bim.architectural_joints import resolve_joints
    from bf_bim.geometry import architectural_footprint
    import copy
    elements=[dict(id='a',name='A',type='wall',floor_id='f1',polygon=[[0,0],[4,0],[4,.2],[0,.2]],height=3,source={'geometry_status':'inferred','material':'concrete'}),
              dict(id='b',name='B',type='wall',floor_id='f1',polygon=[[2,0],[6,0],[6,.2],[2,.2]],height=3,source={'geometry_status':'inferred','material':'concrete'})]
    original=copy.deepcopy([e['polygon'] for e in elements])
    report=resolve_joints(elements,load_parameters())
    m=Model.model_validate(dict(id='joints',name='Joints',floors=[dict(id='f1',name='1F',elevation=0)],elements=elements,places=[],links=[]))
    a,b=map(architectural_footprint,m.elements)
    assert a.intersection(b).area==pytest.approx(0)
    assert a.union(b).area==pytest.approx(1.2)
    assert [e.polygon for e in m.elements]==[[tuple(v) for v in poly] for poly in original]
    assert report['resolved_wall_junctions']==1


def test_column_junction_closure_preserves_protected_shaft_void():
    from bf_bim.architectural_joints import close_column_face_gaps
    small=box(1,1,2,2);shaft=box(3,3,4,4)
    slab=box(0,0,6,6).difference(small.union(shaft))
    repaired,count=close_column_face_gaps(slab,[box(1.2,1.2,1.8,1.8),box(3.2,3.2,3.8,3.8)],shaft)
    assert count==1
    assert repaired.intersection(small).area==pytest.approx(1)
    assert repaired.intersection(shaft).area==pytest.approx(0)
