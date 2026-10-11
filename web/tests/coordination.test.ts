import {readFileSync} from 'node:fs';
import {describe,it,expect} from 'vitest';
import {parseModel} from '../src/model';
import {validateGeometry} from '../src/geometry';
import {renderPieces} from '../src/bimGeometry';
import {interiorView} from '../src/interiorView';
import {inside,raw} from '../src/geometry';
const path=new URL('../public/models/precision-rebuild.json',import.meta.url);
describe('published coordination draft viewer',()=>{
 it('validates all profiles, keeps native locations and isolates provisional 3D dimensions',()=>{
   const m=parseModel(JSON.parse(readFileSync(path,'utf8')));validateGeometry(m);
   expect(readFileSync(path,'utf8')).not.toMatch(/[A-Z]:[\\/]/);
   expect(m.provenance.coordination_draft).toBe(true);
   expect(m.elements.every(e=>!e.verified&&e.height===null)).toBe(true);
   expect(m.elements.filter(e=>e.type==='column')).toHaveLength(211);
   expect(m.elements.every(e=>renderPieces(e,m,false).every(p=>p.height===null))).toBe(true);
   for(const kind of ['floor','roof','window','door','stair','elevator'])
     expect(m.elements.some(e=>e.type===kind&&renderPieces(e,m,true).some(p=>p.height!==null))).toBe(true);
 });
 it('places the interior camera inside a drawn room and away from barriers on both reviewed floors',()=>{
   const m=parseModel(JSON.parse(readFileSync(path,'utf8')));
   for(const fid of ['f1','f2']){
     const view=interiorView(m,fid);expect(view).not.toBeNull();
     expect(inside(view!.point,raw(m.elements.find(e=>e.id===view!.roomId)!))).toBe(true);
     expect(view!.clearanceM).toBeGreaterThan(.4);
     expect(m.elements.some(e=>e.floor_id===fid&&e.type==='floor'&&inside(view!.point,raw(e)))).toBe(true);
   }
 });
});
