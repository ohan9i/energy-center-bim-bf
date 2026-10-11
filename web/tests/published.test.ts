import {describe,it,expect} from 'vitest';
import {readFileSync,readdirSync} from 'node:fs';
import {parseModel} from '../src/model';
import {validateGeometry} from '../src/geometry';
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
});
