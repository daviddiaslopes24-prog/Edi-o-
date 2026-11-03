---
name: editar-video
description: Edita um vídeo completo do canal Impacto Econômico a partir de um áudio de narração e do roteiro. Corta pausas, respirações e repetições, gera cenas animadas (mapas, gráficos, números, listas) no estilo documentário, adiciona trilha e efeitos sonoros e entrega o MP4 final em 1080p. Use quando o usuário mandar um áudio (m4a/mp3/wav) e um roteiro pedindo um vídeo.
---

# Editar vídeo (áudio + roteiro → MP4)

Meta: entregar em até ~50 min. Rode etapas pesadas em segundo plano e avise o usuário do progresso.

## Passos
1. **Preparar** (paralelo): `bash tools/setup.sh $A` (A = pasta de trabalho no scratchpad) e gere sons:
   `python3 tools/sound.py $A/sfx <duracao_estimada_em_s>` (rode de novo com a duração final antes do render).
2. **Transcrever** o áudio original (≈1,5 min para 12 min de áudio):
   `ffmpeg -i AUDIO -ac 1 -ar 16000 $A/a16.wav && python3 tools/transcrever.py $A/a16.wav $A/tx.json`
3. **Achar repetições**: leia a transcrição e compare com o roteiro. Repetições = frases recomeçadas,
   palavras duplicadas ("mais mais"), tentativas abandonadas. Imprima os tempos das palavras ao redor
   e escreva `cortes.json` com `[inicio, fim]` de cada trecho a remover (sempre remova a tentativa
   ANTERIOR e mantenha a última, que costuma ser a completa).
4. **Editar o áudio**: `python3 tools/edit_audio.py AUDIO $A/tx.json cortes.json $A/ed`
   → remove também pausas > 0,32 s e respirações; gera `$A/ed/voz.wav`.
5. **Retranscrever** o áudio editado (`voz.wav` → `tx2.json`) para conferir que as repetições sumiram
   e para sincronizar as cenas.
6. **Plano de cenas** `videos/NN-tema/plano.json`: uma cena a cada 5–10 s. Cada cena tem `anchor`
   (primeiras palavras da frase na transcrição editada, sem acento) — a cena começa quando essa frase é dita.
   Tipos: `title, chapter, kinetic, question, bignum, datecard, timeline, line, bars, list, chips, chain,
   doc, map, timer, stamp, versus, grid, outro`. Veja `videos/01-bolsa-despenca/plano.json` como modelo.
   Use `fonte` para mostrar a fonte no canto. Dados que não estão no roteiro devem levar `note: "Gráfico ilustrativo"`.
7. **Testar** 3–4 cenas: `ONLY=0,12,21 python3 tools/render.py plano.json tx2.json voz.wav $A out.mp4`,
   extrair quadros com ffmpeg e olhar.
8. **Render final** (≈10–12 min para 10 min de vídeo, 4 núcleos):
   `python3 tools/render.py plano.json $A/tx2.json $A/ed/voz.wav $A $A/out/video.mp4`
9. Entregar com `SendUserFile`. Não commitar o MP4 (grande); commitar `plano.json` e `cortes.json`.

## FOTOS E VÍDEOS DE BANCO (Pexels + Pixabay) — usar SEMPRE, bastante
O usuário quer o vídeo **muito dinâmico**: misture animações com fotos e vídeos reais.
- Chaves lidas do ambiente: `PIXABAY_KEY` e `PEXELS_KEY` (nunca escrever chaves no repositório).
  Se faltar alguma, use só a que existir; se faltarem as duas, avise o usuário e siga só com animações.
- `tools/stock.py` busca e baixa (só filmagem real, sem animações), sem repetir o mesmo arquivo no vídeo.
- No plano, qualquer cena aceita `"media": {"q": "busca em inglês", "kind": "video"|"photo"}`:
  vira o fundo da cena (escurecido para o texto aparecer; `dim` ajusta, 0 = sem escurecer).
- Cena `broll`: foto/vídeo em tela cheia, com tarja de TV opcional (`caption`, `sub`). Fotos ganham zoom lento.
- **Proporção alvo: ~40–50% das cenas com mídia real** (broll ou fundo), alternando com mapas/gráficos.
  Ex.: frase sobre pessoas/empresas/cidade/dinheiro → broll; número importante → bignum com vídeo ao fundo.
- **Revise a mídia visualmente antes do render** (contact sheet com ffmpeg `tile`): busca automática traz
  coisas erradas (ex.: parlamento da Hungria para "Polônia", constituição alemã, animações). Fixe os bons
  arquivos no plano com `"media": {"file": "stock/pbXXXX.mp4"}`. Nunca use rosto de político real que não
  seja o citado na frase.
- Buscas em inglês e concretas ("brazilian real banknotes", "stock exchange traders", "sao paulo skyline").
- **Crédito da fonte**: aparece sozinho, pequeno e discreto no canto inferior direito, como na TV
  ("Pixabay" ou "Pexels / Nome do autor"). Não fazer créditos chamativos.

## REGRAS FIXAS DE ÁUDIO (pedido do usuário — sempre seguir)
- **A voz é sempre o elemento mais alto.** Efeitos sonoros e música SEMPRE abaixo da voz: dá para ouvir,
  mas nunca competem com a fala. Valores no `render.py`: `SFX_LEVEL = 0.16`, `SFX_CEIL = 0.16`
  (limitador do barramento de efeitos), música 0.085 com voz / 0.17 nas pausas. Não aumentar.
- **Nada de sirene ou alarme alto.** O som `alarm` agora é um pulso grave e discreto. Não criar sons estridentes.
- **Tirar eco/reverberação** (o usuário grava no celular, às vezes em ambiente aberto):
  `edit_audio.py` passa a voz pelo DeepFilterNet (remove ruído e reverberação) e depois por filtros
  (expansor contra a cauda do eco, corte de 300 Hz abafado, presença em 3 kHz, de-esser, compressor).
  Se o DeepFilterNet não estiver instalado: `pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu && pip install deepfilternet` (o edit_audio.py já contorna a incompatibilidade com torchaudio novo).
- Ao revisar: confira que a voz soa limpa, sem eco e sem cortes de palavras.

## Estilo (referências do usuário)
Documentário explicativo: mapa escuro verde com regiões em vermelho e etiquetas; papel creme
quadriculado com título serifado e palavra em *itálico* vermelho; documento com trecho grifado;
números grandes animados; câmera sempre em leve movimento; cortes com whoosh; trilha tensa ao fundo.

**Segunda leva de referências (MISTURAR com o estilo acima, sem remover nada):** documentário
cinematográfico e jornalismo investigativo.
- `cine`: abertura de série — faixas vermelhas diagonais, letras grandes condensadas e gastas, poeira,
  barras de cinema, brilho passando. Use na abertura (cena 0) e em viradas fortes.
- `headline`: manchete de jornal investigativo — fundo de jornal envelhecido, recorte de papel rasgado,
  título datilografado, sublinhado vermelho, data. Alterne com `chapter` nas aberturas de parte.
- `"tilt": true` (vale para QUALQUER cena): câmera em ângulo — a cena vira um cartão inclinado em 3D
  com fundo desfocado e poeira; `tilt_side` 1 ou -1 alterna o lado; `year` põe etiqueta de ano.
  Use em ~1 de cada 4 cenas (números, documentos, gráficos).
- `burst`: ilustração editorial — raios azul-marinho/laranja girando e cartão de papel rasgado com
  número (`from/to/suffix/label`) ou texto (`big/label`). Use 1–3 vezes por vídeo em destaques.
- `"letterbox": true`: barras pretas de cinema em qualquer cena.
Regra de mistura: não repetir o mesmo tipo de cena mais de 2 vezes seguidas; variar fundos
(escuro / papel creme / jornal / mapa) ao longo do vídeo.
