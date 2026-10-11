import { useEffect, useState } from "react";
import {
  Box,
  CheckCircle2,
  ChevronRight,
  Layers,
  Search,
  TriangleAlert,
  BrickWall,
  Columns3,
  DoorOpen,
  PanelsTopLeft,
  Footprints,
  ArrowUpFromLine,
  Square,
  Waypoints,
  Building2,
} from "lucide-react";
import { kinds, labels, type Model, type Element } from "./model";

const elementIcons: Record<string, typeof Box> = {
  wall: BrickWall,
  column: Columns3,
  door: DoorOpen,
  window: PanelsTopLeft,
  floor: Layers,
  roof: Building2,
  stair: ArrowUpFromLine,
  space: Square,
  corridor: Footprints,
  ramp: Waypoints,
};

interface Props {
  model: Model;
  elements: Element[];
  selected: string;
  query: string;
  category: string;
  onQuery: (v: string) => void;
  onCategory: (v: string) => void;
  onSelect: (id: string) => void;
}
export default function ObjectExplorer({
  model,
  elements,
  selected,
  query,
  category,
  onQuery,
  onCategory,
  onSelect,
}: Props) {
  const [limits, setLimits] = useState<Record<string, number>>({});
  useEffect(() => setLimits({}), [query, category, model.id, elements.length]);
  return (
    <>
      <div className="panel-heading">
        <h2>
          <Layers size={17} />
          객체 탐색
        </h2>
        <span>{elements.length.toLocaleString()}</span>
      </div>
      <div className="search-field">
        <Search size={16} />
        <input
          aria-label="객체 검색"
          placeholder="이름, 종류 또는 ID 검색"
          value={query}
          onChange={(e) => onQuery(e.target.value)}
        />
        {query && (
          <button aria-label="검색 초기화" onClick={() => onQuery("")}>
            ×
          </button>
        )}
      </div>
      <select
        className="category-filter"
        aria-label="건축 요소 종류"
        value={category}
        onChange={(e) => onCategory(e.target.value)}
      >
        <option value="all">모든 건축 요소</option>
        {kinds.map((k) => (
          <option value={k} key={k}>
            {labels[k]}
          </option>
        ))}
      </select>
      <div className="object-list" aria-label="층별 건축 요소">
        {model.floors.map((f) => {
          const group = elements.filter((e) => e.floor_id === f.id);
          return (
            group.length > 0 && (
              <details className="floor-group" key={f.id} open>
                <summary>
                  <Layers size={15} />
                  {f.name}
                  <span>{group.length}</span>
                </summary>
                {kinds.map((k) => {
                  const KindIcon = elementIcons[k] || Box;
                  const objects = group.filter((e) => e.type === k),
                    key = f.id + ":" + k,
                    limit = limits[key] ?? 100;
                  return (
                    objects.length > 0 && (
                      <details
                        className="kind-group"
                        key={k}
                        open={
                          category !== "all" ||
                          Boolean(query) ||
                          objects.some((e) => e.id === selected) ||
                          objects.length < 8
                        }
                      >
                        <summary>
                          <KindIcon size={14} />
                          {labels[k]}
                          <span>{objects.length}</span>
                        </summary>
                        {objects.slice(0, limit).map((e) => (
                          <button
                            className={`object-row ${e.id === selected ? "selected" : ""}`}
                            aria-pressed={e.id === selected}
                            title={`${e.name} · ${e.id}`}
                            key={e.id}
                            onClick={() => onSelect(e.id)}
                          >
                            <span className={`object-dot ${e.type}`} />
                            <span>
                              <strong>{e.name}</strong>
                              <small>
                                {e.excluded ? (
                                  "제외됨"
                                ) : e.verified ? (
                                  <>
                                    <CheckCircle2 size={11} />
                                    사용자 확인 기록
                                  </>
                                ) : (
                                  <>
                                    <TriangleAlert size={11} />
                                    검토 필요
                                  </>
                                )}
                              </small>
                            </span>
                            <ChevronRight size={14} />
                          </button>
                        ))}
                        {objects.length > limit && (
                          <button
                            className="load-more"
                            onClick={() =>
                              setLimits((v) => ({ ...v, [key]: limit + 100 }))
                            }
                          >
                            {labels[k]} 더 보기 · {limit} / {objects.length}
                          </button>
                        )}
                      </details>
                    )
                  );
                })}
              </details>
            )
          );
        })}
        {elements.length === 0 && (
          <div className="empty-state">
            <Search size={24} />
            <strong>검색 결과가 없습니다</strong>
            <p>검색어 또는 층·종류 필터를 변경하세요.</p>
            <button
              onClick={() => {
                onQuery("");
                onCategory("all");
              }}
            >
              검색 조건 초기화
            </button>
          </div>
        )}
      </div>
    </>
  );
}
