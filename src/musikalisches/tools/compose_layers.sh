#!/usr/bin/env bash
# ffmpeg 参数脚本：合成 staff + spectra + dice 三层透明视频并注入 L3 进度
# 用法：./compose_layers.sh staff.mp4 spectra.mp4 dice.mp4 output.mp4
set -euo pipefail

STAFF="${1:?需要 --staff 参数}"
SPECTRA="${2:?需要 --spectra 参数}"
DICE="${3:?需要 --dice 参数}"
OUTPUT="${4:?需要 --output 参数}"

ffmpeg -y -i "$STAFF" -i "$SPECTRA" -i "$DICE" \
  -filter_complex "[0:v][1:v]overlay=0:0[s1];[s1][2:v]overlay=0:0[s2]" \
  -vf "drawtext=text='123/45949729863572161':x=20:y=30:fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf:fontcolor=white:fontsize=16" \
  -c:v libx264 -preset ultrafast -pix_fmt yuv420p "$OUTPUT"
