import asyncio
import json
import time
import uuid
from pathlib import Path


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
        except (ValueError, TypeError): logger.warning('[电脑截图清理] 清理记录异常，保留缓存供检查')
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
        self.logger.info('[电脑截图清理] 全部发送完成，%s 秒后删除 %s 个缓存文件', delay, len(paths))

    async def run(self, key):
        while key in self.jobs:
            job = self.jobs[key]
            await asyncio.sleep(max(0, job['deadline'] - time.time()))
            failed = []
            for path in job['paths']:
                try:
                    Path(path).unlink(missing_ok=True)
                    self.logger.info('[电脑截图清理] 已删除缓存：%s', path)
                except OSError as exc:
                    failed.append(path)
                    self.logger.warning('[电脑截图清理] 文件占用，30秒后重试：%s；%s', path, exc)
            if failed: self.jobs[key] = {'deadline': time.time()+30, 'paths': failed}
            else: self.jobs.pop(key, None)
            self.save()

    async def close(self):
        for task in tuple(self.tasks): task.cancel()
        if self.tasks: await asyncio.gather(*self.tasks, return_exceptions=True)
