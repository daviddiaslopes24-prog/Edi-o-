"""Divide automaticamente cenas longas (> MAX s) inserindo b-rolls no meio da fala.
Uso: python3 tools/dividir_cenas.py plano.json transcricao_editada.json duracao_s assets_dir arquivo1 arquivo2 ...
(arquivos = mídias revisadas, relativas a assets_dir, ex.: stock/pb123.mp4)"""
import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("ASSETS", ".")
import render as r

MAX = float(os.environ.get("MAX_CENA", "9"))
plan_p, tx_p, total, assets = sys.argv[1], sys.argv[2], float(sys.argv[3]), sys.argv[4]
pool = [f for f in sys.argv[5:] if os.path.exists(os.path.join(assets, f))]
plan = json.load(open(plan_p)); words = [w for s in json.load(open(tx_p)) for w in s["w"]]
toks = [(tk, w[0]) for w in words for tk in r.norm(w[2])]
k = 0
for _ in range(3):
    st = r.resolve(plan, words, total); ends = st[1:] + [total]; new = []; added = 0
    for i, sc in enumerate(plan):
        new.append(sc); D = ends[i] - st[i]
        # nunca interromper infográficos (cadeias, grades, listas, gráficos, mapas): eles revelam itens ao longo da cena
        INFO = ("outro", "chain", "grid", "list", "chips", "bars", "line", "timeline", "datecard", "map", "globe", "versus")
        if D > (MAX if sc["type"] not in INFO else 15) and sc["type"] != "outro" and pool:
            n = int(D // 7.5)
            for j in range(1, n + 1):
                tm = st[i] + D * j / (n + 1)
                q = next((q for q, (_, t0) in enumerate(toks) if t0 >= tm), None)
                if q is None or q + 3 >= len(toks): continue
                new.append({"type": "broll", "anchor": " ".join(t for t, _ in toks[q:q + 4]),
                            "media": {"file": pool[k % len(pool)]}, "_filler": True}); k += 1; added += 1
    plan = new
    if not added: break
st = r.resolve(plan, words, total); d = [b - a for a, b in zip(st, st[1:] + [total])]
json.dump(plan, open(plan_p, "w"), ensure_ascii=False, indent=0)
print(f"{len(plan)} cenas, média {sum(d)/len(d):.1f} s, maior {max(d):.1f} s")
