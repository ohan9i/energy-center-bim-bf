import {z} from 'zod';
import pc from 'polygon-clipping';
import type {Model,XY,Element} from './model';
import {raw,inside,dist,validateGeometry,type Multi,type Poly} from './geometry';

const n=z.number().finite(), point=z.tuple([n,n]), ring=z.array(point).min(3).max(2000);
const region=z.array(z.array(ring).min(1)).max(2000);
const review=z.object({reviewer:z.string().min(1),reviewed_at:z.string().datetime({offset:true}),
  model_fingerprint:z.string(),content_fingerprint:z.string(),evidence:z.array(z.string().min(1)).min(1)}).strict().nullable();
const approval={status:z.enum(['unresolved','confirmed']),evidence:z.array(z.string()),review,reasons:z.array(z.string())};
const conditions=z.object({clear_width:n.positive().nullable(),step:n.nonnegative().nullable(),operational:z.boolean().nullable()}).strict();
export const spatialSchema=z.object({version:z.literal('bf-spatial/1'),model_id:z.string(),model_fingerprint:z.string(),
 override_state:z.string(),
 spaces:z.array(z.object({id:z.string(),element_id:z.string().nullable(),floor_id:z.string(),name:z.string(),
   kind:z.enum(['room','corridor','hall','entrance','elevator_car']),region,step:n.nonnegative().nullable(),slope:n.nonnegative().nullable(),
   boundary_audit:z.object({method:z.string(),tolerance_m:n,unsupported_source_boundary_m:n,compared_native_traces:n.int(),status:z.string()}).strict().optional(),...approval}).strict()).max(1000),
 blockers:z.array(z.object({id:z.string(),element_id:z.string().nullable(),floor_id:z.string(),kind:z.string(),region,
   review:review.optional(),evidence:z.array(z.string()).optional()}).strict()).max(10000),
 portals:z.array(z.object({id:z.string(),element_id:z.string().nullable(),floor_id:z.string(),kind:z.enum(['door','open_passage']),
   host_wall_ids:z.array(z.string()),space_ids:z.array(z.string()).max(2),points:z.tuple([point,point]),region,properties:conditions,
   source_geometry:z.object({hinge:point.nullable(),leaf_end:point.nullable(),swing_end:point.nullable(),measured_leaf_span_m:n.nullable(),cad_ids:z.array(z.string())}).strict().optional(),...approval}).strict()).max(1000),
 vertical:z.array(z.object({id:z.string(),kind:z.enum(['elevator','stair','ramp']),element_ids:z.tuple([z.string(),z.string()]),
   space_ids:z.array(z.string()).max(2),points:z.tuple([point,point]),distance:n.positive(),
   properties:conditions.extend({slope:n.nonnegative().nullable()}),...approval}).strict()).max(500)
}).strict();
export type Spatial=z.infer<typeof spatialSchema>;
export type Space=Spatial['spaces'][number];
export type Portal=Spatial['portals'][number];
export type Vertical=Spatial['vertical'][number];
export type Blocker=Spatial['blockers'][number];

export function modelFingerprint(m:Model):string {
 const parts:string[]=['bf-model-dependencies/2',m.id];
 const num=(v:number|null|undefined)=>v===null||v===undefined?'null':v.toFixed(7);
 const geometry=(e:Pick<Element,'polygon'|'holes'|'height'|'z_offset'> & {role?:string;mesh?:{vertices:number[][];triangles:number[][]}|null})=>{
  parts.push(e.role??'',num(e.height),num(e.z_offset));
  for(const ring of [e.polygon,...e.holes]){parts.push('ring');for(const p of ring)for(const v of p)parts.push(num(v));}
  if(e.mesh){parts.push('mesh');for(const p of [...e.mesh.vertices,...e.mesh.triangles])for(const v of p)parts.push(num(v));}
 };
 for(const f of m.floors)parts.push(f.id,num(f.elevation));
 for(const e of [...m.elements].sort((a,b)=>a.id<b.id?-1:a.id>b.id?1:0)){
  parts.push(e.id,e.type,e.floor_id,String(e.excluded),String(e.source.source_sha256??''));
  parts.push(num(e.properties.clear_width),num(e.properties.step),num(e.properties.slope),e.properties.operational===null?'null':String(e.properties.operational),String(e.verified));
  geometry(e);
  for(const c of e.components)geometry(c);
  // Host cut profiles are used by the route builder independently of the
  // rendered solids. Editing only this metadata must invalidate old reviews.
  for(const id of [...(e.source.host_wall_ids??[]) as string[]].sort())parts.push('host',id);
  for(const cut of (e.source.host_openings??[]) as {host_wall_id:string;polygon:XY[];holes?:XY[][]}[]){
   parts.push('opening-host',cut.host_wall_id);geometry({...cut,holes:cut.holes??[],height:null,z_offset:0});
  }
 }
 for(const t of (m.provenance.cad_traces??[]) as {id:string;floor_id:string;kind:string;points:XY[]}[]){
  parts.push(t.id,t.floor_id,t.kind);for(const p of t.points)for(const v of p)parts.push(num(v));
 }
 let hash=2166136261;const s=parts.join('|');for(let i=0;i<s.length;i++)hash=Math.imul(hash^s.charCodeAt(i),16777619)>>>0;
 return hash.toString(16).padStart(8,'0');
}
export function spatialData(m:Model):Spatial|null {
 return m.provenance.bf_spatial?spatialSchema.parse(m.provenance.bf_spatial):null;
}
const ringArea=(r:XY[])=>Math.abs(r.reduce((s,a,i)=>s+a[0]*r[(i+1)%r.length][1]-r[(i+1)%r.length][0]*a[1],0))/2;
export const area=(multi:Multi)=>multi.reduce((s,p)=>s+ringArea(p[0])-p.slice(1).reduce((n,r)=>n+ringArea(r),0),0);
export function union(polys:Multi):Multi {return polys.length?pc.union(...polys as [Poly,...Poly[]]) as Multi:[];}
export const difference=(a:Multi,b:Multi):Multi=>!a.length?[]:!b.length?a:pc.difference(a,...b) as Multi;
export const overlap=(a:Multi,b:Multi)=>a.length&&b.length?area(pc.intersection(a,b) as Multi):0;
export const covers=(r:Multi,p:XY)=>r.some(poly=>inside(p,poly));
export const reviewed=(r:{review?:z.infer<typeof review>;evidence?:string[]},token:string)=>
 Boolean(r.review?.reviewer&&r.review.model_fingerprint===token&&r.review.content_fingerprint===recordFingerprint(r)&&r.review.evidence.length&&r.evidence?.length);
export function recordFingerprint(r:object):string {
 const omitted=new Set(['id','name','status','review','evidence','reasons','boundary_audit','source_geometry']);
 const normalize=(v:unknown):unknown=>typeof v==='number'?v.toFixed(7):Array.isArray(v)?v.map(normalize):v&&typeof v==='object'?Object.fromEntries(Object.entries(v).sort(([a],[b])=>a<b?-1:a>b?1:0).map(([k,v])=>[k,normalize(v)])):v;
 const text=JSON.stringify(normalize(Object.fromEntries(Object.entries(r).filter(([k])=>!omitted.has(k)))));
 let hash=2166136261;for(let i=0;i<text.length;i++)hash=Math.imul(hash^text.charCodeAt(i),16777619)>>>0;
 return hash.toString(16).padStart(8,'0');
}
export const approved=(r:Space|Portal|Vertical,token:string)=>r.status==='confirmed'&&!r.reasons.length&&reviewed(r,token);

/** Always reconstruct physical obstacles from BIM. Omitting a ledger blocker cannot delete a wall.
 * A drawing-reviewed correction may replace its footprint, and never edits the source BIM.
 */
export function physicalBlockers(m:Model,s:Spatial):Blocker[] {
 const currentToken=modelFingerprint(m);
 const out:Blocker[]=s.blockers.filter(b=>!b.element_id||!m.elements.some(e=>e.id===b.element_id));
 for(const e of m.elements.filter(e=>!e.excluded&&['wall','column','obstacle','unclassified','stair','elevator'].includes(e.type))){
  const edits=s.blockers.filter(b=>b.element_id===e.id);
  const corrections=edits.filter(b=>b.kind===e.type&&reviewed(b,currentToken));
  if(corrections.length)out.push(...corrections);
  else {
   out.push({id:'block-'+e.id,element_id:e.id,floor_id:e.floor_id,kind:e.type,region:[raw(e)]});
   // An unreviewed wall correction cannot remove the source wall. Its additional
   // occupied area is blocked too, until the drawing-linked correction is reviewed.
   for(const b of edits)if(b.kind===e.type&&JSON.stringify(b.region)!==JSON.stringify([raw(e)]))out.push({...b,id:'pending-'+b.id});
  }
  if(e.type==='elevator')for(const [i,c] of e.components.entries())if(/lining|wall/.test(c.role)){
   const id=`lining-${e.id}-${i}`,edit=edits.find(b=>b.id===id),original:Blocker={id,element_id:e.id,floor_id:e.floor_id,kind:'wall',region:[[c.polygon,...c.holes]]};
   if(edit&&reviewed(edit,currentToken))out.push(edit);else{out.push(original);if(edit&&JSON.stringify(edit.region)!==JSON.stringify(original.region))out.push({...edit,id:'pending-'+id});}
  }
 }
 // Slab holes remain voids even if a user accidentally omits the generated void ledger.
 for(const e of m.elements.filter(e=>e.type==='floor'&&!e.excluded))for(const [i,h] of e.holes.entries())
  out.push({id:`support-hole-${e.id}-${i}`,element_id:null,floor_id:e.floor_id,kind:'void',region:[[h]]});
 return out;
}

/** Geometry checks validate every boundary. Unresolved records may lack adjacency, but never authorize travel. */
export function validateSpatial(m:Model,input:unknown):Spatial {
 const s=spatialSchema.parse(input);
 if(s.model_id!==m.id||s.model_fingerprint!==modelFingerprint(m))throw Error('BIM 또는 CAD가 변경되었습니다. 공간 경계와 통행 조건을 다시 검토하세요.');
 const floors=new Set(m.floors.map(f=>f.id)),elements=new Map(m.elements.map(e=>[e.id,e]));
 const records=[...s.spaces,...s.blockers,...s.portals,...s.vertical];
 if(new Set(records.map(x=>x.id)).size!==records.length)throw Error('BF 공간 데이터의 ID가 중복됩니다.');
 for(const r of [...s.spaces,...s.blockers,...s.portals]){
  if(!floors.has(r.floor_id)||r.element_id!==null&&!elements.has(r.element_id))throw Error(r.id+': 층/부재 참조 오류');
  if(r.element_id&&elements.get(r.element_id)!.floor_id!==r.floor_id)throw Error(r.id+': 부재와 공간의 층이 다릅니다.');
  for(const [i,p] of r.region.entries()){
   const mock={id:r.id+'/'+i,name:r.id,type:'space' as const,floor_id:r.floor_id,polygon:p[0],holes:p.slice(1),height:null,z_offset:0,
    verified:false,excluded:false,properties:{clear_width:null,step:null,slope:null,operational:null},source:{},components:[]};
   validateGeometry({...m,elements:[mock],places:[],links:[]});
  }
 }
 for(const r of [...s.spaces,...s.portals,...s.vertical])if(r.status==='confirmed'&&!approved(r,s.model_fingerprint))
  throw Error(r.id+': 검토자·시점·현재 BIM 해시·도면 근거와 미확정 사유 해소 기록이 필요합니다.');
 const spaces=new Map(s.spaces.map(x=>[x.id,x]));
 for(const v of s.vertical)if(v.element_ids.some(id=>!elements.has(id)))throw Error(v.id+': 층간 시설 부재 참조 오류');
 const confirmed=s.spaces.filter(x=>approved(x,s.model_fingerprint));
 for(const a of confirmed){
  if(!a.region.length||a.step===null||a.slope===null)throw Error(a.id+': 이동 바닥 경계/단차/경사 미확정');
  if(a.element_id&&elements.get(a.element_id)!.excluded)throw Error(a.id+': 제외된 BIM 공간/시설은 통행에 사용할 수 없습니다.');
  if(a.kind==='elevator_car'&&(!a.element_id||elements.get(a.element_id)?.type!=='elevator'))throw Error(a.id+': 승강기 카 부재 연결 필요');
  const support=union(m.elements.filter(e=>e.floor_id===a.floor_id&&e.type==='floor'&&!e.excluded).map(raw));
  if(a.kind!=='elevator_car'&&area(difference(a.region,support))>1e-7)throw Error(a.id+': 구조 바닥 지지 영역 밖입니다.');
  if(a.kind==='elevator_car'&&area(difference(a.region,[raw(elements.get(a.element_id!)!)]))>1e-7)throw Error(a.id+': 승강기 카가 샤프트 경계 밖입니다.');
  for(const b of s.spaces)if(a.id!==b.id&&a.floor_id===b.floor_id&&overlap(a.region,b.region)>1e-7)throw Error('확인된 공간과 다른 공간 경계가 겹칩니다: '+a.id+' / '+b.id);
 }
 for(const g of s.portals.filter(g=>approved(g,s.model_fingerprint))){
  const [a,b]=g.space_ids.map(id=>spaces.get(id));
  if(!a||!b||a.id===b.id||a.floor_id!==g.floor_id||b.floor_id!==g.floor_id||!approved(a,s.model_fingerprint)||!approved(b,s.model_fingerprint))throw Error(g.id+': 양쪽 확인된 공간 연결 필요');
  if(!covers(a.region,g.points[0])||!covers(b.region,g.points[1])||!covers(g.region,g.points[0])||!covers(g.region,g.points[1]))throw Error(g.id+': 문 접근 지점/통로 영역 불일치');
  if(g.properties.clear_width===null||g.properties.step===null||g.properties.operational===null)throw Error(g.id+': 문 유효폭/단차/개폐 조건 미확정');
  const support=union([...m.elements.filter(e=>e.floor_id===g.floor_id&&e.type==='floor'&&!e.excluded).map(raw),...confirmed.filter(x=>x.floor_id===g.floor_id&&x.kind==='elevator_car').flatMap(x=>x.region)]);
  if(area(difference(g.region,support))>1e-7)throw Error(g.id+': 문 통로가 지지 바닥/검토된 카 영역 밖입니다.');
  if(g.kind==='door'&&(!g.element_id||elements.get(g.element_id)?.type!=='door'||!g.host_wall_ids.length))throw Error(g.id+': 실제 문과 호스트 벽 연결 필요');
  for(const id of g.host_wall_ids){const wall=elements.get(id);if(!wall||wall.type!=='wall'||wall.floor_id!==g.floor_id||!overlap([raw(wall)],g.region))throw Error(g.id+': 호스트 벽 불일치');}
  if(g.kind==='door'&&!overlap([raw(elements.get(g.element_id!)!)],g.region))throw Error(g.id+': 실제 문 기호와 통로 불일치');
 }
 for(const v of s.vertical.filter(v=>approved(v,s.model_fingerprint))){
  const [a,b]=v.space_ids.map(id=>spaces.get(id)),[ea,eb]=v.element_ids.map(id=>elements.get(id));
  if(!a||!b||!ea||!eb||a.floor_id===b.floor_id||ea.floor_id!==a.floor_id||eb.floor_id!==b.floor_id||ea.excluded||eb.excluded||ea.type!==v.kind||eb.type!==v.kind||!approved(a,s.model_fingerprint)||!approved(b,s.model_fingerprint))throw Error(v.id+': 층간 공간/시설 연결 오류');
  if(v.kind==='elevator'&&(a.kind!=='elevator_car'||b.kind!=='elevator_car'||a.element_id!==ea.id||b.element_id!==eb.id))throw Error(v.id+': 층별 카 및 승강장 문 연결 필요');
  if(!covers(a.region,v.points[0])||!covers(b.region,v.points[1])||!inside(v.points[0],raw(ea))||!inside(v.points[1],raw(eb)))throw Error(v.id+': 층간 연결 지점 오류');
  const dz=m.floors.find(f=>f.id===a.floor_id)!.elevation-m.floors.find(f=>f.id===b.floor_id)!.elevation;
  if(v.distance+1e-8<Math.hypot(dist(...v.points),dz))throw Error(v.id+': 층간 연결 길이 오류');
  if(v.properties.clear_width===null||v.properties.step===null||v.properties.operational===null||v.kind==='ramp'&&v.properties.slope===null)throw Error(v.id+': 층간 통행 조건 미확정');
 }
 return s;
}

const storageKey=(id:string)=>'bf-spatial-overrides:'+id;
export function restoreSpatial(m:Model):Model {
 const value=localStorage.getItem(storageKey(m.id));if(!value)return m;
 try {const data=spatialSchema.parse(JSON.parse(value));
  // Preserve stale patches but do not replace regenerated current observations.
  if(data.model_fingerprint!==modelFingerprint(m))return {...m,provenance:{...m.provenance,bf_spatial_override_state:'stale_preserved'}};
  return {...m,provenance:{...m.provenance,bf_spatial:data}};
 }catch{return {...m,provenance:{...m.provenance,bf_spatial_override_state:'invalid_preserved'}};}
}
export function storeSpatial(m:Model,s:Spatial){localStorage.setItem(storageKey(m.id),JSON.stringify(s));}
