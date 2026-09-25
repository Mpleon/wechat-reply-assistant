from pathlib import Path
import ctypes,time,json,sys,xml.etree.ElementTree as ET
import native_access as n
BASE=Path(__file__).resolve().parent
from runtime_paths import CONFIG
TARGET=CONFIG.get('target_name','')
if (BASE/'peer.json').exists():TARGET=json.loads((BASE/'peer.json').read_text(encoding='utf-8'))['display_name']
ALLOWED={TARGET,'文件传输助手'}
def walk(root):
    stack=[root]
    while stack:
        c=stack.pop();yield c;stack.extend(reversed(c.GetChildren()))
def root():return n.auto.ControlFromHandle(n.activate())
def input_control():return next(c for c in walk(root()) if c.AutomationId=='chat_input_field')
def current():return input_control().Name
def click(c):
    ctypes.windll.user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
    u=ctypes.windll.user32
    foreground=u.GetForegroundWindow()
    own_thread=ctypes.windll.kernel32.GetCurrentThreadId()
    fg_thread=n.win32process.GetWindowThreadProcessId(foreground)[0] if foreground else 0
    attached=False
    try:
        if fg_thread and fg_thread!=own_thread:attached=bool(u.AttachThreadInput(own_thread,fg_thread,True))
        n.win32gui.ShowWindow(n.window(),9)
        n.win32gui.BringWindowToTop(n.window())
        n.win32gui.SetForegroundWindow(n.window())
    finally:
        if attached:u.AttachThreadInput(own_thread,fg_thread,False)
    active=ctypes.windll.user32.GetForegroundWindow()
    if n.WeChatUIA._pid_from_hwnd(active)!=n.WeChatUIA._pid_from_hwnd(n.window()):raise RuntimeError('User changed focus; retry later')
    c.Click(simulateMove=False,waitTime=.1)
def open_chat(target):
    if target not in ALLOWED:raise RuntimeError('Recipient not allowed')
    for w in n.auto.GetRootControl().GetChildren():
        if w.ClassName=='mmui::EmoticonPopover':
            n.win32gui.PostMessage(w.NativeWindowHandle,0x10,0,0)
            time.sleep(.1)
    if current()==target:return
    # Prefer existing session controls; exact recipient name from database lookup.
    sessions=next(c for c in walk(root()) if c.AutomationId=='session_list')
    matches=[c for c in sessions.GetChildren() if c.Name.split('\n')[0]==target]
    if len(matches)!=1:
        search=next(c for c in walk(root()) if c.ControlTypeName=='EditControl' and c.Name=='搜索')
        search.GetValuePattern().SetValue(target);time.sleep(.6)
        matches=[c for c in walk(root()) if c.AutomationId.startswith('search_item_') and c.Name.split('\n')[0]==target]
    if len(matches)!=1:raise RuntimeError('Exact recipient control not found')
    click(matches[0]);time.sleep(.2)
    if current()!=target:raise RuntimeError('Recipient mismatch')
def send_text(target,text):
    if not text.strip() or len(text)>500:raise ValueError('Invalid message')
    open_chat(target);e=input_control();p=e.GetValuePattern()
    if p.Value:raise RuntimeError('Existing draft; preserve user input')
    p.SetValue(text)
    if current()!=target or p.Value!=text:raise RuntimeError('Draft mismatch')
    send=next(c for c in walk(root()) if c.Name=='发送' and c.ControlTypeName=='ButtonControl')
    click(send);time.sleep(.2)
    if p.Value:raise RuntimeError('Draft remains; sending is unconfirmed')
class StickerNotSent(RuntimeError):
    """Preparation failed before clicking a sticker; no delivery was attempted."""

def send_sticker(target,digest,reader):
    try:
        item=_prepare_sticker(target,digest,reader)
    except Exception as exc:
        raise StickerNotSent(str(exc)) from exc
    # Failures at/after this boundary remain uncertain and must stop retries.
    item.Click(simulateMove=False,waitTime=.1);time.sleep(.3)

def _prepare_sticker(target,digest,reader):
    order=reader.query(reader.files[1],'SELECT md5 FROM kFavEmoticonOrderTable ORDER BY rowid DESC')
    ids=[x['md5'] for x in order]
    if digest not in ids:raise RuntimeError('Sticker is not in favorites')
    index=ids.index(digest)
    if index>=25:raise RuntimeError('Sticker requires unvalidated scrolling')
    open_chat(target)
    if input_control().GetValuePattern().Value:raise RuntimeError('User draft exists')
    button=next(c for c in walk(root()) if c.Name=='发送表情(Alt+E)')
    click(button);time.sleep(.2)
    panel=next((w for w in n.auto.GetRootControl().GetChildren() if w.ClassName=='mmui::EmoticonPopover'),None)
    if panel is None:raise RuntimeError('Emoji panel absent')
    tabs=[c for c in walk(panel) if c.Name=='自定义表情' and c.ControlTypeName=='TabItemControl']
    if len(tabs)!=1:raise RuntimeError('Favorites tab missing')
    # Grid state can differ from database order; verify the selected bitmap below.
    tabs[0].Click(simulateMove=False,waitTime=.1);time.sleep(.2)
    items=[c for c in walk(panel) if c.ClassName=='mmui::FavEmoticonItemView']
    if len(items)<index+1:raise RuntimeError('Favorites page mismatch')
    if current()!=target:raise RuntimeError('Recipient changed')
    if not sticker_matches(items[index],digest):raise RuntimeError('Sticker cell differs from requested asset; no send')
    # Native item bounds, no fixed pixel coordinates or OCR.
    return items[index]
def sticker_matches(control,digest):
    # Small bitmap comparison verifies the database-to-grid mapping; no OCR.
    from PIL import Image,ImageGrab,ImageChops,ImageStat
    catalog=json.loads((BASE/'stickers.json').read_text(encoding='utf-8'))
    item=next((x for x in catalog if x['md5']==digest),None)
    if item is None:return False
    rect=control.BoundingRectangle
    shot=ImageGrab.grab(bbox=(int(rect.left),int(rect.top),int(rect.right),int(rect.bottom)),all_screens=True).convert('RGB')
    asset=Image.open(BASE/'stickers'/item['file']);best=255
    for frame in range(getattr(asset,'n_frames',1)):
        asset.seek(frame);rgba=asset.convert('RGBA')
        bg=Image.new('RGBA',rgba.size,(249,249,249,255));bg.alpha_composite(rgba);expected=bg.convert('RGB').resize((24,24))
        for margin in (0,.04,.08,.09,.10,.12,.15):
            dx=int(shot.width*margin);dy=int(shot.height*margin)
            crop=shot.crop((dx,dy,shot.width-dx,shot.height-dy)).resize((24,24))
            score=sum(ImageStat.Stat(ImageChops.difference(crop,expected)).mean)/3
            best=min(best,score)
    return best<22
def verify(reader,target,kind,value,since):
    user='filehelper' if target=='文件传输助手' else reader.target
    for _ in range(6):
        for m in reader.recent(user,12):
            if m['create_time']<since or m['sender']!='我':continue
            if kind=='text' and m['local_type']==1 and m['content']==value:return {'server_id':m['server_id'],'local_id':m['local_id']}
            if kind=='sticker' and m['local_type'] in (47,34359738417):
                e=ET.fromstring(m['content']);emoji=e.find('.//emoji')
                digest=emoji.get('md5') if emoji is not None else e.findtext('.//emoticonmd5')
                if digest==value:return {'server_id':m['server_id'],'local_id':m['local_id']}
        time.sleep(.7)
    raise RuntimeError('No matching sent message in database; do not resend automatically')
if __name__=='__main__':
    from reader import Reader
    r=Reader();started=int(time.time())
    digest='8854ae70c828f51984b8a752782cbbf9'
    send_sticker('文件传输助手',digest,r)
    proof=verify(r,'文件传输助手','sticker',digest,started)
    (BASE/'sticker-send-proof.json').write_text(json.dumps(proof),encoding='utf-8')
    print(json.dumps(proof))
