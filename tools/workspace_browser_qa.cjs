// Current public-model UI and retirement migration checks in an isolated browser.
const fs=require('node:fs'),path=require('node:path'),os=require('node:os'),http=require('node:http'),assert=require('node:assert/strict');
const {chromium}=require(process.env.UI_QA_MODULE||path.join(os.tmpdir(),'spatial-bim-qa/node_modules/playwright'));
const base='/energy-center-bim-bf/',dist=path.resolve('web/dist');
(async()=>{
 let server,browser;
 try{
  let origin=process.env.BIM_QA_URL;
  if(!origin){
   server=http.createServer((req,res)=>{
    const url=new URL(req.url,'http://localhost');
    if(!url.pathname.startsWith(base)){res.writeHead(404);res.end();return;}
    const target=path.resolve(dist,decodeURIComponent(url.pathname.slice(base.length))||'index.html');
    if(!target.startsWith(dist+path.sep)){res.writeHead(403);res.end();return;}
    const types={'.html':'text/html','.js':'text/javascript','.css':'text/css','.json':'application/json','.woff2':'font/woff2','.svg':'image/svg+xml'};
    fs.readFile(target,(err,data)=>{res.writeHead(err?404:200,{'Content-Type':types[path.extname(target)]||'application/octet-stream'});res.end(err?'missing':data);});
   });
   await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
   origin='http://127.0.0.1:'+server.address().port+base;
  }
  browser=await chromium.launch({channel:'chrome',headless:true,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});
  const context=await browser.newContext({viewport:{width:1600,height:1000}}),page=await context.newPage();
  const errors=[],badRequests=[],apiRequests=[],retiredRequests=[];
  page.on('pageerror',e=>errors.push(e.message));page.on('response',r=>{if(r.status()>=400)badRequests.push({url:r.url(),status:r.status()})});page.on('request',r=>{const url=new URL(r.url());if(url.pathname.includes('/api/'))apiRequests.push(r.url());if(/models\/(?:demo\.json|project\.json|coordination-baseline(?:-(?:draft|verified))?\.(?:json|ifc))$/.test(url.pathname))retiredRequests.push(r.url())});
  await page.goto(origin,{waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>document.querySelector('select[aria-label="BIM 건축물"]')?.value==='energy-center-precision-rebuild'&&Number(document.querySelector('.viewer canvas')?.dataset.triangles)>0,null,{timeout:90000});
  assert.equal(await page.locator('.fallback').count(),0);
  const rendered=await page.locator('.viewer canvas').evaluate(c=>({triangles:c.dataset.triangles,components:c.dataset.modelComponents,modelVersion:c.dataset.modellingVersion}));
  const current=JSON.parse(fs.readFileSync('web/public/models/precision-rebuild.json','utf8'));
  assert.equal(rendered.components,String(current.elements.reduce((n,e)=>n+e.components.length,0)));
  assert.equal(rendered.modelVersion,String(current.provenance.modelling_version));
  assert.equal(await page.getByRole('button',{name:'개선 전 모델 비교',exact:true}).count(),0);
  assert.equal(await page.getByRole('button',{name:'정밀 1층 검토',exact:true}).count(),0);
  await page.getByRole('button',{name:'공간 경계 검증',exact:true}).click();
  await page.getByRole('dialog',{name:'BF 공간 경계 검증'}).waitFor();
  assert((await page.getByTestId('spatial-summary').innerText()).includes('확인 공간 0 / 31'));
  assert(await page.getByRole('img',{name:'CAD와 BF 공간 경계 중첩'}).locator('polyline').count()>0);
  assert.equal(await page.getByRole('button',{name:'JSON 편집 적용',exact:true}).count(),0);
  await page.getByRole('button',{name:'닫기',exact:true}).click();
  await page.getByRole('button',{name:'표시 설정',exact:true}).click();
  await page.getByLabel('검증 상태 표시').selectOption('verified');
  await page.waitForFunction(()=>document.querySelector('.viewer canvas')?.dataset.evidenceMode==='verified'&&document.querySelector('.viewer canvas')?.dataset.displayedElements==='0');
  await page.getByLabel('검증 상태 표시').selectOption('full');
  await page.waitForFunction(()=>Number(document.querySelector('.viewer canvas')?.dataset.triangles)>0);
  await page.getByRole('heading',{level:1}).click();
  assert.equal(await page.getByLabel('BIM 건축물').locator('option').count(),1);
  await page.getByRole('button',{name:'BF 경로 탐색',exact:true}).click();
  await page.getByRole('button',{name:'경로 탐색',exact:true}).click();
  await page.getByText('경로 없음',{exact:true}).waitFor({timeout:30000});
  const bf='no_path';
  await page.getByRole('button',{name:'BIM 모델',exact:true}).click();
  // Seed retired records in this isolated test context and verify the migration.
  await page.evaluate(async()=>{
   localStorage.setItem('space-link-model',JSON.stringify({id:'energy-center-coordination-baseline'}));
   localStorage.setItem('space-link-model-previous',JSON.stringify({id:'energy-center-actual-1f2f-previous-0'}));
   const db=await new Promise((resolve,reject)=>{const r=indexedDB.open('space-link-bim',1);r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error)});
   await new Promise((resolve,reject)=>{const tx=db.transaction('models','readwrite');tx.objectStore('models').put(JSON.stringify({id:'energy-center-actual-1f2f'}),'current');tx.objectStore('models').put(JSON.stringify({id:'energy-center-coordination-baseline-saved'}),'previous');tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error)});
   db.close();
  });
  await page.reload({waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>document.querySelector('select[aria-label="BIM 건축물"]')?.value==='energy-center-precision-rebuild'&&Number(document.querySelector('.viewer canvas')?.dataset.triangles)>0,null,{timeout:90000});
  assert.equal(await page.getByLabel('BIM 건축물').locator('option').count(),1);
  assert(await page.evaluate(async()=>{
   if(localStorage.getItem('space-link-model')!==null||localStorage.getItem('space-link-model-previous')!==null)return false;
   const db=await new Promise((resolve,reject)=>{const r=indexedDB.open('space-link-bim',1);r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error)});
   const values=await Promise.all(['current','previous'].map(key=>new Promise(resolve=>{const r=db.transaction('models','readonly').objectStore('models').get(key);r.onsuccess=()=>resolve(r.result)})));
   db.close();return values.every(value=>value===undefined);
  }));
  const output=path.join(os.tmpdir(),'EnergyCenterSingleModelQA-20261011');fs.mkdirSync(output,{recursive:true});
  const phase=process.env.BIM_QA_URL?'live':'local';
  await page.screenshot({path:path.join(output,phase+'-desktop.png'),fullPage:true});
  await page.setViewportSize({width:390,height:844});
  await page.reload({waitUntil:'domcontentloaded'});
  await page.waitForFunction(()=>document.querySelector('select[aria-label="BIM 건축물"]')?.value==='energy-center-precision-rebuild'&&Number(document.querySelector('.viewer canvas')?.dataset.triangles)>0,null,{timeout:90000});
  await page.waitForFunction(()=>document.querySelector('.viewer canvas')?.getBoundingClientRect().width>0);
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1));
  await page.screenshot({path:path.join(output,phase+'-mobile.png'),fullPage:true});
  assert.deepEqual(errors,[]);assert.deepEqual(badRequests,[]);assert.deepEqual(apiRequests,[]);assert.deepEqual(retiredRequests,[]);
  const result={status:'passed',origin,rendered,bf,errors,badRequests,apiRequests,desktopAndMobile:true,singleBuiltInModel:true,retiredStoragePurged:true,precisionFirstFloorRemoved:true,spatialCadReview:true};
  fs.writeFileSync(path.join(output,phase+'-results.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
 }finally{if(browser)await browser.close();if(server)await new Promise(resolve=>server.close(resolve));}
})().catch(e=>{console.error(e);process.exitCode=1});
