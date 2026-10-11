from shapely.geometry import Polygon, box
from shapely.ops import unary_union
import pytest

from bf_bim.precise.window_geometry import constrain_windows, native_segments, audit_window_profiles
from bf_bim.precise.coordination_quality import host_opening
from bf_bim.architectural_assemblies import refine_assemblies, load_parameters


def bent_window():
    profile=box(0,0,5,.15).union(box(0,0,.15,2))
    entities=[]
    for i,(a,b) in enumerate([((0,0),(5,0)),((0,.15),(5,.15)),((0,0),(0,2)),((.15,0),(.15,2))]):
        entities.append({'id':str(i),'type':'LINE','support':'full',
                         'geometry':{'start':[30000000+a[0]*1000,-5000000+a[1]*1000,0],
                                     'end':[30000000+b[0]*1000,-5000000+b[1]*1000,0]}})
    e={'id':'bent','type':'window','floor_id':'f1','polygon':list(profile.exterior.coords)[:-1],'holes':[],
       'source':{'cad_ids':['0','1','2','3'],'unknowns':[]},'components':[]}
    spec={'id':'f1','origin':[30000000,-5000000]}
    return e,entities,spec,profile


def test_native_bent_window_restores_both_runs_without_rectangular_infill():
    e,entities,spec,p=bent_window();parameters=load_parameters()
    refine_assemblies([e],parameters)
    report=constrain_windows([e],entities,{'f1':spec},parameters)
    occupied=unary_union([Polygon(c['polygon'],c['holes']) for c in e['components']])
    assert len(e['source']['window_plan_segments'])==2
    assert report[0]['before_outside_footprint_m2']>.1
    assert occupied.difference(p).area<1e-10
    assert p.difference(occupied).area<1e-8
    assert 'window_plan_axis' not in e['source']
    # Host openings belong to each native run; no bounding-box shortcut.
    cut=host_opening(box(-1,-.1,6,.25),e)
    assert cut.intersection(box(2,-.1,4,.25)).area==pytest.approx(.7)
    assert cut.intersection(box(5.1,-.1,6,.25)).area==0
    assert e['source']['plan_geometry_review']['design_assignment_verified'] is False


def test_missing_native_run_cannot_be_filled_by_an_enclosing_rectangle():
    e,entities,spec,_=bent_window()
    with pytest.raises(ValueError,match='complete native'):
        native_segments(e,entities[:2],spec)


def test_straight_window_rounding_does_not_create_geometry_outside_recorded_plan():
    e,_,_,_=bent_window();p=box(0,0,5,.15)
    e.update(polygon=list(p.exterior.coords)[:-1]);e['source']['window_plan_axis']={
        'origin':[2.5,.0754],'direction':[1,0],'width_m':5,'depth_m':.15}
    refine_assemblies([e],load_parameters())
    report=constrain_windows([e],[],{},load_parameters())
    assert report[0]['before_outside_footprint_m2']>0
    assert report[0]['after_outside_footprint_m2']<1e-10
    assert audit_window_profiles([e])[0]['outside_footprint_m2']<1e-10


def test_final_audit_rejects_a_window_solid_outside_its_observed_plan():
    e,_,_,_=bent_window();refine_assemblies([e],load_parameters())
    with pytest.raises(AssertionError,match='escapes'):
        audit_window_profiles([e])
