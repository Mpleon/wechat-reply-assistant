'use strict';
const $=id=>document.getElementById(id);
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let state=null, selected='', editorKey='', formDirty=false, formRevision=0, messageSignature='', eventSignature='', toastTimer, followLatest=true;
let selectedProfile=null,profileEditorVersion=0,profileEditorId=null,modelDirty=false;
const modelFields=new Set(['provider','codex-model','reasoning','base-url','api-protocol','api-model','api-key','api-stream','clear-key','profile-name']);
const latestButton=document.createElement('button');latestButton.className='quiet';latestButton.textContent='最新 ↓';latestButton.title='跳到最新消息';
document.querySelector('.chat-panel .panel-head').append(latestButton);
function jumpLatest(){const box=$('messages');box.scrollTo({top:box.scrollHeight,behavior:'instant'});}
latestButton.onclick=()=>{followLatest=true;jumpLatest();};
['wheel','touchmove','pointerdown'].forEach(event=>$('messages').addEventListener(event,()=>{followLatest=false;},{passive:true}));
const labels={starting:'正在启动',connecting:'连接微信中',watching:'正在监听',paused:'已暂停',preparing:'准备上下文',generating:'正在生成',sending:'正在发送',needs_user:'需要处理',error:'连接异常',queued:'等待生成',awaiting:'待你确认',send_queued:'准备发送',sent:'已核验发送',partial:'部分完成',skipped:'已跳过',stale:'上下文已更新',failed:'失败',uncertain:'发送待核对',cancelled:'已取消',superseded:'已有修改版',no_reply:'暂不回复'};
const sources={incoming:'新消息回复',manual:'主动生成',revision:'修改版本'};
function toast(text,bad=false){$('toast').textContent=text;$('toast').className='toast'+(bad?' bad':'');clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').classList.add('hidden'),5000);}
async function api(path,payload){const options=payload===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':state?.csrf||''},body:JSON.stringify(payload)};const r=await fetch(path,options);const data=await r.json();if(!r.ok)throw Error(data.error||'请求失败');return data;}
async function action(fn){try{await fn();await refresh();}catch(e){toast(e.message,true);}}
function sticker(id){return state?.stickers.find(s=>s.md5===id);}
function stickerURL(s){return s?.file?'/media/stickers/'+encodeURIComponent(s.file):'';}
function showTab(tab){document.querySelectorAll('.tab').forEach(x=>x.classList.toggle('active',x.id===tab));document.querySelectorAll('.nav').forEach(x=>x.classList.toggle('active',x.dataset.tab===tab));$('page-title').textContent={conversation:'对话与草稿',activity:'运行记录',settings:'模型与提示词'}[tab];}
document.querySelectorAll('.nav').forEach(x=>x.addEventListener('click',()=>showTab(x.dataset.tab)));
function renderMessages(){
 const signature=JSON.stringify(state.messages);if(signature===messageSignature)return;messageSignature=signature;
 const list=$('messages');const nearBottom=list.scrollHeight-list.scrollTop-list.clientHeight<85;
 list.innerHTML=state.messages.length?state.messages.map(m=>{
  const media=m.asset?`<img class="${m.kind==='sticker'?'sticker-image':'media-image'}" src="${esc(m.asset)}" alt="${esc(m.text)}" loading="lazy">`:m.kind==='image'||m.kind==='sticker'?`<button class="load-media" data-media="${esc(m.id)}">${m.kind==='image'?'查看图片':'查看表情'}</button>`:'';
  return `<article class="msg ${m.sender==='我'?'self':''}"><div class="msg-meta">${esc(m.sender)} · ${esc(m.time)}</div>${media||`<div class="bubble">${esc(m.text)}</div>`}</article>`;
 }).join(''):'<div class="empty">连接后会显示最近对话。<br>不会补发启动前的旧消息。</div>';
 if(nearBottom||!list.dataset.loaded||followLatest){requestAnimationFrame(jumpLatest);list.dataset.loaded='1';}
 list.querySelectorAll('img').forEach(img=>img.addEventListener('load',()=>{if(followLatest)jumpLatest();},{once:true}));
}
$('messages').addEventListener('click',e=>{const b=e.target.closest('[data-media]');if(b)action(async()=>{b.disabled=true;b.textContent='正在读取…';await api('/api/media',{message_id:b.dataset.media});toast('已请求读取媒体');});else if(e.target.tagName==='IMG')window.open(e.target.src,'_blank','noopener');});
function partHTML(p,i,editable){
 const remove=editable?`<button class="remove-part" data-remove="${i}" title="删除这条">移除</button>`:'';
 let inner;
 if(p.kind==='text')inner=`<textarea data-value rows="3" maxlength="500" ${editable?'':'readonly'} aria-label="回复文字 ${i+1}">${esc(p.value)}</textarea>`;
 else{const s=sticker(p.value);inner=`<div class="sticker-edit"><img src="${esc(stickerURL(s))}" alt="${esc(s?.description||'表情')}"><select data-value ${editable?'':'disabled'} aria-label="选择表情">${state.stickers.filter(x=>x.native_verified||x.md5===p.value).map(x=>`<option value="${esc(x.md5)}" ${x.md5===p.value?'selected':''}>${esc(x.description)}</option>`).join('')}</select></div>`;}
 return `<div class="part" data-kind="${p.kind}"><div class="part-head"><span>${i+1} / ${p.kind==='text'?'文字':'表情'}</span>${remove}</div>${inner}</div>`;
}
function readParts(){return [...$('draft-editor').querySelectorAll('.part')].map(x=>({kind:x.dataset.kind,value:x.querySelector('[data-value]').value}));}
function activeJob(){return state?.jobs.find(j=>j.id===selected);}
function renderDraft(){
 if(!selected||!state.jobs.some(j=>j.id===selected))selected=state.jobs[0]?.id||'';
 const picker=$('draft-picker');picker.innerHTML=state.jobs.length?state.jobs.map(j=>`<option value="${j.id}" ${j.id===selected?'selected':''}>${esc(j.created_at.slice(5))} · ${sources[j.source]||j.source} · ${labels[j.status]||j.status}</option>`).join(''):'<option value="">还没有草稿</option>';
 const j=activeJob();if(!j)return;
 $('draft-state').textContent=labels[j.status]||j.status;$('draft-state').className='badge'+(['failed','uncertain','needs_user'].includes(j.status)?' bad':'');
 $('draft-meta').textContent=[sources[j.source],j.configuration?.profile_name,j.model,j.settings_revision?'配置 v'+j.settings_revision:'',j.metrics?j.metrics.seconds+' 秒':'',j.image_count?j.image_count+' 个媒体附件':''].filter(Boolean).join(' · ');
 $('draft-usage').innerHTML=tokenHTML(j.metrics||j.progress);
 const warning=j.error||(['stale','uncertain'].includes(j.status)?'请核对最新对话后重新生成':'');$('draft-warning').textContent=warning;$('draft-warning').classList.toggle('hidden',!warning);
 const editable=['awaiting','stale','failed','needs_user'].includes(j.status);
 const key=j.id+':'+j.version;
 if(key!==editorKey){
  const same=editorKey.startsWith(j.id+':');const focused=$('draft-editor').contains(document.activeElement);
  if(!same||!focused){$('draft-editor').innerHTML=j.parts.length?j.parts.map((p,i)=>partHTML(p,i,editable)).join(''):`<div class="empty">${['queued','preparing','generating'].includes(j.status)?'正在整理上下文并生成回复…':esc(j.reason||'此任务没有可发送内容')}</div>`;editorKey=key;}
 }
 $('editor-tools').classList.toggle('hidden',!editable);$('revision-area').classList.toggle('hidden',!editable);
 $('draft-reason').textContent=j.reason?'生成说明：'+j.reason:'';
 $('approve').disabled=j.status!=='awaiting'||!state.runtime.connected;
 $('skip').disabled=!['awaiting','stale','failed','needs_user','queued'].includes(j.status);
 $('save-edit').disabled=!['awaiting','stale'].includes(j.status);
}
$('draft-picker').addEventListener('change',e=>{selected=e.target.value;editorKey='';$('revision-prompt').value='';renderDraft();});
$('draft-editor').addEventListener('click',e=>{const b=e.target.closest('[data-remove]');if(!b)return;const parts=readParts();parts.splice(Number(b.dataset.remove),1);$('draft-editor').innerHTML=parts.map((p,i)=>partHTML(p,i,true)).join('');});
$('draft-editor').addEventListener('change',e=>{if(e.target.tagName==='SELECT'){const s=sticker(e.target.value);e.target.closest('.part').querySelector('img').src=stickerURL(s);}});
function addPart(kind){const parts=readParts();if(parts.length>=4)return toast('最多 4 条');const first=state.stickers.find(s=>s.native_verified);if(kind==='sticker'&&!first)return;parts.push({kind,value:kind==='text'?'':first.md5});$('draft-editor').innerHTML=parts.map((p,i)=>partHTML(p,i,true)).join('');}
$('add-text').onclick=()=>addPart('text');$('add-sticker').onclick=()=>addPart('sticker');
$('save-edit').onclick=()=>action(async()=>{const j=activeJob();await api(`/api/jobs/${j.id}/edit`,{version:j.version,parts:readParts()});toast('编辑已保存');});
$('approve').onclick=()=>action(async()=>{const j=activeJob();$('approve').disabled=true;await api(`/api/jobs/${j.id}/approve`,{version:j.version,parts:readParts()});toast('已提交发送，正在核验');});
$('skip').onclick=()=>action(async()=>{const j=activeJob();await api(`/api/jobs/${j.id}/skip`,{version:j.version});toast('已跳过，不会发送');});
$('revise').onclick=()=>action(async()=>{const j=activeJob();const next=await api(`/api/jobs/${j.id}/revise`,{version:j.version,parts:readParts(),instruction:$('revision-prompt').value});selected=next.id;editorKey='';$('revision-prompt').value='';toast('正在根据你的要求修改，原版本仍保留');});
$('generate').onclick=()=>action(async()=>{$('generate').disabled=true;const j=await api('/api/generate',{instruction:$('topic').value});selected=j.id;editorKey='';toast('主动生成任务已开始');});
$('toggle').onclick=()=>action(async()=>{await api('/api/control',{enabled:!state.runtime.enabled});});
$('reconnect').onclick=()=>action(async()=>{await api('/api/reconnect',{});toast('正在重新连接');});
$('quick-mode').onchange=()=>action(async()=>{await api('/api/settings',{settings:{mode:$('quick-mode').value}});toast('回复方式已更新');});
function showProvider(){$('codex-fields').classList.toggle('hidden',$('provider').value!=='codex');$('custom-fields').classList.toggle('hidden',$('provider').value!=='custom');}
function fillSettings(s){$('system-prompt').value=s.system_prompt;$('use-style').checked=s.use_style;$('mode').value=s.mode;$('quiet-seconds').value=s.quiet_seconds;formRevision=s.revision;if(!state.profiles)fillModel(s);}
function formSettings(){return{provider:$('provider').value,codex_model:$('codex-model').value.trim(),reasoning:$('reasoning').value,base_url:$('base-url').value.trim(),api_protocol:$('api-protocol').value,api_model:$('api-model').value.trim(),system_prompt:$('system-prompt').value,use_style:$('use-style').checked,api_stream:$('api-stream').checked,mode:$('mode').value,quiet_seconds:Number($('quiet-seconds').value)};}
function markChanged(e){if(['show-api-key','profile-picker'].includes(e.target.id))return;if(modelFields.has(e.target.id)){modelDirty=true;$('profile-note').textContent='此模型配置有未保存的修改';$('activate-profile').disabled=true;}else{formDirty=true;$('settings-note').textContent='有未保存的提示词或回复设置';}showProvider();}
$('settings-form').addEventListener('input',markChanged);$('settings-form').addEventListener('change',markChanged);
$('settings-form').addEventListener('submit',e=>{e.preventDefault();action(async()=>{const all=formSettings();const globals=Object.fromEntries(['system_prompt','use_style','mode','quiet_seconds'].map(k=>[k,all[k]]));await api('/api/settings',{settings:globals});formDirty=false;formRevision=0;$('settings-note').textContent='提示词与回复设置已保存，下一轮生效';toast('提示词与回复设置已保存');});});
$('test-model').onclick=()=>action(async()=>{$('test-model').disabled=true;await api('/api/model-test',{settings:formSettings(),profile_id:selectedProfile,api_key:$('api-key').value,testcase:$('testcase').value,with_image:$('test-image').checked});$('test-result').textContent='正在测试，请稍候…';});
function renderTest(){const t=state.tests.at(-1);if(!t){$('test-model').disabled=false;return;}$('test-model').disabled=t.state==='running';$('test-result').textContent=(t.state==='running'?'正在调用模型… 测试不会发送微信消息':t.state==='success'?`连接成功 · ${t.model} · ${t.seconds} 秒${t.images?' · 已附带图片':''}\n\n${t.response}`:`测试失败\n\n${t.error}`)+'\n\n'+tokenText(t.progress||t);}
function renderEvents(){const filter=$('event-filter').value;const rows=state.events.filter(e=>filter==='all'||e.kind===filter||filter==='error'&&e.kind==='skipped_sticker'||filter==='model_usage'&&['generated','model_usage','model_test'].includes(e.kind));const sig=filter+JSON.stringify(rows);if(sig===eventSignature)return;eventSignature=sig;const types={sent:'发送成功',generated:'生成决策',error:'需要处理',skipped_sticker:'跳过表情',settings:'设置更新',connected:'连接成功',control:'运行控制',model_usage:'模型用量',model_test:'连通性测试'};
 $('events').innerHTML=rows.length?rows.map(e=>`<article class="event"><time>${esc(e.time)}</time><div><span class="badge ${e.kind==='error'?'bad':''}">${types[e.kind]||esc(e.kind)}</span></div><div class="event-content">${esc(e.message)}${e.part?.kind==='text'?`<div class="bubble">${esc(e.part.value)}</div>`:e.part?.kind==='sticker'&&sticker(e.part.value)?`<img class="sticker-image" src="${esc(stickerURL(sticker(e.part.value)))}" alt="${esc(sticker(e.part.value).description)}">`:''}${e.model?`<div class="subtle">${esc(e.model)} · ${esc(e.seconds)} 秒</div>`:''}${tokenHTML(e.metrics,e.usage_reference)}</div></article>`).join(''):'<div class="empty">暂无此类记录</div>';
}
$('event-filter').onchange=renderEvents;
async function refresh(){
 try{state=await api('/api/state');const r=state.runtime;
  $('connection').textContent=labels[r.state]||r.state;$('connection').className='badge'+(['error','needs_user'].includes(r.state)?' bad':'');
  $('toggle').textContent=r.enabled?'暂停监听':'开始监听';$('toggle').disabled=!r.connected;
  $('target').textContent=r.target||'微信尚未连接';$('current-model').textContent=(state.settings.profile_name?state.settings.profile_name+' · ':'')+(state.settings.provider==='codex'?`${state.settings.codex_model} · ${state.settings.reasoning}`:state.settings.api_model||'待配置 API');
  $('quick-mode').value=state.settings.mode;$('last-poll').textContent=r.last_poll?.slice(11)||'—';
  $('error-banner').textContent=r.error||'';$('error-banner').classList.toggle('hidden',!r.error);
  const auto=state.settings.mode==='auto'&&r.enabled;$('auto-notice').classList.toggle('hidden',!auto);
  $('generate').textContent=auto?'生成并自动发送':'生成草稿';$('proactive-hint').textContent=auto?'按当前自动模式发送':'先生成草稿，由你确认发送';
  $('generate').disabled=!r.connected||state.jobs.some(j=>j.source==='manual'&&['queued','preparing','generating'].includes(j.status));
  $('pending-count').textContent=state.jobs.filter(j=>j.status==='awaiting').length;
  $('footer-status').textContent='页面已更新 '+new Date().toLocaleTimeString('zh-CN');
  if(!formDirty&&formRevision!==state.settings.revision)fillSettings(state.settings);
  renderProfiles();renderMessages();renderDraft();renderEvents();renderTest();renderUsage();
 }catch(e){$('connection').textContent='页面服务未连接';$('connection').className='badge bad';$('error-banner').textContent='无法连接本机服务，请重新运行 start.ps1。';$('error-banner').classList.remove('hidden');}
}
const liveUsage=document.createElement('section');liveUsage.id='live-usage';liveUsage.className='panel usage-panel hidden';$('error-banner').after(liveUsage);
const draftUsage=document.createElement('div');draftUsage.id='draft-usage';$('draft-meta').after(draftUsage);
const streamOption=document.createElement('label');streamOption.className='check';streamOption.innerHTML='<input id="api-stream" type="checkbox" checked>流式接收与用量上报（服务不兼容时可关闭）';$('custom-fields').append(streamOption);
const keyVisibility=document.createElement('label');keyVisibility.className='check';keyVisibility.innerHTML='<input id="show-api-key" type="checkbox" aria-controls="api-key">显示 API Key';$('api-key').after(keyVisibility);
$('show-api-key').addEventListener('change',()=>{$('api-key').type=$('show-api-key').checked?'text':'password';});
const profileBlock=document.createElement('div');profileBlock.className='profile-manager';profileBlock.innerHTML='<label for="profile-picker">已保存的模型配置</label><select id="profile-picker"></select><div class="profile-tools"><button id="new-profile" type="button" class="quiet">＋ 新增配置</button><button id="activate-profile" type="button" class="secondary">设为当前使用</button><button id="delete-profile" type="button" class="quiet">删除</button></div><label for="profile-name">配置名称</label><input id="profile-name" maxlength="80" placeholder="例如：日常聊天 / 深度思考"><p id="profile-note" class="hint"></p>';
$('provider').previousElementSibling.before(profileBlock);
const saveProfileButton=document.createElement('button');saveProfileButton.id='save-profile';saveProfileButton.type='button';saveProfileButton.className='primary';saveProfileButton.textContent='保存此模型配置';$('provider').parentElement.append(saveProfileButton);
 $('settings-form').noValidate=true;
document.querySelector('#settings-form button[type="submit"]').textContent='保存提示词与回复设置';
function fillModel(p){$('profile-name').value=p.name||p.profile_name||'';$('provider').value=p.provider;$('codex-model').value=p.codex_model;$('reasoning').value=p.reasoning;$('base-url').value=p.base_url;$('api-protocol').value=p.api_protocol;$('api-model').value=p.api_model;$('api-stream').checked=p.api_stream!==false;$('key-status').textContent=p.has_api_key?'（该配置已保存）':'（该配置未保存）';$('api-key').value='';$('clear-key').checked=false;$('show-api-key').checked=false;$('api-key').type='password';profileEditorVersion=p.version||0;profileEditorId=p.id||null;modelDirty=false;showProvider();}
function renderProfiles(){if(!state.profiles)return;if(selectedProfile===null)selectedProfile=state.settings.active_profile_id;const profiles=state.profiles;if(selectedProfile&&!profiles.some(p=>p.id===selectedProfile))selectedProfile=state.settings.active_profile_id;
 $('profile-picker').innerHTML=(selectedProfile===''?'<option value="" selected>新配置（尚未保存）</option>':'')+profiles.map(p=>`<option value="${esc(p.id)}" ${p.id===selectedProfile?'selected':''}>${esc(p.name)}${p.id===state.settings.active_profile_id?' · 当前使用':''}</option>`).join('');
 const p=profiles.find(p=>p.id===selectedProfile);if(p&&!modelDirty&&(profileEditorId!==p.id||profileEditorVersion!==p.version))fillModel(p);
 $('activate-profile').disabled=!p||p.id===state.settings.active_profile_id||modelDirty;$('delete-profile').disabled=!p||p.id==='codex-default'||p.id===state.settings.active_profile_id;
 if(!modelDirty)$('profile-note').textContent=p?(p.id===state.settings.active_profile_id?'这是当前使用的配置；修改保存后从下一轮生成生效。':'正在编辑此配置；点击“设为当前使用”才会切换生成模型。'):'填写并保存后可切换使用；每个配置单独保存 API Key。';
}
$('profile-picker').onchange=e=>{if(modelDirty&&!confirm('放弃此配置尚未保存的修改？')){e.target.value=selectedProfile;return;}selectedProfile=e.target.value;profileEditorVersion=0;modelDirty=false;renderProfiles();};
$('new-profile').onclick=()=>{if(modelDirty&&!confirm('放弃当前未保存的修改并新增配置？'))return;selectedProfile='';fillModel({name:'',provider:'custom',codex_model:'gpt-6-astra',reasoning:'medium',base_url:'',api_model:'',api_protocol:'chat_completions',api_stream:true});renderProfiles();};
$('save-profile').onclick=()=>action(async()=>{const all=formSettings();const profile=Object.fromEntries(['provider','codex_model','reasoning','base_url','api_model','api_protocol','api_stream'].map(k=>[k,all[k]]));profile.name=$('profile-name').value;const result=await api('/api/profiles/save',{id:selectedProfile||null,version:profileEditorVersion||null,profile,api_key:$('api-key').value,clear_key:$('clear-key').checked});selectedProfile=result.profile.id;profileEditorVersion=0;modelDirty=false;$('api-key').value='';toast('模型配置已保存');});
$('activate-profile').onclick=()=>action(async()=>{await api('/api/profiles/activate',{id:selectedProfile});formRevision=0;toast('已切换，从下一轮生成生效');});
$('delete-profile').onclick=()=>action(async()=>{const p=state.profiles.find(p=>p.id===selectedProfile);if(!p||!confirm('删除“'+p.name+'”及其保存的 API Key？历史草稿与记录会保留。'))return;await api('/api/profiles/delete',{id:p.id,version:p.version});selectedProfile=null;profileEditorVersion=0;modelDirty=false;toast('模型配置已删除');});
const usageFilter=document.createElement('option');usageFilter.value='model_usage';usageFilter.textContent='模型用量';$('event-filter').append(usageFilter);
const tokenNumber=n=>n===null||n===undefined?'—':Number(n).toLocaleString('zh-CN');
function usageNote(m){const u=m?.usage;if(!u)return '该记录未采集 Token 用量';if(u.status==='waiting')return '用量尚未上报，— 不表示 0；服务端返回后自动更新';if(u.status==='unavailable')return '服务端未返回用量，无法确定实际 Token 数';if(u.status==='interrupted')return '调用中断：仅显示已上报用量，最终消耗可能不完整';if(!u.final)return '当前为服务端已上报的部分用量，尚非最终值';return u.cached_input_tokens==null?'最终用量；服务端未返回缓存字段':'最终用量；缓存 Token 已包含在输入中';}
function tokenText(m){const u=m?.usage;if(!u)return usageNote(m);return `输入 ${tokenNumber(u.input_tokens)} · 输出 ${tokenNumber(u.output_tokens)} · 缓存命中 ${tokenNumber(u.cached_input_tokens)} · 命中率 ${u.cache_hit_rate==null?'—':u.cache_hit_rate+'%'} · 合计 ${tokenNumber(u.total_tokens)} Token\n${usageNote(m)}`;}
function tokenHTML(m,reference=false){const u=m?.usage;if(!u)return `<div class="usage-note">${esc(usageNote(m))}</div>`;return `<div class="token-grid"><div><span>输入</span><b>${tokenNumber(u.input_tokens)}</b></div><div><span>输出</span><b>${tokenNumber(u.output_tokens)}</b></div><div><span>输入中缓存命中</span><b>${tokenNumber(u.cached_input_tokens)}</b></div><div><span>缓存命中率</span><b>${u.cache_hit_rate==null?'—':u.cache_hit_rate+'%'}</b></div><div><span>合计 Token</span><b>${tokenNumber(u.total_tokens)}</b></div></div><div class="usage-note">${esc(usageNote(m))}${u.reasoning_output_tokens!=null?` · 输出中推理 ${tokenNumber(u.reasoning_output_tokens)}`:''}${reference?' · 关联生成用量，本次发送不重复计费':''}${m.call_id?' · 调用 '+esc(m.call_id.slice(0,8)):''}</div>`;}
function renderUsage(){const calls=state.calls||[];const running=calls.filter(c=>!['completed','failed','interrupted'].includes(c.phase));const shown=running.length?running:calls.slice(0,1);liveUsage.classList.toggle('hidden',!shown.length);const ops={manual:'主动生成',incoming:'新消息回复',revision:'修改草稿',connectivity_test:'模型连通性测试'};const phases={connecting:'连接中',starting:'启动模型',generating:'正在生成',receiving:'接收输出',completed:'已完成',failed:'失败',interrupted:'已中断'};
 liveUsage.innerHTML=shown.map(c=>{const active=!['completed','failed','interrupted'].includes(c.phase);const elapsed=active&&c.started_at?Math.max(0,Date.now()/1000-c.started_at).toFixed(1):c.seconds;return `<div class="usage-call"><div class="usage-title"><strong>${active?'当前操作':'最近一次调用'} · ${ops[c.operation]||'模型生成'}</strong><span class="subtle">${esc(c.model)} · ${phases[c.phase]||esc(c.phase)} · ${esc(elapsed)} 秒</span></div>${tokenHTML(c)}${active?`<div class="usage-note">已接收输出 ${tokenNumber(c.output_characters)} 个字符（不等于 Token，不含不可见推理）</div>`:''}</div>`}).join('');}
refresh();setInterval(refresh,1000);
