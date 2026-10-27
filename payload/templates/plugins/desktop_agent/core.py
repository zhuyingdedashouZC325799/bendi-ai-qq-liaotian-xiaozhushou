"""Owner-directed Windows desktop actions. No shell or model-generated commands."""
from portable_settings import remap as _portable_path, owners as _portable_owners, settings as _portable_settings, speaker_policy as _portable_speaker, text as _portable_text, port as _portable_port, cache_for as _portable_cache
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import re
import time
from PIL import Image, ImageChops, ImageFilter, ImageGrab, ImageStat
OWNERS = frozenset(_portable_owners(as_int=False))
TTL = 300

class AgentError(ValueError):
    pass

def owner_allowed(uid, group_id='', mentioned=False):
    return str(uid) in OWNERS and (not group_id or mentioned)

def normalize_name(value):
    return re.sub('[\\s_\\-（）()]+', '', value).casefold()

def app_catalog():
    roots = [Path(os.environ.get('PROGRAMDATA', 'C:/ProgramData')) / 'Microsoft/Windows/Start Menu/Programs', Path(os.environ.get('APPDATA', '')) / 'Microsoft/Windows/Start Menu/Programs', Path.home() / 'Desktop', Path(_portable_path('C:/Users/Public/Desktop'))]
    apps = {}
    for root in roots:
        if root.is_dir():
            for path in root.rglob('*'):
                if path.suffix.lower() == '.lnk' and (not re.search('卸载|uninstall', path.stem, re.I)):
                    apps.setdefault(path.stem, str(path.resolve()))
    windows = Path(os.environ.get('WINDIR', 'C:/Windows'))
    for name, exe in [('记事本', 'notepad.exe'), ('计算器', 'calc.exe'), ('画图', 'mspaint.exe'), ('资源管理器', 'explorer.exe')]:
        candidate = windows / 'System32' / exe
        if not candidate.exists():
            candidate = windows / exe
        if candidate.exists():
            apps[name] = str(candidate)
    return apps

def find_app(query, apps):
    query = query.strip(' ，。！!')
    if not query or len(query) > 80 or any((c in query for c in ('\\', '/', '\n', '\r', ':'))):
        raise AgentError('请提供软件名，例如：电脑 打开记事本。')
    aliases = {'浏览器': 'Google Chrome', '谷歌浏览器': 'Google Chrome', 'chrome': 'Google Chrome', 'edge': 'Microsoft Edge', '微信': '微信', '文件管理器': '资源管理器', 'notepad': '记事本', '网易云': '网易云音乐', 'qq音乐': 'QQ音乐'}
    query = aliases.get(query.casefold(), query)
    q = normalize_name(query)
    exact = [name for name in apps if normalize_name(name) == q]
    if exact:
        return (exact[0], apps[exact[0]])
    names = [name for name in apps if q in normalize_name(name)]
    if len(names) == 1:
        return (names[0], apps[names[0]])
    if names:
        raise AgentError('找到多个软件，请说完整名称：' + '、'.join(names[:12]))
    raise AgentError('没有找到这个软件。发“电脑 软件列表”查看已识别的软件。')

def desktop_ready():
    user32 = ctypes.windll.user32
    user32.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    user32.OpenInputDesktop.restype = wintypes.HANDLE
    user32.SwitchDesktop.argtypes = [wintypes.HANDLE]
    user32.CloseDesktop.argtypes = [wintypes.HANDLE]
    handle = user32.OpenInputDesktop(0, False, 256)
    if not handle:
        raise AgentError('当前桌面已锁定或处于系统授权界面，无法操作；请先在电脑上解锁。')
    try:
        if not user32.SwitchDesktop(handle):
            raise AgentError('当前桌面不可交互，请先在电脑上解锁。')
    finally:
        user32.CloseDesktop(handle)

def dpi_aware():
    try:
        fn = ctypes.windll.user32.SetThreadDpiAwarenessContext
        fn.argtypes = [ctypes.c_void_p]
        fn.restype = ctypes.c_void_p
        return fn(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        return None

def restore_dpi(previous):
    if previous:
        ctypes.windll.user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(previous))

def capture():
    desktop_ready()
    previous = dpi_aware()
    try:
        image = ImageGrab.grab(all_screens=False).convert('RGB')
    finally:
        restore_dpi(previous)
    if image.width < 100 or image.height < 100:
        raise AgentError('无法获取有效桌面截图。')
    if max(ImageStat.Stat(image.resize((64, 64))).stddev) < 1:
        raise AgentError('截图为空白，当前桌面可能不可用。')
    return image

def launch_app(path):
    desktop_ready()
    candidate = Path(path)
    if candidate.suffix.lower() not in ('.lnk', '.exe') or not candidate.is_file():
        raise AgentError('软件启动入口已失效，请更新软件列表。')
    os.startfile(str(candidate))

def thumbnail(image):
    image = image.copy()
    image.thumbnail((1280, 900), Image.Resampling.LANCZOS)
    return image

def changed_fraction(a, b):
    if a.size != b.size:
        return 1.0
    diff = ImageChops.difference(a.convert('RGB').resize((240, 135)), b.convert('RGB').resize((240, 135)))
    return sum((max(px) > 48 for px in diff.getdata())) / (240 * 135)

def marked_point(original, marked):
    """Locate a single closed annotation by comparing against the exact sent screenshot."""
    original = original.convert('RGB')
    marked = marked.convert('RGB')
    if abs(original.width / original.height - marked.width / marked.height) > 0.02:
        raise AgentError('请在机器人刚发出的完整截图上画圈，不要裁剪截图。')
    marked = marked.resize(original.size, Image.Resampling.LANCZOS)
    if changed_fraction(original, marked) > 0.12:
        raise AgentError('图片与上一张截图不一致，请重新截图后只圈一个按钮。')
    scale = min(1, 640 / original.width)
    size = (round(original.width * scale), round(original.height * scale))
    diff = ImageChops.difference(original.resize(size), marked.resize(size))
    mask = Image.new('L', size)
    mask.putdata([255 if max(p) > 65 and sum(p) > 120 else 0 for p in diff.getdata()])
    mask = mask.filter(ImageFilter.MaxFilter(3))
    pixels = bytearray(mask.tobytes())
    w, h = size
    candidates = []
    for start in range(len(pixels)):
        if not pixels[start]:
            continue
        stack = [start]
        pixels[start] = 0
        component = []
        while stack:
            i = stack.pop()
            component.append(i)
            x = i % w
            y = i // w
            for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if 0 <= nx < w and 0 <= ny < h:
                    j = ny * w + nx
                    if pixels[j]:
                        pixels[j] = 0
                        stack.append(j)
        if len(component) < 35:
            continue
        xs = [i % w for i in component]
        ys = [i // w for i in component]
        left, right, top, bottom = (min(xs), max(xs), min(ys), max(ys))
        bw = right - left + 1
        bh = bottom - top + 1
        if bw < 9 or bh < 9 or bw > w * 0.65 or (bh > h * 0.65):
            continue
        blocked = {(i % w - left + 1, i // w - top + 1) for i in component}
        outside = {(0, 0)}
        stack = [(0, 0)]
        while stack:
            x, y = stack.pop()
            for p in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if 0 <= p[0] < bw + 2 and 0 <= p[1] < bh + 2 and (p not in blocked) and (p not in outside):
                    outside.add(p)
                    stack.append(p)
        enclosed = (bw + 2) * (bh + 2) - len(blocked) - len(outside)
        if enclosed > max(20, bw * bh * 0.12):
            candidates.append(((left + right) / 2 / scale, (top + bottom) / 2 / scale))
    if len(candidates) != 1:
        raise AgentError('没有识别到唯一的圈选。请用红色粗线只圈一个按钮，再发完整截图。')
    return candidates[0]

def click_point(baseline, displayed_size, point, double=False, right=False):
    desktop_ready()
    previous = dpi_aware()
    try:
        current = ImageGrab.grab(all_screens=False).convert('RGB')
        if changed_fraction(baseline, current) > 0.025:
            raise AgentError('电脑画面已经变化，为防止点错，请重新截图再圈选。')
        x = round(point[0] * baseline.width / displayed_size[0])
        y = round(point[1] * baseline.height / displayed_size[1])
        if not (0 < x < baseline.width - 1 and 0 < y < baseline.height - 1):
            raise AgentError('圈选位置超出可点击范围。')
        user32 = ctypes.windll.user32
        user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
        if not user32.SetCursorPos(x, y):
            raise AgentError('移动鼠标失败，未点击。')
        flags = (8, 16) if right else (2, 4)
        for _ in range(2 if double else 1):
            user32.mouse_event(flags[0], 0, 0, 0, 0)
            user32.mouse_event(flags[1], 0, 0, 0, 0)
            time.sleep(0.08)
        return (x, y)
    finally:
        restore_dpi(previous)
