const {chromium}=require('./app-test-tools/node_modules/playwright');
const fs=require('fs');
(async()=>{
 const browser=await chromium.launch({executablePath:'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',headless:true});
 const base='http://127.0.0.1:8765';let original;const prefix='QA_PROFILE_'+Date.now();
 async function state(){return(await fetch(base+'/api/state')).json();}
 async function post(path,data){const s=await state();const r=await fetch(base+path,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':s.csrf},body:JSON.stringify(data)});const v=await r.json();if(!r.ok)throw Error(v.error);return v;}
 async function until(predicate){for(let i=0;i<60;i++){const s=await state();if(predicate(s))return s;await new Promise(r=>setTimeout(r,200));}throw Error('Profile state timeout');}
 try{
  original=await state();await post('/api/control',{enabled:false});
  const page=await browser.newPage({viewport:{width:1440,height:1100}});page.on('dialog',d=>d.accept());const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base);await page.locator('[data-tab="settings"]').click();await page.waitForSelector('#profile-picker option',{state:'attached'});
  async function create(suffix,model,key){
   await page.locator('#new-profile').click();await page.locator('#profile-name').fill(prefix+suffix);await page.locator('#base-url').fill('https://example.invalid/v1');await page.locator('#api-model').fill(model);await page.locator('#api-key').fill(key);await page.locator('#save-profile').click();
   const s=await until(s=>s.profiles.some(p=>p.name===prefix+suffix));const p=s.profiles.find(p=>p.name===prefix+suffix);await page.waitForTimeout(1200);return p;
  }
  const a=await create('_A','qa-model-a','qa-key-a');await page.locator('#activate-profile').click();await until(s=>s.settings.active_profile_id===a.id);
  const b=await create('_B','qa-model-b','qa-key-b');if((await state()).settings.active_profile_id!==a.id)throw Error('Save unexpectedly activated B');
  await page.locator('#profile-picker').selectOption(a.id);await page.waitForFunction(()=>document.querySelector('#api-model').value==='qa-model-a');
  if(await page.locator('#api-key').inputValue()!=='')throw Error('Saved secret returned to form');
  await page.locator('#api-model').fill('qa-model-a-edited');await page.locator('#save-profile').click();await until(s=>s.settings.api_model==='qa-model-a-edited');
  await page.locator('#profile-picker').selectOption(b.id);await page.waitForFunction(()=>document.querySelector('#api-model').value==='qa-model-b');await page.locator('#activate-profile').click();await until(s=>s.settings.active_profile_id===b.id);
  fs.mkdirSync('qa',{recursive:true});await page.screenshot({path:'qa/model-profiles.png',fullPage:true});
  await page.locator('#profile-picker').selectOption(a.id);await page.waitForTimeout(500);await page.locator('#delete-profile').click();await until(s=>!s.profiles.some(p=>p.id===a.id));
  if(errors.length)throw Error(errors.join('\n'));
  console.log('Profile create/edit/switch/delete flow passed; no model request or WeChat send performed.');
 }finally{
  if(original){await post('/api/profiles/activate',{id:original.settings.active_profile_id});for(const p of (await state()).profiles.filter(p=>p.name.startsWith(prefix)))await post('/api/profiles/delete',{id:p.id,version:p.version});await post('/api/control',{enabled:original.runtime.enabled});}
  await browser.close();
 }
})().catch(e=>{console.error(e);process.exitCode=1});
