import json
from pathlib import Path
import pytest
from shapely.geometry import Polygon
from shapely.ops import unary_union
from bf_bim.schema import Model
from bf_bim.ifc_export import export_ifc
from bf_bim.precise.coordination import COURTYARD

def test_current_verified_download_matches_the_current_coordination_namespace(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    import bf_bim.app as api
    monkeypatch.setattr(api,'REBUILD_DIR',tmp_path)
    (tmp_path/'coordination-v2').mkdir()
    (tmp_path/'verified.ifc').write_text('strict older export',encoding='utf8')
    (tmp_path/'coordination-v2/energy-center-Verified.ifc').write_text('current coordination export',encoding='utf8')
    assert TestClient(api.app).get('/api/rebuilt-ifc').text=='current coordination export'

def test_draft_export_cannot_bypass_explicit_metadata():
    m=Model(id='x',name='x',floors=[{'id':'f','name':'f','elevation':0}],elements=[],places=[],links=[],provenance={'precision_rebuild':True})
    with pytest.raises(ValueError,match='explicitly labelled'):export_ifc(m,coordination_draft=True)
    m.provenance['export_status']='coordination_draft'
    result=export_ifc(m,coordination_draft=True)
    assert 'DRAFT - NOT DESIGN VERIFIED' in result
    with pytest.raises(ValueError,match='verified.ifc'):export_ifc(m)

@pytest.mark.skipif(not Path('cad_output/precision-rebuild/coordination-v2/preview.json').exists(),reason='Generate artifact first')
def test_generated_coordination_honours_evidence_and_openings():
    m=Model.model_validate_json(Path('cad_output/precision-rebuild/coordination-v2/preview.json').read_text(encoding='utf-8'))
    assert not any(e.verified for e in m.elements)
    for e in m.elements:
        if e.type=='beam' and not e.source.get('user_assumed_completion'):
            evidence=e.source['structural_girder']
            assert len(evidence['support_ids'])==2 and evidence['section_references']
            assert not evidence['native_outline_recovered'] and not evidence['member_assignment_verified']
    assert len([e for e in m.elements if e.type=='column'])==211
    assert {'wall','window','door','floor','roof','stair','elevator'}<=set(e.type for e in m.elements)
    for e in m.elements:
        assert e.source['validation_status'] in ['verified','drawing_based','schedule_matched','provisional','unresolved']
        if e.source.get('ceiling_completion'):
            # Ceiling closures have context references, not fabricated CAD IDs.
            assert not e.source['cad_ids'] and e.source['context_slab_ids'] and e.source['context_room_ids']
        else:assert e.source['cad_ids']
        assert e.source['source_sha256']
        assert e.height is None
        if e.type=='roof':assert e.source['roof_source_floor']==e.floor_id
        if e.type=='stair' and e.floor_id=='roof':
            assert not e.components and e.source['unresolved_plan_only']
        if e.type=='stair' and e.components:
            landings=[c.z_offset+c.height for c in e.components if c.role=='landing' and c.height is not None]
            assert abs(max(landings)-e.source['applied_dimensions']['storey_interval_m'])<1e-6
        if e.type in ('floor','roof'):
            voids=[Polygon(q.polygon,q.holes) for q in m.elements if q.floor_id==e.floor_id and q.type in ('stair','elevator')]
            if e.floor_id!='b1':voids.append(COURTYARD)
            assert Polygon(e.polygon,e.holes).intersection(unary_union(voids)).area<1e-4
        for c in e.components:
            assert c.source['validation_status']=='provisional'
    walls=[e for e in m.elements if e.type=='wall']
    for opening in [e for e in m.elements if e.type in ('door','window') and e.components]:
        op=opening.source['provisional_opening']
        mid=op['z_offset']+op['height']/2
        p=Polygon(opening.polygon,opening.holes)
        for w in walls:
            if w.floor_id!=opening.floor_id:continue
            for c in w.components:
                if c.z_offset<mid<c.z_offset+c.height:
                    assert Polygon(c.polygon,c.holes).intersection(p).area<1e-5

@pytest.mark.skipif(not Path('cad_output/precision-rebuild/coordination-v2/energy-center-Coordination-Draft.ifc').exists(),reason='Generate artifact first')
def test_read_only_draft_endpoints_and_generic_export_gate():
    from fastapi.testclient import TestClient
    from bf_bim.app import app
    client=TestClient(app)
    response=client.get('/api/rebuilt-model')
    assert response.status_code==200 and response.json()['provenance']['coordination_draft']
    response=client.get('/api/rebuilt-draft-ifc')
    assert response.status_code==200 and 'DRAFT - NOT DESIGN VERIFIED' in response.text
    assert 'Coordination-Draft' in response.headers['content-disposition']
