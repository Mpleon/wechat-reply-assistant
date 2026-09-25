const {chromium}=require('./app-test-tools/node_modules/playwright');
(async()=>{
 const browser=await chromium.launch({executablePath:'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}});await page.goto('http://127.0.0.1:8765');
  await page.waitForFunction(()=>document.querySelector('#system-prompt').value.length>0);
  await page.locator('[data-tab="settings"]').click();const original=await page.locator('#system-prompt').inputValue();
  await page.locator('#system-prompt').fill(original+'\n[页面配置保存验收]');await page.locator('#settings-form button[type="submit"]').click();
  await page.waitForFunction(()=>document.querySelector('#settings-note').textContent.includes('已保存'));
  await page.reload();await page.locator('[data-tab="settings"]').click();await page.waitForFunction(()=>document.querySelector('#system-prompt').value.includes('[页面配置保存验收]'));
  await page.locator('#system-prompt').fill(original);await page.locator('#settings-form button[type="submit"]').click();await page.waitForFunction(()=>document.querySelector('#settings-note').textContent.includes('已保存'));
  await page.locator('[data-tab="conversation"]').click();await page.getByRole('button',{name:'最新 ↓'}).click();await page.waitForTimeout(900);
  const bottom=await page.locator('#messages').evaluate(e=>e.scrollHeight-e.scrollTop-e.clientHeight);if(bottom>8)throw Error('Latest-message scroll failed: '+bottom);
  await page.screenshot({path:'qa/final-page.png',fullPage:true});console.log('Settings persisted across reload and restored; latest-message scrolling verified.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1});
