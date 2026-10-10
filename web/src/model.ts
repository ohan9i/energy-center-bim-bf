import { z } from 'zod';
import {inside,dist,raw} from './geometry';
const num = z.number().finite();
export const pointSchema = z.tuple([num,num]);
const ring = z.array(pointSchema).min(3).max(2000);
export const kinds = ['wall','column','floor','space','corridor','door','stair','ramp','elevator','obstacle','unclassified'] as const;
export const labels: Record<string,string> = {wall:'벽체',column:'기둥',floor:'바닥',space:'실',corridor:'복도',door:'출입문',stair:'계단',ramp:'경사로',elevator:'승강기',obstacle:'장애물',unclassified:'미분류'};
export const elementSchema = z.object({id:z.string().min(1).max(160),name:z.string(),type:z.enum(kinds),floor_id:z.string(),polygon:ring,holes:z.array(ring).default([]),height:num.positive().max(100).nullable().default(null),z_offset:num.default(0),verified:z.boolean().default(false),excluded:z.boolean().default(false),properties:z.object({clear_width:num.positive().max(100).nullable().default(null),step:num.min(0).max(100).nullable().default(null),slope:num.min(0).max(10).nullable().default(null),operational:z.boolean().nullable().default(null)}).strict().default({clear_width:null,step:null,slope:null,operational:null}),source:z.record(z.string(),z.unknown()).default({})}).strict();
export const modelSchema=z.object({schema_version:z.literal('1.0'),id:z.string(),name:z.string(),units:z.literal('m'),is_example:z.boolean().default(false),revision:num.int().min(0).default(0),floors:z.array(z.object({id:z.string(),name:z.string(),elevation:num}).strict()).min(1).max(30),elements:z.array(elementSchema).max(10000),places:z.array(z.object({id:z.string(),name:z.string(),floor_id:z.string(),point:pointSchema}).strict()).max(500),links:z.array(z.object({id:z.string(),element_id:z.string(),from_place:z.string(),to_place:z.string(),distance:num.positive().max(1000)}).strict()).max(500),warnings:z.array(z.string()).default([]),provenance:z.record(z.string(),z.unknown()).default({})}).strict();
export type Model=z.infer<typeof modelSchema>;
export type Element=z.infer<typeof elementSchema>;
export type XY=[number,number];
export interface Profile {name:string;body_width:number;min_door_width:number;min_corridor_width:number;max_step:number;max_slope:number;allow_stairs:boolean;speed:number;elevator_wait:number;stair_penalty:number}
export const profileSchema=z.object({name:z.string(),body_width:num.min(.1).max(3),min_door_width:num.min(.1).max(5),min_corridor_width:num.min(.1).max(5),max_step:num.min(0).max(1),max_slope:num.min(0).max(2),allow_stairs:z.boolean(),speed:num.min(.1).max(3),elevator_wait:num.min(0).max(600),stair_penalty:num.min(1).max(20)});
export interface Rules {id:string;name:string;verification_status:string;effective_date:string;source_document:string;source_clause:string|null;reference_url:string;reference_document:string;items:{id:string;item:string;target:string;field:string;unit:string}[];profiles:Record<string,Profile>}
export function parseModel(input:unknown):Model {
  const m=modelSchema.parse(input);
  for(const arr of [m.floors,m.elements,m.places,m.links]) if(new Set(arr.map(x=>x.id)).size!==arr.length) throw Error('중복 ID가 있습니다.');
  const floors=new Set(m.floors.map(x=>x.id)), places=new Map(m.places.map(x=>[x.id,x])), elements=new Map(m.elements.map(x=>[x.id,x]));
  if([...m.elements,...m.places].some(x=>!floors.has(x.floor_id))) throw Error('층 참조가 잘못되었습니다.');
  for(const l of m.links){ const a=places.get(l.from_place),b=places.get(l.to_place),e=elements.get(l.element_id); if(!a||!b||!e||!['stair','ramp','elevator'].includes(e.type)||a.floor_id===b.floor_id||a.floor_id!==e.floor_id)throw Error('층간 연결 참조가 잘못되었습니다.'); if(!inside(a.point,raw(e))||!inside(b.point,raw(e)))throw Error('층간 연결 지점은 시설 평면 영역 안에 있어야 합니다.'); const dz=m.floors.find(f=>f.id===a.floor_id)!.elevation-m.floors.find(f=>f.id===b.floor_id)!.elevation;if(l.distance+1e-8<Math.hypot(dist(a.point,b.point),dz))throw Error('층간 이동 길이가 두 지점 사이 직선거리보다 짧습니다.'); }
  return m;
}
