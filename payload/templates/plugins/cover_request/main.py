from astrbot.core.utils import local_compute as compute_gate
from data.plugins.music_request.local_library import ClientAudioProtected
import asyncio
import json
from pathlib import Path
import re
import time
import uuid
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.star import Context, Star, register
import astrbot.api.message_components as Comp
from data.plugins.music_request.core import MusicService, AudioUnavailable, LoginRequired, render_card
from data.plugins.music_request.selection_state import claim,active,clear
from data.plugins.music_request.content_screen import POLITICS
from .pipeline import CoverPipeline, list_voices, select_voice, list_indexes
from .cache_cleanup import CleanupQueue

@register('cover_request','local','QQ音乐选歌、选择PTH、UVR5分离、RVC换声后发送QQ语音','1.0.0')
class CoverRequest(Star):
    def __init__(self,context: Context):
        super().__init__(context)
        self.folder=Path(__file__).resolve().parent
        self.pipeline=CoverPipeline(self.folder)
        music_folder=self.folder.parent/'music_request'
        self.music=MusicService(music_folder,self.logger)
        self.cleanup=CleanupQueue(self.pipeline.cache,self.folder/'cleanup_jobs.json',self.logger)
        self.pending={};self.lock=asyncio.Lock();self.search_lock=asyncio.Lock()
        self.pending_file=self.folder/'pending_choices.json'
        self.running={}
        if self.pending_file.exists():
            try:
                for row in json.loads(self.pending_file.read_text(encoding='utf-8')):
                    key=tuple(row['key']);state=row['state']
                    if len(key)==2 and state.get('expires',0)>time.time():
                        self.pending[key]=state;claim(key,'cover')
            except (ValueError,KeyError,TypeError):self.logger.warning('[翻唱] 选择记录损坏，未恢复')

    def save_pending(self):
        temporary=self.pending_file.with_suffix('.tmp')
        temporary.write_text(json.dumps([{'key':list(k),'state':v} for k,v in self.pending.items()],ensure_ascii=False),encoding='utf-8')
        temporary.replace(self.pending_file)

    async def heartbeat(self,event,key):
        while key in self.running:
            await asyncio.sleep(90)
            job=self.running.get(key)
            if not job:return
            elapsed=int(time.monotonic()-job['started'])
            try:await self.say(event,f"翻唱仍在处理：{job['stage']}；已用时 {elapsed//60}分{elapsed%60}秒。可发“翻唱进度”查看。")
            except Exception:self.logger.warning('[翻唱] 进度提示发送失败，继续处理音频')


    def key(self,event):return(event.unified_msg_origin,str(event.get_sender_id()))
    def addressed(self,event):
        return not event.get_group_id() or any(isinstance(p,Comp.At) and str(p.qq)==str(event.get_self_id()) for p in event.get_messages())
    async def say(self,event,text):
        mid=getattr(event.message_obj,'message_id',None)
        chain=([Comp.Reply(id=str(mid))] if mid is not None else [])+[Comp.Plain(text)]
        await event.send(MessageChain(chain))
    async def send_cover_outputs(self,event,song,result):
        title=re.sub(r'[\x00-\x1f<>:"/\\|?*]','_',str(song['name'])).strip(' .')[:120] or '歌曲'
        filename=title+'翻唱.mp3'
        failed=[]
        try:
            await event.send(MessageChain([Comp.Record.fromFileSystem(str(result))]))
        except Exception as exc:
            failed.append('语音')
            self.logger.exception('[翻唱] 成品语音发送失败：%s',type(exc).__name__)
        try:
            await event.send(MessageChain([Comp.File(name=filename,file=str(result))]))
        except Exception as exc:
            failed.append('MP3文件')
            self.logger.exception('[翻唱] 成品MP3发送失败：%s',type(exc).__name__)
        if failed:
            await self.say(event,'翻唱已完成，但'+'和'.join(failed)+'未发送成功，成品缓存已保留。')
            return False
        return True

    async def choose_model(self,event,song):
        voices=await asyncio.to_thread(list_voices)
        if not voices:raise ValueError('本机没有找到可用 PTH 模型。')
        self.pending[self.key(event)]={'stage':'voice','song':song,'voices':voices,'expires':time.time()+1800}
        claim(self.key(event),'cover');self.save_pending()
        listing='\n'.join(f"{i+1}. {v['filename']}"+('（有检索索引）' if v['index'] else '') for i,v in enumerate(voices))
        await self.say(event,'已选《'+song['name']+'》—'+song['artist']+'。\n请选择 PTH 文件：\n'+listing+'\n直接回复模型编号，例如 1；也可回复“翻唱模型 洛天依.pth”。30分钟内有效；回复0取消。')

    async def choose_index(self,event,voice):
        indexes=await asyncio.to_thread(list_indexes,voice)
        key=self.key(event)
        if not indexes:
            await self.say(event,'这个 PTH 没有找到配套 INDEX 文件，暂不开始翻唱。请从上一份 PTH 清单选择另一个模型，或把配套 INDEX 放入对应模型目录。')
            return
        self.pending[key].update(stage='index',voice=voice,indexes=indexes,expires=time.time()+1800)
        claim(key,'cover');self.save_pending()
        listing='\n'.join(f"{i+1}. {item['name']}（{item['bytes']/1048576:.1f}MB）" for i,item in enumerate(indexes))
        await self.say(event,'已选 PTH：'+voice['filename']+'\n请选择配套 INDEX：\n'+listing+'\n直接回复索引编号，例如 1；选完开始翻唱，回复0取消。')

    @filter.event_message_type(filter.EventMessageType.ALL,priority=1250)
    async def cover_command(self,event: AstrMessageEvent):
        text=''.join(p.text for p in event.get_messages() if isinstance(p,Comp.Plain)).strip()
        key=self.key(event)
        expired=key in self.pending and self.pending[key]['expires']<time.time()
        for old in list(self.pending):
            if self.pending[old]['expires']<time.time():self.pending.pop(old,None)
        if text=='翻唱进度':
            event.stop_event()
            if key in self.running:
                job=self.running[key];elapsed=int(time.monotonic()-job['started'])
                await self.say(event,f"当前进度：{job['stage']}；已用时 {elapsed//60}分{elapsed%60}秒。")
            elif key in self.pending:
                await self.say(event,'还没有开始处理音频，正在等待你'+({'song':'选择歌曲','voice':'选择PTH模型','index':'选择INDEX文件'}[self.pending[key]['stage']])+'；直接回复清单里的数字即可。')
            else:await self.say(event,'当前没有正在处理的翻唱任务。请发“翻唱 歌名”开始。')
            return
        if expired and re.fullmatch(r'\d+',text) and active(key,'cover'):
            event.stop_event();clear(key,'cover');self.save_pending()
            await self.say(event,'上次翻唱选择已过期，请重新发“翻唱 歌名”。');return
        start=re.fullmatch(r'翻唱(?:\s+(.+))?',text,re.S)
        song_select=re.fullmatch(r'翻唱选歌\s*(\d+)',text)
        voice_select=re.fullmatch(r'翻唱模型\s+(.+)',text,re.S)
        index_select=re.fullmatch(r'翻唱索引\s+(.+)',text,re.S)
        cancel=text in ('翻唱取消','取消翻唱')
        number=re.fullmatch(r'(\d{1,3})',text)
        if number and key in self.pending and active(key,'cover'):
            if text=='0':cancel=True
            elif self.pending[key]['stage']=='song':song_select=number
            elif self.pending[key]['stage']=='voice':voice_select=number
            else:index_select=number
        if not (start or song_select or voice_select or index_select or cancel):return
        if start and not self.addressed(event):return
        if not start and key not in self.pending:return
        event.stop_event()
        try:
            if cancel:
                self.pending.pop(key,None);clear(key,'cover');self.save_pending();await self.say(event,'已取消翻唱选择。');return
            if self.lock.locked():
                await self.say(event,'当前有一首歌正在翻唱，完成后再试，避免多任务抢占资源。');return
            if start:
                query=(start.group(1) or '').strip()
                if not query:
                    await self.say(event,'格式：@我 翻唱 歌名，例如：@我 翻唱 薛之谦 认真的雪');return
                if len(query)>100:raise ValueError('歌名请控制在100字以内。')
                if POLITICS.search(query):await self.say(event,'我拒绝。');return
                if self.search_lock.locked():await self.say(event,'正在搜索上一首歌，请稍等。');return
                claim(key,'cover')
                async with self.search_lock:
                    self.pending.pop(key,None)
                    self.save_pending()
                    await self.say(event,'正在搜索候选歌曲，稍后回复数字选择；不需要知道歌手…')
                    songs=await asyncio.wait_for(self.music.search(query),timeout=45)
                    if not songs:raise ValueError('没有搜到候选歌曲，可以换几个歌名关键词再试，不需要知道歌手。')
                    self.pending[key]={'stage':'song','songs':songs,'expires':time.time()+1800}
                    self.save_pending()
                    listing='\n'.join(f"{i+1}. {s['name']} — {s['artist']} / {s['album']} / {s['duration']//60}:{s['duration']%60:02d}" for i,s in enumerate(songs))
                    card=self.pipeline.cache/('song_choices_'+uuid.uuid4().hex+'.png')
                    try:
                        await asyncio.to_thread(render_card,self.music.folder/'background.jpg',songs,query,card,mode='cover')
                        mid=getattr(event.message_obj,'message_id',None)
                        chain=([Comp.Reply(id=str(mid))] if mid is not None else [])+[Comp.Image.fromFileSystem(str(card))]
                        await event.send(MessageChain(chain))
                        self.cleanup.schedule([card],delay=60)
                        await self.say(event,'回复 1～'+str(len(songs))+' 选歌，0取消；选歌后选择PTH和INDEX，30分钟内有效。')
                    except Exception as exc:
                        card.unlink(missing_ok=True)
                        self.logger.warning('[翻唱] 选歌图片发送失败，改发文字清单：%s',type(exc).__name__)
                        await self.say(event,listing+'\n直接回复歌曲编号，例如 1；回复0取消。')
                return
            claim(key,'cover')
            state=self.pending[key]
            if song_select:
                if state['stage']!='song':raise ValueError('歌曲已选好，请按清单选择 PTH 模型。')
                index=int(song_select.group(1))-1
                if not 0<=index<len(state['songs']):raise ValueError('歌曲编号超出清单范围。')
                await self.choose_model(event,state['songs'][index]);return
            if state['stage']=='voice':
                if not voice_select:raise ValueError('请先选择PTH模型。')
                voice=select_voice(voice_select.group(1),state['voices'])
                await self.choose_index(event,voice);return
            if state['stage']!='index' or not index_select:raise ValueError('请按当前清单选择INDEX文件。')
            index_text=index_select.group(1).strip()
            choices=state['indexes']
            if index_text.isdigit() and 1<=int(index_text)<=len(choices):chosen=choices[int(index_text)-1]
            else:
                matching=[entry for entry in choices if entry['name']==index_text]
                if len(matching)!=1:raise ValueError('INDEX编号或文件名不在配套索引清单内。')
                chosen=matching[0]
            voice=dict(state['voice'],index=chosen['path'])
            song=state['song']
            if POLITICS.search(song['name']+' '+song['artist']+' '+voice['name']):await self.say(event,'我拒绝。');return
            async with self.lock:
                self.pending.pop(key,None);clear(key,'cover');self.save_pending()
                source=None;result=None
                self.running[key]={'started':time.monotonic(),'stage':'获取完整歌曲'}
                heartbeat=asyncio.create_task(self.heartbeat(event,key))
                async def progress(text):
                    self.running[key]['stage']=text
                    await self.say(event,text)
                cover_reserved=False
                try:
                    await compute_gate.begin_cover()
                    cover_reserved=True
                    await self.say(event,'已选择 '+voice['filename']+' + '+chosen['name']+'，正在获取完整歌曲，从网页取得原曲后，按模型忙闲、显卡占用和显存自动选择GPU或CPU，分离人声并换声。')
                    source=await asyncio.wait_for(self.music.download(song),timeout=300)
                    result=await asyncio.wait_for(self.pipeline.make(source,voice,progress),timeout=1800)
                    self.running[key]["stage"]="发送QQ语音和MP3文件"
                    if await self.send_cover_outputs(event,song,result):
                        self.cleanup.schedule([result],delay=60)
                        self.logger.info('[翻唱] 语音和MP3均已发送：%s / %s / %s',song['name'],song['artist'],voice['filename'])
                finally:
                    if cover_reserved:compute_gate.end_cover()
                    self.running.pop(key,None);heartbeat.cancel();await asyncio.gather(heartbeat,return_exceptions=True)
                    if source:source.unlink(missing_ok=True)
                    # Failed sends keep the generated output for one hour for troubleshooting.
                    if result and result.exists() and not any(str(result.resolve()) in job.get('paths',[]) for job in self.cleanup.jobs.values()):
                        self.cleanup.schedule([result],delay=3600)
        except asyncio.TimeoutError:await self.say(event,"这次翻唱步骤超时，已停止等待。可以重新发起；处理日志已保留。")
        except ValueError as exc:await self.say(event,str(exc))
        except ClientAudioProtected as exc:await self.say(event,str(exc)+' 未开始翻唱。')
        except AudioUnavailable as exc:await self.say(event,str(exc)+' 未开始翻唱，可稍后重试或换版本。')
        except LoginRequired:await self.say(event,'音乐网页登录需要重新授权，请主人重新扫码登录。')
        except PermissionError:await self.say(event,'当前歌曲未返回完整音频，可能涉及该歌曲的播放权限；不能据此判断账号登录已失效。')
        except Exception as exc:
            self.logger.exception('[翻唱] 处理失败：%s',type(exc).__name__)
            await self.say(event,'这次翻唱处理失败，未拿原唱代替。可以重新发起；日志已保留供排查。')

    async def terminate(self):
        self.save_pending()
        await self.cleanup.close()
