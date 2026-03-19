#!/bin/bash
###
# @Description:自动循环推流脚本
# @Author: Chaos42DAMA
# @E-mail: zoomquiet+chaos42dama@gmail.com
# @Github: ZoomQuiet
#   DGD: rtmp://a.rtmp.youtube.com/live2/amj3-qauw-v6p3-uvfp-3gd8
#   Chaos42DAMA:
# rtmp://a.rtmp.youtube.com/live2/0rqu-3ypj-fg96-bgw8-25g5
# 0rqu-3ypj-fg96-bgw8-25g5
# rtmp://a.rtmp.youtube.com/live2/0rqu-3ypj-fg96-bgw8-25g5
###

# 检查参数个数
if [ $# -ne 1 ]; then
  echo "Usage: $0 rtmp-url"
  exit 1
fi

# 检查参数是否以rtmp开头 
if [[ $1 != rtmp* ]]; then
  echo "Error: Streaming url must start with rtmp"
  exit 1
fi

# 参数检查ok,执行程序  
echo "Streaming to $1"

while true
do

ffmpeg -hide_banner \
    -stats_period 1 \
    -re -f concat -safe 0 -i /opt/vlog/p2ffconcat.txt \
    -vcodec copy -b:v 5000k -acodec copy -b:a 1800k \
    -g 2 \
    -f flv "$1" 2>/opt/vlog/rtmp4ffmpeg.log 

done

#    -keyint_min 50 -g 50 -sc_threshold 0 \

#ffmpeg -hide_banner \
#    -stats_period 1 \
#    -re -f concat -safe 0 -i /opt/vlog/p2ffconcat.txt \
#    -vcodec copy -b:v 5000k -acodec copy -b:a 1800k \
#    -f flv "$1" 2>/opt/vlog/rtmp4ffmpeg.log 
#    -progress pipe:1 -loglevel error \
#    | tee -a /opt/vlog/ffmpeg4stats.log

#while true
#do
#    ffmpeg -re -f concat -safe 0 -i /opt/vlog/p2ffconcat.txt -vcodec copy -acodec copy -f flv "$1"
#done
