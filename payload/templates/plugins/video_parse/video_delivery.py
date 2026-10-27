"""Keep an MP4 deliverable when QQ declines to acknowledge its video bubble."""
import re
from astrbot.api.event import MessageChain
import astrbot.api.message_components as Comp

async def send_video(context,origin,path,title,logger):
    try:
        await context.send_message(origin,MessageChain([Comp.Video.fromFileSystem(str(path))]))
        return 'video'
    except Exception as exc:
        reason=str(exc).lower()
        # Never retry an upload on a timeout: it may still be in flight.
        if 'no message receipt' not in reason and 'delivery was not confirmed' not in reason:
            raise
        logger.warning('[视频解析] QQ未返回视频气泡回执，改发MP4文件，原视频不重发')
        name=re.sub(r'[\x00-\x1f<>:"/\\|?*]','_',title).strip(' .')[:100] or '视频'
        await context.send_message(origin,MessageChain([Comp.File(name=name+'.mp4',file=str(path))]))
        try:
            await context.send_message(origin,MessageChain([Comp.Plain('QQ未确认视频气泡，已改发 MP4 文件；若气泡稍后出现，是同一段视频。')]))
        except Exception:
            logger.warning('[视频解析] MP4文件已确认发送，补充说明发送失败')
        return 'file'
