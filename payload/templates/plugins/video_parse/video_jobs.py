"""Journal download work across restarts; never replay an uncertain upload."""
import asyncio,hashlib,json,time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from astrbot.api.event import MessageChain
import astrbot.api.message_components as Comp

class VideoJobs:
    def __init__(self,path):
        self.path=Path(path);self.jobs={}
        try:
            data=json.loads(self.path.read_text(encoding='utf-8'))
            if not isinstance(data,dict):data={}
            self.jobs={k:v for k,v in data.items() if isinstance(v,dict) and time.time()-v.get('created',0)<86400}
        except (OSError,ValueError,TypeError):pass
    def save(self):
        temporary=self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.jobs,ensure_ascii=False,indent=2),encoding='utf-8')
        temporary.replace(self.path)
    def key(self,event,url):
        value='|'.join([event.unified_msg_origin,str(event.get_sender_id()),str(event.message_obj.message_id),url])
        return hashlib.sha256(value.encode()).hexdigest()[:24]
    @contextmanager
    def track(self,event,url):
        key=self.key(event,url)
        previous=self.jobs.get(key,{})
        self.jobs[key]={'url':url,'origin':event.unified_msg_origin,'sender':str(event.get_sender_id()),
                        'group':str(event.get_group_id() or ''),'message_id':str(event.message_obj.message_id),
                        'created':previous.get('created',time.time()),'state':'downloading',
                        'orphans':previous.get('orphans',getattr(event,'record',{}).get('orphans',[]))}
        self.save()
        try:yield key
        except asyncio.CancelledError:
            # The download may safely restart; an upload must remain uncertain.
            raise
        except BaseException:
            self.jobs.pop(key,None);self.save();raise
        else:self.jobs.pop(key,None);self.save()
    def uploading(self,key):
        self.jobs[key]['state']='uploading';self.save()
    def recoverable(self):
        return [dict(v) for v in self.jobs.values() if v.get('state')=='downloading']

class RecoveredVideoEvent:
    def __init__(self,context,record):
        self.context=context;self.record=record;self.unified_msg_origin=record['origin']
        self.message_obj=SimpleNamespace(message_id=record['message_id'])
    def get_sender_id(self):return self.record['sender']
    def get_group_id(self):return self.record.get('group','')
    def stop_event(self):pass
    def plain_result(self,text):return MessageChain([Comp.Reply(id=str(self.message_obj.message_id)),Comp.Plain(text)])
    async def send(self,chain):await self.context.send_message(self.unified_msg_origin,chain)
