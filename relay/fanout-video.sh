#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-only
# OBS -> Streamplace. Reads loopback RTMP so H264 stays AVCC and -c copy is lossless.
set -eu
set -a; . /etc/streamplace/feeder.env; . /etc/streamplace/relay.env; set +a
exec /usr/bin/ffmpeg -hide_banner -loglevel warning -stats \
  -i "rtmp://127.0.0.1:1936/${DJ_PATH}" \
  -map 0:v:0 -map 0:a:0 -c copy \
  -f flv "rtmps://rtmp.stream.place:1935/live/${STREAM_KEY}"
