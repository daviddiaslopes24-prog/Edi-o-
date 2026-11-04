"""Renderizador de SHORTS verticais (1080x1920), bem dinâmico: uma animação diferente a cada ~4-5 s,
legenda grande palavra por palavra, câmera com punch-in, tremores nos impactos, glitch e flashes.
Uso: python short.py plano.json transcricao_editada.json voz.wav assets_dir saida.mp4
Reaproveita fontes, texto 3D, sincronização e mixagem do render.py.
"""
import json, sys, os, math, subprocess
from functools import lru_cache
from multiprocessing import Pool
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render as R

W, H, FPS = 1080, 1920, 30
R.W, R.H = W, H  # helpers do render.py (dust, label_box, light_sweep, vinheta) passam a usar o quadro vertical
F, ease, ease_io, back, prog, rgba, fmt_br, tw = R.F, R.ease, R.ease_io, R.back, R.prog, R.rgba, R.fmt_br, R.tw
clamp = R.clamp
RED, GREEN, GOLD, WHITE, INK, BLUE = R.RED, R.GREEN, R.GOLD, R.WHITE, R.INK, R.BLUE
YEL = (255, 214, 10); BG0 = (10, 14, 13); BGR = (40, 6, 10)
CY = 800          # centro da área de animação (legenda fica embaixo, em ~1330)
CAP_Y = 1470
BRAND = os.environ.get("BRAND", "IMPACTO ECONÔMICO")

# ---------------- utilidades ----------------
@lru_cache(None)
def text_layer(text, size, color, font="black", stroke=0, stroke_color=(0, 0, 0)):
    f = F(font, size); w = int(tw(f, text)) + 2 * stroke + 20; h = int(size * 1.4) + 2 * stroke
    lay = Image.new("RGBA", (w, h))
    ImageDraw.Draw(lay).text((w / 2, h / 2), text, font=f, fill=tuple(color) + (255,), anchor="mm",
                             stroke_width=stroke, stroke_fill=tuple(stroke_color) + (255,))
    return lay

def put(img, lay, cx, cy, s=1.0, alpha=1.0, rot=0.0):
    if s <= 0.01 or alpha <= 0.01: return
    if s != 1.0: lay = lay.resize((max(1, int(lay.width * s)), max(1, int(lay.height * s))), Image.BICUBIC)
    if rot: lay = lay.rotate(rot, Image.BICUBIC, expand=True)
    if alpha < 1: lay = lay.copy(); lay.putalpha(lay.getchannel("A").point(lambda v: int(v * alpha)))
    img.alpha_composite(lay, (int(cx - lay.width / 2), int(cy - lay.height / 2)))

def fit(lay, maxw):
    return lay if lay.width <= maxw else lay.resize((maxw, int(lay.height * maxw / lay.width)), Image.BICUBIC)

@lru_cache(None)
def ext3d(text, size, face, side, depth=20, maxw=1000):
    return fit(R.extruded_text(text, size, face=face, side=side, depth=depth), maxw)

def shadowed(img, lay, cx, cy, s=1.0, alpha=1.0):
    sh = Image.new("RGBA", lay.size, (0, 0, 0, 0)); sh.putalpha(lay.getchannel("A").point(lambda v: v * 0.55))
    sh = sh.resize((max(1, lay.width // 4), max(1, lay.height // 4))).filter(ImageFilter.GaussianBlur(4)).resize(lay.size)
    put(img, sh, cx + 18, cy + 26, s, alpha); put(img, lay, cx, cy, s, alpha)

def pill(dr, cx, cy, text, size=44, fg=WHITE, bgc=RED, alpha=1.0):
    f = F("xbold", size); w = tw(f, text) + 56; h = size + 34
    dr.rounded_rectangle([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], radius=h / 2, fill=rgba(bgc, alpha))
    dr.text((cx, cy + 2), text, font=f, fill=rgba(fg, alpha), anchor="mm")

def note(dr, text):
    dr.text((W - 40, CY + 545), text, font=F("med", 26), fill=rgba(WHITE, 0.55), anchor="rm")

# ---------------- fundos (maiores que o quadro, para rolar) ----------------
@lru_cache(None)
def bgimg(kind):
    h = H + 120
    y, x = np.mgrid[0:h, 0:W]
    d = np.sqrt(((x - W / 2) / W) ** 2 + ((y - CY) / h) ** 2)
    base = {"dark": BG0, "red": BGR, "navy": (8, 14, 32), "paper": (243, 237, 222)}[kind]
    if kind == "paper":
        a = np.array(base, float)[None, None] * (1.03 - 0.25 * d[..., None])
    else:
        a = np.array(base, float)[None, None] * (1.8 - 1.3 * d[..., None])
    img = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)).convert("RGBA")
    dr = ImageDraw.Draw(img)
    gc = {"dark": (26, 40, 35), "red": (70, 16, 22), "navy": (22, 34, 66), "paper": (222, 214, 192)}[kind]
    for gx in range(0, W + 1, 60): dr.line([(gx, 0), (gx, h)], fill=gc + (255,), width=1)
    for gy in range(0, h, 60): dr.line([(0, gy), (W, gy)], fill=gc + (255,), width=1)
    return img

def background(kind, t):
    off = int((t * 45) % 60)
    return bgimg(kind).crop((0, off, W, off + H)).copy()

def pulse_glow(img, t, color, period=0.9, strength=0.35, cy=CY):
    k = 0.5 + 0.5 * math.sin(t * 2 * math.pi / period)
    ov = Image.new("RGBA", (W // 8, H // 8)); d = ImageDraw.Draw(ov)
    r = 70 + 15 * k
    d.ellipse([W / 16 - r, cy / 8 - r, W / 16 + r, cy / 8 + r], fill=rgba(color, strength * (0.6 + 0.4 * k)))
    img.alpha_composite(ov.filter(ImageFilter.GaussianBlur(18)).resize((W, H), Image.BILINEAR))

def particles(dr, t, n=50, seed=1, color=WHITE, speed=60):
    rng = np.random.default_rng(seed)
    for _ in range(n):
        x0, y0, r, v = rng.random() * W, rng.random() * H, rng.random() * 3 + 1, (0.4 + rng.random()) * speed
        y = (y0 - t * v) % H
        dr.ellipse([x0 - r, y - r, x0 + r, y + r], fill=rgba(color, 0.2 + 0.4 * rng.random()))

# ================= CENAS =================
def sc_hook(img, dr, t, D, p):
    """Abertura: gráfico despencando + palavras 3D batendo na tela."""
    pulse_glow(img, t, RED, 0.6, 0.45)
    # linha de preço caindo atrás
    rng = np.random.default_rng(3); n = 60; k = ease(prog(t, 0, 1.6))
    ys = np.cumsum(rng.normal(0, 14, n)) + np.linspace(0, 760, n) ** 1.15 / 2.4
    pts = [(40 + i * (W - 80) / (n - 1), 380 + ys[i]) for i in range(int(2 + (n - 2) * k))]
    if len(pts) > 1:
        dr.line(pts, fill=rgba(RED, 0.35), width=22, joint="curve"); dr.line(pts, fill=rgba((255, 110, 110), 1), width=8, joint="curve")
        x, y = pts[-1]; dr.ellipse([x - 16, y - 16, x + 16, y + 16], fill=rgba(WHITE, 1))
    lines = p.get("lines", ["BOLSA", "*DESPENCA*"]); times = p.get("times", [0.0, 1.0])
    ev = [(0.0, "boom", 0.6)]
    for i, ln in enumerate(lines):
        acc = ln.startswith("*"); ln = ln.strip("*")
        lay = ext3d(ln, 210 if acc else 190, (255, 80, 90) if acc else (255, 255, 255), (90, 10, 18) if acc else (70, 76, 82), 24)
        a = times[i]; kk = prog(t, a, 0.28)
        if kk <= 0: continue
        s = 2.6 - 1.6 * ease(kk) if kk < 1 else 1 + 0.03 * math.sin((t - a) * 6)
        lay = R.warp3d(lay, 0.18 * math.sin(t * 1.3 + i), 0)
        shadowed(img, lay, W / 2, CY - 120 + i * 230, s, clamp(kk * 3))
        if i: ev.append((a + 0.2, "hit", 0.6))
    if p.get("sub"):
        a = ease(prog(t, times[-1] + 0.5, 0.3)); pill(dr, W / 2, CY + 330, p["sub"], 52, WHITE, RED, a)
    R.dust(dr, t, 40, 2, (255, 190, 190))
    return ev

def sc_date(img, dr, t, D, p):
    """Calendário caindo em 3D e marcando o dia."""
    k = prog(t, 0, 0.45)
    cw, ch = 620, 700
    card = Image.new("RGBA", (cw, ch)); c = ImageDraw.Draw(card)
    c.rounded_rectangle([0, 0, cw, ch], 40, fill=(250, 248, 242, 255))
    c.rounded_rectangle([0, 0, cw, 180], 40, fill=RED + (255,)); c.rectangle([0, 140, cw, 180], fill=RED + (255,))
    for xx in (150, cw - 150): c.ellipse([xx - 22, -10, xx + 22, 34], fill=(60, 60, 60, 255))
    c.text((cw / 2, 95), p.get("weekday", "SEGUNDA-FEIRA"), font=F("black", 64), fill=WHITE + (255,), anchor="mm")
    c.text((cw / 2, 400), p.get("day", "26"), font=F("black", 330), fill=INK + (255,), anchor="mm")
    c.text((cw / 2, 610), p.get("month", "OUTUBRO 2026"), font=F("xbold", 60), fill=(90, 90, 90, 255), anchor="mm")
    # círculo vermelho desenhado à mão em volta do número
    ck = ease(prog(t, 0.9, 0.6))
    if ck > 0:
        c.arc([110, 230, cw - 110, 575], -200, -200 + 360 * ck, fill=RED + (255,), width=16)
    yaw = 0.5 * (1 - ease(k)) + 0.06 * math.sin(t * 1.5)
    lay = R.warp3d(card, yaw, 0)
    y = CY - 1300 * (1 - back(k)) if k < 1 else CY + 8 * math.sin(t * 2)
    shadowed(img, lay, W / 2, y, 1.0, 1.0)
    if p.get("kicker"):
        a = ease(prog(t, 1.2, 0.3)); pill(dr, W / 2, CY - 470, p["kicker"], 50, WHITE, (20, 20, 20), a)
    particles(dr, t, 30, 4)
    return [(0.0, "whoosh_down", 0.5), (0.4, "hit", 0.5), (0.9, "paper", 0.4)]

def sc_candles(img, dr, t, D, p):
    """Gráfico de velas despencando, rolando para a esquerda."""
    pulse_glow(img, t, RED, 1.2, 0.25)
    rng = np.random.default_rng(11); n = 46
    price = [100.0]
    for i in range(n - 1): price.append(price[-1] + rng.normal(-0.9, 2.2) - (2.5 if 25 < i < 34 else 0))
    lo, hi = min(price) - 6, max(price) + 6
    x0, x1, y0, y1 = 60, W - 150, CY - 380, CY + 360
    vis = 8 + int((n - 8) * ease_io(prog(t, 0, D * 0.85)))
    shown = 18; start = max(0, vis - shown); step = (x1 - x0) / shown
    for gy in np.linspace(y0, y1, 6): dr.line([(x0, gy), (x1 + 100, gy)], fill=rgba(WHITE, 0.08), width=2)
    def Y(v): return y1 - (v - lo) / (hi - lo) * (y1 - y0)
    for j, i in enumerate(range(start, vis)):
        o = price[i - 1] if i else price[0] + 1; c_ = price[i]
        hi_ = max(o, c_) + abs(rng.normal(0, 1.5)) + 0.5; lo_ = min(o, c_) - abs(rng.normal(0, 1.5)) - 0.5
        cx = x0 + (j + 0.5) * step; col = GREEN if c_ > o else RED
        grow = ease(clamp((vis - i) / 1.5)) if i == vis - 1 else 1
        dr.line([(cx, Y(hi_)), (cx, Y(lo_))], fill=rgba(col, 1), width=4)
        top, bot = Y(max(o, c_)), Y(min(o, c_))
        bot = top + max(6, (bot - top)) * grow
        dr.rectangle([cx - step * 0.32, top, cx + step * 0.32, bot], fill=rgba(col, 1))
    last = price[vis - 1]; ly = Y(last)
    dr.line([(x0, ly), (x1 + 10, ly)], fill=rgba(RED, 0.6), width=2)
    dr.rounded_rectangle([x1 + 6, ly - 28, W - 10, ly + 28], 8, fill=rgba(RED, 1))
    dr.polygon([(x1 + 6, ly - 12), (x1 - 10, ly), (x1 + 6, ly + 12)], fill=rgba(RED, 1))
    dr.text(((x1 + W) / 2, ly + 2), "▼", font=F("sym", 34), fill=rgba(WHITE, 1), anchor="mm")
    a = ease(prog(t, 0.1, 0.3))
    pill(dr, W / 2, y0 - 110, p.get("title", "IBOVESPA"), 54, WHITE, (20, 20, 20), a)
    if math.sin(t * 9) > 0: dr.ellipse([W / 2 - 200, y0 - 126, W / 2 - 172, y0 - 98], fill=rgba(RED, a))
    if p.get("label"):
        k = back(prog(t, 1.0, 0.4)); put(img, text_layer(p["label"], 60, YEL, "black", 6), W / 2, y1 + 110, k)
    note(dr, "Movimento ilustrativo")
    return [(0.0, "whoosh", 0.5), (0.3, "glitch", 0.4), (1.1, "pop", 0.4)]

def sc_bignum(img, dr, t, D, p):
    """Número gigante contando, com batida, tremor e glitch."""
    col = tuple(p.get("color", RED))
    pulse_glow(img, t, col, 0.5 if t > p.get("dur", 1.0) else 0.25, 0.4)
    k = ease(prog(t, 0.1, p.get("dur", 1.0)))
    v = p.get("from", 0) + (p["to"] - p.get("from", 0)) * k
    txt = p.get("prefix", "") + fmt_br(v, p.get("dec", 0)) + p.get("suffix", "")
    face = (255, 90, 100) if col == RED else (120, 255, 170)
    lay = R.extruded_text(txt, p.get("size", 300), face=face, side=(90, 10, 18) if col == RED else (10, 80, 40), depth=28)
    lay = fit(lay, 1000)
    hitk = prog(t, 0.1 + p.get("dur", 1.0), 0.25)
    s = 1.0 + 0.25 * (1 - ease(hitk)) * (hitk > 0) + 0.02 * math.sin(t * 5)
    lay = R.warp3d(lay, 0.12 * math.sin(t * 1.4), 0)
    shadowed(img, lay, W / 2, CY, s)
    # seta para baixo pulsando
    if p.get("arrow"):
        ay = CY - 340 + 20 * math.sin(t * 6); up = p["arrow"] == "up"
        R.arrow_tri(dr, W / 2, ay, 70, up, col, ease(prog(t, 0, 0.3)))
    if p.get("kicker"):
        pill(dr, W / 2, CY - 470, p["kicker"], 50, WHITE, (20, 20, 20), ease(prog(t, 0, 0.3)))
    if p.get("label"):
        put(img, text_layer(p["label"], 58, WHITE, "black", 6), W / 2, CY + 260, back(prog(t, 0.4 + p.get("dur", 1.0), 0.35)))
    R.dust(dr, t, 30, 7)
    d = p.get("dur", 1.0)
    return [(0.0, "whoosh", 0.5)] + [(0.1 + d * i / 6, "tick", 0.5) for i in range(6)] + [(0.1 + d, "hit", 0.7), (0.12 + d, "glitch", 0.35)]

def sc_ticker(img, dr, t, D, p):
    """Painel de cotação em LED com fita rolando."""
    x0, y0, x1, y1 = 50, CY - 330, W - 50, CY + 300
    dr.rounded_rectangle([x0 - 12, y0 - 12, x1 + 12, y1 + 12], 34, fill=rgba((60, 60, 66), 1))
    dr.rounded_rectangle([x0, y0, x1, y1], 26, fill=rgba((6, 6, 8), 1))
    k = prog(t, 0.0, 0.35)
    blink = 1 if (t < 0.9 or math.sin(t * 10) > -0.3) else 0.45
    dr.text((W / 2, y0 + 110), p.get("name", "IBOVESPA"), font=F("black", 96), fill=rgba(YEL, ease(k)), anchor="mm")
    dr.text((W / 2, y0 + 210), p.get("sub", "FECHAMENTO · 26/10"), font=F("bold", 44), fill=rgba((200, 200, 200), ease(k)), anchor="mm")
    v = p["to"] * ease(prog(t, 0.2, 0.9))
    txt = "▼ " + fmt_br(v, 2) + "%"
    lay = text_layer(txt.replace("▼ ", ""), 200, RED, "black")
    put(img, lay, W / 2 + 50, y0 + 420, 1.0, blink)
    dr.text((W / 2 - lay.width / 2 - 20, y0 + 420), "▼", font=F("sym", 130), fill=rgba(RED, blink), anchor="mm")
    # grade de LED por cima
    ov = Image.new("RGBA", (x1 - x0, y1 - y0)); od = ImageDraw.Draw(ov)
    for gx in range(0, x1 - x0, 7): od.line([(gx, 0), (gx, y1 - y0)], fill=(0, 0, 0, 150), width=2)
    for gy in range(0, y1 - y0, 7): od.line([(0, gy), (x1 - x0, gy)], fill=(0, 0, 0, 150), width=2)
    img.alpha_composite(ov, (x0, y0))
    # fita
    tape = "   ".join([p.get("tape", "IBOV -13,88%  •  CIRCUIT BREAKER  •  PREGÃO DE 26/10")] * 4)
    dr.rectangle([0, y1 + 60, W, y1 + 150], fill=rgba(RED, 1))
    off = -(t * 320) % 900
    dr.text((off - 900, y1 + 105), tape, font=F("black", 52), fill=rgba(WHITE, 1), anchor="lm")
    return [(0.0, "glitch", 0.5), (0.2, "typing", 0.4), (1.1, "hit", 0.5)]

def hazard(img, y, h, t, ang=-8):
    band = Image.new("RGBA", (W + 400, h)); bd = ImageDraw.Draw(band)
    off = (t * 220) % 120
    bd.rectangle([0, 0, W + 400, h], fill=YEL + (255,))
    for x in range(-240, W + 520, 120):
        x2 = x + off; bd.polygon([(x2, 0), (x2 + 60, 0), (x2 + 60 - h, h), (x2 - h, h)], fill=(15, 15, 15, 255))
    band = band.rotate(ang, Image.BICUBIC, expand=True)
    img.alpha_composite(band, (int(W / 2 - band.width / 2), int(y - band.height / 2)))

def sc_alert(img, dr, t, D, p):
    """Alerta: faixas de perigo, luz giratória e texto 3D."""
    # luz giratória
    ov = Image.new("RGBA", (W // 4, H // 4)); od = ImageDraw.Draw(ov)
    ang = (t * 300) % 360
    for a0 in (ang, ang + 180):
        od.pieslice([W / 8 - 600, CY / 4 - 600, W / 8 + 600, CY / 4 + 600], a0, a0 + 35, fill=(230, 40, 50, 90))
    img.alpha_composite(ov.filter(ImageFilter.GaussianBlur(6)).resize((W, H), Image.BILINEAR))
    k = ease(prog(t, 0, 0.35))
    hazard(img, CY - 420 - 300 * (1 - k), 90, t, -7)
    hazard(img, CY + 420 + 300 * (1 - k), 90, -t, -7)
    for i, (ln, a) in enumerate([(p.get("l1", "CIRCUIT"), 0.15), (p.get("l2", "BREAKER"), 0.35)]):
        kk = prog(t, a, 0.3)
        if kk <= 0: continue
        lay = ext3d(ln, 200, (255, 220, 60), (120, 70, 0), 26)
        lay = R.warp3d(lay, 0.2 * math.sin(t * 1.6 + i * 1.5), 0)
        s = 2.2 - 1.2 * ease(kk) if kk < 1 else 1.0
        shadowed(img, lay, W / 2, CY - 110 + i * 210, s, clamp(kk * 3))
    if p.get("sub"):
        pill(dr, W / 2, CY + 290, p["sub"], 50, WHITE, RED, ease(prog(t, 0.9, 0.3)))
    return [(0.0, "alarm", 0.4), (0.15, "boom", 0.6), (0.4, "hit", 0.5)]

def sc_since(img, dr, t, D, p):
    """Ano voltando no tempo (efeito caça-níquel) até o marco."""
    dr.text((W / 2, CY - 380), p.get("kicker", "PELA 1ª VEZ DESDE"), font=F("black", 70), fill=rgba(WHITE, ease(prog(t, 0, 0.3))), anchor="mm")
    y_from, y_to = p.get("from", 2026), p.get("to", 2020)
    k = ease_io(prog(t, 0.2, 1.3)); val = y_from + (y_to - y_from) * k
    # rolo: ano atual e vizinhos deslizando verticalmente
    base = math.floor(val); frac = val - base
    box = [80, CY - 230, W - 80, CY + 170]
    dr.rounded_rectangle(box, 40, fill=rgba((18, 26, 48), 1), outline=rgba(BLUE, 1), width=6)
    layer = Image.new("RGBA", (box[2] - box[0], box[3] - box[1])); ld = ImageDraw.Draw(layer)
    hh = box[3] - box[1]
    for d in (-1, 0, 1, 2):
        yr = base + d; yy = hh / 2 + (d - frac) * 300 * -1
        a = clamp(1 - abs(d - frac) * 0.8)
        col = GOLD if (k >= 1 and yr == y_to) else WHITE
        ld.text((layer.width / 2, yy), str(yr), font=F("black", 280), fill=rgba(col, a), anchor="mm")
    img.alpha_composite(layer, (box[0], box[1]))
    if p.get("month"):
        kk = back(prog(t, 1.6, 0.35))
        put(img, text_layer(p["month"], 110, (255, 255, 255), "black", 0), W / 2, CY + 320, kk, 1.0, rot=-6 * kk)
        if kk > 0:
            lay = text_layer(p["month"], 110, (255, 255, 255), "black")
            bw = lay.width * kk
            dr.rectangle([W / 2 - bw / 2 - 10, CY + 320 + 52, W / 2 + bw / 2 + 10, CY + 320 + 66], fill=rgba(RED, 1))
    return [(0.0, "whoosh", 0.5)] + [(0.25 + 0.2 * i, "tick", 0.5) for i in range(6)] + [(1.6, "ding", 0.5)]

def sc_question(img, dr, t, D, p):
    """Interrogação 3D gigante girando."""
    pulse_glow(img, t, GOLD, 1.4, 0.3)
    k = back(prog(t, 0, 0.5))
    lay = ext3d("?", 640, (255, 214, 10), (130, 90, 0), 40)
    lay = R.warp3d(lay, 0.45 * math.sin(t * 1.8), 0.05 * math.sin(t))
    shadowed(img, lay, W / 2, CY - 40 + 20 * math.sin(t * 2.5), clamp(k, 0, 1.3))
    if p.get("label"):
        pill(dr, W / 2, CY + 400, p["label"], 56, INK, WHITE, ease(prog(t, 0.5, 0.3)))
    particles(dr, t, 40, 9, (255, 230, 120))
    return [(0.0, "whoosh", 0.5), (0.2, "pop", 0.5)]

def sc_switch(img, dr, t, D, p):
    """Disjuntor que desarma: liga (verde) -> desliga (vermelho), com faíscas."""
    flip = p.get("flip", 1.1)
    bx0, by0, bx1, by1 = W / 2 - 260, CY - 360, W / 2 + 260, CY + 300
    dr.rounded_rectangle([bx0, by0, bx1, by1], 50, fill=rgba((54, 58, 64), 1), outline=rgba((120, 126, 134), 1), width=8)
    for sx, sy in ((bx0 + 50, by0 + 50), (bx1 - 50, by0 + 50), (bx0 + 50, by1 - 50), (bx1 - 50, by1 - 50)):
        dr.ellipse([sx - 16, sy - 16, sx + 16, sy + 16], fill=rgba((150, 155, 160), 1))
        dr.line([(sx - 9, sy), (sx + 9, sy)], fill=rgba((60, 60, 60), 1), width=4)
    slot = [W / 2 - 90, CY - 230, W / 2 + 90, CY + 170]
    dr.rounded_rectangle(slot, 30, fill=rgba((16, 16, 18), 1))
    k = ease(prog(t, flip, 0.18)); on = k < 0.5
    ly = (CY - 130) + (CY + 70 - (CY - 130)) * k
    col = GREEN if on else RED
    dr.rounded_rectangle([W / 2 - 75, ly - 90, W / 2 + 75, ly + 90], 22, fill=rgba(col, 1))
    dr.rounded_rectangle([W / 2 - 60, ly - 80, W / 2 + 60, ly - 50], 12, fill=rgba(WHITE, 0.35))
    dr.text((W / 2, by0 + 22 + 40), "ON" if on else "OFF", font=F("black", 64), fill=rgba(col, 1), anchor="mm")
    # faíscas
    if t > flip:
        rng = np.random.default_rng(5); e = t - flip
        for _ in range(40):
            ang = rng.random() * 2 * math.pi; sp = 400 + rng.random() * 900
            r0 = sp * e; r1 = sp * max(0, e - 0.05)
            a = clamp(1 - e / 0.7)
            if a <= 0: break
            cx, cy = W / 2, CY - 30
            dr.line([(cx + math.cos(ang) * r1, cy + math.sin(ang) * r1), (cx + math.cos(ang) * r0, cy + math.sin(ang) * r0)],
                    fill=rgba(YEL, a), width=5)
    pill(dr, W / 2, by0 - 90, p.get("kicker", "MECANISMO DE SEGURANÇA"), 46, WHITE, (20, 20, 20), ease(prog(t, 0, 0.3)))
    if p.get("label"):
        put(img, text_layer(p["label"], 66, YEL, "black", 6), W / 2, by1 + 110, back(prog(t, flip + 0.3, 0.35)))
    return [(0.0, "whoosh", 0.5), (flip, "hit", 0.7), (flip + 0.02, "glitch", 0.4)]

def sc_gauge(img, dr, t, D, p):
    """Termômetro da queda: desce até o limite de -10% e trava."""
    lim = p.get("limit", 10)
    x0, x1, y0, y1 = W / 2 - 120, W / 2 + 120, CY - 400, CY + 330
    dr.rounded_rectangle([x0 - 10, y0 - 10, x1 + 10, y1 + 10], 40, fill=rgba((40, 44, 50), 1))
    dr.rounded_rectangle([x0, y0, x1, y1], 32, fill=rgba((12, 12, 14), 1))
    k = ease_io(prog(t, 0.2, 1.4)); v = lim * 1.05 * k
    def Y(val): return y0 + 30 + (y1 - y0 - 60) * val / (lim * 1.1)
    yy = Y(min(v, lim))
    dr.rounded_rectangle([x0 + 12, y0 + 12, x1 - 12, max(y0 + 40, yy)], 24, fill=rgba(RED, 1))
    for i in range(0, lim + 1, 2):
        ty = Y(i); dr.line([(x1 + 20, ty), (x1 + 60, ty)], fill=rgba(WHITE, 0.8), width=4)
        dr.text((x1 + 80, ty), f"-{i}%" if i else "0%", font=F("bold", 44), fill=rgba(WHITE, 0.85), anchor="lm")
    hitt = 0.2 + 1.4 * 0.93
    reached = t >= hitt
    ly = Y(lim); blink = (math.sin(t * 14) > 0) if reached else True
    dr.line([(60, ly), (x0 - 20, ly)], fill=rgba(YEL, 1 if blink else 0.3), width=8)
    dr.text((70, ly - 46), "LIMITE", font=F("black", 52), fill=rgba(YEL, 1 if blink else 0.3), anchor="lm")
    if reached:
        kk = back(prog(t, hitt, 0.3))
        put(img, text_layer("PARA TUDO!", 120, WHITE, "black", 10, RED), W / 2, CY + 470, kk, 1.0, rot=-7)
    if p.get("kicker"):
        pill(dr, W / 2, y0 - 90, p["kicker"], 46, WHITE, (20, 20, 20), ease(prog(t, 0, 0.3)))
    return [(0.0, "whoosh", 0.5), (0.2, "riser", 0.4), (hitt, "hit", 0.7)]

def lock_icon(dr, cx, cy, s, col, closed=1.0):
    lift = (1 - closed) * 40 * s
    dr.arc([cx - 55 * s, cy - 120 * s - lift, cx + 55 * s, cy - 10 * s - lift], 180, 360, fill=rgba(col, 1), width=int(20 * s))
    dr.line([(cx - 45 * s, cy - 65 * s - lift), (cx - 45 * s, cy - 10 * s)], fill=rgba(col, 1), width=int(20 * s))
    dr.line([(cx + 45 * s, cy - 65 * s - lift), (cx + 45 * s, cy - 20 * s - lift)], fill=rgba(col, 1), width=int(20 * s))
    dr.rounded_rectangle([cx - 80 * s, cy - 20 * s, cx + 80 * s, cy + 100 * s], int(20 * s), fill=rgba(col, 1))
    dr.ellipse([cx - 14 * s, cy + 22 * s, cx + 14 * s, cy + 50 * s], fill=rgba((20, 20, 20), 1))

def sc_timer(img, dr, t, D, p):
    """Cronômetro de 30 minutos com cadeado: negociações suspensas."""
    mins = p.get("minutes", 30)
    k = ease_io(prog(t, 0.2, 1.6))
    r = 330; cx, cy = W / 2, CY - 60
    dr.ellipse([cx - r, cy - r, cx + r, cy + r], outline=rgba((50, 60, 80), 1), width=40)
    if k > 0: dr.arc([cx - r, cy - r, cx + r, cy + r], -90, -90 + 360 * k, fill=rgba(GOLD, 1), width=40)
    ang = math.radians(-90 + 360 * k)
    dr.ellipse([cx + math.cos(ang) * r - 30, cy + math.sin(ang) * r - 30, cx + math.cos(ang) * r + 30, cy + math.sin(ang) * r + 30], fill=rgba(WHITE, 1))
    dr.text((cx, cy - 30), f"{int(round(mins * k))}", font=F("black", 250), fill=rgba(WHITE, 1), anchor="mm")
    dr.text((cx, cy + 120), "MINUTOS", font=F("black", 64), fill=rgba(GOLD, 1), anchor="mm")
    closed = ease(prog(t, 1.9, 0.25))
    lock_icon(dr, cx + 260, cy - 270, 0.8, RED, closed)
    if p.get("label"):
        put(img, text_layer(p["label"], 64, WHITE, "black", 8, RED), W / 2, CY + 400, back(prog(t, 0.6, 0.35)))
    return [(0.0, "whoosh", 0.5)] + [(0.2 + 0.27 * i, "tick", 0.45) for i in range(6)] + [(1.9, "hit", 0.6)]

@lru_cache(None)
def brazil_layer(size=900):
    d = json.load(open(os.path.join(R.ASSETS, "geo", "countries.geojson")))
    feats = {}
    for f in d["features"]:
        pr = f["properties"]; iso = pr.get("ADM0_A3") or pr.get("ISO_A3")
        feats[iso] = f["geometry"]
    lon0, lon1, lat0, lat1 = -75, -33, -35, 7
    s = size / (lon1 - lon0)
    lay = Image.new("RGBA", (size, int((lat1 - lat0) * s)))
    ld = ImageDraw.Draw(lay)
    def rings(g):
        polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        return [poly[0] for poly in polys]
    for iso, g in feats.items():
        if not g: continue
        for rg in rings(g):
            pts = [((x - lon0) * s, (lat1 - y) * s) for x, y in rg]
            if iso == "BRA": continue
            ld.polygon(pts, fill=(30, 52, 44, 255), outline=(70, 110, 90, 255))
    br = Image.new("L", lay.size); bd = ImageDraw.Draw(br)
    for rg in rings(feats["BRA"]):
        bd.polygon([((x - lon0) * s, (lat1 - y) * s) for x, y in rg], fill=255)
    return lay, br, s, lon0, lat1

def sc_map(img, dr, t, D, p):
    """Mapa do Brasil pulsando em vermelho, com ondas saindo de Brasília."""
    base, mask, s, lon0, lat1 = brazil_layer()
    k = ease(prog(t, 0, 0.6)); zoom = 0.9 + 0.12 * (t / max(D, 0.1))
    lay = base.copy()
    a = 0.75 + 0.25 * math.sin(t * 5)
    red = Image.new("RGBA", lay.size, RED + (int(255 * a),)); lay.paste(red, (0, 0), mask)
    edge = mask.filter(ImageFilter.FIND_EDGES).point(lambda v: 255 if v > 30 else 0)
    lay.paste(Image.new("RGBA", lay.size, (255, 200, 200, 255)), (0, 0), edge)
    bx, by = (-47.9 - lon0) * s, (lat1 + 15.8) * s
    ld = ImageDraw.Draw(lay)
    for i in range(3):
        rr = ((t * 260 + i * 140) % 420)
        ld.ellipse([bx - rr, by - rr, bx + rr, by + rr], outline=(255, 255, 255, int(200 * (1 - rr / 420))), width=6)
    ld.ellipse([bx - 16, by - 16, bx + 16, by + 16], fill=(255, 255, 255, 255))
    lay = R.warp3d(lay, 0.12 * math.sin(t * 0.9), 0)
    put(img, lay, W / 2, CY + 20, zoom * k, clamp(k * 2))
    if p.get("label"):
        put(img, text_layer(p["label"], 70, WHITE, "black", 8), W / 2, CY - 450, back(prog(t, 0.4, 0.35)))
    return [(0.0, "whoosh", 0.5), (0.4, "boom", 0.4)]

def sc_outro(img, dr, t, D, p):
    """Final: marca do canal + botão de inscrever com clique."""
    pulse_glow(img, t, RED, 1.0, 0.35)
    lay = ext3d("IMPACTO", 170, (255, 255, 255), (70, 76, 82), 22)
    shadowed(img, R.warp3d(lay, 0.15 * math.sin(t * 1.5), 0), W / 2, CY - 330, back(prog(t, 0, 0.35)))
    lay2 = ext3d("ECONÔMICO", 150, (255, 80, 90), (90, 10, 18), 22)
    shadowed(img, R.warp3d(lay2, 0.15 * math.sin(t * 1.5 + 1), 0), W / 2, CY - 140, back(prog(t, 0.2, 0.35)))
    clicked = t > 1.1
    k = back(prog(t, 0.45, 0.35)); press = 1 - 0.08 * math.exp(-max(0, t - 1.1) * 10) * clicked
    bw, bh = 640 * k * press, 150 * k * press
    if k > 0.02:
        col = (90, 90, 90) if clicked else RED
        dr.rounded_rectangle([W / 2 - bw / 2, CY + 140 - bh / 2, W / 2 + bw / 2, CY + 140 + bh / 2], bh / 2, fill=rgba(col, 1))
        put(img, text_layer("INSCRITO!" if clicked else "INSCREVA-SE", 66, WHITE, "black"), W / 2, CY + 142, k * press)
    # cursor
    ck = ease(prog(t, 0.6, 0.5)); mx = W / 2 + 120 + 300 * (1 - ck); my = CY + 170 + 300 * (1 - ck)
    if ck > 0:
        dr.polygon([(mx, my), (mx, my + 80), (mx + 22, my + 60), (mx + 40, my + 98), (mx + 54, my + 90), (mx + 36, my + 54), (mx + 64, my + 52)],
                   fill=rgba(WHITE, 1), outline=rgba(INK, 1))
    if p.get("label"):
        dr.text((W / 2, CY + 330), p["label"], font=F("bold", 46), fill=rgba(WHITE, ease(prog(t, 0.8, 0.4))), anchor="mm")
    return [(0.0, "whoosh", 0.5), (1.1, "pop", 0.6), (1.15, "ding", 0.5)]

SCENES = {k[3:]: v for k, v in globals().items() if k.startswith("sc_")}
BGS = {"hook": "red", "date": "dark", "candles": "dark", "bignum": "red", "ticker": "dark", "alert": "red",
       "since": "navy", "question": "navy", "switch": "dark", "gauge": "dark", "timer": "navy", "map": "dark", "outro": "red"}

# ================= LEGENDA (palavra por palavra) =================
KEYS = {"bolsa", "despenca", "queda", "grave", "circuit", "breaker", "b3", "ibovespa", "seguranca", "suspensas",
        "turbulentos", "preocupacao", "futuro", "minutos", "negociacoes"}

def caption_chunks(words, maxw=930, size=92):
    f = F("black", size); chunks = []; cur = []
    for i, w in enumerate(words):
        txt = w[2].strip().upper()
        if not txt: continue
        test = " ".join(x[2] for x in cur + [[0, 0, txt]])
        gap = (w[0] - cur[-1][1]) if cur else 0
        prev_end = cur[-1][2][-1:] in ".,?!" if cur else False
        if cur and (len(cur) >= 3 or tw(f, test) > maxw or gap > 0.35 or prev_end):
            chunks.append(cur); cur = []
        cur.append([w[0], w[1], txt])
    if cur: chunks.append(cur)
    out = []
    for i, c in enumerate(chunks):
        end = chunks[i + 1][0][0] if i + 1 < len(chunks) else c[-1][1] + 0.5
        out.append((c[0][0], min(end, c[-1][1] + 0.6), c))
    return out

def draw_caption(img, g, chunks, size=92):
    cur = None
    for a, b, c in chunks:
        if a - 0.02 <= g < b: cur = (a, c); break
    if not cur: return
    a, c = cur; f = F("black", size)
    space = tw(f, " ")
    widths = [tw(f, w[2]) for w in c]; total = sum(widths) + space * (len(c) - 1)
    x = W / 2 - total / 2
    k_in = back(prog(g, a, 0.15))
    for (s, e, txt), wd in zip(c, widths):
        if g < s - 0.02: col = (255, 255, 255); alpha = 0.0
        else:
            alpha = 1.0
            nk = " ".join(R.norm(txt))
            active = s - 0.02 <= g < e + 0.05
            col = YEL if active else ((255, 85, 95) if (nk in KEYS or any(ch.isdigit() for ch in txt)) else (255, 255, 255))
        if alpha > 0:
            pk = 1 + 0.22 * (1 - ease(prog(g, s, 0.12)))
            lay = text_layer(txt, size, col, "black", 9)
            put(img, lay, x + wd / 2, CAP_Y, pk * clamp(k_in, 0.5, 1.2))
        x += wd + space

# ================= QUADRO =================
def frame(scene, t, D, g, chunks, total, rng):
    kind = scene["type"]
    img = background(scene.get("bg") or BGS.get(kind, "dark"), g)
    dr = ImageDraw.Draw(img, "RGBA")
    sfx = SCENES[kind](img, dr, t, D, scene)
    # câmera: punch-in na entrada + aproximação lenta + tremor nos impactos
    s = 1.0 + 0.035 * (t / max(D, 0.1)) + 0.16 * (1 - ease(prog(t, 0, 0.3)))
    dx = dy = 0.0
    for at, name, gn in sfx:
        if name in ("hit", "boom") and 0 <= t - at < 0.35:
            e = (1 - (t - at) / 0.35) * 22 * gn; dx += rng.normal(0, e); dy += rng.normal(0, e)
    cw, ch = W / s, H / s; x0, y0 = (W - cw) / 2 + dx, (H - ch) / 2 + dy
    im = img.transform((W, H), Image.EXTENT, (x0, y0, x0 + cw, y0 + ch), Image.BILINEAR)
    if not scene.get("nocap"): draw_caption(im, g, chunks)
    d = ImageDraw.Draw(im, "RGBA")
    # marca + barra de progresso
    d.rectangle([0, 0, W, 10], fill=(0, 0, 0, 120)); d.rectangle([0, 0, W * g / total, 10], fill=rgba(RED, 1))
    d.text((W / 2, 70), BRAND, font=F("black", 34), fill=rgba(WHITE, 0.75), anchor="mm")
    a = np.asarray(im.convert("RGB"), dtype=np.float32)
    # flash branco na troca de cena e glitch RGB nos impactos
    fl = 0.55 * (1 - prog(t, 0, 0.12))
    glitch = any(name == "glitch" and 0 <= t - at < 0.2 for at, name, _ in sfx) or t < 0.07
    if glitch:
        sh = int(rng.integers(12, 28)); a[..., 0] = np.roll(a[..., 0], sh, 1); a[..., 2] = np.roll(a[..., 2], -sh, 1)
        for _ in range(4):
            y = int(rng.integers(0, H - 60)); hgt = int(rng.integers(10, 60)); a[y:y + hgt] = np.roll(a[y:y + hgt], int(rng.integers(-60, 60)), 1)
    if fl > 0: a = a * (1 - fl) + 255 * fl
    a = a * R.vignette() + R.grains()[int(g * FPS) % 6]
    return np.clip(a, 0, 255).astype(np.uint8), sfx

def render_scene(args):
    i, scene, f0, f1, outdir, chunks, total = args
    n = f1 - f0; D = n / FPS; path = f"{outdir}/s{i:03d}.mp4"
    proc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
                             "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-threads", "2", path],
                            stdin=subprocess.PIPE)
    rng = np.random.default_rng(i); sfx = None
    for k in range(n):
        a, s = frame(scene, k / FPS, D, (f0 + k) / FPS, chunks, total, rng)
        if sfx is None: sfx = s
        proc.stdin.write(a.tobytes())
    proc.stdin.close(); proc.wait()
    ev = [(f0 / FPS + a, name, g) for a, name, g in (sfx or []) if a < D]
    json.dump(ev, open(f"{outdir}/s{i:03d}.json", "w"))
    return i

def main():
    plan_p, tx_p, voice_p, assets, out = sys.argv[1:6]
    R.ASSETS = assets; os.environ["ASSETS"] = assets
    plan = json.load(open(plan_p))
    words = [w for s in json.load(open(tx_p)) for w in s["w"]]
    vdur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", voice_p],
                                capture_output=True, text=True).stdout)
    total = vdur + float(os.environ.get("TAIL", "2.2"))
    for sc in plan:
        if sc.get("at") == "end": sc["at"] = vdur + 0.1
    starts = R.resolve(plan, words, total)
    chunks = caption_chunks(words)
    work = os.path.splitext(out)[0] + "_parts"; os.makedirs(work, exist_ok=True)
    jobs = []; only = os.environ.get("ONLY")
    for i, sc in enumerate(plan):
        f0 = round(starts[i] * FPS); f1 = round((starts[i + 1] if i + 1 < len(plan) else total) * FPS)
        if f1 - f0 < 1: continue
        print(f"cena {i:2d} {sc['type']:9s} {starts[i]:6.2f}s  ({(f1 - f0) / FPS:.1f}s)")
        if only and str(i) not in only.split(","): continue
        jobs.append((i, sc, f0, f1, work, chunks, total))
    order = sorted(jobs, key=lambda j: -(j[3] - j[2]))
    with Pool(int(os.environ.get("JOBS", "4"))) as pool: pool.map(render_scene, order, chunksize=1)
    if only: print("ok parcial"); return
    events = [e for j in jobs for e in json.load(open(f"{work}/s{j[0]:03d}.json"))]
    with open(f"{work}/list.txt", "w") as fl:
        for j in jobs: fl.write(f"file 's{j[0]:03d}.mp4'\n")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", f"{work}/list.txt", "-c", "copy", f"{work}/video.mp4"], check=True)
    R.mix(voice_p, events, os.path.join(assets, "sfx"), os.path.join(assets, "sfx", "music.wav"), f"{work}/audio.wav", total)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", f"{work}/video.mp4", "-i", f"{work}/audio.wav", "-c:v", "copy",
                    "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", out], check=True)
    print("OK", out, f"{total:.1f}s")

if __name__ == "__main__":
    main()
