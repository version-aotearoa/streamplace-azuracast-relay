#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Switches between the radio feeder and the OBS fan-out, and keeps the
fan-out legs alive while a DJ is publishing."""
import json, subprocess, sys, time, urllib.parse, urllib.request

API = "http://127.0.0.1:9997/v3/paths/get/"
FEEDER_DIR = "/opt/streamplace-feeder"
IMAGE = "ghcr.io/azuracast/azuracast:latest"
LEGS = [("relay-video", "/fanout-video.sh"), ("relay-audio", "/fanout-audio.sh")]
POLL = 2.0
RESTART_COOLDOWN = 15.0
last_start = {}


def log(msg):
    print(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), msg, flush=True)


def run(cmd, **kw):
    """Every external call is bounded; a hung docker/HTTP call must not freeze the loop."""
    kw.setdefault("timeout", 20)
    kw.setdefault("capture_output", True)
    kw.setdefault("text", True)
    try:
        return subprocess.run(cmd, **kw)
    except subprocess.TimeoutExpired:
        log("TIMEOUT: " + " ".join(cmd[:3]))
        return None


def env(path, key):
    with open(path) as f:
        for line in f:
            if line.startswith(key + "="):
                return line.split("=", 1)[1].strip()
    raise SystemExit(f"{key} missing from {path}")


DJ_PATH = env("/etc/streamplace/relay.env", "DJ_PATH")


def running(name):
    r = run(["docker", "inspect", "-f", "{{.State.Running}}", name])
    return bool(r) and r.returncode == 0 and r.stdout.strip() == "true"


def path_ready():
    url = API + urllib.parse.quote(DJ_PATH, safe="")
    try:
        with urllib.request.urlopen(url, timeout=3) as r:
            return bool(json.load(r).get("ready"))
    except Exception as e:
        if str(e) not in getattr(path_ready, "_seen", ""):
            path_ready._seen = str(e)
            log(f"api error: {type(e).__name__} {e} url={url}")
        return False


def start_leg(name, script):
    last_start[name] = time.monotonic()
    run(["docker", "rm", "-f", name])
    run([
        "docker", "run", "-d", "--name", name, "--network", "host",
        "--entrypoint", "/bin/sh",
        "-v", "/etc/streamplace:/etc/streamplace:ro",
        "-v", f"/opt/streamplace-relay{script}:{script}:ro",
        "-v", "/opt/streamplace-relay/pusher.py:/opt/streamplace-relay/pusher.py:ro",
        IMAGE, script,
    ], check=False, capture_output=True)
    log(f"started {name}")


def stop_legs():
    for name, _ in LEGS:
        run(["docker", "rm", "-f", name])
    log("fan-out stopped")


def set_feeder(want):
    up = running("streamplace-feeder")
    if want and not up:
        run(["docker", "compose", "start"], cwd=FEEDER_DIR)
        log("radio feeder started")
    elif not want and up:
        run(["docker", "compose", "stop"], cwd=FEEDER_DIR)
        log("radio feeder stopped")


def main():
    log(f"supervisor watching {DJ_PATH}")
    last_beat = 0.0
    while True:
        ready = path_ready()
        legs = {name: running(name) for name, _ in LEGS}
        any_leg = any(legs.values())

        if ready and not any_leg:
            set_feeder(False)
            for name, script in LEGS:
                start_leg(name, script)
        elif not ready and any_leg:
            stop_legs()
            set_feeder(True)
        elif ready and any_leg:
            # watchdog: a leg that died while the DJ is still publishing
            now = time.monotonic()
            for name, script in LEGS:
                if not legs[name] and now - last_start.get(name, 0) > RESTART_COOLDOWN:
                    log(f"{name} is down while path is live - restarting")
                    start_leg(name, script)
        if time.monotonic() - last_beat > 30:
            last_beat = time.monotonic()
            log(f"alive ready={ready} legs={legs} feeder={running('streamplace-feeder')}")
        time.sleep(POLL)


if __name__ == "__main__":
    main()
