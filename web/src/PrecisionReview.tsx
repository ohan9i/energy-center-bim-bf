import { useEffect, useMemo, useState } from 'react';
import './precisionReview.css';

type Member = {
  id: string; kind: string; verification: string; plan_status: string;
  plan_polygon: number[][] | null; cad_ids: string[]; unknowns: string[];
  conflicts: { type: string; other_member_id?: string; field?: string }[];
  references: { drawing_id: string; drawing_number: string | null; source_sha256: string; cad_ids: string[]; relation: string }[];
  dimensions: Record<string, { value: number | null; status: string; evidence_ids: string[] }>;
};
type Comparison = { member_id: string; status: string; boundary_distance_m?: number; symmetric_difference_m2?: number; reason?: string };
type Pilot = {
  name: string; members: Member[]; preview_members: Member[];
  registration: { status: string; origin_cad: number[]; scale_m_per_unit: number };
  cad_traces: { cad_id: string; kind: string; points: number[][]; member_id: string; status: string }[];
  comparisons: { plan: Comparison[]; vertical: Comparison[] };
  summary: { plan_profiles: number; member_candidates: number; verified_solids: number; conflicts: number };
  native_entities: {id:string;type:string;definition_handle:string|null;effective_layer:string;insert_ancestry:string[];
    geometry:{radius?:number;segments?:{type:string;length?:number}[]}}[];
};
type Drawing = {
  id: string; file: string; hash_matches_audit: boolean; extraction_state: string;
  coverage: { scene_entity_count: number; scene_truncated: boolean };
  warning_counts: Record<string, number>;
  external_references: { kind: string; stored_path: string; exists: boolean; contents_extracted?: boolean }[];
};
const names: Record<string, string> = {column:'기둥',wall:'벽체',floor:'슬래브',beam:'보',door:'출입문',window:'창호',stair:'계단'};
const status: Record<string,string> = {unresolved:'미확정',plan_only:'평면 경계만 확인',conflict:'충돌',verified:'검증 완료',unknown:'미확인',measured_geometry:'CAD 기하 측정',trace_only:'선·기호만 확인',confirmed:'도면 확인',match:'허용오차 이내',mismatch:'불일치',insufficient_source:'원본 근거 부족'};
async function get<T,>(name: string, signal: AbortSignal): Promise<T> {
  const response = await fetch(`/api/precision/${name}`,{signal});
  if (!response.ok) throw Error(`정밀 자료를 읽을 수 없습니다 (${response.status}). 로컬 API와 1단계 생성 결과를 확인하세요.`);
  return response.json();
}

export default function PrecisionReview({onClose}:{onClose:()=>void}) {
  const [pilot,setPilot]=useState<Pilot|null>(null),[drawings,setDrawings]=useState<Drawing[]>([]),[error,setError]=useState('');
  const [selected,setSelected]=useState(''),[kind,setKind]=useState('all'),[tab,setTab]=useState('plan');
  const [showCad,setShowCad]=useState(true),[showBim,setShowBim]=useState(true),[preview,setPreview]=useState(false);
  const [showMissing,setShowMissing]=useState(false);
  const [view,setView]=useState([0,0,100,90]);
  useEffect(()=>{const c=new AbortController(); Promise.all([get<Pilot>('pilot',c.signal),get<Drawing[]>('drawings',c.signal)])
    .then(([p,d])=>{setPilot(p);setDrawings(d);}).catch(e=>{if(!c.signal.aborted)setError(String(e.message));});return()=>c.abort();},[]);
  useEffect(()=>{const listener=(e:KeyboardEvent)=>{if(e.key==='Escape')onClose();};document.addEventListener('keydown',listener);return()=>document.removeEventListener('keydown',listener);},[onClose]);
  const members=useMemo(()=>pilot ? (preview?pilot.preview_members:pilot.members).filter(m=>kind==='all'||m.kind===kind):[],[pilot,kind,preview]);
  const member=pilot?.members.find(m=>m.id===selected);
  const comparison=pilot?.comparisons.plan.find(c=>c.member_id===selected);
  const source=pilot?.native_entities.find(e=>e.id===member?.cad_ids[0]);
  const traces=useMemo(()=>pilot?.cad_traces.filter(t=>kind==='all'||t.kind===kind)??[],[pilot,kind]);
  const mismatches=useMemo(()=>new Set(pilot?.comparisons.plan.filter(c=>c.status==='mismatch').map(c=>c.member_id)),[pilot]);
  return <div className="precision-review" role="dialog" aria-modal="true" aria-label="정밀 1층 CAD BIM 검토">
    <header><strong>정밀 1층 검토 · 기존 모델과 별도</strong><button onClick={onClose}>기존 BIM / BF로 돌아가기</button></header>
    {error?<p role="alert">{error}</p>:!pilot?<p>원본 근거와 정밀 시범 데이터를 읽고 있습니다…</p>:<>
      <p className="precision-notice">평면 경계 {pilot.summary.plan_profiles}개 · CAD 부재 후보 {pilot.summary.member_candidates}개 · 검증된 입체 {pilot.summary.verified_solids}개 · 충돌 {pilot.summary.conflicts}개. 선·기호 후보 수는 실제 건축 부재 수와 다릅니다. 높이 미확인 부재는 압출하지 않습니다.</p>
      <nav aria-label="정밀 검토 탭">{[['plan','CAD 중첩'],['vertical','단면·입면 비교'],['drawings','30개 DWG 추출 상태']].map(([id,label])=><button key={id} aria-pressed={tab===id} onClick={()=>setTab(id)}>{label}</button>)}</nav>
      {tab==='drawings'?<div className="precision-drawings"><table><thead><tr><th>DWG</th><th>원본 해시</th><th>추출 범위</th><th>손실·누락</th></tr></thead><tbody>{drawings.map(d=><tr key={d.id}><td><b>{d.id}</b><small>{d.file}</small></td><td>{d.hash_matches_audit?'일치':'불일치 / 사용 중단'}</td><td>{d.extraction_state==='full_native_archive'?'전체 객체·블록 원시 보존':'조사 및 문자·치수 자료'}<small>{d.coverage.scene_entity_count.toLocaleString()} 객체{d.coverage.scene_truncated?' · 확장 상한 도달':''}</small></td><td>{Object.entries(d.warning_counts).filter(([code])=>!['DISPLAY_LIMITATIONS','CONVERSION_LOSS_NOT_VERIFIABLE'].includes(code)).map(([c,n])=><small key={c}>{c}: {n}</small>)}{d.external_references.map((r,i)=><small key={i}>{r.kind}: {r.stored_path} · {r.exists?'경로 존재':'경로 누락'} / {r.contents_extracted?'추출됨':'내용 미추출'}</small>)}</td></tr>)}</tbody></table><p>변환된 DXF의 추출 범위입니다. DWG 사용자 객체의 무손실 변환을 보증하지 않습니다.</p></div>:
      <div className="precision-body"><aside><label>부재 종류 <select value={kind} onChange={e=>setKind(e.target.value)}><option value="all">전체</option>{Object.entries(names).map(([k,n])=><option key={k} value={k}>{n}</option>)}</select></label>
        <p>기호·선 후보와 닫힌 경계를 구분합니다. 목록에서 선택하면 원본 객체 ID와 근거를 확인할 수 있습니다.</p>
        <div className="precision-list">{members.map(m=><button key={m.id} aria-pressed={selected===m.id} onClick={()=>setSelected(m.id)}>{names[m.kind]??m.kind} · {m.cad_ids[0]}<small>{status[m.verification]}</small></button>)}</div>
      </aside><main>{tab==='vertical'?<div className="precision-vertical"><h3>수직 비교: 원본 근거 부족</h3><p>단면·입면의 부재 연결과 좌표 등록이 미확정이므로 높이 비교를 완료할 수 없습니다. 도면상의 레벨 문자만으로 각 부재의 하단·상단을 확정하지 않습니다.</p><p>수직 비교 엔진은 근거가 연결되면 하단 레벨·높이·창호 하단·상단의 차이와 치수 충돌을 계산합니다.</p>{member&&<p>{member.cad_ids[0]}: {pilot.comparisons.vertical.find(c=>c.member_id===member.id)?.reason}</p>}</div>:<>
        <div className="precision-tools"><label><input type="checkbox" checked={showCad} onChange={e=>setShowCad(e.target.checked)}/>원본 CAD (대상 레이어)</label><label><input type="checkbox" checked={showBim} onChange={e=>setShowBim(e.target.checked)}/>평면 경계 (청록 / 충돌 주황 / 불일치 빨강)</label><label><input type="checkbox" checked={showMissing} onChange={e=>setShowMissing(e.target.checked)}/>근거 부족 표시 (주황 점선)</label><label><input type="checkbox" checked={preview} onChange={e=>setPreview(e.target.checked)}/>임시 가정 미리보기</label><button onClick={()=>setView([0,0,100,90])}>전체 보기</button><button onClick={()=>setView(v=>[v[0]+v[2]*.125,v[1]+v[3]*.125,v[2]*.75,v[3]*.75])}>확대</button><button onClick={()=>setView(v=>[v[0]-v[2]/6,v[1]-v[3]/6,v[2]*4/3,v[3]*4/3])}>축소</button></div>
        {preview&&<p>자동으로 가정한 형상은 없습니다. 미리보기 자료는 검증 모델 및 IFC에 포함되지 않습니다.</p>}
        <svg className="precision-overlay" viewBox={view.join(' ')} role="img" aria-label="원본 CAD와 정밀 평면 중첩" onWheel={e=>{const factor=e.deltaY>0?1.1:.9;setView(v=>[v[0]+v[2]*(1-factor)/2,v[1]+v[3]*(1-factor)/2,v[2]*factor,v[3]*factor]);}}>
          <g transform="translate(0 90) scale(1 -1)">
            {showCad&&traces.map(t=><polyline key={t.cad_id} points={t.points.map(p=>p.join(',')).join(' ')} fill="none" stroke={selected===t.member_id?'#dc2626':showMissing&&t.status!=='measured_geometry'?'#d97706':'#7c8590'} strokeDasharray={showMissing&&t.status!=='measured_geometry'?'3 2':undefined} strokeWidth={selected===t.member_id?2:1} vectorEffect="non-scaling-stroke" onClick={()=>setSelected(t.member_id)}/>)}
            {showBim&&members.filter(m=>m.plan_polygon).map(m=><polygon key={m.id} data-member-id={m.id} points={m.plan_polygon!.map(p=>p.join(',')).join(' ')} fill={mismatches.has(m.id)?'#dc262655':m.conflicts.length?'#f59e0b55':'#10b98144'} stroke={selected===m.id||mismatches.has(m.id)?'#dc2626':m.conflicts.length?'#d97706':'#059669'} strokeWidth={selected===m.id?3:1.5} vectorEffect="non-scaling-stroke" onClick={()=>setSelected(m.id)}/>)}
          </g>
        </svg><p>동일 A04 원본 좌표의 왕복·경계 비교입니다. 도면 간 공통 좌표 검증은 미완료입니다. 로컬 원점: {pilot.registration.origin_cad.join(', ')} mm.</p>
      </>}</main><aside className="precision-inspector">{member?<><h3>{names[member.kind]} · {status[member.verification]}</h3><small>{member.id}</small><p>평면: {status[member.plan_status]}</p>{comparison&&<p>경계 대조: {status[comparison.status]}{comparison.boundary_distance_m!==undefined&&` / ${(comparison.boundary_distance_m*1000).toFixed(3)} mm`}</p>}
        <h4>원본 근거</h4>{member.references.map((r,i)=><p key={i}>{r.drawing_id} · 도면 번호 {r.drawing_number??'미확정'}<small>{drawings.find(d=>d.id===r.drawing_id)?.file}</small><small>{r.cad_ids.join('\n')}</small><small>SHA256 {r.source_sha256}</small></p>)}
        {source&&<><h4>CAD 객체와 변환 계층</h4><p>{source.type} · 레이어 {source.effective_layer}<small>원본 정의 핸들: {source.definition_handle??'미확인'}</small><small>블록 경로: {source.insert_ancestry.join(' → ')||'직접 객체'}</small></p>
          {source.geometry.radius!==undefined&&<p>CAD 반지름: {source.geometry.radius.toFixed(3)} mm (일람표 연결 미완료)</p>}
          {source.geometry.segments&&<p>CAD 구간 길이: {source.geometry.segments.map(s=>s.length?.toFixed(3)??s.type).join(', ')} mm (주석 치수 확인과 별도)</p>}</>}
        <h4>치수</h4>{Object.entries(member.dimensions).map(([k,d])=><p key={k}>{k}: {d.value===null?'미확인':`${d.value} m`} ({status[d.status]??d.status})</p>)}
        <h4>미확인 정보</h4><p>{member.unknowns.join(', ')}</p>{member.conflicts.length>0&&<><h4>충돌</h4>{member.conflicts.map((c,i)=><p key={i}>{c.type}<small>{c.other_member_id??c.field}</small></p>)}</>}</>:<p>CAD 선 또는 부재를 선택하세요.</p>}<button disabled title="공통 좌표 및 검증된 입체가 없어 IFC 내보내기를 차단합니다">정밀 IFC 내보내기 — 검증 미완료</button></aside></div>}
    </>}
  </div>;
}
