"""Cover jobs reserve the GPU; new chat requests wait and then resume in order."""
import asyncio,functools,inspect,time

active_llm=0
last_llm_finished=0.0
cover_gpu=False
cover_jobs=0
_chat_queue=asyncio.Lock()

async def wait_for_cover():
    while cover_jobs>0 or cover_gpu:await asyncio.sleep(.1)

async def enter_llm():
    global active_llm
    await _chat_queue.acquire()
    try:
        await wait_for_cover()
        active_llm+=1
    except BaseException:
        _chat_queue.release();raise

def leave_llm():
    global active_llm,last_llm_finished
    active_llm=max(0,active_llm-1);last_llm_finished=time.monotonic()
    _chat_queue.release()

async def begin_cover():
    global cover_jobs
    cover_jobs+=1
    try:
        # Let an already running response finish, while preventing new responses.
        while active_llm:await asyncio.sleep(.1)
    except BaseException:
        cover_jobs-=1;raise

def end_cover():
    global cover_jobs
    cover_jobs=max(0,cover_jobs-1)

def cover_task(fn):
    @functools.wraps(fn)
    async def run(*args,**kwargs):
        await begin_cover()
        try:return await fn(*args,**kwargs)
        finally:end_cover()
    return run

def llm_busy():
    return active_llm>0 or (not cover_jobs and time.monotonic()-last_llm_finished<5)

def claim_cover():
    global cover_gpu
    if cover_gpu or llm_busy():return False
    cover_gpu=True;return True

def release_cover():
    global cover_gpu
    cover_gpu=False

def track_local_llm(fn):
    if inspect.isasyncgenfunction(fn):
        @functools.wraps(fn)
        async def stream(*args,**kwargs):
            await enter_llm()
            try:
                async for item in fn(*args,**kwargs):yield item
            finally:leave_llm()
        return stream
    @functools.wraps(fn)
    async def query(*args,**kwargs):
        await enter_llm()
        try:return await fn(*args,**kwargs)
        finally:leave_llm()
    return query
