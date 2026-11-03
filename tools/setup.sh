#!/usr/bin/env bash
# Prepara o ambiente: transcritor, fontes, mapas e efeitos sonoros. Uso: bash tools/setup.sh ASSETS_DIR
set -e
A=${1:-/tmp/assets}; mkdir -p "$A/fonts" "$A/geo"
python3 -c "import faster_whisper" 2>/dev/null || pip install -q faster-whisper
cd "$A/fonts"
for f in "playfairdisplay/PlayfairDisplay%5Bwght%5D.ttf" "playfairdisplay/PlayfairDisplay-Italic%5Bwght%5D.ttf" \
         poppins/Poppins-Black.ttf poppins/Poppins-Bold.ttf poppins/Poppins-ExtraBold.ttf poppins/Poppins-Medium.ttf poppins/Poppins-Regular.ttf; do
  [ -f "$(basename "$f")" ] || curl -sSfLO "https://raw.githubusercontent.com/google/fonts/main/ofl/$f"
done
cd "$A/geo"
[ -f countries.geojson ] || curl -sSfL -o countries.geojson https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_admin_0_countries.geojson
[ -f states.geojson ] || curl -sSfL -o states.geojson https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_admin_1_states_provinces.geojson
# IA que remove eco/reverberação e ruído da voz (DeepFilterNet3)
python3 -c "import df" 2>/dev/null || { pip install -q torch torchaudio --index-url https://download.pytorch.org/whl/cpu && pip install -q deepfilternet; }
M=~/.cache/DeepFilterNet/DeepFilterNet3
if [ ! -f "$M/config.ini" ]; then
  mkdir -p ~/.cache/DeepFilterNet && cd ~/.cache/DeepFilterNet
  curl -sSfL -o dfn3.zip https://raw.githubusercontent.com/Rikorose/DeepFilterNet/main/models/DeepFilterNet3.zip && unzip -qo dfn3.zip && rm dfn3.zip
fi
echo "assets prontos em $A"
