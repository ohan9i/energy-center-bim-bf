import type {Model,Profile,XY} from './model';
import {profileSchema} from './model';
import {bounds,contained,touches,dist,raw,type Multi} from './geometry';
import {approved,covers,validateSpatial,physicalBlockers,union,difference,type Spatial,type Space} from './spatial';
import type {RouteResult,FloorCheck} from './navigation';
import type {Evaluation} from './evaluation';

type Node={floor:string;point:XY;space:string};
type Edge={to:number;distance:number;cost:number;via?:string;wait:number};
export interface SpatialNetwork {nodes:Node[];edges:Edge[][];space_edges:{from:string;to:string;via:string;kind:string}[];
 checks:Map<string,FloorCheck>;spaceChecks:Map<string,(a:XY,b:XY)=>boolean>;excluded:RouteResult['excluded'];}
const condition=(properties:{clear_width:number|null;step:number|null;operational:boolean|null;slope?:number|null},p:Profile)=>
 properties.clear_width!==null&&properties.clear_width>=Math.max(p.body_width,p.min_door_width)&&properties.step!==null&&
 properties.step<=p.max_step&&properties.operational===true;
export function buildSpatialNetwork(m:Model,input:Spatial,p:Profile,grid=.25):SpatialNetwork {
 profileSchema.parse(p);if(!Number.isFinite(grid)||grid<.1||grid>1)throw Error('격자 간격은 0.1~1 m 범위여야 합니다.');
 const s=validateSpatial(m,input),token=s.model_fingerprint;
 const spaces=s.spaces.filter(x=>approved(x,token)&&x.step!==null&&x.step<=p.max_step&&x.slope!==null&&x.slope<=p.max_slope);
 const spaceMap=new Map(spaces.map(x=>[x.id,x]));
 const candidates=s.portals.filter(g=>approved(g,token)&&condition(g.properties,p)&&g.space_ids.every(id=>spaceMap.has(id))&&
   (!g.element_id||!m.elements.find(e=>e.id===g.element_id)!.excluded)&&g.host_wall_ids.every(id=>!m.elements.find(e=>e.id===id)!.excluded));
 const net:SpatialNetwork={nodes:[],edges:[],space_edges:[],checks:new Map(),spaceChecks:new Map(),excluded:[]};
 for(const r of [...s.spaces,...s.portals,...s.vertical])if(!approved(r,token))net.excluded.push({id:r.id,status:'unknown',reasons:r.reasons.length?r.reasons:['공간/연결 검토 기록 미확정']});
 for(const r of s.spaces.filter(x=>approved(x,token)&&!spaceMap.has(x.id)))net.excluded.push({id:r.id,status:'blocked',reasons:['바닥 단차 또는 경사가 현재 이동 조건을 초과합니다.']});
 for(const r of s.portals.filter(x=>approved(x,token)&&!candidates.includes(x)))net.excluded.push({id:r.id,status:'blocked',reasons:['문 폭·단차·개폐 또는 연결 공간 조건 불충족']});
 const rawBlockers=physicalBlockers(m,s);
 const radius=p.body_width/2, corridorRadius=Math.max(radius,p.min_corridor_width/2);
 const safe=(a:XY,b:XY,r:Multi,obs:Multi,envelope:number)=>contained(a,b,r,envelope)&&!obs.some(o=>touches(a,b,o,envelope));
 const floorBlockers=(fid:string,allowed:Spatial['portals']):Multi=>{
  const pieces:Multi=[];
  for(const b of rawBlockers.filter(b=>b.floor_id===fid)){
   let r=b.region;
   // Only the explicitly reviewed car floor can occupy a shaft, never a corridor shortcut.
   for(const car of spaces.filter(x=>x.kind==='elevator_car'&&x.floor_id===fid)){
    if(b.kind==='elevator'&&b.element_id===car.element_id||b.kind==='void')r=difference(r,car.region);
   }
   // A doorway cuts only its explicitly associated wall, and only while its conditions pass.
   const cuts=allowed.filter(g=>g.host_wall_ids.includes(b.element_id??''));
   if(b.kind==='wall'&&cuts.length)r=difference(r,cuts.flatMap(g=>{
    if(g.kind==='open_passage')return g.region;
    const door=m.elements.find(e=>e.id===g.element_id)!;
    const fragments=(door.source.host_openings??[]) as {host_wall_id:string;polygon:XY[];holes:XY[][]}[];
    // Approach polygons cannot enlarge the measured opening along a host wall.
    const opening=union([raw(door),...fragments.filter(f=>f.host_wall_id===b.element_id).map(f=>[f.polygon,...(f.holes??[])])]);
    return difference(g.region,difference(g.region,opening));
   }));
   pieces.push(...r);
  }
  return pieces;
 };
 // A failed doorway must not carve a hole or relax room clearance. Validate
 // each approach using only its own host cut before building any space grids.
 const gates=candidates.filter(g=>{
  const r=union([...g.space_ids.flatMap(id=>spaceMap.get(id)!.region),...g.region]);
  const gateRadius=Math.max(radius,p.min_door_width/2);
  let consistentWidth=true;
  if(g.kind==='door'){
   const door=m.elements.find(e=>e.id===g.element_id)!;
   const length=dist(...g.points),normal:XY=[-(g.points[1][1]-g.points[0][1])/length,(g.points[1][0]-g.points[0][0])/length];
   const projections=door.polygon.map(p=>p[0]*normal[0]+p[1]*normal[1]);
   // Symbol span is an upper bound, never a measured effective width.
   // Do not apply the claimed door width to distant approach columns/endpoints.
   const span=Math.max(...projections)-Math.min(...projections);
   consistentWidth=Number.isFinite(span)&&g.properties.clear_width!<=span+1e-7;
  }
  if(consistentWidth&&safe(...g.points,r,floorBlockers(g.floor_id,[g]),gateRadius)&&contained(...g.points,g.region,gateRadius))return true;
  net.excluded.push({id:g.id,status:'blocked',reasons:['문 접근 구간이 벽·장애물 또는 기하학적 유효폭과 충돌합니다.']});return false;
 });
 const blockers=new Map(m.floors.map(f=>[f.id,floorBlockers(f.id,gates)]));
 const add=(space:Space,point:XY)=>{const id=net.nodes.length;net.nodes.push({floor:space.floor_id,space:space.id,point});net.edges.push([]);return id;};
 const connect=(a:number,b:number,d:number,cost=d,via?:string,wait=0)=>{net.edges[a].push({to:b,distance:d,cost,via,wait});net.edges[b].push({to:a,distance:d,cost,via,wait});};
 const grids=new Map<string,Map<string,number>>(),boxes=new Map<string,ReturnType<typeof bounds>>();
 for(const space of spaces){
  const incident=gates.filter(g=>g.space_ids.includes(space.id)),r=union([...space.region,...incident.flatMap(g=>g.region)]),obs=blockers.get(space.floor_id)!;
  const clear=(a:XY,b:XY)=>{
   if(!covers(space.region,a)||!covers(space.region,b)||!safe(a,b,r,obs,radius))return false;
   // Clearance relaxation is confined to the actual reviewed doorway footprint.
   const near=incident.some(g=>contained(a,b,g.region));
   return near||safe(a,b,r,obs,corridorRadius);
  };
  net.spaceChecks.set(space.id,clear);
  const box=bounds(space.region),nx=Math.ceil((box.max[0]-box.min[0])/grid),ny=Math.ceil((box.max[1]-box.min[1])/grid);
  if(nx*ny>50000||net.nodes.length+nx*ny>100000)throw Error('BF 공간 격자 범위가 너무 큽니다. 공간을 분리하거나 단위를 확인하세요.');
  const map=new Map<string,number>();grids.set(space.id,map);boxes.set(space.id,box);
  for(let x=0;x<=nx;x++)for(let y=0;y<=ny;y++){const pt:XY=[box.min[0]+x*grid,box.min[1]+y*grid];if(clear(pt,pt))map.set(`${x},${y}`,add(space,pt));}
  for(const [key,a] of map){const [x,y]=key.split(',').map(Number);for(const [dx,dy] of [[1,0],[0,1],[1,1],[1,-1]]){
   const b=map.get(`${x+dx},${y+dy}`);if(b!==undefined&&clear(net.nodes[a].point,net.nodes[b].point))connect(a,b,dist(net.nodes[a].point,net.nodes[b].point));
  }}
 }
 const anchor=(space:Space,point:XY)=>{
  if(!net.spaceChecks.get(space.id)!(point,point))return undefined;
  const a=add(space,point),box=boxes.get(space.id)!,map=grids.get(space.id)!;
  const x=Math.round((point[0]-box.min[0])/grid),y=Math.round((point[1]-box.min[1])/grid);
  for(let dx=-2;dx<=2;dx++)for(let dy=-2;dy<=2;dy++){
   const b=map.get(`${x+dx},${y+dy}`);if(b!==undefined&&dist(point,net.nodes[b].point)<=grid*2&&net.spaceChecks.get(space.id)!(point,net.nodes[b].point))connect(a,b,dist(point,net.nodes[b].point));
  }
  return a;
 };
 for(const g of gates){
  const [aSpace,bSpace]=g.space_ids.map(id=>spaceMap.get(id)!);
  const r=union([...aSpace.region,...bSpace.region,...g.region]);
  // Both the user's envelope and the claimed clear width are checked against geometry.
  const gateRadius=Math.max(radius,p.min_door_width/2);
  if(!safe(...g.points,r,blockers.get(g.floor_id)!,gateRadius)||!contained(...g.points,g.region,gateRadius)){
   net.excluded.push({id:g.id,status:'blocked',reasons:['문 접근 구간이 벽·장애물 또는 기하학적 유효폭과 충돌합니다.']});continue;
  }
  const a=anchor(aSpace,g.points[0]),b=anchor(bSpace,g.points[1]);
  if(a!==undefined&&b!==undefined){connect(a,b,dist(...g.points),dist(...g.points),g.id);net.space_edges.push({from:aSpace.id,to:bSpace.id,via:g.id,kind:g.kind});}
  else net.excluded.push({id:g.id,status:'blocked',reasons:['문 양측 접근점의 몸체 여유폭이 부족하여 공간 격자에 연결할 수 없습니다.']});
 }
 for(const v of s.vertical){
  if(!approved(v,token))continue;
  if(!condition(v.properties,p)||v.kind==='stair'&&!p.allow_stairs||v.kind==='ramp'&&(v.properties.slope===null||v.properties.slope>p.max_slope||v.properties.clear_width!<p.min_corridor_width)){
   net.excluded.push({id:v.id,status:'blocked',reasons:['층간 시설의 폭·단차·운행·경사 또는 계단 허용 조건 불충족']});continue;
  }
  const [aSpace,bSpace]=v.space_ids.map(id=>spaceMap.get(id));if(!aSpace||!bSpace){net.excluded.push({id:v.id,status:'blocked',reasons:['층간 시설에 연결된 공간의 바닥 통행 조건이 충족되지 않습니다.']});continue;}
  // Elevator nodes are car-floor nodes reached exclusively through reviewed landing doors.
  if(v.kind==='elevator'&&[aSpace,bSpace].some(car=>!net.space_edges.some(g=>g.kind==='door'&&(g.from===car.id||g.to===car.id)))){
   net.excluded.push({id:v.id,status:'blocked',reasons:['한쪽 층의 승강장 문 연결이 없어 승강기 층간 이동을 차단했습니다.']});continue;
  }
  const a=anchor(aSpace,v.points[0]),b=anchor(bSpace,v.points[1]);
  if(a!==undefined&&b!==undefined){const wait=v.kind==='elevator'?p.elevator_wait:0;connect(a,b,v.distance,v.distance*(v.kind==='stair'?p.stair_penalty:1)+wait*p.speed,v.id,wait);
   net.space_edges.push({from:aSpace.id,to:bSpace.id,via:v.id,kind:v.kind});}
  else net.excluded.push({id:v.id,status:'blocked',reasons:['층간 시설 접근점이 장애물 또는 이동 여유폭과 충돌합니다.']});
 }
 // Public floor check supports independent final-segment audits; cross-space movement must be a gate.
 for(const floor of m.floors){
  const local=spaces.filter(x=>x.floor_id===floor.id),localGates=s.portals.filter(g=>g.floor_id===floor.id);
  const clear=(a:XY,b:XY)=>local.some(x=>net.spaceChecks.get(x.id)!(a,b))||localGates.some(g=>{
   if(!net.space_edges.some(e=>e.via===g.id))return false;
   const inEither=(pt:XY)=>g.points.some(end=>dist(pt,end)<1e-7);
   return inEither(a)&&inEither(b)&&safe(a,b,union([...local.flatMap(x=>x.region),...g.region]),blockers.get(floor.id)!,radius);
  });
  net.checks.set(floor.id,{region:union(local.flatMap(x=>x.region)),obstacles:blockers.get(floor.id)!,gates:localGates.flatMap(g=>g.region.map(polygon=>({polygon,status:net.space_edges.some(e=>e.via===g.id)?'pass':approved(g,token)?'blocked':'unknown'}))),clear});
 }
 // Attach place nodes last, without introducing a shortcut between space graphs.
 for(const place of m.places){const owners=spaces.filter(s=>s.floor_id===place.floor_id&&covers(s.region,place.point));if(owners.length===1)anchor(owners[0],place.point);}
 const targets=new Map<string,Pick<Evaluation,'name'|'element_ids'|'floor_ids'|'spatial_kind'>>();
 for(const r of s.spaces)targets.set(r.id,{name:r.name,element_ids:r.element_id?[r.element_id]:[],floor_ids:[r.floor_id],spatial_kind:'spaces'});
 for(const r of s.portals)targets.set(r.id,{name:m.elements.find(e=>e.id===r.element_id)?.name??'개방 통로',element_ids:r.element_id?[r.element_id]:[],floor_ids:[r.floor_id],spatial_kind:'portals'});
 for(const r of s.vertical)targets.set(r.id,{name:{elevator:'승강기 층간 연결',stair:'계단 층간 연결',ramp:'경사로 층간 연결'}[r.kind],element_ids:r.element_ids,floor_ids:r.element_ids.map(id=>m.elements.find(e=>e.id===id)!.floor_id),spatial_kind:'vertical'});
 net.excluded=net.excluded.map(r=>({...r,...targets.get(r.id)}));
 return net;
}

export function findSpatialRoute(m:Model,startId:string,endId:string,p:Profile,grid=.25):RouteResult {
 profileSchema.parse(p);
 const start=m.places.find(x=>x.id===startId),end=m.places.find(x=>x.id===endId);if(!start||!end)throw Error('출발지와 목적지를 지정하세요.');
 const result:RouteResult={status:'no_path',points:[],distance:0,seconds:0,floors:[],uses_elevator:false,excluded:[],instructions:[],
 assumptions:'확인된 공간·문·층간 시설과 사용자 이동 조건에 의한 기하학 경로 검토입니다. 공식 BF 인증 판정이 아닙니다.',revision:m.revision,node_count:0};
 let net:SpatialNetwork;
 try {net=buildSpatialNetwork(m,m.provenance.bf_spatial as Spatial,p,grid);}catch(e){result.instructions=[e instanceof Error?e.message:String(e)];return result;}
 result.node_count=net.nodes.length;result.excluded=net.excluded;
 const find=(place:typeof start)=>net.nodes.findIndex(n=>n.floor===place.floor_id&&dist(n.point,place.point)<1e-7);
 const a=find(start),b=find(end);
 if(a<0||b<0){result.instructions=['출발지 또는 목적지의 공간 경계·바닥 통행 조건이 미확정이거나 이동 여유폭이 부족합니다. 검증 경로 생성을 차단했습니다.'];return result;}
 // Binary heap Dijkstra also handles stairs penalties and elevator waits without a misleading heuristic.
 const heap:{id:number;cost:number}[]=[];
 const push=(item:{id:number;cost:number})=>{heap.push(item);let i=heap.length-1;while(i>0){const j=(i-1)>>1;if(heap[j].cost<=item.cost)break;heap[i]=heap[j];i=j;}heap[i]=item;};
 const pop=()=>{const top=heap[0],last=heap.pop()!;if(heap.length){let i=0;while(i*2+1<heap.length){let j=i*2+1;if(j+1<heap.length&&heap[j+1].cost<heap[j].cost)j++;if(heap[j].cost>=last.cost)break;heap[i]=heap[j];i=j;}heap[i]=last;}return top;};
 const costs=new Map<number,number>([[a,0]]),prev=new Map<number,{node:number;edge:Edge}>();push({id:a,cost:0});
 let found=false;while(heap.length){const {id:u,cost}=pop();if(cost>(costs.get(u)??Infinity))continue;if(u===b){found=true;break;}
  for(const edge of net.edges[u]){const next=cost+edge.cost;if(next<(costs.get(edge.to)??Infinity)-1e-8){costs.set(edge.to,next);prev.set(edge.to,{node:u,edge});push({id:edge.to,cost:next});}}
 }
 if(!found){result.instructions=['확인된 출입구·개방 통로·승강장 문을 통한 공간 연결이 없습니다. 벽 또는 미확정 구간을 통과하는 경로는 생성하지 않습니다.'];return result;}
 const order=[b],vias:string[]=[];let cursor=b;
 while(cursor!==a){const item=prev.get(cursor)!;result.distance+=item.edge.distance;result.seconds+=item.edge.wait;if(item.edge.via)vias.push(item.edge.via);cursor=item.node;order.unshift(cursor);}
 result.status='found';result.points=order.map((id,i)=>({floor:net.nodes[id].floor,point:net.nodes[id].point,via:i?prev.get(id)?.edge.via:undefined}));
 result.floors=[...new Set(result.points.map(p=>p.floor))];result.uses_elevator=vias.some(id=>(m.provenance.bf_spatial as Spatial).vertical.some(v=>v.id===id&&v.kind==='elevator'));
 result.seconds+=result.distance/p.speed;
 const ledger=m.provenance.bf_spatial as Spatial;
 result.instructions=[start.name+'에서 출발합니다.',...order.slice(1).flatMap((id,i)=>{
  const via=prev.get(id)?.edge.via;if(!via)return [];
  const a=net.nodes[order[i]],b=net.nodes[id],gate=ledger.portals.find(g=>g.id===via);
  if(gate){const names=[a.space,b.space].map(id=>ledger.spaces.find(s=>s.id===id)?.name??id);return [`${m.elements.find(e=>e.id===gate.element_id)?.name??'개방 통로'}: ${names[0]} → ${names[1]}`];}
  const v=ledger.vertical.find(v=>v.id===via)!;
  return [`${{elevator:'승강기',stair:'계단',ramp:'경사로'}[v.kind]}: ${[a.floor,b.floor].map(id=>m.floors.find(f=>f.id===id)!.name).join(' → ')}`];
 }),end.name+'에 도착합니다.'];return result;
}
