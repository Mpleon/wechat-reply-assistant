const {chromium}=require('./app-test-tools/node_modules/playwright');
(async()=>{
 const browser=await chromium.launch({executablePath:'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1100}}),errors=[],posts=[];
  page.on('pageerror',e=>errors.push(e.message));
  const base='http://127.0.0.1:8765';
  const template=await (await fetch(base+'/api/state')).json();
  const contacts=[{id:'legacy',display_name:'Test A',runtime:{...template.runtime,enabled:false,connected:true,state:'paused',error:''}}];
  await page.route('**/api/**',async route=>{
   const request=route.request(),url=new URL(request.url());let body={ok:true};
   if(request.method()==='POST'){
    const payload=request.postDataJSON();posts.push({path:url.pathname,payload});
    if(url.pathname==='/api/contacts/add'){body={id:'second',display_name:'Test B'};contacts.push({...body,runtime:{...contacts[0].runtime}});}
   }else if(url.pathname==='/api/state'){
    const id=url.searchParams.get('peer_id')||'legacy',peer=contacts.find(c=>c.id===id);
    body={...template,peer_id:id,contacts,runtime:{...peer.runtime,target:peer.display_name},jobs:[],events:[],calls:[],tests:[],messages:[{id:'same',sender:'我',time:'2026-01-01 12:00:00',seq:1,kind:'text',text:id==='legacy'?'Only A history':'Only B history'}]};
   }
   await route.fulfill({json:body});
  });
  await page.goto(base);await page.getByText('Only A history',{exact:true}).waitFor();
  await page.locator('#contact-identifier').fill('public_wechat_id');await page.locator('#add-contact').click();
  await page.getByText('Only B history',{exact:true}).waitFor();
  if(await page.getByText('Only A history',{exact:true}).count())throw Error('Other history leaked');
  await page.locator('#toggle').click();await page.waitForTimeout(300);
  if(!posts.some(p=>p.path==='/api/control'&&p.payload.peer_id==='second'&&p.payload.enabled))throw Error('Wrong control recipient');
  await page.locator('#contact-picker').selectOption('legacy');await page.getByText('Only A history',{exact:true}).waitFor();
  await page.locator('#pause-all').click();await page.waitForTimeout(300);
  if(!posts.some(p=>p.payload.all===true&&p.payload.enabled===false))throw Error('Pause-all missing');
  if(errors.length)throw Error(errors.join('\n'));
  console.log('Contact add, switch, isolated history, selected control and pause-all passed. API writes mocked; no WeChat messages sent.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
