"""Read-only booru search adapters, unified metadata and throttled HTTP.
No site scraping, no access-control bypass. Python 3.10+.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from urllib.parse import urlsplit, urljoin
import re
import threading
import time

import requests

SOURCES = ('e621', 'Danbooru', 'Gelbooru', 'Derpibooru', 'Rule34.xxx')
SOURCE_DOMAINS = {
    'e621': ('e621.net', 'e926.net'),
    'Danbooru': ('donmai.us',),
    'Gelbooru': ('gelbooru.com',),
    'Derpibooru': ('derpibooru.org', 'trixiebooru.org', 'derpicdn.net'),
    'Rule34.xxx': ('rule34.xxx',),
}
IMAGE_EXTS = {'jpg', 'jpeg', 'png', 'webp', 'gif', 'apng', 'mp4', 'webm', 'mov', 'mkv', 'avi', 'bmp', 'tiff'}


@dataclass
class Post:
    source: str
    post_id: str
    url: str
    page_url: str
    tags: list[str]
    groups: dict[str, list[str]] = field(default_factory=dict)
    md5: str = ''
    score: int | None = None
    rating: str = ''
    artist: str = ''

    metadata: dict = field(default_factory=dict)

    @property
    def media_type(self):
        ext = self.metadata.get("file_ext") or urlsplit(self.url).path.rsplit(".",1)[-1].lower()
        if ext in ("mp4","webm","mov","mkv","avi"):
            return "Vídeos"
        if ext in ("gif","apng") or "animated" in self.tags and ext in ("webp","png"):
            return "GIFs/animações"
        return "Imagens" if ext in IMAGE_EXTS else "A apurar"

    @property
    def key(self) -> str:
        return f'{self.source}:{self.post_id}'


@dataclass
class SearchResult:
    posts: list[Post]
    total: int | None = None
    has_more: bool = False
    skipped: int = 0


def media_url_ok(url: str, source: str) -> bool:
    try:
        p = urlsplit(url)
        if p.scheme != 'https' or p.username or p.password or p.port not in (None, 443):
            return False
        host = (p.hostname or '').lower().rstrip('.')
        return any(host == d or host.endswith('.' + d) for d in SOURCE_DOMAINS[source])
    except (ValueError, KeyError):
        return False


def canonical_tags(tags) -> list[str]:
    if isinstance(tags, str):
        raw = tags.split()
    elif isinstance(tags, (list, tuple)):
        raw = tags
    else:
        raw = []
    found, seen = [], set()
    for t in raw:
        if not isinstance(t, str) or not t.strip():
            continue
        t = t.strip().replace(' ', '_')
        if t not in seen:
            seen.add(t)
            found.append(t)
    return found


def build_query(source: str, positive: str, excluded: str, min_e621_score: int) -> str:
    """Simple cross-site AND query; preserves site-specific syntax only when useful."""
    pos = []
    for t in re.split(r'[,;\s]+', positive.strip()):
        if t:
            if not re.fullmatch(r"[\w()'.+!:\-]+", t):
                raise ValueError(f'Tag inválida: {t}')
            pos.append(t.lstrip('-'))
    if not pos:
        raise ValueError('Informe pelo menos uma tag.')
    neg = [re.sub(r'\s+', '_', t.strip().lower().lstrip('-'))
           for t in re.split('[,;\n]+', excluded) if t.strip()]
    if set(pos) & set(neg):
        raise ValueError('A mesma tag aparece como obrigatória e excluída.')
    if source == 'Derpibooru':
        return ', '.join([t.replace('_', ' ') for t in pos] + ['-' + t.replace('_', ' ') for t in neg])
    terms = pos + ['-' + t for t in neg]
    if source == 'e621' and min_e621_score > 0:
        terms.append(f'score:>={min_e621_score}')
    return ' '.join(terms)


def _valid_md5(s: str) -> str:
    s = str(s or '').lower().strip()
    return s if re.fullmatch('[a-f0-9]{32}', s) else ''


def _score(v):
    if isinstance(v, dict):
        v = v.get('total')
    try:
        return int(v)
    except (ValueError, TypeError):
        return None


def _post(source: str, post_id, url, page_url, tags, groups=None, md5='', rating='', score=None, artist=''):
    tagset = {t.lower() for t in canonical_tags(tags)}
    if tagset.intersection({'cub','loli','shota','lolicon','shotacon','underage','child','young'}) and (
            str(rating).lower() not in ('s','safe','g','general') or
            tagset.intersection({'explicit','questionable','sex','nude','nudity'})):
        return None
    if not isinstance(url, str) or not media_url_ok(url, source):
        return None
    if not urlsplit(url).path.lower().split('.')[-1] in IMAGE_EXTS:
        # Some CDNs use URLs with no filename extension; image verification follows.
        if '.' in urlsplit(url).path.rsplit('/', 1)[-1]:
            return None
    return Post(source, str(post_id), url, page_url, canonical_tags(tags), groups or {},
                _valid_md5(md5), _score(score), str(rating or ''), str(artist or ''))


def add_metadata(p,item):
    fmeta = item.get("file") if isinstance(item.get("file"),dict) else {}
    p.metadata.update(file_ext=fmeta.get("ext") or item.get("file_ext") or item.get("format"),
        mime_type=item.get("mime_type"), file_size=fmeta.get("size") or item.get("file_size") or item.get("size"),
        duration=item.get("duration"), source_urls=item.get("sources") or item.get("source_urls") or item.get("source") or item.get("source_url"),
        preview_url=(item.get("preview") or {}).get("url") if isinstance(item.get("preview"),dict) else item.get("preview_file_url") or item.get("preview_url") or (item.get("representations") or {}).get("thumb"),
        license=item.get("license"), usage_notes=item.get("usage_notes"))


def parse_e621(data: dict) -> SearchResult:
    result = []
    for item in data.get('posts', []):
        f = item.get('file') or {}
        groups = {k: canonical_tags(v) for k,v in (item.get('tags') or {}).items() if isinstance(v, list)}
        url = f.get('url')
        p = _post('e621', item.get('id'), url, f'https://e621.net/posts/{item.get("id")}',
                  [t for vals in groups.values() for t in vals], groups, f.get('md5'),
                  item.get('rating'), item.get('score'), ', '.join(groups.get('artist', [])))
        if p:
            add_metadata(p,item)
            result.append(p)
    return SearchResult(result, None, len(data.get('posts', [])) >= 100, len(data.get('posts', [])) - len(result))


def parse_danbooru(data: list) -> SearchResult:
    result = []
    for item in data if isinstance(data, list) else []:
        groups = {k: canonical_tags(item.get('tag_string_' + k, ''))
                  for k in ('artist', 'character', 'copyright', 'general', 'meta')}
        url = item.get('file_url')
        p = _post('Danbooru', item.get('id'), url, f'https://danbooru.donmai.us/posts/{item.get("id")}',
                  canonical_tags(item.get('tag_string', '')), groups, item.get('md5'),
                  item.get('rating'), item.get('score'), item.get('tag_string_artist', ''))
        if p:
            add_metadata(p,item)
            result.append(p)
    return SearchResult(result, None, len(data) >= 100, len(data) - len(result))


def parse_gelbooru(data) -> SearchResult:
    if isinstance(data, dict):
        arr = data.get('post') or []
        attrs = data.get('@attributes') or {}
        total = _score(attrs.get('count'))
    else:
        arr, total = data if isinstance(data, list) else [], None
    if isinstance(arr, dict):
        arr = [arr]
    result = []
    for item in arr:
        p = _post('Gelbooru', item.get('id'), item.get('file_url'),
                  f'https://gelbooru.com/index.php?page=post&s=view&id={item.get("id")}',
                  item.get('tags', ''), {}, item.get('md5'), item.get('rating'), item.get('score'))
        if p:
            add_metadata(p,item)
            result.append(p)
    return SearchResult(result, total, len(arr) >= 100, len(arr) - len(result))


def parse_rule34(data) -> SearchResult:
    arr = data.get('post') or [] if isinstance(data, dict) else data
    if not isinstance(arr, list):
        arr = [arr] if isinstance(arr, dict) else []
    result = []
    for item in arr:
        p = _post('Rule34.xxx', item.get('id'), item.get('file_url'),
                  f'https://rule34.xxx/index.php?page=post&s=view&id={item.get("id")}',
                  item.get('tags', ''), {}, item.get('md5'), item.get('rating'), item.get('score'))
        if p:
            add_metadata(p,item)
            result.append(p)
    return SearchResult(result, None, len(arr) >= 100, len(arr) - len(result))


def parse_derpibooru(data: dict) -> SearchResult:
    result = []
    for item in data.get('images', []):
        reps = item.get('representations') or {}
        url = item.get('view_url') or reps.get('full')
        tags = canonical_tags(item.get('tags', []))
        artist = ', '.join(t for t in tags if t.lower().startswith('artist:'))
        p = _post('Derpibooru', item.get('id'), url,
                  f'https://derpibooru.org/images/{item.get("id")}', tags,
                  {'artist': canonical_tags([artist]) if artist else [], 'general': tags},
                  '', '', item.get('score'), artist)
        if p:
            add_metadata(p,item)
            result.append(p)
    return SearchResult(result, _score(data.get('total')), len(data.get('images', [])) >= 50, len(data.get('images', [])) - len(result))


class SourceClient:
    def __init__(self, username: str = '', gel_user_id: str = '', gel_key: str = '',
                 rule_user_id: str = '', rule_key: str = '', derpi_key: str = '',
                 stop: threading.Event | None = None):
        self.username = username.strip()
        self.gel_user_id, self.gel_key = gel_user_id.strip(), gel_key.strip()
        self.rule_user_id, self.rule_key = rule_user_id.strip(), rule_key.strip()
        self.derpi_key = derpi_key.strip()
        self.stop = stop or threading.Event()
        self.e621_key="";self.dan_auth=None
        self.session = requests.Session()
        suffix = f' (by {self.username} on e621)' if self.username else ' (local dataset tool)'
        self.session.headers.update({'User-Agent': 'CaptionCreate/1.2' + suffix, 'Accept': 'application/json'})
        self.last_request = {}

    def request(self, url, params=None, stream=False, auth=None):
        host = urlsplit(url).hostname or ''
        for attempt in range(4):
            delay = max(0, 1.35 - (time.monotonic() - self.last_request.get(host, 0)))
            if self.stop.wait(delay):
                raise InterruptedError('Cancelado.')
            self.last_request[host] = time.monotonic()
            try:
                current = url
                for hop in range(5):
                    r = self.session.get(current, params=params if not hop else None, stream=stream,
                                         timeout=(12,65), auth=auth if not hop else None, allow_redirects=False)
                    if not r.is_redirect:
                        break
                    target = urljoin(current,r.headers.get("Location",""))
                    r.close()
                    if not stream or not any(media_url_ok(url,s) and media_url_ok(target,s) for s in SOURCES):
                        raise ValueError("Redirecionamento fora da CDN autorizada.")
                    current = target
                else:
                    raise ValueError("Redirecionamentos excessivos.")
                if r.status_code in (429, 500, 502, 503, 504) and attempt < 3:
                    retry = r.headers.get('Retry-After')
                    r.close()
                    try:
                        n = min(90, max(3, int(retry)))
                    except (ValueError, TypeError):
                        n = 3 * (2 ** attempt)
                    if self.stop.wait(n):
                        raise InterruptedError('Cancelado.')
                    continue
                if r.status_code in (401, 403):
                    r.close()
                    raise PermissionError(f'{host} recusou a conexão ({r.status_code}). Verifique conta, API key, filtros de acesso ou verificação de idade.')
                if r.status_code >= 400:
                    r.close()
                    raise ValueError(f"{host}: HTTP {r.status_code}")
                return r
            except (requests.ConnectionError, requests.Timeout):
                if attempt == 3:
                    raise ConnectionError(f"Falha de conexão com {host}") from None
                if self.stop.wait(2 * (attempt + 1)):
                    raise InterruptedError('Cancelado.')
        raise ConnectionError('Falha na conexão.')

    def search(self, source: str, query: str, page: int = 1) -> SearchResult:
        key = (source, query, page)
        cache = getattr(self, "_pages", {})
        stamp, result = cache.get(key,(0,None))
        if result is not None and time.monotonic()-stamp < 90:
            return result
        result = self._search(source,query,page)
        if len(cache)>=16:cache.pop(next(iter(cache)))
        cache[key]=(time.monotonic(),result)
        self._pages = cache
        return result

    def _search(self, source: str, query: str, page: int = 1) -> SearchResult:
        page = max(1, int(page))
        if source == 'e621':
            auth = (self.username,self.e621_key) if self.e621_key else None
            if not self.username:
                raise ValueError('Para e621, informe seu nome de usuário no campo de identificação.')
            params = {'tags': query, 'limit': 100}
            if page > 1:
                params['page'] = page
            with self.request('https://e621.net/posts.json', params, auth=auth) as r:
                return parse_e621(r.json())
        if source == 'Danbooru':
            with self.request('https://danbooru.donmai.us/posts.json', {'tags': query, 'limit': 100, 'page': page},auth=self.dan_auth) as r:
                return parse_danbooru(r.json())
        if source == 'Gelbooru':
            params = {'page': 'dapi', 's': 'post', 'q': 'index', 'json': 1,
                      'limit': 100, 'pid': page-1, 'tags': query}
            if self.gel_user_id and self.gel_key:
                params.update({'user_id': self.gel_user_id, 'api_key': self.gel_key})
            with self.request('https://gelbooru.com/index.php', params) as r:
                return parse_gelbooru(r.json())
        if source == 'Derpibooru':
            params = {'q': query, 'page': page, 'per_page': 50}
            if self.derpi_key:
                params['key'] = self.derpi_key
            with self.request('https://derpibooru.org/api/v1/json/search/images', params) as r:
                return parse_derpibooru(r.json())
        if source == 'Rule34.xxx':
            params = {'page': 'dapi', 's': 'post', 'q': 'index', 'json': 1,
                      'limit': 100, 'pid': page-1, 'tags': query}
            if self.rule_key and self.rule_user_id:
                params.update({'api_key': self.rule_key, 'user_id': self.rule_user_id})
            with self.request('https://api.rule34.xxx/index.php', params) as r:
                return parse_rule34(r.json())
        raise ValueError('Fonte desconhecida: ' + source)

    def count(self, source: str, query: str) -> int | None:
        if source != 'e621':
            return None
        with self.request('https://e621.net/posts/count.json', {'tags': query},auth=(self.username,self.e621_key) if self.e621_key else None) as response:
            obj = response.json()
        c = obj.get('counts', obj) if isinstance(obj, dict) else {}
        return _score(c.get('posts', c.get('count'))) if isinstance(c, dict) else None
