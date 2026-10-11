import {describe,it,expect} from 'vitest';
import * as T from 'three';
import {batchElementMeshes,batchEdges,pickedComponent} from '../src/renderBatching';

describe('BIM rendering batches preserve identity',()=>{
 it('merges one object/material while retaining triangle-to-component mapping and bounds',()=>{
  const scene=new T.Scene();const make=(id:string,part:string,x:number)=>{
   const mesh=new T.Mesh(new T.BoxGeometry(1,1,1),new T.MeshStandardMaterial({color:0xaabbcc}));
   mesh.position.set(x,2,3);mesh.userData={id,componentId:part};scene.add(mesh);return mesh;
  };
  const a=make('stair','step-1',0),b=make('stair','step-2',1),c=make('other','part-3',5);
  const merged=batchElementMeshes([a,b,c],scene);
  expect(merged).toHaveLength(2);expect(merged[0].userData.id).toBe('stair');
  expect(pickedComponent(merged[0],0)).toBe('step-1');expect(pickedComponent(merged[0],12)).toBe('step-2');
  expect(pickedComponent(merged[1],0)).toBe('part-3');
  merged[0].geometry.computeBoundingBox();expect(merged[0].geometry.boundingBox!.max.toArray()).toEqual([1.5,2.5,3.5]);
 });
 it('batches only annotation lines and leaves semantic meshes selectable',()=>{
  const scene=new T.Scene(),edges=[0,1].map(x=>{const edge=new T.LineSegments(new T.EdgesGeometry(new T.BoxGeometry()),new T.LineBasicMaterial({color:0x555555,opacity:.2}));edge.position.x=x;scene.add(edge);return edge;});
  batchEdges(edges,scene);expect(scene.children).toHaveLength(1);expect((scene.children[0] as T.LineSegments).geometry.getAttribute('position').count).toBe(48);
 });
});
