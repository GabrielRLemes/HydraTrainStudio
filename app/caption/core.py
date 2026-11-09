"""E621 LoRA Studio: networking, image transform, persistent workspace and captions.
No executable code is downloaded from image providers. Python 3.10+.
"""
from __future__ import annotations

import base64
import io
import json
import os
import re
import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import requests
from PIL import Image, ImageOps

VERSION = '4.2.0'
APP_TITLE = 'E621 LoRA Studio'
API_BASE = 'https://e621.net'
MIN_INTERVAL = 1.15
PAGE_SIZE = 100
STATIC_FORMATS = {'png', 'jpg', 'jpeg', 'webp', 'gif'}
CATEGORIES = ('artist', 'copyright', 'character', 'species', 'general', 'lore', 'meta', 'contributor', 'invalid')

DEFAULT_PROMPT = '''You write accurate English captions for a Krea 2 RAW artistic-style LoRA dataset.
Use the supplied image metadata as structured clues, but verify everything against the image and correct mismatches.
Write one natural caption in English, normally 45–110 words, focused on visible content rather than art-quality praise.
Always mention the main subject(s), confirmed identities, species, apparent body type, clothing or nudity, pose, expression, camera framing, composition, and background.
When the image is NSFW or sexual, be explicit and concrete instead of vague: describe visible explicit anatomy, sexual actions, interaction type, participant count, positioning, contact, fluids, toys, and exposure level whenever they are clearly visible or strongly supported by the metadata.
Do not invent details. Do not mention artist names, website names, quality tags, technical tags, or explanations about brushwork, lineart, rendering quality, or style analysis.
Output caption text only, no bullet points or labels. Start with the exact trigger token {trigger}, followed by a comma and a space.'''


def normalize_positive(value: str) -> list[str]:
    """Space or comma separated single tags; e621's literal AND search."""
    result = []
    for raw in re.split(r'[\s,;]+', value.strip()):
        raw = raw.strip().lower().replace(' ', '_')
        if not raw:
            continue
        if not re.fullmatch(r"[a-z0-9_()'.+!\-]+", raw) or raw.startswith('-'):
            raise ValueError(f'Tag de inclusão inválida: {raw!r}. Use nomes simples de tags.')
        if raw not in result:
            result.append(raw)
    if not result:
        raise ValueError('Informe pelo menos uma tag de inclusão.')
    return result


def normalize_excluded(value: str) -> list[str]:
    """Comma or newline separates tags; `blue hair` -> `blue_hair`."""
    result = []
    for part in re.split(r'[,;\n]+', value):
        raw = re.sub(r'\s+', '_', part.strip().lower().lstrip('-'))
        if not raw:
            continue
        if not re.fullmatch(r"[a-z0-9_()'.+!\-]+", raw):
            raise ValueError(f'Tag de exclusão inválida: {raw!r}')
        if raw not in result:
            result.append(raw)
    return result


def compose_query(positive: str, excluded: str, min_score: int) -> str:
    incl = normalize_positive(positive)
    excl = normalize_excluded(excluded)
    intersect = set(incl) & set(excl)
    if intersect:
        raise ValueError(f'Tag exigida e excluída ao mesmo tempo: {", ".join(sorted(intersect))}')
    if min_score < 0:
        raise ValueError('Pontuação mínima não pode ser negativa.')
    terms = incl + ['-' + x for x in excl]
    if min_score:
        terms.append(f'score:>={min_score}')
    if len(terms) > 6:
        # e621 enforces tag limits depending on account level; warn in GUI.
        raise ValueError('A busca ultrapassa 6 termos. Reduza as tags/filtros ou use uma conta com limite maior.')
    return ' '.join(terms)


def all_tags(post: dict) -> list[str]:
    tags = post.get('tags') or {}
    if not isinstance(tags, dict):
        return []
    seen, result = set(), []
    for category in list(CATEGORIES) + [x for x in tags if x not in CATEGORIES]:
        for tag in tags.get(category, []):
            if isinstance(tag, str) and tag not in seen:
                seen.add(tag)
                result.append(tag)
    return result


def tag_caption(tags: list[str]) -> str:
    return ', '.join(t.replace('_', ' ') for t in tags)


# ---------- Caption v4 helpers ----------

NSFW_HINT_TAGS = {
    'nude', 'naked', 'nipples', 'breasts', 'big_breasts', 'small_breasts', 'areola', 'navel', 'penis', 'balls',
    'vagina', 'vulva', 'pussy', 'clitoris', 'ass', 'anus', 'butt', 'buttocks', 'spread_legs', 'cameltoe',
    'underwear', 'panties', 'bra', 'lingerie', 'thong', 'topless', 'bottomless', 'partially_clothed',
    'fully_nude', 'completely_nude', 'erection', 'sex', 'cum', 'cumshot', 'cum_in_pussy', 'cum_in_ass',
    'cum_on_body', 'cum_on_face', 'cumdrip', 'fellatio', 'cunnilingus', 'oral', 'deepthroat', 'anal',
    'vaginal_penetration', 'anal_penetration', 'double_penetration', 'fingering', 'handjob', 'footjob',
    'scissoring', 'tribadism', 'masturbation', 'dildo', 'vibrator', 'sex_toy', 'gag', 'bondage', 'bdsm',
    'rape', 'forced', 'presenting', 'spread_pussy', 'spreading', 'penetration', 'genital_focus', 'breast_focus',
    'pov', 'sex_from_behind', 'missionary_position', 'doggystyle', 'cowgirl_position', 'reverse_cowgirl_position',
}

ANATOMY_HINTS = {
    'breasts', 'big_breasts', 'small_breasts', 'flat_chest', 'wide_hips', 'thick_thighs', 'slim', 'muscular',
    'curvy', 'hourglass_figure', 'waist', 'abs', 'penis', 'balls', 'vagina', 'vulva', 'pussy', 'anus', 'tail',
    'wings', 'horns', 'claws', 'fangs', 'anthro', 'feral', 'humanoid', 'genitals', 'nipples', 'navel'
}
CLOTHING_HINTS = {
    'dress', 'skirt', 'shirt', 'jacket', 'hoodie', 'coat', 'cape', 'gloves', 'stockings', 'pantyhose', 'socks',
    'boots', 'shoes', 'heels', 'sandals', 'hat', 'cap', 'scarf', 'armor', 'uniform', 'bikini', 'swimsuit',
    'underwear', 'lingerie', 'bra', 'panties', 'thong', 'leotard', 'bodysuit', 'apron', 'kimono', 'robe'
}
POSE_HINTS = {
    'solo', 'duo', 'group', 'looking_at_viewer', 'looking_back', 'standing', 'sitting', 'kneeling', 'lying',
    'crouching', 'sprawled', 'bent_over', 'from_behind', 'from_above', 'from_below', 'close-up', 'upper_body',
    'full_body', 'portrait', 'selfie', 'pov', 'spread_legs', 'legs_up', 'presenting', 'facing_viewer', 'profile'
}
BACKGROUND_HINTS = {
    'indoors', 'outdoors', 'bedroom', 'bed', 'bathroom', 'shower', 'forest', 'park', 'beach', 'ocean', 'street',
    'city', 'room', 'sofa', 'couch', 'window', 'night', 'day', 'sunset', 'sky', 'grass', 'water', 'table'
}
META_SKIP = {'hi_res', 'highres', 'absurd_res', 'signature', 'watermark', 'tagme', 'source_request', 'translation_request'}


def _pretty_tags(values: list[str], limit: int | None = None) -> str:
    seen, out = set(), []
    for tag in values:
        if not isinstance(tag, str):
            continue
        tag = tag.strip()
        if not tag or tag in seen:
            continue
        seen.add(tag)
        out.append(tag.replace('_', ' '))
        if limit and len(out) >= limit:
            break
    return ', '.join(out)


def infer_nsfw(tags: list[str], rating: str = '') -> bool:
    if (rating or '').lower() in {'q', 'e'}:
        return True
    stags = {str(t).lower() for t in tags}
    return any(t in NSFW_HINT_TAGS for t in stags)


def split_general_tags(tags: list[str]) -> dict[str, list[str]]:
    buckets = {
        'anatomy': [], 'clothing': [], 'pose_action': [], 'nsfw': [], 'background': [], 'other': []
    }
    for raw in tags:
        t = str(raw).lower().strip()
        if not t or t in META_SKIP:
            continue
        if t in NSFW_HINT_TAGS:
            buckets['nsfw'].append(t)
        elif t in ANATOMY_HINTS or 'breast' in t or 'thigh' in t or 'hip' in t or 'nipple' in t:
            buckets['anatomy'].append(t)
        elif t in CLOTHING_HINTS:
            buckets['clothing'].append(t)
        elif t in POSE_HINTS or 'pose' in t or 'looking' in t:
            buckets['pose_action'].append(t)
        elif t in BACKGROUND_HINTS:
            buckets['background'].append(t)
        else:
            buckets['other'].append(t)
    return buckets


def normalize_tag_groups(tag_groups: dict | None) -> dict[str, list[str]]:
    base = {k: [] for k in ('artist', 'copyright', 'character', 'species', 'general', 'lore', 'meta', 'contributor', 'invalid')}
    if isinstance(tag_groups, dict):
        for k, vals in tag_groups.items():
            if isinstance(vals, list):
                base[k] = [str(v) for v in vals if isinstance(v, str)]
    return base


def build_structured_metadata(tags: list[str], rating: str = '', tag_groups: dict | None = None) -> str:
    groups = normalize_tag_groups(tag_groups)
    if not any(groups.values()):
        groups['general'] = [str(t) for t in tags if isinstance(t, str)]
    general_split = split_general_tags(groups.get('general', []) or [])
    nsfw = infer_nsfw(tags, rating)
    lines = []
    rating_label = {'s': 'safe', 'q': 'questionable', 'e': 'explicit'}.get((rating or '').lower(), rating or 'unknown')
    lines.append(f'Rating: {rating_label}.')
    if groups['character']:
        lines.append('Character identities: ' + _pretty_tags(groups['character'], 18) + '.')
    if groups['species']:
        lines.append('Species or creature types: ' + _pretty_tags(groups['species'], 18) + '.')
    if groups['copyright']:
        lines.append('Series or franchise context: ' + _pretty_tags(groups['copyright'], 12) + '.')
    if general_split['anatomy']:
        lines.append('Visible body/anatomy clues: ' + _pretty_tags(general_split['anatomy'], 22) + '.')
    if general_split['clothing']:
        lines.append('Clothing or accessories: ' + _pretty_tags(general_split['clothing'], 22) + '.')
    if general_split['pose_action']:
        lines.append('Pose, action, framing or gaze: ' + _pretty_tags(general_split['pose_action'], 26) + '.')
    if general_split['background']:
        lines.append('Background or setting clues: ' + _pretty_tags(general_split['background'], 20) + '.')
    if nsfw:
        nsfw_tags = list(general_split['nsfw'])
        extras = [t for t in general_split['other'] if any(k in t for k in ('sex', 'cum', 'nude', 'undress', 'arousal', 'genital', 'penetr', 'oral', 'anal', 'kiss', 'lick', 'moan', 'spread', 'pussy', 'penis', 'breast', 'ass'))]
        for t in extras:
            if t not in nsfw_tags:
                nsfw_tags.append(t)
        if nsfw_tags:
            lines.append('NSFW or sexual-content clues: ' + _pretty_tags(nsfw_tags, 32) + '.')
        lines.append('Instruction: if the scene is sexual or explicit, describe the explicit content clearly and concretely, including visible anatomy, participant count, interaction type, exposure, positioning, penetration/oral/manual contact, toys, and fluids when supported by the image or metadata.')
    leftovers = [t for t in general_split['other'] if t not in general_split['nsfw']]
    if leftovers:
        lines.append('Other relevant tags: ' + _pretty_tags(leftovers, 30) + '.')
    return '\n'.join(lines)


def valid_media_url(url: str) -> bool:
    try:
        p = urlparse(url)
        return p.scheme == 'https' and p.hostname is not None and (
            p.hostname == 'e621.net' or p.hostname.endswith('.e621.net')
        ) and not p.username and not p.password
    except ValueError:
        return False


def post_media(post: dict, include_gif: bool = False) -> tuple[str, str] | None:
    f = post.get('file') or {}
    ext = str(f.get('ext') or '').lower()
    if ext not in STATIC_FORMATS or (ext == 'gif' and not include_gif):
        return None
    if f.get('url') and valid_media_url(f['url']):
        return f['url'], ext
    # Some posts have no original URL, and samples may be JPEG/PNG.
    sample = post.get('sample') or {}
    sample_url = sample.get('url')
    if sample_url and valid_media_url(sample_url):
        suffix = Path(urlparse(sample_url).path).suffix.lstrip('.').lower()
        if suffix in STATIC_FORMATS:
            return sample_url, suffix
    return None


def atomic_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    with temp.open('w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(temp, path)


def atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(value.rstrip() + '\n', encoding='utf-8')
    os.replace(temp, path)


class Workspace:
    """Temporary originals and curation metadata (API keys intentionally never persisted)."""
    def __init__(self, root: Path):
        self.root = root.expanduser().resolve()
        self.raw = self.root / 'originais'
        self.raw.mkdir(parents=True, exist_ok=True)
        self.path = self.root / 'projeto.json'
        self.items: dict[str, dict] = {}
        self.cursors: dict[str, int] = {}
        self.completed: list[str] = []
        self.load()

    def load(self):
        if self.path.exists():
            data = json.loads(self.path.read_text(encoding='utf-8'))
            self.items = data.get('items', {})
            self.cursors = data.get('cursors', {})
            self.completed = data.get('completed', [])

    def save(self):
        atomic_json(self.path, {
            'version': VERSION,
            'items': self.items,
            'cursors': self.cursors,
            'completed': self.completed,
        })

    def image_path(self, item: dict) -> Path:
        return self.raw / item['filename']


    def reset(self, delete_originals: bool = True, delete_caption_settings: bool = False,
              delete_caption_backups: bool = True) -> None:
        """Clear tracked progress so the user can start a new dataset from scratch."""
        self.items = {}
        self.cursors = {}
        self.completed = []

        # Remove saved project state.
        self.path.unlink(missing_ok=True)

        if delete_originals and self.raw.exists():
            shutil.rmtree(self.raw, ignore_errors=True)
        self.raw.mkdir(parents=True, exist_ok=True)

        if delete_caption_backups:
            shutil.rmtree(self.root / 'backups_legendas', ignore_errors=True)

        if delete_caption_settings:
            (self.root / 'config_legendas.json').unlink(missing_ok=True)

        self.save()

    def insert(self, post: dict, filename: str, query: str) -> dict:
        pid = str(int(post['id']))
        entry = {
            'id': int(pid),
            'filename': filename,
            'query': query,
            'tags': all_tags(post),
            'tag_groups': {k: list(v) for k, v in (post.get('tags') or {}).items() if isinstance(v, list)},
            'sdxl': tag_caption(all_tags(post)),
            'krea': '',
            'caption_error': '',
            'caption_profile': '',
            'score': (post.get('score') or {}).get('total', 0),
            'rating': post.get('rating', ''),
            'status': 'pendente',
            'crop': {'cx': 0.5, 'cy': 0.5, 'scale': 1.0},
        }
        self.items[pid] = entry
        self.save()
        return entry


class Cancelled(Exception):
    pass


class E621Client:
    def __init__(self, username: str, api_key: str, stop: threading.Event | None = None):
        if not username.strip():
            raise ValueError('Informe seu usuário do e621 para identificar as requisições.')
        self.stop = stop or threading.Event()
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': f'E621LoRAStudio/{VERSION} (by {username.strip()} on e621)',
            'Accept': 'application/json',
        })
        self.auth = (username.strip(), api_key) if api_key else None
        self.last_request = 0.0

    def wait(self, secs):
        if self.stop.wait(max(0, secs)):
            raise Cancelled()

    def get(self, url: str, *, params=None, api=True, stream=False):
        for attempt in range(5):
            self.wait(MIN_INTERVAL - (time.monotonic() - self.last_request))
            self.last_request = time.monotonic()
            try:
                result = self.session.get(url, params=params, timeout=(15, 65),
                                          stream=stream, auth=self.auth if api else None)
                if result.status_code in (429, 500, 502, 503, 504) and attempt < 4:
                    delay = result.headers.get('Retry-After')
                    result.close()
                    try:
                        seconds = min(120, max(2, float(delay)))
                    except (ValueError, TypeError):
                        seconds = min(60, 3 * 2**attempt)
                    self.wait(seconds)
                    continue
                result.raise_for_status()
                return result
            except (requests.Timeout, requests.ConnectionError) as exc:
                if attempt == 4:
                    raise RuntimeError(f'Falha de conexão com o e621: {exc}') from exc
                self.wait(min(60, 3 * 2**attempt))
            except requests.HTTPError as exc:
                raise RuntimeError(f'HTTP {exc.response.status_code}: {exc.response.text[:220]}') from exc
        raise RuntimeError('Falha de rede.')

    def count(self, query: str) -> int:
        with self.get(f'{API_BASE}/posts/count.json', params={'tags': query}) as response:
            data = response.json()
        for candidate in (data.get('counts'), data):
            if isinstance(candidate, dict):
                for name in ('posts', 'count'):
                    if name in candidate and isinstance(candidate[name], (int, float)):
                        return int(candidate[name])
        raise RuntimeError(f'Formato inesperado de contagem: {str(data)[:250]}')

    def posts(self, query: str, cursor: int | None = None) -> list[dict]:
        params = {'tags': query, 'limit': PAGE_SIZE}
        if cursor is not None:
            params['page'] = f'b{cursor}'
        with self.get(f'{API_BASE}/posts.json', params=params) as response:
            data = response.json()
        if not isinstance(data, dict) or not isinstance(data.get('posts'), list):
            raise RuntimeError('Resposta de posts inesperada.')
        return data['posts']

    def download(self, url: str, dest: Path) -> None:
        if not valid_media_url(url):
            raise ValueError('URL da imagem não pertence aos servidores do e621.')
        temp = dest.with_suffix(dest.suffix + '.part')
        try:
            with self.get(url, api=False, stream=True) as response, temp.open('wb') as writer:
                size = 0
                for chunk in response.iter_content(chunk_size=256 * 1024):
                    if self.stop.is_set():
                        raise Cancelled()
                    if chunk:
                        size += len(chunk)
                        writer.write(chunk)
                if size == 0:
                    raise ValueError('Arquivo de imagem vazio.')
            # Verify image payload, not an HTML error page or decompression bomb.
            with Image.open(temp) as im:
                im.verify()
            os.replace(temp, dest)
        finally:
            if temp.exists():
                temp.unlink()


def opaque_rgb(image: Image.Image) -> Image.Image:
    """Flatten transparency on neutral gray, not undefined RGB in clear pixels."""
    image = image.copy()
    if image.mode in ('RGBA', 'LA') or (image.mode == 'P' and 'transparency' in image.info):
        foreground = image.convert('RGBA')
        background = Image.new('RGBA', image.size, (128, 128, 128, 255))
        return Image.alpha_composite(background, foreground).convert('RGB')
    return image.convert('RGB')


def input_jpeg_bytes(image_path: Path, max_side: int = 1152) -> str:
    """Convert to a small JPEG for multimodal APIs; original untouched."""
    with Image.open(image_path) as source:
        if getattr(source, 'is_animated', False):
            source.seek(0)
        img = opaque_rgb(ImageOps.exif_transpose(source))
        img.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, 'JPEG', quality=88, optimize=True)
    return base64.b64encode(buf.getvalue()).decode('ascii')


@dataclass
class AIConfig:
    provider: str
    model: str
    key: str
    prompt: str
    trigger: str
    ollama_url: str = 'http://127.0.0.1:11434'
    llama_url: str = 'http://127.0.0.1:8080'
    max_tokens: int = 550
    thinking: bool = False



def llama_server_base(url: str) -> str:
    """Allow localhost base URL or a complete llama.cpp OpenAI-compatible API URL."""
    from urllib.parse import urlsplit, urlunsplit
    raw = url.strip().rstrip('/')
    if not raw:
        raise ValueError('Informe o endereço do servidor llama.cpp, como http://127.0.0.1:8080')
    p = urlsplit(raw)
    if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password or p.query or p.fragment:
        raise ValueError('Endereço llama.cpp inválido. Use http://127.0.0.1:8080')
    try:
        _ = p.port
    except ValueError as exc:
        raise ValueError('Porta do llama.cpp inválida.') from exc
    path = p.path.rstrip('/')
    for suffix in ('/v1/chat/completions', '/v1/models', '/v1/health', '/health', '/v1'):
        if path.endswith(suffix):
            path = path[:-len(suffix)].rstrip('/')
            break
    return urlunsplit((p.scheme, p.netloc, path, '', ''))


def llama_multimodal_payload(model: str, prompt: str, b64: str,
                             *, max_tokens: int = 400, thinking: bool = False) -> dict:
    """OpenAI chat format supported by llama-server running Qwen3-VL with --mmproj."""
    payload = {
        'model': model.strip(),
        'messages': [{'role': 'user', 'content': [
            {'type': 'text', 'text': prompt},
            {'type': 'image_url', 'image_url': {'url': 'data:image/jpeg;base64,' + b64}},
        ]}],
        'stream': False,
        'temperature': 0.2,
        'max_tokens': max_tokens,
    }
    if thinking:
        payload.update(chat_template_kwargs={"enable_thinking":True},reasoning_format="deepseek",
                       max_tokens=max_tokens+768)
    return payload


def llama_chat(base_url: str, payload: dict, *, timeout: int = 360) -> str:
    try:
        response = requests.post(llama_server_base(base_url) + '/v1/chat/completions',
                                 json=payload, timeout=(10, timeout))
        response.raise_for_status()
        obj = response.json()
        choices = obj.get('choices') or []
        if not choices:
            raise ValueError('O llama.cpp não retornou choices. Confira o console do servidor.')
        msg = choices[0].get('message') or {}
        text = msg.get('content', '')
        if isinstance(text, list):
            text = ' '.join(p.get('text', '') for p in text if isinstance(p, dict))
        text = str(text or '').strip()
        if payload.get("chat_template_kwargs",{}).get("enable_thinking"):
            parsed=re.search(r"<think>.*?</think>",text,flags=re.S|re.I)
            if not parsed and not str(msg.get("reasoning_content") or msg.get("reasoning") or "").strip():
                raise ValueError("O servidor não retornou raciocínio separado. Confira o modelo Think ou desative a opção em IA e prompts.")
            text=re.sub(r"<think>.*?</think>","",text,flags=re.S|re.I).strip()
            if "<think>" in text.lower() or choices[0].get("finish_reason")=="length":
                raise ValueError("Resposta Think incompleta. A legenda anterior foi preservada.")
        if not text:
            finish = choices[0].get('finish_reason', '')
            reason = ' (a resposta consumiu tokens apenas no raciocínio)' if msg.get('reasoning_content') else ''
            raise ValueError(f'O llama.cpp retornou resposta final vazia (finish_reason={finish}){reason}. '
                             'Tente aumentar max_tokens, reduzir o prompt ou desativar thinking no modelo.')
        return text
    except requests.ConnectionError as exc:
        raise RuntimeError('Não foi possível conectar ao llama.cpp. Abra o .bat do Qwen3-VL, '
                           'aguarde "listening on http://127.0.0.1:8080" e tente novamente.') from exc
    except requests.Timeout as exc:
        raise RuntimeError('O llama.cpp demorou demais para responder; confira o console e o uso de VRAM.') from exc
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else '?'
        body = exc.response.text[:450] if exc.response is not None else ''
        raise RuntimeError(f'Erro HTTP {status} no llama.cpp: {body}') from exc
    except (ValueError, requests.exceptions.JSONDecodeError) as exc:
        raise RuntimeError(f'Resposta inválida do llama.cpp: {exc}') from exc


def test_llama_vision(cfg: AIConfig) -> str:
    """Health check + synthetic image inference; avoids uploading user images in a test."""
    base = llama_server_base(cfg.llama_url)
    if not cfg.model.strip():
        raise ValueError('Informe o alias do modelo configurado no .bat.')
    try:
        health = requests.get(base + '/health', timeout=(5, 15))
        if health.status_code != 200:
            raise RuntimeError(f'O servidor está carregando ou indisponível (HTTP {health.status_code}).')
        health.raise_for_status()
        models_response = requests.get(base + '/v1/models', timeout=(5, 15))
        models_response.raise_for_status()
        model_list = (models_response.json().get('data') or [])
    except requests.ConnectionError as exc:
        raise RuntimeError('Servidor llama.cpp offline. Inicie primeiro o .bat do Qwen3-VL na porta 8080.') from exc
    except requests.Timeout as exc:
        raise RuntimeError('Tempo esgotado consultando o llama.cpp.') from exc
    except requests.HTTPError as exc:
        raise RuntimeError(f'Erro HTTP ao verificar llama.cpp: {exc}') from exc

    available = [str(x.get('id', '')) for x in model_list if isinstance(x, dict)]
    if available and cfg.model.strip() not in available:
        raise ValueError(f'Alias configurado: {cfg.model}. Modelos que o servidor informa: {", ".join(available)}. '
                         'Ajuste o campo Modelo para corresponder ao --alias do .bat.')
    chosen = next((x for x in model_list if x.get('id') == cfg.model.strip()), {})
    modalities = (chosen.get('architecture') or {}).get('input_modalities') if isinstance(chosen, dict) else None
    if isinstance(modalities, list) and 'image' not in modalities:
        raise ValueError('O modelo carregado não anuncia capacidade de receber imagens. '
                         'Verifique o --mmproj no .bat.')

    # Two strong colors, visually distinct. A textual reply alone doesn't prove
    # accuracy; the answer is surfaced for manual inspection.
    with io.BytesIO() as buf:
        with Image.new('RGB', (224, 224), (238, 23, 35)) as sample:
            sample.save(buf, format='JPEG', quality=92)
        b64 = base64.b64encode(buf.getvalue()).decode('ascii')
    reply = llama_chat(base, llama_multimodal_payload(
        cfg.model, 'Look at the attached image. What is its main color? Respond with one English color word.',
        b64, max_tokens=80, thinking=cfg.thinking), timeout=180)
    return (f'Servidor online: {base}\n'
            f'Modelo informado: {cfg.model}\n'
            f'Projetor multimodal: {"anunciado" if isinstance(modalities, list) else "não informado pela API"}\n'
            f'Imagem de teste: quadrado VERMELHO\n'
            f'Resposta da IA: {reply[:260]}\n\n'
            'O teste de visão foi concluído. Confira se o modelo reconheceu a cor vermelha.')


def describe_image(image_path: Path, tags: list[str], cfg: AIConfig,
                   rating: str = '', tag_groups: dict | None = None, *, include_metadata: bool = True) -> str:
    if cfg.provider == 'Nenhuma':
        return ''
    if not cfg.model.strip():
        raise ValueError('Informe o nome do modelo multimodal.')
    trigger = cfg.trigger.strip()
    prompt = cfg.prompt.replace('{trigger}', trigger)
    if include_metadata:
        structured = build_structured_metadata(tags, rating, tag_groups)
        prompt += '\n\nStructured image metadata (verify against the image and resolve contradictions):\n' + structured
        if tag_groups and isinstance(tag_groups, dict):
            raw_general = tag_groups.get('general') or []
            if raw_general:
                prompt += '\n\nRaw general tags: ' + ', '.join(map(str, raw_general[:180]))
        else:
            prompt += '\n\nRaw tags: ' + ', '.join(tags[:220])
    b64 = input_jpeg_bytes(image_path)
    if cfg.provider == 'llama.cpp (local)':
        payload=llama_multimodal_payload(cfg.model,prompt,b64,max_tokens=cfg.max_tokens,thinking=cfg.thinking)
        text=llama_chat(cfg.llama_url,payload)
    elif cfg.provider == 'Ollama (local)':
        url = cfg.ollama_url.rstrip('/') + '/api/chat'
        response = requests.post(url, json={
            'model': cfg.model.strip(),
            'messages': [{'role': 'user', 'content': prompt, 'images': [b64]}],
            'stream': False,
            'options': {'temperature': 0.2, 'num_predict': cfg.max_tokens},
        }, timeout=(15, 420))
        response.raise_for_status()
        text = (response.json().get('message') or {}).get('content', '')
    elif cfg.provider == 'Google Gemini':
        if not cfg.key:
            raise ValueError('Informe a API key do Google AI Studio.')
        url = ('https://generativelanguage.googleapis.com/v1beta/models/'
               + cfg.model.strip() + ':generateContent')
        response = requests.post(url, headers={'x-goog-api-key': cfg.key}, json={
            'contents': [{'parts': [
                {'text': prompt},
                {'inline_data': {'mime_type': 'image/jpeg', 'data': b64}},
            ]}],
            'generationConfig': {'temperature': 0.2, 'maxOutputTokens': cfg.max_tokens},
        }, timeout=(15, 180))
        response.raise_for_status()
        candidates = response.json().get('candidates') or []
        parts = ((candidates[0].get('content') or {}).get('parts') or []) if candidates else []
        text = ' '.join(x.get('text', '') for x in parts if 'text' in x)
    elif cfg.provider == 'OpenRouter':
        if not cfg.key:
            raise ValueError('Informe a API key do OpenRouter.')
        response = requests.post('https://openrouter.ai/api/v1/chat/completions', headers={
            'Authorization': 'Bearer ' + cfg.key,
            'Content-Type': 'application/json',
            'HTTP-Referer': 'https://localhost/',
            'X-Title': 'E621 LoRA Studio',
        }, json={
            'model': cfg.model.strip(),
            'messages': [{'role': 'user', 'content': [
                {'type': 'text', 'text': prompt},
                {'type': 'image_url', 'image_url': {'url': 'data:image/jpeg;base64,' + b64}},
            ]}],
            'temperature': 0.2,
            'max_tokens': cfg.max_tokens,
        }, timeout=(15, 240))
        response.raise_for_status()
        choices = response.json().get('choices') or []
        text = (choices[0].get('message') or {}).get('content', '') if choices else ''
        if isinstance(text, list):
            text = ' '.join(p.get('text', '') for p in text if isinstance(p, dict))
    else:
        raise ValueError('Provedor de IA desconhecido.')
    text = re.sub(r'\s+', ' ', str(text)).strip().strip('"\'`')
    if not text:
        raise ValueError('O modelo retornou uma descrição vazia ou bloqueada.')
    if trigger and not text.lower().startswith(trigger.lower()):
        text = f'{trigger}, {text}'
    return text


def render_dataset_image(src: Path, target_size: int, crop: dict,
                         fit_mode: str = 'Recortar 1:1', fmt: str = 'PNG') -> Image.Image:
    with Image.open(src) as raw:
        if getattr(raw, 'is_animated', False):
            raw.seek(0)
        img = opaque_rgb(ImageOps.exif_transpose(raw))
    w, h = img.size
    if fit_mode == 'Recortar 1:1':
        scale = max(0.25, min(1.0, float(crop.get('scale', 1.0))))
        side = max(1, round(min(w, h) * scale))
        cx = min(max(float(crop.get('cx', 0.5)) * w, side / 2), w - side / 2)
        cy = min(max(float(crop.get('cy', 0.5)) * h, side / 2), h - side / 2)
        left = max(0, min(w-side, round(cx - side/2)))
        top = max(0, min(h-side, round(cy - side/2)))
        img = img.crop((left, top, left + side, top + side))
        img = img.resize((target_size, target_size), Image.Resampling.LANCZOS)
    elif fit_mode == 'Encaixar sem cortar':
        img.thumbnail((target_size, target_size), Image.Resampling.LANCZOS)
        blank = Image.new('RGB', (target_size, target_size), (128, 128, 128))
        blank.paste(img, ((target_size-img.width)//2, (target_size-img.height)//2))
        img = blank
    elif fit_mode == 'Manter proporção':
        if max(w, h) > target_size:
            img.thumbnail((target_size, target_size), Image.Resampling.LANCZOS)
        # Don't upscale small sources to avoid phantom detail.
    else:
        raise ValueError('Modo de corte inválido.')
    return img


def export_items(items: list[dict], workspace: Workspace, out: Path, mode: str,
                 target_size: int, fit_mode: str, fmt: str, notify, stop: threading.Event):
    out.mkdir(parents=True, exist_ok=True)
    folders = (['SDXL', 'Krea2'] if mode == 'Ambos' else [mode])
    total = 0
    failures = []
    for i, item in enumerate(items, 1):
        if stop.is_set():
            raise Cancelled()
        src = workspace.image_path(item)
        if not src.is_file():
            failures.append(f"#{item['id']}: original ausente")
            continue
        try:
            rendered = render_dataset_image(src, target_size, item.get('crop', {}), fit_mode, fmt)
            basename = f"e621_{item['id']}"
            suffix = '.png' if fmt == 'PNG' else '.jpg'
            for folder in folders:
                destination = out / folder
                destination.mkdir(parents=True, exist_ok=True)
                image_file = destination / (basename + suffix)
                temp_file = destination / (basename + '.processing' + suffix)
                try:
                    if fmt == 'PNG':
                        rendered.save(temp_file, format='PNG', optimize=True)
                    else:
                        rendered.save(temp_file, format='JPEG', quality=95, subsampling=0)
                    os.replace(temp_file, image_file)
                    caption = item['sdxl'] if folder == 'SDXL' else item['krea']
                    atomic_text(destination / (basename + '.txt'), caption)
                finally:
                    if temp_file.exists():
                        temp_file.unlink()
            rendered.close()
            total += 1
        except Exception as ex:
            failures.append(f"#{item['id']}: {ex}")
        notify('export_progress', i, len(items), item['id'])
    return total, failures
