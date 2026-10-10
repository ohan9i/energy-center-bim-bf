import {describe,it,expect} from 'vitest';
import {readFileSync} from 'node:fs';
import {parseModel} from '../src/model';
import {validateGeometry} from '../src/geometry';
import {findRoute} from '../src/navigation';

const input=readFileSync(new URL('../public/models/project.json',import.meta.url),'utf8');
describe('published actual project model',()=>{
 it('retains both actual floors and geometry without local paths',()=>{
  const m=parseModel(JSON.parse(input));validateGeometry(m);
  expect(m.is_example).toBe(false);expect(m.elements).toHaveLength(820);
  expect(m.floors.map(f=>f.elevation)).toEqual([0,expect.closeTo(4.2)]);
  expect(m.provenance.publication).toBe('github_pages');
  expect(input).not.toMatch(/[A-Z]:[\\/]/);
 });
 it('keeps unknown actual conditions from becoming an accessible route',()=>{
  const m=parseModel(JSON.parse(input));
  const rules=JSON.parse(readFileSync(new URL('../public/rules.json',import.meta.url),'utf8'));
  expect(m.elements.every(e=>!e.verified)).toBe(true);
  expect(findRoute(m,m.places[0].id,m.places[1].id,rules.profiles.wheelchair).status).toBe('no_path');
 });
});
