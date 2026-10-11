from pathlib import Path
import math

import ezdxf
import pytest
from shapely.geometry import LineString,Polygon

from bf_bim.precise.rebuild import topological_profiles,native_profile,column_alignment,safe
from bf_bim.precise.geometry import sample_hatch_paths,sample
from bf_bim.precise.schema import Registration
from cad_reader.geometry import entity_geometry
from bf_bim.schema import Model
from bf_bim.ifc_export import export_ifc


def test_topology_accepts_closed_faces_but_never_bridges_gap_or_merges_materials():
    records=[(LineString([a,b]),str(i)) for i,(a,b) in enumerate([
        ((0,0),(3,0)),((3,0),(3,.2)),((3,.2),(0,.2)),((0,.2),(0,0))])]
    result=topological_profiles(records)
    assert len(result)==1 and result[0][0].area==pytest.approx(.6)
    assert result[0][1]==['0','1','2','3']
    broken=records[:3]+[(LineString([(0,.2),(0,.01)]),'3')]
    assert topological_profiles(broken)==[]
    # Room boundary is not a wall or structural slab.
    assert topological_profiles([(LineString([(0,0),(10,0),(10,10),(0,10),(0,0)]),'room')])==[]


def test_curved_column_profile_retains_shape_and_nonzero_cad_origin():
    frame=Registration(id='f',drawing_id='d',origin_cad=(30000000,-5000000),scale_m_per_unit=.001)
    line,poly=native_profile({'type':'CIRCLE','geometry':{'center':[30001000,-4998000,0],'radius':300}},frame)
    assert poly.centroid.x==pytest.approx(1,abs=1e-9)
    assert poly.centroid.y==pytest.approx(2,abs=1e-9)
    assert poly.area==pytest.approx(math.pi*.3**2,rel=.003)
    assert len(line.coords)>30


def test_xclip_and_transform_loss_fail_closed():
    e={'support':'full','insert_ancestry':['parent']}
    assert safe(e,set())
    assert not safe(e,{'parent'})
    assert not safe({**e,'precision_geometry_blocked':True},set())


def test_collinear_alignment_cannot_verify_2d_controls():
    points=[{'id':str(i),'center':[i,0],'sizes':{}} for i in range(5)]
    assert column_alignment(points,points)['status']=='insufficient_controls'
    points[-1]['center']=[0,1]
    assert column_alignment(points,points)['status']=='geometry_controls_match'
    shifted=[{**p,'center':[p['center'][0]+.01,p['center'][1]]} for p in points]
    assert column_alignment(points,shifted)['status']=='insufficient_controls'


def test_hatch_preserves_holes_negative_bulge_and_ocs_elevation():
    doc=ezdxf.new();hatch=doc.modelspace().add_hatch(dxfattribs={'elevation':(0,0,7),'extrusion':(0,.6,.8)})
    hatch.paths.add_polyline_path([(0,0,-1),(2,0,0),(2,2,0),(0,2,0)],is_closed=True,flags=1)
    hatch.paths.add_polyline_path([(.5,.5),(1,.5),(1,1),(.5,1)],is_closed=True,flags=0)
    g,support=entity_geometry(hatch)
    assert support=='partial' and g['pattern_support']=='not_expanded'
    loops=sample_hatch_paths(g,.001)
    assert len(loops)==2 and len(loops[0]['points'])>10
    from ezdxf.math import OCS,Vec3
    ocs=OCS(g['normal'])
    assert max(abs(ocs.from_wcs(Vec3(p)).z-7) for loop in loops for p in loop['points'])<1e-9
    with pytest.raises(ValueError,match='explicit OCS'):sample_hatch_paths({'boundary_paths_ocs':[]},.1)


def test_fit_only_spline_without_tangents_remains_unresolved():
    g={'degree':3,'fit_points':[(0,0,0),(1,2,0),(3,0,0)]}
    with pytest.raises(ValueError,match='explicit endpoint tangents'):sample('SPLINE',g,.001)
    points=sample('SPLINE',{**g,'start_tangent':[1,0,0],'end_tangent':[1,0,0]},.001)
    assert len(points)>10 and points[0]==pytest.approx((0,0,0))
    assert points[-1]==pytest.approx((3,0,0))


def test_precision_preview_cannot_leak_into_generic_ifc_export():
    m=Model(id='p',name='p',floors=[{'id':'f','name':'F','elevation':0}],elements=[],places=[],links=[],provenance={'precision_rebuild':True})
    with pytest.raises(ValueError,match='verified.ifc'):export_ifc(m)
