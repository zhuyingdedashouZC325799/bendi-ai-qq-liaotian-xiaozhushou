"""Recipient-only service launcher. No developer account or drive assumptions."""
import importlib.util,json,os,shutil,socket,subprocess,sys,time,traceback,urllib.request,threading
from pathlib import Path

def open_port(port):
    try:
        with socket.create_connection(('127.0.0.1',port),timeout=.3):return True
    except OSError:return False

def main(config_file):
    config_path=Path(config_file).resolve();cfg=json.loads(config_path.read_text(encoding='utf-8-sig'))
    root=Path(cfg['install_dir']);cache=Path(cfg['cache_dir']);models=Path(cfg['models_dir']);ports=cfg['ports']
    env=os.environ;env['LOCALBOT_CONFIG']=str(config_path);env['ASTRBOT_ROOT']=str(root/'userdata');env['PYTHONUTF8']='1'
    env.update(TEMP=str(cache/'temp'),TMP=str(cache/'temp'),TORCH_HOME=str(cache/'torch'),HF_HOME=str(cache/'huggingface'),NUMBA_CACHE_DIR=str(cache/'numba'),OLLAMA_MODELS=str(models/'ollama'),OLLAMA_HOST='127.0.0.1:'+str(ports['ollama']),OLLAMA_CONTEXT_LENGTH='8192',OLLAMA_NUM_PARALLEL='1',OLLAMA_MAX_LOADED_MODELS='1',OLLAMA_MAX_QUEUE='8',OLLAMA_KEEP_ALIVE='2m')
    env['PATH']=str(root/'tools/ffmpeg/bin')+os.pathsep+env.get('PATH','')
    for p in ('temp','logs','video','torch','huggingface','numba'):(cache/p).mkdir(parents=True,exist_ok=True)
    sys.path.insert(0,str(root/'backend/app'))
    spec=importlib.util.spec_from_file_location('live_console',root/'scripts/live_console.py');console_mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(console_mod)
    console_mod.PORTS={name:ports[key] for name,key in [('Ollama','ollama'),('CPU筛查','screen'),('视频解析','php'),('QQ音乐网页','qq_music'),('机器人后台','dashboard')]}
    console=console_mod.Console(cache);console.root=root
    # The original console supports a different root; override its source registry
    # with this installation's selected cache directory.
    console.logs=cache/'logs';console.reports=cache/'logs/error-reports'
    def discover():
        patterns={'机器人':cache/'logs/astrbot.log','内存监控':cache/'logs/memory-guard.log'}
        for name in ('ollama','screen-fast','video-parser','bridge'):
            files=list((cache/'logs').glob(name+'-*.log'))
            if files:patterns[name]=max(files,key=lambda p:p.stat().st_ctime_ns)
        for label,path in patterns.items():
            key=(label,0)
            if path.exists() and (key not in console.tails or console.tails[key].path!=path):console.tails[key]=console_mod.Tail(path)
    console.discover=discover
    def start(name,exe,args,port=None,folder=None,visible=False):
        if port and open_port(port):
            import psutil
            owners=[c.pid for c in psutil.net_connections(kind='tcp') if c.laddr and c.laddr.port==port and c.status=='LISTEN']
            if not owners or not any(Path(psutil.Process(pid).exe()).resolve()==Path(exe).resolve() for pid in owners if pid):raise RuntimeError('端口 '+str(port)+' 被其他程序占用，请在配置中修改端口。')
            console.emit('启动',name+' 沿用当前安装的进程',False);return
        log=cache/'logs'/(name+'-'+time.strftime('%Y%m%d-%H%M%S')+'.log')
        output=log.open('ab')
        try:subprocess.Popen([str(exe)]+list(map(str,args)),cwd=str(folder or root),env=dict(env),stdout=output,stderr=subprocess.STDOUT,creationflags=0 if visible else subprocess.CREATE_NO_WINDOW)
        finally:output.close()
        console.emit('启动',name+' 已启动',False)
    def wait(name,port,seconds=90):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            discover();console.pump()
            if open_port(port):return
            time.sleep(.5)
        raise RuntimeError(name+' 等待超时，端口 '+str(port))
    try:
        start('ollama',root/'tools/ollama/ollama.exe',['serve'],ports['ollama']);wait('Ollama',ports['ollama'])
        start('memory-guard',sys.executable,[root/'scripts/memory_guard.py'])
        manifest=json.loads((models/'ollama/manifests/registry.ollama.ai/library/qwen3-vl/4b').read_text())
        model=next(x for x in manifest['layers'] if x['mediaType']=='application/vnd.ollama.image.model')
        projector=next(x for x in manifest['layers'] if x['mediaType']=='application/vnd.ollama.image.projector')
        llama=root/'tools/ollama/lib/ollama/llama-server.exe'
        start('screen-fast',llama,['--model',models/'ollama/blobs'/model['digest'].replace(':','-'),'--mmproj',models/'ollama/blobs'/projector['digest'].replace(':','-'),'--host','127.0.0.1','--port',str(ports['screen']),'--alias','local-screen','--no-webui','--offline','--no-mmproj-offload','-ngl','0','--device','none','--image-min-tokens','64','--image-max-tokens','256','--ctx-size','4096','--parallel','1','--threads','4','--threads-batch','4','--no-jinja','--chat-template','chatml','--reasoning','off','--reasoning-budget','0','--reasoning-format','none','--load-mode','none'],ports['screen'])
        start('video-parser',root/'tools/php/php.exe',['-S','127.0.0.1:'+str(ports['php']),'-t',root/'tools/video-parser'],ports['php'])
        browser=next((p for p in [Path(os.environ.get('PROGRAMFILES','C:/Program Files'))/'Google/Chrome/Application/chrome.exe',Path(os.environ.get('PROGRAMFILES(X86)','C:/Program Files (x86)'))/'Microsoft/Edge/Application/msedge.exe'] if p.is_file()),None)
        if browser is None:raise RuntimeError('请先安装 Microsoft Edge 或 Chrome，以使用网页登录和点歌功能。')
        for key,url,profile in [('qq_music','https://y.qq.com/','qq-browser-profile'),('netease','https://music.163.com/','browser-profile')]:
            profile=root/'userdata/data/plugins/music_request'/profile;fresh=not profile.exists();profile.mkdir(parents=True,exist_ok=True)
            args=['--disable-gpu','--no-first-run','--no-default-browser-check','--remote-debugging-address=127.0.0.1','--remote-debugging-port='+str(ports[key]),'--user-data-dir='+str(profile),url]
            if not fresh or key=='netease':args.insert(0,'--headless=new')
            start('music-'+key,browser,args,ports[key],visible=fresh and key=='qq_music')
        # Plugins and launcher use the same fresh, recipient-specific profiles.
        start('astrbot',sys.executable,[root/'backend/launch_backend.py'],ports['dashboard'],root/'backend');wait('机器人后台',ports['dashboard'])
        if cfg['bridge_type']=='napcat':
            bridge_root=Path(cfg.get('bridge_path') or str(root/'bridge'))
            launchers=[bridge_root/name for name in ('launcher-user.bat','launcher.bat','napcat.bat')]
            launchers+=list(bridge_root.rglob('launcher-user.bat'))+list(bridge_root.rglob('launcher.bat'))+list(bridge_root.rglob('napcat.bat'))
            launcher=next((p for p in launchers if p.exists()),None)
            if launcher is None:
                launchers=[]
                launcher=launchers[0] if launchers else None
            if launcher is None:raise RuntimeError('NapCat 官方引导文件不存在，请重新运行安装修复。')
            # A visible third-party wizard is intentional: QQ installation,
            # permissions and login are confirmed by the recipient.
            os.startfile(str(launcher),cwd=str(launcher.parent))
            console.emit('QQ登录','请在打开的官方 QQ / NapCat 窗口完成安装及扫码登录。',False)
        else:
            console.emit('QQ登录','请独立启动自己的 SnowLuma，配置反向 WebSocket：ws://127.0.0.1:'+str(ports['reverse_ws'])+'/ws；连接令牌见本机 localbot.json。',False)
        def watch_bridge():
            while not console.stop:
                if open_port(ports['bridge_http']):console_mod.PORTS['QQ接入']=ports['bridge_http'];return
                time.sleep(3)
        threading.Thread(target=watch_bridge,daemon=True).start()
        console.emit('登录','QQ音乐请使用自己有播放权限的账号登录；新安装不含任何旧登录信息。',False)
        console.emit('配置','人设和主人号由 localbot.json 中的 persona、owners 设置；后台 http://127.0.0.1:'+str(ports['dashboard']),False)
        console.emit('后台账号','用户名 admin；初始随机密码在本机 localbot.json 中的 dashboard_password。',False)
        console.run(no_start=True)
    except KeyboardInterrupt:pass
    except Exception as error:
        console.emit('启动','ERROR '+str(error));console.report(traceback.format_exc(),'startup')
        input('启动未完成，错误报告已保存。按回车关闭日志窗口。')

if __name__=='__main__':main(sys.argv[1])
