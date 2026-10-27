"""Bounded download of the owner's marked screenshot; never read user-supplied local paths."""
import base64
from io import BytesIO
import ipaddress
import socket
import urllib.request
import urllib.parse
from PIL import Image
from .core import AgentError

LIMIT=10*1024*1024

def check_url(url):
    p=urllib.parse.urlsplit(url)
    if p.scheme not in ('http','https') or not p.hostname or p.username or p.password or p.port not in (None,80,443):
        raise AgentError('图片地址无效，请直接发送圈好的原图。')
    addresses=socket.getaddrinfo(p.hostname,p.port or (443 if p.scheme=='https' else 80),type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(v[4][0]).is_global for v in addresses):
        raise AgentError('图片地址不是公开图片链接，请直接发送图片。')

class Redirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        check_url(newurl)
        return super().redirect_request(req,fp,code,msg,headers,newurl)

def download_marked(url):
    if url.startswith('base64://'):
        if len(url)>LIMIT*4//3+32: raise AgentError('图片太大，请压缩到10MB以内。')
        data=base64.b64decode(url[9:],validate=True)
    else:
        check_url(url)
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),Redirect())
        with opener.open(urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'}),timeout=15) as response:
            data=response.read(LIMIT+1)
    if len(data)>LIMIT: raise AgentError('图片太大，请压缩到10MB以内。')
    image=Image.open(BytesIO(data))
    if image.width*image.height>20_000_000: raise AgentError('图片分辨率过大，请发机器人上一张完整截图。')
    return image.convert('RGB')
