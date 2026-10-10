import {useEffect,useRef,useState} from 'react';
import * as T from 'three';
import {OrbitControls} from 'three/addons/controls/OrbitControls.js';
import type {Model,XY,Profile} from './model';
import {footprints,bounds,raw,type Poly} from './geometry';
import type {RouteResult} from './navigation';
import {evaluate} from './evaluation';
interface Props {model:Model;floor:string;plan:boolean;selected:string;route:RouteResult|null;profile:Profile;onSelect:(id:string)=>void}
const colors:Record<string,number>={wall:0xc8d3d5,column:0x788d93,floor:0xe8eeee,door:0x187c79,ramp:0x96b7a2,stair:0xb3a28a,elevator:0x739cad,obstacle:0x7f8b94,unclassified:0xd2b77c};
export default function Viewer({model,floor,plan,selected,route,profile,onSelect}:Props){
 const host=useRef<HTMLDivElement>(null);const selectRef=useRef(onSelect);selectRef.current=onSelect;
 const [fallback,setFallback]=useState(false);
 useEffect(()=>{
  const container=host.current;if(!container)return;
  let renderer:T.WebGLRenderer;
  try{renderer=new T.WebGLRenderer({antialias:true});setFallback(false);}catch{setFallback(true);return;}
  const scene=new T.Scene();scene.background=new T.Color(0xf5f7f7);
  const camera=new T.PerspectiveCamera(38,1,.01,2000);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio,2));renderer.outputColorSpace=T.SRGBColorSpace;
  container.append(renderer.domElement);
  const controls=new OrbitControls(camera,renderer.domElement);controls.enableDamping=true;
  const es=model.elements.filter(e=>!e.excluded&&(floor==='all'||e.floor_id===floor));
  const box=es.length?bounds(es.map(e=>raw(e))):{min:[0,0] as XY,max:[20,12] as XY};
  const cx=(box.min[0]+box.max[0])/2,cy=(box.min[1]+box.max[1])/2,size=Math.max(box.max[0]-box.min[0],box.max[1]-box.min[1],5);
  const base=model.floors.find(f=>f.id===floor)?.elevation||0;
  controls.target.set(cx,base,cy);camera.position.set(cx+(plan?0:size*.65),base+size*(plan?1.6:1.15),cy+(plan?.001:size*1.1));
  controls.maxPolarAngle=Math.PI/2-.01;controls.enableRotate=!plan;controls.update();
  scene.add(new T.HemisphereLight(0xffffff,0xc4cdd0,2.7));const light=new T.DirectionalLight(0xffffff,2.3);light.position.set(cx+15,30,cy-8);scene.add(light);
  const grid=new T.GridHelper(Math.max(30,Math.ceil(size*1.4)),Math.min(100,Math.ceil(size*1.4)),0xd3dcdf,0xe4e9eb);grid.position.set(cx,base-.18,cy);scene.add(grid);
  const selectable:T.Mesh[]=[];
  function shape(poly:Poly){const s=new T.Shape(poly[0].map(p=>new T.Vector2(p[0],-p[1])));for(const r of poly.slice(1))s.holes.push(new T.Path(r.map(p=>new T.Vector2(p[0],-p[1]))));return s;}
  for(const e of es){
   const z=model.floors.find(f=>f.id===e.floor_id)!.elevation+e.z_offset;
   if(['space','corridor'].includes(e.type))continue;
   const ev=evaluate(e,profile);let color=colors[e.type]||0xd2b77c;
   if(e.id===selected)color=0x32a7c2;else if(['door','stair','ramp','elevator','unclassified'].includes(e.type)){if(ev.status==='blocked')color=0xc2554c;else if(ev.status==='unknown')color=0xc79532;}
   for(const poly of footprints(e,model)){
    // Unknown height has a flat footprint; display never asserts an invented storey height.
    const depth=plan?(e.type==='floor'?.03:.08):(e.height??.025);
    const geo=new T.ExtrudeGeometry(shape(poly),{depth,bevelEnabled:false,steps:1});geo.rotateX(-Math.PI/2);
    const mat=new T.MeshStandardMaterial({color,roughness:.85,transparent:e.type==='door'||e.height===null,opacity:e.type==='door'?.32:e.height===null?.5:1});
    const mesh=new T.Mesh(geo,mat);mesh.position.y=z;mesh.userData.id=e.id;scene.add(mesh);selectable.push(mesh);
    const outline=new T.LineSegments(new T.EdgesGeometry(geo),new T.LineBasicMaterial({color:e.id===selected?0x087b9a:0x809398,transparent:true,opacity:.55}));outline.position.copy(mesh.position);scene.add(outline);
   }
  }
  for(const place of model.places.filter(p=>floor==='all'||p.floor_id===floor)){
   const c=document.createElement('canvas');c.width=512;c.height=96;const ctx=c.getContext('2d')!;ctx.fillStyle='#ffffff';ctx.fillRect(0,0,512,96);ctx.fillStyle='#183e48';ctx.font='600 34px sans-serif';ctx.textAlign='center';ctx.fillText(place.name,256,60);
   const tex=new T.CanvasTexture(c);const sprite=new T.Sprite(new T.SpriteMaterial({map:tex,transparent:true,depthTest:false}));sprite.position.set(place.point[0],(model.floors.find(f=>f.id===place.floor_id)!.elevation)+(plan?.35:3.2),place.point[1]);sprite.scale.set(3.6,.675,1);scene.add(sprite);
  }
  if(route?.status==='found'){
   for(let i=1;i<route.points.length;i++){const a=route.points[i-1],b=route.points[i];if(floor!=='all'&&(a.floor!==floor||b.floor!==floor))continue;
    const za=model.floors.find(f=>f.id===a.floor)!.elevation+.12,zb=model.floors.find(f=>f.id===b.floor)!.elevation+.12;
    const start=new T.Vector3(a.point[0],za,a.point[1]),end=new T.Vector3(b.point[0],zb,b.point[1]);
    if(start.distanceTo(end)<1e-6)continue;
    const geo=new T.CylinderGeometry(.045,.045,start.distanceTo(end),8);const mesh=new T.Mesh(geo,new T.MeshBasicMaterial({color:a.floor===b.floor?0x0d9087:0x6366b6,depthTest:false}));mesh.position.copy(start).add(end).multiplyScalar(.5);mesh.quaternion.setFromUnitVectors(new T.Vector3(0,1,0),end.clone().sub(start).normalize());mesh.renderOrder=10;scene.add(mesh);
   }
  }
  let down:[number,number]|null=null;const pointerDown=(e:PointerEvent)=>{down=[e.clientX,e.clientY];};
  const pointerUp=(e:PointerEvent)=>{if(!down||Math.hypot(e.clientX-down[0],e.clientY-down[1])>5)return;const r=renderer.domElement.getBoundingClientRect();const ray=new T.Raycaster();ray.setFromCamera(new T.Vector2((e.clientX-r.left)/r.width*2-1,-(e.clientY-r.top)/r.height*2+1),camera);const hit=ray.intersectObjects(selectable).find(x=>model.elements.find(el=>el.id===x.object.userData.id)?.type!=='floor');if(hit)selectRef.current(hit.object.userData.id);};
  renderer.domElement.addEventListener('pointerdown',pointerDown);renderer.domElement.addEventListener('pointerup',pointerUp);
  const resize=new ResizeObserver(()=>{const w=container.clientWidth,h=container.clientHeight;camera.aspect=w/h;camera.updateProjectionMatrix();renderer.setSize(w,h);});resize.observe(container);
  let frame=0;function animate(){controls.update();renderer.render(scene,camera);frame=requestAnimationFrame(animate);}animate();
  return ()=>{cancelAnimationFrame(frame);resize.disconnect();controls.dispose();renderer.domElement.removeEventListener('pointerdown',pointerDown);renderer.domElement.removeEventListener('pointerup',pointerUp);scene.traverse(obj=>{const mesh=obj as T.Mesh;if(mesh.geometry)mesh.geometry.dispose();if(mesh.material){for(const mat of Array.isArray(mesh.material)?mesh.material:[mesh.material]){const map=(mat as T.SpriteMaterial).map;map?.dispose();mat.dispose();}}});renderer.dispose();renderer.domElement.remove();};
 },[model,floor,plan,selected,route,profile]);
 const fs=model.floors.find(f=>f.id===floor)?.id||model.floors[0].id;
 const els=model.elements.filter(e=>e.floor_id===fs&&!e.excluded);const b=els.length?bounds(els.map(raw)):{min:[0,0] as XY,max:[20,12] as XY};
 return <div className="viewer" ref={host} role="img" aria-label={`${model.name} ${plan?'평면':'3D'} 모델. 객체 선택은 좌측 객체 목록에서도 가능합니다.`}>{fallback&&<div className="fallback"><p>WebGL을 사용할 수 없어 평면도로 표시합니다.</p><svg viewBox={`${b.min[0]-1} ${b.min[1]-1} ${b.max[0]-b.min[0]+2} ${b.max[1]-b.min[1]+2}`} role="img" aria-label="건축물 평면도">{els.filter(e=>!['space','corridor'].includes(e.type)).flatMap(e=>footprints(e,model).map((poly,i)=><path key={e.id+i} d={poly.map(r=>'M'+r.map(p=>p.join(',')).join('L')+'Z').join(' ')} fill={e.id===selected?'#32a7c2':'#'+(colors[e.type]||0xaaaaaa).toString(16)} fillRule="evenodd" stroke="#607982" strokeWidth=".035" onClick={()=>onSelect(e.id)}/>))}{route?.points.slice(1).map((p,i)=>{const a=route.points[i];return a.floor===fs&&p.floor===fs?<line key={i} x1={a.point[0]} y1={a.point[1]} x2={p.point[0]} y2={p.point[1]} stroke="#07877d" strokeWidth=".12"/>:null;})}</svg></div>}</div>;
}
