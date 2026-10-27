"""Observe the selected song in both QQ Music detail and separate player tabs."""
import asyncio,json,time,logging
from urllib.parse import quote,urlsplit
import aiohttp
from collections import deque

async def play_url(browser,song):
    log=logging.getLogger(__name__)
    async with aiohttp.ClientSession() as http:
        await browser.ensure()
        version=await(await http.get(f'http://127.0.0.1:{browser.port}/json/version')).json()
        async with http.ws_connect(version['webSocketDebuggerUrl']) as ws:
            serial=0;sessions={};targets={};pending={};clicked=set();backlog=deque();retired=set()
            async def send(method,params=None,session=None):
                nonlocal serial
                serial+=1;msg={'id':serial,'method':method,'params':params or {}}
                if session:msg['sessionId']=session
                await ws.send_json(msg);return serial
            async def call(method,params=None,session=None):
                ident=await send(method,params,session)
                while True:
                    msg=await ws.receive_json(timeout=10)
                    if msg.get('id')==ident:
                        if msg.get('error'):raise RuntimeError(msg['error'].get('message','Browser command failed'))
                        return msg.get('result',{})
                    backlog.append(msg)
            async def finish(url):
                # Wait for pause commands to complete before closing CDP.
                for session in list(sessions):
                    try:
                        await call('Runtime.evaluate',{'expression':"(()=>{document.querySelectorAll('audio,video').forEach(e=>e.pause());const b=document.querySelector('.btn_big_play--pause');if(b)b.click()})()"},session)
                    except (RuntimeError,asyncio.TimeoutError):pass
                return url
            async def attach(target):
                tid=target['targetId']
                if tid in targets:return
                sid=(await call('Target.attachToTarget',{'targetId':tid,'flatten':True}))['sessionId']
                targets[tid]=sid;sessions[sid]={'target':tid,'player':'/player' in target.get('url','')}
                await call('Page.setWebLifecycleState',{'state':'active'},sid)
                await call('Network.enable',{},sid);await call('Page.enable',{},sid)
                if song.get('_refresh_media'):await call('Network.setCacheDisabled',{'cacheDisabled':True},sid)
            await call('Target.setDiscoverTargets',{'discover':True})
            infos=(await call('Target.getTargets'))['targetInfos']
            pages=[t for t in infos if t.get('type')=='page' and t.get('url','').startswith(browser.base)]
            players=[t for t in pages if '/player' in t['url']]
            for target in players[2:]:
                retired.add(target['targetId'])
                await call('Target.closeTarget',{'targetId':target['targetId']})
            pages=[t for t in pages if t['targetId'] not in retired]
            # Old background detail renderers can become unresponsive. Recreate only
            # our detail tabs; retain the authenticated player and browser profile.
            for target in pages:
                if '/player' not in target['url']:
                    retired.add(target['targetId'])
                    await call('Target.closeTarget',{'targetId':target['targetId']})
            pages=[t for t in pages if '/player' in t['url']]
            tid=(await call('Target.createTarget',{'url':'about:blank','background':True}))['targetId']
            detail={'targetId':tid,'url':'about:blank','type':'page'};pages.append(detail)
            for target in pages:await attach(target)
            sid=targets[detail['targetId']]
            await call('Page.navigate',{'url':browser.base+'/n/ryqq_v2/songDetail/'+quote(str(song['id']))},sid)
            started=time.monotonic();last=0
            while time.monotonic()-started<45:
                if time.monotonic()-started>2 and time.monotonic()-last>.6:
                    last=time.monotonic()
                    for session,meta in list(sessions.items()):
                        expr=("(()=>{const visible=e=>e&&e.getBoundingClientRect().width>0&&e.getBoundingClientRect().height>0;"
                          "const confirm=[...document.querySelectorAll('a,button')].find(e=>visible(e)&&e.innerText.trim()==='开始播放');"
                          "const media="+("[]" if song.get('_refresh_media') else "performance.getEntriesByType('resource').map(r=>r.name).filter(v=>{try{const u=new URL(v);return (u.hostname.endsWith('.qqmusic.qq.com')||u.hostname.endsWith('.qqmusic.tc.qq.com'))&&u.pathname.includes("+json.dumps(str(song.get('media_mid') or song['id']))+")}catch(e){return false}})")+";if(media.length)return {media:media[media.length-1]};"
                          "const selected=!!document.querySelector('a[href*=\"/songDetail/"+str(song['id'])+"\"]')||document.body.innerText.includes("
                          +json.dumps(song['name']+' - '+song['artist'])+");"
                          "if(selected&&document.body.innerText.includes('试听中，完整播放需要开通会员'))return {preview:true};"
                          "let b=confirm;if(!b&&!"+str(session in clicked).lower()+"){"
                          "if(location.pathname.endsWith('/'+"+json.dumps(str(song['id']))+"))"
                          "b=[...document.querySelectorAll('a.mod_btn_green,button.mod_btn_green')].find(e=>visible(e)&&/播放/.test(e.innerText));"
                          "if(!b&&selected)b=document.querySelector('.btn_big_play:not(.btn_big_play--pause)');}"
                          "if(!visible(b))return null;const r=b.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()")
                        ident=await send('Runtime.evaluate',{'expression':expr,'returnByValue':True,'userGesture':True},session)
                        pending[ident]=session
                try:msg=backlog.popleft() if backlog else await ws.receive_json(timeout=.4)
                except asyncio.TimeoutError:continue
                method=msg.get('method');params=msg.get('params',{})
                if method=='Target.targetCreated':
                    target=params['targetInfo']
                    if target['targetId'] in retired:continue
                    if target.get('type')=='page' and target.get('url','').startswith(browser.base):await attach(target)
                if method=='Target.targetInfoChanged':
                    target=params['targetInfo']
                    if target['targetId'] in retired:continue
                    if target.get('type')=='page' and target.get('url','').startswith(browser.base) and target['targetId'] not in targets:await attach(target)
                if msg.get('id') in pending:
                    session=pending.pop(msg['id']);point=msg.get('result',{}).get('result',{}).get('value')
                    if isinstance(point,dict) and point.get('media'):return await finish(point['media'])
                    if isinstance(point,dict) and point.get('preview'):raise RuntimeError('QQ音乐网页当前账号对所选原曲只返回试听')
                    if isinstance(point,dict) and 'x' in point:
                        clicked.add(session)
                        for kind in ('mousePressed','mouseReleased'):
                            await send('Input.dispatchMouseEvent',{'type':kind,'x':point['x'],'y':point['y'],'button':'left','clickCount':1},session)
                if method=='Network.responseReceived':
                    response=params['response'];url=response.get('url','');parts=urlsplit(url);host=(parts.hostname or '').lower()
                    if host.endswith('.qqmusic.qq.com') or host.endswith('.qqmusic.tc.qq.com'):
                        expected=bool(song.get('media_mid') and song['media_mid'] in parts.path)
                        log.info('QQ网页音频响应：host=%s status=%s selected_media=%s',host,response.get('status'),expected)
                        if not expected or response.get('status') not in {200,206}:continue
                        return await finish(url)
            raise RuntimeError('QQ音乐网页未返回所选歌曲的完整音频地址，已检查详情页和播放器标签页')
