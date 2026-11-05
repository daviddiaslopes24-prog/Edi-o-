"""Renderizador de vídeo explicativo (estilo documentário com mapas e gráficos).
Uso: python render.py plano.json transcricao_editada.json voz.wav assets_dir saida.mp4
"""
import json, sys, os, math, re, unicodedata, subprocess, wave
from functools import lru_cache
from multiprocessing import Pool
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H, FPS = 1920, 1080, 25
ASSETS = os.environ.get("ASSETS", ".")
BRAND = os.environ.get("BRAND", "IMPACTO ECONÔMICO")

# ---------- paleta ----------
DARK_BG = (11, 18, 16); DARK_GRID = (24, 38, 33)
LAND = (30, 58, 44); LAND_EDGE = (78, 140, 104); OCEAN = (9, 16, 15)
PAPER = (245, 240, 226); PAPER_GRID = (226, 219, 200); INK = (24, 24, 24)
RED = (230, 57, 70); GREEN = (46, 204, 113); BLUE = (91, 155, 213); GOLD = (244, 196, 48)
WHITE = (245, 245, 245); MUTED = (150, 165, 158)
# Cores do canal: PRETO e AMARELO (pedido do usuário). ACCENT = destaque da marca; RED fica só para dados negativos.
YELLOW = (255, 204, 0)
ACCENT = YELLOW if os.environ.get("TEMA", "amarelo") == "amarelo" else (230, 57, 70)
ON_ACCENT = (14, 14, 14) if ACCENT == YELLOW else (245, 245, 245)  # texto sobre o destaque

# ---------- utilidades ----------
@lru_cache(None)
def F(name, size):
    files = {"black": "Poppins-Black.ttf", "bold": "Poppins-Bold.ttf", "xbold": "Poppins-ExtraBold.ttf",
             "med": "Poppins-Medium.ttf", "reg": "Poppins-Regular.ttf",
             "serif": "PlayfairDisplay%5Bwght%5D.ttf", "serifi": "PlayfairDisplay-Italic%5Bwght%5D.ttf",
             "sym": "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"}
    f = files[name]
    path = f if f.startswith("/") else os.path.join(ASSETS, "fonts", f)
    font = ImageFont.truetype(path, size)
    if name.startswith("serif"):
        try: font.set_variation_by_axes([800 if name == "serif" else 700])
        except Exception: pass
    return font

def clamp(x, a=0.0, b=1.0): return max(a, min(b, x))
def ease(x): x = clamp(x); return 1 - (1 - x) ** 3
def ease_io(x): x = clamp(x); return x * x * (3 - 2 * x)
def back(x):
    x = clamp(x); c = 1.70158; return 1 + (c + 1) * (x - 1) ** 3 + c * (x - 1) ** 2
def prog(t, a, d): return clamp((t - a) / d) if d > 0 else (1.0 if t >= a else 0.0)
def rgba(c, a): return (c[0], c[1], c[2], int(clamp(a) * 255))

def fmt_br(v, dec=0):
    s = f"{abs(v):,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return ("-" if v < 0 else "") + s

def tw(font, text): return font.getlength(text)

def wrap(text, font, maxw):
    words, lines, cur = text.split(), [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if tw(font, test) <= maxw or not cur: cur = test
        else: lines.append(cur); cur = w
    if cur: lines.append(cur)
    return lines

# ---------- fundos ----------
@lru_cache(None)
def bg(kind):
    if kind == "dark":
        y, x = np.mgrid[0:H, 0:W]
        d = np.sqrt(((x - W / 2) / W) ** 2 + ((y - H / 2) / H) ** 2)
        base = np.array(DARK_BG, float)[None, None] * (1.25 - 0.6 * d[..., None])
        img = Image.fromarray(np.clip(base, 0, 255).astype(np.uint8)).convert("RGBA")
        dr = ImageDraw.Draw(img)
        for gx in range(0, W, 80): dr.line([(gx, 0), (gx, H)], fill=DARK_GRID + (255,), width=1)
        for gy in range(0, H, 80): dr.line([(0, gy), (W, gy)], fill=DARK_GRID + (255,), width=1)
        return img
    if kind == "paper":
        rng = np.random.default_rng(1)
        n = rng.normal(0, 3, (H, W, 1))
        img = Image.fromarray(np.clip(np.array(PAPER, float)[None, None] + n, 0, 255).astype(np.uint8)).convert("RGBA")
        dr = ImageDraw.Draw(img)
        for gx in range(0, W, 60): dr.line([(gx, 0), (gx, H)], fill=PAPER_GRID + (255,), width=1)
        for gy in range(0, H, 60): dr.line([(0, gy), (W, gy)], fill=PAPER_GRID + (255,), width=1)
        return img
    if kind == "cream":
        rng = np.random.default_rng(2)
        return Image.fromarray(np.clip(np.array(CREAM, float)[None, None] + rng.normal(0, 4, (H, W, 1)), 0, 255).astype(np.uint8)).convert("RGBA")
    if kind == "gray":
        y, x = np.mgrid[0:H, 0:W]
        d = np.sqrt(((x - W / 2) / W) ** 2 + ((y - H / 2) / H) ** 2)
        v = 70 - 50 * d
        return Image.fromarray(np.clip(np.stack([v, v + 2, v + 2], -1), 0, 255).astype(np.uint8)).convert("RGBA")

@lru_cache(None)
def vignette():
    y, x = np.mgrid[0:H, 0:W]
    d = np.sqrt(((x - W / 2) / (W / 2)) ** 2 + ((y - H / 2) / (H / 2)) ** 2)
    return (1 - 0.35 * np.clip(d - 0.45, 0, 1) ** 1.5)[..., None].astype(np.float32)

@lru_cache(None)
def grains():
    rng = np.random.default_rng(5)
    return [rng.normal(0, 4.5, (H // 2, W // 2, 1)).astype(np.float32).repeat(2, 0).repeat(2, 1) for _ in range(6)]

# ---------- mapa ----------
@lru_cache(None)
def geo():
    def load(p, key):
        d = json.load(open(os.path.join(ASSETS, "geo", p)))
        out = []
        for f in d["features"]:
            g = f["geometry"]
            if not g: continue
            polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
            rings = [np.array(poly[0]) for poly in polys]
            bb = [min(r[:, 0].min() for r in rings), min(r[:, 1].min() for r in rings),
                  max(r[:, 0].max() for r in rings), max(r[:, 1].max() for r in rings)]
            out.append((f["properties"].get(key), rings, bb))
        return out
    return load("countries.geojson", "ADM0_A3"), [s for s in load("states.geojson", "admin") if s[0] == "Brazil"]

def lerp_box(a, b, k): return [a[i] + (b[i] - a[i]) * k for i in range(4)]

def map_proj(view):
    # view = [lon_c, lat_c, largura_em_graus]  (projeção equiretangular com correção de latitude)
    lc, la, wd = view
    sx = W / wd; cosl = math.cos(math.radians(clamp(la, -60, 60)))
    def P(lon, lat): return ((lon - lc) * sx * cosl + W / 2, (la - lat) * sx + H / 2)
    return P, (lc - wd / 2 / cosl, la - wd * H / W / 2 / 1, lc + wd / 2 / cosl, la + wd * H / W / 2)

def draw_map(img, view, highlights, t, hl_alpha=1.0, states=True):
    countries, br_states = geo()
    lc, la, wd = view
    cosl = math.cos(math.radians(clamp(la, -60, 60)))
    sx = W / wd * cosl; sy = W / wd
    def P(arr):
        return np.stack([(arr[:, 0] - lc) * sx + W / 2, (la - arr[:, 1]) * sy + H / 2], 1)
    lon_half = W / 2 / sx + 5; lat_half = H / 2 / sy + 5
    vb = (lc - lon_half, la - lat_half, lc + lon_half, la + lat_half)
    dr = ImageDraw.Draw(img, "RGBA")
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0)); do = ImageDraw.Draw(ov)
    step = 1 if wd < 120 else 2
    for code, rings, bb in countries:
        if bb[2] < vb[0] or bb[0] > vb[2] or bb[3] < vb[1] or bb[1] > vb[3]: continue
        hl = highlights.get(code)
        for r in rings:
            pts = [tuple(p) for p in P(r[::step])]
            if len(pts) < 3: continue
            dr.polygon(pts, fill=LAND + (255,), outline=LAND_EDGE + (255,))
            if hl:
                do.polygon(pts, fill=rgba(hl, 0.62 * hl_alpha), outline=rgba(hl, hl_alpha))
    if states and wd < 90:
        for _, rings, _ in br_states:
            for r in rings:
                pts = [tuple(p) for p in P(r)]
                if len(pts) > 2: dr.line(pts + [pts[0]], fill=LAND_EDGE + (110,), width=1)
    img.alpha_composite(ov)
    def project(lon, lat): return ((lon - lc) * sx + W / 2, (la - lat) * sy + H / 2)
    return project

# ---------- elementos gráficos ----------
def label_box(dr, xy, text, t, color=WHITE, bgc=(0, 0, 0), size=34, anchor="mm", alpha=1.0):
    if bgc == ACCENT and color == WHITE: color = ON_ACCENT
    f = F("xbold", size); x, y = xy
    w = tw(f, text) + 34; h = size + 26
    if anchor == "mm": x0, y0 = x - w / 2, y - h / 2
    else: x0, y0 = x, y - h / 2
    dr.rounded_rectangle([x0, y0, x0 + w, y0 + h], radius=8, fill=rgba(bgc, 0.78 * alpha))
    dr.text((x0 + w / 2, y0 + h / 2 + 2), text, font=f, fill=rgba(color, alpha), anchor="mm")
    return x0, y0, w, h

def callout(dr, pt, text, t, start=0.0, dx=180, dy=-120, color=WHITE):
    k = ease(prog(t, start, 0.5))
    if k <= 0: return
    x, y = pt; ex, ey = x + dx * k, y + dy * k
    r = 8 + 4 * math.sin(t * 5)
    dr.ellipse([x - r, y - r, x + r, y + r], outline=rgba(color, 1), width=3)
    dr.ellipse([x - 5, y - 5, x + 5, y + 5], fill=rgba(color, 1))
    dr.line([(x, y), (ex, ey)], fill=rgba(color, 1), width=3)
    if k > 0.6:
        a = prog(t, start + 0.3, 0.3)
        label_box(dr, (ex + (12 if dx > 0 else -12), ey), text, t, anchor="lm" if dx > 0 else "mm", alpha=a)

def arrow_tri(dr, cx, cy, s, up, color, a=1.0):
    if up: pts = [(cx, cy - s), (cx - s, cy + s * 0.7), (cx + s, cy + s * 0.7)]
    else: pts = [(cx, cy + s), (cx - s, cy - s * 0.7), (cx + s, cy - s * 0.7)]
    dr.polygon(pts, fill=rgba(color, a))

def curve_arrow(dr, a, b, k, color=GOLD, width=6, bend=-0.3):
    if k <= 0: return
    (x0, y0), (x1, y1) = a, b
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    nx, ny = -(y1 - y0), (x1 - x0)
    cx, cy = mx + nx * bend, my + ny * bend
    pts = []
    N = 60
    for i in range(int(N * k) + 1):
        u = i / N
        pts.append(((1 - u) ** 2 * x0 + 2 * (1 - u) * u * cx + u * u * x1, (1 - u) ** 2 * y0 + 2 * (1 - u) * u * cy + u * u * y1))
    for i in range(0, len(pts) - 1, 2):
        dr.line([pts[i], pts[i + 1]], fill=rgba(color, 1), width=width)
    if len(pts) >= 2:
        (ax, ay), (bx, by) = pts[-2], pts[-1]
        ang = math.atan2(by - ay, bx - ax); s = 22
        dr.polygon([(bx + math.cos(ang) * s, by + math.sin(ang) * s),
                    (bx + math.cos(ang + 2.4) * s, by + math.sin(ang + 2.4) * s),
                    (bx + math.cos(ang - 2.4) * s, by + math.sin(ang - 2.4) * s)], fill=rgba(color, 1))

def word_reveal(dr, lines, font, cx, cy, t, start=0.0, gap=0.09, color=WHITE, accent=ACCENT, lh=1.15, align="center", x0=None):
    """Linhas de texto com palavras surgindo; palavras entre *asteriscos* ficam na cor de destaque."""
    word_reveal.acc = False
    sz = font.size; total_h = len(lines) * sz * lh; y = cy - total_h / 2 + sz * lh / 2
    idx = 0
    for line in lines:
        words = line.split()
        clean = [w.replace("*", "") for w in words]
        lw = tw(font, " ".join(clean))
        x = (cx - lw / 2) if align == "center" else x0
        for w, c in zip(words, clean):
            k = ease(prog(t, start + idx * gap, 0.35)); idx += 1
            if w.startswith("*"): word_reveal.acc = True
            on = getattr(word_reveal, "acc", False)
            if w.endswith("*") or w.rstrip("?.,!").endswith("*"): word_reveal.acc = False
            if k > 0:
                col = accent if on else color
                dr.text((x, y + (1 - k) * 40), c, font=font, fill=rgba(col, k), anchor="lm")
            x += tw(font, c + " ")
        y += sz * lh
    return idx

def kicker(dr, text, x, y, color=ACCENT, t=0, start=0, dark=True):
    k = ease(prog(t, start, 0.4))
    f = F("bold", 30)
    w = tw(f, text)
    dr.rectangle([x, y - 4, x + 8, y + 36], fill=rgba(color, k))
    dr.text((x + 22 - (1 - k) * 30, y + 16), text, font=f, fill=rgba(WHITE if dark else INK, k), anchor="lm")

# ---------- cenas ----------
def sc_title(img, dr, t, D, p):
    lines = p["lines"]
    f = F("black", 118)
    word_reveal(dr, lines, f, W / 2, H / 2 - 40, t, 0.15, 0.12)
    k = ease(prog(t, 0.9, 0.6))
    dr.rectangle([W / 2 - 420 * k, H / 2 + 120, W / 2 + 420 * k, H / 2 + 132], fill=rgba(ACCENT, 1))
    if p.get("sub"):
        a = prog(t, 1.2, 0.5)
        dr.text((W / 2, H / 2 + 200), p["sub"], font=F("med", 52), fill=rgba(WHITE, a), anchor="mm")
    # faixa de "ao vivo"
    a = prog(t, 0.3, 0.4)
    label_box(dr, (W / 2, 190), "MERCADO EM QUEDA", t, color=WHITE, bgc=ACCENT, size=30, alpha=a)
    return [(0.0, "boom", 0.9), (0.15, "whoosh", 0.5)]

def sc_chapter(img, dr, t, D, p):
    n = p["n"]; title = p["title"]
    kk = ease(prog(t, 0.0, 0.5))
    dr.text((160, 380), f"PARTE {n}", font=F("bold", 40), fill=rgba(ACCENT, kk), anchor="lm")
    dr.rectangle([160, 420, 160 + 120 * kk, 426], fill=rgba(ACCENT, 1))
    # máquina de escrever com trecho em itálico (*...*)
    parts = re.split(r"(\*[^*]+\*)", title)
    total = sum(len(s.strip("*")) for s in parts)
    shown = int(total * prog(t, 0.35, max(0.6, min(1.6, total * 0.045))))
    fr, fi = F("serif", 96), F("serifi", 96)
    x, y = 160, 520; maxw = W - 320; cnt = 0
    for s in parts:
        if not s: continue
        it = s.startswith("*"); s = s.strip("*"); f = fi if it else fr
        for word in re.split(r"(\s+)", s):
            if not word: continue
            if word.strip() and x + tw(f, word) > 160 + maxw: x = 160; y += 120
            vis = word[: max(0, shown - cnt)]; cnt += len(word)
            if vis: dr.text((x, y), vis, font=f, fill=rgba(ACCENT if it else INK, 1), anchor="ls")
            x += tw(f, word)
    if shown < total and int(t * 3) % 2 == 0:
        dr.rectangle([x + 6, y - 80, x + 12, y + 10], fill=rgba(INK, 1))
    return [(0.0, "whoosh", 0.6), (0.35, "typing", 0.5)]

def sc_kinetic(img, dr, t, D, p):
    dark = p.get("bg", "dark") != "paper"
    f = F("black", p.get("size", 96))
    lines = wrap(p["text"], f, W - 300)
    word_reveal(dr, lines, f, W / 2, H / 2, t, 0.1, 0.1, color=WHITE if dark else INK)
    return [(0.0, "whoosh", 0.55)]

def sc_question(img, dr, t, D, p):
    f = F("black", 104)
    lines = wrap(p["text"], f, W - 360)
    k = back(prog(t, 0.0, 0.5))
    qf = F("black", 420)
    dr.text((W - 260, H / 2), "?", font=qf, fill=rgba(ACCENT, 0.25 * k), anchor="mm")
    word_reveal(dr, lines, f, W / 2 - 80, H / 2, t, 0.1, 0.1)
    return [(0.0, "whoosh_down", 0.6), (0.1, "hit", 0.35)]

def count_val(p, t):
    k = ease_io(prog(t, 0.2, p.get("dur", 1.6)))
    return p.get("from", 0) + (p["to"] - p.get("from", 0)) * k, k

def sc_bignum(img, dr, t, D, p):
    v, k = count_val(p, t)
    txt = p.get("prefix", "") + (str(int(round(v))) if p.get("plain") else fmt_br(v, p.get("dec", 0))) + p.get("suffix", "")
    col = {"red": RED, "green": GREEN, "white": WHITE, "gold": GOLD}[p.get("color", "red")]
    s = 1 + 0.15 * (1 - back(prog(t, 0.0, 0.45)))
    f = F("black", int(200 * s * p.get("scale", 1)))
    a = prog(t, 0, 0.2)
    dr.text((W / 2 + 60, H / 2 - 30), txt, font=f, fill=rgba(col, a), anchor="mm")
    if p.get("arrow"):
        wtxt = tw(F("black", int(200 * p.get("scale", 1))), txt)
        arrow_tri(dr, W / 2 + 60 - wtxt / 2 - 110, H / 2 - 30, 60, p["arrow"] == "up", col, a)
    la = ease(prog(t, 0.5, 0.5))
    dr.text((W / 2, H / 2 + 140 + (1 - la) * 30), p["label"], font=F("med", 54), fill=rgba(WHITE, la), anchor="mm")
    if p.get("kicker"): kicker(dr, p["kicker"], 140, 150, t=t)
    return [(0.0, "hit", 0.7), (0.2, "riser", 0.15), (0.2 + p.get("dur", 1.6), "ding", 0.35)]

def sc_datecard(img, dr, t, D, p):
    # calendário de outubro de 2026 (1º de outubro = quinta-feira)
    month, first_wd, ndays = p.get("month", "OUTUBRO 2026"), p.get("first_wd", 4), p.get("ndays", 31)
    cw, ch = 150, 104; gx = W / 2 - cw * 3.5; gy = 300
    a = ease(prog(t, 0, 0.4))
    dr.text((W / 2, 180), month, font=F("black", 80), fill=rgba(WHITE, a), anchor="mm")
    for i, d in enumerate(["DOM", "SEG", "TER", "QUA", "QUI", "SEX", "SÁB"]):
        dr.text((gx + cw * i + cw / 2, gy - 20), d, font=F("bold", 30), fill=rgba(MUTED, a), anchor="mm")
    hl = p.get("highlight", [])
    for day in range(1, ndays + 1):
        pos = first_wd + day - 1; r, c = divmod(pos, 7)
        x, y = gx + c * cw, gy + 20 + r * ch
        k = ease(prog(t, 0.1 + day * 0.012, 0.3))
        on = day in hl
        hk = ease(prog(t, 0.8 + hl.index(day) * 0.18, 0.3)) if on else 0
        dr.rounded_rectangle([x + 6, y + 6, x + cw - 6, y + ch - 6], radius=12,
                             fill=rgba(ACCENT, 0.9 * hk) if on and hk > 0 else rgba((30, 45, 40), k),
                             outline=rgba((60, 80, 72), k))
        dr.text((x + cw / 2, y + ch / 2 + 2), str(day), font=F("bold", 40), fill=rgba(ON_ACCENT if (on and hk > 0.5) else WHITE, k), anchor="mm")
    if p.get("label"):
        la = ease(prog(t, 1.4, 0.4))
        label_box(dr, (W / 2, H - 90), p["label"], t, bgc=ACCENT, size=36, alpha=la)
    return [(0.0, "whoosh", 0.5)] + [(0.8 + i * 0.18, "pop", 0.4) for i in range(len(hl))]

def sc_timeline(img, dr, t, D, p):
    items = p["items"]; hl = p.get("hl")
    x0, x1, y = 200, W - 200, H / 2 + 40
    k = ease(prog(t, 0, 0.8))
    dr.line([(x0, y), (x0 + (x1 - x0) * k, y)], fill=rgba(MUTED, 1), width=4)
    n = len(items); sfx = [(0.0, "whoosh", 0.5)]
    for i, (yr, txt) in enumerate(items):
        x = x0 + (x1 - x0) * (i + 0.5) / n
        st = 0.3 + i * 0.35; a = ease(prog(t, st, 0.4))
        on = (yr == hl)
        col = ACCENT if on else WHITE
        r = 18 if not on else 22 + 4 * math.sin(t * 6)
        dr.ellipse([x - r, y - r, x + r, y + r], fill=rgba(col, a))
        dr.text((x, y - 80 - (1 - a) * 20), yr, font=F("black", 76 if on else 56), fill=rgba(col, a), anchor="mm")
        for j, ln in enumerate(wrap(txt, F("med", 34), 420)):
            dr.text((x, y + 70 + j * 44), ln, font=F("med", 34), fill=rgba(WHITE if on else MUTED, a), anchor="mm")
        sfx.append((st, "tick", 0.4))
    if p.get("title"): kicker(dr, p["title"], 140, 150, t=t)
    return sfx

def chart_frame(dr, box, ymin, ymax, ticks, fmtf, dark=True):
    x0, y0, x1, y1 = box
    for v in ticks:
        yy = y1 - (v - ymin) / (ymax - ymin) * (y1 - y0)
        dr.line([(x0, yy), (x1, yy)], fill=rgba((60, 80, 72) if dark else (200, 192, 170), 1), width=1)
        dr.text((x0 - 20, yy), fmtf(v), font=F("med", 28), fill=rgba(MUTED if dark else (110, 100, 80), 1), anchor="rm")

def sc_line(img, dr, t, D, p):
    pts = p["points"]  # [[rotulo_x, valor], ...]
    ymin, ymax = p["ymin"], p["ymax"]
    box = (260, 230, W - 200, H - 190)
    x0, y0, x1, y1 = box
    chart_frame(dr, box, ymin, ymax, p["ticks"], lambda v: p.get("yfmt", "{}").format(fmt_br(v, p.get("ydec", 0))))
    n = len(pts)
    def XY(i, v): return (x0 + (x1 - x0) * i / (n - 1), y1 - (v - ymin) / (ymax - ymin) * (y1 - y0))
    k = ease_io(prog(t, 0.3, p.get("draw", 2.5)))
    upto = k * (n - 1); full = int(upto)
    poly = [XY(i, pts[i][1]) for i in range(full + 1)]
    if full < n - 1:
        fr = upto - full; a = XY(full, pts[full][1]); b = XY(full + 1, pts[full + 1][1])
        poly.append((a[0] + (b[0] - a[0]) * fr, a[1] + (b[1] - a[1]) * fr))
    col = {"red": RED, "green": GREEN}[p.get("color", "red")]
    if len(poly) > 1:
        ov = Image.new("RGBA", (W, H)); do = ImageDraw.Draw(ov)
        do.polygon(poly + [(poly[-1][0], y1), (poly[0][0], y1)], fill=rgba(col, 0.18))
        img.alpha_composite(ov)
        dr.line(poly, fill=rgba(col, 1), width=7, joint="curve")
        ex, ey = poly[-1]; r = 12 + 3 * math.sin(t * 8)
        dr.ellipse([ex - r, ey - r, ex + r, ey + r], fill=rgba(WHITE, 1))
    for i, (lab, v) in enumerate(pts):
        if lab and i <= upto + 0.01:
            x, _ = XY(i, v)
            dr.text((x, y1 + 40), lab, font=F("med", 28), fill=rgba(MUTED, 1), anchor="mm")
    for i, txt in p.get("notes", {}).items():
        i = int(i)
        if upto >= i - 0.01:
            x, y = XY(i, pts[i][1])
            callout(dr, (x, y), txt, t, start=0.3 + p.get("draw", 2.5) * i / (n - 1), dx=-200 if x > W * 0.6 else 160,
                    dy=-100)
    if p.get("title"): kicker(dr, p["title"], 140, 120, t=t)
    if p.get("note"): dr.text((W - 200, H - 120), p["note"], font=F("reg", 24), fill=rgba(MUTED, 1), anchor="rm")
    return [(0.0, "whoosh", 0.5), (0.3, "riser", 0.25)]

def sc_bars(img, dr, t, D, p):
    items = p["items"]; vmax = p.get("vmax", max(abs(v) for _, v in items))
    title = p["title"]
    parts = re.split(r"(\*[^*]+\*)", title); x = 160
    for s in parts:
        if not s: continue
        it = s.startswith("*"); s = s.strip("*"); f = F("serifi" if it else "serif", 76)
        dr.text((x, 200), s, font=f, fill=rgba(ACCENT if it else INK, prog(t, 0, 0.4)), anchor="ls"); x += tw(f, s)
    if p.get("sub"): dr.text((162, 250), p["sub"], font=F("reg", 30), fill=rgba((90, 85, 70), prog(t, 0.2, 0.4)), anchor="lm")
    n = len(items); gap = min(170, (H - 420) / n); y = 360
    span = min(p.get("span", D * 0.75), D * 0.72); sfx = [(0.0, "whoosh", 0.5)]
    for i, (name, v) in enumerate(items):
        st = 0.4 + span * i / max(1, n)
        k = ease(prog(t, st, 0.9))
        if k <= 0: y += gap; continue
        dr.text((160, y), name, font=F("bold", 42), fill=rgba(INK, k), anchor="ls")
        L = (W - 600) * abs(v) / vmax * k
        col = RED if v < 0 else (GREEN if p.get("posgreen") else BLUE)
        dr.rectangle([160, y + 16, 160 + L, y + 70], fill=rgba(col, 0.9))
        dr.text((180 + L, y + 44), (p.get("fmt", "{}")).format(fmt_br(v * k, p.get("dec", 0))), font=F("black", 46),
                fill=rgba(col, k), anchor="lm")
        sfx.append((st, "pop", 0.5)); y += gap
    return sfx

def sc_list(img, dr, t, D, p):
    dark = p.get("bg", "dark") == "dark"; items = p["items"]; n = len(items)
    fg = WHITE if dark else INK
    if p.get("title"):
        a = ease(prog(t, 0, 0.4))
        dr.text((160, 200), p["title"], font=F("black", 64), fill=rgba(fg, a), anchor="lm")
        dr.rectangle([160, 250, 160 + 140 * a, 258], fill=rgba(ACCENT, 1))
    span = min(p.get("span", D * 0.7), D * 0.72); sfx = [(0.0, "whoosh", 0.5)]
    gap = min(150, (H - 380) / max(n, 1)); y0 = 330 + (H - 330 - 100 - gap * n) / 2
    for i, it in enumerate(items):
        st = 0.35 + span * i / max(1, n); k = ease(prog(t, st, 0.45))
        if k <= 0: continue
        y = y0 + i * gap + gap / 2; x = 160 + (1 - k) * -60
        dr.ellipse([x, y - 38, x + 76, y + 38], fill=rgba(ACCENT, k))
        dr.text((x + 38, y + 2), str(i + 1), font=F("black", 40), fill=rgba(ON_ACCENT, k), anchor="mm")
        f = F("bold", 54)
        dr.text((x + 110, y + 2), it, font=f, fill=rgba(fg, k), anchor="lm")
        sfx.append((st, "pop", 0.45))
    return sfx

def sc_chips(img, dr, t, D, p):
    items = p["items"]; col = ACCENT if p.get("color", "red") == "red" else GREEN
    if p.get("title"):
        a = ease(prog(t, 0, 0.4))
        dr.text((W / 2, 230), p["title"], font=F("black", 70), fill=rgba(WHITE, a), anchor="mm")
    f = F("black", 64); rows = [[]]; rw = 0
    for it in items:
        w = tw(f, it) + 120
        if rw + w > W - 300 and rows[-1]: rows.append([]); rw = 0
        rows[-1].append((it, w)); rw += w + 30
    y = H / 2 + 40 - (len(rows) - 1) * 80; idx = 0; span = min(p.get("span", D * 0.6), D * 0.72); sfx = [(0.0, "whoosh", 0.5)]
    for row in rows:
        tot = sum(w for _, w in row) + 30 * (len(row) - 1); x = W / 2 - tot / 2
        for it, w in row:
            st = 0.3 + span * idx / max(1, len(items)); idx += 1
            k = back(prog(t, st, 0.35))
            if k > 0:
                cx = x + w / 2; s = k
                dr.rounded_rectangle([cx - w / 2 * s, y - 60 * s, cx + w / 2 * s, y + 60 * s], radius=int(24 * s) + 1, fill=rgba(col, 0.95))
                if s > 0.6:
                    dr.text((cx, y + 3), it, font=f, fill=rgba(ON_ACCENT if col == ACCENT else WHITE, clamp(s)), anchor="mm")
                sfx.append((st, "pop", 0.55))
            x += w + 30
        y += 160
    if p.get("fonte"): pass
    return sfx

def sc_chain(img, dr, t, D, p):
    items = p["items"]; n = len(items)
    bw = min(380, (W - 200 - (n - 1) * 90) / n); bh = 230
    tot = n * bw + (n - 1) * 90; x = W / 2 - tot / 2; y = H / 2 + 20
    span = min(p.get("span", D * 0.7), D * 0.72); sfx = [(0.0, "whoosh", 0.5)]
    if p.get("title"): kicker(dr, p["title"], 140, 150, t=t)
    for i, it in enumerate(items):
        txt, arrow = (it if isinstance(it, list) else [it, None])
        st = 0.3 + span * i / max(1, n); k = back(prog(t, st, 0.4))
        if k > 0:
            cx = x + bw / 2; s = clamp(k, 0, 1.2)
            dr.rounded_rectangle([cx - bw / 2 * s, y - bh / 2 * s, cx + bw / 2 * s, y + bh / 2 * s], radius=20,
                                 fill=rgba((24, 40, 34), 1), outline=rgba(RED if arrow == "up" else (GREEN if arrow == "down2" else MUTED), 1), width=4)
            if s > 0.7:
                yy = y - (30 if arrow else 0)
                lines = wrap(txt, F("bold", 40), bw - 40)
                for j, ln in enumerate(lines):
                    dr.text((cx, yy + (j - (len(lines) - 1) / 2) * 50), ln, font=F("bold", 40), fill=rgba(WHITE, 1), anchor="mm")
                if arrow in ("up", "down"):
                    arrow_tri(dr, cx, y + bh / 2 - 45, 24, arrow == "up", RED if arrow == "up" else RED)
            sfx.append((st, "pop", 0.5))
        if i < n - 1:
            ka = ease(prog(t, st + 0.3, 0.35))
            if ka > 0:
                ax = x + bw + 15; dr.line([(ax, y), (ax + 60 * ka, y)], fill=rgba(GOLD, 1), width=6)
                if ka > 0.9: arrow_tri(dr, ax + 60, y, 16, True, GOLD) if False else dr.polygon([(ax + 72, y), (ax + 52, y - 16), (ax + 52, y + 16)], fill=rgba(GOLD, 1))
        x += bw + 90
    return sfx

def sc_doc(img, dr, t, D, p):
    # página de "documento" com trecho grifado (estilo referência 1)
    text = p["text"]; hl = p.get("hl", "")
    pw, ph = 1300, 700; px, py = W / 2 - pw / 2, H / 2 - ph / 2 + 30
    a = ease(prog(t, 0, 0.4))
    dr.rectangle([px + 14, py + 14, px + pw + 14, py + ph + 14], fill=rgba((0, 0, 0), 0.35 * a))
    dr.rectangle([px, py, px + pw, py + ph], fill=rgba((252, 252, 250), a))
    dr.rectangle([px, py, px + pw, py + 90], fill=rgba((28, 52, 92), a))
    dr.text((px + 40, py + 45), p.get("head", "ANÁLISE"), font=F("bold", 34), fill=rgba(WHITE, a), anchor="lm")
    f = F("serif", 54); lines = wrap(text, f, pw - 120)
    hs = text.find(hl) if hl else -1; he = hs + len(hl)
    # posição de cada caractere para o grifo
    y = py + 190; pos = 0; boxes = []
    for ln in lines:
        st = text.find(ln, pos); x = px + 60
        if hs >= 0:
            a0, a1 = max(hs, st), min(he, st + len(ln))
            if a1 > a0:
                bx0 = x + tw(f, ln[: a0 - st]); bx1 = x + tw(f, ln[: a1 - st]); boxes.append((bx0, y - 44, bx1, y + 22))
        pos = st + len(ln); y += 78
    hk = ease_io(prog(t, 0.7, 1.2)); total = sum(b[2] - b[0] for b in boxes); acc = 0
    for b in boxes:
        w = b[2] - b[0]; vis = clamp((hk * total - acc) / w if w else 0); acc += w
        if vis > 0: dr.rectangle([b[0], b[1], b[0] + w * vis, b[3]], fill=rgba((120, 170, 255), 0.55))
    y = py + 190
    for ln in lines:
        dr.text((px + 60, y), ln, font=f, fill=rgba(INK, a), anchor="ls"); y += 78
    if p.get("fonte"): dr.text((px + pw - 40, py + ph - 40), p["fonte"], font=F("reg", 26), fill=rgba((110, 110, 110), a), anchor="rm")
    return [(0.0, "whoosh", 0.5), (0.7, "typing", 0.25)]

def sc_map(img, dr, t, D, p):
    v0, v1 = p["from"], p.get("to", p["from"])
    k = ease_io(prog(t, 0, p.get("move", D * 0.8)))
    # zoom em escala logarítmica para o movimento ficar natural
    wd = math.exp(math.log(v0[2]) + (math.log(v1[2]) - math.log(v0[2])) * k)
    view = (v0[0] + (v1[0] - v0[0]) * k, v0[1] + (v1[1] - v0[1]) * k, wd)
    hl = {c: {"red": RED, "green": GREEN, "gold": GOLD, "blue": BLUE}[col] for c, col in p.get("hl", {}).items()}
    P = draw_map(img, view, hl, t, hl_alpha=ease(prog(t, p.get("hl_at", 0.6), 0.6)))
    sfx = [(0.0, "whoosh_down", 0.5)]
    for i, lab in enumerate(p.get("labels", [])):
        st = lab.get("at", 0.9 + i * 0.6)
        callout(dr, P(*lab["ll"]), lab["text"], t, start=st, dx=lab.get("dx", 180), dy=lab.get("dy", -120))
        sfx.append((st, "pop", 0.4))
    for i, ar in enumerate(p.get("arrows", [])):
        st = ar.get("at", 1.0 + i * 0.5)
        curve_arrow(dr, P(*ar["a"]), P(*ar["b"]), ease(prog(t, st, 1.2)), color={"gold": GOLD, "red": RED, "green": GREEN}[ar.get("color", "gold")])
        sfx.append((st, "whoosh", 0.35))
    if p.get("radar"):
        rl = Image.new("RGBA", (W, H)); radar_overlay(ImageDraw.Draw(rl), P(*p["radar"]["ll"]), t, p["radar"].get("r", 260)); img.alpha_composite(rl)
    for j, path in enumerate(p.get("ships", [])):
        a_, b_ = P(*path[0]), P(*path[1])
        for m in range(4):
            u = ((t * 0.08 + m * 0.25 + j * 0.13) % 1.0)
            sx_, sy_ = a_[0] + (b_[0] - a_[0]) * u, a_[1] + (b_[1] - a_[1]) * u
            dr.ellipse([sx_ - 9, sy_ - 9, sx_ + 9, sy_ + 9], fill=rgba(GOLD, 1), outline=rgba((0, 0, 0), 1))
        dr.line([a_, b_], fill=rgba(GOLD, 0.35), width=3)
    if p.get("title"): kicker(dr, p["title"], 140, 120, t=t)
    return sfx

def sc_timer(img, dr, t, D, p):
    tot = p.get("seconds", 1800); k = ease_io(prog(t, 0.6, D - 1.0))
    rem = tot * (1 - 0.9 * k); mm, ss = divmod(int(rem), 60)
    flash = 0.5 + 0.5 * math.sin(t * 6)
    label_box(dr, (W / 2, 230), "NEGOCIAÇÕES SUSPENSAS", t, bgc=ACCENT, size=44, alpha=prog(t, 0, 0.3))
    dr.text((W / 2, H / 2 + 40), f"{mm:02d}:{ss:02d}", font=F("black", 300), fill=rgba(WHITE, 1), anchor="mm")
    dr.text((W / 2, H / 2 + 260), p.get("label", "pausa obrigatória na B3"), font=F("med", 48), fill=rgba(MUTED, 1), anchor="mm")
    dr.ellipse([W / 2 - 520, H / 2 - 120, W / 2 - 490, H / 2 - 90], fill=rgba(ACCENT, flash))
    return [(0.0, "alarm", 0.45)] + [(0.6 + i * 0.5, "tick", 0.5) for i in range(int((D - 1) / 0.5))]

def sc_stamp(img, dr, t, D, p):
    s = 1 + 1.5 * (1 - ease(prog(t, 0.2, 0.25)))
    a = prog(t, 0.2, 0.1)
    if a > 0:
        lay = Image.new("RGBA", (1400, 400)); ld = ImageDraw.Draw(lay)
        ld.rounded_rectangle([10, 10, 1390, 390], radius=20, outline=rgba(ACCENT, 1), width=16)
        fs = 120
        while fs > 50 and tw(F("black", fs), p["text"]) > 1260: fs -= 4
        ld.text((700, 150), p["text"], font=F("black", fs), fill=rgba(ACCENT, 1), anchor="mm")
        if p.get("sub"): ld.text((700, 290), p["sub"], font=F("bold", 52), fill=rgba(WHITE, 1), anchor="mm")
        lay = lay.rotate(-4, expand=True, resample=Image.BICUBIC)
        lay = lay.resize((int(lay.width * s), int(lay.height * s)), Image.BILINEAR)
        if a < 1: lay.putalpha(lay.getchannel("A").point(lambda v: int(v * a)))
        ox, oy = int(W / 2 - lay.width / 2), int(H / 2 - lay.height / 2)
        if ox < 0 or oy < 0:
            lay = lay.crop((max(0, -ox), max(0, -oy), max(0, -ox) + min(W, lay.width), max(0, -oy) + min(H, lay.height)))
            ox, oy = max(0, ox), max(0, oy)
        img.alpha_composite(lay, (ox, oy))
    if p.get("foot"):
        fa = prog(t, 1.0, 0.4)
        dr.text((W / 2, H - 140), p["foot"], font=F("med", 46), fill=rgba(WHITE, fa), anchor="mm")
    return [(0.0, "alarm", 0.4), (0.4, "boom", 0.8)]

def sc_versus(img, dr, t, D, p):
    L, R = p["left"], p["right"]
    for i, (side, cx) in enumerate([(L, W * 0.28), (R, W * 0.72)]):
        st = 0.2 + i * 0.6; k = back(prog(t, st, 0.5)); a = clamp(k)
        col = RED if side["dir"] == "down" else GREEN
        dr.text((cx, H / 2 - 170), side["name"], font=F("black", 90), fill=rgba(WHITE, a), anchor="mm")
        off = math.sin(t * 3) * 10 * (1 if side["dir"] == "up" else -1)
        arrow_tri(dr, cx, H / 2 + 60 + off, 110 * clamp(k, 0, 1.2), side["dir"] == "up", col, a)
        dr.text((cx, H / 2 + 260), side.get("val", ""), font=F("black", 70), fill=rgba(col, a), anchor="mm")
    a = prog(t, 0.6, 0.3)
    dr.line([(W / 2, 220), (W / 2, H - 220)], fill=rgba(MUTED, a), width=3)
    return [(0.0, "whoosh", 0.5), (0.2, "hit", 0.5), (0.8, "hit", 0.5)]

def sc_grid(img, dr, t, D, p):
    items = p["items"]; n = len(items); cols = 2 if n == 4 else n
    rows = math.ceil(n / cols); tw_, th = 760, 240
    if p.get("title"):
        a = ease(prog(t, 0, 0.4)); dr.text((W / 2, 170), p["title"], font=F("black", 64), fill=rgba(WHITE, a), anchor="mm")
    sfx = [(0.0, "whoosh", 0.5)]
    for i, it in enumerate(items):
        r, c = divmod(i, cols)
        cx = W / 2 + (c - (cols - 1) / 2) * (tw_ + 40) if cols > 1 else W / 2
        if cols == n and n == 3: cx = W / 2 + (c - 1) * 560; tw2 = 500
        else: tw2 = tw_
        cy = H / 2 + 60 + (r - (rows - 1) / 2) * (th + 40)
        st = 0.3 + i * p.get("gap", 0.45); k = back(prog(t, st, 0.4))
        if k <= 0: continue
        s = clamp(k, 0, 1.15)
        dr.rounded_rectangle([cx - tw2 / 2 * s, cy - th / 2 * s, cx + tw2 / 2 * s, cy + th / 2 * s], radius=22,
                             fill=rgba((24, 40, 34), 1), outline=rgba(ACCENT, 1), width=4)
        if s > 0.7:
            big, small = (it if isinstance(it, list) else [it, ""])
            fs = 62
            while fs > 30 and tw(F("black", fs), big) > tw2 - 60: fs -= 2
            dr.text((cx, cy - (25 if small else 0)), big, font=F("black", fs), fill=rgba(WHITE, 1), anchor="mm")
            if small: dr.text((cx, cy + 55), small, font=F("med", 34), fill=rgba(MUTED, 1), anchor="mm")
        sfx.append((st, "pop", 0.5))
    return sfx

def sc_outro(img, dr, t, D, p):
    a = ease(prog(t, 0, 0.5))
    dr.text((W / 2, H / 2 - 160), BRAND, font=F("black", 110), fill=rgba(WHITE, a), anchor="mm")
    dr.rectangle([W / 2 - 300 * a, H / 2 - 80, W / 2 + 300 * a, H / 2 - 72], fill=rgba(ACCENT, 1))
    k = back(prog(t, 1.0, 0.4)); clicked = t > p.get("click", 3.2)
    if k > 0:
        bw, bh = 560 * k, 130 * k; cx, cy = W / 2, H / 2 + 120
        dr.rounded_rectangle([cx - bw / 2, cy - bh / 2, cx + bw / 2, cy + bh / 2], radius=int(20 * k) + 1,
                             fill=rgba((90, 90, 90) if clicked else ACCENT, 1))
        if k > 0.7: dr.text((cx, cy + 3), "INSCRITO ✓" if clicked else "INSCREVA-SE", font=F("black", 58) if not clicked else F("sym", 54), fill=rgba(WHITE if clicked else ON_ACCENT, 1), anchor="mm")
        # cursor
        ck = ease(prog(t, 2.2, 0.9)); mx = W / 2 + 500 - 380 * ck; my = H / 2 + 420 - 270 * ck
        if t > 2.2:
            dr.polygon([(mx, my), (mx, my + 60), (mx + 16, my + 46), (mx + 30, my + 76), (mx + 42, my + 70), (mx + 28, my + 42), (mx + 48, my + 42)],
                       fill=rgba(WHITE, 1), outline=rgba((0, 0, 0), 1))
    return [(0.0, "whoosh", 0.5), (1.0, "pop", 0.6), (p.get("click", 3.2), "ding", 0.6)]


# ================= ESTILO CINEMATOGRÁFICO / INVESTIGATIVO =================
NAVY = (31, 45, 74); ORANGE = (214, 96, 52); CREAM = (240, 230, 210)

@lru_cache(None)
def newsprint():
    """Fundo de jornal envelhecido (colunas de texto, manchetes, manchas de tinta)."""
    rng = np.random.default_rng(11)
    img = Image.new("RGB", (W, H), (226, 222, 212)); d = ImageDraw.Draw(img)
    f = F("serif", 15); fb = F("serif", 40)
    words = ("mercado bolsa economia governo juros dólar investidores crise pregão índice fiscal dívida banco "
             "central inflação emprego empresas ações queda alta semana relatório análise contas").split()
    x = 16
    while x < W:
        colw = int(rng.integers(230, 330)); y = 14
        while y < H:
            if rng.random() < 0.1:
                d.text((x, y), " ".join(rng.choice(words, 2)).upper(), font=fb, fill=(60, 58, 55)); y += 56
            else:
                for _ in range(int(rng.integers(6, 15))):
                    d.text((x, y), " ".join(rng.choice(words, int(rng.integers(4, 7)))), font=f, fill=(105, 101, 96)); y += 19
                y += 14
        x += colw + 24
    a = np.asarray(img).astype(np.float32)
    blot = np.asarray(Image.fromarray((rng.random((18, 32)) * 255).astype(np.uint8)).resize((W, H), Image.BICUBIC)).astype(np.float32) / 255
    a = a * (0.78 + 0.3 * blot[..., None]) + rng.normal(0, 6, (H, W, 1))
    g = a.mean(2, keepdims=True); a = g * 0.85 + a * 0.15
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)).convert("RGBA")

@lru_cache(None)
def grunge(w, h, seed=3):
    rng = np.random.default_rng(seed)
    n = np.asarray(Image.fromarray((rng.random((h // 8, w // 8)) * 255).astype(np.uint8)).resize((w, h), Image.BICUBIC)).astype(np.float32) / 255
    fine = rng.random((h, w))
    m = np.clip((n * 0.88 + fine * 0.12 - 0.12) * 4, 0, 1)
    return Image.fromarray((m * 255).astype(np.uint8))

def torn_mask(w, h, seed=0, rough=12):
    rng = np.random.default_rng(seed); pts = []
    for x in np.linspace(0, w, 48): pts.append((x, rng.uniform(0, rough)))
    for y in np.linspace(0, h, 28): pts.append((w - rng.uniform(0, rough), y))
    for x in np.linspace(w, 0, 48): pts.append((x, h - rng.uniform(0, rough)))
    for y in np.linspace(h, 0, 28): pts.append((rng.uniform(0, rough), y))
    m = Image.new("L", (int(w), int(h)), 0); ImageDraw.Draw(m).polygon(pts, fill=255); return m

def paper_card(w, h, color=CREAM, seed=0):
    card = Image.new("RGBA", (int(w), int(h)), color + (255,))
    card.putalpha(torn_mask(w, h, seed)); return card

def light_sweep(img, t, start=0.2, dur=1.4, strength=0.35):
    k = prog(t, start, dur)
    if k <= 0 or k >= 1: return
    ov = Image.new("RGBA", (W, H)); d = ImageDraw.Draw(ov)
    cx = -600 + (W + 1200) * ease_io(k)
    for i, wd in enumerate((260, 160, 70)):
        a = strength * (0.35 + i * 0.3)
        d.polygon([(cx - wd, 0), (cx + wd, 0), (cx + wd - 500, H), (cx - wd - 500, H)], fill=(255, 245, 225, int(a * 80)))
    img.alpha_composite(ov)

def dust(dr, t, n=40, seed=0, color=WHITE):
    rng = np.random.default_rng(seed + int(t * 8))
    for _ in range(n):
        x, y = rng.random() * W, rng.random() * H; r = rng.random() * 2.2 + 0.5
        dr.ellipse([x - r, y - r, x + r, y + r], fill=rgba(color, 0.25 + rng.random() * 0.4))

def condensed_text(text, size, color, cond=0.78, grunge_on=True):
    f = F("black", size); w = int(tw(f, text)) + 40; h = int(size * 1.35)
    lay = Image.new("RGBA", (w, h)); ImageDraw.Draw(lay).text((20, h / 2), text, font=f, fill=color + (255,), anchor="lm")
    lay = lay.resize((max(1, int(w * cond)), h), Image.LANCZOS)
    if grunge_on:
        g = grunge(lay.width, lay.height, 7)
        lay.putalpha(Image.fromarray((np.asarray(lay.getchannel("A")).astype(np.float32) * (0.78 + 0.22 * np.asarray(g) / 255)).astype(np.uint8)))
    return lay

def sc_headline(img, dr, t, D, p):
    """Manchete de jornal investigativo sobre fundo de jornal."""
    img.alpha_composite(newsprint())
    k = ease(prog(t, 0.0, 0.6))
    cw, ch = 1500, 420
    card = paper_card(cw, ch, (246, 242, 232), seed=len(p["title"]))
    cd = ImageDraw.Draw(card)
    cd.text((70, 70), p.get("kicker", "INVESTIGAÇÃO"), font=F("bold", 30), fill=rgba(ACCENT, 1), anchor="lm")
    cd.text((cw - 70, 70), p.get("date", ""), font=F("med", 28), fill=rgba((90, 90, 90), 1), anchor="rm")
    for x in range(70, cw - 70, 14): cd.ellipse([x, 108, x + 4, 112], fill=rgba((120, 120, 120), 1))
    f = F("serif", 92); lines = wrap(p["title"].replace("*", ""), f, cw - 140)
    n_chars = sum(len(l) for l in lines); shown = int(n_chars * prog(t, 0.4, min(1.8, n_chars * 0.04))); c = 0
    y = 200 if len(lines) > 1 else 240
    for ln in lines:
        vis = ln[: max(0, shown - c)]; c += len(ln)
        cd.text((70, y), vis, font=f, fill=rgba(INK, 1), anchor="lm"); y += 110
    ul = ease(prog(t, 0.4 + min(1.8, n_chars * 0.04), 0.5))
    cd.rectangle([70, ch - 70, 70 + (cw - 140) * 0.45 * ul, ch - 58], fill=rgba(ACCENT, 1))
    rot = -2 + 1.5 * (1 - k)
    card = card.rotate(rot, expand=True, resample=Image.BICUBIC)
    sh = Image.new("RGBA", card.size, (0, 0, 0, 0)); sh.putalpha(card.getchannel("A").point(lambda v: v * 0.45))
    sh = sh.filter(ImageFilter.GaussianBlur(14))
    x0 = int(W / 2 - card.width / 2); y0 = int(H / 2 - card.height / 2 + (1 - k) * 80)
    img.alpha_composite(sh, (x0 + 18, y0 + 24)); img.alpha_composite(card, (x0, y0))
    light_sweep(img, t, 0.3, 1.6, 0.4)
    return [(0.0, "whoosh", 0.4), (0.4, "typing", 0.35), (0.0, "paper", 0.5)]

def sc_cine(img, dr, t, D, p):
    """Abertura cinematográfica: faixas vermelhas diagonais, letras grandes gastas, poeira."""
    img.paste((14, 12, 12, 255), (0, 0, W, H))
    rng = np.random.default_rng(4)
    ov = Image.new("RGBA", (W, H)); od = ImageDraw.Draw(ov)
    for i in range(5):
        st = 0.05 + i * 0.12; k = ease(prog(t, st, 0.7))
        off = (1 - k) * 2200 * (1 if i % 2 else -1)
        y = 140 + i * 190 + math.sin(i) * 40; th = 90 + 60 * rng.random()
        col = ((200 + int(55 * rng.random()), 150 + int(40 * rng.random()), 0, 235) if ACCENT == YELLOW else (150 + int(60 * rng.random()), 20, 28, 235))
        od.polygon([(-400 + off, y + 260), (W + 400 + off, y - 260), (W + 400 + off, y - 260 + th), (-400 + off, y + 260 + th)], fill=col)
    g = grunge(W, H, 9); ov.putalpha(Image.fromarray((np.asarray(ov.getchannel("A")).astype(np.float32) * np.asarray(g) / 255).astype(np.uint8)))
    img.alpha_composite(ov)
    band = Image.new("RGBA", (W, H)); bd = ImageDraw.Draw(band)
    for i in range(60):
        yy = H / 2 - 330 + i * 11; aa = int(150 * math.sin(math.pi * i / 59))
        bd.rectangle([0, yy, W, yy + 11], fill=(0, 0, 0, aa))
    img.alpha_composite(band)
    s = 1.12 - 0.1 * ease(prog(t, 0.3, D)); a = prog(t, 0.5, 0.4)
    y = H / 2 - 40 * (len(p["lines"]) - 1)
    for i, ln in enumerate(p["lines"]):
        accent = ln.startswith("*"); lay = condensed_text(ln.strip("*"), int((200 if accent else 150) * s), (255, 255, 255) if accent else (215, 205, 200))
        if a < 1: lay.putalpha(lay.getchannel("A").point(lambda v: int(v * a)))
        img.alpha_composite(lay, (int(W / 2 - lay.width / 2), int(y - lay.height / 2 + i * 170 * s - 60 * (len(p["lines"]) - 1))))
    if p.get("sub"):
        sa = prog(t, 1.2, 0.5)
        dr.text((W / 2, H - 230), p["sub"], font=F("bold", 44), fill=rgba((230, 225, 220), sa), anchor="mm")
    light_sweep(img, t, 0.9, 1.4, 0.5)
    dust(dr, t, 60, 1, (255, 220, 120))
    return [(0.0, "boom", 0.6), (0.05, "whoosh", 0.4), (0.5, "hit", 0.4)]

def sc_burst(img, dr, t, D, p):
    """Ilustração editorial: raios de explosão em azul/laranja e cartão de papel rasgado com número/texto."""
    rot = t * 6; k = back(prog(t, 0.1, 0.5))
    ov = Image.new("RGBA", (W, H)); od = ImageDraw.Draw(ov)
    for i in range(36):
        a0 = math.radians(rot + i * 10); a1 = a0 + math.radians(4)
        col = (ACCENT if i % 2 else (28, 28, 28)) if ACCENT == YELLOW else (ORANGE if i % 2 else NAVY)
        od.polygon([(W / 2, H / 2), (W / 2 + 1400 * math.cos(a0), H / 2 + 1400 * math.sin(a0)),
                    (W / 2 + 1400 * math.cos(a1), H / 2 + 1400 * math.sin(a1))], fill=col + (int(150 * clamp(k)),))
    img.alpha_composite(ov)
    if k > 0:
        cw, ch = int(1000 * clamp(k, 0, 1.2)), int(520 * clamp(k, 0, 1.2))
        if cw > 20:
            card = paper_card(cw, ch, CREAM, 5); cd = ImageDraw.Draw(card)
            v, _ = count_val(p, t) if "to" in p else (None, 1)
            big = (p.get("prefix", "") + fmt_br(v, p.get("dec", 0)) + p.get("suffix", "")) if v is not None else p.get("big", "")
            bfs = int(170 * cw / 1000)
            while bfs > 20 and tw(F("black", bfs), big) > cw * 0.88: bfs -= 4
            cd.text((cw / 2, ch * 0.42), big, font=F("black", bfs), fill=rgba(((14, 14, 14) if ACCENT == YELLOW else (ORANGE if p.get("color") != "navy" else NAVY)), 1), anchor="mm")
            lfs = int(44 * cw / 1000)
            while lfs > 12 and tw(F("bold", lfs), p.get("label", "")) > cw * 0.9: lfs -= 2
            cd.text((cw / 2, ch * 0.78), p.get("label", ""), font=F("bold", lfs), fill=rgba((60, 60, 60) if ACCENT == YELLOW else NAVY, 1), anchor="mm")
            img.alpha_composite(card.rotate(-3, expand=True, resample=Image.BICUBIC), (int(W / 2 - cw / 2 - 20), int(H / 2 - ch / 2 - 20)))
    return [(0.0, "whoosh", 0.4), (0.1, "hit", 0.45)]

def sc_photo(img, dr, t, D, p):
    """Cartão com ano e texto em ângulo de câmera (documentário P&B). Usa imagem se houver 'img'."""
    img.paste((20, 20, 22, 255), (0, 0, W, H))
    dust(dr, t, 50, 2)
    return []

def sc_broll(img, dr, t, D, p):
    """Foto/vídeo em tela cheia. 'caption' = tarja de TV (lower third) opcional."""
    if p.get("caption"):
        k = ease(prog(t, 0.4, 0.5)); f = F("bold", 40); w = tw(f, p["caption"]) + 70
        x0 = 90 - (1 - k) * (w + 120); y0 = H - 230
        dr.rectangle([x0, y0, x0 + 14, y0 + 76], fill=rgba(ACCENT, 1))
        dr.rectangle([x0 + 14, y0, x0 + 14 + w, y0 + 76], fill=rgba((12, 14, 16), 0.85))
        dr.text((x0 + 14 + 35, y0 + 40), p["caption"], font=f, fill=rgba(WHITE, 1), anchor="lm")
        if p.get("sub"):
            dr.rectangle([x0 + 14, y0 + 76, x0 + 14 + w * 0.8, y0 + 120], fill=rgba(ACCENT, 0.9 * k))
            dr.text((x0 + 49, y0 + 99), p["sub"], font=F("med", 28), fill=rgba(ON_ACCENT, k), anchor="lm")
    return [(0.0, "whoosh", 0.3)]

def sc_phone(img, dr, t, D, p):
    """Celular com app de banco genérico mostrando um alerta (ex.: serviço suspenso)."""
    k = back(prog(t, 0.05, 0.6)); ph_w, ph_h = 520, 1000
    phone = Image.new("RGBA", (ph_w, ph_h)); pd = ImageDraw.Draw(phone, "RGBA")
    pd.rounded_rectangle([0, 0, ph_w, ph_h], radius=70, fill=(18, 18, 20, 255), outline=(90, 90, 96, 255), width=6)
    pd.rounded_rectangle([22, 22, ph_w - 22, ph_h - 22], radius=54, fill=(245, 246, 250, 255))
    pd.rounded_rectangle([ph_w / 2 - 70, 34, ph_w / 2 + 70, 62], radius=14, fill=(18, 18, 20, 255))
    pd.rectangle([22, 90, ph_w - 22, 230], fill=NAVY + (255,))
    pd.text((60, 140), p.get("app", "MEU BANCO"), font=F("bold", 34), fill=(255, 255, 255), anchor="lm")
    pd.text((60, 190), "Saldo disponível", font=F("reg", 24), fill=(200, 210, 230), anchor="lm")
    bal = p.get("saldo", "••••••")
    pd.text((60, 290), bal, font=F("black", 64), fill=(30, 30, 30), anchor="lm")
    for i, lab in enumerate(["Pix / Transferir", "Pagar", "Extrato"]):
        y = 400 + i * 110
        pd.rounded_rectangle([50, y, ph_w - 50, y + 84], radius=18, fill=(230, 232, 240, 255))
        pd.text((80, y + 42), lab, font=F("med", 30), fill=(120, 120, 130), anchor="lm")
    a = prog(t, p.get("alert_at", 1.2), 0.25)
    if a > 0:
        sh = back(prog(t, p.get("alert_at", 1.2), 0.4))
        bw, bh = int((ph_w - 70) * clamp(sh, 0.05, 1.1)), int(380 * clamp(sh, 0.05, 1.1))
        pd.rounded_rectangle([22, 22, ph_w - 22, ph_h - 22], radius=54, fill=(0, 0, 0, int(120 * a)))
        bx, by = ph_w / 2 - bw / 2, ph_h / 2 - bh / 2
        pd.rounded_rectangle([bx, by, bx + bw, by + bh], radius=26, fill=(255, 255, 255, 255))
        if sh > 0.7:
            pd.ellipse([ph_w / 2 - 40, by + 30, ph_w / 2 + 40, by + 110], fill=RED + (255,))
            pd.text((ph_w / 2, by + 72), "!", font=F("black", 60), fill=(255, 255, 255), anchor="mm")
            for j, ln in enumerate(wrap(p.get("alert", "Serviço indisponível"), F("bold", 34), bw - 60)):
                pd.text((ph_w / 2, by + 160 + j * 44), ln, font=F("bold", 34), fill=(30, 30, 30), anchor="mm")
            pd.text((ph_w / 2, by + bh - 40), p.get("alert_sub", "Tente novamente mais tarde"), font=F("reg", 24), fill=(120, 120, 120), anchor="mm")
    sc = 0.85 * clamp(k, 0.05, 1.1); yaw = 0.18 * math.sin(t * 0.8)
    lay = warp3d(phone.resize((int(ph_w * sc), int(ph_h * sc)), Image.BICUBIC), yaw)
    img.alpha_composite(lay, (int(W * 0.68 - lay.width / 2), int(H / 2 - lay.height / 2 + 20)))
    if p.get("title"):
        ta = ease(prog(t, 0.3, 0.5)); f = F("black", 76)
        for j, ln in enumerate(wrap(p["title"], f, 820)):
            dr.text((140, H / 2 - 80 + j * 92), ln, font=f, fill=rgba(WHITE, ta), anchor="lm")
    if p.get("sub"):
        label_box(dr, (140, H / 2 + 150), p["sub"], t, bgc=ACCENT, size=34, anchor="lm", alpha=prog(t, 0.8, 0.4))
    return [(0.0, "whoosh", 0.4), (p.get("alert_at", 1.2), "pop", 0.6), (p.get("alert_at", 1.2), "glitch", 0.3)]

def find_coeffs(dst, src):
    A = []
    for (x, y), (X, Y) in zip(dst, src):
        A.append([x, y, 1, 0, 0, 0, -X * x, -X * y]); A.append([0, 0, 0, x, y, 1, -Y * x, -Y * y])
    b = np.array(src).reshape(8)
    return np.linalg.solve(np.array(A, float), b).tolist()

def tilt_frame(inner, t, D, p):
    """Câmera em ângulo: a cena vira um cartão inclinado em 3D, com fundo desfocado e poeira."""
    small = inner.resize((W // 6, H // 6), Image.BILINEAR).filter(ImageFilter.GaussianBlur(3)).resize((W, H), Image.BILINEAR)
    bgimg = Image.blend(small.convert("RGB"), Image.new("RGB", (W, H), (0, 0, 0)), 0.55).convert("RGBA")
    k = ease_io(t / max(D, 0.1)); side = p.get("tilt_side", 1)
    yaw = (0.22 - 0.12 * k) * side  # rotação aparente
    sc = 0.80 + 0.05 * k
    cw, ch = W * sc, H * sc; cx, cy = W / 2 + 40 * side * (1 - k), H / 2
    dz = yaw * cw * 0.5
    quad = [(cx - cw / 2, cy - ch / 2 + dz * 0.6), (cx + cw / 2, cy - ch / 2 - dz * 0.6),
            (cx + cw / 2, cy + ch / 2 + dz * 0.6), (cx - cw / 2, cy + ch / 2 - dz * 0.6)]
    coeffs = find_coeffs(quad, [(0, 0), (W, 0), (W, H), (0, H)])
    rgba_in = inner.convert("RGBA")
    warped = rgba_in.transform((W, H), Image.PERSPECTIVE, coeffs, Image.BILINEAR)
    m = Image.new("L", (W, H), 0); ImageDraw.Draw(m).polygon(quad, fill=255)
    sh = Image.new("RGBA", (W, H), (0, 0, 0, 0)); ImageDraw.Draw(sh).polygon([(x + 30, y + 40) for x, y in quad], fill=(0, 0, 0, 170))
    sh = sh.resize((W // 4, H // 4)).filter(ImageFilter.GaussianBlur(6)).resize((W, H))
    bgimg.alpha_composite(sh); bgimg.paste(warped, (0, 0), m)
    d = ImageDraw.Draw(bgimg, "RGBA"); dust(d, t, 35, 3)
    if p.get("year"):
        a = prog(t, 0.3, 0.5)
        label_box(d, (cx - cw / 2 + 140, cy - ch / 2 + 20), p["year"], t, bgc=(0, 0, 0), size=48, alpha=a)
    return bgimg

# ================= MOTION 3D =================
def extruded_text(text, size, face=(245, 245, 245), side=(120, 20, 28), depth=22, font="black"):
    """Texto com extrusão 3D (profundidade + face com degradê)."""
    f = F(font, size); w = int(tw(f, text)) + 80 + depth; h = int(size * 1.45) + depth
    mask = Image.new("L", (w, h)); ImageDraw.Draw(mask).text((40, h / 2 - depth / 2), text, font=f, fill=255, anchor="lm")
    out = Image.new("RGBA", (w, h))
    for k in range(depth, 0, -1):
        sh = 0.45 + 0.55 * (1 - k / depth)
        col = tuple(int(c * sh) for c in side) + (255,)
        layer = Image.new("RGBA", (w, h), col); out.paste(layer, (k, k), mask)
    grad = np.linspace(1.0, 0.72, h)[:, None, None] * np.array(face, float)[None, None]
    facei = Image.fromarray(np.clip(grad.repeat(w, 1), 0, 255).astype(np.uint8)).convert("RGBA")
    out.paste(facei, (0, 0), mask)
    # brilho na borda superior
    hl = Image.new("RGBA", (w, h), (255, 255, 255, 90)); edge = mask.filter(ImageFilter.FIND_EDGES)
    out.paste(hl, (0, -1), edge)
    return out

def warp3d(layer, yaw, pitch=0.0):
    """Gira um layer em 3D (perspectiva) em torno do centro."""
    w, h = layer.size; dz = yaw * w * 0.5; dp = pitch * h * 0.5
    quad = [(0 + dp * 0.3, 0 + dz * 0.5), (w - dp * 0.3, 0 - dz * 0.5), (w + dp * 0.3, h + dz * 0.5), (0 - dp * 0.3, h - dz * 0.5)]
    pad = int(abs(dz) + abs(dp)) + 10
    quad = [(x + pad, y + pad) for x, y in quad]
    coeffs = find_coeffs(quad, [(0, 0), (w, 0), (w, h), (0, h)])
    return layer.transform((w + 2 * pad, h + 2 * pad), Image.PERSPECTIVE, coeffs, Image.BICUBIC)

def sc_text3d(img, dr, t, D, p):
    """Título em letras 3D extrudadas que giram no espaço, com reflexo e partículas."""
    lines = p["lines"]; n = len(lines)
    if not p.get("_media"):
        # piso com perspectiva (grade)
        ov = Image.new("RGBA", (W, H)); od = ImageDraw.Draw(ov)
        hz = H * 0.62
        for i in range(-20, 21):
            od.line([(W / 2 + i * 40, hz), (W / 2 + i * 260, H)], fill=ACCENT + (50,), width=2)
        for j in range(12):
            yy = hz + (H - hz) * (j / 12) ** 1.8; od.line([(0, yy), (W, yy)], fill=ACCENT + (40,), width=2)
        img.alpha_composite(ov)
    yaw = (p.get("yaw", 0.28)) * math.cos(t * 0.9) * (1 - 0.5 * ease(prog(t, 0, D)))
    total_h = 0; layers = []
    for i, ln in enumerate(lines):
        acc = ln.startswith("*")
        lay = extruded_text(ln.strip("*"), p.get("size", 150) if not acc else int(p.get("size", 150) * 1.1),
                            face=(255, 255, 255) if not acc else (255, 214, 40) if ACCENT == YELLOW else (255, 90, 100),
                            side=((110, 80, 0) if ACCENT == YELLOW else (90, 14, 22)) if acc else (60, 66, 72))
        k = back(prog(t, 0.15 + i * 0.25, 0.6))
        if k <= 0.01: layers.append(None); continue
        lay = warp3d(lay, yaw + (1 - clamp(k)) * 0.8 * (1 if i % 2 else -1), 0)
        if k != 1: lay = lay.resize((max(1, int(lay.width * clamp(k, 0.05, 1.2))), max(1, int(lay.height * clamp(k, 0.05, 1.2)))), Image.BICUBIC)
        layers.append(lay); total_h += lay.height * 0.82
    y = H / 2 - total_h / 2 - 30
    for lay in layers:
        if lay is None: continue
        x = int(W / 2 - lay.width / 2)
        # sombra difusa
        sh = Image.new("RGBA", lay.size, (0, 0, 0, 0)); sh.putalpha(lay.getchannel("A").point(lambda v: v * 0.5))
        sh = sh.resize((max(1, lay.width // 4), max(1, lay.height // 4))).filter(ImageFilter.GaussianBlur(4)).resize(lay.size)
        img.alpha_composite(sh, (x + 20, int(y) + 30)); img.alpha_composite(lay, (x, int(y)))
        y += lay.height * 0.82
    if p.get("sub"):
        a = ease(prog(t, 0.9, 0.5))
        label_box(dr, (W / 2, H - 170), p["sub"], t, bgc=ACCENT, size=40, alpha=a)
    light_sweep(img, t, 0.6, 1.5, 0.4)
    dust(dr, t, 45, 5, (255, 200, 200))
    return [(0.0, "boom", 0.5), (0.15, "whoosh", 0.45), (0.4, "whoosh", 0.35)]

def sc_globe(img, dr, t, D, p):
    """Globo 3D girando (projeção ortográfica) com países destacados."""
    countries, _ = geo()
    k = ease_io(prog(t, 0, p.get("move", D * 0.85)))
    lon0 = p["from"][0] + (p["to"][0] - p["from"][0]) * k; lat0 = p["from"][1] + (p["to"][1] - p["from"][1]) * k
    R = p.get("r", 430) * (1 + 0.08 * k); cx, cy = W / 2, H / 2 + 20
    # brilho da atmosfera
    ov = Image.new("RGBA", (W, H)); od = ImageDraw.Draw(ov)
    for i in range(18, 0, -1):
        od.ellipse([cx - R - i * 4, cy - R - i * 4, cx + R + i * 4, cy + R + i * 4], fill=(60, 140, 200, int(6 + 3 * (18 - i) / 18 * 4)))
    img.alpha_composite(ov)
    yy, xx = np.mgrid[-R:R, -R:R].astype(np.float32)
    dd = np.sqrt(xx ** 2 + yy ** 2) / R
    shade = np.clip(1.0 - 0.55 * dd ** 2 - 0.25 * (xx + yy) / (2 * R), 0.25, 1.1)
    sph = np.stack([12 * shade, 34 * shade, 52 * shade, (dd <= 1) * 255], -1).astype(np.uint8)
    img.alpha_composite(Image.fromarray(sph, "RGBA"), (int(cx - R), int(cy - R)))
    l0, p0 = math.radians(lon0), math.radians(lat0)
    def proj(arr):
        lam = np.radians(arr[:, 0]) - l0; phi = np.radians(arr[:, 1])
        cosc = math.sin(p0) * np.sin(phi) + math.cos(p0) * np.cos(phi) * np.cos(lam)
        x = np.cos(phi) * np.sin(lam); y = math.cos(p0) * np.sin(phi) - math.sin(p0) * np.cos(phi) * np.cos(lam)
        nrm = np.sqrt(x * x + y * y) + 1e-9
        x = np.where(cosc < 0, x / nrm, x); y = np.where(cosc < 0, y / nrm, y)
        return np.stack([cx + R * x, cy - R * y], 1), cosc
    hl = {c: {"red": RED, "green": GREEN, "gold": GOLD, "blue": BLUE}[col] for c, col in p.get("hl", {}).items()}
    ha = ease(prog(t, p.get("hl_at", 0.5), 0.6))
    land = Image.new("RGBA", (W, H)); ld = ImageDraw.Draw(land)
    for code, rings, bb in countries:
        for r in rings:
            pts, cosc = proj(r[::2] if len(r) > 60 else r)
            if (cosc > 0).sum() < 3: continue
            P = [tuple(q) for q in pts]
            col = hl.get(code)
            ld.polygon(P, fill=(rgba(col, 0.55 + 0.4 * ha) if col and ha > 0 else (46, 92, 70, 255)), outline=(120, 190, 150, 200))
    # sombreamento por cima da terra
    shade_l = Image.fromarray(np.stack([np.zeros_like(shade), np.zeros_like(shade), np.zeros_like(shade),
                                        np.clip((1 - shade) * 200, 0, 200) * (dd <= 1)], -1).astype(np.uint8), "RGBA")
    land.alpha_composite(shade_l, (int(cx - R), int(cy - R)))
    img.alpha_composite(land)
    # graticula
    for lat in range(-60, 90, 30):
        arr = np.array([[lo, lat] for lo in range(-180, 181, 6)], float); pts, cosc = proj(arr)
        seg = [tuple(q) for q, c in zip(pts, cosc) if c > 0]
        if len(seg) > 1: dr.line(seg, fill=(150, 200, 230, 40), width=1)
    for lo in range(-180, 180, 30):
        arr = np.array([[lo, la] for la in range(-90, 91, 6)], float); pts, cosc = proj(arr)
        seg = [tuple(q) for q, c in zip(pts, cosc) if c > 0]
        if len(seg) > 1: dr.line(seg, fill=(150, 200, 230, 40), width=1)
    sfx = [(0.0, "whoosh", 0.4)]
    for i, lab in enumerate(p.get("labels", [])):
        pt, c = proj(np.array([lab["ll"]], float))
        if c[0] > 0.15:
            callout(dr, tuple(pt[0]), lab["text"], t, start=lab.get("at", 1.0), dx=lab.get("dx", 180), dy=lab.get("dy", -120))
    if p.get("title"): kicker(dr, p["title"], 140, 120, t=t)
    dust(dr, t, 70, 7)
    return sfx

def radar_overlay(dr, pt, t, r=260, color=GREEN):
    x, y = pt
    for i in range(1, 5):
        rr = r * i / 4; dr.ellipse([x - rr, y - rr, x + rr, y + rr], outline=rgba(color, 0.35), width=2)
    dr.line([(x - r, y), (x + r, y)], fill=rgba(color, 0.25)); dr.line([(x, y - r), (x, y + r)], fill=rgba(color, 0.25))
    ang = (t * 140) % 360
    for k in range(18):
        a0 = ang - k * 3
        dr.pieslice([x - r, y - r, x + r, y + r], a0 - 3, a0, fill=rgba(color, 0.22 * (1 - k / 18) ** 1.5))
    rng = np.random.default_rng(3)
    for _ in range(5):
        a = rng.random() * 360; d = r * (0.3 + 0.6 * rng.random())
        diff = (ang - a) % 360; al = clamp(1 - diff / 200)
        bx, by = x + d * math.cos(math.radians(a)), y + d * math.sin(math.radians(a))
        dr.ellipse([bx - 7, by - 7, bx + 7, by + 7], fill=rgba(RED, al))

# ================= COLAGEM 2.5D (estilo da referência do vídeo 06) =================
@lru_cache(None)
def halftone():
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    a = math.radians(45); u = (xx * math.cos(a) + yy * math.sin(a)) / 7.0; v = (-xx * math.sin(a) + yy * math.cos(a)) / 7.0
    d = np.sqrt((u - np.round(u)) ** 2 + (v - np.round(v)) ** 2)
    return (0.9 + 0.1 * np.clip(d * 2.2, 0, 1))[..., None].astype(np.float32)

@lru_cache(None)
def foliage(seed=0):
    """Folhagem escura e bem desfocada nas bordas (primeiro plano, dá profundidade)."""
    rng = np.random.default_rng(seed); lay = Image.new("RGBA", (W, H)); d = ImageDraw.Draw(lay)
    for cx0, cy0 in ((-60, H * 0.75), (W + 60, H * 0.35), (W * 0.15, H + 80)):
        for _ in range(45):
            r = rng.uniform(90, 230); x = cx0 + rng.normal(0, 110); y = cy0 + rng.normal(0, 220)
            g = int(rng.uniform(10, 35)); d.ellipse([x - r, y - r, x + r, y + r], fill=(g, g, g + 3, 245))
    return lay.resize((W // 8, H // 8)).filter(ImageFilter.GaussianBlur(5)).resize((W, H), Image.BICUBIC)

def sign_card(text, seed, style="white"):
    rng = np.random.default_rng(seed)
    lines = text.split("|"); f = F("black", 78)
    w = int(max(tw(f, l) for l in lines)) + 90; h = int(len(lines) * 88 + 70)
    bgc = (250, 248, 240) if style == "white" else ACCENT; fg = (14, 14, 14)
    card = Image.new("RGBA", (w, h), bgc + (255,)); cd = ImageDraw.Draw(card)
    cd.rectangle([8, 8, w - 9, h - 9], outline=fg + (255,), width=7)
    for i, l in enumerate(lines): cd.text((w / 2, 40 + 88 * i + 44), l, font=f, fill=fg, anchor="mm")
    card.putalpha(torn_mask(w, h, seed, 6))
    return card.rotate(float(rng.uniform(-16, 16)), expand=True, resample=Image.BICUBIC)

def grade_mono(img, warm=0.06):
    """Gradação P&B contrastada + retícula; o amarelo fica reservado para os elementos gráficos."""
    a = np.asarray(img.convert("RGB"), dtype=np.float32)
    g = a @ np.array([0.3, 0.59, 0.11], np.float32)
    g = np.clip((g - 128) * 1.35 + 118, 0, 255)[..., None]
    out = np.concatenate([g * (1 + warm), g, g * (1 - warm * 1.5)], -1) * halftone()
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8)).convert("RGBA")

def sc_collage(img, dr, t, D, p):
    """Colagem 2.5D: fundo P&B com retícula, cartazes que entram girando (parallax), folhagem em primeiro
    plano, mira pulsando e movimento 'stop motion' (12 qps nos elementos)."""
    tq = math.floor(t * 12) / 12  # stop motion
    base = grade_mono(img) if p.get("_media") else img
    img.paste(base, (0, 0))
    # faixa/tarja amarela inclinada com a manchete
    if p.get("tape"):
        k = ease(prog(tq, 0.2, 0.5)); f = F("black", 54)
        w = int(tw(f, p["tape"])) + 80
        tape = Image.new("RGBA", (w, 90), ACCENT + (255,)); ImageDraw.Draw(tape).text((w / 2, 46), p["tape"], font=f, fill=ON_ACCENT, anchor="mm")
        tape = tape.rotate(-6, expand=True, resample=Image.BICUBIC)
        x = int(W * p.get("tape_x", 0.52) - tape.width / 2 + (1 - k) * -W - tq * 18); y = int(H * p.get("tape_y", 0.16))
        img.alpha_composite(tape, (max(-tape.width + 1, x), y)) if x > -tape.width else None
    # mira pulsando
    if p.get("target"):
        tx, ty = p["target"][0] * W, p["target"][1] * H
        ka = prog(t, p.get("target_at", 0.8), 0.3)
        if ka > 0:
            ov = Image.new("RGBA", (W, H)); od = ImageDraw.Draw(ov)
            for i in range(4):
                r = 30 + i * 38 + 10 * math.sin(t * 7 - i)
                od.ellipse([tx - r, ty - r, tx + r, ty + r], outline=ACCENT + (int(230 * ka * (1 - i * 0.18)),), width=6 - i)
            od.ellipse([tx - 16, ty - 16, tx + 16, ty + 16], fill=ACCENT + (int(255 * ka),))
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                od.line([(tx + dx * 170, ty + dy * 170), (tx + dx * 220, ty + dy * 220)], fill=ACCENT + (int(220 * ka),), width=5)
            img.alpha_composite(ov)
    # cartazes / adesivos com parallax
    sfx = [(0.0, "whoosh", 0.4)]
    for i, sg in enumerate(p.get("signs", [])):
        st = sg.get("at", 0.3 + i * 0.55); k = back(prog(tq, st, 0.35))
        if k <= 0: continue
        card = sign_card(sg["text"], 10 + i * 7 + p.get("_idx", 0), sg.get("style", "white" if i % 2 == 0 else "yellow"))
        sc = clamp(k, 0.05, 1.15) * sg.get("scale", 1.0)
        if sc != 1: card = card.resize((max(1, int(card.width * sc)), max(1, int(card.height * sc))), Image.BICUBIC)
        jit = ((hash((i, int(t * 12))) % 7) - 3) * 1.5
        x = sg["x"] * W - card.width / 2 + (tq - st) * sg.get("drift", -40 if i % 2 else 40) + jit
        y = sg["y"] * H - card.height / 2 + jit
        x = min(max(x, 20), W - card.width - 20); y = min(max(y, 20), H - card.height - 20)
        shd = Image.new("RGBA", card.size, (0, 0, 0, 0)); shd.putalpha(card.getchannel("A").point(lambda v: v * 0.55))
        img.alpha_composite(shd, (int(x + 16), int(y + 22))); img.alpha_composite(card, (int(x), int(y)))
        sfx.append((st, "paper", 0.35))
    # folhagem desfocada em primeiro plano (move mais rápido = profundidade)
    if p.get("foliage", True):
        fol = foliage(p.get("_idx", 0) % 3)
        off = int(70 * math.sin(t * 0.6 + p.get("_idx", 0)) + t * 12 * (1 if p.get("_idx", 0) % 2 else -1))
        img.alpha_composite(fol.transform((W, H), Image.AFFINE, (1, 0, off, 0, 1, 0), Image.BILINEAR))
    if p.get("headline"):
        k = ease(prog(tq, 0.5, 0.4)); f = F("black", 92)
        for j, ln in enumerate(wrap(p["headline"], f, W - 320)):
            yy = H - 300 + j * 100 + (1 - k) * 60
            dr.text((W / 2 + 4, yy + 5), ln.replace("*", ""), font=f, fill=(0, 0, 0, int(200 * k)), anchor="mm")
        word_reveal(dr, wrap(p["headline"], f, W - 320), f, W / 2, H - 300 + 50 * (len(wrap(p["headline"], f, W - 320)) - 1), tq, 0.5, 0.08, accent=ACCENT)
    return sfx

SCENES = {k[3:]: v for k, v in globals().items() if k.startswith("sc_")}
BGS = {"collage": "dark", "phone": "dark", "globe": "dark", "text3d": "dark", "broll": "dark", "title": "dark", "chapter": "paper", "bars": "paper", "doc": "gray", "map": "ocean", "burst": "cream", "headline": "dark", "cine": "dark"}

# ---------- quadro final ----------
def frame(scene, t, D, mframe=None):
    kind = scene["type"]; p = scene
    b = p.get("bg") or BGS.get(kind, "dark")
    if mframe is not None:
        # foto/vídeo de banco como fundo; escurece quando há texto/gráfico por cima
        img = mframe.copy(); b = "dark"
        dim = p.get("dim", 0.0 if kind in ("broll", "collage") else 0.58)
        if dim: img.alpha_composite(Image.new("RGBA", (W, H), (0, 0, 0, int(255 * dim))))
    else:
        img = Image.new("RGBA", (W, H), OCEAN + (255,)) if b == "ocean" else bg(b).copy()
    dr = ImageDraw.Draw(img, "RGBA")
    sfx = SCENES[kind](img, dr, t, D, p)
    # marca do canal + fonte
    dark = b in ("dark", "ocean", "gray")
    if p.get("fonte"):
        dr.text((60, H - 50), "Fonte: " + p["fonte"], font=F("reg", 26), fill=rgba(WHITE if dark else INK, 0.7), anchor="lm")
    if D > BEAT * 1.6 and t >= BEAT:
        nb = int(t // BEAT)
        if (D - nb * BEAT) > 1.0: light_sweep(img, t - nb * BEAT, 0.0, 0.9, 0.3)
    if p.get("tilt"):
        img = tilt_frame(img, t, D, p); dr = ImageDraw.Draw(img, "RGBA")
    if p.get("letterbox") or kind == "cine":
        lb = int(110 * ease(prog(t, 0, 0.5))); dr.rectangle([0, 0, W, lb], fill=(0, 0, 0, 255)); dr.rectangle([0, H - lb, W, H], fill=(0, 0, 0, 255))
    # câmera: leve aproximação contínua + entrada
    kb = 0.14 if (p.get("_media") or {}).get("kind") == "photo" else 0.045
    s = 1.0 + kb * (t / max(D, 0.1)) + 0.06 * (1 - ease(prog(t, 0, 0.45)))
    # BATIDAS: em cenas longas, a cada BEAT s um "punch-in" rápido de câmera (algo acontece a cada < 10 s)
    if D > BEAT * 1.6:
        nb = int(t // BEAT)
        if nb >= 1 and (D - nb * BEAT) > 1.0:
            u = t - nb * BEAT
            s += 0.07 * math.exp(-u * 4.5) * (1 if u > 0 else 0)
    im = img.convert("RGB")
    if s != 1.0:
        cw, ch = W / s, H / s; x0, y0 = (W - cw) / 2, (H - ch) / 2
        if (p.get("_media") or {}).get("kind") == "photo":  # pan lateral alternado (Ken Burns)
            dirx = 1 if p.get("_idx", 0) % 2 else -1
            x0 += dirx * (W - cw) / 2 * (2 * (t / max(D, 0.1)) - 1) * 0.9
        im = im.transform((W, H), Image.EXTENT, (x0, y0, x0 + cw, y0 + ch), Image.BILINEAR)
    ImageDraw.Draw(im, "RGBA").text((60, 60), BRAND, font=F("bold", 26), fill=rgba(WHITE if dark else INK, 0.55), anchor="lm")
    if p.get("_media"):
        # crédito discreto no canto, como na TV
        d2 = ImageDraw.Draw(im); txt = p["_media"]["credit"]; f = F("med", 22)
        x, y = W - 48, H - 42
        d2.text((x + 2, y + 2), txt, font=f, fill=(0, 0, 0), anchor="rm")
        d2.text((x, y), txt, font=f, fill=(225, 225, 225), anchor="rm")
    return im, sfx

BEAT = 5.0  # segundos entre "batidas" visuais em cenas longas

def beat_events(D):
    """Efeitos sonoros discretos para cada batida visual."""
    ev = []
    if D > BEAT * 1.6:
        k = 1
        while k * BEAT < D - 1.0:
            ev.append((k * BEAT - 0.25, "whoosh", 0.25)); k += 1
    return ev

def post(im, fi):
    a = np.asarray(im, dtype=np.float32)
    a = a * vignette() + grains()[0]
    return np.clip(a, 0, 255).astype(np.uint8)

def render_scene(args):
    i, scene, f0, f1, outdir = args
    n = f1 - f0; D = n / FPS
    path = f"{outdir}/s{i:03d}.mp4"
    proc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                             "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
                             "-pix_fmt", "yuv420p", "-threads", "2", path], stdin=subprocess.PIPE)
    sfx = None
    med = scene.get("_media"); reader = photo = None
    if med and med["kind"] == "video":
        reader = subprocess.Popen(["ffmpeg", "-v", "error", "-stream_loop", "-1", "-ss", "0.3", "-i", med["path"], "-an",
                                   "-vf", f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS}",
                                   "-frames:v", str(n), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
    elif med:
        ph = Image.open(med["path"]).convert("RGB"); r = max(W / ph.width, H / ph.height)
        ph = ph.resize((int(ph.width * r + 1), int(ph.height * r + 1)), Image.LANCZOS)
        photo = ph.crop(((ph.width - W) // 2, (ph.height - H) // 2, (ph.width - W) // 2 + W, (ph.height - H) // 2 + H)).convert("RGBA")
    last = None
    for k in range(n):
        mf = photo
        if reader:
            raw = reader.stdout.read(W * H * 3)
            if len(raw) == W * H * 3: last = Image.frombuffer("RGB", (W, H), raw).convert("RGBA")
            mf = last
        im, s = frame(scene, k / FPS, D, mf)
        if sfx is None: sfx = s
        proc.stdin.write(post(im, f0 + k).tobytes())
    proc.stdin.close(); proc.wait()
    if reader: reader.stdout.close(); reader.wait()
    ev = [(f0 / FPS + a, name, g) for a, name, g in ((sfx or []) + beat_events(D)) if a < D]
    json.dump(ev, open(f"{outdir}/s{i:03d}.json", "w"))
    return i, [(f0 / FPS + a, name, g) for a, name, g in (sfx or []) if a < D]

# ---------- sincronização com a fala ----------
def norm(s):
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9 ]", " ", s).split()

def resolve(plan, words, total):
    toks = []
    for w in words:
        for tk in norm(w[2]): toks.append((tk, w[0]))
    pos = 0; starts = []
    for sc in plan:
        if sc.get("at") is not None: starts.append(sc["at"]); continue
        ph = norm(sc["anchor"]); found = None
        for j in range(pos, len(toks) - len(ph) + 1):
            if all(toks[j + m][0] == ph[m] for m in range(len(ph))): found = j; break
        if found is None:
            print("ÂNCORA NÃO ENCONTRADA:", sc["anchor"]); starts.append(None); continue
        pos = found + 1; starts.append(max(0.0, toks[found][1] - 0.15))
    for i in range(len(starts)):
        if starts[i] is None: starts[i] = (starts[i - 1] + 3) if i else 0
    starts[0] = 0.0
    return starts

SFX_LEVEL = 0.16   # volume geral dos efeitos (antes 0.42: estava alto demais)
SFX_CEIL = 0.16    # pico máximo do barramento de efeitos (voz tem pico ~0.8)

def mix(voice_path, sfx_events, assets_sfx, music_path, out_path, total):
    SR = 48000
    def rd(p):
        r = subprocess.run(["ffmpeg", "-v", "error", "-i", p, "-ac", "2", "-ar", str(SR), "-f", "f32le", "-"], capture_output=True, check=True).stdout
        return np.frombuffer(r, np.float32).reshape(-1, 2)
    N = int(total * SR)
    voice = np.zeros((N, 2), np.float32); v = rd(voice_path)[:N]; voice[: len(v)] = v
    music = np.zeros((N, 2), np.float32); m = rd(music_path)[:N]; music[: len(m)] = m
    # ducking: música mais baixa quando há voz
    envv = np.abs(voice[:, 0]); hop = 2400
    blk = envv[: N // hop * hop].reshape(-1, hop).mean(1)
    act = (blk > 0.01).astype(np.float32)
    sm = np.convolve(act, np.ones(5) / 5, mode="same")
    gain = 0.085 + (0.17 - 0.085) * (1 - sm)  # música bem abaixo da voz
    g = np.repeat(gain, hop); g = np.concatenate([g, np.full(N - len(g), g[-1] if len(g) else 0.2)])
    music *= g[:, None]
    fx = np.zeros((N, 2), np.float32); cache = {}
    for tsec, name, gn in sfx_events:
        if name not in cache: cache[name] = rd(os.path.join(assets_sfx, name + ".wav"))
        s = cache[name]; i = int(tsec * SR)
        if i >= N: continue
        e = min(N, i + len(s)); fx[i:e] += s[: e - i] * min(gn, 0.6) * SFX_LEVEL
    # efeitos: limitador no barramento para nunca passarem da voz; ainda mais baixos enquanto há fala
    fx = np.tanh(fx / SFX_CEIL) * SFX_CEIL
    dk = np.repeat(0.65 + 0.35 * (1 - sm), hop); dk = np.concatenate([dk, np.ones(max(0, N - len(dk)))])[:N]
    fx *= dk[:, None]
    out = voice * 1.0 + music + fx
    out = np.tanh(out * 1.05) / 1.05
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(SR), "-ac", "2", "-i", "-",
                          "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-ar", str(SR), out_path], stdin=subprocess.PIPE)
    p.communicate(out.astype(np.float32).tobytes())

def main():
    plan_p, tx_p, voice_p, assets, out = sys.argv[1:6]
    global ASSETS; ASSETS = assets; os.environ["ASSETS"] = assets
    plan = json.load(open(plan_p))
    words = [w for s in json.load(open(tx_p)) for w in s["w"]]
    total = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", voice_p],
                                 capture_output=True, text=True).stdout) + 1.5
    starts = resolve(plan, words, total)
    for i, sc in enumerate(plan): sc["_idx"] = i
    longas = [(i, plan[i]["type"], round((starts[i + 1] if i + 1 < len(plan) else total) - starts[i], 1)) for i in range(len(plan))
              if ((starts[i + 1] if i + 1 < len(plan) else total) - starts[i]) > 10]
    if longas: print("AVISO: cenas com mais de 10 s (recebem batidas automáticas, mas prefira dividir):", longas)
    work = os.path.splitext(out)[0] + "_parts"; os.makedirs(work, exist_ok=True)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import stock
    for i, sc in enumerate(plan):
        m = sc.get("media")
        if not m: continue
        if m.get("file"):  # arquivo escolhido a dedo (revisado visualmente)
            fp = m["file"] if os.path.isabs(m["file"]) else os.path.join(assets, m["file"])
            if os.path.exists(fp):
                sc["_media"] = {"path": fp, "credit": m.get("credit", "Pixabay"), "kind": "video" if fp.endswith(".mp4") else "photo"}
                continue
        if not m.get("q"): print(f"cena {i}: arquivo de mídia não encontrado ({m.get('file')}), sem mídia"); continue
        r = stock.fetch(m["q"], m.get("kind", "video"), os.path.join(assets, "stock"), seed=i)
        if r: sc["_media"] = r; print(f"cena {i}: {r['credit']} <- {m['q']}")
        elif sc["type"] == "broll":
            sc.update({"type": "kinetic", "text": sc.get("caption") or m["q"]}); print(f"cena {i}: sem mídia para '{m['q']}', virou texto")
    only = os.environ.get("ONLY")
    jobs = []
    for i, sc in enumerate(plan):
        a = starts[i]; b = starts[i + 1] if i + 1 < len(plan) else total
        f0, f1 = round(a * FPS), round(b * FPS)
        if f1 - f0 < 1: continue
        if only and str(i) not in only.split(","): continue
        jobs.append((i, sc, f0, f1, work))
    jobs.sort(key=lambda j: -(j[3] - j[2]))
    with Pool(int(os.environ.get("JOBS", "4"))) as pool:
        res = pool.map(render_scene, jobs, chunksize=1)
    if only and not os.environ.get("FINAL"): print("ok parcial"); return
    allj = []
    for i, sc in enumerate(plan):
        a = starts[i]; b = starts[i + 1] if i + 1 < len(plan) else total
        f0, f1 = round(a * FPS), round(b * FPS)
        if f1 - f0 >= 1: allj.append((i, sc, f0, f1, work))
    jobs = allj
    events = [e for j in jobs for e in json.load(open(f"{work}/s{j[0]:03d}.json"))]
    with open(f"{work}/list.txt", "w") as fl:
        for j in sorted(jobs): fl.write(f"file 's{j[0]:03d}.mp4'\n")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", f"{work}/list.txt", "-c", "copy", f"{work}/video.mp4"], check=True)
    mix(voice_p, events, os.path.join(assets, "sfx"), os.path.join(assets, "sfx", "music.wav"), f"{work}/audio.wav", total)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", f"{work}/video.mp4", "-i", f"{work}/audio.wav", "-c:v", "copy",
                    "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", out], check=True)
    json.dump([[plan[j[0]]["type"], round(starts[j[0]], 2)] for j in sorted(jobs)], open(f"{work}/timeline.json", "w"))
    print("OK", out)

if __name__ == "__main__":
    main()
