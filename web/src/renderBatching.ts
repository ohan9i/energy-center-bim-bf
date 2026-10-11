import * as T from 'three';
import {mergeGeometries} from 'three/addons/utils/BufferGeometryUtils.js';

/** Batch only within one BIM object/material. Triangle ranges preserve part IDs. */
export function batchElementMeshes(meshes:T.Mesh[],scene:T.Scene):T.Mesh[]{
 const groups=new Map<string,T.Mesh[]>();
 for(const mesh of meshes){
  const m=mesh.material as T.MeshStandardMaterial;
  const key=[mesh.userData.id,m.type,m.color.getHex(),m.roughness,m.metalness,m.opacity,m.transparent,m.side,mesh.userData.role==='section_cap'?'cut':'body'].join(':');
  const group=groups.get(key)??[];group.push(mesh);groups.set(key,group);
 }
 return [...groups.values()].map(group=>{
  if(group.length===1)return group[0];
  const parts:{start:number;end:number;componentId?:string;role?:string}[]=[];let triangles=0;
  const geometries=group.map(mesh=>{
   mesh.updateMatrix();let geo=mesh.geometry.clone();
   if(geo.index){const old=geo;geo=geo.toNonIndexed();old.dispose();}
   geo.deleteAttribute('uv');geo.applyMatrix4(mesh.matrix);
   const count=geo.getAttribute('position').count/3;
   parts.push({start:triangles,end:triangles+count,componentId:mesh.userData.componentId,role:mesh.userData.role});triangles+=count;return geo;
  });
  const geometry=mergeGeometries(geometries)!;for(const geo of geometries)geo.dispose();
  const mesh=new T.Mesh(geometry,group[0].material);mesh.userData={...group[0].userData,parts};
  mesh.castShadow=group.some(m=>m.castShadow);mesh.receiveShadow=group.some(m=>m.receiveShadow);
  for(const [i,old] of group.entries()){scene.remove(old);old.geometry.dispose();if(i)(old.material as T.Material).dispose();}
  scene.add(mesh);return mesh;
 });
}

/** Edges are visual annotations, independently batched from semantic objects. */
export function batchEdges(edges:T.LineSegments[],scene:T.Scene){
 const groups=new Map<string,T.LineSegments[]>();
 for(const edge of edges){const m=edge.material as T.LineBasicMaterial,key=m.color.getHex()+':'+m.opacity;const group=groups.get(key)??[];group.push(edge);groups.set(key,group);}
 for(const group of groups.values()){
  if(group.length===1)continue;
  const geometries=group.map(edge=>{edge.updateMatrix();return edge.geometry.clone().applyMatrix4(edge.matrix);});
  const merged=new T.LineSegments(mergeGeometries(geometries)!,group[0].material);
  for(const geo of geometries)geo.dispose();
  for(const [i,old] of group.entries()){scene.remove(old);old.geometry.dispose();if(i)(old.material as T.Material).dispose();}
  scene.add(merged);
 }
}

export function pickedComponent(mesh:T.Mesh,face:number|null|undefined):string{
 return mesh.userData.parts?.find((p:{start:number;end:number})=>face!==null&&face!==undefined&&face>=p.start&&face<p.end)?.componentId??mesh.userData.componentId??'';
}
