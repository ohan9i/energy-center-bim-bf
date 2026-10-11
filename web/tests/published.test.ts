import {describe,it,expect} from 'vitest';
import {readFileSync,readdirSync} from 'node:fs';
import {parseModel,type XY} from '../src/model';
import {validateGeometry,raw} from '../src/geometry';
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
});
