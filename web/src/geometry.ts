import pc from 'polygon-clipping';
import type {Element,Model,XY} from './model';
export type Poly=XY[][];
export type Multi=Poly[];
const EPS=1e-8;
export const dist=(a:XY,b:XY)=>Math.hypot(a[0]-b[0],a[1]-b[1]);
const cross=(a:XY,b:XY,c:XY)=>(b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]);
export function pointSegment(p:XY,a:XY,b:XY){const dx=b[0]-a[0],dy=b[1]-a[1];const t=Math.max(0,Math.min(1,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/(dx*dx+dy*dy||1)));return dist(p,[a[0]+t*dx,a[1]+t*dy]);}
export function intersects(a:XY,b:XY,c:XY,d:XY){
  if(Math.max(a[0],b[0])+EPS<Math.min(c[0],d[0])||Math.max(c[0],d[0])+EPS<Math.min(a[0],b[0])||Math.max(a[1],b[1])+EPS<Math.min(c[1],d[1])||Math.max(c[1],d[1])+EPS<Math.min(a[1],b[1])) return false;
  const x=cross(a,b,c),y=cross(a,b,d),u=cross(c,d,a),v=cross(c,d,b);
  return x*y<=EPS&&u*v<=EPS;
}
export function segmentDistance(a:XY,b:XY,c:XY,d:XY){return intersects(a,b,c,d)?0:Math.min(pointSegment(a,c,d),pointSegment(b,c,d),pointSegment(c,a,b),pointSegment(d,a,b));}
export function edges(r:XY[]){return r.map((p,i)=>[p,r[(i+1)%r.length]] as [XY,XY]).filter(([a,b])=>dist(a,b)>EPS);}
export function insideRing(p:XY,r:XY[]){let yes=false;for(const [a,b] of edges(r)){if(pointSegment(p,a,b)<EPS)return true;if((a[1]>p[1])!==(b[1]>p[1])&&p[0]<(b[0]-a[0])*(p[1]-a[1])/(b[1]-a[1])+a[0])yes=!yes;}return yes;}
export function inside(p:XY,poly:Poly){return insideRing(p,poly[0])&&!poly.slice(1).some(r=>insideRing(p,r));}
export function touches(a:XY,b:XY,poly:Poly,r=0){return inside(a,poly)||inside(b,poly)||poly.some(ring=>edges(ring).some(([c,d])=>segmentDistance(a,b,c,d)<=r+EPS));}
export function contained(a:XY,b:XY,region:Multi,r=0){return region.some(poly=>inside(a,poly)&&inside(b,poly)&&poly.every(ring=>edges(ring).every(([c,d])=>segmentDistance(a,b,c,d)>r+EPS)));}
export function raw(e:Element):Poly{return [e.polygon,...e.holes];}
export function footprints(e:Element,m:Model):Multi {
  const eb=bounds([raw(e)]);
  const doors=m.elements.filter(d=>{if(d.type!=='door'||d.floor_id!==e.floor_id||d.excluded)return false;const db=bounds([raw(d)]);return db.max[0]>=eb.min[0]&&db.min[0]<=eb.max[0]&&db.max[1]>=eb.min[1]&&db.min[1]<=eb.max[1];});
  return e.type==='wall'&&doors.length?pc.difference(raw(e),...doors.map(raw)) as Multi:[raw(e)];
}
export function floorRegion(m:Model,floor:string):Multi{
 const floors=m.elements.filter(e=>e.type==='floor'&&e.floor_id===floor&&!e.excluded);
 return floors.length?pc.union(...floors.map(raw) as [Poly,...Poly[]]) as Multi:[];
}
export function bounds(region:Multi){const p=region.flat(2);return {min:[Math.min(...p.map(x=>x[0])),Math.min(...p.map(x=>x[1]))] as XY,max:[Math.max(...p.map(x=>x[0])),Math.max(...p.map(x=>x[1]))] as XY};}
export function validateGeometry(m:Model){for(const e of m.elements.flatMap(e=>[e,...e.components.map((c,i)=>({...e,...c,id:e.id+'/component/'+i,components:[]}))])){for(const ring of [e.polygon,...e.holes]){const es=edges(ring);if(es.length<3||Math.abs(ring.reduce((n,a,i)=>n+a[0]*ring[(i+1)%ring.length][1]-ring[(i+1)%ring.length][0]*a[1],0))<EPS)throw Error(e.id+': 면적이 없는 다각형입니다.');for(let i=0;i<es.length;i++)for(let j=i+2;j<es.length;j++){if(i===0&&j===es.length-1)continue;if(intersects(...es[i],...es[j]))throw Error(e.id+': 자기교차 다각형입니다.');}}
 const ringArea=(r:XY[])=>Math.abs(r.reduce((n,a,i)=>n+a[0]*r[(i+1)%r.length][1]-r[(i+1)%r.length][0]*a[1],0))/2;
 const area=(multi:Multi)=>multi.reduce((n,p)=>n+ringArea(p[0])-p.slice(1).reduce((v,r)=>v+ringArea(r),0),0);
 // A hole may touch a boundary at a single point (valid OGC polygon). Require
 // area containment rather than rejecting every boundary intersection.
 for(let i=0;i<e.holes.length;i++){const h=e.holes[i];if(area(pc.difference([h],[e.polygon]) as Multi)>EPS)throw Error(e.id+': 개구부는 외곽 내부에 있어야 합니다.');for(let j=0;j<i;j++){if(area(pc.intersection([h],[e.holes[j]]) as Multi)>EPS)throw Error(e.id+': 개구부가 서로 겹칩니다.');}}
 pc.union(raw(e));}}
