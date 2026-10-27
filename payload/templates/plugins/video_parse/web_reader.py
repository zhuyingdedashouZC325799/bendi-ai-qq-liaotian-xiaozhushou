"""Read public search result pages with bounded size and explicit completeness status."""
import asyncio
import ipaddress
import socket
import urllib.request
import urllib.parse
from bs4 import BeautifulSoup

UA = 'Mozilla/5.0'

def public_url(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('unsupported URL')
    if parsed.port not in (None, 80, 443):
        raise ValueError('unsupported port')
    addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80), type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ValueError('non-public address')
    return url

class PublicRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)

def extract_html(html, limit=1800):
    soup = BeautifulSoup(html, 'html.parser')
    for element in soup.select('script,style,nav,footer,header,aside,noscript,form,svg'):
        element.decompose()
    body = soup.select_one('article') or soup.select_one('main') or soup.body or soup
    lines = []
    seen = set()
    for line in body.get_text('\n', strip=True).splitlines():
        line = ' '.join(line.split())
        if line and line not in seen:
            seen.add(line)
            lines.append(line)
    text = '\n'.join(lines)
    return {'content': text[:limit], 'content_truncated': len(text) > limit,
            'extracted_chars': len(text), 'content_status': 'partial' if len(text) > limit else 'extracted'}

def read_page(url):
    try:
        public_url(url)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), PublicRedirect())
        request = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept-Language': 'zh-CN,zh;q=0.9'})
        with opener.open(request, timeout=6) as response:
            if 'text/html' not in response.headers.get('Content-Type', '').lower():
                return {'content_status': 'unsupported', 'content': ''}
            raw = response.read(750001)
            charset = response.headers.get_content_charset() or 'utf-8'
        result = extract_html(raw[:750000].decode(charset, 'replace'))
        if len(raw) > 750000:
            result.update(content_truncated=True, content_status='partial')
        if not result['content']:
            result['content_status'] = 'empty'
        return result
    except Exception as exc:
        return {'content_status': 'unavailable', 'content': '', 'fetch_error': type(exc).__name__}

async def enrich_results(results):
    # Three independent pages, fetched concurrently; preserve all search results on timeout.
    async def fetch(item):
        try:
            extra = await asyncio.wait_for(asyncio.to_thread(read_page, item['url']), timeout=8)
        except Exception:
            extra = {'content_status': 'unavailable', 'content': ''}
        return dict(item, **extra)
    enriched = await asyncio.gather(*(fetch(item) for item in results[:3]))
    return enriched + [dict(item, content_status='snippet_only') for item in results[3:]]
