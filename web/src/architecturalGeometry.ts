import * as T from 'three';
import type {Piece} from './bimGeometry';
import type {XY} from './model';
import {insideRing,inside} from './geometry';

export function pieceGeometry(piece:Piece,flat=false):T.BufferGeometry{
 if(piece.mesh&&!flat){
  const geo=new T.BufferGeometry();
  geo.setAttribute('position',new T.Float32BufferAttribute(piece.mesh.vertices.flatMap(([x,y,z])=>[x,z,y]),3));
  // Swapping model Y/Z reverses orientation; keep outward normals.
  geo.setIndex(piece.mesh.triangles.flatMap(([a,b,c])=>[a,c,b]));
  const result=geo.toNonIndexed();geo.dispose();result.computeVertexNormals();return result;
 }
 const shape=new T.Shape(piece.poly[0].map(([x,y])=>new T.Vector2(x,-y)));
 for(const r of piece.poly.slice(1))shape.holes.push(new T.Path(r.map(([x,y])=>new T.Vector2(x,-y))));
 const geo=flat||piece.height===null?new T.ShapeGeometry(shape):new T.ExtrudeGeometry(shape,{depth:piece.height,bevelEnabled:false,steps:1});
 return geo.rotateX(-Math.PI/2);
}

/** Suppress horizontal seams introduced solely by vertical opening slices. */
export function wallEdges(geo:T.BufferGeometry,piece:Piece,pieces:Piece[]):T.EdgesGeometry{
 const edges=new T.EdgesGeometry(geo,35),position=edges.getAttribute('position'),kept:number[]=[];
 for(let i=0;i<position.count;i+=2){
  const a=new T.Vector3().fromBufferAttribute(position,i),b=new T.Vector3().fromBufferAttribute(position,i+1);
  const z=piece.z+(a.y+b.y)/2,length=Math.hypot(b.x-a.x,b.z-a.z);
  let seam=false;
  if(Math.abs(a.y-b.y)<1e-6&&length>1e-6){
   const x=(a.x+b.x)/2,y=(a.z+b.z)/2,nx=-(b.z-a.z)/length*.00005,ny=(b.x-a.x)/length*.00005;
   const occupied=(level:number)=>pieces.some(p=>p.height!==null&&level>p.z&&level<p.z+p.height&&(inside([x+nx,y+ny],p.poly)||inside([x-nx,y-ny],p.poly)));
   seam=occupied(z-.0001)&&occupied(z+.0001);
  }
  if(!seam)kept.push(...a.toArray(),...b.toArray());
 }
 edges.setAttribute('position',new T.Float32BufferAttribute(kept,3));return edges;
}

/** Slice the actual triangles, reconstruct nested loops, preserve voids.
 * Unlike a bounding-box filler this cannot fill a courtyard or shaft hole. */
export function sectionCap(geo:T.BufferGeometry,offset:T.Vector3,plane:T.Plane):T.BufferGeometry|null{
 const pos=geo.getAttribute('position'),index=geo.getIndex();
 const count=index?.count??pos.count;
 const key=(p:T.Vector3)=>p.toArray().map(x=>Math.round(x*1e5)).join(':');
 const points=new Map<string,T.Vector3>(),adj=new Map<string,Set<string>>();
 for(let i=0;i<count;i+=3){
  const pts=[0,1,2].map(j=>new T.Vector3().fromBufferAttribute(pos,index?.getX(i+j)??i+j).add(offset));
  const ds=pts.map(p=>plane.distanceToPoint(p));if(ds.every(d=>d>=-1e-7)||ds.every(d=>d<=1e-7))continue;
  const hits:T.Vector3[]=[];
  for(let j=0;j<3;j++){const k=(j+1)%3;
   if(Math.abs(ds[j])<1e-7)hits.push(pts[j]);
   else if(ds[j]*ds[k]<0)hits.push(pts[j].clone().lerp(pts[k],ds[j]/(ds[j]-ds[k])));
  }
  const unique=[...new Map(hits.map(p=>[key(p),p])).values()];if(unique.length!==2)continue;
  const [a,b]=unique.map(key);if(a===b)continue;
  for(const p of unique)points.set(key(p),p);
  (adj.get(a)??adj.set(a,new Set()).get(a)!).add(b);(adj.get(b)??adj.set(b,new Set()).get(b)!).add(a);
 }
 const loops:T.Vector3[][]=[];
 while(adj.size){
  const start=adj.keys().next().value!;let current=start,previous='',closed=false;const loop:T.Vector3[]=[];
  for(let limit=0;limit<=points.size;limit++){
   loop.push(points.get(current)!);const next=[...(adj.get(current)??[])].find(k=>k!==previous);if(!next)break;
   adj.get(current)?.delete(next);adj.get(next)?.delete(current);
   if(!adj.get(current)?.size)adj.delete(current);if(!adj.get(next)?.size)adj.delete(next);
   previous=current;current=next;if(current===start){closed=true;break;}
  }
  if(closed&&loop.length>=3)loops.push(loop);else adj.delete(current);
 }
 if(!loops.length)return null;
 const normal=plane.normal,u=Math.abs(normal.x)>.5?new T.Vector3(0,0,1):new T.Vector3(1,0,0),v=new T.Vector3().crossVectors(normal,u);
 const rings=loops.map(loop=>loop.map(p=>[p.dot(u),p.dot(v)] as XY));
 const area=(r:XY[])=>Math.abs(r.reduce((n,a,i)=>{const b=r[(i+1)%r.length];return n+a[0]*b[1]-a[1]*b[0];},0));
 const parents=rings.map((r,i)=>rings.map((p,j)=>({j,a:area(p)})).filter(q=>q.j!==i&&q.a>area(r)&&insideRing(r[0],rings[q.j])).sort((a,b)=>a.a-b.a)[0]?.j??-1);
 const depth=(i:number):number=>parents[i]<0?0:1+depth(parents[i]);
 const vertices:number[]=[];
 for(let i=0;i<rings.length;i++)if(depth(i)%2===0){
  const shape=new T.Shape(rings[i].map(p=>new T.Vector2(...p)));
  for(let j=0;j<rings.length;j++)if(parents[j]===i)shape.holes.push(new T.Path(rings[j].map(p=>new T.Vector2(...p))));
  const cap=new T.ShapeGeometry(shape).toNonIndexed(),attr=cap.getAttribute('position');
  for(let k=0;k<attr.count;k++){const p=u.clone().multiplyScalar(attr.getX(k)).addScaledVector(v,attr.getY(k)).addScaledVector(normal,-plane.constant+.00015);vertices.push(...p.toArray());}
  cap.dispose();
 }
 if(!vertices.length)return null;
 const cap=new T.BufferGeometry();cap.setAttribute('position',new T.Float32BufferAttribute(vertices,3));cap.computeVertexNormals();return cap;
}
