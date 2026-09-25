"""Provider-reported usage only. Missing numbers are unknown, never fabricated zeroes."""
import copy,json,queue,subprocess,threading,time,uuid

FIELDS=('input_tokens','output_tokens','cached_input_tokens','reasoning_output_tokens','total_tokens')
def number(value):return value if isinstance(value,int) and not isinstance(value,bool) and value>=0 else None
def first(*values):return next((n for v in values if (n:=number(v)) is not None),None)
def normalize(raw):
    raw=raw if isinstance(raw,dict) else {}
    inp=raw.get('input_tokens_details') or raw.get('prompt_tokens_details') or {}
    out=raw.get('output_tokens_details') or raw.get('completion_tokens_details') or {}
    result={'input_tokens':first(raw.get('input_tokens'),raw.get('prompt_tokens')),
            'output_tokens':first(raw.get('output_tokens'),raw.get('completion_tokens')),
            'cached_input_tokens':first(raw.get('cached_input_tokens'),inp.get('cached_tokens'),raw.get('prompt_cache_hit_tokens')),
            'reasoning_output_tokens':first(raw.get('reasoning_output_tokens'),out.get('reasoning_tokens')),
            'total_tokens':first(raw.get('total_tokens'))}
    return {k:v for k,v in result.items() if v is not None}

class UsageTracker:
    def __init__(self,provider,model,images=0,callback=None):
        self.started=time.monotonic();self.callback=callback;self.last_emit=0
        self.data={'call_id':uuid.uuid4().hex,'provider':provider,'model':model,'images':images,
          'started_at':time.time(),'seconds':0,'phase':'connecting','output_characters':0,
          'usage':{**{f:None for f in FIELDS},'cache_hit_rate':None,'uncached_input_tokens':None,
                   'reported':False,'final':False,'status':'waiting','source':provider}}
        self.emit(True)
    def snapshot(self):
        result=copy.deepcopy(self.data);result['seconds']=round(time.monotonic()-self.started,2);return result
    def emit(self,force=False):
        if self.callback and (force or time.monotonic()-self.last_emit>=.35):
            self.last_emit=time.monotonic();self.callback(self.snapshot())
    def phase(self,value):
        if self.data['phase']!=value:self.data['phase']=value;self.emit(True)
        else:self.emit()
    def output(self,text):
        self.data['output_characters']+=len(text);self.data['phase']='receiving';self.emit()
    def accept(self,raw,final=False):
        values=normalize(raw)
        if not values:return
        usage=self.data['usage'];usage.update(values);usage.update(reported=True,final=final,status='final' if final else 'partial')
        i,o,c=usage['input_tokens'],usage['output_tokens'],usage['cached_input_tokens']
        if 'total_tokens' not in values and i is not None and o is not None:usage['total_tokens']=i+o
        if i is not None and c is not None and c<=i:
            usage['uncached_input_tokens']=i-c;usage['cache_hit_rate']=round(c/i*100,2) if i else None
        self.emit(True)
    def finish(self,success=True):
        usage=self.data['usage']
        if not usage['reported']:usage.update(status='unavailable' if success else 'interrupted',final=False)
        elif not success:usage.update(status='interrupted',final=False)
        elif not usage['final']:usage.update(status='partial')
        self.data['phase']='completed' if success else 'failed';self.emit(True)
        return self.snapshot()

def codex_events(command,prompt,output,cwd,timeout,tracker):
    """Read stdout JSONL while running, without retaining reasoning or stderr secrets."""
    process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
        text=True,encoding='utf-8',errors='replace',cwd=cwd,creationflags=0x08000000 if __import__('os').name=='nt' else 0)
    lines=queue.Queue()
    def reader():
        try:
            for line in process.stdout:lines.put(line)
        finally:lines.put(None)
    thread=threading.Thread(target=reader,daemon=True);thread.start()
    try:
        process.stdin.write(prompt);process.stdin.close()
        deadline=time.monotonic()+timeout;eof=False;failed=False
        while not eof:
            remaining=deadline-time.monotonic()
            if remaining<=0:raise TimeoutError('Codex 生成超时')
            try:line=lines.get(timeout=min(.3,remaining))
            except queue.Empty:tracker.emit();continue
            if line is None:eof=True;continue
            try:event=json.loads(line)
            except ValueError:continue
            kind=event.get('type','')
            if kind=='thread.started':tracker.phase('starting')
            elif kind=='turn.started':tracker.phase('generating')
            elif kind=='turn.completed':tracker.accept(event.get('usage'),final=True)
            elif kind in ('turn.failed','error'):failed=True
            elif kind.startswith('item.'):
                item=event.get('item') or {}
                if item.get('type')=='agent_message' and kind=='item.completed':tracker.output(item.get('text',''))
                elif item.get('type')=='reasoning':tracker.phase('generating')
            # Some CLI versions can publish interim usage snapshots.
            elif kind in ('token_usage.updated','thread.token_usage.updated'):
                tracker.accept(event.get('usage'),final=False)
        code=process.wait(timeout=max(.1,deadline-time.monotonic()))
        if code or failed or not output.exists():raise ValueError('Codex 调用失败，请检查登录、模型权限或网络')
        return output.read_text(encoding='utf-8')
    finally:
        if process.poll() is None:process.kill();process.wait()
        if process.stdout:process.stdout.close()

def sse_events(response):
    data=[];size=0
    for rawline in response:
        size+=len(rawline)
        if size>16*1024*1024:raise ValueError('模型返回的流过大')
        line=rawline.decode('utf-8').rstrip('\r\n')
        if not line:
            if data:
                joined='\n'.join(data);data=[]
                if joined.strip()=='[DONE]':yield {'_done':True};return
                yield json.loads(joined)
        elif line.startswith('data:'):data.append(line[5:].lstrip())
    if data:
        joined='\n'.join(data)
        if joined.strip()=='[DONE]':yield {'_done':True}
        else:yield json.loads(joined)

def read_api_response(response,protocol,tracker):
    if 'text/event-stream' not in response.headers.get('Content-Type','').lower():
        body=json.loads(response.read(8*1024*1024));tracker.accept(body.get('usage'),final=True)
        if protocol=='responses':text=body.get('output_text') or ''.join(c.get('text','') for i in body.get('output',[]) for c in i.get('content',[]) if c.get('type')=='output_text')
        else:
            try:text=body['choices'][0]['message']['content']
            except (KeyError,IndexError,TypeError):raise ValueError('响应中缺少 choices[0].message.content') from None
            if isinstance(text,list):text=''.join(c.get('text','') for c in text)
        if isinstance(text,str):tracker.output(text)
        return text
    parts=[];complete=False;authoritative=None
    for event in sse_events(response):
        if event.get('_done'):complete=True;break
        if event.get('error'):raise ValueError('服务端报告流式生成失败')
        if protocol=='responses':
            kind=event.get('type','');body=event.get('response') or {}
            if kind in ('response.failed','response.incomplete','error'):raise ValueError('Responses 输出流未完整完成')
            if kind=='response.output_text.delta':
                delta=event.get('delta','');parts.append(delta);tracker.output(delta)
            if body.get('usage'):tracker.accept(body['usage'],final=kind=='response.completed')
            elif event.get('usage'):tracker.accept(event['usage'],final=False)
            if kind=='response.completed':
                complete=True
                authoritative=body.get('output_text') or ''.join(c.get('text','') for i in body.get('output',[]) for c in i.get('content',[]) if c.get('type')=='output_text')
        else:
            for choice in event.get('choices',[]):
                if choice.get('index',0)!=0:continue
                delta=choice.get('delta',{}).get('content')
                if isinstance(delta,str):parts.append(delta);tracker.output(delta)
                if choice.get('finish_reason') is not None:complete=True
            if event.get('usage'):tracker.accept(event['usage'],final=complete or not event.get('choices'))
    if not complete:raise ValueError('输出流意外中断，未发送回复；用量可能不完整')
    return authoritative or ''.join(parts)
