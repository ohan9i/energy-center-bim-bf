import {dist,bounds,floorRegion,footprints,raw,contained,touches,type Multi} from './geometry';
import {evaluate,type Evaluation} from './evaluation';
import {profileSchema,type Model,type Profile,type XY} from './model';
import {findSpatialRoute,buildSpatialNetwork} from './spatialRoute';
import type {Spatial} from './spatial';
type Node={floor:string;point:XY;place?:string};
type Edge={to:number;distance:number;cost:number;link?:string};
export interface RoutePoint {floor:string;point:XY;via?:string}
export interface RouteResult {status:'found'|'no_path';points:RoutePoint[];distance:number;seconds:number;floors:string[];uses_elevator:boolean;excluded:Evaluation[];instructions:string[];assumptions:string;revision:number;node_count:number}
export interface FloorCheck {region:Multi;obstacles:Multi;gates:{polygon:ReturnType<typeof raw>;status:string}[];clear:(a:XY,b:XY)=>boolean}
export function floorCheck(m:Model,floor:string,p:Profile):FloorCheck {
 if(m.provenance.bf_spatial)return buildSpatialNetwork(m,m.provenance.bf_spatial as Spatial,p).checks.get(floor)!;
 if(m.provenance.precision_rebuild)return {region:[],obstacles:[],gates:[],clear:()=>false};
 const es=m.elements.filter(e=>e.floor_id===floor&&!e.excluded), region=floorRegion(m,floor);
 const doors=es.filter(e=>e.type==='door');
 const obstacles=es.filter(e=>['wall','column','obstacle','unclassified'].includes(e.type)).flatMap(e=>footprints(e,m));
 // Unknown floor geometry and floor elevation changes cannot be presumed traversable.
 const zones=es.filter(e=>['floor','door','ramp','stair','corridor','elevator'].includes(e.type)&&evaluate(e,p).status!=='pass').map(raw);
 const gates=doors.map(e=>({polygon:raw(e),status:evaluate(e,p).status}));
 const clear=(a:XY,b:XY)=>{
  const radius=p.body_width/2;
  if(!contained(a,b,region,radius)||zones.some(poly=>touches(a,b,poly,radius))||obstacles.some(poly=>touches(a,b,poly,radius)))return false;
  // Door approaches have body-envelope clearance; the doorway itself is checked separately.
  // Outside these approaches, require half the requested corridor width on every side.
  const nearDoor=doors.some(e=>touches(a,b,raw(e),p.min_corridor_width));
  const corridorRadius=Math.max(radius,p.min_corridor_width/2);
  if(!nearDoor&&(!contained(a,b,region,corridorRadius)||obstacles.some(poly=>touches(a,b,poly,corridorRadius))))return false;
  return true;
 };
 return {region,obstacles,gates,clear};
}
class Heap {
 data:{id:number;f:number}[]=[];
 push(x:{id:number;f:number}){const a=this.data;a.push(x);let i=a.length-1;while(i>0){const j=(i-1)>>1;if(a[j].f<=x.f)break;a[i]=a[j];i=j;}a[i]=x;}
 pop(){const a=this.data,top=a[0],last=a.pop()!;if(a.length){let i=0;while(i*2+1<a.length){let j=i*2+1;if(j+1<a.length&&a[j+1].f<a[j].f)j++;if(a[j].f>=last.f)break;a[i]=a[j];i=j;}a[i]=last;}return top;}
}
export function findRoute(m:Model,startId:string,endId:string,p:Profile,grid=.25):RouteResult {
 if(m.provenance.bf_spatial)return findSpatialRoute(m,startId,endId,p,grid);
 if(m.provenance.precision_rebuild)return findSpatialRoute(m,startId,endId,p,grid);
 profileSchema.parse(p);
 if(grid<.1||grid>1)throw Error('격자 간격은 0.1~1 m 범위여야 합니다.');
 const start=m.places.find(x=>x.id===startId),end=m.places.find(x=>x.id===endId);
 if(!start||!end)throw Error('출발지와 목적지를 지정하세요.');
 const excluded=m.elements.filter(x=>!x.excluded&&['door','floor','ramp','stair','elevator','unclassified','corridor'].includes(x.type)).map(x=>evaluate(x,p)).filter(x=>x.status!=='pass');
 const result:RouteResult={status:'no_path',points:[],distance:0,seconds:0,floors:[],uses_elevator:false,excluded,instructions:[],assumptions:`이동속도 ${p.speed} m/s, 승강기 1회 대기 ${p.elevator_wait}초. 사용자 조건에 의한 기하학 검토이며 BF 인증 판정은 아닙니다.`,revision:m.revision,node_count:0};
 const nodes:Node[]=[],adj:Edge[][]=[],checks=new Map<string,FloorCheck>(),maps=new Map<string,Map<string,number>>();
 const add=(n:Node)=>{nodes.push(n);adj.push([]);return nodes.length-1;};
 const connect=(a:number,b:number,d:number,cost=d,link?:string)=>{adj[a].push({to:b,distance:d,cost,link});adj[b].push({to:a,distance:d,cost,link});};
 for(const floor of m.floors){
  const check=floorCheck(m,floor.id,p);checks.set(floor.id,check);const map=new Map<string,number>();maps.set(floor.id,map);
  if(!check.region.length)continue;
  if(!m.elements.some(e=>e.type==='floor'&&e.floor_id===floor.id&&!e.excluded&&evaluate(e,p).status==='pass'))continue;
  const box=bounds(check.region),nx=Math.ceil((box.max[0]-box.min[0])/grid),ny=Math.ceil((box.max[1]-box.min[1])/grid);
  if(nx*ny>50000||nodes.length+nx*ny>100000)throw Error('도면 범위가 너무 큽니다. 단위와 층별 도면 범위를 확인하거나 모델을 분리하세요.');
  for(let x=0;x<=nx;x++)for(let y=0;y<=ny;y++){const pt:XY=[box.min[0]+x*grid,box.min[1]+y*grid];if(check.clear(pt,pt))map.set(`${x},${y}`,add({floor:floor.id,point:pt}));}
  for(const [key,a] of map){const [x,y]=key.split(',').map(Number);for(const [dx,dy] of [[1,0],[0,1],[1,1],[1,-1]]){const b=map.get(`${x+dx},${y+dy}`);if(b!==undefined&&check.clear(nodes[a].point,nodes[b].point))connect(a,b,dist(nodes[a].point,nodes[b].point));}}
 }
 const placeNodes=new Map<string,number>();
 for(const place of m.places){
  const check=checks.get(place.floor_id)!;if(!check.clear(place.point,place.point))continue;
  const a=add({floor:place.floor_id,point:place.point,place:place.id});placeNodes.set(place.id,a);
  const candidates=[...(maps.get(place.floor_id)?.values()||[])].map(id=>({id,d:dist(place.point,nodes[id].point)})).filter(x=>x.d<=grid*2).sort((a,b)=>a.d-b.d);
  for(const b of candidates)if(check.clear(place.point,nodes[b.id].point))connect(a,b.id,b.d);
 }
 for(const l of m.links){const e=m.elements.find(x=>x.id===l.element_id)!;if(evaluate(e,p).status!=='pass')continue;const a=placeNodes.get(l.from_place),b=placeNodes.get(l.to_place);if(a!==undefined&&b!==undefined){const elevation=Math.abs(m.floors.find(f=>f.id===nodes[a].floor)!.elevation-m.floors.find(f=>f.id===nodes[b].floor)!.elevation);if(l.distance+1e-8<elevation)throw Error(l.id+': 층간 이동 길이가 층간 높이보다 짧습니다.');connect(a,b,l.distance,l.distance*(e.type==='stair'?p.stair_penalty:1)+(e.type==='elevator'?p.elevator_wait*p.speed:0),l.id);}}
 result.node_count=nodes.length;
 const a=placeNodes.get(startId),b=placeNodes.get(endId);
 if(a===undefined||b===undefined){result.instructions=['출발지 또는 목적지가 확인된 이동 가능 영역 밖에 있습니다. 미확인 바닥·문·층간 시설의 속성을 보완하세요.'];return result;}
 const costs=new Map<number,number>([[a,0]]),prev=new Map<number,{node:number;edge:Edge}>(),queue=new Heap();
 // Horizontal Euclidean distance is admissible if all floor links keep XY fixed.
 // Arbitrary CAD links may change XY, so use zero heuristic (A* reduces to Dijkstra).
 const aligned=m.links.every(l=>dist(m.places.find(x=>x.id===l.from_place)!.point,m.places.find(x=>x.id===l.to_place)!.point)<1e-8);
 const heuristic=(id:number)=>aligned?dist(nodes[id].point,nodes[b].point):0;
 queue.push({id:a,f:heuristic(a)});let found=false;
 while(queue.data.length){const item=queue.pop(),u=item.id;if(item.f>(costs.get(u)??Infinity)+heuristic(u)+1e-8)continue;if(u===b){found=true;break;}for(const edge of adj[u]){const next=costs.get(u)!+edge.cost;if(next<(costs.get(edge.to)??Infinity)-1e-8){costs.set(edge.to,next);prev.set(edge.to,{node:u,edge});queue.push({id:edge.to,f:next+heuristic(edge.to)});}}}
 if(!found){result.instructions=['현재 이동 조건을 만족하는 연결 경로가 없습니다. 문 유효폭·단차·층간 시설 및 확인 필요 요소를 검토하세요.'];return result;}
 const order=[b];let cursor=b;const usedLinks:string[]=[];while(cursor!==a){const item=prev.get(cursor)!;result.distance+=item.edge.distance;if(item.edge.link)usedLinks.push(item.edge.link);cursor=item.node;order.unshift(cursor);}
 result.status='found';result.floors=[...new Set(order.map(id=>nodes[id].floor))];
 result.points=order.map((id,i)=>({floor:nodes[id].floor,point:nodes[id].point,via:i?prev.get(id)?.edge.link:undefined}));
 result.uses_elevator=usedLinks.some(id=>m.elements.find(e=>e.id===m.links.find(l=>l.id===id)!.element_id)!.type==='elevator');
 result.seconds=result.distance/p.speed+usedLinks.reduce((n,id)=>n+(m.elements.find(e=>e.id===m.links.find(l=>l.id===id)!.element_id)!.type==='elevator'?p.elevator_wait:0),0);
 result.instructions=[`${start.name}에서 출발합니다.`,...usedLinks.reverse().map(id=>{const l=m.links.find(x=>x.id===id)!,e=m.elements.find(x=>x.id===l.element_id)!;return `${e.name}을 이용해 층을 이동합니다.`;}),`${end.name}에 도착합니다.`, '문·벽체·장애물의 기하학과 현재 이동 조건을 적용했습니다.'];
 return result;
}
