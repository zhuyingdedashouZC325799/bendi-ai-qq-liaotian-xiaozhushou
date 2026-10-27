from portable_settings import remap as _portable_path, owners as _portable_owners, settings as _portable_settings, speaker_policy as _portable_speaker, text as _portable_text, port as _portable_port, cache_for as _portable_cache
import asyncio
import json
from pathlib import Path
import re
import time
import uuid
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.star import Context, Star, register
import astrbot.api.message_components as Comp
from .core import AgentError, TTL, owner_allowed, app_catalog, find_app, capture, thumbnail, launch_app, marked_point, click_point
from .image_io import download_marked
from .cache_cleanup import CleanupQueue
HELP = '本地电脑 Agent 已接入。\n• 电脑 打开记事本（也支持其他已安装的软件）\n• 电脑 截图\n• 电脑 软件列表\n把刚发出的完整截图保存后，用红色粗线只圈一个按钮，发回来即点击；可配文字“双击”或“右键”。\n• 电脑 取消：清除待圈选截图\n私聊直接发；群聊每次都要 @我。只认两个主人QQ号，截图5分钟内有效。'
from .desktop_intent import command

@register('desktop_agent', 'local', '主人专属本地电脑控制：打开软件、截图、圈选点击', '1.0.0')
class DesktopAgent(Star):

    def __init__(self, context: Context):
        super().__init__(context)
        self.folder = Path(__file__).resolve().parent
        self.cache = _portable_cache(__file__, 'cache')
        self.cache.mkdir(exist_ok=True)
        self.cleanup = CleanupQueue(self.cache, self.folder / 'cleanup_jobs.json', self.logger)
        self.lock = asyncio.Lock()
        self.sessions = {}
        self.generation = 0
        self.apps = {}

    def key(self, event):
        return (event.unified_msg_origin, str(event.get_sender_id()))

    def quote(self, event):
        mid = getattr(event.message_obj, 'message_id', None)
        return [Comp.Reply(id=str(mid))] if mid is not None else []

    async def say(self, event, text):
        await event.send(MessageChain(self.quote(event) + [Comp.Plain(text)]))

    def audit(self, event, action):
        path = self.folder / 'actions.jsonl'
        if path.exists() and path.stat().st_size > 1000000:
            path.replace(self.folder / 'actions.previous.jsonl')
        with path.open('a', encoding='utf-8') as output:
            output.write(json.dumps({'time': time.strftime('%Y-%m-%d %H:%M:%S'), 'qq': str(event.get_sender_id()), 'origin': event.unified_msg_origin, 'action': action}, ensure_ascii=False) + '\n')

    async def send_screen(self, event, note='当前电脑画面'):
        image = await asyncio.to_thread(capture)
        shown = thumbnail(image)
        token = uuid.uuid4().hex[:8]
        path = self.cache / (token + '.png')
        await asyncio.to_thread(shown.save, path)
        try:
            await event.send(MessageChain(self.quote(event) + [Comp.Plain(note + '。截图编号 ' + token + '；请只圈一个按钮并发回完整图片，5分钟内有效。'), Comp.Image.fromFileSystem(str(path))]))
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        self.cleanup.schedule([path], delay=TTL)
        if len(self.sessions) >= 8:
            self.sessions.pop(next(iter(self.sessions)), None)
        self.sessions[self.key(event)] = {'baseline': image, 'shown': shown, 'generation': self.generation, 'expires': time.monotonic() + TTL, 'token': token}
        self.audit(event, 'screenshot ' + token)

    @filter.event_message_type(filter.EventMessageType.ALL, priority=2000)
    async def desktop_command(self, event: AstrMessageEvent):
        text = ''.join((p.text for p in event.get_messages() if isinstance(p, Comp.Plain))).strip()
        action, explicit = command(text)
        key = self.key(event)
        for old in list(self.sessions):
            if self.sessions[old]['expires'] < time.monotonic():
                self.sessions.pop(old, None)
        images = [p for p in event.get_messages() if isinstance(p, Comp.Image)]
        active = key in self.sessions
        if not explicit and (not (images and active)):
            return
        mentioned = any((isinstance(p, Comp.At) and str(p.qq) == str(event.get_self_id()) for p in event.get_messages()))
        qq_platform = event.get_platform_name() in ('aiocqhttp', 'qq_official', 'qq_official_webhook')
        if not qq_platform or not owner_allowed(event.get_sender_id(), event.get_group_id(), mentioned):
            if event.get_group_id() and (not mentioned):
                return
            event.stop_event()
            await self.say(event, '拒绝操作：电脑控制只允许两个主人QQ号使用；群聊必须 @我。')
            return
        event.stop_event()
        if self.lock.locked():
            await self.say(event, '电脑正在执行上一条操作，请稍后再发。')
            return
        async with self.lock:
            try:
                if action in ('取消', '停止', '结束', '退出'):
                    self.sessions.pop(key, None)
                    await self.say(event, '已取消待圈选截图。')
                    return
                if images:
                    if len(images) != 1:
                        raise AgentError('每次请只发一张圈选截图。')
                    session = self.sessions.get(key)
                    if not session or session['expires'] < time.monotonic():
                        raise AgentError('没有有效的待圈选截图，请先发“电脑 截图”。')
                    if session['generation'] != self.generation:
                        self.sessions.pop(key, None)
                        raise AgentError('电脑已被其他操作改变，请重新发“电脑 截图”再圈选。')
                    if action not in ('', '点击', '点这里', '点击圈选', '点击圈出的按钮', '双击', '右键', '点击这里'):
                        raise AgentError('圈选图片请只配“点击”“双击”或“右键”，也可以不配文字。')
                    url = images[0].url or images[0].file or ''
                    marked = await asyncio.to_thread(download_marked, url)
                    point = await asyncio.to_thread(marked_point, session['shown'], marked)
                    self.sessions.pop(key, None)
                    await asyncio.to_thread(click_point, session['baseline'], session['shown'].size, point, action == '双击', action == '右键')
                    self.generation += 1
                    self.audit(event, 'marked ' + ('double' if action == '双击' else 'right' if action == '右键' else 'click'))
                    await asyncio.sleep(0.65)
                    await self.send_screen(event, '已' + ('双击' if action == '双击' else '右键点击' if action == '右键' else '点击') + '圈出的按钮')
                    return
                if action in ('', '帮助', 'help', '开启', '开始'):
                    await self.say(event, HELP)
                    return
                if action in ('截图', '截屏', '看看', '查看屏幕', '看看电脑'):
                    await self.send_screen(event)
                    return
                if action in ('软件列表', '应用列表', '有哪些软件'):
                    self.apps = await asyncio.to_thread(app_catalog)
                    names = sorted(self.apps, key=str.casefold)
                    for start in range(0, len(names), 60):
                        await self.say(event, '可打开的软件：\n' + '\n'.join(names[start:start + 60]))
                    return
                match = re.fullmatch('(?:打开|启动)\\s*(.+?)(?:\\s*(?:并|然后|后)(?:给我)?截图)?', action, re.S)
                if match:
                    self.apps = await asyncio.to_thread(app_catalog)
                    name, path = find_app(match.group(1), self.apps)
                    await self.say(event, '正在打开 ' + name + '，随后返回截图。')
                    await asyncio.to_thread(launch_app, path)
                    self.generation += 1
                    self.audit(event, 'open ' + name)
                    await asyncio.sleep(2)
                    await self.send_screen(event, '已发出 ' + name + ' 的启动请求；当前画面如下')
                    return
                await self.say(event, HELP)
            except AgentError as exc:
                await self.say(event, str(exc))
            except Exception as exc:
                self.logger.exception('[电脑Agent] 执行失败: %s', type(exc).__name__)
                await self.say(event, '电脑操作没有完成，未继续执行。请重新发“电脑 截图”检查当前画面。')

    async def terminate(self):
        self.sessions.clear()
        await self.cleanup.close()
