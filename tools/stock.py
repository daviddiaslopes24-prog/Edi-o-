"""Busca e baixa fotos e vídeos gratuitos (Pexels e Pixabay) com o crédito da fonte.

As chaves NUNCA ficam no repositório: são lidas das variáveis de ambiente
PIXABAY_KEY e PEXELS_KEY (configuradas nas configurações do ambiente).
"""
import json, os, hashlib, urllib.request, urllib.parse, random

UA = {"User-Agent": "editor-video/1.0"}
_used = set()

def _get(url, headers=None):
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())

def _download(url, path):
    if os.path.exists(path) and os.path.getsize(path) > 0: return path
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=120) as r, open(path + ".part", "wb") as f:
        while True:
            b = r.read(1 << 20)
            if not b: break
            f.write(b)
    os.replace(path + ".part", path); return path

def _pixabay(q, kind):
    key = os.environ.get("PIXABAY_KEY")
    if not key: return []
    base = "https://pixabay.com/api/videos/" if kind == "video" else "https://pixabay.com/api/"
    d = _get(base + "?" + urllib.parse.urlencode({"key": key, "q": q, "per_page": 20, "safesearch": "true",
                                                    **({} if kind == "video" else {"image_type": "photo", "orientation": "horizontal", "min_width": 1600})}))
    out = []
    for h in d.get("hits", []):
        if kind == "video":
            vs = [v for v in h["videos"].values() if v.get("url") and v.get("width", 0) >= 1280]
            if not vs or h.get("duration", 0) < 4 or h.get("type") == "animation": continue  # só filmagem real
            v = min(vs, key=lambda v: abs(v["width"] - 1920))
            out.append({"id": f"pb{h['id']}", "url": v["url"], "ext": "mp4", "credit": "Pixabay", "dur": h.get("duration", 0)})
        else:
            out.append({"id": f"pb{h['id']}", "url": h.get("largeImageURL") or h["webformatURL"], "ext": "jpg", "credit": "Pixabay"})
    return out

def _pexels(q, kind):
    key = os.environ.get("PEXELS_KEY")
    if not key: return []
    if kind == "video":
        d = _get("https://api.pexels.com/videos/search?" + urllib.parse.urlencode({"query": q, "per_page": 20, "orientation": "landscape"}), {"Authorization": key})
        out = []
        for v in d.get("videos", []):
            fs = [f for f in v.get("video_files", []) if f.get("width") and f["width"] >= 1280 and f.get("file_type") == "video/mp4"]
            if not fs or v.get("duration", 0) < 4: continue
            f = min(fs, key=lambda f: abs(f["width"] - 1920))
            out.append({"id": f"px{v['id']}", "url": f["link"], "ext": "mp4", "credit": f"Pexels / {v['user']['name']}", "dur": v.get("duration", 0)})
        return out
    d = _get("https://api.pexels.com/v1/search?" + urllib.parse.urlencode({"query": q, "per_page": 20, "orientation": "landscape"}), {"Authorization": key})
    return [{"id": f"px{p['id']}", "url": p["src"]["large2x"], "ext": "jpg", "credit": f"Pexels / {p['photographer']}"} for p in d.get("photos", [])]

def fetch(q, kind, cache, seed=0):
    """Retorna {path, credit, kind} de um resultado ainda não usado neste vídeo, ou None."""
    os.makedirs(cache, exist_ok=True)
    idx = os.path.join(cache, "busca_" + hashlib.md5(f"{kind}:{q}".encode()).hexdigest()[:12] + ".json")
    if os.path.exists(idx): res = json.load(open(idx))
    else:
        res = []
        for fn in (_pexels, _pixabay):
            try: res += fn(q, kind)
            except Exception as e: print("busca falhou", fn.__name__, q, e)
        json.dump(res, open(idx, "w"))
    # mantém a ordem de relevância da busca; Pexels primeiro, depois Pixabay
    cands = [r for r in res if r["id"] not in _used]
    cands.sort(key=lambda r: 0 if r["id"].startswith("px") else 1)
    for r in cands[:4]:
        try:
            p = _download(r["url"], os.path.join(cache, f"{r['id']}.{r['ext']}"))
            _used.add(r["id"]); return {"path": p, "credit": r["credit"], "kind": kind}
        except Exception as e:
            print("download falhou", r["url"], e)
    return None
