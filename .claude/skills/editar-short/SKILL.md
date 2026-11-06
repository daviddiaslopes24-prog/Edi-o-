---
name: editar-short
description: Faz um SHORT vertical (YouTube Shorts / Reels / TikTok, 1080x1920, até 60 s) a partir de um áudio ou vídeo do canal Impacto Econômico. Escolhe a melhor parte, corta pausas e regravações, acelera, e monta um vídeo MUITO dinâmico com uma animação diferente a cada 2–5 s (texto 3D, números contando, gráficos, mapas, ícones), legenda grande palavra por palavra, flashes, glitch, tremores, trilha e efeitos. Use sempre que o usuário pedir um "short", "vídeo curto", "vídeo vertical/em pé" ou "reels".
---

# Editar SHORT (áudio/vídeo → MP4 vertical de até 1 min)

Pedido fixo do usuário: **"quanto mais dinâmico, melhor"**. Nunca deixar a tela parada: uma cena
diferente a cada 2–5 s, nada de cena com mais de ~6 s. Modelos prontos: `videos/05-short-circuit-breaker/` (economia) e `videos/06-short-golpe-polonia/` (política).

## Passos
1. **Preparar** (em segundo plano, ~5 min na 1ª vez): `bash tools/setup.sh $A` (A = pasta no scratchpad).
   Depois: `python3 tools/sound.py $A/sfx 70`.
2. **Transcrever o original**. Se for um vídeo já feito, a transcrição pode estar em
   `videos/NN-tema/transcricao_original.json` (confira se a duração bate). Se o usuário mandar vídeo,
   extraia o áudio: `ffmpeg -i VIDEO -vn -ac 1 -ar 16000 $A/a16.wav`. Senão:
   `ffmpeg -i AUDIO -ac 1 -ar 16000 $A/a16.wav && python3 tools/transcrever.py $A/a16.wav $A/tx.json`.
3. **Escolher a melhor parte** (40–60 s de fala depois de acelerar):
   - Prefira o trecho mais dramático e com números fortes (queda, recorde, "pela primeira vez", "pior desde").
   - **Gancho nos primeiros 2–3 s**: pode colar a frase-título do vídeo (ex.: "Bolsa de Valores despenca
     no Brasil") antes do trecho.
   - Termine numa frase que feche a ideia.
   - Escreva `videos/NN-short-tema/cortes.json` = tudo que sai: `[[0, ini_gancho], [fim_gancho, ini_trecho], ..., [fim_trecho, duração]]`
     e também as regravações dentro do trecho.
   - **Pode reordenar trechos** (ex.: gancho → fatos → "Imagine..." → pergunta final): cole os trechos na ordem
     com `ffmpeg -filter_complex "[0]atrim=A:B,asetpts=N/SR/TB[a];...concat=n=N:v=0:a=1"`, transcreva o arquivo colado
     e rode o `edit_audio.py` nele com `cortes.json` = `[]`. Guarde a ordem em `trechos.json` (modelo: `videos/08-short-crise-paraguai/`).
4. **Caçar regravações**: o whisper às vezes não transcreve uma tentativa abandonada. Se houver um
   buraco grande entre palavras (> 1 s) ou uma palavra "longa demais", meça a energia do trecho com ffmpeg
   e retranscreva só aquele pedaço (`-ss X -t 8`) para ver o que foi dito. Mantenha sempre a ÚLTIMA tentativa.
   Não corte "mais mais" e parecidos sem conferir a energia: a palavra pode ser uma só.
5. **Editar e acelerar**:
   `python3 tools/edit_audio.py AUDIO tx.json cortes.json $A/ed`
   `ffmpeg -i $A/ed/voz.wav -af atempo=1.15 -ar 48000 $A/voz_fast.wav` (1.1–1.25; meta: voz ≤ 57 s)
6. **Retranscrever** `voz_fast.wav` → `$A/tx2.json`. Corrija erros do whisper direto no JSON
   (ex.: "Ibovesco" → "Ibovespa", palavra duplicada na troca de segmento), porque a legenda usa esse texto.
   Salve uma cópia em `videos/NN-short-tema/transcricao_short.json`.
7. **Plano** `videos/NN-short-tema/plano.json`: lista de cenas com `anchor` (palavras da frase, sem acento)
   ou `at` (segundos; `"at": "end"` = logo após a fala, para o outro). Cena 0 = `hook` com `"at": 0`,
   e a última é o `outro`. Não repita o mesmo tipo em seguida; alterne os fundos (`"bg": dark|red|navy|paper`).
8. **Testar**: monte um contact sheet chamando `short.frame(...)` (ou renderize com `ONLY=0,3,7`) e olhe
   os quadros antes do render final.
9. **Render** (~3 min para 55 s, 4 núcleos):
   `ASSETS=$A python3 tools/short.py plano.json $A/tx2.json $A/voz_fast.wav $A $A/out/short.mp4`
   **Recomprima sempre** (o grão deixa o arquivo com ~200 MB):
   `ffmpeg -i short.mp4 -c:v libx264 -preset medium -crf 25 -c:a copy -movflags +faststart short_final.mp4` (~40 MB)
10. Confira o contact sheet do MP4 final, entregue com `SendUserFile` e faça commit de `plano.json`, `cortes.json`
    e da transcrição (o MP4 não vai para o git).

## Cenas do `tools/short.py` (todas animadas, com 3D, tremor ou glitch)
| tipo | uso | parâmetros |
|---|---|---|
| `hook` | abertura: palavras 3D batendo + gráfico despencando | `lines` (`*destaque*`), `times`, `sub`, `nocap: true` |
| `date` | calendário caindo e circulando o dia | `weekday`, `day`, `month`, `kicker` |
| `candles` | gráfico de velas despencando, ou subindo com `up: true` (ilustrativo, já mostra o aviso) | `title`, `label`, `up` |
| `bignum` | número gigante 3D contando + batida | `from`, `to`, `dec`, `prefix`, `suffix`, `dur`, `arrow` up/down, `color`, `kicker`, `label` |
| `donut` | anel de porcentagem enchendo em 3D com o número no centro (ex.: 82,9% do PIB) | `pct`, `dec`, `unit`, `color`, `dur`, `kicker`, `label` |
| `ticker` | painel de LED com cotação + fita rolando | `name`, `sub`, `to`, `tape` |
| `alert` | faixas de perigo, luz girando, texto 3D amarelo | `l1`, `l2`, `sub` |
| `since` | ano voltando no tempo até um marco | `kicker`, `from`, `to`, `month` |
| `question` | interrogação 3D gigante | `label` |
| `switch` | disjuntor ON → OFF com faíscas | `kicker`, `label`, `flip` (s) |
| `gauge` | termômetro descendo até um limite + "PARA TUDO!" | `limit`, `kicker` |
| `timer` | cronômetro circular + cadeado | `minutes`, `label` |
| `map` | mapa de qualquer país pulsando, com alfinete, mísseis e navios | `iso` (ISO3, padrão BRA), `view` [lon0,lon1,lat0,lat1], `size`, `pin` [lon,lat], `pin_label`, `label`, `labels` [[lon,lat,texto]], `strikes` [[origem,alvo,t0]] (míssil em arco + explosão), `ships` [[[lon,lat],...]] (navios andando na rota) |
| `versus` | duelo: dois cartões com silhueta (ou prédio com `icon: "bank"`) + VS 3D e raio | `left`/`right` {`name`,`role`,`color`,`icon`}, `right_at`, `vs_at`, `kicker` |
| `court` | prédio de tribunal/banco/instituição subindo; `crack` racha e treme; `stamp` carimba (ex.: INTERDITADO) | `label`, `kicker`, `crack`, `stamp`, `at_stamp` |
| `phone` | celular com app do banco: saldo some, cadeado e alerta | `app`, `lock_at`, `toast`, `toast_at` |
| `stamp` | cartão de autoridade + carimbo batendo | `name`, `role`, `stamp` (padrão SUSPENSO), `at_stamp`, `kicker` |
| `reaction` | 3 reações em sequência (ícones `politico`, `autoridade`, `manifestante` ou `glyph:⚔`) | `items` [[ícone, rótulo]], `times`, `gap`, `scale` |
| `police` | sirene azul/vermelha, distintivo e fita de isolamento | `label`, `badge`, `tape` |
| `flagdays` | bandeira tremulando (GBR, DEU, JPN) + contagem de dias 3D | `iso`, `country`, `days`, `unit`, `at_days`, `label` |
| `glitchword` | palavras 3D gigantes com glitch (termos fortes, abertura) | `lines` (`*destaque*`), `sub`, `glitchy: true` |
| `outro` | marca 3D + botão "Inscreva-se" clicado | `label`, `nocap: true` |

Quando o assunto pedir algo novo (ex.: dólar, inflação, juros, empresas), **crie uma cena nova** no
`short.py` seguindo o mesmo padrão (função `sc_nome(img, dr, t, D, p)` que desenha e devolve a lista de efeitos
`[(tempo, "som", ganho)]`, mais a entrada em `BGS`). Cada short deve ficar um pouco melhor que o anterior.

## Regras fixas do estilo
- **Vertical 1080x1920, 30 fps, até 60 s.** A animação fica no centro (`CY = 800`) e a legenda em `CAP_Y = 1470`,
  fora da área que a interface do YouTube cobre embaixo e à direita.
- **Legenda palavra por palavra** em Poppins Black com contorno preto, até 3 palavras por vez. A palavra falada fica
  em amarelo, e números e palavras-chave (`KEYS` no `short.py`) em vermelho. Desligue com `nocap` quando a cena já
  escreve a frase em letras grandes.
- **Toda troca de cena** tem flash branco, punch-in de zoom e glitch RGB rápido, com whoosh. Batidas (`hit`/`boom`)
  tremem a câmera. Barra de progresso vermelha no topo e "IMPACTO ECONÔMICO" no alto.
- **Áudio** segue as mesmas regras da skill `editar-video`: a voz é sempre o mais alto, os efeitos e a música ficam
  baixos, nada de sirene, e a voz passa pelo DeepFilterNet.
- **Pessoas reais** aparecem só como silhueta genérica com nome e cargo, nunca como rosto desenhado ou inventado.
  Corrija a grafia dos nomes na transcrição (ex.: "Carl Nile World" → "Karol Nawrocki"), usando o `plano.json` do vídeo longo como referência.
- **Final com pergunta**: se o trecho terminar numa pergunta, use `question` com um rótulo que chame comentários ("É GOLPE? COMENTA AÍ").
- Toda cena aceita `"glitchy": true` (glitch intermitente durante a cena toda).
- **Dados**: só números do roteiro/áudio. Gráficos sem número real levam "Movimento ilustrativo".
- Se houver `PEXELS_KEY`/`PIXABAY_KEY`, dá para usar filmagens reais (veja `tools/stock.py`). Por enquanto o
  short é 100% animação.
