"""QQ song -> UVR5 stems -> local RVC -> vocal/accompaniment mix."""
from portable_settings import remap as _portable_path, owners as _portable_owners, settings as _portable_settings, speaker_policy as _portable_speaker, text as _portable_text, port as _portable_port, cache_for as _portable_cache
import asyncio
import json
import os
from pathlib import Path
import shutil
import uuid
from .compute_policy import run_stage, wait_process
from astrbot.core.utils.local_compute import cover_task
RVC_PYTHON = Path(_portable_path('D:/new rvc/python/python.exe'))
RVC_DATA = Path(_portable_path('D:/new rvc/core/data'))
LEGACY = Path(_portable_path('D:/RVC20240604Nvidia50x0'))
FFMPEG = _portable_path('D:/AI/ffmpeg/bin/ffmpeg.exe')
FFPROBE = _portable_path('D:/AI/ffmpeg/bin/ffprobe.exe')

def list_voices():
    voices = []
    seen = set()
    for folder in sorted((Path(_portable_settings()['voices_dir'])).iterdir(), key=lambda p: p.name.casefold()):
        path = folder / 'model.pth'
        if not path.is_file():
            continue
        meta = json.loads((folder / 'voice.json').read_text(encoding='utf-8')) if (folder / 'voice.json').exists() else {'name':folder.name}
        sources = meta.get('source_files') or []
        filename = next((str(x) for x in sources if str(x).lower().endswith('.pth')), folder.name + '.pth')
        index = folder / 'model.index'
        if not index.is_file():
            stems = [Path(filename).stem, folder.name]
            if folder.name == '洛天依':
                stems.append('luotianyi')
            if folder.name == 'hatsunemiku_pth':
                stems.append('HatsuneMiku_index')
            options = [i for i in (LEGACY / 'assets/indices').glob('*.index') if any((i.stem.casefold() == s.casefold() or i.stem.casefold() == (s + '_v2').casefold() for s in stems))]
            index = options[0] if len(options) == 1 else None
        voices.append({'name': str(meta.get('name') or folder.name), 'filename': filename, 'path': str(path.resolve()), 'index': str(index.resolve()) if index else ''})
        seen.add(filename.casefold())
    for path in sorted(list((LEGACY / 'assets/weights').glob('*.pth'))+list(Path(_portable_settings()['voices_dir']).glob('*.pth'))):
        if path.name.casefold() not in seen:
            voices.append({'name': path.stem, 'filename': path.name, 'path': str(path.resolve()), 'index': ''})
    return voices

def select_voice(text, voices):
    text = text.strip()
    if text.isdigit():
        index = int(text) - 1
        if 0 <= index < len(voices):
            return voices[index]
    matches = [v for v in voices if text.casefold() in (v['name'].casefold(), v['filename'].casefold())]
    if len(matches) == 1:
        return matches[0]
    raise ValueError('请选择清单中的模型编号或完整 PTH 文件名。')

def list_indexes(voice):
    paths = []
    if voice.get('index'):
        paths.append(Path(voice['index']))
    folder = Path(voice['path']).parent
    if folder.is_relative_to(Path(_portable_settings()['voices_dir'])) and Path(voice['path']).name=='model.pth':
        paths.extend(folder.glob('*.index'))
    stems = {Path(voice['filename']).stem.casefold(), voice['name'].casefold()}
    if '洛天依' in stems:
        stems.add('luotianyi')
    if 'hatsunemiku_pth' in stems:
        stems.add('hatsunemiku_index')
    for root in (LEGACY / 'assets/indices', LEGACY / 'logs', Path(_portable_settings()['voices_dir'])):
        for path in root.glob('*.index'):
            name = path.stem.casefold()
            if name in stems or any((name == stem + '_v2' for stem in stems)):
                paths.append(path)
    result = []
    seen = set()
    for path in paths:
        if not path.is_file():
            continue
        resolved = str(path.resolve())
        if resolved in seen:
            continue
        seen.add(resolved)
        label = path.name
        if path.name == 'model.index' and (folder / 'voice.json').is_file():
            meta = json.loads((folder / 'voice.json').read_text(encoding='utf-8')) if (folder / 'voice.json').exists() else {'name':folder.name}
            sources = meta.get('index_sources') or {}
            if isinstance(sources, dict):
                value = sources.get('model.index')
                if isinstance(value, str):
                    label = value
        result.append({'name': label, 'path': resolved, 'bytes': path.stat().st_size})
    return result

class CoverPipeline:

    def __init__(self, folder):
        self.folder = Path(folder)
        self.cache = _portable_cache(__file__, 'cache')
        self.cache.mkdir(parents=True, exist_ok=True)
        self.engine_data = self.folder / 'engine-data'
        self.engine_data.mkdir(exist_ok=True)
        settings = self.engine_data / 'settings.toml'
        if not settings.exists():
            settings.write_text(_portable_text('[paths]\nassets_dir = "D:/new rvc/core/data/assets"\nmodels_dir = "D:/new rvc/core/data/models"\n[compute]\ndevice = "cpu"\nprecision = "fp32"\ngpu_jobs = 1\n'), encoding='utf-8')

    async def command(self, args, log, timeout=3600, env=None, gpu_guard=False):
        with Path(log).open('ab') as output:
            proc = await asyncio.create_subprocess_exec(*map(str, args), stdout=output, stderr=output, env=env, creationflags=134217728 if os.name == 'nt' else 0)
            try:
                await wait_process(proc, timeout, gpu_guard)
            except BaseException:
                if proc.returncode is None:
                    if os.name == 'nt':
                        killer = await asyncio.create_subprocess_exec('taskkill', '/PID', str(proc.pid), '/T', '/F', stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL, creationflags=134217728)
                        await killer.wait()
                    else:
                        proc.kill()
                    await proc.wait()
                raise
        if proc.returncode:
            raise RuntimeError('音频处理步骤失败，已保留本次日志供排查。')

    async def duration(self, path):
        proc = await asyncio.create_subprocess_exec(FFPROBE, '-v', 'error', '-show_entries', 'format=duration', '-of', 'json', str(path), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, creationflags=134217728 if os.name == 'nt' else 0)
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), 30)
        except BaseException:
            if proc.returncode is None:
                proc.kill()
                await proc.wait()
            raise
        if proc.returncode:
            raise RuntimeError('生成的音频无法读取。')
        return float(json.loads(out).get('format', {}).get('duration') or 0)

    @cover_task
    async def make(self, source, voice, progress, pitch=0):
        voices = list_voices()
        matches = [v for v in voices if v['path'] == voice['path']]
        if len(matches) != 1:
            raise ValueError('模型不在本机受信任的 PTH 清单内。')
        selected_index = voice.get('index')
        allowed = list_indexes(matches[0])
        if selected_index not in {entry['path'] for entry in allowed}:
            raise ValueError('请选择该PTH配套的INDEX文件后再开始翻唱。')
        voice = dict(matches[0], index=selected_index)
        token = uuid.uuid4().hex
        job = self.cache / ('job_' + token)
        job.mkdir()
        result = self.cache / (token + '.mp3')
        log = _portable_cache(__file__, 'logs')
        log.mkdir(exist_ok=True)
        log = log / (token + '.log')
        env = dict(os.environ, PYTHONUTF8='1', RVC_NEXT_DATA_DIR=str(self.engine_data), NUMBA_NUM_THREADS='4', OMP_NUM_THREADS='4', MKL_NUM_THREADS='4', TOKENIZERS_PARALLELISM='false')
        env['PATH'] = _portable_path('D:/AI/ffmpeg/bin;') + env.get('PATH', '')
        success = False
        try:
            await progress('正在用 UVR5 分离人声和伴奏…')
            prepared = job / 'source.wav'
            await self.command([FFMPEG, '-v', 'error', '-y', '-i', source, '-vn', '-ac', '2', '-ar', '44100', prepared], log, 120, env)
            await run_stage(self, [RVC_PYTHON, '-u', self.folder / 'uvr_worker.py', '--input', prepared, '--output', job / 'uvr', '--device', '__DEVICE__'], log, env, progress, 'UVR5分离人声和伴奏')
            stems = json.loads((job / 'uvr/stems.json').read_text(encoding='utf-8'))
            vocal = Path(stems['vocals'])
            instrument = Path(stems['instrumental'])
            if vocal.resolve().parent != (job / 'uvr/vocals').resolve() or instrument.resolve().parent != (job / 'uvr/instrumental').resolve():
                raise RuntimeError('UVR5 输出路径异常。')
            await progress('人声分离完成，正在用 ' + voice['filename'] + ' 换声…')
            args = [RVC_PYTHON, '-u', '-m', 'rvc_next', 'convert', vocal, '--voice', voice['path'], '--pitch', str(pitch), '--f0', 'rmvpe', '--index-rate', '0.66' if voice['index'] else '0', '--format', 'wav', '--output', job / 'converted', '--json']
            if voice['index']:
                args.extend(['--index', voice['index']])
            await run_stage(self, args, log, env, progress, 'RVC换声')
            converted = list((job / 'converted').rglob('*.wav'))
            if len(converted) != 1:
                raise RuntimeError('RVC 没有输出唯一的人声音轨。')
            await progress('换声完成，正在混合伴奏并生成语音…')
            await self.command([FFMPEG, '-v', 'error', '-y', '-i', converted[0], '-i', instrument, '-filter_complex', '[0:a]aresample=44100,volume=1.0[v];[1:a]aresample=44100,volume=0.85[b];[v][b]amix=inputs=2:duration=longest:normalize=0,alimiter=limit=0.95:level=false[out]', '-map', '[out]', '-ac', '2', '-ar', '44100', '-c:a', 'libmp3lame', '-b:a', '192k', result], log, 180, env)
            original_duration = await self.duration(source)
            duration = await self.duration(result)
            if original_duration <= 0 or abs(duration - original_duration) > max(3, original_duration * 0.03):
                raise RuntimeError('成品时长不完整，未发送。')
            success = True
            return result
        finally:
            if job.resolve().parent == self.cache.resolve() and job.name == 'job_' + token:
                shutil.rmtree(job, ignore_errors=True)
            if not success:
                result.unlink(missing_ok=True)
