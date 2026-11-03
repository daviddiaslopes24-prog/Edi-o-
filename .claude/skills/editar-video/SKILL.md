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

## Estilo (referências do usuário)
Documentário explicativo: mapa escuro verde com regiões em vermelho e etiquetas; papel creme
quadriculado com título serifado e palavra em *itálico* vermelho; documento com trecho grifado;
números grandes animados; câmera sempre em leve movimento; cortes com whoosh; trilha tensa ao fundo.
