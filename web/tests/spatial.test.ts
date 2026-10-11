import {describe,it,expect} from 'vitest';
import {readFileSync,writeFileSync} from 'node:fs';
import {parseModel,type Profile} from '../src/model';
import {findRoute,floorCheck} from '../src/navigation';
import {buildSpatialNetwork} from '../src/spatialRoute';
import {spatialData,modelFingerprint,recordFingerprint,validateSpatial,spatialSchema,covers,type Spatial} from '../src/spatial';
import {spatialFixture,rect} from './spatialFixture';
const p:Profile={name:'User-defined test wheelchair',body_width:.6,min_door_width:.9,min_corridor_width:1.2,max_step:.02,max_slope:1/12,allow_stairs:false,speed:.8,elevator_wait:30,stair_penalty:3};
const ledger=(m:ReturnType<typeof spatialFixture>)=>m.provenance.bf_spatial as Spatial;
const reapprove=(m:ReturnType<typeof spatialFixture>)=>{for(const r of [...ledger(m).spaces,...ledger(m).portals,...ledger(m).vertical])if(r.review)r.review.content_fingerprint=recordFingerprint(r);};
describe('space-scoped BF graph and navigation geometry',()=>{
 it('calculates entrance to elevator and second floor route using both landing doors',()=>{
  const m=spatialFixture();const single=findRoute(m,'entrance','lift1',p),r=findRoute(m,'entrance','room2',p);
  expect(single.status).toBe('found');expect(r.status).toBe('found');expect(r.uses_elevator).toBe(true);expect(r.floors).toEqual(['f1','f2']);
  expect(r.points.filter(p=>p.via).map(p=>p.via)).toEqual(['f1-gate','lift-link','f2-gate']);expect(r.seconds).toBeCloseTo(r.distance/p.speed+30);
  const net=buildSpatialNetwork(m,ledger(m),p);expect(net.space_edges).toHaveLength(3);
  for(const [i,b] of r.points.entries()){if(!i)continue;const a=r.points[i-1];if(a.floor===b.floor)expect(net.checks.get(a.floor)!.clear(a.point,b.point)).toBe(true);else expect(b.via).toBe('lift-link');}
  if(process.env.BF_SPATIAL_FIXTURE_OUTPUT)writeFileSync(process.env.BF_SPATIAL_FIXTURE_OUTPUT,JSON.stringify(m));
 });
 it('never crosses a wall or courtyard and avoids a column with body clearance',()=>{
  const m=spatialFixture(),check=floorCheck(m,'f1',p);
  expect(check.clear([4,2],[7,2])).toBe(false);expect(check.clear([2,6],[2,9.5])).toBe(false);
  expect(check.clear([2,4.5],[4,4.5])).toBe(false);expect(check.clear([2,3.2],[4,3.2])).toBe(true);
 });
 it('cannot cross a space boundary without an explicit portal even if geometry touches',()=>{
  const m=spatialFixture(),s=ledger(m);s.portals[0].status='unresolved';expect(findRoute(m,'entrance','lift1',p).status).toBe('no_path');
  const n=spatialFixture();ledger(n).portals=[];expect(findRoute(n,'entrance','room2',p).status).toBe('no_path');
 });
 it('unknown width, threshold, opening, floor step and elevator conditions fail closed',()=>{
  for(const property of ['clear_width','step','operational'] as const){const m=spatialFixture();ledger(m).portals[0].properties[property]=null;reapprove(m);expect(findRoute(m,'entrance','room2',p).status).toBe('no_path');}
  for(const field of ['step','slope'] as const){const m=spatialFixture();ledger(m).spaces[0][field]=null;reapprove(m);expect(findRoute(m,'entrance','room2',p).status).toBe('no_path');}
  const m=spatialFixture();ledger(m).vertical[0].properties.operational=null;reapprove(m);expect(findRoute(m,'entrance','room2',p).status).toBe('no_path');
 });
 it('blocks narrow, raised and closed doors, without carving unapproved openings',()=>{
  for(const props of [{clear_width:.8},{step:.05},{operational:false}]){const m=spatialFixture();Object.assign(ledger(m).portals[0].properties,props);reapprove(m);expect(findRoute(m,'entrance','room2',p).status).toBe('no_path');}
  const m=spatialFixture();ledger(m).portals[0].region=[[rect(3.4,4.2,6.6,4.8)]];reapprove(m);expect(findRoute(m,'entrance','room2',p).status).toBe('no_path');
 });
 it('does not cut unassociated intersecting walls, columns or stair shafts',()=>{
  const m=spatialFixture();m.elements.push({...m.elements[1],id:'extra-wall',polygon:rect(5.6,3,5.8,6)});
  const token=modelFingerprint(m);ledger(m).model_fingerprint=token;for(const r of [...ledger(m).spaces,...ledger(m).portals,...ledger(m).vertical])r.review!.model_fingerprint=token;
  expect(findRoute(m,'entrance','room2',p).status).toBe('no_path');
 });
 it('geometry, source, components and elevation edits invalidate review evidence',()=>{
  for(const edit of [(m:ReturnType<typeof spatialFixture>)=>m.elements[1].polygon[0][0]+=.01,
    (m:ReturnType<typeof spatialFixture>)=>m.floors[1].elevation+=.1,
    (m:ReturnType<typeof spatialFixture>)=>m.elements[1].source.source_sha256='changed']){
   const m=spatialFixture();edit(m);expect(findRoute(m,'entrance','room2',p).status).toBe('no_path');
  }
 });
 it('rejects forged approval without review and incorrect host/space/floor assignment',()=>{
  const m=spatialFixture();ledger(m).spaces[0].review=null;expect(()=>validateSpatial(m,ledger(m))).toThrow();
  const n=spatialFixture();ledger(n).portals[0].host_wall_ids=['f2-wall'];expect(findRoute(n,'entrance','room2',p).status).toBe('no_path');
  const o=spatialFixture();ledger(o).vertical[0].space_ids=['f1-lobby','f2-lobby'];expect(findRoute(o,'entrance','room2',p).status).toBe('no_path');
 });
 it('does not authorize actual CAD candidates or revert to legacy slab routing',()=>{
  const m=parseModel(JSON.parse(readFileSync(new URL('../public/models/precision-rebuild.json',import.meta.url),'utf8')));
  const s=spatialData(m)!;expect(s.model_fingerprint).toBe(modelFingerprint(m));expect(()=>validateSpatial(m,s)).not.toThrow();
  expect(s.spaces).toHaveLength(31);expect(s.portals).toHaveLength(98);expect(s.vertical).toHaveLength(10);
  const start=m.places.find(p=>p.floor_id==='f1')!,end=m.places.find(p=>p.floor_id==='f2')!;
  const lift=m.places.find(p=>p.floor_id==='f1'&&p.name.includes('E.V'))!;
  expect(findRoute(m,start.id,lift.id,p).status).toBe('no_path');
  expect(findRoute(m,start.id,end.id,p).status).toBe('no_path');delete m.provenance.bf_spatial;expect(findRoute(m,start.id,end.id,p).status).toBe('no_path');
 });
 it('rejects self-intersections, overlapping spaces and geometric floor expansion',()=>{
  const m=spatialFixture();ledger(m).spaces[0].region=[[[[0,0],[5,5],[0,5],[5,0]]]];expect(()=>validateSpatial(m,ledger(m))).toThrow();
  const n=spatialFixture();ledger(n).spaces[0].region=[[rect(-1,0,5,10)]];expect(()=>validateSpatial(n,ledger(n))).toThrow();
  expect(spatialSchema.safeParse({...ledger(spatialFixture()),version:'bad'}).success).toBe(false);
 });
 it('spatial geometry and condition edits invalidate the selected review itself',()=>{
  const m=spatialFixture();ledger(m).spaces[0].region[0][0][0][0]=.1;expect(findRoute(m,'entrance','room2',p).status).toBe('no_path');
  const n=spatialFixture();ledger(n).portals[0].properties.clear_width=1.2;expect(findRoute(n,'entrance','room2',p).status).toBe('no_path');
  reapprove(n);expect(findRoute(n,'entrance','room2',p).status).toBe('found');
 });
 it('a broad approach polygon never widens a measured doorway along a wall',()=>{
  const m=spatialFixture();m.elements.find(e=>e.id==='f1-door')!.polygon=rect(5,4.2,5.3,4.8);
  const token=modelFingerprint(m);ledger(m).model_fingerprint=token;for(const r of [...ledger(m).spaces,...ledger(m).portals,...ledger(m).vertical])r.review!.model_fingerprint=token;
  expect(findRoute(m,'entrance','room2',p).status).toBe('no_path');
 });
 it('unreviewed wall corrections retain the source wall and block added occupied area',()=>{
  const m=spatialFixture();ledger(m).blockers.push({id:'block-f1-wall',element_id:'f1-wall',floor_id:'f1',kind:'wall',region:[[rect(4.6,3,4.8,6)]],review:null,evidence:[]});
  expect(findRoute(m,'entrance','room2',p).status).toBe('no_path');
  expect(floorCheck(m,'f1',p).clear([4,2],[6,2])).toBe(false);
 });
 it('host IDs and opening profiles invalidate existing reviews even when solids stay unchanged',()=>{
  for(const edit of [(m:ReturnType<typeof spatialFixture>)=>m.elements.find(e=>e.id==='f1-door')!.source.host_wall_ids=['f1-wall'],
   (m:ReturnType<typeof spatialFixture>)=>m.elements.find(e=>e.id==='f1-door')!.source.host_openings=[{host_wall_id:'f1-wall',polygon:rect(5,3,5.3,6),holes:[]}]]){
   const m=spatialFixture();expect(findRoute(m,'entrance','room2',p).status).toBe('found');
   edit(m);expect(ledger(m).model_fingerprint).not.toBe(modelFingerprint(m));expect(findRoute(m,'entrance','room2',p).status).toBe('no_path');
  }
 });
 it('reports a missing landing door with selectable BIM and floor references',()=>{
  const m=spatialFixture();ledger(m).portals[1].properties.operational=false;reapprove(m);
  const net=buildSpatialNetwork(m,ledger(m),p),link=net.excluded.find(e=>e.id==='lift-link')!;
  expect(link.reasons.join(' ')).toContain('승강장 문');expect(link.element_ids).toEqual(['f1-lift','f2-lift']);
  expect(link.floor_ids).toEqual(['f1','f2']);expect(link.name).toBe('승강기 층간 연결');expect(link.spatial_kind).toBe('vertical');
  expect(net.checks.get('f2')!.gates.every(g=>g.status==='blocked')).toBe(true);
 });
 it('describes floors and spaces in the actual travel direction when returning downstairs',()=>{
  const m=spatialFixture(),r=findRoute(m,'room2','entrance',p);
  expect(r.status).toBe('found');expect(r.instructions).toContain('승강기: 2F → 1F');
  expect(r.instructions).toContain('Landing door: Reviewed car floor → Lobby');
  expect(r.instructions.some(s=>s.includes('f1-gate')||s.includes('lift-link'))).toBe(false);
 });
 it('a reviewed door that fails physical clearance is displayed as blocked',()=>{
  const m=spatialFixture();m.elements.find(e=>e.id==='f1-door')!.polygon=rect(5,4.2,5.3,4.8);
  const token=modelFingerprint(m);ledger(m).model_fingerprint=token;for(const r of [...ledger(m).spaces,...ledger(m).portals,...ledger(m).vertical])r.review!.model_fingerprint=token;
  const net=buildSpatialNetwork(m,ledger(m),p);
  expect(net.checks.get('f1')!.gates).toHaveLength(1);
  expect(net.checks.get('f1')!.gates.every(g=>g.status==='blocked')).toBe(true);
  expect(covers(net.checks.get('f1')!.obstacles,[5.15,4.5])).toBe(true);
  expect(net.excluded.find(r=>r.id==='f1-gate')!.element_ids).toEqual(['f1-door']);
 });
 it('does not relax an entire narrow corridor segment merely because one end touches a doorway',()=>{
  const m=spatialFixture(),net=buildSpatialNetwork(m,ledger(m),p);
  expect(net.spaceChecks.get('f1-lobby')!([4.6,3.2],[4.6,4.2])).toBe(false);
  expect(findRoute(m,'entrance','room2',p).status).toBe('found');
 });
 it('rejects a recorded clear width larger than the actual doorway geometry',()=>{
  const m=spatialFixture();ledger(m).portals[0].properties.clear_width=1.7;reapprove(m);
  const net=buildSpatialNetwork(m,ledger(m),p);
  expect(findRoute(m,'entrance','room2',p).status).toBe('no_path');
  expect(net.excluded.find(r=>r.id==='f1-gate')!.reasons.join(' ')).toContain('기하학적 유효폭');
  expect(covers(net.checks.get('f1')!.obstacles,[5.15,4.5])).toBe(true);
 });
 it('never authorizes a confirmed space attached to an excluded BIM element',()=>{
  const m=spatialFixture();ledger(m).spaces[0].element_id='f1-column';m.elements.find(e=>e.id==='f1-column')!.excluded=true;
  const token=modelFingerprint(m);ledger(m).model_fingerprint=token;for(const r of [...ledger(m).spaces,...ledger(m).portals,...ledger(m).vertical])r.review!.model_fingerprint=token;
  reapprove(m);expect(()=>validateSpatial(m,ledger(m))).toThrow('제외된 BIM');
 });
});
