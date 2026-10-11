from copy import deepcopy
import json
from pathlib import Path

import pytest
from shapely.affinity import rotate
from shapely.geometry import LineString, Polygon, box
from shapely.ops import unary_union

from bf_bim.precise.coordination_quality import host_opening, verification_decision, geometry_digest, apply_review, is_boolean_sliver, audit_navigation_junctions, audit_relationships
from bf_bim.precision_model import stair_components
from bf_bim.architectural_assemblies import refine_assemblies, load_parameters


def portal(poly):
    return {'type':'window','polygon':list(poly.exterior.coords)[:-1], 'source':{}}


@pytest.mark.parametrize('angle',[0,45,90])
def test_opening_cuts_full_parallel_host_depth_without_widening_span(angle):
    wall=rotate(box(0,0,6,.5),angle,origin=(0,0))
    symbol=rotate(box(1,.15,3,.25),angle,origin=(0,0))
    cut=host_opening(wall,portal(symbol))
    expected=rotate(box(1,0,3,.5),angle,origin=(0,0))
    assert cut.intersection(wall).symmetric_difference(expected).area<1e-8
    # Adjacent/orthogonal walls must not receive a cut by the window's proximity.
    perpendicular=rotate(box(3,0,3.3,4),angle,origin=(0,0))
    assert host_opening(perpendicular,portal(symbol)) is None


def test_split_host_and_remote_parallel_wall_do_not_share_opening():
    walls=unary_union([box(0,0,2,.4),box(2.2,0,6,.4),box(0,3,6,3.4)])
    cut=host_opening(walls,portal(box(1,.1,3,.2)))
    assert cut.intersection(box(0,3,6,3.4)).is_empty
    assert cut.intersection(walls).area==pytest.approx(.72)


def test_short_cad_edge_does_not_delete_substantial_corner_solid():
    corner=Polygon([[0,0],[.03,0],[.03,.015],[.029537,.015],[.029537,.014904],[0,.014904]])
    assert corner.minimum_clearance<.0001
    assert not is_boolean_sliver(corner)
    assert is_boolean_sliver(box(0,0,2,.00005))


def test_basement_riser_count_and_soffit_are_reconstructed_without_scaling_rail():
    nosings=[(LineString([(0,i*.3),(3.2,i*.3)]),str(i)) for i in range(11)]
    envelope=box(0,-1.5,3.2,4.5)
    parts,detail=stair_components(nosings,envelope,[{'text':'177.27 x 11EA'}],
                                riser_m=3.9/22,risers_per_flight=11,storey_interval_m=3.9)
    e={'id':'b1-stair','type':'stair','height':3.9,'polygon':list(envelope.exterior.coords)[:-1],
       'holes':[],'source':detail,'components':parts}
    parameters=load_parameters();refine_assemblies([e],parameters)
    landings=[c['z_offset']+c['height'] for c in e['components'] if c['role']=='landing']
    assert max(landings)==pytest.approx(3.9)
    assert sorted(set(landings))==pytest.approx([0,1.95,3.9])
    assert detail['risers_per_flight']==11 and detail['riser_m']==pytest.approx(3.9/22)
    for c in e['components']:
        if c['role']=='landing':assert c['height']==pytest.approx(parameters['landing_thickness'])
        if c['role']=='handrail':
            assert c['source']['parameter_keys'] and not c['source']['dimension_verified']
    bad,_=stair_components(nosings,envelope,[],riser_m=.175,risers_per_flight=12,storey_interval_m=4.2)
    assert bad==[]


def evidence_record():
    return {'status':'verified','references':[{'cad_ids':['native'], 'source_sha256':'a'*64}],
            'review':{'reviewer':'test fixture reviewer','reviewed_at':'2026-10-11'}}


def test_verification_gate_rejects_flags_without_complete_evidence_and_conflicts():
    required=('identity','position','profile','base','top','material','scope','revision')
    src={'verified':True,'design_assignment_verified':True,
         'property_evidence':{k:evidence_record() for k in required}}
    components=[{'height':3,'source':{'geometry_status':'verified'}}]
    assert verification_decision(src,components,{'cad':True})['eligible']
    for key in required:
        invalid=deepcopy(src);invalid['property_evidence'][key]['references']=[]
        assert not verification_decision(invalid,components,{'cad':True})['eligible']
    for extra in ({'assumptions':{'height':3}}, {'conflicts':['wrong mark']}, {'missing_references':['xref']}):
        assert not verification_decision({**src,**extra},components,{'cad':True})['eligible']
    assert not verification_decision(src,components,{'cad':False})['eligible']
    assert not verification_decision(src,[],{'cad':True})['eligible']
    assert not verification_decision(src,[{'height':3,'source':{'geometry_status':'provisional'}}],{'cad':True})['eligible']


def test_review_is_invalidated_by_source_or_component_geometry_change():
    c={'id':'c','polygon':[[0,0],[1,0],[1,1],[0,1]],'holes':[], 'height':3,'z_offset':0,'role':'column','source':{}}
    e={'id':'e','components':[c],'source':{'source_sha256':'a'*64,'verification_required_fields':['position'],
                                       'property_evidence':{},'assumptions':{},'unknowns':[]}}
    ref=evidence_record()
    record={'source_sha256':'a'*64,'components':{'c':{'geometry_sha256':geometry_digest(c),**ref}},
            'checks':{k:{'passed':True,**ref} for k in ('cad_plan','section_height','schedule_assignment','junctions','source_coverage')},
            'property_evidence':{'position':ref},'resolved_assumptions':[],'resolved_unknowns':[]}
    assert all(apply_review(deepcopy(e),record).values())
    changed=deepcopy(e);changed['components'][0]['height']=3.1
    assert not apply_review(changed,record)['review_geometry_matches']
    assert changed['components'][0]['source'].get('geometry_status')!='verified'
    assert not apply_review(deepcopy(e),{**record,'source_sha256':'b'*64})['review_source_matches']


@pytest.mark.skipif(not Path('cad_output/precision-rebuild/coordination-v2/member-validation.json').exists(),reason='Regenerate v8')
def test_generated_quality_results_cover_every_member_and_prior_empty_wall():
    root=Path('cad_output/precision-rebuild/coordination-v2')
    model=json.loads((root/'preview.json').read_text(encoding='utf-8'))
    validation=json.loads((root/'validation.json').read_text(encoding='utf-8'))
    members=json.loads((root/'member-validation.json').read_text(encoding='utf-8'))
    assert len(members['members'])==len(model['elements'])
    assert model['provenance']['verified_solids']==sum(r['eligible'] for r in members['members'])
    assert len(validation['boolean_remnant_review'])==44
    assert all(r['native_curves'] for r in validation['boolean_remnant_review'])
    assert all(r['status']=='passed' for r in validation['architectural_relationships']['host_openings'])
    assert model['provenance']['improvements']['host_openings']>0
    b1=[e for e in model['elements'] if e['type']=='stair' and e['floor_id']=='b1']
    assert len(b1)==1 and b1[0]['source']['section_dimension_link']['risers_per_flight']==11
    junctions=validation['navigation_junctions']
    assert len(junctions['portals'])==sum(e['type'] in ('door','window') for e in model['elements'])
    assert len(junctions['stairs'])==sum(e['type']=='stair' for e in model['elements'])
    for e in model['elements']:
        if e['type'] not in ('door','window'):continue
        assert set(e['source'].get('host_wall_ids',[]))=={r['host_wall_id'] for r in e['source'].get('host_openings',[])}
        assert e['source']['connection_review']['bf_passage_verified'] is False


def test_junction_audit_rejects_remote_host_and_retains_unresolved_stair_contact():
    wall={'id':'wall','type':'wall','floor_id':'f1','polygon':list(box(0,0,4,.3).exterior.coords),'components':[], 'source':{}}
    door={'id':'door','type':'door','floor_id':'f1','polygon':list(box(1,0,2,.3).exterior.coords),'components':[],
          'source':{'host_wall_ids':['wall'],'host_openings':[]},'verified':False}
    specs=[{'id':'f1','elevation':0,'height_preview':4.2},{'id':'f2','elevation':4.2}]
    with pytest.raises(AssertionError,match='actual cut fragments'):
        audit_navigation_junctions([wall,door],specs)
    door['source']['host_wall_ids']=[]
    stair={'id':'stair','type':'stair','floor_id':'f1','source':{},'components':[
        {'role':'landing','polygon':list(box(0,0,2,1).exterior.coords),'height':.2,'z_offset':4.0}]}
    slab={'id':'slab','type':'floor','floor_id':'f2','polygon':list(box(2.3,0,5,3).exterior.coords)}
    result=audit_navigation_junctions([wall,door,stair,slab],specs)
    assert result['portals'][0]['status']=='unresolved_no_wall_host'
    assert result['stairs'][0]['plan_gap_to_upper_slab_m']==pytest.approx(.3)
    assert result['stairs'][0]['level_difference_m']==pytest.approx(0)
    assert result['stairs'][0]['status']=='unresolved_connection'
    assert door['verified'] is False


def test_slab_contact_separates_plan_touch_from_vertical_and_structural_connection():
    profile=list(box(0,0,2,.3).exterior.coords)
    wall={'id':'wall','type':'wall','floor_id':'f1','polygon':profile,'components':[
        {'polygon':profile,'role':'wall_body','height':4.2,'z_offset':0}]}
    footprint=list(box(0,0,4,4).exterior.coords)
    slab={'id':'slab','type':'floor','floor_id':'f1','polygon':footprint,'components':[
        {'id':'structural','polygon':footprint,'role':'structural_slab','height':.25,'z_offset':-.32},
        {'id':'finish','polygon':footprint,'role':'floor_finish','height':.07,'z_offset':-.07}]}
    result=audit_relationships([wall,slab],[{'id':'f1','elevation':0}],Polygon())
    contacts={c['slab_component_id']:c for c in result['contacts']}
    assert contacts['structural']['vertical_gap_m']==pytest.approx(.07)
    assert contacts['structural']['relation']=='plan_contact_z_unresolved'
    assert contacts['finish']['relation']=='observed_draft_z_contact'
    assert all(c['structural_connection_verified'] is False for c in contacts.values())
