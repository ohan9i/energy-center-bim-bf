import {parseModel,type Model} from '../src/model';
import {modelFingerprint,recordFingerprint,type Spatial} from '../src/spatial';
export const rect=(a:number,b:number,c:number,d:number):[number,number][]=>[[a,b],[c,b],[c,d],[a,d]];
export function spatialFixture():Model {
 const elements=['f1','f2'].flatMap(fid=>[
  {id:fid+'-floor',name:'Structural slab',type:'floor',floor_id:fid,polygon:rect(0,0,10,10),holes:[rect(5.3,3,9,6),rect(1,7,3,9)]},
  {id:fid+'-wall',name:'Shaft host wall',type:'wall',floor_id:fid,polygon:rect(5,0,5.3,10)},
  {id:fid+'-lift',name:'Elevator shaft',type:'elevator',floor_id:fid,polygon:rect(5.3,3,9,6)},
  {id:fid+'-door',name:'Landing door',type:'door',floor_id:fid,polygon:rect(5,3.7,5.3,5.3)},
  {id:fid+'-column',name:'Column',type:'column',floor_id:fid,polygon:rect(2.6,4,3.4,5)}
 ]);
 const m=parseModel({schema_version:'1.0',id:'spatial-test-only',name:'Explicit synthetic spatial routing test',units:'m',floors:[{id:'f1',name:'1F',elevation:0},{id:'f2',name:'2F',elevation:4.2}],elements,
  places:[{id:'entrance',name:'Entrance',floor_id:'f1',point:[2,2]},{id:'lift1',name:'Car 1F',floor_id:'f1',point:[7,4.5]},
   {id:'room2',name:'Room 2F',floor_id:'f2',point:[4,8]}],links:[],provenance:{precision_rebuild:true}});
 const token=modelFingerprint(m),evidence=['test-drawing:reviewed-fixture-geometry'];
 const approval={status:'confirmed' as const,evidence,review:{reviewer:'Test fixture author',reviewed_at:'2026-10-11T00:00:00Z',model_fingerprint:token,content_fingerprint:'',evidence},reasons:[]};
 const s:Spatial={version:'bf-spatial/1',model_id:m.id,model_fingerprint:token,override_state:'test_fixture',blockers:[],
  spaces:['f1','f2'].flatMap(fid=>[
   {id:fid+'-lobby',element_id:null,floor_id:fid,name:'Lobby',kind:fid==='f1'?'hall':'room',region:[[rect(0,0,5,10),rect(1,7,3,9)]],step:0,slope:0,...structuredClone(approval)},
   {id:fid+'-car',element_id:fid+'-lift',floor_id:fid,name:'Reviewed car floor',kind:'elevator_car',region:[[rect(5.3,3,9,6)]],step:0,slope:0,...structuredClone(approval)}
  ]),
  portals:['f1','f2'].map(fid=>({id:fid+'-gate',element_id:fid+'-door',floor_id:fid,kind:'door',space_ids:[fid+'-lobby',fid+'-car'],points:[[4,4.5],[6,4.5]],region:[[rect(3.4,3.7,6.6,5.3)]],host_wall_ids:[fid+'-wall'],properties:{clear_width:1.1,step:0,operational:true},...structuredClone(approval)})),
  vertical:[{id:'lift-link',kind:'elevator',element_ids:['f1-lift','f2-lift'],space_ids:['f1-car','f2-car'],points:[[7,4.5],[7,4.5]],distance:4.2,properties:{clear_width:1.1,step:0,operational:true,slope:null},...structuredClone(approval)}]};
 for(const r of [...s.spaces,...s.portals,...s.vertical])r.review!.content_fingerprint=recordFingerprint(r);
 m.provenance.bf_spatial=s;return m;
}
