# Setup

From a blank Linux VPS with Docker to a working relay. Placeholders:

| Placeholder | Meaning |
|---|---|
| `<vps-ip>` | the server's public IPv4 |
| `<ingest-host>` | hostname for OBS ingest, e.g. `multistream.example.com` |
| `<station-host>` | the AzuraCast hostname, e.g. `stream.example.com` |
| `<stream-key>` | Streamplace stream key |
| `<dj-path>` | ingest path, e.g. `live/dj-<hex>` |

Assumptions: AzuraCast runs in Docker on the same host, and its station mount is
reachable on `127.0.0.1` (Icecast) plus the Liquidsoap harbor for live sources.

## 1. DNS and firewall

Both hostnames must be **DNS-only** (no Cloudflare proxy) — proxying breaks ACME
renewal and RTMPS.

```
<station-host>  A  <vps-ip>
<ingest-host>   A  <vps-ip>
```

Open inbound `22`, `80`, `443`, `1935` (RTMPS). Keep the AzuraCast station ports
closed unless you deliberately serve listeners directly.

## 2. TLS

If AzuraCast issues the certificate, add both names to its base URL/extra
domains so the ACME cert carries both SANs, then mirror it out:

```bash
install -d -m 700 /etc/streamplace/tls
docker cp azuracast:/var/azuracast/storage/acme/acme.crt /etc/streamplace/tls/fullchain.pem
docker cp azuracast:/var/azuracast/storage/acme/acme.key /etc/streamplace/tls/privkey.pem
chmod 600 /etc/streamplace/tls/privkey.pem
```

Install `systemd/streamplace-cert-sync.{service,timer}` to re-copy the cert daily
and restart the ingest when it changes.

## 3. Secrets

```bash
install -d -m 700 /etc/streamplace

# Streamplace push key (used by the radio feeder and the relay)
read -rsp "stream key: " K && printf 'STREAM_KEY=%s\n' "$K" > /etc/streamplace/feeder.env && unset K

# AzuraCast streamer credentials (see icecast.env.example)
install -m 600 /dev/null /etc/streamplace/icecast.env

# Ingest path
printf 'DJ_PATH=<dj-path>\n' > /etc/streamplace/relay.env

chmod 600 /etc/streamplace/*.env
```

`ICECAST_HOST` must be `127.0.0.1`, `ICECAST_PORT` the harbor port (default
`8005`), `ICECAST_MOUNT=/`.

## 4. Radio feeder

```bash
install -d /opt/streamplace-feeder
cp feeder/* /opt/streamplace-feeder/
cp cover.png /etc/streamplace/cover.png
cd /opt/streamplace-feeder && docker compose up -d
docker logs -f streamplace-feeder
```

Expect `station mount ready - starting push` and `artwork updated`. If the mount
never becomes ready, check `SRC` in `docker-compose.yml` (default
`http://127.0.0.1:8000/radio.mp3`).

## 5. Relay

```bash
install -d /opt/streamplace-relay
cp relay/* /opt/streamplace-relay/
chmod 755 /opt/streamplace-relay/*.sh
sed -i "s|live/dj-REDACTED|<dj-path>|" /opt/streamplace-relay/mediamtx.yml
cd /opt/streamplace-relay && docker compose up -d
```

MediaMTX should log listeners on `:1935` (RTMPS), `127.0.0.1:1936` (RTMP) and
`127.0.0.1:9997` (API).

```bash
cp systemd/* /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now streamplace-relay
```

## 6. Verify

```bash
# TLS on the ingest port
openssl s_client -connect <ingest-host>:1935 -servername <ingest-host> </dev/null

# synthetic publish (see CONTRIBUTING.md for the ffmpeg line)
# then, in another shell:
journalctl -u streamplace-relay -f     # feeder stopped -> fan-out started
docker logs -f relay-audio             # harbor: HTTP/1.0 200 OK
```

AzuraCast `/api/nowplaying` should report `live: true` while publishing, and the
feeder should resume within seconds of the publisher stopping.

## 7. OBS

```
Server:     rtmps://<ingest-host>:1935/live
Stream key: <dj-path without the "live/" prefix>
```

Encoder: h264, CBR, keyframe interval 1 s, B-frames 0, AAC 48 kHz stereo.

## Rollback

```bash
systemctl disable --now streamplace-relay
docker rm -f relay-video relay-audio
docker compose -f /opt/streamplace-feeder/docker-compose.yml up -d
```

AzuraCast is untouched by any of the above.
