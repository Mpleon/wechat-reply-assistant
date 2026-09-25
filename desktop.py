"""Frozen desktop entry point. The data service lives only as long as this process."""
import ctypes,json,os,sys,threading,traceback
from pathlib import Path
from runtime_paths import DATA_DIR,RESOURCE_DIR
from app_version import VERSION

def self_test():
    import apsw,zstandard,win32cred,win32gui,win32process,uiautomation,webview,imageio_ffmpeg
    import reader,media_context,native_send
    from app_store import Store
    from dashboard import Application,handler
    from http.server import ThreadingHTTPServer
    from app_engine import Engine
    from cryptography.hazmat.primitives.ciphers import Cipher
    assert (RESOURCE_DIR/'web/index.html').is_file()
    assert (RESOURCE_DIR/'reply.schema.json').is_file()
    assert Path(imageio_ffmpeg.get_ffmpeg_exe()).is_file()
    store=Store(':memory:');app=Application(store,engine=Engine(store,None))
    server=ThreadingHTTPServer(('127.0.0.1',0),handler(app))
    threading.Thread(target=server.serve_forever,daemon=True).start()
    import urllib.request
    state=json.load(urllib.request.urlopen('http://127.0.0.1:'+str(server.server_port)+'/api/state'))
    assert state['version']==VERSION and state['setup']['required']
    server.shutdown();server.server_close();app.contacts.close();app.test_pool.shutdown()
    (DATA_DIR/'self-test.json').write_text(json.dumps({'ok':True,'version':VERSION,'resources':True,'dependencies':True,'http':True}),encoding='utf-8')

def main():
    DATA_DIR.mkdir(parents=True,exist_ok=True)
    if sys.stdout is None:sys.stdout=(DATA_DIR/'desktop.log').open('a',encoding='utf-8',buffering=1)
    if sys.stderr is None:sys.stderr=sys.stdout
    if '--self-test' in sys.argv:self_test();return
    import webview
    if '--ui-smoke-test' in sys.argv:
        window=webview.create_window('WeChat Reply UI test',html='<h1>Desktop runtime ready</h1>',hidden=True)
        def verify():
            window.events.loaded.wait(20)
            if window.evaluate_js('document.querySelector("h1").textContent')=='Desktop runtime ready':
                (DATA_DIR/'ui-test.json').write_text('{"ok":true}',encoding='utf-8')
            window.destroy()
        webview.start(verify,gui='edgechromium',private_mode=True);return
    k=ctypes.windll.kernel32;k.CreateMutexW.restype=ctypes.c_void_p
    mutex=k.CreateMutexW(None,True,'Local\\CodexWechatReplySingleTarget')
    if k.GetLastError()==183:
        ctypes.windll.user32.MessageBoxW(None,'回复台已运行。请使用已打开的窗口；源码版运行时请先退出源码服务。','微信回复台',0);return
    from dashboard import Application,handler
    from http.server import ThreadingHTTPServer
    app=Application();server=ThreadingHTTPServer(('127.0.0.1',0),handler(app))
    threading.Thread(target=server.serve_forever,daemon=True).start();app.contacts.start()
    window=webview.create_window('微信回复台 '+VERSION,'http://127.0.0.1:'+str(server.server_port),width=1380,height=960,min_size=(1000,700))
    try:webview.start(gui='edgechromium',private_mode=True)
    finally:
        app.contacts.stop_all();app.contacts.close();server.shutdown();server.server_close()
        # Pending model calls cannot keep a closed application alive or send later.
        os._exit(0)

if __name__=='__main__':
    try:main()
    except Exception:
        detail=traceback.format_exc();(DATA_DIR/'startup-error.log').write_text(detail,encoding='utf-8')
        if '--self-test' not in sys.argv and '--ui-smoke-test' not in sys.argv:
            ctypes.windll.user32.MessageBoxW(None,'启动失败，请查看 '+str(DATA_DIR/'startup-error.log')+'。请确认已安装 Microsoft Edge WebView2 Runtime。','微信回复台',16)
        raise
