# Edição de vídeo automática — Impacto Econômico

Mande o **áudio da narração + roteiro** para o Claude (app/celular, aba Code) e peça `/editar-video`.
O pipeline fica em `tools/` e a skill em `.claude/skills/editar-video/`.

- `tools/transcrever.py` — transcrição com tempos por palavra (faster-whisper)
- `tools/edit_audio.py` — corta pausas, respirações e repetições; trata e normaliza a voz
- `tools/sound.py` — trilha e efeitos sonoros sintetizados (sem direitos autorais)
- `tools/render.py` — gera as cenas animadas (mapas, gráficos, números) sincronizadas com a fala e mixa tudo
- `videos/NN-tema/` — plano de cenas e cortes de cada vídeo
