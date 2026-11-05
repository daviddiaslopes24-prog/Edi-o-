"""Corta pausas, respirações e trechos repetidos de uma narração.
Uso: python edit_audio.py audio_original transcricao.json cortes.json saida_dir
cortes.json: lista de [inicio, fim] (segundos no áudio original) a remover (repetições).
Gera: voz.wav (48k estéreo tratado) e mapa.json (lista de trechos mantidos [ini, fim, novo_ini])."""
import json, sys, subprocess, numpy as np, os

src, txp, cutp, out = sys.argv[1:5]
os.makedirs(out, exist_ok=True)
SR = 48000
raw = subprocess.run(["ffmpeg", "-v", "error", "-i", src, "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                     capture_output=True, check=True).stdout
x = np.frombuffer(raw, np.float32).copy()
dur = len(x) / SR

# energia em janelas de 20 ms (com passa-alta simples para ignorar ronco)
hp = x - np.convolve(x, np.ones(48) / 48, mode="same")
fr = int(0.02 * SR); n = len(hp) // fr
rms = 20 * np.log10(np.sqrt((hp[: n * fr].reshape(n, fr) ** 2).mean(1)) + 1e-9)
speech_db = np.percentile(rms[rms > -60], 75)
thr = speech_db - 17  # respirações e ruído ficam abaixo disso
voiced = rms > thr
# suaviza: preenche buracos < 120 ms dentro da fala
k = 6
idx = np.where(voiced)[0]
for a, b in zip(idx[:-1], idx[1:]):
    if 1 < b - a <= k: voiced[a:b] = True

words = [w for s in json.load(open(txp)) for w in s["w"]]
cuts = [tuple(c) for c in json.load(open(cutp))]

# remove: (1) repetições; (2) silêncios/respirações longos -> mantém 0.18 s
remove = list(cuts)
PAUSE_KEEP = 0.18
i = 0
while i < n:
    if not voiced[i]:
        j = i
        while j < n and not voiced[j]: j += 1
        a, b = i * fr / SR, j * fr / SR
        if b - a > 0.32:
            remove.append((a + PAUSE_KEEP * 0.5, b - PAUSE_KEEP * 0.5))
        i = j
    else:
        i += 1
# lacunas entre palavras com respiração audível
for w1, w2 in zip(words[:-1], words[1:]):
    a, b = w1[1] + 0.14, w2[0] - 0.06
    if b - a > 0.45:
        remove.append((a, b))
# início/fim
if words:
    remove.append((0, max(0, words[0][0] - 0.25)))
    remove.append((min(dur, words[-1][1] + 0.6), dur))

remove.sort(); merged = []
for a, b in remove:
    if b <= a: continue
    if merged and a <= merged[-1][1] + 0.05: merged[-1][1] = max(merged[-1][1], b)
    else: merged.append([a, b])
keep = []; t = 0.0
for a, b in merged:
    if a - t > 0.04: keep.append([t, a])
    t = max(t, b)
if dur - t > 0.04: keep.append([t, dur])

# ---- limpeza da voz: tira eco/reverberação de ambiente aberto e ruído ----
def dereverb(path):
    """Usa DeepFilterNet (IA que remove ruído e reverberação) se instalado; senão segue só com filtros."""
    try:
        import torch, types
        # compatibilidade: versões novas do torchaudio não têm mais torchaudio.backend.common
        if "torchaudio.backend.common" not in sys.modules:
            b = types.ModuleType("torchaudio.backend"); c = types.ModuleType("torchaudio.backend.common")
            c.AudioMetaData = object; b.common = c
            sys.modules["torchaudio.backend"] = b; sys.modules["torchaudio.backend.common"] = c
        from df.enhance import enhance, init_df
        mdir = os.environ.get("DFN_MODEL", os.path.expanduser("~/.cache/DeepFilterNet/DeepFilterNet3"))
        model, st, _ = init_df(model_base_dir=mdir, log_level="ERROR")
        sr = st.sr()
        r = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"], capture_output=True, check=True).stdout
        a = torch.from_numpy(np.frombuffer(r, np.float32).copy())[None]
        e = enhance(model, st, a).squeeze(0).numpy().astype(np.float32)
        clean = os.path.join(out, "voz_limpa.wav")
        p = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(sr), "-ac", "1", "-i", "-", clean], stdin=subprocess.PIPE)
        p.communicate(e.tobytes()); print("eco/ruído removidos com DeepFilterNet")
        return clean
    except BaseException as ex:
        print("DeepFilterNet indisponível, usando só filtros:", ex)
        return path

# Pedido do usuário (vídeo 05): NÃO tentar tirar o eco por padrão — só cortar pausas e erros.
# Para ligar a limpeza de eco/ruído com IA: LIMPAR_ECO=1
LIMPAR_ECO = os.environ.get("LIMPAR_ECO") == "1"
clean_src = dereverb(src) if LIMPAR_ECO else src
# filtros: corta graves de vento, reduz ruído, "expansor" que encurta a cauda do eco entre palavras,
# tira o som abafado de sala (250-400 Hz), dá presença (3 kHz), compressor para voz firme e na frente
VOICE_CHAIN = (("highpass=f=85,afftdn=nf=-28,agate=threshold=0.02:ratio=2.5:range=0.2:attack=3:release=120:knee=4,")
               if LIMPAR_ECO else "highpass=f=70,") + (
               "equalizer=f=300:t=q:w=1.2:g=-3,equalizer=f=3200:t=q:w=1:g=2.5,equalizer=f=8000:t=q:w=1:g=1,"
               "deesser=i=0.4,acompressor=threshold=-22dB:ratio=3.5:attack=5:release=100:makeup=4")

# monta com crossfade curto (10 ms) para evitar estalos
X = np.frombuffer(subprocess.run(["ffmpeg", "-v", "error", "-i", clean_src, "-ac", "1", "-ar", str(SR),
     "-af", VOICE_CHAIN, "-f", "f32le", "-"],
     capture_output=True, check=True).stdout, np.float32)
fade = int(0.012 * SR); parts = []; mapa = []; pos = 0.0
for a, b in keep:
    seg = X[int(a * SR): int(b * SR)].copy()
    if len(seg) > 2 * fade:
        seg[:fade] *= np.linspace(0, 1, fade); seg[-fade:] *= np.linspace(1, 0, fade)
    parts.append(seg); mapa.append([a, b, pos]); pos += len(seg) / SR
y = np.concatenate(parts)
p = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", "-",
                      "-af", "loudnorm=I=-16:TP=-1.5:LRA=9", "-ar", str(SR), "-ac", "2", f"{out}/voz.wav"], stdin=subprocess.PIPE)
p.communicate(y.astype(np.float32).tobytes())
json.dump(mapa, open(f"{out}/mapa.json", "w"))
print(f"original {dur:.1f}s -> editado {pos:.1f}s ({len(keep)} trechos, limiar {thr:.1f} dB)")
