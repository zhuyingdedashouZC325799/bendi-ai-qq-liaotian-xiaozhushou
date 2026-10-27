"""Independent factual sources and public-domain original texts, with source provenance."""
import asyncio
import concurrent.futures
import json
import re
import urllib.parse
import urllib.request
from bs4 import BeautifulSoup

CLASSICS={'出师表':'前出師表','前出师表':'前出師表','后出师表':'後出師表','岳阳楼记':'岳陽樓記',
          '滕王阁序':'滕王閣序','陋室铭':'陋室銘','爱莲说':'愛蓮說','桃花源记':'桃花源記',
          '兰亭集序':'蘭亭集序','师说':'師說','醉翁亭记':'醉翁亭記','琵琶行':'琵琶行','长恨歌':'長恨歌','将进酒':'將進酒'}

def get_json(host,params):
    url='https://'+host+'/w/api.php?'+urllib.parse.urlencode(params)
    req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0','Accept-Language':'zh-CN,zh;q=0.9'})
    with urllib.request.urlopen(req,timeout=8) as response:
        raw=response.read(1_000_001)
    if len(raw)>1_000_000:raise ValueError('source too large')
    return json.loads(raw)

def classic_title(text):
    if not re.search(r'背|原文|全文|完整|默写|朗诵|朗读|阅读',text):return None
    # Match the more specific titles first, keeping 后出师表 distinct from 前出师表.
    for name in sorted(CLASSICS,key=len,reverse=True):
        if name in text:return CLASSICS[name]
    return None

def original_text(title):
    if title not in CLASSICS.values():raise ValueError('not an allowlisted public-domain text')
    data=get_json('zh.wikisource.org',{'action':'parse','page':title,'prop':'text','format':'json'})
    parsed=data.get('parse') or {}
    if parsed.get('title')!=title:raise ValueError('source title mismatch')
    soup=BeautifulSoup(parsed.get('text',{}).get('*',''),'html.parser')
    for node in soup.select('small,sup,.reference,.noprint,.ws-noexport,.licenseContainer,.licensetpl,#headerContainer,.mw-editsection'):
        node.decompose()
    body=soup.select_one('.mw-parser-output') or soup
    paragraphs=[]
    for p in body.select(':scope > p'):
        text=p.get_text('',strip=True)
        if not text:continue
        if any(x in text for x in ('公有領域','公有领域','Public domain','著作權','版权')):continue
        paragraphs.append(text)
    text='\n\n'.join(paragraphs)
    if len(text)<50:raise ValueError('source did not contain an original text')
    if title=='前出師表' and ('先帝創業未半' not in text or '今當遠離' not in text):
        raise ValueError('original text incomplete')
    return '《'+title+'》\n\n'+text+'\n\n原文来源：https://zh.wikisource.org/wiki/'+urllib.parse.quote(title)

def clean_query(query):
    query=re.sub(r'背首|背一下|背诵|默写|全文|原文|是什么|介绍一下|帮我查|请问',' ',query)
    return re.sub(r'\s+',' ',query).strip(' 《》“”？?，。')

def wiki_search(query):
    query=clean_query(query)
    if not query:return []
    data=get_json('zh.wikipedia.org',{'action':'query','list':'search','srsearch':query,'srlimit':4,'format':'json'})
    results=[]
    grams={query[i:i+2] for i in range(max(0,len(query)-1)) if not query[i:i+2].isspace()}
    for row in data.get('query',{}).get('search',[]):
        snippet=BeautifulSoup(row.get('snippet',''),'html.parser').get_text(' ',strip=True)
        title=row.get('title','')
        hay=title+' '+snippet
        if query.lower() not in hay.lower() and (not grams or sum(g in hay for g in grams)<max(1,len(grams)//3)):continue
        results.append({'title':title,'url':'https://zh.wikipedia.org/wiki/'+urllib.parse.quote(title),'snippet':snippet,'source':'Wikipedia'})
    return results

async def combine_search(query,legacy):
    direct=re.findall(r'https?://[^\s<>《》]+',query)
    if direct:
        return [{'title':'用户提供的网页','url':url.rstrip('，。！？)'), 'snippet':'读取指定网页，正文是否完整以 content_status 为准。'} for url in direct[:3]]
    async def run(fn):
        try:return await asyncio.wait_for(asyncio.to_thread(fn,query),12)
        except Exception:return []
    groups=await asyncio.gather(run(legacy),run(wiki_search))
    results=[];seen=set()
    for group in groups:
        for row in group:
            if row['url'] in seen:continue
            seen.add(row['url']);results.append(row)
    return results[:6]

def split_text(text,limit=1200):
    # A transport chunk size, never a total answer length cap. Preserve every character.
    chunks=[]
    while len(text)>limit:
        cut=max(text.rfind('\n',0,limit),text.rfind('。',0,limit))
        cut=cut+1 if cut>=limit//2 else limit
        chunks.append(text[:cut]);text=text[cut:]
    if text:chunks.append(text)
    return chunks
