"""Generate a new recipient installation; never imports the developer's config."""
import argparse,copy,hashlib,json,os,re,secrets,shutil,socket,sys
from pathlib import Path

def free_port(preferred,reserved):
    for port in range(preferred,preferred+500):
        if port in reserved:continue
        try:
            with socket.socket() as s:s.bind(('127.0.0.1',port))
            reserved.add(port);return port
        except OSError:continue
    raise RuntimeError('没有可用的本地服务端口')

def main(config_file):
    path=Path(config_file);cfg=json.loads(path.read_text(encoding='utf-8-sig'))
    for field in ('install_dir','models_dir','voices_dir','cache_dir'):
        cfg[field]=str(Path(cfg[field]).resolve());Path(cfg[field]).mkdir(parents=True,exist_ok=True)
    cfg['owners']=list(dict.fromkeys(str(v).strip() for v in cfg['owners']))
    if not cfg['owners'] or any(not re.fullmatch(r'[1-9][0-9]{4,11}',v) for v in cfg['owners']):raise ValueError('至少填写一个有效主人QQ号')
    root=Path(cfg['install_dir']);models=Path(cfg['models_dir']);cache=Path(cfg['cache_dir'])
    if not cfg.get('ports'):
        used=set();cfg['ports']={name:free_port(port,used) for name,port in [('ollama',11434),('screen',11435),('dashboard',6185),('reverse_ws',6199),('php',8088),('qq_music',9226),('netease',9225),('bridge_http',3000)]}
    cfg.setdefault('bridge_token',secrets.token_urlsafe(24));cfg.setdefault('dashboard_password','Aa7_'+secrets.token_urlsafe(18))
    path.write_text(json.dumps(cfg,ensure_ascii=False,indent=2),encoding='utf-8')
    os.environ['LOCALBOT_CONFIG']=str(path);os.environ['ASTRBOT_ROOT']=str(root/'userdata')
    sys.path.insert(0,str(root/'backend/app'))
    from astrbot.core.config.default import DEFAULT_CONFIG
    from astrbot.core.utils.auth_password import hash_dashboard_password
    fresh=copy.deepcopy(DEFAULT_CONFIG)
    # Choose independent ports instead of hijacking a recipient's existing apps.
    ports=cfg['ports'];cfg.setdefault('bridge_token',secrets.token_urlsafe(24));cfg.setdefault('dashboard_password',secrets.token_urlsafe(18))
    fresh['admins_id']=cfg['owners'];fresh['wake_prefix']=[cfg.get('bot_name') or '本地助手']
    fresh['platform']=[{'id':'qq-local','type':'aiocqhttp','enable':True,'ws_reverse_host':'127.0.0.1','ws_reverse_port':ports['reverse_ws'],'ws_reverse_token':cfg['bridge_token']}]
    fresh['provider_sources']=[{'id':'ollama-local_source','type':'openai_chat_completion','provider_type':'chat_completion','provider':'openai','api_base':f"http://127.0.0.1:{ports['ollama']}/v1",'key':['ollama'],'model_configs':{},'ollama_disable_thinking':True}]
    fresh['provider']=[{'id':'ollama-local','provider_source_id':'ollama-local_source','enable':True,'model':'qwen3-vl:4b','modalities':{'name':'qwen3-vl:4b','id':'qwen3-vl:4b','vision':True},'custom_extra_body':{'max_tokens':4096,'reasoning_effort':'none','options':{'num_ctx':8192}},'ollama_disable_thinking':True}]
    fresh.setdefault('provider_settings',{})['default_provider_id']='ollama-local'
    fresh['provider_settings']['default_personality']=''
    fresh.setdefault('dashboard',{}).update({'host':'127.0.0.1','port':ports['dashboard'],'username':'admin','password':hashlib.md5(cfg['dashboard_password'].encode()).hexdigest(),'jwt_secret':secrets.token_urlsafe(48),'password_change_required':False})
    for key in ('pbkdf2_password','totp'):fresh['dashboard'].pop(key,None)
    fresh['dashboard']['pbkdf2_password']=hash_dashboard_password(cfg['dashboard_password'])
    fresh['dashboard']['password_storage_upgraded']=True
    fresh['log_file_enable']=True;fresh['log_file_path']=str(cache/'logs/astrbot.log');fresh['log_file_max_mb']=20
    fresh.setdefault('platform_settings',{})['reply_with_quote']=True
    (root/'userdata/data/plugins').mkdir(parents=True,exist_ok=True)
    for plugin in (root/'templates/plugins').iterdir():
        if plugin.name=='cover_request' and not cfg.get('enable_cover',False):continue
        shutil.copytree(plugin,root/'userdata/data/plugins'/plugin.name,dirs_exist_ok=True)
    config=root/'userdata/data/cmd_config.json'
    config.write_text(json.dumps(fresh,ensure_ascii=False,indent=2),encoding='utf-8')
    for folder in [cache/'logs',cache/'temp',cache/'video',models/'ollama',models/'rvc/assets',models/'rvc/models',Path(cfg['voices_dir']),root/'engines/legacy-rvc/assets/weights',root/'engines/legacy-rvc/assets/indices']:
        folder.mkdir(parents=True,exist_ok=True)
    # Preserve user-selected voices_dir despite the legacy pipeline's layout.
    engine=root/'userdata/data/plugins/cover_request/engine-data';engine.mkdir(parents=True,exist_ok=True)
    engine.joinpath('settings.toml').write_text('[paths]\nassets_dir = '+json.dumps(str(models/'rvc/assets').replace('\\','/'))+'\nmodels_dir = '+json.dumps(str(models/'rvc/models').replace('\\','/'))+'\n[compute]\ndevice = "cpu"\nprecision = "fp32"\ngpu_jobs = 1\n',encoding='utf-8')
    # OneBot config contains only this recipient's fresh token and bot account.
    bridge={'network':{'httpServers':[{'name':'localbot-http','enable':True,'host':'127.0.0.1','port':ports['bridge_http'],'token':cfg['bridge_token']}],
      'httpSseServers':[],'httpClients':[],'websocketServers':[],
      'websocketClients':[{'name':'localbot','enable':True,'url':f"ws://127.0.0.1:{ports['reverse_ws']}/ws",'token':cfg['bridge_token'],'reportSelfMessage':False,'messagePostFormat':'array','reconnectInterval':3000,'heartInterval':30000}]},'musicSignUrl':'','enableLocalFile2Url':True,'parseMultMsg':False}
    if cfg.get('bridge_type')=='napcat':
        bridge_root=Path(cfg.get('bridge_path') or str(root/'bridge'))
        core_root=Path(cfg.get('bridge_core_dir') or str(bridge_root/'napcat'))
        for folder in [core_root/'config',bridge_root/'config']:
            folder.mkdir(parents=True,exist_ok=True)
            if cfg.get('bot_qq'):folder.joinpath('onebot11_'+cfg['bot_qq']+'.json').write_text(json.dumps(bridge,ensure_ascii=False,indent=2),encoding='utf-8')
            folder.joinpath('onebot11.json').write_text(json.dumps(bridge,ensure_ascii=False,indent=2),encoding='utf-8')
    else:
        (root/'userdata/onebot-connection.json').write_text(json.dumps({'url':f"ws://127.0.0.1:{ports['reverse_ws']}/ws",'token':cfg['bridge_token']},indent=2),encoding='utf-8')
    path.write_text(json.dumps(cfg,ensure_ascii=False,indent=2),encoding='utf-8')
    (root/'userdata/data/dist').mkdir(parents=True,exist_ok=True)
    (root/'.localbot-package').write_text('LocalBot online distribution 1\n',encoding='utf-8')
    print('已生成全新配置；主人、人设、路径和网页登录均与其他安装隔离。',flush=True)
if __name__=='__main__':main(sys.argv[1])
