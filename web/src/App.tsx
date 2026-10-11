import { useEffect, useRef, useState } from "react";
import {
  ArrowRight,
  ArrowUpRight,
  Box,
  Check,
  ChevronRight,
  Download,
  FileUp,
  Layers,
  MapPin,
  Move,
  Navigation,
  PanelLeft,
  PanelRight,
  Rotate3D,
  Save,
  Settings2,
  ShieldCheck,
  Square,
  Upload,
  X,
  Building2,
  ChevronDown,
  HelpCircle,
  Search,
  ArrowLeftRight,
  CheckCircle2,
  TriangleAlert,
} from "lucide-react";
import Viewer from "./Viewer";
import PrecisionReview from "./PrecisionReview";
import BimInspector from "./BimInspector";
import ObjectExplorer from "./ObjectExplorer";
import { isRetiredModel, loadModelRecords, saveModelRecord } from "./modelStorage";
import {
  parseModel,
  elementSchema,
  kinds,
  labels,
  type Model,
  type Element,
  type Profile,
  type Rules,
} from "./model";
import { validateGeometry } from "./geometry";
import { evaluate, statusLabel } from "./evaluation";
import type { RouteResult } from "./navigation";
const base = import.meta.env.BASE_URL;
const editing = import.meta.env.VITE_VIEWER_ONLY !== "true";
type CAD = {
  token: string;
  entity_count: number;
  units: { meters_per_drawing_unit: number | null; name: string };
  layers: { name: string; count: number; suggested: string }[];
  warnings: { code: string; message: string }[];
};
async function request(url: string, init?: RequestInit) {
  const r = await fetch(url, init);
  if (!r.ok) {
    let message = r.statusText;
    try {
      const j = await r.json();
      message =
        typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {}
    throw Error(message);
  }
  return r;
}
function download(data: BlobPart, name: string, type = "application/json") {
  const u = URL.createObjectURL(new Blob([data], { type }));
  const a = document.createElement("a");
  a.href = u;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(u), 1000);
}
function checkedModel(data: unknown) {
  const m = parseModel(data);
  if (isRetiredModel(m)) throw Error("삭제된 기본 모델입니다. 최신 통합 3D 모델을 사용하세요.");
  validateGeometry(m);
  return m;
}
export default function App() {
  const [precisionOpen, setPrecisionOpen] = useState(false);
  const [initializing, setInitializing] = useState(true);
  const [model, setModel] = useState<Model | null>(null),
    [library, setLibrary] = useState<Model[]>([]),
    [rules, setRules] = useState<Rules | null>(null),
    [profile, setProfile] = useState<Profile | null>(null),
    [profileKey, setProfileKey] = useState("wheelchair");
  const [mode, setMode] = useState(editing ? "designer" : "visitor"),
    [tab, setTab] = useState("objects"),
    [floor, setFloor] = useState("all"),
    [plan, setPlan] = useState(false),
    [selected, setSelected] = useState(""),
    [query, setQuery] = useState("");
  const [start, setStart] = useState(""),
    [end, setEnd] = useState(""),
    [route, setRoute] = useState<RouteResult | null>(null),
    [busy, setBusy] = useState(false),
    [message, setMessage] = useState(""),
    [error, setError] = useState("");
  const [api, setApi] = useState(false),
    [oda, setOda] = useState(false),
    [cad, setCad] = useState<CAD | null>(null),
    [mapping, setMapping] = useState<Record<string, string>>({}),
    [scale, setScale] = useState(""),
    [height, setHeight] = useState("3"),
    [thickness, setThickness] = useState(".2");
  const [draft, setDraft] = useState(""),
    [editor, setEditor] = useState<"element" | "model" | "add" | null>(null),
    [showConditions, setShowConditions] = useState(false);
  const [bimWorkspace, setBimWorkspace] = useState(true),
    [category, setCategory] = useState("all");
  const [leftOpen, setLeftOpen] = useState(() => window.innerWidth > 1100),
    [rightOpen, setRightOpen] = useState(false);
  const modalRef = useRef<HTMLDivElement>(null),
    editorTrigger = useRef<HTMLElement | null>(null);
  const worker = useRef<Worker | null>(null);
  const epoch = useRef(0);
  useEffect(() => {
    const media = window.matchMedia("(max-width:1100px)");
    const change = () => {
      setLeftOpen(!media.matches);
      setRightOpen(false);
    };
    media.addEventListener("change", change);
    return () => media.removeEventListener("change", change);
  }, []);
  useEffect(() => {
    const close = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !editor && window.innerWidth <= 1100) {
        setLeftOpen(false);
        setRightOpen(false);
      }
    };
    document.addEventListener("keydown", close);
    return () => document.removeEventListener("keydown", close);
  }, [editor]);
  useEffect(() => {
    if (!message) return;
    const timer = setTimeout(() => setMessage(""), 6000);
    return () => clearTimeout(timer);
  }, [message]);
  useEffect(() => {
    if (!editor) return;
    const previous = editorTrigger.current;
    const dialog = modalRef.current;
    const escape = (e: KeyboardEvent) => {
      if (e.key === "Escape") setEditor(null);
      if (e.key === "Tab" && dialog) {
        const nodes = Array.from(
          dialog.querySelectorAll<HTMLElement>(
            "button:not(:disabled),textarea",
          ),
        );
        const first = nodes[0],
          last = nodes.at(-1);
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last?.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first?.focus();
        }
      }
    };
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("keydown", escape);
      previous?.focus();
    };
  }, [editor]);
  function togglePanel(side: "left" | "right") {
    if (side === "left") {
      setLeftOpen((v) => !v);
      if (window.innerWidth <= 1100) setRightOpen(false);
    } else {
      setRightOpen((v) => !v);
      if (window.innerWidth <= 1100) setLeftOpen(false);
    }
  }
  function selectObject(id: string) {
    setSelected(id);
    if (id) {
      setRightOpen(true);
      if (window.innerWidth <= 1100) setLeftOpen(false);
    }
  }
  function changeWorkspace(bim: boolean) {
    setBimWorkspace(bim);
    setRightOpen(!bim);
    if (window.innerWidth <= 1100) setLeftOpen(false);
  }
  const [helpOpen, setHelpOpen] = useState(false);
  useEffect(() => {
    const close = (e: KeyboardEvent) => {
      if (e.key === "Escape") setHelpOpen(false);
    };
    document.addEventListener("keydown", close);
    return () => document.removeEventListener("keydown", close);
  }, []);
  function openEditor(kind: "element" | "model" | "add") {
    editorTrigger.current = document.activeElement as HTMLElement | null;
    setEditor(kind);
  }
  function fail(e: unknown) {
    setError(e instanceof Error ? e.message : String(e));
    setBusy(false);
  }
  function activate(m: Model) {
    worker.current?.terminate();
    epoch.current++;
    setBusy(false);
    setModel(m);
    setRoute(null);
    setSelected("");
    setFloor(m.is_example ? m.floors[0].id : "all");
    setCategory("all");
    setStart(m.places[0]?.id || "");
    setEnd(
      m.places.find((p) => p.floor_id !== m.places[0]?.floor_id)?.id ||
        m.places.at(-1)?.id ||
        "",
    );
  }
  useEffect(() => {
    let cancelled = false;
    Promise.all([
      request(base + "models/precision-rebuild.json").then((r) => r.json()),
      request(base + "rules.json").then((r) => r.json()),
    ])
      .then(async ([data, r]) => {
        if (cancelled) return;
        const published = checkedModel(data);
        let current = published;
        const restored: Model[] = [];
        setRules(r);
        setProfile(r.profiles.wheelchair);
        const records = await loadModelRecords();
        if (cancelled) return;
        try {
          if (records.current) {
            const m = checkedModel(JSON.parse(records.current));
            if (m.id === published.id && Number(m.provenance.modelling_version ?? 0) >= Number(published.provenance.modelling_version ?? 0)) {
              current = m;
            } else {
              restored.push({...m, id: m.id === published.id ? m.id + "-saved" : m.id});
            }
          }
        } catch {
          setMessage("이전에 저장한 모델을 읽지 못해 최신 통합 3D 모델을 열었습니다.");
        }
        records.previous.forEach((previous, i) => {
          try {
            const old = checkedModel(JSON.parse(previous)),
              retained = {
                ...old,
                id: old.id + "-previous-" + i,
                name: old.name + " · 이전 저장본 " + (i + 1),
              };
            restored.push(retained);
          } catch {}
        });
        setLibrary([current, ...restored.filter(m => m.id !== current.id)]);
        activate(current);
        setInitializing(false);
        if (editing) {
          request("/api/health")
            .then((r) => r.json())
            .then((h) => {
              setApi(h.status === "ok");
              setOda(h.oda_available);
            })
            .catch(() => {});
        }
      })
      .catch(fail);
    return () => { cancelled = true; worker.current?.terminate(); };
  }, []);
  useEffect(() => {
    setRoute(null);
    worker.current?.terminate();
    epoch.current++;
    setBusy(false);
  }, [model, profile, start, end]);
  function update(m: Model) {
    try {
      m = checkedModel({ ...m, revision: (model?.revision || 0) + 1 });
      setModel(m);
      setLibrary((list) => [...list.filter((x) => x.id !== m.id), m]);
      setRoute(null);
      setMessage("모델 형상과 속성을 검증해 적용했습니다.");
      return true;
    } catch (e) {
      fail(e);
      return false;
    }
  }
  async function save() {
    if (!model) return;
    try {
      await saveModelRecord(JSON.stringify(model));
      setMessage(
        "이 브라우저의 모델 저장소에 저장했습니다. 기존 저장본도 보존합니다.",
      );
    } catch (e) {
      fail(e);
    }
  }
  async function importJSON(file: File) {
    try {
      const m = checkedModel(JSON.parse(await file.text()));
      setLibrary((list) => [...list.filter((x) => x.id !== m.id), m]);
      activate(m);
      setMessage("JSON 모델을 불러왔습니다.");
    } catch (e) {
      fail(e);
    }
  }
  async function uploadCAD(file: File) {
    setBusy(true);
    setError("");
    try {
      const form = new FormData();
      form.append("file", file);
      const data: CAD = await (
        await request("/api/cad/analyze", { method: "POST", body: form })
      ).json();
      setCad(data);
      setMapping(
        Object.fromEntries(data.layers.map((l) => [l.name, l.suggested])),
      );
      setScale(data.units.meters_per_drawing_unit?.toString() || "");
      setTab("cad");
      setMessage(
        `${data.entity_count.toLocaleString()}개 객체를 분석했습니다.`,
      );
      setBusy(false);
    } catch (e) {
      fail(e);
    }
  }
  async function buildCAD() {
    if (!cad) return;
    setBusy(true);
    try {
      const data = await (
        await request("/api/cad/build", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            token: cad.token,
            mapping,
            scale: scale ? Number(scale) : null,
            height: Number(height),
            thickness: Number(thickness),
          }),
        })
      ).json();
      let m = checkedModel(data);
      // Keep user changes to stable CAD IDs only when the extracted source geometry is unchanged.
      if (model?.id === m.id) {
        m.elements = m.elements.map((e) => {
          const old = model.elements.find((x) => x.id === e.id);
          return old &&
            old.source.origin === "user_edit" &&
            JSON.stringify(old.source.original_polygon) ===
              JSON.stringify(e.polygon)
            ? old
            : e;
        });
      }
      setLibrary((list) => [...list.filter((x) => x.id !== m.id), m]);
      activate(m);
      setMessage("CAD 기반 모델 생성 완료. 확인 필요 속성을 보완하세요.");
      setBusy(false);
    } catch (e) {
      fail(e);
    }
  }
  async function exportIFC(draft = false) {
    if (!model) return;
    setBusy(true);
    try {
      if (model.provenance.precision_rebuild) {
        const assets = model.provenance.ifc_assets as {draft?:string;verified?:string}|undefined;
        const candidate = draft ? assets?.draft : assets?.verified;
        const asset = candidate && /^precision-rebuild-(coordination-draft|verified)\.ifc$/.test(candidate)
          ? candidate : draft ? "precision-rebuild-coordination-draft.ifc" : "precision-rebuild-verified.ifc";
        const r = await request(base + "models/" + asset);
        download(await r.text(), draft ? "energy-center-Coordination-Draft.ifc" : "energy-center-Verified.ifc", "application/x-step");
        setMessage(draft ? "검토용 Draft IFC를 저장했습니다. 미확정 입체와 적용 가정이 포함되며 설계 검증 완료 BIM이 아닙니다." : `검증 형상 IFC를 저장했습니다. 도면 근거와 검증 조건을 충족한 부재 ${Number(model.provenance.verified_solids ?? 0)}개를 포함합니다.`);
        setBusy(false);
        return;
      }
      const r = await request("/api/ifc", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(model),
      });
      download(await r.text(), "building.ifc", "application/x-step");
      setBusy(false);
      setMessage("IFC4 파일을 내보냈습니다.");
    } catch (e) {
      fail(e);
    }
  }
  function runRoute() {
    if (!model || !profile) return;
    setBusy(true);
    setError("");
    worker.current?.terminate();
    const w = new Worker(new URL("./route.worker.ts", import.meta.url), {
      type: "module",
    });
    worker.current = w;
    const current = ++epoch.current;
    w.onmessage = (e) => {
      if (current !== epoch.current) return;
      setBusy(false);
      w.terminate();
      if (e.data.error) fail(Error(e.data.error));
      else {
        setRoute(e.data.result);
        setMessage(
          e.data.result.status === "found"
            ? "이동 조건을 만족하는 경로를 찾았습니다."
            : "현재 조건에서 경로를 찾지 못했습니다.",
        );
      }
    };
    w.onerror = () => {
      if (current === epoch.current)
        fail(
          Error(
            "경로 계산 중 오류가 발생했습니다. 모델 범위와 속성을 확인하세요.",
          ),
        );
      w.terminate();
    };
    w.postMessage({ model, start, end, profile });
  }
  function editElement(e: Element) {
    setDraft(JSON.stringify(e, null, 2));
    openEditor("element");
  }
  function commitEditor() {
    if (!model) return;
    try {
      let applied = false;
      if (editor === "model") {
        applied = update(checkedModel(JSON.parse(draft)));
      } else {
        let e = elementSchema.parse(JSON.parse(draft));
        const old = model.elements.find((x) => x.id === e.id);
        if (editor === "add" && old)
          throw Error("새 객체에는 고유 ID가 필요합니다.");
        if (editor === "element" && e.id !== selected)
          throw Error("기존 객체의 ID를 바꾸지 마세요.");
        e = {
          ...e,
          verified: false,
          source: {
            ...e.source,
            origin: "user_edit",
            original_polygon:
              old?.source.original_polygon || old?.polygon || e.polygon,
          },
        };
        applied = update({
          ...model,
          elements:
            editor === "add"
              ? [...model.elements, e]
              : model.elements.map((x) => (x.id === e.id ? e : x)),
        });
      }
      if (applied) setEditor(null);
    } catch (e) {
      fail(e);
    }
  }
  if (initializing || !model || !profile || !rules)
    return (
      <div className="loading" role="status">
        <Box size={32} />
        <h2>
          {error ? "모델을 불러오지 못했습니다" : "공간을 준비하고 있습니다"}
        </h2>
        <p>{error || "BIM 모델과 도면 근거를 불러오는 중…"}</p>
        {error && (
          <button onClick={() => window.location.reload()}>다시 시도</button>
        )}
      </div>
    );
  const item = model.elements.find((e) => e.id === selected),
    review = model.elements
      .filter(
        (e) =>
          !e.excluded &&
          [
            "door",
            "stair",
            "ramp",
            "elevator",
            "floor",
            "unclassified",
          ].includes(e.type),
      )
      .map((e) => ({ e, ...evaluate(e, profile) }));
  const attention = review.filter((x) => x.status !== "pass"),
    elements = model.elements.filter(
      (e) =>
        (floor === "all" || e.floor_id === floor) &&
        (category === "all" || e.type === category) &&
        `${e.name} ${e.id} ${labels[e.type]}`
          .toLowerCase()
          .includes(query.toLowerCase()),
    );
  const designer = mode === "designer";
  const counts = {
    blocked: review.filter((x) => x.status === "blocked").length,
    unknown: review.filter((x) => x.status === "unknown").length,
  };
  function quick(field: keyof Element["properties"], value: unknown) {
    if (!item) return;
    update({
      ...model!,
      elements: model!.elements.map((e) =>
        e.id === item.id
          ? {
              ...e,
              verified: false,
              properties: { ...e.properties, [field]: value },
              source: {
                ...e.source,
                origin: "user_edit",
                original_polygon: e.source.original_polygon || e.polygon,
              },
            }
          : e,
      ),
    });
  }
  return (
    <div className="app-shell">
      <a
        className="skip"
        href="#navigation"
        onClick={() => {
          setRightOpen(true);
          if (window.innerWidth <= 1100) setLeftOpen(false);
        }}
      >
        속성 · 경로 설정으로 바로가기
      </a>
      <header className="header">
        <a className="brand" href="#" aria-label="공간이음 홈">
          <span className="brand-icon">
            <svg viewBox="0 0 32 32" fill="none" aria-hidden="true">
              <path
                d="M4 10 16 3l12 7v13l-12 7L4 23V10Z"
                stroke="currentColor"
                strokeWidth="1.6"
              />
              <path
                d="m4 10 12 7 12-7M16 17v13M10 13.5v-7m12 7v-7M10 20l6 3.5 6-3.5"
                stroke="currentColor"
                strokeWidth="1.6"
              />
            </svg>
          </span>
          <span>
            공간이음<small>BIM / BF WORKSPACE</small>
          </span>
        </a>
        <div className="header-divider" />
        <div className="project-identity">
          <Building2 size={16} />
          <h1 title={model.name}>{model.name}</h1>
          <span className="revision">
            R{String(model.revision).padStart(2, "0")}
          </span>
        </div>
        <div className="header-actions">
          {editing && <button className="icon-button" aria-label="정밀 1층 검토" onClick={() => setPrecisionOpen(true)}>정밀 1층</button>}
          {precisionOpen && <PrecisionReview onClose={() => setPrecisionOpen(false)} />}
          <span className="model-state">
            <i />
            {model.is_example ? "예제 모델" : "도면 기반 모델"}
          </span>
          {editing && (
            <div className="mode-switch" aria-label="작업 모드">
              <button
                aria-pressed={designer}
                className={designer ? "active" : ""}
                onClick={() => setMode("designer")}
              >
                설계자
              </button>
              <button
                aria-pressed={!designer}
                className={!designer ? "active" : ""}
                onClick={() => {
                  setMode("visitor");
                  setTab("objects");
                }}
              >
                이용자
              </button>
            </div>
          )}
          <button
            className="icon-button help-trigger"
            aria-label="사용 도움말"
            aria-expanded={helpOpen}
            onClick={() => setHelpOpen((v) => !v)}
          >
            <HelpCircle size={18} />
          </button>
        </div>
      </header>
      <nav className="workspace-bar" aria-label="작업 공간">
        <div className="workspace-switch">
          <button
            aria-pressed={bimWorkspace}
            className={bimWorkspace ? "active" : ""}
            onClick={() => changeWorkspace(true)}
          >
            <Box size={16} />
            BIM 모델
          </button>
          <button
            aria-pressed={!bimWorkspace}
            className={!bimWorkspace ? "active" : ""}
            onClick={() => changeWorkspace(false)}
          >
            <Navigation size={16} />
            BF 경로 탐색
          </button>
        </div>
        <div className="workspace-bar-actions">
          {(designer || Boolean(model.provenance.precision_rebuild)) && (
            <div className="project-actions">
              {designer && <>
              <button onClick={save} title="현재 브라우저에 모델 저장">
                <Save size={15} />
                <span>저장</span>
              </button>
              <button
                onClick={() =>
                  download(JSON.stringify(model, null, 2), "building.json")
                }
                title="JSON 모델 내보내기"
              >
                <Download size={15} />
                <span>JSON</span>
              </button>
              </>}
              <button
                disabled={(!api && !model.provenance.precision_rebuild) || busy}
                onClick={() => exportIFC()}
                title={model.provenance.precision_rebuild ? `근거 검증 부재 ${Number(model.provenance.verified_solids ?? 0)}개 · 미확정 부재 제외` : "IFC 생성에는 로컬 Python 서버가 필요합니다."}
              >
                <Download size={15} />
                <span>IFC</span>
              </button>
              {Boolean(model.provenance.coordination_draft) && <button disabled={busy} onClick={() => exportIFC(true)} title="미확정 입체와 가정을 포함한 검토용 IFC">
                <Download size={15} /><span>Draft IFC</span>
              </button>}
            </div>
          )}
          <button
            className={leftOpen ? "active panel-toggle" : "panel-toggle"}
            aria-controls="explorer-panel"
            aria-label="객체 탐색"
            aria-expanded={leftOpen}
            onClick={() => togglePanel("left")}
          >
            <PanelLeft size={16} />
            <span>객체 탐색</span>
          </button>
          <button
            className={rightOpen ? "active panel-toggle" : "panel-toggle"}
            aria-controls="inspector-panel"
            aria-label={bimWorkspace ? "속성 · 근거" : "경로 설정"}
            aria-expanded={rightOpen}
            onClick={() => togglePanel("right")}
          >
            <PanelRight size={16} />
            <span>{bimWorkspace ? "속성 · 근거" : "경로 설정"}</span>
          </button>
        </div>
      </nav>
      {helpOpen && (
        <>
          <button
            className="help-scrim"
            aria-label="도움말 닫기"
            onClick={() => setHelpOpen(false)}
          />
          <section className="help-popover" aria-label="사용 도움말">
            <div className="section-heading">
              <h2>모델 탐색 시작하기</h2>
              <button
                className="icon-button"
                aria-label="도움말 닫기"
                onClick={() => setHelpOpen(false)}
              >
                <X size={16} />
              </button>
            </div>
            <p>모델을 중심으로 건축 요소와 이동 경로를 검토하세요.</p>
            <dl>
              <dt>회전</dt>
              <dd>왼쪽 버튼으로 드래그 · 한 손가락 이동</dd>
              <dt>이동</dt>
              <dd>오른쪽 버튼으로 드래그 · 두 손가락 이동</dd>
              <dt>확대 / 축소</dt>
              <dd>마우스 휠 · 두 손가락 벌리기</dd>
              <dt>객체 검토</dt>
              <dd>모델이나 객체 목록에서 요소 선택</dd>
              <dt>단면 보기</dt>
              <dd>뷰어 하단의 단면 · 층 분리 도구</dd>
              <dt>경로 탐색</dt>
              <dd>BF 경로 탐색 → 출발지·목적지 → 경로 탐색</dd>
            </dl>
            <small>실내 시점에서는 WASD 이동 · Q/E 높이 조절</small>
          </section>
        </>
      )}
      {error && (
        <div className="notice error" role="alert">
          {error}
          <button aria-label="오류 닫기" onClick={() => setError("")}>
            <X size={16} />
          </button>
        </div>
      )}
      <div
        className={`workspace ${!bimWorkspace ? "route-workspace" : ""} ${leftOpen ? "left-open" : ""} ${rightOpen ? "right-open" : ""}`}
      >
        {(leftOpen || rightOpen) && (
          <button
            className="panel-scrim"
            aria-label="패널 닫기"
            onClick={() => {
              setLeftOpen(false);
              setRightOpen(false);
            }}
          />
        )}
        <aside
          className="left-panel"
          id="explorer-panel"
          aria-label="모델 탐색기"
          inert={!leftOpen}
        >
          <div className="drawer-heading">
            <strong>객체 탐색 · 검토</strong>
            <button
              aria-label="객체 패널 닫기"
              onClick={() => setLeftOpen(false)}
            >
              <X size={17} />
            </button>
          </div>
          <section className="explorer-project">
            <div className="section-label">PROJECT LIBRARY</div>
            <label className="project-select">
              <Building2 size={17} />
              <select
                aria-label="BIM 건축물"
                value={model.id}
                onChange={(e) => {
                  const m = library.find((x) => x.id === e.target.value);
                  if (m) activate(m);
                }}
              >
                {library.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}
                  </option>
                ))}
              </select>
            </label>
            <div className="project-meta">
              <span>
                {model.is_example ? "예제 · 테스트용" : "CAD · 건축 모델"}
              </span>
              <span>{model.floors.length} LEVELS</span>
            </div>
          </section>
          <section className="level-navigation" aria-label="층별 탐색">
            <div className="section-heading">
              <h2>
                <Layers size={14} />
                층별 보기
              </h2>
              <button
                className={floor === "all" ? "active all-floors" : "all-floors"}
                onClick={() => setFloor("all")}
              >
                전체
              </button>
            </div>
            <div className="level-grid">
              {[...model.floors].reverse().map((f) => (
                <button
                  key={f.id}
                  title={`${f.name} · 기준 높이 ${f.elevation.toFixed(2)} m`}
                  aria-pressed={floor === f.id}
                  className={floor === f.id ? "active" : ""}
                  onClick={() => setFloor(f.id)}
                >
                  <span>{f.name}</span>
                  <small>{f.elevation.toFixed(2)} m</small>
                </button>
              ))}
            </div>
          </section>
          <div className="tabs" role="tablist" aria-label="설계 패널">
            {(designer
              ? [
                  ["objects", "객체"],
                  ["review", "BF 검토"],
                  ["cad", "도면"],
                ]
              : [
                  ["objects", "객체"],
                  ["review", "BF 검토"],
                ]
            ).map(([id, name]) => (
              <button
                key={id}
                role="tab"
                aria-selected={tab === id}
                className={tab === id ? "active" : ""}
                onClick={() => setTab(id)}
              >
                {name}
              </button>
            ))}
          </div>
          {tab === "objects" && (
            <>
              <ObjectExplorer
                model={model}
                elements={elements}
                selected={selected}
                query={query}
                category={category}
                onQuery={setQuery}
                onCategory={setCategory}
                onSelect={selectObject}
              />
              {designer && (
                <div className="panel-bottom">
                  <button
                    onClick={() => {
                      setDraft(
                        JSON.stringify(
                          {
                            id: "manual-" + Date.now(),
                            name: "추가 요소",
                            type: "obstacle",
                            floor_id:
                              floor === "all" ? model.floors[0].id : floor,
                            polygon: [
                              [1, 1],
                              [2, 1],
                              [2, 2],
                              [1, 2],
                            ],
                            height: 1,
                            verified: false,
                            properties: {},
                            source: { origin: "manual" },
                          },
                          null,
                          2,
                        ),
                      );
                      openEditor("add");
                    }}
                  >
                    + 요소 추가
                  </button>
                  <button
                    onClick={() => {
                      setDraft(JSON.stringify(model, null, 2));
                      openEditor("model");
                    }}
                  >
                    층 · 공간 · 연결 편집
                  </button>
                </div>
              )}{" "}
            </>
          )}
          {tab === "review" && (
            <>
              <div className="panel-heading">
                <h2>
                  <ShieldCheck size={17} /> 이동 조건 검토
                </h2>
              </div>
              <div className="review-summary">
                <div>
                  <strong>{counts.blocked}</strong>
                  <span>통과 불가능</span>
                </div>
                <div>
                  <strong>{counts.unknown}</strong>
                  <span>추가 확인 필요</span>
                </div>
              </div>
              <p className="muted padded">
                현재 사용자 정의 조건을 적용합니다. 공식 BF 인증 판정이
                아닙니다.
              </p>
              <div className="object-list">
                {review.map((r) => (
                  <button
                    className="review-row"
                    key={r.id}
                    onClick={() => selectObject(r.id)}
                  >
                    <strong>{r.e.name}</strong>
                    <span className={"status " + r.status}>
                      {statusLabel[r.status]}
                    </span>
                    <small>{r.reasons.join(" · ")}</small>
                  </button>
                ))}
              </div>
              <details className="padded">
                <summary>적용 기준 및 근거</summary>
                <p>{rules.source_document}</p>
                <p>적용일: {rules.effective_date} / 검증 상태: 사용자 정의</p>
                <a href={rules.reference_url} target="_blank" rel="noreferrer">
                  BF 해설서 참고 자료 <ArrowUpRight size={12} />
                </a>
                <p>해설서의 개별 수치·적용 조항 검증은 완료되지 않았습니다.</p>
                <button
                  onClick={() =>
                    download(
                      JSON.stringify(
                        { ...rules, profiles: { current: profile } },
                        null,
                        2,
                      ),
                      "mobility-rules.json",
                    )
                  }
                >
                  검토 조건 내보내기
                </button>
              </details>
            </>
          )}
          {designer && tab === "cad" && (
            <div className="cad-panel">
              <h2>
                <FileUp size={18} /> 도면 관리
              </h2>
              <label className={`upload-box ${!api ? "disabled" : ""}`}>
                <Upload size={25} />
                <strong>DWG / DXF 불러오기</strong>
                <span>원본을 보존하고 복사본을 분석합니다</span>
                <input
                  aria-label="CAD 도면 파일"
                  type="file"
                  accept=".dwg,.dxf"
                  disabled={!api || busy}
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) uploadCAD(f);
                    e.target.value = "";
                  }}
                />
              </label>
              <p className="muted">
                {api
                  ? `로컬 처리 서버 연결됨 · ODA ${oda ? "확인됨" : "미설치: DXF 사용 가능"}`
                  : "CAD 분석과 IFC 출력에는 로컬 Python 서버가 필요합니다."}
              </p>
              <label className="file-button">
                JSON 모델 불러오기
                <input
                  type="file"
                  accept=".json"
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) importJSON(f);
                    e.target.value = "";
                  }}
                />
              </label>
              {cad && (
                <>
                  <h3>레이어 대응</h3>
                  <p className="muted">
                    {cad.entity_count.toLocaleString()}개 객체 ·{" "}
                    {cad.units.name}
                  </p>
                  <div className="layer-list">
                    {cad.layers
                      .filter((l) => l.count > 0)
                      .map((l) => (
                        <label key={l.name}>
                          <span>
                            {l.name}
                            <small>{l.count}개</small>
                          </span>
                          <select
                            value={mapping[l.name]}
                            onChange={(e) =>
                              setMapping({
                                ...mapping,
                                [l.name]: e.target.value,
                              })
                            }
                          >
                            {[...kinds, "ignore"].map((k) => (
                              <option key={k} value={k}>
                                {labels[k] || "제외"}
                              </option>
                            ))}
                          </select>
                        </label>
                      ))}
                  </div>
                  <label>
                    도면 1단위 → m
                    <input
                      type="number"
                      step="any"
                      value={scale}
                      onChange={(e) => setScale(e.target.value)}
                    />
                  </label>
                  <label>
                    모델링 층고 가정 (m)
                    <input
                      type="number"
                      step=".1"
                      value={height}
                      onChange={(e) => setHeight(e.target.value)}
                    />
                  </label>
                  <label>
                    선 벽체 두께 가정 (m)
                    <input
                      type="number"
                      step=".01"
                      value={thickness}
                      onChange={(e) => setThickness(e.target.value)}
                    />
                  </label>
                  <button
                    className="primary full"
                    disabled={busy}
                    onClick={buildCAD}
                  >
                    BIM 모델 생성 <ArrowRight size={15} />
                  </button>
                  <a href={`/api/cad/${cad.token}/report`} download>
                    CAD 원시 분석 JSON
                  </a>
                  <details>
                    <summary>분석 경고 {cad.warnings.length}건</summary>
                    {cad.warnings.slice(0, 30).map((w, i) => (
                      <p key={i}>
                        {w.code}: {w.message}
                      </p>
                    ))}
                  </details>
                </>
              )}
            </div>
          )}
          <div className="explorer-footer">
            <span>
              <i className="connection-dot" />
              모델 로드 완료
            </span>
            <span>{model.elements.length.toLocaleString()} 객체</span>
          </div>
        </aside>
        <main className="model-panel" aria-label="모델 작업 화면">
          <div className="model-toolbar">
            <div className="canvas-title">
              <span className="canvas-indicator" />
              <strong>{bimWorkspace ? "모델 검토" : "이동 경로"}</strong>
              <span className="canvas-title-separator">/</span>
              <span>
                {floor === "all"
                  ? "전체 건물"
                  : model.floors.find((f) => f.id === floor)?.name}
              </span>
            </div>
            <div className="view-buttons">
              <button
                aria-pressed={!plan}
                className={!plan ? "active" : ""}
                onClick={() => {
                  setPlan(false);
                }}
              >
                <Rotate3D size={15} /> 3D
              </button>
              <button
                aria-pressed={plan}
                className={plan ? "active" : ""}
                onClick={() => {
                  setPlan(true);
                }}
              >
                <Square size={15} /> 평면
              </button>
            </div>
            <label className="floor-selector">
              <Layers size={15} />
              <select
                aria-label="표시 층"
                value={floor}
                onChange={(e) => setFloor(e.target.value)}
              >
                <option value="all">전체 층</option>
                {model.floors.map((f) => (
                  <option key={f.id} value={f.id}>
                    {f.name}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <Viewer
              model={model}
              floor={floor}
              plan={plan}
              selected={selected}
              route={bimWorkspace ? null : route}
              profile={profile}
              onSelect={selectObject}
          />
          <div className="canvas-footer">
            <div className="model-hint">
              <Move size={13} />
              {plan
                ? "드래그: 이동 · 스크롤: 확대/축소"
                : "드래그: 회전 · 우클릭: 이동 · 스크롤: 확대/축소"}
            </div>
            <div className="legend">
              {bimWorkspace ? (
                <>
                  <span>
                    <i style={{ background: "#cbd1cc" }} />
                    벽체
                  </span>
                  <span>
                    <i style={{ background: "#75838b" }} />
                    구조
                  </span>
                  <span>
                    <i style={{ background: "#7fc6df" }} />
                    창호
                  </span>
                  <span>
                    <i style={{ background: "#976f46" }} />문
                  </span>
                  <span>
                    <i className="unknown" />
                    미확정 면
                  </span>
                </>
              ) : (
                <>
                  <span>
                    <i className="pass" />
                    통과 가능
                  </span>
                  <span>
                    <i className="blocked" />
                    통과 불가능
                  </span>
                  <span>
                    <i className="unknown" />
                    확인 필요
                  </span>
                  <span>
                    <i className="route" />
                    이동 경로
                  </span>
                </>
              )}
            </div>
            <div className="model-caption">
              <span>
                {model.is_example ? "SYNTHETIC MODEL" : "CAD-DERIVED MODEL"} /
                REV {model.revision.toString().padStart(2, "0")}
              </span>
              <span>
                {bimWorkspace
                  ? "CAD 출처 · 재구성 후보 구분"
                  : "기하학·입력 조건 기반 검토"}
              </span>
            </div>
          </div>
        </main>
        <div
          className="inspector-shell"
          id="inspector-panel"
          inert={!rightOpen}
        >
          <div className="drawer-heading">
            <strong>
              {bimWorkspace ? "속성 · 도면 근거" : "BF 경로 설정"}
            </strong>
            <button
              aria-label="속성 패널 닫기"
              onClick={() => setRightOpen(false)}
            >
              <X size={17} />
            </button>
          </div>
          {bimWorkspace ? (
            <BimInspector
              model={model}
              library={library}
              item={item}
              floor={floor}
              onActivate={activate}
              onFloor={setFloor}
              onSelect={selectObject}
              onEdit={designer ? editElement : undefined}
            />
          ) : (
            <aside className="right-panel" id="navigation">
              <div className="navigation-title">
                <span className="mini-icon">
                  <Navigation size={18} />
                </span>
                <div>
                  <h2>접근 가능한 길찾기</h2>
                  <p>나의 이동 조건에 맞는 경로</p>
                </div>
              </div>
              {!designer && (
                <label className="file-button">
                  JSON
                  <input
                    type="file"
                    accept=".json"
                    aria-label="JSON model import"
                    onChange={(e) => {
                      const f = e.target.files?.[0];
                      if (f) importJSON(f);
                      e.target.value = "";
                    }}
                  />
                </label>
              )}
              <div className="destination-fields">
                <label className="field">
                  <span>
                    <i className="start-dot" />
                    출발지
                  </span>
                  <select
                    aria-label="출발지"
                    value={start}
                    onChange={(e) => setStart(e.target.value)}
                  >
                    <option value="">출발지 선택</option>
                    {model.places.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="field">
                  <span>
                    <MapPin size={13} />
                    목적지
                  </span>
                  <select
                    aria-label="목적지"
                    value={end}
                    onChange={(e) => setEnd(e.target.value)}
                  >
                    <option value="">목적지 선택</option>
                    {model.places.map((p) => (
                      <option key={p.id} value={p.id}>
                        {p.name}
                      </option>
                    ))}
                  </select>
                </label>
                <button
                  className="swap-destinations icon-button"
                  aria-label="출발지와 목적지 바꾸기"
                  title="출발지와 목적지 바꾸기"
                  onClick={() => {
                    setStart(end);
                    setEnd(start);
                  }}
                >
                  <ArrowLeftRight size={14} />
                </button>
              </div>
              <label className="field">
                이용자 유형
                <select
                  aria-label="이용자 유형"
                  value={profileKey}
                  onChange={(e) => {
                    setProfileKey(e.target.value);
                    setProfile({ ...rules.profiles[e.target.value] });
                  }}
                >
                  {Object.entries(rules.profiles).map(([key, p]) => (
                    <option key={key} value={key}>
                      {p.name}
                    </option>
                  ))}
                </select>
              </label>
              <button
                className="conditions-toggle"
                onClick={() => setShowConditions(!showConditions)}
                aria-expanded={showConditions}
              >
                <Settings2 size={15} /> 세부 이동 조건
                <ChevronRight size={14} />
              </button>
              {showConditions && (
                <div className="conditions">
                  {(
                    [
                      ["body_width", "이동 몸체 폭 (m)"],
                      ["min_door_width", "최소 문 유효폭 (m)"],
                      ["min_corridor_width", "통로 여유폭 (m)"],
                      ["max_step", "최대 단차 (m)"],
                      ["max_slope", "최대 경사 (m/m)"],
                      ["speed", "이동속도 (m/s)"],
                      ["elevator_wait", "승강기 대기 (초)"],
                    ] as const
                  ).map(([key, label]) => (
                    <label key={key}>
                      {label}
                      <input
                        type="number"
                        step=".01"
                        value={profile[key]}
                        onChange={(e) => {
                          const v = Number(e.target.value);
                          if (Number.isFinite(v))
                            setProfile({ ...profile, [key]: v });
                        }}
                      />
                    </label>
                  ))}
                  <label className="check-label">
                    <input
                      type="checkbox"
                      checked={profile.allow_stairs}
                      onChange={(e) =>
                        setProfile({
                          ...profile,
                          allow_stairs: e.target.checked,
                        })
                      }
                    />
                    계단 이용 허용
                  </label>
                </div>
              )}
              <button
                className="primary route-button"
                disabled={busy || !start || !end}
                onClick={runRoute}
              >
                {busy ? "처리 중…" : "경로 탐색"}
                <ArrowRight size={17} />
              </button>
              <p className="route-note">
                미확인 구간은 이동 가능한 것으로 가정하지 않습니다.
              </p>
              {!bimWorkspace && (
                <section className="results" aria-live="polite">
                  <div className="results-heading">
                    <h2>
                      <Navigation size={17} /> 경로 분석 결과
                    </h2>
                    <span>
                      {route?.status === "found" ? (
                        <span className="status pass">
                          <Check size={12} />
                          조건 충족 경로
                        </span>
                      ) : route?.status === "no_path" ? (
                        <span className="status blocked">경로 없음</span>
                      ) : (
                        <span className="muted">경로를 탐색해 주세요</span>
                      )}
                    </span>
                  </div>
                  {route ? (
                    <>
                      <div className="result-metrics">
                        <div>
                          <span>총 이동 거리</span>
                          <strong>
                            {route.distance.toFixed(1)}
                            <small> m</small>
                          </strong>
                        </div>
                        <div>
                          <span>예상 이동 시간</span>
                          <strong>
                            {Math.ceil(route.seconds)}
                            <small> 초</small>
                          </strong>
                        </div>
                        <div>
                          <span>이동 층</span>
                          <strong>
                            {route.floors
                              .map(
                                (id) =>
                                  model.floors.find((f) => f.id === id)?.name,
                              )
                              .join(" → ") || "—"}
                          </strong>
                        </div>
                        <div>
                          <span>층간 이동</span>
                          <strong>
                            {route.uses_elevator
                              ? "승강기"
                              : route.floors.length > 1
                                ? "계단 / 경사로"
                                : "없음"}
                          </strong>
                        </div>
                      </div>
                      <ol className="directions">
                        {route.instructions.map((s, i) => (
                          <li key={i}>{s}</li>
                        ))}
                      </ol>
                      <p className="muted">
                        {route.assumptions} · 격자 0.25 m ·{" "}
                        {route.node_count.toLocaleString()}개 노드
                      </p>
                      {route.excluded.length > 0 && (
                        <details>
                          <summary>
                            모델에서 제외 또는 확인이 필요한 요소{" "}
                            {route.excluded.length}개
                          </summary>
                          {route.excluded.map((r) => (
                            <p key={r.id}>
                              <button
                                className="text-button"
                                onClick={() => {
                                  setSelected(r.id);
                                  setTab("review");
                                  setLeftOpen(true);
                                  if (window.innerWidth <= 1100)
                                    setRightOpen(false);
                                }}
                              >
                                {
                                  model.elements.find((e) => e.id === r.id)
                                    ?.name
                                }
                              </button>
                              : {statusLabel[r.status]} — {r.reasons.join(", ")}
                            </p>
                          ))}
                        </details>
                      )}
                    </>
                  ) : (
                    <p className="empty-result">
                      출발지와 목적지, 이동 조건을 선택하면 벽체와 장애물을 피해
                      이동할 수 있는 경로를 계산합니다.
                    </p>
                  )}
                </section>
              )}
              {designer && (
                <section className="property-panel">
                  <div className="section-heading">
                    <h2>객체 속성</h2>
                    <span>INSPECTOR</span>
                  </div>
                  {item ? (
                    <>
                      <strong className="selected-name">{item.name}</strong>
                      <p className="muted">
                        {labels[item.type]} · {item.id}
                      </p>
                      <span
                        className={"status " + evaluate(item, profile).status}
                      >
                        {statusLabel[evaluate(item, profile).status]}
                      </span>
                      <ul className="reasons">
                        {evaluate(item, profile).reasons.map((s) => (
                          <li key={s}>{s}</li>
                        ))}
                      </ul>
                      {[
                        "door",
                        "ramp",
                        "elevator",
                        "stair",
                        "floor",
                        "corridor",
                      ].includes(item.type) && (
                        <div className="property-fields">
                          {(item.type === "floor"
                            ? ["step"]
                            : item.type === "ramp"
                              ? ["clear_width", "step", "slope"]
                              : ["clear_width", "step"]
                          ).map((key) => (
                            <label key={key}>
                              {key === "clear_width"
                                ? "유효폭 (m)"
                                : key === "step"
                                  ? "단차 (m)"
                                  : "경사 (m/m)"}
                              <input
                                type="number"
                                aria-label={`객체 ${key}`}
                                step=".01"
                                value={
                                  item.properties[
                                    key as keyof Element["properties"]
                                  ] === null
                                    ? ""
                                    : String(
                                        item.properties[
                                          key as keyof Element["properties"]
                                        ],
                                      )
                                }
                                placeholder="미확인"
                                onChange={(e) =>
                                  quick(
                                    key as keyof Element["properties"],
                                    e.target.value === ""
                                      ? null
                                      : Number(e.target.value),
                                  )
                                }
                              />
                            </label>
                          ))}
                          {item.type === "elevator" && (
                            <label>
                              가동 상태
                              <select
                                value={
                                  item.properties.operational === null
                                    ? "unknown"
                                    : String(item.properties.operational)
                                }
                                onChange={(e) =>
                                  quick(
                                    "operational",
                                    e.target.value === "unknown"
                                      ? null
                                      : e.target.value === "true",
                                  )
                                }
                              >
                                <option value="unknown">미확인</option>
                                <option value="true">이용 가능</option>
                                <option value="false">이용 불가</option>
                              </select>
                            </label>
                          )}
                        </div>
                      )}
                      <label className="check-label">
                        <input
                          type="checkbox"
                          checked={item.verified}
                          onChange={(e) =>
                            update({
                              ...model,
                              elements: model.elements.map((x) =>
                                x.id === item.id
                                  ? {
                                      ...x,
                                      verified: e.target.checked,
                                      source: {
                                        ...x.source,
                                        origin: "user_edit",
                                        original_polygon:
                                          x.source.original_polygon ||
                                          x.polygon,
                                      },
                                    }
                                  : x,
                              ),
                            })
                          }
                        />
                        기하학·입력 속성을 확인했습니다
                      </label>
                      <button
                        className="full"
                        onClick={() => editElement(item)}
                      >
                        위치 · 형상 · 분류 편집
                      </button>
                      <button
                        className="text-button"
                        onClick={() =>
                          update({
                            ...model,
                            elements: model.elements.map((x) =>
                              x.id === item.id
                                ? { ...x, excluded: !x.excluded }
                                : x,
                            ),
                          })
                        }
                      >
                        {item.excluded ? "요소 다시 포함" : "요소 제외"}
                      </button>
                      <details>
                        <summary>원본 CAD 정보</summary>
                        <pre>{JSON.stringify(item.source, null, 2)}</pre>
                      </details>
                    </>
                  ) : (
                    <div className="empty-property">
                      <Box size={28} />
                      <p>
                        모델 또는 객체 목록에서
                        <br />
                        검토할 요소를 선택하세요.
                      </p>
                    </div>
                  )}
                </section>
              )}
            </aside>
          )}
        </div>
      </div>

      <footer className="status-bar">
        <span>
          <span className="connection-dot" />
          공간이음<span className="status-divider">/</span>
          {bimWorkspace ? "BIM MODEL REVIEW" : "BF NAVIGATION"}
        </span>
        <div>
          {model.warnings.length > 0 && (
            <details className="warnings">
              <summary>
                <TriangleAlert size={12} />
                모델 검토 {model.warnings.length}건
              </summary>
              <div className="warnings-content">
                <h2>모델 분석 주의사항</h2>
                {model.warnings.slice(0, 80).map((w, i) => (
                  <p key={i}>{w}</p>
                ))}
              </div>
            </details>
          )}
          <span className="footer-disclaimer">
            {model.is_example
              ? "테스트용 예제"
              : "도면 기반 · 미확정 치수 포함"}{" "}
            · BF 인증 판정과 별도
          </span>
          <span className="status-unit">m</span>
        </div>
      </footer>
      <div className={`toast ${message ? "visible" : ""}`} role="status">
        {message && <CheckCircle2 size={16} />} {message}
      </div>
      {editor && (
        <div className="modal-backdrop">
          <div
            className="modal"
            ref={modalRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby="editor-title"
          >
            <div>
              <h2 id="editor-title">
                {editor === "model"
                  ? "층 · 장소 · 층간 연결 편집"
                  : editor === "add"
                    ? "건축 요소 추가"
                    : "객체 상세 편집"}
              </h2>
              <button aria-label="편집창 닫기" onClick={() => setEditor(null)}>
                <X size={18} />
              </button>
            </div>
            <p>
              좌표·치수는 m입니다. polygon은 XY 점 목록, floor.elevation은 층
              기준 높이입니다. verified는 현장 또는 도면 확인 후 설정하세요.
            </p>
            <textarea
              aria-label="모델 JSON 편집"
              spellCheck={false}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              autoFocus
            />
            <div className="modal-actions">
              <button onClick={() => setEditor(null)}>취소</button>
              <button className="primary" onClick={commitEditor}>
                검증 후 적용
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
