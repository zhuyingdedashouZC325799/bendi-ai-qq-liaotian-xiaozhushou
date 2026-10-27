import html,json,re,ctypes,asyncio
from pathlib import Path
from urllib.parse import urlencode
import aiohttp

class NoPlayableMV(RuntimeError):
    pass

def comparable(text):
    text=str(text)
    try:
        fn=ctypes.windll.kernel32.LCMapStringEx
        fn.argtypes=[ctypes.c_wchar_p,ctypes.c_uint,ctypes.c_wchar_p,ctypes.c_int,ctypes.c_wchar_p,ctypes.c_int,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_longlong]
        size=fn('zh-CN',0x02000000,text,-1,None,0,None,None,0)
        if size:
            buffer=ctypes.create_unicode_buffer(size)
            if fn('zh-CN',0x02000000,text,-1,buffer,size,None,None,0):return buffer.value.casefold()
    except (AttributeError,OSError):pass
    return text.casefold()

def key(song):return song['name'].strip()+'|'+song['artist'].strip()
def plain(text):return html.unescape(re.sub('<[^>]+>','',str(text)))
def matches(song,title):
    title=plain(title)
    normalized=comparable(title)
    if comparable(song['name']) not in normalized or not all(comparable(a.strip()) in normalized for a in song['artist'].split('/')):return False
    if re.search(r'翻唱|伴奏|现场|演唱会|混音|混剪|合唱|串烧|改编|翻弹|指弹|女版|男版|解说|reaction|live|cover|remix|[\u4e00-\u9fff][xX×][\u4e00-\u9fff]|》\s*[xX×+]',title,re.I):return False
    return True

async def find_mv(service,song):
    headers={'User-Agent':'Mozilla/5.0','Referer':'https://www.bilibili.com/'}
    cachefile=service.folder/'mv_sources.json'
    try:cached=json.loads(cachefile.read_text(encoding='utf-8'))
    except (FileNotFoundError,ValueError):cached={}
    pages=[]
    if key(song) in cached:pages.append(cached[key(song)]['page'])
    # Reuse verified MV pages before repeating music authorization calls.
    if not pages:
        # First use the official MV linked to this exact song ID.
        try:
            detail=await service.qq_browser.qq_api('music.pf_song_detail_svr','get_song_detail_yqq',{'song_mid':song['id'],'song_type':0})
            track=detail.get('track_info') or {};vid=(track.get('mv') or {}).get('vid')
            if vid:
                meta=await service.qq_browser.qq_api('video.VideoDataServer','get_video_info_batch',{'vidlist':[vid],'required':['vid','name','singers','duration']})
                item=meta.get(vid) or {};urls=await service.qq_browser.qq_api('gosrf.Stream.MvUrlProxy','GetMvUrls',{'vids':[vid],'request_typet':10001})
                for quality in (urls.get(vid) or {}).get('mp4',[]):
                    choices=quality.get('freeflow_url') or quality.get('url') or []
                    if choices:return {'url':choices[-1],'duration':int(item.get('duration') or song['duration']),
                                       'title':item.get('name') or song['name'],'page':'https://y.qq.com/n/ryqq_v2/mv/'+vid,'provider':'qq'}
        except (RuntimeError,OSError,aiohttp.ClientError,TimeoutError):pass
    async with aiohttp.ClientSession(headers=headers,timeout=aiohttp.ClientTimeout(total=40)) as http:
        if not pages:
            query=song['artist']+' '+song['name']+' MV'
            try:
                async with http.get('https://api.bilibili.com/x/web-interface/search/type',params={'search_type':'video','keyword':query,'page':1}) as r:
                    r.raise_for_status();data=await r.json(content_type=None)
                for item in (data.get('data') or {}).get('result',[]):
                    title=plain(item.get('title',''));tags=plain(item.get('tag',''))+' '+str(item.get('typename',''))
                    if matches(song,title) and re.search(r'MV|音乐视频',title+' '+tags,re.I) and item.get('bvid'):
                        pages.append('https://www.bilibili.com/video/'+item['bvid']+'/')
            except (ValueError,aiohttp.ClientError,TimeoutError):pass
        for page in pages[:5]:
            try:
                from data.plugins.video_parse.parse_transport import parse_payload
                payload=await asyncio.to_thread(parse_payload,'bilibili/bilibili.php',page)
                info=payload.get('data') or {};duration=int(info.get('duration') or 0)
                if payload.get('code')!=200 or not info.get('url') or not matches(song,info.get('title','')):continue
                if not song['duration']*.85<=duration<=song['duration']*1.25:continue
                return {'url':info['url'],'duration':duration,'title':info['title'],'page':page,'provider':'bilibili'}
            except (ValueError,aiohttp.ClientError,TimeoutError):continue
    raise NoPlayableMV('没有找到歌名、歌手及完整时长均匹配的可播放MV')

def remember_mv(service,song,mv):
    if mv.get('provider')!='bilibili':return
    path=service.folder/'mv_sources.json'
    try:data=json.loads(path.read_text(encoding='utf-8'))
    except (FileNotFoundError,ValueError):data={}
    data[key(song)]={'page':mv['page'],'title':mv['title'],'duration':mv['duration']}
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8');temp.replace(path)
