"""Use ordinary audio downloaded by the user's QQ Music client; keep originals."""
from portable_settings import remap as _portable_path, owners as _portable_owners, settings as _portable_settings, speaker_policy as _portable_speaker, text as _portable_text, port as _portable_port, cache_for as _portable_cache
import asyncio, hashlib, json, os, re, shutil, uuid
from pathlib import Path
from .mv_fallback import comparable
PROBE = _portable_path('D:/AI/ffmpeg/bin/ffprobe.exe')
EXTENSIONS = {'.flac', '.mp3', '.wav', '.m4a', '.ogg'}

class ClientAudioProtected(RuntimeError):
    pass

def roots():
    music = Path(os.environ.get('USERPROFILE', str(Path.home()))) / 'Music'
    return [music, music / 'QQMusic']

def candidates(query):
    words = [comparable(x) for x in query.split() if x]
    result = []
    for root in roots():
        if not root.is_dir():
            continue
        for path in root.iterdir():
            if path.suffix.lower() not in EXTENSIONS or not path.is_file():
                continue
            resolved = path.resolve()
            if not resolved.is_relative_to(root.resolve()):
                continue
            compact = lambda value: re.sub('[\\W_]+', '', comparable(value))
            wanted = compact(query)
            names = [path.stem, ''.join(reversed(path.stem.split(' - ')))]
            if all((word in comparable(path.stem) for word in words)) or (wanted and any((wanted in compact(name) for name in names))):
                result.append(resolved)
    return result[:24]

async def inspect(path):
    proc = await asyncio.create_subprocess_exec(PROBE, '-v', 'error', '-show_entries', 'format=duration:format_tags=title,artist,album:stream=codec_type,codec_name', '-of', 'json', str(path), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), 12)
    except BaseException:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
        raise
    if proc.returncode:
        return None
    data = json.loads(out)
    if not any((x.get('codec_type') == 'audio' for x in data.get('streams', []))):
        return None
    fmt = data.get('format') or {}
    tags = {k.lower(): v for k, v in (fmt.get('tags') or {}).items()}
    if not tags.get('title') or not tags.get('artist'):
        return None
    return {'id': 'local:' + hashlib.sha256(str(path).encode()).hexdigest()[:20], 'name': tags['title'], 'artist': tags['artist'], 'album': tags.get('album', ''), 'duration': round(float(fmt.get('duration') or 0)), 'provider': 'local', 'page': '', 'status': '客户端已下载', '_local_path': str(path)}

async def search(query, matcher):
    found = []
    for path in candidates(query):
        try:
            song = await inspect(path)
        except (ValueError, OSError, TimeoutError):
            continue
        if song and matcher(query, {'name': song['name'], 'artists': [{'name': song['artist']}], 'album': {'name': song['album']}}):
            found.append(song)
    return found[:8]

async def acquire(service, song):
    for path in candidates(song['name']):
        try:
            local = await inspect(path)
        except (ValueError, OSError, TimeoutError):
            continue
        if not local or comparable(local['name']) != comparable(song['name']):
            continue
        if comparable(local['artist'].replace(' / ', '/')) != comparable(song['artist'].replace(' / ', '/')):
            continue
        if song.get('album') and comparable(local['album']) != comparable(song['album']):
            continue
        if song.get('duration') and abs(local['duration'] - song['duration']) > max(8, song['duration'] * 0.05):
            continue
        token = uuid.uuid4().hex
        source = service.cache / (token + '.audio')
        output = service.cache / (token + '.mp3')
        try:
            await asyncio.to_thread(shutil.copyfile, path, source)
            await service.to_mp3(source, output, song.get('duration') or local['duration'])
            song['_audio_source'] = 'QQ音乐客户端下载'
            return output
        except BaseException:
            output.unlink(missing_ok=True)
            raise
        finally:
            source.unlink(missing_ok=True)
    protected = roots()[0] / 'VipSongsDownload'
    if protected.is_dir():
        stem = comparable(song['artist'] + ' - ' + song['name'])
        for path in protected.iterdir():
            if path.suffix.lower() in {'.mgg', '.mflac', '.qmcflac', '.qmc0', '.qmcogg'}:
                name = re.sub('_[LHS]$', '', path.stem, flags=re.I)
                if comparable(name) == stem:
                    raise ClientAudioProtected('QQ音乐客户端已下载原曲，但文件是会员专用格式，无法直接转换MP3；未用MV替代。现有普通FLAC/MP3歌曲仍可使用。')
    return None
