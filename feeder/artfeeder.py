#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Streamplace feeder sidecar.

Emits the current track's artwork as a constant 2 fps MJPEG stream on stdout and
writes two text files that ffmpeg burns into the bottom band:

    /tmp/feeder/line1.txt   Artist - Title
    /tmp/feeder/line2.txt   state | elapsed / duration

Polling goes over loopback (HTTPS + Host header) so it costs no egress.
"""
import json, os, ssl, subprocess, sys, threading, time, urllib.request

HOST = os.environ.get("AZ_HOST", "stream.versionradio.live")
API = "https://127.0.0.1/api/nowplaying"
W, H = 1280, 720
FPS = 5.0
POLL = 15.0
TEXTDIR = "/tmp/feeder"
LINE1 = os.path.join(TEXTDIR, "line1.txt")
LINE2 = os.path.join(TEXTDIR, "line2.txt")
FALLBACK = "/cover.png"
LINE1_MAX = 46

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

frame = None
lock = threading.Lock()
state = {"line1": "VERSION RADIO", "line2": "connecting", "art": None,
         "elapsed": 0.0, "duration": 0.0, "live": False, "anchor": time.monotonic()}


def log(msg):
    print(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {msg}", file=sys.stderr, flush=True)


def clean(s, limit=None):
    s = " ".join(str(s or "").split())
    s = "".join(ch for ch in s if ch.isprintable() and ch != "\ufeff")
    if limit and len(s) > limit:
        s = s[: max(limit - 1, 0)].rstrip() + "\u2026"
    return s


def write_atomic(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    os.replace(tmp, path)


def clock(sec):
    sec = max(int(sec), 0)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def get(url, timeout=10):
    req = urllib.request.Request(url, headers={"Host": HOST, "User-Agent": "streamplace-feeder/1"})
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
        return r.read()


def render(img):
    p = subprocess.run(
        ["/usr/bin/ffmpeg", "-hide_banner", "-loglevel", "error", "-i", "-",
         "-vf", f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
                f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=0x0A0A0F",
         "-frames:v", "1", "-pix_fmt", "yuv420p", "-f", "mjpeg", "-q:v", "3", "-"],
        input=img, capture_output=True, timeout=30)
    if p.returncode != 0 or not p.stdout:
        raise RuntimeError("render failed: " + p.stderr.decode(errors="replace")[:200])
    return p.stdout


def refresh():
    d = json.loads(get(API))
    st = d[0]
    np = st.get("now_playing") or {}
    song = np.get("song") or {}
    artist = clean(song.get("artist"))
    title = clean(song.get("title"))
    state["line1"] = clean(f"{artist} \u2014 {title}" if artist and title else (title or artist or "VERSION RADIO"), LINE1_MAX)
    state["elapsed"] = float(np.get("elapsed") or 0)
    state["duration"] = float(np.get("duration") or 0)
    state["live"] = bool((st.get("live") or {}).get("is_live"))
    state["anchor"] = time.monotonic()
    return (song.get("art") or "").strip()


def poll():
    global frame
    last = None
    while True:
        try:
            art = refresh()
            if art and art != last:
                path = art.split(HOST, 1)[-1]
                new = render(get(f"https://127.0.0.1{path}"))
                with lock:
                    frame = new
                last = art
                log(f"artwork updated ({len(new)} bytes)")
        except Exception as e:
            log(f"poll failed: {e}")
        time.sleep(POLL)


def ticker():
    """Rewrite the caption lines once a second; progress is interpolated locally."""
    last = (None, None)
    while True:
        label = "LIVE" if state["live"] else ("RE-AIR" if state["duration"] > 5 else "AUTODJ")
        el = state["elapsed"] + (time.monotonic() - state["anchor"])
        if state["duration"] > 5:
            el = min(el, state["duration"])
            line2 = f"{label}  \u00b7  {clock(el)} / {clock(state['duration'])}"
        else:
            line2 = label
        cur = (state["line1"], line2)
        if cur != last:
            try:
                write_atomic(LINE1, state["line1"])
                write_atomic(LINE2, line2)
                last = cur
            except Exception as e:
                log(f"caption write failed: {e}")
        time.sleep(1)


def main():
    global frame
    os.makedirs(TEXTDIR, exist_ok=True)
    write_atomic(LINE1, state["line1"])
    write_atomic(LINE2, state["line2"])
    try:
        with open(FALLBACK, "rb") as f:
            frame = render(f.read())
    except Exception as e:
        log(f"fallback render failed: {e}")
        return 1
    threading.Thread(target=poll, daemon=True).start()
    threading.Thread(target=ticker, daemon=True).start()
    out = sys.stdout.buffer
    period = 1.0 / FPS
    nxt = time.monotonic()
    t_start = nxt
    frames = 0
    while True:
        with lock:
            f = frame
        try:
            out.write(f)
            out.flush()
        except BrokenPipeError:
            return 0
        # Deadline pacing: never accumulate a deficit. Sleeping a fixed 0.5s
        # after each write made the true period slightly long, which drifted the
        # video timeline behind wall clock (~0.2%/h) and dragged audio with it.
        frames += 1
        if frames % 120 == 0:
            wall = time.monotonic() - t_start
            log(f"cadence frames={frames} wall={wall:.1f}s ideal={frames * period:.1f}s delta={frames * period - wall:+.2f}s")
        nxt += period
        delay = nxt - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        else:
            nxt = time.monotonic()


if __name__ == "__main__":
    sys.exit(main())
