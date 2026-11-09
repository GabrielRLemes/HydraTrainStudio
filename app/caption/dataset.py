"""Workspace, deduplication, review, and dataset export for Caption Create 1.0."""
from __future__ import annotations
import csv
import hashlib
import json
import os
import re
import shutil
import tempfile
import threading
from pathlib import Path

from PIL import Image, ImageOps

from core import render_dataset_image, atomic_json, opaque_rgb
from sources import Post, canonical_tags, media_url_ok

MAX_BYTES = 90 * 1024 * 1024
from media import dimensions
import psutil
Image.MAX_IMAGE_PIXELS = max(1, psutil.virtual_memory().total // 48)
VALID_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp', '.gif'}


def file_hash(path: Path, algorithm: str = 'sha256') -> str:
    h = hashlib.new(algorithm)
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def image_fingerprint(path: Path) -> tuple[str, str]:
    """Full-pixel checksum + 64-bit dHash to flag near duplicates for review."""
    with Image.open(path) as im:
        if getattr(im, 'is_animated', False):
            im.seek(0)
        dimensions(*im.size)
        im = ImageOps.exif_transpose(im)
        im.load()
        rgb = opaque_rgb(im)
        pixhash = hashlib.sha256()
        pixhash.update(f'{rgb.width}x{rgb.height}'.encode())
        pixhash.update(rgb.tobytes())
        scaled = rgb.convert('L').resize((9, 8), Image.Resampling.LANCZOS)
        px = list(scaled.get_flattened_data()) if hasattr(scaled, 'get_flattened_data') else list(scaled.getdata())
        value = 0
        for row in range(8):
            for col in range(8):
                value = (value << 1) | int(px[row*9+col] > px[row*9+col+1])
    return pixhash.hexdigest(), f'{value:016x}'


def hamming64(a: str, b: str) -> int:
    return (int(a, 16) ^ int(b, 16)).bit_count()


def normalize_id(text: str) -> str:
    return re.sub(r'[^A-Za-z0-9_.-]+', '_', text).strip('_')[:90] or 'image'


from catalog import Catalog

class Dataset(Catalog):
    def __init__(self, folder: Path):
        self.root = Path(folder).expanduser().resolve()
        self.images = self.root / 'originais'
        self.images.mkdir(parents=True, exist_ok=True)
        self.path = self.root / 'projeto.json'
        self.items: dict[str, dict] = {}
        self.counters = {'duplicates': 0, 'imported': 0}
        self.open_catalog()

    def add_post(self, post: Post, client, stop: threading.Event | None = None) -> tuple[str, str]:
        known = self.known(post)
        if known:
            return self.merge(known, post)
        if not media_url_ok(post.url, post.source):
            raise ValueError('URL da imagem não pertence ao domínio esperado.')
        if self.library and post.md5:
            path=self.library.original(post.md5)
            if path:
                return self.receive(path,post.source,post.post_id,post=post,md5=post.md5)
        suffix = '.' + (post.url.split('?',1)[0].rsplit('.',1)[-1].lower())
        if suffix not in VALID_EXTENSIONS:
            suffix = '.png'
        temp = self.root / ('download_' + normalize_id(post.key) + suffix + '.part')
        label=f'{post.source} #{post.post_id}'
        size=0
        transferred=False
        self.progress('download',label,0,None)
        try:
            with client.request(post.url, stream=True) as response, temp.open('wb') as f:
                headers = getattr(response,'headers',{})
                mime = headers.get('Content-Type','').split(';')[0]
                if mime and not (mime.startswith(('image/','video/')) or mime in ('application/octet-stream','binary/octet-stream','application/ogg')):
                    raise ValueError('Tipo HTTP incompatível: '+mime)
                if int(headers.get('Content-Length',0)) > self.settings.max_mb*1024**2:
                    raise ValueError('Tamanho anunciado excede o limite.')
                expected=int(headers.get('Content-Length') or 0) or None
                if headers.get('Content-Encoding'):expected=None
                self.progress('download',label,0,expected)
                for chunk in response.iter_content(chunk_size=262144):
                    if stop and stop.is_set():
                        raise InterruptedError('Cancelado.')
                    if not chunk:
                        continue
                    size += len(chunk)
                    if size > self.settings.max_mb * 1024**2:
                        raise ValueError('Arquivo acima do limite configurado.')
                    f.write(chunk)
                    self.progress('download',label,size,expected)
                if expected and size!=expected:raise ValueError('Download incompleto.')
                transferred=True
                self.progress('download',label,size,expected,True)
            # .part suffix doesn't represent an image, so receive() checks actual content.
            return self.receive(temp, post.source, post.post_id, post.tags, post.groups,
                                post.rating, post.score, post.page_url, post.md5, post.artist, post=post)
        except Exception:
            if not transferred:self.progress('download',label+' · interrompido',size,None)
            raise
        finally:
            temp.unlink(missing_ok=True)

    def reject(self, key, delete_file=False):
        item = self.items[key]
        item['status'] = 'rejeitado'
        if delete_file and item.get('frame_index') is not None:
            self.path_for(item).unlink(missing_ok=True)
        self.save()

    def export(self, output: Path, mode: str, size: int, fit: str, fmt='PNG',
               stop: threading.Event | None = None, callback=None):
        output = Path(output).expanduser().resolve()
        if output == self.root or self.root in output.parents:
            raise ValueError('A exportação precisa ficar fora da pasta de trabalho.')
        if mode not in ('SDXL','Krea2','Ambos') or fmt not in ('JPEG','PNG'):
            raise ValueError('Modo de exportação inválido.')
        if output.exists() and any(output.iterdir()):
            raise ValueError('Escolha uma pasta de exportação vazia.')
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=output.parent,prefix=".caption_export_") as tmp:
            stage = Path(tmp)/"dataset"
            stage.mkdir()
            count,errors = self._write_export(stage,mode,size,fit,fmt,stop,callback)
            if errors or (stop and stop.is_set()):
                return 0,errors or ["Exportação interrompida."]
            if output.exists():output.rmdir()
            stage.rename(output)
            return count,[]

    def _write_export(self, output, mode, size, fit, fmt, stop, callback):
        rows = []
        done, failed = 0, []
        stems=set()
        approved = [(key,it) for key,it in self.items.items() if it.get('status') == 'aprovado' and not it.get('removed')]
        for key, it in approved:
            if stop and stop.is_set():
                break
            src = self.path_for(it)
            if not src.is_file():
                failed.append(f'{key}: original ausente')
                continue
            try:
                out_name = Path(it['filename']).stem + ('.png' if fmt=='PNG' else '.jpg')
                if out_name.casefold() in stems:
                    out_name = Path(out_name).stem+"_"+key+Path(out_name).suffix
                stems.add(out_name.casefold())
                image = render_dataset_image(src, size, it.get('crop', {}), fit, fmt)
                for sub in (['SDXL', 'Krea2'] if mode == 'Ambos' else [mode]):
                    folder = output / sub
                    folder.mkdir(exist_ok=True)
                    temp = folder / (out_name + '.part')
                    final = folder / out_name
                    image.save(temp, format=fmt, **({'quality':94} if fmt=='JPEG' else {}))
                    os.replace(temp, final)
                    caption = (it.get('sdxl', '') if sub=='SDXL' else it.get('krea', ''))
                    cap_path = final.with_suffix('.txt')
                    cap_path.write_text(caption.strip() + '\n', encoding='utf-8')
                rows.append({**it, 'filename':out_name,'export_sha256':file_hash(final),'status':'exported','sha256':it['sha256'],
                             'origins':it['origins'], 'tags':it.get('tags', []), 'caption_profile':it.get('caption_profile', ''),
                             'near_duplicates':it.get('near_duplicates', [])})
                done += 1
                if callback:
                    callback(done, len(approved))
            except Exception as exc:
                failed.append(f'{key}: {exc}')
        atomic_json(output / 'dataset_manifest.json', {'creator':'Caption Create 1.2.1', 'mode':mode,
                    'resolution':size, 'fit':fit, 'images':rows})
        with (output / 'ORIGENS_E_CREDITOS.csv').open('w', encoding='utf-8-sig', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['arquivo', 'site', 'post_id', 'link', 'artista','media_uid','frame_uid','pts_ms','frame_index','sha256_original','sha256_export','tags_origem','tags_frame','caption','perfil','modelo','crop','license','usage_notes','versao'])
            for row in rows:
                for origin in row['origins']:
                    writer.writerow([row['filename'], origin['source'], origin['post_id'],
                                     origin.get('url',''), origin.get('artist',''), row['media_uid'],row['frame_uid'],
                                     row['pts_ms'],row['frame_index'],row['original_sha256'],row['export_sha256'],
                                     ', '.join(origin.get('tags',[])),row.get('sdxl',''),row.get('krea',''),
                                     row.get('caption_profile',''),row.get('caption_model',''),json.dumps(row['crop']),
                                     origin.get('metadata',{}).get('license'),origin.get('metadata',{}).get('usage_notes'),'1.2.1'])
        return done, failed
