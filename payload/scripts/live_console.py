"""Visible server console for startup, live logs, and diagnostic reports."""
from portable_settings import remap as _portable_path, owners as _portable_owners, settings as _portable_settings, speaker_policy as _portable_speaker, text as _portable_text, port as _portable_port, cache_for as _portable_cache
import argparse, codecs, datetime, json, logging, logging.handlers, os, queue, re, socket, subprocess, sys, threading, time
from collections import deque
from pathlib import Path
ROOT = Path(_portable_path('D:/AI'))
LOGS = ROOT / 'logs'
REPORTS = LOGS / 'error-reports'
BACKEND = ROOT / 'astrbot-data/data/logs/astrbot.log'
ANSI = re.compile('\\x1b\\[[0-?]*[ -/]*[@-~]')
ERROR = re.compile('\\b(?:ERROR|CRITICAL|FATAL)\\b|Traceback \\(most recent call last\\)|启动未完成|启动失败|处理失败|发送失败|下载失败', re.I)
PORTS = {'Ollama': _portable_port('ollama'), 'CPU筛查': _portable_port('screen'), '视频解析': _portable_port('php'), '音乐网页': _portable_port('qq_music'), '机器人后台': 6185, 'QQ消息接口': _portable_port('bridge_http')}

def redact(text):
    text = ANSI.sub('', str(text))
    text = re.sub('(?i)(Bearer\\s+)[^\\s\\"\\\']+', '\\1[已隐藏]', text)
    text = re.sub('(?i)((?:access_token|authorization|cookie|password|api_key|p_skey|skey|vkey|token)\\s*[=:]\\s*)[^\\s,;\\]}]+', '\\1[已隐藏]', text)
    text = re.sub('(https?://)[^/\\s:@]+:[^/\\s@]+@', '\\1[已隐藏]@', text)
    return text[:12000]

def port_open(port):
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=0.25):
            return True
    except OSError:
        return False

class Tail:

    def __init__(self, path, initial_tail=True):
        self.path = Path(path)
        self.offset = 0
        self.partial = ''
        self.decoder = codecs.getincrementaldecoder('utf-8')('replace')
        self.skip_first = False
        if initial_tail:
            try:
                self.offset = max(0, self.path.stat().st_size - 3500)
                self.skip_first = self.offset > 0
            except OSError:
                pass

    def read(self):
        try:
            size = self.path.stat().st_size
            if size < self.offset:
                self.offset = 0
                self.partial = ''
                self.decoder.reset()
            with self.path.open('rb') as f:
                f.seek(self.offset)
                raw = f.read(128 * 1024)
                self.offset = f.tell()
            if not raw:
                return []
            text = self.partial + self.decoder.decode(raw)
            lines = text.split('\n')
            self.partial = lines.pop()[-16000:]
            if self.skip_first and lines:
                lines.pop(0)
                self.skip_first = False
            return [s.rstrip('\r') for s in lines if s.strip()]
        except OSError:
            return []

class Console:

    def __init__(self, root=ROOT):
        self.root = Path(root)
        self.logs = self.root / 'logs'
        self.reports = self.logs / 'error-reports'
        self.logs.mkdir(parents=True, exist_ok=True)
        stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
        self.history = deque(maxlen=300)
        self.events = queue.Queue(maxsize=1000)
        self.tails = {}
        self.last_report = {}
        self.stop = False
        self.log = logging.getLogger('console-' + stamp + '-' + str(id(self)))
        self.log.setLevel(logging.INFO)
        self.handler = logging.handlers.RotatingFileHandler(self.logs / ('console-' + stamp + '.log'), maxBytes=4 * 1024 ** 2, backupCount=2, encoding='utf-8')
        self.log.addHandler(self.handler)
        self.ready = False
        self.process = None
        self.failure_count = {}
        self.down = set()
        self.pending_error = None

    def emit(self, source, line, detect=True):
        line = redact(line)
        rendered = '[{0}] [{1}] {2}'.format(datetime.datetime.now().strftime('%H:%M:%S'), source, line)
        self.history.append(rendered)
        self.log.info(rendered)
        color = '\x1b[31m' if ERROR.search(line) else '\x1b[33m' if re.search('\\bWARN(?:ING)?\\b', line, re.I) else ''
        try:
            print(color + rendered + ('\x1b[0m' if color else ''), flush=True)
        except (OSError, UnicodeError):
            pass
        if detect and ERROR.search(line) and (self.pending_error is None):
            self.pending_error = (time.monotonic() + 2, source, line)

    def snapshot(self):
        status = {'时间': datetime.datetime.now().isoformat(timespec='seconds'), '服务端口': {name: port_open(port) for name, port in PORTS.items()}}
        try:
            import psutil
            memory = psutil.virtual_memory()
            status['内存'] = {'总量MB': round(memory.total / 1024 ** 2), '可用MB': round(memory.available / 1024 ** 2), '占用百分比': memory.percent}
            status['相关进程'] = [{'名称': p.info['name'], 'PID': p.pid, '内存MB': round(p.info['memory_info'].rss / 1024 ** 2)} for p in psutil.process_iter(['name', 'exe', 'memory_info']) if p.info['exe'] and Path(p.info['exe']).is_relative_to(self.root)][:30]
        except Exception:
            pass
        return status

    def report(self, reason, category='manual'):
        now = time.monotonic()
        if category != 'manual' and now - self.last_report.get(category, -1000) < 60:
            return None
        self.last_report[category] = now
        self.reports.mkdir(parents=True, exist_ok=True)
        stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        path = self.reports / ('错误报告-' + stamp + '.txt')
        status = self.snapshot()
        content = '本地助手错误报告\n时间：' + status['时间'] + '\n问题：' + redact(reason) + '\n\n服务和内存状态\n' + json.dumps(status, ensure_ascii=False, indent=2) + '\n\n最近整合日志（敏感凭据已遮盖）\n' + '\n'.join(self.history) + '\n\n排查提示：先查看上述问题及其前后的错误堆栈；端口异常表示对应服务未就绪。\n'
        temporary = path.with_suffix('.tmp')
        temporary.write_text(content, encoding='utf-8-sig')
        temporary.replace(path)
        self.emit('报告', '错误报告已生成：' + str(path), False)
        return path

    def discover(self):
        groups = {'机器人': ('astrbot-data/data/logs/astrbot.log',), 'QQ': ('logs/snowluma-*.log', 'logs/snowluma-*.err.log'), 'Ollama': ('logs/ollama-*.err.log',), 'CPU筛查': ('logs/screen-fast-*.err.log',), '视频服务': ('logs/video-parser-*.err.log',), '内存监控': ('logs/ollama-memory-guard.log',)}
        for label, patterns in groups.items():
            for index, pattern in enumerate(patterns):
                files = [p for p in self.root.glob(pattern) if p.is_file() and (not (label == 'QQ' and index == 0 and p.name.endswith('.err.log')))]
                if not files:
                    continue
                path = max(files, key=lambda p: p.stat().st_ctime_ns)
                key = (label, index)
                if key not in self.tails or self.tails[key].path != path:
                    self.tails[key] = Tail(path)

    def pump(self):
        for (label, _), tail in list(self.tails.items()):
            for line in tail.read():
                self.emit(label, line)
        for _ in range(200):
            try:
                kind, line = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == 'command':
                command = line.strip().lower()
                if command in ('exit', 'quit', '退出'):
                    self.stop = True
                elif command in ('report', '报告'):
                    self.report('用户手动生成诊断报告')
                elif command in ('status', '状态'):
                    self.emit('状态', json.dumps(self.snapshot(), ensure_ascii=False), False)
                elif command:
                    self.emit('帮助', '命令：status/状态、report/报告、exit/退出', False)
            else:
                self.emit(kind, line)
        if self.pending_error and time.monotonic() >= self.pending_error[0]:
            _, source, line = self.pending_error
            self.pending_error = None
            self.report(source + '：' + line, 'runtime-' + source)

    def startup(self):
        startup = self.root / 'scripts/start-dafeiyu.ps1'
        command = "$u=New-Object System.Text.UTF8Encoding($false); [Console]::OutputEncoding=$u; $OutputEncoding=$u; & '" + str(startup).replace("'", "''") + "'; exit $LASTEXITCODE"
        self.process = subprocess.Popen(['powershell.exe', '-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command', command], cwd=self.root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace', bufsize=1)

        def reader():
            for line in self.process.stdout:
                self.events.put(('启动', line.rstrip()))
        self.startup_reader = threading.Thread(target=reader, daemon=True)
        self.startup_reader.start()

    def health(self):
        for name, port in PORTS.items():
            if port_open(port):
                self.failure_count[name] = 0
                if name in self.down:
                    self.down.remove(name)
                    self.emit('监控', name + ' 已恢复', False)
            else:
                self.failure_count[name] = self.failure_count.get(name, 0) + 1
                if self.failure_count[name] >= 3 and name not in self.down:
                    self.down.add(name)
                    reason = name + ' 连续三次未响应（端口 ' + str(port) + '）'
                    self.emit('监控', 'ERROR ' + reason, False)
                    self.report(reason, 'service-' + name)

    def run(self, no_start=False, seconds=None):
        self.emit('控制台', '本地助手实时控制台 | 日志持续滚动；错误报告：' + str(self.reports), False)
        self.emit('控制台', '输入 status 查看状态，report 导出报告，exit 关闭日志窗口。服务继续后台运行。', False)
        if not no_start:
            self.startup()
        else:
            self.ready = True

        def reader():
            for line in sys.stdin:
                self.events.put(('command', line))
        if seconds is None:
            threading.Thread(target=reader, daemon=True).start()
        deadline = None if seconds is None else time.monotonic() + seconds
        next_discovery = 0
        next_health = 0
        startup_done = False
        while not self.stop and (deadline is None or time.monotonic() < deadline):
            now = time.monotonic()
            if now >= next_discovery:
                self.discover()
                next_discovery = now + 5
            self.pump()
            if self.process and (not startup_done) and (self.process.poll() is not None):
                self.startup_reader.join(timeout=1)
                self.pump()
                startup_done = True
                if self.process.returncode:
                    self.pending_error = None
                    self.report('一键启动失败，退出码 ' + str(self.process.returncode), 'startup')
                    self.emit('控制台', '启动失败，窗口保留供排查。修复后重新双击启动快捷方式。', False)
                else:
                    self.ready = True
                    self.emit('控制台', '启动完成，正在持续显示实时日志。', False)
            if self.ready and now >= next_health:
                self.health()
                next_health = now + 10
            time.sleep(0.2)
        self.handler.close()
        self.log.removeHandler(self.handler)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--no-start', action='store_true')
    parser.add_argument('--seconds', type=float)
    args = parser.parse_args()
    os.environ['PYTHONUTF8'] = '1'
    if os.name == 'nt':
        import ctypes
        kernel = ctypes.windll.kernel32
        kernel.SetConsoleTitleW('本地助手服务器 · 实时日志与错误报告')
        handle = kernel.GetStdHandle(-11)
        mode = ctypes.c_ulong()
        if kernel.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel.SetConsoleMode(handle, mode.value | 4)
    app = Console()
    try:
        app.run(args.no_start, args.seconds)
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        app.emit('控制台', 'ERROR ' + repr(exc))
        app.report('日志控制台异常：' + repr(exc), 'console')
        if args.seconds is None:
            input('错误报告已保存，按回车关闭窗口。')
if __name__ == '__main__':
    main()
