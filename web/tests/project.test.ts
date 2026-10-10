import {describe,it,expect} from 'vitest';
import {existsSync,readFileSync} from 'node:fs';
import {parseModel} from '../src/model';
import {validateGeometry} from '../src/geometry';
import {findRoute} from '../src/navigation';
const path=new URL('../../cad_output/energy-center-model.json',import.meta.url);
describe.skipIf(!existsSync(path))('local actual DWG reconstruction',()=>{
 it('loads actual 1F/2F model with metre coordinates and section levels',()=>{
  const model=parseModel(JSON.parse(readFileSync(path,'utf8')));validateGeometry(model);
  expect(model.is_example).toBe(false);expect(model.floors[1].elevation).toBeCloseTo(4.2);
  expect(model.elements.length).toBeGreaterThan(100);expect(model.elements.some(e=>e.type==='column')).toBe(true);
  expect(model.places.some(p=>p.name.includes('사무실'))).toBe(true);
 });
 it('does not invent an accessible path through unverified actual geometry',()=>{
  const m=parseModel(JSON.parse(readFileSync(path,'utf8'))),rules=JSON.parse(readFileSync(new URL('../public/rules.json',import.meta.url),'utf8'));
  const route=findRoute(m,m.places[0].id,m.places[1].id,rules.profiles.wheelchair);
  expect(route.status).toBe('no_path');expect(route.excluded.some(x=>x.status==='unknown')).toBe(true);
 });
});
