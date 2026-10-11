import { useEffect, useRef, useState } from "react";
import * as T from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";
import type { Model, XY, Profile } from "./model";
import { bounds, raw } from "./geometry";
import type { RouteResult } from "./navigation";
import { renderPieces, floorOffset, createRenderContext } from "./bimGeometry";
import { pieceGeometry, sectionCap, wallEdges } from "./architecturalGeometry";
import { interiorView } from "./interiorView";
import {
  batchElementMeshes,
  batchEdges,
  pickedComponent,
} from "./renderBatching";
import {
  Focus,
  Maximize,
  PersonStanding,
  Settings2,
  Scissors,
  Layers,
  TriangleAlert,
  EyeOff,
  Eye,
  Rotate3D,
  ArrowUp,
} from "lucide-react";
interface Props {
  model: Model;
  floor: string;
  plan: boolean;
  selected: string;
  route: RouteResult | null;
  profile: Profile;
  onSelect: (id: string) => void;
}
const colors: Record<string, number> = {
  wall: 0xcbd1cc,
  column: 0x75838b,
  beam: 0x68737e,
  floor: 0xe4dfd3,
  roof: 0xb2bbc0,
  door: 0x976f46,
  window: 0x7fc6df,
  opening: 0xd69e50,
  space: 0x91bfb0,
  corridor: 0xa9c2d9,
  ramp: 0x96b7a2,
  stair: 0xb0aaa0,
  elevator: 0x8a9aac,
  obstacle: 0x7f8b94,
  unclassified: 0xd2b77c,
};
type CameraAPI = {
  fit: () => void;
  focus: (id: string) => void;
  interior: () => void;
};
export default function Viewer({
  model,
  floor,
  plan,
  selected,
  route,
  onSelect,
}: Props) {
  const host = useRef<HTMLDivElement>(null),
    selectRef = useRef(onSelect),
    selectedRef = useRef(selected),
    apiRef = useRef<CameraAPI | null>(null);
  selectRef.current = onSelect;
  selectedRef.current = selected;
  const meshesRef = useRef<T.Mesh[]>([]),
    [fallback, setFallback] = useState(false);
  const needsRender = useRef(true);
  const [hideWalls, setHideWalls] = useState(false),
    [showSpaces, setShowSpaces] = useState(false),
    [showLabels, setShowLabels] = useState(false),
    [showMarkers, setShowMarkers] = useState(Boolean(model.provenance.precision_rebuild)),
    [hideRoof, setHideRoof] = useState(false),
    [assumptions, setAssumptions] = useState(true),
    [separation, setSeparation] = useState(0),
    [section, setSection] = useState("none"),
    [cut, setCut] = useState(50),
    [walking, setWalking] = useState(false);
  const cameraState = useRef<{
    key: string;
    position: T.Vector3;
    target: T.Vector3;
  } | null>(null);
  const [tool, setTool] = useState<"display" | "section" | null>(null);
  const [transparentEnvelope, setTransparentEnvelope] = useState(false),
    [isolated, setIsolated] = useState(false),
    [doorOpen, setDoorOpen] = useState(0),
    [viewDirection, setViewDirection] = useState("building");
  const [pickedPart, setPickedPart] = useState("");
  const [evidenceMode, setEvidenceMode] = useState("full");
  const [showGround, setShowGround] = useState(true);
  const [hiddenIds, setHiddenIds] = useState<string[]>([]);
  useEffect(() => setHiddenIds([]), [model.id]);
  useEffect(() => setShowMarkers(Boolean(model.provenance.precision_rebuild)), [model.id]);
  const isolationKey = isolated ? selected : "";
  const toolsHost = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!tool) return;
    const close = (e: PointerEvent) => {
      if (!toolsHost.current?.contains(e.target as Node)) setTool(null);
    };
    const escape = (e: KeyboardEvent) => {
      if (e.key === "Escape") setTool(null);
    };
    document.addEventListener("pointerdown", close);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", close);
      document.removeEventListener("keydown", escape);
    };
  }, [tool]);
  useEffect(() => {
    setWalking(false);
    setPickedPart("");
    setIsolated(false);
    cameraState.current = null;
  }, [model.id, floor, plan]);
  useEffect(() => {
    const container = host.current;
    if (!container) return;
    needsRender.current = true;
    let renderer: T.WebGLRenderer;
    try {
      renderer = new T.WebGLRenderer({ antialias: true });
      setFallback(false);
    } catch {
      setFallback(true);
      return;
    }
    const scene = new T.Scene();
    scene.background = new T.Color(0xf2f3f2);
    const camera = new T.PerspectiveCamera(
      42,
      container.clientWidth / Math.max(container.clientHeight, 1),
      0.025,
      2000,
    );
    camera.rotation.order = "YXZ";
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.outputColorSpace = T.SRGBColorSpace;
    renderer.toneMapping = T.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1;
    renderer.localClippingEnabled = true;
    renderer.shadowMap.enabled = !plan;
    renderer.shadowMap.type = T.PCFSoftShadowMap;
    renderer.shadowMap.autoUpdate = false;
    renderer.shadowMap.needsUpdate = true;
    container.append(renderer.domElement);
    renderer.domElement.tabIndex = 0;
    renderer.domElement.setAttribute("aria-label", "BIM 3D 탐색 화면");
    renderer.domElement.dataset.walking = String(walking);
    renderer.domElement.dataset.modelRevision = String(model.revision);
    renderer.domElement.dataset.modellingVersion = String(
      model.provenance.modelling_version ?? 0,
    );
    renderer.domElement.dataset.modelComponents = String(
      model.elements.reduce((n, e) => n + e.components.length, 0),
    );
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.enableRotate = !plan;
    controls.maxPolarAngle = Math.PI * 0.94;
    controls.minDistance = 0.25;
    const visible = model.elements.filter(
      (e) =>
        !e.excluded &&
        (!e.source.unresolved_plan_only || evidenceMode === "drawing") &&
        (evidenceMode !== "verified" || (e.source.validation_status === "verified" && (e.source.verification as {eligible?:boolean}|undefined)?.eligible === true)) &&
        (evidenceMode !== "drawing" || e.source.geometry_status === "measured_plan" || Boolean(e.source.precision_member_id)) &&
        !hiddenIds.includes(e.id) &&
        (floor === "all" || e.floor_id === floor) &&
        (!isolationKey || e.id === isolationKey),
    );
    const renderContext = createRenderContext(model);
    const piecesByElement = new Map(
      visible.map((e) => [
        e.id,
        renderPieces(e, model, assumptions && evidenceMode !== "drawing", doorOpen / 100, renderContext),
      ]),
    );
    const nativeTraces = model.provenance.cad_traces as {floor_id:string;kind:string;points:XY[]}[] | undefined;
    renderer.domElement.dataset.evidenceMode = evidenceMode;
    renderer.domElement.dataset.displayedElements = String(visible.length);
    const visibleTraces = (nativeTraces ?? []).filter(t => evidenceMode !== "verified" &&
      (!model.provenance.coordination_draft || evidenceMode === "drawing") && (floor === "all" || t.floor_id === floor) && !isolationKey);
    const extent = visible.length || visibleTraces.length
      ? bounds([...visible.map(raw), ...visibleTraces.map(t => [t.points])])
      : { min: [0, 0] as XY, max: [20, 12] as XY };
    const cx = (extent.min[0] + extent.max[0]) / 2,
      cy = (extent.min[1] + extent.max[1]) / 2,
      size = Math.max(
        extent.max[0] - extent.min[0],
        extent.max[1] - extent.min[1],
        5,
      );
    const base =
      model.floors.find((f) => f.id === floor)?.elevation ??
      Math.min(...model.floors.map((f) => f.elevation));
    const top = Math.max(
      ...model.floors
        .filter((f) => floor === "all" || f.id === floor)
        .map((f) => f.elevation + floorOffset(model, f.id, separation) + 5),
      5,
    );
    const actualZ = visible.flatMap((e) => {
      const z =
        model.floors.find((f) => f.id === e.floor_id)!.elevation +
        floorOffset(model, e.floor_id, separation);
      return piecesByElement
        .get(e.id)!
        .flatMap((p) => [z + p.z, z + p.z + (p.height ?? 0)]);
    });
    const cutBase = actualZ.length ? Math.min(...actualZ) : base,
      cutTop = actualZ.length ? Math.max(...actualZ) : top;
    const planes: T.Plane[] = [];
    if (section === "x")
      planes.push(
        new T.Plane(
          new T.Vector3(-1, 0, 0),
          extent.min[0] + ((extent.max[0] - extent.min[0]) * cut) / 100,
        ),
      );
    if (section === "y")
      planes.push(
        new T.Plane(
          new T.Vector3(0, 0, -1),
          extent.min[1] + ((extent.max[1] - extent.min[1]) * cut) / 100,
        ),
      );
    if (section === "z")
      planes.push(
        new T.Plane(
          new T.Vector3(0, -1, 0),
          cutBase + ((cutTop - cutBase) * cut) / 100,
        ),
      );
    let renderedBounds: T.Box3 | null = null;
    let fitMeshes: (T.Mesh | T.LineSegments)[] = [];
    const fit = () => {
      const box =
        renderedBounds ??
        new T.Box3(
          new T.Vector3(extent.min[0], base, extent.min[1]),
          new T.Vector3(extent.max[0], top, extent.max[1]),
        );
      const directions: Record<string, T.Vector3> = {
        building: new T.Vector3(0.8, 0.45, -0.85),
        iso: new T.Vector3(0.62, 0.65, 0.78),
        front: new T.Vector3(0, 0.08, 1),
        back: new T.Vector3(0, 0.08, -1),
        left: new T.Vector3(-1, 0.08, 0),
        right: new T.Vector3(1, 0.08, 0),
        top: new T.Vector3(0, 1, 0.001),
      };
      const center = box.getCenter(new T.Vector3()),
        direction = (plan ? directions.top : directions[viewDirection])
          .clone()
          .normalize();
      const right = new T.Vector3()
          .crossVectors(camera.up, direction)
          .normalize(),
        up = new T.Vector3().crossVectors(direction, right),
        tan = Math.tan(T.MathUtils.degToRad(camera.fov / 2));
      let distance = 3;
      // Fit the actual rotated building, rather than empty corners of its global
      // axis-aligned box, which made the diagonal footprint appear tiny.
      const point = new T.Vector3();
      let minRight = Infinity,
        maxRight = -Infinity,
        minUp = Infinity,
        maxUp = -Infinity;
      for (const mesh of fitMeshes) {
        mesh.updateMatrixWorld();
        const positions = mesh.geometry.getAttribute("position");
        for (let i = 0; i < positions.count; i++) {
          point
            .fromBufferAttribute(positions, i)
            .applyMatrix4(mesh.matrixWorld)
            .sub(center);
          const r = point.dot(right),
            u = point.dot(up);
          minRight = Math.min(minRight, r);
          maxRight = Math.max(maxRight, r);
          minUp = Math.min(minUp, u);
          maxUp = Math.max(maxUp, u);
        }
      }
      // Center the visible silhouette rather than the empty corners of the
      // world-space box. This is especially noticeable in portrait viewports.
      if (Number.isFinite(minRight)) {
        center.addScaledVector(right, (minRight + maxRight) / 2);
        center.addScaledVector(up, (minUp + maxUp) / 2);
      }
      for (const mesh of fitMeshes) {
        mesh.updateMatrixWorld();
        const positions = mesh.geometry.getAttribute("position");
        for (let i = 0; i < positions.count; i++) {
          point
            .fromBufferAttribute(positions, i)
            .applyMatrix4(mesh.matrixWorld)
            .sub(center);
          const depth = point.dot(direction);
          distance = Math.max(
            distance,
            Math.abs(point.dot(right)) / (tan * Math.max(camera.aspect, 0.1)) +
              depth,
            Math.abs(point.dot(up)) / tan + depth,
          );
        }
      }
      controls.target.copy(center);
      camera.position.copy(center).addScaledVector(direction, distance * 1.08);
      controls.update();
      needsRender.current = true;
    };
    const key =
        model.id + floor + plan + viewDirection + isolationKey + separation,
      saved = cameraState.current;
    if (saved?.key === key) {
      camera.position.copy(saved.position);
      controls.target.copy(saved.target);
      controls.update();
    }
    controls.enabled = !walking;
    const pmrem = new T.PMREMGenerator(renderer),
      room = new RoomEnvironment(),
      environment = pmrem.fromScene(room, 0.04);
    scene.environment = environment.texture;
    scene.environmentIntensity = 0.45;
    room.dispose();
    pmrem.dispose();
    scene.add(new T.HemisphereLight(0xfafcff, 0x7f898e, 0.8));
    const light = new T.DirectionalLight(0xfff4e5, 2.2);
    light.position.set(cx + size * 0.5, top + size * 0.7, cy + size * 0.3);
    scene.add(light);
    light.castShadow = true;
    light.shadow.mapSize.set(2048, 2048);
    light.shadow.camera.left = -size;
    light.shadow.camera.right = size;
    light.shadow.camera.top = size;
    light.shadow.camera.bottom = -size;
    light.shadow.camera.far = Math.max(250, size * 4);
    light.shadow.normalBias = 0.012;
    light.shadow.bias = -0.00005;
    light.target.position.set(cx, base, cy);
    scene.add(light.target);
    const fill = new T.DirectionalLight(0xd8e7fc, 0.65);
    fill.position.set(cx - 30, top + 10, cy - 15);
    scene.add(fill);
    const grade =
      showGround && floor === "all" && !isolationKey && !separation
        ? (model.floors.find((f) => f.id === "f1")?.elevation ?? base) - 0.24
        : base - 0.28;
    const grid = new T.GridHelper(
      Math.max(30, Math.ceil(size * 1.4)),
      Math.min(100, Math.ceil(size * 1.4)),
      0xc7d1d7,
      0xd4dde2,
    );
    grid.position.set(cx, grade + 0.005, cy);
    (grid.material as T.Material).transparent = true;
    (grid.material as T.Material).opacity = 0.2;
    scene.add(grid);
    if (!plan) {
      const mat = showGround
        ? new T.MeshStandardMaterial({
            color: 0xe8e9e5,
            roughness: 1,
            clippingPlanes: planes,
            side: T.DoubleSide,
          })
        : new T.ShadowMaterial({ opacity: 0.2 });
      const ground = new T.Mesh(new T.PlaneGeometry(size * 3, size * 3), mat);
      ground.rotation.x = -Math.PI / 2;
      ground.position.set(cx, grade, cy);
      ground.receiveShadow = true;
      scene.add(ground);
    }
    let selectable: T.Mesh[] = [];
    const edgeObjects: T.LineSegments[] = [];
    const traces = visibleTraces;
    const traceGroups = new Map<string,number[]>();
    for (const t of traces ?? []) {
      if ((floor !== "all" && t.floor_id !== floor) || isolationKey ||
          (hideWalls && ["wall","finish"].includes(t.kind)) || (hideRoof && t.kind === "roof_trace")) continue;
      const elevation = (model.floors.find(f => f.id === t.floor_id)?.elevation ?? 0) + floorOffset(model,t.floor_id,separation) + .003;
      const positions = traceGroups.get(t.kind) ?? [];
      for (let i=1;i<t.points.length;i++) {
        const a=t.points[i-1],b=t.points[i];
        positions.push(a[0],elevation,a[1],b[0],elevation,b[1]);
      }
      traceGroups.set(t.kind,positions);
    }
    for (const [kind,positions] of traceGroups) {
      const geometry = new T.BufferGeometry();
      geometry.setAttribute("position",new T.Float32BufferAttribute(positions,3));
      const lines = new T.LineSegments(geometry,new T.LineBasicMaterial({color:kind === "door" ? 0x94662d : kind === "window" ? 0x1485af : kind === "stair" ? 0x8d567b : 0x657783,clippingPlanes:planes}));
      scene.add(lines);edgeObjects.push(lines);
    }
    renderer.domElement.dataset.nativeTraceSegments = String([...traceGroups.values()].reduce((n,v)=>n+v.length/6,0));
    for (const e of visible) {
      const marker = Boolean(e.source.marker_width_m),
        space = ["space", "corridor"].includes(e.type);
      if (
        (marker && !showMarkers) ||
        (hideWalls && e.type === "wall") ||
        (hideRoof && e.type === "roof") ||
        (space && !showSpaces) ||
        (e.type === "opening" && !showMarkers)
      )
        continue;
      const elevation =
        model.floors.find((f) => f.id === e.floor_id)!.elevation +
        floorOffset(model, e.floor_id, separation);
      for (const piece of piecesByElement.get(e.id)!) {
        const portal =
          e.type === "door" &&
          !e.components.length &&
          Array.isArray(e.source.hinge);
        const flat =
          piece.height === null || space || e.type === "opening" || portal;
        const geo = pieceGeometry(piece, flat || plan);
        const material = piece.material ?? String(e.source.material ?? ""),
          glass = material === "glazing",
          metal = material === "metal";
        const lower = ["b1", "f1", "f2"].includes(e.floor_id),
          exterior =
            e.source.envelope_role === "exterior_candidate" ||
            e.source.material === "finish";
        const infill = Boolean(
          piece.role &&
            [
              "sill_infill",
              "head_infill",
              "window_reveal",
              "depth_reveal",
            ].includes(piece.role),
        );
        const color = evidenceMode === "highlight"
          ? e.source.validation_status === "verified" ? 0x36aa80 : e.source.validation_status === "unresolved" ? 0xcd6666 : 0xeaa335 : marker
          ? 0xd29c47
          : metal
            ? 0x485e69
            : glass
              ? 0x6892a5
              : material === "concrete"
                ? 0xb4bbb9
                : material === "finish" || e.type === "wall"
                  ? (lower && exterior) || (lower && infill)
                    ? 0x9ea6a7
                    : 0xe5e7e1
                  : (colors[e.type] ?? 0xd2b77c);
        const envelope =
          transparentEnvelope &&
          (e.type === "roof" || infill || (e.type === "wall" && exterior));
        const transparent =
          envelope ||
          glass ||
          (!e.components.length && ["window", "elevator"].includes(e.type)) ||
          space ||
          marker ||
          e.type === "opening" ||
          portal;
        const parameters = {
          color,
          roughness: glass
            ? 0.08
            : metal
              ? 0.28
              : material === "finish"
                ? 0.65
                : 0.88,
          metalness: metal ? 0.85 : 0,
          side: T.DoubleSide,
          transparent,
          opacity: envelope
            ? 0.16
            : portal
              ? 0.14
              : glass
                ? 0.52
                : transparent
                  ? space
                    ? 0.28
                    : marker
                      ? 0.5
                      : 0.2
                  : 1,
          depthWrite: !transparent,
          clippingPlanes: planes,
        };
        const mat = glass
          ? new T.MeshPhysicalMaterial({
              ...parameters,
              ior: 1.5,
              clearcoat: 1,
              clearcoatRoughness: 0.08,
            })
          : new T.MeshStandardMaterial(parameters);
        if (transparent) mat.forceSinglePass = true;
        const mesh = new T.Mesh(geo, mat);
        mesh.position.y =
          elevation +
          (plan ? e.z_offset : piece.z) +
          (space ? 0.003 : flat ? 0.003 : 0);
        mesh.userData = {
          id: e.id,
          componentId: piece.componentId,
          role: piece.role,
          baseColor: color,
          space,
        };
        scene.add(mesh);
        selectable.push(mesh);
        mesh.castShadow = !flat && !transparent;
        mesh.receiveShadow = !transparent;
        const edgeGeo =
          e.type === "wall" && !plan && !flat
            ? wallEdges(geo, piece, piecesByElement.get(e.id)!)
            : new T.EdgesGeometry(geo, 35);
        const edges = new T.LineSegments(
          edgeGeo,
          new T.LineBasicMaterial({
            color: marker ? 0xb18035 : 0x53636c,
            transparent: true,
            opacity: envelope ? 0.08 : space ? 0.3 : metal ? 0.22 : 0.2,
            clippingPlanes: planes,
          }),
        );
        edges.position.copy(mesh.position);
        scene.add(edges);
        edgeObjects.push(edges);
        if (!plan && !flat && !glass && !envelope && planes.length) {
          const capGeo = sectionCap(geo, mesh.position, planes[0]);
          if (capGeo) {
            const cap = new T.Mesh(
              capGeo,
              new T.MeshStandardMaterial({
                color: material === "concrete" ? 0x9dada8 : 0xc9b79a,
                roughness: 0.95,
                side: T.DoubleSide,
                clippingPlanes: planes,
              }),
            );
            cap.userData = {
              ...mesh.userData,
              role: "section_cap",
              baseColor: material === "concrete" ? 0x9dada8 : 0xc9b79a,
            };
            scene.add(cap);
            selectable.push(cap);
          }
        }
      }
      if (
        e.type === "door" &&
        !e.components.length &&
        Array.isArray(e.source.hinge) &&
        Array.isArray(e.source.leaf_end)
      ) {
        const a = e.source.hinge as XY,
          b = e.source.leaf_end as XY,
          h = !plan ? (e.height ?? (assumptions ? 2.1 : 0.04)) : 0.02;
        const geo = new T.BoxGeometry(
            Math.hypot(b[0] - a[0], b[1] - a[1]),
            h,
            0.04,
          ),
          mat = new T.MeshStandardMaterial({
            color: colors.door,
            roughness: 0.7,
            clippingPlanes: planes,
          });
        const mesh = new T.Mesh(geo, mat);
        mesh.position.set(
          (a[0] + b[0]) / 2,
          elevation + e.z_offset + h / 2,
          (a[1] + b[1]) / 2,
        );
        mesh.rotation.y = -Math.atan2(b[1] - a[1], b[0] - a[0]);
        mesh.userData = { id: e.id, baseColor: colors.door };
        scene.add(mesh);
        selectable.push(mesh);
      }
    }
    selectable = batchElementMeshes(selectable, scene);
    batchEdges(edgeObjects, scene);
    const batchedLines = model.provenance.precision_rebuild
      ? scene.children.filter((child): child is T.LineSegments => child instanceof T.LineSegments && child !== grid)
      : [];
    const capCount = selectable.filter(
      (m) => m.userData.role === "section_cap",
    ).length;
    renderedBounds = new T.Box3();
    for (const mesh of selectable) renderedBounds.expandByObject(mesh);
    for (const lines of batchedLines) renderedBounds.expandByObject(lines);
    fitMeshes = [...selectable, ...batchedLines];
    if (renderedBounds.isEmpty()) renderedBounds = null;
    if (saved?.key !== key) fit();
    meshesRef.current = selectable;
    for (const mesh of selectable)
      if (mesh.userData.id === selectedRef.current) {
        const mat = mesh.material as T.MeshStandardMaterial;
        mat.emissive.setHex(0x075060);
        mat.emissiveIntensity = 0.4;
      }
    if (showLabels)
      for (const place of model.places.filter(
        (p) => floor === "all" || p.floor_id === floor,
      )) {
        const c = document.createElement("canvas");
        c.width = 512;
        c.height = 96;
        const ctx = c.getContext("2d")!;
        ctx.fillStyle = "#ffffffdd";
        ctx.fillRect(0, 0, 512, 96);
        ctx.fillStyle = "#183e48";
        ctx.font = "600 30px sans-serif";
        ctx.textAlign = "center";
        ctx.fillText(place.name, 256, 60);
        const tex = new T.CanvasTexture(c),
          sprite = new T.Sprite(
            new T.SpriteMaterial({
              map: tex,
              transparent: true,
              depthTest: true,
            }),
          );
        sprite.position.set(
          place.point[0],
          model.floors.find((f) => f.id === place.floor_id)!.elevation +
            floorOffset(model, place.floor_id, separation) +
            (plan ? 0.2 : 1.8),
          place.point[1],
        );
        sprite.scale.set(4.2, 0.788, 1);
        scene.add(sprite);
      }
    let routeSegments = 0;
    if (route?.status === "found")
      for (let i = 1; i < route.points.length; i++) {
        const a = route.points[i - 1],
          b = route.points[i];
        if (floor !== "all" && (a.floor !== floor || b.floor !== floor))
          continue;
        const start = new T.Vector3(
            a.point[0],
            model.floors.find((f) => f.id === a.floor)!.elevation +
              floorOffset(model, a.floor, separation) +
              0.12,
            a.point[1],
          ),
          end = new T.Vector3(
            b.point[0],
            model.floors.find((f) => f.id === b.floor)!.elevation +
              floorOffset(model, b.floor, separation) +
              0.12,
            b.point[1],
          );
        if (start.distanceTo(end) < 1e-6) continue;
        const mesh = new T.Mesh(
          new T.CylinderGeometry(0.055, 0.055, start.distanceTo(end), 8),
          // A route is a review overlay, so slabs and walls must not obscure it.
          // Route coordinates and navigation calculations remain unchanged.
          new T.MeshBasicMaterial({
            color: 0x26786b,
            clippingPlanes: planes,
            depthTest: false,
            depthWrite: false,
          }),
        );
        mesh.position.copy(start).add(end).multiplyScalar(0.5);
        mesh.quaternion.setFromUnitVectors(
          new T.Vector3(0, 1, 0),
          end.sub(start).normalize(),
        );
        mesh.renderOrder = 20;
        routeSegments++;
        scene.add(mesh);
      }
    renderer.domElement.dataset.routeSegments = String(routeSegments);
    apiRef.current = {
      fit,
      focus: (id) => {
        const box = new T.Box3();
        for (const mesh of selectable)
          if (mesh.userData.id === id) box.expandByObject(mesh);
        if (box.isEmpty()) return;
        const s = Math.max(box.getSize(new T.Vector3()).length(), 1);
        const element = model.elements.find((e) => e.id === id),
          axis = element?.source.window_plan_axis as
            | { direction: XY }
            | undefined;
        const direction = axis
          ? new T.Vector3(-axis.direction[1], 0.4, axis.direction[0])
          : new T.Vector3(0.65, 0.55, 0.85);
        controls.target.copy(box.getCenter(new T.Vector3()));
        camera.position
          .copy(controls.target)
          .add(direction.normalize().multiplyScalar(s * 1.6));
        controls.update();
        needsRender.current = true;
      },
      interior: () => {
        const viewpoint=interiorView(model,floor,selectedRef.current);
        if(viewpoint){
          const z=model.floors.find(f=>f.id===viewpoint.floorId)!.elevation+floorOffset(model,viewpoint.floorId,separation);
          camera.position.set(viewpoint.point[0],z+1.6,viewpoint.point[1]);
          controls.target.copy(camera.position).add(new T.Vector3(viewpoint.direction[0]*3,0,viewpoint.direction[1]*3));
          camera.lookAt(controls.target);controls.update();needsRender.current=true;return;
        }
        const target =
            model.places.find(
              (p) =>
                (floor === "all" || p.floor_id === floor) &&
                p.name.includes("홀"),
            ) ??
            model.places.find((p) => floor === "all" || p.floor_id === floor),
          z =
            model.floors.find((f) => f.id === (target?.floor_id ?? floor))
              ?.elevation ?? base;
        camera.position.set(
          target?.point[0] ?? cx,
          z + floorOffset(model, target?.floor_id ?? floor, separation) + 1.6,
          target?.point[1] ?? cy,
        );
        controls.target.copy(camera.position).add(new T.Vector3(0, 0, -3));
        camera.lookAt(controls.target);
        controls.update();
        needsRender.current = true;
      },
    };
    let down: [number, number] | null = null,
      last: [number, number] | null = null;
    const keys = new Set<string>();
    const pointerDown = (e: PointerEvent) => {
      down = [e.clientX, e.clientY];
      last = down;
      if (walking) {
        renderer.domElement.focus();
        renderer.domElement.setPointerCapture(e.pointerId);
      }
    };
    const pointerMove = (e: PointerEvent) => {
      if (!walking || !last || !e.buttons) return;
      camera.rotation.y -= (e.clientX - last[0]) * 0.004;
      camera.rotation.x = T.MathUtils.clamp(
        camera.rotation.x - (e.clientY - last[1]) * 0.004,
        -1.45,
        1.45,
      );
      last = [e.clientX, e.clientY];
    };
    const pointerUp = (e: PointerEvent) => {
      last = null;
      if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 5)
        return;
      const r = renderer.domElement.getBoundingClientRect(),
        ray = new T.Raycaster();
      ray.setFromCamera(
        new T.Vector2(
          ((e.clientX - r.left) / r.width) * 2 - 1,
          (-(e.clientY - r.top) / r.height) * 2 + 1,
        ),
        camera,
      );
      const hits = ray
        .intersectObjects(selectable)
        .filter((hit) =>
          planes.every((p) => p.distanceToPoint(hit.point) >= 0),
        );
      const hit =
        hits.find((x) => {
          const kind = model.elements.find(
            (el) => el.id === x.object.userData.id,
          )?.type;
          return !["floor", "roof", "space", "corridor", "elevator"].includes(
            kind ?? "",
          );
        }) ?? hits[0];
      if (hit) {
        setPickedPart(pickedComponent(hit.object as T.Mesh, hit.faceIndex));
        selectRef.current(hit.object.userData.id);
      }
    };
    const keyName = (k: string) => (k.length === 1 ? k.toLowerCase() : k);
    const keydown = (e: KeyboardEvent) => {
        if (!walking || document.activeElement !== renderer.domElement) return;
        const k = keyName(e.key);
        if (
          [
            "w",
            "a",
            "s",
            "d",
            "q",
            "e",
            "ArrowUp",
            "ArrowDown",
            "ArrowLeft",
            "ArrowRight",
            "Shift",
          ].includes(k)
        ) {
          keys.add(k);
          e.preventDefault();
        }
      },
      keyup = (e: KeyboardEvent) => keys.delete(keyName(e.key)),
      blur = () => keys.clear();
    renderer.domElement.addEventListener("pointerdown", pointerDown);
    renderer.domElement.addEventListener("pointermove", pointerMove);
    renderer.domElement.addEventListener("pointerup", pointerUp);
    renderer.domElement.addEventListener("keydown", keydown);
    window.addEventListener("keyup", keyup);
    renderer.domElement.addEventListener("blur", blur);
    const resize = new ResizeObserver(() => {
      const w = container.clientWidth,
        h = container.clientHeight;
      if (w < 1 || h < 1) return;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
      needsRender.current = true;
    });
    resize.observe(container);
    let frame = 0,
      lastTime = performance.now();
    function animate(time = performance.now()) {
      const dt = Math.min((time - lastTime) / 1000, 0.05);
      lastTime = time;
      if (walking) {
        const forward = new T.Vector3();
        camera.getWorldDirection(forward);
        forward.y = 0;
        forward.normalize();
        const right = new T.Vector3().crossVectors(
            forward,
            new T.Vector3(0, 1, 0),
          ),
          speed = (keys.has("Shift") ? 5 : 2) * dt;
        if (keys.has("w") || keys.has("ArrowUp"))
          camera.position.addScaledVector(forward, speed);
        if (keys.has("s") || keys.has("ArrowDown"))
          camera.position.addScaledVector(forward, -speed);
        if (keys.has("d") || keys.has("ArrowRight"))
          camera.position.addScaledVector(right, speed);
        if (keys.has("a") || keys.has("ArrowLeft"))
          camera.position.addScaledVector(right, -speed);
        if (keys.has("e")) camera.position.y += speed;
        if (keys.has("q")) camera.position.y -= speed;
      }
      const changed = !walking && controls.update();
      if (walking || changed || needsRender.current) {
        renderer.render(scene, camera);
        needsRender.current = false;
      }
      renderer.domElement.dataset.meshes = String(selectable.length);
      renderer.domElement.dataset.triangles = String(
        renderer.info.render.triangles,
      );
      renderer.domElement.dataset.drawCalls = String(
        renderer.info.render.calls,
      );
      renderer.domElement.dataset.sectionCaps = String(capCount);
      renderer.domElement.dataset.camera = JSON.stringify(
        camera.position.toArray(),
      );
      frame = requestAnimationFrame(animate);
    }
    animate();
    return () => {
      if (walking) {
        const dir = new T.Vector3();
        camera.getWorldDirection(dir);
        controls.target.copy(camera.position).addScaledVector(dir, 3);
      }
      cameraState.current = {
        key,
        position: camera.position.clone(),
        target: controls.target.clone(),
      };
      cancelAnimationFrame(frame);
      resize.disconnect();
      controls.dispose();
      window.removeEventListener("keyup", keyup);
      scene.traverse((obj) => {
        const mesh = obj as T.Mesh;
        mesh.geometry?.dispose();
        if (mesh.material)
          for (const mat of Array.isArray(mesh.material)
            ? mesh.material
            : [mesh.material]) {
            (mat as T.SpriteMaterial).map?.dispose();
            mat.dispose();
          }
      });
      environment.dispose();
      renderer.dispose();
      renderer.domElement.remove();
      apiRef.current = null;
      meshesRef.current = [];
    };
  }, [
    model,
    floor,
    plan,
    route,
    hideWalls,
    showSpaces,
    showLabels,
    showMarkers,
    hideRoof,
    assumptions,
    evidenceMode,
    separation,
    section,
    cut,
    walking,
    transparentEnvelope,
    isolationKey,
    doorOpen,
    viewDirection,
    showGround,
    hiddenIds,
  ]);
  useEffect(() => {
    for (const mesh of meshesRef.current) {
      const mat = mesh.material as T.MeshStandardMaterial;
      mat.color.setHex(mesh.userData.baseColor);
      mat.emissive.setHex(mesh.userData.id === selected ? 0x075060 : 0);
      mat.emissiveIntensity = 0.4;
    }
    needsRender.current = true;
  }, [selected]);
  const fs = model.floors.find((f) => f.id === floor)?.id ?? model.floors[0].id;
  const els = model.elements.filter(
    (e) =>
      e.floor_id === fs &&
      !e.excluded &&
      !hiddenIds.includes(e.id) &&
      (!hideWalls || e.type !== "wall") &&
      (!hideRoof || e.type !== "roof") &&
      (!e.source.marker_width_m || showMarkers) &&
      (!["space", "corridor"].includes(e.type) || showSpaces),
  );
  const b = els.length
    ? bounds(els.map(raw))
    : { min: [0, 0] as XY, max: [20, 12] as XY };
  return (
    <div className="viewer-wrap">
      <div
        className="bim-view-options"
        aria-label="BIM 조작 도구"
        ref={toolsHost}
      >
        <div className="camera-tools">
          <button
            aria-label="전체 맞춤"
            title="현재 층의 전체 모델 맞춤"
            disabled={fallback}
            onClick={() => {
              setWalking(false);
              apiRef.current?.fit();
            }}
          >
            <Maximize size={16} />
            <span>전체 맞춤</span>
          </button>
          <button
            aria-label="선택 확대"
            title="선택 객체 확대"
            disabled={!selected || plan || fallback}
            onClick={() => {
              setWalking(false);
              apiRef.current?.focus(selected);
            }}
          >
            <Focus size={16} />
            <span>선택 확대</span>
          </button>
          <button
            aria-label={walking ? "실내 시점 종료" : "실내 시점"}
            title="실내 자유 시점 · WASD 이동"
            disabled={plan || fallback}
            aria-pressed={walking}
            className={walking ? "active" : ""}
            onClick={() => {
              if (!walking) apiRef.current?.interior();
              setWalking(!walking);
            }}
          >
            <PersonStanding size={16} />
            <span>{walking ? "실내 종료" : "실내 시점"}</span>
          </button>
        </div>
        <div className="advanced-tools">
          <button
            aria-label="선택 객체 숨기기"
            title="선택 객체 숨기기"
            disabled={!selected || fallback}
            onClick={() => {
              setHiddenIds((ids) => [...new Set([...ids, selected])]);
              setIsolated(false);
              onSelect("");
            }}
          >
            <EyeOff size={16} />
            <span>숨기기</span>
          </button>
          <button
            aria-label="선택 객체만 보기"
            title="선택한 조립체를 집중 검토"
            disabled={!selected || fallback}
            aria-pressed={isolated}
            className={isolated ? "active" : ""}
            onClick={() => setIsolated(!isolated)}
          >
            <Focus size={16} />
            <span>{isolated ? "집중 보기 종료" : "선택만 보기"}</span>
          </button>
          <button
            aria-label="표시 설정"
            title="표시 설정"
            aria-expanded={tool === "display"}
            aria-controls="display-options"
            className={tool === "display" ? "active" : ""}
            onClick={() => setTool(tool === "display" ? null : "display")}
          >
            <Settings2 size={16} />
            <span>표시 설정</span>
          </button>
          <button
            aria-label="단면 · 층 분리"
            title="단면 · 층 분리"
            aria-expanded={tool === "section"}
            aria-controls="section-options"
            className={
              tool === "section" || section !== "none" || separation > 0
                ? "active"
                : ""
            }
            onClick={() => setTool(tool === "section" ? null : "section")}
          >
            <Scissors size={16} />
            <span>단면 · 층 분리</span>
          </button>
        </div>
        {tool === "display" && (
          <div className="tool-popover" id="display-options">
            <h3>
              <Settings2 size={16} />
              모델 표시
            </h3>
            {Boolean(model.provenance.precision_rebuild) && <label>
              <span>검증 상태 표시</span>
              <select aria-label="검증 상태 표시" value={evidenceMode} onChange={e=>setEvidenceMode(e.target.value)}>
                <option value="full">전체 3D 모델</option>
                <option value="drawing">도면 기반 형상만</option>
                <option value="verified">검증 완료 부재만</option>
                <option value="highlight">미확정 형상 강조</option>
              </select>
            </label>}
            <label>
              <span>벽체 표시</span>
              <input
                type="checkbox"
                checked={!hideWalls}
                onChange={(e) => setHideWalls(!e.target.checked)}
              />
            </label>
            <label>
              <span>지붕 표시</span>
              <input
                type="checkbox"
                checked={!hideRoof}
                onChange={(e) => setHideRoof(!e.target.checked)}
              />
            </label>
            <label>
              <span>외벽 · 지붕 투명화</span>
              <input
                type="checkbox"
                checked={transparentEnvelope}
                onChange={(e) => setTransparentEnvelope(e.target.checked)}
              />
            </label>
            <label>
              <span>가정 지반 표시</span>
              <input
                type="checkbox"
                checked={showGround}
                onChange={(e) => setShowGround(e.target.checked)}
              />
            </label>
            <p>
              전체 외관의 지반은 1층 바닥 기준 가정면입니다. 지하층은 지반을
              끄거나 층별·단면 보기로 확인하세요.
            </p>
            <label>
              <span>뷰 방향</span>
              <select
                aria-label="뷰 방향"
                value={viewDirection}
                onChange={(e) => {
                  setWalking(false);
                  setViewDirection(e.target.value);
                }}
              >
                <option value="building">건물 사선</option>
                <option value="iso">기본 사선</option>
                <option value="front">정면</option>
                <option value="back">후면</option>
                <option value="left">좌측</option>
                <option value="right">우측</option>
                <option value="top">위에서</option>
              </select>
            </label>
            <label>
              <span>실 영역</span>
              <input
                type="checkbox"
                checked={showSpaces}
                onChange={(e) => setShowSpaces(e.target.checked)}
              />
            </label>
            <label>
              <span>실명</span>
              <input
                type="checkbox"
                checked={showLabels}
                onChange={(e) => setShowLabels(e.target.checked)}
              />
            </label>
            <label>
              <span>미확정 면</span>
              <input
                type="checkbox"
                checked={showMarkers}
                onChange={(e) => setShowMarkers(e.target.checked)}
              />
            </label>
            <label>
              <span>임시 조립체 입체 표시</span>
              <input
                type="checkbox"
                checked={assumptions}
                onChange={(e) => setAssumptions(e.target.checked)}
              />
            </label>
            <label>
              <span>문 개방 표시</span>
              <output>{doorOpen}%</output>
            </label>
            <input
              aria-label="문 개방 표시"
              type="range"
              min="0"
              max="100"
              step="10"
              value={doorOpen}
              onChange={(e) => setDoorOpen(Number(e.target.value))}
            />
            <p>
              회전호 방향을 따르는 검토 표시입니다. 닫힘 방향·통행 유효폭은
              미확정이며, 원본 형상과 BF 계산은 변경하지 않습니다.
            </p>
          </div>
        )}
        {tool === "section" && (
          <div className="tool-popover" id="section-options">
            <h3>
              <Layers size={16} />
              단면 · 층 분리
            </h3>
            <label>
              <span>층 분리 간격</span>
              <output>{separation} m</output>
            </label>
            <input
              aria-label="층 분리 간격"
              type="range"
              min="0"
              max="12"
              step="1"
              value={separation}
              onChange={(e) => setSeparation(Number(e.target.value))}
            />
            <label>
              <span>단면 방향</span>
              <select
                aria-label="단면 방향"
                value={section}
                onChange={(e) => setSection(e.target.value)}
              >
                <option value="none">없음</option>
                <option value="x">X 방향</option>
                <option value="y">Y 방향</option>
                <option value="z">높이 Z</option>
              </select>
            </label>
            {section !== "none" && (
              <>
                <label>
                  <span>단면 위치</span>
                  <output>{cut}%</output>
                </label>
                <input
                  aria-label="단면 위치"
                  type="range"
                  min="0"
                  max="100"
                  value={cut}
                  onChange={(e) => setCut(Number(e.target.value))}
                />
              </>
            )}
            <button
              className="full"
              onClick={() => {
                setSection("none");
                setSeparation(0);
                setCut(50);
              }}
            >
              단면 · 분리 초기화
            </button>
          </div>
        )}
      </div>
      <div className="orientation-widget" aria-label="카메라 방향 전환">
        <span>VIEW</span>
        <div>
          <button
            aria-label="사선 보기"
            title="사선 보기"
            aria-pressed={viewDirection === "building" && !plan}
            disabled={plan || fallback}
            onClick={() => {
              setWalking(false);
              setViewDirection("building");
            }}
          >
            <Rotate3D size={17} />
          </button>
          <button
            aria-label="정면 보기"
            title="정면 보기"
            aria-pressed={viewDirection === "front" && !plan}
            disabled={plan || fallback}
            onClick={() => {
              setWalking(false);
              setViewDirection("front");
            }}
          >
            F
          </button>
          <button
            aria-label="상부 보기"
            title="상부 보기"
            aria-pressed={viewDirection === "top" && !plan}
            disabled={plan || fallback}
            onClick={() => {
              setWalking(false);
              setViewDirection("top");
            }}
          >
            <ArrowUp size={17} />
          </button>
        </div>
      </div>
      {hiddenIds.length > 0 && (
        <button className="restore-objects" onClick={() => setHiddenIds([])}>
          <Eye size={14} />
          {hiddenIds.length}개 숨김 · 모두 표시
        </button>
      )}
      {evidenceMode === "verified" && model.provenance.verified_solids === 0 && <div className="viewer-assumption-note">
        검증 완료 입체 부재가 0개입니다. 전체 3D 모델에서 도면 기반 검토 형상을 확인하세요.
      </div>}
      {assumptions && !model.is_example && evidenceMode !== "verified" && (
        <details className="viewer-caution">
          <summary>
            <TriangleAlert size={14} />
            {model.provenance.coordination_draft ? `통합 3D Coordination Draft · 검증 입체 ${Number(model.provenance.verified_solids ?? 0)}개` : model.provenance.precision_rebuild ? `도면 평면 + 미확정 3D · 검증 입체 ${Number(model.provenance.verified_solids ?? 0)}개` : "임시 치수 포함 · 도면 검토 필요"}
          </summary>
          <p>
            {model.provenance.coordination_draft ? "CAD 위치와 검토용 입체 조립체를 표시합니다. 높이·두께·재료 가정은 객체 속성에 기록됩니다. Draft IFC와 Verified IFC를 구분해 저장하세요." : model.provenance.precision_rebuild
              ? "원본 평면 경계와 미확정 층간 외피를 표시합니다. 1 mm 벽면 표시는 실제 벽 두께가 아닙니다. 검증된 입체는 0개이며, 미확정 외피는 IFC에서 제외됩니다."
              : "슬래브·마감·참·문틀·창틀·샤프트는 검토 후보입니다. JSON/IFC에도 미확정 근거를 보존합니다. 선택 객체에서 치수와 근거를 확인하세요."}
          </p>
          {evidenceMode === "highlight" && <p>초록: 근거 검증 완료 · 주황: 임시 치수 또는 미배정 · 빨강: 미해결. 도면 기반 형상 모드에서는 입체로 만들지 못한 원본 후보도 확인할 수 있습니다.</p>}
        </details>
      )}
      {walking && (
        <p className="walk-help">
          화면 클릭 후 WASD: 전후좌우 · Q/E: 높이 · 드래그: 둘러보기. 자유
          시점이며 통행 가능 여부를 판정하지 않습니다.
        </p>
      )}
      {pickedPart &&
        model.elements
          .find((e) => e.id === selected)
          ?.components.some((c) => c.id === pickedPart) && (
          <output className="component-pick" aria-label="선택 구성요소">
            {
              model.elements
                .find((e) => e.id === selected)
                ?.components.find((c) => c.id === pickedPart)?.role
            }{" "}
            · {pickedPart.split("/component/")[1]} · 치수 검토 후보
          </output>
        )}
      <div
        className="viewer"
        ref={host}
        aria-label={`${model.name} ${plan ? "평면" : "3D"} 모델`}
      >
        {fallback && (
          <div className="fallback">
            <p>
              WebGL을 사용할 수 없어 평면도로 표시합니다. 전체 층에서는{" "}
              {model.floors.find((f) => f.id === fs)?.name}을 표시합니다.
            </p>
            <svg
              viewBox={`${b.min[0] - 1} ${b.min[1] - 1} ${b.max[0] - b.min[0] + 2} ${b.max[1] - b.min[1] + 2}`}
              role="img"
              aria-label="건축물 평면도"
            >
              {els.map((e) => (
                <path
                  key={e.id}
                  d={raw(e)
                    .map((r) => "M" + r.map((p) => p.join(",")).join("L") + "Z")
                    .join(" ")}
                  fill={
                    e.id === selected
                      ? "#22a2bd"
                      : "#" +
                        (colors[e.type] ?? 0xaaaaaa)
                          .toString(16)
                          .padStart(6, "0")
                  }
                  fillOpacity={["space", "corridor"].includes(e.type) ? 0.3 : 1}
                  fillRule="evenodd"
                  stroke="#607982"
                  strokeWidth=".035"
                  onClick={() => onSelect(e.id)}
                />
              ))}
            </svg>
          </div>
        )}
      </div>
    </div>
  );
}
