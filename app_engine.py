"""Background orchestration; HTTP handlers never call the WeChat sender directly."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import copy,hashlib,json,os,queue,threading,time,xml.etree.ElementTree as ET
from app_store import Conflict,now
import app_models
BASE=Path(__file__).resolve().parent
SEND_LOCK=threading.RLock()

def message_id(m):return str(m['server_id']) if m['server_id'] else m['database']+':'+str(m['local_id'])
def revision(messages):
    return hashlib.sha256(json.dumps([(message_id(m),m['sort_seq'],m['content']) for m in messages[-20:]],ensure_ascii=False).encode()).hexdigest()
def latest_incoming(messages,watermark):
    human=[m for m in messages if m['sender'] in ('我','她')]
    return human[-1]['sort_seq'] if human and human[-1]['sender']=='她' and human[-1]['sort_seq']>watermark else None

class Engine:
    def __init__(self,store,secrets,reader_factory=None,media_factory=None,sender=None,generator=None):
        self.store=store;self.secrets=secrets;self.reader_factory=reader_factory;self.media_factory=media_factory
        self.sender=sender;self.generator=generator or app_models.generate
        self.lock=threading.RLock();self.gate=threading.RLock();self.commands=queue.Queue()
        self.pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='reply-model');self.future=None;self.future_job=None
        self.reader=None;self.media=None;self.raw=[];self.rev='';self.watermark=0;self.pending=None;self.pending_at=0
        self.enabled=False;self.epoch=0;self.closed=False;self.excluded=set();self.next_read=0
        self.runtime={'state':'starting','connected':False,'enabled':False,'error':'','target':'','last_poll':None,'pid':os.getpid()}
    def snapshot(self):
        with self.lock:return copy.deepcopy(self.runtime)
    def state(self,**fields):
        with self.lock:
            self.runtime.update(fields);self.runtime['enabled']=self.enabled;self.runtime['updated_at']=now()
    def control(self,enabled):
        with self.gate:
            self.enabled=bool(enabled)
            if not enabled:self.epoch+=1
            if not enabled:
                for j in self.store.jobs():
                    if j['status'] in ('queued','preparing','generating','send_queued'):
                        self.store.update(j['id'],status='cancelled',error='已暂停，未发送的任务已取消')
            self.commands.put(('control',self.enabled))
            self.state(state='watching' if enabled and self.reader else 'paused')
            self.store.event('control',message='开始监听新消息' if enabled else '已暂停自动处理')
        return self.snapshot()
    def proactive(self,instruction):
        if not self.snapshot()['connected']:raise Conflict('微信数据尚未连接，请先重试连接')
        with self.store.lock:
            if any(j['status'] in ('queued','preparing','generating') and j['source']=='manual' for j in self.store.jobs()):
                raise Conflict('已有主动生成任务正在进行')
            j=self.store.create('manual',instruction or '根据当前对话自然地主动聊一句，不编造本人活动。')
            j=self.store.update(j['id'],auto_requested=self.enabled and self.store.settings()['mode']=='auto')
            self.commands.put(('generate',j['id']))
            return j
    def approve(self,jobid,version,parts):
        clean=app_models.validate_parts(parts)
        job=self.store.update(jobid,version,('awaiting',),status='send_queued',parts=clean)
        self.commands.put(('send',jobid));return job
    def edit(self,jobid,version,parts):
        return self.store.update(jobid,version,('awaiting','stale'),parts=app_models.validate_parts(parts))
    def revise(self,jobid,version,instruction,parts):
        if not instruction.strip():raise ValueError('请填写希望模型怎样修改')
        with self.store.lock:
            old=self.store.update(jobid,version,('awaiting','stale','needs_user','failed'),status='superseded',parts=app_models.validate_parts(parts) if parts else [])
            job=self.store.create('revision',instruction,parent={'id':old['id'],'parts':old['parts'],'reason':old.get('reason','')})
            self.commands.put(('generate',job['id']));return job
    def skip(self,jobid,version):return self.store.update(jobid,version,('awaiting','stale','needs_user','failed','queued'),status='skipped')
    def _connect(self):
        self.state(state='connecting',connected=False,error='')
        try:
            if self.reader_factory:self.reader=self.reader_factory()
            else:
                from reader import Reader
                self.reader=Reader()
            if self.media_factory:self.media=self.media_factory(self.reader)
            else:
                from media_context import MediaContext
                self.media=MediaContext(self.reader)
            if self.sender is None:
                import native_send
                native_send.n.auto.InitializeUIAutomationInCurrentThread()
                self.sender=native_send
            self._refresh();self.watermark=max((m['sort_seq'] for m in self.raw),default=0)
            self.state(state='watching' if self.enabled else 'paused',connected=True,target=self.reader.target_name,error='')
            self.store.event('connected',message='已连接微信，从当前消息开始，不补发旧回复')
        except Exception as e:
            self.reader=None;self.enabled=False;self.state(state='error',connected=False,error=str(e))
            self.store.event('error',message='连接失败：'+str(e))
    def _public(self,m):
        kind=m['local_type']&0xffffffff
        d={'id':message_id(m),'sender':m['sender'],'time':time.strftime('%Y-%m-%d %H:%M:%S',time.localtime(m['create_time'])),
           'seq':m['sort_seq'],'kind':'text','text':'','sticker_id':None,'asset':None}
        if kind==1:d['text']=m['content']
        elif kind==3:d.update(kind='image',text='图片')
        elif kind==47 or m['local_type']==34359738417:
            d.update(kind='sticker',text='表情')
            try:
                e=ET.fromstring(m['content']);emoji=e.find('.//emoji')
                digest=emoji.get('md5') if emoji is not None else e.findtext('.//emoticonmd5')
                d['sticker_id']=digest
                item=next((s for s in app_models.catalog() if s['md5']==digest),None)
                if item:d['asset']='/media/stickers/'+item['file'];d['text']=item['description']
            except ET.ParseError:pass
        elif kind==49:
            d['kind']='share'
            try:d['text']='[分享/引用] '+(ET.fromstring(m['content']).findtext('.//appmsg/title') or '')
            except ET.ParseError:d['text']='分享消息'
        elif kind==10000:d.update(kind='system',text='系统消息')
        else:d.update(kind='other',text={34:'语音',43:'视频',50:'通话'}.get(kind,'媒体消息'))
        return d
    def _refresh(self):
        raw=self.reader.recent(limit=100);rev=revision(raw)
        if rev!=self.rev:
            self.raw=raw;self.rev=rev
            previous={m['id']:m for m in self.store.messages()}
            public=[]
            for m in raw:
                x=self._public(m)
                if previous.get(x['id'],{}).get('asset'):x['asset']=previous[x['id']]['asset']
                public.append(x)
            self.store.cache_messages(public)
            for j in self.store.jobs():
                if j['status']=='awaiting' and j.get('baseline')!=rev:
                    self.store.update(j['id'],status='stale',error='对话有新消息，请参考最新上下文重新生成')
        self.state(last_poll=now())
    def _cache_previews(self,context,images):
        public=self.store.messages();bytime={(m['time'],m['sender']):m for m in public}
        for row in context.get('messages',[]):
            item=bytime.get((row['time'],row['sender']))
            if item is not None and row.get('attachment'):
                path=Path(images[row['attachment']-1]);item['asset']='/media/incoming/'+path.name
        self.store.cache_messages(public)
    def _progress(self,jobid,metrics):
        job=self.store.job(jobid)
        self.store.record_call(metrics,job_id=jobid,operation=job['source'])
        self.store.update(jobid,progress=metrics)
    def _begin(self,jobid):
        j=self.store.job(jobid)
        if j['status']!='queued':return
        if self.future:
            self.commands.put(('generate',jobid));time.sleep(.1);return
        if self.reader is None:
            self.store.update(jobid,status='failed',error='微信未连接');return
        captured_epoch=self.epoch
        self.store.update(jobid,status='preparing');self.state(state='preparing',error='')
        try:
            self._refresh();baseline=self.rev;settings=self.store.settings()
            if not self.raw:raise ValueError('尚无可用对话上下文')
            since=self.watermark if j['source']=='incoming' else self.raw[-1]['sort_seq']-1
            context,images=self.media.prepare(self.raw,since)
            self._cache_previews(context,images)
            key=app_models.credential_for(self.secrets,settings).get() if settings['provider']=='custom' else ''
            if self.epoch!=captured_epoch or self.store.job(jobid)['status']=='cancelled':return
            model=settings['codex_model'] if settings['provider']=='codex' else settings['api_model']
            auto_requested=self.enabled and settings['mode']=='auto' and (j['source']=='incoming' or j.get('auto_requested',False))
            self.store.update(jobid,status='generating',baseline=baseline,model=model,provider=settings['provider'],settings_revision=settings['revision'],configuration=copy.deepcopy(settings),mode=settings['mode'],auto_send_requested=auto_requested,epoch=captured_epoch,image_count=len(images))
            self.future=self.pool.submit(self.generator,copy.deepcopy(settings),key,context,images,j['instruction'],j.get('parent'),tuple(self.excluded),progress=lambda metrics:self._progress(jobid,metrics))
            self.future_job=jobid;self.state(state='generating')
        except Exception as e:
            self.store.update(jobid,status='failed',error=str(e));self.store.event('error',job_id=jobid,message='生成准备失败：'+str(e))
            self.state(state='watching' if self.enabled else 'paused',error=str(e))
    def _finish(self):
        jobid=self.future_job;future=self.future;self.future=None;self.future_job=None
        job=self.store.job(jobid)
        try:
            reply,metrics=future.result()
            if job['status']=='cancelled' or job['epoch']!=self.epoch:
                self.store.update(jobid,metrics=metrics)
                self.store.event('model_usage',job_id=jobid,message='已取消的生成仍产生模型用量；没有发送',metrics=metrics)
                return
            self._refresh()
            status='awaiting' if reply['decision']=='reply' else 'needs_user' if reply['decision']=='needs_user' else 'no_reply'
            if job['baseline']!=self.rev:status='stale'
            job=self.store.update(jobid,status=status,parts=reply['parts'],reason=reply['reason'],metrics=metrics,
                                  error='生成时对话有更新，请重新生成' if status=='stale' else '')
            self.store.event('generated',job_id=jobid,message=reply['reason'],model=job['model'],seconds=metrics['seconds'],metrics=metrics)
            # Revisions always return to review. Auto mode never retro-sends an old review draft.
            if status=='awaiting' and job.get('auto_send_requested',False) and self.store.settings()['mode']=='auto' and self.enabled and job['source']!='revision':
                self.store.update(jobid,status='send_queued');self.commands.put(('send',jobid))
        except Exception as e:
            if self.store.job(jobid)['status']!='cancelled':self.store.update(jobid,status='failed',error=str(e))
            self.store.event('error',job_id=jobid,message='生成失败：'+str(e),metrics=self.store.job(jobid).get('progress'))
        finally:self.state(state='watching' if self.enabled else 'paused')
    def _send(self,jobid):
        with SEND_LOCK:
            if self.reader is not None and hasattr(self.reader,'resolve_contact'):
                try:
                    peer=self.reader.resolve_contact(self.reader.target)
                    if peer['display_name']!=self.reader.target_name:raise ValueError('联系人备注已变化，请重新连接后生成新草稿')
                    self.sender.ALLOWED={peer['display_name']}
                except Exception as exc:
                    self.store.update(jobid,status='failed',error=str(exc));return
            return self._send_locked(jobid)
    def _send_locked(self,jobid):
        job=self.store.job(jobid)
        if job['status']!='send_queued':return
        if self.reader is None:self.store.update(jobid,status='failed',error='微信未连接');return
        self._refresh()
        if job['baseline']!=self.rev:
            self.store.update(jobid,status='stale',error='发送前发现新消息，本次未发送');return
        parts=app_models.validate_parts(job['parts']);proofs=[];skipped=[];expected=self.rev;epoch=self.epoch
        for index,part in enumerate(parts):
            with self.gate:
                if epoch!=self.epoch or self.store.job(jobid)['status']=='cancelled':break
                self._refresh()
                if self.rev!=expected:
                    self.store.update(jobid,status='partial' if proofs else 'stale',proofs=proofs,error='对话已更新，剩余内容未发送');return
                self.store.update(jobid,status='sending',sending_part=index);self.state(state='sending')
                try:
                    start=int(time.time())
                    if part['kind']=='text':self.sender.send_text(self.reader.target_name,part['value'])
                    else:
                        try:self.sender.send_sticker(self.reader.target_name,part['value'],self.reader)
                        except self.sender.StickerNotSent as e:
                            skipped.append({'part':part,'reason':str(e)});self.excluded.add(part['value'])
                            self.store.update(jobid,status='sending',skipped=skipped)
                            self.store.event('skipped_sticker',job_id=jobid,message=str(e),part=part,metrics=job.get('metrics'),usage_reference=True);continue
                    proof=self.sender.verify(self.reader,self.reader.target_name,part['kind'],part['value'],start)
                    proofs.append({'part':part,**proof});self.store.update(jobid,proofs=proofs)
                    self.store.event('sent',job_id=jobid,message='已发送并核验',part=part,proof=proof,metrics=job.get('metrics'),usage_reference=True)
                    # Only our newly verified sends may advance the conversation while sending.
                    self._refresh()
                    newest=self.raw[-1] if self.raw else None
                    if newest and str(newest['server_id'])!=str(proof['server_id']):
                        self.store.update(jobid,status='partial',error='发送期间收到新消息，其余内容已取消',proofs=proofs);return
                    expected=self.rev;self.watermark=max((m['sort_seq'] for m in self.raw),default=self.watermark)
                except Exception as e:
                    self.store.update(jobid,status='uncertain',error=str(e),proofs=proofs,skipped=skipped)
                    self.enabled=False;self.epoch+=1;self.state(state='needs_user',error='发送结果未确认，已暂停：'+str(e))
                    self.store.event('error',job_id=jobid,message='发送结果未确认，禁止自动重发：'+str(e),metrics=job.get('metrics'),usage_reference=True);return
            time.sleep(.4)
        if self.store.job(jobid)['status']=='cancelled':return
        complete=len(proofs)+len(skipped)==len(parts)
        self.store.update(jobid,status='sent' if proofs and not skipped and complete else 'partial' if proofs else 'skipped',proofs=proofs,skipped=skipped)
        self.state(state='watching' if self.enabled else 'paused')
    def _load_media(self,messageid):
        try:
            m=next(x for x in self.raw if message_id(x)==messageid)
            kind=m['local_type']&0xffffffff
            if kind==3:path=self.media.image(m)
            else:
                _,path=self.media.emoji(m)
                if path is None:return
            public=self.store.messages();item=next(x for x in public if x['id']==messageid)
            item['asset']='/media/incoming/'+Path(path).name;self.store.cache_messages([item])
        except Exception as e:self.store.event('error',message='媒体读取失败：'+str(e))
    def run(self):
        self._connect()
        while not self.closed:
            try:
                try:action,value=self.commands.get(timeout=.2)
                except queue.Empty:action=None;value=None
                if action=='control':
                    if value and self.reader:self._refresh();self.watermark=max((m['sort_seq'] for m in self.raw),default=0);self.pending=None
                elif action=='reconnect':self._connect()
                elif action=='generate':self._begin(value)
                elif action=='send':self._send(value)
                elif action=='media':self._load_media(value)
                if self.reader and time.monotonic()>=self.next_read:
                    self._refresh();self.next_read=time.monotonic()+1
                if self.future and self.future.done():self._finish()
                if self.enabled and self.reader and not self.future:
                    marker=latest_incoming(self.raw,self.watermark)
                    if marker is None:
                        self.pending=None
                        if self.raw and self.raw[-1]['sender']=='我':self.watermark=max(self.watermark,self.raw[-1]['sort_seq'])
                    elif marker!=self.pending:self.pending=marker;self.pending_at=time.monotonic()
                    elif time.monotonic()-self.pending_at>=self.store.settings()['quiet_seconds']:
                        job=self.store.create('incoming');self._begin(job['id']);self.watermark=marker;self.pending=None
            except Exception as e:
                self.enabled=False;self.state(state='error',error=str(e));self.store.event('error',message=str(e));time.sleep(1)
    def start(self):
        self.thread=threading.Thread(target=self.run,name='wechat-engine',daemon=True);self.thread.start()
