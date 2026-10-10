import {describe,it,expect} from 'vitest';
import {readFileSync} from 'node:fs';
import {renderToStaticMarkup} from 'react-dom/server';
import {createElement} from 'react';
import {parseModel} from '../src/model';
import {renderPieces,planArea,floorOffset} from '../src/bimGeometry';
import Viewer from '../src/Viewer';
const model=()=>parseModel({schema_version:'1.0',id:'test',name:'Test',units:'m',floors:[{id:'f1',name:'1F',elevation:0}],places:[],links:[],elements:[
 {id:'wall',name:'Wall',type:'wall',floor_id:'f1',polygon:[[0,0],[6,0],[6,.2],[0,.2]],height:3},
 {id:'door',name:'Door',type:'door',floor_id:'f1',polygon:[[1,-.1],[2,-.1],[2,.3],[1,.3]],height:2.1},
 {id:'window',name:'Window',type:'window',floor_id:'f1',polygon:[[3,-.1],[5,-.1],[5,.3],[3,.3]],height:1.2,z_offset:.9}]});
describe('architectural BIM geometry',()=>{
 it('retains window sill and opening head, matching IFC vertical slices',()=>{
  const m=model(),parts=renderPieces(m.elements[0],m);
  const areaAt=(z:number)=>parts.filter(p=>p.z<=z&&z<p.z+p.height!).reduce((sum,p)=>sum+planArea({polygon:p.poly[0],holes:p.poly.slice(1)}),0);
  expect(areaAt(.5)).toBeCloseTo(1);expect(areaAt(1.5)).toBeCloseTo(.6);expect(areaAt(2.5)).toBeCloseTo(1.2);
 });
 it('keeps preview height assumptions outside persisted model geometry',()=>{
  const m=model();m.elements[2].height=null;const before=JSON.stringify(m);
  expect(renderPieces(m.elements[2],m,false)[0].height).toBeNull();
  expect(renderPieces(m.elements[2],m,true)[0]).toMatchObject({assumed:true,z:1.8,height:2.4});
  expect(JSON.stringify(m)).toBe(before);
 });
 it('separates storeys without modifying architectural elevations',()=>{
  const m=model();m.floors.push({id:'f2',name:'2F',elevation:4.2});expect(floorOffset(m,'f2',6)).toBe(6);expect(m.floors[1].elevation).toBe(4.2);
 });
 it('uses full host depth for provisional openings while preserving route footprint and saved values',()=>{
  const m=model();m.elements[1].height=null;
  m.elements[1].polygon=[[1,0],[2,0],[2,.1],[1,.1]];
  m.elements[1].source={provisional_opening:{height:2.1,z_offset:0},architectural_opening_polygons:[[[1,-.01],[2,-.01],[2,.21],[1,.21]]]};
  const before=JSON.stringify(m),pieces=renderPieces(m.elements[0],m,true);
  const area=pieces.filter(p=>p.z<=.5&&.5<p.z+p.height!).reduce((sum,p)=>sum+planArea({polygon:p.poly[0],holes:p.poly.slice(1)}),0);
  expect(area).toBeCloseTo(1);expect(JSON.stringify(m)).toBe(before);
 });
 it('keeps original BIM object when its duplicate wall solid is removed',()=>{
  const m=model();m.elements[0].source.architectural_wall_profiles=[];
  expect(renderPieces(m.elements[0],m,true)).toEqual([]);
  expect(planArea(m.elements[0])).toBeCloseTo(1.2);
 });
 it('renders architectural controls and disclosure for unknown heights',()=>{
  const m=model(),profile=JSON.parse(readFileSync(new URL('../public/rules.json',import.meta.url),'utf8')).profiles.wheelchair;
  const html=renderToStaticMarkup(createElement(Viewer,{model:m,floor:'f1',plan:false,selected:'',route:null,profile,onSelect:()=>{}}));
  for(const label of ['벽 숨김','실 영역','실내 시점','단면 방향','층 분리 간격','JSON/IFC에도 미확정 근거를 보존합니다'])expect(html).toContain(label);
 });
});
