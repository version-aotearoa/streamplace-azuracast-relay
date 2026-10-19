#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Restarts the radio feeder when its Icecast input goes stale.

ffmpeg survives an AzuraCast restart with a dead input and keeps encoding
silence, which looks live on Streamplace. Detect "station up but our mount has
no reader" and restart the feeder. Stands down while an OBS DJ owns the output.
"""
import json, ssl, subprocess, sys, time, urllib.parse, urllib.request

FEEDER = "streamplace-feeder"
API = "https://127.0.0.1/api/nowplaying"
ICECAST = "http://127.0.0.1:8000/status-json.xsl"
MTX = "http://127.0.0.1:9997/v3/paths/get/"
AZ_HOST = "stream.versionradio.live"
CHECK = 30
STRIKES = 2
COOLDOWN = 300

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE


def log(msg):
    print(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), msg, flush=True)


def env(path, key):
    with open(path) as f:
        for line in f:
            if line.startswith(key + "="):
                return line.split("=", 1)[1].strip()
    return ""


DJ_PATH = env("/etc/streamplace/relay.env", "DJ_PATH")


def get_json(url, headers=None, insecure=False, timeout=8):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout, context=ctx if insecure else None) as r:
        return json.loads(r.read())


def feeder_running():
    r = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", FEEDER],
                       capture_output=True, text=True, timeout=20)
    return r.returncode == 0 and r.stdout.strip() == "true"


def obs_active():
    if not DJ_PATH:
        return False
    try:
        return bool(get_json(MTX + urllib.parse.quote(DJ_PATH, safe="")).get("ready"))
    except Exception:
        return False


def mount_listeners():
    try:
        src = get_json(ICECAST)["icestats"]["source"]
        src = src if isinstance(src, list) else [src]
        return sum(int(s.get("listeners") or 0) for s in src)
    except Exception:
        return None


def restart_feeder():
    subprocess.run(["docker", "restart", FEEDER], capture_output=True, text=True, timeout=60)


def main():
    log(f"watchdog watching {FEEDER} (path {DJ_PATH or 'n/a'})")
    strikes = 0
    last_action = 0.0
    last_state = None
    while True:
        state = "idle"
        try:
            if obs_active():
                state = "obs"
                strikes = 0
            elif not feeder_running():
                state = "feeder-down"   # the relay supervisor owns start/stop
                strikes = 0
            else:
                listeners = mount_listeners()
                if listeners:
                    state = "ok"
                    strikes = 0
                else:
                    strikes = min(strikes + 1, STRIKES + 1)
                    state = f"stale({strikes}/{STRIKES})"
                    if strikes >= STRIKES and time.monotonic() - last_action > COOLDOWN:
                        log("mount has had no reader for %ds - restarting feeder" % (CHECK * STRIKES))
                        restart_feeder()
                        last_action = time.monotonic()
                        strikes = 0
                        state = "restarted"
        except Exception as e:
            state = f"error: {e}"
        if state != last_state:
            log(state)
            last_state = state
        time.sleep(CHECK)


if __name__ == "__main__":
    main()
