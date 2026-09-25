import io,json,sys,tempfile,time,unittest
from pathlib import Path
from app_usage import UsageTracker,normalize,read_api_response,codex_events
from app_store import Store

class Stream(io.BytesIO):
    def __init__(self,events):
        raw=''.join('data: '+(e if isinstance(e,str) else json.dumps(e))+'\n\n' for e in events)
        super().__init__(raw.encode());self.headers={'Content-Type':'text/event-stream; charset=utf-8'}
class UsageTests(unittest.TestCase):
    def test_cache_is_part_of_input_not_added_to_total(self):
        t=UsageTracker('codex','test');t.accept({'input_tokens':100,'cached_input_tokens':80,'output_tokens':20,'reasoning_output_tokens':10},True)
        u=t.finish()['usage'];self.assertEqual(u['total_tokens'],120);self.assertEqual(u['cache_hit_rate'],80);self.assertEqual(u['uncached_input_tokens'],20)
    def test_missing_cache_does_not_mean_zero(self):
        t=UsageTracker('custom','test');t.accept({'prompt_tokens':100,'completion_tokens':20},True)
        self.assertIsNone(t.finish()['usage']['cached_input_tokens'])
    def test_zero_is_reported_and_preserved(self):
        self.assertEqual(normalize({'prompt_tokens':0,'completion_tokens':0,'prompt_tokens_details':{'cached_tokens':0}})['cached_input_tokens'],0)
    def test_missing_usage_stays_unknown(self):
        t=UsageTracker('custom','test');u=t.finish()['usage'];self.assertIsNone(u['total_tokens']);self.assertEqual(u['status'],'unavailable')
    def test_cumulative_updates_are_not_summed(self):
        t=UsageTracker('custom','test');t.accept({'input_tokens':100,'output_tokens':2});t.accept({'input_tokens':100,'output_tokens':4},True)
        self.assertEqual(t.finish()['usage']['total_tokens'],104)
    def test_chat_stream_updates_and_final_usage(self):
        progress=[];t=UsageTracker('custom','test',callback=progress.append)
        stream=Stream([{'choices':[{'delta':{'content':'Hi'},'index':0}],'usage':None},
          {'choices':[{'delta':{},'index':0,'finish_reason':'stop'}]},
          {'choices':[],'usage':{'prompt_tokens':20,'completion_tokens':4,'total_tokens':24,'prompt_tokens_details':{'cached_tokens':12}}},'[DONE]'])
        self.assertEqual(read_api_response(stream,'chat_completions',t),'Hi')
        u=t.finish()['usage'];self.assertEqual(u['total_tokens'],24);self.assertEqual(u['cache_hit_rate'],60)
        self.assertTrue(any(p['usage']['reported'] for p in progress))
    def test_responses_stream_partial_then_final_usage(self):
        progress=[];t=UsageTracker('custom','test',callback=progress.append)
        stream=Stream([{'type':'response.in_progress','response':{'usage':{'input_tokens':10}}},
          {'type':'response.output_text.delta','delta':'Hello'},
          {'type':'response.completed','response':{'output_text':'Hello','usage':{'input_tokens':10,'output_tokens':5,'input_tokens_details':{'cached_tokens':0}}}}])
        self.assertEqual(read_api_response(stream,'responses',t),'Hello')
        self.assertTrue(any(p['usage']['status']=='partial' and p['usage']['input_tokens']==10 for p in progress))
        self.assertEqual(t.finish()['usage']['total_tokens'],15)
    def test_interrupted_stream_does_not_turn_partial_text_into_a_reply(self):
        t=UsageTracker('custom','test')
        with self.assertRaises(ValueError):read_api_response(Stream([{'choices':[{'delta':{'content':'half'}}]}]),'chat_completions',t)
        u=t.finish(False)['usage'];self.assertEqual(u['status'],'interrupted');self.assertIsNone(u['total_tokens'])
    def test_json_fallback_retains_usage(self):
        r=io.BytesIO(json.dumps({'choices':[{'message':{'content':'ok'}}],'usage':{'prompt_tokens':5,'completion_tokens':1}}).encode());r.headers={'Content-Type':'application/json'}
        t=UsageTracker('custom','test');self.assertEqual(read_api_response(r,'chat_completions',t),'ok');self.assertEqual(t.finish()['usage']['total_tokens'],6)
    def test_codex_subprocess_events_live(self):
        with tempfile.TemporaryDirectory() as d:
            output=Path(d)/'out.txt';script=Path(d)/'fixture.py'
            script.write_text("import sys,json,time\nfrom pathlib import Path\nsys.stdin.read()\nprint(json.dumps({'type':'turn.started'}),flush=True)\nprint(json.dumps({'type':'token_usage.updated','usage':{'input_tokens':100}}),flush=True)\ntime.sleep(.5)\nPath(sys.argv[1]).write_text('ok')\nprint(json.dumps({'type':'turn.completed','usage':{'input_tokens':120,'cached_input_tokens':80,'output_tokens':30}}),flush=True)\n",encoding='utf-8')
            progress=[];t=UsageTracker('codex','test',callback=progress.append)
            self.assertEqual(codex_events([sys.executable,'-u',str(script),str(output)],'test',output,d,5,t),'ok')
            self.assertTrue(any(x['usage']['input_tokens']==100 and not x['usage']['final'] for x in progress))
            self.assertEqual(t.finish()['usage']['total_tokens'],150)
    def test_store_upsert_does_not_duplicate_call(self):
        s=Store(':memory:');t=UsageTracker('custom','test');s.record_call(t.snapshot(),job_id='job')
        t.accept({'input_tokens':10,'output_tokens':2},True);s.record_call(t.finish(),job_id='job')
        self.assertEqual(len(s.calls()),1);self.assertEqual(s.calls()[0]['usage']['total_tokens'],12)
    def test_restart_marks_running_call_incomplete(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'test.db';s=Store(p);t=UsageTracker('custom','test');t.accept({'input_tokens':10});s.record_call(t.snapshot());s.db.close()
            s=Store(p);self.assertEqual(s.calls()[0]['usage']['status'],'interrupted');self.assertFalse(s.calls()[0]['usage']['final']);s.db.close()
if __name__=='__main__':unittest.main()
