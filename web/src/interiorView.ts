import type {Model, XY} from './model';
import {raw,inside,edges,pointSegment,bounds} from './geometry';
import {planArea} from './bimGeometry';

// Viewpoint selection only. This does not add BF links or certify clearances.
export function interiorCeilingFloor(model:Model, floor:string):string|null {
  if(floor==='all')return null;
  const base=model.floors.find(f=>f.id===floor)?.elevation;
  if(base===undefined)return null;
  return model.floors.filter(f=>f.elevation>base && model.elements.some(e=>
    e.floor_id===f.id&&!e.excluded&&!e.source.unresolved_plan_only&&
    ['floor','roof'].includes(e.type)&&e.components.some(c=>c.height!==null)))
    .sort((a,b)=>a.elevation-b.elevation)[0]?.id??null;
}

export function interiorView(model:Model, floor:string, selected='') {
  const fid=floor==='all'?(model.elements.find(e=>e.id===selected)?.floor_id??model.floors.find(f=>f.id==='f1')?.id??model.floors[0].id):floor;
  const rooms=model.elements.filter(e=>e.floor_id===fid&&!e.excluded&&['space','corridor'].includes(e.type)&&e.source.space_usage!=='outdoor');
  const room=rooms.find(e=>e.id===selected)??rooms.sort((a,b)=>planArea(b)-planArea(a))[0];
  if(!room)return null;
  const region=raw(room), bb=bounds([region]);
  const obstacles=model.elements.filter(e=>e.floor_id===fid&&!e.excluded&&!e.source.unresolved_no_representation&&['wall','column','window','stair','elevator'].includes(e.type)).flatMap(e=>
    ['stair','elevator'].includes(e.type)?[raw(e)]:e.components.length?
      e.components.filter(c=>c.height!==null&&e.z_offset+c.z_offset<1.6&&e.z_offset+c.z_offset+c.height>1.6).map(c=>[c.polygon,...c.holes]):
      e.height!==null&&e.z_offset<1.6&&e.z_offset+e.height>1.6?[raw(e)]:[]);
  const local=obstacles.filter(p=>{const b=bounds([p]);return b.max[0]>=bb.min[0]&&b.min[0]<=bb.max[0]&&b.max[1]>=bb.min[1]&&b.min[1]<=bb.max[1];});
  const segments=[...region.flatMap(edges),...local.flatMap(p=>p.flatMap(edges))];
  const clear=(p:XY)=>inside(p,region)&&!local.some(q=>inside(p,q));
  let best:XY|null=null,score=-1;
  for(let i=0;i<15;i++)for(let j=0;j<15;j++){
    const p:XY=[bb.min[0]+(bb.max[0]-bb.min[0])*(i+.5)/15,bb.min[1]+(bb.max[1]-bb.min[1])*(j+.5)/15];
    if(!clear(p))continue;
    const distance=Math.min(...segments.map(([a,b])=>pointSegment(p,a,b)));
    if(distance>score){score=distance;best=p;}
  }
  if(!best)return null;
  let direction:XY=[0,-1],longest=-1;
  for(let i=0;i<16;i++){
    const d:XY=[Math.cos(i*Math.PI/8),Math.sin(i*Math.PI/8)];let run=0;
    for(let step=.25;step<=12;step+=.25){if(!clear([best[0]+d[0]*step,best[1]+d[1]*step]))break;run=step;}
    if(run>longest){longest=run;direction=d;}
  }
  return {floorId:fid,point:best,direction,roomId:room.id,clearanceM:score};
}
