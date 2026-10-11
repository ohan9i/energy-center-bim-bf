import {describe,it,expect} from 'vitest';
import * as T from 'three';
import {pieceGeometry,sectionCap,wallEdges} from '../src/architecturalGeometry';
import {parseModel} from '../src/model';
import {renderPieces} from '../src/bimGeometry';

function area(geo:T.BufferGeometry){const p=geo.getAttribute('position');let sum=0;for(let i=0;i<p.count;i+=3){const [a,b,c]=[0,1,2].map(j=>new T.Vector3().fromBufferAttribute(p,i+j));sum+=b.sub(a).cross(c.sub(a)).length()/2;}return sum;}
describe('actual architectural triangle geometry',()=>{
 it('removes artificial wall slice seams while retaining the real wall head',()=>{
  const pieces=[{poly:[[[0,0],[6,0],[6,.2],[0,.2]]] as [number,number][][],z:0,height:1.5},{poly:[[[0,0],[6,0],[6,.2],[0,.2]]] as [number,number][][],z:1.5,height:1.5}];
  const p=wallEdges(pieceGeometry(pieces[1]),pieces[1],pieces).getAttribute('position');
  let lower=0,upper=0;for(let i=0;i<p.count;i+=2){if(Math.abs(p.getY(i)-p.getY(i+1))<1e-5){if(Math.abs(p.getY(i))<1e-5)lower++;if(Math.abs(p.getY(i)-1.5)<1e-5)upper++;}}
  expect(lower).toBe(0);expect(upper).toBe(4);
 });
 it('fills horizontal slab section while preserving a through-shaft hole',()=>{
  const geo=pieceGeometry({poly:[[[0,0],[6,0],[6,6],[0,6]],[[2,2],[4,2],[4,4],[2,4]]],z:0,height:.2});
  const cap=sectionCap(geo,new T.Vector3(0,-.2,0),new T.Plane(new T.Vector3(0,-1,0),-.1));
  expect(cap).not.toBeNull();expect(area(cap!)).toBeCloseTo(32,4);
  cap!.computeBoundingBox();expect(cap!.boundingBox!.max.y).toBeCloseTo(-.1,3);
 });
 it('closes a vertical wall section from triangles and excludes a nonintersecting cut',()=>{
  const geo=pieceGeometry({poly:[[[0,0],[6,0],[6,.2],[0,.2]]],z:0,height:3});
  const cap=sectionCap(geo,new T.Vector3(),new T.Plane(new T.Vector3(-1,0,0),2));
  expect(area(cap!)).toBeCloseTo(.6);expect(sectionCap(geo,new T.Vector3(),new T.Plane(new T.Vector3(-1,0,0),8))).toBeNull();
 });
 it('rotates only the leaf according to CAD arc, without changing BF coordinates or components',()=>{
  const m=parseModel({schema_version:'1.0',id:'door',name:'Door',units:'m',floors:[{id:'f1',name:'1F',elevation:0}],places:[],links:[],elements:[{id:'d',name:'D',type:'door',floor_id:'f1',polygon:[[0,0],[1,0],[1,.04],[0,.04]],source:{hinge:[0,0],leaf_end:[1,0],swing_end:[0,1]},components:[{id:'leaf',role:'door_leaf',polygon:[[0,0],[1,0],[1,.04],[0,.04]],height:2.1,source:{geometry_status:'provisional'}}]}]});
  const before=JSON.stringify(m),opened=renderPieces(m.elements[0],m,true,1);
  expect(opened[0].poly[0][1][0]).toBeCloseTo(0);expect(opened[0].poly[0][1][1]).toBeCloseTo(1);
  expect(JSON.stringify(m)).toBe(before);expect(renderPieces(m.elements[0],m,false)[0].height).toBeNull();
 });
 it('applies provisional partial-height profiles only with assumptions enabled',()=>{
  const m=parseModel({schema_version:'1.0',id:'wall',name:'Wall',units:'m',floors:[{id:'f1',name:'1F',elevation:0}],places:[],links:[],elements:[{id:'w',name:'W',type:'wall',floor_id:'f1',height:4.2,polygon:[[0,0],[2,0],[2,.2],[0,.2]],source:{architectural_vertical_profiles:[{polygon:[[0,0],[2,0],[2,.2],[0,.2]],holes:[],height:3.97,z_offset:0,geometry_status:'provisional'}]}}]});
  expect(renderPieces(m.elements[0],m,true)[0].height).toBe(3.97);expect(renderPieces(m.elements[0],m,false)[0].height).toBe(4.2);
 });
});
