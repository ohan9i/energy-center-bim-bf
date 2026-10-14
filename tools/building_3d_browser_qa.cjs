// Actual own-app WebGL views for manual architectural inspection.
const fs=require('node:fs'),path=require('node:path'),os=require('node:os'),http=require('node:http'),assert=require('node:assert/strict');
const {chromium}=require(process.env.UI_QA_MODULE||path.join(os.tmpdir(),'spatial-bim-qa/node_modules/playwright'));
const before=process.argv.includes('--before');
const out=path.resolve('cad_output/precision-rebuild/coordination-v2/browser-building-3d'+(before?'-before':''));
const root=path.resolve('web/dist'),base='/energy-center-bim-bf/';
(async()=>{
 let server,browser;const screens=[],errors=[],badRequests=[];fs.mkdirSync(out,{recursive:true});
 try{
  const model=JSON.parse(fs.readFileSync('web/public/models/precision-rebuild.json','utf8'));
  if(!before){assert.equal(model.revision,12);assert.equal(model.provenance.modelling_version,15);}
  server=http.createServer((req,res)=>{
   const pathname=new URL(req.url,'http://localhost').pathname;
   if(!pathname.startsWith(base)){res.writeHead(404);res.end();return;}
   const file=path.resolve(root,decodeURIComponent(pathname.slice(base.length))||'index.html');
   if(!file.startsWith(root+path.sep)){res.writeHead(403);res.end();return;}
   fs.readFile(file,(err,data)=>{res.writeHead(err?404:200,{'Content-Type':{'.html':'text/html','.js':'text/javascript','.css':'text/css','.json':'application/json','.svg':'image/svg+xml','.ifc':'application/x-step'}[path.extname(file)]||'application/octet-stream'});res.end(err?'missing':data)});
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  browser=await chromium.launch({channel:'chrome',headless:true,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});
  const context=await browser.newContext({viewport:{width:1600,height:1000}}),page=await context.newPage();
  // Model is fixed for this run even if a generator completes concurrently.
  await page.route('**/models/precision-rebuild.json',route=>route.fulfill({json:model}));
  page.on('pageerror',e=>errors.push(e.message));page.on('response',r=>{if(r.status()>=400)badRequests.push({url:r.url(),status:r.status()})});
  const canvas=page.locator('.viewer canvas');
  const ready=()=>page.waitForFunction(()=>Number(document.querySelector('.viewer canvas')?.dataset.triangles)>0,null,{timeout:90000});
  async function panel(name){const b=page.getByRole('button',{name,exact:true});if(await b.getAttribute('aria-expanded')!=='true')await b.click();}
  async function screen(name){
   await ready();const heading=page.getByRole('heading',{level:1});
   if(await heading.isVisible())await heading.click();
   await page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))));
   await page.screenshot({path:path.join(out,name+'.png')});
   const state=await canvas.evaluate(c=>({...c.dataset}));assert.equal(Number(state.modelRevision),model.revision);
   screens.push({name,...state});console.log('screen',name);
  }
  await page.goto('http://127.0.0.1:'+server.address().port+base,{waitUntil:'domcontentloaded'});await ready();
  for(const view of ['building','front','back','left','right','top']){
   await panel('표시 설정');await page.getByLabel('뷰 방향',{exact:true}).selectOption(view);await screen('whole-'+view);
  }
  for(const fid of ['f1','f3','roof']){
   await page.getByLabel('표시 층').selectOption(fid);await panel('표시 설정');
   await page.getByLabel('뷰 방향',{exact:true}).selectOption('building');await screen('floor-'+fid);
  }
  for(const fid of ['f1','f2']){
   await page.getByLabel('표시 층').selectOption(fid);await panel('표시 설정');
   await page.getByLabel('천장 구조 표시',{exact:true}).check();
   await page.waitForFunction(()=>Number(document.querySelector('.viewer canvas')?.dataset.interiorCeilingElements)>0);
   await screen('ceiling-'+fid);
   await panel('표시 설정');await page.getByLabel('천장 구조 표시',{exact:true}).uncheck();
  }
  await page.getByLabel('표시 층').selectOption('all');
  await panel('단면과 층 분리');await page.getByLabel('단면 방향',{exact:true}).selectOption('x');
  await page.getByLabel('단면 위치',{exact:true}).fill('50');await screen('whole-section-x');
  assert(Number(screens.at(-1).sectionCaps)>0);
  await panel('단면과 층 분리');await page.getByRole('button',{name:'단면과 분리 초기화',exact:true}).click();
  await page.getByLabel('단면 방향',{exact:true}).selectOption('y');
  await page.getByLabel('단면 위치',{exact:true}).fill('60');await screen('whole-section-y');
  await panel('단면과 층 분리');await page.getByRole('button',{name:'단면과 분리 초기화',exact:true}).click();
  await page.getByLabel('표시 층').selectOption('f1');
  const entry=model.elements.find(e=>e.id==='coord-48640c9874f6dd4d4424');assert(entry);
  await page.getByLabel('객체 검색').fill(entry.id);await page.locator(`.object-row[title$="${entry.id}"]`).click();
  await page.getByRole('button',{name:'선택 확대',exact:true}).click();await screen('entry-context');
  await page.getByLabel('객체 검색').fill('');
  await page.getByRole('button',{name:'실내 시점',exact:true}).click();await screen('interior-f1');
  assert(Number(await canvas.getAttribute('data-interior-ceiling-elements'))>0);
  await page.getByRole('button',{name:'실내 시점 종료',exact:true}).click();
  await page.getByLabel('표시 층').selectOption('all');
  for(const width of [390,320]){await page.setViewportSize({width,height:844});await screen('mobile-'+width);assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));}
  assert.deepEqual(errors,[]);assert.deepEqual(badRequests,[]);
  fs.writeFileSync(path.join(out,'results.json'),JSON.stringify({status:'passed',revision:model.revision,screens,errors,badRequests,
    manualArchitecturalReviewRequired:true,independentDrawingVerified:false,routeCalculated:false},null,2));
  console.log(JSON.stringify({status:'passed',revision:model.revision,screens:screens.length,errors,badRequests}));
 }finally{await browser?.close();await new Promise(resolve=>server?server.close(resolve):resolve());}
})().catch(e=>{console.error(e);process.exitCode=1});
