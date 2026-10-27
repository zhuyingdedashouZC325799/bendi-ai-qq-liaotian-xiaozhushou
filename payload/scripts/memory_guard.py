"""Bound memory recovery to the dedicated robot's Ollama service and children."""
from portable_settings import remap as _portable_path, owners as _portable_owners, settings as _portable_settings, speaker_policy as _portable_speaker, text as _portable_text, port as _portable_port, cache_for as _portable_cache
import argparse, ctypes, json, logging, logging.handlers, os, subprocess, time, urllib.request
from pathlib import Path
import psutil
EXE = Path(_portable_path('D:/AI/Ollama/ollama.exe'))
LOG = Path(_portable_path('D:/AI/logs/ollama-memory-guard.log'))

def decision(available_mb, private_mb, pressure_samples):
    if available_mb < 512 and private_mb > 512:
        return 'emergency'
    if pressure_samples >= 3 and (available_mb < 1536 or private_mb > 7168):
        return 'unload'
    return 'none'

def owned():
    for p in psutil.process_iter(['exe', 'cmdline']):
        try:
            if p.info['exe'] and Path(p.info['exe']) == EXE and ('serve' in (p.info['cmdline'] or [])):
                return (p, [p] + p.children(recursive=True))
        except (psutil.Error, OSError):
            pass
    return (None, [])

def api(path, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(_portable_text('http://127.0.0.1:11434') + path, data=data, headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=8) as response:
        return json.load(response)

def recover(server, processes, action, dry_run):
    log = logging.getLogger('guard')
    log.warning('Memory recovery action=%s dry_run=%s', action, dry_run)
    if dry_run:
        return
    if action == 'unload':
        try:
            for model in api('/api/ps').get('models', []):
                api('/api/generate', {'model': model['name'], 'keep_alive': 0, 'stream': False})
            return
        except Exception as exc:
            log.warning('Unload failed: %s', type(exc).__name__)
        return
    for p in reversed(processes):
        if p.pid == server.pid:
            continue
        try:
            if server.pid in [x.pid for x in p.parents()] and Path(p.exe()).is_relative_to(EXE.parent):
                p.kill()
                log.warning('Stopped dedicated Ollama runner pid=%d under critical RAM pressure', p.pid)
        except (psutil.Error, OSError):
            pass
    try:
        if server.memory_info().private > 2 * 1024 ** 3 and Path(server.exe()) == EXE:
            server.kill()
            server.wait(timeout=5)
            with open(LOG.parent / 'ollama-memory-restart.log', 'ab') as output:
                subprocess.Popen([str(EXE), 'serve'], cwd=str(EXE.parent), env=os.environ.copy(), stdout=output, stderr=output, creationflags=subprocess.CREATE_NO_WINDOW)
            log.warning('Restarted dedicated Ollama server after critical server memory growth')
    except (psutil.Error, OSError):
        log.exception('Dedicated Ollama server recovery failed')

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--once', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.restype = ctypes.c_void_p
    handle = kernel.CreateMutexW(None, False, 'Local\\LocalBotMemoryGuard_'+__import__('hashlib').sha256(str(EXE).encode()).hexdigest()[:12])
    if not handle or ctypes.get_last_error() == 183:
        return
    LOG.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(LOG, maxBytes=512 * 1024, backupCount=2, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    log = logging.getLogger('guard')
    log.setLevel(logging.INFO)
    log.addHandler(handler)
    pressure = 0
    last_recovery = 0
    last_status = 0
    try:
        while True:
            try:
                server, processes = owned()
                available = psutil.virtual_memory().available / 1024 ** 2
                private = sum((getattr(p.memory_info(), 'private', p.memory_info().rss) for p in processes if p.is_running())) / 1024 ** 2
                pressure = pressure + 1 if available < 1536 or private > 7168 else 0
                action = decision(available, private, pressure)
                if time.monotonic() - last_status > 300 or args.once:
                    log.info('available_mb=%.0f ollama_private_mb=%.0f action=%s', available, private, action)
                    last_status = time.monotonic()
                if server and action != 'none' and (time.monotonic() - last_recovery > 90):
                    recover(server, processes, action, args.dry_run)
                    last_recovery = time.monotonic()
                if args.once:
                    print(json.dumps({'available_mb': round(available), 'ollama_private_mb': round(private), 'action': action, 'dry_run': args.dry_run}))
                    return
            except Exception as exc:
                log.warning('Monitor sample failed: %s', type(exc).__name__)
            time.sleep(15)
    finally:
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel.CloseHandle(handle)
if __name__ == '__main__':
    main()
