"""Bounded streaming inspection and candidate selection using FFmpeg (PyAV) and Pillow."""
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import av
import numpy as np
import psutil
from PIL import Image, ImageOps, UnidentifiedImageError

PROFILES = {"Conservador": 0.20, "Equilibrado": 0.10, "Detalhado": 0.045}
FORMATS = {"PNG": "png", "JPEG": "jpg", "GIF": "gif", "WEBP": "webp", "TIFF": "tif", "BMP": "bmp"}

@dataclass
class Settings:
    profile: str = "Equilibrado"
    full_scan: bool = False
    interval_ms: int = 120
    per_media: int = 80
    per_scene: int = 8
    min_side: int = 1
    sharpness: float = 0
    allow_similar: bool = False
    max_seconds: int = 3600
    max_mb: int = 512
    sensitivity: float = 1.0
    ffprobe: str = ""

    def validate(self):
        if self.profile not in PROFILES or min(self.per_media, self.per_scene, self.min_side,
                self.max_seconds, self.max_mb, self.sensitivity) <= 0 or self.interval_ms < 0:
            raise ValueError("Configuração do extrator inválida.")

def video_format(path):
    with path.open("rb") as f:
        header = f.read(16)
    if header.startswith(b"\x1aE\xdf\xa3"):
        return "matroska"
    if header[4:8] in (b"ftyp", b"moov", b"mdat", b"wide", b"free"):
        return "mov"
    if header[:4] == b"RIFF" and header[8:12] == b"AVI ":
        return "avi"
    raise ValueError("Conteúdo de mídia desconhecido.")

def video(path):
    return av.open(str(path), format=video_format(path),
                   options={"protocol_whitelist":"file", "enable_drefs":"0", "use_absolute_path":"0"})

def dimensions(w, h):
    # Decoding, EXIF orientation, compositing and deduplication need several buffers.
    pixels = w * h
    if w <= 0 or h <= 0 or pixels * 24 > psutil.virtual_memory().available // 2:
        raise ValueError(f"RAM livre insuficiente para preparar o original de {w} × {h}.")

def inspect(path: Path, cfg: Settings):
    cfg.validate()
    if path.stat().st_size > cfg.max_mb * 1024**2:
        raise ValueError("Arquivo excede o limite de tamanho configurado.")
    try:
        with Image.open(path, formats=tuple(FORMATS)) as im:
            dimensions(*im.size)
            animated = getattr(im, "is_animated", False)
            im.load()
            return ("animation" if animated else "image", FORMATS[im.format], None)
    except UnidentifiedImageError:
        pass
    if cfg.ffprobe:
        import subprocess,json
        fmt=video_format(path)
        cmd=[cfg.ffprobe,"-v","error","-protocol_whitelist","file","-f",fmt,"-select_streams","v:0",
             "-show_entries","stream=width,height:format=duration","-of","json",str(path)]
        probe=json.loads(subprocess.check_output(cmd,timeout=25,stderr=subprocess.PIPE))
        if not probe.get("streams"):raise ValueError("FFprobe não encontrou vídeo.")
    with video(path) as container:
        if not container.streams.video:
            raise ValueError("Arquivo sem stream de vídeo.")
        stream = container.streams.video[0]
        dimensions(stream.width, stream.height)
        duration = container.duration / av.time_base if container.duration else None
        if duration and duration > cfg.max_seconds:
            raise ValueError("Vídeo excede a duração configurada.")
        ext = {"mov":"mp4", "matroska":"mkv", "avi":"avi"}[video_format(path)]
        with path.open("rb") as f:
            signature=f.read(256)
        if ext=="mkv" and b"webm" in signature:ext="webm"
        if ext=="mp4" and (signature[4:8]!=b"ftyp" or signature[8:12]==b"qt  "):ext="mov"
        return "video", ext, duration

def decoded(path, kind):
    if kind != "video":
        with Image.open(path) as im:
            ms = 0
            first = int(bool(im.info.get("default_image"))) if kind == "animation" else 0
            for i in range(first, im.n_frames if hasattr(im, "n_frames") else 1):
                im.seek(i)
                yield i, Fraction(ms, 1000), ImageOps.exif_transpose(im).convert("RGBA")
                ms += round(im.info.get("duration", 0))
        return
    with video(path) as container:
        for i, frame in enumerate(container.decode(video=0)):
            if frame.pts is None:
                raise ValueError("Frame sem PTS; inspecione a mídia.")
            dimensions(frame.width, frame.height)
            yield i, frame.pts * frame.time_base, frame.to_image()

def candidates(path, kind, duration, cfg, stop, progress=None):
    previous = accepted = None
    scene = in_scene = count = 0
    last_ms = sampled_ms = -float("inf")
    start = None
    threshold = PROFILES[cfg.profile] / cfg.sensitivity
    frames=None
    if progress and kind=="animation":
        with Image.open(path) as im:frames=im.n_frames
    if progress:progress("extract",path.name,0,frames if frames else duration)
    for index, pts, image in decoded(path, kind):
        if stop and stop.is_set():
            raise InterruptedError("Extração interrompida.")
        ms = round(pts * 1000)
        if start is None:
            start = ms
        if progress:
            progress("extract",path.name,index+1 if frames else (ms-start)/1000,frames or duration)
        if ms-start > cfg.max_seconds * 1000:
            raise ValueError("Duração excedida durante a decodificação.")
        if kind == "video" and not cfg.full_scan and ms-sampled_ms < min(cfg.interval_ms, 250):
            continue
        sampled_ms = ms
        thumb = np.asarray(image.convert("RGB").resize((32,32)), dtype=np.float32) / 255
        delta = 1.0
        if accepted is not None:
            changes = np.abs(thumb-accepted).mean(axis=2)
            cells = changes.reshape(8,4,8,4).mean(axis=(1,3)).ravel()
            delta = max(float(changes.mean()),float(np.partition(cells,-8)[-8:].mean())*0.75)
        cut = previous is None or float(np.abs(thumb-previous).mean()) >= max(0.22, threshold)
        previous = thumb
        if cut:
            scene += 1
            in_scene = 0
        if min(image.size) < cfg.min_side or in_scene >= cfg.per_scene:
            continue
        if accepted is not None and (delta < threshold and not cfg.allow_similar or
                                     ms-last_ms < cfg.interval_ms and not cut):
            continue
        # Reserve capacity for later scenes in a long clip.
        if duration and count >= max(3, int(cfg.per_media * ((ms-start)/1000/duration)) + 2):
            continue
        gray = thumb.mean(axis=2)
        sharp = float(np.abs(np.diff(gray, axis=0)).mean()*255 + np.abs(np.diff(gray, axis=1)).mean()*255)
        yield index, pts, image, dict(scene=scene, sharpness=round(sharp, 3),
                                    similarity=round(1-delta, 4), uncertain=sharp < cfg.sharpness)
        accepted, last_ms = thumb, ms
        count += 1
        in_scene += 1
        if count >= cfg.per_media:
            break

