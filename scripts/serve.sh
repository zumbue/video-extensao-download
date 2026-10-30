#!/usr/bin/env bash
# Sobe o serviço local. Cria o ambiente só na primeira vez.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"
if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
  .venv/bin/python -m pip install -r host/requirements.txt
fi
exec .venv/bin/python -m host
