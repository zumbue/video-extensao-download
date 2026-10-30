#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
.venv/bin/python -m pip install -r host/requirements.txt

socket_unit="video-extensao-download.socket"
held=0
if systemctl --user is-active --quiet "$socket_unit" 2>/dev/null; then
  systemctl --user stop "$socket_unit"
  held=1
fi
set +e
.venv/bin/python -m host
status=$?
set -e
if [[ "$held" == 1 ]]; then
  systemctl --user start "$socket_unit" || true
fi
exit "$status"
