import {useEffect,useMemo,useRef,useState} from 'react';
import type {Model,Profile,XY} from './model';
import {bounds} from './geometry';
import {approved,reviewed,spatialData,spatialSchema,validateSpatial,storeSpatial,modelFingerprint,recordFingerprint,physicalBlockers,difference,overlap,type Spatial} from './spatial';
import {buildSpatialNetwork} from './spatialRoute';

interface Props {model:Model;profile:Profile;floor:string;editing:boolean;initialSelection?:string;onApply:(m:Model)=>void;onClose:()=>void}
const fileDownload=(data:unknown,name:string)=>{const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
export default function SpatialReview({model,profile,floor,editing,initialSelection='',onApply,onClose}:Props){
 const [data,setData]=useState<Spatial|null>(()=>{try{return spatialData(model);}catch{return null;}});
 const [fid,setFid]=useState(floor==='all'?'f1':floor),[category,setCategory]=useState<'spaces'|'portals'|'blockers'|'vertical'>(()=>
  (['spaces','portals','blockers','vertical'] as const).find(key=>data?.[key].some(r=>r.id===initialSelection))??'spaces');
 const [selected,setSelected]=useState(initialSelection),[text,setText]=useState(''),[error,setError]=useState(''),[message,setMessage]=useState('');
 const [cad,setCad]=useState(true),[showGrid,setShowGrid]=useState(false),[zoom,setZoom]=useState(1),[reviewer,setReviewer]=useState(''),[references,setReferences]=useState('');
 const svg=useRef<SVGSVGElement>(null),group=useRef<SVGGElement>(null),drag=useRef<{poly:number;ring:number;point:number}|null>(null);
 const records=data?data[category].filter(r=>'floor_id' in r?r.floor_id===fid:r.element_ids.some(id=>model.elements.find(e=>e.id===id)?.floor_id===fid)):[];
 const item=records.find(r=>r.id===selected);
 useEffect(()=>{setText(item?JSON.stringify(item,null,2):'');},[item]);
 const traces=(model.provenance.cad_traces??[]) as {id:string;floor_id:string;kind:string;points:XY[]}[];
 const box=useMemo(()=>{
  const regions=data?[...data.spaces,...data.blockers,...data.portals].filter(r=>r.floor_id===fid).flatMap(r=>r.region):[];
  return regions.length?bounds(regions):{min:[0,0] as XY,max:[100,90] as XY};
 },[data,fid]);
 const width=box.max[0]-box.min[0]+2,height=box.max[1]-box.min[1]+2;
 const currentToken=modelFingerprint(model);
 const view=[box.min[0]-1+width*(1-1/zoom)/2,-box.max[1]-1+height*(1-1/zoom)/2,width/zoom,height/zoom];
 const path=(region:XY[][][])=>region.map(poly=>poly.map(r=>'M'+r.map(p=>p.join(',')).join('L')+'Z').join(' ')).join(' ');
 const effective=data?physicalBlockers(model,data).filter(b=>b.floor_id===fid):[];
 const green=(region:XY[][][])=>difference(region,network?.checks.get(fid)?.obstacles??effective.flatMap(b=>b.region));
 const pass=(s:Spatial['spaces'][number])=>Boolean(network)&&approved(s,currentToken)&&s.step!==null&&s.step<=profile.max_step&&s.slope!==null&&s.slope<=profile.max_slope;
 function replace(value:unknown){
  if(!data||!item)return;
  try{const copy=structuredClone(data),next=structuredClone(value) as typeof item;
   if('status' in next&&next.status==='confirmed'&&!reviewed(next,currentToken)){next.status='unresolved';next.review=null;next.reasons=['Boundary or passage conditions edited; drawing review required'];}
   (copy[category] as typeof records)[(copy[category] as typeof records).findIndex(r=>r.id===item.id)]=next;
   const parsed=spatialSchema.parse(copy);setData(parsed);setError('');setMessage('편집 중입니다. 별도 저장을 누르면 모델과 경로에 적용됩니다.');
  }catch(e){setError(e instanceof Error?e.message:String(e));}
 }
 function addRecord(){
  if(!data)return;
  const x=(box.min[0]+box.max[0])/2,y=(box.min[1]+box.max[1])/2;
  const region:XY[][][]=[[[[x-1,y-1],[x+1,y-1],[x+1,y+1],[x-1,y+1]]]];
  const id='bf-user-'+crypto.randomUUID(),approval={status:'unresolved' as const,evidence:[],review:null,reasons:['User draft; align boundary with actual drawing and record passage conditions']};
  const copy=structuredClone(data);
  if(category==='spaces')copy.spaces.push({id,element_id:null,floor_id:fid,name:'새 공간 · 도면 경계 편집 필요',kind:'room',region,step:null,slope:null,...approval});
  else if(category==='portals')copy.portals.push({id,element_id:null,floor_id:fid,kind:'open_passage',host_wall_ids:[],space_ids:[],points:[[x-.5,y],[x+.5,y]],region,properties:{clear_width:null,step:null,operational:null},...approval});
  else if(category==='blockers')copy.blockers.push({id,element_id:null,floor_id:fid,kind:'obstacle',region,evidence:[],review:null});
  else {setError('층간 연결은 기존 시설의 실제 부재 ID와 공간 연결을 먼저 확인하세요. JSON 가져오기로 새 연결을 추가할 수 있습니다.');return;}
  setData(copy);setSelected(id);setMessage('새 항목은 미확정 초안입니다. 실제 도면에 맞게 꼭짓점과 연결·통행 조건을 편집하세요.');
 }
 function save(){
  if(!data)return;
  try{const parsed=validateSpatial(model,data);storeSpatial(model,parsed);onApply({...model,provenance:{...model.provenance,bf_spatial:parsed}});setError('');setMessage('공간 수정 데이터를 이 브라우저에 별도 저장했습니다. 원본 DWG는 보존됩니다.');}
  catch(e){setError(e instanceof Error?e.message:String(e));}
 }
 function confirm(){
  if(!item||!data)return;
  const evidence=references.split('\n').map(s=>s.trim()).filter(Boolean);
  if(!reviewer.trim()||!evidence.length){setError('검토자와 도면·객체·치수 근거를 입력하세요.');return;}
  replace({...item,...('status' in item?{status:'confirmed',reasons:[]}:{}),evidence,
   review:{reviewer:reviewer.trim(),reviewed_at:new Date().toISOString(),model_fingerprint:modelFingerprint(model),content_fingerprint:recordFingerprint(item),evidence}});
 }
 const networkResult=useMemo(()=>{if(!data)return {network:null,error:''};try{return {network:buildSpatialNetwork(model,data,profile),error:''};}catch(e){return {network:null,error:e instanceof Error?e.message:String(e)};}},[model,data,profile]);
 const network=networkResult.network;
 return <div className="spatial-dialog" role="dialog" aria-modal="true" aria-label="BF 공간 경계 검증">
  <header><div><h2>BF 공간 경계 검증</h2><p>초록: 확인된 이동 영역 · 빨강: 장애물/빈 공간 · 파랑: 확인된 연결 · 주황: 미확정</p></div><button onClick={onClose}>닫기</button></header>
  {!data?<p>이 모델에는 별도 BF 공간 데이터가 없습니다. 현재 도면 모델을 재생성하세요.</p>:<>
  <div className="spatial-toolbar"><label>검토 층 <select aria-label="공간 검토 층" value={fid} onChange={e=>{setFid(e.target.value);setSelected('');}}>{model.floors.map(f=><option key={f.id} value={f.id}>{f.name}</option>)}</select></label>
   <label><input type="checkbox" checked={cad} onChange={e=>setCad(e.target.checked)}/>원본 CAD 추출선 중첩</label>
   <label><input type="checkbox" checked={showGrid} onChange={e=>setShowGrid(e.target.checked)}/>이동 여유폭 적용 격자</label>
   <button onClick={()=>setZoom(v=>Math.min(8,v*1.3))}>확대</button><button onClick={()=>setZoom(v=>Math.max(1,v/1.3))}>축소</button>
   <button onClick={()=>fileDownload(data,'overrides.json')}>수정 데이터 내보내기</button>
   <button onClick={()=>fileDownload(network?{model_fingerprint:data.model_fingerprint,nodes:network.nodes,edges:network.edges,space_edges:network.space_edges}: {error:'공간 검토가 필요합니다.'},'bf-spatial-network.json')}>공간 네트워크 내보내기</button>
   {editing&&<label className="spatial-import">수정 데이터 가져오기<input aria-label="BF 수정 데이터 가져오기" type="file" accept=".json" onChange={async e=>{const f=e.target.files?.[0];if(!f)return;try{const s=validateSpatial(model,JSON.parse(await f.text()));setData(s);setSelected('');setError('');}catch(e){setError(e instanceof Error?e.message:String(e));}}}/></label>}
  </div>
  <p className="spatial-summary" data-testid="spatial-summary">확인 공간 {data.spaces.filter(s=>approved(s,currentToken)).length} / {data.spaces.length} · 확인 연결 {network?.space_edges.length??0} · 이동 격자 {network?.nodes.length??0} · 공식 BF 인증 판정 아님</p>
  {data.model_fingerprint!==currentToken&&<p role="alert">BIM 또는 CAD가 변경되어 기존 경계 검토를 사용할 수 없습니다. 변경 구간의 경계와 연결 조건을 다시 검토하세요.</p>}
  {model.provenance.bf_spatial_override_state&&<p role="alert">이전 공간 수정본은 BIM 변경으로 재검토가 필요합니다. 브라우저 저장소에는 보존되어 있습니다.</p>}
  {error&&<p role="alert" className="spatial-error">{error}</p>}{message&&<p role="status">{message}</p>}
  {networkResult.error&&<p role="alert" className="spatial-error">공간 연결 검사: {networkResult.error}</p>}
  <div className="spatial-body"><aside><label>검토 대상 <select aria-label="공간 검토 대상" value={category} onChange={e=>{setCategory(e.target.value as typeof category);setSelected('');}}>
   <option value="spaces">실·복도·홀 경계</option><option value="portals">출입문·개방 통로</option><option value="blockers">벽·기둥·중정·샤프트</option><option value="vertical">층간 연결</option></select></label>
   {editing&&category!=='vertical'&&<button onClick={addRecord}>미확정 항목 추가</button>}
   <div className="spatial-list">{records.map(r=><button key={r.id} aria-pressed={selected===r.id} onClick={()=>setSelected(r.id)}>{'name' in r?r.name:r.id}<small>{'status' in r?approved(r,currentToken)?'검토 기록 있음':'미확정 / 재검토':r.kind}</small></button>)}</div>
  </aside><main><svg ref={svg} className="spatial-map" viewBox={view.join(' ')} role="img" aria-label="CAD와 BF 공간 경계 중첩" onPointerMove={e=>{
   if(!drag.current||!item||!('region' in item)||!group.current||!editing)return;
   const matrix=group.current.getScreenCTM();if(!matrix)return;const p=new DOMPoint(e.clientX,e.clientY).matrixTransform(matrix.inverse());
   const copy=structuredClone(item);copy.region[drag.current.poly][drag.current.ring][drag.current.point]=[Math.round(p.x*1000)/1000,Math.round(p.y*1000)/1000];
   if('status' in copy){copy.status='unresolved';copy.reasons=['Boundary edited; drawing and clearance review required'];}copy.review=null;replace(copy);
  }} onPointerUp={()=>{drag.current=null;}} onPointerCancel={()=>{drag.current=null;}}>
   <g ref={group} transform="scale(1 -1)">
    {data.spaces.filter(s=>s.floor_id===fid).map(s=><path key={s.id} data-space-id={s.id} d={path(pass(s)?green(s.region):s.region)} fill={pass(s)?'#10b98166':'#f59e0b35'} fillRule="evenodd" stroke={selected===s.id?'#0f172a':'#d97706'} strokeWidth={selected===s.id?2.5:1} vectorEffect="non-scaling-stroke" onClick={()=>{setCategory('spaces');setSelected(s.id);}}/>)}
    {(network?.checks.get(fid)?.obstacles??effective.flatMap(b=>b.region)).map((region,i)=><path key={'physical-'+i} d={path([region])} fill="#ef444455" fillRule="evenodd" stroke="#b91c1c" strokeWidth=".7" vectorEffect="non-scaling-stroke" onClick={()=>{const b=effective.find(b=>overlap(b.region,[region])>1e-8);if(b){setCategory('blockers');setSelected(b.id.replace(/^pending-/,''));}}}/>)}
    {cad&&traces.filter(t=>t.floor_id===fid).map(t=><polyline key={t.id} points={t.points.map(p=>p.join(',')).join(' ')} fill="none" stroke="#475569" strokeWidth=".7" vectorEffect="non-scaling-stroke" pointerEvents="none"/>)}
    {data.portals.filter(g=>g.floor_id===fid).map(g=>{const usable=network?.space_edges.some(e=>e.via===g.id)??false;
     return <g key={g.id} data-portal-id={g.id} onClick={()=>{setCategory('portals');setSelected(g.id);}}><path d={path(g.region)} fill={usable?'#0284c788':approved(g,currentToken)?'#ef444466':'#f59e0b66'} stroke={selected===g.id?'#0f172a':usable?'#0284c7':'#d97706'} strokeWidth={selected===g.id?'3':'1.5'} vectorEffect="non-scaling-stroke"/>
      <polyline points={g.points.map(p=>p.join(',')).join(' ')} fill="none" stroke={usable?'#0284c7':approved(g,currentToken)?'#b91c1c':'#d97706'} strokeDasharray={usable?undefined:'3 3'} strokeWidth="2" vectorEffect="non-scaling-stroke"/></g>;})}
    {showGrid&&network?.nodes.filter(n=>n.floor===fid).slice(0,10000).map((n,i)=><circle data-grid-node key={'node-'+i} cx={n.point[0]} cy={n.point[1]} r={.035/zoom} fill="#0369a1" pointerEvents="none"/>)}
    {editing&&item&&'region' in item&&item.region.map((poly,pi)=>poly.map((ring,ri)=>ring.map((p,i)=><circle key={`${pi}-${ri}-${i}`} cx={p[0]} cy={p[1]} r={width/zoom/(svg.current?.clientWidth||800)*5} fill="#0f172a" onPointerDown={e=>{e.preventDefault();e.stopPropagation();drag.current={poly:pi,ring:ri,point:i};svg.current?.setPointerCapture(e.pointerId);}}/>)))}
   </g>
  </svg><p>도면의 같은 좌표계(m)를 사용합니다. CAD 추출선 중첩은 원본 DWG의 독립 설계 검증과 구분됩니다. {editing?'꼭짓점을 드래그하면 경계를 수정할 수 있습니다.':'검토 대상 선택으로 경계와 연결 근거를 확인하세요.'}</p></main>
  <aside className="spatial-editor">{item?<><h3>{'name' in item?item.name:item.id}</h3><p>{'reasons' in item?item.reasons.join(' · '):'벽체 수정은 별도 검토 근거가 필요합니다.'}</p>
   {network?.excluded.filter(r=>r.id===item.id).map(r=><p key={r.id} role="status">현재 경로 조건: {r.reasons.join(' · ')}</p>)}
   <label>경계·연결·통행 조건 JSON<textarea aria-label="BF 공간 편집 JSON" disabled={!editing} value={text} onChange={e=>setText(e.target.value)}/></label>
   {editing&&<><button onClick={()=>{try{replace(JSON.parse(text));}catch(e){setError(String(e));}}}>JSON 편집 적용</button>
    <p>region은 [외곽, 내부 구멍] 다각형 목록입니다. 문은 양쪽 space_ids, 접근 points, 실제 호스트 벽 ID가 필요합니다. 단차·경사·유효폭·개폐 조건의 null은 미확정입니다.</p>
    <label>검토자<input aria-label="BF 공간 검토자" value={reviewer} onChange={e=>setReviewer(e.target.value)}/></label>
    <label>도면·객체·치수 근거 (한 줄씩)<textarea aria-label="BF 공간 검토 근거" value={references} onChange={e=>setReferences(e.target.value)}/></label>
    <button onClick={confirm}>선택 항목의 경계·통행 조건 검토 확인</button><p>현재 입력을 직접 검토했다는 기록입니다. 인증 승인으로 사용하지 않습니다.</p>
   </>}
  </>:<p>공간·문·장애물을 선택해 근거와 경계를 확인하세요.</p>}
  {editing&&<button className="primary full" onClick={save}>공간 수정 별도 저장</button>}
  </aside></div></>}
 </div>;
}
