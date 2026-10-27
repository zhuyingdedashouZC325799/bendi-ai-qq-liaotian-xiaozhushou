import asyncio
import json
import time
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlparse


def media_url(value):
    if isinstance(value, dict):
        value = value.get('url') or value.get('src') or (value.get('url_list') or [''])[0]
    if isinstance(value, list):
        value = value[0] if value else ''
    return value if isinstance(value, str) and value.startswith(('http://', 'https://')) else ''


def normalize_result(platform, payload, original_url):
    if not isinstance(payload, dict) or str(payload.get('code')) != '200':
        raise ValueError('解析服务返回失败：' + str(payload.get('msg', '') if isinstance(payload, dict) else '无效响应'))
    data = payload.get('data')
    if not isinstance(data, dict):
        raise ValueError('解析服务 data 字段不是对象')
    author = data.get('author') or data.get('user') or data.get('owner') or ''
    if isinstance(author, dict): author = author.get('name') or author.get('nickname') or ''
    info = {'title': str(data.get('title') or data.get('desc') or '分享内容'),
            'author': str(author), 'cover': media_url(data.get('cover') or data.get('pic')),
            'quality': str(data.get('quality') or ''), 'source_url': original_url,
            'description':str(data.get('description') or data.get('desc') or ''),'tags':str(data.get('tags') or '')}
    images = [media_url(v) for v in (data.get('images') or [])]
    images = list(dict.fromkeys(v for v in images if v))
    kind = str(data.get('type') or '').lower()
    if kind in {'image', 'images', 'photo'} or (images and not data.get('url')):
        if not images:
            images = [v for v in [media_url(data.get('url')), info['cover']] if v]
        if not images: raise ValueError('图文作品未返回原图地址')
        info['images'] = images
        return platform, images[0], 0, info, 'image'
    url = media_url(data.get('url'))
    duration = data.get('duration')
    parts = data.get('videos') or []
    if parts:
        try: wanted = max(1, int(parse_qs(urlparse(original_url).query).get('p', ['1'])[0]))
        except ValueError: raise ValueError('分集 p 参数必须是正整数')
        selected = next((p for i, p in enumerate(parts, 1) if int(p.get('index') or i) == wanted), None)
        if selected is None: raise ValueError(f'没有第 {wanted} 个分集')
        chosen_url = media_url(selected.get('url'))
        if not chosen_url and int(data.get('selected_index') or 0) == wanted: chosen_url = url
        if not chosen_url: raise ValueError(f'第 {wanted} 个分集暂未返回可下载地址')
        url = chosen_url
        # The parent duration may be the sum of dozens of episodes.
        duration = selected.get('duration')
        total = int(data.get('totalVideos') or len(parts))
        info['part_index'], info['part_total'] = wanted, total
        subtitle = str(selected.get('title') or '')
        info['title'] += f' · P{wanted}/{total}' + (' ' + subtitle if subtitle else '')
    if not parts:
        info['video_backups'] = [media_url(item) for item in (data.get('video_backup') or data.get('backup') or []) if media_url(item)]
    if not url: raise ValueError('解析服务未返回可下载的视频地址')
    return platform, url, duration, info, 'video'


class CleanupQueue:
    """Persist successful-send deadlines so restarting AstrBot cannot lose them."""
    def __init__(self, cache, manifest, logger):
        self.cache = Path(cache).resolve()
        self.manifest = Path(manifest)
        self.logger = logger
        self.jobs = {}
        self.tasks = set()
        try:
            loaded = json.loads(self.manifest.read_text(encoding='utf-8'))
            for key, job in loaded.items():
                if isinstance(job, dict) and all(self.allowed(p) for p in job.get('paths', [])):
                    self.jobs[key] = job
        except FileNotFoundError: pass
        except (ValueError, TypeError): logger.warning('[视频清理] 清理记录异常，保留缓存供检查')
        for key in self.jobs: self.start(key)

    def allowed(self, path):
        try: return Path(path).resolve().parent == self.cache
        except (OSError, ValueError): return False

    def save(self):
        temp = self.manifest.with_suffix('.tmp')
        temp.write_text(json.dumps(self.jobs, ensure_ascii=False), encoding='utf-8')
        temp.replace(self.manifest)

    def start(self, key):
        task = asyncio.create_task(self.run(key))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    def schedule(self, paths, delay=60):
        paths = list(dict.fromkeys(str(Path(p).resolve()) for p in paths if p is not None))
        if not paths or not all(self.allowed(p) for p in paths): raise ValueError('缓存清理路径越界')
        key = uuid.uuid4().hex
        self.jobs[key] = {'deadline': time.time() + delay, 'paths': paths}
        self.save()
        self.start(key)
        self.logger.info('[视频清理] 全部发送完成，%s 秒后删除 %s 个缓存文件', delay, len(paths))

    async def run(self, key):
        while key in self.jobs:
            job = self.jobs[key]
            await asyncio.sleep(max(0, job['deadline'] - time.time()))
            failed = []
            for path in job['paths']:
                try:
                    Path(path).unlink(missing_ok=True)
                    self.logger.info('[视频清理] 已删除缓存：%s', path)
                except OSError as exc:
                    failed.append(path)
                    self.logger.warning('[视频清理] 文件占用，30秒后重试：%s；%s', path, exc)
            if failed: self.jobs[key] = {'deadline': time.time()+30, 'paths': failed}
            else: self.jobs.pop(key, None)
            self.save()

    async def close(self):
        for task in tuple(self.tasks): task.cancel()
        if self.tasks: await asyncio.gather(*self.tasks, return_exceptions=True)
