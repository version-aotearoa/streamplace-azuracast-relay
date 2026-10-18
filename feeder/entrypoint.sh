#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-only
# Streamplace feeder: pulls the AzuraCast Icecast mount, muxes it with the
# current track artwork and burned-in caption band, pushes RTMPS to Streamplace.
# Waits for the station to actually produce audio before starting, so we never
# publish silence.
set -eu

: "${STREAM_KEY:?STREAM_KEY not set}"
SRC="${SRC:-http://127.0.0.1:8000/radio.mp3}"
RTMP="${RTMP:-rtmps://rtmp.stream.place:1935/live/$STREAM_KEY}"
BOLD=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf
REG=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf

mkdir -p /tmp/feeder

until /usr/bin/ffprobe -v error -select_streams a -show_entries stream=codec_type \
      -of csv=p=0 "$SRC" 2>/dev/null | grep -q audio; do
  echo "$(date -u +%FT%TZ) station mount not ready ($SRC) - retrying in 10s"
  sleep 10
done

echo "$(date -u +%FT%TZ) station mount ready - starting push"
/usr/bin/python3 /opt/streamplace-feeder/artfeeder.py | \
exec /usr/bin/ffmpeg -hide_banner -loglevel warning -stats \
  -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 -re -i "$SRC" \
  -f image2pipe -framerate 5 -vcodec mjpeg -i - \
  -map 0:a -map 1:v \
  -c:a aac -b:a 128k -ar 44100 -ac 2 \
  -vf "drawbox=x=0:y=548:w=1280:h=172:color=0x000000@0.72:t=fill,\
drawbox=x=0:y=548:w=1280:h=2:color=0xE0453A:t=fill,\
drawtext=fontfile=$BOLD:textfile=/tmp/feeder/line1.txt:reload=1:fontsize=40:fontcolor=0xF4F4F6:shadowcolor=0x000000@0.6:shadowx=2:shadowy=2:x=60:y=584,\
drawtext=fontfile=$REG:textfile=/tmp/feeder/line2.txt:reload=1:fontsize=26:fontcolor=0xC2C2CE:shadowcolor=0x000000@0.6:shadowx=1:shadowy=1:x=60:y=646,\
drawtext=fontfile=$BOLD:text='VERSION RADIO':fontsize=21:fontcolor=0x8C8C98:x=w-text_w-60:y=590" \
  -c:v libx264 -preset ultrafast -tune stillimage -threads 1 \
  -r 5 -g 5 -bf 0 -pix_fmt yuv420p -b:v 400k -maxrate 400k -bufsize 800k \
  -force_key_frames "expr:gte(t,n_forced*1)" \
  -f flv "$RTMP"
