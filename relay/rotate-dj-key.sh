#!/bin/bash
# SPDX-License-Identifier: AGPL-3.0-only
# Generates a new DJ stream path/key, updates relay.env + mediamtx.yml, recreates ingest.
set -euo pipefail
KEY="dj-$(openssl rand -hex 12)"
sed -i "s|^DJ_PATH=.*|DJ_PATH=live/${KEY}|" /etc/streamplace/relay.env
python3 - "$KEY" <<'PY'
import re, sys
key = sys.argv[1]
p = "/opt/streamplace-relay/mediamtx.yml"
s = open(p).read()
s = re.sub(r"^  live/dj-[0-9a-f]+:", f"  live/{key}:", s, flags=re.M)
open(p, "w").write(s)
PY
cd /opt/streamplace-relay
docker compose up -d --force-recreate >/dev/null
systemctl restart streamplace-relay
echo
echo "New DJ credentials:"
echo "  Server:     rtmps://multistream.versionradio.live:1935/live"
echo "  Stream key: ${KEY}"
echo
echo "Old key is dead. Rehearsal key stays 'rehearsal'."
