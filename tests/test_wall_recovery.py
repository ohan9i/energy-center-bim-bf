import pytest
import json
from pathlib import Path
from shapely.geometry import Polygon,box
from bf_bim.precise.wall_recovery import recover_wall_gaps,exact_prism_mesh
from bf_bim.assembly_solids import mesh_volume

def test_closed_source_wall_return_is_recovered_without_duplicate_body_or_column():
    # A concrete wall crosses a column. Its two faces and endcaps are explicit.
    wall=box(0,0,3,.2);col=box(0,-.2,.4,.4)
    traces=[{'floor_id':'f1','id':'wall-native','kind':'wall','points':list(wall.exterior.coords)},
            {'floor_id':'f1','id':'column-native','kind':'column','points':list(col.exterior.coords)}]
    existing=box(.6,0,3,.2)
    added,audit=recover_wall_gaps(traces,[('f1',existing,{},'wall')],{'f1':[col]},[])
    assert len(added)==1
    recovered=added[0][1]
    assert recovered.area==pytest.approx(.2*.2)
    assert recovered.intersection(existing).area==0 and recovered.intersection(col).area==0
    assert recovered.difference(wall).area==0
    assert audit[0]['boundary_residual_m']<1e-6

def test_exact_prism_preserves_concavity_holes_and_volume():
    p=box(0,0,3,2).difference(box(1,.5,2,1.5)).difference(box(2.5,1,3,2))
    mesh=exact_prism_mesh(p,3.9)
    assert mesh_volume(mesh)==pytest.approx(p.area*3.9)
    for a,b,c in mesh['triangles']:
        points=[mesh['vertices'][i] for i in (a,b,c)]
        if len({v[2] for v in points})==1:
            assert p.covers(Polygon([(v[0],v[1]) for v in points]))

def test_open_source_room_cycle_and_roundoff_bands_are_not_generated_walls():
    for points in ([[0,0],[3,0],[3,.2],[0,.2]],list(box(0,0,3,3).exterior.coords)):
        added,_=recover_wall_gaps([{'floor_id':'f1','id':'wall','kind':'wall','points':points}],[],{},[])
        assert added==[]
    traces=[{'floor_id':'f1','id':'wall','kind':'wall','points':list(box(0,0,3,.2).exterior.coords)}]
    added,_=recover_wall_gaps(traces,[('f1',box(0,0,3,.1999),{},'old')],{},[])
    assert added==[]

def test_drawing_door_envelope_remains_open_during_recovery():
    wall=box(0,0,3,.2)
    traces=[{'floor_id':'f1','id':'wall','kind':'wall','points':list(wall.exterior.coords)}]
    door={'type':'door','floor_id':'f1','polygon':list(box(1,-.1,2,.3).exterior.coords),'holes':[]}
    added,_=recover_wall_gaps(traces,[],{},[door])
    assert sum(p.area for fid,p,s,n in added)==pytest.approx(.4)
    assert all(p.intersection(Polygon(door['polygon'])).area==0 for fid,p,s,n in added)

@pytest.mark.skipif(not Path('cad_output/precision-rebuild/coordination-v2/wall-recovery-validation.json').exists(),reason='Rebuild first')
def test_generated_wall_returns_remain_inside_source_cycles_and_are_bf_blockers():
    m=json.loads(Path('cad_output/precision-rebuild/coordination-v2/preview.json').read_text(encoding='utf8'))
    added=[e for e in m['elements'] if e['source'].get('native_wall_closure')]
    assert added and {e['floor_id'] for e in added}=={'b1','f1','f2','f3','f4'}
    blockers={b['element_id']:b for b in m['provenance']['bf_spatial']['blockers'] if b['kind']=='wall'}
    for e in added:
        p=Polygon(e['polygon'],e['holes']);record=e['source']['native_wall_closure']
        cycle=Polygon(record['cycle']['polygon'],record['cycle']['holes'])
        assert p.difference(cycle.buffer(1e-6)).area<1e-7
        assert record['boundary_residual_m']<1e-6 and not e['verified']
        assert e['id'] in blockers
        assert e['components'] and e['source']['assumptions']['height']['value_m']>0
