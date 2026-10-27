"""NetEase web requests observed in the browser console; no private API keys."""
from portable_settings import remap as _portable_path, owners as _portable_owners, settings as _portable_settings, speaker_policy as _portable_speaker, text as _portable_text, port as _portable_port, cache_for as _portable_cache
import asyncio
import base64
import json
import re
import subprocess
import time
import uuid
import unicodedata
from pathlib import Path
from urllib.parse import quote, urlencode, urlparse
import aiohttp
from PIL import Image, ImageDraw, ImageFont, ImageOps
from .content_screen import POLITICS, screen_video
from .search_choices import candidate_match, rank_choices
from .mv_fallback import find_mv, remember_mv, NoPlayableMV
BASE = 'https://music.163.com'
HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130.0 Safari/537.36', 'Referer': BASE + '/', 'Accept': 'application/json,text/plain,*/*'}
MAX_AUDIO = 60 * 1024 * 1024

class LoginRequired(RuntimeError):
    pass

class AudioUnavailable(RuntimeError):
    pass

class PoliticalMediaError(ValueError):
    pass

def normalize(value):
    value = unicodedata.normalize('NFKC', str(value)).casefold()
    return re.sub('[\\s\\u200b《》“”"\\\']+', '', value)

def exact_song_match(query, song):
    """A title must match in full; an optional singer must also match in full."""
    wanted = normalize(query)
    title = normalize(song.get('name', ''))
    artists = [normalize(a.get('name', '')) for a in song.get('artists', [])]
    if not title or not wanted:
        return False
    matched = wanted == title
    match_artists = artists if len(artists) <= 1 else ['/'.join(artists), ''.join(artists)]
    for artist in match_artists:
        if artist and wanted in {artist + title, title + artist, artist + '-' + title, title + '-' + artist, artist + '—' + title, title + '—' + artist}:
            matched = True
    if not matched:
        return False
    version_tags = '翻唱|伴奏|现场|演唱会|翻自|串烧|加速版|降调版|remix|\\bcover\\b|\\blive\\b|dj版'
    metadata = ' '.join([song.get('name', ''), (song.get('album') or {}).get('name', ''), ' '.join(song.get('alias') or [])])
    if re.search(version_tags, metadata, re.I) and (not re.search(version_tags, query, re.I)):
        return False
    return True
_BROWSER_LOCKS = {}

class BrowserConsole:
    """A dedicated, loopback-only Chrome profile; never uses the user's browser."""

    def __init__(self, profile, port=_portable_port('netease'), base=BASE):
        self.profile = Path(profile)
        self.port = port
        self.base = base
        self.lock = _BROWSER_LOCKS.setdefault(port, asyncio.Lock())

    async def ensure(self):
        endpoint = f'http://127.0.0.1:{self.port}/json/list'
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=2)) as http:
            try:
                tabs = await (await http.get(endpoint)).json()
                if not any((t.get('type') == 'page' for t in tabs)):
                    async with http.put(f'http://127.0.0.1:{self.port}/json/new?{self.base}/') as response:
                        response.raise_for_status()
                        tab = await response.json()
                    await asyncio.sleep(1.5)
                    return tab
                return next((t for t in tabs if t.get('type') == 'page' and t.get('url', '').startswith(self.base)), next((t for t in tabs if t.get('type') == 'page')))
            except (aiohttp.ClientError, asyncio.TimeoutError, StopIteration):
                pass
        chrome = next((p for p in [Path(_portable_path('C:/Program Files/Google/Chrome/Application/chrome.exe')), Path(_portable_path('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'))] if p.exists()), None)
        if not chrome:
            raise RuntimeError('未找到 Chrome 或 Edge')
        self.profile.mkdir(parents=True, exist_ok=True)
        subprocess.Popen([str(chrome), '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check', '--remote-debugging-address=127.0.0.1', f'--remote-debugging-port={self.port}', f'--user-data-dir={self.profile}', self.base + '/'], creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(30):
            await asyncio.sleep(0.25)
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=1)) as http:
                try:
                    tabs = await (await http.get(endpoint)).json()
                    return next((t for t in tabs if t.get('type') == 'page'))
                except (aiohttp.ClientError, asyncio.TimeoutError, StopIteration):
                    continue
        raise RuntimeError('音乐浏览器启动超时')

    async def request(self, path, form=None):
        async with self.lock:
            tab = await self.ensure()
            async with aiohttp.ClientSession() as http, http.ws_connect(tab['webSocketDebuggerUrl']) as ws:

                async def call(serial, method, params):
                    await ws.send_json({'id': serial, 'method': method, 'params': params})
                    while True:
                        msg = await ws.receive_json(timeout=12)
                        if msg.get('id') == serial:
                            if 'error' in msg:
                                raise RuntimeError(str(msg['error']))
                            return msg.get('result', {})
                if not tab.get('url', '').startswith(self.base):
                    await call(1, 'Page.navigate', {'url': self.base + '/'})
                    await asyncio.sleep(1)
                options = {'method': 'POST' if form is not None else 'GET', 'credentials': 'same-origin'}
                if form is not None:
                    options['headers'] = {'Content-Type': 'application/x-www-form-urlencoded'}
                    options['body'] = urlencode(form)
                expression = '(async()=>{const o=' + json.dumps(options) + ';o.signal=AbortSignal.timeout(6500);const r=await fetch(' + json.dumps(path) + ',o);if(!r.ok)throw new Error("HTTP "+r.status);return await r.json();})()'
                result = await call(2, 'Runtime.evaluate', {'expression': expression, 'awaitPromise': True, 'returnByValue': True})
                if result.get('exceptionDetails'):
                    raise RuntimeError('网页请求失败')
                value = result.get('result', {}).get('value')
                if not isinstance(value, dict):
                    raise RuntimeError('网页未返回有效数据')
                return value

    async def qq_api(self, module, method, param):
        async with self.lock:
            tab = await self.ensure()
            data = {'comm': {'ct': 24, 'cv': 0, 'format': 'json', 'uin': 0}, 'req_1': {'module': module, 'method': method, 'param': param}}
            expression = "(async()=>{for(const host of ['u.y.qq.com','t.y.qq.com']){try{const r=await fetch('https://'+host+'/cgi-bin/musicu.fcg',{method:'POST',credentials:'include',headers:{'Content-Type':'application/json'},signal:AbortSignal.timeout(6000),body:JSON.stringify(" + json.dumps(data, ensure_ascii=False) + ")});const d=await r.json();if(d.req_1?.code===0)return d;}catch(e){}}throw new Error('QQMusic network unavailable')})()"
            async with aiohttp.ClientSession() as http, http.ws_connect(tab['webSocketDebuggerUrl']) as ws:
                await ws.send_json({'id': 1, 'method': 'Runtime.evaluate', 'params': {'expression': expression, 'awaitPromise': True, 'returnByValue': True}})
                while True:
                    msg = await ws.receive_json(timeout=16)
                    if msg.get('id') == 1:
                        if msg.get('result', {}).get('exceptionDetails'):
                            raise RuntimeError('QQ音乐网页网络请求失败，请稍后重试')
                        result = msg.get('result', {}).get('result', {}).get('value')
                        if not isinstance(result, dict):
                            raise RuntimeError('QQ音乐网页请求失败')
                        item = result.get('req_1') or {}
                        if item.get('code') != 0:
                            raise RuntimeError('QQ音乐接口返回状态 ' + str(item.get('code')))
                        return item.get('data') or {}

    async def qq_play_url(self, song):
        from .web_player import play_url
        async with self.lock:
            return await play_url(self, song)

    async def search_page(self, query):
        """Read the actual website's search response, not the deprecated API."""
        async with self.lock:
            tab = await self.ensure()
            async with aiohttp.ClientSession() as http, http.ws_connect(tab['webSocketDebuggerUrl']) as ws:
                await ws.send_json({'id': 1, 'method': 'Network.enable', 'params': {}})
                await ws.send_json({'id': 2, 'method': 'Page.navigate', 'params': {'url': BASE + '/#/search/m/?' + urlencode({'s': query, 'type': 1, '_request': uuid.uuid4().hex}, quote_via=quote)}})
                deadline = time.monotonic() + 22
                requests = set()
                bodies = set()
                serial = 100
                while time.monotonic() < deadline:
                    try:
                        message = await ws.receive_json(timeout=3)
                    except asyncio.TimeoutError:
                        continue
                    method = message.get('method')
                    params = message.get('params', {})
                    if method == 'Network.responseReceived':
                        url = params.get('response', {}).get('url', '')
                        if '/weapi/cloudsearch/get/web' in url or '/weapi/search/get' in url:
                            requests.add(params['requestId'])
                    elif method == 'Network.loadingFinished' and params.get('requestId') in requests:
                        serial += 1
                        bodies.add(serial)
                        await ws.send_json({'id': serial, 'method': 'Network.getResponseBody', 'params': {'requestId': params['requestId']}})
                    elif message.get('id') in bodies and 'result' in message:
                        result = message['result']
                        body = result.get('body', '')
                        if result.get('base64Encoded'):
                            body = base64.b64decode(body).decode('utf-8')
                        data = json.loads(body)
                        if data.get('code') in {301, 302, 401, 50000005}:
                            raise LoginRequired('网易云实际网页搜索要求登录')
                        if data.get('code') == 200:
                            if isinstance(data.get('result'), str):
                                expression = '(()=>{\n                                  const d=document.querySelector(\'#g_iframe\')?.contentDocument;\n                                  if(!d)return null;\n                                  const input=d.querySelector(\'#m-search-input\');\n                                  const rows=[...d.querySelectorAll(\'.srchsongst .item\')];\n                                  const songs=rows.map(row=>{\n                                    const a=row.querySelector(\'a[href*="/song?id="]\');\n                                    if(!a)return null;\n                                    const title=a.querySelector(\'b\');\n                                    const artist=row.querySelector(\'.w1 .text\');\n                                    const artists=[...row.querySelectorAll(\'.w1 a[href*="/artist?id="]\')].map(x=>({name:x.innerText.trim()}));\n                                    if(!artists.length&&artist)artists.push({name:artist.innerText.trim()});\n                                    const album=row.querySelector(\'.w2 .text\');\n                                    const clock=[...row.querySelectorAll(\'.td\')].map(x=>x.innerText.trim()).find(x=>/^\\d{1,3}:\\d{2}$/.test(x))||\'0:00\';\n                                    const [minutes,seconds]=clock.split(\':\').map(Number);\n                                    return {id:Number(new URL(a.href).searchParams.get(\'id\')),name:title?.getAttribute(\'title\')||a.innerText.trim(),\n                                      artists,album:{name:album?.innerText.trim()||\'\'},duration:(minutes*60+seconds)*1000};\n                                  }).filter(Boolean);\n                                  const tag=rows[0]?.querySelector(\'[data-res-data]\')?.getAttribute(\'data-res-data\');\n                                  return {query:tag||input?.value||\'\',songs,text:d.body.innerText.slice(0,200)};\n                                })()'
                                for tick in range(35):
                                    await ws.send_json({'id': 1000 + tick, 'method': 'Runtime.evaluate', 'params': {'expression': expression, 'returnByValue': True}})
                                    while True:
                                        rendered = await ws.receive_json(timeout=5)
                                        if rendered.get('id') == 1000 + tick:
                                            ui = rendered.get('result', {}).get('result', {}).get('value') or {}
                                            break
                                    if normalize(ui.get('query', '')) == normalize(query) and ui.get('songs'):
                                        return {'code': 200, 'result': {'songs': ui['songs']}}
                                    if normalize(ui.get('query', '')) == normalize(query) and re.search('找到\\s*0\\s*首|没有找到', ui.get('text', '')):
                                        return {'code': 200, 'result': {'songs': []}}
                                    await asyncio.sleep(0.2)
                                raise RuntimeError('网页未展示与当前关键词一致的搜索结果')
                            return data
                        raise RuntimeError('网易云网页搜索返回状态 ' + str(data.get('code')))
                raise RuntimeError('网易云实际网页搜索超时')

class MusicService:

    def __init__(self, folder, logger=None, browser_port=_portable_port('netease')):
        self.folder = Path(folder)
        self.cache = _portable_cache(__file__, 'cache')
        self.cache.mkdir(parents=True, exist_ok=True)
        self.browser = BrowserConsole(self.folder / 'browser-profile', browser_port)
        self.qq_browser = BrowserConsole(self.folder / 'qq-browser-profile', _portable_port('qq_music'), 'https://y.qq.com')
        self.logger = logger
        self.download_limit = asyncio.Semaphore(2)
        for path in self.cache.glob('*'):
            if path.is_file() and time.time() - path.stat().st_mtime > 3600:
                try:
                    path.unlink()
                except OSError:
                    pass

    async def request(self, path, form=None):
        try:
            return await asyncio.wait_for(self.browser.request(path, form), timeout=13)
        except (aiohttp.ClientError, asyncio.TimeoutError, RuntimeError, OSError) as exc:
            if self.logger:
                self.logger.warning('音乐网页控制台请求失败，复用相同 HTTP 请求重试：%s', type(exc).__name__)
        async with aiohttp.ClientSession(headers=HEADERS, timeout=aiohttp.ClientTimeout(total=15)) as http:
            async with http.request('POST' if form is not None else 'GET', BASE + path, data=form) as response:
                response.raise_for_status()
                data = await response.json(content_type=None)
                if not isinstance(data, dict):
                    raise RuntimeError('音乐接口返回格式异常')
                return data

    async def search(self, query):
        try:
            data = await self.qq_browser.qq_api('music.search.SearchCgiService', 'DoSearchForQQMusicDesktop', {'grp': 1, 'num_per_page': 50, 'page_num': 1, 'query': query[:100], 'search_type': 0})
            raw = (data.get('body') or {}).get('song', {}).get('list', [])
            songs = []
            seen = set()
            for song in raw:
                normalized = {'name': song.get('name', ''), 'artists': song.get('singer') or [], 'album': song.get('album') or {}, 'alias': [str(song.get('title') or ''), str(song.get('subtitle') or '')]}
                if not song.get('name') or not song.get('mid') or song.get('mid') in seen:
                    continue
                seen.add(song['mid'])
                songs.append({'id': song['mid'], 'name': song.get('title') or song['name'], 'artist': ' / '.join((a['name'] for a in song.get('singer', []))), 'album': (song.get('album') or {}).get('name', ''), 'duration': int(song.get('interval') or 0), '_catalog_name': song['name'], 'media_mid': (song.get('file') or {}).get('media_mid', ''), 'provider': 'qq', 'page': 'https://y.qq.com/n/ryqq_v2/songDetail/' + song['mid'], 'status': '待网页确认'})
                if len(songs) == 50:
                    break
            if songs:
                return rank_choices(query, songs)
        except (aiohttp.ClientError, asyncio.TimeoutError, RuntimeError, OSError) as exc:
            if self.logger:
                self.logger.warning('QQ音乐网页搜索暂不可用，继续网易云：%s', type(exc).__name__)
        return await self.search_netease(query)

    async def search_netease(self, query):
        result = await self.browser.search_page(query[:100])
        if result.get('code') != 200:
            raise RuntimeError('网易云搜索暂时不可用')
        songs = []
        seen = set()
        for song in (result.get('result') or {}).get('songs', []):
            song = dict(song)
            song['artists'] = song.get('artists') or song.get('ar') or []
            song['album'] = song.get('album') or song.get('al') or {}
            song['duration'] = song.get('duration') or song.get('dt') or 0
            if not song.get('name') or int(song['id']) in seen:
                continue
            seen.add(int(song['id']))
            songs.append({'id': int(song['id']), 'name': str(song.get('name') or '未命名歌曲'), 'artist': ' / '.join((a.get('name', '') for a in song.get('artists', []))) or '未知歌手', 'album': (song.get('album') or {}).get('name', ''), 'duration': int(song.get('duration') or 0) // 1000, 'provider': 'netease', 'page': f"https://music.163.com/#/song?id={int(song['id'])}", 'status': '待选歌检查'})
            if len(songs) == 50:
                break
        songs = rank_choices(query, songs)
        if songs:
            try:
                playable = await self.resolve([s['id'] for s in songs])
                for song in songs:
                    song['status'] = '可播放' if self.usable(playable.get(song['id'], {})) else '待网页确认'
            except (aiohttp.ClientError, asyncio.TimeoutError, RuntimeError, ValueError):
                pass
        return songs

    async def resolve(self, ids):
        data = await self.request('/api/song/enhance/player/url?' + urlencode({'ids': json.dumps(ids), 'br': 128000}))
        if data.get('code') != 200:
            raise RuntimeError('播放地址获取失败')
        return {int(item['id']): item for item in data.get('data', [])}

    @staticmethod
    def usable(info):
        return bool(info.get('url')) and info.get('code') == 200 and (not info.get('freeTrialInfo'))

    @staticmethod
    def audio_url(url):
        parsed = urlparse(url)
        host = (parsed.hostname or '').lower()
        if parsed.scheme not in {'http', 'https'} or not (host == 'music.163.com' or host.endswith('.music.126.net') or host.endswith('.music.163.com') or host.endswith('.qqmusic.qq.com') or host.endswith('.qqmusic.tc.qq.com') or host.endswith('.bilivideo.com') or host.endswith('.bilivideo.cn') or host.endswith('.video.qq.com') or host.endswith('.video.gtimg.com') or host.endswith('.tc.qq.com') or host.endswith('.music.qq.com')):
            raise RuntimeError('音频来源域名不符合预期')
        return url

    async def download(self, song):
        async with self.download_limit:
            if song.get('provider') == 'local':
                raise AudioUnavailable('音源已切换为网页端，请重新点歌或翻唱并选择网页歌曲')
            if song.get('provider') == 'qq':
                failure = None
                for attempt in range(2):
                    try:
                        selected = dict(song, _refresh_media=bool(attempt))
                        url = await self.qq_browser.qq_play_url(selected)
                        return await self.download_url(self.audio_url(url), song)
                    except (PermissionError, RuntimeError, aiohttp.ClientError, asyncio.TimeoutError) as exc:
                        failure = exc
                        if self.logger:
                            self.logger.warning('QQ音乐原曲获取未完成，尝试 %s/2，原因类型：%s', attempt + 1, type(exc).__name__)
                reason = str(failure) if isinstance(failure, RuntimeError) else ''
                if '试听' in reason:
                    message = '所选歌曲当前网页仅返回试听片段，未取得完整音频；不会换歌或换成MV版。'
                else:
                    message = 'QQ音乐网页播放或音频采集暂未完成，已自动重试；不能据此判断登录失效。请稍后重试，不会换歌或换成MV版。'
                raise AudioUnavailable(message) from failure
            try:
                info = (await self.resolve([song['id']])).get(song['id'], {})
            except (aiohttp.ClientError, asyncio.TimeoutError, RuntimeError, ValueError):
                info = {}
            urls = [info['url']] if self.usable(info) else []
            urls.append(BASE + '/song/media/outer/url?' + urlencode({'id': str(song['id']) + '.mp3'}))
            failures = []
            for url in dict.fromkeys(urls):
                try:
                    return await self.download_url(self.audio_url(url), song)
                except (aiohttp.ClientError, asyncio.TimeoutError, RuntimeError, ValueError, OSError) as exc:
                    failures.append(type(exc).__name__ + ': ' + str(exc))
            if self.logger:
                self.logger.warning('歌曲 %s 官方网页资源未取得完整音频：%s', song['id'], '; '.join(failures))
            raise PermissionError('官方网页接口没有返回这首歌的完整音频，可能只有试听或需要登录权限')

    async def download_url(self, url, song):
        if song.get('_from_mv') and POLITICS.search(song['name'] + ' ' + song['artist'] + ' ' + song.get('_mv_title', '')):
            raise PoliticalMediaError('我拒绝。')
        token = uuid.uuid4().hex
        source = self.cache / (token + '.audio')
        mp3 = self.cache / (token + '.mp3')
        try:
            headers = dict(HEADERS)
            if song.get('provider') == 'qq':
                headers['Referer'] = 'https://y.qq.com/'
            if song.get('_mv_provider') == 'bilibili':
                headers['Referer'] = 'https://www.bilibili.com/'
            limit = 250 * 1024 * 1024 if song.get('_from_mv') else MAX_AUDIO
            async with aiohttp.ClientSession(headers=headers, timeout=aiohttp.ClientTimeout(total=100, sock_read=25)) as http:
                for _ in range(5):
                    async with http.get(url, allow_redirects=False) as response:
                        if response.status in {301, 302, 303, 307, 308}:
                            from urllib.parse import urljoin
                            url = self.audio_url(urljoin(url, response.headers['Location']))
                            continue
                        response.raise_for_status()
                        if response.content_length and response.content_length > limit:
                            raise RuntimeError('媒体文件超过大小上限')
                        total = 0
                        with source.open('wb') as output:
                            async for chunk in response.content.iter_chunked(65536):
                                total += len(chunk)
                                if total > limit:
                                    raise RuntimeError('媒体文件超过大小上限')
                                output.write(chunk)
                        break
                else:
                    raise RuntimeError('音频重定向次数过多')
            if not source.exists() or source.stat().st_size < 1024:
                raise RuntimeError('音频文件为空或不完整')
            if song.get('_from_mv'):
                verdict = await screen_video(source, song['name'] + ' ' + song['artist'] + ' ' + song.get('_mv_title', ''))
                if verdict == 'reject':
                    raise PoliticalMediaError('我拒绝。')
                if verdict != 'allow':
                    raise RuntimeError('暂时无法完成MV内容筛查，这次不发送')
            await self.to_mp3(source, mp3, song.get('duration', 0))
            return mp3
        except BaseException:
            mp3.unlink(missing_ok=True)
            raise
        finally:
            source.unlink(missing_ok=True)

    async def to_mp3(self, source, destination, expected_duration=0):
        probe = _portable_path('D:/AI/ffmpeg/bin/ffprobe.exe')
        convert = _portable_path('D:/AI/ffmpeg/bin/ffmpeg.exe')
        proc = await asyncio.create_subprocess_exec(probe, '-v', 'error', '-show_entries', 'stream=codec_name,codec_type:format=duration', '-of', 'json', str(source), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout=20)
        except BaseException:
            proc.kill()
            await proc.wait()
            raise
        if proc.returncode:
            raise RuntimeError('下载内容不是有效音频')
        metadata = json.loads(out)
        streams = metadata.get('streams', [])
        if not any((s.get('codec_type') == 'audio' for s in streams)):
            raise RuntimeError('下载内容不含音轨')
        actual_duration = float((metadata.get('format') or {}).get('duration') or 0)
        if expected_duration and abs(actual_duration - expected_duration) > max(8, expected_duration * 0.05):
            raise RuntimeError('下载音频时长与选中歌曲不符，可能只有试听片段，已取消发送')
        if any((s.get('codec_name') == 'mp3' for s in streams)):
            source.replace(destination)
            return
        proc = await asyncio.create_subprocess_exec(convert, '-y', '-v', 'error', '-i', str(source), '-vn', '-c:a', 'libmp3lame', '-b:a', '192k', str(destination), stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
        try:
            await asyncio.wait_for(proc.communicate(), timeout=90)
        except BaseException:
            proc.kill()
            await proc.wait()
            raise
        if proc.returncode:
            raise RuntimeError('MP3 转码失败')

def safe_filename(song):
    text = re.sub('[\\x00-\\x1f<>:"/\\\\|?*]', '_', song['name'] + ' - ' + song['artist'])
    return text.strip(' .')[:100] + '.mp3'

def render_card(background, songs, query, output, *, mode='music'):
    width, height = (1080, 1440)
    image = ImageOps.fit(Image.open(background).convert('RGB'), (width, height), centering=(0.5, 0.36)).convert('RGBA')
    tint = Image.new('RGBA', image.size)
    d = ImageDraw.Draw(tint)
    for y in range(height):
        alpha = int(40 + 90 * y / height)
        d.line((0, y, width, y), fill=(8, 22, 44, alpha))
    image = Image.alpha_composite(image, tint)
    layer = Image.new('RGBA', image.size)
    d = ImageDraw.Draw(layer)
    regular = _portable_path('C:/Windows/Fonts/msyh.ttc')
    bold = _portable_path('C:/Windows/Fonts/msyhbd.ttc')
    font = lambda n, b=False: ImageFont.truetype(bold if b else regular, n)

    def text(pos, value, size, fill='#F8FCFF', b=False):
        d.text(pos, str(value), font=font(size, b), fill=fill)

    def fit(value, size, max_width):
        value = str(value)
        f = font(size)
        if d.textlength(value, font=f) <= max_width:
            return value
        while value and d.textlength(value + '…', font=f) > max_width:
            value = value[:-1]
        return value + '…'
    d.rounded_rectangle((44, 48, 1036, 246), radius=28, fill=(7, 26, 50, 175))
    text((78, 65), '本地助手翻唱台' if mode == 'cover' else '本地助手点歌台', 56, b=True)
    text((80, 147), fit('搜索：' + query, 30, 860), 30)
    platform = 'QQ音乐' if songs and songs[0].get('provider') == 'qq' else '网易云音乐'
    text((80, 197), platform + '  /  搜到 ' + str(len(songs)) + ' 首', 23, '#BDEEFF')
    d.rounded_rectangle((44, 274, 1036, 336), radius=18, fill=(9, 35, 57, 224))
    for x, label in [(72, '序号'), (178, '歌曲 / 专辑'), (635, '歌手'), (934, '时长')]:
        text((x, 289), label, 23, '#BDEEFF', True)
    for index, song in enumerate(songs):
        top = 351 + index * 111
        d.rounded_rectangle((44, top, 1036, top + 99), radius=19, fill=(7, 23, 43, 188))
        d.rounded_rectangle((69, top + 22, 129, top + 78), radius=16, fill=(112, 225, 248, 240))
        text((87, top + 28), index + 1, 28, '#09263C', True)
        text((178, top + 12), fit(song['name'], 28, 425), 28, b=True)
        detail = fit(song.get('album', ''), 20, 280)
        text((178, top + 58), detail, 20, '#CDDFED')
        status = song.get('status', '待选歌检查')
        text((490, top + 60), '可播' if status == '可播放' else '待确认' if status in {'待选歌检查', '待网页确认'} else '受限', 19, '#9CF5CD' if status == '可播放' else '#FFD99C')
        text((635, top + 30), fit(song['artist'], 24, 265), 24)
        seconds = song.get('duration', 0)
        text((930, top + 32), f'{seconds // 60}:{seconds % 60:02}', 23)
    d.rounded_rectangle((44, 1270, 1036, 1388), radius=24, fill=(7, 26, 50, 224))
    text((76, 1285), '直接回复数字选歌 · 回复 0 取消', 32, b=True)
    text((77, 1340), '仅发起者可选 · 30 分钟有效 · 选歌后选择 PTH 和 INDEX' if mode == 'cover' else '仅点歌人可选 · 3 分钟有效 · 发送 MP3 文件', 23, '#BDEEFF')
    image = Image.alpha_composite(image, layer).convert('RGB')
    image.save(output, 'PNG', optimize=True)
    return Path(output)
