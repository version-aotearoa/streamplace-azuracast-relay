# Contributing

Thanks for your interest. This repo is small, ops-focused infrastructure code:
Python and shell running on a VPS, plus Docker Compose definitions. Bug reports,
operational war stories and PRs are all welcome.

## Licence and contribution terms

This project is licensed **AGPL-3.0-only**. By submitting a pull request, issue
patch, or any other contribution, you agree that your contribution is licensed
under the same terms and that you have the right to submit it.

There is currently **no separate CLA**. If that changes (for example, to allow
future relicensing), it will be announced in a PR against this file, and it will
apply only to contributions made after that point.

## Reporting bugs

Open an issue with:

- what you expected and what happened
- the relevant log lines (`journalctl -u streamplace-relay`, `docker logs <name>`)
- which stack is involved: `feeder/` (24/7 radio relay) or `relay/` (OBS ingest)
- the versions: MediaMTX, ffmpeg, Docker, AzuraCast

**Redact before posting:** stream keys, Icecast passwords, the DJ ingest path,
your public IP, and the AzuraCast internal API key. Logs from `liquidsoap.log`
carry plaintext streamer passwords — never paste those.

## Reporting security issues

Do not open a public issue for a vulnerability. Use GitHub's **private
vulnerability reporting** (Security → Advisories → Report a vulnerability) on
this repository, or contact a maintainer directly.

## Development

The code is deliberately dependency-light: Python 3 standard library only, and
shell that runs in `sh`/`bash` with coreutils. `shellcheck` and
`python -m py_compile` are the whole test suite.

### Prerequisites to run anything for real

- Docker with Compose
- An AzuraCast instance (or a local one) exposing the station mount and the
  Liquidsoap harbor
- A Streamplace account and stream key
- A certificate for the ingest hostname if you want RTMPS

### Local checks before you push

```bash
shellcheck relay/*.sh feeder/*.sh
python3 -m py_compile relay/*.py feeder/*.py
docker compose -f feeder/docker-compose.yml config --quiet
docker compose -f relay/docker-compose.yml config --quiet
```

### Testing a change

Anything touching the pipeline should be exercised with a synthetic source
instead of a live DJ:

```bash
# publish a test pattern through the ingest path (replace <path>)
ffmpeg -re -f lavfi -i "testsrc2=size=1280x720:rate=30" -f lavfi -i "sine=frequency=440" \
  -c:v libx264 -preset ultrafast -b:v 2000k -g 30 -bf 0 -pix_fmt yuv420p \
  -c:a aac -b:a 128k -t 30 -f flv "rtmps://<ingest-host>:1935/<path>"
```

Expected sequence:

1. MediaMTX logs `is publishing to path …`
2. the supervisor stops the radio feeder and starts both legs
3. the log shows `harbor: HTTP/1.0 200 OK` for the audio leg
4. AzuraCast reports `live: true`
5. when the publisher stops, fan-out stops and the feeder restarts

If you change encoder settings, include the before/after cadence lines:

```bash
docker logs <feeder> | grep cadence
```

`delta` must stay **flat**. A growing negative delta means the producer is
falling behind wall clock, which drags playback behind live (see the lessons in
the README).

## Invariants — please do not "simplify" these

1. **Video passthrough reads loopback RTMP (`127.0.0.1:1936`), never RTSP.**
   RTSP carries H.264 as Annex-B; FLV/RTMP needs AVCC. Copying across that
   boundary produces a stream that decodes to nothing.
2. **The frame producer is deadline-paced**, not `sleep(1/fps)`.
3. **One publisher per Streamplace key** — the feeder and the relay must never
   run simultaneously.
4. **One source per AzuraCast harbor mount** — a direct DJ blocks the relay's
   audio leg; the pusher retries and video keeps flowing.
5. **No `-use_wallclock_as_timestamps` with `-copyts`** in this pipeline; it
   produces non-monotonic DTS.
6. **Secrets stay in `/etc/streamplace/`**, `0600`, and never in the repo.

## Pull requests

- branch from `main`, one logical change per PR
- describe the operational impact: what changes on air, what could go wrong,
  how to roll back
- include the commands you ran to verify
- update `README.md` / `docs/` when behaviour or interfaces change
- keep commits scoped; a short imperative subject line is enough

Maintainers review for correctness and operational safety rather than style.
