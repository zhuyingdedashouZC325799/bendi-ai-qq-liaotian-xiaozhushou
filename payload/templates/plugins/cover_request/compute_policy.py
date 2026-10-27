"""Choose GPU only when chat is idle and headroom is sufficient."""
from portable_settings import remap as _portable_path, owners as _portable_owners, settings as _portable_settings, speaker_policy as _portable_speaker, text as _portable_text, port as _portable_port, cache_for as _portable_cache
import asyncio, os, shutil, time
import aiohttp
from astrbot.core.utils import local_compute as gate

class YieldGPU(RuntimeError):
    pass

def eligible(samples, min_free=4096):
    return bool(samples) and all((util < 25 and total - used >= min_free for util, used, total in samples))

async def snapshot():
    exe = shutil.which('nvidia-smi')
    if not exe:
        return None
    proc = await asyncio.create_subprocess_exec(exe, '--query-gpu=utilization.gpu,memory.used,memory.total', '--format=csv,noheader,nounits', stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, creationflags=134217728 if os.name == 'nt' else 0)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), 4)
    except BaseException:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
        raise
    try:
        return tuple((int(x.strip()) for x in out.decode().splitlines()[0].split(','))) if proc.returncode == 0 else None
    except (ValueError, IndexError):
        return None

async def choose():
    if _portable_settings().get('gpu_mode') != 'nvidia':
        return ('cpu', '安装时选择了CPU通用环境')
    if gate.llm_busy():
        return ('cpu', '语言模型正在处理或刚结束请求')
    samples = []
    for _ in range(3):
        try:
            sample = await snapshot()
        except (OSError, TimeoutError):
            sample = None
        if not sample:
            return ('cpu', '无法读取显卡状态')
        samples.append(sample)
        await asyncio.sleep(0.4)
    if any((s[0] >= 25 for s in samples)):
        return ('cpu', '显卡占用较高')
    if not gate.claim_cover():
        return ('cpu', '聊天或其他翻唱已占用显卡')
    if not eligible(samples):
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=8)) as http:
                async with http.post(_portable_text('http://127.0.0.1:11434/api/generate'), json={'model': 'qwen3-vl:4b-dafeiyu', 'keep_alive': 0, 'stream': False}) as response:
                    response.raise_for_status()
                    await response.read()
            for _ in range(10):
                sample = await snapshot()
                if sample and eligible([sample]):
                    break
                await asyncio.sleep(0.3)
            if not sample or not eligible([sample]):
                gate.release_cover()
                return ('cpu', '空闲模型释放后显存仍不足')
        except (OSError, TimeoutError, aiohttp.ClientError):
            gate.release_cover()
            return ('cpu', '无法释放空闲模型显存')
        except BaseException:
            gate.release_cover()
            raise
    return ('cuda', '模型空闲，显卡占用低于25%且可用显存超过4GB')

async def monitor(proc):
    while proc.returncode is None:
        try:
            sample = await snapshot()
        except (OSError, TimeoutError):
            sample = None
        if sample is None or sample[2] - sample[1] < 768:
            raise YieldGPU('显卡状态异常或剩余显存不足')
        await asyncio.sleep(1)

async def run_stage(pipeline, args, log, env, progress, label):
    device, reason = await choose()
    owns_gpu = device == 'cuda'
    stage_env = dict(env, RVC_NEXT_COMPUTE__DEVICE='cuda:0' if device == 'cuda' else 'cpu', RVC_NEXT_COMPUTE__PRECISION='fp32')

    def command_for(which):
        return [which if x == '__DEVICE__' else x for x in args]
    try:
        await progress(label + '：' + ('GPU加速' if device == 'cuda' else 'CPU处理') + '（' + reason + '）')
        await pipeline.command(command_for(device), log, 3600, stage_env, gpu_guard=device == 'cuda')
    except (YieldGPU, RuntimeError):
        if device != 'cuda':
            raise
        gate.release_cover()
        owns_gpu = False
        await progress(label + '：已释放显卡，改用CPU重新处理当前阶段')
        stage_env.update(RVC_NEXT_COMPUTE__DEVICE='cpu', RVC_NEXT_COMPUTE__PRECISION='fp32')
        await pipeline.command(command_for('cpu'), log, 3600, stage_env)
    finally:
        if owns_gpu:
            gate.release_cover()

async def wait_process(proc, timeout, gpu_guard):
    if not gpu_guard:
        return await asyncio.wait_for(proc.wait(), timeout)
    waiter = asyncio.create_task(proc.wait())
    watch = asyncio.create_task(monitor(proc))
    try:
        done, _ = await asyncio.wait((waiter, watch), timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
        if not done:
            raise asyncio.TimeoutError()
        if watch in done:
            watch.result()
        return await waiter
    finally:
        for task in (waiter, watch):
            if not task.done():
                task.cancel()
        await asyncio.gather(waiter, watch, return_exceptions=True)
