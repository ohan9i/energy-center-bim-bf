import pc from 'polygon-clipping';
import type {Element,Model,XY,SolidMesh} from './model';
import {raw,bounds,type Poly} from './geometry';
export interface Piece {poly:Poly;z:number;height:number|null;role?:string;assumed?:boolean;material?:string;mesh?:SolidMesh|null;componentId?:string}
export const previewDimensions={door:2.1,window:2.4,sill:.9};
export function createRenderContext(m:Model){const openings=new Map<string,Element[]>();for(const e of m.elements)if(!e.excluded&&['door','window'].includes(e.type)){const group=openings.get(e.floor_id)??[];group.push(e);openings.set(e.floor_id,group);}return openings;}
export function renderPieces(e:Element,m:Model,assumptions=false,openingFraction=0,context?:Map<string,Element[]>):Piece[]{
 if(assumptions&&['floor','roof'].includes(e.type)&&Array.isArray(e.source.architectural_slab_profiles)&&!e.source.architectural_slab_profiles.length)return [];
 if(assumptions&&['space','corridor'].includes(e.type)&&Array.isArray(e.source.architectural_space_profiles))return (e.source.architectural_space_profiles as Poly[]).map(poly=>({poly,z:e.z_offset,height:null,assumed:true}));
 if(e.components.length)return e.components.map(c=>({poly:c.role==='door_leaf'&&openingFraction?rotateDoor([c.polygon,...c.holes],e,openingFraction):[c.polygon,...c.holes],z:e.z_offset+c.z_offset,
  height:!assumptions&&c.source.geometry_status==='provisional'?null:c.height,role:c.role,
  assumed:c.source.geometry_status==='provisional',material:String(c.source.material??e.source.material??'unknown'),mesh:!assumptions&&c.source.geometry_status==='provisional'?null:c.mesh,componentId:c.id}));
 const vertical=assumptions?e.source.architectural_vertical_profiles as {polygon:XY[];holes:XY[][];z_offset:number;height:number;geometry_status:string}[]|undefined:undefined;
 if(e.type!=='wall'){
  if(vertical)return vertical.map(v=>({poly:[v.polygon,...v.holes],z:v.z_offset,height:v.height,assumed:v.geometry_status==='provisional'}));
  const assumed=assumptions&&e.height===null&&['door','window'].includes(e.type);
  return [{poly:raw(e),z:e.z_offset+(assumed&&e.type==='window'?previewDimensions.sill:0),height:assumed?(e.type==='door'?previewDimensions.door:previewDimensions.window):e.height,assumed}];
 }
 if(e.height===null)return [{poly:raw(e),z:e.z_offset,height:null}];
 const wallProfiles=(e.source.architectural_wall_profiles as Poly[]|undefined)??[raw(e)];
 if(!wallProfiles.length)return [];
 const eb=bounds([raw(e)]);
 const openings=(context?.get(e.floor_id)??m.elements.filter(d=>!d.excluded&&d.floor_id===e.floor_id&&['door','window'].includes(d.type))).flatMap(d=>{
  const rings=assumptions?d.source.architectural_opening_polygons as XY[][]|undefined:undefined;
  const profiles:Poly[]=rings?.map(r=>[r])??[raw(d)];
  const db=bounds(profiles);if(db.max[0]<eb.min[0]||db.min[0]>eb.max[0]||db.max[1]<eb.min[1]||db.min[1]>eb.max[1])return [];
  const assumed=assumptions&&d.height===null;if(d.height===null&&!assumed)return [];
  const provisional=d.source.provisional_opening as {z_offset:number;height:number}|undefined;
  const z=d.z_offset+(assumed?(provisional?.z_offset??(d.type==='window'?previewDimensions.sill:0)):0);
  return profiles.map(poly=>({poly,z,height:d.height??provisional?.height??(d.type==='window'?previewDimensions.window:previewDimensions.door),assumed}));
 });
 const envelopes=vertical?.map(v=>({poly:[v.polygon,...v.holes],z:v.z_offset,height:v.height,assumed:v.geometry_status==='provisional'}))??wallProfiles.map(poly=>({poly,z:e.z_offset,height:e.height!,assumed:false}));
 return envelopes.flatMap(envelope=>{
 const start=envelope.z,end=start+envelope.height;
 const levels=[...new Set([start,end,...openings.flatMap(d=>[Math.max(start,Math.min(end,d.z)),Math.max(start,Math.min(end,d.z+d.height))])])].sort((a,b)=>a-b);
 return levels.slice(1).flatMap((hi,i)=>{
  const lo=levels[i],cuts=openings.filter(d=>d.z<=lo&&d.z+d.height>=hi);
  const polys=cuts.length?pc.difference(envelope.poly,...cuts.map(d=>d.poly)) as Poly[]:[envelope.poly];
  return polys.map(poly=>({poly,z:lo,height:hi-lo,assumed:envelope.assumed||cuts.some(d=>d.assumed)}));
 });});
}
export function rotateDoor(poly:Poly,e:Element,fraction:number):Poly{
 const a=e.source.hinge as XY|undefined,b=e.source.leaf_end as XY|undefined,c=e.source.swing_end as XY|undefined;
 if(!a||!b||!c)return poly;
 const angle=Math.atan2((b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]),(b[0]-a[0])*(c[0]-a[0])+(b[1]-a[1])*(c[1]-a[1]))*Math.max(0,Math.min(1,fraction));
 const cos=Math.cos(angle),sin=Math.sin(angle);
 return poly.map(r=>r.map(p=>[a[0]+(p[0]-a[0])*cos-(p[1]-a[1])*sin,a[1]+(p[0]-a[0])*sin+(p[1]-a[1])*cos]));
}
export function planArea(e:Pick<Element,'polygon'|'holes'>){
 const area=(r:XY[])=>Math.abs(r.reduce((sum,a,i)=>{const b=r[(i+1)%r.length];return sum+a[0]*b[1]-b[0]*a[1];},0))/2;
 return area(e.polygon)-e.holes.reduce((sum,r)=>sum+area(r),0);
}
export function floorOffset(m:Model,floorId:string,separation:number){return Math.max(0,m.floors.findIndex(f=>f.id===floorId))*separation;}
