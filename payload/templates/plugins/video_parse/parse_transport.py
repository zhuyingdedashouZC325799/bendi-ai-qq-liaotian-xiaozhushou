"""Bounded, independent PHP workers: slow links never queue behind the PHP web server."""
from portable_settings import remap as _portable_path, owners as _portable_owners, settings as _portable_settings, speaker_policy as _portable_speaker, text as _portable_text, port as _portable_port, cache_for as _portable_cache
import copy
import json
from pathlib import Path
import subprocess
import threading
import time
import urllib.parse
import urllib.request
PHP = Path(_portable_path('D:/AI/php/php.exe'))
ROOT = Path(_portable_path('D:/AI/short_videos/api'))
_GUARD = threading.Lock()
_LOCKS = {}
_CACHE = {}
WRAPPER = _portable_text('$_SERVER["REQUEST_METHOD"]="GET"; $_SERVER["REQUEST_URI"]="/api/".$argv[2]."?url=".rawurlencode($argv[3]); $_SERVER["HTTP_HOST"]="127.0.0.1:8088"; $_SERVER["DOCUMENT_ROOT"]=$argv[4]; $_SERVER["SCRIPT_FILENAME"]=$argv[1]; $_GET=["url"=>$argv[3]]; $_REQUEST=$_GET; chdir(dirname($argv[1])); require $argv[1];')

def parse_payload(endpoint, url, base=_portable_text('http://127.0.0.1:8088/api')):
    key = (endpoint, url, base)
    with _GUARD:
        lock = _LOCKS.setdefault(key, threading.Lock())
    with lock:
        cached = _CACHE.get(key)
        if cached and cached[0] > time.monotonic():
            return copy.deepcopy(cached[1])
        local = urllib.parse.urlsplit(base)
        if local.hostname in ('127.0.0.1', 'localhost') and local.port == _portable_port('php') and (local.path.rstrip('/') == '/api'):
            target = (ROOT / endpoint).resolve()
            if not target.is_relative_to(ROOT.resolve()) or not target.is_file():
                raise ValueError('解析接口路径无效')
            try:
                result = subprocess.run([str(PHP), '-d', 'display_errors=stderr', '-d', 'default_socket_timeout=8', '-d', 'max_execution_time=60', '-r', WRAPPER, str(target), endpoint, url, str(ROOT.parent)], capture_output=True, timeout=65, creationflags=134217728)
            except subprocess.TimeoutExpired as exc:
                raise TimeoutError('上游解析超过65秒，已结束本次任务，不影响其他链接；请稍后重试') from exc
            if result.returncode:
                raise RuntimeError('平台解析进程异常，未返回结果')
            raw = result.stdout
        else:
            api = base.rstrip('/') + '/' + endpoint + '?url=' + urllib.parse.quote(url, safe='')
            try:
                with urllib.request.urlopen(api, timeout=65) as response:
                    raw = response.read(4000001)
            except TimeoutError as exc:
                raise TimeoutError('远程解析接口超时，请稍后重试') from exc
        if len(raw) > 4000000:
            raise ValueError('解析结果过大')
        try:
            data = json.loads(raw.decode('utf-8-sig'))
        except (ValueError, UnicodeError) as exc:
            raise RuntimeError('解析接口没有返回有效JSON') from exc
        if isinstance(data, dict) and str(data.get('code')) == '200':
            _CACHE[key] = (time.monotonic() + 90, data)
        if len(_CACHE) > 128:
            for old in list(_CACHE)[:32]:
                _CACHE.pop(old, None)
        return copy.deepcopy(data)
