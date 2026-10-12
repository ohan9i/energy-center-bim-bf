// Run from the repo root with UI_QA_MODULE pointing at an installed Playwright.
const fs=require('node:fs'),path=require('node:path'),http=require('node:http'),assert=require('node:assert/strict');
const {chromium}=require(process.env.UI_QA_MODULE||path.resolve('.runtime/qa/node_modules/playwright'));
const root=path.resolve('web/dist'),out=path.resolve('cad_output/ceiling-review');
(async()=>{
 let browser,server;
 const errors=[];
 try{
  fs.mkdirSync(out,{recursive:true});
  server=http.createServer((req,res)=>{
   const name=decodeURIComponent(new URL(req.url,'http://local').pathname).replace(/^\/energy-center-bim-bf\//,'');
   const base=name.startsWith('models/')?path.resolve('web/public'):root;
   const file=path.resolve(base,name||'index.html');
   if(!file.startsWith(base+path.sep)){res.writeHead(403);res.end();return;}
   fs.readFile(file,(err,data)=>{res.writeHead(err?404:200,{'Content-Type':({'.html':'text/html','.js':'text/javascript','.css':'text/css','.json':'application/json','.woff2':'font/woff2','.svg':'image/svg+xml'})[path.extname(file)]||'application/octet-stream'});res.end(err?'missing':data);});
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  browser=await chromium.launch({channel:process.env.UI_QA_CHANNEL||'msedge',headless:true,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});
  const page=await browser.newPage({viewport:{width:1440,height:1000}});
  page.on('pageerror',e=>errors.push(e.message));
  await page.goto(`http://127.0.0.1:${server.address().port}/energy-center-bim-bf/`);
  const canvas=page.locator('.viewer canvas');
  const ready=()=>page.waitForFunction(()=>Number(document.querySelector('.viewer canvas')?.dataset.triangles)>0,null,{timeout:90000});
  const settings=async()=>{const b=page.getByRole('button',{name:'표시 설정',exact:true});if(await b.getAttribute('aria-expanded')!=='true')await b.click();};
  await ready();
  const model=JSON.parse(fs.readFileSync('web/public/models/precision-rebuild.json','utf8'));
  const results=[];
  for(const fid of ['f1','f2']){
   await page.getByLabel('표시 층').selectOption(fid);await ready();
   await settings();await page.getByLabel('천장 구조 표시',{exact:true}).uncheck();await ready();
   const before=Number(await canvas.getAttribute('data-displayed-elements'));
   await page.getByLabel('천장 구조 표시',{exact:true}).check();await ready();
   await page.waitForFunction(()=>Number(document.querySelector('.viewer canvas')?.dataset.interiorCeilingElements)>0);
   const ceiling=Number(await canvas.getAttribute('data-interior-ceiling-elements'));
   assert.equal(Number(await canvas.getAttribute('data-displayed-elements'))-before,ceiling);
   await page.getByRole('button',{name:'표시 설정',exact:true}).click();
   await page.screenshot({path:path.join(out,fid+'-ceiling-structure.png')});
   const closure=model.elements.find(e=>e.floor_id===fid&&e.source.ceiling_completion);
   if(closure){
    const room=closure.source.context_room_ids[0];
    await page.getByLabel('객체 검색').fill(room);
    await page.locator(`.object-row[title$="${room}"]`).click();
    await page.getByLabel('객체 검색').fill('');
   }
   await page.getByRole('button',{name:'실내 시점',exact:true}).click();
   await page.waitForFunction(()=>document.querySelector('.viewer canvas')?.dataset.walking==='true');await ready();
   const box=await canvas.boundingBox();
   await page.mouse.move(box.x+box.width*.5,box.y+box.height*.65);await page.mouse.down();
   await page.mouse.move(box.x+box.width*.5,box.y+box.height*.65-90,{steps:10});await page.mouse.up();
   await page.screenshot({path:path.join(out,fid+'-ceiling-interior.png')});
   results.push({floor:fid,ceilingMembers:ceiling});
   console.log('Verified ceiling view',fid);
   await page.getByRole('button',{name:'실내 시점 종료',exact:true}).click();await ready();
  }
  await page.setViewportSize({width:390,height:844});await ready();
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1));
  await settings();assert(await page.getByLabel('천장 구조 표시',{exact:true}).isVisible());
  await page.screenshot({path:path.join(out,'ceiling-mobile.png')});
  assert.deepEqual(errors,[]);
  fs.writeFileSync(path.join(out,'browser-validation.json'),JSON.stringify({results,errors},null,2));
  console.log(JSON.stringify({results,errors}));
 }finally{if(browser)await browser.close();if(server)server.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
