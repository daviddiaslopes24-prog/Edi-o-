# Edição de vídeo automática — Impacto Econômico

Mande o **áudio da narração + roteiro** para o Claude (app/celular, aba Code) e peça `/editar-video`.
O pipeline fica em `tools/` e a skill em `.claude/skills/editar-video/`.

- `tools/transcrever.py` — transcrição com tempos por palavra (faster-whisper)
- `tools/edit_audio.py` — corta pausas, respirações e repetições; trata e normaliza a voz
- `tools/sound.py` — trilha e efeitos sonoros sintetizados (sem direitos autorais)
- `tools/render.py` — gera as cenas animadas (mapas, gráficos, números) sincronizadas com a fala e mixa tudo
- `videos/NN-tema/` — plano de cenas e cortes de cada vídeo

## Shorts (vertical, até 1 min)
Mande o áudio ou o vídeo e peça um short (`/editar-short`). O Claude escolhe a melhor parte, acelera e monta
um vídeo vertical muito dinâmico (animação nova a cada 2–5 s, legenda palavra por palavra) com `tools/short.py`.
Modelo: `videos/05-short-circuit-breaker/`.
