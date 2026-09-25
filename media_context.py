from pathlib import Path
import sys,os,ast,types,ctypes,hashlib,struct,re,time,json,io,subprocess,base64,urllib.request,urllib.parse
import xml.etree.ElementTree as ET
from typing import List,Optional,Tuple
from reader import scope,AUDIT
from PIL import Image
from cryptography.hazmat.primitives.ciphers import Cipher,algorithms,modes
import imageio_ffmpeg
from runtime_paths import DATA_DIR as BASE,RESOURCE_DIR
class MediaContext:
    def __init__(self,reader):
        self.reader=reader;self.key=None;self.attempted=False
        self.image_cache={};self.emoji_cache={}
        self.dest=BASE/'incoming-media';self.dest.mkdir(exist_ok=True)
        catalog_file=BASE/'stickers.json'
        self.catalog={x['md5']:x for x in json.loads(catalog_file.read_text(encoding='utf-8'))} if catalog_file.exists() else {}
        tree=ast.parse((AUDIT/'media.py').read_text(encoding='utf-8-sig'))
        methods={'__init__','_probe_ct','_validate_key','_scan_aes_key','_derive_xor_key'}
        class Strip(ast.NodeTransformer):
            def visit_ImportFrom(self,n):return None if n.level else n
        nodes=[]
        for n in tree.body:
            if isinstance(n,(ast.Import,ast.ImportFrom)) or isinstance(n,ast.Assign) and n.lineno<53:nodes.append(n)
            elif isinstance(n,ast.FunctionDef) and n.name in ('_jpeg_like','aligned_aes_block_size'):nodes.append(n)
            elif isinstance(n,ast.ClassDef) and n.name=='MediaDownloader':
                n.body=[Strip().visit(m) for m in n.body if isinstance(m,ast.FunctionDef) and m.name in methods];nodes.append(n)
        self.ns={'_dbmod':types.SimpleNamespace(**scope)}
        exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),'reviewed_media_helpers','exec'),self.ns)
        db=object.__new__(scope['WeChatDB']);db.account_dir=str(reader.root.parent)
        self.md=self.ns['MediaDownloader'](db)
    def image(self,m):
        packed=base64.b64decode(m['packed_base64']);match=re.search(rb'[0-9a-f]{32}',packed)
        if not match:raise RuntimeError('Image ID missing')
        digest=match.group().decode();month=time.strftime('%Y-%m',time.localtime(m['create_time']))
        folder=self.reader.root.parent/'msg/attach'/hashlib.md5(self.reader.target.encode()).hexdigest()/month/'Img'
        p=next((folder/(digest+s) for s in ('_h.dat','.dat','_t.dat') if (folder/(digest+s)).exists()),None)
        if p is None:raise RuntimeError('Image cache missing')
        info=p.stat();cache_key=(str(p),info.st_size,info.st_mtime_ns)
        cached=self.image_cache.get(cache_key)
        if cached and cached.exists():return cached
        data=p.read_bytes()
        if data[:6]!=self.ns['V2_MAGIC']:raise RuntimeError('Unsupported incoming image format')
        if self.key is None:
            if self.attempted:raise RuntimeError('Image key unavailable')
            self.attempted=True;self.md._probe_ct(str(p));self.key=self.derive_image_key()
            if not self.key:self.key=self.md._scan_aes_key(monitor=False)
        if not self.key:raise RuntimeError('Image key unavailable')
        aes_size,xor_size=struct.unpack_from('<II',data,6);block=self.ns['aligned_aes_block_size'](aes_size)
        dec=Cipher(algorithms.AES(self.key.encode()),modes.ECB()).decryptor();plain=dec.update(data[15:15+block])+dec.finalize()
        pad=plain[-1]
        if not 1<=pad<=16 or plain[-pad:]!=bytes([pad])*pad:raise RuntimeError('Image padding failed')
        thumb=folder/(digest+'_t.dat');xor=self.md._derive_xor_key(str(thumb if thumb.exists() else p))
        plain=plain[:-pad]+(data[15+block:-xor_size] if xor_size else data[15+block:])+ (bytes(x^xor for x in data[-xor_size:]) if xor_size else b'')
        if plain.startswith(b'wxgf'):
            start=plain.find(b'\x00\x00\x00\x01');output=self.dest/(digest+'.png')
            if start<0:raise RuntimeError('Image stream unavailable')
            result=subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-v','error','-f','hevc','-i','pipe:0','-frames:v','1','-y',str(output)],input=plain[start:],capture_output=True,timeout=20,creationflags=0x08000000)
            if result.returncode:raise RuntimeError('Image preview failed')
            plain=output.read_bytes()
        im=Image.open(io.BytesIO(plain));im.load();p=self.dest/(digest+'.'+im.format.lower());p.write_bytes(plain)
        self.image_cache[cache_key]=p
        return p
    def derive_image_key(self):
        helpers={'_find_weixin_module','_extract_movabs_xor_key','_read_remote_string','_read_remote_bytes','extract_master_key_from_cfg'}
        tree=ast.parse((AUDIT/'db.py').read_text(encoding='utf-8-sig'))
        nodes=[node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name in helpers
               or isinstance(node,ast.ClassDef) and node.name=='_MODULEENTRY32W']
        local=dict(scope)
        exec(compile(ast.Module(body=nodes,type_ignores=[]),'reviewed_image_config_helpers','exec'),local)
        for pid in self.md.db._find_weixin_pids():
            try:result=local['extract_master_key_from_cfg'](pid)
            except (ValueError,IndexError,struct.error):continue
            if result:
                _,number,account=result
                if account!=self.reader.self_id:continue
                candidate=hashlib.md5((str(number)+account).encode()).hexdigest()[:16]
                if self.md._validate_key(candidate):return candidate
        return None
    def emoji(self,m):
        e=ET.fromstring(m['content']);emoji=e.find('.//emoji')
        digest=emoji.get('md5') if emoji is not None else e.findtext('.//emoticonmd5')
        if digest in self.catalog:return self.catalog[digest]['description'],None
        if digest in self.emoji_cache and self.emoji_cache[digest].exists():
            return '表情画面见附件（动图取中间帧）',self.emoji_cache[digest]
        url=emoji.get('cdnurl') if emoji is not None else None
        if not url and digest:
            records=self.reader.query(self.reader.files[1],'SELECT cdn_url FROM kNonStoreEmoticonTable WHERE md5=?',(digest,))
            if records:url=records[0].get('cdn_url')
        if not url:raise RuntimeError('Sticker content unavailable')
        host=urllib.parse.urlparse(url).hostname or ''
        if not host.endswith(('.qq.com','.qpic.cn')):raise RuntimeError('Unrecognized media origin')
        with urllib.request.urlopen(url,timeout=15) as response:data=response.read(15*1024*1024)
        if hashlib.md5(data).hexdigest()!=digest:raise RuntimeError('Sticker integrity mismatch')
        im=Image.open(io.BytesIO(data));im.seek(getattr(im,'n_frames',1)//2);im.load()
        p=self.dest/(digest+'-preview.png');im.convert('RGBA').save(p)
        self.emoji_cache[digest]=p
        return '表情画面见附件（动图取中间帧）',p
    def prepare(self,messages,new_since):
        context=[];images=[]
        latest_time=max((m['create_time'] for m in messages),default=0)
        # A short response often refers to a picture sent before the watermark,
        # including one sent by the user. Include the last three recent pictures.
        historical_pictures=[m for m in messages if (m['local_type']&0xffffffff)==3
                             and latest_time-m['create_time']<=1800][-3:]
        picture_seqs={m['sort_seq'] for m in historical_pictures}
        for m in messages:
            kind=m['local_type']&0xffffffff
            role='owner' if m['sender']=='我' else 'peer' if m['sender'] in ('她','对方') else 'system'
            row={'sender':m['sender'],'speaker':role,'message_seq':m['sort_seq'],
                 'time':time.strftime('%Y-%m-%d %H:%M:%S',time.localtime(m['create_time']))}
            new=m['sort_seq']>new_since and m['sender']=='她'
            if kind==1:row['text']=m['content']
            elif kind==47 or m['local_type']==34359738417:
                if new:
                    desc,p=self.emoji(m);row['media']=desc
                    if p:images.append(p);row['attachment']=len(images)
                else:
                    e=ET.fromstring(m['content']);emoji=e.find('.//emoji')
                    digest=emoji.get('md5') if emoji is not None else e.findtext('.//emoticonmd5')
                    row['media']=self.catalog.get(digest,{}).get('description','表情（未解析）')
            elif kind==3:
                row['media']='图片'
                if new or m['sort_seq'] in picture_seqs:
                    images.append(self.image(m));row['attachment']=len(images)
            elif kind==49:
                e=ET.fromstring(m['content']);row['text']='[分享/引用] '+(e.findtext('.//appmsg/title') or '')
                quote=e.findtext('.//refermsg/content')
                if quote and not quote.startswith('<'):row['quote']=quote
            elif kind==10000:continue
            else:
                row['media']='未解析的媒体消息'
                if new:raise RuntimeError('Incoming voice/video needs user interpretation')
            context.append(row)
        if len(images)>5:raise RuntimeError('Too many incoming images for one reply')
        human=[row for row in context if row['speaker'] in ('owner','peer')]
        return {'speaker_definitions':{'owner':'账号本人，你要代写的身份；我发出的历史消息',
                                      'peer':'收件人，对方发来的历史消息','system':'系统通知'},
                'messages':context,'last_speaker':human[-1]['speaker'] if human else None,
                'attachments':[{'attachment':row['attachment'],'speaker':row['speaker'],
                                'message_seq':row['message_seq'],'time':row['time']}
                               for row in context if 'attachment' in row]},images
