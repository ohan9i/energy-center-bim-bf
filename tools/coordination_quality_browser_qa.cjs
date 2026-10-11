// Fresh local production assets, real Chrome WebGL, isolated user storage.
const fs=require('node:fs'),path=require('node:path'),os=require('node:os'),http=require('node:http'),assert=require('node:assert/strict');
const {chromium}=require(process.env.UI_QA_MODULE||path.join(os.tmpdir(),'spatial-bim-qa/node_modules/playwright'));
const root=path.resolve('web/dist'),out=path.resolve('cad_output/precision-rebuild/coordination-v2/browser-current');
(async()=>{
 let server,browser;const screens=[],errors=[],badRequests=[];
 fs.mkdirSync(out,{recursive:true});
 try{
  const model=JSON.parse(fs.readFileSync('web/public/models/precision-rebuild.json','utf8'));
  assert.equal(model.provenance.modelling_version,9);
  const base='/energy-center-bim-bf/';
  let origin=process.env.BIM_QA_URL;
  if(!origin){server=http.createServer((req,res)=>{
   const pathname=new URL(req.url,'http://localhost').pathname;
   if(!pathname.startsWith(base)){res.writeHead(404);res.end();return;}
   const file=path.resolve(root,decodeURIComponent(pathname.slice(base.length))||'index.html');
   if(!file.startsWith(root+path.sep)){res.writeHead(403);res.end();return;}
   const mime={'.html':'text/html','.js':'text/javascript','.css':'text/css','.json':'application/json','.ifc':'application/x-step','.woff2':'font/woff2','.svg':'image/svg+xml'};
   fs.readFile(file,(err,data)=>{res.writeHead(err?404:200,{'Content-Type':mime[path.extname(file)]||'application/octet-stream'});res.end(err?'missing':data)});
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  origin='http://127.0.0.1:'+server.address().port+base;}
  browser=await chromium.launch({channel:'chrome',headless:true,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});
  const context=await browser.newContext({viewport:{width:1600,height:1000}}),page=await context.newPage();
  page.on('pageerror',e=>errors.push(e.message));page.on('response',r=>{if(r.status()>=400)badRequests.push({url:r.url(),status:r.status()})});
  const canvas=page.locator('.viewer canvas');
  const ready=()=>page.waitForFunction(()=>Number(document.querySelector('.viewer canvas')?.dataset.triangles)>0||Number(document.querySelector('.viewer canvas')?.dataset.nativeTraceSegments)>0,null,{timeout:90000});
  async function tools(name){const b=page.getByRole('button',{name,exact:true});if(await b.getAttribute('aria-expanded')!=='true')await b.click();}
  async function screen(name){await ready();await page.getByRole('heading',{level:1}).click();await page.screenshot({path:path.join(out,name+'.png')});
   screens.push({name,...await canvas.evaluate(c=>({triangles:Number(c.dataset.triangles),meshes:Number(c.dataset.meshes),components:Number(c.dataset.modelComponents),
    modelVersion:Number(c.dataset.modellingVersion),sectionCaps:Number(c.dataset.sectionCaps),evidenceMode:c.dataset.evidenceMode,displayedElements:Number(c.dataset.displayedElements)}))});console.log('screen',name);}
  async function range(label,value){await page.getByLabel(label,{exact:true}).evaluate((el,value)=>{
   Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(el,String(value));el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));
  },value);}
  async function download(name,file){const pending=page.waitForEvent('download');await page.getByRole('button',{name,exact:true}).click();const d=await pending;await d.saveAs(path.join(out,file));return fs.readFileSync(path.join(out,file),'utf8');}
  await page.goto(origin,{waitUntil:'domcontentloaded'});await ready();
  assert.equal(await page.getByLabel('BIM 건축물').inputValue(),model.id);
  assert.equal(await canvas.getAttribute('data-model-components'),String(model.elements.reduce((n,e)=>n+e.components.length,0)));
  assert.equal(await page.locator('.fallback').count(),0);
  if(process.argv.includes('--authoring-only')){
   const id='coord-7856c0b97b13a29f12cb';
   await page.getByLabel('표시 층').selectOption('f1');await page.getByLabel('객체 검색').fill(id);
   await page.locator(`.object-row[title$="${id}"]`).click();
   const text=await page.locator('.architectural-properties').innerText();
   assert(text.includes('AW-5 · 1.800 m × 1.600 m (도면 대조)'));
   assert(text.includes('5 + 14 + 5 mm'));
   assert(text.includes('설계 승인과 BF 통행 확인은 별도'));
   await page.getByRole('button',{name:'선택 확대',exact:true}).click();
   await page.getByRole('button',{name:'선택 객체만 보기',exact:true}).click();
   await page.getByText('적용 창호 규격 · AW-5',{exact:true}).scrollIntoViewIfNeeded();
   await screen('after-authoring-inspector-f1');
   assert.equal(errors.length,0);assert.equal(badRequests.length,0);
   fs.writeFileSync(path.join(out,'authoring-inspector-results.json'),JSON.stringify({status:'passed',screens,errors,badRequests},null,2));
   console.log(JSON.stringify({status:'passed',screens:screens.length,errors,badRequests}));return;
  }
  await screen('after-whole');
  await tools('표시 설정');await page.getByLabel('뷰 방향',{exact:true}).selectOption('front');await screen('after-front');
  assert.equal(await page.getByRole('button',{name:'개선 전 모델 비교',exact:true}).count(),0);
  assert.equal(await page.getByLabel('BIM 건축물').locator('option').count(),1);
  await tools('표시 설정');await page.getByLabel('뷰 방향',{exact:true}).selectOption('building');
  const verified=await download('IFC','verified-download.ifc');
  assert(verified.includes('IFCBUILDINGSTOREY'));
  if(model.provenance.verified_solids===0)assert(!/IFC(?:WALL|COLUMN|BEAM|SLAB|WINDOW|DOOR)\(/.test(verified));
  const draft=await download('Draft IFC','draft-download.ifc');assert(draft.includes('DRAFT - NOT DESIGN VERIFIED'));
  for(const fid of ['b1','f1','f2','f3','f4','roof','phroof']){
   if(fid==='phroof'){await tools('표시 설정');await page.getByLabel('검증 상태 표시').selectOption('drawing');}
   await page.getByLabel('표시 층').selectOption(fid);await screen('after-floor-'+fid);
  }
  await page.getByLabel('표시 층').selectOption('f1');await tools('표시 설정');await page.getByLabel('검증 상태 표시').selectOption('highlight');await screen('after-evidence-highlight');
  await tools('표시 설정');await page.getByLabel('검증 상태 표시').selectOption('verified');
  await page.waitForFunction(n=>document.querySelector('.viewer canvas')?.dataset.evidenceMode==='verified'&&Number(document.querySelector('.viewer canvas')?.dataset.displayedElements)===n,model.provenance.verified_solids);
  await page.screenshot({path:path.join(out,'after-verified-mode.png')});
  await page.getByLabel('검증 상태 표시').selectOption('full');
  const stair=model.elements.find(e=>e.floor_id==='b1'&&e.type==='stair');
  await page.getByLabel('표시 층').selectOption('b1');await page.getByLabel('객체 검색').fill(stair.id);
  await page.locator(`.object-row[title$="${stair.id}"]`).click();
  assert((await page.locator('.architectural-properties').innerText()).includes('계단 단면 치수 대조'));
  await page.getByRole('button',{name:'선택 확대',exact:true}).click();await page.getByRole('button',{name:'선택 객체만 보기',exact:true}).click();await screen('after-basement-stair');
  await page.getByRole('button',{name:'선택 객체만 보기',exact:true}).click();await page.getByLabel('객체 검색').fill('');
  await page.getByLabel('표시 층').selectOption('all');
  await tools('단면 · 층 분리');await range('층 분리 간격',3);await screen('after-separated');
  await tools('단면 · 층 분리');await page.getByRole('button',{name:'단면 · 분리 초기화',exact:true}).click();
  await page.getByLabel('단면 방향').selectOption('x');await range('단면 위치',50);await screen('after-section-x');assert(screens.at(-1).sectionCaps>0);
  await tools('단면 · 층 분리');await page.getByRole('button',{name:'단면 · 분리 초기화',exact:true}).click();
  await page.getByLabel('표시 층').selectOption('f1');await page.getByRole('button',{name:'실내 시점',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('.viewer canvas')?.dataset.walking==='true');await screen('after-interior-f1');
  await page.getByRole('button',{name:'실내 시점 종료',exact:true}).click();
  for(const [fid,id,label] of [
   ['f1','coord-e09c1449d93909693e2f','after-schedule-aw1-f1'],
   ['f1','coord-7856c0b97b13a29f12cb','after-schedule-aw5-f1'],
   ['f1','coord-159000784c09bac2d6b9','after-constrained-window-f1'],
   ['f3','coord-00088d6131cb5fe92e68','after-bent-window-f3'],
   ['f4','coord-0aa6a2cc9653d0908c64','after-bent-window-f4'],
  ]){
   await page.getByLabel('표시 층').selectOption(fid);await page.getByLabel('객체 검색').fill(id);
   await page.locator(`.object-row[title$="${id}"]`).click();
   await page.getByRole('button',{name:'선택 확대',exact:true}).click();
   await page.getByRole('button',{name:'선택 객체만 보기',exact:true}).click();await screen(label);
   await page.getByRole('button',{name:'선택 객체만 보기',exact:true}).click();await page.getByLabel('객체 검색').fill('');
  }
  await page.getByLabel('표시 층').selectOption('all');
  await page.getByRole('button',{name:'BF 경로 탐색',exact:true}).click();await page.getByRole('button',{name:'경로 탐색',exact:true}).click();await page.getByText('경로 없음',{exact:true}).waitFor({timeout:30000});
  await page.getByLabel('JSON model import').setInputFiles(path.resolve('web/tests/fixtures/navigation-model.json'));
  await page.getByRole('button',{name:'경로 탐색',exact:true}).click();await page.getByText('조건 충족 경로',{exact:true}).waitFor({timeout:30000});
  const fixtureRoute=await page.locator('.result-metrics').innerText();assert(fixtureRoute.includes('32.6'));
  await page.getByRole('button',{name:'BIM 모델',exact:true}).click();
  const fixture=JSON.parse(fs.readFileSync('web/tests/fixtures/navigation-model.json','utf8'));
  fixture.id='qa-user-preserved';fixture.name='사용자 보존 검사';
  await page.evaluate(async fixture=>{
   const db=await new Promise((resolve,reject)=>{const r=indexedDB.open('space-link-bim',1);r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error)});
   await new Promise((resolve,reject)=>{const tx=db.transaction('models','readwrite');tx.objectStore('models').put(JSON.stringify(fixture),'current');
    tx.objectStore('models').put(JSON.stringify({...fixture,id:'qa-user-previous',name:'이전 사용자 보존 검사'}),'previous');tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error)});db.close();
  },fixture);
  await page.reload({waitUntil:'domcontentloaded'});await ready();
  const ids=await page.getByLabel('BIM 건축물').locator('option').evaluateAll(options=>options.map(o=>o.value));
  assert(ids.includes('qa-user-preserved')&&ids.some(id=>id.startsWith('qa-user-previous-')));
  assert.equal(await page.getByLabel('BIM 건축물').inputValue(),model.id);
  await page.setViewportSize({width:390,height:844});await ready();assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1));await page.screenshot({path:path.join(out,'after-mobile.png')});
  assert.deepEqual(errors,[]);assert.deepEqual(badRequests,[]);
  const result={status:'passed',origin,renderBackend:'Chrome WebGL / SwiftShader',screens,errors,badRequests,bf:'no_path (unverified real building)',bfFixtureRoute:fixtureRoute,userRecordsPreserved:true,
   userStorage:'isolated context; no user records changed',verifiedSolids:model.provenance.verified_solids};
  fs.writeFileSync(path.join(out,'results.json'),JSON.stringify(result,null,2));console.log(JSON.stringify({status:'passed',screens:screens.length,errors,badRequests}));
 }catch(e){fs.writeFileSync(path.join(out,'results.json'),JSON.stringify({status:'failed',error:String(e),screens,errors,badRequests},null,2));throw e;}
 finally{if(browser)await browser.close();if(server)await new Promise(resolve=>server.close(resolve));}
})().catch(e=>{console.error(e);process.exitCode=1});
