#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-only
# OBS -> AzuraCast harbor. Separate process: its failure must not stop video.
set -eu
set -a; . /etc/streamplace/icecast.env; . /etc/streamplace/relay.env; set +a
export INPUT_URL="rtmp://127.0.0.1:1936/${DJ_PATH}"
export ICE_NAME="OBS Relay"
exec /usr/bin/python3 /opt/streamplace-relay/pusher.py
