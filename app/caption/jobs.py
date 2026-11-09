"""Sequential, resumable visual inference for approved dataset images."""
from catalog import apply_source_tags
from captions import create_tags, create_caption
from sources import canonical_tags
import requests

def infer(call, stop):
    for attempt in range(3):
        if stop.is_set():
            raise InterruptedError("Fila interrompida.")
        try:
            return call()
        except (requests.RequestException, RuntimeError):
            if attempt == 2:
                raise
            if stop.wait(2**attempt):
                raise InterruptedError("Fila interrompida.")

def run_jobs(project, keys, operation, cfg, profile, fit, stop, notify, strategy="Qwen sugere", force=False, allow_pending=False):
    failures = 0
    for key in keys:
        if stop.is_set():
            break
        it = project.items[key]
        if it.get("removed") or it.get("status") not in (("aprovado","pendente") if allow_pending else ("aprovado",)):
            continue
        path = project.path_for(it)
        geom = [fit,it["crop"].copy(),it.get("ai_resolution",768)]
        needs_caption = not it.get("krea") or it.get("caption_stale") or (it.get("caption_geom") and it["caption_geom"] != geom)
        try:
            if apply_source_tags(it):
                project.save_one(key)
                needs_caption=True
            if not it.get("tags") and not it.get("inherited_tags") and not it.get("sdxl_edited"):
                request=dict(it)
                tags=infer(lambda:create_tags(path,request,cfg,fit),stop)
                it.update(tags=tags,tags_ready=True,tags_stale=False,tags_geom=geom,
                          visual_groups=request.get("visual_groups",{}),tag_model=cfg.model,
                          tag_origins={t:"qwen" for t in tags},sdxl=", ".join(tags),
                          caption_stale=bool(it.get("krea")),ai_error="")
                project.save_one(key)
                needs_caption=True
                notify(key,"Tags salvas")
            if operation in ("caption","both") and (force or needs_caption):
                if it.get("caption_edited") and not force:
                    raise ValueError("Caption manual protegida. Use regeneração com backup.")
                cap = infer(lambda:create_caption(path,it,cfg,fit), stop)
                it.update(krea=cap,caption_profile=profile,caption_model=cfg.model,
                          caption_stale=False,caption_geom=geom,caption_edited=False, ai_error="")
                project.save_one(key)
                notify(key,"Caption salva")
        except InterruptedError:
            raise
        except Exception as exc:
            it["ai_error"] = str(exc)
            project.save_one(key)
            failures += 1
            notify(key,"Falha: "+str(exc))
    return failures

