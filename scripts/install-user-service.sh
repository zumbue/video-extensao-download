#!/usr/bin/env bash
# Grava o soquete do systemd. O programa só sobe quando chega um pedido.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
config="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
unit="video-extensao-download.service"
socket_unit="video-extensao-download.socket"
old="media-downloader-ext.service"
template="$root/systemd/user/video-extensao-download.service.in"
socket_template="$root/systemd/user/video-extensao-download.socket"

mkdir -p "$config"
systemctl --user disable --now "$unit" || true
if [[ -e "$config/$old" || -e "$config/${old%.service}.socket" ]]; then
  systemctl --user disable --now "$old" || true
  rm -f "$config/$old"
fi
rm -f "$config/$unit" "$config/$socket_unit"
python3 - "$template" "$config/$unit" "$root" <<'PY'
import pathlib
import sys

source, destination, root = sys.argv[1:]
text = pathlib.Path(source).read_text(encoding="utf-8").replace("@ROOT@", root)
pathlib.Path(destination).write_text(text, encoding="utf-8")
PY
cp "$socket_template" "$config/$socket_unit"
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
systemctl --user enable --now "$socket_unit"
echo "A porta ${port} fica escutando sem deixar o programa aberto."
echo "A extensão inicia o serviço ao colar um link. Ele encerra depois do download."
