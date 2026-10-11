import {describe,it,expect} from 'vitest';
import {readFileSync,readdirSync} from 'node:fs';
import {parseModel,type XY} from '../src/model';
import {validateGeometry,raw,inside,edges,pointSegment,dist} from '../src/geometry';
import {area,difference} from '../src/spatial';
import {findRoute} from '../src/navigation';

const input=readFileSync(new URL('../public/models/precision-rebuild.json',import.meta.url),'utf8');
describe('published coordination model',()=>{
 it('ships only the current model and its IFC exports',()=>{
  expect(readdirSync(new URL('../public/models/',import.meta.url)).sort()).toEqual([
   'precision-rebuild-coordination-draft.ifc','precision-rebuild-verified.ifc','precision-rebuild.json',
  ]);
  const m=parseModel(JSON.parse(input));validateGeometry(m);
  expect(m.id).toBe('energy-center-precision-rebuild');
  expect(m.is_example).toBe(false);
  expect(m.provenance.coordination_draft).toBe(true);
  expect(m.provenance.verified_solids).toBe(m.elements.filter(e=>(e.source.verification as {eligible?:boolean}|undefined)?.eligible===true).length);
  expect(m.provenance.comparison_baseline).toBeUndefined();
  expect(input).not.toMatch(/[A-Z]:[\\/]/);
 });
 it('keeps unknown actual conditions from becoming an accessible route',()=>{
  const m=parseModel(JSON.parse(input));
  const rules=JSON.parse(readFileSync(new URL('../public/rules.json',import.meta.url),'utf8'));
  expect(m.elements.every(e=>!e.verified)).toBe(true);
  expect(findRoute(m,m.places[0].id,m.places[1].id,rules.profiles.wheelchair).status).toBe('no_path');
 });
 it('binds portal hosts only to their actual intersecting opening fragments without approving travel',()=>{
  const m=parseModel(JSON.parse(input)),elements=new Map(m.elements.map(e=>[e.id,e]));
  for(const e of m.elements.filter(e=>e.type==='door'||e.type==='window')){
   const cuts=(e.source.host_openings??[]) as {host_wall_id:string;polygon:XY[];holes:XY[][]}[];
   expect(new Set(e.source.host_wall_ids as string[]??[])).toEqual(new Set(cuts.map(c=>c.host_wall_id)));
   expect((e.source.connection_review as {bf_passage_verified:boolean}).bf_passage_verified).toBe(false);
   for(const c of cuts){
    const host=elements.get(c.host_wall_id)!;expect(host.type).toBe('wall');expect(host.floor_id).toBe(e.floor_id);
    expect(area(difference([[c.polygon,...c.holes]],[raw(host)]))).toBeLessThan(1e-7);
   }
  }
 });
 it('keeps rendered window solids inside their CAD footprints and preserves both bent runs',()=>{
  const m=parseModel(JSON.parse(input));
  for(const e of m.elements.filter(e=>e.type==='window'&&e.components.length)){
   // Exact outside-area validation runs in the Python/GEOS generator. Here
   // independently check the actual render edges without polygon-clipping's
   // unstable difference of numerically coincident diagonal output rings.
   const boundary=raw(e).flatMap(edges);
   for(const c of e.components)for(const [a,b] of [c.polygon,...c.holes].flatMap(edges)){
    const n=Math.max(1,Math.ceil(dist(a,b)/.05));
    for(let i=0;i<=n;i++){
     const pt:XY=[a[0]+(b[0]-a[0])*i/n,a[1]+(b[1]-a[1])*i/n];
     expect(inside(pt,raw(e))||boundary.some(([x,y])=>pointSegment(pt,x,y)<=.000002),e.id).toBe(true);
    }
   }
  }
  for(const id of ['coord-00088d6131cb5fe92e68','coord-0aa6a2cc9653d0908c64']){
   const e=m.elements.find(e=>e.id===id)!;
   const runs=e.source.window_plan_segments as {cad_ids:string[]}[];
   expect(runs).toHaveLength(2);expect(runs.every(r=>r.cad_ids.length>=2)).toBe(true);
   expect(e.source.window_plan_axis).toBeUndefined();expect(e.verified).toBe(false);
  }
 });
 it('renders the dimensioned AW-1 and AW-5 elevations without treating them as approved passages',()=>{
  const m=parseModel(JSON.parse(input));
  for(const [id,height,sill] of [
   ['coord-e09c1449d93909693e2f',2.8,0],['coord-7856c0b97b13a29f12cb',1.6,1.2],
  ] as const){
   const e=m.elements.find(e=>e.id===id)!;
   const assignment=e.source.schedule_assignment as {width_m:number;height_m:number;sill_m:number;glass_thickness_m:number};
   expect(assignment.width_m).toBeCloseTo(1.8,5);expect(assignment.height_m).toBeCloseTo(height,5);
   expect(assignment.sill_m).toBeCloseTo(sill,5);expect(assignment.glass_thickness_m).toBe(.024);
   expect(Math.min(...e.components.map(c=>c.z_offset))).toBeCloseTo(sill,5);
   expect(Math.max(...e.components.map(c=>c.z_offset+c.height!))).toBeCloseTo(sill+height,5);
   expect(e.components.some(c=>c.role==='transom')).toBe(true);
   expect(e.verified).toBe(false);
   expect((e.source.connection_review as {bf_passage_verified:boolean}).bf_passage_verified).toBe(false);
  }
 });
});
