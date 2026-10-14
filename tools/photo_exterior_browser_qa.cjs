// Own-app regression: isolated Chrome storage, production assets and WebGL.
const fs=require('node:fs'),path=require('node:path'),os=require('node:os'),http=require('node:http'),assert=require('node:assert/strict');
const {chromium}=require(process.env.UI_QA_MODULE||path.join(os.tmpdir(),'spatial-bim-qa/node_modules/playwright'));
const root=path.resolve('web/dist'),out=path.resolve('cad_output/precision-rebuild/coordination-v2/browser-photo-exterior');
(async()=>{
 let server,browser;const screens=[],errors=[],badRequests=[];fs.mkdirSync(out,{recursive:true});
 try{
  const model=JSON.parse(fs.readFileSync(process.env.BIM_QA_MODEL_PATH||'web/public/models/precision-rebuild.json','utf8'));
  assert.equal(model.revision,12);
  assert(model.elements.every(e=>e.components.every(c=>!/^photo_(?:rooftop_pv|outdoor_pv|parking_|pv_support)/.test(c.role))));
  const base='/energy-center-bim-bf/';let origin=process.env.BIM_QA_URL;
  if(!origin){server=http.createServer((req,res)=>{
   const pathname=new URL(req.url,'http://localhost').pathname;
   if(!pathname.startsWith(base)){res.writeHead(404);res.end();return;}
   const file=path.resolve(root,decodeURIComponent(pathname.slice(base.length))||'index.html');
   if(!file.startsWith(root+path.sep)){res.writeHead(403);res.end();return;}
   fs.readFile(file,(err,data)=>{res.writeHead(err?404:200,{'Content-Type':{'.html':'text/html','.js':'text/javascript','.css':'text/css','.json':'application/json','.svg':'image/svg+xml'}[path.extname(file)]||'application/octet-stream'});res.end(err?'missing':data)});
  });await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));origin='http://127.0.0.1:'+server.address().port+base;}
  browser=await chromium.launch({channel:'chrome',headless:true,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});
  const context=await browser.newContext({viewport:{width:1600,height:1000}}),page=await context.newPage();
  if(process.env.BIM_QA_MODEL_PATH)await page.route('**/models/precision-rebuild.json',route=>route.fulfill({json:model}));
  page.on('pageerror',e=>errors.push(e.message));page.on('response',r=>{if(r.status()>=400)badRequests.push({url:r.url(),status:r.status()})});
  const canvas=page.locator('.viewer canvas');
  const ready=()=>page.waitForFunction(()=>Number(document.querySelector('.viewer canvas')?.dataset.triangles)>0,null,{timeout:90000});
  async function screen(name){await ready();const heading=page.getByRole('heading',{level:1});if(await heading.isVisible())await heading.click();await page.screenshot({path:path.join(out,name+'.png')});screens.push({name,...await canvas.evaluate(c=>({...c.dataset}))});console.log('screen',name);}
  async function tools(name){const b=page.getByRole('button',{name,exact:true});if(await b.getAttribute('aria-expanded')!=='true')await b.click();}
  await page.goto(origin,{waitUntil:'domcontentloaded'});await ready();
  assert.equal(await canvas.getAttribute('data-modelling-version'),'15');assert.equal(await page.locator('.fallback').count(),0);
  await screen('exterior');
  for(const view of ['front','right','top']){await tools('표시 설정');await page.getByLabel('뷰 방향',{exact:true}).selectOption(view);await screen('view-'+view);}
  await tools('표시 설정');await page.getByLabel('뷰 방향',{exact:true}).selectOption('building');
  const photo=model.elements.find(e=>e.source.photo_reference&&e.components[0].role==='photo_bipv_module');
  await page.getByLabel('객체 검색').fill(photo.id);await page.locator(`.object-row[title$="${photo.id}"]`).click();
  assert((await page.locator('.architectural-properties').innerText()).includes('사진 기반 외관'));
  assert.equal(await page.getByRole('link',{name:'사진 출처',exact:true}).getAttribute('href'),photo.source.photo_reference.url);
  await screen('photo-evidence');await page.getByLabel('객체 검색').fill('');
  for(const fid of ['f1','f3','roof']){await page.getByLabel('표시 층').selectOption(fid);await screen('floor-'+fid);}
  await tools('표시 설정');await page.getByLabel('검증 상태 표시').selectOption('verified');
  await page.waitForFunction(()=>document.querySelector('.viewer canvas')?.dataset.displayedElements==='0');
  await page.getByLabel('검증 상태 표시').selectOption('full');
  await page.getByLabel('표시 층').selectOption('all');
  await page.getByRole('button',{name:'공간 경계 검증',exact:true}).click();
  assert((await page.getByTestId('spatial-summary').innerText()).includes('확인 공간 0 / 31'));
  await page.getByRole('button',{name:'닫기',exact:true}).click();
  for(const width of [390,320]){await page.setViewportSize({width,height:844});await screen('mobile-'+width);assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));}
  assert.deepEqual(errors,[]);assert.deepEqual(badRequests,[]);
  fs.writeFileSync(path.join(out,'results.json'),JSON.stringify({status:'passed',origin,screens,errors,badRequests},null,2));
  console.log(JSON.stringify({status:'passed',screens:screens.length,errors,badRequests}));
 }finally{await browser?.close();await new Promise(resolve=>server?server.close(resolve):resolve());}
})().catch(e=>{console.error(e);process.exitCode=1});
