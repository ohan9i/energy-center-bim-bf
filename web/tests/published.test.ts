import {describe,it,expect} from 'vitest';
import {readFileSync} from 'node:fs';
import {parseModel} from '../src/model';
import {validateGeometry} from '../src/geometry';
import {findRoute} from '../src/navigation';

const input=readFileSync(new URL('../public/models/project.json',import.meta.url),'utf8');
describe('published actual project model',()=>{
 it('retains both actual floors and geometry without local paths',()=>{
  const m=parseModel(JSON.parse(input));validateGeometry(m);
  expect(m.is_example).toBe(false);expect(m.elements.length).toBeGreaterThan(820);
  expect(m.floors.map(f=>f.elevation)).toEqual([expect.closeTo(-3.9),0,expect.closeTo(4.2),expect.closeTo(8.4),expect.closeTo(12.6),expect.closeTo(16.8)]);
  expect(m.elements.some(e=>e.type==='window')).toBe(true);
  expect(m.elements.some(e=>e.type==='space')).toBe(true);
  expect(m.elements.filter(e=>e.type==='stair'&&e.floor_id==='f1')).toHaveLength(2);
  expect(m.elements.filter(e=>e.type==='stair').every(e=>e.components.length>10)).toBe(true);
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
