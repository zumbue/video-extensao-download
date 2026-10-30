#!/usr/bin/env bash
# Prepara o serviço local e abre a página. Pensado para dois cliques em Instalar.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"

title="Video Extensão Download"
port="${MDE_PORT:-8734}"
url="http://127.0.0.1:${port}/"

say() {
  printf '%s\n' "$1" >&2
}

gui() {
  local kind="$1"
  local text="$2"
  if [[ -n "${VED_NO_DIALOG:-}" ]]; then
    say "$text"
    if [[ "$kind" == "yesno" ]]; then
      return 1
    fi
    return 0
  fi
  if command -v kdialog >/dev/null 2>&1; then
    case "$kind" in
      info) kdialog --title "$title" --msgbox "$text" ;;
      error) kdialog --title "$title" --error "$text" ;;
      yesno) kdialog --title "$title" --yesno "$text" ;;
      toast) kdialog --title "$title" --passivepopup "$text" 8 ;;
    esac
    return
  fi
  if command -v zenity >/dev/null 2>&1; then
    case "$kind" in
      info) zenity --info --title "$title" --text "$text" --width=440 ;;
      error) zenity --error --title "$title" --text "$text" --width=440 ;;
      yesno) zenity --question --title "$title" --text "$text" --width=440 ;;
      toast) zenity --notification --text "$text" ;;
    esac
    return
  fi
  say "$text"
  if [[ "$kind" == "yesno" ]]; then
    return 1
  fi
}

has_js() {
  command -v node >/dev/null 2>&1 || command -v deno >/dev/null 2>&1 || command -v bun >/dev/null 2>&1
}

python_ok() {
  command -v python3 >/dev/null 2>&1 && python3 -c 'import venv' >/dev/null 2>&1
}

install_packages() {
  local -a packages=("$@")
  if ! command -v pkexec >/dev/null 2>&1; then
    return 1
  fi
  if command -v pacman >/dev/null 2>&1; then
    pkexec pacman -S --needed --noconfirm "${packages[@]}"
    return
  fi
  if command -v apt-get >/dev/null 2>&1; then
    local -a deb=()
    local pkg
    for pkg in "${packages[@]}"; do
      case "$pkg" in
        python) deb+=(python3 python3-venv) ;;
        ffmpeg) deb+=(ffmpeg) ;;
        nodejs) deb+=(nodejs) ;;
        *) deb+=("$pkg") ;;
      esac
    done
    pkexec apt-get install -y "${deb[@]}"
    return
  fi
  return 1
}

missing_pkgs() {
  python_ok || printf '%s\n' python
  command -v ffmpeg >/dev/null 2>&1 || printf '%s\n' ffmpeg
  has_js || printf '%s\n' nodejs
}

join_lines() {
  local joined=""
  local item
  for item in "$@"; do
    if [[ -n "$joined" ]]; then
      joined+=", "
    fi
    joined+="$item"
  done
  printf '%s' "$joined"
}

gui toast "Preparando o Video Extensão Download. A página abre em seguida."

mapfile -t missing < <(missing_pkgs)
if ((${#missing[@]})); then
  list="$(join_lines "${missing[@]}")"
  if gui yesno "Faltam estes programas: ${list}. Posso pedir a senha do sistema para instalar?"; then
    if ! install_packages "${missing[@]}"; then
      gui error "Não consegui instalar ${list}. Instale Python, FFmpeg e Node e abra Instalar de novo."
      exit 1
    fi
  fi
fi

mapfile -t missing < <(missing_pkgs)
if ((${#missing[@]})); then
  list="$(join_lines "${missing[@]}")"
  gui error "Ainda falta: ${list}. Instale Python, FFmpeg e Node e abra Instalar de novo."
  exit 1
fi

if [[ ! -x .venv/bin/python ]] || ! .venv/bin/python -c 'import sys' >/dev/null 2>&1; then
  rm -rf .venv
  python3 -m venv .venv
fi

if ! .venv/bin/python -m pip install -r host/requirements.txt; then
  if ! .venv/bin/python -c 'import yt_dlp' >/dev/null 2>&1; then
    gui error "Não consegui instalar o yt-dlp. Confira a internet e abra Instalar de novo."
    exit 1
  fi
  say "yt-dlp já estava instalado. Segui sem atualizar."
fi

if ! ./scripts/install-user-service.sh; then
  gui error "Não consegui preparar o serviço."
  exit 1
fi

ready=0
for _ in $(seq 1 90); do
  if python3 - "$url" <<'PY'
import sys
import urllib.request

try:
    with urllib.request.urlopen(sys.argv[1] + "health", timeout=1) as response:
        raise SystemExit(0 if response.status == 200 else 1)
except Exception:
    raise SystemExit(1)
PY
  then
    ready=1
    break
  fi
  sleep 1
done

if [[ "$ready" != 1 ]]; then
  gui error "O serviço não respondeu em ${url}. Abra Instalar de novo."
  exit 1
fi

if [[ -z "${VED_NO_BROWSER:-}" ]]; then
  opened=0
  for browser in brave google-chrome chromium microsoft-edge firefox; do
    if command -v "$browser" >/dev/null 2>&1; then
      "$browser" "$url" >/dev/null 2>&1 &
      opened=1
      break
    fi
  done
  if [[ "$opened" != 1 ]] && command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$url" >/dev/null 2>&1 &
  fi
  disown || true
fi

gui info "A página está pronta. Cole o link e clique em Baixar.

No Linux o programa não fica aberto o tempo todo. A extensão inicia o serviço ao colar um link e ele se encerra sozinho depois do download.

Os arquivos vão para Downloads, na pasta Video Extensao Download.

A extensão da pasta extension é opcional. No navegador, ative o modo do desenvolvedor e carregue essa pasta."
