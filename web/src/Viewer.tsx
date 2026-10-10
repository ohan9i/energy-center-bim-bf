import {useEffect,useRef,useState} from 'react';
import * as T from 'three';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';
import type {Model,XY,Profile} from './model';
import {bounds,raw,type Poly} from './geometry';
import type {RouteResult} from './navigation';
import {renderPieces,floorOffset} from './bimGeometry';
import {Focus,Maximize,PersonStanding,Settings2,Scissors,Layers,TriangleAlert} from 'lucide-react';
interface Props {model:Model;floor:string;plan:boolean;selected:string;route:RouteResult|null;profile:Profile;onSelect:(id:string)=>void}
const colors:Record<string,number>={wall:0xcbd1cc,column:0x75838b,beam:0x68737e,floor:0xe4dfd3,roof:0xb2bbc0,door:0x976f46,window:0x7fc6df,opening:0xd69e50,space:0x91bfb0,corridor:0xa9c2d9,ramp:0x96b7a2,stair:0xb0aaa0,elevator:0x8a9aac,obstacle:0x7f8b94,unclassified:0xd2b77c};
type CameraAPI={fit:()=>void;focus:(id:string)=>void;interior:()=>void};
export default function Viewer({model,floor,plan,selected,route,onSelect}:Props){
 const host=useRef<HTMLDivElement>(null),selectRef=useRef(onSelect),selectedRef=useRef(selected),apiRef=useRef<CameraAPI|null>(null);
 selectRef.current=onSelect;selectedRef.current=selected;
 const meshesRef=useRef<T.Mesh[]>([]),[fallback,setFallback]=useState(false);
 const [hideWalls,setHideWalls]=useState(false),[showSpaces,setShowSpaces]=useState(false),[showLabels,setShowLabels]=useState(false),[showMarkers,setShowMarkers]=useState(false),[hideRoof,setHideRoof]=useState(false),[assumptions,setAssumptions]=useState(true),[separation,setSeparation]=useState(0),[section,setSection]=useState('none'),[cut,setCut]=useState(50),[walking,setWalking]=useState(false);
 const cameraState=useRef<{key:string;position:T.Vector3;target:T.Vector3}|null>(null);
 const [tool,setTool]=useState<'display'|'section'|null>(null);
 const toolsHost=useRef<HTMLDivElement>(null);
 useEffect(()=>{if(!tool)return;const close=(e:PointerEvent)=>{if(!toolsHost.current?.contains(e.target as Node))setTool(null);};const escape=(e:KeyboardEvent)=>{if(e.key==='Escape')setTool(null);};document.addEventListener('pointerdown',close);document.addEventListener('keydown',escape);return()=>{document.removeEventListener('pointerdown',close);document.removeEventListener('keydown',escape);};},[tool]);
 useEffect(()=>{setWalking(false);cameraState.current=null;},[model.id,floor,plan]);
 useEffect(()=>{
  const container=host.current;if(!container)return;
  let renderer:T.WebGLRenderer;
  try{renderer=new T.WebGLRenderer({antialias:true});setFallback(false);}catch{setFallback(true);return;}
  const scene=new T.Scene();scene.background=new T.Color(0xe9eef1);
  const camera=new T.PerspectiveCamera(42,container.clientWidth/Math.max(container.clientHeight,1),.025,2000);camera.rotation.order='YXZ';
  renderer.setPixelRatio(Math.min(window.devicePixelRatio,2));renderer.outputColorSpace=T.SRGBColorSpace;
  renderer.toneMapping=T.ACESFilmicToneMapping;renderer.toneMappingExposure=1;renderer.localClippingEnabled=true;
  renderer.shadowMap.enabled=!plan;renderer.shadowMap.type=T.PCFSoftShadowMap;
  container.append(renderer.domElement);renderer.domElement.tabIndex=0;renderer.domElement.setAttribute('aria-label','BIM 3D 탐색 화면');
  const controls=new OrbitControls(camera,renderer.domElement);controls.enableDamping=true;controls.dampingFactor=.08;controls.enableRotate=!plan;controls.maxPolarAngle=Math.PI*.94;controls.minDistance=.25;
  const visible=model.elements.filter(e=>!e.excluded&&(floor==='all'||e.floor_id===floor));
  const extent=visible.length?bounds(visible.map(raw)):{min:[0,0] as XY,max:[20,12] as XY};
  const cx=(extent.min[0]+extent.max[0])/2,cy=(extent.min[1]+extent.max[1])/2,size=Math.max(extent.max[0]-extent.min[0],extent.max[1]-extent.min[1],5);
  const base=model.floors.find(f=>f.id===floor)?.elevation??0;
  const top=Math.max(...model.floors.filter(f=>floor==='all'||f.id===floor).map(f=>f.elevation+floorOffset(model,f.id,separation)+5),5);
  const planes:T.Plane[]=[];
  if(section==='x')planes.push(new T.Plane(new T.Vector3(-1,0,0),extent.min[0]+(extent.max[0]-extent.min[0])*cut/100));
  if(section==='y')planes.push(new T.Plane(new T.Vector3(0,0,-1),extent.min[1]+(extent.max[1]-extent.min[1])*cut/100));
  if(section==='z')planes.push(new T.Plane(new T.Vector3(0,-1,0),base+(top-base)*cut/100));
  let renderedBounds:T.Box3|null=null;
  const fit=()=>{
   const box=renderedBounds??new T.Box3(new T.Vector3(extent.min[0],base,extent.min[1]),new T.Vector3(extent.max[0],top,extent.max[1]));
   const center=box.getCenter(new T.Vector3()),direction=(plan?new T.Vector3(0,1,.001):new T.Vector3(.62,.65,.78)).normalize();
   const right=new T.Vector3().crossVectors(camera.up,direction).normalize(),up=new T.Vector3().crossVectors(direction,right),tan=Math.tan(T.MathUtils.degToRad(camera.fov/2));
   let distance=3;
   for(const x of [box.min.x,box.max.x])for(const y of [box.min.y,box.max.y])for(const z of [box.min.z,box.max.z]){
    const corner=new T.Vector3(x,y,z).sub(center),depth=corner.dot(direction);
    distance=Math.max(distance,Math.abs(corner.dot(right))/(tan*Math.max(camera.aspect,.1))+depth,Math.abs(corner.dot(up))/tan+depth);
   }
   controls.target.copy(center);camera.position.copy(center).addScaledVector(direction,distance*1.12);controls.update();
  };
  const key=model.id+floor+plan,saved=cameraState.current;
  if(saved?.key===key){camera.position.copy(saved.position);controls.target.copy(saved.target);controls.update();}
  controls.enabled=!walking;
  scene.add(new T.HemisphereLight(0xfafcff,0x8b989f,2));const light=new T.DirectionalLight(0xfffaf2,2.6);light.position.set(cx+20,top+35,cy+15);scene.add(light);
  light.castShadow=true;light.shadow.mapSize.set(2048,2048);light.shadow.camera.left=-size;light.shadow.camera.right=size;
  light.shadow.camera.top=size;light.shadow.camera.bottom=-size;light.shadow.camera.far=250;light.shadow.normalBias=.035;
  light.target.position.set(cx,base,cy);scene.add(light.target);
  const fill=new T.DirectionalLight(0xe2ecf5,.9);fill.position.set(cx-30,top+10,cy-15);scene.add(fill);
  const grid=new T.GridHelper(Math.max(30,Math.ceil(size*1.4)),Math.min(100,Math.ceil(size*1.4)),0xc7d1d7,0xd4dde2);grid.position.set(cx,base-.12,cy);(grid.material as T.Material).transparent=true;(grid.material as T.Material).opacity=.45;scene.add(grid);
  if(!plan){const ground=new T.Mesh(new T.PlaneGeometry(size*3,size*3),new T.ShadowMaterial({opacity:.13}));ground.rotation.x=-Math.PI/2;ground.position.set(cx,base-.14,cy);ground.receiveShadow=true;scene.add(ground);}
  const selectable:T.Mesh[]=[];
  function shape(poly:Poly){const s=new T.Shape(poly[0].map(p=>new T.Vector2(p[0],-p[1])));for(const r of poly.slice(1))s.holes.push(new T.Path(r.map(p=>new T.Vector2(p[0],-p[1]))));return s;}
  for(const e of visible){
   const marker=Boolean(e.source.marker_width_m),space=['space','corridor'].includes(e.type);
   if(marker&&!showMarkers||hideWalls&&e.type==='wall'||hideRoof&&e.type==='roof'||space&&!showSpaces||e.type==='opening'&&!showMarkers)continue;
   const elevation=model.floors.find(f=>f.id===e.floor_id)!.elevation+floorOffset(model,e.floor_id,separation);
   for(const piece of renderPieces(e,model,assumptions)){
    const portal=e.type==='door'&&!e.components.length&&Array.isArray(e.source.hinge);
    const flat=piece.height===null||space||e.type==='opening'||portal;let geo:T.BufferGeometry;
    if(flat||plan){geo=new T.ShapeGeometry(shape(piece.poly));geo.rotateX(-Math.PI/2);}
    else{geo=new T.ExtrudeGeometry(shape(piece.poly),{depth:piece.height!,bevelEnabled:false,steps:1});geo.rotateX(-Math.PI/2);}
    const material=piece.material??String(e.source.material??''),glass=material==='glazing',metal=material==='metal';
    const color=marker?0xd29c47:metal?0x69777f:material==='concrete'?0xbfc4c2:material==='finish'?0xe7e5dd:colors[e.type]??0xd2b77c;
    const transparent=glass||!e.components.length&&['window','elevator'].includes(e.type)||space||marker||e.type==='opening'||portal;
    const mat=new T.MeshStandardMaterial({color,roughness:glass?.2:metal?.45:.82,metalness:metal?.35:0,side:T.DoubleSide,transparent,
      opacity:portal?.14:glass?.38:transparent?(space?.28:marker?.5:.2):1,depthWrite:!transparent,clippingPlanes:planes});
    const mesh=new T.Mesh(geo,mat);mesh.position.y=elevation+(plan?e.z_offset:piece.z)+(space?.07:flat?.012:0);mesh.userData={id:e.id,baseColor:color,space};scene.add(mesh);selectable.push(mesh);
    mesh.castShadow=!flat&&!transparent;mesh.receiveShadow=!transparent;
    const edges=new T.LineSegments(new T.EdgesGeometry(geo,25),new T.LineBasicMaterial({color:marker?0xb18035:0x596871,transparent:true,opacity:space?.3:.18,clippingPlanes:planes}));edges.position.copy(mesh.position);scene.add(edges);
   }
   if(e.type==='door'&&!e.components.length&&Array.isArray(e.source.hinge)&&Array.isArray(e.source.leaf_end)){
    const a=e.source.hinge as XY,b=e.source.leaf_end as XY,h=!plan?(e.height??(assumptions?2.1:.04)):.02;
    const geo=new T.BoxGeometry(Math.hypot(b[0]-a[0],b[1]-a[1]),h,.04),mat=new T.MeshStandardMaterial({color:colors.door,roughness:.7,clippingPlanes:planes});
    const mesh=new T.Mesh(geo,mat);mesh.position.set((a[0]+b[0])/2,elevation+e.z_offset+h/2,(a[1]+b[1])/2);mesh.rotation.y=-Math.atan2(b[1]-a[1],b[0]-a[0]);mesh.userData={id:e.id,baseColor:colors.door};scene.add(mesh);selectable.push(mesh);
   }
  }
  renderedBounds=new T.Box3();for(const mesh of selectable)renderedBounds.expandByObject(mesh);
  if(renderedBounds.isEmpty())renderedBounds=null;
  if(saved?.key!==key)fit();
  meshesRef.current=selectable;
  for(const mesh of selectable)if(mesh.userData.id===selectedRef.current)(mesh.material as T.MeshStandardMaterial).color.setHex(0x22a2bd);
  if(showLabels)for(const place of model.places.filter(p=>floor==='all'||p.floor_id===floor)){
   const c=document.createElement('canvas');c.width=512;c.height=96;const ctx=c.getContext('2d')!;ctx.fillStyle='#ffffffdd';ctx.fillRect(0,0,512,96);ctx.fillStyle='#183e48';ctx.font='600 30px sans-serif';ctx.textAlign='center';ctx.fillText(place.name,256,60);
   const tex=new T.CanvasTexture(c),sprite=new T.Sprite(new T.SpriteMaterial({map:tex,transparent:true,depthTest:true}));sprite.position.set(place.point[0],model.floors.find(f=>f.id===place.floor_id)!.elevation+floorOffset(model,place.floor_id,separation)+(plan?.2:1.8),place.point[1]);sprite.scale.set(4.2,.788,1);scene.add(sprite);
  }
  if(route?.status==='found')for(let i=1;i<route.points.length;i++){
   const a=route.points[i-1],b=route.points[i];if(floor!=='all'&&(a.floor!==floor||b.floor!==floor))continue;
   const start=new T.Vector3(a.point[0],model.floors.find(f=>f.id===a.floor)!.elevation+floorOffset(model,a.floor,separation)+.12,a.point[1]),end=new T.Vector3(b.point[0],model.floors.find(f=>f.id===b.floor)!.elevation+floorOffset(model,b.floor,separation)+.12,b.point[1]);
   if(start.distanceTo(end)<1e-6)continue;
   const mesh=new T.Mesh(new T.CylinderGeometry(.045,.045,start.distanceTo(end),8),new T.MeshBasicMaterial({color:0x0d9087,clippingPlanes:planes}));mesh.position.copy(start).add(end).multiplyScalar(.5);mesh.quaternion.setFromUnitVectors(new T.Vector3(0,1,0),end.sub(start).normalize());scene.add(mesh);
  }
  apiRef.current={fit,focus:(id)=>{
   const e=model.elements.find(e=>e.id===id);if(!e)return;const b=bounds([raw(e)]),s=Math.max(b.max[0]-b.min[0],b.max[1]-b.min[1],3),z=model.floors.find(f=>f.id===e.floor_id)!.elevation+floorOffset(model,e.floor_id,separation)+e.z_offset;
   controls.target.set((b.min[0]+b.max[0])/2,z+1,(b.min[1]+b.max[1])/2);camera.position.copy(controls.target).add(new T.Vector3(s*.6,s*.7,s*.7));controls.update();
  },interior:()=>{
   const target=model.places.find(p=>(floor==='all'||p.floor_id===floor)&&p.name.includes('홀'))??model.places.find(p=>floor==='all'||p.floor_id===floor),z=model.floors.find(f=>f.id===(target?.floor_id??floor))?.elevation??base;
   camera.position.set(target?.point[0]??cx,z+floorOffset(model,target?.floor_id??floor,separation)+1.6,target?.point[1]??cy);
   controls.target.copy(camera.position).add(new T.Vector3(0,0,-3));camera.lookAt(controls.target);controls.update();
  }};
  let down:[number,number]|null=null,last:[number,number]|null=null;const keys=new Set<string>();
  const pointerDown=(e:PointerEvent)=>{down=[e.clientX,e.clientY];last=down;if(walking){renderer.domElement.focus();renderer.domElement.setPointerCapture(e.pointerId);}};
  const pointerMove=(e:PointerEvent)=>{if(!walking||!last||!e.buttons)return;camera.rotation.y-=(e.clientX-last[0])*.004;camera.rotation.x=T.MathUtils.clamp(camera.rotation.x-(e.clientY-last[1])*.004,-1.45,1.45);last=[e.clientX,e.clientY];};
  const pointerUp=(e:PointerEvent)=>{
   last=null;if(!down||Math.hypot(e.clientX-down[0],e.clientY-down[1])>5)return;
   const r=renderer.domElement.getBoundingClientRect(),ray=new T.Raycaster();ray.setFromCamera(new T.Vector2((e.clientX-r.left)/r.width*2-1,-(e.clientY-r.top)/r.height*2+1),camera);
   const hits=ray.intersectObjects(selectable).filter(hit=>planes.every(p=>p.distanceToPoint(hit.point)>=0));
   const hit=hits.find(x=>{const kind=model.elements.find(el=>el.id===x.object.userData.id)?.type;return !['floor','roof','space','corridor','elevator'].includes(kind??'');})??hits[0];if(hit)selectRef.current(hit.object.userData.id);
  };
  const keydown=(e:KeyboardEvent)=>{if(!walking||document.activeElement!==renderer.domElement)return;if(['w','a','s','d','q','e','ArrowUp','ArrowDown','ArrowLeft','ArrowRight','Shift'].includes(e.key)){keys.add(e.key);e.preventDefault();}},keyup=(e:KeyboardEvent)=>keys.delete(e.key),blur=()=>keys.clear();
  renderer.domElement.addEventListener('pointerdown',pointerDown);renderer.domElement.addEventListener('pointermove',pointerMove);renderer.domElement.addEventListener('pointerup',pointerUp);renderer.domElement.addEventListener('keydown',keydown);window.addEventListener('keyup',keyup);renderer.domElement.addEventListener('blur',blur);
  const resize=new ResizeObserver(()=>{const w=container.clientWidth,h=container.clientHeight;if(w<1||h<1)return;camera.aspect=w/h;camera.updateProjectionMatrix();renderer.setSize(w,h);});resize.observe(container);
  let frame=0,lastTime=performance.now();function animate(time=performance.now()){
   const dt=Math.min((time-lastTime)/1000,.05);lastTime=time;
   if(walking){const forward=new T.Vector3();camera.getWorldDirection(forward);forward.y=0;forward.normalize();const right=new T.Vector3().crossVectors(forward,new T.Vector3(0,1,0)),speed=(keys.has('Shift')?5:2)*dt;
    if(keys.has('w')||keys.has('ArrowUp'))camera.position.addScaledVector(forward,speed);if(keys.has('s')||keys.has('ArrowDown'))camera.position.addScaledVector(forward,-speed);if(keys.has('d')||keys.has('ArrowRight'))camera.position.addScaledVector(right,speed);if(keys.has('a')||keys.has('ArrowLeft'))camera.position.addScaledVector(right,-speed);if(keys.has('e'))camera.position.y+=speed;if(keys.has('q'))camera.position.y-=speed;
   }else controls.update();renderer.render(scene,camera);frame=requestAnimationFrame(animate);
  }animate();
  return ()=>{
   if(walking){const dir=new T.Vector3();camera.getWorldDirection(dir);controls.target.copy(camera.position).addScaledVector(dir,3);}
   cameraState.current={key,position:camera.position.clone(),target:controls.target.clone()};cancelAnimationFrame(frame);resize.disconnect();controls.dispose();window.removeEventListener('keyup',keyup);
   scene.traverse(obj=>{const mesh=obj as T.Mesh;mesh.geometry?.dispose();if(mesh.material)for(const mat of Array.isArray(mesh.material)?mesh.material:[mesh.material]){(mat as T.SpriteMaterial).map?.dispose();mat.dispose();}});renderer.dispose();renderer.domElement.remove();apiRef.current=null;meshesRef.current=[];
  };
 },[model,floor,plan,route,hideWalls,showSpaces,showLabels,showMarkers,hideRoof,assumptions,separation,section,cut,walking]);
 useEffect(()=>{for(const mesh of meshesRef.current)(mesh.material as T.MeshStandardMaterial).color.setHex(mesh.userData.id===selected?0x22a2bd:mesh.userData.baseColor);},[selected]);
 const fs=model.floors.find(f=>f.id===floor)?.id??model.floors[0].id;
 const els=model.elements.filter(e=>e.floor_id===fs&&!e.excluded&&(!hideWalls||e.type!=='wall')&&(!hideRoof||e.type!=='roof')&&(!e.source.marker_width_m||showMarkers)&&(!['space','corridor'].includes(e.type)||showSpaces));
 const b=els.length?bounds(els.map(raw)):{min:[0,0] as XY,max:[20,12] as XY};
 return <div className="viewer-wrap"><div className="bim-view-options" aria-label="BIM 조작 도구" ref={toolsHost}>
  <div className="camera-tools"><button aria-label="전체 맞춤" title="현재 층의 전체 모델 맞춤" disabled={fallback} onClick={()=>{setWalking(false);apiRef.current?.fit();}}><Maximize size={16}/><span>전체 맞춤</span></button><button aria-label="선택 확대" title="선택 객체 확대" disabled={!selected||plan||fallback} onClick={()=>{setWalking(false);apiRef.current?.focus(selected);}}><Focus size={16}/><span>선택 확대</span></button>
  <button aria-label={walking?'실내 시점 종료':'실내 시점'} title="실내 자유 시점 · WASD 이동" disabled={plan||fallback} aria-pressed={walking} className={walking?'active':''} onClick={()=>{if(!walking)apiRef.current?.interior();setWalking(!walking);}}><PersonStanding size={16}/><span>{walking?'실내 종료':'실내 시점'}</span></button></div>
  <div className="advanced-tools"><button aria-label="표시 설정" title="표시 설정" aria-expanded={tool==='display'} aria-controls="display-options" className={tool==='display'?'active':''} onClick={()=>setTool(tool==='display'?null:'display')}><Settings2 size={16}/><span>표시 설정</span></button><button aria-label="단면 · 층 분리" title="단면 · 층 분리" aria-expanded={tool==='section'} aria-controls="section-options" className={tool==='section'||section!=='none'||separation>0?'active':''} onClick={()=>setTool(tool==='section'?null:'section')}><Scissors size={16}/><span>단면 · 층 분리</span></button></div>
  {tool==='display'&&<div className="tool-popover" id="display-options"><h3><Settings2 size={16}/>모델 표시</h3>
   <label><span>벽체 표시</span><input type="checkbox" checked={!hideWalls} onChange={e=>setHideWalls(!e.target.checked)}/></label><label><span>지붕 표시</span><input type="checkbox" checked={!hideRoof} onChange={e=>setHideRoof(!e.target.checked)}/></label>
   <label><span>실 영역</span><input type="checkbox" checked={showSpaces} onChange={e=>setShowSpaces(e.target.checked)}/></label><label><span>실명</span><input type="checkbox" checked={showLabels} onChange={e=>setShowLabels(e.target.checked)}/></label><label><span>미확정 면</span><input type="checkbox" checked={showMarkers} onChange={e=>setShowMarkers(e.target.checked)}/></label>
   <label><span>임시 조립체 입체 표시</span><input type="checkbox" checked={assumptions} onChange={e=>setAssumptions(e.target.checked)}/></label><p>표시 설정은 원본 형상과 저장 데이터를 변경하지 않습니다.</p></div>}
  {tool==='section'&&<div className="tool-popover" id="section-options"><h3><Layers size={16}/>단면 · 층 분리</h3><label><span>층 분리 간격</span><output>{separation} m</output></label><input aria-label="층 분리 간격" type="range" min="0" max="12" step="1" value={separation} onChange={e=>setSeparation(Number(e.target.value))}/><label><span>단면 방향</span><select aria-label="단면 방향" value={section} onChange={e=>setSection(e.target.value)}><option value="none">없음</option><option value="x">X 방향</option><option value="y">Y 방향</option><option value="z">높이 Z</option></select></label>
   {section!=='none'&&<><label><span>단면 위치</span><output>{cut}%</output></label><input aria-label="단면 위치" type="range" min="0" max="100" value={cut} onChange={e=>setCut(Number(e.target.value))}/></>}<button className="full" onClick={()=>{setSection('none');setSeparation(0);setCut(50);}}>단면 · 분리 초기화</button></div>}
 </div>{assumptions&&!model.is_example&&<details className="viewer-caution"><summary><TriangleAlert size={14}/>임시 치수 포함 · 도면 검토 필요</summary><p>슬래브·마감·참·문틀·창틀·샤프트는 검토 후보입니다. JSON/IFC에도 미확정 근거를 보존합니다. 선택 객체에서 치수와 근거를 확인하세요.</p></details>}
 {walking&&<p className="walk-help">화면 클릭 후 WASD: 전후좌우 · Q/E: 높이 · 드래그: 둘러보기. 자유 시점이며 통행 가능 여부를 판정하지 않습니다.</p>}
 <div className="viewer" ref={host} aria-label={`${model.name} ${plan?'평면':'3D'} 모델`}>
 {fallback&&<div className="fallback"><p>WebGL을 사용할 수 없어 평면도로 표시합니다. 전체 층에서는 {model.floors.find(f=>f.id===fs)?.name}을 표시합니다.</p><svg viewBox={`${b.min[0]-1} ${b.min[1]-1} ${b.max[0]-b.min[0]+2} ${b.max[1]-b.min[1]+2}`} role="img" aria-label="건축물 평면도">
  {els.map(e=><path key={e.id} d={raw(e).map(r=>'M'+r.map(p=>p.join(',')).join('L')+'Z').join(' ')} fill={e.id===selected?'#22a2bd':'#'+(colors[e.type]??0xaaaaaa).toString(16).padStart(6,'0')} fillOpacity={['space','corridor'].includes(e.type)?.3:1} fillRule="evenodd" stroke="#607982" strokeWidth=".035" onClick={()=>onSelect(e.id)}/>)}
 </svg></div>}</div></div>;
}
