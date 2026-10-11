// Large BIM models exceed localStorage quotas once an earlier model is retained.
// Store user revisions atomically; remove retired built-in records on load.
const legacyCurrent='space-link-model',legacyPrevious='space-link-model-previous';
const retiredIds=['demo-two-storey','energy-center-actual-1f2f','energy-center-coordination-baseline'];
export function isRetiredModel(model:{id:string}){
 return retiredIds.some(id=>model.id===id||model.id.startsWith(id+'-'));
}
function retired(payload:string|null){
 if(!payload)return false;
 try{const model=JSON.parse(payload);return typeof model?.id==='string'&&isRetiredModel(model);}catch{return false;}
}
function local(key:string){try{return localStorage.getItem(key);}catch{return null;}}
function open():Promise<IDBDatabase>{return new Promise((resolve,reject)=>{
 if(typeof indexedDB==='undefined'){reject(Error('IndexedDB unavailable'));return;}
 const req=indexedDB.open('space-link-bim',1);let blocked=false;
 req.onupgradeneeded=()=>{if(!req.result.objectStoreNames.contains('models'))req.result.createObjectStore('models');};
 req.onsuccess=()=>{if(blocked){req.result.close();return;}resolve(req.result);};req.onerror=()=>reject(req.error);
 req.onblocked=()=>{blocked=true;reject(Error('모델 저장소가 다른 창에서 사용 중입니다.'));};
});}
function read(db:IDBDatabase,key:string):Promise<string|null>{return new Promise((resolve,reject)=>{
 const req=db.transaction('models','readonly').objectStore('models').get(key);
 req.onsuccess=()=>resolve(typeof req.result==='string'?req.result:null);req.onerror=()=>reject(req.error);
});}
export async function loadModelRecords(){
 for(const key of [legacyCurrent,legacyPrevious]){
  if(retired(local(key)))try{localStorage.removeItem(key);}catch{}
 }
 const retain=(payload:string|null)=>retired(payload)?null:payload;
 const legacy=retain(local(legacyCurrent)),older=retain(local(legacyPrevious));let current:string|null=null,previous:string|null=null;
 try{const db=await open();try{
  [current,previous]=await Promise.all([read(db,'current'),read(db,'previous')]);
  const keys=[retired(current)?'current':null,retired(previous)?'previous':null].filter((key):key is string=>key!==null);
  if(keys.length)await new Promise<void>((resolve,reject)=>{
   const tx=db.transaction('models','readwrite');for(const key of keys)tx.objectStore('models').delete(key);
   tx.oncomplete=()=>resolve();tx.onabort=()=>reject(tx.error);tx.onerror=()=>reject(tx.error);
  });
 }finally{db.close();}}catch{}
 current=retain(current);previous=retain(previous);
 return {current:current??legacy,previous:[...new Set([previous,older,current?legacy:null].filter((s):s is string=>s!==null&&s!==(current??legacy)))]};
}
export async function saveModelRecord(payload:string){
 if(retired(payload))throw Error('삭제된 기본 모델은 다시 저장할 수 없습니다.');
 let db:IDBDatabase;
 try{db=await open();}catch{
  const previous=local(legacyCurrent);
  if(previous&&previous!==payload&&!local(legacyPrevious))localStorage.setItem(legacyPrevious,previous);
  localStorage.setItem(legacyCurrent,payload);return;
 }
 try{await new Promise<void>((resolve,reject)=>{
  const tx=db.transaction('models','readwrite'),store=tx.objectStore('models');
  const old=store.get('current'),backup=store.get('previous');
  // Requests complete in order within one transaction; abort preserves both keys.
  backup.onsuccess=()=>{
   const previous=typeof old.result==='string'?old.result:local(legacyCurrent);
   if(!backup.result&&previous&&previous!==payload)store.put(previous,'previous');
   store.put(payload,'current');
  };
  tx.oncomplete=()=>resolve();tx.onabort=()=>reject(tx.error??Error('모델 저장에 실패했습니다.'));
  tx.onerror=()=>reject(tx.error??Error('모델 저장에 실패했습니다.'));
 });}finally{db.close();}
}
