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
    if alpha <= 0.02: return
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
    rng = np.random.default_rng(3); n = 60; k = ease(prog(t, 0, 1.6)) if p.get("chart", True) else 0
    ys = np.cumsum(rng.normal(0, 14, n)) + np.linspace(0, 760, n) ** 1.15 / 2.4
    pts = [(40 + i * (W - 80) / (n - 1), 380 + ys[i]) for i in range(int(2 + (n - 2) * k))]
    if len(pts) > 2:
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
    sg = -1 if p.get("up") else 1
    for i in range(n - 1): price.append(price[-1] + sg * (rng.normal(-0.9, 2.2) - (2.5 if 25 < i < 34 else 0)))
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
    dr.text(((x1 + W) / 2, ly + 2), "▲" if p.get("up") else "▼", font=F("sym", 34), fill=rgba(WHITE, 1), anchor="mm")
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
    lay = text_layer(txt.replace("▼ ", ""), 170, RED, "black")
    put(img, lay, W / 2 + 50, y0 + 420, 1.0, blink)
    dr.text((W / 2 - lay.width / 2 - 10, y0 + 420), "▼", font=F("sym", 110), fill=rgba(RED, blink), anchor="mm")
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
def country_layer(iso="BRA", view=(-75, -33, -35, 7), size=900):
    """Recorte de mapa: vizinhos em verde-escuro e máscara do país em destaque (projeção com correção de latitude)."""
    d = json.load(open(os.path.join(R.ASSETS, "geo", "countries.geojson")))
    lon0, lon1, lat0, lat1 = view
    cl = math.cos(math.radians((lat0 + lat1) / 2))
    s = size / ((lon1 - lon0) * cl)
    lay = Image.new("RGBA", (size, int((lat1 - lat0) * s))); ld = ImageDraw.Draw(lay)
    mask = Image.new("L", lay.size); md = ImageDraw.Draw(mask)
    def P(x, y): return ((x - lon0) * s * cl, (lat1 - y) * s)
    for f in d["features"]:
        g = f["geometry"]; pr = f["properties"]
        if not g: continue
        code = pr.get("ADM0_A3") or pr.get("ISO_A3")
        polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
        for poly in polys:
            pts = [P(x, y) for x, y in poly[0]]
            if code == iso: md.polygon(pts, fill=255)
            else: ld.polygon(pts, fill=(30, 52, 44, 255), outline=(70, 110, 90, 255))
    return lay, mask, P

def sc_map(img, dr, t, D, p):
    """Mapa de um país pulsando em vermelho, com ondas saindo de um ponto (capital/cidade)."""
    base, mask, P = country_layer(p.get("iso", "BRA"), tuple(p.get("view", (-75, -33, -35, 7))), p.get("size", 900))
    k = ease(prog(t, 0, 0.6)); zoom = 0.9 + 0.12 * (t / max(D, 0.1))
    lay = base.copy()
    a = 0.75 + 0.25 * math.sin(t * 5)
    lay.paste(Image.new("RGBA", lay.size, RED + (int(255 * a),)), (0, 0), mask)
    edge = mask.filter(ImageFilter.FIND_EDGES).point(lambda v: 255 if v > 30 else 0)
    lay.paste(Image.new("RGBA", lay.size, (255, 200, 200, 255)), (0, 0), edge)
    bx, by = P(*p.get("pin", (-47.9, -15.8)))
    ld = ImageDraw.Draw(lay)
    for i in range(3):
        rr = ((t * 260 + i * 140) % 420)
        ld.ellipse([bx - rr, by - rr, bx + rr, by + rr], outline=(255, 255, 255, int(200 * (1 - rr / 420))), width=6)
    ld.ellipse([bx - 16, by - 16, bx + 16, by + 16], fill=(255, 255, 255, 255))
    for (lo, la, txt) in p.get("labels", []):
        x, y = P(lo, la); ld.text((x, y), txt, font=F("black", 40), fill=(235, 240, 235, int(255 * ease(prog(t, 0.3, 0.4)))), anchor="mm",
                                  stroke_width=5, stroke_fill=(0, 0, 0, 200))
    for j, route in enumerate(p.get("ships", [])):
        pts = [P(*q) for q in route]
        segs = [math.dist(a_, b_) for a_, b_ in zip(pts[:-1], pts[1:])]; tot = sum(segs)
        ld.line(pts, fill=(255, 255, 255, 70), width=4)
        for m in range(3):
            dd = ((t * 70 + m * tot / 3 + j * 40) % tot); ii = 0
            while ii < len(segs) - 1 and dd > segs[ii]: dd -= segs[ii]; ii += 1
            f_ = dd / segs[ii]; x = pts[ii][0] + (pts[ii + 1][0] - pts[ii][0]) * f_; y = pts[ii][1] + (pts[ii + 1][1] - pts[ii][1]) * f_
            ld.rounded_rectangle([x - 18, y - 9, x + 18, y + 9], 6, fill=(255, 200, 40, 255), outline=(40, 30, 0, 255), width=2)
    for (a0, b0, t0) in p.get("strikes", []):
        ks = prog(t, t0, 0.7)
        if ks <= 0: continue
        (x0, y0), (x1, y1) = P(*a0), P(*b0); mx, my = (x0 + x1) / 2, min(y0, y1) - 220
        path = []
        for q in np.linspace(0, ease_io(ks), 24):
            path.append(((1 - q) ** 2 * x0 + 2 * (1 - q) * q * mx + q * q * x1, (1 - q) ** 2 * y0 + 2 * (1 - q) * q * my + q * q * y1))
        if len(path) > 1: ld.line(path, fill=(255, 120, 60, 255), width=7); ld.ellipse([path[-1][0] - 10, path[-1][1] - 10, path[-1][0] + 10, path[-1][1] + 10], fill=(255, 255, 255, 255))
        ke = prog(t, t0 + 0.7, 0.6)
        if 0 < ke < 1:
            rr = 30 + 160 * ease(ke); al = int(255 * (1 - ke))
            ld.ellipse([x1 - rr, y1 - rr, x1 + rr, y1 + rr], fill=(255, 150, 40, al)); ld.ellipse([x1 - rr * 0.5, y1 - rr * 0.5, x1 + rr * 0.5, y1 + rr * 0.5], fill=(255, 245, 200, al))
    if p.get("pin_label") and t > 0.5:
        f = F("black", 54); w = tw(f, p["pin_label"]) + 40
        lx = bx + 30 if bx + 30 + w < lay.width else bx - 30 - w
        ld.rounded_rectangle([lx, by - 110, lx + w, by - 30], 14, fill=(15, 15, 15, 235))
        ld.text((lx + 20, by - 70), p["pin_label"], font=f, fill=(255, 255, 255, 255), anchor="lm")
    lay = R.warp3d(lay, 0.12 * math.sin(t * 0.9), 0)
    put(img, lay, W / 2, CY + 20, zoom * k, clamp(k * 2))
    if p.get("label"):
        put(img, text_layer(p["label"], 70, WHITE, "black", 8), W / 2, CY - 450, back(prog(t, 0.4, 0.35)))
    return [(0.0, "whoosh", 0.5), (0.4, "boom", 0.4)] + [(st[2] + 0.7, "boom", 0.6) for st in p.get("strikes", [])] + [(st[2] + 0.72, "hit", 0.5) for st in p.get("strikes", [])]

# ---------- pessoas / instituições (silhuetas genéricas, nunca rostos reais) ----------
def silhouette(d, cx, cy, s, col, tie=None):
    d.ellipse([cx - 60 * s, cy - 170 * s, cx + 60 * s, cy - 50 * s], fill=rgba(col, 1))
    d.rounded_rectangle([cx - 120 * s, cy - 30 * s, cx + 120 * s, cy + 150 * s], int(70 * s), fill=rgba(col, 1))
    if tie: d.polygon([(cx, cy - 25 * s), (cx - 16 * s, cy + 10 * s), (cx, cy + 90 * s), (cx + 16 * s, cy + 10 * s)], fill=rgba(tie, 1))

def person_card(name, role, col, w=470, h=640, icon_kind=None):
    c = Image.new("RGBA", (w, h)); d = ImageDraw.Draw(c, "RGBA")
    d.rounded_rectangle([0, 0, w, h], 36, fill=(245, 242, 235, 255))
    d.rounded_rectangle([0, 0, w, 380], 36, fill=col + (255,)); d.rectangle([0, 340, w, 380], fill=col + (255,))
    if icon_kind == "bank": building(d, w / 2, 350, 0.42, (245, 242, 235), tuple(int(v * 0.6) for v in col))
    else: silhouette(d, w / 2, 250, 1.15, tuple(int(v * 0.45) for v in col), (240, 240, 240))
    lines = R.wrap(name, F("black", 56), w - 40)
    for i, ln in enumerate(lines[:2]):
        d.text((w / 2, 440 + i * 62), ln, font=F("black", 56), fill=INK + (255,), anchor="mm")
    d.text((w / 2, 440 + len(lines[:2]) * 62 + 20), role, font=F("bold", 38), fill=col + (255,), anchor="mm")
    return c

def sc_versus(img, dr, t, D, p):
    """Duelo: dois cartões entrando pelos lados e um VS 3D com raio."""
    L, Rr = p["left"], p["right"]
    ra, va = p.get("right_at", 0.35), p.get("vs_at", 0.8)
    for side, info, a0 in ((-1, L, 0.0), (1, Rr, ra)):
        k = back(prog(t, a0, 0.45))
        if k <= 0: continue
        card = person_card(info["name"], info["role"], tuple(info.get("color", BLUE if side < 0 else RED)), icon_kind=info.get("icon"))
        card = R.warp3d(card, -0.25 * side + 0.05 * math.sin(t * 1.5), 0)
        x = W / 2 + side * 275 + side * 700 * (1 - k)
        shadowed(img, card, x, CY + 10 * math.sin(t * 2 + side), 0.8)
    kv = prog(t, va, 0.25)
    if kv > 0:
        if 0 < t - va < 0.15:
            img.alpha_composite(Image.new("RGBA", (W, H), (255, 255, 255, 120)))
        bolt = [(W / 2 + 40, CY - 420), (W / 2 - 50, CY - 60), (W / 2 + 30, CY - 60), (W / 2 - 40, CY + 400)]
        dr.line(bolt, fill=rgba(YEL, 0.9 * (0.6 + 0.4 * math.sin(t * 30))), width=16, joint="curve")
        lay = ext3d("VS", 230, (255, 214, 10), (130, 90, 0), 26)
        shadowed(img, R.warp3d(lay, 0.2 * math.sin(t * 2), 0), W / 2, CY - 40, 2.2 - 1.2 * ease(kv) if kv < 1 else 1.0)
    if p.get("kicker"): pill(dr, W / 2, CY - 480, p["kicker"], 48, WHITE, (20, 20, 20), ease(prog(t, 0, 0.3)))
    return [(0.0, "whoosh", 0.5), (ra, "whoosh", 0.4), (va, "boom", 0.6), (va + 0.02, "glitch", 0.3)]

def building(d, cx, base_y, s, col, shade):
    w = 820 * s; colw = 64 * s; n = 6
    d.polygon([(cx - w / 2 - 30 * s, base_y - 520 * s), (cx, base_y - 720 * s), (cx + w / 2 + 30 * s, base_y - 520 * s)], fill=rgba(col, 1))
    d.polygon([(cx - w / 2 + 40 * s, base_y - 540 * s), (cx, base_y - 680 * s), (cx + w / 2 - 40 * s, base_y - 540 * s)], fill=rgba(shade, 1))
    d.rectangle([cx - w / 2 - 20 * s, base_y - 520 * s, cx + w / 2 + 20 * s, base_y - 470 * s], fill=rgba(col, 1))
    for i in range(n):
        x = cx - w / 2 + 50 * s + i * (w - 100 * s - colw) / (n - 1)
        d.rectangle([x, base_y - 470 * s, x + colw, base_y - 90 * s], fill=rgba(col, 1))
        d.rectangle([x + colw * 0.62, base_y - 470 * s, x + colw, base_y - 90 * s], fill=rgba(shade, 1))
    for j in range(3):
        d.rectangle([cx - w / 2 - 20 * s - j * 30 * s, base_y - 90 * s + j * 30 * s, cx + w / 2 + 20 * s + j * 30 * s, base_y - 60 * s + j * 30 * s], fill=rgba(col, 1))

def sc_court(img, dr, t, D, p):
    """Prédio do tribunal (colunas) subindo; com `crack`, racha e treme."""
    k = back(prog(t, 0, 0.5)); by = CY + 330 + 900 * (1 - clamp(k))
    pulse_glow(img, t, RED if p.get("crack") else GOLD, 1.3, 0.25, CY - 100)
    ov = Image.new("RGBA", (W, H)); od = ImageDraw.Draw(ov, "RGBA")
    building(od, W / 2, by, 1.0, (238, 232, 218), (190, 182, 165))
    if p.get("crack"):
        ck = ease(prog(t, 0.6, 0.8)); rng = np.random.default_rng(4)
        for c in range(3):
            x, y = W / 2 + (c - 1) * 230, by - 690 + c * 40; pts = [(x, y)]
            for _ in range(int(2 + 12 * ck)):
                x += rng.normal(0, 40); y += 50; pts.append((x, y))
            od.line(pts, fill=(25, 20, 20, 255), width=10)
    img.alpha_composite(R.warp3d(ov.crop((0, 0, W, H)), 0.06 * math.sin(t * 1.2), 0).resize((W, H)))
    if p.get("stamp"):
        at = p.get("at_stamp", 0.8); ks = prog(t, at, 0.22)
        if ks > 0:
            st = text_layer(p["stamp"], 130, RED, "black", 0)
            box = Image.new("RGBA", (st.width + 60, st.height + 20)); bd = ImageDraw.Draw(box)
            bd.rounded_rectangle([4, 4, box.width - 4, box.height - 4], 20, outline=RED + (255,), width=14); box.alpha_composite(st, (30, 10))
            put(img, fit(box, 980), W / 2, CY - 60, 2.6 - 1.6 * ease(ks) if ks < 1 else 1.0, 0.95, rot=12)
    if p.get("label"):
        put(img, text_layer(p["label"], 66, WHITE, "black", 8, (0, 0, 0)), W / 2, CY + 420, back(prog(t, 0.5, 0.35)))
    if p.get("kicker"): pill(dr, W / 2, CY - 500, p["kicker"], 48, WHITE, RED, ease(prog(t, 0.2, 0.3)))
    ev = [(0.0, "whoosh_down", 0.5), (0.35, "hit", 0.5)]
    if p.get("stamp"): ev.append((p.get("at_stamp", 0.8) + 0.2, "hit", 0.8))
    if p.get("crack"): ev += [(0.6, "glitch", 0.4), (0.9, "boom", 0.5)]
    return ev

def sc_stamp(img, dr, t, D, p):
    """Cartão de uma autoridade e um carimbo vermelho batendo por cima."""
    k = back(prog(t, 0, 0.4))
    card = person_card(p["name"], p["role"], tuple(p.get("color", (70, 80, 100))), 560, 700)
    card = R.warp3d(card, 0.15 * math.sin(t * 1.3), 0)
    shadowed(img, card, W / 2, CY - 20, clamp(k, 0, 1.2))
    at = p.get("at_stamp", 0.9); ks = prog(t, at, 0.22)
    if ks > 0:
        st = text_layer(p.get("stamp", "SUSPENSO"), 150, RED, "black", 0)
        box = Image.new("RGBA", (st.width + 60, st.height + 20)); bd = ImageDraw.Draw(box)
        bd.rounded_rectangle([4, 4, box.width - 4, box.height - 4], 20, outline=RED + (255,), width=14)
        box.alpha_composite(st, (30, 10))
        put(img, fit(box, 980), W / 2, CY + 60, 2.6 - 1.6 * ease(ks) if ks < 1 else 1.0, 0.92, rot=14)
    if p.get("kicker"): pill(dr, W / 2, CY - 480, p["kicker"], 48, WHITE, (20, 20, 20), ease(prog(t, 0, 0.3)))
    return [(0.0, "whoosh", 0.5), (at + 0.2, "hit", 0.8), (at + 0.22, "paper", 0.4)]

def icon(d, kind, cx, cy, s, col):
    if kind == "politico": silhouette(d, cx, cy + 30 * s, s * 0.8, col, (230, 57, 70))
    elif kind == "autoridade":
        d.polygon([(cx, cy - 120 * s), (cx + 100 * s, cy - 70 * s), (cx + 85 * s, cy + 60 * s), (cx, cy + 130 * s), (cx - 85 * s, cy + 60 * s), (cx - 100 * s, cy - 70 * s)], fill=rgba(col, 1))
        star = [(cx + math.cos(math.radians(-90 + 36 * i)) * (55 if i % 2 == 0 else 22) * s, cy + math.sin(math.radians(-90 + 36 * i)) * (55 if i % 2 == 0 else 22) * s) for i in range(10)]
        d.polygon(star, fill=rgba(YEL, 1))
    elif kind.startswith("glyph:"):
        d.text((cx, cy + 6 * s), kind[6:], font=F("sym", int(150 * s)), fill=rgba(col, 1), anchor="mm")
    else:  # manifestantes: placa levantada
        d.line([(cx, cy - 40 * s), (cx, cy + 130 * s)], fill=rgba((150, 110, 70), 1), width=int(16 * s))
        d.rounded_rectangle([cx - 110 * s, cy - 140 * s, cx + 110 * s, cy - 20 * s], int(14 * s), fill=rgba(col, 1))
        d.text((cx, cy - 80 * s), "!!!", font=F("black", int(80 * s)), fill=rgba(RED, 1), anchor="mm")

def sc_reaction(img, dr, t, D, p):
    """Três reações aparecendo em sequência (ícones + rótulos)."""
    items = p.get("items", [["politico", "POLÍTICOS"], ["autoridade", "AUTORIDADES"], ["manifestante", "MANIFESTANTES"]])
    times = p.get("times", [0.2 + 0.6 * i for i in range(len(items))])
    ev = [(0.0, "whoosh", 0.5)]
    for i, ((kind, label), a) in enumerate(zip(items, times)):
        k = back(prog(t, a, 0.35))
        if k <= 0: continue
        gap = p.get("gap", 300); y = CY - 380 + i * gap; x = W / 2 + 18 * math.sin(t * 2 + i)
        ov = Image.new("RGBA", (W, 280)); od = ImageDraw.Draw(ov, "RGBA")
        od.rounded_rectangle([60, 10, W - 60, 270], 40, fill=(250, 248, 242, 255))
        od.ellipse([90, 30, 310, 250], fill=(30, 36, 50, 255))
        icon(od, kind, 200, 140, 0.75, (240, 240, 240))
        fs = 78
        while fs > 40 and tw(F("black", fs), label) > W - 60 - 350 - 30: fs -= 4
        od.text((350, 140), label, font=F("black", fs), fill=INK + (255,), anchor="lm")
        put(img, R.warp3d(ov, 0.12 * math.sin(t * 1.4 + i), 0), x + 400 * (1 - clamp(k)), y, clamp(k, 0, 1.1) * p.get("scale", 1.0))
        ev.append((a, "pop", 0.6))
    return ev

def sc_police(img, dr, t, D, p):
    """Sirene azul/vermelha piscando, distintivo e fita de isolamento."""
    on = int(t * 6) % 2
    ov = Image.new("RGBA", (W // 8, H // 8)); od = ImageDraw.Draw(ov)
    od.ellipse([-60, CY / 8 - 120, W / 16 + 20, CY / 8 + 120], fill=(230, 40, 50, 150 if on else 40))
    od.ellipse([W / 16 - 20, CY / 8 - 120, W / 8 + 60, CY / 8 + 120], fill=(40, 90, 255, 40 if on else 150))
    img.alpha_composite(ov.filter(ImageFilter.GaussianBlur(14)).resize((W, H), Image.BILINEAR))
    k = back(prog(t, 0.1, 0.45))
    b = Image.new("RGBA", (520, 600)); bd = ImageDraw.Draw(b, "RGBA")
    icon(bd, "autoridade", 260, 300, 2.3, (30, 60, 140))
    bd.text((260, 470), p.get("badge", "POLÍCIA"), font=F("black", 60), fill=(255, 255, 255, 255), anchor="mm")
    shadowed(img, R.warp3d(b, 0.3 * math.sin(t * 1.6), 0), W / 2, CY - 60, clamp(k, 0, 1.2))
    tape = Image.new("RGBA", (W + 500, 100)); td = ImageDraw.Draw(tape)
    td.rectangle([0, 0, W + 500, 100], fill=YEL + (255,))
    msg = "   ".join([p.get("tape", "ÁREA ISOLADA")] * 8); off = -(t * 260) % 700
    td.text((off - 700, 50), msg, font=F("black", 56), fill=(15, 15, 15, 255), anchor="lm")
    tape = tape.rotate(-9, Image.BICUBIC, expand=True)
    kt = ease(prog(t, 0.5, 0.35))
    img.alpha_composite(tape, (int(W / 2 - tape.width / 2 - 1400 * (1 - kt)), int(CY + 360 - tape.height / 2)))
    if p.get("label"):
        put(img, text_layer(p["label"], 64, WHITE, "black", 8, (0, 0, 0)), W / 2, CY - 470, back(prog(t, 0.3, 0.35)))
    return [(0.0, "whoosh", 0.5), (0.1, "alarm", 0.3), (0.5, "whoosh", 0.4)]

def sc_glitchword(img, dr, t, D, p):
    """Palavras 3D gigantes com glitch constante e rachaduras (para acusações / termos fortes)."""
    pulse_glow(img, t, RED, 0.4, 0.5)
    lines = p.get("lines", ["GOLPE", "*DE ESTADO?*"]); ev = [(0.0, "boom", 0.6), (0.05, "glitch", 0.5)]
    for i, ln in enumerate(lines):
        acc = ln.startswith("*"); ln = ln.strip("*"); a = 0.1 + i * 0.35
        kk = prog(t, a, 0.25)
        if kk <= 0: continue
        lay = ext3d(ln, 200 if not acc else 150, (255, 80, 90) if acc else (255, 255, 255), (90, 10, 18) if acc else (70, 76, 82), 26)
        jitter = (np.random.default_rng(int(t * 20) + i).normal(0, 10) if math.sin(t * 9 + i) > 0.6 else 0)
        shadowed(img, R.warp3d(lay, 0.15 * math.sin(t * 1.7 + i), 0), W / 2 + jitter, CY - 120 + i * 240, 2.4 - 1.4 * ease(kk) if kk < 1 else 1.0)
        if i: ev.append((a + 0.2, "hit", 0.6))
    if p.get("sub"): pill(dr, W / 2, CY + 330, p["sub"], 48, WHITE, (20, 20, 20), ease(prog(t, 1.0, 0.3)))
    return ev

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


def flag_img(iso, w=640, h=400):
    f = Image.new("RGBA", (w, h)); d = ImageDraw.Draw(f)
    if iso == "DEU":
        for i, c in enumerate([(20, 20, 20), (220, 30, 40), (255, 205, 0)]): d.rectangle([0, i * h / 3, w, (i + 1) * h / 3], fill=c + (255,))
    elif iso == "JPN":
        d.rectangle([0, 0, w, h], fill=(250, 250, 250, 255)); r = h * 0.3; d.ellipse([w / 2 - r, h / 2 - r, w / 2 + r, h / 2 + r], fill=(200, 16, 46, 255))
    elif iso == "GBR":
        d.rectangle([0, 0, w, h], fill=(1, 33, 105, 255))
        d.line([(0, 0), (w, h)], fill=(255, 255, 255, 255), width=int(h * 0.2)); d.line([(0, h), (w, 0)], fill=(255, 255, 255, 255), width=int(h * 0.2))
        d.line([(0, 0), (w, h)], fill=(200, 16, 46, 255), width=int(h * 0.07)); d.line([(0, h), (w, 0)], fill=(200, 16, 46, 255), width=int(h * 0.07))
        d.rectangle([w / 2 - h * 0.17, 0, w / 2 + h * 0.17, h], fill=(255, 255, 255, 255)); d.rectangle([0, h / 2 - h * 0.17, w, h / 2 + h * 0.17], fill=(255, 255, 255, 255))
        d.rectangle([w / 2 - h * 0.1, 0, w / 2 + h * 0.1, h], fill=(200, 16, 46, 255)); d.rectangle([0, h / 2 - h * 0.1, w, h / 2 + h * 0.1], fill=(200, 16, 46, 255))
    return f

def wave(img_f, t, amp=18):
    w, h = img_f.size; out = Image.new("RGBA", (w, h + 2 * amp)); n = 32; sw = w // n + 1
    for i in range(n):
        x = i * w // n; ph = math.sin(t * 5 - i * 0.35); y = amp + ph * amp * (i / n)
        strip = img_f.crop((x, 0, min(w, x + sw), h))
        if ph < 0: strip = Image.blend(strip, Image.new("RGBA", strip.size, (0, 0, 0, 255)), -ph * 0.25)
        out.paste(strip, (x, int(y)))
    return out

def sc_flagdays(img, dr, t, D, p):
    """Bandeira tremulando + contagem de dias em 3D."""
    k = back(prog(t, 0, 0.45))
    fl = wave(flag_img(p.get("iso", "GBR")), t)
    shadowed(img, R.warp3d(fl, 0.18 * math.sin(t * 1.2), 0), W / 2, CY - 300 - 600 * (1 - clamp(k)), 1.0)
    dr.text((W / 2, CY - 50), p.get("country", ""), font=F("black", 80), fill=rgba(WHITE, ease(prog(t, 0.3, 0.3))), anchor="mm")
    a = p.get("at_days", 0.6); kd = ease(prog(t, a, 0.7))
    if t >= a:
        n = int(round(p.get("days", 3) * kd))
        lay = R.extruded_text(str(n), 300, face=(255, 214, 10), side=(130, 90, 0), depth=26)
        s = 1 + 0.2 * (1 - ease(prog(t, a + 0.7, 0.25)))
        shadowed(img, R.warp3d(lay, 0.15 * math.sin(t * 1.6), 0), W / 2 - 120, CY + 220, s)
        dr.text((W / 2 + 110, CY + 230), p.get("unit", "DIAS"), font=F("black", 110), fill=rgba(WHITE, 1), anchor="lm")
    if p.get("label"): pill(dr, W / 2, CY + 450, p["label"], 46, WHITE, RED, ease(prog(t, 1.2, 0.3)))
    return [(0.0, "whoosh", 0.5), (a, "riser", 0.3), (a + 0.7, "hit", 0.6)]


def sc_phone(img, dr, t, D, p):
    """Celular com app do banco: saldo some, cadeado e alerta "conta bloqueada"."""
    k = back(prog(t, 0, 0.45))
    pw, ph = 520, 980
    ph_img = Image.new("RGBA", (pw, ph)); d = ImageDraw.Draw(ph_img, "RGBA")
    d.rounded_rectangle([0, 0, pw, ph], 70, fill=(25, 25, 30, 255))
    d.rounded_rectangle([20, 20, pw - 20, ph - 20], 56, fill=(245, 245, 248, 255))
    d.rounded_rectangle([pw / 2 - 70, 34, pw / 2 + 70, 62], 14, fill=(25, 25, 30, 255))
    d.rounded_rectangle([20, 20, pw - 20, 300], 56, fill=(40, 90, 200, 255)); d.rectangle([20, 240, pw - 20, 300], fill=(40, 90, 200, 255))
    d.text((60, 120), p.get("app", "MEU BANCO"), font=F("black", 44), fill=(255, 255, 255, 255), anchor="lm")
    d.text((60, 200), "Saldo disponível", font=F("med", 32), fill=(220, 230, 255, 255), anchor="lm")
    lock_at = p.get("lock_at", 1.2); kl = prog(t, lock_at, 0.4)
    bal = "•••••" if kl > 0 else p.get("balance", "••• ••••")
    d.text((60, 260), bal, font=F("black", 52), fill=(255, 255, 255, 255), anchor="lm")
    for i, lbl in enumerate(["PIX", "TRANSFERIR", "PAGAR", "SACAR"]):
        y = 360 + i * 130; dis = kl > 0
        d.rounded_rectangle([60, y, pw - 60, y + 100], 24, fill=(225, 225, 230, 255) if dis else (220, 232, 255, 255))
        d.text((100, y + 50), lbl, font=F("bold", 40), fill=(160, 160, 165, 255) if dis else (40, 90, 200, 255), anchor="lm")
        if dis: d.line([(80, y + 50), (pw - 80, y + 50)], fill=(230, 57, 70, 255), width=6)
    yaw = 0.2 * math.sin(t * 1.3)
    shadowed(img, R.warp3d(ph_img, yaw, 0), W / 2, CY + 40 + 900 * (1 - clamp(k)), 0.95)
    if kl > 0:
        lock_icon(dr, W / 2, CY - 40, 1.6 * back(kl), RED, ease(prog(t, lock_at + 0.2, 0.3)))
    ka = back(prog(t, p.get("toast_at", 2.0), 0.35))
    if ka > 0:
        put(img, text_layer(p.get("toast", "CONTA BLOQUEADA"), 78, WHITE, "black", 10, RED), W / 2, CY - 470, ka, 1.0, rot=-4)
    return [(0.0, "whoosh", 0.5), (lock_at, "hit", 0.6), (p.get("toast_at", 2.0), "glitch", 0.4)]


def sc_donut(img, dr, t, D, p):
    """Anel de porcentagem enchendo em 3D com o número no centro (ex.: 82,9% do PIB)."""
    col = tuple(p.get("color", RED)); pct = p["pct"]
    pulse_glow(img, t, col, 1.0, 0.3)
    k = ease_io(prog(t, 0.2, p.get("dur", 1.4))); v = pct * k
    S = 760; ring = Image.new("RGBA", (S, S)); rd = ImageDraw.Draw(ring)
    rd.ellipse([20, 20, S - 20, S - 20], outline=(255, 255, 255, 40), width=90)
    if k > 0: rd.arc([20, 20, S - 20, S - 20], -90, -90 + 360 * v / 100, fill=col + (255,), width=90)
    ang = math.radians(-90 + 360 * v / 100); cx = cy = S / 2; r = S / 2 - 65
    rd.ellipse([cx + math.cos(ang) * r - 30, cy + math.sin(ang) * r - 30, cx + math.cos(ang) * r + 30, cy + math.sin(ang) * r + 30], fill=(255, 255, 255, 255))
    ring = R.warp3d(ring, 0.18 * math.sin(t * 1.2), 0.05)
    s = back(prog(t, 0, 0.45))
    shadowed(img, ring, W / 2, CY - 40, clamp(s, 0, 1.2) * 0.95)
    txt = fmt_br(v, p.get("dec", 1)) + "%"
    lay = fit(R.extruded_text(txt, 170, face=(255, 255, 255), side=(70, 76, 82), depth=18), 520)
    put(img, lay, W / 2, CY - 60, clamp(s, 0, 1.2) * (1 + 0.15 * (1 - ease(prog(t, 0.2 + p.get("dur", 1.4), 0.25)))))
    if p.get("unit"): dr.text((W / 2, CY + 90), p["unit"], font=F("black", 56), fill=rgba(col, ease(prog(t, 0.5, 0.3))), anchor="mm")
    if p.get("kicker"): pill(dr, W / 2, CY - 500, p["kicker"], 48, WHITE, (20, 20, 20), ease(prog(t, 0, 0.3)))
    if p.get("label"): put(img, text_layer(p["label"], 60, WHITE, "black", 7), W / 2, CY + 430, back(prog(t, 0.8, 0.35)))
    d = p.get("dur", 1.4)
    return [(0.0, "whoosh", 0.5)] + [(0.2 + d * i / 6, "tick", 0.45) for i in range(6)] + [(0.2 + d, "hit", 0.6)]

SCENES = {k[3:]: v for k, v in globals().items() if k.startswith("sc_")}
BGS = {"hook": "red", "date": "dark", "candles": "dark", "bignum": "red", "ticker": "dark", "alert": "red",
       "since": "navy", "question": "navy", "switch": "dark", "gauge": "dark", "timer": "navy", "map": "dark", "outro": "red",
       "versus": "dark", "court": "navy", "stamp": "red", "reaction": "dark", "police": "dark", "glitchword": "red", "flagdays": "navy", "phone": "dark", "donut": "navy"}

# ================= LEGENDA (palavra por palavra) =================
KEYS = {"bolsa", "despenca", "queda", "grave", "circuit", "breaker", "b3", "ibovespa", "seguranca", "suspensas",
        "turbulentos", "preocupacao", "futuro", "minutos", "negociacoes",
        "golpe", "estado", "polonia", "tribunal", "constitucional", "suspenso", "policiais", "critico", "independencia"}

def caption_chunks(words, maxw=930, size=92):
    f = F("black", size); chunks = []; cur = []
    for i, w in enumerate(words):
        txt = w[2].strip().upper()
        if not txt: continue
        if cur and txt[0] in ",.%?!-":
            cur[-1][2] += txt; cur[-1][1] = w[1]; continue
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
    space = tw(f, " ") + 22
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
            pk = 1 + 0.12 * (1 - ease(prog(g, s, 0.12)))
            lay = text_layer(txt, size, col, "black", 9)
            put(img, lay, x + wd / 2, CAP_Y, pk * clamp(k_in, 0.5, 1.2))
        x += wd + space

# ================= QUADRO =================
def frame(scene, t, D, g, chunks, total, rng):
    kind = scene["type"]
    base = background(scene.get("bg") or BGS.get(kind, "dark"), g)
    img = base.copy()
    dr = ImageDraw.Draw(img, "RGBA")
    sfx = SCENES[kind](img, dr, t, D, scene)
    img = Image.alpha_composite(base, img)  # textos com alfa ~0 não deixam "buracos" no quadro
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
    glitch = any(name == "glitch" and 0 <= t - at < 0.2 for at, name, _ in sfx) or t < 0.07 or (scene.get("glitchy") and math.sin(t * 11) > 0.85)
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
