import {useState} from 'react';
import {labels,type Model,type Element} from './model';
import {planArea} from './bimGeometry';
import {bounds,raw} from './geometry';
interface Props {model:Model;library:Model[];item?:Element;floor:string;onActivate:(m:Model)=>void;onFloor:(id:string)=>void;onSelect:(id:string)=>void;onEdit?:(e:Element)=>void}
const format=(v:unknown)=>typeof v==='number'?v.toFixed(3)+' m':'미확인';
export default function BimInspector({model,library,item,floor,onActivate,onFloor,onSelect,onEdit}:Props){
 const [noteFilter,setNoteFilter]=useState('structure');
 const visible=model.elements.filter(e=>!e.excluded&&(floor==='all'||e.floor_id===floor));
 const counts=new Map<string,number>();for(const e of visible)counts.set(e.type,(counts.get(e.type)??0)+1);
 const missing=Array.isArray(model.provenance.missing_information)?model.provenance.missing_information as string[]:[];
 const related=item?['adjacent_space_ids','host_wall_ids'].flatMap(key=>Array.isArray(item.source[key])?item.source[key] as string[]:[]):[];
 const bb=item?bounds([raw(item)]):null;
 const survey=model.provenance.drawing_evidence as {column_sections?:{mark:string;shape:string;dimensions_m:number[]}[];wall_sections?:{mark:string;thickness_m:number}[];note_candidates?:{file:string;text:string}[];unavailable_references?:string[]}|undefined;
 const sections=Array.isArray(survey?.column_sections)?survey.column_sections:[],notes=Array.isArray(survey?.note_candidates)?survey.note_candidates:[];
 const filteredNotes=notes.filter(n=>noteFilter==='all'||(noteFilter==='structure'?n.file.includes('/S'):noteFilter==='facade'?/^(A06|A10)/.test(n.file):n.file.startsWith('A03')));
 return <aside className="right-panel bim-inspector" id="navigation">
  <h2>BIM 모델 검토</h2><p className="muted">도면 근거 · 건축 요소 · 미확정 정보</p>
  <label className="field">건축물<select aria-label="BIM 건축물" value={model.id} onChange={e=>{const m=library.find(x=>x.id===e.target.value);if(m)onActivate(m);}}>{library.map(m=><option key={m.id} value={m.id}>{m.name}</option>)}</select></label>
  <div className="bim-floor-list">{model.floors.map(f=><button className={floor===f.id?'active':''} key={f.id} onClick={()=>onFloor(f.id)}>{f.name}<small> Z {f.elevation.toFixed(2)} m</small></button>)}</div>
  <div className="bim-counts">{[...counts].map(([kind,count])=><span key={kind}>{labels[kind]} <strong>{count}</strong></span>)}</div>
  <section className="properties architectural-properties"><h2>선택 객체</h2>
  {item?<><h3>{item.name}</h3><p className="muted">{labels[item.type]} · {item.id}</p><span className="status unknown">{item.verified?'사용자 검토 기록 있음':item.source.geometry_status==='measured_plan'?'평면 형상 측정 · 높이 검토 필요':'재구성 후보 · 검토 필요'}</span>
   <dl className="bim-facts"><dt>소속 층</dt><dd>{model.floors.find(f=>f.id===item.floor_id)?.name}</dd><dt>기준 Z</dt><dd>{((model.floors.find(f=>f.id===item.floor_id)?.elevation??0)+item.z_offset).toFixed(3)} m</dd>
    <dt>높이 / 두께</dt><dd>{format(item.height)}</dd><dt>XY 투영 면적</dt><dd>{planArea(item).toFixed(2)} m² <small>(수량 미검증)</small></dd>
    <dt>X / Y 범위 길이</dt><dd>{bb&&`${(bb.max[0]-bb.min[0]).toFixed(3)} / ${(bb.max[1]-bb.min[1]).toFixed(3)} m`}</dd>
    {item.source.measured_thickness_m!==undefined&&<><dt>벽면 간격</dt><dd>{format(item.source.measured_thickness_m)}</dd></>}
    {item.source.leaf_radius_m!==undefined&&<><dt>문 회전호 반지름</dt><dd>{format(item.source.leaf_radius_m)} <small>(문 유효폭과 별도)</small></dd></>}
    {item.components.length>0&&<><dt>조립체 구성요소</dt><dd>{item.components.length}개 · {[...new Set(item.components.map(c=>c.role))].join(', ')}</dd></>}
    {item.type==='stair'&&<><dt>평면 단선 간격</dt><dd>{format(item.source.tread_pitch_m)}</dd><dt>상세 단높이</dt><dd>{format(item.source.riser_m)}</dd></>}
    <dt>도면</dt><dd>{String(item.source.file??'출처 없음')}</dd><dt>높이 근거</dt><dd>{item.height===null?'미확인 · 가정 표시와 별도로 저장':String(item.source.height_source??'구성요소별 근거 확인')}</dd>
   </dl>
   {item.source.assembly_status!==undefined&&<details open><summary>임시 조립체 치수 · 도면 검증 전</summary><p className="geometry-assumption">아래 높이와 두께에는 가정값이 포함됩니다. 객체 편집에서 components를 수정하거나 bf_bim/assembly_parameters.json 변경 후 재생성할 수 있습니다.</p><table><thead><tr><th>구성</th><th>상대 Z (m)</th><th>높이/두께 (m)</th></tr></thead><tbody>{item.components.slice(0,40).map((c,i)=><tr key={i}><td>{c.role}</td><td>{c.z_offset.toFixed(3)}</td><td>{c.height?.toFixed(3)??'미확인'}</td></tr>)}</tbody></table></details>}
   {item.source.marker_width_m!==undefined&&<p className="geometry-assumption">이 면의 10 mm 폭은 위치 표시용입니다. 실제 벽 두께가 아닙니다.</p>}
   {item.source.boundary_status==='labels_share_boundary'&&<p className="geometry-assumption">여러 실명이 한 경계에 포함됩니다. 실별 칸막이와 면적 분리는 미확정입니다.</p>}
   {item.source.detail_pitch_conflict===true&&<p className="geometry-assumption">평면 280 mm / 코어 상세 300 mm 단너비 불일치. 자동 통일하지 않았습니다.</p>}
   {Array.isArray(item.source.coincident_profile_ids)&&item.source.coincident_profile_ids.length>0&&<p className="geometry-assumption">같은 중심의 서로 다른 기둥 단면이 있습니다. 부재 구분이 미확인되어 높이 없는 평면으로 보존합니다.</p>}
   {Array.isArray(item.source.structural_section_candidates)&&item.source.structural_section_candidates.length>0&&<p className="geometry-assumption">기둥 일람표의 단면 크기 호환 후보: {item.source.structural_section_candidates.map(c=>String((c as {mark?:string}).mark)).join(', ')}. 위치·부재 부호 매칭은 미확정입니다.</p>}
   {item.source.flight_height_status!==undefined&&<p className="geometry-assumption">지하 / 옥탑 비기준층의 단높이와 단수 매칭은 미확인입니다. 기준층 계단 높이를 복사하지 않았습니다.</p>}
   {related.length>0&&<details><summary>인접 실 / 벽체 후보 {related.length}개</summary>{[...new Set(related)].slice(0,30).map(id=><button className="related-object" key={id} onClick={()=>onSelect(id)}>{model.elements.find(e=>e.id===id)?.name??id}</button>)}</details>}
   {onEdit&&<button className="full" onClick={()=>onEdit(item)}>객체 형상 · 속성 편집</button>}
   <details><summary>CAD 객체 ID와 복원 근거</summary><pre>{JSON.stringify(item.source,null,2)}</pre></details>
  </>:<p className="empty-property">3D 모델 또는 좌측 목록에서 객체를 선택하세요. 공간은 ‘실 영역’을 켜면 화면에서도 선택할 수 있습니다.</p>}</section>
  <details open className="missing-evidence"><summary>추가 대조 / 필요한 자료 {missing.length}건</summary><ul>{missing.map(s=><li key={s}>{s}</li>)}</ul></details>
  {sections.length>0&&<details className="drawing-survey"><summary>구조 일람표 · 상세 도면 조사</summary><p className="muted">아래 치수는 일람표/상세 기록입니다. 개별 부재의 위치·높이·재료 적용은 미확정입니다.</p><table><thead><tr><th>부호</th><th>단면 기록 (m)</th></tr></thead><tbody>{sections.map(s=><tr key={s.mark}><td>{s.mark}</td><td>{s.shape==='circular'?'Ø ':''}{s.dimensions_m.join(' × ')}</td></tr>)}</tbody></table>{survey?.wall_sections?.map(w=><p key={w.mark}>벽체 {w.mark}: 일람표 두께 {w.thickness_m} m (적용 위치 미확정)</p>)}<label>상세·재료 기록<select aria-label="도면 근거 범주" value={noteFilter} onChange={e=>setNoteFilter(e.target.value)}><option value="structure">구조</option><option value="facade">외벽 · 창호</option><option value="interior">실내 마감</option><option value="all">전체</option></select></label><p className="muted">선택 범주 {filteredNotes.length}건 / 전체 {notes.length}건 (아래 40건 표시)</p>{filteredNotes.slice(0,40).map((n,i)=><p key={i}><strong>{n.text}</strong><small>{n.file}</small></p>)}<p className="muted">미제공 외부참조/자산: {survey?.unavailable_references?.join(', ')}</p></details>}
  <p className="muted">층 분리와 단면은 표시 옵션입니다. 원본 좌표와 저장 모델은 그대로 유지합니다.</p>
 </aside>;
}
