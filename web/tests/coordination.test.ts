import {readFileSync} from 'node:fs';
import {describe,it,expect} from 'vitest';
import {parseModel} from '../src/model';
import {validateGeometry} from '../src/geometry';
import {renderPieces} from '../src/bimGeometry';
import {interiorView,interiorCeilingFloor,ceilingElements} from '../src/interiorView';
import {inside,raw} from '../src/geometry';
const path=new URL('../public/models/precision-rebuild.json',import.meta.url);
describe('published coordination draft viewer',()=>{
 it('includes upper slabs and downstand beams in ceiling review, without upper walls or reference plans',()=>{
   const m=parseModel(JSON.parse(readFileSync(path,'utf8')));
   for(const [floor,upper] of [['f1','f2'],['f2','f3']]){
     const members=ceilingElements(m,floor);
     expect(members.some(e=>e.type==='floor')).toBe(true);
     expect(members.some(e=>e.type==='beam')).toBe(true);
     expect(members.every(e=>e.floor_id===upper&&['floor','roof','beam'].includes(e.type))).toBe(true);
     const excluded=members[0];
     const changed={...m,elements:m.elements.map(e=>e.id===excluded.id?{...e,excluded:true}:e)};
     expect(ceilingElements(changed,floor).some(e=>e.id===excluded.id)).toBe(false);
   }
   expect(ceilingElements(m,'all')).toEqual([]);
   expect(ceilingElements(m,'phroof')).toEqual([]);
 });
 it('uses actual upper slabs as interior ceilings and ignores reference-only plans',()=>{
   const m=parseModel(JSON.parse(readFileSync(path,'utf8')));
   for(const [floor,upper] of [['b1','f1'],['f1','f2'],['f2','f3'],['f3','f4'],['f4','roof'],['roof','phroof']])
     expect(interiorCeilingFloor(m,floor)).toBe(upper);
   expect(interiorCeilingFloor(m,'all')).toBeNull();
   expect(interiorCeilingFloor(m,'phroof')).toBeNull();
   const stripped={...m,elements:m.elements.filter(e=>e.floor_id!=='phroof')};
   expect(interiorCeilingFloor(stripped,'roof')).toBeNull();
 });
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
