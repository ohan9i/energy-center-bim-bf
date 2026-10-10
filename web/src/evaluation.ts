import type {Element,Profile} from './model';
export type Status='pass'|'blocked'|'unknown';
export interface Evaluation {id:string;status:Status;reasons:string[]}
export const statusLabel={pass:'통과 가능',blocked:'통과 불가능',unknown:'추가 확인 필요'};
export function evaluate(e:Element,p:Profile):Evaluation {
 const reasons:string[]=[];let blocked=false,unknown=false;
 const reject=(s:string)=>{blocked=true;reasons.push(s);};
 const missing=(s:string)=>{unknown=true;reasons.push(s);};
 if(e.excluded)return {id:e.id,status:'blocked',reasons:['설계자가 제외한 요소']};
 if(!e.verified)missing('기하학·통행 속성 미확인');
 const width=(limit:number)=>{const w=e.properties.clear_width;if(w===null)missing('유효폭 미입력');else if(w<Math.max(limit,p.body_width))reject(`유효폭 ${w} m < 필요 ${Math.max(limit,p.body_width)} m`);};
 const step=()=>{const s=e.properties.step;if(s===null)missing('단차 미입력');else if(s>p.max_step)reject(`단차 ${s} m > 허용 ${p.max_step} m`);};
 if(e.type==='door'){width(p.min_door_width);step();}
 if(e.type==='floor')step();
 if(e.type==='corridor'&&e.properties.clear_width!==null)width(p.min_corridor_width);
 if(e.type==='stair'){if(!p.allow_stairs)reject('계단 이용 제외');width(p.min_door_width);}
 if(e.type==='ramp'){width(p.min_corridor_width);step();if(e.properties.slope===null)missing('경사 미입력');else if(e.properties.slope>p.max_slope)reject(`경사 ${e.properties.slope.toFixed(3)} > 허용 ${p.max_slope.toFixed(3)}`);}
 if(e.type==='elevator'){width(p.min_door_width);step();if(e.properties.operational===null)missing('승강기 가동 상태 미확인');else if(!e.properties.operational)reject('승강기 이용 불가');}
 if(e.type==='unclassified')missing('건축 요소 종류 미분류');
 return {id:e.id,status:blocked?'blocked':unknown?'unknown':'pass',reasons:reasons.length?reasons:['확인된 입력값이 현재 사용자 이동 조건을 충족합니다.']};
}
