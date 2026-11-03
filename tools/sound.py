"""Gera efeitos sonoros e trilha de fundo sintetizados (sem direitos autorais)."""
import numpy as np, wave, sys, os
SR = 48000
rng = np.random.default_rng(7)

def save(path, x):
    x = np.asarray(x, dtype=np.float64)
    if x.ndim == 1: x = np.stack([x, x], 1)
    peak = np.max(np.abs(x)) or 1
    x = x / peak * 0.89
    with wave.open(path, "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((x * 32767).astype(np.int16).tobytes())

def t(d): return np.arange(int(SR * d)) / SR

def lp(x, a):  # one-pole lowpass, a in (0,1) or array
    y = np.empty_like(x); s = 0.0
    a = np.broadcast_to(a, x.shape)
    for i in range(len(x)):
        s += a[i] * (x[i] - s); y[i] = s
    return y

def fast_lp(x, cutoff):
    # FFT brickwall-ish lowpass
    X = np.fft.rfft(x); f = np.fft.rfftfreq(len(x), 1 / SR)
    X *= 1 / (1 + (f / cutoff) ** 4)
    return np.fft.irfft(X, len(x))

def bandsweep(n, f0, f1, q=0.25):
    # noise filtered by moving bandpass using STFT
    x = rng.standard_normal(n)
    hop = 512; win = 2048; out = np.zeros(n + win); wsum = np.zeros(n + win)
    w = np.hanning(win); xs = np.pad(x, (0, win))
    frames = range(0, n, hop)
    for k, i in enumerate(frames):
        p = i / max(1, n)
        fc = f0 * (f1 / f0) ** p
        seg = xs[i:i + win] * w
        S = np.fft.rfft(seg); f = np.fft.rfftfreq(win, 1 / SR)
        S *= np.exp(-((np.log2((f + 1) / fc)) ** 2) / (2 * q * q * 4))
        out[i:i + win] += np.fft.irfft(S, win) * w; wsum[i:i + win] += w * w
    return out[:n] / np.maximum(wsum[:n], 1e-3)

def env(n, a, r, curve=2.0):
    e = np.ones(n); na = int(a * SR); nr = int(r * SR)
    if na: e[:na] = np.linspace(0, 1, na)
    if nr: e[-nr:] *= np.linspace(1, 0, nr) ** curve
    return e

def whoosh(d=0.7, up=True):
    n = int(SR * d); f0, f1 = (300, 6000) if up else (6000, 300)
    x = bandsweep(n, f0, f1)
    e = np.sin(np.linspace(0, np.pi, n)) ** 1.5
    l = x * e; r = np.roll(x, 90) * e
    return np.stack([l * np.linspace(1.2, 0.6, n), r * np.linspace(0.6, 1.2, n)], 1)

def boom(d=2.2):
    tt = t(d); f = 38 + 50 * np.exp(-tt * 9)
    ph = 2 * np.pi * np.cumsum(f) / SR
    body = np.sin(ph) * np.exp(-tt * 2.2)
    click = rng.standard_normal(len(tt)) * np.exp(-tt * 60) * 0.6
    rum = fast_lp(rng.standard_normal(len(tt)), 200) * np.exp(-tt * 1.8) * 3
    return np.tanh((body + click + rum) * 1.6)

def hit(d=1.2):  # impacto mais curto e brilhante
    tt = t(d)
    body = np.sin(2 * np.pi * (60 + 120 * np.exp(-tt * 30)) * tt) * np.exp(-tt * 5)
    noise = fast_lp(rng.standard_normal(len(tt)), 3000) * np.exp(-tt * 14) * 2
    return np.tanh((body + noise) * 1.5)

def riser(d=2.0):
    n = int(SR * d); x = bandsweep(n, 200, 8000, 0.35)
    tt = t(d); tone = np.sin(2 * np.pi * np.cumsum(200 + 1400 * (tt / d) ** 2) / SR) * 0.25
    e = (np.linspace(0, 1, n) ** 2.5); e[-int(0.03 * SR):] *= np.linspace(1, 0, int(0.03 * SR))
    return (x + tone) * e

def tick(d=0.05):
    tt = t(d); return np.sin(2 * np.pi * 2400 * tt) * np.exp(-tt * 180) + rng.standard_normal(len(tt)) * np.exp(-tt * 400) * 0.4

def typing(d=1.0, rate=14):
    n = int(SR * d); x = np.zeros(n)
    k = tick(0.03) * 0.6
    pos = 0.0
    while pos < d - 0.04:
        i = int(pos * SR); g = 0.5 + rng.random() * 0.5
        c = k * g; x[i:i + len(c)] += c[: n - i]
        pos += 1 / rate * (0.6 + rng.random() * 0.8)
    return fast_lp(x, 5000)

def ding(d=1.2):
    tt = t(d)
    x = sum(a * np.sin(2 * np.pi * f * tt) * np.exp(-tt * dk) for f, a, dk in [(1318, 1, 4), (2637, .5, 6), (1975, .4, 5), (3951, .2, 9)])
    return x

def pop(d=0.12):
    tt = t(d); f = 900 * np.exp(-tt * 25) + 200
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-tt * 30)

def glitch(d=0.35):
    n = int(SR * d); x = np.zeros(n); i = 0
    while i < n:
        L = int(SR * (0.01 + rng.random() * 0.04)); f = rng.choice([200, 800, 1600, 3200, 60])
        seg = np.sign(np.sin(2 * np.pi * f * np.arange(L) / SR)) * (0.3 + rng.random() * 0.7)
        if rng.random() < .4: seg = rng.standard_normal(L) * 0.6
        x[i:i + L] = seg[: n - i]; i += L + int(SR * rng.random() * 0.01)
    return fast_lp(x, 7000) * env(n, 0.005, 0.05)

def alarm(d=1.6):
    """Antes era uma sirene (alta demais). Agora: pulso grave e discreto de tensão."""
    tt = t(d)
    pulse = np.sin(2 * np.pi * 55 * tt) * (0.5 + 0.5 * np.sin(2 * np.pi * 2 * tt - np.pi / 2))
    return fast_lp(pulse + rng.standard_normal(len(tt)) * 0.03, 400) * env(len(tt), 0.15, 0.6) * 0.6

def paper(d=0.5):
    """Folha de papel / jornal deslizando."""
    x = bandsweep(int(SR * d), 2500, 900, 0.5)
    crack = np.zeros(int(SR * d))
    for _ in range(25):
        i = rng.integers(0, len(crack) - 200); crack[i:i + 120] += rng.standard_normal(120) * np.exp(-np.arange(120) / 25)
    return (x * 0.7 + crack * 0.5) * env(int(SR * d), 0.03, 0.2)

def cash(d=0.9):
    return ding(d) * 0.6 + np.concatenate([np.zeros(int(0.02 * SR)), tick(d - 0.02) * 0])[: int(SR * d)] + \
        fast_lp(rng.standard_normal(int(SR * d)), 6000) * np.exp(-t(d) * 25) * 0.5

def note(m): return 440 * 2 ** ((m - 69) / 12)

def music(seconds, bpm=92, seed=3):
    """Trilha documental tensa: pads em menor + pulso grave + percussão leve."""
    r = np.random.default_rng(seed)
    n = int(SR * seconds); L = np.zeros(n); R = np.zeros(n)
    beat = 60 / bpm; bar = beat * 4
    # progressão (Am - F - C - G) / (Dm - Am - E - Am) alternando por seção
    progA = [[57, 60, 64], [53, 57, 60], [48, 52, 55], [55, 59, 62]]
    progB = [[50, 53, 57], [57, 60, 64], [52, 56, 59], [57, 60, 64]]
    nbars = int(seconds / bar) + 1
    padlen = int(bar * SR)
    tt = np.arange(padlen) / SR
    for b in range(nbars):
        sec = (b // 16) % 2
        ch = (progA if sec == 0 else progB)[b % 4]
        i0 = int(b * bar * SR)
        if i0 >= n: break
        pad = np.zeros(padlen)
        for m in ch:
            for det in (-0.08, 0.08):
                f = note(m + det)
                # saw aproximado com 6 harmônicos
                pad += sum(np.sin(2 * np.pi * f * k * tt + r.random() * 6) / k for k in range(1, 7)) * 0.12
        pad = fast_lp(pad, 900 + 500 * np.sin(b / 3))
        pad *= env(padlen, 0.4, 0.4, 1)
        # baixo pulsado em colcheias
        bass = np.zeros(padlen); f = note(ch[0] - 24)
        for k in range(8):
            j = int(k * beat / 2 * SR); L8 = int(beat / 2 * SR)
            tb = np.arange(L8) / SR
            bass[j:j + L8] += np.tanh(2 * np.sin(2 * np.pi * f * tb)) * np.exp(-tb * 6) * (0.9 if k % 2 == 0 else 0.55)
        bass = fast_lp(bass, 300)
        # percussão: kick nos tempos 1 e 3, hat em colcheias, a partir do compasso 4
        perc = np.zeros(padlen)
        if b >= 4 and (b % 32) < 30:
            for k in range(4):
                j = int(k * beat * SR)
                if k in (0, 2):
                    kk = boom(0.35) * 0.55; perc[j:j + len(kk)] += kk[: padlen - j]
                if k in (1, 3):
                    sn = fast_lp(r.standard_normal(int(0.18 * SR)), 4000) * np.exp(-t(0.18) * 22) * 0.35
                    perc[j:j + len(sn)] += sn[: padlen - j]
            for k in range(8):
                j = int(k * beat / 2 * SR)
                hh = r.standard_normal(int(0.05 * SR)); hh = hh - fast_lp(hh, 7000)
                hh *= np.exp(-t(0.05) * 90) * (0.18 if k % 2 else 0.1)
                perc[j:j + len(hh)] += hh[: padlen - j]
        seg = pad * 0.9 + bass * 0.55 + perc
        e = min(n, i0 + padlen) - i0
        L[i0:i0 + e] += seg[:e]; R[i0:i0 + e] += np.roll(seg, 120)[:e] * 0.97 + pad[:e] * 0.05
    fade = int(3 * SR); L[-fade:] *= np.linspace(1, 0, fade); R[-fade:] *= np.linspace(1, 0, fade)
    L[:fade] *= np.linspace(0, 1, fade); R[:fade] *= np.linspace(0, 1, fade)
    return np.tanh(np.stack([L, R], 1) * 0.8)

if __name__ == "__main__":
    out = sys.argv[1]; dur = float(sys.argv[2]) if len(sys.argv) > 2 else 600
    os.makedirs(out, exist_ok=True)
    for name, fn in [("whoosh", lambda: whoosh(0.7)), ("whoosh_down", lambda: whoosh(0.6, False)), ("boom", boom),
                     ("hit", hit), ("riser", riser), ("tick", tick), ("typing", typing), ("ding", ding),
                     ("pop", pop), ("glitch", glitch), ("alarm", alarm), ("cash", cash), ("paper", paper)]:
        save(f"{out}/{name}.wav", fn())
    save(f"{out}/music.wav", music(dur))
    print("ok")
