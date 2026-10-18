# Streamplace feeder

Pushes the Version Radio AzuraCast stream to Streamplace as a 24/7 video
stream, with the current track's artwork as the video frame. Streamplace
relays to viewers; this box is only the encoder.

## Architecture

    AzuraCast Icecast mount (127.0.0.1:8000/radio.mp3)  ── audio ──┐
                                                                  ├─► ffmpeg ──RTMPS──► rtmp.stream.place:1935
    AzuraCast API (loopback, /api/nowplaying, 15s poll) ─ artwork ─┘      (live/live/<key>)

* `entrypoint.sh` waits until the mount actually returns AAC/MP3 audio, then
  starts the pipeline. If the station is down or has no queue, the feeder waits
  instead of publishing silence.
* `artfeeder.py` polls the now-playing API over loopback HTTPS, letterboxes the
  current cover art to 1280x720, and streams it to ffmpeg as 2 fps MJPEG on
  stdin. Artwork swaps without reconnecting the stream.
* Falls back to `/cover.png` (typographic card) when art is missing.

## Files

| Path | Purpose |
|---|---|
| `/opt/streamplace-feeder/docker-compose.yml` | service definition (host network, restart policy, log rotation) |
| `/opt/streamplace-feeder/entrypoint.sh` | mount gate + ffmpeg invocation |
| `/opt/streamplace-feeder/artfeeder.py` | now-playing poller and artwork renderer |
| `/etc/streamplace/feeder.env` | `STREAM_KEY=...` (mode 600, root only) |
| `/etc/streamplace/cover.png` | fallback frame |
| `/var/azuracast/` | AzuraCast itself - never modified by this service |

## Encoder settings

| Setting | Value | Why |
|---|---|---|
| Audio | AAC-LC 128k, 44.1 kHz stereo | matches the 320k source reasonably, keeps size down |
| Video | h264, 1280x720, 2 fps, CBR 400k, `-g 2`, `-bf 0` | Streamplace requires <=1s keyframes and no B-frames |
| Keyframes | forced to whole seconds | avoids Streamplace `variable_segment_length` warnings |
| Measured | ~540 kbps total, ~8-12% of one core, ~70 MB RAM | |

Traffic: roughly 5.8 GB/day (~175 GB/month) of the VPS's 3 TB allowance.
Streamplace serves the viewers, so listener traffic does not touch this box.

## Captions (burned into the video)

`artfeeder.py` writes two files once a second; ffmpeg re-reads them per frame
(`textfile=...:reload=1`) and draws them in the bottom band.

| File | Content |
|---|---|
| `/tmp/feeder/line1.txt` | `Artist - Title` (truncated to 46 chars with an ellipsis) |
| `/tmp/feeder/line2.txt` | `LIVE \| RE-AIR \| AUTODJ  ·  elapsed / duration` |

* Elapsed time is interpolated locally between 15s API polls, so the clock ticks per second.
* `LIVE` comes from `now_playing.live.is_live`; `RE-AIR` when the item has a real duration (a recorded show playing in the live playlist); `AUTODJ` otherwise.
* Layout lives in the `-vf` chain in `entrypoint.sh`: scrim `drawbox` at y=548 h=172, title at y=584, status line at y=646, station mark right-aligned.
* To change wording or position, edit the filter and `docker compose up -d --force-recreate`.
* Text is drawn by ffmpeg, not encoded into the art, so a caption change costs no reconnect.

## Timing / drift

The artwork producer paces against a monotonic deadline (`next += period`) rather
than `sleep(0.5)`. A fixed sleep accumulated ~0.2%/hour of deficit, which made
the video timeline fall behind the audio clock and dragged the whole stream
behind real time (1 minute after ~8 hours, and growing).

Diagnostics:

* `docker logs streamplace-feeder | grep cadence` prints every 120 frames:
  `frames=N wall=Ns ideal=Ns delta=±Ns`. `delta` must stay roughly constant —
  a growing negative delta means the producer is falling behind again.
* `time=` in ffmpeg's stats should advance at 1.000x wall clock. A *constant*
  offset from process start is normal (startup/PTS origin); a *growing* one is
  the bug above.

Do not add `-use_wallclock_as_timestamps` with `-copyts` here: mixing epoch
timestamps with the live audio input produced non-monotonic DTS and made things
worse.

## OBS relay (remote DJ)

A separate stack at `/opt/streamplace-relay/` lets a DJ publish video with OBS:

```
OBS ──RTMPS──► MediaMTX :1935 ──► relay-video  (-c copy)      ──► Streamplace
                                 └─ relay-audio  (MP3 256k)    ──► AzuraCast harbor :8005
```

| Piece | Detail |
|---|---|
| Ingest | `rtmps://multistream.versionradio.live:1935/live`, key in `/etc/streamplace/relay.env` |
| TLS | cert mirrored from AzuraCast's ACME storage to `/etc/streamplace/tls/`; daily systemd timer `streamplace-cert-sync` |
| Supervisor | `streamplace-relay.service` polls MediaMTX `/v3/paths/get/...` every 2 s |
| Switch | DJ path ready → radio feeder stopped + fan-out started; path gone → reversed |
| Rehearsal | `live/rehearsal` path (key `rehearsal`) publishes without triggering the cutover |
| Video | passthrough (`-c copy`), no transcode, full resolution preserved |
| Audio | separate process; retries every 5 s if the harbor is busy (`403 Mountpoint already taken`) |

**One source per mount.** If a DJ is connected directly to AzuraCast (streamer
account on :8005), the relay's audio leg cannot publish until they disconnect —
video still works. The pusher retries in the background.

Operate:

    systemctl status streamplace-relay
    journalctl -u streamplace-relay -f
    docker logs -f relay-video ; docker logs -f relay-audio
    docker logs -f streamplace-ingest

Rollback: `systemctl disable --now streamplace-relay` then start the radio feeder.

## Operate

    cd /opt/streamplace-feeder
    docker compose ps
    docker logs -f --tail 50 streamplace-feeder
    docker compose restart          # reconnect to Streamplace
    docker compose down             # stop
    docker compose up -d            # start

Health signals in the logs:

* `station mount not ready ... retrying in 10s` - waiting for the station (normal after a reboot)
* `station mount ready - starting push` - pipeline running
* `artwork updated (N bytes)` - new track art picked up
* `frame=  N fps=2.0 ... speed=1x` - steady encode; `speed` should stay near 1.0

## Rotate the Streamplace key

1. Streamplace -> Live Dashboard -> Stream from OBS -> RTMP -> Generate Stream Key.
2. On the box:

       read -rsp "stream key: " K && printf 'STREAM_KEY=%s\n' "$K" > /etc/streamplace/feeder.env && unset K
       chmod 600 /etc/streamplace/feeder.env
       cd /opt/streamplace-feeder && docker compose restart

Verify without printing the key: `awk -F= '{print length($2)}' /etc/streamplace/feeder.env`

## Change the audio source

Default is the station's own Icecast mount (`SRC` in docker-compose.yml), chosen
over the HTTPS `/listen/...` path so the pull never leaves the box and does not
depend on TLS, nginx or the base URL. Another mount can be used by editing `SRC`
and running `docker compose up -d`.

## Change the artwork source or cadence

* Art URL comes from `now_playing.song.art` in `/api/nowplaying`.
* Poll interval: `POLL` in `artfeeder.py` (default 15s).
* Frame rate: `FPS` in `artfeeder.py` and `-framerate 2` in `entrypoint.sh` must stay in sync.
* To go back to a static card, point the ffmpeg input at `/cover.png` instead of the pipe.

## Rollback

    cd /opt/streamplace-feeder && docker compose down
    docker rm -f streamplace-feeder
    rm -rf /opt/streamplace-feeder
    # optional: /etc/streamplace/feeder.env + cover.png

AzuraCast is untouched, so stopping the feeder leaves the radio station exactly as it was.

## Troubleshooting

| Symptom | Check |
|---|---|
| Container restarting | `docker logs streamplace-feeder` - usually `STREAM_KEY not set` or missing mount |
| Stuck on "mount not ready" | Is the station playing? `curl -s http://127.0.0.1:8000/status-json.xsl` |
| Connected but no video in Streamplace | Is art reaching ffmpeg? logs should show `artwork updated`; confirm `/cover.png` is readable |
| Streamplace flags `variable_segment_length` | Keep keyframes on whole seconds (`-force_key_frames`), keep fps >= 2, avoid dropping `-g` |
| High CPU | check `docker stats`; lower fps or resolution in both files |

## Host notes

* SSH: key-only (`PasswordAuthentication no`, `PermitRootLogin prohibit-password`),
  fail2ban jail `sshd` active. Config backup: `/etc/ssh/sshd_config.bak-*`.
* Docker is enabled at boot; the container is `restart: unless-stopped`, so the
  feeder returns automatically after a reboot.

### Why the video leg reads loopback RTMP (127.0.0.1:1936), not RTSP

MediaMTX also exposes RTSP on 8554, and it is tempting to read that: no TLS.
Do not. RTSP carries H.264 as Annex-B; FLV/RTMP requires AVCC with extradata.
`-c copy` across that boundary produces a stream that looks like h264 but
never decodes - Streamplace then plays audio with a black picture. Reading
loopback RTMP keeps H.264 in AVCC and makes `-c copy` genuinely lossless.

### Watchdog

While a DJ is publishing, the supervisor restarts any fan-out leg whose
container has exited (15 s cooldown). A leg dying mid-show no longer leaves
Streamplace "live" with no picture.

### Rotating the DJ key

    /opt/streamplace-relay/rotate-dj-key.sh

Generates a new key, rewrites `relay.env` + `mediamtx.yml`, recreates the
ingest and restarts the supervisor, then prints the new OBS credentials.
The rehearsal key (`rehearsal`) is unchanged.

### Diagnostics

    journalctl -u streamplace-relay -f          # transitions, watchdog, api errors
    docker logs -f relay-video                  # should stay up while OBS publishes
    docker logs -f relay-audio                  # "harbor: HTTP/1.0 200 OK"
    curl -s localhost:9997/v3/paths/list        # path ready / reader count

