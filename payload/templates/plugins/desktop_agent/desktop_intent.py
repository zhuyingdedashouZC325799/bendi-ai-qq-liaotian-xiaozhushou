"""Route explicit local desktop actions before web search or ordinary chat."""
from portable_settings import remap as _portable_path, owners as _portable_owners, settings as _portable_settings, speaker_policy as _portable_speaker, text as _portable_text, port as _portable_port, cache_for as _portable_cache
import re
LOCATION = '(?:(?:我(?:的)?)?(?:电脑|计算机|桌面)的|(?:(?:我(?:的)?)?(?:电脑|计算机|桌面)(?:里面|里边|上面|上|里|中)|(?:本机|本地)(?:里面|上|里)?)(?:的|那个|这个)?)\\s*'
COURTESY = '(?:(?:本地助手|本地助手|用户|请你|请|麻烦你|麻烦|你能不能|能不能|能否|可以帮我|可以|你|帮我|给我|帮忙|在|我这边|这边)\\s*[,，:：]?\\s*)*'

def command(text):
    text = text.strip()
    match = re.match('^(?:[/／]?(?:电脑|agent|本地agent|控制电脑|电脑控制))(?:\\s+|[:：]\\s*|(?=打开|启动|运行|截图|截屏|软件列表|应用列表|取消|帮助|停止|$))(.*)$', text, re.I | re.S)
    if match:
        tail = match.group(1).strip()
        if tail == text:
            return (tail, True)
        action, explicit = command(tail)
        return (action if explicit else tail, True)
    if re.search('^(?:不要|别|不用|不必)|怎么(?:打开|启动)|如何(?:打开|启动)', text):
        return (text, False)
    base = re.sub('^' + COURTESY, '', text).strip()
    if re.fullmatch('(?:电脑)?(?:截(?:个)?图|截屏|看看电脑|看看屏幕|电脑截图)(?:一下|给我|吧)?[。！!？?]*', base):
        return ('截图', True)
    prefix = COURTESY + '(?:' + LOCATION + ')?'
    tail = '(?:\\s*[,，]?\\s*(?:并|然后|之后|后|再)(?:给我|帮我)?截(?:个)?图)?(?:一下|下|吧|好吗|可以吗|行吗|看看|给我看看)?[。！!？?]*'
    verb = '(?:打开|启动|运行|开一下|开下)'
    patterns = [prefix + verb + '(?:一下|下)?\\s*(.+?)' + tail, prefix + '(?:把|将)(?:' + LOCATION + ')?(.+?)(?:给我|给|帮我)?' + verb + '(?:一下|下)?' + tail]
    for pattern in patterns:
        match = re.fullmatch(pattern, text, re.S)
        if not match:
            continue
        name = re.sub('^(?:' + LOCATION + ')', '', match.group(1).strip())
        name = re.sub('^(?:那个|这个)', '', name)
        name = re.sub('(?:这个|那个)?(?:软件|应用|程序)$', '', name).strip(' ，。！!《》“”"\'')
        if 0 < len(name) <= 80 and (not re.search('https?://|网址|链接|官网|网页', name, re.I)):
            return ('打开 ' + name, True)
    return (text, False)
