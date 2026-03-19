#!/bin/bash
###
# @Description:base FFmpeg mix 2 audio MP3
# @Author: Chaos42DAMA
# @E-mail: zoomquiet+chaos42dama@gmail.com
# @Github: ZoomQuiet
#   overlap
#   acrossfade
###

# 检查参数个数
if [ $# -ne 4 ]; then
  echo "Usage: $0 1.mp3 2.mp3 mixed.mp3 420"
  exit 1
fi

## 检查参数是否以rtmp开头 
#if [[ $1 != rtmp* ]]; then
#  echo "Error: Streaming url must start with rtmp"
#  exit 1
#fi

# 参数检查ok,执行程序  
echo "1st au: $1"
echo "2nd au: $2"
echo "mix to: $3"
echo "mix ms= $4"

#echo 'ffmpeg -i $1 -i $2 -filter_complex "[0:a]adelay=$4|$4[del];[1:a][del]amix" -map 0:a -map 1:a -c:a libmp3lame -y $3'

#ffmpeg -hide_banner -i $1 -i $2 -filter_complex "[0:a]adelay=$4|$4[del];[1:a][del]amix" -map 0:a -map 1:a -c:a libmp3lame -y $3

#ffmpeg -hide_banner -i $1 -i $2 -filter_complex "[1]adelay=$4|$4[a1];[0:a][a1]amix=inputs=2[a]" -y $3

ffmpeg -hide_banner -i $1 -i $2 -filter_complex "[0:a]adelay=$4|$4[a1];[0:a][a1]amix" -map 0:a -map 1:a -c:a libmp3lame -y $3


ffprobe -hide_banner -show_entries format=duration:stream=codec_name,start_time -of default=nw=1 $1
echo 
echo "+MIXED+"
echo 
ffprobe -hide_banner -show_entries format=duration:stream=codec_name,start_time -of default=nw=1 $2
echo 
echo "GOT:."
echo 
ffprobe -hide_banner -show_entries format=duration:stream=codec_name,start_time -of default=nw=1 $3


