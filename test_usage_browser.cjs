const {chromium}=require('./app-test-tools/node_modules/playwright');
const fs=require('fs');
(async()=>{
 const browser=await chromium.launch({executablePath:'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1100}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('http://127.0.0.1:8765');await page.waitForFunction(()=>document.querySelector('#system-prompt').value.length>0);
  await page.locator('[data-tab="settings"]').click();await page.locator('#provider').selectOption('codex');
  await page.locator('#testcase').fill('只回复 TOKEN_UI_OK，不使用工具。');await page.locator('#test-model').click();
  await page.waitForFunction(()=>document.querySelector('#live-usage').textContent.includes('当前操作'),null,{timeout:12000});
  const early=await page.locator('#live-usage').innerText();if(!early.includes('尚未上报'))throw Error('Pending usage is not clearly labelled');
  await page.screenshot({path:'qa/token-live.png',fullPage:true});
  await page.waitForFunction(()=>document.querySelector('#test-result').textContent.includes('连接成功'),null,{timeout:120000});
  const snapshot=await page.evaluate(async()=>await(await fetch('/api/state')).json());const test=snapshot.tests.at(-1);const u=test.usage;
  if(u.input_tokens==null||u.output_tokens==null||u.cached_input_tokens==null)throw Error('Real Codex usage missing');
  if(u.total_tokens!==u.input_tokens+u.output_tokens)throw Error('Cache incorrectly double-counted');
  if(snapshot.calls.filter(c=>c.call_id===test.call_id).length!==1)throw Error('Duplicate accounting row');
  fs.writeFileSync('qa/token-ui-proof.json',JSON.stringify({call_id:test.call_id,usage:u,seconds:test.seconds},null,2));
  await page.locator('[data-tab="activity"]').click();await page.locator('#event-filter').selectOption('model_usage');
  await page.screenshot({path:'qa/token-records.png',fullPage:true});
  if(!(await page.locator('#events').innerText()).includes('缓存命中率'))throw Error('Usage missing from history');
  // Explicit UI fixture: verifies live partial usage changes without billing or sending.
  let tick=0;
  await page.route('**/api/state',async route=>{const data=structuredClone(snapshot);tick++;data.calls=[{call_id:'ui-fixture',model:'UI模拟数据（不计费）',phase:'receiving',operation:'connectivity_test',started_at:Date.now()/1000,seconds:0,output_characters:tick,usage:{input_tokens:100,output_tokens:tick*10,cached_input_tokens:40,total_tokens:100+tick*10,cache_hit_rate:40,reported:true,final:false,status:'partial'}}];await route.fulfill({contentType:'application/json',body:JSON.stringify(data)});});
  await page.reload();await page.waitForFunction(()=>document.querySelector('#live-usage').textContent.includes('UI模拟数据'));
  const first=await page.locator('#live-usage .token-grid div').nth(1).locator('b').innerText();await page.waitForTimeout(2200);
  const next=await page.locator('#live-usage .token-grid div').nth(1).locator('b').innerText();if(Number(next)<=Number(first))throw Error('Partial usage not updating live');
  await page.unroute('**/api/state');await page.reload();await page.waitForTimeout(1200);await page.setViewportSize({width:390,height:844});
  if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('Usage panel overflows mobile viewport');
  await page.screenshot({path:'qa/token-mobile.png',fullPage:true});
  if(errors.length)throw Error(errors.join('\n'));
  console.log(JSON.stringify({real_codex_usage:u,seconds:test.seconds,live_partial_ui_verified:true,no_wechat_message_sent:true}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
