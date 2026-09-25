const {chromium}=require('./app-test-tools/node_modules/playwright');
const fs=require('fs');
let browser;
(async()=>{
 browser=await chromium.launch({executablePath:'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',headless:true});
 const page=await browser.newPage({viewport:{width:1440,height:1050}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://127.0.0.1:8765');await page.waitForFunction(()=>document.querySelector('#target').textContent!=='正在读取…');
 fs.mkdirSync('qa',{recursive:true});await page.screenshot({path:'qa/conversation.png',fullPage:true});
 await page.locator('[data-tab="settings"]').click();await page.locator('#provider').selectOption('custom');
 await page.locator('#base-url').fill('http://127.0.0.1:1/v1');await page.locator('#api-model').fill('connectivity-negative-test');await page.locator('#api-key').fill('temporary-test-key-not-saved');
 await page.locator('#test-model').click();await page.waitForFunction(()=>document.querySelector('#test-result').textContent.includes('测试失败'),null,{timeout:30000});
 await page.locator('#api-key').fill('');await page.locator('#provider').selectOption('codex');
 await page.locator('#test-model').click();await page.waitForFunction(()=>document.querySelector('#test-result').textContent.includes('连接成功'),null,{timeout:120000});
 console.log('MODEL_TEST',await page.locator('#test-result').innerText());
 await page.screenshot({path:'qa/settings.png',fullPage:true});
 await page.locator('[data-tab="conversation"]').click();await page.locator('#topic').fill('界面验收：主动生成一句自然的问候草稿，不要发送。');await page.locator('#generate').click();
 await page.waitForFunction(()=>document.querySelector('#draft-state').textContent==='待你确认',null,{timeout:150000});
 await page.screenshot({path:'qa/draft-review.png',fullPage:true});
 const text=page.locator('#draft-editor textarea').first();if(await text.count()){await text.fill('最近在忙什么呀');await page.locator('#save-edit').click();await page.waitForTimeout(2200);}
 await page.locator('#revision-prompt').fill('改成一句更轻松的问候，保持简短，不要提到测试。');await page.locator('#revise').click();
 await page.waitForFunction(()=>document.querySelector('#draft-state').textContent==='待你确认',null,{timeout:150000});
 await page.screenshot({path:'qa/revised-draft.png',fullPage:true});
 await page.locator('#skip').click();await page.waitForTimeout(2300);
 await page.locator('[data-tab="activity"]').click();await page.screenshot({path:'qa/activity.png',fullPage:true});
 await page.setViewportSize({width:390,height:844});await page.locator('[data-tab="settings"]').click();await page.screenshot({path:'qa/mobile.png',fullPage:true});
 const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);if(overflow)throw Error('Mobile horizontal overflow');
 if(errors.length)throw Error(errors.join('\n'));
 console.log('Browser flow passed; no confirm-send action was performed.');await browser.close();
})().catch(async e=>{console.error(e);if(browser)await browser.close();process.exitCode=1;});
