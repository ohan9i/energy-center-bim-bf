import {readFileSync,existsSync} from 'node:fs';
import {describe,it,expect} from 'vitest';
import {parseModel} from '../src/model';
import {validateGeometry} from '../src/geometry';
import {renderPieces} from '../src/bimGeometry';
const path=new URL('../../cad_output/precision-rebuild/preview.json',import.meta.url);
describe.skipIf(!existsSync(path))('drawing-first reconstruction viewer adapter',()=>{
 it('loads the generated geometry and separates every preview height from measured data',()=>{
   const m=parseModel(JSON.parse(readFileSync(path,'utf8')));validateGeometry(m);
   expect(m.provenance.precision_rebuild).toBe(true);
   expect(m.elements.every(e=>!e.verified&&e.height===null)).toBe(true);
   expect(m.elements.some(e=>renderPieces(e,m,true).some(p=>p.height!==null))).toBe(true);
   expect(m.elements.every(e=>renderPieces(e,m,false).every(p=>p.height===null))).toBe(true);
   expect(m.elements.filter(e=>['floor','roof','beam'].includes(e.type))).toHaveLength(0);
 });
});
