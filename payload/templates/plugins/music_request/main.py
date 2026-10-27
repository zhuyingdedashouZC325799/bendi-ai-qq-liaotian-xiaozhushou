from .local_library import ClientAudioProtected
import asyncio
import re
import time
import uuid
from pathlib import Path

from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.star import Context, Star, register
import astrbot.api.message_components as Comp

from .core import AudioUnavailable, LoginRequired, PoliticalMediaError, MusicService, render_card, safe_filename
from .cache_cleanup import CleanupQueue
from .selection_state import claim,active,clear


@register('music_request', 'local', 'QQ/网易云点歌、MV音轨回退与发送后缓存清理', '1.3.0')
class MusicRequest(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.folder = Path(__file__).resolve().parent
        self.music = MusicService(self.folder, self.logger)
        self.pending = {}
        self.locks = {}
        self.tasks = set()
        self.cleanup_queue = CleanupQueue(self.music.cache,self.folder/'music_cleanup_jobs.json',self.logger)

    def key(self, event):
        return (event.unified_msg_origin, str(event.get_sender_id()))

    def addressed(self, event):
        return not event.get_group_id() or any(
            isinstance(part, Comp.At) and str(part.qq) == str(event.get_self_id())
            for part in event.get_messages())

    def cleanup_later(self, path):
        self.cleanup_queue.schedule([path],delay=60)

    async def say(self, event, text):
        await event.send(MessageChain([Comp.Plain(text)]))

    @filter.event_message_type(filter.EventMessageType.ALL, priority=1050)
    async def music_command(self, event: AstrMessageEvent):
        text = ''.join(p.text for p in event.get_messages() if isinstance(p, Comp.Plain)).strip()
        key = self.key(event)
        now = time.monotonic()
        for old_key in list(self.pending):
            if self.pending[old_key]['expires'] < now:
                self.pending.pop(old_key, None)
                lock = self.locks.get(old_key)
                if lock and not lock.locked():
                    self.locks.pop(old_key, None)
        match = re.fullmatch(r'点歌(?:\s+(.+))?', text, re.DOTALL)
        if match and self.addressed(event):
            claim(key,'music')
            event.stop_event()
            query = (match.group(1) or '').strip()
            if not query:
                await self.say(event, '点歌格式：@我 点歌 歌名，例如 @我 点歌 卡农')
                return
            if len(query) > 100:
                await self.say(event, '歌名太长啦，请控制在 100 字以内。')
                return
            lock = self.locks.setdefault(key, asyncio.Lock())
            if lock.locked():
                await self.say(event, '上一条点歌还在处理中，稍等一下。')
                return
            async with lock:
                self.pending.pop(key, None)
                await self.say(event, '正在音乐网页搜索《' + query + '》…')
                card = self.music.cache / (uuid.uuid4().hex + '.png')
                try:
                    songs = await self.music.search(query)
                    if not songs:
                        await self.say(event, '没有搜到候选歌曲，可以换几个关键词再试；不需要知道歌手。')
                        return
                    try:
                        await asyncio.to_thread(render_card, self.folder / 'background.jpg', songs, query, card)
                        await event.send(MessageChain([Comp.Image.fromFileSystem(str(card))]))
                        self.cleanup_later(card)
                    except Exception as exc:
                        card.unlink(missing_ok=True)
                        self.logger.warning('点歌图片不可用，改发文字清单：%s', exc)
                        listing = '\n'.join(f"{i+1}. {s['name']} — {s['artist']} [{s['status']}]" for i, s in enumerate(songs))
                        await self.say(event, listing)
                    self.pending[key] = {'songs': songs, 'expires': time.monotonic() + 180}
                    await self.say(event, '回复 1～' + str(len(songs)) + ' 选歌，0 取消，3 分钟内有效。')
                except LoginRequired:
                    await self.say(event, '音乐网页要求登录，暂时无法可靠搜索。请让管理员登录机器人专用的音乐浏览器，再重新点歌；不会返回不相干的歌单。')
                except Exception as exc:
                    self.logger.exception('点歌搜索失败：%s', exc)
                    await self.say(event, '音乐网页暂时没有响应，请稍后重新点歌。')
            return
        if not re.fullmatch(r'\d{1,2}', text) or key not in self.pending or not active(key,'music'):
            return
        event.stop_event()
        number = int(text)
        lock = self.locks.setdefault(key, asyncio.Lock())
        if lock.locked():
            await self.say(event, '歌曲正在处理中，请稍等。')
            return
        async with lock:
            current = self.pending.get(key)
            if current is None:
                return
            if number == 0:
                self.pending.pop(key, None)
                await self.say(event, '已取消点歌。')
                return
            if not 1 <= number <= len(current['songs']):
                await self.say(event, '请选择 1～' + str(len(current['songs'])) + '，或回复 0 取消。')
                return
            song = current['songs'][number - 1]
            await self.say(event, '正在获取《' + song['name'] + '》— ' + song['artist'] + '…')
            path = None
            stage = '下载'
            try:
                path = await self.music.download(song)
                stage='发送'
                output_song=song
                if song.get('_audio_source')=='MV音轨':
                    await self.say(event,'已从同名、同歌手MV提取音轨，发送MV音轨版。')
                    output_song=dict(song,name=song['name']+'（MV音轨版）')
                await event.send(MessageChain([Comp.File(name=safe_filename(output_song), file=str(path))]))
                self.pending.pop(key, None)
                self.cleanup_later(path)
            except AudioUnavailable as exc:
                self.logger.warning("点歌完整音频未取得：%s",type(exc.__cause__).__name__)
                await self.say(event,str(exc))
            except ClientAudioProtected as exc:
                await self.say(event,str(exc))
            except PoliticalMediaError:
                self.pending.pop(key,None)
                await self.say(event,'我拒绝。')
            except PermissionError:
                await self.say(event, '所选歌曲网页未返回可用的完整音轨，可以换一个版本重试。\n' + song['page'])
            except Exception as exc:
                self.logger.exception('点歌下载或发送失败：%s', exc)
                await self.say(event, '歌曲下载失败，请稍后重新选歌。' if stage=='下载' else '歌曲完整音频已下载，但 QQ 未确认文件发送；缓存已保留，可以稍后重试。')

    async def terminate(self):
        await self.cleanup_queue.close()
        for task in tuple(self.tasks):
            task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
