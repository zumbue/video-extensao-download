#!/usr/bin/env bash
# Grava a unidade do systemd com a pasta desta máquina e liga no login.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
config="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
unit="video-extensao-download.service"
old="media-downloader-ext.service"
template="$root/systemd/user/video-extensao-download.service.in"

mkdir -p "$config"
if [[ -e "$config/$old" ]]; then
  systemctl --user disable --now "$old" || true
  rm -f "$config/$old"
fi
rm -f "$config/$unit"
python3 - "$template" "$config/$unit" "$root" <<'PY'
import pathlib
import sys

source, destination, root = sys.argv[1:]
text = pathlib.Path(source).read_text(encoding="utf-8").replace("@ROOT@", root)
pathlib.Path(destination).write_text(text, encoding="utf-8")
PY
systemctl --user daemon-reload
port="${MDE_PORT:-8734}"
python3 - "$port" <<'PY'
import socket
import sys
import time

port = int(sys.argv[1])
for _ in range(40):
    sock = socket.socket()
    sock.settimeout(0.2)
    try:
        busy = sock.connect_ex(("127.0.0.1", port)) == 0
    finally:
        sock.close()
    if not busy:
        break
    time.sleep(0.25)
PY
systemctl --user enable "$unit"
if ! systemctl --user restart "$unit"; then
  sleep 1
  systemctl --user restart "$unit"
fi
echo "Serviço ativo. Arquivos em ~/Downloads/Video Extensao Download"
echo "Abra http://127.0.0.1:8734/"
