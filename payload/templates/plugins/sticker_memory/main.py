import asyncio
import base64
import random
import re
import sys
import time
from pathlib import Path
from astrbot.api.event import AstrMessageEvent,MessageChain,filter
from astrbot.api.star import Context,Star,register
import astrbot.api.message_components as Comp
from .core import OWNERS,Catalogue,candidates,read_candidate,classify,EMOTIONS,SKIP_REPLY

@register('sticker_memory','local','识别合适表情并收藏到QQ，按话题偶尔主动发送','1.0.0')
class StickerMemory(Star):
    def __init__(self,context: Context):
        super().__init__(context)
        self.folder=Path(__file__).resolve().parent
        self.catalogue=Catalogue(self.folder)
        self.queue=asyncio.Queue(maxsize=8)
        self.bot=None;self.account=None;self.native={};self.synced=False;self.bootstrap_task=None
        self.queued=set();self.admission={};self.last_sent={};self.last_global=0
        self.send_lock=asyncio.Lock()
        self.task=asyncio.create_task(self.worker())

    async def api(self,action,**params):
        if self.bot is None:raise RuntimeError('QQ bridge is not ready')
        result=await asyncio.wait_for(self.bot.call_action(action=action,self_id=self.account,**params),45)
        if isinstance(result,dict) and 'retcode' in result:
            if result['retcode']!=0:raise RuntimeError('QQ action failed')
            result=result.get('data')
        return result

    async def sync(self):
        try:
            entries=await self.api('fetch_custom_face_detail',count=200)
            if isinstance(entries,list):
                self.native={str(item.get('md5') or '').upper():str(item.get('emoji_id') or item.get('resId') or '') for item in entries if isinstance(item,dict)}
                self.synced=True
        except Exception as exc:self.logger.warning('[表情收藏] 读取已有收藏失败：%s',type(exc).__name__)

    async def bootstrap(self):
        try:
            entries=await self.api('fetch_custom_face_detail',count=200)
            if not isinstance(entries,list):return
            self.native={str(v.get('md5') or '').upper():str(v.get('emoji_id') or v.get('resId') or '') for v in entries if isinstance(v,dict)}
            self.synced=True
            # Gradually index existing QQ favorites, without changing or re-uploading them.
            for entry in entries[:12]:
                url=str(entry.get('url') or '')
                if not url.startswith(('http://','https://')) or url in self.queued:continue
                self.queued.add(url)
                await self.queue.put({'url':url,'hint':str(entry.get('desc') or '')[:100],'marked':True,'native_id':str(entry.get('emoji_id') or entry.get('resId') or '')})
        except asyncio.CancelledError:raise
        except Exception as exc:self.logger.warning('[表情收藏] 已有收藏索引未完成：%s',type(exc).__name__)

    async def worker(self):
        while True:
            candidate=await self.queue.get()
            try:
                if not self.catalogue.data['learning'] or not self.catalogue.capacity():continue
                # Video/MV screening takes priority over optional meme learning.
                while any(getattr(sys.modules.get(module),'_LIMIT',None) is not None and sys.modules[module]._LIMIT.locked()
                          for module in ('data.plugins.video_parse.content_screen','data.plugins.music_request.content_screen')):
                    await asyncio.sleep(2)
                image=await asyncio.to_thread(read_candidate,candidate['url'])
                if self.catalogue.known(image['sha']):continue
                result=await classify(image)
                if not result:
                    self.catalogue.reject(image['sha']);continue
                if not self.catalogue.data['learning'] or not self.catalogue.capacity():continue
                if not self.synced:await self.sync()
                emoji_id=candidate.get('native_id') or self.native.get(image['md5'])
                created=False
                if not emoji_id:
                    reply=await self.api('add_custom_face',file='base64://'+base64.b64encode(image['bytes']).decode())
                    emoji_id=(reply or {}).get('emoji_id') if isinstance(reply,dict) else None
                    created=True
                if not emoji_id:raise RuntimeError('QQ did not confirm the favorite ID')
                self.catalogue.remember(image,result,emoji_id,self.account)
                self.native[image['md5']]=emoji_id
                if created:
                    try:await self.api('modify_custom_face',emoji_id=emoji_id,desc=result['caption'][:60])
                    except Exception as exc:self.logger.warning('[表情收藏] 已收藏，备注未写入：%s',type(exc).__name__)
                self.logger.info('[表情收藏] 已加入QQ收藏并索引：%s；标签=%s',result['caption'],','.join(result['tags']))
            except asyncio.CancelledError:raise
            except Exception as exc:self.logger.warning('[表情收藏] 本次学习未完成：%s',str(exc)[:200])
            finally:
                self.queued.discard(candidate['url']);self.queue.task_done()

    async def say(self,event,text):
        mid=getattr(event.message_obj,'message_id',None)
        quote=[Comp.Reply(id=str(mid))] if mid is not None else []
        await event.send(MessageChain(quote+[Comp.Plain(text)]))

    async def maybe_send(self,event,context,probability=.22,reply_to=None):
        origin=event.unified_msg_origin
        now=time.monotonic()
        if not self.catalogue.data['automatic'] or self.send_lock.locked() or now-self.last_global<45 or now-self.last_sent.get(origin,0)<180:return
        chosen=self.catalogue.choose(context,self.account)
        if not chosen or random.random()>probability:return
        sha,item=chosen
        async with self.send_lock:
            try:
                destination={'group_id':int(event.get_group_id())} if event.get_group_id() else {'user_id':int(event.get_sender_id())}
                mid=reply_to or getattr(event.message_obj,'message_id',None)
                if mid is not None:destination['reply_to']=int(mid)
                await self.api('send_custom_face',emoji_id=item['emoji_id'],**destination)
                item['last_used']=time.time();self.catalogue.save()
                self.last_global=time.monotonic();self.last_sent[origin]=self.last_global
                self.logger.info('[表情发送] 已按话题发送QQ收藏表情；标签=%s',','.join(item['tags']))
            except Exception as exc:
                item['retry_after']=time.time()+3600;self.catalogue.save()
                self.logger.warning('[表情发送] 原生发送未完成：%s',str(exc)[:200])

    @filter.event_message_type(filter.EventMessageType.ALL,priority=1850)
    async def observe(self,event: AstrMessageEvent):
        if event.get_platform_name()!='aiocqhttp' or str(event.get_sender_id())==str(event.get_self_id()):return
        self.bot=getattr(event,'bot',None);self.account=str(event.get_self_id())
        if self.bootstrap_task is None and self.bot is not None:
            self.bootstrap_task=asyncio.create_task(self.bootstrap())
        text=''.join(p.text for p in event.get_messages() if isinstance(p,Comp.Plain)).strip()
        management=re.fullmatch(r'表情(?:状态|学习\s*[开关]|自动\s*[开关])',text)
        if management:
            event.stop_event()
            if str(event.get_sender_id()) not in OWNERS:
                await self.say(event,'拒绝执行：只有主人可以使用命令。');return
            if text=='表情状态':
                await self.say(event,f"表情学习：{'开' if self.catalogue.data['learning'] else '关'}；主动表情：{'开' if self.catalogue.data['automatic'] else '关'}\n已索引QQ收藏：{len(self.catalogue.data['items'])}；待识别：{self.queue.qsize()}\n控制：表情学习 开/关、表情自动 开/关")
            else:
                field='learning' if text.startswith('表情学习') else 'automatic'
                self.catalogue.data[field]=text.endswith('开');self.catalogue.save()
                await self.say(event,'已'+('开启' if self.catalogue.data[field] else '关闭')+('表情学习。' if field=='learning' else '主动发表情。'))
            return
        if self.catalogue.data['learning'] and self.catalogue.capacity():
            # Never collect desktop-control screenshots or task attachments.
            if not re.search(r'电脑|圈选|截图|翻唱|点歌|模型|PTH',text,re.I):
                origin=event.unified_msg_origin;now=time.monotonic()
                if now-self.admission.get(origin,0)>40:
                    raw=getattr(event.message_obj,'raw_message',None)
                    for item in candidates(raw):
                        if item['url'] in self.queued or self.queue.full():continue
                        self.queued.add(item['url']);self.queue.put_nowait(item);self.admission[origin]=now
        # Occasional casual reactions even when the main chatbot is not speaking.
        mentioned=any(isinstance(p,Comp.At) and str(p.qq)==str(event.get_self_id()) for p in event.get_messages())
        if event.get_group_id() and not mentioned and len(text)<100 and not SKIP_REPLY.search(text):
            await self.maybe_send(event,text,probability=.07)

    @filter.after_message_sent(priority=100)
    async def after_reply(self,event: AstrMessageEvent):
        if event.get_platform_name()!='aiocqhttp':return
        context=event.get_extra('_sticker_reply_context',None)
        if context:
            self.bot=getattr(event,'bot',None);self.account=str(event.get_self_id())
            await self.maybe_send(event,context[0],reply_to=context[1])

    async def terminate(self):
        tasks=[self.task]+([self.bootstrap_task] if self.bootstrap_task else [])
        for task in tasks:task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        self.catalogue.save()
