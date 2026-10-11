import {describe,it,expect} from 'vitest';
import {readFileSync} from 'node:fs';
import {parseModel,type Profile} from '../src/model';
import {findRoute,floorCheck} from '../src/navigation';
import {validateGeometry} from '../src/geometry';
import {evaluate} from '../src/evaluation';
const fixture=()=>parseModel(JSON.parse(readFileSync(new URL('./fixtures/navigation-model.json',import.meta.url),'utf8')));
const rules=JSON.parse(readFileSync(new URL('../public/rules.json',import.meta.url),'utf8'));
const profile=(key='wheelchair'):Profile=>({...rules.profiles[key]});
describe('collision-checked static navigation',()=>{
 it('ordinary pedestrian chooses stairs; wheelchair chooses elevator',()=>{
  const m=fixture();const walk=findRoute(m,'entrance','class2',profile('pedestrian'));const wheel=findRoute(m,'entrance','class2',profile());
  expect(walk.status).toBe('found');expect(walk.points.some(p=>p.via==='link-stair')).toBe(true);
  expect(wheel.status).toBe('found');expect(wheel.uses_elevator).toBe(true);expect(wheel.points.some(p=>p.via==='link-stair')).toBe(false);
 });
 it('every same-floor route segment respects obstacles and body clearance',()=>{
  const m=fixture(),p=profile(),r=findRoute(m,'entrance','class2',p);expect(r.status).toBe('found');
  const checks=new Map(m.floors.map(f=>[f.id,floorCheck(m,f.id,p)]));
  r.points.slice(1).forEach((b,i)=>{const a=r.points[i];if(a.floor===b.floor)expect(checks.get(a.floor)!.clear(a.point,b.point)).toBe(true);});
  expect(floorCheck(m,'f1',p).clear([5,5],[5,8])).toBe(false);
 });
 it('closed wall prevents route; valid doorway opens it',()=>{
  const m=fixture();expect(findRoute(m,'entrance','class1',profile()).status).toBe('found');
  m.elements.find(e=>e.id==='f1-door-class')!.excluded=true;
  expect(findRoute(m,'entrance','class1',profile()).status).toBe('no_path');
 });
 it('too narrow door excluded; editing width regenerates graph',()=>{
  const m=fixture(),door=m.elements.find(e=>e.id==='f2-door-class')!;
  door.properties.clear_width=.75;expect(findRoute(m,'entrance','class2',profile()).status).toBe('no_path');
  door.properties.clear_width=1.1;m.revision++;expect(findRoute(m,'entrance','class2',profile()).status).toBe('found');
 });
 it('unknown door width never inferred safe',()=>{
  const m=fixture();m.elements.find(e=>e.id==='f1-door-class')!.properties.clear_width=null;
  expect(findRoute(m,'entrance','class1',profile()).status).toBe('no_path');
 });
 it('out of service elevator leaves wheelchair without inter-floor path',()=>{
  const m=fixture();m.elements.find(e=>e.id==='lift')!.properties.operational=false;
  expect(findRoute(m,'entrance','class2',profile()).status).toBe('no_path');
 });
 it('ramp slope and step constraints block traversal',()=>{
  const m=fixture(),ramp=m.elements.find(e=>e.id==='ramp')!;ramp.properties.slope=.15;
  expect(evaluate(ramp,profile()).status).toBe('blocked');ramp.properties.slope=null;
  expect(evaluate(ramp,profile()).status).toBe('unknown');
 });
 it('floor unverified or unknown step excludes it',()=>{
  const m=fixture();m.elements.find(e=>e.id==='f1-floor')!.properties.step=null;
  expect(findRoute(m,'entrance','class1',profile()).status).toBe('no_path');
 });
 it('accounts for wait time and rejects invalid profile',()=>{
  const m=fixture(),p=profile(),r=findRoute(m,'entrance','class2',p);
  expect(r.seconds).toBeCloseTo(r.distance/p.speed+p.elevator_wait);
  expect(()=>findRoute(m,'entrance','class2',{...p,speed:0})).toThrow();
 });
 it('rejects missing references and self crossing polygons',()=>{
  const m=fixture();m.links[0].to_place='missing';expect(()=>parseModel(m)).toThrow();
  const n=fixture();n.elements[0].polygon=[[0,0],[5,5],[0,5],[5,0]];expect(()=>validateGeometry(n)).toThrow();
 });
 it('start equals end is a valid zero-distance path',()=>{
  const r=findRoute(fixture(),'entrance','entrance',profile());expect(r.status).toBe('found');expect(r.distance).toBe(0);
 });
 it('rejects outside and overlapping slab openings',()=>{
  const m=fixture(),floor=m.elements.find(e=>e.id==='f1-floor')!;
  floor.holes=[[[30,30],[32,30],[32,32],[30,32]]];expect(()=>validateGeometry(m)).toThrow();
  floor.holes=[[[1,1],[3,1],[3,3],[1,3]],[[2,2],[4,2],[4,4],[2,4]]];expect(()=>validateGeometry(m)).toThrow();
  floor.holes=[[[1,1],[3,1],[3,3],[1,3]]];expect(()=>validateGeometry(m)).not.toThrow();
 });
});
