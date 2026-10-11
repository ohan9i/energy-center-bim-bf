// Isolated Chrome regression: does not touch the user's browser or original DWG.
const fs=require('node:fs'),path=require('node:path'),os=require('node:os'),assert=require('node:assert/strict');
const {chromium}=require(process.env.UI_QA_MODULE||path.join(os.tmpdir(),'spatial-bim-qa/node_modules/playwright'));
const output=path.resolve('cad_output/bf-spatial/browser'),fixture=path.join(os.tmpdir(),'bf-spatial-test-model.json');
fs.mkdirSync(output,{recursive:true});
(async()=>{
 const browser=await chromium.launch({channel:'chrome',headless:true,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});
 const context=await browser.newContext({viewport:{width:1600,height:1000}}),page=await context.newPage();
 const errors=[],requests=[],checks={};page.on('pageerror',e=>errors.push(e.message));page.on('response',r=>{if(r.status()>=400&&!r.url().includes('/api/'))requests.push([r.status(),r.url()]);});
 const ready=()=>page.waitForFunction(()=>Number(document.querySelector('.viewer canvas')?.dataset.triangles)>0,null,{timeout:90000});
 try{
  await page.goto(process.env.BIM_QA_URL||'http://127.0.0.1:5173/',{waitUntil:'domcontentloaded'});await ready();
  assert.equal(await page.getByRole('button',{name:'정밀 1층 검토',exact:true}).count(),0);checks.precisionFirstFloorRemoved=true;
  await page.getByLabel('표시 층',{exact:true}).selectOption('f1');await ready();
  await page.getByRole('button',{name:'BF 공간 표시',exact:true}).click();
  await page.waitForFunction(()=>Number(document.querySelector('.viewer canvas')?.dataset.spatialPolygons)>0);
  await page.screenshot({path:path.join(output,'actual-f1-spatial-3d.png'),fullPage:true});checks.actualOverlay=true;
  await page.getByRole('button',{name:'공간 경계 검증',exact:true}).click();
  const dialog=page.getByRole('dialog',{name:'BF 공간 경계 검증'});await dialog.waitFor();
  assert((await page.getByTestId('spatial-summary').innerText()).includes('확인 공간 0 / 31'));
  assert(await page.getByRole('img',{name:'CAD와 BF 공간 경계 중첩'}).locator('polyline').count()>0);
  await page.screenshot({path:path.join(output,'actual-f1-cad-overlay.png'),fullPage:true});checks.actualCadOverlay=true;
  await page.locator('.spatial-list button').first().click();
  const textarea=page.getByLabel('BF 공간 편집 JSON'),record=JSON.parse(await textarea.inputValue());
  record.name+=' · browser persistence test';await textarea.fill(JSON.stringify(record));
  await page.getByRole('button',{name:'JSON 편집 적용',exact:true}).click();
  await page.getByRole('button',{name:'공간 수정 별도 저장',exact:true}).click();
  await page.getByRole('status').filter({hasText:'공간 수정 데이터를'}).waitFor();
  const patches=await page.evaluate(()=>Object.keys(localStorage).filter(k=>k.startsWith('bf-spatial-overrides:')));assert.equal(patches.length,1);
  await page.reload();await ready();await page.getByRole('button',{name:'공간 경계 검증',exact:true}).click();
  assert((await page.locator('.spatial-list button').first().innerText()).includes('browser persistence test'));checks.separatePatchRestored=true;
  await page.getByRole('button',{name:'닫기',exact:true}).click();
  await page.getByRole('button',{name:'BF 경로 탐색',exact:true}).click();
  await page.getByLabel('출발지',{exact:true}).selectOption({label:'1층 홀'});
  await page.getByLabel('목적지',{exact:true}).selectOption({label:'2층 회의실'});
  await page.getByRole('button',{name:'경로 탐색',exact:true}).click();await page.getByText('경로 없음',{exact:true}).waitFor();
  checks.actualRoute='no_path';await page.screenshot({path:path.join(output,'actual-route-blocked.png'),fullPage:true});
  // Import the synthetic reviewed spatial fixture using the app's existing JSON import UI.
  await page.getByRole('button',{name:'이용자',exact:true}).click();
  await page.getByLabel('JSON model import',{exact:true}).setInputFiles(fixture);await ready();
  await page.getByLabel('출발지',{exact:true}).selectOption('entrance');await page.getByLabel('목적지',{exact:true}).selectOption('room2');
  await page.getByLabel('표시 층',{exact:true}).selectOption('all');await page.getByRole('button',{name:'경로 탐색',exact:true}).click();
  await page.waitForFunction(()=>Number(document.querySelector('.viewer canvas')?.dataset.routeSegments)>0);
  checks.testRouteSegments=Number(await page.locator('.viewer canvas').getAttribute('data-route-segments'));
  await page.screenshot({path:path.join(output,'fixture-elevator-route-3d.png'),fullPage:true});
  await page.getByRole('button',{name:'공간 경계 검증',exact:true}).click();
  await page.locator('.spatial-list button').first().click();
  // Drag a safe outer corner. Any boundary edit must revoke that space's approval.
  const handle=page.locator('.spatial-map circle').first();await handle.scrollIntoViewIfNeeded();const box=await handle.boundingBox();assert(box);
  await page.screenshot({path:path.join(output,'fixture-before-vertex-edit.png'),fullPage:true});
  await page.evaluate(()=>{window.bfPointerEvents=[];for(const name of ['pointerdown','pointermove','pointerup'])document.addEventListener(name,e=>window.bfPointerEvents.push({name,tag:e.target.tagName,x:e.clientX,y:e.clientY}),true);});
  await page.mouse.move(box.x+box.width/2,box.y+box.height/2);await page.mouse.down();await page.mouse.move(box.x+box.width/2+2,box.y+box.height/2-2);await page.mouse.up();
  try{await page.waitForFunction(()=>{const t=document.querySelector('textarea[aria-label="BF 공간 편집 JSON"]');return t&&JSON.parse(t.value).status==='unresolved';},null,{timeout:5000});}
  catch(e){console.log(JSON.stringify({handle:box,events:await page.evaluate(()=>window.bfPointerEvents)}));throw e;}
  const edited=JSON.parse(await page.getByLabel('BF 공간 편집 JSON').inputValue());assert.equal(edited.status,'unresolved');assert.equal(edited.review,null);checks.vertexEditRevokesApproval=true;
  await page.getByRole('button',{name:'닫기',exact:true}).click();
  await page.setViewportSize({width:390,height:844});await page.getByRole('button',{name:'공간 경계 검증',exact:true}).click();
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  await page.screenshot({path:path.join(output,'mobile-spatial-review.png'),fullPage:true});checks.mobile=true;
  await page.locator('.spatial-list button').first().click();
  await page.getByLabel('BF 공간 편집 JSON').scrollIntoViewIfNeeded();
  assert(await page.getByLabel('BF 공간 편집 JSON').isVisible());
  await page.getByRole('button',{name:'공간 수정 별도 저장',exact:true}).scrollIntoViewIfNeeded();checks.mobileEditorAccessible=true;
  assert.deepEqual(errors,[]);assert.deepEqual(requests,[]);
  fs.writeFileSync(path.join(output,'results.json'),JSON.stringify({status:'passed',checks,errors,requests,realBuildingRouteVerified:false},null,2));
  console.log(JSON.stringify({status:'passed',checks,errors,requests,realBuildingRouteVerified:false}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
