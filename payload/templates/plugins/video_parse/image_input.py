"""Convert model-bound images to a decodable JPEG; retain original animated QQ stickers."""
import asyncio,base64,hashlib
from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit,unquote
import urllib.request
from PIL import Image,ImageOps
from .web_reader import public_url,PublicRedirect

LIMIT=24*1024*1024
_CACHE={}
def normalize_ref(ref):
    if not isinstance(ref,str):raise ValueError('图片地址格式无效')
    if ref.startswith('data:'):
        prefix,payload=ref.split(',',1)
        if ';base64' not in prefix:raise ValueError('图片编码无效')
        if len(payload)>LIMIT*4//3+8:raise ValueError('图片过大')
        raw=base64.b64decode(payload,validate=True)
    elif ref.startswith('base64://'):
        if len(ref)>LIMIT*4//3+20:raise ValueError('图片过大')
        raw=base64.b64decode(ref[9:],validate=True)
    elif ref.startswith(('http://','https://')):
        public_url(ref)
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),PublicRedirect())
        with opener.open(urllib.request.Request(ref,headers={'User-Agent':'Mozilla/5.0'}),timeout=15) as response:
            raw=response.read(LIMIT+1)
    else:
        path=unquote(urlsplit(ref).path).lstrip('/') if ref.startswith('file:///') else ref
        with Path(path).open('rb') as stream:raw=stream.read(LIMIT+1)
    if len(raw)>LIMIT:raise ValueError('图片过大')
    digest=hashlib.sha256(raw).hexdigest()
    if digest in _CACHE:return _CACHE[digest]
    with Image.open(BytesIO(raw)) as image:
        if image.width*image.height>30_000_000:raise ValueError('图片像素过大')
        image.seek(0)
        rgba=ImageOps.exif_transpose(image.copy()).convert('RGBA')
        background=Image.new('RGBA',rgba.size,'white');background.alpha_composite(rgba)
        result=background.convert('RGB');result.thumbnail((1024,1024),Image.Resampling.LANCZOS)
        output=BytesIO();result.save(output,format='JPEG',quality=90)
    value='data:image/jpeg;base64,'+base64.b64encode(output.getvalue()).decode()
    _CACHE[digest]=value
    if len(_CACHE)>16:_CACHE.pop(next(iter(_CACHE)))
    return value

async def normalize_request_images(req):
    req.image_urls=[await asyncio.to_thread(normalize_ref,ref) for ref in (req.image_urls or [])]
    for message in req.contexts or []:
        if not isinstance(message,dict) or not isinstance(message.get('content'),list):continue
        for index,part in enumerate(message['content']):
            if not isinstance(part,dict) or part.get('type')!='image_url':continue
            image=part.get('image_url') or {}
            try:image['url']=await asyncio.to_thread(normalize_ref,image.get('url',''))
            except Exception:message['content'][index]={'type':'text','text':'[之前的图片资源已失效]'}
    for part in req.extra_user_content_parts or []:
        if isinstance(part,dict) and part.get('type')=='image_url':
            part['image_url']['url']=await asyncio.to_thread(normalize_ref,part['image_url']['url'])
        elif getattr(part,'image_url',None) is not None:
            part.image_url.url=await asyncio.to_thread(normalize_ref,part.image_url.url)
