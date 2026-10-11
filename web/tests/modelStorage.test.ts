import {afterEach,beforeEach,describe,it,expect,vi} from 'vitest';
import {IDBFactory,IDBDatabase} from 'fake-indexeddb';
import {loadModelRecords,saveModelRecord} from '../src/modelStorage';
let legacy:Map<string,string>;
beforeEach(()=>{
 legacy=new Map([['space-link-model','old-model'],['space-link-model-previous','older-model']]);
 vi.stubGlobal('indexedDB',new IDBFactory());
 vi.stubGlobal('localStorage',{getItem:(key:string)=>legacy.get(key)??null,setItem:vi.fn((key:string,value:string)=>legacy.set(key,value)),removeItem:vi.fn((key:string)=>legacy.delete(key))});
});
afterEach(()=>{vi.restoreAllMocks();vi.unstubAllGlobals();});
describe('BIM model persistence',()=>{
 it('removes retired built-in models from legacy keys and IndexedDB without reviving their backups',async()=>{
  const db=await new Promise<IDBDatabase>((resolve,reject)=>{const req=indexedDB.open('space-link-bim',1);req.onupgradeneeded=()=>req.result.createObjectStore('models');req.onsuccess=()=>resolve(req.result);req.onerror=()=>reject(req.error);});
  await new Promise<void>((resolve,reject)=>{const tx=db.transaction('models','readwrite');tx.objectStore('models').put(JSON.stringify({id:'demo-two-storey'}),'current');tx.objectStore('models').put(JSON.stringify({id:'energy-center-actual-1f2f-saved'}),'previous');tx.oncomplete=()=>resolve();tx.onerror=()=>reject(tx.error);});
  legacy.set('space-link-model',JSON.stringify({id:'demo-two-storey-previous-0'}));
  legacy.set('space-link-model-previous',JSON.stringify({id:'energy-center-actual-1f2f'}));
  expect(await loadModelRecords()).toEqual({current:null,previous:[]});
  expect(legacy.size).toBe(0);
  for(const key of ['current','previous'])expect(await new Promise(resolve=>{const req=db.transaction('models','readonly').objectStore('models').get(key);req.onsuccess=()=>resolve(req.result);})).toBeUndefined();
  db.close();
  await expect(saveModelRecord(JSON.stringify({id:'demo-two-storey'}))).rejects.toThrow('삭제된 기본 모델');
 });
 it('keeps the latest model and unrelated saved models while removing a retired local backup',async()=>{
  const payload=JSON.stringify({id:'energy-center-precision-rebuild'});
  legacy.set('space-link-model-previous',JSON.stringify({id:'energy-center-actual-1f2f'}));
  await saveModelRecord(payload);
  expect(await loadModelRecords()).toEqual({current:payload,previous:['old-model']});
  expect(legacy.get('space-link-model')).toBe('old-model');
 });
 it('saves large models without touching legacy records and retains the first previous revision',async()=>{
  const payload=JSON.stringify({note:'x'.repeat(3*1024*1024)});
  await saveModelRecord(payload);
  expect(await loadModelRecords()).toEqual({current:payload,previous:['old-model','older-model']});
  await saveModelRecord('next-model');
  expect(await loadModelRecords()).toEqual({current:'next-model',previous:['old-model','older-model']});
  expect(localStorage.setItem).not.toHaveBeenCalled();
 });
 it('preserves the current model and backup if a write transaction is aborted',async()=>{
  await saveModelRecord('saved-model');
  const transaction=IDBDatabase.prototype.transaction;
  vi.spyOn(IDBDatabase.prototype,'transaction').mockImplementationOnce(function(this:IDBDatabase,names:string|Iterable<string>,mode?:IDBTransactionMode,options?:IDBTransactionOptions){
   const tx=transaction.call(this,names,mode,options);queueMicrotask(()=>tx.abort());return tx;
  });
  await expect(saveModelRecord('failed-model')).rejects.toBeTruthy();
  expect(await loadModelRecords()).toEqual({current:'saved-model',previous:['old-model','older-model']});
 });
 it('reads and saves through existing keys when IndexedDB is unavailable',async()=>{
  vi.stubGlobal('indexedDB',undefined);
  expect(await loadModelRecords()).toEqual({current:'old-model',previous:['older-model']});
  await saveModelRecord('small-model');
  expect(await loadModelRecords()).toEqual({current:'small-model',previous:['older-model']});
 });
 it('reports fallback quota failure without overwriting the existing model',async()=>{
  vi.stubGlobal('indexedDB',undefined);
  vi.mocked(localStorage.setItem).mockImplementation(()=>{throw new DOMException('Full','QuotaExceededError');});
  await expect(saveModelRecord('too-large')).rejects.toThrow('Full');
  expect((await loadModelRecords()).current).toBe('old-model');
 });
});
