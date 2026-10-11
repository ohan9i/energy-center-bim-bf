import { useState } from "react";
import { Box, FileSearch, Info, TriangleAlert } from "lucide-react";
import { labels, type Model, type Element } from "./model";
import { planArea } from "./bimGeometry";
import { bounds, raw } from "./geometry";
interface Props {
  model: Model;
  library: Model[];
  item?: Element;
  floor: string;
  onActivate: (m: Model) => void;
  onFloor: (id: string) => void;
  onSelect: (id: string) => void;
  onEdit?: (e: Element) => void;
}
const format = (v: unknown) =>
  typeof v === "number" ? v.toFixed(3) + " m" : "미확인";
const evidenceLabels: Record<string,string> = {identity:"부재 부호",position:"평면 위치",profile:"평면 윤곽",base:"하단 레벨",top:"상단 높이",material:"재료",scope:"적용 층",revision:"도면 개정",member_mark:"창호 부호"};
const evidenceStates: Record<string,string> = {verified:"검증 완료",drawing_based:"도면에서 측정",candidate:"연결 후보 · 확인 필요",provisional:"시각화 가정",unresolved:"미확정"};
export default function BimInspector({
  model,
  library,
  item,
  floor,
  onActivate,
  onFloor,
  onSelect,
  onEdit,
}: Props) {
  const [noteFilter, setNoteFilter] = useState("structure");
  const visible = model.elements.filter(
    (e) => !e.excluded && (floor === "all" || e.floor_id === floor),
  );
  const counts = new Map<string, number>();
  for (const e of visible) counts.set(e.type, (counts.get(e.type) ?? 0) + 1);
  const missing = Array.isArray(model.provenance.missing_information)
    ? (model.provenance.missing_information as string[])
    : [];
  const related = item
    ? [
        ...new Set(
          [
            "adjacent_space_ids",
            "host_wall_ids",
            "continuity_host_wall_ids",
          ].flatMap((key) =>
            Array.isArray(item.source[key])
              ? (item.source[key] as string[])
              : [],
          ),
        ),
      ]
    : [];
  const bb = item ? bounds([raw(item)]) : null;
  const survey = model.provenance.drawing_evidence as
    | {
        column_sections?: {
          mark: string;
          shape: string;
          dimensions_m: number[];
        }[];
        wall_sections?: { mark: string; thickness_m: number }[];
        note_candidates?: { file: string; text: string }[];
        unavailable_references?: string[];
      }
    | undefined;
  const sections = Array.isArray(survey?.column_sections)
      ? survey.column_sections
      : [],
    notes = Array.isArray(survey?.note_candidates)
      ? survey.note_candidates
      : [];
  const filteredNotes = notes.filter(
    (n) =>
      noteFilter === "all" ||
      (noteFilter === "structure"
        ? n.file.includes("/S")
        : noteFilter === "facade"
          ? /^(A06|A10)/.test(n.file)
          : n.file.startsWith("A03")),
  );
  return (
    <aside className="right-panel bim-inspector" id="navigation">
      <div className="inspector-heading">
        <FileSearch size={18} />
        <div>
          <h2>속성 검토</h2>
          <p>객체 정보와 도면 근거</p>
        </div>
      </div>

      <section className="properties architectural-properties">
        <div className="section-heading">
          <h2>선택 객체</h2>
          <Box size={16} />
        </div>
        {item ? (
          <>
            <h3>{item.name}</h3>
            <p className="object-type">
              {labels[item.type]} / {item.type.toUpperCase()}
            </p>
            <p className="object-id" title={item.id}>
              {item.id}
            </p>
            <span className="status unknown">
              <TriangleAlert size={13} />
              {item.verified
                ? "사용자 검토 기록 있음"
                : item.source.geometry_status === "measured_plan"
                  ? "평면 형상 측정 · 높이 검토 필요"
                  : "재구성 후보 · 검토 필요"}
            </span>
            <h4 className="fact-heading">기본 정보</h4>
            <dl className="bim-facts">
              <dt>소속 층</dt>
              <dd>{model.floors.find((f) => f.id === item.floor_id)?.name}</dd>
              <dt>기준 Z</dt>
              <dd>
                {(
                  (model.floors.find((f) => f.id === item.floor_id)
                    ?.elevation ?? 0) + item.z_offset
                ).toFixed(3)}{" "}
                m
              </dd>
              <dt>높이 / 두께</dt>
              <dd>{format(item.height)}</dd>
              <dt>원본 XY 면적</dt>
              <dd>
                {planArea(item).toFixed(2)} m²{" "}
                <small>(BF 기준 평면 · 수량 미검증)</small>
              </dd>
              {item.source.architectural_slab_profiles !== undefined && (
                <>
                  <dt>보정 슬래브 면적</dt>
                  <dd>
                    {item.components
                      .filter((c) => c.role === "structural_slab")
                      .reduce((area, c) => area + planArea(c), 0)
                      .toFixed(2)}{" "}
                    m² <small>(검토용 형상)</small>
                  </dd>
                </>
              )}
            </dl>
            <details className="fact-section">
              <summary>형상 정보 · 구성 요소</summary>
              <dl className="bim-facts">
                <dt>X / Y 범위 길이</dt>
                <dd>
                  {bb &&
                    `${(bb.max[0] - bb.min[0]).toFixed(3)} / ${(bb.max[1] - bb.min[1]).toFixed(3)} m`}
                </dd>
                {item.source.measured_thickness_m !== undefined && (
                  <>
                    <dt>벽면 간격</dt>
                    <dd>{format(item.source.measured_thickness_m)}</dd>
                  </>
                )}
                {item.source.leaf_radius_m !== undefined && (
                  <>
                    <dt>문 회전호 반지름</dt>
                    <dd>
                      {format(item.source.leaf_radius_m)}{" "}
                      <small>(문 유효폭과 별도)</small>
                    </dd>
                  </>
                )}
                {item.components.length > 0 && (
                  <>
                    <dt>조립체 구성요소</dt>
                    <dd>
                      {item.components.length}개 ·{" "}
                      {[...new Set(item.components.map((c) => c.role))].join(
                        ", ",
                      )}
                    </dd>
                  </>
                )}
                {item.type === "stair" && (
                  <>
                    <dt>평면 단선 간격</dt>
                    <dd>{format(item.source.tread_pitch_m)}</dd>
                    <dt>상세 단높이</dt>
                    <dd>{format(item.source.riser_m)}</dd>
                  </>
                )}
              </dl>
            </details>
            <details className="fact-section" open>
              <summary>CAD 근거 · 높이 출처</summary>
              <dl className="bim-facts">
                <dt>객체 ID</dt>
                <dd>{item.id}</dd>
                <dt>도면</dt>
                <dd>{String(item.source.file ?? "출처 없음")}</dd>
                <dt>높이 근거</dt>
                <dd>
                  {item.height === null
                    ? "미확인 · 가정 표시와 별도로 저장"
                    : String(
                        item.source.height_source ?? "구성요소별 근거 확인",
                      )}
                </dd>
                {Boolean(model.provenance.precision_rebuild) && (
                  <>
                    <dt>평면 CAD 객체</dt>
                    <dd>{Array.isArray(item.source.cad_ids) ? (item.source.cad_ids as string[]).join(", ") : "미확인"}</dd>
                    <dt>미확정 정보</dt>
                    <dd>{Array.isArray(item.source.unknowns) ? (item.source.unknowns as string[]).join(", ") : "부재 상세 확인 필요"}</dd>
                    <dt>검증 입체 여부</dt>
                    <dd>{(item.source.verification as {eligible?:boolean}|undefined)?.eligible ? "도면 근거 검증 · Verified IFC 포함" : model.provenance.coordination_draft ? "미확정 · Draft IFC 포함 / Verified IFC 제외" : "미확정 · IFC 입체에서 제외"}</dd>
                  </>
                )}
              </dl>
            </details>
            {item.source.validation_status !== undefined && <details className="fact-section" open>
              <summary>검증 상태 · 적용 가정</summary>
              <dl className="bim-facts">
                <dt>부재 상태</dt><dd>{evidenceStates[String(item.source.validation_status)] ?? String(item.source.validation_status)}</dd>
                {Object.entries((item.source.property_status ?? {}) as Record<string,string>).map(([key,value])=>
                  <div key={key}><dt>{key}</dt><dd>{value}</dd></div>)}
              </dl>
              <p>재료 색상은 미확정 분류의 시각화이며 설계 마감 확정값이 아닙니다.</p>
              {item.source.property_evidence !== undefined && <details open>
                <summary>속성별 도면 근거</summary>
                <table><thead><tr><th>속성</th><th>확인 상태 · 값</th><th>근거</th></tr></thead><tbody>
                  {Object.entries(item.source.property_evidence as Record<string,{status:string;value_m?:number;value?:string;references?:unknown[]}>).map(([field,record])=>
                    <tr key={field}><td>{evidenceLabels[field] ?? field}</td><td>{evidenceStates[record.status] ?? record.status}{record.value_m!==undefined && ` · ${format(record.value_m)}`}{record.value && ` · ${record.value}`}</td><td>{record.references?.length ?? 0}건</td></tr>)}
                </tbody></table>
                <details><summary>도면 객체와 검토 기록</summary><pre style={{whiteSpace:"pre-wrap",overflowWrap:"anywhere",fontSize:12}}>{JSON.stringify(item.source.property_evidence,null,2)}</pre></details>
              </details>}
              {item.source.plan_schedule_links !== undefined && <details open>
                <summary>창호도 부호 연결 후보</summary>
                <pre style={{whiteSpace:"pre-wrap",overflowWrap:"anywhere",fontSize:12}}>{JSON.stringify(item.source.plan_schedule_links,null,2)}</pre>
              </details>}
              {item.source.section_dimension_link !== undefined && <details open>
                <summary>계단 단면 치수 대조</summary>
                <pre style={{whiteSpace:"pre-wrap",overflowWrap:"anywhere",fontSize:12}}>{JSON.stringify(item.source.section_dimension_link,null,2)}</pre>
              </details>}
              {item.source.verification !== undefined && <details>
                <summary>검증 조건 · 남은 항목</summary>
                <pre style={{whiteSpace:"pre-wrap",overflowWrap:"anywhere",fontSize:12}}>{JSON.stringify(item.source.verification,null,2)}</pre>
              </details>}
              {item.source.candidate_classification !== undefined && <p>벽 후보 판정: {String(item.source.candidate_classification)} · {String(item.source.classification_reason)}</p>}
              <pre style={{whiteSpace:"pre-wrap",overflowWrap:"anywhere",fontSize:12}}>{JSON.stringify(item.source.assumptions ?? {}, null, 2)}</pre>
              <details><summary>구성요소별 적용 치수</summary>
                <pre style={{whiteSpace:"pre-wrap",fontSize:12}}>{JSON.stringify(item.source.applied_dimensions ?? {},null,2)}</pre>
              </details>
            </details>}
            {item.source.assembly_status !== undefined && (
              <details>
                <summary>임시 조립체 치수 · 도면 검증 전</summary>
                <p className="geometry-assumption">
                  아래 높이/두께에는 가정값이 포함됩니다. 경사 솔리드의 높이는 Z
                  범위이며 실제 판 두께와 다릅니다.
                </p>
                <table>
                  <thead>
                    <tr>
                      <th>구성 · 재질</th>
                      <th>상대 Z (m)</th>
                      <th>Z 높이 (m)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {item.components.map((c, i) => (
                      <tr key={c.id || i}>
                        <td>
                          <details>
                            <summary>
                              {c.role} · {String(c.source.material ?? "미확인")}
                            </summary>
                            <small>{c.id || "이전 구성 ID 없음"}</small>
                            <p>
                              {c.source.dimension_verified === true
                                ? "치수 확인 기록 있음"
                                : "임시 치수 · 검토 필요"}
                            </p>
                            <pre>{JSON.stringify(c.source, null, 2)}</pre>
                          </details>
                        </td>
                        <td>{c.z_offset.toFixed(3)}</td>
                        <td>{c.height?.toFixed(3) ?? "미확인"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </details>
            )}
            {item.source.architectural_vertical_profiles !== undefined && (
              <p className="geometry-assumption">
                상부 슬래브 접합은 별도 건축 형상으로 처리합니다. 원래 층간
                높이와 BF 평면을 보존하며, 슬래브 두께 가정을 끄면 원래 높이로
                표시합니다.
              </p>
            )}
            {item.source.railing_status !== undefined && (
              <p className="geometry-assumption">
                난간은 CAD 계단 범위의 임시 배치입니다. 상세도 규격 기록과 개별
                계단의 적용 관계는 미확정입니다.
              </p>
            )}
            {item.source.continuity_repair_status !== undefined && (
              <p className="geometry-assumption">
                건축적 단절을 메운 검토용 보정입니다. 창 주변 벽·리빌, 바닥
                연결, 파라펫·옥탑 덮개의 보정 치수는 도면 확정값이 아닙니다.
                원래 BF 평면과 통행 속성은 보존합니다.
              </p>
            )}
            {item.source.continuity_review_issue !== undefined && (
              <p className="geometry-assumption">
                창호 후보의 닫힘 위치와 호스트 연결을 확인하지 못했습니다. 원본
                후보 위치를 유지했으며 임의의 방을 생성하지 않았습니다.
              </p>
            )}
            {item.source.marker_width_m !== undefined && (
              <p className="geometry-assumption">
                이 면의 10 mm 폭은 위치 표시용입니다. 실제 벽 두께가 아닙니다.
              </p>
            )}
            {item.source.boundary_status === "labels_share_boundary" && (
              <p className="geometry-assumption">
                여러 실명이 한 경계에 포함됩니다. 실별 칸막이와 면적 분리는
                미확정입니다.
              </p>
            )}
            {item.source.detail_pitch_conflict === true && (
              <p className="geometry-assumption">
                평면 280 mm / 코어 상세 300 mm 단너비 불일치. 자동 통일하지
                않았습니다.
              </p>
            )}
            {Array.isArray(item.source.coincident_profile_ids) &&
              item.source.coincident_profile_ids.length > 0 && (
                <p className="geometry-assumption">
                  같은 중심의 서로 다른 기둥 단면이 있습니다. 부재 구분이
                  미확인되어 높이 없는 평면으로 보존합니다.
                </p>
              )}
            {Array.isArray(item.source.structural_section_candidates) &&
              item.source.structural_section_candidates.length > 0 && (
                <p className="geometry-assumption">
                  기둥 일람표의 단면 크기 호환 후보:{" "}
                  {item.source.structural_section_candidates
                    .map((c) => String((c as { mark?: string }).mark))
                    .join(", ")}
                  . 위치·부재 부호 매칭은 미확정입니다.
                </p>
              )}
            {item.source.flight_height_status !== undefined && (
              <p className="geometry-assumption">
                지하 / 옥탑 비기준층의 단높이와 단수 매칭은 미확인입니다. 기준층
                계단 높이를 복사하지 않았습니다.
              </p>
            )}
            {related.length > 0 && (
              <details>
                <summary>인접 실 / 벽체 후보 {related.length}개</summary>
                {[...new Set(related)].slice(0, 30).map((id) => (
                  <button
                    className="related-object"
                    key={id}
                    onClick={() => onSelect(id)}
                  >
                    {model.elements.find((e) => e.id === id)?.name ?? id}
                  </button>
                ))}
              </details>
            )}
            {onEdit && (
              <button className="full" onClick={() => onEdit(item)}>
                객체 형상 · 속성 편집
              </button>
            )}
            <details>
              <summary>CAD 객체 ID와 복원 근거</summary>
              <pre>{JSON.stringify(item.source, null, 2)}</pre>
            </details>
          </>
        ) : (
          <div className="empty-state">
            <Box size={30} />
            <strong>검토할 객체를 선택하세요</strong>
            <p>
              모델 또는 객체 탐색에서 선택하면 속성과 CAD 근거를 확인할 수
              있습니다.
            </p>
            <small>실은 표시 설정의 ‘실 영역’을 켜면 선택할 수 있습니다.</small>
          </div>
        )}
      </section>
      <details className="model-overview">
        <summary>모델 구성 · 층별 요소</summary>{" "}
        <div className="bim-floor-list">
          {model.floors.map((f) => (
            <button
              className={floor === f.id ? "active" : ""}
              key={f.id}
              onClick={() => onFloor(f.id)}
            >
              {f.name}
              <small> Z {f.elevation.toFixed(2)} m</small>
            </button>
          ))}
        </div>
        <div className="bim-counts">
          {[...counts].map(([kind, count]) => (
            <span key={kind}>
              {labels[kind]} <strong>{count}</strong>
            </span>
          ))}
        </div>
      </details>
      <details className="missing-evidence">
        <summary>추가 대조 / 필요한 자료 {missing.length}건</summary>
        <ul>
          {missing.map((s) => (
            <li key={s}>{s}</li>
          ))}
        </ul>
      </details>
      {sections.length > 0 && (
        <details className="drawing-survey">
          <summary>구조 일람표 · 상세 도면 조사</summary>
          <p className="muted">
            아래 치수는 일람표/상세 기록입니다. 개별 부재의 위치·높이·재료
            적용은 미확정입니다.
          </p>
          <table>
            <thead>
              <tr>
                <th>부호</th>
                <th>단면 기록 (m)</th>
              </tr>
            </thead>
            <tbody>
              {sections.map((s) => (
                <tr key={s.mark}>
                  <td>{s.mark}</td>
                  <td>
                    {s.shape === "circular" ? "Ø " : ""}
                    {s.dimensions_m.join(" × ")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {survey?.wall_sections?.map((w) => (
            <p key={w.mark}>
              벽체 {w.mark}: 일람표 두께 {w.thickness_m} m (적용 위치 미확정)
            </p>
          ))}
          <label>
            상세·재료 기록
            <select
              aria-label="도면 근거 범주"
              value={noteFilter}
              onChange={(e) => setNoteFilter(e.target.value)}
            >
              <option value="structure">구조</option>
              <option value="facade">외벽 · 창호</option>
              <option value="interior">실내 마감</option>
              <option value="all">전체</option>
            </select>
          </label>
          <p className="muted">
            선택 범주 {filteredNotes.length}건 / 전체 {notes.length}건 (아래
            40건 표시)
          </p>
          {filteredNotes.slice(0, 40).map((n, i) => (
            <p key={i}>
              <strong>{n.text}</strong>
              <small>{n.file}</small>
            </p>
          ))}
          <p className="muted">
            미제공 외부참조/자산: {survey?.unavailable_references?.join(", ")}
          </p>
        </details>
      )}
      <p className="muted inspector-footnote">
        <Info size={14} />층 분리와 단면은 표시 옵션입니다. 원본 좌표와 저장
        모델은 그대로 유지합니다.
      </p>
    </aside>
  );
}
