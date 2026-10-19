# stream.place — Version Radio video relay

Two independent stacks running on one VPS (`<vps-ip>`), both pushing to
[Streamplace](https://stream.place) (AT Protocol livestreaming):

1. **Radio feeder** — 24/7. Relays the AzuraCast station as a video stream with
   the current track's artwork and burned-in captions.
2. **OBS relay** — on demand. Lets a remote DJ publish video from OBS, forwards
   the video untouched to Streamplace and the audio to AzuraCast.

```
                        ┌─────────────────────────────────────────┐
  AzuraCast ──audio──►  │ feeder (ffmpeg + artfeeder.py)          │──RTMPS──► Streamplace
  (Icecast :8000)       │ 720p/5fps, artwork, captions            │
                        └─────────────────────────────────────────┘

  OBS ──RTMPS :1935──►  MediaMTX ──► relay-video (-c:v copy) ────────RTMPS──► Streamplace
                                    └ relay-audio (MP3 256k) ──SOURCE──► AzuraCast harbor :8005
```

Only one publisher can hold the Streamplace stream key at a time, so a
supervisor swaps between the two stacks automatically.

## Repo layout → server paths

| Local | Server |
|---|---|
| `feeder/` | `/opt/streamplace-feeder/` |
| `relay/` | `/opt/streamplace-relay/` |
| `systemd/` | `/etc/systemd/system/` |
| `cover.png` | `/etc/streamplace/cover.png` |

## Components

### Radio feeder (`feeder/`)

- `entrypoint.sh` — waits for audio on the Icecast mount, then starts the push.
  Never publishes silence.
- `artfeeder.py` — polls `/api/nowplaying` over loopback, renders the current
  cover art to 1280x720, emits it as 2 fps MJPEG on stdout (now 5 fps), and
  writes caption text files that ffmpeg burns in.
- `docker-compose.yml` — one service, host networking, `restart: unless-stopped`.

Encoder: AAC 128k, h264 720p, CBR 400k, 5 fps, 1 s keyframes, no B-frames.

### OBS relay (`relay/`)

- `mediamtx.yml` — RTMPS `:1935` (strict TLS, public), plain RTMP
  `127.0.0.1:1936` (loopback only), RTSP loopback, API `127.0.0.1:9997`.
- `fanout-video.sh` — `-c:v copy -c:a copy` → Streamplace. No re-encode.
- `fanout-audio.sh` + `pusher.py` — MP3 256k → AzuraCast Liquidsoap harbor.
  ffmpeg's `icecast://` cannot address the harbour's `/` mount, so `pusher.py`
  speaks the Icecast `SOURCE /` handshake itself.
- `supervisor.py` — polls the MediaMTX API every 2 s; swaps feeder ↔ fan-out,
  and restarts a dead leg while a DJ is live.
- `rotate-dj-key.sh` — new DJ path/key, rewrites config, recreates ingest.

Both legs are separate processes on purpose: the harbor accepts one source, so a
busy mount must not take the video down with it.

## Secrets (never committed)

| File | Contents |
|---|---|
| `/etc/streamplace/feeder.env` | `STREAM_KEY` (Streamplace key, used by both stacks) |
| `/etc/streamplace/icecast.env` | AzuraCast streamer host/port/mount/user/password |
| `/etc/streamplace/relay.env` | `DJ_PATH` (ingest path) |
| `/etc/streamplace/tls/` | cert + key mirrored from AzuraCast's ACME storage |

All `600 root:root`. `.gitignore` blocks `*.env`, `*.pem`, `*.key`.

## Operations

```bash
# radio feeder
docker compose -f /opt/streamplace-feeder/docker-compose.yml ps
docker logs -f streamplace-feeder

# relay
systemctl status streamplace-relay
journalctl -u streamplace-relay -f
docker logs -f relay-video ; docker logs -f relay-audio
curl -s localhost:9997/v3/paths/list        # path ready / reader count

# rotate the Streamplace key (both stacks read feeder.env)
read -rsp "stream key: " K && printf 'STREAM_KEY=%s\n' "$K" > /etc/streamplace/feeder.env && unset K
chmod 600 /etc/streamplace/feeder.env
docker compose -f /opt/streamplace-feeder/docker-compose.yml up -d --force-recreate

# rotate the DJ ingest key
/opt/streamplace-relay/rotate-dj-key.sh
```

## DJ / OBS settings

A DJ-facing walkthrough lives in [docs/dj-obs-quickstart.md](docs/dj-obs-quickstart.md).


```
Server:             rtmps://multistream.versionradio.live:1935/live
Stream key:         dj-<hex>   (see relay.env; rotate with rotate-dj-key.sh)
Rehearsal key:      rehearsal  (publishes without taking the station over)

Encoder:            x264 (or NVENC), CBR
Bitrate:            6000 Kbps @1080p60 / 4000 Kbps @720p60
Keyframe interval:  1 s        (required)
B-frames:           0          (required)
Audio:              AAC 48 kHz stereo 160 Kbps
```

## Lessons that must not be undone

1. **Video leg reads loopback RTMP (`127.0.0.1:1936`), not RTSP.** RTSP carries
   H.264 as Annex-B; FLV/RTMP needs AVCC. `-c copy` across that boundary yields a
   stream that decodes to nothing — Streamplace shows audio with a black frame.
   If someone "simplifies" this back to RTSP, video silently breaks.
2. **Producer must be deadline-paced, not `sleep(0.5)`.** A fixed sleep made the
   video timeline run ~0.2 % slow; after hours the muxer dragged audio with it and
   playback fell a minute+ behind live. `cadence` log lines exist to catch this:
   `delta` must stay flat.
3. **One publisher per Streamplace key.** Feeder and relay can never run at once.
4. **One source per AzuraCast mount.** A direct DJ on `:8005` blocks the relay's
   audio leg (`403 Mountpoint already taken`); the pusher retries every 5 s while
   video keeps flowing.
5. **DNS must stay grey (DNS-only).** Cloudflare proxying breaks ACME renewal and
   RTMPS.
6. **Never use `-use_wallclock_as_timestamps` with `-copyts` here.** Mixing epoch
   timestamps with the live audio input produces non-monotonic DTS.

## Known limitations

- Radio listeners and Streamplace viewers are several seconds apart by design
  (harbor buffer 5 s + Icecast + player vs. Streamplace playback). Accepted, not
  compensated.
- Stream metadata (title/artist) is not pushed to Streamplace; the ATProto
  livestream record would need a separate authenticated updater.
- `liquidsoap.log` on the AzuraCast box records streamer passwords in plaintext.

## Related

- [Community-Radio-Website-CMS](https://github.com/version-aotearoa/Community-Radio-Website-CMS) —
  the station site that consumes the AzuraCast stream this repo feeds.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the invariants, testing recipe and
review expectations. Deployment walkthrough: [docs/setup.md](docs/setup.md).

## Licence

AGPL-3.0-only. See [LICENSE](LICENSE). Modifications offered to users over a
network must make the corresponding source available, as the licence requires.
