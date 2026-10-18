#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Pushes an MP3 stream to AzuraCast's Liquidsoap harbor.

ffmpeg's icecast:// protocol cannot address the harbour's mount ("/"), so this
speaks the Icecast SOURCE handshake directly and then pumps ffmpeg's stdout.
"""
import base64, os, socket, subprocess, sys, time

HOST = os.environ["ICECAST_HOST"]
PORT = int(os.environ["ICECAST_PORT"])
MOUNT = os.environ.get("ICECAST_MOUNT", "/")
USER = os.environ["ICECAST_USER"]
PASS = os.environ["ICECAST_PASSWORD"]
INPUT = os.environ["INPUT_URL"]
BITRATE = os.environ.get("ICECAST_BITRATE", "256k")


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def main():
    ff = subprocess.Popen(
        ["/usr/bin/ffmpeg", "-hide_banner", "-loglevel", "warning",
         "-i", INPUT,
         "-map", "0:a:0", "-c:a", "libmp3lame", "-b:a", BITRATE,
         "-ar", "44100", "-ac", "2", "-f", "mp3", "-"],
        stdout=subprocess.PIPE)

    auth = base64.b64encode(f"{USER}:{PASS}".encode()).decode()
    handshake = (
        f"SOURCE {MOUNT} HTTP/1.0\r\n"
        f"Host: {HOST}:{PORT}\r\n"
        f"Authorization: Basic {auth}\r\n"
        f"Content-Type: audio/mpeg\r\n"
        f"User-Agent: streamplace-relay/1\r\n"
        f"ice-bitrate: {BITRATE}\r\n"
        f"ice-name: {os.environ.get('ICE_NAME', 'OBS Relay')}\r\n"
        f"\r\n"
    )

    # The harbor accepts one source. If a direct DJ owns the mount, retry until
    # it frees up instead of dying for the rest of the show.
    sock = None
    while True:
        try:
            sock = socket.create_connection((HOST, PORT), timeout=15)
            sock.sendall(handshake.encode())
            resp = sock.recv(512).decode(errors="replace").splitlines()
            line = resp[0] if resp else "no response"
            log("harbor: " + line)
            if " 200 " in line:
                break
            sock.close()
            sock = None
        except OSError as e:
            log(f"harbor connect failed: {e}")
            sock = None
        if ff.poll() is not None:
            log("ffmpeg ended while waiting for the mount")
            return 1
        time.sleep(5)

    sock.settimeout(None)
    try:
        while True:
            chunk = ff.stdout.read(8192)
            if not chunk:
                break
            sock.sendall(chunk)
    except (BrokenPipeError, ConnectionResetError) as e:
        log(f"harbor closed: {e}")
        return 1
    finally:
        ff.terminate()
        try:
            sock.close()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
