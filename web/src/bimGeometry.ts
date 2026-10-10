import pc from 'polygon-clipping';
import type {Element,Model,XY} from './model';
import {raw,bounds,type Poly} from './geometry';
export interface Piece {poly:Poly;z:number;height:number|null;role?:string;assumed?:boolean}
export const previewDimensions={door:2.1,window:2.4,sill:.9};
export function renderPieces(e:Element,m:Model,assumptions=false):Piece[]{
 if(e.components.length)return e.components.map(c=>({poly:[c.polygon,...c.holes],z:e.z_offset+c.z_offset,height:c.height,role:c.role}));
 if(e.type!=='wall'){
  const assumed=assumptions&&e.height===null&&['door','window'].includes(e.type);
  return [{poly:raw(e),z:e.z_offset+(assumed&&e.type==='window'?previewDimensions.sill:0),height:assumed?(e.type==='door'?previewDimensions.door:previewDimensions.window):e.height,assumed}];
 }
 if(e.height===null)return [{poly:raw(e),z:e.z_offset,height:null}];
 const eb=bounds([raw(e)]);
 const openings=m.elements.filter(d=>!d.excluded&&d.floor_id===e.floor_id&&['door','window'].includes(d.type)).flatMap(d=>{
  const db=bounds([raw(d)]);if(db.max[0]<eb.min[0]||db.min[0]>eb.max[0]||db.max[1]<eb.min[1]||db.min[1]>eb.max[1])return [];
  const assumed=assumptions&&d.height===null;if(d.height===null&&!assumed)return [];
  const z=d.z_offset+(assumed&&d.type==='window'?previewDimensions.sill:0);
  return [{poly:raw(d),z,height:d.height??(d.type==='window'?previewDimensions.window:previewDimensions.door),assumed}];
 });
 const start=e.z_offset,end=start+e.height;
 const levels=[...new Set([start,end,...openings.flatMap(d=>[Math.max(start,Math.min(end,d.z)),Math.max(start,Math.min(end,d.z+d.height))])])].sort((a,b)=>a-b);
 return levels.slice(1).flatMap((hi,i)=>{
  const lo=levels[i],cuts=openings.filter(d=>d.z<=lo&&d.z+d.height>=hi);
  const polys=cuts.length?pc.difference(raw(e),...cuts.map(d=>d.poly)) as Poly[]:[raw(e)];
  return polys.map(poly=>({poly,z:lo,height:hi-lo,assumed:cuts.some(d=>d.assumed)}));
 });
}
export function planArea(e:Pick<Element,'polygon'|'holes'>){
 const area=(r:XY[])=>Math.abs(r.reduce((sum,a,i)=>{const b=r[(i+1)%r.length];return sum+a[0]*b[1]-b[0]*a[1];},0))/2;
 return area(e.polygon)-e.holes.reduce((sum,r)=>sum+area(r),0);
}
export function floorOffset(m:Model,floorId:string,separation:number){return Math.max(0,m.floors.findIndex(f=>f.id===floorId))*separation;}
